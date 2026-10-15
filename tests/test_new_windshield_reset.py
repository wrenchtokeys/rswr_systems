"""
A new windshield starts the progressive-pricing ladder over.

The ladder counts repairs per unit (UnitRepairCount). A windshield this shop
replaces resets it on its own; one ANOTHER company replaced never did, so the
first chip on new glass was billed as repair #3. The job form now shows the
unit's history and a "New windshield" tap (new_windshield=1) that starts the
unit over before the price is worked out.

Also guards the bug found on the way: replacing a SIDE or REAR window reset
the windshield's count.
"""

from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.technician_portal.models import (
    Repair, Replacement, Technician, UnitRepairCount,
)
from core.models import Customer
from tests.test_fieldops_s1 import TEST_SETTINGS, login, make_shop


def complete_repair(tenant, customer, tech, unit, x=None, y=None):
    return Repair.objects.create(
        tenant=tenant, customer=customer, technician=tech, unit_number=unit,
        queue_status='COMPLETED', damage_location_x=x, damage_location_y=y,
    )


def count_for(tenant, customer, unit):
    row = UnitRepairCount.objects.filter(
        tenant=tenant, customer=customer, unit_number=unit).first()
    return row.repair_count if row else 0


@override_settings(**TEST_SETTINGS)
class NewWindshieldBase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Glass Shop', 'glass@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.fleet = Customer.objects.create(
            name='Smith Trucking', tenant=self.tenant, customer_type='FLEET')
        login(self.client, self.user, self.tenant)
        # Two repairs on unit T-100: the next is #3 ($35).
        complete_repair(self.tenant, self.fleet, self.tech, 'T-100', 20, 40)
        complete_repair(self.tenant, self.fleet, self.tech, 'T-100', 70, 55)


class ResetHelperTests(NewWindshieldBase):
    def test_reset_returns_previous_and_zeroes(self):
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 2)
        previous = UnitRepairCount.reset_for(
            tenant=self.tenant, customer=self.fleet, key='T-100')
        self.assertEqual(previous, 2)
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 0)

    def test_reset_is_tenant_scoped(self):
        other_user, other_tenant = make_shop('Other Shop', 'other@test.com')
        other_tech = Technician.objects.get(user=other_user, tenant=other_tenant)
        other_fleet = Customer.objects.create(
            name='Smith Trucking', tenant=other_tenant, customer_type='FLEET')
        complete_repair(other_tenant, other_fleet, other_tech, 'T-100')

        UnitRepairCount.reset_for(
            tenant=self.tenant, customer=self.fleet, key='T-100')
        self.assertEqual(count_for(other_tenant, other_fleet, 'T-100'), 1)

    def test_missing_row_is_a_noop(self):
        self.assertEqual(UnitRepairCount.reset_for(
            tenant=self.tenant, customer=self.fleet, key='NOPE'), 0)
        self.assertFalse(UnitRepairCount.objects.filter(unit_number='NOPE').exists())


class ReplacementGlassPositionTests(NewWindshieldBase):
    def _replace(self, position):
        return Replacement.objects.create(
            tenant=self.tenant, customer=self.fleet, technician=self.tech,
            unit_number='T-100', glass_position=position,
            queue_status='COMPLETED', cost_override=Decimal('300.00'),
        )

    def test_side_window_does_not_reset_windshield_count(self):
        self._replace('FRONT_LEFT')
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 2)

    def test_rear_window_does_not_reset_windshield_count(self):
        self._replace('REAR')
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 2)

    def test_windshield_replacement_resets(self):
        self._replace('WINDSHIELD')
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 0)

    def test_blank_position_still_resets(self):
        # Older rows predate glass_position; nearly all were windshields.
        self._replace('')
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 0)


class JobFormNewWindshieldTests(NewWindshieldBase):
    def _post(self, **overrides):
        data = {
            'service_type': 'repair',
            'customer': self.fleet.id,
            'unit_number': 'T-100',
            'work_done': 'Chip repair',
            'already_completed': 'on',
        }
        data.update(overrides)
        resp = self.client.post(reverse('job_create'), data)
        self.assertEqual(resp.status_code, 302)
        return Repair.objects.filter(customer=self.fleet).order_by('-pk').first()

    def test_without_tap_prices_as_third_repair(self):
        repair = self._post()
        self.assertEqual(repair.cost, Decimal('35.00'))
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 3)

    def test_new_windshield_prices_as_first_repair(self):
        repair = self._post(new_windshield='1')
        self.assertEqual(repair.cost, Decimal('50.00'))
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 1)

    def test_new_windshield_leaves_private_note(self):
        repair = self._post(new_windshield='1', internal_notes='Gate code 1234')
        self.assertIn('New windshield since the last repair', repair.internal_notes)
        self.assertIn('it was at 2', repair.internal_notes)
        self.assertIn('Gate code 1234', repair.internal_notes)
        # Private: never in the text the customer sees.
        self.assertNotIn('New windshield', repair.technician_notes)

    def test_new_windshield_creates_no_replacement_job(self):
        # Another company did the glass: nothing for this shop to invoice.
        self._post(new_windshield='1')
        self.assertFalse(Replacement.objects.filter(customer=self.fleet).exists())

    def test_flag_ignored_on_a_replacement_job(self):
        self._post(service_type='replacement', new_windshield='1',
                   glass_position='FRONT_LEFT', price='250')
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 2)


