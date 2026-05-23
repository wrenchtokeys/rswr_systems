"""
Regression tests for CODE-061:
  customer_repair_approve() and customer_repair_deny() lacked server-side
  status guards — a direct POST could corrupt completed/in-progress repairs
  by overwriting queue_status to APPROVED or DENIED.

  Same missing guard existed in customer_batch_approve() and
  customer_batch_deny() for multi-break batches.

Root cause:
    The templates hide approve/deny buttons for non-PENDING repairs, but the
    view had no server-side check.  A customer (or anyone with a valid session)
    could POST directly to the URL and:

    1. Flip a COMPLETED repair back to APPROVED — repair appears re-opened,
       invoicing data becomes inconsistent (a COMPLETED repair can be invoiced;
       an APPROVED one cannot be directly invoiced without re-completing).
    2. Flip a DENIED repair back to APPROVED — effectively re-opening a denied
       repair without manager involvement.
    3. Flip a COMPLETED batch (all COMPLETED) back to APPROVED for every
       repair in the batch in one atomic transaction.

Fix:
    Added guard in customer_repair_approve(): redirect with warning if
    repair.queue_status not in ('PENDING', 'REQUESTED').
    Added guard in customer_repair_deny(): same check.
    Added guard in customer_batch_approve(): verify all statuses in
    approvable_statuses before processing POST.
    Added guard in customer_batch_deny(): same check.

Tests verify:
1. Approve PENDING repair → succeeds (happy path).
2. Approve COMPLETED repair → redirects with warning, status unchanged.
3. Approve APPROVED repair → redirects with warning, status unchanged.
4. Approve IN_PROGRESS repair → redirects with warning, status unchanged.
5. Deny PENDING repair → succeeds (happy path).
6. Deny DENIED repair → redirects with warning, status unchanged.
7. Deny COMPLETED repair → redirects with warning, status unchanged.
8. Batch approve — all PENDING → succeeds.
9. Batch approve — mixed PENDING+COMPLETED → rejected, no repairs changed.
10. Batch deny — all PENDING → succeeds.
11. Batch deny — any COMPLETED → rejected, no repairs changed.
"""

import uuid
from decimal import Decimal
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser, RepairApproval
from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(name="Test Shop"):
    # Tenant requires an owner FK — create a placeholder owner user first.
    owner_user, _ = User.objects.get_or_create(
        username=f"_owner_{name.lower().replace(' ', '_')}",
        defaults={"email": f"owner_{name.lower().replace(' ', '_')}@example.com"}
    )
    return Tenant.objects.create(
        name=name,
        subdomain=name.lower().replace(" ", "-"),
        owner=owner_user,
    )


def _make_owner(tenant, username="owner", email="owner@example.com"):
    user = User.objects.create_user(username=username, email=email, password="pw")
    TenantMembership.objects.create(tenant=tenant, user=user, role="owner", is_active=True)
    return user


def _make_customer(tenant, name="Acme Trucking"):
    return Customer.objects.create(name=name, tenant=tenant)


def _make_customer_user(user, customer):
    return CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=True)


def _make_tech(tenant, username="tech1"):
    tech_user = User.objects.create_user(username=username, password="pw")
    tech = Technician.objects.create(user=tech_user, tenant=tenant, can_repair=True)
    TenantMembership.objects.create(tenant=tenant, user=tech_user, role="technician", is_active=True)
    return tech


def _make_repair(customer, technician, status="PENDING"):
    return Repair.objects.create(
        customer=customer,
        technician=technician,
        tenant=customer.tenant,
        unit_number="UNIT-001",
        damage_type="CHIP",
        queue_status=status,
        service_date=date.today(),
        cost=Decimal("75.00"),
    )


