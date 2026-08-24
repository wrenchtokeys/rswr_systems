"""
Fieldops S5 — the dispatch board.

Covers §S5 in docs/strategy/FIELD_OPS_SESSIONS.md: a manager takes a job off
the triage rail, names a technician and a time in one motion, the tech is
notified once, and the collisions that creates are visible on the board.

The board is the S3 day view with S5's *who* added beside S4's *when*, so
these tests exercise one endpoint (``schedule_dispatch``) that composes N1's
``assign_job`` with S4's ``confirm_appointment`` — plus the read-side conflict
signals, which write nothing and block nothing.

Inherited gotchas (S4/S7/N1), all of which bite here too:
- Notifications registered with ``transaction.on_commit`` do not run under
  ``TestCase``; every write POST goes through ``captureOnCommitCallbacks``.
- Creating a job emails the assigned tech (N1), so ``mail.outbox[0]`` is never
  safely "the message this test is about" — filter by subject.
"""

import json
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.technician_portal.models import (
    Repair, Replacement, Technician,
)
from apps.technician_portal.services.dispatch import (
    DispatchError, apply_dispatch, parse_dispatch_request,
)
from apps.technician_portal.services.schedule_conflicts import (
    annotate_conflicts, describe_missed_preference, technician_load,
)
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def tomorrow():
    return timezone.localtime(timezone.now()).date() + timedelta(days=1)


def at(day, hour, minute=0):
    """Aware datetime in the shop's clock — the same convention S1/S4 use."""
    return timezone.make_aware(
        datetime.combine(day, time(hour, minute)),
        timezone.get_current_timezone(),
    )


@override_settings(**TEST_SETTINGS)
class S5Base(TestCase):
    """One shop, an owner, a plain tech, and a working manager."""

    suffix = ''

    def setUp(self):
        s = self.suffix
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial', 'monthly_price': Decimal('0.00'),
                'trial_days': 30, 'display_order': 0, 'is_active': True,
            },
        )
        self.owner = User.objects.create_user(
            f's5owner{s}', f's5owner{s}@test.com', 'TestPass123!',
            first_name='Owner', last_name='Test',
        )
        self.tenant = Tenant.objects.create(
            name=f'S5 Shop{s}', slug=f's5shop{s}', subdomain=f's5shop{s}',
            owner=self.owner, plan='trial', trial_started_at=timezone.now(),
            services_offered='both',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True)
        self.owner_tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True,
            is_manager=True, can_repair=True, can_replace=True,
        )

        self.tech_user = User.objects.create_user(
            f's5tech{s}', f's5tech{s}@test.com', 'TestPass123!',
            first_name='Marcus', last_name='Field',
        )
        TenantMembership.objects.create(
            user=self.tech_user, tenant=self.tenant, role='technician',
            is_active=True)
        self.tech = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True,
        )

        self.other_user = User.objects.create_user(
            f's5other{s}', f's5other{s}@test.com', 'TestPass123!',
            first_name='Dana', last_name='Second',
        )
        TenantMembership.objects.create(
            user=self.other_user, tenant=self.tenant, role='technician',
            is_active=True)
        self.other_tech = Technician.objects.create(
            user=self.other_user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True,
        )

        # A working manager: sees the whole shop (Technician.is_manager) but
        # holds no owner/manager *membership* role, so the can_assign_work
        # gate is the thing deciding whether they may move work.
        self.mgr_user = User.objects.create_user(
            f's5mgr{s}', f's5mgr{s}@test.com', 'TestPass123!',
            first_name='Lee', last_name='Lead',
        )
        TenantMembership.objects.create(
            user=self.mgr_user, tenant=self.tenant, role='technician',
            is_active=True)
        self.mgr = Technician.objects.create(
            user=self.mgr_user, tenant=self.tenant, is_active=True,
            is_manager=True, can_assign_work=False,
            can_repair=True, can_replace=True,
        )
        Group.objects.get_or_create(name='Technicians')

        self.customer = Customer.objects.create(
            tenant=self.tenant, name=f'Fleet Co{s}', customer_type='FLEET',
            email=f's5fleet{s}@test.com',
            address='100 Yard Rd', city='Little Rock', state='AR',
            zip_code='72201', phone='501-555-0100',
        )
        self.client = Client()

    # --- helpers ----------------------------------------------------------
    def login_shop(self, user=None):
        self.client.force_login(user or self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def make_repair(self, unit='UNIT-1', *, technician=None, status='APPROVED',
                    scheduled_for=None, window_end=None, **extra):
        repair = Repair(
            tenant=self.tenant, customer=self.customer,
            technician=technician or self.tech,
            unit_number=unit, queue_status=status,
            damage_type='Chip', description='Rock chip',
            **extra,
        )
        repair.save()
        if scheduled_for is not None:
            Repair.objects.filter(pk=repair.pk).update(
                scheduled_for=scheduled_for, scheduled_window_end=window_end)
            repair.refresh_from_db()
        return repair

    def post_dispatch(self, job, kind='repair', **payload):
        body = {'type': kind, 'id': job.pk}
        body.update(payload)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse('schedule_dispatch'), data=json.dumps(body),
                content_type='application/json',
            )

    @staticmethod
    def assignment_mail():
        return [m for m in mail.outbox if 'Assignment' in m.subject]

    @staticmethod
    def schedule_mail():
        # S7's `job_rescheduled` template — "Your schedule changed for <day>".
        return [m for m in mail.outbox
                if 'schedule changed' in m.subject.lower()]


