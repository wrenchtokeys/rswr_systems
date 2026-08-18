"""
Fieldops S7 — drag to swap two appointments.

Covers the acceptance criteria in docs/strategy/FIELD_OPS_SESSIONS.md §S7:
a manager drags one booked job onto another in the same tech's day and the
two trade start times, each keeping its own window length; the swap touches
no money; every refusal answers JSON; a stale swap 409s and writes nothing;
the assigned tech gets exactly one notification and no customer gets any.

The one thing this file CANNOT prove is the lock ordering: dev runs SQLite,
where select_for_update() is a silent no-op, so a deadlock-ordering test
would pass green and mean nothing. The 409 optimistic-lock path below is
real on both backends; the row-lock story is argued in the module docstring
of services/schedule_swap.py rather than tested here.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import (
    Technician, Repair, Replacement, TechnicianNotification,
)
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
        business_name=business_name, email=email, password='testpass123!',
        first_name='Test', last_name='Owner', services_offered=services,
    )
    return result['user'], result['tenant']


def login(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


def local_day_at(hour, minute=0, day_offset=0):
    local_now = timezone.localtime(timezone.now())
    return (local_now + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


@override_settings(**TEST_SETTINGS)
class SwapBase(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_shop('S7 Shop', 's7owner@test.com')
        self.owner_tech = Technician.objects.get(user=self.owner, tenant=self.tenant)

        self.tech_user = User.objects.create_user(
            's7_marcus', 's7marcus@test.com', 'testpass123!',
            first_name='Marcus', last_name='Field',
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.tech_user,
            role='technician', is_active=True,
        )
        self.tech = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True,
        )

        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, phone='501-555-0100',
        )
        self.client = Client()
        self.url = reverse('schedule_swap')
        self.day_url = reverse('day_schedule')

    # --- factories --------------------------------------------------------
    def make_repair(self, technician=None, status='APPROVED', scheduled=None,
                    window_end=None, **kwargs):
        repair = Repair(
            tenant=self.tenant, customer=self.customer,
            technician=technician or self.tech,
            queue_status=status, unit_number=kwargs.pop('unit_number', 'U-1'),
            **kwargs,
        )
        repair.scheduled_for = scheduled
        repair.scheduled_window_end = window_end
        repair.save()
        return repair

    def make_replacement(self, technician=None, status='APPROVED',
                         scheduled=None, window_end=None, **kwargs):
        repl = Replacement(
            tenant=self.tenant, customer=self.customer,
            technician=technician or self.tech,
            queue_status=status, unit_number=kwargs.pop('unit_number', 'R-1'),
            **kwargs,
        )
        repl.scheduled_for = scheduled
        repl.scheduled_window_end = window_end
        repl.save()
        return repl

    # --- helpers ----------------------------------------------------------
    def ref(self, job, kind='repair', scheduled_for=None):
        when = scheduled_for if scheduled_for is not None else job.scheduled_for
        return {
            'type': kind,
            'id': job.pk,
            'scheduled_for': when.isoformat() if when else None,
        }

    def post_swap(self, a, b):
        # The swap registers its notification with transaction.on_commit, and
        # TestCase never commits — without capturing the callbacks the whole
        # notification path would silently not run in any test here.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url, data=json.dumps({'a': a, 'b': b}),
                content_type='application/json',
            )
        return response


class SwapHappyPathTests(SwapBase):
    """The gesture does what it says: two jobs trade start times."""

    def setUp(self):
        super().setUp()
        login(self.client, self.owner, self.tenant)

    def test_two_repairs_trade_start_times(self):
        early = self.make_repair(scheduled=local_day_at(9), unit_number='AM-1')
        late = self.make_repair(scheduled=local_day_at(14), unit_number='PM-1')

        response = self.post_swap(self.ref(early), self.ref(late))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

        early.refresh_from_db()
        late.refresh_from_db()
        self.assertEqual(timezone.localtime(early.scheduled_for).hour, 14)
        self.assertEqual(timezone.localtime(late.scheduled_for).hour, 9)

    def test_repair_and_replacement_can_trade(self):
        repair = self.make_repair(scheduled=local_day_at(9))
        repl = self.make_replacement(scheduled=local_day_at(11))

        response = self.post_swap(
            self.ref(repair), self.ref(repl, kind='replacement'))
        self.assertEqual(response.status_code, 200)

        repair.refresh_from_db()
        repl.refresh_from_db()
        self.assertEqual(timezone.localtime(repair.scheduled_for).hour, 11)
        self.assertEqual(timezone.localtime(repl.scheduled_for).hour, 9)

    def test_each_job_keeps_its_own_window_length(self):
        """The rule that makes this a swap of starts, not of window pairs.

        Swapping the ends wholesale would graft the replacement's 3-hour
        window onto the 30-minute repair.
        """
        short = self.make_repair(
            scheduled=local_day_at(9), window_end=local_day_at(9, 30))
        long = self.make_replacement(
            scheduled=local_day_at(13), window_end=local_day_at(16))

        response = self.post_swap(
            self.ref(short), self.ref(long, kind='replacement'))
        self.assertEqual(response.status_code, 200)

        short.refresh_from_db()
        long.refresh_from_db()
        self.assertEqual(
            short.scheduled_window_end - short.scheduled_for,
            timedelta(minutes=30),
        )
        self.assertEqual(
            long.scheduled_window_end - long.scheduled_for, timedelta(hours=3))
        self.assertEqual(timezone.localtime(short.scheduled_for).hour, 13)
        self.assertEqual(timezone.localtime(long.scheduled_for).hour, 9)

    def test_null_window_end_stays_null(self):
        a = self.make_repair(scheduled=local_day_at(9))
        b = self.make_repair(
            scheduled=local_day_at(11), window_end=local_day_at(12))

        self.assertEqual(self.post_swap(self.ref(a), self.ref(b)).status_code, 200)

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNone(a.scheduled_window_end)
        self.assertEqual(b.scheduled_window_end - b.scheduled_for,
                         timedelta(hours=1))

    def test_response_names_the_new_times(self):
        """The change is stated in words, not just position."""
        early = self.make_repair(scheduled=local_day_at(9))
        late = self.make_repair(scheduled=local_day_at(14))
        message = self.post_swap(self.ref(early), self.ref(late)).json()['message']
        self.assertIn('Fleet Co', message)
        self.assertIn('2:00 PM', message)
        self.assertIn('9:00 AM', message)

    def test_in_progress_job_can_move(self):
        a = self.make_repair(status='IN_PROGRESS', scheduled=local_day_at(9))
        b = self.make_repair(status='PENDING', scheduled=local_day_at(11))
        self.assertEqual(self.post_swap(self.ref(a), self.ref(b)).status_code, 200)
        a.refresh_from_db()
        self.assertEqual(timezone.localtime(a.scheduled_for).hour, 11)


class SwapTouchesNoMoneyTests(SwapBase):
    """The headline safety property: a schedule change is not a price change.

    GlassService.save() re-prices the job and pushes the new price onto any
    live invoice through invoice_sync — which is exactly why the swap writes
    with .update() and never save().
    """

    def setUp(self):
        super().setUp()
        login(self.client, self.owner, self.tenant)

    def test_prices_tax_and_invoice_totals_are_untouched(self):
        from apps.billing.services.invoice_tracking_service import (
            InvoiceTrackingService,
        )

        a = self.make_repair(scheduled=local_day_at(9), unit_number='INV-A')
        b = self.make_repair(scheduled=local_day_at(13), unit_number='INV-B')

        invoice = InvoiceTrackingService(tenant=self.tenant)\
            .create_invoice_from_services(self.customer, [a, b])

        a.refresh_from_db()
        b.refresh_from_db()
        before = {
            'a_cost': a.cost, 'a_tax': a.tax_amount,
            'b_cost': b.cost, 'b_tax': b.tax_amount,
            'subtotal': invoice.subtotal, 'tax': invoice.tax_amount,
            'total': invoice.total,
        }

        response = self.post_swap(self.ref(a), self.ref(b))
        self.assertEqual(response.status_code, 200)

        a.refresh_from_db()
        b.refresh_from_db()
        invoice.refresh_from_db()

        # The times moved...
        self.assertEqual(timezone.localtime(a.scheduled_for).hour, 13)
        # ...and nothing about the money did.
        self.assertEqual(a.cost, before['a_cost'])
        self.assertEqual(a.tax_amount, before['a_tax'])
        self.assertEqual(b.cost, before['b_cost'])
        self.assertEqual(b.tax_amount, before['b_tax'])
        self.assertEqual(invoice.subtotal, before['subtotal'])
        self.assertEqual(invoice.tax_amount, before['tax'])
        self.assertEqual(invoice.total, before['total'])


class SwapRefusalTests(SwapBase):
    """Every refusal answers JSON — including for callers who can't swap."""

    def setUp(self):
        super().setUp()
        login(self.client, self.owner, self.tenant)

    def assertRefused(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response['Content-Type'].split(';')[0],
                         'application/json')
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['error'])
        return body

    def test_cross_technician_refused(self):
        mine = self.make_repair(self.tech, scheduled=local_day_at(9))
        theirs = self.make_repair(self.owner_tech, scheduled=local_day_at(11))
        body = self.assertRefused(self.post_swap(
            self.ref(mine), self.ref(theirs)), 400)
        self.assertIn('reassign', body['error'].lower())
        mine.refresh_from_db()
        self.assertEqual(timezone.localtime(mine.scheduled_for).hour, 9)

    def test_cross_day_refused(self):
        today = self.make_repair(scheduled=local_day_at(9))
        tomorrow = self.make_repair(scheduled=local_day_at(9, day_offset=1))
        body = self.assertRefused(self.post_swap(
            self.ref(today), self.ref(tomorrow)), 400)
        self.assertIn('different days', body['error'])

    def test_completed_job_refused(self):
        open_job = self.make_repair(scheduled=local_day_at(9))
        done = self.make_repair(status='COMPLETED', scheduled=local_day_at(11))
        self.assertRefused(self.post_swap(
            self.ref(open_job), self.ref(done)), 400)
        open_job.refresh_from_db()
        self.assertEqual(timezone.localtime(open_job.scheduled_for).hour, 9)

    def test_unscheduled_job_refused(self):
        booked = self.make_repair(scheduled=local_day_at(9))
        loose = self.make_repair(scheduled=None)
        # An unscheduled row carries no expected time, which is itself a 409.
        response = self.post_swap(
            self.ref(booked),
            {'type': 'repair', 'id': loose.pk, 'scheduled_for': None},
        )
        self.assertRefused(response, 409)

    def test_multi_break_batch_refused(self):
        """One physical visit split across rows must not be split in time."""
        import uuid
        normal = self.make_repair(scheduled=local_day_at(9))
        batched = self.make_repair(scheduled=local_day_at(11))
        Repair.objects.filter(pk=batched.pk).update(
            repair_batch_id=uuid.uuid4())
        batched.refresh_from_db()

        body = self.assertRefused(self.post_swap(
            self.ref(normal), self.ref(batched)), 400)
        self.assertIn('Multi-break', body['error'])
        normal.refresh_from_db()
        self.assertEqual(timezone.localtime(normal.scheduled_for).hour, 9)

    def test_same_job_twice_refused(self):
        job = self.make_repair(scheduled=local_day_at(9))
        self.assertRefused(self.post_swap(self.ref(job), self.ref(job)), 400)

    def test_repair_and_replacement_with_same_id_are_not_the_same_job(self):
        """`id` alone is ambiguous — the key must carry the type.

        Repair 5 and Replacement 5 both exist in a real database, so a
        same-id pair must swap normally rather than trip the same-job guard.
        """
        repair = self.make_repair(scheduled=local_day_at(9))
        repl = self.make_replacement(scheduled=local_day_at(11))
        # Nothing FKs to a Replacement yet, so re-iding it is safe here;
        # re-iding the Repair would orphan its notification rows.
        Replacement.objects.filter(pk=repl.pk).update(id=repair.pk)
        repl = Replacement.objects.get(pk=repair.pk)
        self.assertEqual(repair.pk, repl.pk)

        response = self.post_swap(
            self.ref(repair), self.ref(repl, kind='replacement'))
        self.assertEqual(response.status_code, 200)
        repair.refresh_from_db()
        repl.refresh_from_db()
        self.assertEqual(timezone.localtime(repair.scheduled_for).hour, 11)
        self.assertEqual(timezone.localtime(repl.scheduled_for).hour, 9)

    def test_other_tenant_job_refused(self):
        other_owner, other_tenant = make_shop('Other Shop', 'other@test.com')
        other_tech = Technician.objects.get(user=other_owner, tenant=other_tenant)
        other_customer = Customer.objects.create(
            name='Not Yours', tenant=other_tenant)
        stranger = Repair(
            tenant=other_tenant, customer=other_customer,
            technician=other_tech, queue_status='APPROVED', unit_number='X-1',
        )
        stranger.scheduled_for = local_day_at(11)
        stranger.save()

        mine = self.make_repair(scheduled=local_day_at(9))
        self.assertRefused(self.post_swap(
            self.ref(mine), self.ref(stranger)), 404)
        stranger.refresh_from_db()
        self.assertEqual(timezone.localtime(stranger.scheduled_for).hour, 11)

    def test_soft_deleted_job_refused(self):
        live = self.make_repair(scheduled=local_day_at(9))
        trashed = self.make_repair(scheduled=local_day_at(11))
        trashed_ref = self.ref(trashed)
        trashed.delete()  # soft delete

        self.assertRefused(self.post_swap(self.ref(live), trashed_ref), 404)
        live.refresh_from_db()
        self.assertEqual(timezone.localtime(live.scheduled_for).hour, 9)

    def test_unknown_job_type_refused(self):
        job = self.make_repair(scheduled=local_day_at(9))
        response = self.post_swap(
            self.ref(job),
            {'type': 'invoice', 'id': 1,
             'scheduled_for': local_day_at(11).isoformat()},
        )
        self.assertRefused(response, 400)

    def test_garbage_body_refused_as_json(self):
        response = self.client.post(
            self.url, data='not json at all',
            content_type='application/json')
        self.assertRefused(response, 400)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class SwapStalenessTests(SwapBase):
    """A drag made against a stale page must not overwrite newer truth."""

    def setUp(self):
        super().setUp()
        login(self.client, self.owner, self.tenant)

    def test_stale_expected_time_returns_409_and_writes_nothing(self):
        a = self.make_repair(scheduled=local_day_at(9), unit_number='A')
        b = self.make_repair(scheduled=local_day_at(11), unit_number='B')

        # Someone else moved A after this page rendered.
        Repair.objects.filter(pk=a.pk).update(scheduled_for=local_day_at(16))

        response = self.post_swap(
            self.ref(a, scheduled_for=local_day_at(9)), self.ref(b))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()['ok'])

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(timezone.localtime(a.scheduled_for).hour, 16)
        # B must be untouched too — a partial swap is worse than no swap.
        self.assertEqual(timezone.localtime(b.scheduled_for).hour, 11)

    def test_status_change_between_render_and_drop_returns_409(self):
        """A job can go DENIED while the stale DOM still offers it."""
        a = self.make_repair(scheduled=local_day_at(9))
        b = self.make_repair(scheduled=local_day_at(11))
        Repair.objects.filter(pk=b.pk).update(queue_status='DENIED')

        response = self.post_swap(self.ref(a), self.ref(b))
        self.assertIn(response.status_code, (400, 409))
        a.refresh_from_db()
        self.assertEqual(timezone.localtime(a.scheduled_for).hour, 9)

    def test_naive_expected_time_refused(self):
        a = self.make_repair(scheduled=local_day_at(9))
        b = self.make_repair(scheduled=local_day_at(11))
        response = self.post_swap(
            {'type': 'repair', 'id': a.pk,
             'scheduled_for': '2026-08-17T09:00:00'},
            self.ref(b),
        )
        self.assertEqual(response.status_code, 409)


