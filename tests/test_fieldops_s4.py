"""
Fieldops S4 — customer requests carry when + where.

Covers the acceptance criteria in docs/strategy/FIELD_OPS_SESSIONS.md §S4:
a customer names a day, a window and (if the vehicle is elsewhere) an address;
the wish rides the job to the shop's triage rail sorted soonest-first; one
confirm turns it into a real booking without touching money; the booked job
appears on the assigned tech's day view and the tech is notified once; a batch
submission carries one wish onto every row and books as one visit; requests
with no preference behave exactly as before; and the four places that claimed
"you're on the schedule" while scheduled_for was null now tell the truth.

Two inherited testing gotchas apply throughout (S7 + N4):
- Notifications registered with transaction.on_commit do not run under
  TestCase — every write POST here goes through captureOnCommitCallbacks.
- Since N1, creating a job emails the assigned tech, so mail.outbox[0] is
  never safely "the message this test is about". Filter by subject.
"""

import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.customer_portal.models import CustomerUser
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.technician_portal.models import (
    PREFERRED_WINDOW_HOURS, Repair, Replacement, Technician,
    TechnicianNotification, shop_timezone_label,
)
from apps.technician_portal.services.schedule_booking import (
    BookingError, confirm_appointment, window_bounds,
)
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def tomorrow():
    return timezone.localtime(timezone.now()).date() + timedelta(days=1)


