"""
CODE-255: Bulk reassign technician action — cross-tenant IDOR

Both RepairAdmin and ReplacementAdmin had a bulk_reassign_technician action
where the POST handler used an unscoped Technician.objects.get(id=technician_id).
The dropdown was correctly filtered to same-tenant technicians, but a staff user
could craft a POST with any technician_id (from another tenant) to reassign
repairs/replacements to a cross-tenant technician.

Fix: Scope the Technician lookup to the tenant of the selected items.
"""
from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User

from apps.technician_portal.admin import RepairAdmin, ReplacementAdmin
from apps.technician_portal.models import Technician, Repair, Replacement, Customer


class BulkReassignTenantScopingTest(TestCase):
    """Verify bulk_reassign_technician rejects cross-tenant technicians."""

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant, TenantMembership

        # Staff user for tenant A (created first — used as tenant owner)
        cls.staff_user_a = User.objects.create_user(
            'staff_a', 'staff_a@test.com', 'pass',
            is_staff=True,
        )
        owner_b = User.objects.create_user('owner_b', 'owner_b@test.com', 'pass')

        # Create two tenants
        cls.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a', owner=cls.staff_user_a)
        cls.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b', owner=owner_b)
        TenantMembership.objects.create(
            user=cls.staff_user_a, tenant=cls.tenant_a,
            role='owner', is_active=True,
        )

        # Technicians — one per tenant
        cls.tech_user_a = User.objects.create_user('tech_a', 'tech_a@test.com', 'pass')
        cls.tech_a = Technician.objects.create(
            user=cls.tech_user_a, tenant=cls.tenant_a, is_active=True,
        )
        cls.tech_user_b = User.objects.create_user('tech_b', 'tech_b@test.com', 'pass')
        cls.tech_b = Technician.objects.create(
            user=cls.tech_user_b, tenant=cls.tenant_b, is_active=True,
        )

        # A customer and repair in tenant A
        cls.customer_a = Customer.objects.create(
            name='Customer A', tenant=cls.tenant_a,
        )
        cls.repair_a = Repair.objects.create(
            customer=cls.customer_a,
            technician=cls.tech_a,
            tenant=cls.tenant_a,
            unit_number='UNIT-001',
            damage_type='CHIP',
            queue_status='PENDING',
        )

        # A replacement in tenant A
        cls.replacement_a = Replacement.objects.create(
            customer=cls.customer_a,
            technician=cls.tech_a,
            tenant=cls.tenant_a,
            unit_number='UNIT-002',
            queue_status='PENDING',
        )

    def _make_post_request(self, user, technician_id):
        """Build a POST request simulating the bulk reassign form submission."""
        factory = RequestFactory()
        request = factory.post('/admin/', {
            'apply': '1',
            'technician_id': str(technician_id),
            'action': 'bulk_reassign_technician',
        })
        request.user = user
        # Django admin message framework requires these
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    def test_repair_reassign_rejects_cross_tenant_technician(self):
        """RepairAdmin should reject a technician_id from another tenant."""
        admin_instance = RepairAdmin(Repair, AdminSite())
        queryset = Repair.objects.filter(id=self.repair_a.id)

        request = self._make_post_request(self.staff_user_a, self.tech_b.id)
        admin_instance.bulk_reassign_technician(request, queryset)

        # Repair should still be assigned to the original technician
        self.repair_a.refresh_from_db()
        self.assertEqual(self.repair_a.technician_id, self.tech_a.id,
                         "Repair was reassigned to a cross-tenant technician!")

    def test_repair_reassign_allows_same_tenant_technician(self):
        """RepairAdmin should allow reassignment within the same tenant."""
        # Create a second tech in tenant A
        tech_user_a2 = User.objects.create_user('tech_a2', 'tech_a2@test.com', 'pass')
        tech_a2 = Technician.objects.create(
            user=tech_user_a2, tenant=self.tenant_a, is_active=True,
        )

        admin_instance = RepairAdmin(Repair, AdminSite())
        queryset = Repair.objects.filter(id=self.repair_a.id)

        request = self._make_post_request(self.staff_user_a, tech_a2.id)
        admin_instance.bulk_reassign_technician(request, queryset)

        self.repair_a.refresh_from_db()
        self.assertEqual(self.repair_a.technician_id, tech_a2.id)

    def test_replacement_reassign_rejects_cross_tenant_technician(self):
        """ReplacementAdmin should reject a technician_id from another tenant."""
        admin_instance = ReplacementAdmin(Replacement, AdminSite())
        queryset = Replacement.objects.filter(id=self.replacement_a.id)

        request = self._make_post_request(self.staff_user_a, self.tech_b.id)
        admin_instance.bulk_reassign_technician(request, queryset)

        self.replacement_a.refresh_from_db()
        self.assertEqual(self.replacement_a.technician_id, self.tech_a.id,
                         "Replacement was reassigned to a cross-tenant technician!")

    def test_replacement_reassign_allows_same_tenant_technician(self):
        """ReplacementAdmin should allow reassignment within the same tenant."""
        tech_user_a3 = User.objects.create_user('tech_a3', 'tech_a3@test.com', 'pass')
        tech_a3 = Technician.objects.create(
            user=tech_user_a3, tenant=self.tenant_a, is_active=True,
        )

        admin_instance = ReplacementAdmin(Replacement, AdminSite())
        queryset = Replacement.objects.filter(id=self.replacement_a.id)

        request = self._make_post_request(self.staff_user_a, tech_a3.id)
        admin_instance.bulk_reassign_technician(request, queryset)

        self.replacement_a.refresh_from_db()
        self.assertEqual(self.replacement_a.technician_id, tech_a3.id)

    def test_repair_reassign_nonexistent_technician_shows_error(self):
        """Posting a non-existent technician_id should show error, not crash."""
        admin_instance = RepairAdmin(Repair, AdminSite())
        queryset = Repair.objects.filter(id=self.repair_a.id)

        request = self._make_post_request(self.staff_user_a, 99999)
        result = admin_instance.bulk_reassign_technician(request, queryset)

        # Should return None (no redirect/render) and repair stays unchanged
        self.assertIsNone(result)
        self.repair_a.refresh_from_db()
        self.assertEqual(self.repair_a.technician_id, self.tech_a.id)
