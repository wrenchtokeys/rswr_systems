"""
Regression tests for CODE-169:
award_completion_points() awarded points to the first-created CustomerUser
instead of the primary contact.

Root Cause:
    In Repair.award_completion_points():
        customer_user = customer_users.first()
    CustomerUser has no default ordering, so .first() returns the record
    with the lowest PK (first created). When a customer has multiple portal
    users (e.g. owner + dispatcher), the first-created account received all
    the reward points — even if they weren't the primary contact.

Fix:
    Prefer the primary contact:
        customer_user = (
            customer_users.filter(is_primary_contact=True).first()
            or customer_users.first()
        )

Tests verify:
 - With a single CustomerUser: points go to them (unchanged)
 - With multiple CustomerUsers: points go to the primary contact
 - If no primary is set: fall back to first CustomerUser (graceful)
 - Primary contact flag changes: subsequent completions go to new primary
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
    owner = User.objects.create_user(
        f"owner_{slug}", f"owner_{slug}@test.com", "Pass123!"
    )
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner,
        plan="trial", trial_started_at=timezone.now(),
    )
    TenantMembership.objects.create(
        user=owner, tenant=tenant, role="owner", is_active=True
    )
    return owner, tenant


def _make_tech(tenant, suffix):
    u = User.objects.create_user(
        f"tech_{tenant.slug}_{suffix}",
        f"tech{suffix}@{tenant.slug}.com",
        "Pass123!",
    )
    tech = Technician.objects.create(
        user=u, tenant=tenant, is_active=True, can_repair=True
    )
    TenantMembership.objects.create(
        user=u, tenant=tenant, role="technician", is_active=True
    )
    return tech


def _make_customer(tenant, name="Test Fleet"):
    return Customer.objects.create(
        tenant=tenant, name=name, customer_type="FLEET"
    )


def _make_customer_user(customer, email, is_primary=False):
    user = User.objects.create_user(
        email.replace("@", "_at_").replace(".", "_"),
        email,
        "Pass123!",
    )
    return CustomerUser.objects.create(
        user=user, customer=customer, is_primary_contact=is_primary
    )


def _make_repair(tenant, tech, customer, status="APPROVED"):
    return Repair.objects.create(
        tenant=tenant,
        technician=tech,
        customer=customer,
        unit_number="UNIT-001",
        damage_type="Chip",
        queue_status=status,
    )


def _get_points(customer_user):
    try:
        return Reward.objects.get(customer_user=customer_user).points
    except Reward.DoesNotExist:
        return 0


class AwardPointsToPrimaryContactTest(TestCase):
    """Points must go to the primary contact, not just the first CustomerUser."""

    def setUp(self):
        _, self.tenant = _make_tenant("Shop Alpha", "alpha169")
        self.tech = _make_tech(self.tenant, "1")
        self.customer = _make_customer(self.tenant)

    # -----------------------------------------------------------------
    # 1. Single CustomerUser (baseline — must still work as before)
    # -----------------------------------------------------------------
    def test_single_customer_user_receives_points(self):
        """Single CustomerUser (primary or not) always gets the points."""
        cu = _make_customer_user(self.customer, "sole@alpha.com", is_primary=True)

        r = _make_repair(self.tenant, self.tech, self.customer)
        r.queue_status = "COMPLETED"
        r.save()

        self.assertEqual(_get_points(cu), 50)

    # -----------------------------------------------------------------
    # 2. Multiple CustomerUsers — primary contact must win
    # -----------------------------------------------------------------
    def test_primary_contact_receives_points_when_multiple_users_exist(self):
        """
        When a customer has multiple portal users, points go to the
        primary contact, not the first-created non-primary user.
        """
        # Create a non-primary user first (lower PK → old code gave them points)
        first_cu = _make_customer_user(
            self.customer, "first_created@alpha.com", is_primary=False
        )
        # Create the actual primary contact second (higher PK)
        primary_cu = _make_customer_user(
            self.customer, "primary@alpha.com", is_primary=True
        )

        r = _make_repair(self.tenant, self.tech, self.customer)
        r.queue_status = "COMPLETED"
        r.save()

        # Primary contact should have the points
        self.assertEqual(
            _get_points(primary_cu),
            50,
            "Primary contact must receive 50 points for completed repair",
        )
        # First-created non-primary must NOT have received any points
        self.assertEqual(
            _get_points(first_cu),
            0,
            "Non-primary contact must not receive points",
        )

    # -----------------------------------------------------------------
    # 3. No primary set — fall back to first (graceful)
    # -----------------------------------------------------------------
    def test_fallback_to_first_when_no_primary_set(self):
        """
        If no CustomerUser has is_primary_contact=True, fall back to first.
        This prevents NoneType errors on customers where primary was never set.
        """
        cu1 = _make_customer_user(
            self.customer, "first@alpha.com", is_primary=False
        )
        cu2 = _make_customer_user(
            self.customer, "second@alpha.com", is_primary=False
        )

        r = _make_repair(self.tenant, self.tech, self.customer)
        r.queue_status = "COMPLETED"
        r.save()

        # Exactly one of them should have received points (the fallback path)
        total_points = _get_points(cu1) + _get_points(cu2)
        self.assertEqual(
            total_points,
            50,
            "Exactly 50 points must be awarded to one user even without a primary",
        )

    # -----------------------------------------------------------------
    # 4. Primary changes between completions
    # -----------------------------------------------------------------
    def test_new_primary_gets_points_after_reassignment(self):
        """
        If the primary contact changes, subsequent repair completions must
        award points to the NEW primary.
        """
        original_primary = _make_customer_user(
            self.customer, "original_primary@alpha.com", is_primary=True
        )
        new_primary = _make_customer_user(
            self.customer, "new_primary@alpha.com", is_primary=False
        )

        # First repair — points go to original_primary
        r1 = _make_repair(self.tenant, self.tech, self.customer)
        r1.queue_status = "COMPLETED"
        r1.save()

        self.assertEqual(_get_points(original_primary), 50)
        self.assertEqual(_get_points(new_primary), 0)

        # Swap primary contact
        original_primary.is_primary_contact = False
        original_primary.save()
        new_primary.is_primary_contact = True
        new_primary.save()

        # Second repair — points should go to new_primary
        r2 = _make_repair(self.tenant, self.tech, self.customer)
        r2.unit_number = "UNIT-002"
        r2.queue_status = "COMPLETED"
        r2.save()

        self.assertEqual(
            _get_points(new_primary),
            50,
            "Points after primary swap must go to the new primary",
        )
        # original_primary should still only have 50 (not 100)
        self.assertEqual(
            _get_points(original_primary),
            50,
            "Original primary must not receive points after being demoted",
        )

    # -----------------------------------------------------------------
    # 5. Multi-customer-user scenario — milestone bonus goes to primary
    # -----------------------------------------------------------------
    def test_milestone_bonus_goes_to_primary_contact(self):
        """Milestone bonuses must also be awarded to the primary contact."""
        non_primary = _make_customer_user(
            self.customer, "dispatcher@alpha.com", is_primary=False
        )
        primary = _make_customer_user(
            self.customer, "manager@alpha.com", is_primary=True
        )

        # Complete 5 repairs to trigger the milestone bonus
        for i in range(5):
            r = _make_repair(self.tenant, self.tech, self.customer)
            r.unit_number = f"UNIT-{i:03d}"
            r.queue_status = "COMPLETED"
            r.save()

        # primary: 4×50 + (50+250) = 500
        self.assertEqual(
            _get_points(primary),
            500,
            "Primary should have 4×50 base + 1×300 (5th milestone) = 500",
        )
        # non_primary: nothing
        self.assertEqual(
            _get_points(non_primary),
            0,
            "Non-primary must not receive milestone bonus",
        )
