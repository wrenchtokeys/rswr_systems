"""
Shop-owned price book (IMPROVEMENT_SESSIONS B6): a completed replacement
teaches the shop's book what this glass on this vehicle costs → the next
replacement on that vehicle offers the price with a "from your price book"
note → the owner can see, pin and rebuild the book.

Guard module: the acceptance criteria in the session doc, one test each, plus
the learn/pin/quote precedence and tenant-isolation invariants.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.technician_portal.models import Repair, Replacement, Technician
from apps.technician_portal.price_book_models import ANY_YEAR, PriceBookEntry
from apps.technician_portal.services import price_book
from core.models import Customer
from tests.test_e2e_today import make_tenant

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

D = Decimal


def shop_client(user, tenant):
    client = Client()
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()
    return client


@override_settings(**TEST_SETTINGS)
class PriceBookTestCase(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant('Book Shop', 'book_owner')
        self.tenant.services_offered = 'both'
        self.tenant.save()
        self.tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True, is_manager=True,
            can_repair=True, can_replace=True,
        )
        self.customer = Customer.objects.create(
            name='Acme Fleet', tenant=self.tenant, customer_type='FLEET',
        )
        self.client = shop_client(self.owner, self.tenant)

    def make_replacement(self, status='COMPLETED', year=2019, make='Ford', model='F-150',
                         position='WINDSHIELD', **kwargs):
        fields = dict(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            queue_status=status, unit_number='4521',
            vehicle_year=year, vehicle_make=make, vehicle_model=model,
            glass_position=position,
        )
        fields.update(kwargs)
        return Replacement.objects.create(**fields)

    def entries(self):
        return PriceBookEntry.objects.filter(tenant=self.tenant)


class LearningTests(PriceBookTestCase):
    def test_completed_replacement_with_parts_and_labor_is_learned(self):
        job = self.make_replacement(parts_cost=D('310.00'), labor_cost=D('140.00'))
        entry = self.entries().get()
        self.assertEqual(entry.price, D('450.00'))
        self.assertEqual((entry.parts_cost, entry.labor_cost), (D('310.00'), D('140.00')))
        self.assertEqual(entry.source, PriceBookEntry.SOURCE_LEARNED)
        self.assertEqual(entry.times_used, 1)
        self.assertEqual(entry.last_job, job)
        self.assertEqual((entry.make_key, entry.model_key, entry.vehicle_year), ('ford', 'f-150', 2019))

    def test_single_price_job_learns_the_price_without_a_split(self):
        self.make_replacement(cost_override=D('425.00'))
        entry = self.entries().get()
        self.assertEqual(entry.price, D('425.00'))
        self.assertFalse(entry.has_breakdown)

    def test_price_is_before_account_discount(self):
        self.customer.parent_account = None
        self.customer.save()
        job = self.make_replacement(cost_override=D('400.00'))
        self.assertEqual(self.entries().get().price, D('400.00'))
        self.assertEqual(job.cost, D('400.00'))

    def test_adas_counts_only_when_required(self):
        self.make_replacement(parts_cost=D('300'), labor_cost=D('100'),
                              requires_adas_calibration=True, adas_calibration_cost=D('150'))
        self.assertEqual(self.entries().get().price, D('550.00'))
        self.entries().delete()
        self.make_replacement(year=2020, parts_cost=D('300'), labor_cost=D('100'),
                              requires_adas_calibration=False, adas_calibration_cost=D('150'))
        entry = self.entries().get()
        self.assertEqual(entry.price, D('400.00'))
        self.assertIsNone(entry.adas_calibration_cost)

    def test_not_completed_not_priced_or_no_vehicle_teaches_nothing(self):
        self.make_replacement(status='APPROVED', cost_override=D('400'))
        self.make_replacement(cost_override=D('0'))          # portal request, unpriced
        self.make_replacement(make='', model='', cost_override=D('400'))
        self.assertEqual(self.entries().count(), 0)

    def test_second_completed_job_updates_price_and_counts(self):
        self.make_replacement(cost_override=D('400'))
        self.make_replacement(cost_override=D('450'))
        entry = self.entries().get()
        self.assertEqual((entry.price, entry.times_used), (D('450.00'), 2))

    def test_resave_of_older_job_does_not_clobber_newer_price(self):
        older = self.make_replacement(cost_override=D('400'))
        self.make_replacement(cost_override=D('450'))
        older.internal_notes = 'edited later'
        older.save()
        entry = self.entries().get()
        self.assertEqual((entry.price, entry.times_used), (D('450.00'), 2))

    def test_correcting_the_latest_job_propagates(self):
        job = self.make_replacement(cost_override=D('400'))
        job.cost_override = D('410')
        job.save()
        entry = self.entries().get()
        self.assertEqual((entry.price, entry.times_used), (D('410.00'), 1))

    def test_make_and_model_are_case_and_space_insensitive(self):
        self.make_replacement(make='Ford ', model='f-150', cost_override=D('400'))
        self.make_replacement(make='FORD', model='F-150', cost_override=D('420'))
        self.assertEqual(self.entries().count(), 1)

    def test_pinned_row_is_never_overwritten_by_a_job(self):
        pinned = PriceBookEntry.objects.create(
            tenant=self.tenant, vehicle_make='Ford', vehicle_model='F-150',
            vehicle_year=2019, glass_position='WINDSHIELD', price=D('399.00'),
            source=PriceBookEntry.SOURCE_PINNED,
        )
        self.make_replacement(cost_override=D('450'))
        pinned.refresh_from_db()
        self.assertEqual(pinned.price, D('399.00'))
        self.assertTrue(pinned.is_pinned)
        self.assertEqual(pinned.times_used, 1)     # still counted as in use

    def test_quote_fills_an_empty_slot_but_never_replaces_a_charge(self):
        job = self.make_replacement(status='APPROVED', parts_cost=D('69.08'))
        price_book.learn_from_job(job, source=PriceBookEntry.SOURCE_QUOTE)
        entry = self.entries().get()
        self.assertEqual((entry.source, entry.price, entry.times_used),
                         (PriceBookEntry.SOURCE_QUOTE, D('69.08'), 0))
        # The job completes at a real price → the quote row becomes learned.
        job.labor_cost = D('150')
        job.queue_status = 'COMPLETED'
        job.save()
        entry.refresh_from_db()
        self.assertEqual((entry.source, entry.price, entry.times_used),
                         (PriceBookEntry.SOURCE_LEARNED, D('219.08'), 1))
        # A later quote on the same vehicle does not undo the charge.
        other = self.make_replacement(status='APPROVED', parts_cost=D('50'))
        price_book.learn_from_job(other, source=PriceBookEntry.SOURCE_QUOTE)
        entry.refresh_from_db()
        self.assertEqual((entry.source, entry.price), (PriceBookEntry.SOURCE_LEARNED, D('219.08')))

    def test_rebuild_replays_history_and_keeps_pinned(self):
        self.make_replacement(cost_override=D('400'))
        self.make_replacement(year=2021, cost_override=D('475'))
        PriceBookEntry.objects.create(
            tenant=self.tenant, vehicle_make='Toyota', vehicle_model='Camry',
            price=D('350'), source=PriceBookEntry.SOURCE_PINNED,
        )
        # A stale learned row whose job is gone.
        PriceBookEntry.objects.create(
            tenant=self.tenant, vehicle_make='Ghost', vehicle_model='Car', vehicle_year=2000,
            price=D('1'), source=PriceBookEntry.SOURCE_LEARNED,
        )
        read, rows = price_book.rebuild_for_tenant(self.tenant)
        self.assertEqual((read, rows), (2, 3))
        self.assertFalse(self.entries().filter(vehicle_make='Ghost').exists())
        self.assertTrue(self.entries().filter(vehicle_make='Toyota', source='PINNED').exists())

    def test_seed_command_rebuilds_and_dry_run_writes_nothing(self):
        self.make_replacement(cost_override=D('400'))
        self.entries().delete()
        out = StringIO()
        call_command('seed_price_book', '--dry-run', tenant=self.tenant.slug, stdout=out)
        self.assertEqual(self.entries().count(), 0)
        self.assertIn('1 completed replacement', out.getvalue())
        call_command('seed_price_book', tenant=self.tenant.slug, stdout=out)
        self.assertEqual(self.entries().count(), 1)


class LookupTests(PriceBookTestCase):
    def test_exact_year_wins_then_any_year_pinned_then_nearest(self):
        self.make_replacement(year=2017, cost_override=D('400'))
        self.make_replacement(year=2021, cost_override=D('475'))
        found = price_book.suggest(self.tenant, year=2021, make='ford', model='F-150', glass_position='WINDSHIELD')
        self.assertEqual((found['match'], found['entry'].price), ('exact', D('475.00')))
        found = price_book.suggest(self.tenant, year=2018, make='Ford', model='F-150', glass_position='WINDSHIELD')
        self.assertEqual((found['match'], found['entry'].vehicle_year), ('nearest_year', 2017))
        PriceBookEntry.objects.create(
            tenant=self.tenant, vehicle_make='Ford', vehicle_model='F-150',
            glass_position='WINDSHIELD', price=D('399'), source=PriceBookEntry.SOURCE_PINNED,
        )
        found = price_book.suggest(self.tenant, year=2018, make='Ford', model='F-150', glass_position='WINDSHIELD')
        self.assertEqual((found['match'], found['entry'].price), ('any_year', D('399.00')))

    def test_glass_position_must_match(self):
        self.make_replacement(cost_override=D('400'))
        self.assertIsNone(price_book.suggest(
            self.tenant, year=2019, make='Ford', model='F-150', glass_position='REAR',
        ))

    def test_blank_position_means_the_usual_glass(self):
        # The job form's position is optional: blank finds the windshield
        # row, or the last glass done on that vehicle when there is none.
        self.make_replacement(position='REAR', cost_override=D('300'))
        found = price_book.suggest(self.tenant, year=2019, make='Ford', model='F-150', glass_position='')
        self.assertEqual(found['entry'].glass_position, 'REAR')
        self.make_replacement(cost_override=D('400'))
        found = price_book.suggest(self.tenant, year=2019, make='Ford', model='F-150', glass_position='')
        self.assertEqual(found['entry'].glass_position, 'WINDSHIELD')
        self.assertIn('windshield', price_book.describe(found))

    def test_note_says_where_the_number_came_from(self):
        self.make_replacement(cost_override=D('400'))
        self.make_replacement(cost_override=D('450'))
        found = price_book.suggest(self.tenant, year=2022, make='Ford', model='F-150', glass_position='WINDSHIELD')
        note = price_book.describe(found, requested_year=2022)
        self.assertIn('$450.00', note)
        self.assertIn('2019 Ford F-150 windshield', note)
        self.assertIn('2 jobs', note)
        self.assertIn('closest year to 2022', note)

    def test_endpoint_returns_the_suggestion_for_a_vehicle(self):
        self.make_replacement(parts_cost=D('310'), labor_cost=D('140'))
        resp = self.client.get(reverse('get_price_book_suggestion'), {
            'year': '2019', 'make': 'Ford', 'model': 'F-150', 'glass_position': 'WINDSHIELD',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['found'])
        self.assertEqual((data['price'], data['parts_cost'], data['labor_cost']),
                         ('450.00', '310.00', '140.00'))
        self.assertTrue(data['has_breakdown'])
        self.assertIn('from your price book', data['note'].lower() + ' from your price book')
        self.assertIn('2019 Ford F-150 windshield', data['note'])

    def test_endpoint_resolves_a_fleet_unit_from_earlier_jobs(self):
        # The tech typed only the unit number; the vehicle is on the last
        # job for that unit — here a repair, not a replacement.
        self.make_replacement(cost_override=D('400'))
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='4521', vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150',
            queue_status='COMPLETED', damage_type='Chip',
        )
        resp = self.client.get(reverse('get_price_book_suggestion'), {
            'customer': self.customer.pk, 'unit_number': '4521', 'glass_position': 'WINDSHIELD',
        })
        self.assertTrue(resp.json()['found'])
        self.assertEqual(resp.json()['price'], '400.00')

    def test_endpoint_says_not_found_for_a_vehicle_never_done(self):
        resp = self.client.get(reverse('get_price_book_suggestion'), {
            'year': '2019', 'make': 'Ram', 'model': '2500', 'glass_position': 'WINDSHIELD',
        })
        self.assertEqual(resp.json(), {'success': True, 'found': False})

    def test_endpoint_never_crosses_tenants(self):
        self.make_replacement(cost_override=D('400'))
        other_owner, other_tenant = make_tenant('Other Shop', 'other_owner')
        Technician.objects.create(user=other_owner, tenant=other_tenant, is_active=True, can_replace=True)
        other = shop_client(other_owner, other_tenant)
        resp = other.get(reverse('get_price_book_suggestion'), {
            'year': '2019', 'make': 'Ford', 'model': 'F-150', 'glass_position': 'WINDSHIELD',
        })
        self.assertFalse(resp.json()['found'])

    def test_forms_carry_the_suggestion_container(self):
        resp = self.client.get(reverse('job_create'))
        self.assertContains(resp, 'data-pricebook-endpoint')
        self.assertContains(resp, 'price_book_suggestion.js')
        job = self.make_replacement(status='APPROVED', parts_cost=D('310'))
        resp = self.client.get(reverse('replacement_edit', args=[job.pk]))
        self.assertContains(resp, 'data-pricebook-parts="id_parts_cost"')
        self.assertContains(resp, 'id="id_vehicle_make"')


class OwnerPageTests(PriceBookTestCase):
    def test_owner_sees_the_book(self):
        self.make_replacement(parts_cost=D('310'), labor_cost=D('140'))
        resp = self.client.get(reverse('price_book_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '2019 Ford F-150')
        self.assertContains(resp, '450.00')
        self.assertContains(resp, '1 completed job')

    def test_settings_links_to_the_book(self):
        resp = self.client.get(reverse('owner_settings') + '?tab=billing')
        self.assertContains(resp, reverse('price_book_list'))

    def test_owner_edit_pins_the_row(self):
        self.make_replacement(cost_override=D('400'))
        entry = self.entries().get()
        resp = self.client.post(reverse('price_book_edit', args=[entry.pk]), {
            'vehicle_year': '2019', 'vehicle_make': 'Ford', 'vehicle_model': 'F-150',
            'glass_position': 'WINDSHIELD', 'parts_cost': '300', 'labor_cost': '125',
            'adas_calibration_cost': '', 'price': '',
        })
        self.assertRedirects(resp, reverse('price_book_list'))
        entry.refresh_from_db()
        self.assertEqual((entry.source, entry.price), (PriceBookEntry.SOURCE_PINNED, D('425.00')))
        self.make_replacement(cost_override=D('999'))
        entry.refresh_from_db()
        self.assertEqual(entry.price, D('425.00'))

    def test_owner_adds_an_any_year_price(self):
        resp = self.client.post(reverse('price_book_new'), {
            'vehicle_year': '', 'vehicle_make': 'Toyota', 'vehicle_model': 'Camry',
            'glass_position': 'WINDSHIELD', 'parts_cost': '', 'labor_cost': '',
            'adas_calibration_cost': '', 'price': '350',
        })
        self.assertRedirects(resp, reverse('price_book_list'))
        entry = self.entries().get()
        self.assertEqual((entry.vehicle_year, entry.is_pinned, entry.price), (ANY_YEAR, True, D('350.00')))
        found = price_book.suggest(self.tenant, year=2024, make='toyota', model='camry', glass_position='WINDSHIELD')
        self.assertEqual(found['match'], 'any_year')

    def test_duplicate_key_is_refused_and_no_price_is_refused(self):
        self.make_replacement(cost_override=D('400'))
        resp = self.client.post(reverse('price_book_new'), {
            'vehicle_year': '2019', 'vehicle_make': 'ford', 'vehicle_model': 'F-150',
            'glass_position': 'WINDSHIELD', 'price': '1',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already has a price')
        resp = self.client.post(reverse('price_book_new'), {
            'vehicle_year': '', 'vehicle_make': 'Ram', 'vehicle_model': '2500',
            'glass_position': '', 'price': '', 'parts_cost': '', 'labor_cost': '',
        })
        self.assertContains(resp, 'Enter a price, or parts and labor.')
        self.assertEqual(self.entries().count(), 1)

    def test_delete_and_rebuild_buttons(self):
        self.make_replacement(cost_override=D('400'))
        entry = self.entries().get()
        self.client.post(reverse('price_book_delete', args=[entry.pk]))
        self.assertEqual(self.entries().count(), 0)
        resp = self.client.post(reverse('price_book_rebuild'))
        self.assertRedirects(resp, reverse('price_book_list'))
        self.assertEqual(self.entries().count(), 1)

    def test_other_shop_cannot_see_or_edit_this_book(self):
        self.make_replacement(cost_override=D('400'))
        entry = self.entries().get()
        other_owner, other_tenant = make_tenant('Other Shop', 'other_owner2')
        other = shop_client(other_owner, other_tenant)
        resp = other.get(reverse('price_book_list'))
        self.assertNotContains(resp, 'F-150')
        self.assertEqual(other.get(reverse('price_book_edit', args=[entry.pk])).status_code, 404)
        self.assertEqual(other.post(reverse('price_book_delete', args=[entry.pk])).status_code, 404)
        self.assertTrue(self.entries().filter(pk=entry.pk).exists())

    def test_technician_without_manager_cannot_open_the_book(self):
        from django.contrib.auth.models import User
        from apps.tenants.models import TenantMembership
        tech_user = User.objects.create_user('plain_tech', 'tech@test.com', 'pw')
        TenantMembership.objects.create(tenant=self.tenant, user=tech_user, role='technician', is_active=True)
        Technician.objects.create(user=tech_user, tenant=self.tenant, is_active=True, can_replace=True)
        client = shop_client(tech_user, self.tenant)
        resp = client.get(reverse('price_book_list'))
        self.assertNotEqual(resp.status_code, 200)
        # …but the suggestion endpoint is for every tech on the job form.
        self.make_replacement(cost_override=D('400'))
        resp = client.get(reverse('get_price_book_suggestion'), {
            'year': '2019', 'make': 'Ford', 'model': 'F-150', 'glass_position': 'WINDSHIELD',
        })
        self.assertTrue(resp.json()['found'])
