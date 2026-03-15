"""
Regression tests for CODE-015: Cross-tenant privilege escalation via broken
_get_membership() ordering + untenanted decorator checks.

Two separate bugs were fixed:

1. common/auth.py _get_membership() — when no tenant given, used .order_by()
   with no arguments (the comment inside was not a real argument, Python strips
   it).  Django's order_by() with no args CLEARS all ordering, returning results
   in database-insertion order (PK ascending).  The comment claimed the intent
   was to return the highest-privilege membership, but the implementation
   returned the *first-created* membership regardless of role.

   Impact: a user who is Owner at Shop A (joined first) and Technician at Shop B
   appears as an Owner everywhere; a user who is Technician at Shop A (joined
   first) and Manager at Shop B appears as a Technician everywhere.

2. apps/technician_portal/decorators.py manager_required / admin_required —
   both called is_tenant_admin(request.user) without passing the current
   request.tenant, so the role check was performed against whichever membership
   _get_membership() happened to return (not the shop the request was for).

   Impact: a user who is Manager at Shop A but Technician at Shop B could pass
   @manager_required on Shop B pages, gaining access to manager-only views for
   a shop where they are a plain technician.

Fix:
- _get_membership() now annotates with role_priority (owner=0..viewer=3) and
  orders by it, guaranteeing highest-privilege membership is returned when no
  tenant is given.
- is_tenant_admin() accepts an optional tenant= kwarg and threads it through
  to get_user_role().
- manager_required and admin_required decorators now pass request.tenant so
  role is checked against the actual shop being accessed.
- manager_required also verifies the Technician.is_manager path belongs to
  the current tenant.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock
from django.http import HttpResponse
from django.test import override_settings

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician
from apps.technician_portal.decorators import (
    is_tenant_admin, manager_required, admin_required
)
from common.auth import _get_membership, get_user_role


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
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner_user,
        plan='trial',
        subscription_plan=plan,
    )


def _membership(user, tenant, role):
    return TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True
    )


def _dummy_view(request, *args, **kwargs):
    return HttpResponse('ok', status=200)


# ---------------------------------------------------------------------------
# 1. _get_membership() ordering
# ---------------------------------------------------------------------------

class GetMembershipOrderingTest(TestCase):
    """_get_membership() with no tenant must return highest-privilege membership."""

    def setUp(self):
        plan = _plan()
        self.owner_a = User.objects.create_user(username='owner_a', password='pw')
        self.owner_b = User.objects.create_user(username='owner_b', password='pw')
        self.tenant_a = _make_tenant('Shop A', self.owner_a, plan)
        self.tenant_b = _make_tenant('Shop B', self.owner_b, plan)

    def test_owner_beats_technician_regardless_of_creation_order(self):
        """If user is technician (created first) and owner (second), returns owner."""
        user = User.objects.create_user(username='multi1', password='pw')
        _membership(user, self.tenant_a, 'technician')  # PK lower — created first
        _membership(user, self.tenant_b, 'owner')       # PK higher — created second

        m = _get_membership(user)
        self.assertEqual(m.role, 'owner',
            "Should return owner membership even though technician was created first.")

    def test_manager_beats_technician_regardless_of_creation_order(self):
        """If user is technician (first) and manager (second), returns manager."""
        user = User.objects.create_user(username='multi2', password='pw')
        _membership(user, self.tenant_a, 'technician')
        _membership(user, self.tenant_b, 'manager')

        m = _get_membership(user)
        self.assertEqual(m.role, 'manager')

    def test_owner_beats_manager(self):
        """Owner beats manager when user has both."""
        user = User.objects.create_user(username='multi3', password='pw')
        _membership(user, self.tenant_a, 'manager')  # first
        _membership(user, self.tenant_b, 'owner')    # second

        m = _get_membership(user)
        self.assertEqual(m.role, 'owner')

    def test_single_membership_returned_correctly(self):
        """A user with only one membership always gets that one."""
        user = User.objects.create_user(username='single1', password='pw')
        _membership(user, self.tenant_a, 'technician')

        m = _get_membership(user)
        self.assertEqual(m.role, 'technician')

    def test_no_membership_returns_none(self):
        user = User.objects.create_user(username='nobody', password='pw')
        self.assertIsNone(_get_membership(user))

    def test_with_tenant_ignores_other_tenants(self):
        """When tenant is given, only that tenant's membership is returned."""
        user = User.objects.create_user(username='scoped1', password='pw')
        _membership(user, self.tenant_a, 'owner')
        _membership(user, self.tenant_b, 'technician')

        m = _get_membership(user, tenant=self.tenant_b)
        self.assertEqual(m.role, 'technician',
            "Should return tenant_b technician, not tenant_a owner.")


