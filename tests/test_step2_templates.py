"""
Smoke tests for Step 2: One Base Template (base_app.html).

Verifies that tech portal pages render with the correct base template
and nav shows the right links based on user role.
"""
from django.test import TestCase, RequestFactory
from django.template import Template, Context, RequestContext
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan


class BaseAppTemplateTests(TestCase):
    """Test that base_app.html exists and renders."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        cls.owner_user = User.objects.create_user('tpl_owner', 'tpl_owner@test.com', 'pass')
        cls.tenant = Tenant.objects.create(
            name='Template Shop', slug='template-shop', subdomain='template-shop',
            owner=cls.owner_user, plan='trial', subscription_plan=cls.plan,
        )
        TenantMembership.objects.create(tenant=cls.tenant, user=cls.owner_user, role='owner')

    def test_base_app_template_exists(self):
        """base_app.html should be loadable."""
        from django.template.loader import get_template
        tpl = get_template('base_app.html')
        self.assertIsNotNone(tpl)

    def test_base_app_has_nav_links(self):
        """Rendered template should contain nav links."""
        from django.template.loader import render_to_string
        factory = RequestFactory()
        request = factory.get('/')
        request.user = self.owner_user
        request.tenant = self.tenant
        # Need to set resolver_match
        from django.urls import resolve
        request.resolver_match = resolve('/')

        html = render_to_string('base_app.html', {
            'user_can_repairs': True,
            'user_can_customers': True,
            'user_can_invoices': True,
            'user_can_settings': True,
            'tenant': self.tenant,
        }, request=request)
        self.assertIn('Dashboard', html)
        self.assertIn('Repairs', html)
        self.assertIn('Customers', html)


class TechTemplatesExtendBaseApp(TestCase):
    """Verify tech portal templates extend base_app.html."""

    def test_tech_templates_extend_base_app(self):
        """All tech portal templates should extend base_app.html."""
        import os
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates', 'technician_portal')
        template_dir = os.path.abspath(template_dir)

        for root, dirs, files in os.walk(template_dir):
            for f in files:
                if f.endswith('.html') and f != '__init__.html':
                    filepath = os.path.join(root, f)
                    # Skip includes
                    if '/includes/' in filepath:
                        continue
                    with open(filepath) as fh:
                        first_line = fh.readline().strip()
                    rel = os.path.relpath(filepath, template_dir)
                    self.assertIn(
                        'base_app.html', first_line,
                        f"Template {rel} should extend base_app.html, got: {first_line}"
                    )
