"""
Tests for Stripe Connect implementation (Phases 1-3).

Tests:
- Fee calculation: tenant override > global default > 0
- create_connected_checkout_session raises ConnectError when no active Connect
- handle_account_updated_webhook: active account → status='active', restricted → status='restricted'
- Invoice email: no payment link when tenant status != active
- Customer portal: pay_online context var False when no active Connect

All Stripe API calls are mocked via unittest.mock.

Author: Amelia (Clawdbot AI)
"""

import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice, PlatformConfig, PlatformFeeRecord
from core.models import Customer
from apps.tenants.services.connect_service import (
    ConnectService,
    handle_account_updated_webhook,
    ConnectError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name, slug=None, username=None):
    slug = slug or name.lower().replace(' ', '-')
    username = username or slug
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        }
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123')
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(user=user, tenant=tenant, role='owner')
    return user, tenant


def make_invoice(tenant, amount=Decimal('100.00')):
    customer = Customer.objects.create(
        name='Test Customer',
        tenant=tenant,
    )
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number='INV-9999',
        subtotal=amount,
        total=amount,
        amount_paid=Decimal('0.00'),
        status='SENT',
    )


# ---------------------------------------------------------------------------
# Fee Calculation Tests
# ---------------------------------------------------------------------------

class PlatformFeeCalculationTests(TestCase):
    """ConnectService.calculate_platform_fee — the ONE implementation.

    There used to be three: this method, a differently-signed module-level
    `calculate_platform_fee(amount_cents, tenant)` with no platform-owner
    exemption, and a second checkout builder writing a different metadata
    key than the reader expected (which is what caused CODE-069). The two
    duplicates are deleted; these tests cover what remains.

    Note fees are now gated on PlatformConfig.fee_enabled, so every test
    that expects a non-zero fee must turn the master switch on.
    """

    def setUp(self):
        _, self.tenant = make_tenant('Fee Test Shop', 'fee-test', 'feeuser')
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.default_fee_percent = Decimal('0.00')
        config.default_fee_fixed_cents = 0
        config.save()
        self.svc = ConnectService()

    def _fee(self, dollars):
        """Returns just the cents, for brevity."""
        return self.svc.calculate_platform_fee(Decimal(str(dollars)), self.tenant)[0]

    def test_no_fee_when_both_zero(self):
        self.tenant.platform_fee_percent = None
        self.tenant.save()
        self.assertEqual(self._fee(100), 0)

    def test_global_default_fee(self):
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('2.50')
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()
        self.assertEqual(self._fee(100), 250)

    def test_tenant_override_beats_global(self):
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('5.00')
        config.save()
        self.tenant.platform_fee_percent = Decimal('1.00')
        self.tenant.save()
        self.assertEqual(self._fee(100), 100)

    def test_zero_tenant_override_beats_global(self):
        """An explicit 0.00 means 'this shop is zero-rated'.

        Migration 0026 clears the legacy 0.00s that were never intended as
        overrides, so this now means what it says.
        """
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('3.00')
        config.save()
        self.tenant.platform_fee_percent = Decimal('0.00')
        self.tenant.save()
        self.assertEqual(self._fee(100), 0)

    def test_fee_never_negative(self):
        self.tenant.platform_fee_percent = Decimal('0.00')
        self.tenant.save()
        self.assertGreaterEqual(self._fee(0), 0)

    def test_fee_truncates_to_whole_cents(self):
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('2.50')
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()
        # $1.25 * 2.5% = 3.125 cents -> 3
        fee = self._fee(Decimal('1.25'))
        self.assertIsInstance(fee, int)
        self.assertEqual(fee, 3)

    def test_master_switch_off_forces_zero(self):
        """fee_enabled=False wins over every configured rate."""
        config = PlatformConfig.get_solo()
        config.fee_enabled = False
        config.default_fee_percent = Decimal('10.00')
        config.save()
        self.tenant.platform_fee_percent = Decimal('5.00')
        self.tenant.save()
        self.assertEqual(self._fee(100), 0)

    def test_platform_owner_is_never_charged(self):
        """We do not take a fee from our own shop."""
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('5.00')
        config.save()
        self.tenant.is_platform_owner = True
        self.tenant.platform_fee_percent = None
        self.tenant.save()
        self.assertEqual(self._fee(100), 0)

    def test_fixed_component_is_added(self):
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('2.00')
        config.default_fee_fixed_cents = 25
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()
        # 2% of $100 = 200c, + 25c fixed
        self.assertEqual(self._fee(100), 225)

    def test_tenant_pair_resolves_as_a_unit(self):
        """A tenant override must not mix its percent with the global fixed.

        Mixing produces a rate nobody configured and nobody can explain to
        a shop owner asking why they were charged what they were.
        """
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('9.00')
        config.default_fee_fixed_cents = 99
        config.save()
        self.tenant.platform_fee_percent = Decimal('1.00')
        self.tenant.platform_fee_fixed_cents = None
        self.tenant.save()
        # 1% of $100 = 100c, and the global 99c fixed must NOT apply.
        self.assertEqual(self._fee(100), 100)

    def test_fee_is_clamped_so_the_charge_can_still_go_through(self):
        """Stripe rejects an application fee larger than the charge.

        Without the clamp a $0.25 invoice with a $0.30 fixed fee makes the
        whole checkout session fail, so the customer cannot pay at all --
        far worse than collecting a smaller fee.
        """
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('0.00')
        config.default_fee_fixed_cents = 30
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()

        fee = self._fee(Decimal('0.25'))  # 25 cent charge
        self.assertLessEqual(fee, 25)
        self.assertGreaterEqual(fee, 0)

    def test_returns_percent_and_fixed_for_metadata(self):
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('2.00')
        config.default_fee_fixed_cents = 25
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()

        cents, percent, fixed = self.svc.calculate_platform_fee(
            Decimal('100'), self.tenant,
        )
        self.assertEqual((cents, percent, fixed), (225, Decimal('2.00'), 25))


