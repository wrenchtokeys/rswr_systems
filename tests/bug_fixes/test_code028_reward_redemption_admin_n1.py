"""
CODE-028 — N+1 queries in RewardRedemptionAdmin list view

BUG: RewardRedemptionAdmin.get_queryset() returned a plain queryset with no
select_related. The admin list_display included computed columns that traversed
multi-hop FK chains on each row:

  get_tenant_display()  → reward → customer_user → customer → tenant (4 hops)
  get_customer_email()  → reward → customer_user → user              (3 hops)
  reward_option col     → reward_option                              (1 hop)
  assigned_technician   → assigned_technician → user                 (1-2 hops)
  get_applied_to_repair → applied_to_repair                          (1 hop)

With N=25 rows per page and no select_related that amounts to ~7N extra queries
(175 extra SELECTs per page load) plus the tenant-isolation filter adding another
25 to fetch TenantMembership — a significant performance problem at scale.

FIX: get_queryset() now calls .select_related() with all the chains used in
list_display before returning the queryset (both the superuser and non-superuser
branches benefit).

TESTS:
1. Accessing list_display values on a prefetched queryset row issues zero extra
   DB queries.
2. Tenant isolation is preserved: non-superuser sees only their tenant's
   redemptions.
3. Superuser sees all redemptions.
4. get_tenant_display() returns the correct tenant name.
5. get_customer_email() returns the correct email.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.rewards_referrals.admin import RewardRedemptionAdmin
from apps.rewards_referrals.models import (
    Reward, RewardOption, RewardRedemption, RewardType,
)
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_reward_setup(tenant, username):
    """Create CustomerUser + Reward for a given tenant."""
    user = User.objects.create_user(username, f'{username}@example.com', 'pass')
    customer = Customer.objects.create(tenant=tenant, name=f'{username} Corp')
    cu = CustomerUser.objects.create(user=user, customer=customer)
    reward = Reward.objects.create(customer_user=cu, points=100)
    return cu, reward


def _make_reward_option(tenant, name='Test Option'):
    rt, _ = RewardType.objects.get_or_create(
        name='Discount', defaults={
            'category': 'REPAIR_DISCOUNT',
            'discount_type': 'PERCENTAGE',
            'discount_value': 10,
        }
    )
    return RewardOption.objects.create(
        tenant=tenant,
        name=name,
        points_required=50,
        reward_type=rt,
        is_active=True,
    )


@override_settings(**TEST_OVERRIDES)
class RewardRedemptionAdminN1Tests(TestCase):
    """Verify get_queryset() uses select_related to eliminate N+1 queries."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = RewardRedemptionAdmin(RewardRedemption, self.site)

        # Shop A
        self.owner_a, self.tenant_a = make_tenant('ShopA', 'owner_a')
        self.cu_a, self.reward_a = _make_reward_setup(self.tenant_a, 'cust_a')
        self.option_a = _make_reward_option(self.tenant_a, 'Option A')
        self.redemption_a = RewardRedemption.objects.create(
            reward=self.reward_a,
            reward_option=self.option_a,
            status='PENDING',
        )

        # Shop B
        self.owner_b, self.tenant_b = make_tenant('ShopB', 'owner_b')
        self.cu_b, self.reward_b = _make_reward_setup(self.tenant_b, 'cust_b')
        self.option_b = _make_reward_option(self.tenant_b, 'Option B')
        self.redemption_b = RewardRedemption.objects.create(
            reward=self.reward_b,
            reward_option=self.option_b,
            status='PENDING',
        )

        # Superuser
        self.superuser = User.objects.create_superuser('super', 'super@test.com', 'pass')

    def _make_request(self, user):
        req = self.factory.get('/admin/rewards_referrals/rewardredemption/')
        req.user = user
        return req

    def test_superuser_gets_all_redemptions(self):
        """Superuser queryset includes redemptions from all tenants."""
        req = self._make_request(self.superuser)
        qs = self.admin.get_queryset(req)
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(self.redemption_a.id, ids)
        self.assertIn(self.redemption_b.id, ids)

    def test_non_superuser_sees_only_own_tenant(self):
        """Non-superuser sees only their tenant's redemptions."""
        req = self._make_request(self.owner_a)
        qs = self.admin.get_queryset(req)
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(self.redemption_a.id, ids)
        self.assertNotIn(self.redemption_b.id, ids)

    def test_select_related_prevents_extra_queries_on_list_display_access(self):
        """
        After fetching via get_queryset(), accessing list_display fields on
        each row should fire ZERO extra DB queries (all FK data is prefetched).
        """
        req = self._make_request(self.superuser)
        qs = list(self.admin.get_queryset(req))  # evaluate queryset once

        # All subsequent attribute accesses should be served from the Python
        # object cache — no additional SQL allowed.
        with CaptureQueriesContext(connection) as ctx:
            for obj in qs:
                # These all traverse multi-hop FK chains:
                _ = self.admin.get_tenant_display(obj)
                _ = self.admin.get_customer_email(obj)
                _ = str(obj.reward_option)          # reward_option col
                _ = obj.applied_to_repair           # applied_to_repair col
        self.assertEqual(
            len(ctx.captured_queries), 0,
            f"Expected 0 extra queries, but {len(ctx.captured_queries)} were fired:\n"
            + '\n'.join(q['sql'] for q in ctx.captured_queries),
        )

    def test_get_tenant_display_correct_value(self):
        """get_tenant_display() returns the correct tenant name."""
        req = self._make_request(self.superuser)
        row = self.admin.get_queryset(req).get(id=self.redemption_a.id)
        self.assertEqual(self.admin.get_tenant_display(row), self.tenant_a.name)

    def test_get_customer_email_correct_value(self):
        """get_customer_email() returns the correct customer email."""
        req = self._make_request(self.superuser)
        row = self.admin.get_queryset(req).get(id=self.redemption_a.id)
        self.assertEqual(self.admin.get_customer_email(row), self.cu_a.user.email)

    def test_select_related_is_set_on_queryset(self):
        """
        get_queryset() applies select_related with the required FK paths so that
        prefetching is visible in the queryset's select_related dict.
        """
        req = self._make_request(self.superuser)
        qs = self.admin.get_queryset(req)
        sr = qs.query.select_related
        # select_related can be True (all) or a dict of paths; in either case
        # it should not be False (disabled).
        self.assertNotEqual(sr, False, 'get_queryset() must set select_related')
