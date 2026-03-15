"""
Regression tests for CODE-031:
N+1 queries in RewardFulfillmentService.assign_technician().

Bug: The method iterated over all technicians and fired one
     Repair.objects.filter(technician=tech).count() per technician —
     O(N) queries for N technicians in a tenant.

Fix: Replaced the loop with a single annotated queryset that uses
     Count('repair', filter=~Q(...)) and order_by('active_repair_count')
     to pick the least-loaded technician in one DB round-trip.

Tests verify:
 - Correct technician is assigned (least active repairs)
 - Stable tie-break (lowest PK wins when workloads are equal)
 - Cross-tenant isolation (only same-tenant technicians are candidates)
 - Query count: ≤ 3 queries total regardless of technician count
"""

from django.test import TestCase
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.test.utils import CaptureQueriesContext
from django.db import connection

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import (
    Reward, RewardType, RewardOption, RewardRedemption,
)
from apps.rewards_referrals.services import RewardFulfillmentService, RewardService


def _make_tenant(name, slug):
    owner = User.objects.create_user(f"owner_{slug}", f"owner_{slug}@test.com", "Pass123!")
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner,
        plan="trial", trial_started_at=timezone.now(),
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role="owner", is_active=True)
    return owner, tenant


def _make_tech(tenant, suffix, can_repair=True):
    u = User.objects.create_user(f"tech_{tenant.slug}_{suffix}", f"tech{suffix}@{tenant.slug}.com", "Pass123!")
    tech = Technician.objects.create(user=u, tenant=tenant, is_active=True, can_repair=can_repair)
    TenantMembership.objects.create(user=u, tenant=tenant, role="technician", is_active=True)
    return tech


def _make_customer_user(tenant, suffix):
    customer = Customer.objects.create(
        tenant=tenant, name=f"Customer {suffix}", customer_type="FLEET"
    )
    u = User.objects.create_user(f"cu_{tenant.slug}_{suffix}", f"cu{suffix}@{tenant.slug}.com", "Pass123!")
    cu = CustomerUser.objects.create(user=u, customer=customer)
    return cu


def _make_reward_option(tenant):
    rt = RewardType.objects.create(
        name=f"Merch_{tenant.slug}", category="MERCHANDISE",
        discount_type="NONE", discount_value=0, is_active=True,
    )
    return RewardOption.objects.create(
        name=f"Donuts_{tenant.slug}", points_required=100,
        reward_type=rt, is_active=True, tenant=tenant,
    )


def _make_active_repair(tenant, customer_user, technician):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer_user.customer,
        technician=technician,
        unit_number="UNIT-1",
        cost=50,
        queue_status="IN_PROGRESS",
    )


class RewardFulfillmentLeastLoadedTest(TestCase):
    """assign_technician picks the technician with fewest active repairs."""

    def setUp(self):
        _, self.tenant = _make_tenant("Shop A", "shop_a_code31")
        self.tech_busy = _make_tech(self.tenant, "busy")
        self.tech_free = _make_tech(self.tenant, "free")

        self.cu = _make_customer_user(self.tenant, "main")
        self.reward_option = _make_reward_option(self.tenant)

        reward = Reward.objects.create(customer_user=self.cu, points=500)

        # Give tech_busy 2 active repairs, tech_free 0
        _make_active_repair(self.tenant, self.cu, self.tech_busy)
        _make_active_repair(self.tenant, self.cu, self.tech_busy)

        self.redemption = RewardRedemption.objects.create(
            reward=reward, reward_option=self.reward_option, status="PENDING"
        )

    def test_assigns_least_loaded_technician(self):
        """Should pick tech_free (0 active) over tech_busy (2 active)."""
        assigned = RewardFulfillmentService.assign_technician(self.redemption)
        self.assertIsNotNone(assigned)
        self.assertEqual(assigned.id, self.tech_free.id)

    def test_redemption_saved_with_assigned_tech(self):
        """assigned_technician FK is persisted to DB."""
        RewardFulfillmentService.assign_technician(self.redemption)
        self.redemption.refresh_from_db()
        self.assertIsNotNone(self.redemption.assigned_technician)
        self.assertEqual(self.redemption.assigned_technician.id, self.tech_free.id)


