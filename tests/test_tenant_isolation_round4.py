"""
Tenant Isolation Tests — Round 4 (BUG-038, BUG-039)

Tests for ViscosityRecommendation and RewardOption tenant scoping.

Found during comprehensive retest audit on March 7, 2026.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory, override_settings

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import ViscosityRecommendation
from apps.rewards_referrals.models import RewardOption, RewardType
from tests.helpers import make_tenant as _make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


@override_settings(**TEST_OVERRIDES)
class ViscosityRecommendationTenantTests(TestCase):
    """BUG-038: ViscosityRecommendation must be tenant-scoped."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Visc A', 'visc_owner_a')
        self.user_b, self.tenant_b = _make_tenant('Visc B', 'visc_owner_b')

        # Create viscosity rules for tenant A
        self.rule_a = ViscosityRecommendation.objects.create(
            tenant=self.tenant_a,
            name='Cold Weather A',
            min_temperature=None,
            max_temperature=Decimal('59.9'),
            recommended_viscosity='Low',
            suggestion_text='Use low viscosity for cold conditions',
            badge_color='blue',
            display_order=10,
        )

        # Create viscosity rules for tenant B
        self.rule_b = ViscosityRecommendation.objects.create(
            tenant=self.tenant_b,
            name='Cold Weather B',
            min_temperature=None,
            max_temperature=Decimal('50.0'),
            recommended_viscosity='Extra Low',
            suggestion_text='Use extra low viscosity',
            badge_color='green',
            display_order=10,
        )

    def test_recommendation_scoped_to_tenant(self):
        """get_recommendation_for_temperature should only return tenant's rules."""
        # At 55F, tenant A's rule matches (max 59.9) but tenant B's doesn't (max 50.0)
        result_a = ViscosityRecommendation.get_recommendation_for_temperature(55.0, tenant=self.tenant_a)
        self.assertIsNotNone(result_a)
        self.assertEqual(result_a['recommendation'], 'Low')

        result_b = ViscosityRecommendation.get_recommendation_for_temperature(55.0, tenant=self.tenant_b)
        self.assertIsNone(result_b)  # 55F > 50F max, no match for tenant B

    def test_no_cross_tenant_rule_leakage(self):
        """Tenant B should not see tenant A's rules."""
        tenant_b_rules = ViscosityRecommendation.objects.filter(tenant=self.tenant_b)
        self.assertEqual(tenant_b_rules.count(), 1)
        self.assertEqual(tenant_b_rules.first().name, 'Cold Weather B')

    def test_new_rule_assigned_to_tenant(self):
        """New rules should be created with tenant context."""
        rule = ViscosityRecommendation.objects.create(
            tenant=self.tenant_a,
            name='Hot Weather',
            min_temperature=Decimal('86.0'),
            recommended_viscosity='High',
            suggestion_text='Use high viscosity',
            badge_color='red',
        )
        self.assertEqual(rule.tenant, self.tenant_a)


@override_settings(**TEST_OVERRIDES)
class RewardOptionTenantTests(TestCase):
    """BUG-039: RewardOption must be tenant-scoped."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Reward A', 'reward_owner_a')
        self.user_b, self.tenant_b = _make_tenant('Reward B', 'reward_owner_b')

        self.reward_type, _ = RewardType.objects.get_or_create(
            name='Repair Discount',
            category='REPAIR_DISCOUNT',
            defaults={'discount_type': 'PERCENTAGE', 'discount_value': 50},
        )

        # Create reward options for tenant A
        self.option_a = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='50% Off Repair (A)',
            description='Tenant A discount',
            points_required=2000,
            reward_type=self.reward_type,
        )

        # Create reward options for tenant B
        self.option_b = RewardOption.objects.create(
            tenant=self.tenant_b,
            name='Free Repair (B)',
            description='Tenant B free repair',
            points_required=3500,
            reward_type=self.reward_type,
        )

    def test_reward_options_scoped_to_tenant(self):
        """Each tenant should only see their own reward options."""
        from apps.rewards_referrals.services import RewardService

        opts_a = RewardService.get_reward_options(tenant=self.tenant_a)
        self.assertEqual(opts_a.count(), 1)
        self.assertEqual(opts_a.first().name, '50% Off Repair (A)')

        opts_b = RewardService.get_reward_options(tenant=self.tenant_b)
        self.assertEqual(opts_b.count(), 1)
        self.assertEqual(opts_b.first().name, 'Free Repair (B)')

    def test_no_cross_tenant_reward_leakage(self):
        """Tenant A should not see tenant B's rewards."""
        tenant_a_options = RewardOption.objects.filter(tenant=self.tenant_a)
        names = list(tenant_a_options.values_list('name', flat=True))
        self.assertNotIn('Free Repair (B)', names)

    def test_without_tenant_returns_all(self):
        """Without tenant filter, service returns all (for superuser)."""
        from apps.rewards_referrals.services import RewardService

        all_opts = RewardService.get_reward_options(tenant=None)
        self.assertEqual(all_opts.count(), 2)