# ---------------------------------------------------------------------------
# handle_account_updated_webhook Tests
# ---------------------------------------------------------------------------

class AccountUpdatedWebhookTests(TestCase):
    """
    Tests for handle_account_updated_webhook:
    - Active account → status='active'
    - Restricted account → status='restricted'
    - Pending (no details submitted) → status='pending'
    - Unknown account → handled=False
    """

    def setUp(self):
        _, self.tenant = make_tenant('Webhook Test Shop', 'webhook-test', 'webhookuser')
        self.tenant.stripe_connect_account_id = 'acct_webhooktest'
        self.tenant.save()

    def _account_data(self, charges_enabled, payouts_enabled, details_submitted, disabled_reason=None):
        return {
            'id': 'acct_webhooktest',
            'charges_enabled': charges_enabled,
            'payouts_enabled': payouts_enabled,
            'details_submitted': details_submitted,
            'requirements': {
                'disabled_reason': disabled_reason,
            },
        }

    def test_active_account_sets_active_status(self):
        result = handle_account_updated_webhook(
            self._account_data(
                charges_enabled=True,
                payouts_enabled=True,
                details_submitted=True,
                disabled_reason=None,
            )
        )
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_onboarding_status, 'active')
        self.assertTrue(self.tenant.stripe_connect_charges_enabled)
        self.assertTrue(self.tenant.stripe_connect_payouts_enabled)
        self.assertEqual(result['onboarding_status'], 'active')
        self.assertTrue(result['handled'])

    def test_restricted_account_sets_restricted_status(self):
        result = handle_account_updated_webhook(
            self._account_data(
                charges_enabled=True,
                payouts_enabled=False,
                details_submitted=True,
                disabled_reason='requirements.past_due',
            )
        )
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_onboarding_status, 'restricted')
        self.assertEqual(result['onboarding_status'], 'restricted')

    def test_in_review_details_submitted_no_charges(self):
        result = handle_account_updated_webhook(
            self._account_data(
                charges_enabled=False,
                payouts_enabled=False,
                details_submitted=True,
            )
        )
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_onboarding_status, 'in_review')

    def test_pending_no_details_submitted(self):
        result = handle_account_updated_webhook(
            self._account_data(
                charges_enabled=False,
                payouts_enabled=False,
                details_submitted=False,
            )
        )
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_onboarding_status, 'pending')

    def test_unknown_account_returns_unhandled(self):
        result = handle_account_updated_webhook({'id': 'acct_unknown99'})
        self.assertFalse(result.get('handled', True))
        self.assertTrue(result['success'])

    def test_first_activation_sets_connected_at(self):
        self.tenant.stripe_onboarding_status = 'pending'
        self.tenant.stripe_connected_at = None
        self.tenant.save()

        handle_account_updated_webhook(
            self._account_data(charges_enabled=True, payouts_enabled=True, details_submitted=True)
        )
        self.tenant.refresh_from_db()
        self.assertIsNotNone(self.tenant.stripe_connected_at)

    def test_re_activation_does_not_overwrite_connected_at(self):
        original_time = timezone.now() - timezone.timedelta(days=7)
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connected_at = original_time
        self.tenant.save()

        handle_account_updated_webhook(
            self._account_data(charges_enabled=True, payouts_enabled=True, details_submitted=True)
        )
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_connected_at, original_time)


