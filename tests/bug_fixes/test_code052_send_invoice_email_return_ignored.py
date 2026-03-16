"""
Regression tests for CODE-052: send_invoice_email billing view ignores
the (bool, str) return value from InvoiceEmailService.send_invoice_email().

Bug:
  - billing/views.send_invoice_email: called email_svc.send_invoice_email()
    without capturing the return tuple.  When email delivery silently failed
    (returned (False, "error")), the view still marked the invoice SENT and
    returned {"success": True} to the caller.
  - billing/views.send_invoice_email_batch: same pattern — silent delivery
    failure was reported as success in the per-invoice result dict.

Fix:
  Both views now capture (success, msg) and return an error response / record
  failure when success is False.
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice
from core.models import Customer

from apps.billing.views import send_invoice_email, send_invoice_email_batch


def _make_request(factory, method, body=None, tenant=None, user=None):
    """Helper to build a fake request with tenant attached."""
    if method == 'POST':
        req = factory.post(
            '/fake/',
            data=json.dumps(body or {}),
            content_type='application/json',
        )
    else:
        req = factory.get('/fake/')
    if tenant:
        req.tenant = tenant
    if user:
        req.user = user
    return req


class SendInvoiceEmailReturnValueTestCase(TestCase):
    """
    Tests that billing/views.send_invoice_email() correctly handles the
    (bool, str) tuple returned by InvoiceEmailService.send_invoice_email().
    """

    def setUp(self):
        self.factory = RequestFactory()

        # Owner user (must be created before Tenant)
        self.owner = User.objects.create_user(
            username="owner52",
            email="owner52@example.com",
            password="password123",
        )

        # Tenant
        self.tenant = Tenant.objects.create(
            name="Test Shop",
            slug="test-shop",
            subdomain="test-shop",
            is_active=True,
            owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role="owner",
            is_active=True,
        )

        # Customer with email
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Fleet Co",
            email="billing@fleet.com",
        )

        # Invoice in DRAFT status
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number="INV-052-001",
            status="DRAFT",
            subtotal=100,
            total=100,
            amount_paid=0,
        )

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
           return_value=(True, "Sent successfully"))
    def test_successful_email_marks_invoice_sent(self, mock_send):
        """When email_svc returns (True, '...'), invoice is marked SENT."""
        req = _make_request(
            self.factory, 'POST',
            body={"recipient_email": "billing@fleet.com"},
            tenant=self.tenant,
            user=self.owner,
        )
        response = send_invoice_email(req, self.invoice.id)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])

        # Invoice should now be SENT
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
           return_value=(False, "SMTP connection refused"))
    def test_failed_email_does_not_mark_invoice_sent(self, mock_send):
        """When email_svc returns (False, 'SMTP error'), invoice stays DRAFT."""
        req = _make_request(
            self.factory, 'POST',
            body={"recipient_email": "billing@fleet.com"},
            tenant=self.tenant,
            user=self.owner,
        )
        response = send_invoice_email(req, self.invoice.id)

        # Should return error
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.content)
        self.assertIn('error', data)
        self.assertIn('SMTP', data['error'])

        # Invoice must still be DRAFT — was NOT falsely promoted to SENT
        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.status, 'DRAFT',
            "Invoice should NOT be marked SENT when email delivery failed"
        )

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
           return_value=(False, "Delivery error"))
    def test_already_sent_invoice_failure_returns_error(self, mock_send):
        """Re-sending a SENT invoice that fails returns error (not success)."""
        self.invoice.status = 'SENT'
        self.invoice.save(update_fields=['status'])

        req = _make_request(
            self.factory, 'POST',
            body={"recipient_email": "billing@fleet.com"},
            tenant=self.tenant,
            user=self.owner,
        )
        response = send_invoice_email(req, self.invoice.id)

        self.assertEqual(response.status_code, 500)
        data = json.loads(response.content)
        self.assertIn('error', data)

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
           return_value=(True, "OK"))
    def test_successful_resend_of_sent_invoice_returns_success(self, mock_send):
        """Resending a SENT invoice that succeeds returns success."""
        self.invoice.status = 'SENT'
        self.invoice.save(update_fields=['status'])

        req = _make_request(
            self.factory, 'POST',
            body={"recipient_email": "billing@fleet.com"},
            tenant=self.tenant,
            user=self.owner,
        )
        response = send_invoice_email(req, self.invoice.id)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])


class SendInvoiceEmailBatchReturnValueTestCase(TestCase):
    """
    Tests that billing/views.send_invoice_email_batch() correctly handles the
    (bool, str) tuple per invoice and records failures accurately.
    """

    def setUp(self):
        self.factory = RequestFactory()

        self.owner = User.objects.create_user(
            username="owner52b",
            email="owner52b@example.com",
            password="password123",
        )
        self.tenant = Tenant.objects.create(
            name="Batch Shop",
            slug="batch-shop",
            subdomain="batch-shop",
            is_active=True,
            owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role="owner",
            is_active=True,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Batch Fleet",
            email="billing@batchfleet.com",
        )
        self.invoice1 = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number="INV-052-B01",
            status="SENT",
            subtotal=50,
            total=50,
            amount_paid=0,
        )
        self.invoice2 = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number="INV-052-B02",
            status="SENT",
            subtotal=75,
            total=75,
            amount_paid=0,
        )

    def _batch_request(self, invoice_ids):
        req = _make_request(
            self.factory, 'POST',
            body={'invoice_ids': invoice_ids},
            tenant=self.tenant,
            user=self.owner,
        )
        return send_invoice_email_batch(req)

    def test_batch_mixed_results_accurately_reported(self):
        """
        When invoice1 succeeds and invoice2 fails, batch results should show
        sent=1, failed=1, with correct per-invoice status.
        """
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (True, "OK")
            else:
                return (False, "Rate limit exceeded")

        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
            side_effect=side_effect
        ):
            response = self._batch_request([self.invoice1.id, self.invoice2.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertTrue(data['success'])
        self.assertEqual(data['sent'], 1)
        self.assertEqual(data['failed'], 1)

        results_by_id = {r['id']: r for r in data['results']}

        self.assertTrue(results_by_id[self.invoice1.id]['success'])
        self.assertFalse(results_by_id[self.invoice2.id]['success'])
        self.assertIn('Rate limit', results_by_id[self.invoice2.id]['error'])

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
           return_value=(False, "Mailserver down"))
    def test_batch_all_failed_reports_zero_sent(self, mock_send):
        """All emails failing → sent=0, failed=N."""
        response = self._batch_request([self.invoice1.id, self.invoice2.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 0)
        self.assertEqual(data['failed'], 2)

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
           return_value=(True, "OK"))
    def test_batch_all_success_reports_correct_count(self, mock_send):
        """All emails succeeding → sent=N, failed=0."""
        response = self._batch_request([self.invoice1.id, self.invoice2.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 2)
        self.assertEqual(data['failed'], 0)
