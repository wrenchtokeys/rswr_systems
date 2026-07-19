"""
CODE-223: customer_repair_approve and customer_repair_deny lack transaction
atomicity and race-condition protection.

Bug: Both views made two separate DB writes (RepairApproval.get_or_create +
repair.save()) without @transaction.atomic, and without a row-level lock via
select_for_update(). A failure between the two writes would leave the DB in an
inconsistent state (approval record created but repair status unchanged, or
vice versa). A double-click or concurrent POST could also slip through the
pre-lock status check.

Fix: Wrapped the write section in transaction.atomic() + select_for_update()
with an inner status re-check, mirroring the pattern already used in
quick_approve_repair and quick_deny_repair.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser, RepairApproval
from apps.tenants.models import Tenant, TenantMembership


class RepairApproveAtomicityTests(TestCase):
    """Verify customer_repair_approve/deny are atomic and race-safe."""

    def setUp(self):
        # Owner user (must be created first so tenant can reference it)
        self.owner = User.objects.create_user(
            username='owner223',
            email='owner223@example.com',
            password='ownerpass',
        )

        # Tenant
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-223',
            is_active=True,
            owner=self.owner,
        )

        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True
        )

        # Technician user
        self.tech_user = User.objects.create_user(
            username='tech223',
            email='tech223@example.com',
            password='techpass',
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.tech_user, role='technician', is_active=True
        )
        self.tech = Technician.objects.create(
            tenant=self.tenant,
            user=self.tech_user,
            is_active=True,
        )

        # Customer
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Fleet',
            customer_type='FLEET',
        )
        # Explicitly require approval — shop-created work auto-approves by default
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )

        # Customer portal user
        self.customer_user_django = User.objects.create_user(
            username='cu223',
            email='cu223@example.com',
            password='cupass',
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.customer_user_django,
            role='viewer',
            is_active=True,
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.customer_user_django,
            customer=self.customer,
            is_primary_contact=True,
        )

        # A PENDING repair
        self.repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='101',
            damage_type='chip',
            queue_status='PENDING',
            cost=45.00,
        )

        self.client = Client()
        # Log in as the customer portal user
        self.client.login(username='cu223', password='cupass')
        # Set session tenant
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    # ----------------------------------------------------------------
    # Approve tests
    # ----------------------------------------------------------------

    def test_approve_sets_repair_to_approved(self):
        """A POST to customer_repair_approve changes queue_status to APPROVED."""
        response = self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': 'Looks good'},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'APPROVED')

    def test_approve_creates_repair_approval_record(self):
        """Approving creates a RepairApproval with approved=True."""
        self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': 'Approved notes'},
        )
        approval = RepairApproval.objects.filter(repair=self.repair).first()
        self.assertIsNotNone(approval, "RepairApproval should be created")
        self.assertTrue(approval.approved)
        self.assertEqual(approval.notes, 'Approved notes')

    def test_approve_idempotent_for_already_approved(self):
        """Approving an already-APPROVED repair returns warning, not 500."""
        self.repair.queue_status = 'APPROVED'
        self.repair.save()
        response = self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': ''},
        )
        # Should redirect back to detail, not crash
        self.assertIn(response.status_code, [200, 302])
        # Status should remain APPROVED
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'APPROVED')

    def test_approve_cannot_change_completed_repair(self):
        """A direct POST cannot flip a COMPLETED repair to APPROVED."""
        self.repair.queue_status = 'COMPLETED'
        self.repair.save()
        self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': ''},
        )
        self.repair.refresh_from_db()
        # Must stay COMPLETED, not be overwritten to APPROVED
        self.assertEqual(self.repair.queue_status, 'COMPLETED')

    def test_approve_cannot_change_denied_repair(self):
        """A direct POST cannot flip a DENIED repair to APPROVED."""
        self.repair.queue_status = 'DENIED'
        self.repair.save()
        self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': ''},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')

    def test_approve_both_writes_succeed_together(self):
        """Both RepairApproval and repair.queue_status are consistent after approve."""
        self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': 'atomic test'},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'APPROVED')
        approval = RepairApproval.objects.filter(repair=self.repair).first()
        self.assertIsNotNone(approval)
        self.assertTrue(approval.approved)

    # ----------------------------------------------------------------
    # Deny tests
    # ----------------------------------------------------------------

    def test_deny_sets_repair_to_denied(self):
        """A POST to customer_repair_deny changes queue_status to DENIED."""
        response = self.client.post(
            f'/app/repairs/{self.repair.id}/deny/',
            {'reason': 'Not authorized'},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')

    def test_deny_creates_repair_approval_record(self):
        """Denying creates a RepairApproval with approved=False."""
        self.client.post(
            f'/app/repairs/{self.repair.id}/deny/',
            {'reason': 'Too expensive'},
        )
        approval = RepairApproval.objects.filter(repair=self.repair).first()
        self.assertIsNotNone(approval, "RepairApproval should be created on deny")
        self.assertFalse(approval.approved)
        self.assertEqual(approval.notes, 'Too expensive')

    def test_deny_idempotent_for_already_denied(self):
        """Denying an already-DENIED repair returns warning, not 500."""
        self.repair.queue_status = 'DENIED'
        self.repair.save()
        response = self.client.post(
            f'/app/repairs/{self.repair.id}/deny/',
            {'reason': ''},
        )
        self.assertIn(response.status_code, [200, 302])
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')

    def test_deny_cannot_change_completed_repair(self):
        """A direct POST cannot flip a COMPLETED repair to DENIED."""
        self.repair.queue_status = 'COMPLETED'
        self.repair.save()
        self.client.post(
            f'/app/repairs/{self.repair.id}/deny/',
            {'reason': ''},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'COMPLETED')

    def test_deny_both_writes_succeed_together(self):
        """Both RepairApproval and repair.queue_status are consistent after deny."""
        self.client.post(
            f'/app/repairs/{self.repair.id}/deny/',
            {'reason': 'atomic deny test'},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')
        approval = RepairApproval.objects.filter(repair=self.repair).first()
        self.assertIsNotNone(approval)
        self.assertFalse(approval.approved)

    def test_approve_requested_repair(self):
        """REQUESTED repairs (customer self-submitted) can also be approved."""
        # Queryset update: PENDING -> REQUESTED is not a legal runtime
        # transition (D1); real REQUESTED repairs are created that way.
        Repair.objects.filter(pk=self.repair.pk).update(queue_status='REQUESTED')
        self.repair.refresh_from_db()
        self.client.post(
            f'/app/repairs/{self.repair.id}/approve/',
            {'notes': 'approved from requested'},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'APPROVED')

    def test_deny_requested_repair(self):
        """REQUESTED repairs can also be denied."""
        # Queryset update — see test_approve_requested_repair.
        Repair.objects.filter(pk=self.repair.pk).update(queue_status='REQUESTED')
        self.repair.refresh_from_db()
        self.client.post(
            f'/app/repairs/{self.repair.id}/deny/',
            {'reason': 'denied from requested'},
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')

    def test_cross_tenant_repair_denied(self):
        """Customer cannot approve a repair belonging to a different tenant."""
        other_owner = User.objects.create_user(
            username='otherowner223',
            email='otherowner223@example.com',
            password='oopass',
        )
        other_tenant = Tenant.objects.create(
            name='Other Shop',
            slug='other-shop-223',
            is_active=True,
            owner=other_owner,
        )
        other_customer = Customer.objects.create(
            tenant=other_tenant,
            name='Other Fleet',
        )
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=other_customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        other_tech_user = User.objects.create_user(
            username='othertech223',
            email='othertech223@example.com',
            password='otpass',
        )
        other_tech = Technician.objects.create(
            tenant=other_tenant,
            user=other_tech_user,
            is_active=True,
        )
        other_repair = Repair.objects.create(
            tenant=other_tenant,
            customer=other_customer,
            technician=other_tech,
            unit_number='999',
            damage_type='chip',
            queue_status='PENDING',
            cost=50.00,
        )
        response = self.client.post(
            f'/app/repairs/{other_repair.id}/approve/',
            {'notes': 'cross-tenant attempt'},
        )
        other_repair.refresh_from_db()
        # Status must not change — 404 or redirect
        self.assertEqual(other_repair.queue_status, 'PENDING')
