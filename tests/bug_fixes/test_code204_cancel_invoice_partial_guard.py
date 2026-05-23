"""
CODE-204: cancel_invoice() API endpoint missing PARTIAL and CANCELLED guards.

Root cause:
    The billing API endpoint POST /billing/invoices/<id>/cancel/ only blocked
    cancellation of PAID invoices.  It did NOT block:

    1. PARTIAL invoices — these have Payment records pointing at them via an
       on_delete=PROTECT FK.  Setting status='CANCELLED' on a PARTIAL invoice
       leaves those Payment rows intact.  The invoice:
         (a) can never be deleted (PROTECT FK prevents it)
         (b) shows amount_paid > 0 on a cancelled invoice (misleading financials)
       Same orphaned-payment problem fixed for the UI path in CODE-123.

    2. CANCELLED invoices — calling cancel() again is a no-op status-wise but
       appends a second "[Cancelled]" entry to internal_notes and fires an
       unnecessary save().  Idempotent calls should be handled gracefully (return
       an informative 400, not silently re-save).

The UI path (owner_invoice_void in saas/views.py) already had both guards
from CODE-123.  This bug only existed in the API endpoint.

Fix:
    Added guards in cancel_invoice() for CANCELLED (return 400 "already
    cancelled") and PARTIAL (return 400 with payment count + instructions),
    mirroring the owner_invoice_void() pattern exactly.

Tests (8):
    1. DRAFT invoice can be cancelled via API.
    2. SENT invoice can be cancelled via API.
    3. PAID invoice is blocked (existing guard still works).
    4. PARTIAL invoice is blocked — new guard (CODE-204).
    5. ALREADY CANCELLED invoice is blocked — new guard (CODE-204).
    6. Blocking PARTIAL returns payment_count in message.
    7. OVERDUE invoice can be cancelled via API.
    8. Cancellation response includes invoice_number and status='CANCELLED'.
"""

import json

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, Payment, BillingConfig
from apps.billing.views import cancel_invoice
from core.models import Customer


def _make_cancel_request(factory, tenant, user, body=None):
    """Build a fake POST request with tenant + user attached, bypassing auth decorator."""
    req = factory.post(
        '/fake/cancel/',
        data=json.dumps(body or {}),
        content_type='application/json',
    )
    req.tenant = tenant
    req.user = user
    return req


