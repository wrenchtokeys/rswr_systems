"""
CODE-124 regression tests: PaymentAdmin.delete_queryset() must reconcile invoice totals.

Bug: Django's QuerySet.delete() fires a SQL DELETE directly, bypassing Python-level
model .delete() overrides.  PaymentAdmin used the default delete_queryset() which
calls queryset.delete() — so bulk-deleting payments via the admin changelist
bypassed Payment.delete() entirely.

Payment.delete() (CODE-118) reconciles invoice.amount_paid and status after a payment
is removed.  Without delete_queryset(), admin bulk delete left:
  - invoice.amount_paid stale (still showing the deleted payment's amount)
  - invoice.status stuck as PAID even with $0 payments
  - paid_at not cleared

Fix: Override PaymentAdmin.delete_queryset() to iterate and call payment.delete()
on each instance, ensuring the CODE-118 reconciliation logic runs for every row.
"""
from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, Payment, BillingConfig
from apps.billing.admin import PaymentAdmin
from core.models import Customer


class PaymentAdminBulkDeleteReconcileTests(TestCase):
    """PaymentAdmin.delete_queryset() must call Payment.delete() on each instance."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_124', password='testpass', email='admin124@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 124', slug='shop-124', owner=self.superuser, is_active=True
        )
        TenantMembership.objects.create(
            user=self.superuser, tenant=self.tenant, role='owner', is_active=True
        )
        BillingConfig.get_for_tenant(self.tenant)

        self.customer = Customer.objects.create(
            name='Test Customer 124',
            tenant=self.tenant,
            email='cust124@test.com',
        )

        # Create an invoice with $100 total
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-124-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('100.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )

        self.site = AdminSite()
        self.admin = PaymentAdmin(Payment, self.site)

        factory = RequestFactory()
        self.request = factory.post('/admin/')
        self.request.user = self.superuser

    def _make_payment(self, amount, method='CASH'):
        """Helper to create a payment and return it."""
        return Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal(str(amount)),
            payment_method=method,
            payment_date=timezone.now().date(),
        )

    def test_bulk_delete_single_payment_resets_invoice_to_sent(self):
        """Bulk-deleting the only payment should reset invoice from PAID to SENT."""
        payment = self._make_payment('100.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(self.invoice.amount_paid, Decimal('100.00'))

        # Simulate admin bulk delete
        qs = Payment.objects.filter(pk=payment.pk)
        self.admin.delete_queryset(self.request, qs)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT',
                         "Invoice should revert to SENT after sole payment deleted")
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'),
                         "amount_paid should be 0 after payment deleted")
        self.assertIsNone(self.invoice.paid_at,
                          "paid_at should be cleared after payment deleted")

    def test_bulk_delete_partial_payment_reduces_amount_paid(self):
        """Bulk-deleting one of two payments should leave invoice PARTIAL."""
        p1 = self._make_payment('60.00')
        p2 = self._make_payment('40.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

        # Delete only the $40 payment
        qs = Payment.objects.filter(pk=p2.pk)
        self.admin.delete_queryset(self.request, qs)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PARTIAL',
                         "Invoice should be PARTIAL after partial payment deleted")
        self.assertEqual(self.invoice.amount_paid, Decimal('60.00'),
                         "amount_paid should reflect remaining payment")

    def test_bulk_delete_multiple_payments_reconciles_all(self):
        """Bulk-deleting multiple payments at once should reconcile all."""
        p1 = self._make_payment('50.00')
        p2 = self._make_payment('50.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

        # Delete both payments at once via queryset
        qs = Payment.objects.filter(pk__in=[p1.pk, p2.pk])
        self.admin.delete_queryset(self.request, qs)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))

    def test_bulk_delete_does_not_affect_other_invoices(self):
        """Deleting a payment on invoice A should not affect invoice B."""
        # Create a second invoice
        invoice_b = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-124-002',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=Decimal('200.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('200.00'),
            amount_paid=Decimal('0.00'),
            status='SENT',
        )
        p_b = Payment.objects.create(
            invoice=invoice_b,
            amount=Decimal('200.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )
        invoice_b.refresh_from_db()
        self.assertEqual(invoice_b.status, 'PAID')

        # Delete a payment on invoice A (no payments yet)
        p_a = self._make_payment('100.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

        qs = Payment.objects.filter(pk=p_a.pk)
        self.admin.delete_queryset(self.request, qs)

        # Invoice A should be reset, invoice B should be unaffected
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')

        invoice_b.refresh_from_db()
        self.assertEqual(invoice_b.status, 'PAID',
                         "Invoice B should not be affected by deleting Invoice A's payment")
        self.assertEqual(invoice_b.amount_paid, Decimal('200.00'))

    def test_default_queryset_delete_bypasses_override_regression(self):
        """
        Verify our delete_queryset IS called (not the default queryset.delete).
        This is a code-structure check: Payment.delete() reconciles invoice totals,
        and delete_queryset iterates each payment.  If the admin used the default
        queryset.delete() instead, this test would fail because reconciliation
        wouldn't run.
        """
        payment = self._make_payment('100.00')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertIsNotNone(self.invoice.paid_at)

        # Use delete_queryset (our override) — invoice should be reconciled
        qs = Payment.objects.filter(pk=payment.pk)
        self.admin.delete_queryset(self.request, qs)

        self.invoice.refresh_from_db()
        # If the override works, invoice is now SENT with $0 paid
        self.assertEqual(self.invoice.status, 'SENT')
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertIsNone(self.invoice.paid_at)

        # Payment should be gone
        self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())

    def test_delete_queryset_with_empty_queryset_is_safe(self):
        """Deleting an empty queryset should not crash."""
        qs = Payment.objects.none()
        # Should not raise
        self.admin.delete_queryset(self.request, qs)
