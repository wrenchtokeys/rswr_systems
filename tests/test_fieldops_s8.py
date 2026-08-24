"""FIELD_OPS S8 — technician working hours.

The rule under test everywhere below: an empty ``working_hours`` means
**undeclared**, never "never works". Every Technician row in production holds
``{}``, so a reader that gets that backwards would flag every job in every
shop the day this deploys.
"""

from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants.services.team_service import add_team_member
from apps.technician_portal.models import Technician
from apps.technician_portal.services import working_hours as wh


MON_FRI = {
    'monday': ['08:00', '17:00'],
    'tuesday': ['08:00', '17:00'],
    'wednesday': ['08:00', '17:00'],
    'thursday': ['08:00', '17:00'],
    'friday': ['08:00', '17:00'],
    'saturday': None,
    'sunday': None,
}

# 2026-08-17 is a Monday; 2026-08-18 a Tuesday; 2026-08-22 a Saturday.
MONDAY = date(2026, 8, 17)
TUESDAY = date(2026, 8, 18)
SATURDAY = date(2026, 8, 22)


def _aware(day, clock):
    return timezone.make_aware(
        datetime.combine(day, clock), timezone.get_current_timezone())


class WorkingHoursReadingTests(TestCase):
    """The parser. Total, forgiving, and undeclared-by-default."""

    def test_empty_is_undeclared(self):
        self.assertFalse(wh.is_declared({}))
        self.assertEqual(wh.read({}), {})
        self.assertEqual(wh.summary({}), '')

    def test_none_and_garbage_are_undeclared_not_crashes(self):
        # The admin exposes a raw JSON textarea in production, so all of these
        # are reachable. None of them may raise, and none may read as "off".
        for raw in (None, [], 'nope', 42, {'monday': 'all day'},
                    {'notaday': ['08:00', '17:00']}, {'monday': ['bad', 'worse']},
                    {'monday': ['17:00', '08:00']}, {'monday': ['08:00']},
                    {'monday': {'start': '25:00', 'end': '17:00'}}):
            with self.subTest(raw=raw):
                self.assertEqual(wh.read(raw), {})
                self.assertFalse(wh.is_declared(raw))
                self.assertIsNone(wh.covers(raw, _aware(MONDAY, time(9, 0)),
                                            _aware(MONDAY, time(10, 0))))

    def test_reads_the_shape_the_admin_documents(self):
        # Single-digit hour: exactly how the admin help text spells it, so any
        # hand-entered production row looks like this.
        parsed = wh.read({'monday': ['9:00', '17:00']})
        self.assertEqual(parsed, {0: (time(9, 0), time(17, 0))})

    def test_dict_form_and_case_insensitive_keys(self):
        parsed = wh.read({'MONDAY': {'start': '07:30', 'end': '16:00'}})
        self.assertEqual(parsed, {0: (time(7, 30), time(16, 0))})

    def test_partial_garbage_keeps_the_good_days(self):
        parsed = wh.read({'monday': ['08:00', '17:00'], 'tuesday': 'whenever'})
        self.assertEqual(set(parsed), {0})

    def test_hours_on_and_is_off_on(self):
        self.assertEqual(wh.hours_on(MON_FRI, MONDAY), (time(8, 0), time(17, 0)))
        self.assertIsNone(wh.hours_on(MON_FRI, SATURDAY))
        self.assertTrue(wh.is_off_on(MON_FRI, SATURDAY))
        self.assertFalse(wh.is_off_on(MON_FRI, MONDAY))

    def test_undeclared_is_never_off(self):
        # "Off" is a claim; an empty record makes no claim at all.
        self.assertFalse(wh.is_off_on({}, SATURDAY))

    def test_covers(self):
        inside = wh.covers(MON_FRI, _aware(MONDAY, time(9, 0)),
                           _aware(MONDAY, time(10, 0)))
        self.assertIs(inside, True)
        early = wh.covers(MON_FRI, _aware(MONDAY, time(4, 30)),
                          _aware(MONDAY, time(5, 45)))
        self.assertIs(early, False)
        weekend = wh.covers(MON_FRI, _aware(SATURDAY, time(9, 0)),
                            _aware(SATURDAY, time(10, 0)))
        self.assertIs(weekend, False)

    def test_covers_returns_none_when_nothing_is_on_file(self):
        # None, not False: the caller must stay silent rather than warn.
        self.assertIsNone(wh.covers({}, _aware(MONDAY, time(4, 30)),
                                    _aware(MONDAY, time(5, 45))))

    def test_covers_is_evaluated_in_local_time(self):
        # 4:30 AM Central is 9:30 UTC — comparing the UTC clock would call this
        # "inside 8-5" and quietly bless the exact case S8 exists to flag.
        start = _aware(MONDAY, time(4, 30))
        self.assertEqual(timezone.localtime(start).hour, 4)
        self.assertIs(wh.covers(MON_FRI, start, _aware(MONDAY, time(5, 45))), False)

    def test_booking_across_midnight_is_never_covered(self):
        self.assertIs(
            wh.covers(MON_FRI, _aware(MONDAY, time(23, 0)),
                      _aware(TUESDAY, time(1, 0))),
            False)

    def test_summary_collapses_consecutive_days(self):
        self.assertEqual(wh.summary(MON_FRI), 'Mon–Fri 8:00 AM – 5:00 PM')
        mixed = dict(MON_FRI, saturday=['09:00', '12:00'])
        self.assertEqual(
            wh.summary(mixed),
            'Mon–Fri 8:00 AM – 5:00 PM · Sat 9:00 AM – 12:00 PM')
        self.assertEqual(wh.summary({'wednesday': ['08:00', '17:00']}),
                         'Wed 8:00 AM – 5:00 PM')

    def test_to_storage_round_trips(self):
        stored = wh.to_storage({0: (time(7, 0), time(16, 0))})
        self.assertEqual(stored['monday'], ['07:00', '16:00'])
        self.assertIsNone(stored['sunday'])
        self.assertEqual(wh.read(stored), {0: (time(7, 0), time(16, 0))})

    def test_editor_rows_prefill_without_declaring(self):
        rows = wh.editor_rows({})
        self.assertFalse(rows['declared'])
        self.assertEqual(len(rows['rows']), 7)
        # Pre-filled Mon-Fri 8-5 but every box unchecked: opening the form
        # must not be the same as agreeing to hours.
        self.assertTrue(all(not row['works'] for row in rows['rows']))
        self.assertEqual(rows['rows'][0]['start'], '08:00')

    def test_editor_rows_reflect_stored_hours(self):
        rows = wh.editor_rows(dict(MON_FRI, monday=['07:00', '16:00']))
        self.assertTrue(rows['declared'])
        self.assertTrue(rows['rows'][0]['works'])
        self.assertEqual(rows['rows'][0]['start'], '07:00')
        self.assertFalse(rows['rows'][5]['works'])  # Saturday


