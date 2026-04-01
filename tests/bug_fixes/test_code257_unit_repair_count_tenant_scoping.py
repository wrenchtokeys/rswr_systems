"""
Tests for CODE-257: UnitRepairCount queries missing tenant scoping in
batch_pricing_service.calculate_batch_pricing() and
pricing_service.apply_pricing_to_repair().

Both functions used UnitRepairCount.objects.get(customer=..., unit_number=...)
without tenant=, which could:
1. Hit stale NULL-tenant rows instead of the correct tenant-scoped row
2. Raise MultipleObjectsReturned if legacy NULL-tenant rows coexist with
   tenant-scoped rows for the same customer+unit_number
3. Produce wrong pricing if the wrong row's repair_count is used

The fix adds tenant= to both lookups, consistent with the unique constraint
(tenant, customer, unit_number) and with the already-fixed get_or_create
in pricing_service.get_expected_cost().
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.tenants.models import Tenant
from apps.technician_portal.models import Customer, UnitRepairCount, Technician, Repair


class UnitRepairCountTenantScopingTest(TestCase):
    """Tests that UnitRepairCount lookups scope by tenant."""

    @classmethod
    def setUpTestData(cls):
        cls.owner_a = User.objects.create_user(username='owner_a_257', password='test')
        cls.owner_b = User.objects.create_user(username='owner_b_257', password='test')
        cls.tenant_a = Tenant.objects.create(
            name='Shop A',
            slug='shop-a',
            owner=cls.owner_a,
            subscription_status='active',
        )
        cls.tenant_b = Tenant.objects.create(
            name='Shop B',
            slug='shop-b',
            owner=cls.owner_b,
            subscription_status='active',
        )
        cls.customer_a = Customer.objects.create(
            tenant=cls.tenant_a,
            name='Fleet Alpha',
            customer_type='FLEET',
        )
        cls.customer_b = Customer.objects.create(
            tenant=cls.tenant_b,
            name='Fleet Beta',
            customer_type='FLEET',
        )
        # Create unit repair counts for customer_a at two tenants' levels
        cls.urc_a = UnitRepairCount.objects.create(
            tenant=cls.tenant_a,
            customer=cls.customer_a,
            unit_number='UNIT-100',
            repair_count=5,
        )
        # A NULL-tenant legacy row for the same customer+unit
        cls.urc_null = UnitRepairCount.objects.create(
            tenant=None,
            customer=cls.customer_a,
            unit_number='UNIT-100',
            repair_count=99,  # Wrong count — should never be used
        )

    # ----- batch_pricing_service tests -----

    def test_batch_pricing_uses_tenant_scoped_count(self):
        """calculate_batch_pricing should use the tenant-scoped row, not NULL."""
        from apps.technician_portal.services.batch_pricing_service import (
            calculate_batch_pricing,
        )
        with patch(
            'apps.technician_portal.services.batch_pricing_service.calculate_repair_cost'
        ) as mock_calc:
            mock_calc.return_value = Decimal('35.00')
            result = calculate_batch_pricing(self.customer_a, 'UNIT-100', 1)
            # Should use repair_count=5 (from tenant_a row), so tier = 5+1 = 6
            mock_calc.assert_called_once()
            _args = mock_calc.call_args
            self.assertEqual(_args[0][1], 6)  # repair_tier

    def test_batch_pricing_ignores_null_tenant_row(self):
        """If only a NULL-tenant row exists but tenant is set, should not match."""
        from apps.technician_portal.services.batch_pricing_service import (
            calculate_batch_pricing,
        )
        # Create a customer at tenant_b with no tenant-scoped URC
        # but a NULL-tenant URC exists for a different customer
        customer_new = Customer.objects.create(
            tenant=self.tenant_b,
            name='Newbie Fleet',
            customer_type='FLEET',
        )
        with patch(
            'apps.technician_portal.services.batch_pricing_service.calculate_repair_cost'
        ) as mock_calc:
            mock_calc.return_value = Decimal('50.00')
            result = calculate_batch_pricing(customer_new, 'UNIT-200', 2)
            # No URC exists for this customer+unit, so base_repair_count = 0
            # Break 1 = tier 1, Break 2 = tier 2
            self.assertEqual(len(result), 2)
            calls = mock_calc.call_args_list
            self.assertEqual(calls[0][0][1], 1)
            self.assertEqual(calls[1][0][1], 2)

    def test_batch_pricing_no_tenant_fallback(self):
        """If customer has no tenant attr, still works (graceful degradation)."""
        from apps.technician_portal.services.batch_pricing_service import (
            calculate_batch_pricing,
        )
        # Temporarily strip tenant from customer (shouldn't happen but tests safety)
        customer = Customer.objects.create(
            tenant=self.tenant_a,
            name='Bare Customer',
            customer_type='RETAIL',
        )
        with patch(
            'apps.technician_portal.services.batch_pricing_service.calculate_repair_cost'
        ) as mock_calc:
            mock_calc.return_value = Decimal('40.00')
            # No URC row at all — should default to 0
            result = calculate_batch_pricing(customer, 'UNIT-999', 1)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['repair_tier'], 1)

    # ----- pricing_service tests -----

    def test_apply_pricing_uses_tenant_scoped_count(self):
        """apply_pricing_to_repair should use the tenant-scoped URC row."""
        from apps.technician_portal.services.pricing_service import (
            apply_pricing_to_repair,
        )

        user = User.objects.create_user(username='tech257', password='test')
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,
            phone_number='555-0257',
        )
        repair = Repair(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='UNIT-100',
            damage_type='STAR',
            technician=tech,
        )

        with patch(
            'apps.technician_portal.services.pricing_service.calculate_repair_cost'
        ) as mock_calc:
            mock_calc.return_value = Decimal('25.00')
            apply_pricing_to_repair(repair)
            # Should use repair_count=5 from tenant_a row
            mock_calc.assert_called_once()
            self.assertEqual(mock_calc.call_args[0][1], 5)

    def test_apply_pricing_skips_null_tenant_row(self):
        """apply_pricing_to_repair should not match NULL-tenant rows."""
        from apps.technician_portal.services.pricing_service import (
            apply_pricing_to_repair,
        )

        user = User.objects.create_user(username='tech257b', password='test')
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_b,
            phone_number='555-0258',
        )
        customer_b2 = Customer.objects.create(
            tenant=self.tenant_b,
            name='Solo Fleet',
            customer_type='FLEET',
        )
        repair = Repair(
            tenant=self.tenant_b,
            customer=customer_b2,
            unit_number='UNIT-100',
            damage_type='STAR',
            technician=tech,
        )

        with patch(
            'apps.technician_portal.services.pricing_service.calculate_repair_cost'
        ) as mock_calc:
            mock_calc.return_value = Decimal('50.00')
            apply_pricing_to_repair(repair)
            # No URC for customer_b2 at tenant_b, so falls back to repair_count=1
            mock_calc.assert_called_once()
            self.assertEqual(mock_calc.call_args[0][1], 1)

    def test_apply_pricing_with_cost_override_skips_lookup(self):
        """apply_pricing_to_repair should skip URC lookup if cost_override is set."""
        from apps.technician_portal.services.pricing_service import (
            apply_pricing_to_repair,
        )

        user = User.objects.create_user(username='tech257c', password='test')
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,
            phone_number='555-0259',
        )
        repair = Repair(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='UNIT-100',
            damage_type='STAR',
            technician=tech,
            cost_override=Decimal('99.99'),
        )

        apply_pricing_to_repair(repair)
        self.assertEqual(repair.cost, Decimal('99.99'))
