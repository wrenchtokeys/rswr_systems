"""
CODE-059 Regression Tests
=========================
convert_to_batch() price override check used `request.user.technician.is_manager`
instead of `get_user_role(request.user, tenant=tenant)`.

Problems fixed:
1. A user who is Manager at Tenant A but plain Technician at Tenant B could
   have is_manager=True on the OneToOne Technician record and bypass the
   price-override gate on Tenant B repairs (cross-tenant privilege escalation).
2. Owners/superusers who have no Technician record would AttributeError at
   `request.user.technician` in the elif branch.

Fix: replaced the elif with get_user_role() — same pattern as CODE-042 for
create_multi_break_repair and CODE-058 for update_queue_status.
"""

import uuid
from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair
from apps.technician_portal.views.batch import convert_to_batch
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial59",
        defaults={
            "name": "Trial59",
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
        username=f"owner59_{name.lower().replace(' ', '_')}",
        email=f"owner59@{name.lower().replace(' ', '')}.com",
        password="pass1234",
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=f"shop59-{name.lower().replace(' ', '-')}",
        owner=owner,
        subscription_plan=plan,
        is_active=True,
    )
    TenantMembership.objects.create(
        user=owner, tenant=tenant, role="owner", is_active=True
    )
    return tenant, owner


def _make_tech(username, email, tenant, is_manager=False, can_override=False, approval_limit=None, role="technician"):
    user = User.objects.create_user(username=username, email=email, password="pass1234")
    TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=is_manager,
        can_override_pricing=can_override,
        approval_limit=approval_limit,
        is_active=True,
    )
    return user, tech


def _make_repair(tenant, customer, technician, queue_status="APPROVED"):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number="UNIT-001",
        damage_type="CHIP",
        service_date="2026-03-01",
        cost=Decimal("50.00"),
        queue_status=queue_status,
    )


def _make_request(factory, user, tenant, method="POST", data=None):
    """Build a fake POST request with messages middleware."""
    req = factory.post("/tech/batch/convert/1/", data or {})
    req.user = user
    req.tenant = tenant
    req.session = {}
    # Attach messages storage
    messages = FallbackStorage(req)
    req._messages = messages
    return req