class TechnicianHelperTests(TestCase):
    """The model delegates, on a real row."""

    @classmethod
    def setUpTestData(cls):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
                      'is_active': True})
        result = create_tenant_with_owner(
            business_name='Hours Shop', email='hours-owner@test.com',
            password='testpass123!', first_name='Hank', last_name='Owner')
        cls.tenant = result['tenant']
        cls.user = result['user']
        cls.tech = Technician.objects.get(user=cls.user, tenant=cls.tenant)

    def test_a_fresh_technician_has_no_hours(self):
        # Signup creates the owner's technician record; nothing sets hours.
        self.assertEqual(self.tech.working_hours, {})
        self.assertFalse(self.tech.has_working_hours)
        self.assertEqual(self.tech.working_hours_summary, '')
        self.assertFalse(self.tech.is_off_on(SATURDAY))
        self.assertIsNone(self.tech.works_during(_aware(SATURDAY, time(9, 0)),
                                                 _aware(SATURDAY, time(10, 0))))

    def test_declared_hours_answer_all_four_questions(self):
        self.tech.working_hours = dict(MON_FRI, monday=['07:00', '16:00'])
        self.tech.save(update_fields=['working_hours'])
        self.tech.refresh_from_db()

        self.assertTrue(self.tech.has_working_hours)
        self.assertIn('Mon 7:00 AM', self.tech.working_hours_summary)
        self.assertEqual(self.tech.working_hours_on(MONDAY),
                         (time(7, 0), time(16, 0)))
        self.assertTrue(self.tech.is_off_on(SATURDAY))
        self.assertIs(
            self.tech.works_during(_aware(MONDAY, time(4, 30)),
                                   _aware(MONDAY, time(5, 45))),
            False)


def _hours_post(**days):
    """Form payload: ``_hours_post(monday=('08:00', '17:00'))``."""
    payload = {}
    for key, window in days.items():
        payload[f'works_{key}'] = 'on'
        payload[f'start_{key}'], payload[f'end_{key}'] = window
    return payload


