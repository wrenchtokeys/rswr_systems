"""
Individuals and fleets are never mixed on customer-facing surfaces.

A fleet account is identified by a unit number ("Unit #4521"). An individual
is identified by their vehicle ("2019 Ford F-150"). The job forms funnel both
into the same `unit_number` column, so before this every invoice printed the
individual's vehicle under a "Unit #" header and inside a
"Windshield repair - Unit #Silver Camry" description.

The rule now lives in three places and nowhere else:
  Customer.is_individual / .vehicle_column_label
  GlassService.get_vehicle_identifier() / .get_vehicle_label()
  InvoiceLineItem.vehicle_identifier + Invoice.vehicle_column_label

Two follow-ons are guarded here as well:

* The vehicle appears exactly ONCE per invoice row. Every surface that renders
  a line's description also renders the vehicle in its own column or sub-line,
  so get_invoice_description() must not name it too.
* UnitRepairCount is keyed on the VEHICLE (UnitRepairCount.key_for), not on the
  unit_number column an individual's job leaves blank.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.services.invoice_service import InvoiceService, description_detail
from apps.technician_portal.models import (
    Repair, Replacement, Technician, UnitRepairCount,
)
from core.models import Customer
from tests.helpers import make_tenant


class VehicleLabelTests(TestCase):
    """GlassService.get_vehicle_identifier/get_vehicle_label."""

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.tenant = make_tenant('Label Shop', 'labelowner')
        cls.tech = Technician.objects.create(tenant=cls.tenant, user=cls.user)
        cls.fleet = Customer.objects.create(
            tenant=cls.tenant, name='Penske', customer_type='FLEET')
        cls.individual = Customer.objects.create(
            tenant=cls.tenant, name='Jane Doe', customer_type='RETAIL')
        cls.walkin = Customer.objects.create(
            tenant=cls.tenant, name='Walk In Bob', customer_type='WALK_IN')

    def _repair(self, customer, **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=self.tech,
            damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'), **kwargs)

    # --- Customer -------------------------------------------------------

    def test_customer_type_classification(self):
        self.assertFalse(self.fleet.is_individual)
        self.assertTrue(self.individual.is_individual)
        self.assertTrue(self.walkin.is_individual)

    def test_column_label_follows_customer_type(self):
        self.assertEqual(self.fleet.vehicle_column_label, 'Unit #')
        self.assertEqual(self.individual.vehicle_column_label, 'Vehicle')
        self.assertEqual(self.walkin.vehicle_column_label, 'Vehicle')

    # --- Fleet ----------------------------------------------------------

    def test_fleet_keeps_unit_number(self):
        repair = self._repair(self.fleet, unit_number='4521')
        self.assertEqual(repair.get_vehicle_identifier(), '4521')
        self.assertEqual(repair.get_vehicle_label(), 'Unit #4521')

    def test_fleet_invoice_description_omits_the_unit(self):
        """The Vehicle/Unit # column already prints it — see the class below."""
        repair = self._repair(self.fleet, unit_number='4521')
        self.assertEqual(
            repair.get_invoice_description(),
            'Windshield repair - Chip')

    # --- Individual -----------------------------------------------------

    def test_individual_prefers_year_make_model(self):
        """The RepairForm path: unit_number blank, vehicle_* populated."""
        repair = self._repair(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        self.assertEqual(repair.get_vehicle_identifier(), '2019 Ford F-150')
        self.assertEqual(repair.get_vehicle_label(), '2019 Ford F-150')

    def test_individual_free_text_is_not_called_a_unit(self):
        """The QuickJobForm path: the tech typed the vehicle into the one box.

        This is the exact bug — 'Unit #Silver Camry' on a person's invoice.
        """
        repair = self._repair(self.individual, unit_number='Silver Camry')
        self.assertEqual(repair.get_vehicle_identifier(), 'Silver Camry')
        self.assertEqual(repair.get_vehicle_label(), 'Silver Camry')
        self.assertNotIn('Unit', repair.get_invoice_description())

    def test_year_make_model_wins_over_a_stale_unit_number(self):
        repair = self._repair(
            self.individual, unit_number='OLD-1',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        self.assertEqual(repair.get_vehicle_identifier(), '2019 Ford F-150')

    def test_partial_vehicle_info(self):
        repair = self._repair(
            self.individual, unit_number='', vehicle_make='Toyota',
            vehicle_model='Camry')
        self.assertEqual(repair.get_vehicle_identifier(), 'Toyota Camry')

    def test_no_vehicle_at_all_drops_the_segment(self):
        """A walk-in with nothing recorded must not print a bare 'Unit #'."""
        repair = self._repair(self.walkin, unit_number='')
        self.assertEqual(repair.get_vehicle_identifier(), '')
        self.assertEqual(repair.get_vehicle_label(), '')
        self.assertEqual(repair.get_invoice_description(),
                         'Windshield repair - Chip')

    def test_fleet_with_no_unit_number_drops_the_segment(self):
        repair = self._repair(self.fleet, unit_number='')
        self.assertEqual(repair.get_vehicle_label(), '')
        self.assertEqual(repair.get_invoice_description(),
                         'Windshield repair - Chip')

    # --- Replacements ---------------------------------------------------

    def test_replacement_description_names_the_service_only(self):
        fleet_repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.fleet, technician=self.tech,
            unit_number='4521', glass_position='WINDSHIELD',
            queue_status='COMPLETED', cost=Decimal('300.00'))
        indiv_repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.individual, technician=self.tech,
            unit_number='2019 Ford F-150', glass_position='WINDSHIELD',
            queue_status='COMPLETED', cost=Decimal('300.00'))
        self.assertEqual(
            fleet_repl.get_invoice_description(), 'Windshield Replacement')
        self.assertEqual(
            indiv_repl.get_invoice_description(), 'Windshield Replacement')
        self.assertNotIn('Unit', indiv_repl.get_invoice_description())

    def test_vehicle_label_still_names_the_vehicle_for_inline_prose(self):
        """Dropping it from the description must not weaken the helper —
        notifications and the loyalty ledger have no vehicle column."""
        fleet_repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.fleet, technician=self.tech,
            unit_number='4521', glass_position='WINDSHIELD',
            queue_status='COMPLETED', cost=Decimal('300.00'))
        self.assertEqual(fleet_repl.get_vehicle_label(), 'Unit #4521')

    def test_replacement_with_no_vehicle_drops_the_na(self):
        """'Rear Window Replacement - Unit #N/A' was noise on every walk-in."""
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.walkin, technician=self.tech,
            unit_number='', glass_position='REAR_WINDOW',
            queue_status='COMPLETED', cost=Decimal('300.00'))
        self.assertNotIn('N/A', repl.get_invoice_description())
        self.assertNotIn('Unit', repl.get_invoice_description())


