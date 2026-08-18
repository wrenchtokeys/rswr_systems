"""
Customer repair requests auto-accept.

Customer-submitted REPAIR requests are priced from the shop's price book, so
there is nothing for the shop to review before work can begin: they are
created as REQUESTED (create-time signals fire: customer confirmation + shop
notice) and immediately second-saved to APPROVED with the customer-initiated
RepairApproval breadcrumb. Replacements keep the review flow — the shop must
confirm the glass and price them before the customer approves.

Also covers the PENDING-only tightening of every customer approve/deny
endpoint: a customer must never approve or deny their own REQUESTED
submission (for replacements that would lock in a $0 job).
"""
import json
import uuid
from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.customer_portal.models import CustomerUser, RepairApproval
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer, Notification

BREADCRUMB_NOTES = "Auto-approved as customer initiated the request"


class CustomerPortalTestBase(TestCase):
    """Tenant + tech + portal-logged-in customer."""

    suffix = ''

    def setUp(self):
        s = self.suffix
        owner = User.objects.create_user(
            f'owner{s}', f'owner{s}@test.com', 'TestPass123!',
            first_name='Owner', last_name='Test',
        )
        self.tenant = Tenant.objects.create(
            name=f'AutoAccept Shop{s}', slug=f'autoaccept{s}',
            subdomain=f'autoaccept{s}', owner=owner,
            plan='trial', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(user=owner, tenant=self.tenant, role='owner', is_active=True)

        tech_user = User.objects.create_user(f'tech{s}', f'tech{s}@test.com', 'TestPass123!')
        self.tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True, can_repair=True,
        )
        TenantMembership.objects.create(user=tech_user, tenant=self.tenant, role='technician', is_active=True)
        Group.objects.get_or_create(name='Technicians')

        self.customer = Customer.objects.create(
            tenant=self.tenant, name=f'Fleet{s}', customer_type='FLEET',
        )
        self.cust_user = User.objects.create_user(f'cust{s}', f'cust{s}@test.com', 'TestPass123!')
        self.cu = CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer, is_primary_contact=True,
        )

        self.client = Client()
        self.client.force_login(self.cust_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()


class SingleRequestAutoAcceptTests(CustomerPortalTestBase):
    suffix = '_single'

    def test_single_repair_request_lands_approved(self):
        resp = self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-1',
            'damage_type': 'Chip',
            'description': 'Rock chip on windshield',
        })
        self.assertEqual(resp.status_code, 302)

        repair = Repair.objects.get(tenant=self.tenant, unit_number='UNIT-1')
        self.assertEqual(repair.queue_status, 'APPROVED')
        self.assertIsNotNone(repair.technician)

        approval = RepairApproval.objects.get(repair=repair)
        self.assertTrue(approval.approved)
        self.assertEqual(approval.approved_by, self.cu)
        self.assertEqual(approval.notes, BREADCRUMB_NOTES)

    def test_detail_page_shows_accepted_not_approve_deny(self):
        self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-2', 'damage_type': 'Chip', 'description': 'x',
        })
        repair = Repair.objects.get(tenant=self.tenant, unit_number='UNIT-2')
        resp = self.client.get(reverse('customer_repair_detail', args=[repair.id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # The point of this test is that an auto-accepted request offers the
        # customer nothing to approve. Fieldops S4 corrected what it says
        # instead: this badge read "Scheduled for Repair" while scheduled_for
        # was null, and it is the claim that outlives the submit toast.
        self.assertIn('Accepted', content)
        self.assertNotIn('Scheduled for Repair', content)
        self.assertNotIn('needs your approval', content)

    def test_submission_notifies_customer_received(self):
        self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-3', 'damage_type': 'Chip', 'description': 'x',
        })
        # Create-time signal fired before the auto-accept second save
        self.assertTrue(
            Notification.objects.filter(
                template__name='repair_request_received',
            ).exists()
        )


class BatchRequestAutoAcceptTests(CustomerPortalTestBase):
    suffix = '_batch'

    def test_batch_request_all_approved_with_breadcrumbs(self):
        units = [
            {'unitNumber': 'B-1', 'damageType': 'Chip', 'notes': ''},
            {'unitNumber': 'B-2', 'damageType': 'Crack', 'notes': '',
             'hasMultipleBreaks': True, 'breakCount': 2},
        ]
        # Test client posts multipart/form-data, so the handler takes the
        # AJAX path and returns JSON rather than redirecting.
        resp = self.client.post(reverse('customer_request_repair'), {
            'batch_submission': 'true',
            'units_data': json.dumps(units),
        })
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['success'])
        # Fieldops S4 corrected this claim: auto-accepted is not booked.
        # Nothing in the request path writes scheduled_for, so "you're on the
        # schedule" promised a time the shop had not picked.
        self.assertNotIn("you're on the schedule", payload['message'])
        self.assertIn('confirm your time', payload['message'])

        repairs = Repair.objects.filter(tenant=self.tenant, customer=self.customer)
        self.assertEqual(repairs.count(), 3)  # 1 + 2 breaks
        for r in repairs:
            self.assertEqual(r.queue_status, 'APPROVED')
            approval = RepairApproval.objects.get(repair=r)
            self.assertEqual(approval.notes, BREADCRUMB_NOTES)