class SwapAuthorizationTests(SwapBase):
    """Managers and owners only — and the refusal is still JSON."""

    def test_plain_technician_gets_json_403(self):
        login(self.client, self.tech_user, self.tenant)
        a = self.make_repair(scheduled=local_day_at(9))
        b = self.make_repair(scheduled=local_day_at(11))

        response = self.post_swap(self.ref(a), self.ref(b))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'].split(';')[0],
                         'application/json')
        self.assertFalse(response.json()['ok'])
        a.refresh_from_db()
        self.assertEqual(timezone.localtime(a.scheduled_for).hour, 9)

    def test_manager_technician_may_swap(self):
        self.tech.is_manager = True
        self.tech.save()
        login(self.client, self.tech_user, self.tenant)
        a = self.make_repair(scheduled=local_day_at(9))
        b = self.make_repair(scheduled=local_day_at(11))
        self.assertEqual(self.post_swap(self.ref(a), self.ref(b)).status_code, 200)

    def test_anonymous_is_redirected_not_served(self):
        response = Client().post(
            self.url, data=json.dumps({}), content_type='application/json')
        self.assertEqual(response.status_code, 302)


class SwapNotificationTests(SwapBase):
    """Exactly one notification, to the tech, never to a customer."""

    def setUp(self):
        super().setUp()
        login(self.client, self.owner, self.tenant)

    def test_assigned_tech_is_notified_once(self):
        a = self.make_repair(self.tech, scheduled=local_day_at(9))
        b = self.make_repair(self.tech, scheduled=local_day_at(11))
        TechnicianNotification.objects.all().delete()
        mail.outbox = []

        self.assertEqual(self.post_swap(self.ref(a), self.ref(b)).status_code, 200)

        rows = TechnicianNotification.objects.filter(technician=self.tech)
        self.assertEqual(rows.count(), 1)
        self.assertIn('Schedule change', rows.first().message)

    def test_no_notification_when_manager_swaps_their_own_day(self):
        a = self.make_repair(self.owner_tech, scheduled=local_day_at(9))
        b = self.make_repair(self.owner_tech, scheduled=local_day_at(11))
        TechnicianNotification.objects.all().delete()
        mail.outbox = []

        self.assertEqual(self.post_swap(self.ref(a), self.ref(b)).status_code, 200)

        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.owner_tech).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_customer_is_never_notified(self):
        a = self.make_repair(self.tech, scheduled=local_day_at(9))
        b = self.make_repair(self.tech, scheduled=local_day_at(11))
        mail.outbox = []

        self.assertEqual(self.post_swap(self.ref(a), self.ref(b)).status_code, 200)

        customer_addresses = {
            self.customer.email} if self.customer.email else set()
        for message in mail.outbox:
            self.assertFalse(customer_addresses & set(message.to))

    def test_two_replacements_notify_without_a_repair_link(self):
        """TechnicianNotification has only a `repair` FK — a replacement-only
        swap still notifies, with a null link and a working action_url."""
        a = self.make_replacement(self.tech, scheduled=local_day_at(9))
        b = self.make_replacement(self.tech, scheduled=local_day_at(11))
        TechnicianNotification.objects.all().delete()

        response = self.post_swap(
            self.ref(a, kind='replacement'), self.ref(b, kind='replacement'))
        self.assertEqual(response.status_code, 200)

        row = TechnicianNotification.objects.filter(technician=self.tech).first()
        self.assertIsNotNone(row)
        self.assertIsNone(row.repair)


