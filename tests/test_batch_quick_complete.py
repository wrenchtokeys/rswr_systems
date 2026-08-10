"""
Multi-break batch quick-complete ("Work is already done").

The multi-break form now has a mark_completed checkbox (default checked,
matching the quick job form's already_completed). The view completes each
break via job_flow.complete_job() — the second-save pattern that fires the
completion side effects exactly once — and never creates rows as COMPLETED.
Breaks that land PENDING (customers who require approval) are skipped with
a warning instead of silently bypassing the approval step.

Also regression-covers the batch_detail per-break status buttons: "Start
This Break" used to post name="new_status" which update_queue_status ignores
(it reads "status"), making the button a silent no-op.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.customer_portal.models import CustomerRepairPreference
from apps.technician_portal.models import Repair, Technician, UnitRepairCount
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class BatchQuickCompleteBase(TestCase):
    suffix = ''

    def setUp(self):
        s = self.suffix
        owner = User.objects.create_user(
            f'bqowner{s}', f'bqowner{s}@test.com', 'TestPass123!',
            first_name='Owner', last_name='Test',
        )
        self.tenant = Tenant.objects.create(
            name=f'BatchQC Shop{s}', slug=f'batchqc{s}', subdomain=f'batchqc{s}',
            owner=owner, plan='trial', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(user=owner, tenant=self.tenant, role='owner', is_active=True)

        self.tech_user = User.objects.create_user(f'bqtech{s}', f'bqtech{s}@test.com', 'TestPass123!')
        self.technician = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True, can_repair=True,
        )
        TenantMembership.objects.create(
            user=self.tech_user, tenant=self.tenant, role='technician', is_active=True,
        )
        group, _ = Group.objects.get_or_create(name='Technicians')
        self.tech_user.groups.add(group)

        self.customer = Customer.objects.create(
            tenant=self.tenant, name=f'BQ Fleet{s}', customer_type='FLEET',
        )

        self.client = Client()
        self.client.force_login(self.tech_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_batch(self, breaks=2, unit='BQ-1', mark_completed=True):
        data = {
            'customer': self.customer.id,
            'unit_number': unit,
            'repair_date': timezone.now().isoformat(),
            'breaks_count': breaks,
        }
        if mark_completed:
            data['mark_completed'] = '1'
        for i in range(breaks):
            data[f'breaks[{i}][damage_type]'] = 'Chip'
        return self.client.post(reverse('create_multi_break_repair'), data)


class MarkCompletedTests(BatchQuickCompleteBase):
    suffix = '_mc'

    def test_mark_completed_completes_all_breaks(self):
        resp = self._post_batch(breaks=3, unit='BQ-DONE')
        self.assertEqual(resp.status_code, 302)

        repairs = Repair.objects.filter(tenant=self.tenant, unit_number='BQ-DONE')
        self.assertEqual(repairs.count(), 3)
        for r in repairs:
            self.assertEqual(r.queue_status, 'COMPLETED')

        # Completion side effects fired once per break (unit counter)
        counter = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number='BQ-DONE',
        )
        self.assertEqual(counter.repair_count, 3)

    def test_without_mark_completed_stays_approved(self):
        resp = self._post_batch(breaks=2, unit='BQ-OPEN', mark_completed=False)
        self.assertEqual(resp.status_code, 302)
        repairs = Repair.objects.filter(tenant=self.tenant, unit_number='BQ-OPEN')
        self.assertEqual(repairs.count(), 2)
        for r in repairs:
            self.assertEqual(r.queue_status, 'APPROVED')

    def test_approval_required_customer_stays_pending(self):
        CustomerRepairPreference.objects.create(
            customer=self.customer, field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        resp = self._post_batch(breaks=2, unit='BQ-PEND')
        self.assertEqual(resp.status_code, 302)
        repairs = Repair.objects.filter(tenant=self.tenant, unit_number='BQ-PEND')
        self.assertEqual(repairs.count(), 2)
        for r in repairs:
            self.assertEqual(r.queue_status, 'PENDING')


class BatchDetailBreakButtonsTests(BatchQuickCompleteBase):
    """The per-break Start/Complete buttons post status transitions that stick."""

    suffix = '_btn'

    def _make_batch(self):
        self._post_batch(breaks=2, unit='BQ-BTN', mark_completed=False)
        return list(Repair.objects.filter(tenant=self.tenant, unit_number='BQ-BTN'))

    def test_start_this_break_posts_status(self):
        repairs = self._make_batch()
        repair = repairs[0]
        self.assertEqual(repair.queue_status, 'APPROVED')
        resp = self.client.post(
            reverse('update_queue_status', args=[repair.id]),
            {'status': 'IN_PROGRESS'},
        )
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'IN_PROGRESS')

    def test_complete_this_break_posts_status(self):
        repairs = self._make_batch()
        repair = repairs[0]
        self.client.post(reverse('update_queue_status', args=[repair.id]), {'status': 'IN_PROGRESS'})
        resp = self.client.post(
            reverse('update_queue_status', args=[repair.id]),
            {'status': 'COMPLETED'},
        )
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'COMPLETED')

    def test_batch_detail_template_posts_correct_field_name(self):
        """The template's hidden inputs must use name="status" — a form posting
        name="new_status" is silently ignored by update_queue_status."""
        repairs = self._make_batch()
        Repair.objects.filter(pk=repairs[0].pk).update(queue_status='APPROVED')
        resp = self.client.get(
            reverse('technician_batch_detail', args=[str(repairs[0].repair_batch_id)])
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('name="new_status"', content)
