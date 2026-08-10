"""Canonical customer-facing pay link for invoices.

The tokened public /pay/ page routes the charge through the shop's own
Stripe Connect account at click time, so it is the only link that should
ever be put in front of a customer. Platform-account Payment Links and
Checkout Sessions (StripeService) must never be used for shop invoices —
that money settles in the platform's Stripe balance with no automated
route back to the shop.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def public_pay_url(invoice):
    """Return the public HMAC-tokened pay URL for an invoice.

    Returns None when the shop cannot accept online payments (no active
    Stripe Connect account) — callers should omit the pay link entirely
    rather than fall back to a platform-account charge.
    """
    tenant = getattr(invoice, 'tenant', None)
    if not tenant or not tenant.can_accept_payments:
        return None
    try:
        from rs_systems.views import generate_payment_token
        base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
        token = generate_payment_token(invoice.id)
        return f"{base_url}/pay/{invoice.id}/{token}/"
    except Exception as e:
        logger.warning(f"Could not build pay URL for invoice #{invoice.id}: {e}")
        return None


def public_invoice_pdf_url(invoice):
    """Return the tokened public PDF link for an invoice (no login).

    Once the invoice is paid the PDF carries the PAID stamp, so this same
    link doubles as the customer's downloadable receipt. Unlike
    public_pay_url this is NOT gated on can_accept_payments — the document
    is viewable regardless of how the shop takes money.
    """
    try:
        from rs_systems.views import generate_payment_token
        base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
        token = generate_payment_token(invoice.id)
        return f"{base_url}/invoice/{invoice.id}/{token}/pdf/"
    except Exception as e:
        logger.warning(f"Could not build PDF URL for invoice #{invoice.id}: {e}")
        return None
