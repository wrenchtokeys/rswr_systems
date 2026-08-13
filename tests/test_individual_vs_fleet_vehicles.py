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
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.services.invoice_service import InvoiceService
from apps.technician_portal.models import Repair, Replacement, Technician
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

    def test_fleet_invoice_description_unchanged(self):
        repair = self._repair(self.fleet, unit_number='4521')
        self.assertEqual(
            repair.get_invoice_description(),
            'Windshield repair - Unit #4521 - Chip')

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
        self.assertEqual(
            repair.get_invoice_description(),
            'Windshield repair - Silver Camry - Chip')

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

    def test_replacement_description_by_customer_type(self):
        fleet_repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.fleet, technician=self.tech,
            unit_number='4521', glass_position='WINDSHIELD',
            queue_status='COMPLETED', cost=Decimal('300.00'))
        indiv_repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.individual, technician=self.tech,
            unit_number='2019 Ford F-150', glass_position='WINDSHIELD',
            queue_status='COMPLETED', cost=Decimal('300.00'))
        self.assertIn('Unit #4521', fleet_repl.get_invoice_description())
        self.assertIn('2019 Ford F-150', indiv_repl.get_invoice_description())
        self.assertNotIn('Unit', indiv_repl.get_invoice_description())

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
