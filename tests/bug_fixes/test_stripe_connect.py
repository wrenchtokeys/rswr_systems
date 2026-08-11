"""
Tests for Stripe Connect multi-tenant payment routing.

Tests the ConnectService, model fields, payment routing logic,
and webhook handling without hitting the Stripe API.
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.connect_service import ConnectService, ConnectError, handle_account_updated

User = get_user_model()


class BaseConnectTestCase(TestCase):
    """Base test case with tenant setup."""

    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Test', slug='test', monthly_price=0, is_active=True
        )
        self.owner = User.objects.create_user(
            username='owner', password='test123', email='owner@testshop.com'
        )
        self.tenant = Tenant.objects.create(
            name='Test Glass Shop',
            slug='test-glass-shop',
            subscription_plan=self.plan,
            business_email='owner@testshop.com',
            owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True
        )


class TenantConnectFieldsTest(BaseConnectTestCase):
    """Test Tenant model Connect fields and properties."""

    def test_default_connect_fields(self):
        """New tenants have no Connect setup.

        platform_fee_percent is NULL, not 0.00. NULL means "use the global
        default"; a literal 0.00 means "this shop is explicitly zero-rated".
        The old assertion encoded migration 0011's `default=0` NOT NULL,
        which 0012 removed and 0026 cleared from existing rows -- that stray
        0.00 is precisely why no platform fee was ever collected.
        """
        self.assertEqual(self.tenant.stripe_connect_account_id, '')
        self.assertFalse(self.tenant.stripe_connect_onboarding_complete)
        self.assertFalse(self.tenant.stripe_connect_charges_enabled)
        self.assertFalse(self.tenant.stripe_connect_payouts_enabled)
        self.assertIsNone(self.tenant.platform_fee_percent)

    def test_can_accept_payments_false_by_default(self):
        """can_accept_payments is False without Connect setup."""
        self.assertFalse(self.tenant.can_accept_payments)

    def test_can_accept_payments_true_when_enabled(self):
        """can_accept_payments needs account id AND active status AND charges.

        The test used to set only two of the three and expect True. The
        third (onboarding_status == 'active') is deliberate: a shop that has
        not finished KYC must not be shown a Pay button, and loosening the
        property to match the test would weaken the gate that hides payment
        links for restricted accounts.
        """
        self.tenant.stripe_connect_account_id = 'acct_test123'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.save()
        self.assertTrue(self.tenant.can_accept_payments)

    def test_can_accept_payments_false_when_onboarding_incomplete(self):
        """Charges enabled but KYC unfinished is still not payable."""
        self.tenant.stripe_connect_account_id = 'acct_test123'
        self.tenant.stripe_onboarding_status = 'pending'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.save()
        self.assertFalse(self.tenant.can_accept_payments)

    def test_can_accept_payments_false_without_account_id(self):
        """can_accept_payments requires account_id even if charges_enabled."""
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.save()
        self.assertFalse(self.tenant.can_accept_payments)

    def test_can_receive_payouts(self):
        """can_receive_payouts requires both account_id and payouts_enabled."""
        self.assertFalse(self.tenant.can_receive_payouts)
        self.tenant.stripe_connect_account_id = 'acct_test123'
        self.tenant.stripe_connect_payouts_enabled = True
        self.tenant.save()
        self.assertTrue(self.tenant.can_receive_payouts)

    def test_platform_fee_percent(self):
        """Platform fee is configurable per tenant."""
        self.tenant.platform_fee_percent = Decimal('2.50')
        self.tenant.save()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.platform_fee_percent, Decimal('2.50'))


class ConnectServiceTest(BaseConnectTestCase):
    """Test ConnectService methods."""

    def test_is_enabled_with_api_key(self):
        """Service is enabled when STRIPE_SECRET_KEY is set."""
        with self.settings(STRIPE_SECRET_KEY='sk_test_xxx'):
            svc = ConnectService()
            self.assertTrue(svc.is_enabled())

    def test_is_enabled_without_api_key(self):
        """Service is disabled without STRIPE_SECRET_KEY."""
        with self.settings(STRIPE_SECRET_KEY=''):
            svc = ConnectService()
            self.assertFalse(svc.is_enabled())

    def _enable_fees(self):
        """Fees are gated on the PlatformConfig master switch."""
        from apps.billing.models import PlatformConfig
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.save()

    def test_calculate_platform_fee_zero(self):
        """No fee when platform_fee_percent is 0.

        Previously compared the returned tuple to a bare int, so it failed
        on every run regardless of the fee logic.
        """
        self._enable_fees()
        svc = ConnectService()
        self.tenant.platform_fee_percent = Decimal('0')
        fee_cents, _percent, _fixed = svc.calculate_platform_fee(
            Decimal('100.00'), self.tenant,
        )
        self.assertEqual(fee_cents, 0)

    def test_calculate_platform_fee_percentage(self):
        """Fee calculated correctly from percentage."""
        self._enable_fees()
        svc = ConnectService()
        self.tenant.platform_fee_percent = Decimal('2.50')
        # $100 * 2.5% = $2.50 = 250 cents
        fee_cents, _percent, _fixed = svc.calculate_platform_fee(
            Decimal('100.00'), self.tenant,
        )
        self.assertEqual(fee_cents, 250)

    def test_calculate_platform_fee_rounds_down(self):
        """Fee converts to cents (int truncation)."""
        self._enable_fees()
        svc = ConnectService()
        self.tenant.platform_fee_percent = Decimal('3.00')
        # $33.33 * 3% = $0.9999 = 99 cents (int truncation)
        fee_cents, _percent, _fixed = svc.calculate_platform_fee(
            Decimal('33.33'), self.tenant,
        )
        self.assertEqual(fee_cents, 99)

    @patch('apps.tenants.services.connect_service.stripe')
    def test_create_connect_account(self, mock_stripe):
        """Creates Express account and returns onboarding URL."""
        mock_stripe.Account.create.return_value = MagicMock(id='acct_new123')
        mock_stripe.AccountLink.create.return_value = MagicMock(
            url='https://connect.stripe.com/setup/e/xxx'
        )

        with self.settings(STRIPE_SECRET_KEY='sk_test_xxx'):
            svc = ConnectService()
            url = svc.create_connect_account(
                self.tenant,
                'https://rssystems.io/return/',
                'https://rssystems.io/refresh/'
            )

        self.assertEqual(url, 'https://connect.stripe.com/setup/e/xxx')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_connect_account_id, 'acct_new123')

    @patch('apps.tenants.services.connect_service.stripe')
    def test_create_connect_account_existing(self, mock_stripe):
        """Reuses existing account ID for onboarding link."""
        self.tenant.stripe_connect_account_id = 'acct_existing'
        self.tenant.save()

        mock_stripe.AccountLink.create.return_value = MagicMock(
            url='https://connect.stripe.com/setup/e/yyy'
        )

        with self.settings(STRIPE_SECRET_KEY='sk_test_xxx'):
            svc = ConnectService()
            url = svc.create_connect_account(
                self.tenant,
                'https://rssystems.io/return/',
                'https://rssystems.io/refresh/'
            )

        # Should NOT create a new account
        mock_stripe.Account.create.assert_not_called()
        self.assertEqual(url, 'https://connect.stripe.com/setup/e/yyy')

    @patch('apps.tenants.services.connect_service.stripe')
    def test_sync_account_status(self, mock_stripe):
        """Syncs charges/payouts/onboarding status from Stripe."""
        self.tenant.stripe_connect_account_id = 'acct_test'
        self.tenant.save()

        mock_account = MagicMock()
        mock_account.charges_enabled = True
        mock_account.payouts_enabled = True
        mock_account.details_submitted = True
        mock_account.requirements.currently_due = []
        mock_account.requirements.eventually_due = []
        mock_account.requirements.past_due = []
        mock_account.requirements.disabled_reason = None
        mock_stripe.Account.retrieve.return_value = mock_account

        with self.settings(STRIPE_SECRET_KEY='sk_test_xxx'):
            svc = ConnectService()
            status = svc.sync_account_status(self.tenant)

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.stripe_connect_charges_enabled)
        self.assertTrue(self.tenant.stripe_connect_payouts_enabled)
        self.assertTrue(self.tenant.stripe_connect_onboarding_complete)
        self.assertTrue(status['charges_enabled'])

    def test_create_connect_account_disabled(self):
        """Raises ConnectError when Stripe is not configured."""
        with self.settings(STRIPE_SECRET_KEY=''):
            svc = ConnectService()
            with self.assertRaises(ConnectError):
                svc.create_connect_account(self.tenant, 'http://x', 'http://y')


class AccountUpdatedWebhookTest(BaseConnectTestCase):
    """Test account.updated webhook handler."""

    @patch('apps.tenants.services.connect_service.ConnectService.sync_account_status')
    def test_handle_known_account(self, mock_sync):
        """Syncs status for known connected accounts."""
        self.tenant.stripe_connect_account_id = 'acct_known'
        self.tenant.save()

        mock_sync.return_value = {
            'charges_enabled': True,
            'payouts_enabled': True,
        }

        result = handle_account_updated({'id': 'acct_known'})
        self.assertTrue(result['success'])
        self.assertTrue(result['handled'])
        mock_sync.assert_called_once()

    def test_handle_unknown_account(self):
        """Ignores account.updated for accounts we don't know about."""
        result = handle_account_updated({'id': 'acct_unknown'})
        self.assertTrue(result['success'])
        self.assertFalse(result['handled'])

    def test_handle_no_account_id(self):
        """Returns error for missing account ID."""
        result = handle_account_updated({})
        self.assertFalse(result['success'])
