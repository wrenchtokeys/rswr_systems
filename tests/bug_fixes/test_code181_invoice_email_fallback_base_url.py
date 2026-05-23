"""
CODE-181: InvoiceEmailService exception-fallback URLs hardcoded to https://rssystems.io

Bug:
  Two exception-handling fallback paths in InvoiceEmailService still used
  hardcoded https://rssystems.io instead of settings.BASE_URL:

  1. _build_html_email(): when generate_payment_token() raises an exception,
     the except-clause fell back to:
       portal_url = f"https://rssystems.io/app/invoices/{invoice_id}/"
     (the happy-path already used getattr(settings, 'BASE_URL', …) correctly,
     but the except branch was never updated)

  2. _build_html_email(): when invoice_id is None/falsy (else branch), it used:
       portal_url = "https://rssystems.io/app/invoices/"
     (hardcoded domain, not BASE_URL)

  These two paths were missed when CODE-178 fixed _build_email_body().
  Unlike CODE-178, these paths live in the HTML email builder rather than the
  plain-text builder.

Impact:
  For tenants on a custom domain (e.g. app.my-glass-shop.com), the HTML
  portion of invoice emails would still point to rssystems.io in:
    - The "View Invoice" link when the HMAC token generation fails
    - Any invoice email where the invoice_data has no 'id' attribute

Fix:
  Both fallback paths now derive the base URL from settings.BASE_URL with the
  same pattern used in the happy path:
    _fb_base = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
  then build the URL from _fb_base.

Coverage:
  - Exception-path fallback in _build_html_email: uses BASE_URL, not hardcoded domain
  - No-invoice-id fallback in _build_html_email: uses BASE_URL, not hardcoded domain
  - Both fallbacks respect trailing-slash stripping
  - Default BASE_URL (no override) still produces valid rssystems.io links
"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.billing.services.invoice_email_service import InvoiceEmailService


# ---------------------------------------------------------------------------
# Minimal test helpers
# ---------------------------------------------------------------------------

class _FakeLineItem:
    unit_number = '1001'
    damage_type = "Bull's Eye"
    final_cost = Decimal('85.00')
    original_cost = Decimal('85.00')
    description = ''


class _FakeInvoiceData:
    """Invoice with id — normal case (happy path follows token branch)."""
    invoice_number = 'INV-0181'
    invoice_date = date(2026, 3, 25)
    customer_name = 'Fleet Corp'
    total = Decimal('85.00')
    line_items = [_FakeLineItem()]
    total_discount = Decimal('0.00')
    tax_amount = Decimal('0.00')
    payment_terms_display = 'NET30'
    id = 181


class _FakeInvoiceDataNoId:
    """Invoice with no pk/id — exercises the else branch."""
    invoice_number = 'INV-0182'
    invoice_date = date(2026, 3, 25)
    customer_name = 'Fleet Corp'
    total = Decimal('85.00')
    line_items = [_FakeLineItem()]
    total_discount = Decimal('0.00')
    tax_amount = Decimal('0.00')
    payment_terms_display = 'NET30'
    # deliberately no 'id' attribute


def _make_service():
    """Build a minimal InvoiceEmailService without hitting __init__."""
    svc = InvoiceEmailService.__new__(InvoiceEmailService)
    svc.tenant = MagicMock()
    svc.tenant.name = 'Test Glass Shop'
    svc.tenant.business_address = ''
    svc.tenant.business_phone = ''
    invoice_service = MagicMock()
    invoice_service.COMPANY_NAME = 'Test Glass Shop'
    invoice_service.COMPANY_PHONE = '555-0181'
    invoice_service.COMPANY_EMAIL = 'shop@example.com'
    svc.invoice_service = invoice_service
    svc.s3_client = None
    svc.s3_bucket = None
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class InvoiceEmailHtmlFallbackBaseUrlTests(TestCase):
    """Regression tests for CODE-181: HTML email fallback URLs respect BASE_URL."""

    # -- Exception-path fallback (generate_payment_token raises) -------------

    @override_settings(BASE_URL='https://app.custom-glass.com')
    def test_exception_fallback_uses_base_url(self):
        """
        When generate_payment_token() raises, the except-branch URL must
        use settings.BASE_URL, not the hardcoded rssystems.io domain.
        """
        svc = _make_service()
        invoice = _FakeInvoiceData()

        # Force generate_payment_token to always raise so we exercise the
        # except branch, not the happy path.
        with patch(
            'rs_systems.views.generate_payment_token',
            side_effect=RuntimeError('token gen failed'),
        ):
            html = svc._build_html_email(invoice)

        self.assertIn('https://app.custom-glass.com/app/invoices/181/', html)
        self.assertNotIn('rssystems.io', html)

    def test_exception_fallback_default_base_url(self):
        """
        With no BASE_URL override the except-branch URL should fall back to
        https://rssystems.io (existing behaviour preserved).
        """
        svc = _make_service()
        invoice = _FakeInvoiceData()

        with patch(
            'rs_systems.views.generate_payment_token',
            side_effect=RuntimeError('token gen failed'),
        ):
            html = svc._build_html_email(invoice)

        self.assertIn('https://rssystems.io/app/invoices/181/', html)

    @override_settings(BASE_URL='https://app.custom-glass.com/')
    def test_exception_fallback_trailing_slash_stripped(self):
        """Trailing slash on BASE_URL must not produce double-slashes in the link."""
        svc = _make_service()
        invoice = _FakeInvoiceData()

        with patch(
            'rs_systems.views.generate_payment_token',
            side_effect=RuntimeError('token gen failed'),
        ):
            html = svc._build_html_email(invoice)

        self.assertNotIn('//app/', html)
        self.assertIn('https://app.custom-glass.com/app/invoices/181/', html)

    # -- No-invoice-id fallback (else branch) ---------------------------------

    @override_settings(BASE_URL='https://app.custom-glass.com')
    def test_no_invoice_id_fallback_uses_base_url(self):
        """
        When invoice_data has no 'id', the else-branch URL must use BASE_URL.
        """
        svc = _make_service()
        invoice = _FakeInvoiceDataNoId()

        # No payment_link supplied → _build_html_email tries to generate one.
        # invoice_id will be None → falls to the else branch.
        html = svc._build_html_email(invoice)

        self.assertIn('https://app.custom-glass.com/app/invoices/', html)
        self.assertNotIn('rssystems.io', html)

    def test_no_invoice_id_fallback_default_base_url(self):
        """Default rssystems.io fallback still works when BASE_URL is not set."""
        svc = _make_service()
        invoice = _FakeInvoiceDataNoId()

        html = svc._build_html_email(invoice)

        self.assertIn('https://rssystems.io/app/invoices/', html)

    @override_settings(BASE_URL='https://app.custom-glass.com/')
    def test_no_invoice_id_trailing_slash_stripped(self):
        """Trailing slash on BASE_URL must not produce double-slashes."""
        svc = _make_service()
        invoice = _FakeInvoiceDataNoId()

        html = svc._build_html_email(invoice)

        self.assertNotIn('//app/', html)
        self.assertIn('https://app.custom-glass.com/app/invoices/', html)