# =============================================================================
# Permissions — two gates, not one
# =============================================================================

class DispatchPermissionTests(S5Base):
    suffix = '_perm'

    def test_plain_technician_cannot_dispatch(self):
        repair = self.make_repair()
        self.login_shop(self.tech_user)
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING')
        self.assertEqual(resp.status_code, 403)
        repair.refresh_from_db()
        self.assertIsNone(repair.scheduled_for)

    def test_working_manager_without_can_assign_work_may_book_not_reassign(self):
        repair = self.make_repair()
        self.login_shop(self.mgr_user)

        # The board hands this manager S4's narrower endpoint, and the
        # dispatch endpoint refuses the half they don't have.
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn('reassign', resp.json()['error'])
        repair.refresh_from_db()
        self.assertEqual(repair.technician_id, self.tech.pk)
        self.assertIsNone(repair.scheduled_for)

        # Booking alone still works for them.
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING')
        self.assertEqual(resp.status_code, 200)
        repair.refresh_from_db()
        self.assertIsNotNone(repair.scheduled_for)

    def test_board_renders_the_narrower_endpoint_for_that_manager(self):
        self.make_repair()
        self.login_shop(self.mgr_user)
        resp = self.client.get(reverse('day_schedule'))
        self.assertTrue(resp.context['can_book'])
        self.assertFalse(resp.context['can_assign'])
        self.assertContains(resp, reverse('schedule_book'))
        self.assertNotContains(resp, 'data-dispatch-tech')

    def test_owner_sees_the_roster_and_the_dispatch_endpoint(self):
        self.make_repair()
        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertTrue(resp.context['can_assign'])
        roster = {t.pk for t in resp.context['roster']}
        self.assertIn(self.tech.pk, roster)
        self.assertIn(self.other_tech.pk, roster)
        self.assertContains(resp, 'data-dispatch-tech')
        self.assertContains(resp, reverse('schedule_dispatch'))

    def test_inactive_technician_is_not_on_the_roster(self):
        self.make_repair()
        Technician.objects.filter(pk=self.other_tech.pk).update(is_active=False)
        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertNotIn(
            self.other_tech.pk, {t.pk for t in resp.context['roster']})


# =============================================================================
# The motion itself
# =============================================================================

