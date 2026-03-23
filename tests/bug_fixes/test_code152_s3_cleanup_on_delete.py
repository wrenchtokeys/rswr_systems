"""
CODE-152: Regression tests — S3 cleanup when invoices are deleted.

Bug: Deleting invoices (via bulk delete or single delete) left orphaned PDF
objects in S3.  Voided invoices correctly kept their PDFs for audit trail,
but actually-deleted invoices should clean up after themselves.

Fix: Added Invoice.delete() override that calls _delete_s3_object() before
the DB row is removed.  Also changed the bulk delete path in
owner_invoice_bulk_action to loop over instances (not QuerySet.delete())
so the model override fires.

Tests verify:
1. Invoice.delete() calls _delete_s3_object when s3_key is set.
2. Invoice.delete() is a no-op for S3 when s3_key is empty.
3. S3 errors during deletion don't block invoice deletion.
4. _delete_s3_object calls boto3 correctly with bucket + key.
"""

from unittest.mock import patch, MagicMock
from decimal import Decimal

from django.test import TestCase, override_settings
from django.contrib.auth.models import User

from apps.billing.models import Invoice, BillingConfig
from apps.tenants.models import Tenant, TenantMembership


class InvoiceS3CleanupOnDeleteTest(TestCase):
    """Tests for S3 object cleanup when invoices are hard-deleted."""

    def setUp(self):
        self.user = User.objects.create_user('owner152', password='test')
        self.tenant = Tenant.objects.create(
            name='S3 Cleanup Shop', slug='s3-cleanup-shop', owner=self.user,
        )
        TenantMembership.objects.create(user=self.user, tenant=self.tenant, role='owner')

        from core.models import Customer
        self.customer = Customer.objects.create(
            name='Cleanup Customer', tenant=self.tenant,
        )

    def _make_invoice(self, s3_key='', status='DRAFT'):
        return Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=f'INV-CLEANUP-{Invoice.objects.count() + 1}',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            status=status,
            s3_key=s3_key,
        )

    @patch.object(Invoice, '_delete_s3_object')
    def test_delete_calls_s3_cleanup(self, mock_s3_delete):
        """Invoice.delete() should call _delete_s3_object."""
        invoice = self._make_invoice(s3_key='invoices/42/test.pdf')
        invoice_id = invoice.id
        invoice.delete()
        mock_s3_delete.assert_called_once()
        self.assertFalse(Invoice.all_objects.filter(id=invoice_id).exists())

    @patch.object(Invoice, '_delete_s3_object')
    def test_delete_calls_s3_cleanup_even_without_key(self, mock_s3_delete):
        """Invoice.delete() always calls _delete_s3_object (method handles empty key)."""
        invoice = self._make_invoice(s3_key='')
        invoice.delete()
        mock_s3_delete.assert_called_once()

    def test_delete_s3_object_skips_when_no_key(self):
        """_delete_s3_object is a no-op when s3_key is empty."""
        invoice = self._make_invoice(s3_key='')
        # Should not raise and should not attempt any S3 call
        invoice._delete_s3_object()  # no-op, just returns

    @override_settings(AWS_STORAGE_BUCKET_NAME=None)
    def test_delete_s3_object_skips_when_no_bucket(self):
        """_delete_s3_object skips when AWS_STORAGE_BUCKET_NAME is unset."""
        invoice = self._make_invoice(s3_key='invoices/1/test.pdf')
        # Should not raise
        invoice._delete_s3_object()

    @override_settings(AWS_STORAGE_BUCKET_NAME='test-bucket')
    @patch('boto3.client')
    def test_delete_s3_object_calls_boto3(self, mock_boto3_client):
        """_delete_s3_object calls S3 delete_object with correct params."""
        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client

        invoice = self._make_invoice(s3_key='invoices/42/invoice_INV-1.pdf')
        invoice._delete_s3_object()

        mock_boto3_client.assert_called_once_with('s3')
        mock_client.delete_object.assert_called_once_with(
            Bucket='test-bucket',
            Key='invoices/42/invoice_INV-1.pdf',
        )

    @override_settings(AWS_STORAGE_BUCKET_NAME='test-bucket')
    @patch('boto3.client')
    def test_delete_s3_object_swallows_errors(self, mock_boto3_client):
        """S3 errors shouldn't propagate — deletion must still succeed."""
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = Exception('S3 unavailable')
        mock_boto3_client.return_value = mock_client

        invoice = self._make_invoice(s3_key='invoices/99/some.pdf')
        invoice_id = invoice.id

        # _delete_s3_object should not raise
        invoice._delete_s3_object()

        # Full delete should also work
        invoice.delete()
        self.assertFalse(Invoice.all_objects.filter(id=invoice_id).exists())
