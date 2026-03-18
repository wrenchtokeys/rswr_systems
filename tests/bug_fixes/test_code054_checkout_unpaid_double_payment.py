"""
Regression tests for CODE-054: _handle_checkout_completed records payment
even when payment_status='unpaid', causing premature payment recording and
a subsequent double-payment when payment_intent.succeeded fires.

Root cause:
  Stripe sends checkout.session.completed with payment_status='unpaid' for
  async payment methods (ACH/bank transfer). When this happened:
  1. payment_intent is None → coerced to empty string '' as stripe_payment_id
  2. Payment recorded immediately (invoice prematurely marked PAID/partial)
  3. Later, payment_intent.succeeded fires with real pi_xxx id
  4. Dedup guard (filter(stripe_payment_id='pi_xxx')) doesn't match ''
  5. Second payment recorded → invoice credited twice

Fix:
  _handle_checkout_completed checks payment_status and skips recording when
  payment_status != 'paid'. The payment_intent.succeeded event handles the
  actual recording when the money clears.
"""
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User

from apps.billing.models import Invoice, Payment
from apps.billing.services.stripe_service import StripeService
from apps.customer_portal.models import Customer
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan


def _uid():
    return uuid.uuid4().hex[:8]


def _make_env():
    """Create a minimal tenant + customer + invoice for testing."""
    slug = f"code054-{_uid()}"
    plan = SubscriptionPlan.objects.create(
        name=slug, slug=slug,
        monthly_price=Decimal("49.00"),
        annual_price=Decimal("490.00"),
    )
    owner = User.objects.create_user(username=f"owner_{slug}", password="pw")
    tenant = Tenant.objects.create(
        name=f"Shop {slug}", slug=slug, owner=owner, subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role="owner", is_active=True)
    customer = Customer.objects.create(
        tenant=tenant, name=f"Customer {slug}", email=f"{slug}@example.com",
    )
    invoice = Invoice.objects.create(
        tenant=tenant, customer=customer,
        invoice_number=f"INV-{slug}",
        subtotal=Decimal("200.00"),
        tax_amount=Decimal("0.00"),
        total=Decimal("200.00"),
        amount_paid=Decimal("0.00"),
        status="SENT",
    )
    return tenant, customer, invoice