class DispatchWriteTests(S5Base):
    suffix = '_write'

    def test_assign_and_book_in_one_motion(self):
        repair = self.make_repair('TRK-1')
        self.login_shop()
        mail.outbox = []

        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
            expected_technician_id=self.tech.pk,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        repair.refresh_from_db()
        self.assertEqual(repair.technician_id, self.other_tech.pk)
        self.assertEqual(repair.scheduled_for, at(tomorrow(), 8))
        self.assertEqual(repair.scheduled_window_end, at(tomorrow(), 12))

        # One message for one decision — the assignment mail carries the time
        # rather than a booking mail chasing it.
        assigned = [m for m in self.assignment_mail()
                    if self.other_user.email in m.to]
        self.assertEqual(len(assigned), 1)
        self.assertEqual(len(self.schedule_mail()), 0)
        self.assertIn('8:00 AM', assigned[0].body)

    def test_book_only_uses_s4s_notification(self):
        repair = self.make_repair('TRK-2')
        self.login_shop()
        mail.outbox = []

        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='AFTERNOON')
        self.assertEqual(resp.status_code, 200)
        repair.refresh_from_db()
        self.assertEqual(repair.scheduled_for, at(tomorrow(), 12))
        self.assertEqual(repair.technician_id, self.tech.pk)
        self.assertEqual(len(self.schedule_mail()), 1)
        self.assertEqual(len(self.assignment_mail()), 0)

    def test_reassign_a_booked_row_keeps_its_time(self):
        booked = at(tomorrow(), 9)
        repair = self.make_repair(
            'TRK-3', scheduled_for=booked, window_end=at(tomorrow(), 10))
        self.login_shop()
        mail.outbox = []

        resp = self.post_dispatch(
            repair, technician_id=self.other_tech.pk,
            expected_technician_id=self.tech.pk,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        repair.refresh_from_db()
        self.assertEqual(repair.technician_id, self.other_tech.pk)
        self.assertEqual(repair.scheduled_for, booked)

        # The tech who lost it hears about it too (N1's rule, unchanged).
        away = [m for m in mail.outbox if self.tech_user.email in m.to]
        self.assertEqual(len(away), 1)

    def test_exact_window_survives_the_board(self):
        repair = self.make_repair('TRK-4')
        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='EXACT',
            start_time='04:30', end_time='05:45',
            technician_id=self.other_tech.pk,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        repair.refresh_from_db()
        self.assertEqual(repair.scheduled_for, at(tomorrow(), 4, 30))
        self.assertEqual(repair.scheduled_window_end, at(tomorrow(), 5, 45))

    def test_replacements_dispatch_too(self):
        repl = Replacement(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-5', queue_status='APPROVED',
            glass_position='Windshield', description='Cracked',
        )
        repl.save()
        self.login_shop()
        resp = self.post_dispatch(
            repl, kind='replacement', date=tomorrow().isoformat(),
            window='MORNING', technician_id=self.other_tech.pk,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        repl.refresh_from_db()
        self.assertEqual(repl.technician_id, self.other_tech.pk)
        self.assertEqual(repl.scheduled_for, at(tomorrow(), 8))

    def test_the_actor_is_never_notified_about_their_own_dispatch(self):
        repair = self.make_repair('TRK-6')
        self.login_shop()
        mail.outbox = []
        # Owner dispatches the job to themselves.
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.owner_tech.pk,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [m for m in mail.outbox if self.owner.email in m.to], [])

    def test_dispatch_does_not_touch_money(self):
        """The booking half stays a bare .update(); the assign half is a save()
        that must still leave price and invoice alone."""
        from apps.billing.models import Invoice, InvoiceLineItem

        repair = self.make_repair('TRK-7')
        repair.cost = Decimal('50.00')
        repair.save()
        invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-S5-1', status='SENT',
            subtotal=Decimal('50.00'), total=Decimal('50.00'),
        )
        line = InvoiceLineItem.objects.create(
            invoice=invoice, repair=repair, description='Windshield repair',
            quantity=1, unit_price=Decimal('50.00'), amount=Decimal('50.00'),
        )

        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        repair.refresh_from_db()
        invoice.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(repair.cost, Decimal('50.00'))
        self.assertEqual(invoice.total, Decimal('50.00'))
        self.assertEqual(line.amount, Decimal('50.00'))


