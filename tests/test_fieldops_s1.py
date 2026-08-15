"""
Fieldops S1 — a real "booked time".

Covers the acceptance criteria in docs/strategy/FIELD_OPS_SESSIONS.md §S1:
`scheduled_for` (booking time) is a first-class nullable field on both job
types, distinct from `service_date` (when work happened); it can be set from
the quick job form (only when the job isn't already done) and the legacy
per-type forms; and the tech dashboard queue groups into Overdue / Today /
Later / Unscheduled buckets — while an all-unscheduled queue behaves exactly
as before S1.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Repair, Replacement
from apps.technician_portal.forms import QuickJobForm, RepairForm
from apps.saas.forms import ReplacementForm
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_shop(business_name, email, services='both'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'),
            'trial_days': 30, 'display_order': 0, 'is_active': True,
        },
    )
    result = create_tenant_with_owner(
        business_name=business_name,
        email=email,
        password='testpass123!',
        first_name='Test',
        last_name='Owner',
        services_offered=services,
    )
    return result['user'], result['tenant']


def login(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


def local_input(dt):
    """Format an aware datetime the way a datetime-local input posts it."""
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


@override_settings(**TEST_SETTINGS)
class ScheduledFieldModelTests(TestCase):
    """The migration is additive: existing flows never touch the new fields."""

    def setUp(self):
        self.user, self.tenant = make_shop('S1 Model Shop', 's1model@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)

    def test_repair_defaults_unscheduled(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-1',
        )
        self.assertIsNone(repair.scheduled_for)
        self.assertIsNone(repair.scheduled_window_end)
        self.assertIsNotNone(repair.service_date)

    def test_replacement_defaults_unscheduled(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-2',
        )
        self.assertIsNone(repl.scheduled_for)
        self.assertIsNone(repl.scheduled_window_end)

    def test_scheduled_fields_persist(self):
        when = timezone.now() + timedelta(days=2)
        window_end = when + timedelta(hours=2)
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-3',
            scheduled_for=when, scheduled_window_end=window_end,
        )
        repair.refresh_from_db()
        self.assertEqual(repair.scheduled_for, when)
        self.assertEqual(repair.scheduled_window_end, window_end)


@override_settings(**TEST_SETTINGS)
class QuickJobScheduleTests(TestCase):
    """/tech/jobs/new/: booking only exists for work that hasn't happened."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S1 Quick Shop', 's1quick@test.com')
        self.customer = Customer.objects.create(
            name='Smith Trucking', tenant=self.tenant, email='smith@test.com',
        )
        login(self.client, self.user, self.tenant)

    def _post(self, **overrides):
        data = {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'T-100',
            'work_done': 'Windshield repair',
            'already_completed': 'on',
        }
        data.update(overrides)
        return self.client.post(reverse('job_create'), data)

    def test_schedule_set_when_not_already_done(self):
        when = timezone.now() + timedelta(days=1)
        resp = self._post(already_completed='', scheduled_for=local_input(when))
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertIsNotNone(repair.scheduled_for)
        self.assertEqual(
            timezone.localtime(repair.scheduled_for).strftime('%Y-%m-%dT%H:%M'),
            local_input(when),
        )
        self.assertNotEqual(repair.queue_status, 'COMPLETED')

    def test_already_done_drops_schedule(self):
        # A schedule typed before the "already done" box was re-checked must
        # not survive: completed walk-ins are history, not bookings.
        when = timezone.now() + timedelta(days=1)
        resp = self._post(scheduled_for=local_input(when))
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertIsNone(repair.scheduled_for)
        self.assertEqual(repair.queue_status, 'COMPLETED')

    def test_no_schedule_behaves_as_before(self):
        resp = self._post(already_completed='')
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertIsNone(repair.scheduled_for)

    def test_replacement_carries_schedule(self):
        when = timezone.now() + timedelta(days=3)
        resp = self._post(
            service_type='replacement', price='425.00',
            work_done='Windshield replacement',
            already_completed='', scheduled_for=local_input(when),
        )
        self.assertEqual(resp.status_code, 302)
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertIsNotNone(repl.scheduled_for)

    def test_form_renders_schedule_field(self):
        resp = self.client.get(reverse('job_create'))
        self.assertContains(resp, 'schedule-row')
        self.assertContains(resp, 'name="scheduled_for"')


