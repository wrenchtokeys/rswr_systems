"""
Regression tests for CODE-079:
    assign_repair() and reassign_to_self() used getattr(request.user, 'technician', None)
    to check is_manager. This reverse OneToOne lookup is NOT tenant-scoped — a manager
    from Shop A could act as manager in Shop B's portal context.

    Fix: both views now use
        Technician.objects.filter(user=request.user, tenant=tenant).first()
    so that Shop A manager is denied manager access in Shop B.

Covers:
    - assign_repair: Shop A manager with no Technician record at Shop B → redirect
    - assign_repair: POST by cross-tenant manager → redirect, repair unchanged
    - assign_repair: Legitimate Shop A manager at Shop A repair → 200 GET
    - reassign_to_self: Shop A manager with no Technician at Shop B → redirect
    - reassign_to_self: POST by cross-tenant manager → redirect, repair unchanged
    - reassign_to_self: Legitimate Shop B manager reassigns → repair changes owner
"""

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import TestCase, RequestFactory

from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_counter = [0]


def _uid():
    _counter[0] += 1
    return _counter[0]


def _make_request(method, url, user, tenant, data=None):
    factory = RequestFactory()
    req = factory.post(url, data or {}) if method == "POST" else factory.get(url)
    req.user = user
    req.tenant = tenant
    setattr(req, "session", "session")
    setattr(req, "_messages", FallbackStorage(req))
    return req


def _make_user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
        first_name="Test",
        last_name=username.capitalize(),
    )


def _make_tenant(name, slug):
    owner = _make_user(f"owner_{slug}_{_uid()}")
    return Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner, is_active=True
    )


def _make_tech(user, tenant, is_manager=False, can_assign_work=True):
    TenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"role": "technician", "is_active": True}
    )
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_active=True,
        is_manager=is_manager,
        can_assign_work=can_assign_work,
    )


def _make_repair(customer, tenant, technician=None, status="REQUESTED"):
    n = _uid()
    if technician is None:
        dummy = _make_user(f"dummy_tech_{n}")
        TenantMembership.objects.create(tenant=tenant, user=dummy, role="technician", is_active=True)
        technician = Technician.objects.create(user=dummy, tenant=tenant, is_active=True)
    return Repair.objects.create(
        customer=customer,
        tenant=tenant,
        technician=technician,
        unit_number=f"UNIT-{n}",
        damage_type="CHIP",
        queue_status=status,
    )


# ---------------------------------------------------------------------------
# assign_repair tests
# ---------------------------------------------------------------------------

class AssignRepairCrossTenantTest(TestCase):
    """Shop A manager (no Technician record at Shop B) cannot assign Shop B repairs."""

    def setUp(self):
        self.shop_a = _make_tenant("Shop A", f"shop-a-ar-{_uid()}")
        self.shop_b = _make_tenant("Shop B", f"shop-b-ar-{_uid()}")

        # Manager belongs ONLY to Shop A
        self.manager_user = _make_user(f"mgr_a_ar_{_uid()}")
        self.manager_tech = _make_tech(
            self.manager_user, self.shop_a, is_manager=True, can_assign_work=True
        )

        # Regular tech in Shop B (target for assignment)
        self.tech_b_user = _make_user(f"tech_b_ar_{_uid()}")
        self.tech_b = _make_tech(self.tech_b_user, self.shop_b)

        customer_b = Customer.objects.create(
            name=f"Customer B {_uid()}", tenant=self.shop_b
        )
        self.repair_b = _make_repair(customer_b, self.shop_b, status="REQUESTED")

    def test_cross_tenant_manager_assign_get_is_redirected(self):
        """GET assign_repair by Shop A manager in Shop B context → 302 redirect."""
        from apps.technician_portal.views.repairs import assign_repair

        req = _make_request("GET", f"/tech/repairs/{self.repair_b.id}/assign/",
                            self.manager_user, self.shop_b)
        response = assign_repair(req, repair_id=self.repair_b.id)
        # Should redirect because no Technician record at shop_b
        self.assertEqual(response.status_code, 302)

    def test_cross_tenant_manager_assign_post_does_not_change_repair(self):
        """POST assign_repair by Shop A manager in Shop B context → redirect, repair unchanged."""
        from apps.technician_portal.views.repairs import assign_repair

        req = _make_request(
            "POST",
            f"/tech/repairs/{self.repair_b.id}/assign/",
            self.manager_user,
            self.shop_b,
            data={"technician_id": str(self.tech_b.id)},
        )
        response = assign_repair(req, repair_id=self.repair_b.id)
        self.assertEqual(response.status_code, 302)
        self.repair_b.refresh_from_db()
        # Must not have been assigned / status must not have changed
        self.assertEqual(self.repair_b.queue_status, "REQUESTED")

    def test_legitimate_manager_assign_get_succeeds(self):
        """GET assign_repair by Shop A manager in Shop A context → 200."""
        from apps.technician_portal.views.repairs import assign_repair

        customer_a = Customer.objects.create(
            name=f"Customer A {_uid()}", tenant=self.shop_a
        )
        repair_a = _make_repair(customer_a, self.shop_a, status="REQUESTED")
        req = _make_request("GET", f"/tech/repairs/{repair_a.id}/assign/",
                            self.manager_user, self.shop_a)
        response = assign_repair(req, repair_id=repair_a.id)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# reassign_to_self tests
