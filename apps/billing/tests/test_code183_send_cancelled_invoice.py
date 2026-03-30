"""
Regression tests for CODE-183:
send_invoice_email() API and send_invoice_email_batch() API allowed
sending emails for CANCELLED (voided) invoices.  The single-send path
also left the door open to accidentally re-activating a cancelled invoice
(status would not change, but the email was still sent to the customer).

Also covers the owner_email_invoice view (saas/views.py), which also
lacked a CANCELLED guard.

Author: Amelia (Clawdbot AI)
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from core.models import Customer
from apps.billing.models import Invoice, BillingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='test-plan-183',
        defaults={
            'name': 'Test Plan 183',
            'max_technicians': 5,
            'max_customers': 50,
            'monthly_price': Decimal('29.99'),
        }
    )
    return plan


def _create_tenant(name, email):
    plan = _create_plan()
    user = User.objects.create_user(username=email, email=email, password='pass123')
    tenant = Tenant.objects.create(
        name=name, owner=user, subscription_plan=plan, plan='starter', is_active=True
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner', is_active=True)
    BillingConfig.objects.get_or_create(tenant=tenant)
    return tenant, user


def _create_customer(tenant):
    return Customer.objects.create(
        name='Test Customer 183',
        email='customer183@example.com',
        tenant=tenant,
    )


def _create_invoice(tenant, customer, status='CANCELLED', suffix=None):
    unique_num = suffix or uuid.uuid4().hex[:8]
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-183-{unique_num}',
        status=status,
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        amount_paid=Decimal('0.00'),
    )


def _make_request(user, tenant, method='post', body=None):
    """Build a request that has tenant, user, session, and messages."""
    factory = RequestFactory()
    if method == 'post':
        req = factory.post('/', data=body or b'{}', content_type='application/json')
    else:
        req = factory.get('/')
    req.user = user
    req.tenant = tenant
    req.session = SessionStore()
    req._messages = FallbackStorage(req)
    return req


# ---------------------------------------------------------------------------
# Tests for billing/views.py :: send_invoice_email (single)
# ---------------------------------------------------------------------------

class SendCancelledInvoiceSingleTest(TestCase):
    """CODE-183: send_invoice_email() must reject CANCELLED invoices."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Shop 183a', 'owner183a@test.com')
        self.customer = _create_customer(self.tenant)
        self.invoice = _create_invoice(self.tenant, self.customer, status='CANCELLED')

    def test_cancelled_invoice_returns_400(self):
        """CANCELLED invoice → 400 with descriptive error."""
        from apps.billing.views import send_invoice_email

        req = _make_request(self.user, self.tenant, body=b'{}')
        response = send_invoice_email(req, self.invoice.id)

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('cancelled', data['error'].lower())

    def test_cancelled_invoice_email_not_sent(self):
        """Email service must not be called for a CANCELLED invoice."""
        from apps.billing.views import send_invoice_email

        with patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email') as mock_send:
            req = _make_request(self.user, self.tenant, body=b'{}')
            send_invoice_email(req, self.invoice.id)

        mock_send.assert_not_called()

    def test_cancelled_invoice_status_unchanged(self):
        """Invoice must remain CANCELLED (not promoted to SENT)."""
        from apps.billing.views import send_invoice_email

        req = _make_request(self.user, self.tenant, body=b'{}')
        send_invoice_email(req, self.invoice.id)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'CANCELLED')

    def test_paid_invoice_still_blocked(self):
        """Existing PAID guard must continue to work."""
        from apps.billing.views import send_invoice_email

        self.invoice.status = 'PAID'
        self.invoice.save(update_fields=['status'])

        req = _make_request(self.user, self.tenant, body=b'{}')
        response = send_invoice_email(req, self.invoice.id)

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('paid', data['error'].lower())

    def test_sent_invoice_still_allowed(self):
        """SENT invoices (resend) must still pass the guard."""
        from apps.billing.views import send_invoice_email

        self.invoice.status = 'SENT'
        self.invoice.save(update_fields=['status'])

        with patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
                   return_value=(True, 'ok')) as mock_send:
            req = _make_request(self.user, self.tenant, body=b'{}')
            response = send_invoice_email(req, self.invoice.id)

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for billing/views.py :: send_invoice_email_batch
# ---------------------------------------------------------------------------