@override_settings(**TEST_SETTINGS)
class S4Base(TestCase):
    """One shop, one tech, one portal-logged-in customer."""

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
            f's4owner{s}', f's4owner{s}@test.com', 'TestPass123!',
            first_name='Owner', last_name='Test',
        )
        self.tenant = Tenant.objects.create(
            name=f'S4 Shop{s}', slug=f's4shop{s}', subdomain=f's4shop{s}',
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
            f's4tech{s}', f's4tech{s}@test.com', 'TestPass123!',
            first_name='Marcus', last_name='Field',
        )
        TenantMembership.objects.create(
            user=self.tech_user, tenant=self.tenant, role='technician',
            is_active=True)
        self.tech = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True,
        )
        Group.objects.get_or_create(name='Technicians')

        self.customer = Customer.objects.create(
            tenant=self.tenant, name=f'Fleet Co{s}', customer_type='FLEET',
            email=f's4fleet{s}@test.com',
            address='100 Yard Rd', city='Little Rock', state='AR',
            zip_code='72201', phone='501-555-0100',
        )
        self.cust_user = User.objects.create_user(
            f's4cust{s}', f's4cust{s}@test.com', 'TestPass123!')
        self.cu = CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer,
            is_primary_contact=True,
        )

        self.client = Client()

    # --- helpers ----------------------------------------------------------
    def login_customer(self):
        self.client.force_login(self.cust_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def login_shop(self, user=None):
        self.client.force_login(user or self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def post_request_repair(self, **extra):
        data = {
            'unit_number': 'UNIT-1',
            'damage_type': 'Chip',
            'description': 'Rock chip',
        }
        data.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('customer_request_repair'), data)

    def post_book(self, job, kind='repair', day=None, window='MORNING',
                  start_time='', end_time='', expected=''):
        payload = {
            'type': kind, 'id': job.pk,
            'date': (day or tomorrow()).isoformat(),
            'window': window, 'expected': expected,
            'start_time': start_time, 'end_time': end_time,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse('schedule_book'), data=json.dumps(payload),
                content_type='application/json',
            )


# =============================================================================
# Capture — the customer names when and where
# =============================================================================

class PreferenceCaptureTests(S4Base):
    suffix = '_cap'

    def test_repair_request_stores_wish_without_booking_anything(self):
        """The whole premise: a wish is not a booking.

        Repairs auto-approve to APPROVED on submit, and APPROVED is on the
        day sheet — so if the wish leaked into scheduled_for the shop would
        have published an appointment nobody agreed to.
        """
        self.login_customer()
        day = tomorrow()
        self.post_request_repair(
            preferred_date=day.isoformat(), preferred_window='MORNING')

        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.preferred_date, day)
        self.assertEqual(repair.preferred_window, 'MORNING')
        self.assertEqual(repair.queue_status, 'APPROVED')
        self.assertIsNone(repair.scheduled_for)
        self.assertIsNone(repair.scheduled_window_end)

    def test_replacement_request_stores_wish(self):
        self.login_customer()
        day = tomorrow()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('customer_request_replacement'), {
                'unit_number': 'TRK-9',
                'glass_position': 'WINDSHIELD',
                'preferred_date': day.isoformat(),
                'preferred_window': 'AFTERNOON',
            })
        repl = Replacement.objects.get(customer=self.customer)
        self.assertEqual(repl.preferred_date, day)
        self.assertEqual(repl.preferred_window, 'AFTERNOON')
        self.assertIsNone(repl.scheduled_for)

    def test_no_preference_behaves_exactly_as_before(self):
        self.login_customer()
        self.post_request_repair()
        repair = Repair.objects.get(customer=self.customer)
        self.assertIsNone(repair.preferred_date)
        self.assertEqual(repair.preferred_window, '')
        self.assertEqual(repair.service_address, '')
        self.assertFalse(repair.has_time_preference)
        self.assertEqual(repair.get_time_preference(), '')

    def test_past_date_is_dropped(self):
        """A stale autosaved form is not a request for last Tuesday."""
        self.login_customer()
        self.post_request_repair(
            preferred_date=(timezone.localtime(timezone.now()).date()
                            - timedelta(days=3)).isoformat(),
            preferred_window='MORNING')
        repair = Repair.objects.get(customer=self.customer)
        self.assertIsNone(repair.preferred_date)
        self.assertEqual(repair.preferred_window, 'MORNING')

    def test_unknown_window_is_ignored(self):
        self.login_customer()
        self.post_request_repair(preferred_window='WHENEVER')
        self.assertEqual(
            Repair.objects.get(customer=self.customer).preferred_window, '')

    def test_address_matching_the_customer_is_not_persisted(self):
        """S2's rule. Freezing a copy would break the fix-it-once property."""
        self.login_customer()
        self.post_request_repair(
            service_address='  100 Yard RD ', service_city='little rock',
            service_state='AR', service_zip='72201')
        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.service_address, '')
        # Still resolves, via the customer fallback.
        self.assertEqual(repair.get_service_location(),
                         '100 Yard Rd, Little Rock, AR 72201')

    def test_partial_override_is_completed_from_the_customer_record(self):
        """get_service_location_parts() is all-or-nothing.

        A street with no city would otherwise drop the customer's city
        wholesale and leave an unmappable address.
        """
        self.login_customer()
        self.post_request_repair(service_address='4500 Industrial Dr, Lot B')
        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.service_address, '4500 Industrial Dr, Lot B')
        self.assertEqual(repair.service_city, 'Little Rock')
        self.assertEqual(repair.service_zip, '72201')
        self.assertIn('Little Rock', repair.get_service_location())

    def test_batch_writes_one_wish_onto_every_row(self):
        self.login_customer()
        day = tomorrow()
        units = [
            {'unitNumber': 'A-1', 'damageType': 'Chip'},
            {'unitNumber': 'A-2', 'damageType': 'Crack',
             'hasMultipleBreaks': True, 'breakCount': 3},
        ]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('customer_request_repair'), {
                'batch_submission': 'true',
                'units_data': json.dumps(units),
                'preferred_date': day.isoformat(),
                'preferred_window': 'ANYTIME',
            })
        repairs = Repair.objects.filter(customer=self.customer)
        self.assertEqual(repairs.count(), 4)
        for repair in repairs:
            self.assertEqual(repair.preferred_date, day)
            self.assertEqual(repair.preferred_window, 'ANYTIME')
            self.assertIsNone(repair.scheduled_for)

    def test_request_pages_render_the_when_and_where_card(self):
        self.login_customer()
        for url in ('customer_request_repair', 'customer_request_replacement'):
            resp = self.client.get(reverse(url))
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, 'name="preferred_date"', msg_prefix=url)
            self.assertContains(resp, 'name="preferred_window"', msg_prefix=url)
            self.assertContains(resp, 'name="service_address"', msg_prefix=url)
            # Address inputs start empty behind a toggle — never prefilled, or
            # every request would freeze a copy of the company address.
            self.assertNotContains(resp, 'value="100 Yard Rd"')


# =============================================================================
# Honesty — the product used to claim a booking it had not made
# =============================================================================

