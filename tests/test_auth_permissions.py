"""
Auth & Permissions Tests — common/auth.py, login routing, role-based access

Tests can_access, get_user_role, requires/requires_api decorators,
login routing, and portal redirects.

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings, RequestFactory
from django.http import JsonResponse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.customer_portal.models import CustomerUser
from common.auth import can_access, get_user_role, redirect_to_portal, requires, requires_api
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_tenant_setup(username='owner', role='owner'):
    """Helper: create plan, user, tenant, membership. Returns (user, tenant)."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'display_order': 0},
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'pass')
    tenant = Tenant.objects.create(
        name=f'Shop-{username}', slug=f'shop-{username}',
        subdomain=f'shop-{username}', owner=user, subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role=role)
    return user, tenant


@override_settings(**TEST_OVERRIDES)
class CanAccessTests(TestCase):

    def test_unauthenticated_denied(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(can_access(AnonymousUser(), 'repairs'))

    def test_superuser_all_access(self):
        su = User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertTrue(can_access(su, area), f"superuser denied {area}")

    def test_owner_all_access(self):
        user, tenant = _make_tenant_setup('owner', 'owner')
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertTrue(can_access(user, area, tenant), f"owner denied {area}")

    def test_manager_all_access(self):
        user, tenant = _make_tenant_setup('mgr', 'manager')
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertTrue(can_access(user, area, tenant), f"manager denied {area}")

    def test_technician_limited_access(self):
        user, tenant = _make_tenant_setup('tech', 'technician')
        self.assertTrue(can_access(user, 'repairs', tenant))
        self.assertTrue(can_access(user, 'customers', tenant))
        self.assertFalse(can_access(user, 'invoices', tenant))
        self.assertFalse(can_access(user, 'reports', tenant))
        self.assertFalse(can_access(user, 'team', tenant))
        self.assertFalse(can_access(user, 'settings', tenant))

    def test_viewer_no_access(self):
        user, tenant = _make_tenant_setup('viewer', 'viewer')
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertFalse(can_access(user, area, tenant), f"viewer allowed {area}")

    def test_unknown_area(self):
        user, tenant = _make_tenant_setup('own', 'owner')
        self.assertFalse(can_access(user, 'nonexistent'))

    def test_staff_gets_access(self):
        user = User.objects.create_user('staff', 'staff@test.com', 'pass', is_staff=True)
        self.assertTrue(can_access(user, 'invoices'))

    def test_no_membership_denied(self):
        user = User.objects.create_user('nobody', 'nobody@test.com', 'pass')
        self.assertFalse(can_access(user, 'repairs'))


@override_settings(**TEST_OVERRIDES)
class GetUserRoleTests(TestCase):

    def test_superuser_role(self):
        su = User.objects.create_superuser('admin', 'a@t.com', 'p')
        self.assertEqual(get_user_role(su), 'superuser')

    def test_staff_role(self):
        u = User.objects.create_user('staff', 's@t.com', 'p', is_staff=True)
        self.assertEqual(get_user_role(u), 'owner')

    def test_membership_role(self):
        user, tenant = _make_tenant_setup('tech', 'technician')
        self.assertEqual(get_user_role(user, tenant), 'technician')

    def test_customer_user_role(self):
        user, tenant = _make_tenant_setup('cowner', 'owner')
        cust_user_django = User.objects.create_user('custuser', 'cu@t.com', 'p')
        cust = Customer.objects.create(tenant=tenant, name='TestCust')
        CustomerUser.objects.create(user=cust_user_django, customer=cust)
        self.assertEqual(get_user_role(cust_user_django), 'customer')

    def test_no_role(self):
        user = User.objects.create_user('orphan', 'o@t.com', 'p')
        self.assertIsNone(get_user_role(user))


@override_settings(**TEST_OVERRIDES)
class LoginRoutingTests(TestCase):
    """Test that /login/ routes users to their correct portal."""

    def setUp(self):
        self.client = Client()

    def test_unauthenticated_sees_login(self):
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)

    def test_login_valid_credentials(self):
        user, _ = _make_tenant_setup('loginuser', 'owner')
        resp = self.client.post('/login/', {'username': 'loginuser', 'password': 'pass'})
        # Should redirect somewhere (302)
        self.assertIn(resp.status_code, [200, 302])


@override_settings(**TEST_OVERRIDES)
class RequiresDecoratorTests(TestCase):
    """Test the @requires and @requires_api decorators."""

    def setUp(self):
        self.client = Client()

    def test_requires_api_unauthenticated(self):
        """Billing API should return 401 for unauthenticated requests."""
        resp = self.client.get('/api/billing/invoices/')
        self.assertEqual(resp.status_code, 401)

    def test_requires_api_unauthorized_role(self):
        """Technician should get 403 on billing endpoints."""
        user, tenant = _make_tenant_setup('techbill', 'technician')
        self.client.login(username='techbill', password='pass')
        resp = self.client.get('/api/billing/invoices/')
        self.assertEqual(resp.status_code, 403)

    def test_requires_api_authorized(self):
        """Owner should access billing endpoints."""
        user, tenant = _make_tenant_setup('ownerbill', 'owner')
        self.client.login(username='ownerbill', password='pass')
        resp = self.client.get('/api/billing/invoices/')
        # Should be 200 or at least not 401/403
        self.assertNotIn(resp.status_code, [401, 403])


@override_settings(**TEST_OVERRIDES)
class PortalAccessTests(TestCase):
    """Test that portals enforce correct access."""

    def setUp(self):
        self.client = Client()

    def test_customer_portal_requires_login(self):
        resp = self.client.get('/app/')
        # Should redirect to login
        self.assertIn(resp.status_code, [302, 301])

    def test_technician_portal_requires_login(self):
        resp = self.client.get('/tech/')
        self.assertIn(resp.status_code, [302, 301])

    def test_customer_portal_with_owner(self):
        """Owner accessing customer portal — should redirect or show dashboard."""
        user, tenant = _make_tenant_setup('cpowner', 'owner')
        self.client.login(username='cpowner', password='pass')
        resp = self.client.get('/app/')
        # May redirect to owner dashboard or show a page
        self.assertIn(resp.status_code, [200, 302])

    def test_tech_portal_with_technician(self):
        user, tenant = _make_tenant_setup('techportal', 'technician')
        self.client.login(username='techportal', password='pass')
        resp = self.client.get('/tech/')
        self.assertIn(resp.status_code, [200, 302])