# =============================================================================
# Refusals — the board never half-applies
# =============================================================================

class DispatchRefusalTests(S5Base):
    suffix = '_refuse'

    def test_stale_technician_is_a_409(self):
        repair = self.make_repair('TRK-8')
        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
            # Someone else moved it to owner_tech since this row rendered.
            expected_technician_id=self.owner_tech.pk,
        )
        self.assertEqual(resp.status_code, 409)
        repair.refresh_from_db()
        self.assertEqual(repair.technician_id, self.tech.pk)
        self.assertIsNone(repair.scheduled_for, "a refused dispatch books nothing")

    def test_stale_time_is_a_409_and_leaves_the_technician_alone(self):
        repair = self.make_repair(
            'TRK-9', scheduled_for=at(tomorrow(), 9),
            window_end=at(tomorrow(), 10))
        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
            expected_technician_id=self.tech.pk,
            expected='',  # the caller thinks it is unscheduled
        )
        self.assertEqual(resp.status_code, 409)
        repair.refresh_from_db()
        self.assertEqual(repair.scheduled_for, at(tomorrow(), 9))
        self.assertEqual(
            repair.technician_id, self.tech.pk,
            "the assign half must roll back with the booking half")

    def test_nothing_to_change_is_refused_not_flashed_as_success(self):
        repair = self.make_repair('TRK-10')
        self.login_shop()
        resp = self.post_dispatch(repair, technician_id=self.tech.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Nothing to change', resp.json()['error'])

    def test_empty_payload_is_refused(self):
        repair = self.make_repair('TRK-11')
        self.login_shop()
        resp = self.post_dispatch(repair)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Pick a technician or a time', resp.json()['error'])

    def test_completed_work_cannot_be_dispatched(self):
        repair = self.make_repair('TRK-12', status='COMPLETED')
        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('completed', resp.json()['error'])

    def test_a_technician_from_another_shop_is_refused(self):
        other_owner = User.objects.create_user(
            's5foreign', 's5foreign@test.com', 'TestPass123!')
        other_tenant = Tenant.objects.create(
            name='Other Shop', slug='s5other', subdomain='s5other',
            owner=other_owner, plan='trial', trial_started_at=timezone.now(),
        )
        foreign = Technician.objects.create(
            user=other_owner, tenant=other_tenant, is_active=True)

        repair = self.make_repair('TRK-13')
        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=foreign.pk)
        self.assertEqual(resp.status_code, 400)
        repair.refresh_from_db()
        self.assertEqual(repair.technician_id, self.tech.pk)

    def test_another_shops_job_is_a_404(self):
        other_owner = User.objects.create_user(
            's5foreign2', 's5foreign2@test.com', 'TestPass123!')
        other_tenant = Tenant.objects.create(
            name='Other Shop 2', slug='s5other2', subdomain='s5other2',
            owner=other_owner, plan='trial', trial_started_at=timezone.now(),
        )
        foreign_tech = Technician.objects.create(
            user=other_owner, tenant=other_tenant, is_active=True)
        foreign_customer = Customer.objects.create(
            tenant=other_tenant, name='Theirs', customer_type='FLEET')
        foreign_job = Repair(
            tenant=other_tenant, customer=foreign_customer,
            technician=foreign_tech, unit_number='X', queue_status='APPROVED',
        )
        foreign_job.save()

        self.login_shop()
        resp = self.post_dispatch(
            foreign_job, date=tomorrow().isoformat(), window='MORNING')
        self.assertEqual(resp.status_code, 404)

    def test_garbage_technician_id_is_refused(self):
        repair = self.make_repair('TRK-14')
        self.login_shop()
        resp = self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id='not-a-number')
        self.assertEqual(resp.status_code, 400)

    def test_parse_requires_a_known_type(self):
        with self.assertRaises(DispatchError):
            parse_dispatch_request({'type': 'invoice', 'id': 1})


