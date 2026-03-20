"""
Regression test for CODE-081: bulk_repair_action() used bare
`request.user.technician` (global OneToOneField) instead of a
tenant-scoped Technician lookup.

Bug:
    bulk_repair_action() started with:

        technician = getattr(request.user, 'technician', None)

    `request.user.technician` resolves the OneToOneField globally — it returns
    the Technician record from whichever tenant the OneToOne FK points to,
    regardless of the current request tenant.

    Attack scenario:
    - User is is_manager=True at Shop A (their Technician.tenant = Shop A).
    - Same user visits Shop B's technician portal.
    - bulk_repair_action() sees technician.is_manager=True (Shop A's record)
      and grants bulk-approve access on Shop B's repairs.
    - Worse: the approved repair is assigned `repair.technician = technician`
      — cross-tenant Technician leaks into Shop B's data.

Fix (CODE-081):
    Use Technician.objects.filter(user=request.user, tenant=tenant).first()
    so that only the Technician record belonging to the current shop is used.
    A user who is_manager at Shop A gets technician=None on Shop B — blocked
    unless they have a separate is_manager Technician record at Shop B.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

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


def _make_tenant(name, plan, suffix=None):
    idx = suffix if suffix is not None else Tenant.objects.count()
    slug = f"{name.lower().replace(' ', '-')}-{idx}"
    owner = User.objects.create_user(username=f'owner_{slug}', password='pw')
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan='trial',
        subscription_plan=plan,
        is_active=True,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return tenant, owner


def _make_technician(user, tenant, is_manager=False, is_active=True):
    TenantMembership.objects.get_or_create(
        user=user, tenant=tenant,
        defaults={
            'role': 'manager' if is_manager else 'technician',
            'is_active': True,
        }
    )
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        phone_number='555-0000',
        is_manager=is_manager,
        is_active=is_active,
        can_assign_work=is_manager,
    )


def _make_customer(tenant):
    return Customer.objects.create(
        tenant=tenant,
        name=f'Customer-{tenant.slug}',
        email=f'customer@{tenant.slug}.com',
    )


def _make_repair(tenant, customer, technician=None, status='PENDING'):
    # Repairs require a technician for most statuses; create a throwaway one if needed
    if technician is None:
        anon_user = User.objects.create_user(
            username=f'anon_tech_{Repair.objects.count()}',
            password='pw',
        )
        technician = Technician.objects.create(
            user=anon_user, tenant=tenant, is_active=True
        )
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        damage_type='CHIP',
        queue_status=status,
    )


def _build_post_request(factory, user, tenant, data):
    request = factory.post('/fake/', data)
    request.user = user
    request.tenant = tenant
    setattr(request, 'session', 'session')
    messages_storage = FallbackStorage(request)
    request._messages = messages_storage
    return request


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class BulkActionCrossTenantManagerTest(TestCase):
    """
    A manager at Shop A must NOT be able to bulk-approve Shop B's repairs.
    """

    def setUp(self):
        self.factory = RequestFactory()
        plan = _make_plan()

        self.shop_a, self.owner_a = _make_tenant('Shop A', plan, suffix=200)
        self.shop_b, self.owner_b = _make_tenant('Shop B', plan, suffix=201)

        # Cross-tenant user: is_manager at Shop A, NO Technician record at Shop B
        self.cross_user = User.objects.create_user(username='cross_manager_081', password='pw')
        self.tech_shop_a = _make_technician(self.cross_user, self.shop_a, is_manager=True)
        # Intentionally NOT creating a Technician for cross_user at shop_b

        self.customer_b = _make_customer(self.shop_b)
        self.repair_b = _make_repair(self.shop_b, self.customer_b, status='PENDING')

    def test_cross_tenant_manager_blocked_from_bulk_approve(self):
        """
        A user who is is_manager=True at Shop A should be blocked when trying
        to bulk-approve repairs on Shop B (where they have no Technician record).
        """
        from apps.technician_portal.views.repairs import bulk_repair_action

        request = _build_post_request(
            self.factory,
            self.cross_user,
            self.shop_b,  # Request is scoped to Shop B
            {'action': 'approve', 'repair_ids': [str(self.repair_b.id)]},
        )

        response = bulk_repair_action(request)

        # Should be redirected (blocked), not approved
        self.assertEqual(response.status_code, 302)

        # Repair should NOT have been approved
        self.repair_b.refresh_from_db()
        self.assertNotEqual(self.repair_b.queue_status, 'APPROVED',
            "Cross-tenant manager should not be able to approve Shop B repairs")

    def test_cross_tenant_manager_not_assigned_as_technician(self):
        """
        A cross-tenant manager should not end up assigned as the technician on
        Shop B's repair (would be a cross-tenant data leak).
        """
        from apps.technician_portal.views.repairs import bulk_repair_action

        request = _build_post_request(
            self.factory,
            self.cross_user,
            self.shop_b,
            {'action': 'approve', 'repair_ids': [str(self.repair_b.id)]},
        )

        bulk_repair_action(request)

        self.repair_b.refresh_from_db()
        if self.repair_b.technician:
            self.assertNotEqual(self.repair_b.technician.tenant_id, self.shop_a.id,
                "Shop A's manager (cross-tenant) was assigned to Shop B repair — tenant leak!")

    def test_legitimate_manager_at_shop_b_can_bulk_approve(self):
        """
        A user who is is_manager=True at Shop B should be allowed to bulk-approve
        Shop B's repairs (control case: fix should not break legitimate managers).
        """
        from apps.technician_portal.views.repairs import bulk_repair_action

        legitimate_user = User.objects.create_user(username='legit_manager_b_081', password='pw')
        _make_technician(legitimate_user, self.shop_b, is_manager=True)

        repair = _make_repair(self.shop_b, self.customer_b, status='PENDING')

        request = _build_post_request(
            self.factory,
            legitimate_user,
            self.shop_b,
            {'action': 'approve', 'repair_ids': [str(repair.id)]},
        )

        response = bulk_repair_action(request)

        self.assertEqual(response.status_code, 302)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED',
            "Legitimate Shop B manager should be allowed to bulk-approve Shop B repairs")

    def test_no_tenant_on_request_blocks_all(self):
        """
        If request.tenant is None (misconfigured middleware), no manager
        should be able to bulk-approve (fails safe to deny).
        """
        from apps.technician_portal.views.repairs import bulk_repair_action

        request = _build_post_request(
            self.factory,
            self.cross_user,
            None,  # No tenant
            {'action': 'approve', 'repair_ids': [str(self.repair_b.id)]},
        )
        request.tenant = None

        response = bulk_repair_action(request)

        self.assertEqual(response.status_code, 302)
        self.repair_b.refresh_from_db()
        self.assertNotEqual(self.repair_b.queue_status, 'APPROVED')
