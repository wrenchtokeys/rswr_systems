"""
CODE-138 Regression: Referral/rewards pages used wrong base template.

Both customer_portal/referrals/dashboard.html and
customer_portal/referrals/rewards.html extended `base.html` (the
admin/staff base) instead of `customer_portal/base_customer.html`.

Customers visiting /app/rewards/ got the admin nav bar — a jarring UX
disconnect with the rest of the customer portal.

Fix: changed extends tag to `customer_portal/base_customer.html` and
removed redundant inline Tailwind CDN blocks (already loaded by base_customer.html).
"""

import os

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from tests.helpers import make_tenant

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'templates',
)

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _read_template(*path_parts):
    path = os.path.join(TEMPLATE_DIR, *path_parts)
    with open(path, 'r') as f:
        return f.read()


class ReferralTemplateBaseTest(TestCase):
    """Ensure referral/reward templates extend the customer portal base."""

    def test_dashboard_extends_customer_base(self):
        """referrals/dashboard.html must extend customer_portal/base_customer.html."""
        content = _read_template('customer_portal', 'referrals', 'dashboard.html')
        self.assertIn(
            "extends 'customer_portal/base_customer.html'",
            content,
            "dashboard.html should extend customer_portal/base_customer.html, not base.html",
        )

    def test_dashboard_does_not_extend_admin_base(self):
        """referrals/dashboard.html must NOT extend base.html (admin base)."""
        content = _read_template('customer_portal', 'referrals', 'dashboard.html')
        # Ensure it's not using the admin/staff base (which lacks the customer navbar)
        self.assertNotIn(
            "extends 'base.html'",
            content,
            "dashboard.html should NOT extend base.html — customers would see admin nav",
        )
        self.assertNotIn(
            'extends "base.html"',
            content,
        )

    def test_rewards_extends_customer_base(self):
        """referrals/rewards.html must extend customer_portal/base_customer.html."""
        content = _read_template('customer_portal', 'referrals', 'rewards.html')
        self.assertIn(
            "extends 'customer_portal/base_customer.html'",
            content,
            "rewards.html should extend customer_portal/base_customer.html, not base.html",
        )

    def test_rewards_does_not_extend_admin_base(self):
        """referrals/rewards.html must NOT extend base.html (admin base)."""
        content = _read_template('customer_portal', 'referrals', 'rewards.html')
        self.assertNotIn(
            "extends 'base.html'",
            content,
            "rewards.html should NOT extend base.html — customers would see admin nav",
        )
        self.assertNotIn(
            'extends "base.html"',
            content,
        )


@override_settings(**TEST_OVERRIDES)
class ReferralPageRenderTest(TestCase):
    """End-to-end: rewards page renders with customer portal nav, not admin nav."""

    def setUp(self):
        self.owner_user, self.tenant = make_tenant('Rewards Test Shop', 'rewards_owner')

        # Customer portal user
        self.customer_user_auth = User.objects.create_user(
            username='test_rewards_customer',
            email='rewards_customer@example.com',
            password='testpass123',
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Rewards Test Co',
            email='company@example.com',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.customer_user_auth,
            customer=self.customer,
            is_primary_contact=True,
        )

        self.client = Client(HTTP_HOST='testserver')

    def test_rewards_page_has_customer_portal_nav(self):
        """GET /app/rewards/ should render the customer portal nav, not admin nav."""
        self.client.login(username='test_rewards_customer', password='testpass123')
        # Patch tenant middleware by setting session tenant
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        response = self.client.get('/app/rewards/', follow=True)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Customer portal nav elements (from base_customer.html)
        self.assertIn('My Repairs', content,
                      "Customer portal nav should include 'My Repairs' link")
        # Should NOT have admin-specific elements
        self.assertNotIn('Django administration', content)
        self.assertNotIn('Admin Site', content)
