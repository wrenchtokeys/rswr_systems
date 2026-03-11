"""
Core Model Tests — Customer, Tenant, SubscriptionPlan, TenantMembership

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan, InviteToken
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


@override_settings(**TEST_OVERRIDES)
class CustomerModelTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('own', 'o@t.com', 'p')
        self.tenant = Tenant.objects.create(
            name='Shop', slug='shop', subdomain='shop',
            owner=self.user, subscription_plan=self.plan,
        )

    def test_create_fleet_customer(self):
        c = Customer.objects.create(
            tenant=self.tenant, name='EOS Trucking',
            customer_type='FLEET', email='eos@test.com',
        )
        self.assertEqual(c.customer_type, 'FLEET')
        self.assertEqual(str(c), 'EOS Trucking')

    def test_create_retail_customer(self):
        c = Customer.objects.create(
            tenant=self.tenant, name='John Smith',
            customer_type='RETAIL',
        )
        self.assertEqual(c.customer_type, 'RETAIL')

    def test_name_stripped(self):
        c = Customer.objects.create(
            tenant=self.tenant, name='  Penske  ',
        )
        self.assertEqual(c.name, 'Penske')

    def test_default_type_fleet(self):
        c = Customer.objects.create(tenant=self.tenant, name='Default Co')
        self.assertEqual(c.customer_type, 'FLEET')

    def test_tax_exempt_default_false(self):
        c = Customer.objects.create(tenant=self.tenant, name='TaxCo')
        self.assertFalse(c.tax_exempt)

    def test_progressive_pricing_default_true(self):
        c = Customer.objects.create(tenant=self.tenant, name='PriceCo')
        self.assertTrue(c.use_progressive_pricing)


@override_settings(**TEST_OVERRIDES)
class TenantModelTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('own', 'o@t.com', 'p')

    def test_auto_slug(self):
        t = Tenant.objects.create(
            name='My Glass Shop', owner=self.user,
            subscription_plan=self.plan,
        )
        self.assertEqual(t.slug, 'my-glass-shop')
        self.assertEqual(t.subdomain, 'my-glass-shop')

    def test_trial_expired(self):
        t = Tenant.objects.create(
            name='Expired', slug='expired', subdomain='expired',
            owner=self.user, subscription_plan=self.plan,
            plan='trial',
            trial_started_at=timezone.now() - timedelta(days=31),
        )
        self.assertTrue(t.is_trial_expired)

    def test_trial_not_expired(self):
        t = Tenant.objects.create(
            name='Fresh', slug='fresh', subdomain='fresh',
            owner=self.user, subscription_plan=self.plan,
            plan='trial',
            trial_started_at=timezone.now() - timedelta(days=5),
        )
        self.assertFalse(t.is_trial_expired)

    def test_trial_days_remaining(self):
        t = Tenant.objects.create(
            name='Remaining', slug='remaining', subdomain='remaining',
            owner=self.user, subscription_plan=self.plan,
            plan='trial',
            trial_started_at=timezone.now() - timedelta(days=20),
        )
        self.assertGreater(t.trial_days_remaining, 0)
        self.assertLessEqual(t.trial_days_remaining, 10)

    def test_not_trial_no_remaining(self):
        t = Tenant.objects.create(
            name='Pro', slug='pro', subdomain='pro',
            owner=self.user, subscription_plan=self.plan,
            plan='starter',
        )
        self.assertEqual(t.trial_days_remaining, 0)

    def test_default_pricing(self):
        t = Tenant.objects.create(
            name='Prices', slug='prices', subdomain='prices',
            owner=self.user, subscription_plan=self.plan,
        )
        self.assertEqual(t.repair_price_1, Decimal('50.00'))
        self.assertEqual(t.repair_price_5_plus, Decimal('25.00'))

    def test_upload_prefix(self):
        t = Tenant.objects.create(
            name='Upload', slug='upload-shop', subdomain='upload-shop',
            owner=self.user, subscription_plan=self.plan,
        )
        self.assertEqual(t.get_upload_prefix(), 'tenants/upload-shop')


@override_settings(**TEST_OVERRIDES)
class SubscriptionPlanTests(TestCase):

    def test_is_free(self):
        plan = SubscriptionPlan.objects.create(
            name='Free', slug='free', monthly_price=Decimal('0.00'),
        )
        self.assertTrue(plan.is_free)

    def test_not_free(self):
        plan = SubscriptionPlan.objects.create(
            name='Pro', slug='pro-test-paid', monthly_price=Decimal('99.00'),
        )
        self.assertFalse(plan.is_free)

    def test_has_feature(self):
        plan = SubscriptionPlan.objects.create(
            name='Full', slug='full', monthly_price=Decimal('99.00'),
            features={'invoicing': True, 'api_access': False},
        )
        self.assertTrue(plan.has_feature('invoicing'))
        self.assertFalse(plan.has_feature('api_access'))
        self.assertFalse(plan.has_feature('nonexistent'))


@override_settings(**TEST_OVERRIDES)
class TenantMembershipTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('member', 'm@t.com', 'p')
        self.tenant = Tenant.objects.create(
            name='MShop', slug='mshop', subdomain='mshop',
            owner=self.user, subscription_plan=self.plan,
        )

    def test_create_membership(self):
        m = TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner',
        )
        self.assertEqual(str(m), f'{self.user.username} — MShop (Owner)')

    def test_unique_membership(self):
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner',
        )
        with self.assertRaises(Exception):
            TenantMembership.objects.create(
                tenant=self.tenant, user=self.user, role='technician',
            )

    def test_user_multiple_tenants(self):
        """User can belong to multiple tenants."""
        tenant2 = Tenant.objects.create(
            name='Shop2', slug='shop2', subdomain='shop2',
            owner=self.user, subscription_plan=self.plan,
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, role='owner')
        TenantMembership.objects.create(tenant=tenant2, user=self.user, role='technician')
        self.assertEqual(self.user.tenant_memberships.count(), 2)


@override_settings(**TEST_OVERRIDES)
class InviteTokenTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.owner = User.objects.create_user('invowner', 'io@t.com', 'p')
        self.tenant = Tenant.objects.create(
            name='InvShop', slug='invshop', subdomain='invshop',
            owner=self.owner, subscription_plan=self.plan,
        )
        self.invitee = User.objects.create_user('invitee', 'inv@t.com', 'p')

    def test_token_valid(self):
        token = InviteToken.objects.create(
            tenant=self.tenant, user=self.invitee, role='technician',
            invited_by=self.owner,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.assertTrue(token.is_valid)

    def test_token_expired(self):
        token = InviteToken.objects.create(
            tenant=self.tenant, user=self.invitee, role='technician',
            invited_by=self.owner,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(token.is_valid)

    def test_token_used(self):
        token = InviteToken.objects.create(
            tenant=self.tenant, user=self.invitee, role='technician',
            invited_by=self.owner,
            expires_at=timezone.now() + timedelta(days=7),
            used_at=timezone.now(),
        )
        self.assertFalse(token.is_valid)