class TeamHoursEndpointTests(TestCase):
    """POST /owner/team/<id>/hours/ — its own endpoint, on purpose."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
                      'is_active': True})
        result = create_tenant_with_owner(
            business_name='Hours Shop', email='owner@hours.test',
            password='testpass123!', first_name='Olive', last_name='Owner')
        self.tenant = result['tenant']
        self.owner = result['user']
        self.owner_membership = TenantMembership.objects.get(
            tenant=self.tenant, user=self.owner)

        self.tech_membership = self._add_member('dana@hours.test', 'Dana',
                                                'technician')
        self.tech = Technician.objects.get(user=self.tech_membership.user,
                                           tenant=self.tenant)
        self.manager_membership = self._add_member('mo@hours.test', 'Mo',
                                                   'manager')

        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _add_member(self, email, first_name, role):
        add_team_member(
            self.tenant, self.owner, email=email, first_name=first_name,
            last_name='Tech', role=role)
        return TenantMembership.objects.get(tenant=self.tenant,
                                            user__email__iexact=email)

    def _url(self, membership):
        return f'/owner/team/{membership.id}/hours/'

    def _login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    # --- the happy path ---------------------------------------------------

    def test_owner_sets_hours_for_a_technician(self):
        response = self.client.post(self._url(self.tech_membership), _hours_post(
            monday=('07:00', '16:00'), tuesday=('07:00', '16:00'),
            wednesday=('07:00', '16:00'), thursday=('07:00', '16:00'),
            friday=('07:00', '16:00')))
        self.assertEqual(response.status_code, 302)

        self.tech.refresh_from_db()
        self.assertEqual(self.tech.working_hours['monday'], ['07:00', '16:00'])
        # Days off are written as explicit null, not omitted, so the stored
        # row reads the same way in the admin box as in the editor.
        self.assertIsNone(self.tech.working_hours['saturday'])
        self.assertEqual(self.tech.working_hours_summary,
                         'Mon–Fri 7:00 AM – 4:00 PM')

    def test_unchecking_every_day_clears_back_to_undeclared(self):
        self.tech.working_hours = MON_FRI
        self.tech.save(update_fields=['working_hours'])

        self.client.post(self._url(self.tech_membership), {})

        self.tech.refresh_from_db()
        self.assertEqual(self.tech.working_hours, {})
        self.assertFalse(self.tech.has_working_hours)
        # Cleared means "available whenever", never "off every day".
        self.assertFalse(self.tech.is_off_on(MONDAY))

    def test_owner_can_set_their_own_hours(self):
        self.client.post(self._url(self.owner_membership),
                         _hours_post(monday=('06:00', '14:00')))
        owner_tech = Technician.objects.get(user=self.owner, tenant=self.tenant)
        self.assertTrue(owner_tech.has_working_hours)

    # --- refusals ---------------------------------------------------------

    def test_end_before_start_is_refused_and_writes_nothing(self):
        response = self.client.post(self._url(self.tech_membership),
                                    _hours_post(monday=('17:00', '08:00')))
        self.assertEqual(response.status_code, 302)
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.working_hours, {})

    def test_a_checked_day_with_no_times_is_refused(self):
        response = self.client.post(
            self._url(self.tech_membership),
            {'works_monday': 'on', 'start_monday': '', 'end_monday': ''})
        self.assertEqual(response.status_code, 302)
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.working_hours, {})

    def test_one_bad_day_does_not_half_apply_the_others(self):
        payload = _hours_post(monday=('08:00', '17:00'))
        payload.update(_hours_post(tuesday=('17:00', '08:00')))
        self.client.post(self._url(self.tech_membership), payload)
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.working_hours, {})

    def test_get_is_not_allowed(self):
        self.assertEqual(
            self.client.get(self._url(self.tech_membership)).status_code, 405)

    def test_manager_cannot_edit_a_peer_manager(self):
        # CODE-212, mirrored from update_team_member: the second door to the
        # same data must not be the weaker one.
        peer = self._add_member('peer@hours.test', 'Peer', 'manager')
        self.manager_membership.user.set_password('testpass123!')
        self.manager_membership.user.save()
        self._login(self.manager_membership.user)

        self.client.post(self._url(peer), _hours_post(monday=('08:00', '17:00')))

        peer_tech = Technician.objects.get(user=peer.user, tenant=self.tenant)
        self.assertEqual(peer_tech.working_hours, {})

    def test_manager_can_edit_a_technician(self):
        self._login(self.manager_membership.user)
        self.client.post(self._url(self.tech_membership),
                         _hours_post(monday=('08:00', '17:00')))
        self.tech.refresh_from_db()
        self.assertTrue(self.tech.has_working_hours)

    def test_another_tenants_membership_is_a_404(self):
        other = create_tenant_with_owner(
            business_name='Other Shop', email='other@hours.test',
            password='testpass123!', first_name='Otto', last_name='Owner')
        other_membership = TenantMembership.objects.get(
            tenant=other['tenant'], user=other['user'])

        response = self.client.post(self._url(other_membership),
                                    _hours_post(monday=('08:00', '17:00')))
        self.assertEqual(response.status_code, 404)

    def test_member_without_a_technician_record_is_refused(self):
        viewer = self._add_member('viewer@hours.test', 'Vee', 'viewer')
        self.assertFalse(
            Technician.objects.filter(user=viewer.user, tenant=self.tenant).exists())
        response = self.client.post(self._url(viewer),
                                    _hours_post(monday=('08:00', '17:00')))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Technician.objects.filter(user=viewer.user, tenant=self.tenant).exists())


class TeamSettingsPageTests(TestCase):
    """What the My Team tab shows before anybody has set anything."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
                      'is_active': True})
        result = create_tenant_with_owner(
            business_name='Hours Shop', email='owner@page.test',
            password='testpass123!', first_name='Olive', last_name='Owner')
        self.tenant = result['tenant']
        self.owner = result['user']
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_page_offers_to_set_hours_and_says_what_blank_means(self):
        response = self.client.get('/owner/settings/?tab=team')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Working hours not set', body)
        self.assertIn('treated as available any time', body)
        self.assertIn('Set hours', body)
        self.assertIn('works_monday', body)

    def test_page_shows_the_summary_once_hours_exist(self):
        tech = Technician.objects.get(user=self.owner, tenant=self.tenant)
        tech.working_hours = MON_FRI
        tech.save(update_fields=['working_hours'])

        body = self.client.get('/owner/settings/?tab=team').content.decode()
        self.assertIn('Mon–Fri 8:00 AM – 5:00 PM', body)
        self.assertIn('Edit hours', body)


