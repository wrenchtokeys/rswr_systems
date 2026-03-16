"""
Regression tests for CODE-043: bulk_repair_action() blocked admin/owner users
without a Technician profile.

Bug:
    bulk_repair_action() in apps/technician_portal/views/repairs.py started with:

        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile.")
            return redirect('technician_dashboard')

        technician = request.user.technician
        is_admin = is_tenant_admin(request.user, tenant=...)

        if not is_admin and not technician.is_manager:
            ...block...

    This meant:
    1. Admins/owners with NO Technician record were blocked by the first guard
       before is_admin was ever checked — they got "You don't have a technician
       profile" instead of being allowed through.
    2. The actor_name in RepairApproval notes was always
       `technician.user.get_full_name()` — would crash with AttributeError if an
       admin somehow bypassed the guard and technician was None.

Fix:
    - Use `getattr(request.user, 'technician', None)` instead of hasattr guard.
    - Check is_admin FIRST; only enforce technician requirement if NOT admin.
    - Build `actor_name` from technician if present, else from request.user.
    - Auto-assign (REQUESTED → technician) skips gracefully when technician is None.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from unittest.mock import patch

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name, plan):
    """Create a tenant with its own owner user; return (tenant, owner_user)."""
    suffix = Tenant.objects.count()
    slug = f"{name.lower().replace(' ', '-')}-{suffix}"
    owner = User.objects.create_user(username=f'owner_{slug}', password='pw')
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan='trial',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant, owner


def _make_technician(username, tenant, is_manager=False):
    user = User.objects.create_user(username=username, password='pw')
    TenantMembership.objects.create(
        user=user, tenant=tenant,
        role='manager' if is_manager else 'technician',
        is_active=True,
    )
    tech = Technician.objects.create(user=user, tenant=tenant, is_manager=is_manager, is_active=True)
    return user, tech


def _make_repair(customer, tenant, status='REQUESTED', technician=None):
    """Create a Repair. If no technician provided, create a throw-away one for this tenant."""
    if technician is None:
        tech_user = User.objects.create_user(
            username=f'anon_tech_{Repair.objects.count()}',
            password='pw',
        )
        technician = Technician.objects.create(
            user=tech_user, tenant=tenant, is_active=True
        )
    return Repair.objects.create(
        customer=customer,
        tenant=tenant,
        unit_number='UNIT-001',
        queue_status=status,
        technician=technician,
    )


def _fake_request(user, tenant, post_data):
    factory = RequestFactory()
    request = factory.post('/bulk/', post_data)
    request.user = user
    request.tenant = tenant
    # Attach messages middleware
    setattr(request, 'session', 'session')
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class BulkRepairActionAdminNoTechProfileTests(TestCase):
    """Admin/owner users without a Technician record should be allowed through."""

    def setUp(self):
        plan = _make_plan()
        self.tenant, self.owner_user = _make_tenant('BulkShop', plan)
        self.customer = Customer.objects.create(name='BulkCo', tenant=self.tenant)

    def _call_view(self, user, post_data):
        from apps.technician_portal.views.repairs import bulk_repair_action
        request = _fake_request(user, self.tenant, post_data)
        with patch('apps.technician_portal.views.repairs.is_tenant_admin') as mock_admin:
            mock_admin.return_value = True  # owner is always admin
            response = bulk_repair_action(request)
        return response

    def test_owner_without_tech_profile_not_blocked(self):
        """Owner with no Technician record should NOT get 'You don't have a technician profile'."""
        repair = _make_repair(self.customer, self.tenant, status='REQUESTED')
        # Sanity: owner has no Technician record
        self.assertFalse(hasattr(self.owner_user, 'technician'))

        response = self._call_view(
            self.owner_user,
            {'action': 'approve', 'repair_ids': [repair.id]}
        )

        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')

    def test_owner_can_approve_repairs(self):
        """Owner without Technician profile can bulk-approve REQUESTED repairs."""
        r1 = _make_repair(self.customer, self.tenant, status='REQUESTED')
        r2 = _make_repair(self.customer, self.tenant, status='PENDING')

        self._call_view(
            self.owner_user,
            {'action': 'approve', 'repair_ids': [r1.id, r2.id]}
        )

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.queue_status, 'APPROVED')
        self.assertEqual(r2.queue_status, 'APPROVED')

    def test_owner_can_deny_repairs(self):
        """Owner without Technician profile can bulk-deny repairs."""
        repair = _make_repair(self.customer, self.tenant, status='PENDING')

        self._call_view(
            self.owner_user,
            {'action': 'deny', 'repair_ids': [repair.id]}
        )

        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'DENIED')

    def test_repair_not_auto_assigned_when_owner_has_no_tech_profile(self):
        """REQUESTED repair technician not changed to owner when owner has no Technician record."""
        # Create a REQUESTED repair already assigned to a known tech
        existing_tech_user = User.objects.create_user(username='known_tech_43', password='pw')
        existing_tech = Technician.objects.create(
            user=existing_tech_user, tenant=self.tenant, is_active=True
        )
        repair = _make_repair(self.customer, self.tenant, status='REQUESTED', technician=existing_tech)
        original_tech_id = repair.technician_id

        self._call_view(
            self.owner_user,
            {'action': 'approve', 'repair_ids': [repair.id]}
        )

        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')
        # Technician should not have changed — owner has no Technician record to set
        self.assertEqual(repair.technician_id, original_tech_id)