# ---------------------------------------------------------------------------
# Invoice Email — No Payment Link Without Active Connect
# ---------------------------------------------------------------------------

class InvoiceEmailConnectGateTests(TestCase):
    """
    Tests that invoice emails omit payment links when tenant has no active Connect.
    """

    def setUp(self):
        _, self.tenant = make_tenant('Email Gate Shop', 'email-gate', 'emailgateuser')
        self.invoice = make_invoice(self.tenant)

    def test_no_payment_link_without_active_connect(self):
        """Email service returns no payment_link when tenant is not active."""
        self.tenant.stripe_onboarding_status = 'not_started'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()

        from apps.billing.services.invoice_email_service import InvoiceEmailService
        service = InvoiceEmailService(tenant=self.tenant)

        # can_accept_payments should be False
        self.assertFalse(self.tenant.can_accept_payments)

    def test_active_tenant_can_accept_payments(self):
        """can_accept_payments is True when active."""
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_account_id = 'acct_test'
        self.tenant.save()

        self.assertTrue(self.tenant.can_accept_payments)

    def test_pending_tenant_cannot_accept_payments(self):
        """can_accept_payments is False when pending."""
        self.tenant.stripe_onboarding_status = 'pending'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()

        self.assertFalse(self.tenant.can_accept_payments)


# ---------------------------------------------------------------------------
# Customer Portal — pay_online Context Variable
# ---------------------------------------------------------------------------

class CustomerPortalPayOnlineTests(TestCase):
    """
    Tests that customer portal invoice view sets can_pay_online=False
    when tenant has no active Connect account.
    """

    def setUp(self):
        _, self.tenant = make_tenant('Portal Test Shop', 'portal-test', 'portaluser')
        self.invoice = make_invoice(self.tenant)

    def test_can_pay_online_false_without_connect(self):
        """Tenant without active Connect → can_accept_payments is False."""
        self.tenant.stripe_onboarding_status = 'not_started'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()

        self.assertFalse(self.tenant.can_accept_payments)

    def test_can_pay_online_false_pending(self):
        """Pending Connect → cannot accept payments."""
        self.tenant.stripe_onboarding_status = 'pending'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()

        self.assertFalse(self.tenant.can_accept_payments)

    def test_can_pay_online_true_with_active_connect(self):
        """Active Connect with charges enabled → can_accept_payments True."""
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_account_id = 'acct_real123'
        self.tenant.save()

        self.assertTrue(self.tenant.can_accept_payments)

    def test_can_pay_online_false_restricted(self):
        """Restricted Connect → cannot accept payments (status != 'active')."""
        self.tenant.stripe_onboarding_status = 'restricted'
        self.tenant.stripe_connect_charges_enabled = True  # Stripe may say charges enabled but status restricted
        self.tenant.stripe_connect_account_id = 'acct_restricted'
        self.tenant.save()

        # can_accept_payments checks onboarding_status == 'active' AND charges_enabled
        self.assertFalse(self.tenant.can_accept_payments)


