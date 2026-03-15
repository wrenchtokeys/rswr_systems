"""
CODE-025 — RewardService.redeem_reward() IDOR: cross-tenant RewardOption lookup

BUG: RewardService.redeem_reward() fetched RewardOption with an unscoped
RewardOption.objects.get(id=reward_option_id).  A customer from Shop A could
pass Shop B's reward option ID and successfully redeem it, spending their own
points for an option they were never entitled to and leaking the existence of
Shop B's reward program.

Same pattern: RewardService.get_available_rewards() called
RewardOption.objects.filter(is_active=True) without a tenant filter, so it
returned reward options from ALL tenants to a customer — a data leak.

FIX:
  - redeem_reward(): lookup now uses .get(id=..., tenant=tenant)
    where tenant = customer_user.customer.tenant
  - get_available_rewards(): filter now includes tenant=tenant
"""

from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import Reward, RewardOption, RewardRedemption
from apps.rewards_referrals.services import RewardService
from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_reward_option(tenant, name='Test Reward', points=100, active=True):
    return RewardOption.objects.create(
        tenant=tenant,
        name=name,
        description='Test',
        points_required=points,
        is_active=active,
    )


def _make_customer_user(tenant, username):
    """Create a Customer + CustomerUser for the given tenant."""
    user = User.objects.create_user(username, f'{username}@test.com', 'pass')
    customer = Customer.objects.create(tenant=tenant, name=f'{username} Corp')
    cu = CustomerUser.objects.create(user=user, customer=customer)
    # Give them some points so redemption can proceed
    Reward.objects.create(customer_user=cu, points=500)
    return cu


@override_settings(**TEST_OVERRIDES)
class RedeemRewardTenantScopeTests(TestCase):
    """CODE-025 regression: redeem_reward must reject cross-tenant option IDs."""

    def setUp(self):
        _, self.tenant_a = make_tenant('RedeemA', 'redeem_owner_a')
        _, self.tenant_b = make_tenant('RedeemB', 'redeem_owner_b')

        self.cu_a = _make_customer_user(self.tenant_a, 'cu_redeem_a')
        self.cu_b = _make_customer_user(self.tenant_b, 'cu_redeem_b')

        self.opt_a = _make_reward_option(self.tenant_a, 'Option A', points=100)
        self.opt_b = _make_reward_option(self.tenant_b, 'Option B', points=100)

    # ------------------------------------------------------------------
    # Happy path: same-tenant redemption must still work
    # ------------------------------------------------------------------

    def test_same_tenant_redemption_succeeds(self):
        """Customer A can redeem Shop A's option."""
        success, result = RewardService.redeem_reward(self.cu_a, self.opt_a.id)
        self.assertTrue(success, f"Expected success but got: {result}")
        self.assertIsInstance(result, RewardRedemption)

    def test_same_tenant_points_deducted(self):
        """Points are deducted on successful redemption."""
        before = Reward.objects.get(customer_user=self.cu_a).points
        RewardService.redeem_reward(self.cu_a, self.opt_a.id)
        after = Reward.objects.get(customer_user=self.cu_a).points
        self.assertEqual(after, before - self.opt_a.points_required)

    def test_same_tenant_redemption_record_created(self):
        """A RewardRedemption row is created on success."""
        RewardService.redeem_reward(self.cu_a, self.opt_a.id)
        self.assertEqual(
            RewardRedemption.objects.filter(
                reward__customer_user=self.cu_a,
                reward_option=self.opt_a
            ).count(),
            1
        )

    # ------------------------------------------------------------------
    # IDOR prevention: cross-tenant option must be rejected
    # ------------------------------------------------------------------

    def test_cross_tenant_option_rejected(self):
        """Customer A must NOT be able to redeem Shop B's option ID."""
        success, result = RewardService.redeem_reward(self.cu_a, self.opt_b.id)
        self.assertFalse(success, "Cross-tenant redemption must fail")
        self.assertIn("Invalid", result)

    def test_cross_tenant_no_redemption_row_created(self):
        """No RewardRedemption row should exist after a cross-tenant attempt."""
        RewardService.redeem_reward(self.cu_a, self.opt_b.id)
        self.assertEqual(
            RewardRedemption.objects.filter(reward__customer_user=self.cu_a).count(),
            0
        )

    def test_cross_tenant_points_not_deducted(self):
        """Cross-tenant rejection must not alter the user's point balance."""
        before = Reward.objects.get(customer_user=self.cu_a).points
        RewardService.redeem_reward(self.cu_a, self.opt_b.id)
        after = Reward.objects.get(customer_user=self.cu_a).points
        self.assertEqual(after, before)

    def test_nonexistent_option_id_rejected(self):
        """A completely bogus option ID must fail gracefully."""
        success, result = RewardService.redeem_reward(self.cu_a, 99999)
        self.assertFalse(success)
        self.assertIn("Invalid", result)


@override_settings(**TEST_OVERRIDES)
class GetAvailableRewardsTenantScopeTests(TestCase):
    """CODE-025 regression: get_available_rewards must not leak cross-tenant options."""

    def setUp(self):
        _, self.tenant_a = make_tenant('AvailA', 'avail_owner_a')
        _, self.tenant_b = make_tenant('AvailB', 'avail_owner_b')

        self.cu_a = _make_customer_user(self.tenant_a, 'cu_avail_a')
        self.cu_b = _make_customer_user(self.tenant_b, 'cu_avail_b')

        # Shop A: 100-point option (affordable) and 9999-point option (too expensive)
        _make_reward_option(self.tenant_a, 'A-Cheap', points=100)
        _make_reward_option(self.tenant_a, 'A-Pricey', points=9999)

        # Shop B: 50-point option (should NOT appear for Shop A customers)
        _make_reward_option(self.tenant_b, 'B-Cheap', points=50)

    def test_available_list_excludes_other_tenant_options(self):
        """get_available_rewards must not return Shop B's options to Shop A customer."""
        result = RewardService.get_available_rewards(self.cu_a)
        all_names = [o.name for o in result['available']] + [o.name for o in result['unavailable']]
        self.assertNotIn('B-Cheap', all_names)

    def test_available_list_contains_own_tenant_options(self):
        """get_available_rewards returns this tenant's options."""
        result = RewardService.get_available_rewards(self.cu_a)
        all_names = [o.name for o in result['available']] + [o.name for o in result['unavailable']]
        self.assertIn('A-Cheap', all_names)
        self.assertIn('A-Pricey', all_names)

    def test_available_and_unavailable_partition_by_balance(self):
        """Options are correctly partitioned by the customer's balance."""
        # cu_a has 500 points (from setUp helper)
        result = RewardService.get_available_rewards(self.cu_a)
        avail_names = [o.name for o in result['available']]
        unavail_names = [o.name for o in result['unavailable']]
        # A-Cheap (100) ≤ 500 → available; A-Pricey (9999) > 500 → unavailable
        self.assertIn('A-Cheap', avail_names)
        self.assertIn('A-Pricey', unavail_names)