class BulkRepairActionTechnicianPermissionTests(TestCase):
    """Plain technicians (non-manager) should still be blocked."""

    def setUp(self):
        plan = _make_plan()
        self.tenant, _ = _make_tenant('BulkShopB', plan)
        self.plain_user, self.plain_tech = _make_technician('plain_tech', self.tenant, is_manager=False)
        self.customer = Customer.objects.create(name='BulkCoB', tenant=self.tenant)

    def test_plain_technician_blocked(self):
        """Non-manager technician should be blocked from bulk actions."""
        from apps.technician_portal.views.repairs import bulk_repair_action
        repair = _make_repair(self.customer, self.tenant, status='REQUESTED')
        request = _fake_request(
            self.plain_user,
            self.tenant,
            {'action': 'approve', 'repair_ids': [repair.id]}
        )

        with patch('apps.technician_portal.views.repairs.is_tenant_admin', return_value=False):
            response = bulk_repair_action(request)

        repair.refresh_from_db()
        # Should NOT have been approved — blocked before processing
        self.assertEqual(repair.queue_status, 'REQUESTED')

    def test_manager_technician_allowed(self):
        """Manager technician should be allowed through."""
        manager_user, manager_tech = _make_technician('manager_tech', self.tenant, is_manager=True)
        repair = _make_repair(self.customer, self.tenant, status='REQUESTED')

        from apps.technician_portal.views.repairs import bulk_repair_action
        request = _fake_request(
            manager_user,
            self.tenant,
            {'action': 'approve', 'repair_ids': [repair.id]}
        )

        with patch('apps.technician_portal.views.repairs.is_tenant_admin', return_value=False):
            bulk_repair_action(request)

        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')


class BulkRepairActionCrossTenantTests(TestCase):
    """Bulk action must only touch repairs from the current tenant."""

    def setUp(self):
        plan = _make_plan()
        self.tenant_a, self.owner_a = _make_tenant('ShopA_bulk', plan)
        self.tenant_b, _ = _make_tenant('ShopB_bulk', plan)
        self.customer_a = Customer.objects.create(name='CustA', tenant=self.tenant_a)
        self.customer_b = Customer.objects.create(name='CustB', tenant=self.tenant_b)

    def test_cannot_approve_other_tenants_repairs(self):
        """Bulk approve for tenant A must not change tenant B's repairs."""
        repair_a = _make_repair(self.customer_a, self.tenant_a, status='REQUESTED')
        repair_b = _make_repair(self.customer_b, self.tenant_b, status='REQUESTED')

        from apps.technician_portal.views.repairs import bulk_repair_action
        request = _fake_request(
            self.owner_a,
            self.tenant_a,
            {'action': 'approve', 'repair_ids': [repair_a.id, repair_b.id]}
        )

        with patch('apps.technician_portal.views.repairs.is_tenant_admin', return_value=True):
            bulk_repair_action(request)

        repair_a.refresh_from_db()
        repair_b.refresh_from_db()
        self.assertEqual(repair_a.queue_status, 'APPROVED')
        # Repair B belongs to a different tenant — must remain untouched
        self.assertEqual(repair_b.queue_status, 'REQUESTED')
