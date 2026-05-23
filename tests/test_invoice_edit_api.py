"""
Tests for the invoice edit API endpoints (Bug 4 fix).

Covers:
- update_invoice            -> /api/billing/invoices/<id>/update/
- update_invoice_line_item  -> /api/billing/invoices/<id>/line-items/<lid>/update/

These let an owner correct invoice notes/terms and fix mispriced line items,
recalculating invoice totals (and tax) on save.

Author: Amelia (Clawdbot AI)
"""

import json
import unittest
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings

try:
    import reportlab  # noqa: F401
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

from apps.billing.models import Invoice, InvoiceLineItem
from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.dummy.EmailBackend',
}


def make_invoice(customer, tenant, status='SENT', tax_rate=Decimal('0.000')):
    """Create an invoice with two line items ($50 + $40 = $90 subtotal)."""
    inv = Invoice.objects.create(
        customer=customer,
        tenant=tenant,
        invoice_number=f'INV-EDIT-{Invoice.objects.count() + 1:04d}',
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=status,
        subtotal=Decimal('90.00'),
        tax_rate=tax_rate,
        total=Decimal('90.00'),
    )
    li1 = InvoiceLineItem.objects.create(
        invoice=inv, description='Repair #1', quantity=1,
        unit_price=Decimal('50.00'), discount=Decimal('0.00'),
        amount=Decimal('50.00'),
    )
    li2 = InvoiceLineItem.objects.create(
        invoice=inv, description='Repair #2', quantity=1,
        unit_price=Decimal('40.00'), discount=Decimal('0.00'),
        amount=Decimal('40.00'),
    )
    return inv, li1, li2


