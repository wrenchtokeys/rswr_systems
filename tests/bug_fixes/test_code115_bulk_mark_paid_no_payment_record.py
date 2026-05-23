"""
CODE-115 regression tests: owner_invoice_bulk_action 'mark_paid' must
create Payment records and set paid_at.

Bug: The bulk mark_paid action directly wrote amount_paid/status='PAID' with
no Payment row created and no paid_at stamp set. Payment history was empty
for bulk-paid invoices and paid_at was always NULL.

Fix: Create a Payment record (method='OTHER') for each invoice's remaining
balance. Payment.save() → _update_invoice_totals() → update_status() sets
paid_at and status='PAID' properly.
"""
import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, Payment, BillingConfig
from core.models import Customer


class BulkMarkPaidCreatesPaymentRecordTests(TestCase):
    """Bulk mark_paid must create Payment rows and set paid_at."""

    def setUp(self):
        # Owner user
        self.owner = User.objects.create_user(
            username='owner_115', password='testpass', email='owner115@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 115', slug='shop-115', owner=self.owner, is_active=True
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )
        BillingConfig.get_for_tenant(self.tenant)

        self.customer = Customer.objects.create(
            name='Test Customer 115',
            tenant=self.tenant,
            email='cust115@test.com',
        )

        self.client = Client()
        self.client.force_login(self.owner)

        # Set tenant in session
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _make_invoice(self, status='SENT', total='100.00', amount_paid='0.00'):
        return Invoice.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            invoice_number=f'INV-115-{Invoice.objects.count() + 1}',
            invoice_date=timezone.now().date(),
            total=Decimal(total),
            amount_paid=Decimal(amount_paid),
            status=status,
        )

    def _bulk_action(self, invoice_ids, action='mark_paid'):
        url = reverse('owner_invoice_bulk_action')
        return self.client.post(
            url,
            data=json.dumps({'action': action, 'invoice_ids': invoice_ids}),
            content_type='application/json',
        )

    def test_mark_paid_creates_payment_record(self):
        """Bulk mark_paid must create a Payment row for each invoice."""
        inv = self._make_invoice(status='SENT', total='150.00')
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 0)

        resp = self._bulk_action([inv.id])
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        # Payment record created
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 1)
        payment = Payment.objects.get(invoice=inv)
        self.assertEqual(payment.amount, Decimal('150.00'))
        self.assertEqual(payment.payment_method, 'OTHER')
        self.assertEqual(payment.recorded_by, self.owner)

    def test_mark_paid_sets_paid_at(self):
        """Bulk mark_paid must set Invoice.paid_at."""
        inv = self._make_invoice(status='SENT', total='200.00')
        self.assertIsNone(inv.paid_at)

        self._bulk_action([inv.id])
        inv.refresh_from_db()
        self.assertIsNotNone(inv.paid_at)

    def test_mark_paid_sets_status_paid(self):
        """Invoice status must be PAID after bulk mark_paid."""
        inv = self._make_invoice(status='SENT', total='75.00')

        self._bulk_action([inv.id])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'PAID')

    def test_mark_paid_sets_amount_paid_to_total(self):
        """Invoice.amount_paid must equal Invoice.total after mark_paid."""
        # Create a PARTIAL invoice with a proper Payment record for the initial partial amount.
        # _update_invoice_totals() re-sums all Payment records, so partial payments must
        # be represented as Payment rows for the final sum to be correct.
        inv = self._make_invoice(status='PARTIAL', total='300.00', amount_paid='100.00')
        # Create the Payment record that represents the already-paid $100
        Payment.objects.create(
            invoice=inv,
            amount=Decimal('100.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )

        self._bulk_action([inv.id])
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal('300.00'))

    def test_mark_paid_partial_invoice_only_creates_remaining_payment(self):
        """For a PARTIAL invoice, Payment amount = remaining balance only."""
        inv = self._make_invoice(status='PARTIAL', total='500.00', amount_paid='200.00')
        # Create the Payment record that represents the already-paid $200
        Payment.objects.create(
            invoice=inv,
            amount=Decimal('200.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )

        self._bulk_action([inv.id])

        # Total payments = $200 (existing) + $300 (bulk) = $500
        # But we only look at the NEW payment created by the bulk action.
        # The new payment should be for the remaining $300.
        payments = Payment.objects.filter(invoice=inv).order_by('created_at')
        self.assertEqual(payments.count(), 2)
        # The second payment (created by bulk action) should be $300
        new_payment = payments.last()
        self.assertEqual(new_payment.amount, Decimal('300.00'))

    def test_mark_paid_multiple_invoices(self):
        """Bulk mark_paid works across multiple invoices simultaneously."""
        inv1 = self._make_invoice(status='SENT', total='100.00')
        inv2 = self._make_invoice(status='OVERDUE', total='250.00')
        inv3 = self._make_invoice(status='DRAFT', total='50.00')

        resp = self._bulk_action([inv1.id, inv2.id, inv3.id])
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        self.assertIn('3', data['message'])  # "3 invoice(s) marked as paid"

        for inv in [inv1, inv2, inv3]:
            inv.refresh_from_db()
            self.assertEqual(inv.status, 'PAID')
            self.assertIsNotNone(inv.paid_at)
            self.assertEqual(Payment.objects.filter(invoice=inv).count(), 1)

    def test_already_paid_invoice_skipped(self):
        """Already-PAID invoice is excluded from mark_paid processing."""
        inv = self._make_invoice(status='PAID', total='100.00', amount_paid='100.00')
        initial_payment_count = Payment.objects.filter(invoice=inv).count()

        resp = self._bulk_action([inv.id])
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        # No additional payments created
        self.assertEqual(
            Payment.objects.filter(invoice=inv).count(),
            initial_payment_count
        )

    def test_tenant_isolation_cross_tenant_invoice_ignored(self):
        """Invoices from another tenant cannot be bulk-marked-paid."""
        other_user = User.objects.create_user('other115', password='pass')
        other_tenant = Tenant.objects.create(
            name='Other Shop 115', slug='other-shop-115', owner=other_user, is_active=True
        )
        TenantMembership.objects.create(
            user=other_user, tenant=other_tenant, role='owner', is_active=True
        )
        other_customer = Customer.objects.create(
            name='Other Customer', tenant=other_tenant, email='other115@test.com'
        )
        other_inv = Invoice.objects.create(
            customer=other_customer,
            tenant=other_tenant,
            invoice_number='INV-OTHER-115-1',
            invoice_date=timezone.now().date(),
            total=Decimal('500.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )

        resp = self._bulk_action([other_inv.id])
        data = json.loads(resp.content)
        # Action succeeds but the cross-tenant invoice is not affected
        self.assertTrue(data['success'])
        other_inv.refresh_from_db()
        self.assertEqual(other_inv.status, 'SENT')
        self.assertEqual(Payment.objects.filter(invoice=other_inv).count(), 0)
