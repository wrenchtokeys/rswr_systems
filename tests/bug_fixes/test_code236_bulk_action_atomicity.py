"""
CODE-236 — customer_bulk_action race condition (select_for_update)

The customer bulk approve/deny view wrapped its work in transaction.atomic()
but did NOT use select_for_update() on the repairs queryset.  Two concurrent
bulk-approve requests could both read the same PENDING status, both transition
to APPROVED, and both create duplicate TechnicianNotification records.

The fix adds select_for_update() to the queryset, re-checks status inside the
lock, and moves notification creation outside the transaction (best effort).

This test file exercises:
  1. Basic bulk approve (happy path)
  2. Basic bulk deny (happy path)
  3. Already-completed repairs are excluded (status guard)
  4. Repairs from a different customer are excluded (tenant isolation)
  5. Notifications are created for each processed repair
  6. No duplicate notifications on double-submit (simulated)
  7. Mixed statuses — only PENDING/REQUESTED are processed
  8. Empty repair_ids → error message
  9. Invalid action → error message
"""
from decimal import Decimal

from django.contrib.auth.models import User, Group
from django.test import TestCase, RequestFactory
from django.utils import timezone

from apps.technician_portal.models import Technician, Repair, TechnicianNotification
from apps.customer_portal.models import CustomerUser, RepairApproval
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class BulkActionAtomicityTestBase(TestCase):
    """Shared setup for customer_bulk_action tests."""

    @classmethod
    def setUpTestData(cls):
        # Owner user (must exist before Tenant — owner_id is NOT NULL)
        cls.owner_user = User.objects.create_user(
            username='owner236', email='owner236@test.com', password='testpass123'
        )
        cls.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-236',
            plan='professional',
            owner=cls.owner_user,
        )
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.owner_user, role='owner', is_active=True
        )

        # Technician
        cls.tech_user = User.objects.create_user(
            username='tech236', email='tech236@test.com', password='testpass123'
        )
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        cls.tech_user.groups.add(tech_group)
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.tech_user, role='technician', is_active=True
        )
        cls.technician = Technician.objects.create(
            user=cls.tech_user, tenant=cls.tenant, is_active=True
        )

        # Customer + CustomerUser (the person who bulk-approves)
        cls.customer = Customer.objects.create(
            name='Bulk Test Fleet', tenant=cls.tenant
        )
        # Explicitly require approval — shop-created work auto-approves by default
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=cls.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        cls.cust_user = User.objects.create_user(
            username='custbulk236', email='custbulk236@test.com', password='testpass123'
        )
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.cust_user, role='viewer', is_active=True
        )
        cls.customer_user = CustomerUser.objects.create(
            user=cls.cust_user, customer=cls.customer
        )

        # Another tenant (for isolation tests)
        cls.other_owner = User.objects.create_user(
            username='otherowner236', email='otherowner236@test.com', password='testpass123'
        )
        cls.tenant_b = Tenant.objects.create(
            name='Other Shop', slug='other-shop-236', plan='professional',
            owner=cls.other_owner,
        )
        cls.customer_b = Customer.objects.create(
            name='Other Fleet', tenant=cls.tenant_b
        )
        CustomerRepairPreference.objects.create(
            customer=cls.customer_b,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )

    def _create_repair(self, status='PENDING', customer=None, tenant=None, **kwargs):
        return Repair.objects.create(
            customer=customer or self.customer,
            tenant=tenant or self.tenant,
            technician=self.technician,
            unit_number='UNIT-236',
            damage_type='CHIP',
            queue_status=status,
            cost=Decimal('50.00'),
            service_date=timezone.now().date(),
            **kwargs,
        )

    def _post_bulk(self, action, repair_ids):
        """POST to customer_bulk_action as the customer user with tenant context."""
        self.client.login(username='custbulk236', password='testpass123')
        # Set tenant in session via the middleware's X-Tenant-Slug header
        data = {'action': action, 'repair_ids': [str(rid) for rid in repair_ids]}
        return self.client.post(
            '/app/repairs/bulk-action/',
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )


class BulkApproveTests(BulkActionAtomicityTestBase):
    """Test bulk approve happy path."""

    def test_bulk_approve_transitions_repairs(self):
        """Bulk approve should transition PENDING repairs to APPROVED."""
        r1 = self._create_repair(status='PENDING')
        r2 = self._create_repair(status='PENDING')

        self._post_bulk('approve', [r1.id, r2.id])

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.queue_status, 'APPROVED')
        self.assertEqual(r2.queue_status, 'APPROVED')

    def test_bulk_approve_creates_approval_records(self):
        """Bulk approve should create RepairApproval records."""
        r1 = self._create_repair(status='PENDING')

        self._post_bulk('approve', [r1.id])

        self.assertTrue(
            RepairApproval.objects.filter(repair=r1, approved=True).exists()
        )

    def test_bulk_approve_creates_notifications(self):
        """Each approved repair should generate a technician notification."""
        r1 = self._create_repair(status='PENDING')
        r2 = self._create_repair(status='PENDING')

        self._post_bulk('approve', [r1.id, r2.id])

        notifs = TechnicianNotification.objects.filter(
            technician=self.technician, repair__in=[r1, r2]
        )
        self.assertEqual(notifs.count(), 2)

    def test_bulk_approve_requested_repairs_refused(self):
        """REQUESTED repairs must NOT be customer-approvable via bulk action —
        the shop reviews/prices submissions; only PENDING is approvable."""
        r1 = self._create_repair(status='REQUESTED')

        self._post_bulk('approve', [r1.id])

        r1.refresh_from_db()
        self.assertEqual(r1.queue_status, 'REQUESTED')