# =============================================================================
# The board half — what the dispatch screen does with the hours (S8)
#
# The foundation above stores and reads hours; these are the four consumers
# S8 exists for. Every one of them has to stay silent for an undeclared
# technician, so each has a paired "and nothing happens when {}" assertion
# rather than one blanket test.
# =============================================================================

from django.urls import reverse  # noqa: E402  (board half, added after S5)

from apps.technician_portal.services.schedule_conflicts import (  # noqa: E402
    annotate_conflicts, describe_outside_hours, technician_load,
)
from tests.test_fieldops_s5 import S5Base  # noqa: E402


class BoardHoursBase(S5Base):
    """S5's shop, plus a way to say when Marcus works.

    Reuses S5Base on purpose: the board is S5's screen, and a divergent
    fixture here would test a shop that doesn't exist.
    """

    suffix = '_s8board'

    def declare(self, tech=None, hours=None):
        tech = tech or self.tech
        tech.working_hours = MON_FRI if hours is None else hours
        tech.save(update_fields=['working_hours'])
        tech.refresh_from_db()
        return tech

    def booked(self, day, start, end, *, technician=None):
        return self.make_repair(
            unit='UNIT-H', technician=technician or self.tech,
            scheduled_for=_aware(day, start), window_end=_aware(day, end))


