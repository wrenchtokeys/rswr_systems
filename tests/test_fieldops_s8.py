"""FIELD_OPS S8 — technician working hours.

The rule under test everywhere below: an empty ``working_hours`` means
**undeclared**, never "never works". Every Technician row in production holds
``{}``, so a reader that gets that backwards would flag every job in every
shop the day this deploys.
"""

from datetime import date, datetime, time

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
