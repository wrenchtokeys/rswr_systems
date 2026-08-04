"""
Tests for the customer-level Receive Payment workflow.

Covers:
- owner_receive_payment -> /owner/payments/receive/
  (one payment applied across several open invoices, oldest first)
- Combined receipt email (one per customer, not one per invoice)
- Bulk mark-paid capturing method/date/reference and sending receipts
- The 'unpaid' invoice list filter including OVERDUE
- owner_record_payment honoring a same-site `next` redirect
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase, Client, override_settings

from apps.billing.models import Invoice, InvoiceLineItem, Payment
from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}

RECEIVE_URL = '/owner/payments/receive/'


def make_invoice(customer, tenant, total, status='SENT', due_days=30):
    n = Invoice.objects.count() + 1
    inv = Invoice.objects.create(
        customer=customer,
        tenant=tenant,
        invoice_number=f'INV-RP-{n:04d}',
        invoice_date=date.today() - timedelta(days=n),
        due_date=date.today() + timedelta(days=due_days),
        status=status,
        subtotal=Decimal(total),
        total=Decimal(total),
    )
    InvoiceLineItem.objects.create(
        invoice=inv, description=f'Job {n}', quantity=1,
        unit_price=Decimal(total), amount=Decimal(total),
    )
    return inv


@override_settings(**TEST_OVERRIDES)
class ReceivePaymentTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('ReceiveShop', 'receiveowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Penske Test', tenant=self.tenant, email='ap@penske-test.com'
        )
        # Oldest due first: inv1 due in 5 days, inv2 in 10, inv3 in 20
        self.inv1 = make_invoice(self.customer, self.tenant, '50.00', due_days=5)
        self.inv2 = make_invoice(self.customer, self.tenant, '80.00', due_days=10)
        self.inv3 = make_invoice(self.customer, self.tenant, '40.00', due_days=20)

    def _post_payment(self, amount, allocs, **extra):
        data = {
            'customer_id': self.customer.id,
            'amount': amount,
            'payment_method': 'CHECK',
            'payment_date': date.today().isoformat(),
            'reference_number': 'CHK-1001',
        }
        for inv, val in allocs.items():
            data[f'alloc_{inv.id}'] = val
        data.update(extra)
        return self.client.post(RECEIVE_URL, data)

    def test_page_lists_open_invoices_for_customer(self):
        resp = self.client.get(f'{RECEIVE_URL}?customer={self.customer.id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for inv in (self.inv1, self.inv2, self.inv3):
            self.assertIn(inv.invoice_number, html)
        self.assertIn('Penske Test', html)

    def test_paid_invoice_not_listed(self):
        paid = make_invoice(self.customer, self.tenant, '99.00', status='PAID')
        resp = self.client.get(f'{RECEIVE_URL}?customer={self.customer.id}')
        self.assertNotContains(resp, paid.invoice_number)

    def test_split_payment_across_invoices(self):
        resp = self._post_payment('90.00', {self.inv1: '50.00', self.inv2: '40.00'})
        self.assertEqual(resp.status_code, 302)

        self.inv1.refresh_from_db()
        self.inv2.refresh_from_db()
        self.inv3.refresh_from_db()
        self.assertEqual(self.inv1.status, 'PAID')
        self.assertEqual(self.inv1.amount_paid, Decimal('50.00'))
        self.assertEqual(self.inv2.status, 'PARTIAL')
        self.assertEqual(self.inv2.amount_paid, Decimal('40.00'))
        self.assertEqual(self.inv3.amount_paid, Decimal('0.00'))

        payments = Payment.objects.filter(invoice__customer=self.customer)
        self.assertEqual(payments.count(), 2)
        for p in payments:
            self.assertEqual(p.payment_method, 'CHECK')
            self.assertEqual(p.reference_number, 'CHK-1001')
            self.assertEqual(p.recorded_by, self.user)

    def test_combined_receipt_one_email_per_party(self):
        self._post_payment('90.00', {self.inv1: '50.00', self.inv2: '40.00'})
        # One combined customer receipt + one owner notification — not one per invoice
        self.assertEqual(len(mail.outbox), 2)
        recipients = {addr for m in mail.outbox for addr in m.to}
        self.assertIn('ap@penske-test.com', recipients)
        customer_mail = next(m for m in mail.outbox if 'ap@penske-test.com' in m.to)
        self.assertIn(self.inv1.invoice_number, customer_mail.body)
        self.assertIn(self.inv2.invoice_number, customer_mail.body)

    def test_amount_mismatch_rejected(self):
        resp = self._post_payment('100.00', {self.inv1: '50.00', self.inv2: '40.00'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.count(), 0)

    def test_overallocation_rejected(self):
        resp = self._post_payment('60.00', {self.inv1: '60.00'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.count(), 0)
        self.inv1.refresh_from_db()
        self.assertEqual(self.inv1.amount_paid, Decimal('0.00'))

    def test_no_allocation_rejected(self):
        resp = self._post_payment('50.00', {})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.count(), 0)

    def test_other_tenant_customer_rejected(self):
        _, tenant2 = make_tenant('OtherReceive', 'otherreceive')
        other_customer = Customer.objects.create(name='Not Mine', tenant=tenant2)
        resp = self.client.post(RECEIVE_URL, {
            'customer_id': other_customer.id,
            'amount': '10.00',
            'payment_method': 'CHECK',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.count(), 0)

    def test_invalid_method_rejected(self):
        resp = self._post_payment('50.00', {self.inv1: '50.00'}, payment_method='BITCOIN')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.count(), 0)


@override_settings(**TEST_OVERRIDES)
class UnpaidFilterTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('FilterShop', 'filterowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Filter Co', tenant=self.tenant, email='filter@test.com'
        )

    def test_unpaid_filter_includes_overdue(self):
        sent = make_invoice(self.customer, self.tenant, '10.00', status='SENT')
        overdue = make_invoice(self.customer, self.tenant, '20.00', status='OVERDUE')
        # Give the overdue invoice a past due date so the auto-promote doesn't
        # interfere either way
        overdue.due_date = date.today() - timedelta(days=10)
        overdue.save(update_fields=['due_date'])
        paid = make_invoice(self.customer, self.tenant, '30.00', status='PAID')

        resp = self.client.get('/owner/invoices/?status=unpaid')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, sent.invoice_number)
        self.assertContains(resp, overdue.invoice_number)
        self.assertNotContains(resp, paid.invoice_number)


@override_settings(**TEST_OVERRIDES)
class BulkMarkPaidTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('BulkShop', 'bulkowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Bulk Co', tenant=self.tenant, email='bulk@test.com'
        )
        self.inv1 = make_invoice(self.customer, self.tenant, '50.00')
        self.inv2 = make_invoice(self.customer, self.tenant, '75.00')

    def _post(self, payload):
        return self.client.post(
            '/owner/invoices/bulk/', data=json.dumps(payload),
            content_type='application/json',
        )

    def test_bulk_mark_paid_records_method_and_reference(self):
        resp = self._post({
            'action': 'mark_paid',
            'invoice_ids': [self.inv1.id, self.inv2.id],
            'payment_method': 'CHECK',
            'payment_date': '2026-08-01',
            'reference_number': 'CHK-555',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

        self.inv1.refresh_from_db()
        self.inv2.refresh_from_db()
        self.assertEqual(self.inv1.status, 'PAID')
        self.assertEqual(self.inv2.status, 'PAID')

        payments = Payment.objects.filter(invoice__customer=self.customer)
        self.assertEqual(payments.count(), 2)
        for p in payments:
            self.assertEqual(p.payment_method, 'CHECK')
            self.assertEqual(p.reference_number, 'CHK-555')
            self.assertEqual(p.payment_date, date(2026, 8, 1))

    def test_bulk_mark_paid_sends_combined_receipt(self):
        self._post({
            'action': 'mark_paid',
            'invoice_ids': [self.inv1.id, self.inv2.id],
        })
        # One combined customer receipt + one owner notification
        self.assertEqual(len(mail.outbox), 2)
        recipients = {addr for m in mail.outbox for addr in m.to}
        self.assertIn('bulk@test.com', recipients)

    def test_bulk_mark_paid_defaults_still_work(self):
        resp = self._post({'action': 'mark_paid', 'invoice_ids': [self.inv1.id]})
        self.assertEqual(resp.status_code, 200)
        payment = Payment.objects.get(invoice=self.inv1)
        self.assertEqual(payment.payment_method, 'OTHER')
        self.assertEqual(payment.payment_date, date.today())

    def test_bulk_mark_paid_invalid_method_rejected(self):
        resp = self._post({
            'action': 'mark_paid',
            'invoice_ids': [self.inv1.id],
            'payment_method': 'BITCOIN',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)


@override_settings(**TEST_OVERRIDES)
class RecordPaymentNextRedirectTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('NextShop', 'nextowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Next Co', tenant=self.tenant, email='next@test.com'
        )
        self.inv = make_invoice(self.customer, self.tenant, '50.00')

    def _post(self, **extra):
        data = {
            'amount': '50.00',
            'payment_method': 'CASH',
        }
        data.update(extra)
        return self.client.post(
            f'/owner/invoices/{self.inv.id}/record-payment/', data
        )

    def test_next_redirect_honored(self):
        resp = self._post(next='/owner/invoices/?status=unpaid')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/owner/invoices/?status=unpaid')
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, 'PAID')

    def test_external_next_ignored(self):
        resp = self._post(next='//evil.example.com/phish')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f'/owner/invoices/{self.inv.id}/')

    def test_default_redirect_unchanged(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f'/owner/invoices/{self.inv.id}/')
