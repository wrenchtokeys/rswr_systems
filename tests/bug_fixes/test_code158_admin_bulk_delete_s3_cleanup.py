"""
CODE-158: Regression tests — Admin bulk_delete_invoices must use instance loop
for S3 cleanup.

Bug: InvoiceAdmin.bulk_delete_invoices() called `safe.delete()` (QuerySet.delete),
which bypasses Invoice.delete() model overrides.  Invoice.delete() calls
_delete_s3_object() to clean up S3 PDF objects on deletion.  Using QuerySet.delete
meant S3 objects were orphaned whenever an admin bulk-deleted DRAFT or CANCELLED
invoices via the Django admin.

This was the same class of bug fixed for the owner portal in CODE-152
(owner_invoice_bulk_action in saas/views.py), but the admin action was missed.

Fix: Changed bulk_delete_invoices to loop `for inv in safe: inv.delete()` so
Invoice.delete() (and its S3 cleanup) fires for every record.

Tests:
1. Verify bulk_delete_invoices calls Invoice.delete() for each invoice.
2. Verify Invoice.delete() calls _delete_s3_object — i.e., S3 cleanup runs.
3. Verify invoices with active/paid status are skipped.
4. Verify invoices with payment records are skipped.
"""

from unittest.mock import patch, MagicMock, call
from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.cookie import CookieStorage

from apps.billing.admin import InvoiceAdmin
from apps.billing.models import Invoice, Payment, BillingConfig
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


def _make_request_with_messages(user):
    """Create a fake admin request with message support."""
    factory = RequestFactory()
    request = factory.post('/')
    request.user = user
    request._messages = CookieStorage(request)
    return request


class AdminBulkDeleteS3CleanupTest(TestCase):
    """Verify bulk_delete_invoices uses instance loop, not QuerySet.delete."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            'admin158', 'admin158@example.com', 'password'
        )
        self.tenant = Tenant.objects.create(
            name='S3 Admin Shop', slug='s3-admin-shop', owner=self.user,
        )
        TenantMembership.objects.create(
            user=self.user, tenant=self.tenant, role='owner',
        )
        self.customer = Customer.objects.create(
            name='Admin Bulk Customer', tenant=self.tenant,
        )
        self.site = AdminSite()
        self.admin = InvoiceAdmin(Invoice, self.site)

    def _make_invoice(self, s3_key='', status='DRAFT', number_suffix='1'):
        return Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=f'INV-ADMIN-{number_suffix}',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            status=status,
            s3_key=s3_key,
        )

    @patch.object(Invoice, '_delete_s3_object')
    def test_bulk_delete_calls_s3_cleanup_for_each_invoice(self, mock_s3):
        """Each deleted invoice triggers _delete_s3_object."""
        inv1 = self._make_invoice(s3_key='invoices/1/a.pdf', number_suffix='A1')
        inv2 = self._make_invoice(s3_key='invoices/1/b.pdf', status='CANCELLED', number_suffix='A2')

        request = _make_request_with_messages(self.user)
        qs = Invoice.objects.filter(pk__in=[inv1.pk, inv2.pk])
        self.admin.bulk_delete_invoices(request, qs)

        # s3 cleanup should fire once per invoice
        self.assertEqual(mock_s3.call_count, 2)

    @patch.object(Invoice, '_delete_s3_object')
    def test_bulk_delete_active_invoices_are_skipped(self, mock_s3):
        """SENT/PAID/PARTIAL invoices are not deleted and S3 is not touched."""
        active = self._make_invoice(s3_key='invoices/1/c.pdf', status='SENT', number_suffix='B1')

        request = _make_request_with_messages(self.user)
        qs = Invoice.objects.filter(pk=active.pk)
        self.admin.bulk_delete_invoices(request, qs)

        mock_s3.assert_not_called()
        # Invoice still exists
        self.assertTrue(Invoice.objects.filter(pk=active.pk).exists())

    def test_bulk_delete_invoices_with_payments_are_skipped(self):
        """CANCELLED invoices with recorded payments cannot be deleted."""
        inv = self._make_invoice(status='CANCELLED', number_suffix='C1')
        from django.utils import timezone as _tz
        Payment.objects.create(
            invoice=inv,
            amount=Decimal('100.00'),
            payment_method='CHECK',
            payment_date=_tz.now().date(),
        )

        request = _make_request_with_messages(self.user)
        qs = Invoice.objects.filter(pk=inv.pk)

        with patch.object(Invoice, '_delete_s3_object'):
            self.admin.bulk_delete_invoices(request, qs)

        # Invoice must still exist — payment blocks deletion
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    @patch.object(Invoice, '_delete_s3_object')
    def test_bulk_delete_removes_draft_and_cancelled_without_payments(self, mock_s3):
        """DRAFT and CANCELLED invoices with no payments are deleted."""
        draft = self._make_invoice(status='DRAFT', number_suffix='D1')
        cancelled = self._make_invoice(status='CANCELLED', number_suffix='D2')

        request = _make_request_with_messages(self.user)
        qs = Invoice.objects.filter(pk__in=[draft.pk, cancelled.pk])
        self.admin.bulk_delete_invoices(request, qs)

        self.assertFalse(Invoice.objects.filter(pk=draft.pk).exists())
        self.assertFalse(Invoice.objects.filter(pk=cancelled.pk).exists())
        self.assertEqual(mock_s3.call_count, 2)

    @patch.object(Invoice, '_delete_s3_object')
    def test_bulk_delete_no_invoices_noop(self, mock_s3):
        """Empty queryset produces no S3 calls and no crash."""
        request = _make_request_with_messages(self.user)
        qs = Invoice.objects.none()
        self.admin.bulk_delete_invoices(request, qs)
        mock_s3.assert_not_called()