class BulkDenyTests(BulkActionAtomicityTestBase):
    """Test bulk deny happy path."""

    def test_bulk_deny_transitions_repairs(self):
        """Bulk deny should transition PENDING repairs to DENIED."""
        r1 = self._create_repair(status='PENDING')

        self._post_bulk('deny', [r1.id])

        r1.refresh_from_db()
        self.assertEqual(r1.queue_status, 'DENIED')

    def test_bulk_deny_creates_denial_record(self):
        """Bulk deny should create RepairApproval with approved=False."""
        r1 = self._create_repair(status='PENDING')

        self._post_bulk('deny', [r1.id])

        approval = RepairApproval.objects.get(repair=r1)
        self.assertFalse(approval.approved)
        self.assertIn('Bulk denied', approval.notes)


class BulkActionStatusGuardTests(BulkActionAtomicityTestBase):
    """Test that non-PENDING/REQUESTED repairs are excluded."""

    def test_completed_repairs_excluded(self):
        """Already-completed repairs should not be processed."""
        r1 = self._create_repair(status='COMPLETED')

        self._post_bulk('approve', [r1.id])

        r1.refresh_from_db()
        self.assertEqual(r1.queue_status, 'COMPLETED')  # unchanged

    def test_mixed_statuses_only_pending_processed(self):
        """Only PENDING/REQUESTED repairs should be processed; others ignored."""
        r_pending = self._create_repair(status='PENDING')
        r_completed = self._create_repair(status='COMPLETED')
        r_denied = self._create_repair(status='DENIED')

        self._post_bulk('approve', [r_pending.id, r_completed.id, r_denied.id])

        r_pending.refresh_from_db()
        r_completed.refresh_from_db()
        r_denied.refresh_from_db()

        self.assertEqual(r_pending.queue_status, 'APPROVED')
        self.assertEqual(r_completed.queue_status, 'COMPLETED')
        self.assertEqual(r_denied.queue_status, 'DENIED')


class BulkActionTenantIsolationTests(BulkActionAtomicityTestBase):
    """Test that repairs from other tenants cannot be bulk-actioned."""

    def test_other_tenant_repairs_excluded(self):
        """Repairs from another customer/tenant should not be processed."""
        # Create a technician in tenant B for the foreign repair
        other_tech_user = User.objects.create_user(
            username='othertech236', email='othertech236@test.com', password='testpass123'
        )
        other_tech = Technician.objects.create(
            user=other_tech_user, tenant=self.tenant_b, is_active=True
        )
        # Create a repair in tenant B
        r_other = Repair.objects.create(
            customer=self.customer_b,
            tenant=self.tenant_b,
            technician=other_tech,
            unit_number='UNIT-OTHER',
            damage_type='CHIP',
            queue_status='PENDING',
            cost=Decimal('50.00'),
            service_date=timezone.now().date(),
        )

        self._post_bulk('approve', [r_other.id])

        r_other.refresh_from_db()
        self.assertEqual(r_other.queue_status, 'PENDING')  # unchanged


class BulkActionDoubleSubmitTests(BulkActionAtomicityTestBase):
    """Test that double-submit does not create duplicate notifications."""

    def test_no_duplicate_notifications_on_second_submit(self):
        """Second bulk-approve on already-approved repairs creates no new notifications."""
        r1 = self._create_repair(status='PENDING')

        # First submit
        self._post_bulk('approve', [r1.id])

        notif_count_after_first = TechnicianNotification.objects.filter(
            technician=self.technician, repair=r1
        ).count()
        self.assertEqual(notif_count_after_first, 1)

        # Second submit — repair is now APPROVED, so should be skipped
        self._post_bulk('approve', [r1.id])

        notif_count_after_second = TechnicianNotification.objects.filter(
            technician=self.technician, repair=r1
        ).count()
        # Should still be 1 — no duplicate
        self.assertEqual(notif_count_after_second, 1)


class BulkActionValidationTests(BulkActionAtomicityTestBase):
    """Test input validation edge cases."""

    def test_empty_repair_ids(self):
        """Empty repair_ids should redirect with error."""
        self.client.login(username='custbulk236', password='testpass123')
        response = self.client.post(
            '/app/repairs/bulk-action/',
            {'action': 'approve'},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # View returns 302 redirect with error message
        self.assertIn(response.status_code, [302, 400])

    def test_invalid_action(self):
        """Invalid action type should redirect with error."""
        r1 = self._create_repair(status='PENDING')
        self.client.login(username='custbulk236', password='testpass123')
        response = self.client.post(
            '/app/repairs/bulk-action/',
            {'action': 'invalid', 'repair_ids': [str(r1.id)]},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # View returns 302 redirect with error message
        self.assertIn(response.status_code, [302, 400])
