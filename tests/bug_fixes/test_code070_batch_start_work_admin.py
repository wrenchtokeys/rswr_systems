"""
Regression tests for CODE-070:
  technician_batch_start_work() silently did nothing when called by an
  admin/owner who had no Technician profile.

Root cause:
    The view looped over batch repairs and only set queue_status='IN_PROGRESS'
    when `repair.technician == technician`.  For admin users without a
    Technician profile, `getattr(request.user, 'technician', None)` returns
    None.  The comparison `repair.technician == None` is only True when a
    repair is unassigned — so an admin clicking "Start Work" on an assigned
    batch got "No repairs were started" and a warning message, despite the
    batch_detail view having correctly set `can_start_work = True` for admins.

Fix (CODE-070):
    Determine `user_is_admin = is_tenant_admin(request.user, tenant=tenant)`
    in the start_work view (same as batch_detail already did).  In the loop,
    skip non-APPROVED repairs then allow start if `user_is_admin OR
    repair.technician == technician`.

Tests verify:
1. Owner without Technician profile can start all APPROVED repairs in a batch.
2. Owner with Technician profile can start all APPROVED repairs in a batch.
3. Technician can start only repairs assigned to them.
4. Technician cannot start repairs assigned to another tech.
5. Already IN_PROGRESS repairs are not double-counted.
6. Non-APPROVED repairs (PENDING, COMPLETED) are left unchanged.
7. Cross-tenant: start_work on another tenant's batch is blocked.
8. Admin start_work returns correct JSON response for AJAX requests.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User

from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from core.models import Customer


# ---------------------------------------------------------------------------
# Test settings override (allow any host, keep sessions in DB)
# ---------------------------------------------------------------------------
TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    return plan


def _make_tenant(name, slug):
    plan = _get_plan()
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        password='pw',
        email=f'owner_{slug}@test.com',
        first_name='Owner',
        last_name=slug,
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return owner, tenant


def _make_tech(tenant, suffix):
    user = User.objects.create_user(
        username=f'tech_{suffix}',
        password='pw',
        email=f'tech_{suffix}@test.com',
    )
    TenantMembership.objects.create(user=user, tenant=tenant, role='technician', is_active=True)
    tech = Technician.objects.create(user=user, tenant=tenant, is_active=True)
    return user, tech


def _make_customer(tenant, name='Fleet Inc'):
    return Customer.objects.create(
        name=name, tenant=tenant, email=f'{name.lower().replace(" ", "")}@test.com'
    )


def _make_batch(tenant, customer, technician, count=2, status='APPROVED'):
    """Create `count` repairs sharing a batch_id."""
    batch_id = uuid.uuid4()
    repairs = []
    for i in range(count):
        r = Repair.objects.create(
            tenant=tenant,
            technician=technician,
            customer=customer,
            unit_number='UNIT-7',
            service_date=date.today(),
            damage_type='chip',
            cost=75,
            queue_status=status,
            repair_batch_id=batch_id,
            break_number=i + 1,
            total_breaks_in_batch=count,
        )
        repairs.append(r)
    return batch_id, repairs


def _authed_client(user, tenant):
    """Return a logged-in Client with the tenant stored in session."""
    c = Client()
    c.force_login(user)
    session = c.session
    session['tenant_id'] = tenant.id
    session.save()
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class BatchStartWorkAdminTests(TestCase):
    """Admin/owner (with or without Technician profile) can start batch repairs."""

    def setUp(self):
        self.owner, self.tenant = _make_tenant('CODE070 ShopA', 'c070-shop-a')
        self.customer = _make_customer(self.tenant)
        self.tech_user, self.tech = _make_tech(self.tenant, 'c070t1')

    def _url(self, batch_id):
        return reverse('technician_batch_start_work', kwargs={'batch_id': batch_id})

    # ------------------------------------------------------------------
    # 1. Owner WITHOUT Technician profile starts all APPROVED repairs
    # ------------------------------------------------------------------
    def test_owner_no_tech_profile_starts_all_approved(self):
        """Before fix: owner with no Technician profile started 0 repairs. After: all start."""
        # Confirm owner has no Technician record
        self.assertFalse(Technician.objects.filter(user=self.owner).exists())

        batch_id, repairs = _make_batch(self.tenant, self.customer, self.tech, count=3, status='APPROVED')
        client = _authed_client(self.owner, self.tenant)
        resp = client.post(self._url(batch_id), SERVER_NAME='c070-shop-a.testserver')

        # Should redirect back to batch detail (302) — not a server error
        self.assertEqual(resp.status_code, 302)

        # All 3 APPROVED repairs should now be IN_PROGRESS
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(
                r.queue_status,
                'IN_PROGRESS',
                f'Repair {r.id} should be IN_PROGRESS after admin start_work; got {r.queue_status}',
            )

    # ------------------------------------------------------------------
    # 2. Owner WITH Technician profile also starts all APPROVED repairs
    # ------------------------------------------------------------------
    def test_owner_with_tech_profile_starts_all_approved(self):
        """Owner who also has a Technician record can start all assigned repairs."""
        # Give the owner a Technician profile
        Technician.objects.create(user=self.owner, tenant=self.tenant, is_active=True)
        batch_id, repairs = _make_batch(self.tenant, self.customer, self.tech, count=2, status='APPROVED')
        client = _authed_client(self.owner, self.tenant)
        client.post(self._url(batch_id), SERVER_NAME='c070-shop-a.testserver')

        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'IN_PROGRESS')

    # ------------------------------------------------------------------
    # 3. Technician starts only their own repairs
    # ------------------------------------------------------------------
    def test_technician_starts_only_own_repairs(self):
        """A plain technician may only start repairs assigned to them."""
        _, tech2 = _make_tech(self.tenant, 'c070t2')
        batch_id = uuid.uuid4()
        r_mine = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='UNIT-8', service_date=date.today(), damage_type='chip',
            cost=75, queue_status='APPROVED', repair_batch_id=batch_id,
            break_number=1, total_breaks_in_batch=2,
        )
        r_other = Repair.objects.create(
            tenant=self.tenant, technician=tech2, customer=self.customer,
            unit_number='UNIT-8', service_date=date.today(), damage_type='chip',
            cost=75, queue_status='APPROVED', repair_batch_id=batch_id,
            break_number=2, total_breaks_in_batch=2,
        )

        client = _authed_client(self.tech_user, self.tenant)
        client.post(self._url(batch_id), SERVER_NAME='c070-shop-a.testserver')

        r_mine.refresh_from_db()
        r_other.refresh_from_db()
        self.assertEqual(r_mine.queue_status, 'IN_PROGRESS', "Own repair should start")
        self.assertEqual(r_other.queue_status, 'APPROVED', "Other tech's repair should stay APPROVED")

    # ------------------------------------------------------------------
    # 4. Already IN_PROGRESS repairs are skipped
    # ------------------------------------------------------------------
    def test_already_in_progress_stays_in_progress(self):
        """Repairs already IN_PROGRESS are not modified (no double-start side-effects)."""
        batch_id, repairs = _make_batch(self.tenant, self.customer, self.tech, count=2, status='IN_PROGRESS')
        client = _authed_client(self.owner, self.tenant)
        client.post(self._url(batch_id), SERVER_NAME='c070-shop-a.testserver')

        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'IN_PROGRESS')

    # ------------------------------------------------------------------
    # 5. Non-APPROVED repairs (PENDING) are left unchanged
    # ------------------------------------------------------------------
    def test_pending_repairs_not_started(self):
        """Only APPROVED repairs transition; PENDING ones are left alone."""
        batch_id = uuid.uuid4()
        r_pending = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='UNIT-9', service_date=date.today(), damage_type='chip',
            cost=75, queue_status='PENDING', repair_batch_id=batch_id,
            break_number=1, total_breaks_in_batch=2,
        )
        r_approved = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='UNIT-9', service_date=date.today(), damage_type='chip',
            cost=75, queue_status='APPROVED', repair_batch_id=batch_id,
            break_number=2, total_breaks_in_batch=2,
        )

        client = _authed_client(self.owner, self.tenant)
        client.post(self._url(batch_id), SERVER_NAME='c070-shop-a.testserver')

        r_pending.refresh_from_db()
        r_approved.refresh_from_db()
        self.assertEqual(r_pending.queue_status, 'PENDING', 'PENDING should remain PENDING')
        self.assertEqual(r_approved.queue_status, 'IN_PROGRESS', 'APPROVED should become IN_PROGRESS')

    # ------------------------------------------------------------------
    # 6. Cross-tenant: owner from another shop is blocked
    # ------------------------------------------------------------------
    def test_cross_tenant_batch_blocked(self):
        """An owner from a different tenant cannot start another tenant's batch."""
        batch_id, repairs = _make_batch(
            self.tenant, self.customer, self.tech, count=2, status='APPROVED'
        )
        owner_b, tenant_b = _make_tenant('CODE070 ShopB', 'c070-shop-b')
        client_b = _authed_client(owner_b, tenant_b)
        resp = client_b.post(self._url(batch_id), SERVER_NAME='c070-shop-b.testserver')

        # Redirected to dashboard (batch not found for tenant B)
        self.assertEqual(resp.status_code, 302)

        # Tenant A's repairs must remain APPROVED (untouched)
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'APPROVED')

    # ------------------------------------------------------------------
    # 7. AJAX returns JSON with correct started_count
    # ------------------------------------------------------------------
    def test_ajax_returns_correct_started_count(self):
        """AJAX call returns JSON {success, started_count} matching the number of APPROVED repairs."""
        batch_id, repairs = _make_batch(self.tenant, self.customer, self.tech, count=3, status='APPROVED')
        client = _authed_client(self.owner, self.tenant)
        resp = client.post(
            self._url(batch_id),
            SERVER_NAME='c070-shop-a.testserver',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('started_count'), 3)

    # ------------------------------------------------------------------
    # 8. Unauthenticated access redirects to login
    # ------------------------------------------------------------------
    def test_unauthenticated_redirects_to_login(self):
        batch_id, _ = _make_batch(self.tenant, self.customer, self.tech, count=1, status='APPROVED')
        resp = Client().post(self._url(batch_id), SERVER_NAME='c070-shop-a.testserver')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'].lower())
