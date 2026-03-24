"""
CODE-178: InvoiceEmailService._build_email_body() hardcoded https://rssystems.io
for the "View Invoice Online" link instead of using settings.BASE_URL.

Bug:
  _build_email_body() (plain-text portion of outbound invoice emails) always
  generated portal links with a hardcoded "https://rssystems.io" domain.
  _build_html_email() already used `getattr(settings, 'BASE_URL', 'https://rssystems.io')`
  correctly — _build_email_body was missing the same pattern.

  Impact: For any tenant deployed to a custom domain (e.g. app.my-glass-shop.com),
  the plain-text email link pointed to the wrong domain.  Customers would land on
  rssystems.io instead of the correct shop portal.

Fix:
  _build_email_body() now derives _base_url from settings.BASE_URL with the
  same fallback as _build_html_email():
    _base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
  Portal URLs are then f"{_base_url}/app/invoices/{invoice_id}/" and
  f"{_base_url}/app/invoices/" respectively.

Coverage:
  - With default BASE_URL (rssystems.io): links still correct
  - With custom BASE_URL: links use the custom domain
  - No invoice_id: fallback URL uses BASE_URL
"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from apps.billing.services.invoice_email_service import InvoiceEmailService


class _FakeLineItem:
    unit_number = '1001'
    damage_type = 'Bull\'s Eye'
    final_cost = Decimal('85.00')
    original_cost = Decimal('85.00')
    description = ''


class _FakeInvoiceData:
    invoice_number = 'INV-0099'
    invoice_date = date(2026, 3, 24)
    customer_name = 'Fleet Co.'
    total = Decimal('85.00')
    line_items = [_FakeLineItem()]
    total_discount = Decimal('0.00')
    tax_amount = Decimal('0.00')
    payment_terms_display = 'COD'
    id = 42


class _FakeInvoiceDataNoId:
    """Invoice with no pk/id — triggers the fallback URL."""
    invoice_number = 'INV-0100'
    invoice_date = date(2026, 3, 24)
    customer_name = 'Fleet Co.'
    total = Decimal('85.00')
    line_items = [_FakeLineItem()]
    total_discount = Decimal('0.00')
    tax_amount = Decimal('0.00')
    payment_terms_display = 'COD'
    # no 'id' attribute


class InvoiceEmailBaseUrlTests(TestCase):
    """Regression tests for CODE-178: plain-text invoice email portal URL."""

    def _make_service(self):
        svc = InvoiceEmailService.__new__(InvoiceEmailService)
        svc.tenant = MagicMock()
        svc.tenant.name = 'Test Glass Shop'
        invoice_service = MagicMock()
        invoice_service.COMPANY_NAME = 'Test Glass Shop'
        invoice_service.COMPANY_PHONE = '555-0100'
        invoice_service.COMPANY_EMAIL = 'shop@example.com'
        svc.invoice_service = invoice_service
        svc.s3_client = None
        svc.s3_bucket = None
        return svc

    def test_default_base_url_used_in_plain_text(self):
        """With no BASE_URL override, falls back to https://rssystems.io."""
        svc = self._make_service()
        invoice = _FakeInvoiceData()
        body = svc._build_email_body(invoice, include_photos=False)
        self.assertIn('https://rssystems.io/app/invoices/42/', body)
        # Should NOT have a trailing slash after the domain by itself
        self.assertNotIn('https://rssystems.io/', body.replace(
            'https://rssystems.io/app/invoices/42/', ''
        ))

    @override_settings(BASE_URL='https://app.custom-glass-shop.com')
    def test_custom_base_url_used_in_plain_text(self):
        """With a custom BASE_URL, plain-text link uses the custom domain."""
        svc = self._make_service()
        invoice = _FakeInvoiceData()
        body = svc._build_email_body(invoice, include_photos=False)
        self.assertIn('https://app.custom-glass-shop.com/app/invoices/42/', body)
        # Hard-coded fallback domain must NOT appear
        self.assertNotIn('rssystems.io', body)

    @override_settings(BASE_URL='https://app.custom-glass-shop.com')
    def test_custom_base_url_no_invoice_id(self):
        """Fallback URL (no invoice id) also respects BASE_URL."""
        svc = self._make_service()
        invoice = _FakeInvoiceDataNoId()
        body = svc._build_email_body(invoice, include_photos=False)
        self.assertIn('https://app.custom-glass-shop.com/app/invoices/', body)
        self.assertNotIn('rssystems.io', body)

    @override_settings(BASE_URL='https://app.custom-glass-shop.com/')
    def test_trailing_slash_on_base_url_stripped(self):
        """BASE_URL with a trailing slash doesn't produce double-slashes."""
        svc = self._make_service()
        invoice = _FakeInvoiceData()
        body = svc._build_email_body(invoice, include_photos=False)
        self.assertNotIn('//app/', body)
        self.assertIn('https://app.custom-glass-shop.com/app/invoices/42/', body)