class OutsideHoursChipTests(BoardHoursBase):
    """Signal 4: one short chip, and only when the shop has an opinion."""

    def test_undeclared_technician_is_never_flagged(self):
        # The case that is every row in production. 4:30 AM on a Saturday is
        # as far outside a normal week as a booking gets, and the board must
        # still say nothing about a person nobody described.
        job = self.booked(SATURDAY, time(4, 30), time(5, 45))
        annotate_conflicts([job])
        self.assertEqual(job.conflicts, [])
        self.assertEqual(describe_outside_hours(job), '')

    def test_booking_before_the_shift_is_flagged_with_the_hours(self):
        self.declare()
        job = self.booked(MONDAY, time(4, 30), time(5, 45))
        annotate_conflicts([job])
        self.assertEqual(len(job.conflicts), 1)
        self.assertIn("Outside Marcus's hours", job.conflicts[0])
        self.assertIn('8:00 AM', job.conflicts[0])

    def test_booking_that_runs_past_the_shift_is_flagged(self):
        self.declare()
        job = self.booked(MONDAY, time(16, 30), time(18, 0))
        annotate_conflicts([job])
        self.assertEqual(len(job.conflicts), 1)
        self.assertIn("Outside Marcus's hours", job.conflicts[0])

    def test_a_day_off_names_the_weekday_not_the_date(self):
        # "off Saturdays" is the standing fact and reads the same next week;
        # the date is already on the screen.
        self.declare()
        job = self.booked(SATURDAY, time(9, 0), time(10, 0))
        annotate_conflicts([job])
        self.assertEqual(job.conflicts, ['Marcus is off Saturdays'])

    def test_inside_declared_hours_says_nothing(self):
        self.declare()
        job = self.booked(MONDAY, time(9, 0), time(10, 0))
        annotate_conflicts([job])
        self.assertEqual(job.conflicts, [])

    def test_the_shift_edges_are_inclusive(self):
        self.declare()
        job = self.booked(MONDAY, time(8, 0), time(17, 0))
        annotate_conflicts([job])
        self.assertEqual(job.conflicts, [])

    def test_hours_are_wall_clock_not_utc(self):
        # The bug this session refused to inherit: ReviewConfig compares the
        # UTC hour of an aware datetime and sends review emails at 4 AM local.
        # 8:30 AM Central is 13:30 UTC — a UTC comparison would flag it.
        self.declare()
        job = self.booked(MONDAY, time(8, 30), time(9, 30))
        self.assertEqual(timezone.localtime(job.scheduled_for).hour, 8)
        annotate_conflicts([job])
        self.assertEqual(job.conflicts, [])

    def test_garbage_in_the_admin_box_degrades_to_undeclared(self):
        # working_hours is a raw JSON textarea in Django admin, reachable in
        # production. Nonsense must read as "no hours", never as an exception
        # on a screen a shop runs its morning from.
        for junk in ('nine to five', ['monday'], {'monday': 'all day'},
                     {'funday': ['08:00', '17:00']}, {'monday': ['17:00', '08:00']}):
            with self.subTest(junk=junk):
                self.tech.working_hours = junk
                self.tech.save(update_fields=['working_hours'])
                job = self.booked(SATURDAY, time(4, 30), time(5, 45))
                annotate_conflicts([job])
                self.assertEqual(job.conflicts, [])

    def test_the_hours_chip_sits_beside_the_other_signals(self):
        # One row, two true facts: booked outside the shift AND off what the
        # customer asked for. Both print — S5's discipline is one chip per
        # *signal*, not one per row.
        self.declare()
        job = self.booked(MONDAY, time(4, 30), time(5, 45))
        job.preferred_date = MONDAY
        job.preferred_window = 'AFTERNOON'
        job.save(update_fields=['preferred_date', 'preferred_window'])
        annotate_conflicts([job])
        self.assertEqual(len(job.conflicts), 2)
        self.assertTrue(any('Asked for' in c for c in job.conflicts))
        self.assertTrue(any("Marcus's hours" in c for c in job.conflicts))


class LoadAgainstHoursTests(BoardHoursBase):
    """Capacity measured against the clock the shop declared."""

    def test_span_stays_the_denominator_when_nothing_is_declared(self):
        rows = [self.booked(MONDAY, time(8, 0), time(8, 30)),
                self.booked(MONDAY, time(8, 30), time(9, 0))]
        load = technician_load(rows)
        self.assertEqual(load['basis'], 'span')
        self.assertIsNone(load['available_hours'])
        # Two nominal hours of work inside a one-hour span. The span is a weak
        # denominator and this is exactly its false positive — kept, because
        # for an undeclared tech it is the only honest number available.
        self.assertTrue(load['over_committed'])

    def test_declared_hours_clear_the_span_false_positive(self):
        self.declare()
        rows = [self.booked(MONDAY, time(8, 0), time(8, 30)),
                self.booked(MONDAY, time(8, 30), time(9, 0))]
        load = technician_load(rows)
        self.assertEqual(load['basis'], 'hours')
        self.assertEqual(load['available_hours'], 9)
        self.assertFalse(load['over_committed'])
        self.assertIn('on the clock', load['summary'])

    def test_declared_hours_catch_what_the_span_misses(self):
        # Three jobs stretched across a short shift: the span says 4h into 4h
        # and shrugs; the declared 08:00-11:00 shift says three hours of work
        # do not fit in three hours once they are spread over four.
        self.declare(hours=dict(MON_FRI, monday=['08:00', '10:00']))
        rows = [self.booked(MONDAY, time(8, 0), time(9, 0)),
                self.booked(MONDAY, time(9, 0), time(10, 0)),
                self.booked(MONDAY, time(10, 30), time(11, 30))]
        load = technician_load(rows)
        self.assertEqual(load['basis'], 'hours')
        self.assertEqual(load['available_hours'], 2)
        self.assertTrue(load['over_committed'])
        self.assertIn('3h of work', load['summary'])
        self.assertIn('2h on the clock', load['summary'])

    def test_work_on_a_day_off_reads_as_a_day_off(self):
        self.declare()
        rows = [self.booked(SATURDAY, time(9, 0), time(10, 0))]
        load = technician_load(rows)
        self.assertEqual(load['basis'], 'day_off')
        self.assertTrue(load['over_committed'])
        self.assertEqual(load['summary'], '1h of work on a day off')

    def test_an_empty_day_is_still_none(self):
        self.declare()
        self.assertIsNone(technician_load([]))


