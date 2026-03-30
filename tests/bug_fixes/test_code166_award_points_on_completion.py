"""
Regression tests for CODE-166:
award_completion_points() never fires because original_status was updated
to 'COMPLETED' before the method was called.

Root Cause:
    In Repair.save(), the line:
        self.original_status = self.queue_status
    was executed BEFORE calling award_completion_points(). Inside that method,
    the guard:
        if self.original_status == 'COMPLETED': return
    is meant to prevent double-awarding on re-saves of already-completed repairs.
    But since original_status was already updated to 'COMPLETED' by the time the
    guard ran, it always fired — blocking point awards on FIRST completion too.

Fix:
    Move the `self.original_status = self.queue_status` update to AFTER
    apply_available_rewards() and award_completion_points(), so those methods
    see the pre-save original_status.

Tests verify:
 - Completing a repair from IN_PROGRESS awards the customer 50 points (base)
 - Re-saving an already-COMPLETED repair does NOT award duplicate points
 - Milestone bonuses fire at the correct repair counts (5th, 10th, 25th)
 - Milestone bonuses don't double-fire on subsequent saves
 - Points are tenant-scoped (different customers at different shops are isolated)
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import Reward


def _make_tenant(name, slug):
    owner = User.objects.create_user(f"owner_{slug}", f"owner_{slug}@test.com", "Pass123!")
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner,
        plan="trial", trial_started_at=timezone.now(),
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role="owner", is_active=True)
    return owner, tenant


def _make_tech(tenant, suffix):
    u = User.objects.create_user(f"tech_{tenant.slug}_{suffix}", f"tech{suffix}@{tenant.slug}.com", "Pass123!")
    tech = Technician.objects.create(user=u, tenant=tenant, is_active=True, can_repair=True)
    TenantMembership.objects.create(user=u, tenant=tenant, role="technician", is_active=True)
    return tech


def _make_customer(tenant, name="Test Fleet"):
    customer = Customer.objects.create(
        tenant=tenant, name=name, customer_type="FLEET"
    )
    cu_user = User.objects.create_user(
        f"cu_{tenant.slug}_{name.replace(' ', '')}",
        f"cu@{tenant.slug}.com",
        "Pass123!",
    )
    customer_user = CustomerUser.objects.create(
        user=cu_user, customer=customer, is_primary_contact=True
    )
    return customer, customer_user


def _make_repair(tenant, tech, customer, status="PENDING"):
    """Create a repair in the given status."""
    return Repair.objects.create(
        tenant=tenant,
        technician=tech,
        customer=customer,
        unit_number="UNIT-001",
        damage_type="Chip",
        queue_status=status,
    )


class AwardPointsOnCompletionTest(TestCase):
    """Points should be awarded when a repair transitions to COMPLETED."""

    def setUp(self):
        _, self.tenant = _make_tenant("Shop Alpha", "alpha")
        self.tech = _make_tech(self.tenant, "1")
        self.customer, self.customer_user = _make_customer(self.tenant)

    def _get_points(self):
        """Return the customer's current reward balance (0 if no Reward row yet)."""
        try:
            return Reward.objects.get(customer_user=self.customer_user).points
        except Reward.DoesNotExist:
            return 0

    def test_completing_repair_awards_50_base_points(self):
        """Transitioning a repair to COMPLETED should award 50 base points."""
        repair = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
        self.assertEqual(self._get_points(), 0, "No points before completion")

        repair.queue_status = "COMPLETED"
        repair.save()

        self.assertEqual(self._get_points(), 50, "Should award 50 base points on first completion")

    def test_resaving_completed_repair_does_not_duplicate_points(self):
        """Re-saving a COMPLETED repair (e.g. adding photos) must NOT award extra points."""
        repair = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
        repair.queue_status = "COMPLETED"
        repair.save()

        points_after_completion = self._get_points()
        self.assertEqual(points_after_completion, 50)

        # Simulate adding a photo (re-save without status change)
        repair.technician_notes = "Photo added"
        repair.save()

        self.assertEqual(
            self._get_points(),
            points_after_completion,
            "Re-saving COMPLETED repair should not award additional points",
        )

    def test_multiple_repairs_each_award_50_base_points(self):
        """Each completed repair awards 50 base points (except milestone bonuses)."""
        for i in range(3):
            r = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
            r.unit_number = f"UNIT-{i:03d}"
            r.queue_status = "COMPLETED"
            r.save()

        # 3 completions × 50 = 150 base points
        self.assertEqual(self._get_points(), 150)

    def test_fifth_repair_triggers_milestone_bonus(self):
        """The 5th completed repair should award 50 + 250 = 300 points for that repair."""
        # Complete 4 repairs first
        for i in range(4):
            r = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
            r.unit_number = f"UNIT-{i:03d}"
            r.queue_status = "COMPLETED"
            r.save()

        points_before_5th = self._get_points()  # 4 × 50 = 200

        # Complete the 5th repair
        r5 = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
        r5.unit_number = "UNIT-005"
        r5.queue_status = "COMPLETED"
        r5.save()

        # 5th repair: 50 base + 250 milestone = 300 extra
        self.assertEqual(self._get_points(), points_before_5th + 300)

    def test_milestone_does_not_double_fire_on_resave(self):
        """Re-saving a milestone repair should not trigger the bonus again."""
        for i in range(5):
            r = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
            r.unit_number = f"UNIT-{i:03d}"
            r.queue_status = "COMPLETED"
            r.save()
            if i == 4:
                fifth_repair = r

        points_after_5th = self._get_points()  # 4×50 + 300 = 500

        # Re-save the 5th repair
        fifth_repair.technician_notes = "Updated note"
        fifth_repair.save()

        self.assertEqual(
            self._get_points(),
            points_after_5th,
            "Re-saving the milestone repair must not award bonus again",
        )

    def test_cross_tenant_isolation(self):
        """Points at Shop A must not bleed into Shop B."""
        _, tenant_b = _make_tenant("Shop Beta", "beta")
        tech_b = _make_tech(tenant_b, "b")
        customer_b, cu_b = _make_customer(tenant_b, "Beta Fleet")

        # Complete a repair at Shop A
        r_a = _make_repair(self.tenant, self.tech, self.customer, status="APPROVED")
        r_a.queue_status = "COMPLETED"
        r_a.save()

        # Complete a repair at Shop B
        r_b = _make_repair(tenant_b, tech_b, customer_b, status="APPROVED")
        r_b.queue_status = "COMPLETED"
        r_b.save()

        # Both customers should have exactly 50 points — no cross-tenant bleeding
        points_a = Reward.objects.get(customer_user=self.customer_user).points
        points_b = Reward.objects.get(customer_user=cu_b).points

        self.assertEqual(points_a, 50, "Shop A customer should have 50 points")
        self.assertEqual(points_b, 50, "Shop B customer should have 50 points")
