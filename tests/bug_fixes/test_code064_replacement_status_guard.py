"""
Regression tests for CODE-064:
  replacement_update_status() accepted ANY valid status string — including
  backward/illegal transitions.  A shop owner (or manager) could POST
  status=REQUESTED to a COMPLETED replacement and reopen it, or
  status=APPROVED to a DENIED replacement.

Root cause:
    The view only checked ``new_status not in valid_statuses`` but never
    verified the transition was legal from the *current* state.  COMPLETED
    replacements may already have InvoiceLineItem rows; reopening them causes
    the replacement to be picked up by future invoice generation → double-billing.

Fix (CODE-064):
    Introduced ALLOWED_TRANSITIONS dict mapping current status → set of
    reachable next statuses.  COMPLETED and DENIED are terminal (empty set).
    Any POST outside the allowed set is rejected with an error message and
    a redirect back to the detail page — status unchanged.

Tests verify:
1. Valid forward transition REQUESTED → PENDING succeeds.
2. Valid forward transition PENDING → APPROVED succeeds.
3. Valid forward transition APPROVED → IN_PROGRESS succeeds.
4. Valid forward transition IN_PROGRESS → COMPLETED succeeds.
5. Valid forward transition APPROVED → DENIED (early denial) succeeds.
6. Backward transition: COMPLETED → REQUESTED rejected, status unchanged.
7. Backward transition: COMPLETED → APPROVED rejected, status unchanged.
8. Backward transition: DENIED → APPROVED rejected, status unchanged.
9. Backward transition: IN_PROGRESS → REQUESTED rejected, status unchanged.
10. Completely invalid status string rejected.
11. Terminal COMPLETED: any POST rejected with the terminal-state message.
12. Terminal DENIED: any POST rejected with the terminal-state message.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.technician_portal.models import Replacement
from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(name="Test Shop"):
    owner_user, _ = User.objects.get_or_create(
        username=f"_owner_{name.lower().replace(' ', '_')}",
        defaults={"email": f"owner_{name.lower().replace(' ', '_')}@example.com"},
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


def _make_customer(tenant, name="Acme Glass"):
    return Customer.objects.create(name=name, tenant=tenant)


def _make_technician(tenant, username="tech1"):
    from apps.technician_portal.models import Technician
    tech_user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pw",
    )
    TenantMembership.objects.create(tenant=tenant, user=tech_user, role="technician", is_active=True)
    return Technician.objects.create(
        tenant=tenant,
        user=tech_user,
        is_active=True,
        can_repair=True,
    )


def _make_replacement(tenant, customer, technician, status="REQUESTED"):
    return Replacement.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        queue_status=status,
        service_date=date.today(),
        unit_number="UNIT-1",
        glass_position="WINDSHIELD",
        cost=Decimal("350.00"),
    )


class ReplacementStatusGuardTestCase(TestCase):
    """
    Verify that replacement_update_status enforces valid-transition logic.
    """

    def setUp(self):
        self.tenant = _make_tenant("Guard Shop")
        self.owner = _make_owner(self.tenant, username="guard_owner", email="guard@example.com")
        self.customer = _make_customer(self.tenant)
        self.technician = _make_technician(self.tenant, username="guard_tech1")

        self.client = Client()
        self.client.force_login(self.owner)

    def _url(self, pk):
        return reverse("replacement_update_status", args=[pk])

    def _post(self, pk, new_status):
        # Set tenant via session so TenantMiddleware resolves request.tenant.
        # Use the default Django test host ('testserver') so ALLOWED_HOSTS lets
        # the request through; the subdomain-based routing isn't active in tests.
        session = self.client.session
        session["tenant_id"] = self.tenant.id
        session.save()
        return self.client.post(
            self._url(pk),
            {"status": new_status},
        )

    # ------------------------------------------------------------------
    # Happy paths — valid forward transitions
    # ------------------------------------------------------------------

    def test_requested_to_pending_succeeds(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="REQUESTED")
        self._post(rep.pk, "PENDING")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "PENDING")

    def test_pending_to_approved_succeeds(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="PENDING")
        self._post(rep.pk, "APPROVED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "APPROVED")

    def test_approved_to_in_progress_succeeds(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="APPROVED")
        self._post(rep.pk, "IN_PROGRESS")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "IN_PROGRESS")

    def test_in_progress_to_completed_succeeds(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="IN_PROGRESS")
        self._post(rep.pk, "COMPLETED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "COMPLETED")

    def test_approved_to_denied_succeeds(self):
        """Early denial from APPROVED is a valid transition."""
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="APPROVED")
        self._post(rep.pk, "DENIED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "DENIED")

    # ------------------------------------------------------------------
    # Backward/illegal transitions — must be rejected
    # ------------------------------------------------------------------

    def test_completed_to_requested_rejected(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="COMPLETED")
        self._post(rep.pk, "REQUESTED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "COMPLETED",
                         "COMPLETED→REQUESTED must not change status")

    def test_completed_to_approved_rejected(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="COMPLETED")
        self._post(rep.pk, "APPROVED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "COMPLETED",
                         "COMPLETED→APPROVED must not change status")

    def test_denied_to_approved_rejected(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="DENIED")
        self._post(rep.pk, "APPROVED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "DENIED",
                         "DENIED→APPROVED must not change status")

    def test_in_progress_to_requested_rejected(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="IN_PROGRESS")
        self._post(rep.pk, "REQUESTED")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "IN_PROGRESS",
                         "IN_PROGRESS→REQUESTED must not change status")

    def test_invalid_status_string_rejected(self):
        rep = _make_replacement(self.tenant, self.customer, self.technician, status="REQUESTED")
        self._post(rep.pk, "NOTASTATUS")
        rep.refresh_from_db()
        self.assertEqual(rep.queue_status, "REQUESTED",
                         "Invalid status string must not change status")

    # ------------------------------------------------------------------
    # Terminal states — any POST rejected
    # ------------------------------------------------------------------

    def test_completed_terminal_any_transition_rejected(self):
        """COMPLETED is terminal — every posted status must be rejected."""
        for attempted in ["REQUESTED", "PENDING", "APPROVED", "IN_PROGRESS", "DENIED"]:
            rep = _make_replacement(self.tenant, self.customer, self.technician, status="COMPLETED")
            self._post(rep.pk, attempted)
            rep.refresh_from_db()
            self.assertEqual(
                rep.queue_status, "COMPLETED",
                f"COMPLETED→{attempted} must not change status"
            )

    def test_denied_terminal_any_transition_rejected(self):
        """DENIED is terminal — every posted status must be rejected."""
        for attempted in ["REQUESTED", "PENDING", "APPROVED", "IN_PROGRESS", "COMPLETED"]:
            rep = _make_replacement(self.tenant, self.customer, self.technician, status="DENIED")
            self._post(rep.pk, attempted)
            rep.refresh_from_db()
            self.assertEqual(
                rep.queue_status, "DENIED",
                f"DENIED→{attempted} must not change status"
            )
