"""
Smoke tests for Step 1: Unified permission system (common/auth.py).

Tests can_access(), @requires() decorator, and context processor.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User, Group, AnonymousUser
from django.http import HttpResponse
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan


class CanAccessTests(TestCase):
    """Test the can_access() single source of truth."""

    @classmethod
    def setUpTestData(cls):
        # Create a trial plan (may already exist from seed migration)
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        # Superuser
        cls.superuser = User.objects.create_superuser('super', 'super@test.com', 'pass')
        # Owner
        cls.owner_user = User.objects.create_user('owner', 'owner@test.com', 'pass')
        cls.tenant = Tenant.objects.create(
            name='Test Shop', slug='test-shop', subdomain='test-shop',
            owner=cls.owner_user, plan='trial', subscription_plan=cls.plan,
        )
        cls.owner_membership = TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.owner_user, role='owner'
        )
        # Manager
        cls.manager_user = User.objects.create_user('manager', 'mgr@test.com', 'pass')
        cls.manager_membership = TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.manager_user, role='manager'
        )
        # Technician
        cls.tech_user = User.objects.create_user('tech', 'tech@test.com', 'pass')
        cls.tech_membership = TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.tech_user, role='technician'
        )
        # Viewer (customer)
        cls.viewer_user = User.objects.create_user('viewer', 'viewer@test.com', 'pass')
        cls.viewer_membership = TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.viewer_user, role='viewer'
        )

    def test_superuser_can_access_everything(self):
        from common.auth import can_access
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertTrue(can_access(self.superuser, area), f"Superuser should access {area}")

    def test_owner_can_access_everything(self):
        from common.auth import can_access
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertTrue(can_access(self.owner_user, area, self.tenant), f"Owner should access {area}")

    def test_manager_can_access_everything(self):
        from common.auth import can_access
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertTrue(can_access(self.manager_user, area, self.tenant), f"Manager should access {area}")

    def test_technician_can_access_repairs_and_customers(self):
        from common.auth import can_access
        self.assertTrue(can_access(self.tech_user, 'repairs', self.tenant))
        self.assertTrue(can_access(self.tech_user, 'customers', self.tenant))

    def test_technician_cannot_access_invoices_reports_team_settings(self):
        from common.auth import can_access
        for area in ('invoices', 'reports', 'team', 'settings'):
            self.assertFalse(can_access(self.tech_user, area, self.tenant), f"Tech should NOT access {area}")

    def test_viewer_cannot_access_anything(self):
        from common.auth import can_access
        for area in ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings'):
            self.assertFalse(can_access(self.viewer_user, area, self.tenant), f"Viewer should NOT access {area}")


class RequiresDecoratorTests(TestCase):
    """Test the @requires() decorator."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        cls.owner_user = User.objects.create_user('owner2', 'owner2@test.com', 'pass')
        cls.tenant = Tenant.objects.create(
            name='Test Shop 2', slug='test-shop-2', subdomain='test-shop-2',
            owner=cls.owner_user, plan='trial', subscription_plan=cls.plan,
        )
        TenantMembership.objects.create(tenant=cls.tenant, user=cls.owner_user, role='owner')
        cls.tech_user = User.objects.create_user('tech2', 'tech2@test.com', 'pass')
        TenantMembership.objects.create(tenant=cls.tenant, user=cls.tech_user, role='technician')

    def setUp(self):
        self.factory = RequestFactory()

    def _make_request(self, user, tenant=None):
        request = self.factory.get('/fake/')
        request.user = user
        request.tenant = tenant
        # Mock session and messages
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))
        return request

    def test_requires_allows_owner(self):
        from common.auth import requires

        @requires('repairs')
        def my_view(request):
            return HttpResponse('OK')

        request = self._make_request(self.owner_user, self.tenant)
        response = my_view(request)
        self.assertEqual(response.status_code, 200)

    def test_requires_blocks_tech_from_settings(self):
        from common.auth import requires

        @requires('settings')
        def my_view(request):
            return HttpResponse('OK')

        request = self._make_request(self.tech_user, self.tenant)
        response = my_view(request)
        # Should redirect (302)
        self.assertEqual(response.status_code, 302)

    def test_requires_blocks_anonymous(self):
        from common.auth import requires

        @requires('repairs')
        def my_view(request):
            return HttpResponse('OK')

        request = self._make_request(AnonymousUser())
        response = my_view(request)
        self.assertEqual(response.status_code, 302)


class PermissionContextProcessorTests(TestCase):
    """Test the permission context processor."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        cls.owner_user = User.objects.create_user('owner3', 'owner3@test.com', 'pass')
        cls.tenant = Tenant.objects.create(
            name='Test Shop 3', slug='test-shop-3', subdomain='test-shop-3',
            owner=cls.owner_user, plan='trial', subscription_plan=cls.plan,
        )
        TenantMembership.objects.create(tenant=cls.tenant, user=cls.owner_user, role='owner')
        cls.tech_user = User.objects.create_user('tech3', 'tech3@test.com', 'pass')
        TenantMembership.objects.create(tenant=cls.tenant, user=cls.tech_user, role='technician')

    def setUp(self):
        self.factory = RequestFactory()

    def test_owner_gets_all_capabilities(self):
        from common.context_processors import portal_access
        request = self.factory.get('/')
        request.user = self.owner_user
        request.tenant = self.tenant
        ctx = portal_access(request)
        self.assertTrue(ctx.get('user_can_repairs'))
        self.assertTrue(ctx.get('user_can_customers'))
        self.assertTrue(ctx.get('user_can_invoices'))
        self.assertTrue(ctx.get('user_can_settings'))

    def test_tech_gets_limited_capabilities(self):
        from common.context_processors import portal_access
        request = self.factory.get('/')
        request.user = self.tech_user
        request.tenant = self.tenant
        ctx = portal_access(request)
        self.assertTrue(ctx.get('user_can_repairs'))
        self.assertTrue(ctx.get('user_can_customers'))
        self.assertFalse(ctx.get('user_can_invoices'))
        self.assertFalse(ctx.get('user_can_settings'))