class CheckoutUnpaidNotRecordedTests(TestCase):
    """payment_status='unpaid' should NOT create a Payment record."""

    def setUp(self):
        self.tenant, self.customer, self.invoice = _make_env()
        self.svc = StripeService.__new__(StripeService)  # bypass __init__
        self.svc.enabled = True
        self.svc.webhook_secret = "whsec_test"

    def _unpaid_session(self):
        return {
            'id': f'cs_test_{_uid()}',
            'payment_status': 'unpaid',
            'amount_total': 20000,   # $200.00 in cents
            'payment_intent': None,  # None for async payment methods
            'metadata': {
                'rs_invoice_id': str(self.invoice.id),
                'rs_invoice_number': self.invoice.invoice_number,
            },
        }

    def _paid_session(self, pi_id):
        return {
            'id': f'cs_test_{_uid()}',
            'payment_status': 'paid',
            'amount_total': 20000,
            'payment_intent': pi_id,
            'metadata': {
                'rs_invoice_id': str(self.invoice.id),
                'rs_invoice_number': self.invoice.invoice_number,
            },
        }

    def test_unpaid_session_does_not_create_payment(self):
        """checkout.session.completed with payment_status='unpaid' → no Payment created."""
        before = Payment.objects.filter(invoice=self.invoice).count()
        result = self.svc._handle_checkout_completed(self._unpaid_session())
        after = Payment.objects.filter(invoice=self.invoice).count()

        self.assertTrue(result['success'], result)
        self.assertFalse(result.get('handled'), "should signal not-yet-handled")
        self.assertTrue(result.get('deferred'), "should mark as deferred")
        self.assertEqual(after, before, "No Payment row should be created for unpaid session")

    def test_unpaid_session_does_not_change_invoice_status(self):
        """Invoice must stay SENT (not prematurely PAID) after unpaid checkout event."""
        self.svc._handle_checkout_completed(self._unpaid_session())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT', "Invoice must not be marked paid prematurely")
        self.assertEqual(self.invoice.amount_paid, Decimal("0.00"))

    def test_paid_session_does_create_payment(self):
        """checkout.session.completed with payment_status='paid' → Payment IS created."""
        pi_id = f"pi_{_uid()}"
        result = self.svc._handle_checkout_completed(self._paid_session(pi_id))
        payments = Payment.objects.filter(invoice=self.invoice)

        self.assertTrue(result['success'], result)
        self.assertEqual(payments.count(), 1, "One Payment should be created for paid session")
        self.assertEqual(payments.first().stripe_payment_id, pi_id)
        self.assertEqual(payments.first().amount, Decimal("200.00"))

    def test_no_double_payment_unpaid_then_succeeded(self):
        """
        Simulate the full double-payment scenario:
          1. checkout.session.completed arrives with payment_status='unpaid'
          2. payment_intent.succeeded arrives later with real pi_xxx

        Before the fix: step 1 recorded a payment with stripe_payment_id=''.
        Step 2 tried to record again with stripe_payment_id='pi_xxx',
        dedup check didn't match '', so both payments were saved → $400 total.

        After the fix: step 1 is ignored, step 2 records exactly once → $200 total.
        """
        pi_id = f"pi_{_uid()}"

        # Step 1: unpaid checkout completed (should be skipped)
        self.svc._handle_checkout_completed(self._unpaid_session())

        # Step 2: payment_intent.succeeded (should record exactly once)
        payment_intent = {
            'id': pi_id,
            'amount_received': 20000,
            'metadata': {
                'rs_invoice_id': str(self.invoice.id),
            },
        }
        result = self.svc._handle_payment_succeeded(payment_intent)

        self.assertTrue(result['success'], result)

        payments = Payment.objects.filter(invoice=self.invoice)
        self.assertEqual(payments.count(), 1, "Exactly one Payment should exist — no double-billing")
        self.assertEqual(payments.first().amount, Decimal("200.00"))

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("200.00"))

    def test_no_payment_intent_none_recorded_with_empty_id(self):
        """
        Specifically guard against the empty-string stripe_payment_id trap.
        No payment with stripe_payment_id='' should ever be created.
        """
        self.svc._handle_checkout_completed(self._unpaid_session())
        blank_id_payments = Payment.objects.filter(stripe_payment_id='')
        self.assertEqual(
            blank_id_payments.count(), 0,
            "No payment with blank stripe_payment_id should ever be created from an unpaid session"
        )

    def test_no_payment_required_session_not_recorded(self):
        """payment_status='no_payment_required' (free trial / coupon) should also be skipped."""
        session = self._unpaid_session()
        session['payment_status'] = 'no_payment_required'
        result = self.svc._handle_checkout_completed(session)
        payments = Payment.objects.filter(invoice=self.invoice)
        self.assertTrue(result['success'])
        self.assertEqual(payments.count(), 0)

    def test_missing_invoice_id_handled_gracefully(self):
        """Sessions with no rs_invoice_id in metadata should return handled=False without error."""
        session = self._paid_session(f"pi_{_uid()}")
        session['metadata'] = {}  # No invoice id
        result = self.svc._handle_checkout_completed(session)
        self.assertTrue(result['success'])
        self.assertFalse(result.get('handled'))

    def test_dedup_guard_still_works_for_paid_sessions(self):
        """Duplicate checkout.session.completed with same payment_intent → only one Payment."""
        pi_id = f"pi_{_uid()}"
        self.svc._handle_checkout_completed(self._paid_session(pi_id))
        self.svc._handle_checkout_completed(self._paid_session(pi_id))  # duplicate

        payments = Payment.objects.filter(invoice=self.invoice)
        self.assertEqual(payments.count(), 1, "Dedup guard must still work for paid sessions")
