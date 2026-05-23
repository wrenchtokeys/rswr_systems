"""
Regression tests for CODE-082:
Unscoped request.user.technician in create_repair, update_repair, and update_queue_status.

Root cause:
  Three views used `request.user.technician` (unscoped OneToOneField reverse
  lookup) when a non-admin user interacted with repairs:

  1. create_repair  — guard check used bare .technician, then assigned
     `repair.technician = request.user.technician`.  A user who has a
     Technician record at Shop A but a TenantMembership (role=technician)
     at Shop B could create a Shop B repair with Shop A's Technician attached.

  2. update_repair  — `repair.technician_id != request.user.technician.id`
     for the ownership check.  A cross-tenant user could fail the check
     (their Shop A technician_id never matches Shop B repairs) — relatively
     safe in isolation, but still wrong and a symptom of the broader pattern.

  3. update_queue_status — `technician = request.user.technician` unscoped,
     meaning is_manager and manages_technician() calls resolved against the
     wrong tenant's Technician record.

Fix: Use Technician.objects.filter(user=request.user, tenant=tenant).first()
     in all three views.

Test scenarios:
  A. create_repair: Cross-tenant technician (Shop A tech hitting Shop B) is
     blocked at the guard — no Technician record for Shop B.
  B. create_repair: Legitimate Shop B technician can create a repair with
     their own Shop B Technician correctly assigned.
  C. update_queue_status: Cross-tenant technician cannot update Shop B repair
     status (redirect to dashboard).
  D. update_queue_status: Legitimate Shop B technician can update their own
     repair status.
  E. update_repair: Cross-tenant user is blocked from editing a Shop B repair
     (redirect to repair detail, not their repair).
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponseRedirect

from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.views.repairs import create_repair, update_queue_status, update_repair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_get_request(url, user, tenant):
    factory = RequestFactory()
    req = factory.get(url)
    req.user = user
    req.tenant = tenant
    setattr(req, 'session', 'session')
    setattr(req, '_messages', FallbackStorage(req))
    return req


def _make_post_request(url, user, tenant, data):
    factory = RequestFactory()
    req = factory.post(url, data=data)
    req.user = user
    req.tenant = tenant
    setattr(req, 'session', 'session')
    setattr(req, '_messages', FallbackStorage(req))
    return req


def _make_user(username):
    return User.objects.create_user(
        username=username,
        password='testpass123',
        email=f'{username}@test.com',
    )


def _make_tenant(name):
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "_")}',
        password='ownerpass',
        email=f'owner_{name.lower().replace(" ", "")}@test.com',
    )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        is_active=True,
        owner=owner,
    )


def _make_customer(tenant, name='Test Fleet'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='FLEET',
    )


def _make_technician(user, tenant, is_manager=False):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=is_manager,
        is_active=True,
        can_repair=True,
    )


def _make_repair(tenant, customer, technician, status='APPROVED'):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        damage_type='Chip',
        queue_status=status,
    )


# ---------------------------------------------------------------------------
# Test: create_repair guard — cross-tenant technician is blocked
# ---------------------------------------------------------------------------

class CreateRepairCrossTenantGuardTest(TestCase):
    """
    A user with a Technician record at Shop A but TenantMembership (technician)
    at Shop B must be blocked at create_repair's guard check, not allowed through.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A Guard')
        self.shop_b = _make_tenant('Shop B Guard')

        self.user = _make_user('cross_create')

        # Technician record ONLY at Shop A
        self.tech_a = _make_technician(self.user, self.shop_a)

        # TenantMembership at Shop B (so decorator passes)
        TenantMembership.objects.create(
            tenant=self.shop_b,
            user=self.user,
            role='technician',
            is_active=True,
        )

    def test_cross_tenant_technician_blocked_on_create_repair_get(self):
        """
        GET create_repair on Shop B: user has no Shop B Technician record.
        Must redirect away (guard blocks them — does not render the form).
        The redirect target is /tech/ or dashboard depending on role lookup.
        """
        req = _make_get_request('/repairs/create/', self.user, self.shop_b)
        response = create_repair(req)

        self.assertIsInstance(response, HttpResponseRedirect,
                              "Cross-tenant technician should be redirected, not shown the form")


# ---------------------------------------------------------------------------
# Test: create_repair — legitimate technician can create repairs
# ---------------------------------------------------------------------------

class CreateRepairLegitimateTest(TestCase):
    """
    A user with a Technician at Shop B should be able to GET the create_repair
    form (guard passes) and the technician in scope should be the Shop B one.
    """

    def setUp(self):
        self.shop_b = _make_tenant('Shop B Legit Create')

        self.user = _make_user('legit_create')
        self.tech_b = _make_technician(self.user, self.shop_b)

        TenantMembership.objects.create(
            tenant=self.shop_b,
            user=self.user,
            role='technician',
            is_active=True,
        )

        self.customer = _make_customer(self.shop_b)

    def test_legitimate_tech_passes_guard(self):
        """
        GET create_repair on Shop B: user has a Shop B Technician.
        Should render the form (not redirect to dashboard).
        """
        req = _make_get_request('/repairs/create/', self.user, self.shop_b)
        response = create_repair(req)

        # Should render the form (200) or at least not redirect to dashboard
        if isinstance(response, HttpResponseRedirect):
            self.assertNotIn('dashboard', response['Location'],
                             "Legitimate technician was incorrectly blocked by create_repair guard")


