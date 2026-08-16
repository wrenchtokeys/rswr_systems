"""
Fieldops S2 — field dispatch: get the tech to the vehicle.

Covers the acceptance criteria in docs/strategy/FIELD_OPS_SESSIONS.md §S2
(B1 in docs/strategy/IMPROVEMENT_SESSIONS.md): both job types carry a
structured per-job service location (`service_address/_city/_state/_zip`)
that falls back to the customer's address when blank; the quick job form
prefill stores only genuine overrides (an untouched prefill dedupes back to
blank); and the dashboard job card + both detail pages render map/call
elements whose hrefs are composed client-side from data attributes —
degrading to nothing, not an empty shell, when a job has no address.
"""

from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse

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

ADDRESS = dict(
    address='4600 Distribution Dr', city='Little Rock',
    state='AR', zip_code='72209',
)
ADDRESS_ONELINE = '4600 Distribution Dr, Little Rock, AR 72209'


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


@override_settings(**TEST_SETTINGS)
class ServiceLocationModelTests(TestCase):
    """service_* fields override; the customer's address answers otherwise."""

    def setUp(self):
        self.user, self.tenant = make_shop('S2 Model Shop', 's2model@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            name='Penske Fleet', tenant=self.tenant, phone='(501) 555-0134',
            **ADDRESS,
        )

    def _repair(self, **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-1', **kwargs,
        )

    def test_defaults_blank_and_fall_back_to_customer(self):
        repair = self._repair()
        self.assertEqual(repair.service_address, '')
        self.assertEqual(
            repair.get_service_location_parts(),
            ('4600 Distribution Dr', 'Little Rock', 'AR', '72209'),
        )
        self.assertEqual(repair.get_service_location(), ADDRESS_ONELINE)

    def test_own_location_wins_over_customer(self):
        repair = self._repair(
            service_address='9 Job Site Rd', service_city='Benton',
            service_state='AR', service_zip='72015',
        )
        self.assertEqual(
            repair.get_service_location(), '9 Job Site Rd, Benton, AR 72015')

    def test_partial_override_does_not_mix_in_customer_parts(self):
        # Any own part set = the job knows where it is; never splice the
        # customer's city onto a job-site street.
        repair = self._repair(service_address='Bay 4, Westgate Yard')
        self.assertEqual(repair.get_service_location(), 'Bay 4, Westgate Yard')

    def test_no_address_anywhere_is_empty_string(self):
        walk_in = Customer.objects.create(
            name='Jane Doe', tenant=self.tenant, customer_type='RETAIL')
        repair = Repair.objects.create(
            tenant=self.tenant, customer=walk_in, technician=self.tech)
        self.assertEqual(repair.get_service_location(), '')
        repair.customer = None
        self.assertEqual(repair.get_service_location(), '')

    def test_multiline_customer_address_collapses_to_one_line(self):
        self.customer.address = '4600 Distribution Dr\nDock 12'
        self.customer.save()
        repair = self._repair()
        self.assertEqual(
            repair.get_service_location(),
            '4600 Distribution Dr Dock 12, Little Rock, AR 72209',
        )

    def test_replacement_parity(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-2',
        )
        self.assertEqual(repl.get_service_location(), ADDRESS_ONELINE)


