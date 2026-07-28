"""
Regression tests for CODE-069:
  PlatformFeeRecord.fee_percent always recorded as 0.00 when payment went
  through ConnectService.create_connected_checkout_session().

Root cause:
    In _handle_payment_succeeded (stripe_service.py), the fee_percent
    derivation was gated on metadata.get('rs_fee_cents') being present:

        fee_cents_meta = metadata.get('rs_fee_cents')
        if fee_cents_meta and amount > 0:
            fee_percent = (application_fee_amount / (amount * 100) * 100)
        else:
            fee_percent = Decimal('0.00')

    BUT ConnectService.create_connected_checkout_session() stores
    'rs_fee_percent' in metadata (not 'rs_fee_cents').  Only the
    module-level create_direct_charge_session() uses 'rs_fee_cents'.

    Result: every payment via the class-method path (which is the one used
    by customer_invoice_pay) recorded fee_percent=0.00 in the audit
    record, even though the actual application_fee_amount was collected
    correctly.

Fix (CODE-069):
    Remove the metadata-key gate entirely. application_fee_amount (cents)
    and amount (dollars) are always available when we reach this code path.
    Derive fee_percent directly:
        fee_percent = application_fee_amount / amount   (algebra: cents/dollars*100 / 100)
    This is correct regardless of which checkout helper created the session.

Tests verify:
1. When payment_intent has rs_fee_percent metadata (class-method path),
   PlatformFeeRecord.fee_percent is computed correctly (not 0.00).
2. When payment_intent has rs_fee_cents metadata (module-level path),
   PlatformFeeRecord.fee_percent is still computed correctly.
3. When NEITHER key is present in metadata (e.g. future path),
   fee_percent is still computed correctly from raw amounts.
4. When amount is 0, fee_percent is safely 0.00 (no ZeroDivisionError).
5. Duplicate payment_intent_id is not recorded twice.
6. No application_fee_amount → no PlatformFeeRecord created.
7. Fee calculation: 2.5% on $100 gives fee_amount=2.50, fee_percent=2.50.
8. Fee calculation: 1% on $57.30 → fee_amount=0.57, fee_percent~0.99.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User

from apps.billing.models import Invoice, PlatformFeeRecord
from apps.billing.services.stripe_service import StripeService
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer


def _make_payment_intent(
    invoice_id,
    amount_received_cents,
    application_fee_amount=None,
    metadata_extra=None,
):
    """Build a minimal mock PaymentIntent dict for the webhook handler."""
    meta = {
        'rs_invoice_id': str(invoice_id),
    }
    if metadata_extra:
        meta.update(metadata_extra)

    pi = {
        'id': 'pi_test_12345',
        'amount_received': amount_received_cents,
        'metadata': meta,
    }
    if application_fee_amount is not None:
        pi['application_fee_amount'] = application_fee_amount
    return pi


class PlatformFeePercentMetadataTests(TestCase):
    """CODE-069: PlatformFeeRecord.fee_percent computed from raw amounts, not metadata keys."""

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'monthly_price': Decimal('0.00'),
                'trial_days': 30,
            },
        )
        self.owner = User.objects.create_user(
            username='testshop-owner',
            password='testpass123',
            email='owner@testshop.com',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop',
            subdomain='test-shop',
            owner=self.owner,
            subscription_plan=plan,
            plan='trial',
            subscription_status='trialing',
            stripe_connect_account_id='acct_testshop',
            stripe_onboarding_status='active',
            stripe_connect_charges_enabled=True,
            stripe_connect_payouts_enabled=True,
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner'
        )
        self.customer = Customer.objects.create(
            name='Fleet Co',
            tenant=self.tenant,
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-001',
            status='SENT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
        )

    def _call_handle_payment_succeeded(self, pi_dict):
        """Call the private handler via StripeService.

        event_account mirrors the Connect event's top-level 'account' field —
        it must match the tenant's Connect account or the payment is refused
        (account-mismatch guard added in the multi-shop hardening pass).
        """
        svc = StripeService()
        return svc._handle_payment_succeeded(
            pi_dict, event_account=self.tenant.stripe_connect_account_id
        )

    # ------------------------------------------------------------------ #
    # 1. rs_fee_percent metadata (ConnectService class-method path)
    # ------------------------------------------------------------------ #
    def test_fee_percent_computed_when_rs_fee_percent_in_metadata(self):
        """fee_percent should be 2.50 when application_fee_amount=250, amount=$100."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=10000,  # $100.00
            application_fee_amount=250,   # $2.50 → 2.5%
            metadata_extra={'rs_fee_percent': '2.50'},  # class-method stores this
        )
        self._call_handle_payment_succeeded(pi)

        record = PlatformFeeRecord.objects.get(payment_intent_id='pi_test_12345')
        self.assertEqual(record.fee_amount, Decimal('2.50'))
        self.assertEqual(record.fee_percent, Decimal('2.50'))

    # ------------------------------------------------------------------ #
    # 2. rs_fee_cents metadata (module-level path)
    # ------------------------------------------------------------------ #
    def test_fee_percent_computed_when_rs_fee_cents_in_metadata(self):
        """fee_percent should be 2.50 when application_fee_amount=250, amount=$100."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=10000,
            application_fee_amount=250,
            metadata_extra={'rs_fee_cents': '250'},  # module-level helper stores this
        )
        self._call_handle_payment_succeeded(pi)

        record = PlatformFeeRecord.objects.get(payment_intent_id='pi_test_12345')
        self.assertEqual(record.fee_amount, Decimal('2.50'))
        self.assertEqual(record.fee_percent, Decimal('2.50'))

    # ------------------------------------------------------------------ #
    # 3. No metadata keys — still derives correctly from raw amounts
    # ------------------------------------------------------------------ #
    def test_fee_percent_computed_without_any_fee_metadata_key(self):
        """fee_percent derived from raw amounts regardless of metadata."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=10000,
            application_fee_amount=250,
            # No rs_fee_percent, no rs_fee_cents
        )
        self._call_handle_payment_succeeded(pi)

        record = PlatformFeeRecord.objects.get(payment_intent_id='pi_test_12345')
        self.assertEqual(record.fee_amount, Decimal('2.50'))
        self.assertEqual(record.fee_percent, Decimal('2.50'))

    # ------------------------------------------------------------------ #
    # 4. amount=0 → no ZeroDivisionError, fee_percent=0.00
    # ------------------------------------------------------------------ #
    def test_fee_percent_zero_when_amount_is_zero(self):
        """Should not raise ZeroDivisionError when amount_received=0."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=0,
            application_fee_amount=0,
        )
        # Should complete without error (application_fee_amount=0 so no record created)
        result = self._call_handle_payment_succeeded(pi)
        self.assertFalse(PlatformFeeRecord.objects.filter(payment_intent_id='pi_test_12345').exists())

    # ------------------------------------------------------------------ #
    # 5. Duplicate payment_intent_id not recorded twice
    # ------------------------------------------------------------------ #
    def test_duplicate_payment_intent_not_double_recorded(self):
        """Second call with same payment_intent_id creates only one record."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=10000,
            application_fee_amount=250,
        )
        self._call_handle_payment_succeeded(pi)
        self._call_handle_payment_succeeded(pi)  # second call

        self.assertEqual(
            PlatformFeeRecord.objects.filter(payment_intent_id='pi_test_12345').count(),
            1,
        )

    # ------------------------------------------------------------------ #
    # 6. No application_fee_amount → no PlatformFeeRecord
    # ------------------------------------------------------------------ #
    def test_no_fee_record_when_no_application_fee(self):
        """If no application_fee_amount, no PlatformFeeRecord should be created."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=10000,
            application_fee_amount=None,
        )
        self._call_handle_payment_succeeded(pi)

        self.assertFalse(PlatformFeeRecord.objects.filter(payment_intent_id='pi_test_12345').exists())

    # ------------------------------------------------------------------ #
    # 7. Exact math: 2.5% on $100
    # ------------------------------------------------------------------ #
    def test_fee_math_2_5_percent_on_100_dollars(self):
        """2.5% of $100 → fee_amount=$2.50, fee_percent=2.50."""
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=10000,
            application_fee_amount=250,
        )
        self._call_handle_payment_succeeded(pi)

        record = PlatformFeeRecord.objects.get(payment_intent_id='pi_test_12345')
        self.assertEqual(record.gross_amount, Decimal('100.00'))
        self.assertEqual(record.fee_amount, Decimal('2.50'))
        self.assertEqual(record.fee_percent, Decimal('2.50'))

    # ------------------------------------------------------------------ #
    # 8. 1% on $57.30 → fee_amount=$0.57, fee_percent≈0.99
    #    (Stripe rounds down fee_cents to 57, so percent is slightly under 1%)
    # ------------------------------------------------------------------ #
    def test_fee_math_1_percent_on_57_dollars(self):
        """
        1% of $57.30 = $0.573 → Stripe truncates to $0.57 (57 cents).
        fee_percent from raw amounts: 57 / 5730 * 100 ≈ 0.99%.
        Verifies that we use actual collected fee, not the requested percent.
        """
        pi = _make_payment_intent(
            invoice_id=self.invoice.id,
            amount_received_cents=5730,
            application_fee_amount=57,   # Stripe's truncated fee
        )
        self._call_handle_payment_succeeded(pi)

        record = PlatformFeeRecord.objects.get(payment_intent_id='pi_test_12345')
        self.assertEqual(record.gross_amount, Decimal('57.30'))
        self.assertEqual(record.fee_amount, Decimal('0.57'))
        # fee_percent = 57 / 57.30 = 0.9947... → rounds to 0.99
        self.assertEqual(record.fee_percent, Decimal('0.99'))