@override_settings(**TEST_OVERRIDES)
class UpdateInvoiceLineItemTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('EditShop', 'editowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Edit Co', tenant=self.tenant, email='edit@test.com'
        )

    def _url(self, inv, li):
        return f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/'

    def test_update_line_item_recalculates_totals(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 35.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        # Line item dropped to $35
        self.assertEqual(data['line_item']['amount'], 35.0)
        # Invoice subtotal = 35 + 40 = 75
        self.assertEqual(data['invoice']['subtotal'], 75.0)
        self.assertEqual(data['invoice']['total'], 75.0)

        li1.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(li1.amount, Decimal('35.00'))
        self.assertEqual(inv.subtotal, Decimal('75.00'))
        self.assertEqual(inv.total, Decimal('75.00'))

    def test_update_line_item_with_discount(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 50.00, 'discount': 10.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # amount = 50 - 10 = 40
        self.assertEqual(data['line_item']['amount'], 40.0)
        # subtotal counts gross unit prices (50 + 40 = 90), discount = 10
        self.assertEqual(data['invoice']['subtotal'], 90.0)
        self.assertEqual(data['invoice']['discount'], 10.0)
        # total = 90 - 10 = 80
        self.assertEqual(data['invoice']['total'], 80.0)

    def test_update_line_item_recalculates_tax(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant, tax_rate=Decimal('10.000'))
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 60.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # subtotal = 60 + 40 = 100, tax 10% = 10, total = 110
        self.assertEqual(data['invoice']['subtotal'], 100.0)
        self.assertEqual(data['invoice']['tax_amount'], 10.0)
        self.assertEqual(data['invoice']['total'], 110.0)

    def test_update_line_item_description(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'description': 'Corrected description'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        li1.refresh_from_db()
        self.assertEqual(li1.description, 'Corrected description')

    def test_explicit_amount_preserved(self):
        """An explicit amount (even when price/discount sent) is honored."""
        inv, li1, li2 = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 50.00, 'amount': 25.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        li1.refresh_from_db()
        self.assertEqual(li1.amount, Decimal('25.00'))

    def test_paid_invoice_rejected(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant, status='PAID')
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 35.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        li1.refresh_from_db()
        self.assertEqual(li1.amount, Decimal('50.00'))  # unchanged

    def test_cancelled_invoice_rejected(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant, status='CANCELLED')
        resp = self.client.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 35.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_other_tenant_invoice_404(self):
        _, tenant2 = make_tenant('OtherEditShop', 'otheredit')
        cust2 = Customer.objects.create(name='Other', tenant=tenant2)
        inv2, li1, li2 = make_invoice(cust2, tenant2)
        resp = self.client.post(
            self._url(inv2, li1),
            data=json.dumps({'unit_price': 35.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_bad_line_item_404(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/999999/update/',
            data=json.dumps({'unit_price': 35.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_requires_authentication(self):
        inv, li1, li2 = make_invoice(self.customer, self.tenant)
        anon = Client()
        resp = anon.post(
            self._url(inv, li1),
            data=json.dumps({'unit_price': 35.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)


@override_settings(**TEST_OVERRIDES)
class UpdateInvoiceTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('NotesShop', 'notesowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Notes Co', tenant=self.tenant, email='notes@test.com'
        )

    def _url(self, inv):
        return f'/api/billing/invoices/{inv.id}/update/'

    def test_update_notes_and_terms(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv),
            data=json.dumps({
                'notes': 'Customer note',
                'internal_notes': 'Internal note',
                'payment_terms': 'NET30',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.notes, 'Customer note')
        self.assertEqual(inv.internal_notes, 'Internal note')
        self.assertEqual(inv.payment_terms, 'NET30')

    def test_update_due_date(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv),
            data=json.dumps({'due_date': '2026-12-31'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.due_date, date(2026, 12, 31))

    def test_invalid_due_date_rejected(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv),
            data=json.dumps({'due_date': 'not-a-date'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_fields_rejected(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            self._url(inv),
            data=json.dumps({'unknown_field': 'x'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_paid_invoice_rejected(self):
        inv, _, _ = make_invoice(self.customer, self.tenant, status='PAID')
        resp = self.client.post(
            self._url(inv),
            data=json.dumps({'notes': 'x'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_requires_authentication(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        anon = Client()
        resp = anon.post(
            self._url(inv),
            data=json.dumps({'notes': 'x'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)


@override_settings(**TEST_OVERRIDES)
class InvoiceDescriptionFieldTests(TestCase):
    """Bug 7: invoice-level description field — model, API, and PDF."""

    def setUp(self):
        self.user, self.tenant = make_tenant('DescShop', 'descowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Desc Co', tenant=self.tenant, email='desc@test.com'
        )

    def test_description_defaults_blank(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        self.assertEqual(inv.description, '')

    def test_update_endpoint_sets_description(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        resp = self.client.post(
            f'/api/billing/invoices/{inv.id}/update/',
            data=json.dumps({'description': 'Quarterly fleet windshield service'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['description'], 'Quarterly fleet windshield service')
        inv.refresh_from_db()
        self.assertEqual(inv.description, 'Quarterly fleet windshield service')

    def test_get_invoice_returns_description(self):
        inv, _, _ = make_invoice(self.customer, self.tenant)
        inv.description = 'Visible to customer'
        inv.save(update_fields=['description'])
        resp = self.client.get(f'/api/billing/invoices/{inv.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['invoice']['description'], 'Visible to customer')

    @unittest.skipUnless(HAS_REPORTLAB, "reportlab not installed in this environment")
    def test_pdf_renders_description(self):
        """The PDF service should embed an invoice description when provided."""
        from apps.billing.services.invoice_service import InvoiceData, InvoiceService
        from datetime import datetime as dt
        data = InvoiceData(
            invoice_number='INV-DESC-1',
            invoice_date=dt(2026, 5, 22),
            customer_name='Desc Co',
            customer_email='desc@test.com',
            customer_address=None,
            line_items=[],
            subtotal=Decimal('0.00'),
            total_discount=Decimal('0.00'),
            total=Decimal('0.00'),
            description='Special handling note on PDF',
        )
        pdf_bytes = InvoiceService().generate_pdf(data, include_photos=False)
        # Valid PDF produced (description rendering path executes without error)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertGreater(len(pdf_bytes), 500)


@override_settings(**TEST_OVERRIDES)
class OwnerInvoiceDetailEditUITests(TestCase):
    """Bug 4: the owner invoice detail page exposes the edit controls."""

    def setUp(self):
        self.user, self.tenant = make_tenant('UIShop', 'uiowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='UI Co', tenant=self.tenant, email='ui@test.com'
        )

    def test_editable_invoice_shows_edit_controls(self):
        inv, li1, _ = make_invoice(self.customer, self.tenant, status='SENT')
        resp = self.client.get(f'/owner/invoices/{inv.id}/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Header edit button, per-line-item edit, and both modals present
        self.assertIn('Edit Details', html)
        self.assertIn('openInvoiceEditModal()', html)
        self.assertIn('line-item-modal', html)
        self.assertIn('invoice-edit-modal', html)
        self.assertIn(f'openLineItemEditModal({li1.id}', html)
        # Endpoints referenced by the AJAX wiring
        self.assertIn(f'/api/billing/invoices/${{INVOICE_ID}}/line-items/', html)

    def test_paid_invoice_hides_edit_controls(self):
        inv, _, _ = make_invoice(self.customer, self.tenant, status='PAID')
        resp = self.client.get(f'/owner/invoices/{inv.id}/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn('Edit Details', html)
        self.assertNotIn('openLineItemEditModal(', html)

    def test_description_shown_when_set(self):
        inv, _, _ = make_invoice(self.customer, self.tenant, status='SENT')
        inv.description = 'A customer-facing summary'
        inv.save(update_fields=['description'])
        resp = self.client.get(f'/owner/invoices/{inv.id}/')
        self.assertContains(resp, 'A customer-facing summary')
