"""
CODE-155: Regression tests — billing API record_payment missing overpayment guard.

Bug: The API endpoint POST /billing/invoices/<id>/record-payment/ in
`apps/billing/views.py` → `record_payment()` had no validation against
overpayment, no status guard (PAID/CANCELLED), and no SELECT FOR UPDATE lock.

Contrast with the UI endpoint `apps/saas/views.py` → `owner_record_payment()`
which had all three since CODE-056.

Impact:
- A shop owner using the API could record a $10,000 payment on a $50 invoice.
  `amount_paid` would exceed `total`, making the invoice show negative balance.
- Two concurrent API requests could both pass the amount_due check and together
  overpay by the full amount.
- Paying a PAID or CANCELLED invoice would silently succeed.

Fix: Added amount > 0 guard, status guard (PAID/CANCELLED), and
SELECT FOR UPDATE + overpayment check inside a transaction — exactly mirroring
the pattern in `owner_record_payment`.

Tests:
1. Overpayment attempt is rejected with 400 and an error message.
2. $0 payment attempt rejected.
3. Negative amount rejected.
4. Invalid (non-numeric) amount rejected.
5. Paying a PAID invoice rejected.
6. Paying a CANCELLED invoice rejected.
7. Valid partial payment succeeds and updates invoice correctly.
8. Valid full payment succeeds and marks invoice PAID.
9. Missing 'amount' field rejected.
"""

import json
import uuid
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import BillingConfig, Invoice, Payment
from core.models import Customer


# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

TEST_OVERRIDES = {
    'DEFAULT_FROM_EMAIL': 'test@example.com',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:8]


def _make_tenant(name=None):
    slug = _uid()
    name = name or f'Shop {slug}'
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name='Test Plan',
        defaults={
            'slug': 'test-plan',
            'stripe_price_id': 'price_test',
            'monthly_price': Decimal('0.00'),
            'annual_price': Decimal('0.00'),
            'max_technicians': 10,
            'max_repairs_per_month': 200,
        },
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        plan=plan,
        owner=owner,
        is_active=True,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    # Ensure BillingConfig exists
    BillingConfig.get_for_tenant(tenant)
    return tenant, owner


def _make_customer(tenant):
    return Customer.objects.create(
        tenant=tenant,
        name='Test Fleet',
        email='fleet@example.com',
    )


def _make_invoice(tenant, customer, total, status='SENT', amount_paid=Decimal('0.00')):
    slug = _uid()
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-{slug}',
        invoice_date='2026-01-01',
        due_date='2026-02-01',
        total=total,
        subtotal=total,
        amount_paid=amount_paid,
        status=status,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class APIRecordPaymentOverpaymentTests(TestCase):
    """Test the billing API record_payment endpoint for overpayment guards."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Overpayment Test Shop')
        self.client = Client()
        self.client.force_login(self.owner)
        self.customer = _make_customer(self.tenant)
        # Invoice for $100, $0 paid
        self.invoice = _make_invoice(self.tenant, self.customer, Decimal('100.00'))

    def _post(self, invoice_id, payload):
        return self.client.post(
            f'/api/billing/invoices/{invoice_id}/payment/',
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_overpayment_rejected(self):
        """Paying more than amount_due (e.g. $150 on $100 invoice) should return 400."""
        resp = self._post(self.invoice.id, {'amount': '150.00', 'payment_method': 'CHECK'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)
        self.assertIn('exceeds', data['error'].lower())
        # Invoice should be unchanged
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'SENT')

    def test_zero_amount_rejected(self):
        """$0 payment should be rejected."""
        resp = self._post(self.invoice.id, {'amount': '0', 'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_negative_amount_rejected(self):
        """Negative payment should be rejected."""
        resp = self._post(self.invoice.id, {'amount': '-50', 'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_invalid_amount_rejected(self):
        """Non-numeric amount string should be rejected cleanly."""
        resp = self._post(self.invoice.id, {'amount': 'abc', 'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_missing_amount_rejected(self):
        """Request without 'amount' key should return 400."""
        resp = self._post(self.invoice.id, {'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_paying_paid_invoice_rejected(self):
        """Cannot record payment on an already-PAID invoice."""
        paid_invoice = _make_invoice(
            self.tenant, self.customer,
            Decimal('50.00'), status='PAID', amount_paid=Decimal('50.00')
        )
        resp = self._post(paid_invoice.id, {'amount': '50.00', 'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_paying_cancelled_invoice_rejected(self):
        """Cannot record payment on a CANCELLED (voided) invoice."""
        voided = _make_invoice(
            self.tenant, self.customer,
            Decimal('75.00'), status='CANCELLED'
        )
        resp = self._post(voided.id, {'amount': '75.00', 'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_valid_partial_payment_succeeds(self):
        """A valid partial payment should succeed and update the invoice."""
        resp = self._post(self.invoice.id, {'amount': '40.00', 'payment_method': 'CHECK'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('40.00'))
        self.assertEqual(self.invoice.status, 'PARTIAL')

    def test_valid_full_payment_marks_paid(self):
        """A payment equal to the full balance should mark invoice as PAID."""
        resp = self._post(self.invoice.id, {'amount': '100.00', 'payment_method': 'CASH'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('100.00'))
        self.assertEqual(self.invoice.status, 'PAID')

    def test_overpayment_second_payment_rejected(self):
        """After a partial payment, trying to overpay remaining balance is rejected."""
        # First payment: $60
        resp1 = self._post(self.invoice.id, {'amount': '60.00', 'payment_method': 'CASH'})
        self.assertEqual(resp1.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('60.00'))

        # Second payment: $50 but only $40 remains → overpayment
        resp2 = self._post(self.invoice.id, {'amount': '50.00', 'payment_method': 'CASH'})
        self.assertEqual(resp2.status_code, 400)
        data = json.loads(resp2.content)
        self.assertIn('error', data)
        self.assertIn('exceeds', data['error'].lower())
        # Invoice still at $60 paid
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('60.00'))