class SendCancelledInvoiceBatchTest(TestCase):
    """CODE-183: send_invoice_email_batch() must skip CANCELLED invoices."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Shop 183b', 'owner183b@test.com')
        self.customer = _create_customer(self.tenant)
        self.cancelled_inv = _create_invoice(self.tenant, self.customer, status='CANCELLED', suffix='CXL')
        self.sent_inv = _create_invoice(self.tenant, self.customer, status='SENT', suffix='SENT')

    def test_cancelled_invoice_skipped_in_batch(self):
        """Batch send must report CANCELLED invoice as failed (not send it)."""
        from apps.billing.views import send_invoice_email_batch

        body = json.dumps({'invoice_ids': [self.cancelled_inv.id]}).encode()
        req = _make_request(self.user, self.tenant, body=body)
        response = send_invoice_email_batch(req)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['sent'], 0)
        self.assertEqual(data['failed'], 1)
        result = next(r for r in data['results'] if r['id'] == self.cancelled_inv.id)
        self.assertFalse(result['success'])
        self.assertIn('cancelled', result['error'].lower())

    def test_cancelled_invoice_email_not_sent_in_batch(self):
        """Email service must not be called for CANCELLED invoice in batch."""
        from apps.billing.views import send_invoice_email_batch

        body = json.dumps({'invoice_ids': [self.cancelled_inv.id]}).encode()

        with patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email') as mock_send:
            req = _make_request(self.user, self.tenant, body=body)
            send_invoice_email_batch(req)

        mock_send.assert_not_called()

    def test_batch_sends_non_cancelled_alongside_cancelled(self):
        """Batch with one CANCELLED + one SENT: SENT goes through, CANCELLED is skipped."""
        from apps.billing.views import send_invoice_email_batch

        body = json.dumps({'invoice_ids': [self.cancelled_inv.id, self.sent_inv.id]}).encode()

        with patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
                   return_value=(True, 'ok')):
            req = _make_request(self.user, self.tenant, body=body)
            response = send_invoice_email_batch(req)

        data = json.loads(response.content)
        self.assertEqual(data['sent'], 1)
        self.assertEqual(data['failed'], 1)

        cancelled_result = next(r for r in data['results'] if r['id'] == self.cancelled_inv.id)
        self.assertFalse(cancelled_result['success'])

        sent_result = next(r for r in data['results'] if r['id'] == self.sent_inv.id)
        self.assertTrue(sent_result['success'])


# ---------------------------------------------------------------------------
# Tests for saas/views.py :: owner_email_invoice
# ---------------------------------------------------------------------------

class OwnerEmailCancelledInvoiceTest(TestCase):
    """CODE-183: owner_email_invoice() in saas/views.py must block CANCELLED invoices."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Shop 183c', 'owner183c@test.com')
        self.customer = _create_customer(self.tenant)
        self.invoice = _create_invoice(self.tenant, self.customer, status='CANCELLED')

    def _post_to_owner_email_invoice(self):
        from apps.saas.views import owner_email_invoice

        factory = RequestFactory()
        req = factory.post('/', data={'email': 'customer183@example.com'})
        req.user = self.user
        req.tenant = self.tenant
        req.session = SessionStore()
        req._messages = FallbackStorage(req)
        return owner_email_invoice(req, self.invoice.id)

    def test_cancelled_invoice_redirects_with_error(self):
        """Cancelled invoice → redirect back to detail with error message."""
        response = self._post_to_owner_email_invoice()
        # Should redirect (302) not crash or send email
        self.assertEqual(response.status_code, 302)

    def test_cancelled_invoice_email_not_sent_via_owner_view(self):
        """Email service must NOT be called when invoice is CANCELLED."""
        with patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email') as mock_send:
            self._post_to_owner_email_invoice()

        mock_send.assert_not_called()

    def test_cancelled_invoice_status_unchanged_via_owner_view(self):
        """Invoice status must not change after blocked owner email attempt."""
        self._post_to_owner_email_invoice()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'CANCELLED')