# ---------------------------------------------------------------------------
# 2. is_tenant_admin() with tenant kwarg
# ---------------------------------------------------------------------------

class IsTenantAdminWithTenantTest(TestCase):
    """is_tenant_admin(user, tenant=) must scope to the given tenant."""

    def setUp(self):
        plan = _plan()
        self.owner_a = User.objects.create_user(username='owner_2a', password='pw')
        self.owner_b = User.objects.create_user(username='owner_2b', password='pw')
        self.tenant_a = _make_tenant('Alpha Shop', self.owner_a, plan)
        self.tenant_b = _make_tenant('Beta Shop', self.owner_b, plan)

    def test_manager_at_a_is_not_admin_at_b(self):
        """User who is manager at Shop A must NOT be admin at Shop B."""
        user = User.objects.create_user(username='mgr_a_tech_b', password='pw')
        _membership(user, self.tenant_a, 'manager')
        _membership(user, self.tenant_b, 'technician')

        self.assertTrue(is_tenant_admin(user, tenant=self.tenant_a))
        self.assertFalse(is_tenant_admin(user, tenant=self.tenant_b))

    def test_owner_at_b_is_not_admin_at_a(self):
        user = User.objects.create_user(username='tech_a_owner_b', password='pw')
        _membership(user, self.tenant_a, 'technician')
        _membership(user, self.tenant_b, 'owner')

        self.assertFalse(is_tenant_admin(user, tenant=self.tenant_a))
        self.assertTrue(is_tenant_admin(user, tenant=self.tenant_b))

    def test_superuser_is_always_admin(self):
        su = User.objects.create_superuser(username='su_x', password='pw', email='su@x.com')
        self.assertTrue(is_tenant_admin(su, tenant=self.tenant_a))
        self.assertTrue(is_tenant_admin(su, tenant=self.tenant_b))
        self.assertTrue(is_tenant_admin(su))


# ---------------------------------------------------------------------------
# 3. manager_required decorator — cross-tenant gate
# ---------------------------------------------------------------------------

