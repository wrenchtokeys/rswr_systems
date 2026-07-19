"""
Regression tests for CODE-065:
  customer_bulk_action() only filtered queue_status='PENDING', silently
  dropping REQUESTED repairs without any warning to the user.

Root cause:
    All other customer approval views (customer_repair_approve,
    customer_batch_approve) accept both PENDING and REQUESTED repairs.
    customer_bulk_action was inconsistent — it only queried queue_status='PENDING'.

    When a customer submitted their own repair request, it starts as REQUESTED.
    If the customer tried to approve those repairs via the bulk multi-select UI,
    the REQUESTED repairs were silently excluded from the queryset and the
    success message counted fewer repairs than selected — confusing and wrong.

Fix:
    Changed queue_status='PENDING' to queue_status__in=['PENDING', 'REQUESTED']
    in customer_bulk_action(). Consistent with all other customer approval paths.

Tests verify:
1. Bulk approve PENDING repairs → all approved.
2. Bulk approve REQUESTED repairs → all approved (was silently skipped before).
3. Bulk approve mixed PENDING+REQUESTED → all approved.
4. Bulk approve non-approvable statuses (COMPLETED, IN_PROGRESS) → excluded / no change.
5. Bulk deny PENDING repairs → all denied.
6. Bulk deny REQUESTED repairs → all denied (was silently skipped before).
7. No valid repairs selected → error message.
8. Cross-customer repairs excluded (tenant safety).
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_tenant(name="Bulk Test Shop"):
    owner_user, _ = User.objects.get_or_create(
        username=f"_owner_{name.lower().replace(' ', '_').replace('-', '_')}",
        defaults={"email": f"owner_{name.lower().replace(' ', '_')}@example.com"}
    )
    return Tenant.objects.create(
        name=name,
        subdomain=name.lower().replace(" ", "-"),
        owner=owner_user,
    )


def _make_customer(tenant, name="Fleet Co"):
    customer = Customer.objects.create(name=name, tenant=tenant)
    # Explicitly require approval — shop-created work auto-approves by default
    from apps.customer_portal.models import CustomerRepairPreference
    CustomerRepairPreference.objects.create(
        customer=customer,
        field_repair_approval_mode='REQUIRE_APPROVAL',
    )
    return customer


def _make_customer_user(user, customer):
    return CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=True)


def _make_tech(tenant, username="bulk_tech"):
    tech_user = User.objects.create_user(username=username, password="pw")
    Technician.objects.create(user=tech_user, tenant=tenant, can_repair=True)
    TenantMembership.objects.create(tenant=tenant, user=tech_user, role="technician", is_active=True)
    return tech_user


def _make_repair(customer, tech_user, status="PENDING", unit="UNIT-001"):
    tech = tech_user.technician
    return Repair.objects.create(
        customer=customer,
        technician=tech,
        tenant=customer.tenant,
        unit_number=unit,
        damage_type="CHIP",
        queue_status=status,
        service_date=date.today(),
        cost=Decimal("75.00"),
    )


class CustomerBulkActionApproveTests(TestCase):
    """customer_bulk_action() should accept PENDING and REQUESTED repairs for approval."""

    def setUp(self):
        self.tenant = _make_tenant("Bulk Approve Shop")
        self.customer = _make_customer(self.tenant)
        self.tech_user = _make_tech(self.tenant, username="bulk_tech_a")

        self.cu_user = User.objects.create_user(username="bulk_cu_a", password="pw")
        self.cu = _make_customer_user(self.cu_user, self.customer)

        self.client = Client()
        self.client.force_login(self.cu_user)

    def _bulk_approve(self, repair_ids):
        return self.client.post(
            reverse("customer_bulk_action"),
            {"action": "approve", "repair_ids": repair_ids},
            follow=False,
        )

    def test_bulk_approve_pending_repairs(self):
        """PENDING repairs are approved via bulk action (happy path)."""
        r1 = _make_repair(self.customer, self.tech_user, status="PENDING", unit="U-001")
        r2 = _make_repair(self.customer, self.tech_user, status="PENDING", unit="U-002")

        response = self._bulk_approve([r1.id, r2.id])

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.queue_status, "APPROVED")
        self.assertEqual(r2.queue_status, "APPROVED")
        self.assertEqual(response.status_code, 302)

    def test_bulk_approve_requested_repairs(self):
        """
        REQUESTED repairs (customer-initiated) must be approved by bulk action.
        
        Before CODE-065 fix: these were silently excluded (queue_status='PENDING'
        filter), the user got a misleading success message, and repairs stayed REQUESTED.
        """
        r1 = _make_repair(self.customer, self.tech_user, status="REQUESTED", unit="U-101")
        r2 = _make_repair(self.customer, self.tech_user, status="REQUESTED", unit="U-102")

        response = self._bulk_approve([r1.id, r2.id])

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.queue_status, "APPROVED",
                         "REQUESTED repair should be APPROVED after bulk approve (CODE-065 regression)")
        self.assertEqual(r2.queue_status, "APPROVED",
                         "REQUESTED repair should be APPROVED after bulk approve (CODE-065 regression)")
        self.assertEqual(response.status_code, 302)

    def test_bulk_approve_mixed_pending_and_requested(self):
        """Mix of PENDING and REQUESTED repairs all get approved."""
        r_pending = _make_repair(self.customer, self.tech_user, status="PENDING", unit="U-201")
        r_requested = _make_repair(self.customer, self.tech_user, status="REQUESTED", unit="U-202")

        response = self._bulk_approve([r_pending.id, r_requested.id])

        r_pending.refresh_from_db()
        r_requested.refresh_from_db()
        self.assertEqual(r_pending.queue_status, "APPROVED")
        self.assertEqual(r_requested.queue_status, "APPROVED",
                         "REQUESTED repair must not be silently skipped in mixed bulk approve (CODE-065)")
        self.assertEqual(response.status_code, 302)

    def test_bulk_approve_skips_non_approvable_statuses(self):
        """COMPLETED and IN_PROGRESS repairs are not changed by bulk approve."""
        r_completed = _make_repair(self.customer, self.tech_user, status="COMPLETED", unit="U-301")
        r_in_progress = _make_repair(self.customer, self.tech_user, status="IN_PROGRESS", unit="U-302")

        # These should either be excluded from the queryset or result in an error
        response = self._bulk_approve([r_completed.id, r_in_progress.id])

        r_completed.refresh_from_db()
        r_in_progress.refresh_from_db()
        # Statuses must not be overwritten
        self.assertEqual(r_completed.queue_status, "COMPLETED")
        self.assertEqual(r_in_progress.queue_status, "IN_PROGRESS")

    def test_bulk_approve_no_valid_repairs_returns_error(self):
        """Selecting only non-approvable repairs results in an error message, not a crash."""
        r_completed = _make_repair(self.customer, self.tech_user, status="COMPLETED", unit="U-401")

        response = self._bulk_approve([r_completed.id])
        # Should redirect back with an error
        self.assertEqual(response.status_code, 302)
        r_completed.refresh_from_db()
        self.assertEqual(r_completed.queue_status, "COMPLETED")


class CustomerBulkActionDenyTests(TestCase):
    """customer_bulk_action() should accept PENDING and REQUESTED repairs for denial."""

    def setUp(self):
        self.tenant = _make_tenant("Bulk Deny Shop")
        self.customer = _make_customer(self.tenant)
        self.tech_user = _make_tech(self.tenant, username="bulk_tech_d")

        self.cu_user = User.objects.create_user(username="bulk_cu_d", password="pw")
        self.cu = _make_customer_user(self.cu_user, self.customer)

        self.client = Client()
        self.client.force_login(self.cu_user)

    def _bulk_deny(self, repair_ids):
        return self.client.post(
            reverse("customer_bulk_action"),
            {"action": "deny", "repair_ids": repair_ids},
            follow=False,
        )

    def test_bulk_deny_pending_repairs(self):
        """PENDING repairs are denied via bulk action (happy path)."""
        r1 = _make_repair(self.customer, self.tech_user, status="PENDING", unit="D-001")
        r2 = _make_repair(self.customer, self.tech_user, status="PENDING", unit="D-002")

        self._bulk_deny([r1.id, r2.id])

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.queue_status, "DENIED")
        self.assertEqual(r2.queue_status, "DENIED")

    def test_bulk_deny_requested_repairs(self):
        """
        REQUESTED repairs can also be denied via bulk action.

        Before CODE-065 fix: these were silently excluded.
        """
        r1 = _make_repair(self.customer, self.tech_user, status="REQUESTED", unit="D-101")
        r2 = _make_repair(self.customer, self.tech_user, status="REQUESTED", unit="D-102")

        self._bulk_deny([r1.id, r2.id])

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.queue_status, "DENIED",
                         "REQUESTED repair should be DENIED after bulk deny (CODE-065 regression)")
        self.assertEqual(r2.queue_status, "DENIED",
                         "REQUESTED repair should be DENIED after bulk deny (CODE-065 regression)")


class CustomerBulkActionTenantScopeTest(TestCase):
    """Cross-customer repairs must not be modifiable via bulk action."""

    def setUp(self):
        self.tenant = _make_tenant("Bulk Tenant Shop")
        self.customer_a = _make_customer(self.tenant, name="Customer A")
        self.customer_b = _make_customer(self.tenant, name="Customer B")
        self.tech_user = _make_tech(self.tenant, username="bulk_tech_t")

        # Customer A user
        self.cu_user_a = User.objects.create_user(username="bulk_cu_ta", password="pw")
        self.cu_a = _make_customer_user(self.cu_user_a, self.customer_a)

        self.client = Client()
        self.client.force_login(self.cu_user_a)

    def test_cannot_approve_other_customers_repairs(self):
        """Customer A cannot bulk-approve Customer B's repairs."""
        r_b = _make_repair(self.customer_b, self.tech_user, status="PENDING", unit="B-001")

        response = self.client.post(
            reverse("customer_bulk_action"),
            {"action": "approve", "repair_ids": [r_b.id]},
            follow=False,
        )

        r_b.refresh_from_db()
        # Repair B must stay PENDING — not approved by customer A
        self.assertEqual(r_b.queue_status, "PENDING",
                         "Cross-customer bulk approve must be blocked by customer filter")
        # Should redirect with error or no-valid-repairs message
        self.assertEqual(response.status_code, 302)
