"""
Tests for free-form invoice line items (custom charges).

Covers:
- add_invoice_line_item    -> /api/billing/invoices/<id>/line-items/add/
- delete_invoice_line_item -> /api/billing/invoices/<id>/line-items/<lid>/delete/

These let an owner add one-off charges (trip fees, service charges) to a live
invoice without a Repair/Replacement behind them, and remove them again.
Job-linked lines can never be deleted through this endpoint.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings

from apps.billing.models import Invoice, InvoiceLineItem
from apps.technician_portal.models import Repair, Technician
from core.models import Customer
from tests.helpers import make_tenant


def make_repair(tenant, customer, user):
    tech = Technician.objects.create(tenant=tenant, user=user)
    return Repair.objects.create(
        tenant=tenant, customer=customer, technician=tech,
        unit_number='U-1', damage_type='chip',
        queue_status='COMPLETED', cost=Decimal('50.00'),
    )

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.dummy.EmailBackend',
}


def make_invoice(customer, tenant, status='SENT', tax_rate=Decimal('0.000')):
    """Create an invoice with one $50 line item."""
    inv = Invoice.objects.create(
        customer=customer,
        tenant=tenant,
        invoice_number=f'INV-CUST-{Invoice.objects.count() + 1:04d}',
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=status,
        subtotal=Decimal('50.00'),
        tax_rate=tax_rate,
        total=Decimal('50.00'),
    )
    li = InvoiceLineItem.objects.create(
        invoice=inv, description='Repair #1', quantity=1,
        unit_price=Decimal('50.00'), discount=Decimal('0.00'),
        amount=Decimal('50.00'),
    )
    return inv, li


@override_settings(**TEST_OVERRIDES)
class AddInvoiceLineItemTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('AddLineShop', 'addlineowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='AddLine Co', tenant=self.tenant, email='addline@test.com'
        )

    def _url(self, inv):
        return f'/api/billing/invoices/{inv.id}/line-items/add/'

    def _post(self, inv, payload):
        return self.client.post(
            self._url(inv), data=json.dumps(payload),
            content_type='application/json',
        )

    def test_add_free_form_line_updates_totals(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        resp = self._post(inv, {'description': 'Trip charge', 'amount': 25.00})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['line_item']['description'], 'Trip charge')
        self.assertEqual(data['line_item']['amount'], 25.0)
        self.assertEqual(data['invoice']['subtotal'], 75.0)
        self.assertEqual(data['invoice']['total'], 75.0)

        line = inv.line_items.get(id=data['line_item']['id'])
        self.assertIsNone(line.repair_id)
        self.assertIsNone(line.replacement_id)
        self.assertEqual(line.unit_price, Decimal('25.00'))
        self.assertEqual(line.quantity, 1)
        inv.refresh_from_db()
        self.assertEqual(inv.total, Decimal('75.00'))

    def test_add_taxable_line_recalculates_tax(self):
        inv, _ = make_invoice(self.customer, self.tenant, tax_rate=Decimal('10.000'))
        resp = self._post(inv, {'description': 'Service fee', 'amount': 50.00, 'taxable': True})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # subtotal = 100, tax 10% = 10, total = 110
        self.assertEqual(data['invoice']['subtotal'], 100.0)
        self.assertEqual(data['invoice']['tax_amount'], 10.0)
        self.assertEqual(data['invoice']['total'], 110.0)

    def test_add_non_taxable_line_skips_tax(self):
        inv, _ = make_invoice(self.customer, self.tenant, tax_rate=Decimal('10.000'))
        resp = self._post(inv, {'description': 'Trip charge', 'amount': 50.00, 'taxable': False})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Only the original $50 line is taxable: tax = 5, total = 105
        self.assertEqual(data['invoice']['subtotal'], 100.0)
        self.assertEqual(data['invoice']['tax_amount'], 5.0)
        self.assertEqual(data['invoice']['total'], 105.0)

    def test_tax_exempt_customer_defaults_non_taxable(self):
        self.customer.tax_exempt = True
        self.customer.save(update_fields=['tax_exempt'])
        inv, _ = make_invoice(self.customer, self.tenant, tax_rate=Decimal('10.000'))
        resp = self._post(inv, {'description': 'Fee', 'amount': 50.00})
        self.assertEqual(resp.status_code, 200)
        line = inv.line_items.get(id=resp.json()['line_item']['id'])
        self.assertFalse(line.taxable)

    def test_missing_description_rejected(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        resp = self._post(inv, {'description': '   ', 'amount': 25.00})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(inv.line_items.count(), 1)

    def test_bad_amount_rejected(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        for bad in (None, 'abc', 0, -5):
            resp = self._post(inv, {'description': 'Fee', 'amount': bad})
            self.assertEqual(resp.status_code, 400, f'amount={bad!r} should be rejected')
        self.assertEqual(inv.line_items.count(), 1)

    def test_paid_invoice_rejected(self):
        inv, _ = make_invoice(self.customer, self.tenant, status='PAID')
        resp = self._post(inv, {'description': 'Fee', 'amount': 25.00})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(inv.line_items.count(), 1)

    def test_cancelled_invoice_rejected(self):
        inv, _ = make_invoice(self.customer, self.tenant, status='CANCELLED')
        resp = self._post(inv, {'description': 'Fee', 'amount': 25.00})
        self.assertEqual(resp.status_code, 400)

    def test_other_tenant_invoice_404(self):
        _, tenant2 = make_tenant('OtherAddShop', 'otheradd')
        cust2 = Customer.objects.create(name='Other', tenant=tenant2)
        inv2, _ = make_invoice(cust2, tenant2)
        resp = self._post(inv2, {'description': 'Fee', 'amount': 25.00})
        self.assertEqual(resp.status_code, 404)

    def test_requires_authentication(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        anon = Client()
        resp = anon.post(
            self._url(inv), data=json.dumps({'description': 'Fee', 'amount': 25.00}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)


@override_settings(**TEST_OVERRIDES)
class DeleteInvoiceLineItemTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('DelLineShop', 'dellineowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='DelLine Co', tenant=self.tenant, email='delline@test.com'
        )

    def _url(self, inv, li):
        return f'/api/billing/invoices/{inv.id}/line-items/{li.id}/delete/'

    def test_delete_free_form_line_updates_totals(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        extra = InvoiceLineItem.objects.create(
            invoice=inv, description='Trip charge', quantity=1,
            unit_price=Decimal('25.00'), amount=Decimal('25.00'),
        )
        resp = self.client.post(self._url(inv, extra))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['invoice']['subtotal'], 50.0)
        self.assertEqual(data['invoice']['total'], 50.0)
        self.assertFalse(inv.line_items.filter(id=extra.id).exists())

    def test_job_linked_line_rejected(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        repair = make_repair(self.tenant, self.customer, self.user)
        job_line = InvoiceLineItem.objects.create(
            invoice=inv, repair=repair, description='Chip repair', quantity=1,
            unit_price=Decimal('50.00'), amount=Decimal('50.00'),
        )
        resp = self.client.post(self._url(inv, job_line))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(inv.line_items.filter(id=job_line.id).exists())

    def test_paid_invoice_rejected(self):
        inv, li = make_invoice(self.customer, self.tenant, status='PAID')
        resp = self.client.post(self._url(inv, li))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(inv.line_items.filter(id=li.id).exists())

    def test_other_tenant_invoice_404(self):
        _, tenant2 = make_tenant('OtherDelShop', 'otherdel')
        cust2 = Customer.objects.create(name='Other', tenant=tenant2)
        inv2, li2 = make_invoice(cust2, tenant2)
        resp = self.client.post(self._url(inv2, li2))
        self.assertEqual(resp.status_code, 404)

    def test_missing_line_404(self):
        inv, _ = make_invoice(self.customer, self.tenant)
        resp = self.client.post(f'/api/billing/invoices/{inv.id}/line-items/999999/delete/')
        self.assertEqual(resp.status_code, 404)


@override_settings(**TEST_OVERRIDES)
class OwnerInvoiceDetailAddLineUITests(TestCase):
    """The owner invoice detail page exposes the add/delete controls."""

    def setUp(self):
        self.user, self.tenant = make_tenant('AddUIShop', 'adduiowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='AddUI Co', tenant=self.tenant, email='addui@test.com'
        )

    def test_editable_invoice_shows_add_controls(self):
        inv, _ = make_invoice(self.customer, self.tenant, status='SENT')
        free_form = InvoiceLineItem.objects.create(
            invoice=inv, description='Trip charge', quantity=1,
            unit_price=Decimal('25.00'), amount=Decimal('25.00'),
        )
        resp = self.client.get(f'/owner/invoices/{inv.id}/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('openAddLineItemModal()', html)
        self.assertIn('line-item-add-modal', html)
        self.assertIn(f'deleteLineItem({free_form.id}', html)

    def test_job_linked_line_has_no_delete_button(self):
        inv, _ = make_invoice(self.customer, self.tenant, status='SENT')
        repair = make_repair(self.tenant, self.customer, self.user)
        job_line = InvoiceLineItem.objects.create(
            invoice=inv, repair=repair, description='Chip repair', quantity=1,
            unit_price=Decimal('50.00'), amount=Decimal('50.00'),
        )
        resp = self.client.get(f'/owner/invoices/{inv.id}/')
        html = resp.content.decode()
        self.assertNotIn(f'deleteLineItem({job_line.id}', html)

    def test_paid_invoice_hides_add_controls(self):
        inv, _ = make_invoice(self.customer, self.tenant, status='PAID')
        resp = self.client.get(f'/owner/invoices/{inv.id}/')
        html = resp.content.decode()
        self.assertNotIn('openAddLineItemModal()', html)
