"""
CODE-232: Admin FK dropdown cross-tenant data leak

Bug: Non-superuser staff editing a Repair (or Replacement, Invoice, etc.)
in Django admin could see and select Customers, Technicians, and other
tenant-scoped objects from OTHER tenants via FK dropdown menus.

Root cause: TenantFilterMixin.get_queryset() correctly filtered the
changelist (which records you see), but formfield_for_foreignkey() was
never overridden — so the FK dropdown on change/add forms showed ALL
records across ALL tenants.  A Shop A admin editing a repair could assign
it to a Shop B customer or technician.

Fix: Added formfield_for_foreignkey() to TenantFilterMixin (and
CustomerTenantFilterMixin) that filters any FK whose target model has a
'tenant' field to only show records from the requesting user's tenant(s).
Superusers are unrestricted.

Author: Amelia (Clawdbot AI)
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Customer, Technician, Repair, Replacement, WarrantyPolicy
from apps.technician_portal.admin import RepairAdmin, ReplacementAdmin, CustomerAdmin, WarrantyPolicyAdmin
from apps.billing.models import Invoice, BillingConfig
from apps.billing.admin import InvoiceAdmin


class AdminFKTenantFilteringTest(TestCase):
    """Verify that FK dropdowns in admin are scoped to the user's tenant."""

    @classmethod
    def setUpTestData(cls):
        cls.site = AdminSite()
        cls.factory = RequestFactory()

        # --- Superuser ---
        cls.superuser = User.objects.create_superuser(
            'superadmin', 'super@test.com', 'pass'
        )

        # --- Tenant A ---
        cls.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a', owner=cls.superuser
        )
        cls.staff_a = User.objects.create_user(
            'staff_a', 'staff_a@test.com', 'pass', is_staff=True
        )
        TenantMembership.objects.create(
            user=cls.staff_a, tenant=cls.tenant_a, role='owner', is_active=True
        )
        cls.tech_a = Technician.objects.create(
            user=cls.staff_a, tenant=cls.tenant_a, is_active=True
        )
        cls.customer_a = Customer.objects.create(
            name='Customer A', tenant=cls.tenant_a
        )
        cls.warranty_a = WarrantyPolicy.objects.create(
            tenant=cls.tenant_a, name='Warranty A', applies_to='repairs'
        )

        # --- Tenant B ---
        cls.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b', owner=cls.superuser
        )
        cls.staff_b = User.objects.create_user(
            'staff_b', 'staff_b@test.com', 'pass', is_staff=True
        )
        TenantMembership.objects.create(
            user=cls.staff_b, tenant=cls.tenant_b, role='owner', is_active=True
        )
        cls.tech_b = Technician.objects.create(
            user=cls.staff_b, tenant=cls.tenant_b, is_active=True
        )
        cls.customer_b = Customer.objects.create(
            name='Customer B', tenant=cls.tenant_b
        )
        cls.warranty_b = WarrantyPolicy.objects.create(
            tenant=cls.tenant_b, name='Warranty B', applies_to='repairs'
        )

        # Create a repair in Tenant A
        cls.repair_a = Repair.objects.create(
            tenant=cls.tenant_a,
            technician=cls.tech_a,
            customer=cls.customer_a,
            unit_number='UNIT-001',
            damage_type='CHIP',
            queue_status='PENDING',
        )

    def _make_request(self, user):
        request = self.factory.get('/admin/')
        request.user = user
        return request

    # =========================================================================
    # RepairAdmin FK filtering
    # =========================================================================

    def test_repair_customer_fk_filtered_for_staff(self):
        """Staff user should only see their tenant's customers in the dropdown."""
        admin_obj = RepairAdmin(Repair, self.site)
        request = self._make_request(self.staff_a)

        db_field = Repair._meta.get_field('customer')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.customer_a, qs)
        self.assertNotIn(self.customer_b, qs)

    def test_repair_technician_fk_filtered_for_staff(self):
        """Staff user should only see their tenant's technicians in the dropdown."""
        admin_obj = RepairAdmin(Repair, self.site)
        request = self._make_request(self.staff_a)

        db_field = Repair._meta.get_field('technician')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.tech_a, qs)
        self.assertNotIn(self.tech_b, qs)

    def test_repair_warranty_policy_fk_filtered_for_staff(self):
        """Staff user should only see their tenant's warranty policies."""
        admin_obj = RepairAdmin(Repair, self.site)
        request = self._make_request(self.staff_a)

        db_field = Repair._meta.get_field('warranty_policy')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.warranty_a, qs)
        self.assertNotIn(self.warranty_b, qs)

    def test_repair_fks_unfiltered_for_superuser(self):
        """Superuser should see all tenants' records in FK dropdowns."""
        admin_obj = RepairAdmin(Repair, self.site)
        request = self._make_request(self.superuser)

        customer_field = Repair._meta.get_field('customer')
        formfield = admin_obj.formfield_for_foreignkey(customer_field, request)
        qs = formfield.queryset
        self.assertIn(self.customer_a, qs)
        self.assertIn(self.customer_b, qs)

    # =========================================================================
    # ReplacementAdmin FK filtering
    # =========================================================================

    def test_replacement_customer_fk_filtered(self):
        """Staff should only see their tenant's customers for Replacement."""
        admin_obj = ReplacementAdmin(Replacement, self.site)
        request = self._make_request(self.staff_a)

        db_field = Replacement._meta.get_field('customer')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.customer_a, qs)
        self.assertNotIn(self.customer_b, qs)

    def test_replacement_technician_fk_filtered(self):
        """Staff should only see their tenant's technicians for Replacement."""
        admin_obj = ReplacementAdmin(Replacement, self.site)
        request = self._make_request(self.staff_a)

        db_field = Replacement._meta.get_field('technician')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.tech_a, qs)
        self.assertNotIn(self.tech_b, qs)

    # =========================================================================
    # CustomerAdmin FK filtering (primary_technician)
    # =========================================================================

    def test_customer_primary_technician_fk_filtered(self):
        """Staff editing a Customer should only see their tenant's technicians."""
        admin_obj = CustomerAdmin(Customer, self.site)
        request = self._make_request(self.staff_a)

        db_field = Customer._meta.get_field('primary_technician')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.tech_a, qs)
        self.assertNotIn(self.tech_b, qs)

    # =========================================================================
    # InvoiceAdmin FK filtering
    # =========================================================================

    def test_invoice_customer_fk_filtered(self):
        """Staff should only see their tenant's customers when editing Invoice."""
        admin_obj = InvoiceAdmin(Invoice, self.site)
        request = self._make_request(self.staff_a)

        db_field = Invoice._meta.get_field('customer')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.customer_a, qs)
        self.assertNotIn(self.customer_b, qs)

    # =========================================================================
    # Tenant B staff cannot see Tenant A data
    # =========================================================================

    def test_tenant_b_staff_sees_only_tenant_b(self):
        """Staff B should see only Tenant B records, not Tenant A."""
        admin_obj = RepairAdmin(Repair, self.site)
        request = self._make_request(self.staff_b)

        customer_field = Repair._meta.get_field('customer')
        formfield = admin_obj.formfield_for_foreignkey(customer_field, request)

        qs = formfield.queryset
        self.assertNotIn(self.customer_a, qs)
        self.assertIn(self.customer_b, qs)

        tech_field = Repair._meta.get_field('technician')
        formfield = admin_obj.formfield_for_foreignkey(tech_field, request)

        qs = formfield.queryset
        self.assertNotIn(self.tech_a, qs)
        self.assertIn(self.tech_b, qs)

    # =========================================================================
    # Non-tenant FK fields are NOT filtered (e.g. tenant FK itself)
    # =========================================================================

    def test_non_tenant_scoped_fk_unfiltered(self):
        """FK fields pointing to models without a 'tenant' field should not be filtered."""
        admin_obj = RepairAdmin(Repair, self.site)
        request = self._make_request(self.staff_a)

        # The 'tenant' FK on Repair points to Tenant itself — Tenant does not
        # have a 'tenant' FK on itself, so it should not be filtered.
        tenant_field = Repair._meta.get_field('tenant')
        formfield = admin_obj.formfield_for_foreignkey(tenant_field, request)

        # Should include all tenants (not filtered)
        qs = formfield.queryset
        self.assertIn(self.tenant_a, qs)
        self.assertIn(self.tenant_b, qs)
