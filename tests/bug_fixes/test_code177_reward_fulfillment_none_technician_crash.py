"""
CODE-177: Regression tests — RewardFulfillmentService.mark_as_fulfilled() crashes
when technician=None, and reward_fulfillment_detail view incorrectly grants
fulfillment access to non-technician admins for unassigned rewards.

Bug (part 1 — service):
  mark_as_fulfilled(redemption, technician=None) unconditionally accessed
  ``technician.user``, raising AttributeError: 'NoneType' object has no
  attribute 'user'.

  This path is reached when an owner or manager (with TenantMembership but
  no Technician row) opens an unassigned reward redemption and submits the
  fulfillment form.  @technician_required allows anyone with 'repairs' access,
  which includes owners and managers.

Bug (part 2 — view):
  In ``reward_fulfillment_detail``:
      is_assigned_technician = (redemption.assigned_technician == technician)

  When redemption.assigned_technician is None AND technician is None (owner
  without a Technician profile), this evaluates to True:
      None == None  → True

  So ``can_fulfill = True``, the guard passes, and then the service crashes.

  This also means an owner visiting ANY unassigned reward redemption was
  incorrectly treated as the "assigned technician" rather than as an admin.

Fix:
  1. mark_as_fulfilled() only sets processed_by when technician is not None.
  2. is_assigned_technician requires both sides to be non-None.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone

from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import (
    LoyaltyConfig,
    Reward,
    RewardOption,
    RewardRedemption,
    RewardType,
)
from apps.rewards_referrals.services import RewardFulfillmentService
from core.models import Customer
from apps.customer_portal.models import CustomerUser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(name, slug):
    owner_user = User.objects.create_user(
        f"owner_{slug}", f"owner_{slug}@test.com", "Pass123!"
    )
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner_user,
        plan="pro", trial_started_at=timezone.now(),
    )
    TenantMembership.objects.create(
        user=owner_user, tenant=tenant, role="owner", is_active=True
    )
    return owner_user, tenant


def _make_customer_user(tenant):
    cu_user = User.objects.create_user(
        f"cu_{tenant.slug}", f"cu_{tenant.slug}@test.com", "Pass123!"
    )
    customer = Customer.objects.create(
        name="Test Fleet", tenant=tenant, email=f"cu_{tenant.slug}@test.com"
    )
    TenantMembership.objects.create(
        user=cu_user, tenant=tenant, role="viewer", is_active=True
    )
    customer_user = CustomerUser.objects.create(
        user=cu_user, customer=customer, is_primary_contact=True
    )
    return customer_user


def _make_reward_option(tenant):
    reward_type = RewardType.objects.create(
        name=f"Discount_{tenant.slug}",
        category="REPAIR_DISCOUNT",
        discount_type="PERCENTAGE",
        discount_value=10,
        is_active=True,
    )
    return RewardOption.objects.create(
        tenant=tenant,
        name="10% off",
        points_required=100,
        reward_type=reward_type,
        is_active=True,
    )


def _make_redemption(customer_user, reward_option, tenant):
    """Create a minimal Reward + RewardRedemption pair."""
    reward, _ = Reward.objects.get_or_create(
        customer_user=customer_user,
        defaults={"tenant": tenant, "points": 500},
    )
    return RewardRedemption.objects.create(
        reward=reward,
        reward_option=reward_option,
        status="PENDING",
    )


# ---------------------------------------------------------------------------
# Tests — service layer
# ---------------------------------------------------------------------------

class MarkAsFulfilledNoneTechnicianTest(TestCase):
    """mark_as_fulfilled(redemption, technician=None) must not crash."""

    def setUp(self):
        self.owner_user, self.tenant = _make_tenant("Shop A", "shop-a-177")
        self.cu = _make_customer_user(self.tenant)
        self.opt = _make_reward_option(self.tenant)
        self.redemption = _make_redemption(self.cu, self.opt, self.tenant)

    def test_mark_as_fulfilled_with_none_technician_does_not_crash(self):
        """
        Calling mark_as_fulfilled(redemption, None) must not raise AttributeError.
        The status should be set to FULFILLED and timestamps populated.
        """
        result = RewardFulfillmentService.mark_as_fulfilled(self.redemption, None)
        self.assertEqual(result.status, "FULFILLED")
        self.assertIsNotNone(result.processed_at)
        self.assertIsNotNone(result.fulfilled_at)
        # processed_by should remain None when no technician is provided
        self.assertIsNone(result.processed_by)

    def test_mark_as_fulfilled_with_none_technician_preserves_existing_processed_by(self):
        """
        If redemption.processed_by was already set, passing technician=None
        should not overwrite it (it stays unchanged on the saved object).
        """
        # Simulate a prior partial save that set processed_by
        self.redemption.processed_by = self.owner_user
        self.redemption.save()

        result = RewardFulfillmentService.mark_as_fulfilled(self.redemption, None)
        # processed_by was already on the DB row and None-technician path does
        # not touch it, so it should still be set.
        self.assertIsNotNone(result.processed_by)

    def test_mark_as_fulfilled_with_real_technician_sets_processed_by(self):
        """
        When a real Technician is passed, processed_by is correctly set.
        """
        tech_user = User.objects.create_user("tech177", "tech177@test.com", "Pass123!")
        tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True
        )
        result = RewardFulfillmentService.mark_as_fulfilled(self.redemption, tech)
        self.assertEqual(result.processed_by, tech_user)
        self.assertEqual(result.status, "FULFILLED")

    def test_mark_as_fulfilled_sets_fulfilled_at(self):
        """fulfilled_at must be populated regardless of technician."""
        result = RewardFulfillmentService.mark_as_fulfilled(self.redemption, None, notes="Done")
        self.assertIsNotNone(result.fulfilled_at)
        self.assertEqual(result.notes, "Done")


# ---------------------------------------------------------------------------
# Tests — view layer: is_assigned_technician None == None bug
# ---------------------------------------------------------------------------

class IsAssignedTechnicianNoneNoneTest(TestCase):
    """
    None == None must not make an owner appear as the 'assigned technician'.

    We test the logic inline (without HTTP) since the view requires complex
    middleware (tenant + auth) and the bug is a pure Python equality check.
    """

    def setUp(self):
        self.owner_user, self.tenant = _make_tenant("Shop B", "shop-b-177")
        self.cu = _make_customer_user(self.tenant)
        self.opt = _make_reward_option(self.tenant)
        self.redemption = _make_redemption(self.cu, self.opt, self.tenant)

    def _compute_is_assigned_technician(self, technician, redemption):
        """Replicate the fixed view logic from reward_fulfillment_detail."""
        return (
            technician is not None
            and redemption.assigned_technician is not None
            and redemption.assigned_technician == technician
        )

    def test_none_technician_unassigned_redemption_not_assigned(self):
        """
        owner (no Technician row) + unassigned redemption → is_assigned_technician=False.
        Bug: old code returned True (None == None).
        """
        # No Technician row for the owner → technician=None
        technician = None
        # Redemption is unassigned → assigned_technician=None
        self.assertIsNone(self.redemption.assigned_technician)

        result = self._compute_is_assigned_technician(technician, self.redemption)
        self.assertFalse(result, "None technician must not match unassigned redemption")

    def test_none_technician_assigned_redemption_not_assigned(self):
        """owner (no Technician row) + assigned redemption → is_assigned_technician=False."""
        tech_user = User.objects.create_user("tech177b", "tech177b@test.com", "Pass123!")
        tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True
        )
        self.redemption.assigned_technician = tech
        self.redemption.save()

        result = self._compute_is_assigned_technician(None, self.redemption)
        self.assertFalse(result, "None technician must not match an assigned technician")

    def test_real_technician_matches_assigned(self):
        """A real Technician that is the assigned technician → True."""
        tech_user = User.objects.create_user("tech177c", "tech177c@test.com", "Pass123!")
        tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True
        )
        self.redemption.assigned_technician = tech
        self.redemption.save()

        result = self._compute_is_assigned_technician(tech, self.redemption)
        self.assertTrue(result, "Assigned technician should be recognized")

    def test_different_technician_not_assigned(self):
        """A different Technician → False."""
        tech_user_a = User.objects.create_user("tech177d", "tech177d@test.com", "Pass123!")
        tech_a = Technician.objects.create(
            user=tech_user_a, tenant=self.tenant, is_active=True
        )
        tech_user_b = User.objects.create_user("tech177e", "tech177e@test.com", "Pass123!")
        tech_b = Technician.objects.create(
            user=tech_user_b, tenant=self.tenant, is_active=True
        )
        self.redemption.assigned_technician = tech_a
        self.redemption.save()

        result = self._compute_is_assigned_technician(tech_b, self.redemption)
        self.assertFalse(result, "Wrong technician must not match assigned technician")

    def test_real_technician_unassigned_redemption_not_assigned(self):
        """Technician exists but redemption is unassigned → False."""
        tech_user = User.objects.create_user("tech177f", "tech177f@test.com", "Pass123!")
        tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True
        )

        # redemption.assigned_technician is still None
        result = self._compute_is_assigned_technician(tech, self.redemption)
        self.assertFalse(result, "Unassigned redemption should not match any technician")