class ManagerRequiredDecoratorTenantScopeTest(TestCase):
    """@manager_required must use request.tenant for the role check."""

    def setUp(self):
        self.factory = RequestFactory()
        plan = _plan()
        self.owner_a = User.objects.create_user(username='owner_3a', password='pw')
        self.owner_b = User.objects.create_user(username='owner_3b', password='pw')
        self.tenant_a = _make_tenant('Gamma Shop', self.owner_a, plan)
        self.tenant_b = _make_tenant('Delta Shop', self.owner_b, plan)

    def _request(self, user, tenant):
        """Build a RequestFactory request with messages middleware support."""
        req = self.factory.get('/')
        req.user = user
        req.tenant = tenant
        # Attach a cookie-based message storage (no session required)
        from django.contrib.messages.storage.cookie import CookieStorage
        req._messages = CookieStorage(req)
        return req

    def test_manager_at_a_blocked_at_b(self):
        """Manager of Shop A must be blocked by @manager_required on Shop B request."""
        user = User.objects.create_user(username='mgr_a2', password='pw')
        _membership(user, self.tenant_a, 'manager')
        _membership(user, self.tenant_b, 'technician')

        view = manager_required(_dummy_view)
        response = view(self._request(user, self.tenant_b))
        # Should be a redirect (302), NOT 200 OK
        self.assertEqual(response.status_code, 302,
            "Manager at Shop A must not access manager-only views on Shop B.")

    def test_manager_at_a_allowed_at_a(self):
        """Manager of Shop A must be allowed by @manager_required on Shop A request."""
        user = User.objects.create_user(username='mgr_a3', password='pw')
        _membership(user, self.tenant_a, 'manager')

        view = manager_required(_dummy_view)
        response = view(self._request(user, self.tenant_a))
        self.assertEqual(response.status_code, 200)

    def test_technician_blocked_everywhere(self):
        user = User.objects.create_user(username='tech_only', password='pw')
        _membership(user, self.tenant_a, 'technician')

        view = manager_required(_dummy_view)
        response = view(self._request(user, self.tenant_a))
        self.assertEqual(response.status_code, 302)

    def test_owner_allowed_at_own_shop(self):
        user = User.objects.create_user(username='owner_only3', password='pw')
        _membership(user, self.tenant_a, 'owner')

        view = manager_required(_dummy_view)
        response = view(self._request(user, self.tenant_a))
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_redirected(self):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.cookie import CookieStorage
        req = self.factory.get('/')
        req.user = AnonymousUser()
        req.tenant = self.tenant_a
        req._messages = CookieStorage(req)

        view = manager_required(_dummy_view)
        response = view(req)
        self.assertEqual(response.status_code, 302)

    def test_is_manager_flag_blocked_at_foreign_tenant(self):
        """A Technician with is_manager=True at Shop A cannot pass @manager_required on Shop B."""
        user = User.objects.create_user(username='techmanager_a', password='pw')
        _membership(user, self.tenant_a, 'technician')
        _membership(user, self.tenant_b, 'technician')

        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,  # belongs to Shop A
            is_manager=True,
        )

        view = manager_required(_dummy_view)
        # Request is for Shop B — the Technician is_manager but for Shop A
        response = view(self._request(user, self.tenant_b))
        self.assertEqual(response.status_code, 302,
            "is_manager=True for Shop A tech must not grant manager access on Shop B.")


# ---------------------------------------------------------------------------
# 4. admin_required decorator — cross-tenant gate
# ---------------------------------------------------------------------------

class AdminRequiredDecoratorTenantScopeTest(TestCase):
    """@admin_required must use request.tenant for the role check."""

    def setUp(self):
        self.factory = RequestFactory()
        plan = _plan()
        self.owner_a = User.objects.create_user(username='owner_4a', password='pw')
        self.owner_b = User.objects.create_user(username='owner_4b', password='pw')
        self.tenant_a = _make_tenant('Epsilon Shop', self.owner_a, plan)
        self.tenant_b = _make_tenant('Zeta Shop', self.owner_b, plan)

    def _request(self, user, tenant):
        from django.contrib.messages.storage.cookie import CookieStorage
        req = self.factory.get('/')
        req.user = user
        req.tenant = tenant
        req._messages = CookieStorage(req)
        return req

    def test_owner_at_a_blocked_at_b(self):
        user = User.objects.create_user(username='owner_at_a', password='pw')
        _membership(user, self.tenant_a, 'owner')
        _membership(user, self.tenant_b, 'viewer')

        view = admin_required(_dummy_view)
        response = view(self._request(user, self.tenant_b))
        self.assertEqual(response.status_code, 302,
            "Owner at Shop A must not pass @admin_required on Shop B.")

    def test_owner_at_a_allowed_at_a(self):
        user = User.objects.create_user(username='owner_at_a2', password='pw')
        _membership(user, self.tenant_a, 'owner')

        view = admin_required(_dummy_view)
        response = view(self._request(user, self.tenant_a))
        self.assertEqual(response.status_code, 200)