# =============================================================================
# Batches — one physical visit, one technician, one time
# =============================================================================

class DispatchBatchTests(S5Base):
    suffix = '_batch'

    def make_batch(self, count=3):
        import uuid
        batch_id = uuid.uuid4()
        rows = []
        for i in range(count):
            rows.append(self.make_repair(
                'BATCH-1', repair_batch_id=batch_id,
                total_breaks_in_batch=count, break_number=i + 1,
            ))
        return rows

    def test_dispatching_one_break_moves_and_books_the_whole_visit(self):
        rows = self.make_batch()
        self.login_shop()
        resp = self.post_dispatch(
            rows[1], date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
            expected_technician_id=self.tech.pk,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        for row in rows:
            row.refresh_from_db()
            self.assertEqual(row.technician_id, self.other_tech.pk)
            self.assertEqual(row.scheduled_for, at(tomorrow(), 8))
        self.assertIn('3 breaks', resp.json()['message'])

    def test_a_half_moved_batch_refuses_rather_than_splitting(self):
        rows = self.make_batch()
        Repair.objects.filter(pk=rows[2].pk).update(
            scheduled_for=at(tomorrow(), 15))
        self.login_shop()
        resp = self.post_dispatch(
            rows[0], date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk,
        )
        self.assertEqual(resp.status_code, 409)
        for row in rows:
            row.refresh_from_db()
            self.assertEqual(row.technician_id, self.tech.pk)


# =============================================================================
# Conflicts — informational, and deliberately quiet about coarse windows
# =============================================================================

class ConflictTests(S5Base):
    suffix = '_conflict'

    def test_two_precise_windows_that_overlap_are_flagged_both_ways(self):
        day = tomorrow()
        a = self.make_repair('A', scheduled_for=at(day, 4, 30),
                             window_end=at(day, 5, 45))
        b = self.make_repair('B', scheduled_for=at(day, 5),
                             window_end=at(day, 6))
        annotate_conflicts([a, b])
        self.assertTrue(any('Overlaps' in c for c in a.conflicts))
        self.assertTrue(any('Overlaps' in c for c in b.conflicts))

    def test_a_pile_up_is_one_chip_not_a_wall_of_identical_ones(self):
        day = tomorrow()
        rows = [
            self.make_repair(f'PILE{i}', scheduled_for=at(day, 8),
                             window_end=at(day, 9))
            for i in range(3)
        ]
        annotate_conflicts(rows)
        for row in rows:
            overlaps = [c for c in row.conflicts if 'Overlaps' in c]
            self.assertEqual(overlaps, ['Overlaps 2 other jobs at this time'])

    def test_precise_windows_that_do_not_touch_are_quiet(self):
        day = tomorrow()
        a = self.make_repair('A', scheduled_for=at(day, 8),
                             window_end=at(day, 9))
        b = self.make_repair('B', scheduled_for=at(day, 9),
                             window_end=at(day, 10))
        annotate_conflicts([a, b])
        self.assertEqual(a.conflicts, [])
        self.assertEqual(b.conflicts, [])

    def test_two_morning_bookings_are_not_called_a_double_booking(self):
        """Presets are buckets, not clock times — flagging every pair of them
        would flag a normal day end to end."""
        day = tomorrow()
        a = self.make_repair('A', scheduled_for=at(day, 8),
                             window_end=at(day, 12))
        b = self.make_repair('B', scheduled_for=at(day, 8),
                             window_end=at(day, 12))
        annotate_conflicts([a, b])
        self.assertEqual([c for c in a.conflicts if 'Overlaps' in c], [])

    def test_breaks_of_one_visit_do_not_overlap_each_other(self):
        import uuid
        day = tomorrow()
        batch_id = uuid.uuid4()
        rows = [
            self.make_repair(
                'BATCH', repair_batch_id=batch_id, total_breaks_in_batch=2,
                break_number=i + 1, scheduled_for=at(day, 7),
                window_end=at(day, 8),
            )
            for i in range(2)
        ]
        annotate_conflicts(rows)
        for row in rows:
            self.assertEqual([c for c in row.conflicts if 'Overlaps' in c], [])

    def test_a_booking_that_misses_the_customers_window_is_flagged(self):
        day = tomorrow()
        repair = self.make_repair(
            'WISH', preferred_date=day, preferred_window='MORNING',
            scheduled_for=at(day, 13), window_end=at(day, 17),
        )
        annotate_conflicts([repair])
        self.assertTrue(any('Asked for' in c for c in repair.conflicts))

    def test_a_booking_that_honours_the_window_is_quiet(self):
        day = tomorrow()
        repair = self.make_repair(
            'WISH', preferred_date=day, preferred_window='MORNING',
            scheduled_for=at(day, 8), window_end=at(day, 12),
        )
        annotate_conflicts([repair])
        self.assertEqual(repair.conflicts, [])

    def test_a_booking_on_the_wrong_day_is_flagged(self):
        day = tomorrow()
        repair = self.make_repair(
            'WISH', preferred_date=day, preferred_window='MORNING',
            scheduled_for=at(day + timedelta(days=2), 8),
            window_end=at(day + timedelta(days=2), 12),
        )
        self.assertIn('Asked for', describe_missed_preference(repair))

    def test_an_exact_ask_booked_outside_its_minutes_is_flagged(self):
        day = tomorrow()
        repair = self.make_repair(
            'FLEET', preferred_date=day, preferred_window='EXACT',
            preferred_time_start=time(4, 30), preferred_time_end=time(5, 45),
            scheduled_for=at(day, 8), window_end=at(day, 12),
        )
        self.assertIn('Asked for', describe_missed_preference(repair))

    def test_an_exact_ask_booked_inside_its_minutes_is_quiet(self):
        day = tomorrow()
        repair = self.make_repair(
            'FLEET', preferred_date=day, preferred_window='EXACT',
            preferred_time_start=time(4, 30), preferred_time_end=time(5, 45),
            scheduled_for=at(day, 4, 30), window_end=at(day, 5, 45),
        )
        self.assertEqual(describe_missed_preference(repair), '')

    def test_a_job_with_no_wish_is_never_flagged_for_missing_one(self):
        day = tomorrow()
        repair = self.make_repair(
            'PLAIN', scheduled_for=at(day, 13), window_end=at(day, 17))
        self.assertEqual(describe_missed_preference(repair), '')

    def test_over_committed_day_is_summarized(self):
        day = tomorrow()
        rows = [
            self.make_repair(f'LOAD{i}', scheduled_for=at(day, 8),
                             window_end=at(day, 10))
            for i in range(3)
        ]
        load = technician_load(rows)
        self.assertTrue(load['over_committed'])
        self.assertEqual(load['count'], 3)
        self.assertIn('3h of work booked into 2h', load['summary'])

    def test_a_comfortable_day_is_not_summarized_as_over_committed(self):
        day = tomorrow()
        rows = [
            self.make_repair('L1', scheduled_for=at(day, 8),
                             window_end=at(day, 9)),
            self.make_repair('L2', scheduled_for=at(day, 13),
                             window_end=at(day, 14)),
        ]
        self.assertFalse(technician_load(rows)['over_committed'])

    def test_an_empty_day_has_no_load(self):
        self.assertIsNone(technician_load([]))

    def test_the_board_shows_the_flags(self):
        day = timezone.localtime(timezone.now()).date()
        self.make_repair('A', scheduled_for=at(day, 4, 30),
                         window_end=at(day, 5, 45))
        self.make_repair('B', scheduled_for=at(day, 5),
                         window_end=at(day, 6))
        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertContains(resp, 'Overlaps')

    def test_the_board_flags_an_over_committed_technician(self):
        day = timezone.localtime(timezone.now()).date()
        for i in range(3):
            self.make_repair(f'LOAD{i}', scheduled_for=at(day, 8),
                             window_end=at(day, 9))
        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertContains(resp, '3h of work booked into 1h')

    def test_a_comfortable_day_gets_no_badge_on_the_board(self):
        day = timezone.localtime(timezone.now()).date()
        self.make_repair('L1', scheduled_for=at(day, 8), window_end=at(day, 9))
        self.make_repair('L2', scheduled_for=at(day, 13), window_end=at(day, 14))
        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertNotContains(resp, 'of work booked into')

    def test_a_technician_sees_their_own_double_booking(self):
        day = timezone.localtime(timezone.now()).date()
        self.make_repair('A', scheduled_for=at(day, 4, 30),
                         window_end=at(day, 5, 45))
        self.make_repair('B', scheduled_for=at(day, 5),
                         window_end=at(day, 6))
        self.login_shop(self.tech_user)
        resp = self.client.get(reverse('day_schedule'))
        self.assertFalse(resp.context['sees_whole_shop'])
        self.assertContains(resp, 'Overlaps')


# =============================================================================
# The rail as a working pile
# =============================================================================

class TriageRailTests(S5Base):
    suffix = '_rail'

    def test_rail_expands_in_place_instead_of_leaving_the_board(self):
        for i in range(10):
            self.make_repair(f'PILE-{i}')
        self.login_shop()

        resp = self.client.get(reverse('day_schedule'))
        self.assertEqual(len(resp.context['triage_jobs']), 8)
        self.assertEqual(resp.context['triage_overflow'], 2)
        self.assertContains(resp, 'rail=all')

        resp = self.client.get(reverse('day_schedule'), {'rail': 'all'})
        self.assertEqual(len(resp.context['triage_jobs']), 10)
        self.assertEqual(resp.context['triage_overflow'], 0)
        self.assertContains(resp, 'Show fewer')

    def test_dispatching_from_the_rail_removes_it_from_the_rail(self):
        repair = self.make_repair('RAIL-1')
        self.login_shop()
        self.post_dispatch(
            repair, date=tomorrow().isoformat(), window='MORNING',
            technician_id=self.other_tech.pk)

        resp = self.client.get(
            reverse('day_schedule'), {'date': tomorrow().isoformat()})
        self.assertEqual(resp.context['triage_jobs'], [])
        booked = {job.pk for group in resp.context['groups']
                  for job in group['jobs']}
        self.assertIn(repair.pk, booked)


# =============================================================================
# The service, called directly
# =============================================================================

class ServiceTests(S5Base):
    suffix = '_service'

    def test_apply_dispatch_needs_a_tenant(self):
        repair = self.make_repair('SVC-1')
        with self.assertRaises(DispatchError) as caught:
            apply_dispatch(tenant=None, service_type='repair', pk=repair.pk,
                           technician_id=self.other_tech.pk)
        self.assertEqual(caught.exception.status, 403)

    def test_parse_passes_booking_validation_through(self):
        with self.assertRaises(DispatchError) as caught:
            parse_dispatch_request({
                'type': 'repair', 'id': 1, 'date': tomorrow().isoformat(),
                'window': 'EXACT', 'start_time': '09:00', 'end_time': '08:00',
            })
        self.assertIn('after the start', caught.exception.message)

    def test_parse_reads_a_reassign_only_payload(self):
        parsed = parse_dispatch_request({
            'type': 'replacement', 'id': 7, 'technician_id': '3',
            'expected_technician_id': '2',
        })
        self.assertEqual(parsed['service_type'], 'replacement')
        self.assertEqual(parsed['technician_id'], 3)
        self.assertEqual(parsed['expected_technician_id'], 2)
        self.assertIsNone(parsed['booking'])
