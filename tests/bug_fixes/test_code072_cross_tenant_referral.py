"""
Regression tests for CODE-072:
  process_referral() had no tenant check, allowing a customer from Shop A to
  use a referral code from Shop B, creating a cross-tenant Referral record
  and awarding Shop B's customer 500 illegitimate referral points.

Root cause:
    ReferralService.process_referral() only checked for self-referrals and
    duplicate referrals.  It never verified that both parties belonged to the
    same tenant.  Because ReferralCode has no tenant FK of its own, the tenant
    is reached via the chain:
        ReferralCode.customer_user → CustomerUser.customer → Customer.tenant

    A customer from any shop could look up any other shop's referral code
    (codes are short, 8-char alphanumeric — easy to enumerate) and call
    referral_tracking to award themselves 100 points and the foreign shop's
    customer 500 points.

Fix:
    Added cross-tenant check at top of process_referral():
        code_tenant = referral_code_obj.customer_user.customer.tenant_id
        user_tenant  = customer_user.customer.tenant_id
        if code_tenant != user_tenant: return False

Tests verify:
1. Same-tenant referral is processed successfully (baseline).
2. Cross-tenant referral is rejected — returns False.
3. Cross-tenant referral: no Referral record created.
4. Cross-tenant referral: referrer earns NO points.
5. Cross-tenant referral: referring user earns NO points.
6. Self-referral is still rejected (pre-existing guard not broken).
7. Duplicate same-tenant referral is still rejected.
8. Successful same-tenant referral awards correct points to both parties.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.rewards_referrals.models import (
    ReferralCode,
    Referral,
    Reward,
    RewardRedemption,
)
from apps.rewards_referrals.services import ReferralService
from apps.customer_portal.models import CustomerUser
from core.models import Customer

try:
    from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
    HAS_TENANT = True
except ImportError:
    HAS_TENANT = False


def _get_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='test-plan',
        defaults={
            'name': 'Test Plan',
            'monthly_price': 0,
            'max_technicians': 10,
            'max_customers': 100,
            'trial_days': 30,
            'display_order': 0,
        },
    )
    return plan


def _make_tenant(name, slug):
    """Create a Tenant with an owner user for tests."""
    plan = _get_plan()
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        password='pw',
        email=f'owner_{slug}@test.com',
    )
    t = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=t, user=owner, role='owner', is_active=True)
    return t


def _make_customer(name, tenant):
    c = Customer(name=name, tenant=tenant)
    c.save()
    return c


def _make_customer_user(email, customer):
    user = User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="testpass123",
    )
    cu = CustomerUser.objects.create(user=user, customer=customer)
    return cu


def _make_referral_code(customer_user):
    code = ReferralService.generate_code_for_user(customer_user)
    return code


class CrossTenantReferralTests(TestCase):
    """Regression tests for CODE-072."""

    def setUp(self):
        if not HAS_TENANT:
            self.skipTest("Tenant model not available")

        # Two separate tenants (shops)
        self.shop_a = _make_tenant("Shop A", "shop-a")
        self.shop_b = _make_tenant("Shop B", "shop-b")

        # Customers in each shop
        self.cust_a = _make_customer("Customer A Corp", self.shop_a)
        self.cust_b = _make_customer("Customer B Corp", self.shop_b)

        # Portal users in each shop
        self.cu_a = _make_customer_user("alice@shop-a.com", self.cust_a)
        self.cu_b = _make_customer_user("bob@shop-b.com", self.cust_b)

        # Referral codes for each user
        self.code_a = _make_referral_code(self.cu_a)
        self.code_b = _make_referral_code(self.cu_b)

    # ------------------------------------------------------------------
    # 1. Same-tenant referral works (baseline)
    # ------------------------------------------------------------------
    def test_same_tenant_referral_succeeds(self):
        """A referral within the same shop should be processed."""
        cu_a2 = _make_customer_user("alice2@shop-a.com", self.cust_a)
        result = ReferralService.process_referral(self.code_a, cu_a2)
        self.assertTrue(result, "Same-tenant referral should succeed")

    # ------------------------------------------------------------------
    # 2. Cross-tenant referral is rejected
    # ------------------------------------------------------------------
    def test_cross_tenant_referral_rejected(self):
        """Shop A's customer cannot use Shop B's referral code."""
        result = ReferralService.process_referral(self.code_b, self.cu_a)
        self.assertFalse(result, "Cross-tenant referral should be rejected")

    # ------------------------------------------------------------------
    # 3. No Referral record created for cross-tenant attempt
    # ------------------------------------------------------------------
    def test_cross_tenant_no_referral_record_created(self):
        """No Referral DB row should be created on cross-tenant rejection."""
        before = Referral.objects.count()
        ReferralService.process_referral(self.code_b, self.cu_a)
        after = Referral.objects.count()
        self.assertEqual(before, after, "No Referral record should be created for cross-tenant attempt")

    # ------------------------------------------------------------------
    # 4. Referrer earns no points on cross-tenant rejection
    # ------------------------------------------------------------------
    def test_cross_tenant_referrer_earns_no_points(self):
        """Shop B's code owner should NOT earn points for a cross-tenant attempt."""
        initial = Reward.objects.filter(customer_user=self.cu_b).first()
        initial_points = initial.points if initial else 0

        ReferralService.process_referral(self.code_b, self.cu_a)

        after = Reward.objects.filter(customer_user=self.cu_b).first()
        after_points = after.points if after else 0
        self.assertEqual(
            initial_points,
            after_points,
            "Referrer should not earn points on cross-tenant rejection",
        )

    # ------------------------------------------------------------------
    # 5. Referring user earns no points on cross-tenant rejection
    # ------------------------------------------------------------------
    def test_cross_tenant_referring_user_earns_no_points(self):
        """Shop A's customer should NOT earn welcome points from a cross-tenant code."""
        initial = Reward.objects.filter(customer_user=self.cu_a).first()
        initial_points = initial.points if initial else 0

        ReferralService.process_referral(self.code_b, self.cu_a)

        after = Reward.objects.filter(customer_user=self.cu_a).first()
        after_points = after.points if after else 0
        self.assertEqual(
            initial_points,
            after_points,
            "Referring user should not earn welcome points from cross-tenant code",
        )

    # ------------------------------------------------------------------
    # 6. Self-referral still rejected
    # ------------------------------------------------------------------
    def test_self_referral_still_rejected(self):
        """Existing self-referral guard should not be broken by the tenant check."""
        result = ReferralService.process_referral(self.code_a, self.cu_a)
        self.assertFalse(result, "Self-referral should still be rejected")

    # ------------------------------------------------------------------
    # 7. Duplicate same-tenant referral still rejected
    # ------------------------------------------------------------------
    def test_duplicate_same_tenant_referral_rejected(self):
        """Duplicate-referral guard should still work after the tenant fix."""
        cu_a2 = _make_customer_user("alice2b@shop-a.com", self.cust_a)
        # First referral should succeed
        first = ReferralService.process_referral(self.code_a, cu_a2)
        self.assertTrue(first)
        # Second identical referral should be rejected
        second = ReferralService.process_referral(self.code_a, cu_a2)
        self.assertFalse(second, "Duplicate referral should be rejected")

    # ------------------------------------------------------------------
    # 8. Successful same-tenant referral awards correct points
    # ------------------------------------------------------------------
    def test_same_tenant_referral_awards_correct_points(self):
        """
        Successful same-tenant referral should award REFERRER_POINTS (500) to
        the code owner and REFERRED_POINTS (100) to the new user.
        """
        cu_a3 = _make_customer_user("alice3@shop-a.com", self.cust_a)

        referrer_before = Reward.objects.filter(customer_user=self.cu_a).first()
        referrer_before_pts = referrer_before.points if referrer_before else 0

        referred_before = Reward.objects.filter(customer_user=cu_a3).first()
        referred_before_pts = referred_before.points if referred_before else 0

        ReferralService.process_referral(self.code_a, cu_a3)

        referrer_after = Reward.objects.filter(customer_user=self.cu_a).first()
        referred_after = Reward.objects.filter(customer_user=cu_a3).first()

        self.assertEqual(
            (referrer_after.points if referrer_after else 0),
            referrer_before_pts + ReferralService.REFERRER_POINTS,
            f"Referrer should earn {ReferralService.REFERRER_POINTS} points",
        )
        self.assertEqual(
            (referred_after.points if referred_after else 0),
            referred_before_pts + ReferralService.REFERRED_POINTS,
            f"Referred user should earn {ReferralService.REFERRED_POINTS} points",
        )
