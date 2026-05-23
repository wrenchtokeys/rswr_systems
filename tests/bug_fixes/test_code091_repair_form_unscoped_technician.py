"""
Regression tests for CODE-091:
RepairForm used unscoped self.user.technician in __init__ and clean().

Root cause:
  apps/technician_portal/forms.py — RepairForm:
  1. __init__: `self.user.technician` to decide whether to show pricing override
     fields (cost_override, override_reason).
  2. clean(): `self.user.technician` to validate pricing override permissions and
     approval_limit.
  3. clean(): `self.user.technician.is_manager` to let managers skip the
     after-photo requirement.

  All three used the bare OneToOneField accessor, which resolves globally —
  returning whichever Technician row exists for the user, regardless of tenant.
  A manager at Shop A could:
    (a) See/submit pricing override fields in Shop B's repair form.
    (b) Bypass cost_override permission checks in Shop B.
    (c) Submit repairs in Shop B without an after-photo.

  The form already received `tenant` as a kwarg; the fix is to use
  Technician.objects.filter(user=..., tenant=...).first() in all three places.

Test scenarios:
  A. Manager at Shop A does NOT see override fields in Shop B's form.
  B. Non-manager at Shop A does NOT see override fields (baseline).
  C. Manager at Shop B DOES see override fields in Shop B's form.
  D. Clean rejects cost_override submitted by cross-tenant manager (Shop A manager, Shop B form).
  E. Clean rejects after-photo bypass for cross-tenant manager (Shop A manager, Shop B form).
  F. Clean allows pricing override by correct Shop B manager.
  G. Clean allows after-photo bypass for correct Shop B manager.
  H. Form with no tenant context falls back gracefully (staff/superuser path).
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Customer
from apps.tenants.models import Tenant
from apps.technician_portal.models import Technician, Repair
from apps.technician_portal.forms import RepairForm


_counter = [9000]


def _uid():
    _counter[0] += 1
    return _counter[0]


def _make_user(prefix='u'):
    n = _uid()
    return User.objects.create_user(
        username=f'{prefix}_{n}',
        email=f'{prefix}_{n}@example.com',
        password='pw',
    )


def _make_tenant(name_prefix='shop', owner=None):
    n = _uid()
    if owner is None:
        owner = _make_user(f'owner_{name_prefix}')
    return Tenant.objects.create(
        name=f'{name_prefix} {n}',
        slug=f'{name_prefix}-{n}',
        plan='pro',
        owner=owner,
    )


def _make_technician(user, tenant, is_manager=False, can_override_pricing=False,
                     approval_limit=None, can_repair=True):
    """Helper to create a Technician linked to a user+tenant."""
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=is_manager,
        can_override_pricing=can_override_pricing,
        approval_limit=approval_limit,
        can_repair=can_repair,
        is_active=True,
    )


def _make_customer(tenant, name='Fleet Co'):
    return Customer.objects.create(
        name=name,
        tenant=tenant,
        customer_type='FLEET',
    )


class RepairFormUnscopedTechnicianTest(TestCase):
    """CODE-091: RepairForm.user.technician must be scoped to current tenant."""

    def setUp(self):
        # --- Shop A ---
        self.manager_a_user = _make_user('mgr_a')
        self.tenant_a = _make_tenant('alpha', owner=self.manager_a_user)
        self.manager_a = _make_technician(
            self.manager_a_user, self.tenant_a,
            is_manager=True, can_override_pricing=True, approval_limit=Decimal('500.00'),
        )
        self.customer_a = _make_customer(self.tenant_a, 'Fleet Alpha')

        # --- Shop B ---
        self.manager_b_user = _make_user('mgr_b')
        self.tenant_b = _make_tenant('beta', owner=self.manager_b_user)
        self.manager_b = _make_technician(
            self.manager_b_user, self.tenant_b,
            is_manager=True, can_override_pricing=True, approval_limit=Decimal('300.00'),
        )
        self.regular_b_user = _make_user('reg_b')
        self.regular_b = _make_technician(self.regular_b_user, self.tenant_b, is_manager=False)
        self.customer_b = _make_customer(self.tenant_b, 'Fleet Beta')

    # ------------------------------------------------------------------ #
    # A: Cross-tenant manager should NOT see override fields               #
    # ------------------------------------------------------------------ #
    def test_cross_tenant_manager_override_fields_hidden(self):
        """Manager from Shop A viewing Shop B form: override fields must be hidden."""
        form = RepairForm(user=self.manager_a_user, tenant=self.tenant_b)
        # cost_override should be a HiddenInput — manager_a has no Technician in tenant_b
        from django.forms.widgets import HiddenInput
        self.assertIsInstance(
            form.fields['cost_override'].widget, HiddenInput,
            "Shop A manager should NOT see cost_override field in Shop B form",
        )
        self.assertIsInstance(
            form.fields['override_reason'].widget, HiddenInput,
            "Shop A manager should NOT see override_reason field in Shop B form",
        )

    # ------------------------------------------------------------------ #
    # B: Regular tech in correct tenant — override fields hidden           #
    # ------------------------------------------------------------------ #
    def test_regular_tech_override_fields_hidden(self):
        """Non-manager in Shop B: override fields must be hidden."""
        form = RepairForm(user=self.regular_b_user, tenant=self.tenant_b)
        from django.forms.widgets import HiddenInput
        self.assertIsInstance(form.fields['cost_override'].widget, HiddenInput)
        self.assertIsInstance(form.fields['override_reason'].widget, HiddenInput)

    # ------------------------------------------------------------------ #
    # C: Correct manager sees override fields                              #
    # ------------------------------------------------------------------ #
    def test_correct_tenant_manager_override_fields_visible(self):
        """Manager in Shop B viewing Shop B form: override fields must be visible."""
        form = RepairForm(user=self.manager_b_user, tenant=self.tenant_b)
        from django.forms.widgets import HiddenInput
        self.assertNotIsInstance(
            form.fields['cost_override'].widget, HiddenInput,
            "Shop B manager SHOULD see cost_override field in Shop B form",
        )
        self.assertNotIsInstance(
            form.fields['override_reason'].widget, HiddenInput,
            "Shop B manager SHOULD see override_reason field in Shop B form",
        )

    # ------------------------------------------------------------------ #
    # D: clean() rejects cross-tenant override attempt                     #
    # ------------------------------------------------------------------ #
    def _base_repair_data(self, customer, status='PENDING'):
        return {
            'damage_type': 'CHIP',
            'queue_status': status,
            'customer': customer.pk,
            'technician': '',
            'unit_number': 'UNIT-001',
            'repair_date': '2026-03-19T10:00',
            'break_number': '',
            'total_breaks_in_batch': '',
            'repair_batch_id': '',
        }

    def test_cross_tenant_manager_cannot_override_pricing_via_clean(self):
        """
        Shop A manager submits cost_override on Shop B form.
        clean() must reject it (no Technician record in tenant_b).
        """
        data = self._base_repair_data(self.customer_b)
        data['cost_override'] = '150.00'
        data['override_reason'] = 'testing cross-tenant'
        form = RepairForm(data, user=self.manager_a_user, tenant=self.tenant_b)
        form.is_valid()
        self.assertIn(
            'cost_override', form.errors,
            "clean() should reject cost_override from a cross-tenant manager",
        )

    # ------------------------------------------------------------------ #
    # E: clean() rejects after-photo bypass for cross-tenant manager       #
    # ------------------------------------------------------------------ #
    def test_cross_tenant_manager_cannot_bypass_after_photo_requirement(self):
        """
        Shop A manager completes a Shop B repair with no after photo.
        clean() must require the photo since they're not a manager in Shop B.
        """
        data = self._base_repair_data(self.customer_b, status='COMPLETED')
        form = RepairForm(data, user=self.manager_a_user, tenant=self.tenant_b)
        form.is_valid()
        self.assertIn(
            'damage_photo_after', form.errors,
            "Cross-tenant manager should NOT bypass after-photo requirement",
        )

    # ------------------------------------------------------------------ #
    # F: Correct tenant manager can override pricing in clean()            #
    # ------------------------------------------------------------------ #
    def test_correct_tenant_manager_can_override_pricing(self):
        """
        Shop B manager overrides pricing within approval_limit on a Shop B repair.
        Should NOT produce a cost_override error.
        """
        data = self._base_repair_data(self.customer_b)
        data['cost_override'] = '200.00'
        data['override_reason'] = 'Fleet discount'
        form = RepairForm(data, user=self.manager_b_user, tenant=self.tenant_b)
        form.is_valid()
        self.assertNotIn(
            'cost_override', form.errors,
            "Shop B manager within approval limit should be allowed to override pricing",
        )

    # ------------------------------------------------------------------ #
    # G: Correct tenant manager can bypass after-photo requirement         #
    # ------------------------------------------------------------------ #
    def test_correct_tenant_manager_can_skip_after_photo(self):
        """
        Shop B manager completes a Shop B repair without an after photo.
        clean() must NOT add a damage_photo_after error for a valid manager.
        """
        data = self._base_repair_data(self.customer_b, status='COMPLETED')
        form = RepairForm(data, user=self.manager_b_user, tenant=self.tenant_b)
        form.is_valid()
        self.assertNotIn(
            'damage_photo_after', form.errors,
            "Shop B manager should be able to skip after-photo requirement",
        )

    # ------------------------------------------------------------------ #
    # H: Approval limit enforced for correct tenant manager                #
    # ------------------------------------------------------------------ #
    def test_approval_limit_enforced_for_correct_tenant_manager(self):
        """
        Shop B manager tries to override with amount above their approval_limit.
        clean() must reject it.
        """
        data = self._base_repair_data(self.customer_b)
        data['cost_override'] = '999.00'  # > approval_limit of 300
        data['override_reason'] = 'Big discount'
        form = RepairForm(data, user=self.manager_b_user, tenant=self.tenant_b)
        form.is_valid()
        self.assertIn(
            'cost_override', form.errors,
            "Amount above approval_limit should be rejected",
        )
        self.assertIn('approval limit', form.errors['cost_override'][0].lower())
