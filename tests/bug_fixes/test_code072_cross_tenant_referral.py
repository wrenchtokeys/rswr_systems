"""
Regression tests for CODE-072:
  The referral pipeline had no tenant check, allowing a customer from Shop A
  to use a referral code from Shop B, creating a cross-tenant Referral record
  and awarding Shop B's customer illegitimate referral points.

Root cause:
    The referral service only checked for self-referrals and duplicate
    referrals.  It never verified that both parties belonged to the same
    tenant.  Because ReferralCode has no tenant FK of its own, the tenant
    is reached via the chain:
        ReferralCode.customer_user → CustomerUser.customer → Customer.tenant

    A customer from any shop could look up any other shop's referral code
    (codes are short, 8-char alphanumeric — easy to enumerate) and use it
    to earn points for themselves and the foreign shop's customer.

Fix (current architecture):
    ReferralService.record_referral() rejects the attempt up front:
        code_tenant = referral_code_obj.customer_user.customer.tenant
        user_tenant  = customer_user.customer.tenant
        if code_tenant.pk != user_tenant.pk: return False

    record_referral() records a PENDING Referral and moves NO points at
    signup; ReferralService.award_referral_bonuses(customer) pays out when
    the referred customer's first job completes.  Points anchor on the
    Customer (company), not the portal account, and same-company referrals
    are also rejected.

Tests verify:
1. Same-tenant (different-company) referral is recorded as PENDING —
   no points move at signup.
2. Cross-tenant referral is rejected — returns False.
3. Cross-tenant referral: no Referral record created.
4. Cross-tenant referral: referrer's company earns NO points, even after
   the referred company completes a job.
5. Cross-tenant referral: referred company earns NO welcome points.
6. Self-referral is still rejected; same-company referral is rejected too.
7. Duplicate same-tenant referral is still rejected.
8. Successful same-tenant referral pays the configured bonuses to both
   companies once the referred company's first job completes.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.rewards_referrals.models import (
    LoyaltyConfig,
    ReferralCode,
    Referral,
    Reward,
    RewardRedemption,
)
from apps.rewards_referrals.services import LoyaltyService, ReferralService
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
        # A second, distinct company in Shop A (same-tenant referrals must be
        # between different companies — same-company referrals are rejected)
        self.cust_a2 = _make_customer("Customer A2 Corp", self.shop_a)

        # Portal users in each shop
        self.cu_a = _make_customer_user("alice@shop-a.com", self.cust_a)
        self.cu_b = _make_customer_user("bob@shop-b.com", self.cust_b)

        # Referral codes for each user
        self.code_a = _make_referral_code(self.cu_a)
        self.code_b = _make_referral_code(self.cu_b)

    # ------------------------------------------------------------------
    # 1. Same-tenant referral works (baseline) — recorded PENDING, no points
    # ------------------------------------------------------------------
    def test_same_tenant_referral_succeeds(self):
        """A referral within the same shop (different company) is recorded."""
        cu_a2 = _make_customer_user("newco@shop-a.com", self.cust_a2)
        result = ReferralService.record_referral(self.code_a, cu_a2)
        self.assertTrue(result, "Same-tenant referral should be recorded")

        referral = Referral.objects.get(
            referral_code=self.code_a, customer_user=cu_a2
        )
        self.assertEqual(referral.status, 'PENDING')
        # NO points move at signup — payout waits for the first job.
        self.assertEqual(LoyaltyService.get_balance(self.cust_a), 0)
        self.assertEqual(LoyaltyService.get_balance(self.cust_a2), 0)

    # ------------------------------------------------------------------
    # 2. Cross-tenant referral is rejected
    # ------------------------------------------------------------------
    def test_cross_tenant_referral_rejected(self):
        """Shop A's customer cannot use Shop B's referral code."""
        result = ReferralService.record_referral(self.code_b, self.cu_a)
        self.assertFalse(result, "Cross-tenant referral should be rejected")

    # ------------------------------------------------------------------
    # 3. No Referral record created for cross-tenant attempt
    # ------------------------------------------------------------------
    def test_cross_tenant_no_referral_record_created(self):
        """No Referral DB row should be created on cross-tenant rejection."""
        before = Referral.objects.count()
        ReferralService.record_referral(self.code_b, self.cu_a)
        after = Referral.objects.count()
        self.assertEqual(before, after, "No Referral record should be created for cross-tenant attempt")

    # ------------------------------------------------------------------
    # 4. Referrer earns no points on cross-tenant rejection
    # ------------------------------------------------------------------
    def test_cross_tenant_referrer_earns_no_points(self):
        """Shop B's company must NOT earn points from a cross-tenant attempt."""
        initial_points = LoyaltyService.get_balance(self.cust_b)

        ReferralService.record_referral(self.code_b, self.cu_a)
        # Even when the referred company later completes work, nothing
        # pays out — no Referral was recorded.
        ReferralService.award_referral_bonuses(self.cust_a)

        self.assertEqual(
            LoyaltyService.get_balance(self.cust_b),
            initial_points,
            "Referrer's company should not earn points on cross-tenant rejection",
        )

    # ------------------------------------------------------------------
    # 5. Referring user earns no points on cross-tenant rejection
    # ------------------------------------------------------------------
    def test_cross_tenant_referring_user_earns_no_points(self):
        """Shop A's company must NOT earn welcome points from a cross-tenant code."""
        initial_points = LoyaltyService.get_balance(self.cust_a)

        ReferralService.record_referral(self.code_b, self.cu_a)
        ReferralService.award_referral_bonuses(self.cust_a)

        self.assertEqual(
            LoyaltyService.get_balance(self.cust_a),
            initial_points,
            "Referred company should not earn welcome points from cross-tenant code",
        )

    # ------------------------------------------------------------------
    # 6. Self-referral and same-company referral still rejected
    # ------------------------------------------------------------------
    def test_self_referral_still_rejected(self):
        """Existing self-referral guard should not be broken by the tenant check."""
        result = ReferralService.record_referral(self.code_a, self.cu_a)
        self.assertFalse(result, "Self-referral should still be rejected")

    def test_same_company_referral_rejected(self):
        """A second portal user of the SAME company cannot be 'referred'."""
        colleague = _make_customer_user("colleague@shop-a.com", self.cust_a)
        result = ReferralService.record_referral(self.code_a, colleague)
        self.assertFalse(result, "Same-company referral should be rejected")

    # ------------------------------------------------------------------
    # 7. Duplicate same-tenant referral still rejected
    # ------------------------------------------------------------------
    def test_duplicate_same_tenant_referral_rejected(self):
        """Duplicate-referral guard should still work after the tenant fix."""
        cu_a2 = _make_customer_user("newco2@shop-a.com", self.cust_a2)
        # First referral should succeed
        first = ReferralService.record_referral(self.code_a, cu_a2)
        self.assertTrue(first)
        # Second identical referral should be rejected
        second = ReferralService.record_referral(self.code_a, cu_a2)
        self.assertFalse(second, "Duplicate referral should be rejected")

    # ------------------------------------------------------------------
    # 8. Successful same-tenant referral awards correct points on payout
    # ------------------------------------------------------------------
    def test_same_tenant_referral_awards_correct_points(self):
        """
        Once the referred company's first job completes, the referrer's
        company earns referral_bonus_referrer and the referred company earns
        referral_bonus_referred (from LoyaltyConfig).
        """
        cu_a3 = _make_customer_user("newco3@shop-a.com", self.cust_a2)

        referrer_before = LoyaltyService.get_balance(self.cust_a)
        referred_before = LoyaltyService.get_balance(self.cust_a2)

        self.assertTrue(ReferralService.record_referral(self.code_a, cu_a3))
        awarded = ReferralService.award_referral_bonuses(self.cust_a2)
        self.assertEqual(awarded, 1)

        config = LoyaltyConfig.get_for_tenant(self.shop_a)
        self.assertEqual(
            LoyaltyService.get_balance(self.cust_a),
            referrer_before + config.referral_bonus_referrer,
            f"Referrer's company should earn {config.referral_bonus_referrer} points",
        )
        self.assertEqual(
            LoyaltyService.get_balance(self.cust_a2),
            referred_before + config.referral_bonus_referred,
            f"Referred company should earn {config.referral_bonus_referred} points",
        )

        referral = Referral.objects.get(referral_code=self.code_a, customer_user=cu_a3)
        self.assertEqual(referral.status, 'AWARDED')
        self.assertIsNotNone(referral.awarded_at)

        # Payout is idempotent — a second job completion pays nothing more.
        self.assertEqual(ReferralService.award_referral_bonuses(self.cust_a2), 0)
        self.assertEqual(
            LoyaltyService.get_balance(self.cust_a),
            referrer_before + config.referral_bonus_referrer,
        )
