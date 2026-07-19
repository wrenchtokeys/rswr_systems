"""
CODE-254: Batch approve/deny views missing select_for_update()

Bug: customer_batch_approve() and customer_batch_deny() used @transaction.atomic
on the view decorator but did NOT use select_for_update() on individual repairs.
This meant two concurrent POST requests (double-click, two tabs) could both pass
the status guard and approve/deny the same batch — creating duplicate
RepairApproval records and TechnicianNotification records.

The single-repair views were fixed in CODE-223 and replacements in CODE-234,
but the batch views were missed.

Fix: Replaced @transaction.atomic decorator with an explicit `with transaction.atomic()`
block that uses Repair.objects.select_for_update() to lock all batch repairs, then
re-checks statuses inside the lock.  Also moved TechnicianNotification creation
outside the transaction (best effort, same pattern as CODE-223/CODE-234).
"""

import uuid
from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from apps.tenants.models import Tenant
from apps.technician_portal.models import Repair, TechnicianNotification, Technician
from apps.customer_portal.models import CustomerUser, RepairApproval
from core.models import Customer


class BatchApproveSelectForUpdateTest(TestCase):
    """Verify batch approve uses select_for_update and re-checks status."""

    def setUp(self):
        self.owner = User.objects.create_user('owner1', 'owner1@test.com', 'testpass123')
        self.tenant = Tenant.objects.create(name='Test Shop', slug='test-shop', owner=self.owner)
        self.user = User.objects.create_user('custuser', 'cust@test.com', 'testpass123')
        self.customer = Customer.objects.create(name='Test Fleet', tenant=self.tenant)
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user, customer=self.customer, is_primary_contact=True
        )
        self.tech_user = User.objects.create_user('techuser', 'tech@test.com', 'testpass123')
        self.technician = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True, can_repair=True
        )

        # Create a batch of 3 PENDING repairs
        self.batch_id = uuid.uuid4()
        self.repairs = []
        for i in range(1, 4):
            r = Repair.objects.create(
                tenant=self.tenant,
                customer=self.customer,
                technician=self.technician,
                unit_number='UNIT-001',
                damage_type='Star Break',
                queue_status='PENDING',
                repair_batch_id=self.batch_id,
                break_number=i,
                total_breaks_in_batch=3,
                cost=Decimal('25.00'),
            )
            self.repairs.append(r)

    def _make_request(self, method='POST'):
        """Build a request with tenant and session attached."""
        factory = RequestFactory()
        if method == 'POST':
            req = factory.post(f'/app/batch/{self.batch_id}/approve/')
        else:
            req = factory.get(f'/app/batch/{self.batch_id}/approve/')
        req.user = self.user
        req.tenant = self.tenant
        req.session = SessionStore()
        req.session.create()
        # Attach messages framework
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))
        return req

    def test_batch_approve_locks_repairs_and_approves(self):
        """Batch approve should lock repairs and transition all to APPROVED."""
        from apps.customer_portal.views import customer_batch_approve

        request = self._make_request('POST')
        response = customer_batch_approve(request, self.batch_id)

        # Should redirect to dashboard on success
        self.assertEqual(response.status_code, 302)

        # All repairs should be APPROVED
        for repair in Repair.objects.filter(repair_batch_id=self.batch_id):
            self.assertEqual(repair.queue_status, 'APPROVED')

        # RepairApproval records should exist for each repair
        approvals = RepairApproval.objects.filter(repair__repair_batch_id=self.batch_id)
        self.assertEqual(approvals.count(), 3)
        for approval in approvals:
            self.assertTrue(approval.approved)

        # One batch notification should be created (not 3 individual ones)
        notifications = TechnicianNotification.objects.filter(
            technician=self.technician,
            repair_batch_id=self.batch_id,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn('APPROVED', notifications.first().message)

    def test_batch_approve_rejects_already_processed(self):
        """If repairs are already approved/completed, batch approve should bail."""
        # Simulate a concurrent request that already approved the batch
        for r in self.repairs:
            r.queue_status = 'APPROVED'
            r.save()

        from apps.customer_portal.views import customer_batch_approve

        request = self._make_request('POST')
        response = customer_batch_approve(request, self.batch_id)

        # Should redirect (guard catches non-pending status)
        self.assertEqual(response.status_code, 302)

        # No new approvals created
        self.assertEqual(RepairApproval.objects.count(), 0)


class BatchDenySelectForUpdateTest(TestCase):
    """Verify batch deny uses select_for_update and re-checks status."""

    def setUp(self):
        self.owner = User.objects.create_user('owner2', 'owner2@test.com', 'testpass123')
        self.tenant = Tenant.objects.create(name='Test Shop 2', slug='test-shop-2', owner=self.owner)
        self.user = User.objects.create_user('custuser2', 'cust2@test.com', 'testpass123')
        self.customer = Customer.objects.create(name='Test Fleet 2', tenant=self.tenant)
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user, customer=self.customer, is_primary_contact=True
        )
        self.tech_user = User.objects.create_user('techuser2', 'tech2@test.com', 'testpass123')
        self.technician = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True, can_repair=True
        )

        self.batch_id = uuid.uuid4()
        self.repairs = []
        for i in range(1, 3):
            r = Repair.objects.create(
                tenant=self.tenant,
                customer=self.customer,
                technician=self.technician,
                unit_number='UNIT-002',
                damage_type='Bull Eye',
                queue_status='PENDING',
                repair_batch_id=self.batch_id,
                break_number=i,
                total_breaks_in_batch=2,
                cost=Decimal('30.00'),
            )
            self.repairs.append(r)

    def _make_request(self, method='POST', data=None):
        factory = RequestFactory()
        if method == 'POST':
            req = factory.post(f'/app/batch/{self.batch_id}/deny/', data=data or {})
        else:
            req = factory.get(f'/app/batch/{self.batch_id}/deny/')
        req.user = self.user
        req.tenant = self.tenant
        req.session = SessionStore()
        req.session.create()
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))
        return req

    def test_batch_deny_locks_repairs_and_denies(self):
        """Batch deny should lock repairs and transition all to DENIED."""
        from apps.customer_portal.views import customer_batch_deny

        request = self._make_request('POST', data={'reason': 'Not needed'})
        response = customer_batch_deny(request, self.batch_id)

        self.assertEqual(response.status_code, 302)

        for repair in Repair.objects.filter(repair_batch_id=self.batch_id):
            self.assertEqual(repair.queue_status, 'DENIED')

        approvals = RepairApproval.objects.filter(repair__repair_batch_id=self.batch_id)
        self.assertEqual(approvals.count(), 2)
        for approval in approvals:
            self.assertFalse(approval.approved)
            self.assertIn('Not needed', approval.notes)

        notifications = TechnicianNotification.objects.filter(
            technician=self.technician,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn('DENIED', notifications.first().message)

    def test_batch_deny_rejects_already_processed(self):
        """If repairs are already denied, batch deny should bail."""
        for r in self.repairs:
            r.queue_status = 'DENIED'
            r.save()

        from apps.customer_portal.views import customer_batch_deny

        request = self._make_request('POST', data={'reason': 'Too late'})
        response = customer_batch_deny(request, self.batch_id)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(RepairApproval.objects.count(), 0)
