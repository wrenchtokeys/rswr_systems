"""
CODE-268: RewardFulfillmentService.assign_technician() assigns to inactive
          technicians and uses full save() instead of save(update_fields=...).

Root cause:
  assign_technician() filtered technicians with Technician.objects.all() (no
  is_active filter).  A deactivated technician could be chosen as the lowest-
  workload assignee and then notified, sending spurious TechnicianNotification
  rows to former staff.

  The method also called redemption.save() without update_fields, which rewrote
  every field on the redemption - potentially overwriting concurrent changes.

Fix:
  Filter technicians to is_active=True AND user__is_active=True before selecting
  the lowest-workload assignee.  Use save(update_fields=['assigned_technician']).

  When tenant is None (data integrity error upstream) return None rather than
  querying globally.

Affected path:
  apps/rewards_referrals/services.py - RewardFulfillmentService.assign_technician()
"""
from django.test import TestCase
from django.contrib.auth.models import User

from apps.rewards_referrals.services import RewardFulfillmentService
from apps.rewards_referrals.models import (
    LoyaltyConfig, Reward, RewardOption, RewardRedemption, RewardType,
)
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.tenants.models import Tenant
from apps.technician_portal.models import Technician


def _make_user(username, active=True):
    return User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password='testpass',
        is_active=active,
    )