class RepairApproveStatusGuardTests(TestCase):
    """customer_repair_approve() must reject non-pending repairs."""

    def setUp(self):
        self.tenant = _make_tenant("ApproveGuard Shop")
        self.owner_user = _make_owner(self.tenant)
        self.customer = _make_customer(self.tenant)
        self.tech = _make_tech(self.tenant)

        # Create a customer-portal user
        self.cu_user = User.objects.create_user(username="cuuser", password="pw")
        self.cu = _make_customer_user(self.cu_user, self.customer)

        self.client = Client()
        self.client.force_login(self.cu_user)

    def _post_approve(self, repair, notes=""):
        url = reverse("customer_repair_approve", kwargs={"repair_id": repair.id})
        return self.client.post(url, {"notes": notes}, follow=False)

    def test_approve_pending_succeeds(self):
        """Approving a PENDING repair must succeed and flip status to APPROVED."""
        repair = _make_repair(self.customer, self.tech, status="PENDING")
        response = self._post_approve(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "APPROVED")
        self.assertEqual(response.status_code, 302)

    def test_approve_completed_rejected(self):
        """POSTing approve on a COMPLETED repair must not change its status."""
        repair = _make_repair(self.customer, self.tech, status="COMPLETED")
        response = self._post_approve(repair)
        repair.refresh_from_db()
        # Status must stay COMPLETED
        self.assertEqual(repair.queue_status, "COMPLETED")
        # Should redirect back to detail page
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(repair.id), response["Location"])

    def test_approve_already_approved_rejected(self):
        """POSTing approve on an already APPROVED repair must be a no-op."""
        repair = _make_repair(self.customer, self.tech, status="APPROVED")
        response = self._post_approve(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "APPROVED")
        self.assertEqual(response.status_code, 302)

    def test_approve_in_progress_rejected(self):
        """POSTing approve on an IN_PROGRESS repair must not change status."""
        repair = _make_repair(self.customer, self.tech, status="IN_PROGRESS")
        response = self._post_approve(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "IN_PROGRESS")
        self.assertEqual(response.status_code, 302)

    def test_approve_requested_succeeds(self):
        """REQUESTED repairs (customer-initiated) can also be approved."""
        repair = _make_repair(self.customer, self.tech, status="REQUESTED")
        response = self._post_approve(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "APPROVED")
        self.assertEqual(response.status_code, 302)


class RepairDenyStatusGuardTests(TestCase):
    """customer_repair_deny() must reject non-pending repairs."""

    def setUp(self):
        self.tenant = _make_tenant("DenyGuard Shop")
        self.customer = _make_customer(self.tenant)
        self.tech = _make_tech(self.tenant)

        self.cu_user = User.objects.create_user(username="cuuser2", password="pw")
        self.cu = _make_customer_user(self.cu_user, self.customer)

        self.client = Client()
        self.client.force_login(self.cu_user)

    def _post_deny(self, repair, reason="test reason"):
        url = reverse("customer_repair_deny", kwargs={"repair_id": repair.id})
        return self.client.post(url, {"reason": reason}, follow=False)

    def test_deny_pending_succeeds(self):
        """Denying a PENDING repair must succeed."""
        repair = _make_repair(self.customer, self.tech, status="PENDING")
        response = self._post_deny(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "DENIED")
        self.assertEqual(response.status_code, 302)

    def test_deny_completed_rejected(self):
        """POSTing deny on a COMPLETED repair must not change its status."""
        repair = _make_repair(self.customer, self.tech, status="COMPLETED")
        response = self._post_deny(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "COMPLETED")
        self.assertEqual(response.status_code, 302)

    def test_deny_already_denied_rejected(self):
        """POSTing deny on an already DENIED repair must not change status."""
        repair = _make_repair(self.customer, self.tech, status="DENIED")
        response = self._post_deny(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, "DENIED")
        self.assertEqual(response.status_code, 302)


