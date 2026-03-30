"""
Regression tests for CODE-234: RewardRedemptionAdmin FK dropdown cross-tenant leak.

RewardRedemptionAdmin used autocomplete_fields for reward_option,
assigned_technician, applied_to_repair, and reward.  While the autocomplete
*search* results are scoped by the target model's admin get_queryset(), the
form's ModelChoiceField validation was NOT — a non-superuser could POST an
arbitrary cross-tenant FK id and Django would silently accept it.

The fix adds formfield_for_foreignkey() to RewardRedemptionAdmin that scopes
each FK dropdown to the user's tenant(s).
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User

from apps.rewards_referrals.admin import RewardRedemptionAdmin
from apps.rewards_referrals.models import RewardRedemption, RewardOption, RewardType
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class RewardRedemptionFKScopingTest(TestCase):
    """Verify RewardRedemptionAdmin.formfield_for_foreignkey scopes FKs to tenant."""

    @classmethod
    def setUpTestData(cls):
        # Owners for each tenant
        owner_a = User.objects.create_user('owner_a', 'owner_a@test.com', 'pass')
        owner_b = User.objects.create_user('owner_b', 'owner_b@test.com', 'pass')

        # Create two tenants
        cls.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a', owner=owner_a)
        cls.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b', owner=owner_b)

        # Staff user belonging to tenant A only
        cls.staff_user = User.objects.create_user(
            'staff_a', 'staff_a@test.com', 'pass',
            is_staff=True,
        )
        TenantMembership.objects.create(
            user=cls.staff_user, tenant=cls.tenant_a,
            role='manager', is_active=True,
        )

        # Superuser
        cls.superuser = User.objects.create_superuser(
            'super', 'super@test.com', 'pass',
        )

        # Technician in each tenant
        tech_user_a = User.objects.create_user('tech_a', 'tech_a@test.com', 'pass')
        tech_user_b = User.objects.create_user('tech_b', 'tech_b@test.com', 'pass')
        cls.tech_a = Technician.objects.create(user=tech_user_a, tenant=cls.tenant_a)
        cls.tech_b = Technician.objects.create(user=tech_user_b, tenant=cls.tenant_b)

        # Customer + repair in each tenant
        cls.cust_a = Customer.objects.create(name='Cust A', tenant=cls.tenant_a)
        cls.cust_b = Customer.objects.create(name='Cust B', tenant=cls.tenant_b)
        cls.repair_a = Repair.objects.create(
            customer=cls.cust_a, tenant=cls.tenant_a,
            technician=cls.tech_a, unit_number='U-A1',
        )
        cls.repair_b = Repair.objects.create(
            customer=cls.cust_b, tenant=cls.tenant_b,
            technician=cls.tech_b, unit_number='U-B1',
        )

        # RewardType (global) and RewardOption per tenant
        cls.rtype = RewardType.objects.create(
            name='Discount', category='DISCOUNT',
            discount_type='PERCENTAGE', discount_value=10,
        )
        cls.opt_a = RewardOption.objects.create(
            tenant=cls.tenant_a, name='Option A',
            points_required=100, reward_type=cls.rtype,
        )
        cls.opt_b = RewardOption.objects.create(
            tenant=cls.tenant_b, name='Option B',
            points_required=200, reward_type=cls.rtype,
        )

        cls.site = AdminSite()
        cls.factory = RequestFactory()

    def _make_request(self, user):
        request = self.factory.get('/admin/')
        request.user = user
        return request

    def _get_admin(self):
        return RewardRedemptionAdmin(RewardRedemption, self.site)

    # ------------------------------------------------------------------ tests

    def test_reward_option_scoped_for_staff(self):
        """Staff at Shop A should only see Shop A's RewardOptions."""
        admin = self._get_admin()
        request = self._make_request(self.staff_user)

        # Get the db_field for 'reward_option'
        db_field = RewardRedemption._meta.get_field('reward_option')
        formfield = admin.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.opt_a, qs)
        self.assertNotIn(self.opt_b, qs,
                         "Shop A staff should NOT see Shop B's RewardOption")

    def test_assigned_technician_scoped_for_staff(self):
        """Staff at Shop A should only see Shop A's Technicians."""
        admin = self._get_admin()
        request = self._make_request(self.staff_user)

        db_field = RewardRedemption._meta.get_field('assigned_technician')
        formfield = admin.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.tech_a, qs)
        self.assertNotIn(self.tech_b, qs,
                         "Shop A staff should NOT see Shop B's Technician")

    def test_applied_to_repair_scoped_for_staff(self):
        """Staff at Shop A should only see Shop A's Repairs."""
        admin = self._get_admin()
        request = self._make_request(self.staff_user)

        db_field = RewardRedemption._meta.get_field('applied_to_repair')
        formfield = admin.formfield_for_foreignkey(db_field, request)

        qs = formfield.queryset
        self.assertIn(self.repair_a, qs)
        self.assertNotIn(self.repair_b, qs,
                         "Shop A staff should NOT see Shop B's Repair")

    def test_superuser_sees_all(self):
        """Superusers should see all records across tenants."""
        admin = self._get_admin()
        request = self._make_request(self.superuser)

        for field_name in ('reward_option', 'assigned_technician', 'applied_to_repair'):
            db_field = RewardRedemption._meta.get_field(field_name)
            formfield = admin.formfield_for_foreignkey(db_field, request)
            # Superuser queryset should be unrestricted — check it includes both tenants
            qs = formfield.queryset
            if field_name == 'reward_option':
                self.assertIn(self.opt_a, qs)
                self.assertIn(self.opt_b, qs)
            elif field_name == 'assigned_technician':
                self.assertIn(self.tech_a, qs)
                self.assertIn(self.tech_b, qs)
            elif field_name == 'applied_to_repair':
                self.assertIn(self.repair_a, qs)
                self.assertIn(self.repair_b, qs)

    def test_processed_by_unrestricted(self):
        """processed_by (User FK) should NOT be tenant-scoped — it's set programmatically."""
        admin = self._get_admin()
        request = self._make_request(self.staff_user)

        db_field = RewardRedemption._meta.get_field('processed_by')
        formfield = admin.formfield_for_foreignkey(db_field, request)

        # User model has no tenant FK — the queryset should include all users
        # (or at least not error out trying to filter by tenant)
        qs = formfield.queryset
        self.assertIn(self.staff_user, qs)
        self.assertIn(self.superuser, qs)
