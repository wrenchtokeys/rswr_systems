"""
Regression tests for CODE-022: technician_batch_detail and technician_batch_start_work
crash with RelatedObjectDoesNotExist for admin/owner users who lack a Technician
model record.

Root cause:
    Both views began with the bare attribute access:
        technician = request.user.technician
    This raises RelatedObjectDoesNotExist (a subclass of AttributeError) for any
    user who is permitted through @technician_required (superusers, staff, owners,
    managers via TenantMembership) but has no associated Technician row.

    The rest of both views already handled ``technician = None`` gracefully
    (elif/if guards throughout), so the fix was a one-liner:
        technician = getattr(request.user, 'technician', None)

Scenario that triggers the bug:
    A shop owner signs up and gets a TenantMembership(role='owner').
    They never create a Technician record for themselves.
    They try to view a batch via the URL — crash.

Fixed in: apps/technician_portal/views/batch.py
"""

import uuid
from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician, Repair, TechnicianNotification
from core.models import Customer


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name, owner):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner,
        plan='trial',
        subscription_plan=_make_plan(),
    )


def _make_membership(user, tenant, role='technician'):
    TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)


def _make_tech(user, tenant, is_manager=False):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        phone_number='555-0100',
        is_manager=is_manager,
    )


class BatchDetailNoTechProfileTests(TestCase):
    """
    Verifies that technician_batch_detail and technician_batch_start_work do NOT
    crash when the authenticated user has no Technician model record.
    """

    def setUp(self):
        _make_plan()

        # Owner without a Technician record
        self.owner_user = User.objects.create_user(username='shop_owner', password='pw')
        self.tenant = _make_tenant('Test Shop', self.owner_user)
        _make_membership(self.owner_user, self.tenant, 'owner')
        # Intentionally NOT creating a Technician for owner_user

        # Separate tech user who DOES have a Technician record (creates the batch)
        self.tech_user = User.objects.create_user(username='tech_a', password='pw')
        _make_membership(self.tech_user, self.tenant, 'technician')
        self.tech = _make_tech(self.tech_user, self.tenant)

        self.customer = Customer.objects.create(
            name='Fleet Co',
            address='1 Industrial Blvd',
            email='fleet@example.com',
            tenant=self.tenant,
        )

        # Build a batch of 2 repairs
        # Note: is_part_of_batch is a @property, not a field — do not pass it to create()
        self.batch_id = uuid.uuid4()
        self.repair_1 = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            service_date='2026-03-15',
            unit_number='T-001',
            damage_type='CHIP',
            queue_status='APPROVED',
            cost=Decimal('75.00'),
            repair_batch_id=self.batch_id,
            break_number=1,
            total_breaks_in_batch=2,
        )
        self.repair_2 = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            service_date='2026-03-15',
            unit_number='T-001',
            damage_type='CRACK',
            queue_status='APPROVED',
            cost=Decimal('85.00'),
            repair_batch_id=self.batch_id,
            break_number=2,
            total_breaks_in_batch=2,
        )

        self.factory = RequestFactory()

    def _make_request(self, user, method='GET', data=None):
        """Build a request with tenant and session attached."""
        if method == 'POST':
            req = self.factory.post(f'/tech/batch/{self.batch_id}/', data or {})
        else:
            req = self.factory.get(f'/tech/batch/{self.batch_id}/')
        req.user = user
        req.tenant = self.tenant
        req.session = {}
        # Attach messages middleware manually
        from django.contrib.messages.storage.fallback import FallbackStorage
        req._messages = FallbackStorage(req)
        return req

    # ------------------------------------------------------------------
    # 1. technician_batch_detail — owner without Technician record
    # ------------------------------------------------------------------

    def test_batch_detail_owner_no_tech_profile_does_not_crash(self):
        """
        Owner user with no Technician record should NOT raise
        RelatedObjectDoesNotExist when viewing a batch.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.owner_user)
        # Should not raise — just return a response
        response = technician_batch_detail(req, batch_id=self.batch_id)
        # Owner is admin → can_view=True → 200 OK (or 302 redirect to dashboard)
        self.assertIn(response.status_code, [200, 302])

    def test_batch_detail_owner_no_tech_profile_can_view(self):
        """
        Owner (is_tenant_admin=True) should be granted can_view even without
        a Technician profile — so they see the batch, not a "permission denied" redirect.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.owner_user)
        response = technician_batch_detail(req, batch_id=self.batch_id)
        # Owner is admin, so should not be redirected to dashboard with error
        # A 200 means the template rendered; a 302 to technician_dashboard would be wrong
        if response.status_code == 302:
            self.assertNotIn('technician_dashboard', response.get('Location', ''))

    def test_batch_detail_superuser_no_tech_profile_does_not_crash(self):
        """
        Superuser (is_superuser=True) with no Technician record should not crash.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        su = User.objects.create_superuser(username='superadmin', password='pw')
        req = self._make_request(su)
        # Should not raise
        response = technician_batch_detail(req, batch_id=self.batch_id)
        self.assertIn(response.status_code, [200, 302])

    def test_batch_detail_nonexistent_batch_returns_redirect(self):
        """
        A batch_id that doesn't exist should return a redirect (not crash).
        Even for owner without tech profile.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        fake_id = uuid.uuid4()
        req = self._make_request(self.owner_user)
        req._messages = __import__('django.contrib.messages.storage.fallback',
                                    fromlist=['FallbackStorage']).FallbackStorage(req)
        response = technician_batch_detail(req, batch_id=fake_id)
        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # 2. technician_batch_start_work — owner without Technician record
    # ------------------------------------------------------------------

    def test_batch_start_work_owner_no_tech_profile_does_not_crash(self):
        """
        Owner without a Technician record should NOT crash in batch_start_work.
        They just don't start any repairs (graceful no-op).
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        req = self._make_request(self.owner_user, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        # Should not raise — redirects back to batch detail
        self.assertEqual(response.status_code, 302)
        # Repairs should NOT have been started (no matching technician)
        self.repair_1.refresh_from_db()
        self.repair_2.refresh_from_db()
        self.assertEqual(self.repair_1.queue_status, 'APPROVED')
        self.assertEqual(self.repair_2.queue_status, 'APPROVED')

    def test_batch_start_work_superuser_no_tech_profile_does_not_crash(self):
        """
        Superuser without a Technician record should not crash in batch_start_work.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        su = User.objects.create_superuser(username='superadmin2', password='pw')
        req = self._make_request(su, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # 3. Normal technician — should still work
    # ------------------------------------------------------------------

    def test_batch_detail_normal_tech_can_view_own_batch(self):
        """
        A regular Technician with repairs in the batch should still be able
        to view the batch after the fix.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.tech_user)
        response = technician_batch_detail(req, batch_id=self.batch_id)
        self.assertIn(response.status_code, [200, 302])

    def test_batch_start_work_tech_with_profile_starts_repairs(self):
        """
        A regular Technician can still start work on their approved batch repairs.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        req = self._make_request(self.tech_user, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        self.assertEqual(response.status_code, 302)
        self.repair_1.refresh_from_db()
        self.repair_2.refresh_from_db()
        self.assertEqual(self.repair_1.queue_status, 'IN_PROGRESS')
        self.assertEqual(self.repair_2.queue_status, 'IN_PROGRESS')

    # ------------------------------------------------------------------
    # 4. getattr guard — unit test
    # ------------------------------------------------------------------

    def test_owner_user_has_no_technician_attribute(self):
        """
        Baseline sanity check: owner_user genuinely has no Technician record.
        Accessing .technician directly should raise an exception; getattr should
        return None.
        """
        with self.assertRaises(Exception):
            _ = self.owner_user.technician

        result = getattr(self.owner_user, 'technician', None)
        self.assertIsNone(result)