class InvoiceVehicleColumnTests(TestCase):
    """The invoice record, its PDF data, and the templates all agree."""

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.tenant = make_tenant('Column Shop', 'columnowner')
        cls.tech = Technician.objects.create(tenant=cls.tenant, user=cls.user)
        cls.fleet = Customer.objects.create(
            tenant=cls.tenant, name='Penske', customer_type='FLEET')
        cls.individual = Customer.objects.create(
            tenant=cls.tenant, name='Jane Doe', customer_type='RETAIL')

    def _invoice_with_repair(self, customer, repair_kwargs, stored_unit=''):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=self.tech,
            damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'), **repair_kwargs)
        invoice = Invoice.objects.create(
            tenant=self.tenant, customer=customer,
            invoice_number=f'INV-COL-{Invoice.objects.count() + 1:04d}',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status='DRAFT', subtotal=Decimal('50.00'), total=Decimal('50.00'))
        line = InvoiceLineItem.objects.create(
            invoice=invoice, repair=repair,
            description=repair.get_invoice_description(),
            quantity=1, unit_price=Decimal('50.00'),
            discount=Decimal('0.00'), amount=Decimal('50.00'),
            unit_number=stored_unit)
        return invoice, line, repair

    def test_invoice_column_label(self):
        fleet_inv, _, _ = self._invoice_with_repair(
            self.fleet, {'unit_number': '4521'}, stored_unit='4521')
        indiv_inv, _, _ = self._invoice_with_repair(
            self.individual, {'unit_number': 'Silver Camry'},
            stored_unit='Silver Camry')
        self.assertEqual(fleet_inv.vehicle_column_label, 'Unit #')
        self.assertEqual(indiv_inv.vehicle_column_label, 'Vehicle')

    def test_line_item_identifier_comes_from_the_job(self):
        """The stored unit_number is stale data; the job is the authority."""
        _, line, _ = self._invoice_with_repair(
            self.individual,
            {'unit_number': '', 'vehicle_year': 2019,
             'vehicle_make': 'Ford', 'vehicle_model': 'F-150'},
            stored_unit='LEGACY-9')
        self.assertEqual(line.vehicle_identifier, '2019 Ford F-150')

    def test_line_item_falls_back_to_stored_unit_without_a_job(self):
        """Free-form charge lines have no repair/replacement behind them."""
        invoice, _, _ = self._invoice_with_repair(
            self.fleet, {'unit_number': '4521'}, stored_unit='4521')
        charge = InvoiceLineItem.objects.create(
            invoice=invoice, description='Trip fee', quantity=1,
            unit_price=Decimal('25.00'), discount=Decimal('0.00'),
            amount=Decimal('25.00'), unit_number='4521')
        self.assertEqual(charge.vehicle_identifier, '4521')

    def test_pdf_data_carries_the_right_header_and_cells(self):
        invoice, _, _ = self._invoice_with_repair(
            self.individual,
            {'unit_number': '', 'vehicle_year': 2019,
             'vehicle_make': 'Ford', 'vehicle_model': 'F-150'})
        data = InvoiceService(tenant=self.tenant).build_invoice_data_from_record(invoice)
        self.assertEqual(data.unit_column_label, 'Vehicle')
        self.assertEqual(data.line_items[0].unit_number, '2019 Ford F-150')

    def test_pdf_data_for_a_fleet_is_unchanged(self):
        invoice, _, _ = self._invoice_with_repair(
            self.fleet, {'unit_number': '4521'}, stored_unit='4521')
        data = InvoiceService(tenant=self.tenant).build_invoice_data_from_record(invoice)
        self.assertEqual(data.unit_column_label, 'Unit #')
        self.assertEqual(data.line_items[0].unit_number, '4521')

    def test_pdf_renders_for_an_individual(self):
        """End to end — the PDF must actually build with the wider column."""
        invoice, _, _ = self._invoice_with_repair(
            self.individual,
            {'unit_number': '', 'vehicle_year': 2019,
             'vehicle_make': 'Ford', 'vehicle_model': 'F-150'})
        pdf, data = InvoiceService(tenant=self.tenant).generate_invoice_from_record(invoice)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(data.unit_column_label, 'Vehicle')

    # --- The vehicle appears exactly once per row -----------------------

    def test_description_does_not_repeat_the_vehicle_column(self):
        """'2022 Toyota Camry' beside 'Windshield repair - 2022 Toyota Camry'."""
        _, line, _ = self._invoice_with_repair(
            self.individual,
            {'unit_number': '', 'vehicle_year': 2022,
             'vehicle_make': 'Toyota', 'vehicle_model': 'Camry'})
        self.assertEqual(line.vehicle_identifier, '2022 Toyota Camry')
        self.assertNotIn('2022 Toyota Camry', line.description)

    def test_fleet_description_does_not_repeat_the_unit_column(self):
        _, line, _ = self._invoice_with_repair(
            self.fleet, {'unit_number': '4521'}, stored_unit='4521')
        self.assertEqual(line.vehicle_identifier, '4521')
        self.assertNotIn('4521', line.description)

    def test_generated_line_stores_the_vehicle_as_its_fallback(self):
        """InvoiceLineItem.unit_number is the fallback if the job ever goes.

        An individual's raw unit_number column is blank, so storing it left
        the fallback empty and the vehicle recoverable from nowhere.
        """
        from apps.billing.services.invoice_tracking_service import (
            InvoiceTrackingService,
        )

        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.individual, technician=self.tech,
            damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'), unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            customer=self.individual, services=[repair])
        line = invoice.line_items.get(repair=repair)
        self.assertEqual(line.unit_number, '2019 Ford F-150')


