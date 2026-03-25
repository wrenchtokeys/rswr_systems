"""
Regression tests for CODE-189: WarrantyService.get_all_warranty_repairs() raised
NameError: name 'models' is not defined.

Bug:
    apps/technician_portal/warranty_service.py used `models.Q(...)` in
    `get_all_warranty_repairs()` but `models` was never imported.
    The file only imported `from django.db import transaction` — not `models`.

    Any call to `get_all_warranty_repairs()` would raise:
        NameError: name 'models' is not defined

    This would crash in any code path that needs to enumerate all active
    warranties for a tenant (e.g. admin reports, dashboard, email notifications).

Fix:
    Added `from django.db import models, transaction` and `from django.db.models import Q`
    to the imports. Changed `models.Q(...)` → `Q(...)`.

Root cause pattern: Incremental development — the `Q` expression was added to
`get_all_warranty_repairs` without adding the import. `assign_warranty`,
`get_active_warranty`, `void_warranty`, and `check_warranty_valid` don't use
`Q` or `models`, so the module imported fine; the error only surfaces at
runtime when `get_all_warranty_repairs` is actually called.
"""
import inspect
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from tests.helpers import make_tenant


class WarrantyServiceImportTest(TestCase):
    """WarrantyService module must import without NameError."""

    def test_module_imports_cleanly(self):
        """Importing WarrantyService must not raise NameError."""
        try:
            from apps.technician_portal.warranty_service import WarrantyService  # noqa: F401
        except NameError as e:
            self.fail(f"WarrantyService import raised NameError: {e}")

    def test_get_all_warranty_repairs_is_callable(self):
        """get_all_warranty_repairs must exist and accept a tenant arg."""
        from apps.technician_portal.warranty_service import WarrantyService
        sig = inspect.signature(WarrantyService.get_all_warranty_repairs)
        params = list(sig.parameters.keys())
        self.assertIn('tenant', params)


class WarrantyServiceGetAllTest(TestCase):
    """
    get_all_warranty_repairs() must return correct QuerySets without NameError.
    """

    def setUp(self):
        self.user_a, self.tenant_a = make_tenant('WarrantyShop A', 'wa_owner')
        self.user_b, self.tenant_b = make_tenant('WarrantyShop B', 'wb_owner')

        from apps.technician_portal.models import Customer, Technician, Repair, WarrantyPolicy

        self.policy_a = WarrantyPolicy.objects.create(
            tenant=self.tenant_a,
            name='Standard Warranty A',
            applies_to='all_repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a, name='Fleet A',
        )

        # Need a Technician for repair FK
        tech_user = User.objects.create_user('wa_tech', 'watech@test.com', 'pass')
        self.technician_a = Technician.objects.create(
            tenant=self.tenant_a, user=tech_user, can_repair=True, is_active=True,
        )

        # Repair with active warranty (expires in future)
        self.repair_active = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='T1',
            queue_status='COMPLETED',
            technician=self.technician_a,
            warranty_policy=self.policy_a,
            warranty_expires_at=timezone.now() + timezone.timedelta(days=200),
            warranty_void=False,
        )

        # Repair with lifetime warranty (expires_at=None, policy set)
        self.repair_lifetime = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='T2',
            queue_status='COMPLETED',
            technician=self.technician_a,
            warranty_policy=self.policy_a,
            warranty_expires_at=None,  # lifetime
            warranty_void=False,
        )

        # Repair with expired warranty
        self.repair_expired = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='T3',
            queue_status='COMPLETED',
            technician=self.technician_a,
            warranty_policy=self.policy_a,
            warranty_expires_at=timezone.now() - timezone.timedelta(days=10),
            warranty_void=False,
        )

        # Repair with voided warranty
        self.repair_voided = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='T4',
            queue_status='COMPLETED',
            technician=self.technician_a,
            warranty_policy=self.policy_a,
            warranty_expires_at=timezone.now() + timezone.timedelta(days=100),
            warranty_void=True,
            warranty_void_reason='New impact damage',
        )

        # Repair with no warranty
        self.repair_no_warranty = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='T5',
            queue_status='COMPLETED',
            technician=self.technician_a,
        )

    def _call_get_all(self, tenant):
        """Call get_all_warranty_repairs and catch NameError explicitly."""
        from apps.technician_portal.warranty_service import WarrantyService
        try:
            return list(WarrantyService.get_all_warranty_repairs(tenant))
        except NameError as e:
            self.fail(
                f"get_all_warranty_repairs raised NameError — missing import fix not applied: {e}"
            )

    def test_no_name_error_raised(self):
        """
        Regression: calling get_all_warranty_repairs must NOT raise NameError.
        Before fix: `models.Q(...)` caused NameError: name 'models' is not defined.
        """
        # This is the primary regression guard — just calling the method is enough.
        self._call_get_all(self.tenant_a)

    def test_returns_active_timed_warranty(self):
        """Active non-expired timed warranties are included."""
        results = self._call_get_all(self.tenant_a)
        pks = [r.pk for r in results]
        self.assertIn(self.repair_active.pk, pks)

    def test_returns_lifetime_warranty(self):
        """Lifetime warranties (expires_at=None, policy set) are included."""
        results = self._call_get_all(self.tenant_a)
        pks = [r.pk for r in results]
        self.assertIn(self.repair_lifetime.pk, pks)

    def test_excludes_expired_warranty(self):
        """Expired warranties are excluded."""
        results = self._call_get_all(self.tenant_a)
        pks = [r.pk for r in results]
        self.assertNotIn(self.repair_expired.pk, pks)

    def test_excludes_voided_warranty(self):
        """Voided warranties are excluded."""
        results = self._call_get_all(self.tenant_a)
        pks = [r.pk for r in results]
        self.assertNotIn(self.repair_voided.pk, pks)

    def test_excludes_no_warranty_repairs(self):
        """Repairs with no warranty assigned are excluded."""
        results = self._call_get_all(self.tenant_a)
        pks = [r.pk for r in results]
        self.assertNotIn(self.repair_no_warranty.pk, pks)

    def test_tenant_isolation(self):
        """Results are scoped to the requested tenant only."""
        results_a = self._call_get_all(self.tenant_a)
        results_b = self._call_get_all(self.tenant_b)

        for r in results_a:
            self.assertEqual(r.tenant_id, self.tenant_a.pk)

        # Tenant B has no warranties
        self.assertEqual(len(results_b), 0)
