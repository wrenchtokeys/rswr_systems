"""
Regression tests for CODE-160: get_available_technician() was not filtering
for is_active=True and can_repair=True.

Bug: Deactivated technicians or managers with can_repair=False could be
assigned to customer-requested repairs submitted via the customer portal.

Fix: Added .filter(is_active=True, can_repair=True) to the queryset in
get_available_technician() in apps/customer_portal/views.py.
"""

from django.test import TestCase
from django.contrib.auth.models import User

from core.models import Customer
from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant
from apps.customer_portal.views import get_available_technician


class GetAvailableTechnicianFilterTest(TestCase):
    """Unit tests for the get_available_technician() helper."""

    def setUp(self):
        # Tenant requires an owner FK
        self.owner_user = User.objects.create_user(
            username='shop_owner_160', password='pass'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-code160',
            plan='trial',
            owner=self.owner_user,
        )

        # Active repair-capable tech
        self.active_user = User.objects.create_user(
            username='active_tech_160', password='pass'
        )
        self.active_tech = Technician.objects.create(
            user=self.active_user,
            tenant=self.tenant,
            is_active=True,
            can_repair=True,
        )

        # Inactive tech (deactivated employee)
        self.inactive_user = User.objects.create_user(
            username='inactive_tech_160', password='pass'
        )
        self.inactive_tech = Technician.objects.create(
            user=self.inactive_user,
            tenant=self.tenant,
            is_active=False,
            can_repair=True,
        )

        # Active manager who can't do repairs (admin-only role)
        self.manager_user = User.objects.create_user(
            username='no_repair_mgr_160', password='pass'
        )
        self.no_repair_tech = Technician.objects.create(
            user=self.manager_user,
            tenant=self.tenant,
            is_active=True,
            can_repair=False,
            is_manager=True,
        )

    def test_returns_active_repair_tech_only(self):
        """Only active, can_repair=True technicians should be returned."""
        result = get_available_technician(tenant=self.tenant)
        self.assertEqual(result, self.active_tech)

    def test_excludes_inactive_tech(self):
        """Inactive technicians must never be returned."""
        # Deactivate the active tech too — should return None
        self.active_tech.is_active = False
        self.active_tech.save()

        result = get_available_technician(tenant=self.tenant)
        self.assertIsNone(result)

    def test_excludes_no_repair_manager(self):
        """Managers with can_repair=False must never be returned."""
        # Deactivate the active tech — only the no_repair manager remains active
        self.active_tech.is_active = False
        self.active_tech.save()

        result = get_available_technician(tenant=self.tenant)
        self.assertIsNone(result)

    def test_returns_none_when_no_tenant(self):
        """Returns None when tenant is None (qs.none() path)."""
        result = get_available_technician(tenant=None)
        self.assertIsNone(result)

    def test_returns_lowest_workload_among_eligible(self):
        """When multiple eligible techs exist, pick the one with fewest repairs."""
        from core.models import Customer as CoreCustomer
        from apps.technician_portal.models import Repair

        # Create a second active repair tech
        user2 = User.objects.create_user(username='tech2_160', password='pass')
        tech2 = Technician.objects.create(
            user=user2,
            tenant=self.tenant,
            is_active=True,
            can_repair=True,
        )

        customer = CoreCustomer.objects.create(
            tenant=self.tenant,
            name='Test Customer 160',
        )

        # Give active_tech one active repair, tech2 has none
        Repair.objects.create(
            tenant=self.tenant,
            technician=self.active_tech,
            customer=customer,
            unit_number='U1',
            damage_type='chip',
            queue_status='APPROVED',
        )

        result = get_available_technician(tenant=self.tenant)
        # tech2 has fewer active repairs → should be selected
        self.assertEqual(result, tech2)

    def test_cross_tenant_isolation(self):
        """Technicians from other tenants must not be returned."""
        other_owner = User.objects.create_user(
            username='other_owner_160', password='pass'
        )
        other_tenant = Tenant.objects.create(
            name='Other Shop',
            slug='other-shop-code160',
            plan='trial',
            owner=other_owner,
        )
        other_user = User.objects.create_user(
            username='other_tech_160', password='pass'
        )
        Technician.objects.create(
            user=other_user,
            tenant=other_tenant,
            is_active=True,
            can_repair=True,
        )

        # Deactivate this tenant's only eligible tech
        self.active_tech.is_active = False
        self.active_tech.save()

        # Should return None, not the other tenant's tech
        result = get_available_technician(tenant=self.tenant)
        self.assertIsNone(result)
