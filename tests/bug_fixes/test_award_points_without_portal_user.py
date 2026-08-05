"""
Regression tests for customer-anchored loyalty:
points accrue to the Customer (company) even when NO portal account exists.

Background:
    Loyalty used to anchor on CustomerUser (portal accounts). Customers with
    no portal logins — the common case for walk-ins and small fleets — could
    never earn points, and shops couldn't show a balance for them.

    The re-anchor moved Reward/PointTransaction onto core.Customer.
    loyalty_hook now awards to service.customer directly; customer_user on
    PointTransaction is optional attribution only.

    (Replaces test_code169_award_points_to_primary_contact.py, which encoded
    the removed primary-contact routing behavior.)

Tests verify:
 - A Customer with ZERO CustomerUsers earns points_per_repair on repair
   completion (balance via LoyaltyService.get_balance; PointTransaction row
   has customer set and customer_user None)
 - A WALK_IN customer earns too
 - Re-saving an already-COMPLETED repair does not double-award
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import PointTransaction
from apps.rewards_referrals.services import LoyaltyService


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


def _make_customer(tenant, name="Test Fleet", customer_type="FLEET"):
    return Customer.objects.create(
        tenant=tenant, name=name, customer_type=customer_type
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


class AwardPointsWithoutPortalUserTest(TestCase):
    """Customers earn points on completion even with no portal accounts."""

    def setUp(self):
        _, self.tenant = _make_tenant("Shop Alpha", "alpha169")
        self.tech = _make_tech(self.tenant, "1")
        self.customer = _make_customer(self.tenant)

    # -----------------------------------------------------------------
    # 1. Zero CustomerUsers — the company still earns
    # -----------------------------------------------------------------
    def test_customer_with_no_portal_users_earns_points(self):
        """A Customer with no CustomerUser rows earns points_per_repair."""
        self.assertEqual(
            CustomerUser.objects.filter(customer=self.customer).count(), 0
        )

        r = _make_repair(self.tenant, self.tech, self.customer)
        r.queue_status = "COMPLETED"
        r.save()

        self.assertEqual(
            LoyaltyService.get_balance(self.customer),
            50,
            "Customer without portal users must earn 50 points on completion",
        )

        pt = PointTransaction.objects.get(
            customer=self.customer, transaction_type="repair_complete"
        )
        self.assertEqual(pt.customer, self.customer)
        self.assertIsNone(
            pt.customer_user,
            "No portal user triggered this earn — attribution must be None",
        )
        self.assertEqual(pt.amount, 50)

    # -----------------------------------------------------------------
    # 2. WALK_IN customers earn too
    # -----------------------------------------------------------------
    def test_walk_in_customer_earns_points(self):
        """WALK_IN customer_type is not excluded from loyalty."""
        walk_in = _make_customer(
            self.tenant, name="Jane Walkin", customer_type="WALK_IN"
        )

        r = _make_repair(self.tenant, self.tech, walk_in)
        r.queue_status = "COMPLETED"
        r.save()

        self.assertEqual(
            LoyaltyService.get_balance(walk_in),
            50,
            "WALK_IN customers must earn points on completion",
        )
        pt = PointTransaction.objects.get(
            customer=walk_in, transaction_type="repair_complete"
        )
        self.assertIsNone(pt.customer_user)

    # -----------------------------------------------------------------
    # 3. Idempotency — re-saving a COMPLETED repair must not re-award
    # -----------------------------------------------------------------
    def test_resave_of_completed_repair_does_not_double_award(self):
        """Re-saving an already-COMPLETED repair awards nothing extra."""
        r = _make_repair(self.tenant, self.tech, self.customer)
        r.queue_status = "COMPLETED"
        r.save()

        self.assertEqual(LoyaltyService.get_balance(self.customer), 50)

        # Simulate an edit after completion (photo/notes re-save)
        r.technician_notes = "Photo added"
        r.save()

        self.assertEqual(
            LoyaltyService.get_balance(self.customer),
            50,
            "Re-saving a COMPLETED repair must not award points again",
        )
        self.assertEqual(
            PointTransaction.objects.filter(
                customer=self.customer, transaction_type="repair_complete"
            ).count(),
            1,
            "Exactly one earn transaction must exist",
        )
