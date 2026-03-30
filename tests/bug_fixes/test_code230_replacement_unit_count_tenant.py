"""
Regression test for CODE-230:
Replacement.save() reset UnitRepairCount without tenant filtering.

Root cause:
    When a Replacement was completed, the code to reset the unit's repair count
    used:
        UnitRepairCount.objects.filter(
            customer=self.customer,
            unit_number=self.unit_number
        ).first()

    This omitted tenant= from the filter.  If two tenants share a Customer
    with the same unit_number (unlikely in practice, but the Customer model
    uses tenant= as a FK, not a unique-with), the wrong tenant's
    UnitRepairCount could be fetched and zeroed.

    More importantly, the omitted tenant= means the query doesn't match the
    unique constraint (tenant, customer, unit_number), so it could return a
    NULL-tenant row or simply the wrong tenant's row depending on database
    ordering.

Fix:
    Added tenant=self.tenant to the UnitRepairCount.objects.filter() call
    in Replacement.save(), bringing it into parity with Repair.save() which
    already included tenant= in its UnitRepairCount lookup.
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.technician_portal.models import (
    Customer, Technician, Replacement, UnitRepairCount,
)


class ReplacementResetUnitCountTenantScopeTest(TestCase):
    """Verify Replacement.save() resets only the correct tenant's UnitRepairCount."""

    def setUp(self):
        # Owner users (Tenant requires a non-null owner)
        self.owner_a = User.objects.create_user('owner_a', 'owner_a@test.com', 'pass')
        self.owner_b = User.objects.create_user('owner_b', 'owner_b@test.com', 'pass')

        # Two tenants
        self.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a', owner=self.owner_a)
        self.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b', owner=self.owner_b)

        # Users for technicians
        self.user_a = User.objects.create_user('tech_a', 'a@test.com', 'pass')
        self.user_b = User.objects.create_user('tech_b', 'b@test.com', 'pass')

        # Technicians
        self.tech_a = Technician.objects.create(user=self.user_a, tenant=self.tenant_a)
        self.tech_b = Technician.objects.create(user=self.user_b, tenant=self.tenant_b)

        # Same-named customer in each tenant (different DB rows)
        self.customer_a = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant_a, email='fleet@a.com'
        )
        self.customer_b = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant_b, email='fleet@b.com'
        )

        # Both tenants have a UnitRepairCount for the same unit number
        self.urc_a = UnitRepairCount.objects.create(
            tenant=self.tenant_a, customer=self.customer_a,
            unit_number='TRUCK-100', repair_count=5,
        )
        self.urc_b = UnitRepairCount.objects.create(
            tenant=self.tenant_b, customer=self.customer_b,
            unit_number='TRUCK-100', repair_count=3,
        )

    def test_replacement_resets_only_own_tenant_count(self):
        """Completing a replacement in Tenant A must not touch Tenant B's count."""
        replacement = Replacement(
            tenant=self.tenant_a,
            customer=self.customer_a,
            technician=self.tech_a,
            unit_number='TRUCK-100',
            queue_status='IN_PROGRESS',
            service_date=timezone.now(),
            glass_position='WINDSHIELD',
            cost=Decimal('500.00'),
        )
        replacement.save()

        # Complete the replacement — should reset Tenant A's count
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        self.urc_a.refresh_from_db()
        self.urc_b.refresh_from_db()

        # Tenant A's count should be reset to 0
        self.assertEqual(self.urc_a.repair_count, 0,
                         "Tenant A's repair count should be reset to 0 after replacement")
        # Tenant B's count must be untouched
        self.assertEqual(self.urc_b.repair_count, 3,
                         "Tenant B's repair count should NOT be affected by Tenant A's replacement")

    def test_replacement_reset_with_no_existing_count(self):
        """Completing a replacement when no UnitRepairCount exists should not crash."""
        # Delete Tenant A's count
        self.urc_a.delete()

        replacement = Replacement(
            tenant=self.tenant_a,
            customer=self.customer_a,
            technician=self.tech_a,
            unit_number='TRUCK-100',
            queue_status='IN_PROGRESS',
            service_date=timezone.now(),
            glass_position='WINDSHIELD',
            cost=Decimal('500.00'),
        )
        replacement.save()

        # Complete — should not crash even with no UnitRepairCount
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        # Tenant B's count should still be untouched
        self.urc_b.refresh_from_db()
        self.assertEqual(self.urc_b.repair_count, 3)