class OverPromiseTests(S4Base):
    suffix = '_honest'

    def test_success_message_no_longer_claims_the_schedule(self):
        self.login_customer()
        resp = self.post_request_repair(follow=False)
        messages = [str(m) for m in resp.wsgi_request._messages]
        joined = ' '.join(messages)
        self.assertNotIn("you're on the schedule", joined)
        self.assertIn('confirm your time', joined)

    def test_success_message_echoes_the_wish(self):
        self.login_customer()
        resp = self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='MORNING')
        joined = ' '.join(str(m) for m in resp.wsgi_request._messages)
        self.assertIn("We'll aim for", joined)
        self.assertIn('morning', joined)

    def test_batch_json_message_no_longer_claims_the_schedule(self):
        self.login_customer()
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                reverse('customer_request_repair'),
                {
                    'batch_submission': 'true',
                    'units_data': json.dumps([{'unitNumber': 'B-1'}]),
                },
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
        body = json.loads(resp.content)
        self.assertTrue(body['success'])
        self.assertNotIn("you're on the schedule", body['message'])

    def test_customer_detail_badge_tells_the_truth(self):
        """The badge outlives the toast, so it is the claim that matters."""
        self.login_customer()
        self.post_request_repair()
        repair = Repair.objects.get(customer=self.customer)

        resp = self.client.get(
            reverse('customer_repair_detail', args=[repair.pk]))
        self.assertNotContains(resp, 'Scheduled for Repair')
        self.assertContains(resp, 'Time to Be Confirmed')

        # Once it IS booked, the badge and a real time both appear.
        self.login_shop()
        self.post_book(repair)
        self.login_customer()
        resp = self.client.get(
            reverse('customer_repair_detail', args=[repair.pk]))
        self.assertContains(resp, 'Scheduled for Repair')

    def test_request_received_email_does_not_say_scheduled(self):
        # Customers keep the email_verified gate (N1's staff default-ON policy
        # is technicians only), so without this the notification is created
        # and nothing is ever sent — the assertion below would test nothing.
        from core.models.notification_preferences import (
            CustomerNotificationPreference,
        )
        CustomerNotificationPreference.objects.update_or_create(
            customer=self.customer,
            defaults={'receive_email_notifications': True,
                      'email_verified': True},
        )
        self.login_customer()
        mail.outbox = []
        self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='MORNING')
        bodies = [m.body for m in mail.outbox
                  if 'Request Received' in m.subject or 'request' in m.subject.lower()]
        self.assertTrue(bodies, [m.subject for m in mail.outbox])
        customer_mail = ' '.join(bodies)
        self.assertNotIn('added to the schedule', customer_mail)
        self.assertNotIn('Status: Scheduled', customer_mail)
        # The guard is the promise, not the phrasing. PR #200's email chassis
        # rewrote this copy from "confirm your time" to "we will confirm the
        # time shortly" — same commitment, and the assertion should survive
        # the next rewrite too. What must never appear is a time the customer
        # was never given, which is what the two lines above check.
        self.assertRegex(customer_mail, r'confirm (?:your|the) time')


# =============================================================================
# The rail — where the wish has to show up
# =============================================================================

class TriageRailTests(S4Base):
    suffix = '_rail'

    def make_repair(self, unit, preferred=None, window='', status='APPROVED',
                    service_date=None):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=unit, queue_status=status,
        )
        repair.preferred_date = preferred
        repair.preferred_window = window
        repair.save()
        if service_date:
            Repair.objects.filter(pk=repair.pk).update(service_date=service_date)
            repair.refresh_from_db()
        return repair

    def test_rail_sorts_the_soonest_wish_first(self):
        """The rail is capped at 8.

        Sorting purely by recency buried a customer who asked for tomorrow
        under eight newer requests that named no day at all.
        """
        now = timezone.now()
        for i in range(8):
            self.make_repair(f'NOWISH-{i}', service_date=now - timedelta(minutes=i))
        wished = self.make_repair(
            'WISHED', preferred=tomorrow(), window='MORNING',
            service_date=now - timedelta(days=5))

        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertEqual(resp.status_code, 200)
        rail = [j.pk for j in resp.context['triage_jobs']]
        self.assertEqual(rail[0], wished.pk)

    def test_rail_shows_the_wish_and_a_book_control(self):
        repair = self.make_repair('WISHED', preferred=tomorrow(), window='MORNING')
        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertContains(resp, 'Asked for')
        # Renamed data-book-form -> data-dispatch-form in S5, when the same
        # row form grew a technician picker beside the date and window.
        self.assertContains(resp, 'data-dispatch-form')
        self.assertContains(resp, f'repair-{repair.pk}')

    def test_plain_technician_sees_no_book_control(self):
        self.make_repair('WISHED', preferred=tomorrow(), window='MORNING')
        self.login_shop(self.tech_user)
        resp = self.client.get(reverse('day_schedule'))
        self.assertFalse(resp.context['can_book'])
        self.assertNotContains(resp, 'data-dispatch-form')


