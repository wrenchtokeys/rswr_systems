"""
CODE-234: customer_replacement_approve and customer_replacement_deny lack
transaction atomicity and race-condition protection.

Bug: Both views wrote replacement.queue_status and saved without
@transaction.atomic or select_for_update(). A double-click race could create
duplicate TechnicianNotification records, or a concurrent approval and denial
could corrupt the status by overwriting each other.

Fix: Wrapped the write section in transaction.atomic() + select_for_update()
with an inner status re-check, mirroring the pattern added to repair
approve/deny in CODE-223.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.technician_portal.models import Technician, Replacement, TechnicianNotification
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership


class ReplacementApproveAtomicityTests(TestCase):
    """Verify customer_replacement_approve/deny are atomic and race-safe."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner234', email='owner234@example.com', password='ownerpass',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 234', slug='test-shop-234', is_active=True, owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True,
        )

        self.tech_user = User.objects.create_user(
            username='tech234', email='tech234@example.com', password='techpass',
        )
        self.technician = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True, can_repair=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.tech_user, role='technician', is_active=True,
        )

        self.cust_user = User.objects.create_user(
            username='cust234', email='cust234@example.com', password='custpass',
        )
        self.customer = Customer.objects.create(
            name='Test Customer 234', tenant=self.tenant,
        )
        # Explicitly require approval — shop-created work auto-approves by
        # default, and these tests exercise the PENDING approve/deny flow
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer, is_primary_contact=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.cust_user, role='viewer', is_active=True,
        )

        self.client = Client()
        self.client.login(username='cust234', password='custpass')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _make_replacement(self, status='PENDING'):
        return Replacement.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='UNIT-234',
            glass_position='WINDSHIELD',
            queue_status=status,
            service_date=timezone.now().date(),
        )

    # -------------------------------------------------------------------
    # APPROVE TESTS
    # -------------------------------------------------------------------

    def test_approve_pending_replacement_succeeds(self):
        """A PENDING replacement can be approved via POST."""
        replacement = self._make_replacement('PENDING')
        url = f'/app/replacements/{replacement.id}/approve/'
        resp = self.client.post(url, {'notes': 'Looks good'})
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'APPROVED')

    def test_approve_requested_replacement_refused(self):
        """A REQUESTED replacement must NOT be customer-approvable — the shop
        has to confirm the glass and price it first (cost is still $0)."""
        replacement = self._make_replacement('REQUESTED')
        url = f'/app/replacements/{replacement.id}/approve/'
        resp = self.client.post(url, {'notes': ''})
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'REQUESTED')

    def test_approve_completed_replacement_rejected(self):
        """A COMPLETED replacement cannot be re-approved (guard)."""
        replacement = self._make_replacement('COMPLETED')
        url = f'/app/replacements/{replacement.id}/approve/'
        resp = self.client.post(url, {'notes': ''})
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'COMPLETED')

    def test_approve_creates_technician_notification(self):
        """Approving a replacement creates a notification for the technician."""
        replacement = self._make_replacement('PENDING')
        url = f'/app/replacements/{replacement.id}/approve/'
        self.client.post(url, {'notes': ''})
        # Wording changed with the email/notification overhaul: the message
        # leads with the actor and drops the shouted status and the emoji.
        # What is under test is that exactly one is written, not the phrasing.
        notif = TechnicianNotification.objects.filter(
            technician=self.technician,
            message__contains=f'approved replacement #{replacement.id}',
        )
        self.assertEqual(notif.count(), 1)

    def test_approve_race_already_processed(self):
        """If the replacement is concurrently changed to APPROVED before the
        lock is acquired, the view should detect it and show a warning."""
        replacement = self._make_replacement('PENDING')
        url = f'/app/replacements/{replacement.id}/approve/'

        # Simulate concurrent approval: change status between initial check and lock
        Replacement.objects.filter(pk=replacement.pk).update(queue_status='APPROVED')

        resp = self.client.post(url, {'notes': ''}, follow=True)
        # Should redirect with a warning about already processed
        self.assertEqual(resp.status_code, 200)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'APPROVED')
        # No duplicate notification
        notif_count = TechnicianNotification.objects.filter(
            technician=self.technician,
            message__contains=f'Replacement #{replacement.id}',
        ).count()
        self.assertEqual(notif_count, 0)

    # -------------------------------------------------------------------
    # DENY TESTS
    # -------------------------------------------------------------------

    def test_deny_pending_replacement_succeeds(self):
        """A PENDING replacement can be denied via POST."""
        replacement = self._make_replacement('PENDING')
        url = f'/app/replacements/{replacement.id}/deny/'
        resp = self.client.post(url, {'reason': 'Not needed'})
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'DENIED')

    def test_deny_requested_replacement_refused(self):
        """A REQUESTED replacement must NOT be customer-deniable — it hasn't
        entered the approval flow yet."""
        replacement = self._make_replacement('REQUESTED')
        url = f'/app/replacements/{replacement.id}/deny/'
        resp = self.client.post(url, {'reason': ''})
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'REQUESTED')

    def test_deny_completed_replacement_rejected(self):
        """A COMPLETED replacement cannot be denied (guard)."""
        replacement = self._make_replacement('COMPLETED')
        url = f'/app/replacements/{replacement.id}/deny/'
        resp = self.client.post(url, {'reason': 'Nope'})
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'COMPLETED')

    def test_deny_creates_technician_notification_with_reason(self):
        """Denying a replacement creates a notification that includes the reason."""
        replacement = self._make_replacement('PENDING')
        url = f'/app/replacements/{replacement.id}/deny/'
        self.client.post(url, {'reason': 'Too expensive'})
        notif = TechnicianNotification.objects.filter(
            technician=self.technician,
            message__contains=f'declined replacement #{replacement.id}',
        )
        self.assertEqual(notif.count(), 1)
        self.assertIn('Too expensive', notif.first().message)

    def test_deny_race_already_processed(self):
        """If the replacement is concurrently denied before lock, the view detects it."""
        replacement = self._make_replacement('PENDING')
        url = f'/app/replacements/{replacement.id}/deny/'

        # Simulate concurrent denial
        Replacement.objects.filter(pk=replacement.pk).update(queue_status='DENIED')

        resp = self.client.post(url, {'reason': 'late'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'DENIED')
        # No notification from this request
        notif_count = TechnicianNotification.objects.filter(
            technician=self.technician,
            message__contains=f'Replacement #{replacement.id}',
        ).count()
        self.assertEqual(notif_count, 0)

    # -------------------------------------------------------------------
    # CROSS-TENANT ISOLATION
    # -------------------------------------------------------------------

    def test_approve_cross_tenant_replacement_404(self):
        """Cannot approve a replacement belonging to another tenant."""
        other_owner = User.objects.create_user(
            username='other_owner234', email='other234@example.com', password='pass',
        )
        other_tenant = Tenant.objects.create(
            name='Other Shop', slug='other-shop-234', is_active=True, owner=other_owner,
        )
        other_customer = Customer.objects.create(name='Other Cust', tenant=other_tenant)
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=other_customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        other_tech_user = User.objects.create_user(
            username='other_tech234', email='othertech234@example.com', password='pass',
        )
        other_tech = Technician.objects.create(
            user=other_tech_user, tenant=other_tenant, is_active=True, can_repair=True,
        )
        other_replacement = Replacement.objects.create(
            tenant=other_tenant,
            technician=other_tech,
            customer=other_customer,
            unit_number='OTHER-1',
            glass_position='WINDSHIELD',
            queue_status='PENDING',
            service_date=timezone.now().date(),
        )
        url = f'/app/replacements/{other_replacement.id}/approve/'
        resp = self.client.post(url, {'notes': ''})
        self.assertEqual(resp.status_code, 404)
        other_replacement.refresh_from_db()
        self.assertEqual(other_replacement.queue_status, 'PENDING')
