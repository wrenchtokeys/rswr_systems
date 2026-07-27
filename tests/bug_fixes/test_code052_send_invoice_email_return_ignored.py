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


# ─────────────────────────────────────────────────────────────────────────────
# CODE-182 regression: send_invoice_email_batch must promote DRAFT → SENT
# ─────────────────────────────────────────────────────────────────────────────

class SendInvoiceEmailBatchStatusUpdateTestCase(TestCase):
    """
    CODE-182: send_invoice_email_batch() never promoted DRAFT invoices to
    SENT after successful delivery.

    Bug:
        The batch loop called email_svc.send_invoice_email() and appended
        the result, but never updated invoice.status or invoice.sent_at.
        Invoices sent via batch stayed DRAFT forever — appearing in "unsent"
        filters, blocking automated reminders, and leaving sent_at as NULL.

    Fix:
        On successful delivery, if invoice.status == 'DRAFT':
            invoice.status = 'SENT'
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=['status', 'sent_at'])

    This matches the existing single-send path behaviour (lines 396-400 of
    billing/views.py at the time of fix).
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = User.objects.create_user(
            username="owner182",
            email="owner182@example.com",
            password="password123",
        )
        self.tenant = Tenant.objects.create(
            name="Status Update Shop",
            slug="status-update-shop",
            subdomain="status-update-shop",
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
            name="Draft Fleet",
            email="billing@draftfleet.com",
        )
        self.invoice_draft = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number="INV-182-01",
            status="DRAFT",
            subtotal=100,
            total=100,
            amount_paid=0,
        )
        self.invoice_sent = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number="INV-182-02",
            status="SENT",
            subtotal=50,
            total=50,
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

    @patch(
        'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        return_value=(True, "Sent successfully"),
    )
    def test_draft_invoice_promoted_to_sent_on_success(self, mock_send):
        """
        CODE-182: A DRAFT invoice must be promoted to SENT after a successful
        batch send (matches single-send behaviour).
        """
        response = self._batch_request([self.invoice_draft.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 1)

        self.invoice_draft.refresh_from_db()
        self.assertEqual(
            self.invoice_draft.status, 'SENT',
            "DRAFT invoice must be promoted to SENT after successful batch send"
        )
        self.assertIsNotNone(
            self.invoice_draft.sent_at,
            "sent_at must be set after successful batch send"
        )

    @patch(
        'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        return_value=(False, "SMTP error"),
    )
    def test_draft_invoice_stays_draft_on_failure(self, mock_send):
        """
        CODE-182: A DRAFT invoice must NOT be promoted when email delivery
        fails — status must remain DRAFT.
        """
        response = self._batch_request([self.invoice_draft.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 0)
        self.assertEqual(data['failed'], 1)

        self.invoice_draft.refresh_from_db()
        self.assertEqual(
            self.invoice_draft.status, 'DRAFT',
            "Invoice status must NOT change when delivery fails"
        )
        self.assertIsNone(
            self.invoice_draft.sent_at,
            "sent_at must remain NULL when delivery fails"
        )

    @patch(
        'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        return_value=(True, "OK"),
    )
    def test_already_sent_invoice_not_re_stamped(self, mock_send):
        """
        CODE-182: Resending a SENT invoice must not overwrite sent_at (the
        first-send timestamp) — only last_sent_at moves. Only DRAFT invoices
        get promoted.
        """
        from django.utils import timezone as tz
        original_sent_at = tz.now() - tz.timedelta(days=5)
        type(self.invoice_sent).all_objects.filter(pk=self.invoice_sent.pk).update(
            sent_at=original_sent_at
        )
        response = self._batch_request([self.invoice_sent.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 1)

        self.invoice_sent.refresh_from_db()
        self.assertEqual(
            self.invoice_sent.status, 'SENT',
            "SENT invoice should remain SENT after resend"
        )
        # sent_at (first send) should not have changed on a resend
        self.assertEqual(
            self.invoice_sent.sent_at, original_sent_at,
            "sent_at of a SENT invoice should not be overwritten by a resend"
        )
        # ...but the resend itself is still recorded
        self.assertIsNotNone(
            self.invoice_sent.last_sent_at,
            "last_sent_at should record the resend"
        )
        self.assertGreater(self.invoice_sent.last_sent_at, original_sent_at)

    @patch(
        'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        return_value=(True, "OK"),
    )
    def test_mixed_batch_only_drafts_promoted(self, mock_send):
        """
        CODE-182: In a mixed batch (DRAFT + SENT), only the DRAFT invoice
        should be promoted. The SENT invoice must be unchanged.
        """
        response = self._batch_request([self.invoice_draft.id, self.invoice_sent.id])

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 2)

        self.invoice_draft.refresh_from_db()
        self.invoice_sent.refresh_from_db()

        self.assertEqual(self.invoice_draft.status, 'SENT')
        self.assertIsNotNone(self.invoice_draft.sent_at)

        # SENT invoice status unchanged
        self.assertEqual(self.invoice_sent.status, 'SENT')