class BatchApproveStatusGuardTests(TestCase):
    """customer_batch_approve() must reject batches with non-pending repairs."""

    def setUp(self):
        self.tenant = _make_tenant("BatchApprove Shop")
        self.customer = _make_customer(self.tenant)
        self.tech = _make_tech(self.tenant, username="techba")

        self.cu_user = User.objects.create_user(username="cuuserba", password="pw")
        self.cu = _make_customer_user(self.cu_user, self.customer)

        self.client = Client()
        self.client.force_login(self.cu_user)

    def _make_batch(self, statuses):
        """Create a batch of repairs with specified statuses."""
        batch_id = uuid.uuid4()
        repairs = []
        for i, status in enumerate(statuses):
            r = Repair.objects.create(
                customer=self.customer,
                technician=self.tech,
                tenant=self.tenant,
                unit_number="BATCH-UNIT",
                damage_type="CHIP",
                queue_status=status,
                service_date=date.today(),
                cost=Decimal("75.00"),
                repair_batch_id=batch_id,
                break_number=i + 1,
                total_breaks_in_batch=len(statuses),
            )
            repairs.append(r)
        return batch_id, repairs

    def _post_batch_approve(self, batch_id):
        url = reverse("customer_batch_approve", kwargs={"batch_id": batch_id})
        return self.client.post(url, {}, follow=False)

    def test_batch_approve_all_pending_succeeds(self):
        """Batch approve works when all repairs are PENDING."""
        batch_id, repairs = self._make_batch(["PENDING", "PENDING"])
        response = self._post_batch_approve(batch_id)
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, "APPROVED")
        self.assertEqual(response.status_code, 302)

    def test_batch_approve_mixed_pending_completed_rejected(self):
        """Batch approve must be rejected when any repair is COMPLETED."""
        batch_id, repairs = self._make_batch(["PENDING", "COMPLETED"])
        response = self._post_batch_approve(batch_id)
        # No repair should change status
        statuses = [Repair.objects.get(pk=r.pk).queue_status for r in repairs]
        self.assertIn("PENDING", statuses)
        self.assertIn("COMPLETED", statuses)
        # No repair flipped to APPROVED
        self.assertNotIn("APPROVED", statuses)
        self.assertEqual(response.status_code, 302)

    def test_batch_approve_all_completed_rejected(self):
        """Batch approve must be rejected when all repairs are COMPLETED."""
        batch_id, repairs = self._make_batch(["COMPLETED", "COMPLETED"])
        response = self._post_batch_approve(batch_id)
        statuses = [Repair.objects.get(pk=r.pk).queue_status for r in repairs]
        self.assertTrue(all(s == "COMPLETED" for s in statuses))
        self.assertEqual(response.status_code, 302)

    def test_batch_approve_requested_succeeds(self):
        """Batch approve works when all repairs are REQUESTED."""
        batch_id, repairs = self._make_batch(["REQUESTED", "REQUESTED"])
        response = self._post_batch_approve(batch_id)
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, "APPROVED")
        self.assertEqual(response.status_code, 302)


class BatchDenyStatusGuardTests(TestCase):
    """customer_batch_deny() must reject batches with non-pending repairs."""

    def setUp(self):
        self.tenant = _make_tenant("BatchDeny Shop")
        self.customer = _make_customer(self.tenant)
        self.tech = _make_tech(self.tenant, username="techbd")

        self.cu_user = User.objects.create_user(username="cuuserbd", password="pw")
        self.cu = _make_customer_user(self.cu_user, self.customer)

        self.client = Client()
        self.client.force_login(self.cu_user)

    def _make_batch(self, statuses):
        batch_id = uuid.uuid4()
        repairs = []
        for i, status in enumerate(statuses):
            r = Repair.objects.create(
                customer=self.customer,
                technician=self.tech,
                tenant=self.tenant,
                unit_number="DENY-UNIT",
                damage_type="CHIP",
                queue_status=status,
                service_date=date.today(),
                cost=Decimal("75.00"),
                repair_batch_id=batch_id,
                break_number=i + 1,
                total_breaks_in_batch=len(statuses),
            )
            repairs.append(r)
        return batch_id, repairs

    def _post_batch_deny(self, batch_id):
        url = reverse("customer_batch_deny", kwargs={"batch_id": batch_id})
        return self.client.post(url, {"reason": "test denial"}, follow=False)

    def test_batch_deny_all_pending_succeeds(self):
        """Batch deny works when all repairs are PENDING."""
        batch_id, repairs = self._make_batch(["PENDING", "PENDING"])
        response = self._post_batch_deny(batch_id)
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, "DENIED")
        self.assertEqual(response.status_code, 302)

    def test_batch_deny_completed_rejected(self):
        """Batch deny must be rejected when any repair is COMPLETED."""
        batch_id, repairs = self._make_batch(["PENDING", "COMPLETED"])
        response = self._post_batch_deny(batch_id)
        statuses = [Repair.objects.get(pk=r.pk).queue_status for r in repairs]
        self.assertNotIn("DENIED", statuses)
        self.assertEqual(response.status_code, 302)

    def test_batch_deny_all_completed_rejected(self):
        """Batch deny must be rejected when all repairs are COMPLETED."""
        batch_id, repairs = self._make_batch(["COMPLETED", "COMPLETED"])
        response = self._post_batch_deny(batch_id)
        statuses = [Repair.objects.get(pk=r.pk).queue_status for r in repairs]
        self.assertTrue(all(s == "COMPLETED" for s in statuses))
        self.assertEqual(response.status_code, 302)