class BoardRenderTests(BoardHoursBase):
    """What the manager actually sees at /tech/schedule/."""

    def _board(self, day):
        self.login_shop(self.owner)
        return self.client.get(
            reverse('day_schedule'), {'date': day.isoformat()})

    def _populate(self, day):
        """Give the day one job belonging to somebody else.

        The board renders per-technician groups only once the day has work in
        it — an empty day gets S3's single "Nothing scheduled today" panel
        instead. "Off today" is a *group* line, so it needs a day that exists.
        """
        return self.booked(day, time(9, 0), time(10, 0),
                           technician=self.other_tech)

    def test_off_today_replaces_nothing_scheduled(self):
        # The highest-value line in the session: a gap to fill and a person
        # who isn't working look identical without hours, and lead to
        # opposite decisions.
        self.declare()
        self._populate(SATURDAY)
        response = self._board(SATURDAY)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Off Sat Aug 22', body)

    def test_undeclared_technician_still_reads_nothing_scheduled(self):
        self._populate(SATURDAY)
        response = self._board(SATURDAY)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Nothing scheduled', body)
        self.assertNotIn('Off Sat Aug 22', body)

    def test_the_header_prints_the_declared_shift(self):
        self.declare()
        self._populate(MONDAY)
        response = self._board(MONDAY)
        self.assertIn('8:00 AM – 5:00 PM', response.content.decode())

    def test_an_off_duty_tech_is_marked_in_the_picker_not_removed(self):
        # A shop with one truck down calls somebody in on their day off. The
        # picker that hides them reads as broken.
        self.declare()
        self.make_repair(unit='UNIT-RAIL', status='REQUESTED')
        response = self._board(SATURDAY)
        body = response.content.decode()
        self.assertIn('— off Sat', body)
        self.assertIn(f'value="{self.tech.pk}"', body)

    def test_the_picker_is_unmarked_when_nobody_declared_hours(self):
        self.make_repair(unit='UNIT-RAIL', status='REQUESTED')
        response = self._board(SATURDAY)
        body = response.content.decode()
        self.assertNotIn('— off', body)
        self.assertIn(f'value="{self.tech.pk}"', body)

    def test_the_board_survives_nonsense_hours(self):
        self.tech.working_hours = 'whenever he feels like it'
        self.tech.save(update_fields=['working_hours'])
        self.booked(SATURDAY, time(4, 30), time(5, 45))
        response = self._board(SATURDAY)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Outside', response.content.decode())

    def test_booking_outside_hours_still_succeeds(self):
        # Informational, exactly like S5's other three signals: a shop that
        # calls somebody in on their day off is allowed to.
        self.declare()
        job = self.make_repair(unit='UNIT-BOOK', status='REQUESTED')
        self.login_shop(self.owner)
        # A real future Saturday: the booking endpoint is a write path, and
        # this test is about the hours signal not blocking it, not about
        # whatever it thinks of dates in the past.
        today = timezone.localtime(timezone.now()).date()
        saturday = today + timedelta(days=((5 - today.weekday()) % 7) or 7)
        response = self.post_dispatch(
            job, date=saturday.isoformat(), window='EXACT',
            start_time='04:30', end_time='05:45', technician_id=self.tech.pk)
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertIsNotNone(job.scheduled_for)