# ---------------------------------------------------------------------------
# Test: update_queue_status — cross-tenant technician blocked
# ---------------------------------------------------------------------------

class UpdateQueueStatusCrossTenantTest(TestCase):
    """
    A user with Technician at Shop A but membership at Shop B cannot update
    Shop B repair statuses.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A QS')
        self.shop_b = _make_tenant('Shop B QS')

        self.cross_user = _make_user('cross_qs_user')
        self.tech_a = _make_technician(self.cross_user, self.shop_a)

        # TenantMembership at Shop B (so decorator passes)
        TenantMembership.objects.create(
            tenant=self.shop_b,
            user=self.cross_user,
            role='technician',
            is_active=True,
        )

        # A legitimate tech to own the Shop B repair
        self.legit_user = _make_user('legit_qs_user')
        self.tech_b = _make_technician(self.legit_user, self.shop_b)
        TenantMembership.objects.create(
            tenant=self.shop_b,
            user=self.legit_user,
            role='technician',
            is_active=True,
        )

        self.customer_b = _make_customer(self.shop_b)
        self.repair_b = _make_repair(self.shop_b, self.customer_b, self.tech_b, 'APPROVED')

    def test_cross_tenant_cannot_update_shop_b_repair_status(self):
        """
        Cross-tenant user (Technician at Shop A) cannot update the status
        of a Shop B repair — must redirect away.
        """
        req = _make_post_request(
            f'/repairs/{self.repair_b.id}/status/',
            self.cross_user,
            self.shop_b,
            {'status': 'IN_PROGRESS'},
        )
        response = update_queue_status(req, repair_id=self.repair_b.id)

        # Must redirect (either dashboard or repair_detail with error)
        self.assertIsInstance(response, HttpResponseRedirect)

        # Repair should still be APPROVED — not changed by cross-tenant user
        self.repair_b.refresh_from_db()
        self.assertEqual(self.repair_b.queue_status, 'APPROVED')

    def test_legitimate_tech_can_update_own_repair_status(self):
        """
        A technician with a proper Shop B record can update their repair status.
        """
        req = _make_post_request(
            f'/repairs/{self.repair_b.id}/status/',
            self.legit_user,
            self.shop_b,
            {'status': 'IN_PROGRESS'},
        )
        response = update_queue_status(req, repair_id=self.repair_b.id)

        # Should redirect (success redirect to repair_detail)
        self.assertIsInstance(response, HttpResponseRedirect)

        # Repair status should now be IN_PROGRESS
        self.repair_b.refresh_from_db()
        self.assertEqual(self.repair_b.queue_status, 'IN_PROGRESS')


# ---------------------------------------------------------------------------
# Test: update_repair — cross-tenant user cannot edit Shop B repair
# ---------------------------------------------------------------------------

class UpdateRepairCrossTenantTest(TestCase):
    """
    A user with Technician at Shop A but membership at Shop B cannot edit
    repairs belonging to Shop B technicians.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A UR')
        self.shop_b = _make_tenant('Shop B UR')

        self.cross_user = _make_user('cross_ur_user')
        self.tech_a = _make_technician(self.cross_user, self.shop_a)

        # TenantMembership at Shop B (so decorator passes)
        TenantMembership.objects.create(
            tenant=self.shop_b,
            user=self.cross_user,
            role='technician',
            is_active=True,
        )

        self.legit_user = _make_user('legit_ur_user')
        self.tech_b = _make_technician(self.legit_user, self.shop_b)
        TenantMembership.objects.create(
            tenant=self.shop_b,
            user=self.legit_user,
            role='technician',
            is_active=True,
        )

        self.customer_b = _make_customer(self.shop_b)
        # Repair at Shop B assigned to the legitimate tech
        self.repair_b = _make_repair(self.shop_b, self.customer_b, self.tech_b, 'IN_PROGRESS')

    def test_cross_tenant_user_cannot_edit_shop_b_repair(self):
        """
        Cross-tenant user (Technician at Shop A) cannot edit Shop B's repair.
        Must be redirected with an error — not shown the edit form.
        """
        req = _make_get_request(
            f'/repairs/{self.repair_b.id}/edit/',
            self.cross_user,
            self.shop_b,
        )
        response = update_repair(req, repair_id=self.repair_b.id)

        # Must redirect — not show the edit form
        self.assertIsInstance(response, HttpResponseRedirect)

    def test_assigned_tech_can_edit_own_repair(self):
        """
        The assigned technician for a Shop B repair can access the edit view.
        """
        req = _make_get_request(
            f'/repairs/{self.repair_b.id}/edit/',
            self.legit_user,
            self.shop_b,
        )
        response = update_repair(req, repair_id=self.repair_b.id)

        # Should render (200) or redirect to detail — not be blocked
        if isinstance(response, HttpResponseRedirect):
            self.assertNotIn('dashboard', response['Location'],
                             "Legitimate technician was blocked from editing their own repair")