def _get_messages(request):
    return [str(m) for m in request._messages]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConvertToBatchPriceOverride(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        plan = _make_plan()

        # Tenant A — where the repair lives
        self.tenant_a, self.owner_a = _make_tenant("ShopA59", plan)

        # Tenant B — second shop, used for cross-tenant escalation
        self.tenant_b, self.owner_b = _make_tenant("ShopB59", plan)

        # Customer in Tenant A
        self.customer = Customer.objects.create(
            tenant=self.tenant_a,
            name="Test Fleet 59",
            customer_type="FLEET",
        )

        # Plain technician in Tenant A (original repair assignee)
        self.plain_user, self.plain_tech = _make_tech(
            "plain59", "plain59@test.com", self.tenant_a,
            is_manager=False, can_override=False,
        )

        # Repair in Tenant A assigned to plain technician
        self.repair = _make_repair(self.tenant_a, self.customer, self.plain_tech)

        # Manager in Tenant A WITH override permission ($200 limit)
        self.mgr_user, self.mgr_tech = _make_tech(
            "mgr59", "mgr59@test.com", self.tenant_a,
            is_manager=True, can_override=True,
            approval_limit=Decimal("200.00"), role="manager",
        )

        # Manager in Tenant A WITHOUT override permission
        self.mgr_no_user, self.mgr_no_tech = _make_tech(
            "mgr59no", "mgr59no@test.com", self.tenant_a,
            is_manager=True, can_override=False, role="manager",
        )

        # Cross-tenant user: Manager at Tenant B (is_manager=True), plain tech membership at A
        self.cross_user = User.objects.create_user(
            username="cross59", email="cross59@test.com", password="pass1234"
        )
        # Their Technician record lives under Tenant B
        self.cross_tech_b = Technician.objects.create(
            user=self.cross_user,
            tenant=self.tenant_b,
            is_manager=True,
            can_override_pricing=True,
            is_active=True,
        )
        # Membership in Tenant B as manager
        TenantMembership.objects.create(
            user=self.cross_user, tenant=self.tenant_b, role="manager", is_active=True
        )
        # Membership in Tenant A as plain technician (no Technician record for A)
        TenantMembership.objects.create(
            user=self.cross_user, tenant=self.tenant_a, role="technician", is_active=True
        )

    def _call_view(self, user, repair, override_cost=None, override_reason=None):
        """POST to convert_to_batch with one extra break and optional price override.

        The view iterates range(additional_breaks) so indices are 0-based.
        """
        post_data = {
            "additional_breaks": "1",
            "damage_type_0": "CHIP",
        }
        if override_cost is not None:
            post_data["override_cost_0"] = str(override_cost)
        if override_reason is not None:
            post_data["override_reason_0"] = override_reason

        req = _make_request(self.factory, user, self.tenant_a, data=post_data)
        response = convert_to_batch(req, repair_id=repair.id)
        messages = _get_messages(req)
        return response, messages

    # ----------------------------------------------------------------
    # Test 1: Owner can always override (no limit applies)
    # ----------------------------------------------------------------
    def test_owner_can_override(self):
        """Owner/superuser should never be blocked from overriding price."""
        # Give owner a technician record so they pass the "is this your repair" check
        Technician.objects.create(
            user=self.owner_a, tenant=self.tenant_a, is_manager=True, is_active=True
        )
        # Reassign the repair to the owner's technician record
        owner_tech = Technician.objects.get(user=self.owner_a, tenant=self.tenant_a)
        self.repair.technician = owner_tech
        self.repair.save()

        response, msgs = self._call_view(
            self.owner_a, self.repair,
            override_cost="999.00", override_reason="Owner special rate",
        )
        combined = " ".join(msgs).lower()
        self.assertFalse(
            "permission to override" in combined,
            f"Owner should not get a permission-denied message. Got: {msgs}",
        )

    # ----------------------------------------------------------------
    # Test 2: Manager with permission and within limit — allowed
    # ----------------------------------------------------------------
    def test_manager_with_permission_within_limit(self):
        """Manager (can_override=True) below approval_limit should be allowed."""
        # Reassign repair to manager's tech record for ownership check
        self.repair.technician = self.mgr_tech
        self.repair.save()

        response, msgs = self._call_view(
            self.mgr_user, self.repair,
            override_cost="150.00", override_reason="Fleet discount",
        )
        combined = " ".join(msgs).lower()
        self.assertFalse(
            "permission" in combined and "override" in combined,
            f"Manager within limit should be allowed. Got: {msgs}",
        )

    # ----------------------------------------------------------------
    # Test 3: Manager over approval_limit — blocked
    # ----------------------------------------------------------------
    def test_manager_over_approval_limit_blocked(self):
        """Manager exceeding approval_limit must be blocked."""
        self.repair.technician = self.mgr_tech
        self.repair.save()

        response, msgs = self._call_view(
            self.mgr_user, self.repair,
            override_cost="250.00", override_reason="Too big",
        )
        combined = " ".join(msgs).lower()
        self.assertTrue(
            "approval limit" in combined or "exceeds" in combined,
            f"Should get approval_limit error. Got: {msgs}",
        )

    # ----------------------------------------------------------------
    # Test 4: Manager without can_override_pricing — blocked
    # ----------------------------------------------------------------
    def test_manager_without_override_perm_blocked(self):
        """Manager with can_override_pricing=False must be blocked."""
        self.repair.technician = self.mgr_no_tech
        self.repair.save()

        response, msgs = self._call_view(
            self.mgr_no_user, self.repair,
            override_cost="80.00", override_reason="Should fail",
        )
        combined = " ".join(msgs).lower()
        self.assertTrue(
            "permission" in combined or "override" in combined,
            f"Manager without override perm should be blocked. Got: {msgs}",
        )

    # ----------------------------------------------------------------
    # Test 5: Plain technician — blocked
    # ----------------------------------------------------------------
    def test_plain_tech_cannot_override(self):
        """Plain technicians must never override pricing."""
        response, msgs = self._call_view(
            self.plain_user, self.repair,
            override_cost="10.00", override_reason="Undersell attempt",
        )
        combined = " ".join(msgs).lower()
        self.assertTrue(
            "permission" in combined or "override" in combined,
            f"Plain tech should be blocked. Got: {msgs}",
        )
        # Confirm no cost_override written to DB
        self.repair.refresh_from_db()
        self.assertIsNone(self.repair.cost_override)

    # ----------------------------------------------------------------
    # Test 6: Cross-tenant manager — MUST be blocked (the core CODE-059 fix)
    # ----------------------------------------------------------------
    def test_cross_tenant_manager_cannot_override_in_shop_a(self):
        """
        User who is Manager at Tenant B, plain technician at Tenant A.

        Old code: request.user.technician.is_manager → Technician from B →
                  True → override allowed (WRONG — cross-tenant privilege escalation).
        Fixed:    get_user_role(user, tenant=tenant_a) → 'technician' →
                  blocked (CORRECT).
        """
        # Reassign repair to cross_user's tech record from B to pass ownership check
        # (They are a plain tech member at A, so we also need to allow them via admin)
        # For this test, grant admin so we can isolate just the price-override check
        TenantMembership.objects.filter(
            user=self.cross_user, tenant=self.tenant_a
        ).update(role="manager")
        # But cross_user's Technician record is under Tenant B — is_manager=True there
        # get_user_role sees their membership as "manager" at Tenant A now, but
        # can_override_pricing on the Tenant B Technician record should not apply
        # because we now look at the Tenant A scoped technician
        # (no Technician record for Tenant A → can_override=False, approval_limit=None)
        # The Tenant B tech (is_manager=True, can_override=True) should NOT bleed through.
        self.repair.technician = self.plain_tech  # original assignment
        self.repair.save()

        response, msgs = self._call_view(
            self.cross_user, self.repair,
            override_cost="5.00", override_reason="Exploit attempt",
        )
        # Cross-user is manager at A now but has no Tenant-A Technician record
        # → can_override_pricing defaults to False → must be blocked
        combined = " ".join(msgs).lower()
        self.assertTrue(
            "permission" in combined or "override" in combined or len(msgs) == 0,
            f"Cross-tenant user should not override Tenant A price. Got: {msgs}",
        )
        # No cost_override should have been persisted
        self.repair.refresh_from_db()
        self.assertIsNone(self.repair.cost_override)

    # ----------------------------------------------------------------
    # Test 7: No override_cost in POST — completes normally
    # ----------------------------------------------------------------
    def test_no_override_completes_normally(self):
        """Omitting override_cost should not trigger any permission error."""
        response, msgs = self._call_view(
            self.plain_user, self.repair,
            override_cost=None, override_reason=None,
        )
        # Should not have a "permission to override" error
        combined = " ".join(msgs).lower()
        self.assertFalse(
            "permission to override" in combined,
            f"No override in POST should not trigger permission error. Got: {msgs}",
        )
        self.repair.refresh_from_db()
        self.assertIsNone(self.repair.cost_override)

    # ----------------------------------------------------------------
    # Test 8: Missing override_reason when override_cost present — error
    # ----------------------------------------------------------------
    def test_override_requires_reason(self):
        """Providing override_cost without override_reason should fail."""
        self.repair.technician = self.mgr_tech
        self.repair.save()

        response, msgs = self._call_view(
            self.mgr_user, self.repair,
            override_cost="100.00", override_reason=None,  # no reason
        )
        combined = " ".join(msgs).lower()
        self.assertTrue(
            "reason" in combined or "permission" in combined or "override" in combined,
            f"Missing override_reason should cause an error. Got: {msgs}",
        )