# =============================================================================
# Confirming — the one write
# =============================================================================

class ConfirmTests(S4Base):
    suffix = '_confirm'

    def make_repair(self, unit='U-1', status='APPROVED', **kwargs):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=unit, queue_status=status,
        )
        for field, value in kwargs.items():
            setattr(repair, field, value)
        repair.save()
        return repair

    def test_confirm_books_the_wished_window(self):
        repair = self.make_repair(
            preferred_date=tomorrow(), preferred_window='MORNING')
        self.login_shop()
        resp = self.post_book(repair, window='MORNING')
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertTrue(body['ok'])

        repair.refresh_from_db()
        start, end = window_bounds(tomorrow(), 'MORNING')
        self.assertEqual(repair.scheduled_for, start)
        self.assertEqual(repair.scheduled_window_end, end)
        self.assertEqual(
            timezone.localtime(repair.scheduled_for).hour,
            PREFERRED_WINDOW_HOURS['MORNING'][0])

    def test_confirm_changes_no_money_and_no_invoice_line(self):
        """A schedule change must never re-price the job.

        GlassService.save() runs TaxService and pushes prices onto live
        invoices through invoice_sync — hence the .update() write path.
        """
        from apps.billing.models import Invoice, InvoiceLineItem

        repair = self.make_repair(unit='MONEY-1')
        Repair.objects.filter(pk=repair.pk).update(
            cost=Decimal('50.00'), tax_amount=Decimal('4.13'))
        repair.refresh_from_db()

        invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-S4-1', status='SENT',
            subtotal=Decimal('50.00'), tax_amount=Decimal('4.13'),
            total=Decimal('54.13'),
        )
        line = InvoiceLineItem.objects.create(
            invoice=invoice, repair=repair, description='Windshield repair',
            quantity=1, unit_price=Decimal('50.00'), amount=Decimal('50.00'),
        )

        self.login_shop()
        self.post_book(repair)

        repair.refresh_from_db()
        invoice.refresh_from_db()
        line.refresh_from_db()
        self.assertIsNotNone(repair.scheduled_for)
        self.assertEqual(repair.cost, Decimal('50.00'))
        self.assertEqual(repair.tax_amount, Decimal('4.13'))
        self.assertEqual(invoice.total, Decimal('54.13'))
        self.assertEqual(line.amount, Decimal('50.00'))

    def test_booked_job_lands_on_the_technicians_day(self):
        repair = self.make_repair(preferred_date=tomorrow())
        self.login_shop()
        self.post_book(repair)

        self.login_shop(self.tech_user)
        resp = self.client.get(
            reverse('day_schedule') + f'?date={tomorrow().isoformat()}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(repair.pk, [j.pk for j in resp.context['jobs']])
        # S2's dispatch actions ride along.
        self.assertContains(resp, 'data-map-query')

    def test_assigned_tech_is_notified_once(self):
        repair = self.make_repair()
        self.login_shop()
        mail.outbox = []
        TechnicianNotification.objects.all().delete()
        self.post_book(repair)

        rows = TechnicianNotification.objects.filter(technician=self.tech)
        self.assertEqual(rows.count(), 1)
        self.assertIn('Scheduled:', rows.first().message)
        schedule_mail = [m for m in mail.outbox if 'schedule changed' in m.subject.lower()]
        self.assertEqual(len(schedule_mail), 1)
        # No customer hears about it from this action.
        for message in mail.outbox:
            self.assertNotIn(self.cust_user.email, message.to)

    def test_no_notification_for_your_own_action(self):
        """A manager booking their own job does not email themselves."""
        repair = self.make_repair()
        Repair.objects.filter(pk=repair.pk).update(technician=self.owner_tech)
        TechnicianNotification.objects.all().delete()
        self.login_shop()
        self.post_book(repair)
        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.owner_tech).count(), 0)

    def test_whole_batch_books_as_one_visit(self):
        """One physical visit, one time. S7 refuses to drag a batch for the
        same reason; a per-row confirm would reintroduce the split."""
        import uuid
        batch_id = uuid.uuid4()
        breaks = []
        for n in range(1, 4):
            repair = Repair(
                tenant=self.tenant, customer=self.customer,
                technician=self.tech, unit_number='BATCH-1',
                queue_status='APPROVED', repair_batch_id=batch_id,
                break_number=n, total_breaks_in_batch=3,
            )
            repair.preferred_date = tomorrow()
            repair.save()
            breaks.append(repair)

        self.login_shop()
        resp = self.post_book(breaks[1])
        self.assertEqual(resp.status_code, 200)

        start, _end = window_bounds(tomorrow(), 'MORNING')
        for repair in breaks:
            repair.refresh_from_db()
            self.assertEqual(repair.scheduled_for, start)

    def test_stale_confirm_is_refused_and_writes_nothing(self):
        repair = self.make_repair()
        # Someone else booked it first.
        already, _ = window_bounds(tomorrow(), 'AFTERNOON')
        Repair.objects.filter(pk=repair.pk).update(scheduled_for=already)

        self.login_shop()
        resp = self.post_book(repair, window='MORNING', expected='')
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(json.loads(resp.content)['ok'])
        repair.refresh_from_db()
        self.assertEqual(repair.scheduled_for, already)

    def test_completed_job_is_refused(self):
        repair = self.make_repair(status='COMPLETED')
        self.login_shop()
        resp = self.post_book(repair)
        self.assertEqual(resp.status_code, 400)
        repair.refresh_from_db()
        self.assertIsNone(repair.scheduled_for)

    def test_other_tenant_job_is_refused_as_json(self):
        other_owner = User.objects.create_user(
            's4other', 's4other@test.com', 'TestPass123!')
        other = Tenant.objects.create(
            name='Other Shop', slug='s4other', subdomain='s4other',
            owner=other_owner, plan='trial', trial_started_at=timezone.now())
        other_tech = Technician.objects.create(
            user=other_owner, tenant=other, is_active=True, can_repair=True)
        stranger = Repair.objects.create(
            tenant=other, technician=other_tech, unit_number='X-1',
            queue_status='APPROVED')

        self.login_shop()
        resp = self.post_book(stranger)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp['Content-Type'], 'application/json')
        stranger.refresh_from_db()
        self.assertIsNone(stranger.scheduled_for)

    def test_technician_cannot_book_and_gets_json(self):
        repair = self.make_repair()
        self.login_shop(self.tech_user)
        resp = self.post_book(repair)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp['Content-Type'], 'application/json')
        repair.refresh_from_db()
        self.assertIsNone(repair.scheduled_for)

    def test_bad_payloads_answer_json(self):
        repair = self.make_repair()
        self.login_shop()
        for payload, status in (
            ({'type': 'repair', 'id': repair.pk, 'window': 'MORNING'}, 400),
            ({'type': 'repair', 'id': repair.pk,
              'date': tomorrow().isoformat(), 'window': 'LUNCH'}, 400),
            ({'type': 'spaceship', 'id': repair.pk,
              'date': tomorrow().isoformat(), 'window': 'MORNING'}, 400),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    reverse('schedule_book'), data=json.dumps(payload),
                    content_type='application/json')
            self.assertEqual(resp.status_code, status, payload)
            self.assertEqual(resp['Content-Type'], 'application/json')
        repair.refresh_from_db()
        self.assertIsNone(repair.scheduled_for)

    def test_replacement_can_be_booked_while_still_requested(self):
        """A replacement waits at REQUESTED for pricing; scheduling the visit
        is part of accepting it, so REQUESTED is bookable."""
        repl = Replacement(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-1', queue_status='REQUESTED',
        )
        repl.preferred_date = tomorrow()
        repl.save()

        self.login_shop()
        resp = self.post_book(repl, kind='replacement')
        self.assertEqual(resp.status_code, 200)
        repl.refresh_from_db()
        self.assertIsNotNone(repl.scheduled_for)