class CancelInvoiceAPIPartialGuardTests(TestCase):
    """Regression tests for CODE-204 — cancel_invoice PARTIAL/CANCELLED guards."""

    def setUp(self):
        self.factory = RequestFactory()

        # Create tenant + owner
        self.owner = User.objects.create_user(
            username='api_cancel_owner',
            email='api.cancel.owner@example.com',
            password='testpass123',
        )
        self.tenant = Tenant.objects.create(
            name='Cancel Test Shop',
            slug='cancel-test-shop',
            owner=self.owner,
            is_active=True,
        )
        TenantMembership.objects.create(
            user=self.owner,
            tenant=self.tenant,
            role='owner',
            is_active=True,
        )

        # Create customer
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Fleet Co',
            email='fleet@test.com',
        )

    def _make_invoice(self, status, amount_paid='0.00'):
        """Helper to create an invoice in a given status."""
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=f'INV-{status}-{id(self)}-{Invoice.objects.count()}',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            status=status,
            subtotal='100.00',
            total='100.00',
            amount_paid=amount_paid,
        )
        return invoice

    def _cancel(self, invoice, reason='Test cancellation'):
        """Helper to call cancel_invoice view directly."""
        req = _make_cancel_request(
            self.factory, self.tenant, self.owner,
            body={'reason': reason},
        )
        return cancel_invoice(req, invoice.id)

    # ------------------------------------------------------------------
    # 1. DRAFT invoice can be cancelled
    # ------------------------------------------------------------------
    def test_cancel_draft_invoice_succeeds(self):
        """DRAFT invoice should be cancelable via API."""
        invoice = self._make_invoice('DRAFT')
        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

    # ------------------------------------------------------------------
    # 2. SENT invoice can be cancelled
    # ------------------------------------------------------------------
    def test_cancel_sent_invoice_succeeds(self):
        """SENT invoice should be cancelable via API."""
        invoice = self._make_invoice('SENT')
        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

    # ------------------------------------------------------------------
    # 3. OVERDUE invoice can be cancelled
    # ------------------------------------------------------------------
    def test_cancel_overdue_invoice_succeeds(self):
        """OVERDUE invoice should be cancelable via API."""
        invoice = self._make_invoice('OVERDUE')
        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

    # ------------------------------------------------------------------
    # 4. PAID invoice is blocked (existing guard)
    # ------------------------------------------------------------------
    def test_cancel_paid_invoice_blocked(self):
        """PAID invoice cannot be cancelled (existing guard)."""
        invoice = self._make_invoice('PAID', amount_paid='100.00')
        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('paid', data['error'].lower())
        # Status unchanged
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'PAID')

    # ------------------------------------------------------------------
    # 5. PARTIAL invoice is blocked — CODE-204 new guard
    # ------------------------------------------------------------------
    def test_cancel_partial_invoice_blocked(self):
        """
        PARTIAL invoice (has payments) cannot be cancelled via API.

        Before CODE-204: status was set to CANCELLED while Payment records
        remained, orphaning them (PROTECT FK prevents deletion; amount_paid
        stays non-zero on a 'cancelled' invoice).

        After CODE-204: returns 400 with instructions to remove payments first.
        """
        invoice = self._make_invoice('PARTIAL', amount_paid='50.00')
        # Create a real Payment row so invoice.payments.count() > 0
        Payment.objects.create(
            invoice=invoice,
            amount='50.00',
            payment_method='CHECK',
            payment_date=timezone.now().date(),
        )

        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('partial', data['error'].lower())

        # Invoice must NOT be cancelled — status unchanged
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'PARTIAL')

    # ------------------------------------------------------------------
    # 6. PARTIAL block returns payment count in error message
    # ------------------------------------------------------------------
    def test_cancel_partial_returns_payment_count(self):
        """Error message for PARTIAL cancellation should mention payment count."""
        invoice = self._make_invoice('PARTIAL', amount_paid='75.00')
        Payment.objects.create(
            invoice=invoice, amount='40.00',
            payment_method='CASH', payment_date=timezone.now().date(),
        )
        Payment.objects.create(
            invoice=invoice, amount='35.00',
            payment_method='CHECK', payment_date=timezone.now().date(),
        )

        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        # Message should tell the caller there are 2 payments
        self.assertIn('2', data['error'])

    # ------------------------------------------------------------------
    # 7. ALREADY CANCELLED invoice is blocked — CODE-204 new guard
    # ------------------------------------------------------------------
    def test_cancel_already_cancelled_invoice_blocked(self):
        """
        Calling cancel on an already-CANCELLED invoice should return 400
        (not silently re-save and append a second [Cancelled] note).

        Before CODE-204: invoice.cancel() was called again, updating
        internal_notes and firing an unnecessary save().

        After CODE-204: returns 400 immediately.
        """
        invoice = self._make_invoice('CANCELLED')
        original_notes = invoice.internal_notes or ''

        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('already', data['error'].lower())

        # internal_notes must NOT have been updated
        invoice.refresh_from_db()
        self.assertEqual(invoice.internal_notes or '', original_notes)

    # ------------------------------------------------------------------
    # 8. Successful cancellation response shape
    # ------------------------------------------------------------------
    def test_cancel_response_includes_invoice_number_and_status(self):
        """Successful cancel should return invoice_number and status='CANCELLED'."""
        invoice = self._make_invoice('DRAFT')
        response = self._cancel(invoice)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['invoice_number'], invoice.invoice_number)
        self.assertEqual(data['status'], 'CANCELLED')