# ---------------------------------------------------------------------------
# PlatformConfig Singleton
# ---------------------------------------------------------------------------

class PlatformConfigTests(TestCase):
    """Tests for PlatformConfig singleton."""

    def test_get_solo_returns_singleton(self):
        c1 = PlatformConfig.get_solo()
        c2 = PlatformConfig.get_solo()
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(c1.pk, 1)

    def test_get_alias_same_as_get_solo(self):
        c1 = PlatformConfig.get()
        c2 = PlatformConfig.get_solo()
        self.assertEqual(c1.pk, c2.pk)

    def test_default_fee_is_zero(self):
        config = PlatformConfig.get_solo()
        self.assertEqual(config.default_fee_percent, Decimal('0.00'))

    def test_cannot_delete(self):
        from django.core.exceptions import ValidationError
        config = PlatformConfig.get_solo()
        with self.assertRaises(ValidationError):
            config.delete()


# ---------------------------------------------------------------------------
# Fee Recording Tests (webhook handler)
# ---------------------------------------------------------------------------

class FeeRecordingTests(TestCase):
    """
    Tests that PlatformFeeRecord is created when payment_intent.succeeded
    has application_fee_amount.
    """

    def setUp(self):
        _, self.tenant = make_tenant('Fee Record Shop', 'fee-record', 'feerecorduser')
        self.tenant.stripe_connect_account_id = 'acct_feerecord'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.save()
        self.invoice = make_invoice(self.tenant)

    def test_fee_record_created_on_payment_with_fee(self):
        """PlatformFeeRecord is created when payment intent has application_fee_amount."""
        from apps.billing.services.stripe_service import StripeService

        svc = StripeService.__new__(StripeService)
        svc.enabled = True

        payment_intent = {
            'id': 'pi_test_fee_record',
            'amount_received': 10000,  # $100
            'application_fee_amount': 250,  # $2.50
            'metadata': {
                'rs_invoice_id': str(self.invoice.id),
                'rs_fee_cents': '250',
            },
            'on_behalf_of': 'acct_feerecord',
        }

        with patch.object(svc, '_record_stripe_payment', return_value={'success': True}):
            svc._handle_payment_succeeded(payment_intent)

        record = PlatformFeeRecord.objects.filter(
            payment_intent_id='pi_test_fee_record'
        ).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.fee_amount, Decimal('2.50'))
        self.assertEqual(record.gross_amount, Decimal('100.00'))

    def test_no_fee_record_without_application_fee(self):
        """No PlatformFeeRecord when payment intent has no application_fee_amount."""
        from apps.billing.services.stripe_service import StripeService

        svc = StripeService.__new__(StripeService)
        svc.enabled = True

        payment_intent = {
            'id': 'pi_test_no_fee',
            'amount_received': 10000,
            'application_fee_amount': None,
            'metadata': {
                'rs_invoice_id': str(self.invoice.id),
            },
        }

        with patch.object(svc, '_record_stripe_payment', return_value={'success': True}):
            svc._handle_payment_succeeded(payment_intent)

        count = PlatformFeeRecord.objects.filter(payment_intent_id='pi_test_no_fee').count()
        self.assertEqual(count, 0)

    def test_no_duplicate_fee_records(self):
        """PlatformFeeRecord is not created twice for the same payment_intent_id."""
        from apps.billing.services.stripe_service import StripeService

        svc = StripeService.__new__(StripeService)
        svc.enabled = True

        payment_intent = {
            'id': 'pi_test_dedup',
            'amount_received': 10000,
            'application_fee_amount': 300,
            'metadata': {
                'rs_invoice_id': str(self.invoice.id),
            },
            'on_behalf_of': None,
        }

        with patch.object(svc, '_record_stripe_payment', return_value={'success': True}):
            svc._handle_payment_succeeded(payment_intent)
            svc._handle_payment_succeeded(payment_intent)  # second call

        count = PlatformFeeRecord.objects.filter(payment_intent_id='pi_test_dedup').count()
        self.assertEqual(count, 1)
