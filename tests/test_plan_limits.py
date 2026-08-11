"""
Plan limit enforcement, feature gating, and annual billing.

Four holes closed here, all of which let a shop have more than it paid for
or paid for something it did not get:

1. **A null `subscription_plan` FK meant unlimited everything.** Every check
   in UsageService returned "allowed" when the FK was None -- reachable by
   deleting a SubscriptionPlan row (it's SET_NULL) or by any tenant created
   before seed_plans ran.

2. **Batch creation overshot the monthly cap.** The gate asked "are you AT
   the cap?" and then created up to 20 rows (technician) or 50x20 (customer
   portal) in one request.

3. **Technician seat reactivation skipped the check.** Only the
   create-a-new-record branch checked the limit, so demote-then-promote
   walked straight past it, repeatably.

4. **Downgrades never reconciled existing usage**, so an Enterprise shop
   with 40 techs could drop to Starter (5) and keep all 40.

Plus: any plan change silently converted annual subscribers to monthly,
because the price written was always `stripe_price_id`.
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.usage_service import UsageService
# Real Stripe responses are StripeObjects (attribute access, and no .get()
# since 15.x dropped dict inheritance). Plain dicts would let these tests
# pass against code that breaks in production.
from tests.test_stripe_api_version_compat import StripeLike


def make_plan(slug, name, price, **limits):
    return SubscriptionPlan.objects.update_or_create(
        slug=slug,
        defaults={'name': name, 'monthly_price': Decimal(str(price)),
                  'is_active': True, **limits},
    )[0]


def make_tenant(slug='limit-shop', plan_obj=None, plan='starter'):
    owner = User.objects.create_user(
        username=f'{slug}-owner', email=f'{slug}@test.com', password='pw123!',
    )
    tenant = Tenant.objects.create(
        name='Limit Shop', slug=slug, owner=owner, plan=plan,
        subscription_plan=plan_obj, subscription_status='active',
    )
    TenantMembership.objects.create(
        tenant=tenant, user=owner, role='owner', is_active=True,
    )
    return tenant, owner


class NullPlanFallbackTests(TestCase):
    """A null FK must not mean unlimited."""

    def setUp(self):
        self.starter = make_plan(
            'starter', 'Starter', 49, max_repairs_per_month=200,
            max_technicians=5, max_customers=50,
        )
        make_plan('trial', 'Trial', 0, max_repairs_per_month=50,
                  max_technicians=2, max_customers=10, trial_days=30)

    def test_null_fk_falls_back_to_the_slug_plan(self):
        tenant, _ = make_tenant(plan_obj=None, plan='starter')
        usage = UsageService(tenant)
        self.assertIsNotNone(
            usage.plan,
            "a null subscription_plan FK used to mean unlimited everything",
        )
        self.assertEqual(usage.plan.slug, 'starter')

    def test_unknown_slug_falls_back_to_trial(self):
        tenant, _ = make_tenant(plan_obj=None, plan='nonexistent')
        self.assertEqual(UsageService(tenant).plan.slug, 'trial')

    def test_limits_actually_apply_after_the_fallback(self):
        tenant, _ = make_tenant(plan_obj=None, plan='trial')
        usage = UsageService(tenant)
        self.assertEqual(usage.remaining_repairs(), 50)


class QuantityAwareRepairLimitTests(TestCase):
    def setUp(self):
        self.plan = make_plan(
            'starter', 'Starter', 49, max_repairs_per_month=5,
            max_technicians=5, max_customers=50,
        )
        self.tenant, _ = make_tenant(plan_obj=self.plan)

    def test_remaining_repairs(self):
        self.assertEqual(UsageService(self.tenant).remaining_repairs(), 5)

    def test_batch_within_quota_is_allowed(self):
        allowed, _msg = UsageService(self.tenant).can_create_repairs(5)
        self.assertTrue(allowed)

    def test_batch_over_quota_is_rejected(self):
        """The overshoot bug: at 0/5, a 6-break batch used to sail through."""
        allowed, msg = UsageService(self.tenant).can_create_repairs(6)
        self.assertFalse(allowed)
        self.assertIn('6 jobs', msg)
        self.assertIn('5 left', msg)

    def test_rejects_rather_than_truncating(self):
        """'I entered 8 breaks, 3 saved' is worse than a clear refusal."""
        allowed, msg = UsageService(self.tenant).can_create_repairs(8)
        self.assertFalse(allowed)
        self.assertIn('Reduce the number of breaks', msg)

    def test_unlimited_plan_allows_any_quantity(self):
        unlimited = make_plan('pro', 'Pro', 99, max_repairs_per_month=None)
        self.tenant.subscription_plan = unlimited
        self.tenant.save()
        allowed, _ = UsageService(self.tenant).can_create_repairs(500)
        self.assertTrue(allowed)

    def test_platform_owner_is_exempt(self):
        self.tenant.is_platform_owner = True
        self.tenant.save()
        allowed, _ = UsageService(self.tenant).can_create_repairs(1000)
        self.assertTrue(allowed)

    def test_single_delegates_to_the_original_check(self):
        allowed, _ = UsageService(self.tenant).can_create_repairs(1)
        self.assertTrue(allowed)


class DowngradePreflightTests(TestCase):
    def setUp(self):
        self.starter = make_plan(
            'starter', 'Starter', 49, max_technicians=2, max_customers=5,
        )
        self.pro = make_plan(
            'pro', 'Pro', 99, max_technicians=15, max_customers=None,
        )
        self.tenant, self.owner = make_tenant(plan_obj=self.pro, plan='pro')

    def _add_customers(self, n):
        from core.models import Customer
        for i in range(n):
            Customer.objects.create(name=f'Cust {i}', tenant=self.tenant)

    def test_no_violations_when_within_the_smaller_plan(self):
        self.assertEqual(
            UsageService(self.tenant).check_against_plan(self.starter), [],
        )

    def test_reports_customer_overage(self):
        self._add_customers(7)
        violations = UsageService(self.tenant).check_against_plan(self.starter)
        self.assertEqual(len(violations), 1)
        self.assertIn('7 customers', violations[0])

    def test_monthly_repairs_are_deliberately_ignored(self):
        """History cannot be reduced; blocking on it would trap a busy shop
        on an expensive plan until the calendar turned over."""
        small = make_plan('tiny', 'Tiny', 9, max_repairs_per_month=0,
                          max_technicians=99, max_customers=99)
        self.assertEqual(
            UsageService(self.tenant).check_against_plan(small), [],
        )

    def test_platform_owner_never_blocked(self):
        self._add_customers(7)
        self.tenant.is_platform_owner = True
        self.tenant.save()
        self.assertEqual(
            UsageService(self.tenant).check_against_plan(self.starter), [],
        )

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_update_subscription_refuses_an_unsafe_downgrade(self):
        from apps.tenants.services.subscription_service import (
            SubscriptionError, SubscriptionService,
        )

        self._add_customers(7)
        self.starter.stripe_price_id = 'price_starter'
        self.starter.save()
        self.pro.stripe_price_id = 'price_pro'
        self.pro.save()
        self.tenant.stripe_subscription_id = 'sub_x'
        self.tenant.save()

        subscription = {
            'id': 'sub_x', 'status': 'active',
            'items': {'data': [{
                'id': 'si_x', 'current_period_end': 1767225600,
                'price': {'id': 'price_pro', 'recurring': {'interval': 'month'}},
            }]},
        }
        with patch('stripe.Subscription.retrieve',
                   return_value=StripeLike(subscription)):
            with self.assertRaises(SubscriptionError) as ctx:
                SubscriptionService().update_subscription(self.tenant, 'starter')
        self.assertIn('smaller than your current usage', str(ctx.exception))


class AnnualBillingTests(TestCase):
    def setUp(self):
        self.starter = make_plan('starter', 'Starter', 49)
        self.starter.stripe_price_id = 'price_starter_monthly'
        self.starter.stripe_annual_price_id = 'price_starter_annual'
        self.starter.save()
        self.pro = make_plan('pro', 'Pro', 99)
        self.pro.stripe_price_id = 'price_pro_monthly'
        self.pro.stripe_annual_price_id = 'price_pro_annual'
        self.pro.save()

    def test_price_id_for_interval(self):
        self.assertEqual(
            self.pro.price_id_for('month'), 'price_pro_monthly')
        self.assertEqual(
            self.pro.price_id_for('year'), 'price_pro_annual')

    def test_falls_back_to_monthly_when_no_annual_price(self):
        """Degrade to 'billed monthly' rather than sending Stripe an empty id."""
        plan = make_plan('bare', 'Bare', 19)
        plan.stripe_price_id = 'price_bare_monthly'
        plan.save()
        self.assertEqual(plan.price_id_for('year'), 'price_bare_monthly')

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_upgrade_preserves_an_annual_subscription(self):
        """The silent-conversion bug: any plan change wrote the monthly price."""
        from apps.tenants.services.subscription_service import SubscriptionService

        tenant, _ = make_tenant(plan_obj=self.starter, plan='starter')
        tenant.stripe_subscription_id = 'sub_annual'
        tenant.save()

        subscription = {
            'id': 'sub_annual', 'status': 'active',
            'items': {'data': [{
                'id': 'si_a', 'current_period_end': 1767225600,
                'price': {'id': 'price_starter_annual',
                          'recurring': {'interval': 'year'}},
            }]},
        }
        with patch('stripe.Subscription.retrieve',
                   return_value=StripeLike(subscription)), \
             patch('stripe.Subscription.modify') as mock_modify:
            SubscriptionService().update_subscription(tenant, 'pro')

        self.assertEqual(
            mock_modify.call_args.kwargs['items'][0]['price'],
            'price_pro_annual',
            "an annual subscriber must not be silently moved to monthly",
        )

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_upgrade_passes_an_idempotency_key(self):
        from apps.tenants.services.subscription_service import SubscriptionService

        tenant, _ = make_tenant(plan_obj=self.starter, plan='starter')
        tenant.stripe_subscription_id = 'sub_i'
        tenant.save()
        subscription = {
            'id': 'sub_i', 'status': 'active',
            'items': {'data': [{
                'id': 'si_i', 'current_period_end': 1767225600,
                'price': {'id': 'price_starter_monthly',
                          'recurring': {'interval': 'month'}},
            }]},
        }
        with patch('stripe.Subscription.retrieve',
                   return_value=StripeLike(subscription)), \
             patch('stripe.Subscription.modify') as mock_modify:
            SubscriptionService().update_subscription(tenant, 'pro')

        self.assertIn('idempotency_key', mock_modify.call_args.kwargs)


class FeatureGateTests(TestCase):
    def setUp(self):
        self.trial = make_plan('trial', 'Trial', 0, features={'rewards': False})
        self.starter = make_plan(
            'starter', 'Starter', 49, features={'rewards': True})

    def test_branding_reads_the_plan_feature(self):
        tenant, _ = make_tenant(plan_obj=self.trial, plan='pro')
        self.assertTrue(tenant.branding_enabled)

    def test_platform_owner_gets_everything(self):
        tenant, _ = make_tenant(plan_obj=self.trial, plan='trial')
        tenant.is_platform_owner = True
        self.assertTrue(tenant.has_feature('rewards'))

    def test_loyalty_is_not_gated_by_plan(self):
        """A trialing shop keeps the loyalty program.

        `rewards` is seeded False on the Trial plan, but the pricing page
        excludes Trial as a tier -- "every plan starts with a 30-day free
        trial" -- so a shop on trial is evaluating a paid plan. Enforcing
        the flag would hide the feature from exactly the audience deciding
        whether to buy.
        """
        tenant, owner = make_tenant(plan_obj=self.trial, plan='trial')
        self.client.force_login(owner)
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()

        resp = self.client.get('/owner/loyalty/')
        self.assertEqual(resp.status_code, 200)


class DeadEnforcementLayerTests(TestCase):
    def test_plan_enforcement_mixin_is_gone(self):
        """It had no callers and carried a third copy of the limit logic,
        including the same null-plan-FK bug UsageService had."""
        from apps.tenants import mixins

        self.assertFalse(hasattr(mixins, 'PlanEnforcementMixin'))
        self.assertFalse(hasattr(mixins, 'check_plan_limit'))
        # The tenant-scoping mixins that ARE used must survive.
        self.assertTrue(hasattr(mixins, 'TenantQuerysetMixin'))
        self.assertTrue(hasattr(mixins, 'TenantCreateMixin'))


class UsageSummaryTests(TestCase):
    def test_storage_gauge_is_gone(self):
        """It reported a hardcoded 0, i.e. a permanent 0% telling nobody
        anything. Enforcing it properly would cost an S3 HEAD per photo."""
        plan = make_plan('starter', 'Starter', 49, max_repairs_per_month=200)
        tenant, _ = make_tenant(plan_obj=plan)
        summary = UsageService(tenant).get_summary()
        self.assertNotIn('storage_mb', summary)
        self.assertIn('repairs', summary)
        self.assertIn('technicians', summary)
        self.assertIn('customers', summary)
