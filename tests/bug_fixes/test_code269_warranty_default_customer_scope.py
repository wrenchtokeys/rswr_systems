"""
CODE-269: WarrantyPolicy default enforcement not scoped to customer

Two bugs:
1. WarrantyPolicy.save() cleared global defaults when a per-customer default
   was saved (missing customer= scope in the dedup filter).
2. WarrantyService.assign_warranty() step 5 fell back to per-customer defaults
   when looking for a global fallback (missing customer__isnull=True filter).
"""

from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.technician_portal.models import WarrantyPolicy, Repair, Technician
from apps.technician_portal.warranty_service import WarrantyService
from apps.tenants.models import Tenant
from core.models import Customer
from django.utils import timezone

User = get_user_model()


class WarrantyDefaultCustomerScopeModelTests(TestCase):
    """Tests for WarrantyPolicy.save() default enforcement (CODE-269, bug #1)."""

    def setUp(self):
        self.user = User.objects.create_user('wtest', 'w@test.com', 'pass123!')
        self.tenant = Tenant.objects.create(
            name='TestShop', slug='testshop', owner=self.user
        )
        self.customer = Customer.objects.create(
            name='EOS Trucking', tenant=self.tenant
        )

    def test_global_default_not_cleared_by_per_customer_default(self):
        """Saving a per-customer is_default policy must NOT clear the global default."""
        global_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=365,
        )
        # Sanity check: global default is set
        global_policy.refresh_from_db()
        self.assertTrue(global_policy.is_default)

        # Create a per-customer default
        customer_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            name='EOS Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=180,
        )

        # Global default must still be set — the per-customer save() must NOT clear it
        global_policy.refresh_from_db()
        self.assertTrue(
            global_policy.is_default,
            "Per-customer is_default policy incorrectly cleared the global default"
        )
        customer_policy.refresh_from_db()
        self.assertTrue(customer_policy.is_default)

    def test_per_customer_default_not_cleared_by_global_default(self):
        """Saving a global is_default must NOT clear per-customer defaults."""
        customer_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            name='EOS Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=180,
        )

        # Now create a global default
        global_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=365,
        )

        # Per-customer default must still be set
        customer_policy.refresh_from_db()
        self.assertTrue(
            customer_policy.is_default,
            "Global is_default policy incorrectly cleared the per-customer default"
        )
        global_policy.refresh_from_db()
        self.assertTrue(global_policy.is_default)

    def test_two_global_defaults_resolved_to_one(self):
        """Two global (customer=None) defaults: only the last one should remain set."""
        p1 = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global 1',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=365,
        )
        p2 = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global 2',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=730,
        )
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertFalse(p1.is_default, "First global default should be cleared by second")
        self.assertTrue(p2.is_default)

    def test_two_per_customer_defaults_resolved_to_one(self):
        """Two per-customer defaults for the same customer: only the last remains."""
        c1 = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            name='EOS 1',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=180,
        )
        c2 = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            name='EOS 2',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=90,
        )
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertFalse(c1.is_default)
        self.assertTrue(c2.is_default)


class WarrantyServiceFallbackScopeTests(TestCase):
    """Tests for WarrantyService.assign_warranty() step 5 fallback (CODE-269, bug #2)."""

    def setUp(self):
        self.owner = User.objects.create_user('warrowner', 'o@test.com', 'pass123!')
        self.tenant = Tenant.objects.create(
            name='WarrShop', slug='warrshop', owner=self.owner
        )
        self.tech_user = User.objects.create_user('warrtech', 't@test.com', 'pass123!')
        self.technician = Technician.objects.create(
            user=self.tech_user,
            tenant=self.tenant,
            can_repair=True,
        )
        self.eos = Customer.objects.create(name='EOS Trucking', tenant=self.tenant)
        self.penske = Customer.objects.create(name='Penske', tenant=self.tenant)

    def _make_completed_repair(self, customer, damage_type='Chip'):
        repair = Repair.objects.create(
            tenant=self.tenant,
            customer=customer,
            technician=self.technician,
            unit_number='T-001',
            damage_type=damage_type,
            queue_status='COMPLETED',
            service_date=timezone.now(),
            cost=50,
        )
        return repair

    def test_step5_fallback_only_uses_global_default_not_per_customer(self):
        """Step 5 must use the global (customer=None) default, not a per-customer one."""
        # Only per-customer default exists — step 5 should NOT use it
        eos_default = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.eos,
            name='EOS Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=90,
        )

        penske_repair = self._make_completed_repair(self.penske, 'Chip')

        # No global default exists — should raise ValueError (no policy for Penske)
        with self.assertRaises(ValueError):
            WarrantyService.assign_warranty(penske_repair)

    def test_step5_fallback_uses_global_default_correctly(self):
        """Step 5 uses global default when no customer-specific policy applies."""
        global_default = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=365,
        )
        eos_default = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.eos,
            name='EOS Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=90,
        )

        penske_repair = self._make_completed_repair(self.penske, 'Chip')

        # Penske repair should get the GLOBAL default, not EOS's policy
        updated = WarrantyService.assign_warranty(penske_repair)
        penske_repair.refresh_from_db()
        self.assertEqual(
            penske_repair.warranty_policy, global_default,
            "Penske repair should use global default, not EOS per-customer default"
        )
        self.assertNotEqual(penske_repair.warranty_policy, eos_default)

    def test_per_customer_policy_assigned_correctly_via_steps_1_2(self):
        """Per-customer policies are still assigned via steps 1-2 (not step 5)."""
        eos_specific = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.eos,
            name='EOS All Repairs',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=90,
        )
        global_default = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=365,
        )

        eos_repair = self._make_completed_repair(self.eos, 'Chip')

        updated = WarrantyService.assign_warranty(eos_repair)
        eos_repair.refresh_from_db()
        # EOS repair should get EOS-specific policy, NOT global default
        self.assertEqual(
            eos_repair.warranty_policy, eos_specific,
            "EOS repair should use EOS per-customer policy"
        )
        self.assertNotEqual(eos_repair.warranty_policy, global_default)

    def test_per_customer_default_not_cleared_after_fix(self):
        """After CODE-269 fix, both global and per-customer defaults coexist."""
        global_def = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Global Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=365,
        )
        eos_def = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            customer=self.eos,
            name='EOS Default',
            applies_to='all_repairs',
            is_default=True,
            duration_type='custom_days',
            duration_days=90,
        )
        global_def.refresh_from_db()
        eos_def.refresh_from_db()
        self.assertTrue(global_def.is_default, "Global default should still be set")
        self.assertTrue(eos_def.is_default, "EOS default should still be set")