class WindshieldHistoryEndpointTests(NewWindshieldBase):
    def _get(self, customer, unit='T-100'):
        return self.client.get(reverse('get_windshield_history'), {
            'customer': customer.id, 'unit_number': unit}).json()

    def test_fleet_unit_with_history(self):
        data = self._get(self.fleet)
        self.assertTrue(data['show'])
        self.assertEqual(data['repair_count'], 2)
        self.assertEqual(data['next_number'], 3)
        self.assertEqual(Decimal(data['next_price']), Decimal('35.00'))
        self.assertEqual(Decimal(data['first_price']), Decimal('50.00'))
        self.assertEqual(
            sorted((s['x'], s['y']) for s in data['spots']),
            [(20.0, 40.0), (70.0, 55.0)])
        self.assertTrue(data['last_repaired'])

    def test_only_repairs_on_current_glass_are_mapped(self):
        UnitRepairCount.reset_for(
            tenant=self.tenant, customer=self.fleet, key='T-100')
        complete_repair(self.tenant, self.fleet, self.tech, 'T-100', 50, 50)
        data = self._get(self.fleet)
        self.assertEqual(data['repair_count'], 1)
        self.assertEqual(data['spots'], [{'x': 50.0, 'y': 50.0}])

    def test_unit_without_history_hidden(self):
        self.assertFalse(self._get(self.fleet, unit='T-999')['show'])

    def test_individual_hidden(self):
        person = Customer.objects.create(
            name='Jane Doe', tenant=self.tenant, customer_type='RETAIL')
        self.assertFalse(self._get(person)['show'])

    def test_progressive_off_hidden(self):
        self.tenant.use_progressive_pricing = False
        self.tenant.save(update_fields=['use_progressive_pricing'])
        self.assertFalse(self._get(self.fleet)['show'])

    def test_other_shops_customer_hidden(self):
        other_user, other_tenant = make_shop('Other Shop', 'other2@test.com')
        other_fleet = Customer.objects.create(
            name='Theirs', tenant=other_tenant, customer_type='FLEET')
        self.assertFalse(self._get(other_fleet)['show'])

    def test_job_form_renders_the_box(self):
        resp = self.client.get(reverse('job_create'))
        self.assertContains(resp, 'id="windshieldHistory"')
        self.assertContains(resp, 'name="new_windshield"')
        self.assertContains(resp, 'js/windshield_history.js')


class ReplacementLoggedAsDoneTests(NewWindshieldBase):
    """The job form's default: a windshield replacement logged already done."""

    def test_quick_form_windshield_replacement_resets(self):
        resp = self.client.post(reverse('job_create'), {
            'service_type': 'replacement', 'customer': self.fleet.id,
            'unit_number': 'T-100', 'glass_position': 'WINDSHIELD',
            'price': '300', 'already_completed': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 0)

    def test_resave_of_completed_replacement_does_not_reset_again(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.fleet, technician=self.tech,
            unit_number='T-100', glass_position='WINDSHIELD',
            queue_status='COMPLETED', cost_override=Decimal('300.00'))
        complete_repair(self.tenant, self.fleet, self.tech, 'T-100')
        repl.refresh_from_db()
        repl.save()
        self.assertEqual(count_for(self.tenant, self.fleet, 'T-100'), 1)


class UnitPageCurrentWindshieldTests(NewWindshieldBase):
    """Customers -> unit page shows the same count and spots as the job form."""

    def _page(self, unit='T-100'):
        return self.client.get(reverse('unit_details', args=[self.fleet.id, unit]))

    def test_shows_count_next_price_and_spots(self):
        resp = self._page()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Current windshield')
        self.assertContains(resp, '2 repairs')
        self.assertContains(resp, 'Next repair is #3 ($35.00)')
        self.assertContains(resp, 'left: 20.0%; top: 40.0%;')
        self.assertContains(resp, 'left: 70.0%; top: 55.0%;')
        self.assertContains(resp, 'All-time repairs')

    def test_after_new_windshield_only_new_glass_counts(self):
        UnitRepairCount.reset_for(
            tenant=self.tenant, customer=self.fleet, key='T-100')
        resp = self._page()
        self.assertContains(resp, 'No repairs on this windshield yet')
        self.assertNotContains(resp, 'left: 20.0%')

    def test_progressive_off_shows_count_without_price(self):
        self.tenant.use_progressive_pricing = False
        self.tenant.save(update_fields=['use_progressive_pricing'])
        resp = self._page()
        self.assertContains(resp, '2 repairs')
        self.assertNotContains(resp, 'Next repair is')

    def test_page_and_job_form_agree(self):
        api = self.client.get(reverse('get_windshield_history'), {
            'customer': self.fleet.id, 'unit_number': 'T-100'}).json()
        page = self._page().context['windshield']
        self.assertEqual(api['repair_count'], page['repair_count'])
        self.assertEqual(api['spots'], page['spots'])