@override_settings(**TEST_SETTINGS)
class QuickJobServiceLocationTests(TestCase):
    """/tech/jobs/new/: prefill stores only genuine overrides."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S2 Quick Shop', 's2quick@test.com')
        self.customer = Customer.objects.create(
            name='Smith Trucking', tenant=self.tenant,
            email='smith@test.com', phone='(501) 555-0199', **ADDRESS,
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

    def test_override_is_stored(self):
        resp = self._post(
            service_address='9 Job Site Rd', service_city='Benton',
            service_state='AR', service_zip='72015',
        )
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.service_address, '9 Job Site Rd')
        self.assertEqual(
            repair.get_service_location(), '9 Job Site Rd, Benton, AR 72015')

    def test_untouched_prefill_dedupes_to_blank(self):
        # The picker JS copies the customer's address into the inputs, so an
        # untouched submit posts it back verbatim. Storing that copy would
        # freeze it; blanking keeps display following the customer record.
        resp = self._post(
            service_address='4600 Distribution Dr', service_city='Little Rock',
            service_state='AR', service_zip='72209',
        )
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.service_address, '')
        self.assertEqual(repair.service_city, '')
        self.assertEqual(repair.get_service_location(), ADDRESS_ONELINE)

    def test_dedupe_survives_case_and_whitespace_noise(self):
        resp = self._post(
            service_address='  4600  distribution dr ',
            service_city='LITTLE ROCK', service_state='ar',
            service_zip='72209',
        )
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.service_address, '')

    def test_blank_stays_blank(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.service_address, '')
        self.assertEqual(repair.get_service_location(), ADDRESS_ONELINE)

    def test_replacement_carries_override(self):
        resp = self._post(
            service_type='replacement', price='425.00',
            work_done='Windshield replacement',
            service_address='Gate 2, Port Yard', service_city='North Little Rock',
            service_state='AR', service_zip='72114',
        )
        self.assertEqual(resp.status_code, 302)
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.service_address, 'Gate 2, Port Yard')

    def test_form_renders_location_block_and_prefill_attrs(self):
        resp = self.client.get(reverse('job_create'))
        self.assertContains(resp, 'service-location-block')
        self.assertContains(resp, 'name="service_address"')
        # The select options carry the customer's address for the picker JS.
        self.assertContains(resp, 'data-address="4600 Distribution Dr"')
        self.assertContains(resp, 'data-zip="72209"')


@override_settings(**TEST_SETTINGS)
class DispatchDisplayTests(TestCase):
    """Job card + detail pages: map/call from data already on the page."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S2 Display Shop', 's2display@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.tech.can_replace = True
        self.tech.save()
        self.customer = Customer.objects.create(
            name='Penske Fleet', tenant=self.tenant,
            phone='(501) 555-0134', **ADDRESS,
        )
        login(self.client, self.user, self.tenant)

    def test_dashboard_card_carries_map_and_call(self):
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-7',
            queue_status='IN_PROGRESS',
        )
        resp = self.client.get(reverse('technician_dashboard'))
        self.assertContains(resp, f'data-map-query="{ADDRESS_ONELINE}"')
        self.assertContains(resp, 'data-call-number="(501) 555-0134"')
        self.assertContains(resp, 'js/field_dispatch.js')
        # No address in any server-rendered URL: the maps href is composed
        # client-side, so the page never contains a maps URL.
        self.assertNotContains(resp, 'google.com/maps')

    def test_dashboard_card_degrades_without_address_or_phone(self):
        walk_in = Customer.objects.create(
            name='Jane Doe', tenant=self.tenant, customer_type='RETAIL')
        Repair.objects.create(
            tenant=self.tenant, customer=walk_in,
            technician=self.tech, queue_status='IN_PROGRESS',
        )
        resp = self.client.get(reverse('technician_dashboard'))
        self.assertNotContains(resp, 'data-map-query')
        self.assertNotContains(resp, 'data-call-number')

    def test_repair_detail_shows_location_and_phone(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-8',
        )
        resp = self.client.get(reverse('repair_detail', args=[repair.id]))
        self.assertContains(resp, f'data-map-query="{ADDRESS_ONELINE}"')
        self.assertContains(resp, 'data-call-number="(501) 555-0134"')
        self.assertContains(resp, 'js/field_dispatch.js')

    def test_repair_detail_prefers_job_override(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-9',
            service_address='9 Job Site Rd', service_city='Benton',
            service_state='AR', service_zip='72015',
        )
        resp = self.client.get(reverse('repair_detail', args=[repair.id]))
        self.assertContains(resp, 'data-map-query="9 Job Site Rd, Benton, AR 72015"')
        self.assertNotContains(resp, f'data-map-query="{ADDRESS_ONELINE}"')

    def test_replacement_detail_shows_location_and_phone(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-10',
        )
        resp = self.client.get(reverse('replacement_detail', args=[repl.id]))
        self.assertContains(resp, f'data-map-query="{ADDRESS_ONELINE}"')
        self.assertContains(resp, 'data-call-number="(501) 555-0134"')
        self.assertContains(resp, 'js/field_dispatch.js')


@override_settings(**TEST_SETTINGS)
class LegacyFormServiceLocationTests(TestCase):
    """The per-type edit forms can set and clear the per-job location."""

    def setUp(self):
        self.user, self.tenant = make_shop('S2 Legacy Shop', 's2legacy@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.tech.can_replace = True
        self.tech.save()
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, **ADDRESS)

    def test_repair_form_saves_override(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='T-9',
        )
        form = RepairForm(
            data={
                'customer': self.customer.id,
                'technician': self.tech.id,
                'unit_number': 'T-9',
                'repair_date': '2026-08-15T09:00',
                'queue_status': repair.queue_status,
                'service_address': '9 Job Site Rd',
                'service_city': 'Benton',
                'service_state': 'AR',
                'service_zip': '72015',
            },
            instance=repair, user=self.user, tenant=self.tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.service_address, '9 Job Site Rd')
        self.assertEqual(
            saved.get_service_location(), '9 Job Site Rd, Benton, AR 72015')

    def test_replacement_form_saves_override(self):
        form = ReplacementForm(data={
            'customer': self.customer.id,
            'technician': self.tech.id,
            'unit_number': 'T-11',
            'parts_cost': '200.00',
            'labor_cost': '150.00',
            'service_address': 'Gate 2, Port Yard',
            'service_city': 'North Little Rock',
            'service_state': 'AR',
            'service_zip': '72114',
        })
        self.assertTrue(form.is_valid(), form.errors)
        repl = form.save(commit=False)
        repl.tenant = self.tenant
        repl.save()
        self.assertEqual(repl.service_address, 'Gate 2, Port Yard')

    def test_quickjob_form_declares_location_fields(self):
        form = QuickJobForm(tenant=self.tenant)
        for name in ('service_address', 'service_city',
                     'service_state', 'service_zip'):
            self.assertIn(name, form.fields)
            self.assertFalse(form.fields[name].required)