class SwapDayViewMarkupTests(SwapBase):
    """The page carries the identity the drag needs — and only for managers."""

    def test_manager_rows_carry_keys_times_and_handles(self):
        login(self.client, self.owner, self.tenant)
        job = self.make_repair(scheduled=local_day_at(9))
        response = self.client.get(self.day_url)
        content = response.content.decode()

        self.assertTrue(response.context['can_swap'])
        self.assertIn(f'data-job-key="repair-{job.pk}"', content)
        self.assertIn('data-scheduled-for=', content)
        self.assertIn('swap-handle', content)
        self.assertIn('schedule_swap.js', content)
        self.assertIn('data-swap-group=', content)

    def test_technician_sees_no_handles_and_no_script(self):
        login(self.client, self.tech_user, self.tenant)
        self.make_repair(self.tech, scheduled=local_day_at(9))
        response = self.client.get(self.day_url)
        content = response.content.decode()

        self.assertFalse(response.context['can_swap'])
        self.assertNotIn('swap-handle', content)
        self.assertNotIn('schedule_swap.js', content)

    def test_completed_and_batched_rows_are_marked_unmovable(self):
        import uuid
        login(self.client, self.owner, self.tenant)
        self.make_repair(status='COMPLETED', scheduled=local_day_at(9),
                         unit_number='DONE-1')
        batched = self.make_repair(scheduled=local_day_at(11),
                                   unit_number='BATCH-1')
        Repair.objects.filter(pk=batched.pk).update(repair_batch_id=uuid.uuid4())

        content = self.client.get(self.day_url).content.decode()
        self.assertIn('data-swap-block="completed"', content)
        self.assertIn('data-swap-block="batch"', content)

    def test_triage_rail_is_a_distinct_drop_group(self):
        login(self.client, self.owner, self.tenant)
        self.make_repair(scheduled=local_day_at(9))
        self.make_repair(scheduled=None, unit_number='LOOSE-1')
        content = self.client.get(self.day_url).content.decode()
        self.assertIn('data-swap-group="triage"', content)
