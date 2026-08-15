"""
common/encryption.py — encryption at rest for third-party credentials.

This is the codebase's ONE mechanism for storing a secret a tenant hands us
(supplier passwords, API keys). Decision record (P1 step 3, 2026-08-14,
docs/strategy/FIELD_OPS_SESSIONS.md):

- Fernet (AES-128-CBC + HMAC, from the `cryptography` package). Symmetric is
  right here: the app must read the secret back to call the supplier, so an
  HSM/KMS adds an AWS dependency and a per-read network call without removing
  the "app can decrypt" capability an attacker with app access already gets.
- The key comes from the FIELD_ENCRYPTION_KEY env var and is deliberately NOT
  SECRET_KEY: rotating Django's signing key must never brick stored
  credentials, and a leaked settings dump shouldn't hand over both.
- settings/development.py derives a stable dev key from SECRET_KEY when the
  env var is unset, so local dev and the test suite need no setup. Production
  has no fallback: encrypting raises so we can never write secrets that a
  later, correctly-configured process cannot read.

Generate a production key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
then `eb setenv FIELD_ENCRYPTION_KEY=<key>`.

Key rotation: Fernet tokens embed a version byte; if rotation is ever needed,
switch `_fernet()` to MultiFernet([new, old]) and re-save rows.
"""
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """Stored ciphertext could not be decrypted (wrong key or corrupt data)."""


def is_configured():
    """True if secrets can be encrypted in this environment."""
    return bool(getattr(settings, 'FIELD_ENCRYPTION_KEY', ''))


def _fernet():
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is required to store credentials. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" and set it with eb setenv."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt_str(value):
    """Encrypt a string. Empty stays empty (so blank fields stay queryable)."""
    if not value:
        return ''
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(token):
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "Could not decrypt stored credential — FIELD_ENCRYPTION_KEY changed "
            "or the data is corrupt. Re-enter the credential to fix."
        ) from exc


class EncryptedTextField(models.TextField):
    """
    TextField that stores Fernet ciphertext and gives back plaintext.

    Values are encrypted on save and decrypted on load; the database and
    dumps only ever see the token. Not queryable by value (by design).
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == '':
            return value
        return encrypt_str(value)

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        return decrypt_str(value)
