"""
CODE-123 regression tests: Voiding a PARTIAL invoice must be blocked, and
deleting CANCELLED invoices with payments must not crash.

Bug (1) — owner_invoice_void:
  A PARTIAL invoice has real money recorded against it (Payment rows).
  The void view only blocked PAID and CANCELLED, so PARTIAL invoices could be
  voided with a single POST.  After voiding:
  - Payment records remained, pointing to a CANCELLED invoice
  - invoice.amount_paid stayed non-zero (stale)
  - The invoice could never be deleted (Payment.invoice is on_delete=PROTECT)
  - Financials were misleading: $X collected but invoice shows CANCELLED

Bug (2) — owner_invoice_bulk_action delete:
  The bulk 'delete' action called deletable.delete() without checking for
  Payment records.  If any CANCELLED invoice in the queryset had associated
  payments, Django raised ProtectedError (unhandled) → 500 crash.

Bug (3) — owner_invoice_bulk_action void:
  The bulk 'void' action excluded ['PAID', 'CANCELLED'] but not 'PARTIAL'.
  Bulk-selecting a mix of SENT + PARTIAL invoices would silently void the
  PARTIAL ones, causing the same orphaned-payment problem as bug (1).

Fix:
  (1) owner_invoice_void returns HTTP 400 with an error message for PARTIAL.
  (2) Bulk delete filters out invoices that have payments, reports skipped count.
  (3) Bulk void also skips PARTIAL invoices with a count in the response message.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, Payment, BillingConfig
from core.models import Customer


class VoidPartialInvoiceTests(TestCase):
    """owner_invoice_void must block PARTIAL invoices."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_123', password='testpass', email='owner123@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 123', slug='shop-123', owner=self.owner, is_active=True
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )
        BillingConfig.get_for_tenant(self.tenant)

        self.customer = Customer.objects.create(
            name='Test Customer 123',
            tenant=self.tenant,
            email='cust123@test.com',
        )

        # Create a PARTIAL invoice (amount_paid < total)
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-123-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )
        # Record a partial payment — triggers Payment.save() → amount_paid updated
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal('40.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PARTIAL')

        self.client = Client()
        self.client.login(username='owner_123', password='testpass')

    def test_void_partial_invoice_is_blocked(self):
        """Voiding a PARTIAL invoice must return 400 with an error message."""
        url = reverse('owner_invoice_void', kwargs={'invoice_id': self.invoice.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('partially-paid', data['error'].lower())

    def test_void_partial_does_not_change_status(self):
        """After a blocked void attempt, the invoice must remain PARTIAL."""
        url = reverse('owner_invoice_void', kwargs={'invoice_id': self.invoice.id})
        self.client.post(url)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PARTIAL')

    def test_void_partial_payment_count_in_error(self):
        """The 400 error should mention how many payments are blocking the void."""
        url = reverse('owner_invoice_void', kwargs={'invoice_id': self.invoice.id})
        response = self.client.post(url)
        data = response.json()
        self.assertIn('1', data['error'])  # 1 payment recorded

    def test_void_sent_invoice_still_works(self):
        """Voiding a SENT (unpaid) invoice must still succeed."""
        sent_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-123-002',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('50.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('50.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )
        url = reverse('owner_invoice_void', kwargs={'invoice_id': sent_invoice.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        sent_invoice.refresh_from_db()
        self.assertEqual(sent_invoice.status, 'CANCELLED')

    def test_void_paid_invoice_still_blocked(self):
        """Voiding a PAID invoice must remain blocked (pre-existing behaviour)."""
        # Add a second payment to push to PAID
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal('60.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        url = reverse('owner_invoice_void', kwargs={'invoice_id': self.invoice.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)


class BulkDeleteProtectedErrorTests(TestCase):
    """
    Bulk delete must not crash with ProtectedError when a CANCELLED invoice
    has associated Payment records.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_123b', password='testpass', email='owner123b@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 123B', slug='shop-123b', owner=self.owner, is_active=True
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )
        BillingConfig.get_for_tenant(self.tenant)

        self.customer = Customer.objects.create(
            name='Test Customer 123B',
            tenant=self.tenant,
            email='cust123b@test.com',
        )

        # Safe-to-delete CANCELLED invoice (no payments)
        self.safe_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-123B-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('50.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('50.00'),
            amount_paid=Decimal('0.00'),
            status='CANCELLED',
        )

        # CANCELLED invoice with a payment (would cause ProtectedError on delete)
        self.protected_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-123B-002',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('60.00'),
            status='CANCELLED',
        )
        # Bypass Payment.save() reconciliation by directly inserting (invoice already CANCELLED)
        Payment.objects.create(
            invoice=self.protected_invoice,
            amount=Decimal('60.00'),
            payment_method='CHECK',
            payment_date=timezone.now().date(),
        )

        self.client = Client()
        self.client.login(username='owner_123b', password='testpass')

    def _bulk_action(self, action, invoice_ids):
        import json
        url = reverse('owner_invoice_bulk_action')
        return self.client.post(
            url,
            data=json.dumps({'action': action, 'invoice_ids': invoice_ids}),
            content_type='application/json',
        )

    def test_delete_cancelled_with_payments_does_not_crash(self):
        """Bulk delete must return 200 (not 500) when a CANCELLED invoice has payments."""
        response = self._bulk_action(
            'delete',
            [self.safe_invoice.id, self.protected_invoice.id],
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

    def test_delete_skips_payment_blocked_invoices(self):
        """Protected invoices must remain after the bulk delete."""
        self._bulk_action(
            'delete',
            [self.safe_invoice.id, self.protected_invoice.id],
        )
        # The protected one still exists
        self.assertTrue(
            Invoice.objects.filter(id=self.protected_invoice.id).exists()
        )

    def test_delete_removes_safe_invoices(self):
        """Invoices without payments must be deleted normally."""
        self._bulk_action(
            'delete',
            [self.safe_invoice.id, self.protected_invoice.id],
        )
        self.assertFalse(
            Invoice.objects.filter(id=self.safe_invoice.id).exists()
        )

    def test_delete_message_mentions_skipped_payments(self):
        """The response message must mention the payment-blocked skipped count."""
        response = self._bulk_action(
            'delete',
            [self.safe_invoice.id, self.protected_invoice.id],
        )
        data = response.json()
        self.assertIn('payment', data['message'].lower())

    def test_delete_only_safe_invoices_no_skipped_message(self):
        """When no invoices are blocked, the message must not mention payments."""
        response = self._bulk_action('delete', [self.safe_invoice.id])
        data = response.json()
        self.assertNotIn('payment', data['message'].lower())


class BulkVoidPartialSkipTests(TestCase):
    """Bulk void must skip PARTIAL invoices."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_123c', password='testpass', email='owner123c@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 123C', slug='shop-123c', owner=self.owner, is_active=True
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )
        BillingConfig.get_for_tenant(self.tenant)

        self.customer = Customer.objects.create(
            name='Test Customer 123C',
            tenant=self.tenant,
            email='cust123c@test.com',
        )

        # SENT invoice (should be voided)
        self.sent_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-123C-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('80.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('80.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )

        # PARTIAL invoice (should be skipped)
        self.partial_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-123C-002',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )
        Payment.objects.create(
            invoice=self.partial_invoice,
            amount=Decimal('30.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )
        self.partial_invoice.refresh_from_db()
        self.assertEqual(self.partial_invoice.status, 'PARTIAL')

        self.client = Client()
        self.client.login(username='owner_123c', password='testpass')

    def _bulk_void(self, invoice_ids):
        import json
        url = reverse('owner_invoice_bulk_action')
        return self.client.post(
            url,
            data=json.dumps({'action': 'void', 'invoice_ids': invoice_ids}),
            content_type='application/json',
        )

    def test_bulk_void_skips_partial(self):
        """PARTIAL invoices must remain PARTIAL after a bulk void."""
        self._bulk_void([self.sent_invoice.id, self.partial_invoice.id])
        self.partial_invoice.refresh_from_db()
        self.assertEqual(self.partial_invoice.status, 'PARTIAL')

    def test_bulk_void_voids_sent(self):
        """SENT invoices in the same bulk void must still be voided."""
        self._bulk_void([self.sent_invoice.id, self.partial_invoice.id])
        self.sent_invoice.refresh_from_db()
        self.assertEqual(self.sent_invoice.status, 'CANCELLED')

    def test_bulk_void_message_mentions_partial_skip(self):
        """The response message must mention the partially-paid invoice(s) skipped."""
        response = self._bulk_void([self.sent_invoice.id, self.partial_invoice.id])
        data = response.json()
        self.assertIn('partial', data['message'].lower())
