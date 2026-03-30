"""
CODE-235: FK dropdown scoping for NotificationAdmin.

Bug: NotificationAdmin had custom get_queryset() for tenant scoping but no
formfield_for_foreignkey override. Non-superuser staff could see ALL customers
and repairs from ALL tenants in the FK dropdowns when editing a notification —
a cross-tenant data leak via the admin UI.

Fix: Added formfield_for_foreignkey to NotificationAdmin that scopes `customer`
and `repair` FK dropdowns to the user's tenant(s).
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from core.admin import NotificationAdmin
from core.models import Notification
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Customer, Repair, Technician


class NotificationFKTenantScopingTests(TestCase):
    """Verify FK dropdowns in NotificationAdmin are tenant-scoped."""

    @classmethod
    def setUpTestData(cls):
        # Staff user for tenant A (non-superuser)
        cls.staff_user = User.objects.create_user(
            'staff_a', 'staff@shopa.com', 'pass',
            is_staff=True,
        )

        # Superuser
        cls.superuser = User.objects.create_superuser(
            'super', 'super@test.com', 'pass',
        )

        # Owners for tenants
        cls.owner_a = User.objects.create_user('owner_a_235', 'ownera@test.com', 'pass')
        cls.owner_b = User.objects.create_user('owner_b_235', 'ownerb@test.com', 'pass')

        # Two tenants
        cls.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a-235', subscription_status='active',
            owner=cls.owner_a,
        )
        cls.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b-235', subscription_status='active',
            owner=cls.owner_b,
        )

        # Staff user belongs to tenant A only
        TenantMembership.objects.create(
            user=cls.staff_user, tenant=cls.tenant_a, role='admin', is_active=True,
        )

        # Technicians (required for Repair)
        cls.tech_user_a = User.objects.create_user('tech_a_235', 'techa@test.com', 'pass')
        cls.tech_user_b = User.objects.create_user('tech_b_235', 'techb@test.com', 'pass')
        cls.tech_a = Technician.objects.create(
            user=cls.tech_user_a, tenant=cls.tenant_a,
        )
        cls.tech_b = Technician.objects.create(
            user=cls.tech_user_b, tenant=cls.tenant_b,
        )

        # Customers
        cls.customer_a = Customer.objects.create(
            name='Customer A', tenant=cls.tenant_a,
        )
        cls.customer_b = Customer.objects.create(
            name='Customer B', tenant=cls.tenant_b,
        )

        # Repairs
        cls.repair_a = Repair.objects.create(
            customer=cls.customer_a,
            tenant=cls.tenant_a,
            technician=cls.tech_a,
            unit_number='UNIT-A-235',
            damage_type='CHIP',
            cost=25,
        )
        cls.repair_b = Repair.objects.create(
            customer=cls.customer_b,
            tenant=cls.tenant_b,
            technician=cls.tech_b,
            unit_number='UNIT-B-235',
            damage_type='CHIP',
            cost=25,
        )

        cls.factory = RequestFactory()

    def _get_fk_queryset(self, field_name, user):
        """Helper: get the queryset from formfield_for_foreignkey for a field."""
        site = AdminSite()
        model_admin = NotificationAdmin(Notification, site)
        request = self.factory.get('/admin/core/notification/add/')
        request.user = user

        db_field = Notification._meta.get_field(field_name)
        formfield = model_admin.formfield_for_foreignkey(db_field, request)
        return formfield.queryset

    # --- customer FK ---

    def test_customer_fk_scoped_for_staff(self):
        """Non-superuser staff should only see their own tenant's customers."""
        qs = self._get_fk_queryset('customer', self.staff_user)
        self.assertIn(self.customer_a, qs)
        self.assertNotIn(self.customer_b, qs)

    def test_customer_fk_unrestricted_for_superuser(self):
        """Superusers should see all customers."""
        qs = self._get_fk_queryset('customer', self.superuser)
        self.assertIn(self.customer_a, qs)
        self.assertIn(self.customer_b, qs)

    # --- repair FK ---

    def test_repair_fk_scoped_for_staff(self):
        """Non-superuser staff should only see their own tenant's repairs."""
        qs = self._get_fk_queryset('repair', self.staff_user)
        self.assertIn(self.repair_a, qs)
        self.assertNotIn(self.repair_b, qs)

    def test_repair_fk_unrestricted_for_superuser(self):
        """Superusers should see all repairs."""
        qs = self._get_fk_queryset('repair', self.superuser)
        self.assertIn(self.repair_a, qs)
        self.assertIn(self.repair_b, qs)

    # --- template FK (no tenant — should NOT be restricted) ---

    def test_template_fk_unrestricted_for_staff(self):
        """Template FK has no tenant — should not be restricted for anyone."""
        qs = self._get_fk_queryset('template', self.staff_user)
        # Just verify it's the default manager queryset (not filtered)
        from core.models import NotificationTemplate
        self.assertEqual(
            set(qs.values_list('pk', flat=True)),
            set(NotificationTemplate.objects.values_list('pk', flat=True)),
        )
