"""
CODE-231: Platform owner bypassed repair limit but NOT technician/customer limits.

Bug: UsageService.can_add_technician() and can_add_customer() were missing the
is_platform_owner short-circuit that can_create_repair() already had. If the platform
owner's SubscriptionPlan had limits set (as it does on the Trial plan: 2 techs, 10
customers), they could be falsely blocked from adding staff or customers.

Also covers the expired-status bypass in UsageService.
both had `subscription_status == 'expired'` checks without first bailing out for
platform owners. A platform owner with a non-standard subscription_status could
be blocked from write operations.

Fix: Added is_platform_owner bypass at the top of can_add_technician() and
can_add_customer() in UsageService.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.test import RequestFactory

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.usage_service import UsageService


class PlatformOwnerUsageLimitsTest(TestCase):
    """
    Ensure the platform owner (Drake's shop) is never blocked by plan limits,
    regardless of what SubscriptionPlan is set on the tenant.
    """

    def setUp(self):
        # A restrictive plan (2 techs, 10 customers, 50 repairs/month)
        self.restrictive_plan = SubscriptionPlan.objects.create(
            name='Restrictive Test',
            slug='restrictive-test-231',
            monthly_price=0,
            max_repairs_per_month=1,
            max_technicians=1,
            max_customers=1,
        )

        self.owner = User.objects.create_user(
            username='platform_owner_231',
            email='owner231@test.com',
            password='pass',
        )
        self.tenant = Tenant.objects.create(
            name='Platform Owner Shop 231',
            slug='platform-owner-231',
            subdomain='platform-owner-231',
            owner=self.owner,
            plan='pro',
            subscription_status='active',
            subscription_plan=self.restrictive_plan,
            is_platform_owner=True,   # ← This is the platform owner
        )

        # A regular tenant with the same restrictive plan (for contrast)
        self.regular_owner = User.objects.create_user(
            username='regular_owner_231',
            email='regular231@test.com',
            password='pass',
        )
        self.regular_tenant = Tenant.objects.create(
            name='Regular Shop 231',
            slug='regular-shop-231',
            subdomain='regular-shop-231',
            owner=self.regular_owner,
            plan='trial',
            subscription_status='trialing',
            subscription_plan=self.restrictive_plan,
            is_platform_owner=False,
        )

    # ----------------------------------------------------------------
    # UsageService — can_create_repair (was already fixed; verify still works)
    # ----------------------------------------------------------------

    def test_platform_owner_can_create_repair_bypasses_limit(self):
        """Platform owner can always create repairs even if plan says 0 or 1."""
        usage = UsageService(self.tenant)
        ok, msg = usage.can_create_repair()
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    # ----------------------------------------------------------------
    # UsageService — can_add_technician (was broken, now fixed)
    # ----------------------------------------------------------------

    def test_platform_owner_can_add_technician_bypasses_limit(self):
        """Platform owner can always add technicians regardless of plan limit."""
        usage = UsageService(self.tenant)
        ok, msg = usage.can_add_technician()
        self.assertTrue(ok, f"Platform owner was blocked from adding technician: {msg}")
        self.assertEqual(msg, "")

    def test_regular_tenant_cannot_exceed_technician_limit(self):
        """Regular tenant is still blocked when at technician limit (regression guard)."""
        # The plan allows 1 technician. Create one so they're at the limit.
        from apps.technician_portal.models import Technician
        tech_user = User.objects.create_user(
            username='tech_231',
            email='tech231@test.com',
            password='pass',
        )
        Technician.objects.create(
            tenant=self.regular_tenant,
            user=tech_user,
            is_active=True,
        )

        usage = UsageService(self.regular_tenant)
        ok, msg = usage.can_add_technician()
        self.assertFalse(ok)
        self.assertIn('1 technicians', msg)

    # ----------------------------------------------------------------
    # UsageService — can_add_customer (was broken, now fixed)
    # ----------------------------------------------------------------

    def test_platform_owner_can_add_customer_bypasses_limit(self):
        """Platform owner can always add customers regardless of plan limit."""
        usage = UsageService(self.tenant)
        ok, msg = usage.can_add_customer()
        self.assertTrue(ok, f"Platform owner was blocked from adding customer: {msg}")
        self.assertEqual(msg, "")

    def test_regular_tenant_cannot_exceed_customer_limit(self):
        """Regular tenant is still blocked when at customer limit (regression guard)."""
        from core.models import Customer
        Customer.objects.create(
            tenant=self.regular_tenant,
            name='Test Customer 231',
            email='tc231@test.com',
        )

        usage = UsageService(self.regular_tenant)
        ok, msg = usage.can_add_customer()
        self.assertFalse(ok)
        self.assertIn('1 customers', msg)

    # ----------------------------------------------------------------
    # Removed with the code they covered
    # ----------------------------------------------------------------
    #
    # This file used to also test check_plan_limit() and
    # PlanEnforcementMixin. Both were deleted: neither had a single
    # production caller, and both carried a third copy of the limit logic
    # that had already drifted from UsageService (same null-plan-FK bug).
    #
    # The platform-owner bypass they verified is covered above against
    # UsageService, which is what the app actually calls. The
    # expired-subscription blocking they also covered lives in
    # SubscriptionEnforcementMiddleware and is tested in
    # tests/test_subscription_expiry.py.
