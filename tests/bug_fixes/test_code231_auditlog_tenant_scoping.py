"""
Regression tests for CODE-231: AuditLogAdmin missing tenant scoping.

Before the fix, non-superuser staff could see ALL Django LogEntry records
in the admin audit log, including entries from other tenants.  This leaked
cross-tenant data through object_repr strings (customer names, invoice
numbers, repair details).

After the fix, AuditLogAdmin.get_queryset() restricts non-superuser staff
to log entries made by users who share at least one active TenantMembership
with the requesting user.
"""

from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, RequestFactory

from apps.tenants.models import Tenant, TenantMembership
from rs_systems.admin import AuditLogAdmin


class AuditLogTenantScopingTests(TestCase):
    """Verify LogEntry records are scoped to the requesting user's tenant(s)."""

    @classmethod
    def setUpTestData(cls):
        # Superuser
        cls.superuser = User.objects.create_superuser(
            'super', 'super@test.com', 'pass',
        )

        # Staff user at Shop A
        cls.staff_a = User.objects.create_user(
            'staff_a', 'staff_a@test.com', 'pass', is_staff=True,
        )

        # Staff user at Shop B
        cls.staff_b = User.objects.create_user(
            'staff_b', 'staff_b@test.com', 'pass', is_staff=True,
        )

        # Two tenants (owner FK is required)
        cls.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a', owner=cls.staff_a)
        cls.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b', owner=cls.staff_b)

        TenantMembership.objects.create(
            user=cls.staff_a, tenant=cls.tenant_a, role='owner', is_active=True,
        )
        TenantMembership.objects.create(
            user=cls.staff_b, tenant=cls.tenant_b, role='owner', is_active=True,
        )

        # Create log entries from each user
        ct = ContentType.objects.get_for_model(Tenant)
        cls.log_a = LogEntry.objects.create(
            user=cls.staff_a,
            content_type=ct,
            object_id=str(cls.tenant_a.pk),
            object_repr='Shop A — sensitive customer data',
            action_flag=CHANGE,
            change_message='Changed name.',
        )
        cls.log_b = LogEntry.objects.create(
            user=cls.staff_b,
            content_type=ct,
            object_id=str(cls.tenant_b.pk),
            object_repr='Shop B — sensitive customer data',
            action_flag=CHANGE,
            change_message='Changed name.',
        )
        cls.log_super = LogEntry.objects.create(
            user=cls.superuser,
            content_type=ct,
            object_id=str(cls.tenant_a.pk),
            object_repr='Super edited Shop A',
            action_flag=CHANGE,
            change_message='Changed by super.',
        )

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = AuditLogAdmin(LogEntry, self.site)

    def _make_request(self, user):
        request = self.factory.get('/admin/admin/logentry/')
        request.user = user
        return request

    def test_superuser_sees_all_log_entries(self):
        """Superuser should see log entries from all tenants."""
        request = self._make_request(self.superuser)
        qs = self.admin.get_queryset(request)
        self.assertIn(self.log_a, qs)
        self.assertIn(self.log_b, qs)
        self.assertIn(self.log_super, qs)

    def test_staff_a_sees_only_own_tenant_logs(self):
        """Shop A staff should see logs from Shop A users only, not Shop B."""
        request = self._make_request(self.staff_a)
        qs = self.admin.get_queryset(request)
        self.assertIn(self.log_a, qs)
        self.assertNotIn(self.log_b, qs,
            "Shop A staff must NOT see Shop B's audit log entries — "
            "this is the cross-tenant data leak that CODE-231 fixes."
        )

    def test_staff_b_sees_only_own_tenant_logs(self):
        """Shop B staff should see logs from Shop B users only, not Shop A."""
        request = self._make_request(self.staff_b)
        qs = self.admin.get_queryset(request)
        self.assertIn(self.log_b, qs)
        self.assertNotIn(self.log_a, qs)

    def test_superuser_log_visible_to_co_tenant_staff(self):
        """
        Superuser is NOT a member of any tenant via TenantMembership,
        so their log entries should NOT be visible to non-superuser staff.
        This prevents accidental leakage of platform-wide admin actions.
        """
        request = self._make_request(self.staff_a)
        qs = self.admin.get_queryset(request)
        self.assertNotIn(self.log_super, qs)

    def test_multi_tenant_staff_sees_both_tenants(self):
        """A user with memberships in both tenants should see logs from both."""
        multi_user = User.objects.create_user(
            'multi', 'multi@test.com', 'pass', is_staff=True,
        )
        TenantMembership.objects.create(
            user=multi_user, tenant=self.tenant_a, role='manager', is_active=True,
        )
        TenantMembership.objects.create(
            user=multi_user, tenant=self.tenant_b, role='manager', is_active=True,
        )
        request = self._make_request(multi_user)
        qs = self.admin.get_queryset(request)
        self.assertIn(self.log_a, qs)
        self.assertIn(self.log_b, qs)

    def test_inactive_membership_excluded(self):
        """
        Staff with an inactive membership in a tenant should NOT see that
        tenant's log entries.
        """
        inactive_user = User.objects.create_user(
            'inactive', 'inactive@test.com', 'pass', is_staff=True,
        )
        TenantMembership.objects.create(
            user=inactive_user, tenant=self.tenant_a, role='owner', is_active=False,
        )
        request = self._make_request(inactive_user)
        qs = self.admin.get_queryset(request)
        self.assertNotIn(self.log_a, qs)
        self.assertNotIn(self.log_b, qs)
        self.assertEqual(qs.count(), 0)
