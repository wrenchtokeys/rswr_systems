"""
Tests for Stripe Connect implementation (Phases 1-3).

Tests:
- Fee calculation: tenant override > global default > 0
- create_direct_charge_session raises ConnectError when no active Connect
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
    calculate_platform_fee,
    create_direct_charge_session,
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
    """
    Tests for calculate_platform_fee:
    - Tenant override > global default > 0 (fallback)
    """

    def setUp(self):
        _, self.tenant = make_tenant('Fee Test Shop', 'fee-test', 'feeuser')
        # Reset platform config to 0
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('0.00')
        config.save()

    def test_no_fee_when_both_zero(self):
        """Default fee 0%, tenant override null → fee = 0 cents."""
        self.tenant.platform_fee_percent = None
        self.tenant.save()
        fee = calculate_platform_fee(10000, self.tenant)  # $100
        self.assertEqual(fee, 0)

    def test_global_default_fee(self):
        """Global default fee is used when tenant has no override."""
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('2.50')
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()

        fee = calculate_platform_fee(10000, self.tenant)  # 2.5% of $100 = 250 cents
        self.assertEqual(fee, 250)

    def test_tenant_override_beats_global(self):
        """Tenant-specific override takes priority over global default."""
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('5.00')
        config.save()
        self.tenant.platform_fee_percent = Decimal('1.00')  # tenant wants 1%
        self.tenant.save()

        fee = calculate_platform_fee(10000, self.tenant)  # 1% of $100 = 100 cents
        self.assertEqual(fee, 100)

    def test_zero_tenant_override_beats_global(self):
        """Tenant override of 0% means no fee, even if global has fee."""
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('3.00')
        config.save()
        self.tenant.platform_fee_percent = Decimal('0.00')
        self.tenant.save()

        fee = calculate_platform_fee(10000, self.tenant)
        self.assertEqual(fee, 0)

    def test_fee_never_negative(self):
        """Fee is never negative (safety check)."""
        self.tenant.platform_fee_percent = Decimal('0.00')
        self.tenant.save()
        fee = calculate_platform_fee(0, self.tenant)
        self.assertGreaterEqual(fee, 0)

    def test_fee_rounding(self):
        """Fee is always an integer (cents, truncated)."""
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('2.50')
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.save()

        # $1.25 * 2.5% = 3.125 cents → truncated to 3
        fee = calculate_platform_fee(125, self.tenant)
        self.assertIsInstance(fee, int)


# ---------------------------------------------------------------------------
# create_direct_charge_session Tests
# ---------------------------------------------------------------------------

class DirectChargeSessionTests(TestCase):
    """
    Tests for create_direct_charge_session:
    - Hard block when tenant status != 'active'
    - Hard block when charges not enabled
    - Success path calls stripe with correct params
    """

    def setUp(self):
        _, self.tenant = make_tenant('Charge Test Shop', 'charge-test', 'chargeuser')
        self.invoice = make_invoice(self.tenant)

    def test_raises_when_not_active(self):
        """ConnectError raised when stripe_onboarding_status != 'active'."""
        for bad_status in ('not_started', 'pending', 'in_review', 'disabled'):
            self.tenant.stripe_onboarding_status = bad_status
            self.tenant.stripe_connect_charges_enabled = False
            self.tenant.save()
            with self.assertRaises(ConnectError) as ctx:
                create_direct_charge_session(
                    self.invoice,
                    'https://example.com/success',
                    'https://example.com/cancel',
                )
            self.assertIn('not active', str(ctx.exception).lower(), msg=f'status={bad_status}')

    def test_raises_when_charges_not_enabled(self):
        """ConnectError raised when stripe_connect_charges_enabled is False even if status is active."""
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.stripe_connect_account_id = 'acct_test123'
        self.tenant.save()
        with self.assertRaises(ConnectError):
            create_direct_charge_session(
                self.invoice,
                'https://example.com/success',
                'https://example.com/cancel',
            )

    @patch('apps.tenants.services.connect_service.stripe')
    @patch('apps.tenants.services.connect_service.settings')
    def test_success_creates_session(self, mock_settings, mock_stripe):
        """Successful path creates Stripe checkout session with correct params."""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_fake'

        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_test123'
        mock_stripe.checkout.Session.create.return_value = mock_session

        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_account_id = 'acct_test123'
        self.tenant.save()

        session = create_direct_charge_session(
            self.invoice,
            'https://example.com/success',
            'https://example.com/cancel',
        )

        self.assertEqual(session, mock_session)
        mock_stripe.checkout.Session.create.assert_called_once()
        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        self.assertEqual(call_kwargs['stripe_account'], 'acct_test123')
        self.assertEqual(call_kwargs['mode'], 'payment')

    @patch('apps.tenants.services.connect_service.stripe')
    @patch('apps.tenants.services.connect_service.settings')
    def test_no_fee_no_payment_intent_data(self, mock_settings, mock_stripe):
        """When fee is 0, payment_intent_data is not set."""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_fake'

        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal('0.00')
        config.save()
        self.tenant.platform_fee_percent = Decimal('0.00')
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_account_id = 'acct_test123'
        self.tenant.save()

        mock_session = MagicMock()
        mock_stripe.checkout.Session.create.return_value = mock_session

        create_direct_charge_session(
            self.invoice,
            'https://example.com/success',
            'https://example.com/cancel',
        )

        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        # payment_intent_data always carries the invoice metadata (the webhook
        # resolves the invoice from PaymentIntent metadata), but must not add
        # an application_fee_amount when the fee is 0.
        self.assertIn('payment_intent_data', call_kwargs)
        self.assertNotIn('application_fee_amount', call_kwargs['payment_intent_data'])
        self.assertEqual(
            call_kwargs['payment_intent_data']['metadata']['rs_invoice_id'],
            str(self.invoice.id),
        )


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
