"""
Regression tests for CODE-170: InvoiceAdmin missing delete_queryset() override.

Bug: InvoiceAdmin had a custom bulk_delete_invoices action that correctly:
  1. Only deleted DRAFT and CANCELLED invoices (skipped SENT/PAID/PARTIAL/OVERDUE)
  2. Skipped invoices with payment records
  3. Called inv.delete() instance-by-instance (so Invoice.delete() fired and
     _delete_s3_object() cleaned up S3 PDF objects)

But InvoiceAdmin did NOT override delete_queryset(). Django's default admin
'Delete selected' action calls delete_queryset() → QuerySet.delete(), which:
  - Deletes ANY invoice regardless of status (PAID, SENT, etc.)
  - Bypasses the payment-record guard (could leave orphaned Payment rows)
  - Never calls Invoice.delete(), so S3 PDF objects are orphaned in storage

This is the same class of bug fixed for RepairAdmin (CODE-167) and
PaymentAdmin (CODE-158).

Fix: Added delete_queryset() override to InvoiceAdmin that mirrors
bulk_delete_invoices: only deletes DRAFT/CANCELLED invoices with no payments,
iterating instance-by-instance so Invoice.delete() fires for each.

(CODE-170)
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.billing.admin import InvoiceAdmin
from apps.billing.models import Invoice, Payment
from apps.technician_portal.models import Customer
from apps.tenants.models import Tenant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser(username):
    return User.objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="testpass",
    )


def _make_tenant(name, owner=None):
    if owner is None:
        owner = User.objects.create_user(
            username=f"owner_{name.lower().replace(' ', '_')}",
            email=f"owner_{name.lower().replace(' ', '_')}@example.com",
            password="testpass",
        )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=owner,
    )


def _make_customer(tenant, name="Fleet Co"):
    return Customer.objects.create(tenant=tenant, name=name)


def _make_invoice(tenant, customer, status='DRAFT', total=Decimal('100.00'), amount_paid=Decimal('0.00'), s3_key=''):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        status=status,
        invoice_number=f"INV-{Invoice.objects.count() + 1:04d}",
        subtotal=total,
        total=total,
        amount_paid=amount_paid,
        tax_rate=Decimal('0.00'),
        tax_amount=Decimal('0.00'),
        s3_key=s3_key,
    )


def _make_payment(invoice, amount=Decimal('50.00')):
    return Payment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_method='CHECK',
        payment_date='2026-01-01',
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class InvoiceAdminDeleteQuerysetTest(TestCase):
    """
    Tests for InvoiceAdmin.delete_queryset() — the override that protects the
    default admin 'Delete selected' action from bypassing invoice safety guards.
    """

    def setUp(self):
        self.site = AdminSite()
        self.admin = InvoiceAdmin(Invoice, self.site)
        self.factory = RequestFactory()
        self.superuser = _make_superuser("superuser")
        self.tenant = _make_tenant("Shop A", owner=self.superuser)
        self.customer = _make_customer(self.tenant, "EOS Trucking")

    def _make_request(self):
        request = self.factory.get('/')
        request.user = self.superuser
        return request

    # ------------------------------------------------------------------
    # 1. DRAFT invoices are deleted
    # ------------------------------------------------------------------
    def test_draft_invoices_deleted(self):
        inv = _make_invoice(self.tenant, self.customer, status='DRAFT')
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 2. CANCELLED invoices are deleted
    # ------------------------------------------------------------------
    def test_cancelled_invoices_deleted(self):
        inv = _make_invoice(self.tenant, self.customer, status='CANCELLED')
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 3. SENT invoices are NOT deleted (active billing)
    # ------------------------------------------------------------------
    def test_sent_invoices_skipped(self):
        inv = _make_invoice(self.tenant, self.customer, status='SENT')
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 4. PAID invoices are NOT deleted (financial record)
    # ------------------------------------------------------------------
    def test_paid_invoices_skipped(self):
        inv = _make_invoice(
            self.tenant, self.customer, status='PAID',
            total=Decimal('100.00'), amount_paid=Decimal('100.00')
        )
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 5. PARTIAL invoices are NOT deleted (has payments)
    # ------------------------------------------------------------------
    def test_partial_invoices_skipped(self):
        inv = _make_invoice(
            self.tenant, self.customer, status='PARTIAL',
            total=Decimal('100.00'), amount_paid=Decimal('50.00')
        )
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 6. OVERDUE invoices are NOT deleted
    # ------------------------------------------------------------------
    def test_overdue_invoices_skipped(self):
        inv = _make_invoice(self.tenant, self.customer, status='OVERDUE')
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 7. CANCELLED invoice WITH payments is skipped (payment guard)
    # ------------------------------------------------------------------
    def test_cancelled_invoice_with_payment_skipped(self):
        """
        A CANCELLED invoice that still has Payment records must not be deleted.
        Deleting it would orphan the Payment rows.
        """
        inv = _make_invoice(self.tenant, self.customer, status='CANCELLED')
        _make_payment(inv, amount=Decimal('75.00'))
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 8. DRAFT invoice WITH payments is skipped (defensive)
    # ------------------------------------------------------------------
    def test_draft_invoice_with_payment_skipped(self):
        """Even a DRAFT invoice with a recorded payment should not be deleted."""
        inv = _make_invoice(self.tenant, self.customer, status='DRAFT')
        _make_payment(inv, amount=Decimal('50.00'))
        request = self._make_request()
        qs = Invoice.objects.filter(pk=inv.pk)
        self.admin.delete_queryset(request, qs)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    # ------------------------------------------------------------------
    # 9. Mixed queryset: only DRAFT/CANCELLED without payments are deleted
    # ------------------------------------------------------------------
    def test_mixed_queryset_only_safe_deleted(self):
        draft = _make_invoice(self.tenant, self.customer, status='DRAFT')
        cancelled = _make_invoice(self.tenant, self.customer, status='CANCELLED')
        sent = _make_invoice(self.tenant, self.customer, status='SENT')
        paid = _make_invoice(
            self.tenant, self.customer, status='PAID',
            total=Decimal('100.00'), amount_paid=Decimal('100.00')
        )
        draft_with_payment = _make_invoice(self.tenant, self.customer, status='DRAFT')
        _make_payment(draft_with_payment)

        request = self._make_request()
        qs = Invoice.objects.filter(
            pk__in=[draft.pk, cancelled.pk, sent.pk, paid.pk, draft_with_payment.pk]
        )
        self.admin.delete_queryset(request, qs)

        # Deleted
        self.assertFalse(Invoice.objects.filter(pk=draft.pk).exists())
        self.assertFalse(Invoice.objects.filter(pk=cancelled.pk).exists())
        # Kept
        self.assertTrue(Invoice.objects.filter(pk=sent.pk).exists())
        self.assertTrue(Invoice.objects.filter(pk=paid.pk).exists())
        self.assertTrue(Invoice.objects.filter(pk=draft_with_payment.pk).exists())

    # ------------------------------------------------------------------
    # 10. Invoice.delete() is called per-instance (S3 cleanup fires)
    # ------------------------------------------------------------------
    def test_invoice_delete_called_per_instance(self):
        """
        delete_queryset() must iterate instance-by-instance so Invoice.delete()
        fires and _delete_s3_object() can clean up the PDF in S3.

        We verify this by patching Invoice.delete and confirming it's called
        exactly once per deleted invoice.
        """
        inv1 = _make_invoice(self.tenant, self.customer, status='DRAFT', s3_key='invoices/inv1.pdf')
        inv2 = _make_invoice(self.tenant, self.customer, status='DRAFT', s3_key='invoices/inv2.pdf')
        request = self._make_request()
        qs = Invoice.objects.filter(pk__in=[inv1.pk, inv2.pk])

        delete_call_count = {'count': 0}
        original_delete = Invoice.delete

        def counting_delete(self_inner, *args, **kwargs):
            delete_call_count['count'] += 1
            return original_delete(self_inner, *args, **kwargs)

        with patch.object(Invoice, 'delete', counting_delete):
            self.admin.delete_queryset(request, qs)

        self.assertEqual(delete_call_count['count'], 2,
                         "Invoice.delete() should be called once per deleted invoice, not via bulk QuerySet.delete()")
