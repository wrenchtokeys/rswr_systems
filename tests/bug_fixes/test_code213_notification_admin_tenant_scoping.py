"""
CODE-213: NotificationAdmin was missing tenant scoping.

Bug:
    NotificationAdmin in core/admin.py used a bare ModelAdmin with no
    get_queryset override.  Any non-superuser staff user could visit
    /admin/core/notification/ and see ALL notifications across ALL tenants
    — a cross-tenant data leak.

    Additionally, the changelist_view stats sidebar called
    Notification.objects.aggregate() directly, bypassing any tenant filter,
    so staff at Shop A would see platform-wide notification stats.

Impact:
    - Tenant data leak: notification titles, messages, and linked customer/
      repair IDs from other tenants visible to staff-level admin users.
    - Stats sidebar showed inflated platform-wide counts.

Fix (CODE-213):
    - Added get_queryset() override: non-superusers see only notifications
      where customer__tenant or repair__customer__tenant is in their active
      TenantMemberships.  System-level notifications (no customer, no repair)
      are hidden from non-superusers.
    - Added get_list_filter() override: superusers get 'customer__tenant'
      filter; non-superusers don't (it would reveal other tenant names).
    - Added get_tenant_display() list_display column to surface tenant
      context for superusers.
    - Added list_select_related to prevent N+1 on the new column.
    - Scoped changelist_view stats to use get_queryset() base so the
      sidebar numbers match the filtered data.

Tests:
    1. Superuser sees notifications from all tenants.
    2. Non-superuser sees only their tenant's notifications.
    3. Non-superuser does NOT see notifications from other tenants.
    4. Notifications with no customer/repair (system-level) are hidden
       from non-superusers.
    5. changelist_view stats respect tenant scoping.
    6. get_tenant_display returns the tenant name (or '—' for system).
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from core.models import Notification, Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_tenant(name):
    # Tenant requires an owner — create a dedicated owner user
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "_")}',
        email=f'owner_{name.lower().replace(" ", "_")}@test.com',
        password='pass',
    )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        owner=owner,
        is_active=True,
    )


def _make_superuser(username):
    return User.objects.create_superuser(
        username=username, email=f'{username}@test.com', password='pass'
    )


def _make_staff(username, tenant):
    u = User.objects.create_user(
        username=username, email=f'{username}@test.com', password='pass',
        is_staff=True,
    )
    TenantMembership.objects.create(user=u, tenant=tenant, role='owner', is_active=True)
    return u


def _make_customer(name, tenant):
    return Customer.objects.create(name=name, tenant=tenant)


def _make_notification(customer=None, repair=None, title='Test notification'):
    """Create a bare Notification; recipient uses ContentType on User (arbitrary)."""
    ct = ContentType.objects.get_for_model(User)
    # We need a valid user id — use id=1 (may not exist, but field is not FK)
    return Notification.objects.create(
        recipient_type=ct,
        recipient_id=1,
        title=title,
        message='Test message',
        category='system',
        priority='LOW',
        customer=customer,
        repair=repair,
    )


# ─── Test Cases ───────────────────────────────────────────────────────────────

class NotificationAdminTenantScopingTests(TestCase):
    """NotificationAdmin.get_queryset() scopes to current user's tenant."""

    def setUp(self):
        self.factory = RequestFactory()
        self.tenant_a = _make_tenant('Shop Alpha')
        self.tenant_b = _make_tenant('Shop Beta')

        self.superuser = _make_superuser('superadmin')
        self.staff_a = _make_staff('staff_a', self.tenant_a)

        self.customer_a = _make_customer('Customer A', self.tenant_a)
        self.customer_b = _make_customer('Customer B', self.tenant_b)

        # Notification for tenant A (via customer)
        self.notif_a = _make_notification(customer=self.customer_a, title='Notif A')
        # Notification for tenant B (via customer)
        self.notif_b = _make_notification(customer=self.customer_b, title='Notif B')
        # System notification (no customer, no repair)
        self.notif_sys = _make_notification(title='System notif')

        self.model_admin = admin_site._registry.get(Notification)
        self.assertIsNotNone(self.model_admin, 'Notification must be registered in admin')

    # ── 1. Superuser sees all ─────────────────────────────────────────────────

    def test_superuser_sees_all_notifications(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.superuser
        qs = self.model_admin.get_queryset(request)
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(self.notif_a.id, ids)
        self.assertIn(self.notif_b.id, ids)
        self.assertIn(self.notif_sys.id, ids)

    # ── 2. Non-superuser sees own tenant's notifications ─────────────────────

    def test_staff_a_sees_tenant_a_notifications(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.staff_a
        qs = self.model_admin.get_queryset(request)
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(self.notif_a.id, ids, 'Staff A should see tenant A notification')

    # ── 3. Non-superuser cannot see other tenant's notifications ──────────────

    def test_staff_a_cannot_see_tenant_b_notifications(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.staff_a
        qs = self.model_admin.get_queryset(request)
        ids = list(qs.values_list('id', flat=True))
        self.assertNotIn(self.notif_b.id, ids, 'Staff A must NOT see tenant B notification')

    # ── 4. System-level notifications hidden from non-superusers ─────────────

    def test_staff_a_cannot_see_system_notification(self):
        """Notifications with no customer/repair have no tenant context — hidden."""
        request = self.factory.get('/admin/core/notification/')
        request.user = self.staff_a
        qs = self.model_admin.get_queryset(request)
        ids = list(qs.values_list('id', flat=True))
        self.assertNotIn(self.notif_sys.id, ids,
                         'System-level notifications should be superuser-only')

    # ── 5. Stats in changelist_view respect tenant scoping ────────────────────

    def test_changelist_stats_scoped_to_tenant(self):
        """
        changelist_view builds stats via get_queryset() so the stats numbers
        reflect only the current user's tenant data.

        We test this indirectly: verify that the scoped queryset count for
        staff_a equals the count of notifications linked to tenant_a only.
        The changelist_view itself requires django admin permissions to render
        the full page, so we test the underlying queryset scoping instead.
        """
        request = self.factory.get('/admin/core/notification/')
        request.user = self.staff_a

        # Build what changelist_view uses for stats: get_queryset()
        qs = self.model_admin.get_queryset(request)
        # staff_a should see notif_a (tenant A) but NOT notif_b (tenant B)
        # or notif_sys (no tenant context)
        self.assertEqual(qs.count(), 1,
                         "Staff A's scoped queryset should contain exactly 1 notification (tenant A only)")
        self.assertIn(self.notif_a.id, qs.values_list('id', flat=True))
        self.assertNotIn(self.notif_b.id, qs.values_list('id', flat=True))

    # ── 6. get_tenant_display returns tenant name or '—' ─────────────────────

    def test_get_tenant_display_customer_linked(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.superuser
        # Ensure the relation is loaded
        notif = Notification.objects.select_related(
            'customer__tenant', 'repair__customer__tenant'
        ).get(pk=self.notif_a.pk)
        result = self.model_admin.get_tenant_display(notif)
        self.assertEqual(result, 'Shop Alpha')

    def test_get_tenant_display_system_notification(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.superuser
        notif = Notification.objects.get(pk=self.notif_sys.pk)
        result = self.model_admin.get_tenant_display(notif)
        self.assertEqual(result, '—')

    # ── 7. list_filter adds customer__tenant for superusers only ─────────────

    def test_superuser_gets_tenant_list_filter(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.superuser
        filters = self.model_admin.get_list_filter(request)
        self.assertIn('customer__tenant', filters,
                      'Superusers should have customer__tenant in list_filter')

    def test_staff_does_not_get_tenant_list_filter(self):
        request = self.factory.get('/admin/core/notification/')
        request.user = self.staff_a
        filters = self.model_admin.get_list_filter(request)
        self.assertNotIn('customer__tenant', filters,
                         'Non-superusers should not have tenant list_filter (reveals other names)')
