"""
Smoke tests for Step 5: Owner Nav Update.

Nav should be: Dashboard | Repairs | Customers | Invoices | Settings
No "Tech Portal" link. No "Billing" standalone link (it's "Invoices" now).
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner


class OwnerNavTests(TestCase):
    """Owner nav should show the right items."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )

    def setUp(self):
        result = create_tenant_with_owner(
            business_name='Nav Test Shop', email='navtest@test.com',
            password='testpass123!', first_name='Nav', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        # Use force_login — create_tenant_with_owner uses first_name as username,
        # not email, so client.login(username=email) would fail.
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_owner_dashboard_has_correct_nav_items(self):
        """Owner dashboard should show Dashboard, Repairs, Customers, Invoices, Settings."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Dashboard', content)
        self.assertIn('Repairs', content)
        self.assertIn('Customers', content)
        self.assertIn('Invoices', content)
        self.assertIn('Settings', content)

    def test_owner_dashboard_no_tech_portal_link(self):
        """Owner dashboard should NOT have a 'Tech Portal' nav link."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('Tech Portal', content)

    def test_owner_can_navigate_to_repairs(self):
        """Owner should be able to access /tech/repairs/ (repair list)."""
        response = self.client.get('/tech/repairs/')
        self.assertEqual(response.status_code, 200)

    def test_owner_can_navigate_to_customers(self):
        """Owner should be able to access /tech/customers/ (customer list)."""
        response = self.client.get('/tech/customers/')
        self.assertEqual(response.status_code, 200)

    def test_tech_portal_pages_use_base_app_template(self):
        """Tech portal pages should render with the base_app.html nav."""
        response = self.client.get('/tech/repairs/')
        content = response.content.decode()
        # base_app.html has the unified nav with these items
        self.assertIn('RS Systems', content)
        # Should NOT have old base.html nav elements
        self.assertNotIn('RS Systems - Technician Portal', content)