class RewardFulfillmentTiebreakerTest(TestCase):
    """When workloads are equal, stable PK-based tie-break applies."""

    def setUp(self):
        _, self.tenant = _make_tenant("Shop Tie", "shop_tie_code31")
        self.tech1 = _make_tech(self.tenant, "t1")  # lower PK
        self.tech2 = _make_tech(self.tenant, "t2")  # higher PK

        self.cu = _make_customer_user(self.tenant, "tie")
        self.reward_option = _make_reward_option(self.tenant)
        reward = Reward.objects.create(customer_user=self.cu, points=500)
        self.redemption = RewardRedemption.objects.create(
            reward=reward, reward_option=self.reward_option, status="PENDING"
        )

    def test_tiebreak_uses_lowest_pk(self):
        """With equal workloads, the technician with the lower PK is selected."""
        assigned = RewardFulfillmentService.assign_technician(self.redemption)
        self.assertIsNotNone(assigned)
        # The lower PK should win the tie
        lower_pk = min(self.tech1.id, self.tech2.id)
        self.assertEqual(assigned.id, lower_pk)


class RewardFulfillmentCrossTenantIsolationTest(TestCase):
    """Technicians from other tenants must never be candidates."""

    def setUp(self):
        _, self.tenant_a = _make_tenant("Shop Cross A", "shop_cross_a_c31")
        _, self.tenant_b = _make_tenant("Shop Cross B", "shop_cross_b_c31")

        # Tenant B has a very free technician — should never be assigned to A's redemption
        self.tech_a = _make_tech(self.tenant_a, "only")
        self.tech_b = _make_tech(self.tenant_b, "free")

        self.cu_a = _make_customer_user(self.tenant_a, "a")
        self.opt_a = _make_reward_option(self.tenant_a)
        reward_a = Reward.objects.create(customer_user=self.cu_a, points=500)
        self.redemption_a = RewardRedemption.objects.create(
            reward=reward_a, reward_option=self.opt_a, status="PENDING"
        )

    def test_only_same_tenant_technician_assigned(self):
        """Tenant A's redemption must only consider Tenant A's technicians."""
        assigned = RewardFulfillmentService.assign_technician(self.redemption_a)
        self.assertIsNotNone(assigned)
        self.assertEqual(assigned.id, self.tech_a.id)
        self.assertNotEqual(assigned.id, self.tech_b.id)
        self.assertEqual(assigned.tenant_id, self.tenant_a.id)


class RewardFulfillmentNoTechniciansTest(TestCase):
    """Returns None when tenant has no technicians."""

    def setUp(self):
        _, self.tenant = _make_tenant("Empty Shop", "empty_shop_c31")
        # No technicians created

        self.cu = _make_customer_user(self.tenant, "alone")
        self.opt = _make_reward_option(self.tenant)
        reward = Reward.objects.create(customer_user=self.cu, points=500)
        self.redemption = RewardRedemption.objects.create(
            reward=reward, reward_option=self.opt, status="PENDING"
        )

    def test_returns_none_with_no_technicians(self):
        assigned = RewardFulfillmentService.assign_technician(self.redemption)
        self.assertIsNone(assigned)


class RewardFulfillmentQueryCountTest(TestCase):
    """assign_technician must use a constant number of queries regardless of technician count."""

    def setUp(self):
        _, self.tenant = _make_tenant("Perf Shop", "perf_shop_c31")

        self.cu = _make_customer_user(self.tenant, "perf")
        self.opt = _make_reward_option(self.tenant)
        reward = Reward.objects.create(customer_user=self.cu, points=500)
        self.redemption = RewardRedemption.objects.create(
            reward=reward, reward_option=self.opt, status="PENDING"
        )

        # Create 5 technicians (old code fired 1 query per tech: 5+ queries)
        for i in range(5):
            _make_tech(self.tenant, f"p{i}")

    def test_query_count_is_bounded(self):
        """Should use ≤ 4 queries total (exists check + annotated select + save + notify)."""
        with CaptureQueriesContext(connection) as ctx:
            RewardFulfillmentService.assign_technician(self.redemption)
        # Old N+1 code fired 1 + 5 = 6 queries minimum. New code: at most 4.
        query_count = len(ctx.captured_queries)
        self.assertLessEqual(
            query_count,
            4,
            f"Expected ≤ 4 queries, got {query_count}:\n"
            + "\n".join(q["sql"][:120] for q in ctx.captured_queries),
        )
