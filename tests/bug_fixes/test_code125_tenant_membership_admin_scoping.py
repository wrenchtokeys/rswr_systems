"""
Regression tests for CODE-125: TenantMembershipAdmin was missing TenantFilterMixin.

Before the fix, a non-superuser staff member at Shop A could see (and modify)
TenantMembership records for Shop B — a tenant data leak via the Django admin.

After the fix, TenantMembershipAdmin inherits TenantFilterMixin so get_queryset()
restricts non-superusers to their own tenant(s).
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.admin import TenantMembershipAdmin
from rs_systems.admin_mixins import TenantFilterMixin


def _make_user(username, email, is_staff=False, is_superuser=False):
    u = User.objects.create_user(
        username=username, email=email, password='pass',
        is_staff=is_staff, is_superuser=is_superuser,
    )
    return u


def _make_tenant(name, slug, owner=None):
    if owner is None:
        owner = _make_user(f'owner_{slug}', f'owner_{slug}@example.com')
    return Tenant.objects.create(name=name, slug=slug, is_active=True, owner=owner)


class TenantMembershipAdminMixinTest(TestCase):
    """TenantMembershipAdmin inherits TenantFilterMixin (structural check)."""

    def test_inherits_tenant_filter_mixin(self):
        self.assertTrue(
            issubclass(TenantMembershipAdmin, TenantFilterMixin),
            "TenantMembershipAdmin must inherit TenantFilterMixin to prevent "
            "cross-tenant membership leaks (CODE-125)."
        )

    def test_tenant_field_is_direct_fk(self):
        """TenantMembership.tenant is a direct FK — mixin should work with default tenant_field='tenant'."""
        admin_obj = TenantMembershipAdmin(TenantMembership, AdminSite())
        self.assertEqual(admin_obj.tenant_field, 'tenant')


class TenantMembershipAdminQuerysetScopingTest(TestCase):
    """Non-superuser staff see only their shop's memberships."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin_obj = TenantMembershipAdmin(TenantMembership, self.site)

        self.shop_a = _make_tenant('Shop A', 'shop-a')
        self.shop_b = _make_tenant('Shop B', 'shop-b')

        # Staff user that belongs only to Shop A
        self.staff_a = _make_user('staff_a', 'staff_a@example.com', is_staff=True)
        TenantMembership.objects.create(tenant=self.shop_a, user=self.staff_a, role='owner')

        # Superuser — should see both
        self.superuser = _make_user('su', 'su@example.com', is_staff=True, is_superuser=True)

        # Two regular technicians — one at each shop
        self.tech_a = _make_user('tech_a', 'tech_a@example.com')
        self.tech_b = _make_user('tech_b', 'tech_b@example.com')
        TenantMembership.objects.create(tenant=self.shop_a, user=self.tech_a, role='technician')
        TenantMembership.objects.create(tenant=self.shop_b, user=self.tech_b, role='technician')

    def _make_request(self, user):
        req = self.factory.get('/admin/tenants/tenantmembership/')
        req.user = user
        return req

    def test_superuser_sees_all_memberships(self):
        req = self._make_request(self.superuser)
        qs = self.admin_obj.get_queryset(req)
        # 3 created in setUp (staff_a owns Shop A, tech_a at Shop A, tech_b at Shop B)
        self.assertEqual(qs.count(), 3)

    def test_non_superuser_sees_only_own_tenant(self):
        req = self._make_request(self.staff_a)
        qs = self.admin_obj.get_queryset(req)
        # staff_a is at Shop A only — should see Shop A's 2 memberships (staff_a + tech_a)
        self.assertEqual(qs.count(), 2)
        tenant_ids = set(qs.values_list('tenant_id', flat=True))
        self.assertEqual(tenant_ids, {self.shop_a.id})

    def test_non_superuser_cannot_see_other_shop_membership(self):
        req = self._make_request(self.staff_a)
        qs = self.admin_obj.get_queryset(req)
        # tech_b's membership (Shop B) must NOT appear
        self.assertFalse(qs.filter(user=self.tech_b).exists())

    def test_staff_at_two_shops_sees_both(self):
        """Staff with memberships at two shops sees both shops' memberships."""
        # Give staff_a membership at Shop B too
        TenantMembership.objects.create(tenant=self.shop_b, user=self.staff_a, role='manager')

        req = self._make_request(self.staff_a)
        qs = self.admin_obj.get_queryset(req)
        # Now staff_a, tech_a (Shop A) and tech_b, staff_a@B (Shop B) = 4
        self.assertEqual(qs.count(), 4)


class TenantMembershipAdminListFilterTest(TestCase):
    """Superusers see 'tenant' in list_filter; non-superusers don't."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin_obj = TenantMembershipAdmin(TenantMembership, self.site)

        self.shop = _make_tenant('Shop X', 'shop-x')
        self.staff = _make_user('staff_x', 'staff_x@example.com', is_staff=True)
        TenantMembership.objects.create(tenant=self.shop, user=self.staff, role='owner')
        self.superuser = _make_user('su2', 'su2@example.com', is_staff=True, is_superuser=True)

    def _make_request(self, user):
        req = self.factory.get('/admin/tenants/tenantmembership/')
        req.user = user
        return req

    def test_superuser_has_tenant_filter(self):
        req = self._make_request(self.superuser)
        filters = self.admin_obj.get_list_filter(req)
        self.assertIn('tenant', filters)

    def test_non_superuser_no_tenant_filter(self):
        req = self._make_request(self.staff)
        filters = self.admin_obj.get_list_filter(req)
        self.assertNotIn('tenant', filters)