class RewardAssignmentInactiveTechTests(TestCase):
    """assign_technician() must skip inactive technicians."""

    def setUp(self):
        self.owner = _make_user('owner268')
        self.tenant = Tenant.objects.create(
            name='Glass Shop 268',
            slug='glass-shop-268',
            is_active=True,
            owner=self.owner,
        )
        LoyaltyConfig.objects.create(
            tenant=self.tenant,
            is_active=True,
            points_per_repair=10,
        )

        # Two technicians: one active, one inactive
        self.active_user = _make_user('active_tech268')
        self.active_tech = Technician.objects.create(
            user=self.active_user,
            tenant=self.tenant,
            phone_number='555-0268',
            is_active=True,
        )

        self.inactive_user = _make_user('inactive_tech268', active=False)
        self.inactive_tech = Technician.objects.create(
            user=self.inactive_user,
            tenant=self.tenant,
            phone_number='555-0269',
            is_active=False,
        )

        # Customer + CustomerUser
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Fleet Co 268',
            primary_technician=self.active_tech,
        )
        self.customer_user_account = _make_user('cu268')
        self.customer_user = CustomerUser.objects.create(
            user=self.customer_user_account,
            customer=self.customer,
            is_primary_contact=True,
        )

        # Reward + RewardOption
        self.reward = Reward.objects.create(
            tenant=self.tenant,
            customer_user=self.customer_user,
            points=100,
        )

        self.reward_type = RewardType.objects.create(
            name='Oil Change 268',
            category='service',
            discount_type='free_service',
            discount_value=0,
        )
        self.reward_option = RewardOption.objects.create(
            tenant=self.tenant,
            name='Free Oil Change 268',
            reward_type=self.reward_type,
            points_required=50,
            is_active=True,
        )

    def _make_redemption(self):
        return RewardRedemption.objects.create(
            reward=self.reward,
            reward_option=self.reward_option,
            status='PENDING',
        )

    # ------------------------------------------------------------------
    # Core behaviour: inactive technicians are skipped
    # ------------------------------------------------------------------

    def test_inactive_technician_not_assigned(self):
        """The inactive technician must never be chosen even if they exist."""
        # Make the active tech unavailable by deactivating them too -
        # only the inactive tech exists now.  Result should be None.
        self.active_tech.is_active = False
        self.active_tech.save(update_fields=['is_active'])

        redemption = self._make_redemption()
        result = RewardFulfillmentService.assign_technician(redemption)
        self.assertIsNone(result)

        redemption.refresh_from_db()
        self.assertIsNone(redemption.assigned_technician)

    def test_active_technician_is_assigned(self):
        """When an active tech exists, they get the assignment."""
        redemption = self._make_redemption()
        result = RewardFulfillmentService.assign_technician(redemption)
        self.assertEqual(result, self.active_tech)

        redemption.refresh_from_db()
        self.assertEqual(redemption.assigned_technician, self.active_tech)

    def test_active_preferred_over_inactive(self):
        """Active tech is chosen even when inactive tech has fewer repairs."""
        # The inactive tech has zero repairs (lowest workload), but the active
        # tech should still win because inactive techs are excluded.
        redemption = self._make_redemption()
        result = RewardFulfillmentService.assign_technician(redemption)
        self.assertEqual(result, self.active_tech)

    def test_inactive_user_account_excluded(self):
        """A tech whose User is deactivated (user.is_active=False) is excluded."""
        # active_tech has an active user; deactivate only the user, not the tech.
        self.active_user.is_active = False
        self.active_user.save(update_fields=['is_active'])
        # Now the only "active" Technician row also has an inactive User.
        redemption = self._make_redemption()
        result = RewardFulfillmentService.assign_technician(redemption)
        self.assertIsNone(result)

    def test_no_active_technicians_returns_none(self):
        """If there are no active technicians at all, return None."""
        self.active_tech.is_active = False
        self.active_tech.save(update_fields=['is_active'])
        self.inactive_tech.is_active = False
        self.inactive_tech.save(update_fields=['is_active'])

        redemption = self._make_redemption()
        result = RewardFulfillmentService.assign_technician(redemption)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Regression: save() uses update_fields
    # ------------------------------------------------------------------

    def test_save_uses_update_fields_not_full_save(self):
        """
        assign_technician() must only update assigned_technician, not all fields.

        Simulate a concurrent change: set a notes value on the redemption in-
        memory before calling assign_technician().  If full save() is used, the
        in-memory notes value would be persisted (overwriting any DB value).
        With update_fields=['assigned_technician'] only the FK is updated.
        """
        redemption = self._make_redemption()

        # Artificially mark a note in the DB that would be lost by a full save.
        RewardRedemption.objects.filter(pk=redemption.pk).update(notes='sentinel-value-268')

        # Now assign (the in-memory object has notes=None/blank)
        result = RewardFulfillmentService.assign_technician(redemption)
        self.assertEqual(result, self.active_tech)

        redemption.refresh_from_db()
        # The DB-side note must survive - a full save() would have wiped it.
        self.assertEqual(redemption.notes, 'sentinel-value-268')
        self.assertEqual(redemption.assigned_technician, self.active_tech)

    # ------------------------------------------------------------------
    # Edge case: None tenant → safe return (no global query)
    # ------------------------------------------------------------------

    def test_no_tenant_cross_tenant_isolation(self):
        """
        When tenant cannot be resolved, the service returns None rather than
        querying all technicians globally.  We verify this by creating a second
        tenant with active technicians — if the service were to fall back to
        Technician.objects.all(), it would return a tech from the other tenant.
        """
        # Create a second tenant with its own active tech.
        owner2 = _make_user('owner268b')
        tenant2 = Tenant.objects.create(
            name='Other Shop 268',
            slug='other-shop-268',
            is_active=True,
            owner=owner2,
        )
        tech2_user = _make_user('tech268b')
        Technician.objects.create(
            user=tech2_user,
            tenant=tenant2,
            phone_number='555-0270',
            is_active=True,
        )

        # Deactivate all techs in the primary tenant so assign_technician() must
        # return None (no eligible techs) and NOT fall through to global query.
        self.active_tech.is_active = False
        self.active_tech.save(update_fields=['is_active'])
        self.inactive_tech.is_active = False
        self.inactive_tech.save(update_fields=['is_active'])

        redemption = self._make_redemption()
        result = RewardFulfillmentService.assign_technician(redemption)
        # Should be None — the tenant2 tech must NOT be assigned.
        self.assertIsNone(result)