class DescriptionDetailTests(SimpleTestCase):
    """The service type appears once per row too, not just the vehicle.

    A line's description must name its own service — the portal, the public
    pay page and the owner screens print it with no type column. The PDF and
    the plain-text email DO print the type, so they trim it back out through
    this one helper.
    """

    def test_repair_keeps_only_the_detail(self):
        self.assertEqual(
            description_detail('Windshield repair - Chip', 'Windshield Repair'),
            'Chip')

    def test_replacement_that_only_restates_the_type(self):
        self.assertEqual(
            description_detail('Windshield Replacement', 'Windshield Replacement'),
            '')

    def test_batch_detail_survives(self):
        self.assertEqual(
            description_detail(
                'Windshield repair - Break 2 of 3 - Chip (upper)',
                'Windshield Repair'),
            'Break 2 of 3 - Chip (upper)')

    def test_owner_edited_description_is_printed_whole(self):
        self.assertEqual(
            description_detail('Rock chip, waived call-out', 'Windshield Repair'),
            'Rock chip, waived call-out')

    def test_unrelated_leading_segment_is_kept(self):
        self.assertEqual(
            description_detail('Mobile visit - Chip', 'Windshield Repair'),
            'Mobile visit - Chip')

    def test_empty_inputs(self):
        self.assertEqual(description_detail('', 'Windshield Repair'), '')
        self.assertEqual(description_detail('Trip fee', ''), 'Trip fee')


