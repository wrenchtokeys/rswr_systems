"""
CODE-009 Regression: Admin managed_technicians queryset must be tenant-scoped.

Before fix: TechnicianAdmin.get_form() built the managed_technicians queryset
from ALL active technicians across ALL tenants. A superuser editing a manager
from Tenant A would see techs from Tenant B in the M2M picker, and could assign
them — bypassing the same-tenant rule entirely.

After fix:
1. get_form() filters the queryset to obj.tenant when editing an existing manager.
2. save_related() calls validate_managed_technicians() to strip any cross-tenant
   techs that sneak through (e.g. when obj has no tenant yet, or obj is new).
"""

from django.test import TestCase
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from apps.technician_portal.admin import TechnicianAdmin
from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant, SubscriptionPlan


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name="Test Plan",
        defaults={
            "monthly_price": 0,
            "max_technicians": 10,
            "max_customers": 100,
            "trial_days": 14,
        },
    )
    return plan


def _make_tenant(name):
    plan = _make_plan()
    owner = User.objects.create_user(
        username=f"owner_{name.lower().replace(' ', '_')}",
        email=f"owner_{name.lower().replace(' ', '_')}@example.com",
        password="pass",
    )
    tenant = Tenant.objects.create(
        name=name,
        subdomain=name.lower().replace(" ", "-"),
        subscription_plan=plan,
        owner=owner,
    )
    return tenant


def _make_tech(tenant, username, is_manager=False):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pass",
        first_name=username,
        last_name="Test",
    )
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        expertise="CHIP",
        is_manager=is_manager,
        is_active=True,
    )
    return tech


class ManagedTechnicianAdminQuerysetTest(TestCase):
    """
    TechnicianAdmin.get_form() managed_technicians queryset must be
    scoped to the manager's tenant.
    """

    def setUp(self):
        self.site = AdminSite()
        self.admin = TechnicianAdmin(Technician, self.site)

        self.tenant_a = _make_tenant("Shop A")
        self.tenant_b = _make_tenant("Shop B")

        self.manager_a = _make_tech(self.tenant_a, "mgr_a", is_manager=True)
        self.tech_a1 = _make_tech(self.tenant_a, "tech_a1")
        self.tech_a2 = _make_tech(self.tenant_a, "tech_a2")
        self.tech_b1 = _make_tech(self.tenant_b, "tech_b1")
        self.tech_b2 = _make_tech(self.tenant_b, "tech_b2")

        # Superuser request
        self.superuser = User.objects.create_superuser(
            username="super", email="super@example.com", password="pass"
        )

    def _make_request(self):
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get("/admin/")
        req.user = self.superuser
        return req

    def test_managed_technicians_queryset_excludes_other_tenant(self):
        """When editing an existing manager, M2M picker must not show foreign-tenant techs."""
        request = self._make_request()
        form = self.admin.get_form(request, obj=self.manager_a)

        if "managed_technicians" not in form.base_fields:
            self.skipTest("managed_technicians not in form fields")

        qs = form.base_fields["managed_technicians"].queryset
        ids = list(qs.values_list("id", flat=True))

        # Tenant B techs must NOT appear
        self.assertNotIn(self.tech_b1.id, ids, "tech_b1 (Tenant B) must not appear in Tenant A manager's picker")
        self.assertNotIn(self.tech_b2.id, ids, "tech_b2 (Tenant B) must not appear in Tenant A manager's picker")

    def test_managed_technicians_queryset_includes_same_tenant(self):
        """Picker must still show active techs from the same tenant."""
        request = self._make_request()
        form = self.admin.get_form(request, obj=self.manager_a)

        if "managed_technicians" not in form.base_fields:
            self.skipTest("managed_technicians not in form fields")

        qs = form.base_fields["managed_technicians"].queryset
        ids = list(qs.values_list("id", flat=True))

        self.assertIn(self.tech_a1.id, ids, "tech_a1 (same tenant) must appear in picker")
        self.assertIn(self.tech_a2.id, ids, "tech_a2 (same tenant) must appear in picker")

    def test_managed_technicians_queryset_excludes_self(self):
        """Manager must not appear in their own managed_technicians picker."""
        request = self._make_request()
        form = self.admin.get_form(request, obj=self.manager_a)

        if "managed_technicians" not in form.base_fields:
            self.skipTest("managed_technicians not in form fields")

        qs = form.base_fields["managed_technicians"].queryset
        ids = list(qs.values_list("id", flat=True))

        self.assertNotIn(self.manager_a.id, ids, "Manager must not appear in their own picker")


class ValidateManagedTechniciansTest(TestCase):
    """
    validate_managed_technicians() must strip cross-tenant techs and raise.
    save_related() must call it so M2M saves are safe.
    """

    def setUp(self):
        self.tenant_a = _make_tenant("Shop X")
        self.tenant_b = _make_tenant("Shop Y")
        self.manager_a = _make_tech(self.tenant_a, "mgr_x", is_manager=True)
        self.tech_b = _make_tech(self.tenant_b, "tech_y")
        self.tech_a = _make_tech(self.tenant_a, "tech_x")

    def test_validate_strips_cross_tenant_techs(self):
        """validate_managed_technicians() removes foreign-tenant techs."""
        from django.core.exceptions import ValidationError

        # Force-add a cross-tenant tech (bypassing the form)
        self.manager_a.managed_technicians.add(self.tech_b)
        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

        with self.assertRaises(ValidationError):
            self.manager_a.validate_managed_technicians()

        # The cross-tenant tech should have been removed
        self.assertEqual(self.manager_a.managed_technicians.count(), 0)

    def test_validate_keeps_same_tenant_techs(self):
        """validate_managed_technicians() does not remove same-tenant techs."""
        self.manager_a.managed_technicians.add(self.tech_a)
        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

        # Should not raise
        self.manager_a.validate_managed_technicians()

        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

    def test_save_related_calls_validate(self):
        """
        TechnicianAdmin.save_related() must call validate_managed_technicians()
        so cross-tenant techs are stripped even if they reach the save step.
        """
        site = AdminSite()
        admin_obj = TechnicianAdmin(Technician, site)

        # Force-add a cross-tenant tech
        self.manager_a.managed_technicians.add(self.tech_b)
        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

        # Simulate what admin does: build a minimal mock form
        class MockForm:
            instance = self.manager_a
            def save_m2m(self):
                pass

        # save_related signature: (request, form, formsets, change)
        admin_obj.save_related(request=None, form=MockForm(), formsets=[], change=True)

        # Cross-tenant tech must be gone
        self.manager_a.refresh_from_db()
        self.assertEqual(
            self.manager_a.managed_technicians.count(), 0,
            "save_related must strip cross-tenant techs via validate_managed_technicians()"
        )
