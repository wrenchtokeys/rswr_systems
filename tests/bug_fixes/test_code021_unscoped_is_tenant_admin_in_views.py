"""
Regression tests for CODE-021: Unscoped is_tenant_admin(request.user) calls
in technician portal views.

After CODE-015 fixed the decorators to pass tenant, 43+ in-view calls to
is_tenant_admin(request.user) were still missing the tenant parameter.

Bug: A user who is owner/manager at Shop A but plain technician at Shop B
could pass is_tenant_admin() checks in views on Shop B's pages (because
the function without a tenant parameter uses highest-privilege membership
across all shops).

This allowed:
- assign_repair, reassign_to_self: cross-tenant admin override bypassing
  manager permission gates in repair assignment
- repair_list, repair_detail: is_admin=True in template context, exposing
  admin-only UI to cross-tenant admins
- batch views: admin overrides in pricing, batch management
- customer views: admin edit gates passed by cross-tenant admins
- dashboard: is_admin flag wrong for cross-tenant users

Fix: All is_tenant_admin(request.user) calls in technician portal views now
pass tenant=getattr(request, 'tenant', None).

Verification: Use is_tenant_admin directly with/without tenant parameter
to confirm scoped vs. unscoped behavior differ for cross-tenant users.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.http import HttpResponse

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician
from apps.technician_portal.decorators import is_tenant_admin
from common.auth import get_user_role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name, owner_user, plan):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-').replace('_', '-'),
        subdomain=name.lower().replace(' ', '-').replace('_', '-'),
        owner=owner_user,
        plan='trial',
        subscription_plan=plan,
    )


def _membership(user, tenant, role):
    return TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class IsAdminScopingTests(TestCase):
    """
    Verify that is_tenant_admin with vs without tenant parameter behaves
    correctly for cross-tenant scenarios.
    """

    def setUp(self):
        plan = _plan()

        # Shop A owner (also manager at Shop A)
        self.owner_a = User.objects.create_user('owner_a_021', password='pw')
        self.tenant_a = _make_tenant('shop_a_021', self.owner_a, plan)
        _membership(self.owner_a, self.tenant_a, 'owner')

        # Shop B owner
        self.owner_b = User.objects.create_user('owner_b_021', password='pw')
        self.tenant_b = _make_tenant('shop_b_021', self.owner_b, plan)
        _membership(self.owner_b, self.tenant_b, 'owner')

        # Cross-tenant user: admin at Shop A, plain technician at Shop B
        self.cross_user = User.objects.create_user('cross_021', password='pw')
        _membership(self.cross_user, self.tenant_a, 'owner')   # admin at A
        _membership(self.cross_user, self.tenant_b, 'viewer')  # viewer at B

    def test_unscoped_returns_highest_privilege(self):
        """Without tenant, is_tenant_admin returns True if user is admin anywhere."""
        # This is expected behavior for unscoped — but it's WRONG in view context
        result = is_tenant_admin(self.cross_user)
        self.assertTrue(result, "Unscoped should return True (admin at Shop A)")

    def test_scoped_to_shop_b_returns_false(self):
        """With tenant=shop_b, is_tenant_admin returns False for cross-tenant admin."""
        result = is_tenant_admin(self.cross_user, tenant=self.tenant_b)
        self.assertFalse(result, "Should NOT be admin at Shop B (only viewer there)")

    def test_scoped_to_shop_a_returns_true(self):
        """With tenant=shop_a, is_tenant_admin returns True for shop_a admin."""
        result = is_tenant_admin(self.cross_user, tenant=self.tenant_a)
        self.assertTrue(result, "Should be admin at Shop A")

    def test_plain_technician_not_admin_at_either_shop(self):
        """A plain technician is not admin at any shop."""
        tech_user = User.objects.create_user('tech_only_021', password='pw')
        _membership(tech_user, self.tenant_a, 'technician')

        self.assertFalse(is_tenant_admin(tech_user))
        self.assertFalse(is_tenant_admin(tech_user, tenant=self.tenant_a))
        self.assertFalse(is_tenant_admin(tech_user, tenant=self.tenant_b))

    def test_manager_at_shop_a_not_admin_at_shop_b(self):
        """A manager at Shop A is not admin at Shop B (even with unrelated membership)."""
        mgr = User.objects.create_user('mgr_021', password='pw')
        _membership(mgr, self.tenant_a, 'manager')
        _membership(mgr, self.tenant_b, 'technician')

        # Unscoped: True (manager at A)
        self.assertTrue(is_tenant_admin(mgr))
        # Scoped to B: False (only technician at B)
        self.assertFalse(is_tenant_admin(mgr, tenant=self.tenant_b))
        # Scoped to A: True
        self.assertTrue(is_tenant_admin(mgr, tenant=self.tenant_a))


class GetUserRoleScopingTests(TestCase):
    """Verify get_user_role (underlying function) respects tenant parameter."""

    def setUp(self):
        plan = _plan()
        self.owner_a = User.objects.create_user('gr_owner_a_021', password='pw')
        self.tenant_a = _make_tenant('gr_shop_a_021', self.owner_a, plan)
        _membership(self.owner_a, self.tenant_a, 'owner')

        self.owner_b = User.objects.create_user('gr_owner_b_021', password='pw')
        self.tenant_b = _make_tenant('gr_shop_b_021', self.owner_b, plan)
        _membership(self.owner_b, self.tenant_b, 'owner')

        self.cross_user = User.objects.create_user('gr_cross_021', password='pw')
        _membership(self.cross_user, self.tenant_a, 'owner')
        _membership(self.cross_user, self.tenant_b, 'technician')

    def test_role_without_tenant_returns_highest(self):
        role = get_user_role(self.cross_user)
        self.assertEqual(role, 'owner', "Without tenant, highest role (owner at A) returned")

    def test_role_scoped_to_b_returns_technician(self):
        role = get_user_role(self.cross_user, tenant=self.tenant_b)
        self.assertEqual(role, 'technician', "Scoped to B: only technician")

    def test_role_scoped_to_a_returns_owner(self):
        role = get_user_role(self.cross_user, tenant=self.tenant_a)
        self.assertEqual(role, 'owner', "Scoped to A: owner")


class ViewCodeUsesCorrectParamTests(TestCase):
    """
    Black-box verification: scan the view source to confirm all in-view
    is_tenant_admin(request.user) calls now include the tenant parameter.
    """

    def test_repairs_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/repairs.py') as f:
            src = f.read()
        # Bare call: is_tenant_admin(request.user) NOT followed by ", tenant"
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in repairs.py: {bare}"
        )

    def test_batch_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/batch.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in batch.py: {bare}"
        )

    def test_customers_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/customers.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in customers.py: {bare}"
        )

    def test_settings_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/settings.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in settings.py: {bare}"
        )

    def test_dashboard_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/dashboard.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in dashboard.py: {bare}"
        )

    def test_rewards_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/rewards.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in rewards.py: {bare}"
        )