class ReplacementStaysRequestedTests(CustomerPortalTestBase):
    suffix = '_repl'

    def _request_replacement(self):
        resp = self.client.post(reverse('customer_request_replacement'), {
            'unit_number': 'R-1',
            'glass_position': 'WINDSHIELD',
            'description': 'Shattered',
        })
        self.assertEqual(resp.status_code, 302)
        return Replacement.objects.get(tenant=self.tenant, customer=self.customer)

    def test_replacement_request_stays_requested(self):
        replacement = self._request_replacement()
        self.assertEqual(replacement.queue_status, 'REQUESTED')

    def test_requested_replacement_detail_has_no_approve_deny(self):
        replacement = self._request_replacement()
        resp = self.client.get(
            reverse('customer_replacement_detail', args=[replacement.id])
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Request Submitted', content)
        self.assertIn('Pricing pending', content)
        self.assertNotIn('Action Required', content)
        self.assertNotIn(
            reverse('customer_replacement_approve', args=[replacement.id]), content
        )

    def test_requested_replacement_approve_refused(self):
        replacement = self._request_replacement()
        resp = self.client.post(
            reverse('customer_replacement_approve', args=[replacement.id]),
            {'notes': ''},
        )
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'REQUESTED')
        self.assertEqual(replacement.cost, 0)

    def test_requested_replacement_deny_refused(self):
        replacement = self._request_replacement()
        resp = self.client.post(
            reverse('customer_replacement_deny', args=[replacement.id]),
            {'reason': ''},
        )
        self.assertEqual(resp.status_code, 302)
        replacement.refresh_from_db()
        self.assertEqual(replacement.queue_status, 'REQUESTED')


class RequestedRefusalMatrixTests(CustomerPortalTestBase):
    """Every customer approve/deny path refuses REQUESTED repairs."""

    suffix = '_matrix'

    def _make_requested_repair(self, unit='M-1', **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number=unit, damage_type='Chip', queue_status='REQUESTED',
            service_date=date.today(), **kwargs,
        )

    def test_single_approve_refused(self):
        repair = self._make_requested_repair()
        self.client.post(reverse('customer_repair_approve', args=[repair.id]), {'notes': ''})
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'REQUESTED')

    def test_single_deny_refused(self):
        repair = self._make_requested_repair()
        self.client.post(reverse('customer_repair_deny', args=[repair.id]), {'reason': ''})
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'REQUESTED')

    def test_batch_approve_refused(self):
        batch_id = uuid.uuid4()
        repairs = [
            self._make_requested_repair(
                unit='M-B', repair_batch_id=batch_id,
                break_number=i + 1, total_breaks_in_batch=2,
            )
            for i in range(2)
        ]
        self.client.post(
            reverse('customer_batch_approve', args=[str(batch_id)]), {'notes': ''}
        )
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'REQUESTED')

    def test_bulk_action_approve_refused(self):
        repair = self._make_requested_repair()
        self.client.post(reverse('customer_bulk_action'), {
            'action': 'approve', 'repair_ids': [repair.id],
        })
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'REQUESTED')
