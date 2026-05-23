"""
CODE-256: get_team_repairs() and update_performance_stats() must be tenant-scoped.

Previously, Technician.get_team_repairs() returned ALL repairs for managed
technicians without filtering by tenant — a cross-tenant data leak waiting
to happen.  Similarly, update_performance_stats() counted repairs from all
tenants, inflating the technician's stats.

Fix: Both methods now filter by self.tenant_id.

Regression tests to ensure the fix holds.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


class GetTeamRepairsTenantScopingTest(TestCase):
    """get_team_repairs() must only return repairs from the manager's tenant."""

    def setUp(self):
        # Owners
        self.owner_a = User.objects.create_user('owner_a', 'owner_a@test.com', 'pass')
        self.owner_b = User.objects.create_user('owner_b', 'owner_b@test.com', 'pass')

        # Shop A
        self.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a', owner=self.owner_a)
        self.user_mgr_a = User.objects.create_user('mgr_a', 'mgr_a@test.com', 'pass')
        self.manager_a = Technician.objects.create(
            user=self.user_mgr_a, tenant=self.tenant_a, is_manager=True,
            can_assign_work=True, is_active=True,
        )
        self.user_tech_a = User.objects.create_user('tech_a', 'tech_a@test.com', 'pass')
        self.tech_a = Technician.objects.create(
            user=self.user_tech_a, tenant=self.tenant_a, is_active=True,
        )
        self.manager_a.managed_technicians.add(self.tech_a)
        self.customer_a = Customer.objects.create(name='Cust A', tenant=self.tenant_a)

        # Shop B
        self.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b', owner=self.owner_b)
        self.user_tech_b = User.objects.create_user('tech_b', 'tech_b@test.com', 'pass')
        self.tech_b = Technician.objects.create(
            user=self.user_tech_b, tenant=self.tenant_b, is_active=True,
        )
        self.customer_b = Customer.objects.create(name='Cust B', tenant=self.tenant_b)

        # Repairs
        self.repair_a = Repair.objects.create(
            tenant=self.tenant_a, customer=self.customer_a,
            technician=self.tech_a, unit_number='UNIT-A',
            queue_status='COMPLETED',
        )
        self.repair_b = Repair.objects.create(
            tenant=self.tenant_b, customer=self.customer_b,
            technician=self.tech_b, unit_number='UNIT-B',
            queue_status='COMPLETED',
        )

    def test_get_team_repairs_returns_only_own_tenant(self):
        """get_team_repairs() must only include repairs from the manager's tenant."""
        team_repairs = self.manager_a.get_team_repairs()
        self.assertIn(self.repair_a, team_repairs)
        self.assertNotIn(self.repair_b, team_repairs)

    def test_get_team_repairs_excludes_cross_tenant_managed_tech(self):
        """Even if a cross-tenant tech is in managed_technicians, their repairs
        from the other tenant must NOT appear."""
        # Simulate admin bypass: add tech_b to manager_a's managed_technicians
        self.manager_a.managed_technicians.add(self.tech_b)

        team_repairs = self.manager_a.get_team_repairs()
        self.assertIn(self.repair_a, team_repairs)
        # repair_b belongs to tenant_b — must be excluded
        self.assertNotIn(self.repair_b, team_repairs)

    def test_get_team_repairs_non_manager_returns_none(self):
        """A non-manager technician gets an empty queryset."""
        result = self.tech_a.get_team_repairs()
        self.assertEqual(result.count(), 0)


class UpdatePerformanceStatsTenantScopingTest(TestCase):
    """update_performance_stats() must only count same-tenant repairs."""

    def setUp(self):
        self.owner_a = User.objects.create_user('owner_a2', 'owner_a2@test.com', 'pass')
        self.owner_b = User.objects.create_user('owner_b2', 'owner_b2@test.com', 'pass')
        self.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a-stats', owner=self.owner_a)
        self.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b-stats', owner=self.owner_b)
        self.user = User.objects.create_user('shared_tech', 'shared@test.com', 'pass')
        # Technician record in Shop A
        self.tech = Technician.objects.create(
            user=self.user, tenant=self.tenant_a, is_active=True,
        )
        self.customer_a = Customer.objects.create(name='Cust A', tenant=self.tenant_a)
        self.customer_b = Customer.objects.create(name='Cust B', tenant=self.tenant_b)

        # 3 completed repairs in Shop A
        for i in range(3):
            Repair.objects.create(
                tenant=self.tenant_a, customer=self.customer_a,
                technician=self.tech, unit_number=f'A-{i}',
                queue_status='COMPLETED',
            )

        # 2 repairs somehow linked to this tech but in Shop B
        # (shouldn't happen normally but defence-in-depth)
        for i in range(2):
            Repair.objects.create(
                tenant=self.tenant_b, customer=self.customer_b,
                technician=self.tech, unit_number=f'B-{i}',
                queue_status='COMPLETED',
            )

    def test_update_performance_stats_counts_only_own_tenant(self):
        """repairs_completed should reflect only tenant_a repairs (3), not all (5)."""
        self.tech.update_performance_stats()
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.repairs_completed, 3)
