"""
Regression tests for CODE-058:
  update_queue_status() allowed any technician to set cost_override via POST
  when completing a repair — no permission check existed.

Root cause:
    The COMPLETED branch in update_queue_status() read `cost_override` and
    `override_reason` from POST and wrote them directly to the repair with no
    check on `can_override_pricing`, `approval_limit`, or the user's role.
    A plain technician could set an arbitrary custom price by POSTing
    status=COMPLETED&cost_override=0.01.

Fix:
    Added get_user_role() check identical to the pattern established in
    batch.py (CODE-042 fix):
      - superuser / owner: always allowed, no limit.
      - manager with can_override_pricing=True: allowed up to approval_limit.
      - manager without can_override_pricing: blocked (warning, no override).
      - plain technician: blocked (warning, no override).

Tests verify:
1. Owner can set cost_override — applied.
2. Authorised manager (can_override_pricing=True, no limit) can set cost_override — applied.
3. Authorised manager exceeding approval_limit is blocked — no override applied.
4. Authorised manager within approval_limit — applied.
5. Manager without can_override_pricing is blocked — no override applied.
6. Plain technician is blocked — no override applied.
7. No cost_override in POST — repair completed normally, no override set.
8. Invalid cost_override value — graceful warning, no crash.
"""

from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair
from apps.technician_portal.views.repairs import update_queue_status
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial58",
        defaults={
            "name": "Trial58",
            "monthly_price": 0,
            "annual_price": 0,
            "max_customers": 50,
            "max_technicians": 10,
            "is_active": True,
        },
    )
    return plan


def _make_tenant(name, plan):
    owner = User.objects.create_user(
        username=f"owner_{name.lower().replace(' ', '_')}",
        email=f"owner@{name.lower().replace(' ', '')}.com",
        password="pass1234",
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=owner,
        subscription_plan=plan,
        is_active=True,
    )
    TenantMembership.objects.create(
        user=owner, tenant=tenant, role="owner", is_active=True
    )
    return tenant, owner


def _make_tech(tenant, username, is_manager=False, can_override=False, approval_limit=None):
    user = User.objects.create_user(
        username=username, email=f"{username}@test.com", password="pass1234"
    )
    TenantMembership.objects.create(
        user=user, tenant=tenant, role="manager" if is_manager else "technician",
        is_active=True
    )
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        is_active=True,
        is_manager=is_manager,
        can_override_pricing=can_override,
        approval_limit=approval_limit,
    )
    return user, tech


def _make_repair(tenant, tech, customer, cost=Decimal("100.00")):
    """Create an APPROVED repair assigned to tech."""
    return Repair.objects.create(
        tenant=tenant,
        technician=tech,
        customer=customer,
        unit_number="UNIT-58",
        queue_status="APPROVED",
        cost=cost,
    )


def _make_request(factory, user, tenant, repair_id, cost_override=None, override_reason=None):
    """Build a POST request to update_queue_status."""
    data = {"status": "COMPLETED"}
    if cost_override is not None:
        data["cost_override"] = str(cost_override)
    if override_reason is not None:
        data["override_reason"] = override_reason

    request = factory.post(f"/repairs/{repair_id}/status/", data)
    request.user = user
    request.tenant = tenant
    # Attach message storage so messages.* calls in the view don't crash
    setattr(request, "session", "session")
    messages = FallbackStorage(request)
    setattr(request, "_messages", messages)
    return request


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class UpdateQueueStatusPriceOverrideTestCase(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.plan = _make_plan()
        self.tenant, self.owner = _make_tenant("Shop58A", self.plan)

        self.customer = Customer.objects.create(
            tenant=self.tenant, name="Fleet58"
        )

        # Plain technician (no override permission)
        self.plain_user, self.plain_tech = _make_tech(self.tenant, "plain58")

        # Manager without override permission
        self.mgr_nooverride_user, self.mgr_nooverride_tech = _make_tech(
            self.tenant, "mgr_noover58", is_manager=True, can_override=False
        )

        # Manager with override permission, no limit
        self.mgr_user, self.mgr_tech = _make_tech(
            self.tenant, "mgr58", is_manager=True, can_override=True, approval_limit=None
        )

        # Manager with override permission, limit $50
        self.mgr_limit_user, self.mgr_limit_tech = _make_tech(
            self.tenant, "mgr_limit58", is_manager=True, can_override=True,
            approval_limit=Decimal("50.00")
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call_view(self, user, repair, cost_override=None, override_reason=None):
        request = _make_request(
            self.factory, user, self.tenant, repair.id,
            cost_override=cost_override, override_reason=override_reason
        )
        return update_queue_status(request, repair_id=repair.id)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_owner_can_set_cost_override(self):
        """Shop owner: cost_override applied when completing."""
        repair = _make_repair(self.tenant, self.plain_tech, self.customer)
        self._call_view(self.owner, repair, cost_override="75.00")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertEqual(repair.cost_override, Decimal("75.00"))

    def test_authorised_manager_can_set_cost_override(self):
        """Manager with can_override_pricing=True, no limit: override applied."""
        repair = _make_repair(self.tenant, self.mgr_tech, self.customer)
        self._call_view(self.mgr_user, repair, cost_override="80.00", override_reason="Discount")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertEqual(repair.cost_override, Decimal("80.00"))

    def test_manager_exceeding_approval_limit_is_blocked(self):
        """Manager with approval_limit=$50: override of $75 is blocked."""
        repair = _make_repair(self.tenant, self.mgr_limit_tech, self.customer)
        self._call_view(self.mgr_limit_user, repair, cost_override="75.00")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertIsNone(repair.cost_override)  # blocked — override NOT applied

    def test_manager_within_approval_limit_is_allowed(self):
        """Manager with approval_limit=$50: override of $40 is allowed."""
        repair = _make_repair(self.tenant, self.mgr_limit_tech, self.customer)
        self._call_view(self.mgr_limit_user, repair, cost_override="40.00")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertEqual(repair.cost_override, Decimal("40.00"))

    def test_manager_without_override_permission_is_blocked(self):
        """Manager with can_override_pricing=False: override blocked."""
        repair = _make_repair(self.tenant, self.mgr_nooverride_tech, self.customer)
        self._call_view(self.mgr_nooverride_user, repair, cost_override="60.00")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertIsNone(repair.cost_override)  # blocked

    def test_plain_technician_cannot_set_cost_override(self):
        """Plain technician: cost_override POST silently ignored with warning."""
        repair = _make_repair(self.tenant, self.plain_tech, self.customer)
        self._call_view(self.plain_user, repair, cost_override="0.01")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertIsNone(repair.cost_override)  # blocked — override NOT applied

    def test_no_cost_override_in_post_completes_normally(self):
        """No cost_override in POST: repair completes, no override set."""
        repair = _make_repair(self.tenant, self.plain_tech, self.customer)
        self._call_view(self.owner, repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertIsNone(repair.cost_override)

    def test_invalid_cost_override_value_does_not_crash(self):
        """Non-numeric cost_override: warning, no crash, repair still completed."""
        repair = _make_repair(self.tenant, self.plain_tech, self.customer)
        self._call_view(self.owner, repair, cost_override="not-a-number")
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertIsNone(repair.cost_override)