# =============================================================================
# Exact windows — the fleet case
# =============================================================================

class ExactWindowTests(S4Base):
    """"Morning" is not an answer when the truck rolls at 6:00.

    A fleet has to be able to say 4:30–5:45, the shop has to be able to book
    it to the minute, and the clock has to say whose timezone it is on.
    """

    suffix = '_exact'

    def test_customer_can_ask_for_a_window_to_the_minute(self):
        self.login_customer()
        day = tomorrow()
        self.post_request_repair(
            preferred_date=day.isoformat(), preferred_window='EXACT',
            preferred_time_start='04:30', preferred_time_end='05:45')

        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.preferred_window, 'EXACT')
        self.assertEqual(repair.preferred_time_start, time(4, 30))
        self.assertEqual(repair.preferred_time_end, time(5, 45))
        self.assertTrue(repair.has_exact_time_preference)
        # Still only a wish.
        self.assertIsNone(repair.scheduled_for)

    def test_the_shop_reads_back_a_clock_not_a_bucket(self):
        self.login_customer()
        self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='EXACT',
            preferred_time_start='04:30', preferred_time_end='05:45')
        repair = Repair.objects.get(customer=self.customer)
        summary = repair.get_time_preference()
        self.assertIn('4:30', summary)
        self.assertIn('5:45 AM', summary)
        self.assertNotIn('set window', summary)
        # An exact time is only unambiguous if you say whose clock it is on.
        self.assertIn(shop_timezone_label(), summary)

    def test_a_hard_cutoff_alone_is_enough(self):
        """"Done by 5:45" is a complete fleet request on its own."""
        self.login_customer()
        self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='EXACT',
            preferred_time_end='05:45')
        repair = Repair.objects.get(customer=self.customer)
        self.assertIsNone(repair.preferred_time_start)
        self.assertEqual(repair.preferred_time_end, time(5, 45))
        self.assertIn('by 5:45 AM', repair.get_time_preference())

    def test_backwards_window_keeps_the_usable_half(self):
        self.login_customer()
        self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='EXACT',
            preferred_time_start='09:00', preferred_time_end='07:00')
        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.preferred_time_start, time(9, 0))
        self.assertIsNone(repair.preferred_time_end)

    def test_exact_with_no_times_is_not_stored_as_a_window(self):
        """A bucket that lies about its own precision is worse than none."""
        self.login_customer()
        self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='EXACT')
        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.preferred_window, '')
        self.assertFalse(repair.has_exact_time_preference)

    def test_times_behind_a_preset_window_are_ignored(self):
        """A stale pair left in the POST must not override the preset."""
        self.login_customer()
        self.post_request_repair(
            preferred_date=tomorrow().isoformat(), preferred_window='MORNING',
            preferred_time_start='04:30', preferred_time_end='05:45')
        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.preferred_window, 'MORNING')
        self.assertIsNone(repair.preferred_time_start)
        self.assertIsNone(repair.preferred_time_end)

    def test_shop_books_the_exact_window(self):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-6', queue_status='APPROVED',
        )
        repair.preferred_date = tomorrow()
        repair.preferred_window = 'EXACT'
        repair.preferred_time_start = time(4, 30)
        repair.preferred_time_end = time(5, 45)
        repair.save()

        self.login_shop()
        resp = self.post_book(repair, window='EXACT',
                              start_time='04:30', end_time='05:45')
        self.assertEqual(resp.status_code, 200)

        repair.refresh_from_db()
        self.assertEqual(timezone.localtime(repair.scheduled_for).time(), time(4, 30))
        self.assertEqual(
            timezone.localtime(repair.scheduled_window_end).time(), time(5, 45))
        # The confirmation says the clock back, not the bucket name.
        self.assertIn('4:30', json.loads(resp.content)['message'])

    def test_booking_a_lone_cutoff_books_back_from_it(self):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-7', queue_status='APPROVED',
        )
        repair.save()
        self.login_shop()
        resp = self.post_book(repair, window='EXACT', end_time='06:00')
        self.assertEqual(resp.status_code, 200)
        repair.refresh_from_db()
        self.assertEqual(
            timezone.localtime(repair.scheduled_window_end).time(), time(6, 0))
        self.assertEqual(
            timezone.localtime(repair.scheduled_for).time(), time(5, 0))

    def test_booking_refuses_a_backwards_window(self):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-8', queue_status='APPROVED',
        )
        repair.save()
        self.login_shop()
        resp = self.post_book(repair, window='EXACT',
                              start_time='09:00', end_time='07:00')
        self.assertEqual(resp.status_code, 400)
        repair.refresh_from_db()
        self.assertIsNone(repair.scheduled_for)

    def test_booking_exact_with_no_times_is_refused(self):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-9', queue_status='APPROVED',
        )
        repair.save()
        self.login_shop()
        resp = self.post_book(repair, window='EXACT')
        self.assertEqual(resp.status_code, 400)
        repair.refresh_from_db()
        self.assertIsNone(repair.scheduled_for)

    def test_request_form_offers_the_specific_window(self):
        self.login_customer()
        for url in ('customer_request_repair', 'customer_request_replacement'):
            resp = self.client.get(reverse(url))
            self.assertContains(resp, 'A specific window', msg_prefix=url)
            self.assertContains(resp, 'name="preferred_time_start"', msg_prefix=url)
            self.assertContains(resp, 'name="preferred_time_end"', msg_prefix=url)
            self.assertContains(resp, 'Must be done by', msg_prefix=url)
            # The clock has to be labelled — there is no per-tenant timezone.
            self.assertContains(resp, shop_timezone_label(), msg_prefix=url)

    def test_rail_offers_the_shop_the_same_precision(self):
        """A fleet asking 4:30-5:45 and booked into "morning" is the same
        broken promise as never asking."""
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRK-10', queue_status='APPROVED',
        )
        repair.preferred_date = tomorrow()
        repair.preferred_window = 'EXACT'
        repair.preferred_time_start = time(4, 30)
        repair.preferred_time_end = time(5, 45)
        repair.save()

        self.login_shop()
        resp = self.client.get(reverse('day_schedule'))
        self.assertContains(resp, 'data-dispatch-start')
        self.assertContains(resp, 'value="04:30"')
        self.assertContains(resp, 'value="05:45"')
        # And the wish itself is shown as a clock.
        self.assertContains(resp, '4:30')


