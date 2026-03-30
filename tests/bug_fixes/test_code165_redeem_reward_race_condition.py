"""
Regression tests for CODE-165:
  RewardService.redeem_reward() had a TOCTOU race condition — two concurrent
  requests inside @transaction.atomic could both pass the "enough points?"
  check before either deducted, resulting in a negative reward balance
  (double-spend).

Root cause:
    Reward.objects.get_or_create(customer_user=customer_user) performed a
    non-locking SELECT.  Within the same @transaction.atomic block, a second
    concurrent call would see the same row with the full balance before the
    first call had saved its deduction.

Fix:
    Replaced get_or_create() with a select_for_update() pattern:
      1. Try Reward.objects.select_for_update().get(...)
      2. If DoesNotExist, create, then re-fetch with select_for_update()
    This acquires a row-level lock so concurrent calls serialize on the
    balance check-and-deduct step.

Tests verify:
1. Single redemption succeeds and deducts the correct number of points.
2. A second redemption when balance is insufficient is rejected.
3. Attempting to redeem a reward from a different tenant is rejected (IDOR).
4. Redeeming an inactive reward option is rejected.
5. The balance never goes negative after two sequential redemptions
   that together exceed the starting balance.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.rewards_referrals.models import Reward, RewardOption, RewardRedemption, RewardType
from apps.rewards_referrals.services import RewardService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(slug):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial",
        defaults={
            "name": "Trial",
            "monthly_price": 0,
            "annual_price": 0,
            "max_customers": 50,
            "max_technicians": 5,
            "is_active": True,
        },
    )
    owner = User.objects.create_user(
        username=f"owner_{slug}", email=f"owner@{slug}.com", password="pass"
    )
    tenant = Tenant.objects.create(
        name=slug,
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan="trial",
        subscription_plan=plan,
        subscription_status="trialing",
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role="owner")
    return tenant, owner


def _make_customer_user(tenant, username, email):
    user = User.objects.create_user(username=username, email=email, password="pass")
    customer = Customer.objects.create(
        tenant=tenant, name=username, customer_type="RETAIL", email=email
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role="viewer")
    cu = CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=True)
    return cu


def _make_reward_option(tenant, points_required, name="Free Oil Change", active=True):
    # RewardType is global (no tenant FK)
    reward_type, _ = RewardType.objects.get_or_create(
        name="Service",
        category="FREE_SERVICE",
        defaults={"description": "Service reward", "discount_type": "FREE"},
    )
    return RewardOption.objects.create(
        tenant=tenant,
        reward_type=reward_type,
        name=name,
        description=name,
        points_required=points_required,
        is_active=active,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class RedeemRewardRaceConditionTestCase(TestCase):
    """Tests for RewardService.redeem_reward() with select_for_update() fix."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant("shoprace")
        self.customer_user = _make_customer_user(
            self.tenant, "cust_race", "cust@race.com"
        )
        # Give customer 500 points
        self.reward_obj = Reward.objects.create(
            customer_user=self.customer_user, points=500
        )
        self.option_200 = _make_reward_option(self.tenant, 200, "200pt Option")
        self.option_400 = _make_reward_option(self.tenant, 400, "400pt Option")

    def test_single_redemption_succeeds(self):
        """A single redemption deducts the correct number of points."""
        success, result = RewardService.redeem_reward(self.customer_user, self.option_200.id)
        self.assertTrue(success, f"Expected success but got: {result}")
        self.assertIsInstance(result, RewardRedemption)

        self.reward_obj.refresh_from_db()
        self.assertEqual(self.reward_obj.points, 300)  # 500 - 200

    def test_second_redemption_with_insufficient_balance_rejected(self):
        """A second redemption that would leave a negative balance is rejected."""
        # First redemption: 500 - 400 = 100 remaining
        success1, _ = RewardService.redeem_reward(self.customer_user, self.option_400.id)
        self.assertTrue(success1)

        # Second redemption of 200 would require 200 but we only have 100
        success2, msg = RewardService.redeem_reward(self.customer_user, self.option_200.id)
        self.assertFalse(success2)
        self.assertIn("Not enough points", msg)

        # Balance must not go negative
        self.reward_obj.refresh_from_db()
        self.assertGreaterEqual(self.reward_obj.points, 0)

    def test_balance_never_negative_after_sequential_overdraws(self):
        """Sequential redemptions that together exceed the balance leave balance >= 0."""
        # 500 points, two 400-point redemptions
        option_400b = _make_reward_option(self.tenant, 400, "400pt Option B")

        success1, _ = RewardService.redeem_reward(self.customer_user, self.option_400.id)
        self.assertTrue(success1)

        success2, msg = RewardService.redeem_reward(self.customer_user, option_400b.id)
        self.assertFalse(success2)  # Should be blocked — only 100 pts remain

        self.reward_obj.refresh_from_db()
        self.assertGreaterEqual(self.reward_obj.points, 0)

    def test_cross_tenant_idor_blocked(self):
        """A customer cannot redeem a reward option from a different tenant."""
        other_tenant, _ = _make_tenant("othershoprace")
        other_option = _make_reward_option(other_tenant, 100, "Cross-Tenant Option")

        success, msg = RewardService.redeem_reward(self.customer_user, other_option.id)
        self.assertFalse(success)
        self.assertEqual(msg, "Invalid reward option")

    def test_inactive_option_rejected(self):
        """Attempting to redeem an inactive reward option is rejected."""
        inactive_option = _make_reward_option(
            self.tenant, 100, "Inactive Option", active=False
        )
        success, msg = RewardService.redeem_reward(self.customer_user, inactive_option.id)
        self.assertFalse(success)
        self.assertIn("not currently available", msg)

    def test_redemption_creates_reward_row_if_none_exists(self):
        """If the Reward row doesn't exist yet, it is created with 0 balance (insufficient)."""
        new_cu = _make_customer_user(self.tenant, "cust_new", "new@race.com")
        # No Reward row for new_cu

        success, msg = RewardService.redeem_reward(new_cu, self.option_200.id)
        self.assertFalse(success)
        self.assertIn("Not enough points", msg)

        # A Reward row should have been created (with 0 points)
        reward = Reward.objects.filter(customer_user=new_cu).first()
        self.assertIsNotNone(reward)
        self.assertEqual(reward.points, 0)

    def test_redemption_deducts_exact_points(self):
        """Verify exact deduction — no off-by-one."""
        self.reward_obj.points = 200
        self.reward_obj.save()

        success, _ = RewardService.redeem_reward(self.customer_user, self.option_200.id)
        self.assertTrue(success)

        self.reward_obj.refresh_from_db()
        self.assertEqual(self.reward_obj.points, 0)  # Exactly zero, not negative
