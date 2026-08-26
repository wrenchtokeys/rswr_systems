"""
Fieldops S3 — day / agenda view.

Covers the acceptance criteria in docs/strategy/FIELD_OPS_SESSIONS.md §S3:
`/tech/schedule/` shows the logged-in tech's day ordered by `scheduled_for`;
managers/owners see every tech's day grouped by technician plus a triage
rail of unscheduled work; entries link to job detail and carry S2's map/call
data attributes; empty states are honest about what's waiting.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Repair, Replacement
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


def local_day_at(hour, minute=0, day_offset=0):
    """An aware datetime at hour:minute local time, day_offset days from today."""
    local_now = timezone.localtime(timezone.now())
    target = (local_now + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    return target


@override_settings(**TEST_SETTINGS)
class DayScheduleBase(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_shop('S3 Shop', 's3owner@test.com')
        self.owner_tech = Technician.objects.get(user=self.owner, tenant=self.tenant)

        # A plain (non-manager) technician with portal access.
        self.tech_user = User.objects.create_user(
            's3_marcus', 's3marcus@test.com', 'testpass123!',
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
            address='500 Depot Rd', city='Little Rock', state='AR',
            zip_code='72201',
        )
        self.client = Client()
        self.url = reverse('day_schedule')

    def make_repair(self, technician, status='APPROVED', scheduled=None, **kwargs):
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=technician,
            queue_status=status, unit_number=kwargs.pop('unit_number', 'U-1'),
            **kwargs,
        )
        repair.scheduled_for = scheduled
        repair.save()
        return repair


class TechnicianDayViewTests(DayScheduleBase):
    """A plain tech sees exactly their own day."""

    def setUp(self):
        super().setUp()
        login(self.client, self.tech_user, self.tenant)

    def test_requires_login(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_own_scheduled_jobs_in_time_order(self):
        late = self.make_repair(self.tech, scheduled=local_day_at(14), unit_number='PM-1')
        early = self.make_repair(self.tech, scheduled=local_day_at(8), unit_number='AM-1')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        jobs = response.context['jobs']
        self.assertEqual([j.pk for j in jobs], [early.pk, late.pk])
        content = response.content.decode()
        self.assertLess(content.index('AM-1'), content.index('PM-1'))

    def test_other_techs_jobs_hidden(self):
        self.make_repair(self.owner_tech, scheduled=local_day_at(9), unit_number='OTHER-9')
        response = self.client.get(self.url)
        self.assertNotContains(response, 'OTHER-9')
        # And no per-tech grouping for a plain tech.
        self.assertIsNone(response.context['groups'])
        self.assertFalse(response.context['sees_whole_shop'])

    def test_tomorrow_only_shows_under_its_date(self):
        tomorrow = local_day_at(10, day_offset=1)
        self.make_repair(self.tech, scheduled=tomorrow, unit_number='TMRW-1')
        today_response = self.client.get(self.url)
        self.assertNotContains(today_response, 'TMRW-1')
        response = self.client.get(
            self.url, {'date': tomorrow.date().isoformat()})
        self.assertContains(response, 'TMRW-1')
        self.assertFalse(response.context['is_today'])

    def test_invalid_date_falls_back_to_today(self):
        response = self.client.get(self.url, {'date': 'not-a-date'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_today'])

    def test_completed_jobs_stay_on_the_sheet(self):
        self.make_repair(
            self.tech, status='COMPLETED', scheduled=local_day_at(8),
            unit_number='DONE-1')
        response = self.client.get(self.url)
        self.assertContains(response, 'DONE-1')
        self.assertEqual(response.context['done_count'], 1)

    def test_unscheduled_requested_jobs_are_not_on_the_sheet(self):
        # A customer request holds a provisional tech; until somebody gives it
        # a time it is not a visit, and it belongs in triage rather than on a
        # day. This is S3's original rule and it still holds — note the job
        # has NO scheduled_for.
        self.make_repair(
            self.tech, status='REQUESTED', scheduled=None, unit_number='REQ-1')
        response = self.client.get(self.url)
        self.assertNotContains(response, 'REQ-1')

    def test_requested_job_with_a_booked_time_IS_on_the_sheet(self):
        # Changed by S10, deliberately. This test used to assert the opposite,
        # with a fixture identical to this one — and that assertion was the
        # bug: the day sheet excluded REQUESTED while the triage rail selects
        # on `scheduled_for IS NULL`, so a REQUESTED job that had been given a
        # time appeared in NEITHER list. It was invisible.
        #
        # A REQUESTED job cannot acquire a `scheduled_for` by accident. The
        # customer's wish lives in preferred_date/preferred_window and the
        # portal never writes scheduled_for (S4, customer_portal/views.py).
        # The only way this state exists is that somebody in the shop booked
        # it — so it belongs on the sheet, marked, which the status badge
        # already does. Booking still does not promote it to APPROVED.
        self.make_repair(
            self.tech, status='REQUESTED', scheduled=local_day_at(11),
            unit_number='REQ-1')
        response = self.client.get(self.url)
        self.assertContains(response, 'REQ-1')
        self.assertContains(response, 'Customer Requested')

    def test_empty_state_counts_unscheduled_jobs(self):
        self.make_repair(self.tech, scheduled=None, unit_number='NOSLOT-1')
        self.make_repair(self.tech, scheduled=None, unit_number='NOSLOT-2')
        response = self.client.get(self.url)
        self.assertContains(response, 'Nothing scheduled')
        self.assertContains(response, '2 unscheduled jobs')
        self.assertContains(response, reverse('job_list'))
        # Plain techs get a count, not the manager triage rail.
        self.assertEqual(response.context['triage_jobs'], [])

    def test_map_and_call_attrs_but_no_server_side_maps_url(self):
        self.make_repair(self.tech, scheduled=local_day_at(9))
        response = self.client.get(self.url)
        content = response.content.decode()
        self.assertIn('data-map-query="500 Depot Rd, Little Rock, AR 72201"', content)
        self.assertIn('data-call-number="501-555-0100"', content)
        self.assertNotIn('google.com/maps', content)
        self.assertIn('js/field_dispatch.js', content)

    def test_entry_links_to_job_detail(self):
        repair = self.make_repair(self.tech, scheduled=local_day_at(9))
        response = self.client.get(self.url)
        self.assertContains(response, reverse('repair_detail', args=[repair.pk]))

    def test_scheduled_replacement_appears(self):
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            queue_status='APPROVED', unit_number='REPL-1',
            scheduled_for=local_day_at(13),
        )
        response = self.client.get(self.url)
        self.assertContains(response, 'REPL-1')
        self.assertContains(
            response, reverse('replacement_detail', args=[replacement.pk]))


class ManagerDayViewTests(DayScheduleBase):
    """Owners/managers see every tech's day plus the triage rail."""

    def setUp(self):
        super().setUp()
        login(self.client, self.owner, self.tenant)

    def test_sees_all_techs_grouped(self):
        self.make_repair(self.owner_tech, scheduled=local_day_at(9), unit_number='OWN-9')
        self.make_repair(self.tech, scheduled=local_day_at(10), unit_number='MARCUS-10')
        response = self.client.get(self.url)
        self.assertContains(response, 'OWN-9')
        self.assertContains(response, 'MARCUS-10')
        self.assertContains(response, 'Marcus Field')
        groups = response.context['groups']
        self.assertEqual(len(groups), 2)
        # The viewer's own group leads.
        self.assertEqual(groups[0]['technician'].pk, self.owner_tech.pk)

    def test_free_tech_still_listed(self):
        # A tech with nothing booked shows up as free, not missing.
        self.make_repair(self.owner_tech, scheduled=local_day_at(9))
        response = self.client.get(self.url)
        self.assertContains(response, 'Marcus Field')
        self.assertContains(response, 'Nothing scheduled')

    def test_triage_rail_lists_unscheduled_and_requested(self):
        self.make_repair(self.tech, scheduled=None, unit_number='RAIL-1')
        self.make_repair(
            self.tech, status='REQUESTED', scheduled=None, unit_number='RAIL-REQ')
        response = self.client.get(self.url)
        self.assertContains(response, 'Needs scheduling')
        self.assertContains(response, 'RAIL-1')
        self.assertContains(response, 'RAIL-REQ')

    def test_completed_jobs_stay_off_the_rail(self):
        self.make_repair(
            self.tech, status='COMPLETED', scheduled=None, unit_number='OLDDONE')
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Needs scheduling')
        self.assertNotContains(response, 'OLDDONE')