# =============================================================================
# Template priorities — the email S4's decision (b) depends on
# =============================================================================

@override_settings(**TEST_SETTINGS)
class TemplatePriorityTests(TestCase):
    """Migration 0009 seeded two templates with lowercase priorities.

    `get_delivery_channels()` compares against 'MEDIUM'/'HIGH'/'URGENT', so a
    lowercase value matched no branch and fell through to in-app only — the
    customer's "request received" email was rendered and discarded on every
    migration-seeded database. S4 echoes the requested time back in that
    email, so it has to actually send.
    """

    def test_no_template_carries_a_lowercase_priority(self):
        from django.apps import apps as django_apps

        NotificationTemplate = django_apps.get_model(
            'core', 'NotificationTemplate')
        offenders = [
            (t.name, t.default_priority)
            for t in NotificationTemplate.objects.all()
            if t.default_priority
            and t.default_priority != t.default_priority.upper()
        ]
        self.assertEqual(offenders, [])

    def test_request_received_actually_reaches_the_email_channel(self):
        from django.apps import apps as django_apps
        from core.models.notification import Notification

        NotificationTemplate = django_apps.get_model(
            'core', 'NotificationTemplate')
        template = NotificationTemplate.objects.get(
            name='repair_request_received')
        notification = Notification(
            priority=template.default_priority, template_id=template.pk)
        self.assertIn('email', notification.get_delivery_channels())


# =============================================================================
# Window arithmetic
# =============================================================================

@override_settings(**TEST_SETTINGS)
class WindowTests(TestCase):
    def test_window_bounds_are_local_wall_clock(self):
        day = date(2026, 9, 15)
        start, end = window_bounds(day, 'AFTERNOON')
        self.assertEqual(timezone.localtime(start).hour, 12)
        self.assertEqual(timezone.localtime(end).hour, 17)
        self.assertEqual(timezone.localtime(start).date(), day)

    def test_unknown_window_falls_back_to_anytime(self):
        day = date(2026, 9, 15)
        self.assertEqual(window_bounds(day, 'NOPE'), window_bounds(day, 'ANYTIME'))

    def test_confirm_requires_a_tenant(self):
        with self.assertRaises(BookingError) as ctx:
            confirm_appointment(
                tenant=None, service_type='repair', pk=1,
                day=date(2026, 9, 15), window='MORNING')
        self.assertEqual(ctx.exception.status, 403)