class VehicleCounterKeyTests(TestCase):
    """UnitRepairCount is keyed by VEHICLE, not by the unit_number column.

    An individual's job leaves unit_number blank, so the counter used to key
    every car a person owns onto one ''-labelled row: their second car's first
    repair was counted as their third.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.tenant = make_tenant('Counter Shop', 'counterowner')
        cls.tech = Technician.objects.create(tenant=cls.tenant, user=cls.user)
        cls.fleet = Customer.objects.create(
            tenant=cls.tenant, name='Penske', customer_type='FLEET')
        cls.individual = Customer.objects.create(
            tenant=cls.tenant, name='Jane Doe', customer_type='RETAIL')

    def _complete(self, customer, **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=self.tech,
            damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'), **kwargs)

    def _counters(self, customer):
        return set(
            UnitRepairCount.objects
            .filter(tenant=self.tenant, customer=customer)
            .values_list('unit_number', flat=True)
        )

    def test_key_for_a_fleet_is_the_unit_number(self):
        repair = self._complete(self.fleet, unit_number='4521')
        self.assertEqual(UnitRepairCount.key_for(repair), '4521')

    def test_key_for_an_individual_is_their_vehicle(self):
        repair = self._complete(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        self.assertEqual(UnitRepairCount.key_for(repair), '2019 Ford F-150')

    def test_key_is_clamped_to_the_column_width(self):
        """Postgres errors rather than truncating a 50-char column."""
        repair = self._complete(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Mercedes-Benz',
            vehicle_model='Sprinter 3500 High Roof Extended Cargo Van')
        key = UnitRepairCount.key_for(repair)
        self.assertEqual(len(key), UnitRepairCount.KEY_MAX_LENGTH)

    def test_two_cars_get_two_counters(self):
        """The bug: both cars shared one row keyed ''."""
        self._complete(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        self._complete(
            self.individual, unit_number='',
            vehicle_year=2022, vehicle_make='Toyota', vehicle_model='Camry')
        self.assertEqual(
            self._counters(self.individual),
            {'2019 Ford F-150', '2022 Toyota Camry'})

    def test_fleet_counters_are_untouched(self):
        self._complete(self.fleet, unit_number='4521')
        self._complete(self.fleet, unit_number='4522')
        self.assertEqual(self._counters(self.fleet), {'4521', '4522'})

    def test_rebuild_counts_per_vehicle(self):
        """The delete/restore and portal paths all funnel through this."""
        from apps.customer_portal.views import rebuild_unit_repair_counts

        self._complete(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        self._complete(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        self._complete(
            self.individual, unit_number='',
            vehicle_year=2022, vehicle_make='Toyota', vehicle_model='Camry')

        rebuild_unit_repair_counts(self.individual)

        counts = dict(
            UnitRepairCount.objects
            .filter(tenant=self.tenant, customer=self.individual)
            .values_list('unit_number', 'repair_count')
        )
        self.assertEqual(counts, {'2019 Ford F-150': 2, '2022 Toyota Camry': 1})

    def test_str_never_calls_an_individuals_car_a_unit(self):
        repair = self._complete(
            self.individual, unit_number='',
            vehicle_year=2019, vehicle_make='Ford', vehicle_model='F-150')
        counter = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.individual,
            unit_number=UnitRepairCount.key_for(repair))
        self.assertNotIn('Unit #', str(counter))
        self.assertIn('2019 Ford F-150', str(counter))