@override_settings(**TEST_SETTINGS)
class TenantIsolationTests(TestCase):
    def test_other_shops_schedule_is_invisible(self):
        owner_a, tenant_a = make_shop('S3 Shop A', 's3a@test.com')
        owner_b, tenant_b = make_shop('S3 Shop B', 's3b@test.com')
        tech_b = Technician.objects.get(user=owner_b, tenant=tenant_b)
        customer_b = Customer.objects.create(name='B Fleet', tenant=tenant_b)
        repair = Repair(
            tenant=tenant_b, customer=customer_b, technician=tech_b,
            queue_status='APPROVED', unit_number='B-SECRET',
        )
        repair.scheduled_for = local_day_at(9)
        repair.save()

        client = Client()
        login(client, owner_a, tenant_a)
        response = client.get(reverse('day_schedule'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'B-SECRET')


@override_settings(**TEST_SETTINGS)
class NavigationTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_shop('S3 Nav Shop', 's3nav@test.com')
        self.client = Client()
        login(self.client, self.owner, self.tenant)

    def test_nav_carries_schedule_link(self):
        response = self.client.get(reverse('technician_dashboard'))
        self.assertContains(response, reverse('day_schedule'))

    def test_today_bucket_header_links_to_schedule(self):
        tech = Technician.objects.get(user=self.owner, tenant=self.tenant)
        customer = Customer.objects.create(name='Nav Fleet', tenant=self.tenant)
        repair = Repair(
            tenant=self.tenant, customer=customer, technician=tech,
            queue_status='IN_PROGRESS',
        )
        repair.scheduled_for = local_day_at(9)
        repair.save()
        response = self.client.get(reverse('technician_dashboard'))
        content = response.content.decode()
        self.assertIn(
            'href="%s"' % reverse('day_schedule'), content)

    def test_date_navigator_present(self):
        response = self.client.get(reverse('day_schedule'))
        self.assertContains(response, 'schedule-date')
        self.assertContains(response, 'date=%s' % (
            timezone.localtime(timezone.now()).date() + timedelta(days=1)
        ).isoformat())