@override_settings(**TEST_SETTINGS)
class LegacyFormScheduleTests(TestCase):
    """The per-type edit forms can set and clear the booking time."""

    def setUp(self):
        self.user, self.tenant = make_shop('S1 Legacy Shop', 's1legacy@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.tech.can_replace = True
        self.tech.save()
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)

    def test_repair_form_sets_scheduled_for(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-9',
        )
        when = timezone.now() + timedelta(days=1)
        form = RepairForm(
            data={
                'customer': self.customer.id,
                'technician': self.tech.id,
                'unit_number': 'T-9',
                'repair_date': local_input(repair.service_date),
                'queue_status': repair.queue_status,
                'scheduled_for': local_input(when),
            },
            instance=repair, user=self.user, tenant=self.tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertIsNotNone(saved.scheduled_for)

    def test_replacement_form_sets_scheduled_for(self):
        when = timezone.now() + timedelta(days=1)
        form = ReplacementForm(
            data={
                'customer': self.customer.id,
                'technician': self.tech.id,
                'unit_number': 'T-10',
                'scheduled_for': local_input(when),
                'parts_cost': '200.00',
                'labor_cost': '150.00',
            },
            tenant=self.tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)
        repl = form.save(commit=False)
        repl.tenant = self.tenant
        repl.save()
        self.assertIsNotNone(repl.scheduled_for)

    def test_quick_form_clean_drops_schedule_when_done(self):
        when = timezone.now() + timedelta(days=1)
        form = QuickJobForm(
            data={
                'service_type': 'repair',
                'customer': self.customer.id,
                'already_completed': 'on',
                'scheduled_for': local_input(when),
            },
            tenant=self.tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['scheduled_for'])


@override_settings(**TEST_SETTINGS)
class DashboardBucketTests(TestCase):
    """The queue groups by booking time; unscheduled queues are untouched."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S1 Bucket Shop', 's1bucket@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        login(self.client, self.user, self.tenant)
        self.now = timezone.now()

    def _repair(self, status='APPROVED', scheduled_for=None, unit='T-1'):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=unit, queue_status=status, scheduled_for=scheduled_for,
        )

    def _get_queue(self):
        resp = self.client.get(reverse('technician_dashboard'))
        self.assertEqual(resp.status_code, 200)
        return resp, list(resp.context['todays_queue'])

    def test_buckets_order_and_labels(self):
        overdue = self._repair(scheduled_for=self.now - timedelta(days=1), unit='OV')
        today = self._repair(scheduled_for=self.now, unit='TD')
        later = self._repair(scheduled_for=self.now + timedelta(days=1), unit='LT')
        unscheduled = self._repair(status='IN_PROGRESS', unit='UN')

        resp, queue = self._get_queue()
        self.assertTrue(resp.context['queue_has_schedule'])
        ids = [(j.id, j.schedule_bucket) for j in queue]
        self.assertEqual(ids, [
            (overdue.id, 'overdue'),
            (today.id, 'today'),
            (later.id, 'later'),
            (unscheduled.id, 'unscheduled'),
        ])
        self.assertContains(resp, 'Overdue')
        self.assertContains(resp, 'Unscheduled')

    def test_scheduled_bucket_sorts_by_time(self):
        second = self._repair(scheduled_for=self.now + timedelta(hours=3), unit='B')
        first = self._repair(scheduled_for=self.now + timedelta(hours=1), unit='A')
        _, queue = self._get_queue()
        self.assertEqual([j.id for j in queue], [first.id, second.id])

    def test_completed_scheduled_job_not_in_queue(self):
        done = self._repair(status='COMPLETED',
                            scheduled_for=self.now - timedelta(days=1))
        _, queue = self._get_queue()
        self.assertNotIn(done.id, [j.id for j in queue])

    def test_replacement_joins_buckets(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='R-1', queue_status='APPROVED',
            scheduled_for=self.now,
        )
        _, queue = self._get_queue()
        match = [j for j in queue if getattr(j, 'service_type', '') == 'replacement']
        self.assertEqual([j.id for j in match], [repl.id])
        self.assertEqual(match[0].schedule_bucket, 'today')

    def test_all_unscheduled_queue_unchanged(self):
        # No bookings anywhere → no headers, no reorder: exactly the pre-S1
        # status-priority queue.
        in_progress = self._repair(status='IN_PROGRESS', unit='A')
        approved = self._repair(status='APPROVED', unit='B')

        resp, queue = self._get_queue()
        self.assertFalse(resp.context['queue_has_schedule'])
        self.assertEqual([j.id for j in queue], [in_progress.id, approved.id])
        self.assertNotContains(resp, '>Unscheduled<')
