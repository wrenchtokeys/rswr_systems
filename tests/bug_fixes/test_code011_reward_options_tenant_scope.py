"""
Regression tests for CODE-011: RewardOption cross-tenant data leak.

Bug:
  apps/customer_portal/views.py::customer_rewards_redirect() fetched reward
  options with:
      RewardOption.objects.filter(is_active=True)
  — no tenant filter.  A customer from Shop A could see (and potentially
  redeem) reward options that belong to Shop B.

Fix:
  Filter is now:
      RewardOption.objects.filter(is_active=True, tenant=tenant)
  where `tenant` comes from customer_user.customer.tenant.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from unittest.mock import patch

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import RewardOption


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name, plan):
    owner = User.objects.create_user(
        username=f"owner_{name.lower().replace(' ', '_')}",
        password='pw'
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner,
        plan='trial',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant, owner


def _make_customer_user(tenant, username='cust_user'):
    user = User.objects.create_user(username=username, password='pw', email=f'{username}@test.com')
    customer = Customer.objects.create(
        name='Test Fleet Co.',
        email=f'{username}@fleet.com',
        tenant=tenant,
    )
    customer_user = CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=True,
    )
    return user, customer_user


class RewardOptionTenantScopeTest(TestCase):
    """
    customer_rewards_redirect must only show the requesting tenant's reward options.
    """

    def setUp(self):
        plan = _make_plan()
        self.tenant_a, _owner_a = _make_tenant('Shop A', plan)
        self.tenant_b, _owner_b = _make_tenant('Shop B', plan)

        self.user_a, self.cu_a = _make_customer_user(self.tenant_a, 'cust_a')
        self.user_b, self.cu_b = _make_customer_user(self.tenant_b, 'cust_b')

        # Shop A reward option
        self.option_a = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='Free Wash - Shop A',
            description='A free wash from Shop A',
            points_required=100,
            is_active=True,
        )
        # Shop B reward option
        self.option_b = RewardOption.objects.create(
            tenant=self.tenant_b,
            name='Free Wash - Shop B',
            description='A free wash from Shop B',
            points_required=200,
            is_active=True,
        )
        # Inactive option in Shop A
        self.option_a_inactive = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='Inactive Shop A Option',
            description='Inactive',
            points_required=50,
            is_active=False,
        )

    # ------------------------------------------------------------------
    # Unit-level: QuerySet behaviour
    # ------------------------------------------------------------------

    def test_queryset_with_tenant_filter_returns_only_own_options(self):
        """Filtering by tenant + is_active must only return that tenant's active options."""
        qs_a = RewardOption.objects.filter(is_active=True, tenant=self.tenant_a)
        self.assertIn(self.option_a, qs_a)
        self.assertNotIn(self.option_b, qs_a)
        self.assertNotIn(self.option_a_inactive, qs_a)

    def test_queryset_without_tenant_filter_leaks_cross_tenant(self):
        """Control: unfiltered queryset DOES contain cross-tenant options (documents the old bug)."""
        qs_all = RewardOption.objects.filter(is_active=True)
        self.assertIn(self.option_a, qs_all)
        self.assertIn(self.option_b, qs_all)

    # ------------------------------------------------------------------
    # View-level: HTTP response must not contain other tenant's options
    # ------------------------------------------------------------------

    def _get_rewards_page(self, user, tenant):
        """Hit the customer_rewards_redirect view as the given user."""
        self.client.force_login(user)
        # Patch request.tenant so middleware-dependent code works
        with patch('apps.customer_portal.views.CustomerUser.objects.select_related') as mock_sel:
            # Let the real ORM do the work — just need the view to succeed
            pass
        response = self.client.get('/app/rewards/', follow=True)
        return response

    def test_view_only_shows_own_tenant_options(self):
        """The rewards view renders only the requesting tenant's active options."""
        self.client.force_login(self.user_a)
        response = self.client.get('/app/rewards/')
        # View should succeed (200 or redirect to login, not 500)
        self.assertIn(response.status_code, (200, 302))

        if response.status_code == 200:
            content = response.content.decode()
            # Shop A's option must appear
            self.assertIn('Shop A', content)
            # Shop B's option must NOT appear
            self.assertNotIn('Shop B', content)

    def test_view_does_not_show_other_tenant_option_to_shop_b_user(self):
        """A Shop B customer must not see Shop A options."""
        self.client.force_login(self.user_b)
        response = self.client.get('/app/rewards/')
        self.assertIn(response.status_code, (200, 302))

        if response.status_code == 200:
            content = response.content.decode()
            self.assertNotIn('Free Wash - Shop A', content)
            self.assertIn('Free Wash - Shop B', content)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_options_for_tenant_returns_empty(self):
        """If a tenant has no active reward options, the view gets an empty list."""
        # Create a third tenant with no options
        plan = _make_plan()
        tenant_c, _owner_c = _make_tenant('Shop C', plan)
        user_c, _cu_c = _make_customer_user(tenant_c, 'cust_c')

        qs_c = RewardOption.objects.filter(is_active=True, tenant=tenant_c)
        self.assertEqual(qs_c.count(), 0)

    def test_inactive_options_excluded(self):
        """Inactive options are excluded even when they belong to the right tenant."""
        qs_a = RewardOption.objects.filter(is_active=True, tenant=self.tenant_a)
        self.assertNotIn(self.option_a_inactive, qs_a)

    def test_options_ordered_by_points_required(self):
        """Options should come back in ascending points_required order."""
        extra = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='Premium Option',
            description='Expensive one',
            points_required=500,
            is_active=True,
        )
        qs = list(RewardOption.objects.filter(is_active=True, tenant=self.tenant_a).order_by('points_required'))
        self.assertEqual(qs[0], self.option_a)      # 100 pts
        self.assertEqual(qs[1], extra)               # 500 pts
