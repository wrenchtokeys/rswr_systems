"""Cloudflare Turnstile verification.

The one implementation. It lived inside `apps/saas/views.py` while signup was
the only public form; `/help/contact/` is the second, and a second copy is how
the platform-fee calculation ended up with three (CODE-069).

Turnstile is the only third-party script the CSP allowlist names — see the
"No third-party asset hosts" and "Content-Security-Policy" sections of
CLAUDE.md before reaching for anything else here.
"""

import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def site_key():
    """The public key for the widget. Empty string means "render no widget"."""
    return os.environ.get('TURNSTILE_SITE_KEY', '')


def verify(request) -> bool:
    """Verify the Turnstile token on this POST, server-side.

    True when verification passes OR when Turnstile is not configured
    (no TURNSTILE_SECRET_KEY — so dev and CI work without keys).
    False only when keys ARE configured and verification fails.

    Fails OPEN on a network error: Cloudflare being unreachable must not stop
    a shop owner from telling us something is broken. The per-IP rate limit on
    each caller is the safety net that assumption leans on, so a view that
    calls this without one is a bug.
    """
    secret_key = os.environ.get('TURNSTILE_SECRET_KEY', '')
    if not secret_key:
        return True

    token = request.POST.get('cf-turnstile-response', '')
    if not token:
        return False

    try:
        data = urllib.parse.urlencode({
            'secret': secret_key,
            'response': token,
            'remoteip': request.META.get('REMOTE_ADDR', ''),
        }).encode()
        req = urllib.request.Request(VERIFY_URL, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
        return result.get('success', False)
    except Exception as e:
        logger.warning('Turnstile verification error: %s', e)
        return True
