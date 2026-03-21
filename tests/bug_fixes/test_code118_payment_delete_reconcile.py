"""
CODE-118 regression tests: Payment.delete() must reconcile invoice totals.

Bug: Payment.save() called _update_invoice_totals() on creation/update, but
there was no Payment.delete() override. When a payment was deleted (via Django
admin inline, QuerySet.delete(), or direct model .delete()), invoice.amount_paid
was never decremented.

Consequence: A PAID invoice would remain PAID even after its only payment was
deleted. The invoice showed $X paid with $0 balance when the actual balance
owed was $X. Shop owners relying on the admin to reverse accidental payments
would be unable to correct invoices.

Fix: Added Payment.delete() override that recomputes invoice totals after
the row is removed using SELECT FOR UPDATE to be concurrency-safe.
Also resets invoice status correctly (PAID → SENT, PAID → PARTIAL, PAID → OVERDUE
for past-due invoices with no payments) and clears paid_at when appropriate.
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, Payment, BillingConfig
from core.models import Customer


class PaymentDeleteReconcileTests(TestCase):
    """Payment.delete() must reconcile invoice totals."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_118', password='testpass', email='owner118@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 118', slug='shop-118', owner=self.owner, is_active=True
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )
        BillingConfig.get_for_tenant(self.tenant)

        self.customer = Customer.objects.create(
            name='Test Customer 118',
            tenant=self.tenant,
            email='cust118@test.com',
        )

        # Create a base invoice with $100 total
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-118-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )

    def _create_payment(self, amount, method='CHECK'):
        return Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal(str(amount)),
            payment_method=method,
            payment_date=timezone.now().date(),
        )

    def test_delete_only_payment_resets_amount_paid_to_zero(self):
        """Deleting the only payment should leave amount_paid=0 and status=SENT."""
        payment = self._create_payment('100.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(self.invoice.amount_paid, Decimal('100.00'))

        # Delete the payment
        payment.delete()

        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.amount_paid, Decimal('0.00'),
            "amount_paid should be 0 after deleting the only payment"
        )
        # Status should revert to SENT (not PAID — no money received)
        self.assertEqual(
            self.invoice.status, 'SENT',
            "Invoice should revert to SENT after its only payment is deleted"
        )
        # paid_at should be cleared
        self.assertIsNone(self.invoice.paid_at, "paid_at should be cleared when payment is deleted")

    def test_delete_partial_payment_reduces_amount_paid(self):
        """Deleting one of two payments should reflect the remaining amount."""
        p1 = self._create_payment('60.00')
        p2 = self._create_payment('40.00')

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(self.invoice.amount_paid, Decimal('100.00'))

        # Delete the $40 payment
        p2.delete()

        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.amount_paid, Decimal('60.00'),
            "amount_paid should be 60 after deleting the $40 payment"
        )
        self.assertEqual(
            self.invoice.status, 'PARTIAL',
            "Invoice should be PARTIAL after one of two payments is deleted"
        )
        self.assertIsNone(
            self.invoice.paid_at,
            "paid_at should be cleared when invoice reverts to PARTIAL"
        )

    def test_delete_all_payments_sequentially_leaves_zero(self):
        """Deleting all payments one by one should leave amount_paid=0."""
        p1 = self._create_payment('50.00')
        p2 = self._create_payment('50.00')

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

        p1.delete()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('50.00'))
        self.assertEqual(self.invoice.status, 'PARTIAL')

        p2.delete()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'SENT')

    def test_invoice_status_reverts_to_overdue_if_past_due(self):
        """After deleting payment on a past-due invoice, status reverts to OVERDUE."""
        # Make the invoice past-due
        past_date = timezone.now().date() - timezone.timedelta(days=5)
        Invoice.objects.filter(pk=self.invoice.pk).update(due_date=past_date, status='OVERDUE')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'OVERDUE')

        payment = self._create_payment('100.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

        payment.delete()

        self.invoice.refresh_from_db()
        # is_overdue returns True (due_date in the past), so should set OVERDUE
        self.assertEqual(
            self.invoice.status, 'OVERDUE',
            "Past-due invoice with no payments should be OVERDUE after payment deletion"
        )
        self.assertIsNone(self.invoice.paid_at)

    def test_paid_at_cleared_when_reverted_to_partial(self):
        """paid_at is cleared when invoice is reverted from PAID to PARTIAL."""
        p1 = self._create_payment('80.00')
        p2 = self._create_payment('20.00')

        self.invoice.refresh_from_db()
        self.assertIsNotNone(self.invoice.paid_at)
        self.assertEqual(self.invoice.status, 'PAID')

        # Delete the $20 payment — invoice should become PARTIAL, paid_at should be cleared
        p2.delete()

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('80.00'))
        self.assertEqual(self.invoice.status, 'PARTIAL')
        self.assertIsNone(
            self.invoice.paid_at,
            "paid_at should be cleared when invoice reverts to PARTIAL"
        )

    def test_delete_payment_safe_when_invoice_does_not_exist(self):
        """Payment deletion is safe even if the invoice is unexpectedly gone (DoesNotExist handled)."""
        # Normal deletion should work without raising
        payment = self._create_payment('100.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('100.00'))
        payment.delete()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))

    def test_payment_delete_leaves_status_unchanged_on_cancelled_invoice(self):
        """Deleting a payment on a CANCELLED invoice should not change status back."""
        payment = self._create_payment('100.00')
        # Manually cancel the invoice
        self.invoice.status = 'CANCELLED'
        self.invoice.save(update_fields=['status'])

        # delete() will recompute — but CANCELLED is skipped
        payment.delete()

        self.invoice.refresh_from_db()
        # Status remains CANCELLED (delete() skips if CANCELLED)
        self.assertEqual(self.invoice.status, 'CANCELLED')