# ---------------------------------------------------------------------------

class ReassignToSelfCrossTenantTest(TestCase):
    """Shop A manager (no Technician at Shop B) cannot reassign Shop B repairs."""

    def setUp(self):
        self.shop_a = _make_tenant("Shop A", f"shop-a-rs-{_uid()}")
        self.shop_b = _make_tenant("Shop B", f"shop-b-rs-{_uid()}")

        # Manager belongs ONLY to Shop A
        self.manager_user = _make_user(f"mgr_a_rs_{_uid()}")
        self.manager_tech = _make_tech(
            self.manager_user, self.shop_a, is_manager=True, can_assign_work=True
        )

        # Tech in Shop B — repair assigned to them
        self.tech_b_user = _make_user(f"tech_b_rs_{_uid()}")
        self.tech_b = _make_tech(self.tech_b_user, self.shop_b)

        customer_b = Customer.objects.create(
            name=f"Customer B {_uid()}", tenant=self.shop_b
        )
        self.repair_b = _make_repair(
            customer_b, self.shop_b, technician=self.tech_b, status="APPROVED"
        )

    def test_cross_tenant_manager_reassign_get_is_redirected(self):
        """GET reassign_to_self by Shop A manager in Shop B context → 302 redirect."""
        from apps.technician_portal.views.repairs import reassign_to_self

        req = _make_request(
            "GET",
            f"/tech/repairs/{self.repair_b.id}/reassign-to-self/",
            self.manager_user,
            self.shop_b,
        )
        response = reassign_to_self(req, repair_id=self.repair_b.id)
        self.assertEqual(response.status_code, 302)

    def test_cross_tenant_manager_reassign_post_does_not_change_repair(self):
        """POST reassign_to_self by Shop A manager in Shop B context → repair unchanged."""
        from apps.technician_portal.views.repairs import reassign_to_self

        req = _make_request(
            "POST",
            f"/tech/repairs/{self.repair_b.id}/reassign-to-self/",
            self.manager_user,
            self.shop_b,
            data={},
        )
        response = reassign_to_self(req, repair_id=self.repair_b.id)
        self.assertEqual(response.status_code, 302)
        self.repair_b.refresh_from_db()
        # Repair must still belong to tech_b
        self.assertEqual(self.repair_b.technician_id, self.tech_b.id)

    def test_legitimate_manager_reassign_post_succeeds(self):
        """POST reassign_to_self by a Shop B manager → repair reassigned to manager."""
        from apps.technician_portal.views.repairs import reassign_to_self

        manager_b_user = _make_user(f"mgr_b_rs_{_uid()}")
        manager_b_tech = _make_tech(
            manager_b_user, self.shop_b, is_manager=True, can_assign_work=True
        )
        manager_b_tech.managed_technicians.add(self.tech_b)

        req = _make_request(
            "POST",
            f"/tech/repairs/{self.repair_b.id}/reassign-to-self/",
            manager_b_user,
            self.shop_b,
            data={},
        )
        response = reassign_to_self(req, repair_id=self.repair_b.id)
        self.assertEqual(response.status_code, 302)
        self.repair_b.refresh_from_db()
        self.assertEqual(self.repair_b.technician_id, manager_b_tech.id)
