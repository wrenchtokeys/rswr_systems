"""
Fieldops S10 — quick-add a job from the schedule.

Covers docs/strategy/FIELD_OPS_SESSIONS.md §S10.

The motion: a customer calls, and the shop puts them on tomorrow without
leaving /tech/schedule/. Before this it took Jobs → New Job → save → land on
the job ticket → navigate to Schedule → find it in the rail → set
date/window/tech → Book.

The load-bearing assertion in here is `test_priced_identically_to_the_form`:
the endpoint and the form must produce the same job, because the whole risk
of this session is that extracting job_create's inline logic into
services/quick_job.py lets the two drift on money or on status.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_shop(business_name, email, services='both'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'display_order': 0, 'is_active': True},
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


@override_settings(**TEST_SETTINGS)
class QuickJobEndpointTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S10 Shop', 's10@test.com')
        self.customer = Customer.objects.create(
            name='Jones Fleet', tenant=self.tenant, email='jones@s10.test',
        )
        login(self.client, self.user, self.tenant)
        self.tomorrow = (
            timezone.localtime(timezone.now()) + timedelta(days=1)).date()
        self.url = reverse('schedule_quick_job')

    def post(self, **payload):
        payload.setdefault('service_type', 'repair')
        payload.setdefault('date', self.tomorrow.isoformat())
        payload.setdefault('window', 'MORNING')
        return self.client.post(
            self.url, data=json.dumps(payload),
            content_type='application/json',
        )

    # --- the motion itself -------------------------------------------------

    def test_creates_and_books_in_one_submit(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.post(
                customer=str(self.customer.id), unit_number='T-100',
                work_done='Chip, passenger side',
                on_screen_date=self.tomorrow.isoformat(),
            )
        self.assertEqual(resp.status_code, 200, resp.content[:400])
        body = resp.json()
        self.assertTrue(body['ok'])

        job = Repair.objects.get(tenant=self.tenant, unit_number='T-100')
        self.assertIsNotNone(job.scheduled_for)
        self.assertEqual(
            timezone.localtime(job.scheduled_for).date(), self.tomorrow)
        # confirm_appointment sets a window end, which is the whole reason the
        # time is written through it rather than passed to the constructor.
        self.assertIsNotNone(job.scheduled_window_end)

    def test_new_individual_created_inline(self):
        """The phone-call case: the caller is not in the system yet."""
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.post(
                new_customer_name='John Smith',
                new_customer_phone='5551234567',
                unit_number='2019 Silverado', work_done='No heat',
                window='EXACT', start_time='09:30', end_time='10:30',
            )
        self.assertEqual(resp.status_code, 200, resp.content[:400])
        job = Repair.objects.get(tenant=self.tenant, unit_number='2019 Silverado')
        self.assertEqual(job.customer.name, 'John Smith')
        local_start = timezone.localtime(job.scheduled_for)
        local_end = timezone.localtime(job.scheduled_window_end)
        self.assertEqual((local_start.hour, local_start.minute), (9, 30))
        self.assertEqual((local_end.hour, local_end.minute), (10, 30))

    def test_returns_a_server_rendered_row_for_the_day_on_screen(self):
        resp = self.post(
            customer=str(self.customer.id), unit_number='T-101',
            work_done='x', on_screen_date=self.tomorrow.isoformat(),
        )
        body = resp.json()
        self.assertTrue(body['day']['on_screen'])
        # A real row from the shared partial — not a second copy of the markup
        # living in JS, which is how the rail bug happened (S7 notes).
        self.assertIn('data-job-key', body['day']['row_html'])
        self.assertIn('T-101', body['day']['row_html'])

    def test_booking_another_day_does_not_pretend_to_be_on_screen(self):
        friday = self.tomorrow + timedelta(days=3)
        resp = self.post(
            customer=str(self.customer.id), unit_number='T-FRI', work_done='x',
            date=friday.isoformat(), window='AFTERNOON',
            on_screen_date=self.tomorrow.isoformat(),
        )
        body = resp.json()
        self.assertEqual(body['day']['date'], friday.isoformat())
        self.assertFalse(body['day']['on_screen'])
        self.assertEqual(body['day']['row_html'], '')

    # --- the extraction must not have changed what a job IS ----------------

    def test_priced_identically_to_the_form(self):
        """Same inputs through /tech/jobs/new/ and through the endpoint must
        produce the same job. This is the whole risk of the extraction."""
        self.client.post(reverse('job_create'), {
            'service_type': 'repair', 'customer': self.customer.id,
            'unit_number': 'TWIN-FORM', 'work_done': 'Chip',
            'already_completed': '',
        })
        with self.captureOnCommitCallbacks(execute=True):
            self.post(customer=str(self.customer.id), unit_number='TWIN-API',
                      work_done='Chip')

        form_job = Repair.objects.get(tenant=self.tenant, unit_number='TWIN-FORM')
        api_job = Repair.objects.get(tenant=self.tenant, unit_number='TWIN-API')
        for field in ('cost', 'tax_amount', 'tax_rate', 'queue_status',
                      'no_tax', 'technician_id'):
            self.assertEqual(
                getattr(form_job, field), getattr(api_job, field),
                f'{field} drifted between the form and the endpoint',
            )

    # --- refusals ----------------------------------------------------------

    def test_duplicate_name_asks_instead_of_creating(self):
        self.post(new_customer_name='John Smith',
                  new_customer_phone='5551234567', work_done='First')
        before = Repair.objects.filter(tenant=self.tenant).count()

        resp = self.post(new_customer_name='John Smith',
                         new_customer_phone='5551234567', work_done='Second')
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertTrue(body['needs_confirmation'])
        self.assertEqual(
            [s['name'] for s in body['suggestions']], ['John Smith'])
        self.assertEqual(
            Repair.objects.filter(tenant=self.tenant).count(), before,
            'A duplicate question must not create anything.',
        )

    def test_confirmed_duplicate_goes_through(self):
        self.post(new_customer_name='John Smith', work_done='First')
        resp = self.post(new_customer_name='John Smith', work_done='Second',
                         confirmed_new_customer=True, unit_number='SECOND')
        self.assertEqual(resp.status_code, 200, resp.content[:400])
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant, name='John Smith').count(), 2)

    def test_a_bad_date_rolls_the_job_back(self):
        """Half a motion is not a useful outcome: no unscheduled orphan."""
        before = Repair.objects.filter(tenant=self.tenant).count()
        resp = self.post(customer=str(self.customer.id), unit_number='ORPHAN',
                         work_done='x', date='not-a-date')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            Repair.objects.filter(tenant=self.tenant).count(), before)
        self.assertFalse(
            Repair.objects.filter(tenant=self.tenant, unit_number='ORPHAN').exists())

    def test_form_validation_is_reused_not_reimplemented(self):
        # QuickJobForm owns "pick a customer or add a new individual".
        resp = self.post(work_done='Nobody')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('errors', resp.json())

    def test_replacement_without_a_price_is_refused(self):
        resp = self.post(service_type='replacement',
                         customer=str(self.customer.id), work_done='Windshield')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('price', resp.json()['errors'])

    def test_service_type_the_shop_does_not_offer_is_refused(self):
        # NB: 'repair', not 'repairs' — signup_service silently falls back to
        # 'both' for an unrecognised value, so a typo here makes this test
        # assert nothing at all.
        user, tenant = make_shop('Repairs Only', 'repairsonly@test.com',
                                 services='repair')
        self.assertFalse(tenant.offers_replacements)
        client = Client()
        login(client, user, tenant)
        cust = Customer.objects.create(name='X', tenant=tenant, email='x@ro.test')
        resp = client.post(self.url, data=json.dumps({
            'service_type': 'replacement', 'customer': str(cust.id),
            'price': '300', 'work_done': 'Windshield',
            'date': self.tomorrow.isoformat(), 'window': 'MORNING',
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Replacement.objects.filter(tenant=tenant).count(), 0)

    def test_garbage_body_is_json_not_a_500(self):
        resp = self.client.post(self.url, data='{not json',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


@override_settings(**TEST_SETTINGS)
class QuickJobPermissionTests(TestCase):
    """Booking a time is a dispatch decision — same gate as S4's book."""

    def setUp(self):
        self.client = Client()
        self.owner, self.tenant = make_shop('S10 Perm Shop', 's10perm@test.com')
        self.customer = Customer.objects.create(
            name='Jones', tenant=self.tenant, email='j@perm.test')
        self.tomorrow = (
            timezone.localtime(timezone.now()) + timedelta(days=1)).date()
        self.url = reverse('schedule_quick_job')

    def test_plain_technician_is_refused_as_json(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user(
            username='plaintech', password='testpass123!', first_name='Plain')
        Technician.objects.create(
            user=user, tenant=self.tenant, is_active=True, is_manager=False)
        from apps.tenants.models import TenantMembership
        TenantMembership.objects.create(
            user=user, tenant=self.tenant, role='technician', is_active=True)

        client = Client()
        login(client, user, self.tenant)
        resp = client.post(self.url, data=json.dumps({
            'service_type': 'repair', 'customer': str(self.customer.id),
            'work_done': 'x', 'date': self.tomorrow.isoformat(),
            'window': 'MORNING',
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp['Content-Type'].split(';')[0], 'application/json')
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 0)


@override_settings(**TEST_SETTINGS)
class BookedRequestedJobStaysVisibleTests(TestCase):
    """The bug S10 folds in: a booked REQUESTED job used to vanish.

    day_schedule excluded REQUESTED from the day sheet while the rail selects
    on scheduled_for IS NULL and confirm_appointment accepts REQUESTED — so
    booking one out of the rail dropped it from both lists.
    """

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S10 Req Shop', 's10req@test.com')
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='f@req.test')
        login(self.client, self.user, self.tenant)
        self.tech = Technician.objects.filter(tenant=self.tenant).first()
        self.tomorrow = (
            timezone.localtime(timezone.now()) + timedelta(days=1)).date()

    def test_requested_job_appears_on_the_day_once_booked(self):
        job = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='REQ-1', queue_status='REQUESTED',
        )
        Repair.objects.filter(pk=job.pk).update(queue_status='REQUESTED')

        resp = self.client.post(reverse('schedule_book'), data=json.dumps({
            'type': 'repair', 'id': job.pk, 'date': self.tomorrow.isoformat(),
            'window': 'MORNING', 'expected': None,
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        page = self.client.get(
            reverse('day_schedule') + f'?date={self.tomorrow.isoformat()}')
        self.assertContains(
            page, 'REQ-1',
            msg_prefix='A booked REQUESTED job must appear on the day sheet; '
                       'it used to vanish from the rail and the day both.',
        )

    def test_unscheduled_requested_job_stays_in_the_rail(self):
        # S3's rationale still holds for work the shop has not accepted and
        # not scheduled: it belongs in triage, not on a day.
        job = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='REQ-2', queue_status='REQUESTED',
        )
        Repair.objects.filter(pk=job.pk).update(queue_status='REQUESTED')
        page = self.client.get(reverse('day_schedule'))
        self.assertContains(page, 'Needs scheduling')
        self.assertContains(page, 'REQ-2')
