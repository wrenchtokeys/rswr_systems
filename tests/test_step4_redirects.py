"""
Smoke tests for Step 4: Fix Redirects.

No redirect('home') for authenticated users — always redirect to their portal.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner


class RedirectToPortalTests(TestCase):
    """redirect_to_portal() sends users to the correct place."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )

    def test_owner_redirects_to_owner_dashboard(self):
        from common.auth import redirect_to_portal
        result = create_tenant_with_owner(
            business_name='Redirect Shop', email='redirect@test.com',
            password='testpass123!', first_name='R', last_name='Owner',
        )
        resp = redirect_to_portal(result['user'])
        self.assertEqual(resp.status_code, 302)
        self.assertIn('owner', resp.url)

    def test_technician_redirects_to_tech_dashboard(self):
        from common.auth import redirect_to_portal
        result = create_tenant_with_owner(
            business_name='Tech Redirect Shop', email='techredirect@test.com',
            password='testpass123!', first_name='T', last_name='Owner',
        )
        # Create a tech-only user
        tech_user = User.objects.create_user('techonly', 'techonly@test.com', 'pass')
        TenantMembership.objects.create(tenant=result['tenant'], user=tech_user, role='technician')
        resp = redirect_to_portal(tech_user)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('tech', resp.url)

    def test_anonymous_redirects_to_login(self):
        from common.auth import redirect_to_portal
        from django.contrib.auth.models import AnonymousUser
        resp = redirect_to_portal(AnonymousUser())
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)


class NoRedirectHomeForAuthenticatedTests(TestCase):
    """Grep-verified: no redirect('home') should exist for authenticated users."""

    def test_no_redirect_home_in_decorators(self):
        """Technician decorator should not redirect to 'home'."""
        import inspect
        from apps.technician_portal.decorators import technician_required
        source = inspect.getsource(technician_required)
        self.assertNotIn("redirect('home')", source)

    def test_redirect_to_portal_exists(self):
        """common.auth.redirect_to_portal should exist."""
        from common.auth import redirect_to_portal
        self.assertTrue(callable(redirect_to_portal))
