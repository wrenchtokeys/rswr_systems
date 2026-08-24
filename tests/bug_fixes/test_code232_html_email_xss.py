"""
CODE-232: XSS in invoice HTML email body

The _build_html_email() method in InvoiceEmailService interpolated user-
controlled strings (customer name, unit number, damage type, tenant name,
business address, business phone) directly into the HTML body without escaping.

A customer named  `<img src=x onerror=alert(1)>` would embed live script into
every invoice email sent to that customer.

Fix: import `html` from stdlib and call `html.escape()` on every user-supplied
string before inserting it into the HTML template.
"""
import html as html_std
from unittest.mock import MagicMock, patch
from django.test import TestCase


class _FakeLineItem:
    def __init__(self, unit_number, damage_type, final_cost, description=''):
        self.unit_number = unit_number
        self.damage_type = damage_type
        self.final_cost = final_cost
        self.description = description


class _FakeInvoiceData:
    def __init__(self, customer_name, invoice_number='INV-001', payment_terms_display='Net 30',
                 line_items=None, total=100.0, total_discount=0, tax_amount=0, tax_rate=0):
        self.customer_name = customer_name
        self.invoice_number = invoice_number
        self.payment_terms_display = payment_terms_display
        self.line_items = line_items or []
        self.total = total
        self.total_discount = total_discount
        self.tax_amount = tax_amount
        self.tax_rate = tax_rate
        from django.utils import timezone
        self.invoice_date = timezone.now().date()
        self.id = 42
        self.pk = 42


class InvoiceEmailXssTest(TestCase):
    """Regression tests for CODE-232 — HTML injection in invoice emails."""

    def _make_service(self, tenant=None):
        from apps.billing.services.invoice_email_service import InvoiceEmailService
        service = InvoiceEmailService.__new__(InvoiceEmailService)
        service.tenant = tenant
        service.invoice_service = MagicMock()
        service.invoice_service.COMPANY_NAME = 'Test Shop'
        service.invoice_service.COMPANY_PHONE = ''
        service.invoice_service.COMPANY_EMAIL = ''
        service.s3_client = None
        service.s3_bucket = None
        return service

    def _get_html(self, service, invoice_data, payment_link=None):
        return service._build_html_email(invoice_data, payment_link=payment_link)

    # ------------------------------------------------------------------
    # Customer name injection
    # ------------------------------------------------------------------

    def test_customer_name_with_script_tag_is_escaped(self):
        service = self._make_service()
        data = _FakeInvoiceData(customer_name='<script>alert(1)</script>')
        result = self._get_html(service, data)
        self.assertNotIn('<script>', result)
        self.assertIn('&lt;script&gt;', result)

    def test_customer_name_with_img_onerror_is_escaped(self):
        service = self._make_service()
        data = _FakeInvoiceData(customer_name='<img src=x onerror=alert(1)>')
        result = self._get_html(service, data)
        self.assertNotIn('<img', result)
        self.assertIn('&lt;img', result)

    def test_customer_name_with_ampersand_is_escaped(self):
        service = self._make_service()
        data = _FakeInvoiceData(customer_name='Smith & Sons')
        result = self._get_html(service, data)
        self.assertIn('Smith &amp; Sons', result)

    def test_customer_name_normal_is_preserved(self):
        service = self._make_service()
        data = _FakeInvoiceData(customer_name='Acme Trucking')
        result = self._get_html(service, data)
        self.assertIn('Acme Trucking', result)

    # ------------------------------------------------------------------
    # Unit number injection
    # ------------------------------------------------------------------

    def test_unit_number_with_html_tag_is_escaped(self):
        service = self._make_service()
        evil_item = _FakeLineItem(
            unit_number='<script>steal()</script>',
            damage_type='Chip',
            final_cost=50.0,
        )
        data = _FakeInvoiceData(customer_name='Safe Co', line_items=[evil_item])
        result = self._get_html(service, data)
        self.assertNotIn('<script>steal()', result)
        self.assertIn('&lt;script&gt;', result)

    # ------------------------------------------------------------------
    # Damage type injection
    # ------------------------------------------------------------------

    def test_damage_type_with_html_tag_is_escaped(self):
        service = self._make_service()
        evil_item = _FakeLineItem(
            unit_number='T-100',
            damage_type='<b onmouseover=evil()>Chip</b>',
            final_cost=50.0,
        )
        data = _FakeInvoiceData(customer_name='Safe Co', line_items=[evil_item])
        result = self._get_html(service, data)
        self.assertNotIn('<b onmouseover', result)
        self.assertIn('&lt;b onmouseover', result)

    # ------------------------------------------------------------------
    # Tenant / company info injection
    # ------------------------------------------------------------------

    def test_tenant_name_with_html_is_escaped(self):
        tenant = MagicMock()
        tenant.name = '<img src=x onerror=alert(2)>'
        tenant.business_address = ''
        tenant.business_phone = ''
        service = self._make_service(tenant=tenant)
        data = _FakeInvoiceData(customer_name='Acme')
        result = self._get_html(service, data)
        self.assertNotIn('<img src=x', result)
        self.assertIn('&lt;img', result)

    def test_tenant_address_with_html_is_escaped(self):
        tenant = MagicMock()
        tenant.name = 'Good Shop'
        tenant.business_address = '<script>steal()</script>'
        tenant.business_phone = ''
        service = self._make_service(tenant=tenant)
        data = _FakeInvoiceData(customer_name='Acme')
        result = self._get_html(service, data)
        self.assertNotIn('<script>steal()', result)
        self.assertIn('&lt;script&gt;', result)

    def test_tenant_phone_with_html_is_escaped(self):
        tenant = MagicMock()
        tenant.name = 'Good Shop'
        tenant.business_address = ''
        tenant.business_phone = '"><script>alert(3)</script>'
        service = self._make_service(tenant=tenant)
        data = _FakeInvoiceData(customer_name='Acme')
        result = self._get_html(service, data)
        self.assertNotIn('<script>alert(3)', result)

    # ------------------------------------------------------------------
    # Invoice number injection (shown in header and details table)
    # ------------------------------------------------------------------

    def test_invoice_number_with_html_is_escaped(self):
        service = self._make_service()
        data = _FakeInvoiceData(
            customer_name='Acme',
            invoice_number='<script>evil()</script>',
        )
        result = self._get_html(service, data)
        self.assertNotIn('<script>evil()', result)
        self.assertIn('&lt;script&gt;', result)

    # ------------------------------------------------------------------
    # Confirm normal output still works correctly
    # ------------------------------------------------------------------

    def test_html_renders_total_correctly(self):
        service = self._make_service()
        item = _FakeLineItem('T-1', 'Chip', 75.00)
        data = _FakeInvoiceData(
            customer_name='Penske',
            line_items=[item],
            total=75.00,
        )
        result = self._get_html(service, data)
        self.assertIn('$75.00', result)

    def test_html_contains_payment_terms(self):
        service = self._make_service()
        data = _FakeInvoiceData(customer_name='Fleet Co', payment_terms_display='Net 45')
        result = self._get_html(service, data)
        self.assertIn('Net 45', result)

    def test_html_contains_view_invoice_button(self):
        # Sentence case since the invoice email moved onto the shared
        # chassis, which writes its actions the way the rest of the product
        # does ("View repair details", "Download receipt").
        service = self._make_service()
        data = _FakeInvoiceData(customer_name='Fleet Co')
        result = self._get_html(service, data)
        self.assertIn('View invoice online', result)
