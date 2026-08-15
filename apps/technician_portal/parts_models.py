"""
Parts-sourcing models — MygrantConfig (per-tenant supplier connection).

P1 in docs/strategy/FIELD_OPS_SESSIONS.md: "Connect your Mygrant account".
Credentials are always the shop's own — there is deliberately no platform-wide
credential path. A tenant without credentials sees no Mygrant UI anywhere
(gate shape mirrors Stripe Connect's is_enabled()).

Secrets (password, API key) are encrypted at rest via common.encryption and
are never shown back in the UI or admin.
"""
from django.db import models
from django.utils import timezone

from common.encryption import EncryptedTextField
from common.models import TenantConfig


class MygrantConfig(TenantConfig):
    """Per-tenant Mygrant Glass web-service credentials + connection state."""

    # Mygrant Customer ID, format C######-###
    customer_id = models.CharField(
        max_length=20,
        blank=True,
        help_text="Mygrant Customer ID (e.g. C000001-001).",
    )
    # Usually the shop's MygrantGlass.com login
    web_user_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="MygrantGlass.com web user ID.",
    )
    password = EncryptedTextField(
        blank=True,
        default='',
        help_text="MygrantGlass.com password. Encrypted at rest.",
    )
    # Generated at MygrantGlass.com → My Account → Edit User Settings after
    # Mygrant completes API User onboarding; sent as the AuthToken header.
    api_key = EncryptedTextField(
        blank=True,
        default='',
        help_text="Mygrant API key. Encrypted at rest.",
    )

    last_verified_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When Test connection last succeeded.",
    )
    last_verify_error = models.CharField(
        max_length=255, blank=True,
        help_text="Why the last Test connection failed (empty = last test passed).",
    )

    class Meta(TenantConfig.Meta):
        verbose_name = "Mygrant Configuration"

    def __str__(self):
        return f"MygrantConfig for {self.tenant}"

    @property
    def has_credentials(self):
        """Login credentials present (enough to attempt a connection test)."""
        return bool(self.customer_id and self.web_user_id and self.password)

    def is_enabled(self):
        """
        Full gate for quote/order features: credentials plus the API key
        (requests without an AuthToken header are rejected outright).
        """
        return self.has_credentials and bool(self.api_key)

    def mark_verified(self):
        self.last_verified_at = timezone.now()
        self.last_verify_error = ''
        self.save(update_fields=['last_verified_at', 'last_verify_error', 'updated_at'])

    def mark_verify_failed(self, error):
        self.last_verify_error = str(error)[:255]
        self.save(update_fields=['last_verify_error', 'updated_at'])
