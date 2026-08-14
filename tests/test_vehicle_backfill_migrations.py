"""The two backfills that clean up data written before the vehicle fix.

Both migrations reimplement a little logic that a historical model can't reach
(``Customer.INDIVIDUAL_TYPES``, ``get_vehicle_identifier()``). These tests pin
that reimplementation, and — more importantly — pin what the migrations must
NOT touch: a fleet's rows, and anything an owner typed by hand.

  billing/0035           strips the vehicle out of stored line descriptions
  technician_portal/0051 re-keys individuals' progressive-pricing counters
"""

from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module

from django.test import SimpleTestCase, TestCase


strip_mod = import_module(
    'apps.billing.migrations.0035_strip_vehicle_from_line_descriptions')
rekey_mod = import_module(
    'apps.technician_portal.migrations.0051_rekey_individual_unit_repair_counts')


class _Customer:
    def __init__(self, customer_type):
        self.customer_type = customer_type


class _Job:
    """Stands in for the historical Repair/Replacement row."""

    def __init__(self, customer_type='FLEET', unit_number='',
                 vehicle_year=None, vehicle_make='', vehicle_model=''):
        self.customer_id = 1
        self.customer = _Customer(customer_type)
        self.unit_number = unit_number
        self.vehicle_year = vehicle_year
        self.vehicle_make = vehicle_make
        self.vehicle_model = vehicle_model


class StripVehicleFromDescriptionsTests(SimpleTestCase):
    """billing/0035 — the vehicle printed twice on every row."""

    def _strip(self, description, job):
        return strip_mod._strip_vehicle(
            description, strip_mod._vehicle_segments(job))

    def test_legacy_fleet_description(self):
        job = _Job(unit_number='100')
        self.assertEqual(
            self._strip('Windshield repair - Unit #100 - Chip', job),
            'Windshield repair - Chip')

    def test_legacy_individual_wearing_a_fleet_label(self):
        """'Unit #Silver Camry' — the string that started all of this."""
        job = _Job(customer_type='RETAIL', unit_number='Silver Camry')
        self.assertEqual(
            self._strip('Windshield repair - Unit #Silver Camry - Chip', job),
            'Windshield repair - Chip')

    def test_individual_year_make_model(self):
        job = _Job(customer_type='RETAIL', vehicle_year=2022,
                   vehicle_make='Toyota', vehicle_model='Camry')
        self.assertEqual(
            self._strip('Windshield repair - 2022 Toyota Camry - Crack', job),
            'Windshield repair - Crack')

    def test_replacement_unit_na(self):
        job = _Job(customer_type='WALK_IN', unit_number='')
        self.assertEqual(
            self._strip('Rear Window Replacement - Unit #N/A', job),
            'Rear Window Replacement')

    def test_empty_unit_segment(self):
        job = _Job(unit_number='')
        self.assertEqual(
            self._strip('Windshield repair - Unit # - Chip', job),
            'Windshield repair - Chip')

    def test_batch_segments_survive(self):
        job = _Job(unit_number='100')
        self.assertEqual(
            self._strip(
                'Windshield repair - Unit #100 - Break 2 of 3 - Chip (upper)',
                job),
            'Windshield repair - Break 2 of 3 - Chip (upper)')

    def test_appended_rate_note_survives(self):
        job = _Job(unit_number='100')
        self.assertEqual(
            self._strip(
                'Windshield repair - Unit #100 - Chip [multi-break rate]', job),
            'Windshield repair - Chip [multi-break rate]')

    def test_hand_written_description_is_untouched(self):
        """Only exact vehicle segments go. Owner prose stays."""
        job = _Job(unit_number='100')
        description = 'Rock chip on the 100th truck we did - waived call-out'
        self.assertEqual(self._strip(description, job), description)

    def test_leading_service_name_is_never_removed(self):
        """A pathological unit number equal to the service name."""
        job = _Job(unit_number='Windshield repair')
        self.assertEqual(
            self._strip('Windshield repair - Chip', job),
            'Windshield repair - Chip')

    def test_already_clean_description_is_a_no_op(self):
        job = _Job(unit_number='100')
        self.assertEqual(
            self._strip('Windshield repair - Chip', job),
            'Windshield repair - Chip')


class RekeyIndividualCountersTests(SimpleTestCase):
    """technician_portal/0051 — the counter key an individual never had."""

    def test_fleet_key_is_the_unit_number(self):
        job = _Job(unit_number='4521')
        self.assertEqual(rekey_mod._vehicle_key(job, False), '4521')

    def test_individual_key_is_the_vehicle(self):
        job = _Job(customer_type='RETAIL', vehicle_year=2019,
                   vehicle_make='Ford', vehicle_model='F-150')
        self.assertEqual(rekey_mod._vehicle_key(job, True), '2019 Ford F-150')

    def test_individual_free_text_key(self):
        job = _Job(customer_type='RETAIL', unit_number='Silver Camry')
        self.assertEqual(rekey_mod._vehicle_key(job, True), 'Silver Camry')

    def test_key_is_clamped_to_the_column_width(self):
        job = _Job(customer_type='RETAIL', vehicle_year=2019,
                   vehicle_make='Mercedes-Benz',
                   vehicle_model='Sprinter 3500 High Roof Extended Cargo Van')
        self.assertEqual(len(rekey_mod._vehicle_key(job, True)), 50)

    def test_matches_the_runtime_helper(self):
        """The migration's copy must not drift from UnitRepairCount.key_for.

        Real (unsaved) model instances, so this compares against the actual
        helper rather than a third transcription of the rule.
        """
        from apps.technician_portal.models import Repair, UnitRepairCount
        from core.models import Customer

        cases = [
            ('FLEET', {'unit_number': '4521'}),
            ('RETAIL', {'unit_number': 'Silver Camry'}),
            ('WALK_IN', {'vehicle_year': 2022, 'vehicle_make': 'Toyota',
                         'vehicle_model': 'Camry'}),
            ('RETAIL', {'unit_number': 'OLD-1', 'vehicle_year': 2019,
                        'vehicle_make': 'Ford', 'vehicle_model': 'F-150'}),
            ('RETAIL', {}),
            ('FLEET', {}),
            ('RETAIL', {'vehicle_year': 2019, 'vehicle_make': 'Mercedes-Benz',
                        'vehicle_model': 'Sprinter 3500 High Roof Extended Van'}),
        ]
        for customer_type, fields in cases:
            with self.subTest(customer_type=customer_type, **fields):
                customer = Customer(customer_type=customer_type)
                repair = Repair(customer=customer, **fields)
                self.assertEqual(
                    rekey_mod._vehicle_key(repair, customer.is_individual),
                    UnitRepairCount.key_for(repair),
                )


class _RealApps:
    """Feeds the migration functions the CURRENT models.

    The two RunPython bodies only use ORM APIs that historical and real models
    share, so running them against real rows exercises every query, lookup and
    bulk write for real — which the string-level tests above cannot do.
    """

    @staticmethod
    def get_model(app_label, model_name):
        from django.apps import apps as django_apps
        return django_apps.get_model(app_label, model_name)


class StripVehicleMigrationRunTests(TestCase):
    """billing/0035 against real rows."""

    @classmethod
    def setUpTestData(cls):
        from apps.technician_portal.models import Repair, Technician
        from core.models import Customer
        from tests.helpers import make_tenant

        cls.user, cls.tenant = make_tenant('Backfill Shop', 'backfillowner')
        cls.tech = Technician.objects.create(tenant=cls.tenant, user=cls.user)
        cls.fleet = Customer.objects.create(
            tenant=cls.tenant, name='Penske', customer_type='FLEET')
        cls.individual = Customer.objects.create(
            tenant=cls.tenant, name='Jane Doe', customer_type='RETAIL')
        cls.Repair = Repair

    def _line(self, customer, description, status='SENT', **repair_kwargs):
        from apps.billing.models import Invoice, InvoiceLineItem

        repair = self.Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=self.tech,
            damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'), **repair_kwargs)
        invoice = Invoice.objects.create(
            tenant=self.tenant, customer=customer,
            invoice_number=f'INV-BF-{Invoice.objects.count() + 1:04d}',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status=status, subtotal=Decimal('50.00'), total=Decimal('50.00'))
        return InvoiceLineItem.objects.create(
            invoice=invoice, repair=repair, description=description,
            quantity=1, unit_price=Decimal('50.00'),
            discount=Decimal('0.00'), amount=Decimal('50.00'))

    def _run(self):
        strip_mod.strip_vehicle_from_descriptions(_RealApps, None)

    def test_live_invoice_is_cleaned(self):
        line = self._line(
            self.individual, 'Windshield repair - Unit #Silver Camry - Chip',
            unit_number='Silver Camry')
        self._run()
        line.refresh_from_db()
        self.assertEqual(line.description, 'Windshield repair - Chip')

    def test_fleet_line_is_cleaned_too(self):
        line = self._line(
            self.fleet, 'Windshield repair - Unit #4521 - Chip',
            unit_number='4521')
        self._run()
        line.refresh_from_db()
        self.assertEqual(line.description, 'Windshield repair - Chip')

    def test_paid_invoice_is_left_alone(self):
        """Settled documents are never rewritten — invoice_sync's rule."""
        original = 'Windshield repair - Unit #4521 - Chip'
        line = self._line(self.fleet, original, status='PAID',
                          unit_number='4521')
        self._run()
        line.refresh_from_db()
        self.assertEqual(line.description, original)

    def test_cancelled_invoice_is_left_alone(self):
        original = 'Windshield repair - Unit #4521 - Chip'
        line = self._line(self.fleet, original, status='CANCELLED',
                          unit_number='4521')
        self._run()
        line.refresh_from_db()
        self.assertEqual(line.description, original)

    def test_charge_line_without_a_job_is_left_alone(self):
        from apps.billing.models import InvoiceLineItem

        line = self._line(self.fleet, 'Windshield repair - Unit #4521 - Chip',
                          unit_number='4521')
        charge = InvoiceLineItem.objects.create(
            invoice=line.invoice, description='Trip fee - Unit #4521',
            quantity=1, unit_price=Decimal('25.00'),
            discount=Decimal('0.00'), amount=Decimal('25.00'))
        self._run()
        charge.refresh_from_db()
        self.assertEqual(charge.description, 'Trip fee - Unit #4521')

    def test_rerunning_is_a_no_op(self):
        line = self._line(self.individual,
                          'Windshield repair - Unit #Silver Camry - Chip',
                          unit_number='Silver Camry')
        self._run()
        self._run()
        line.refresh_from_db()
        self.assertEqual(line.description, 'Windshield repair - Chip')


class RekeyCountersMigrationRunTests(TestCase):
    """technician_portal/0051 against real rows."""

    @classmethod
    def setUpTestData(cls):
        from apps.technician_portal.models import Repair, Technician
        from core.models import Customer
        from tests.helpers import make_tenant

        cls.user, cls.tenant = make_tenant('Rekey Shop', 'rekeyowner')
        cls.tech = Technician.objects.create(tenant=cls.tenant, user=cls.user)
        cls.fleet = Customer.objects.create(
            tenant=cls.tenant, name='Penske', customer_type='FLEET')
        cls.individual = Customer.objects.create(
            tenant=cls.tenant, name='Jane Doe', customer_type='RETAIL')
        cls.Repair = Repair

    def _complete(self, customer, **kwargs):
        return self.Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=self.tech,
            damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'), **kwargs)

    def _counts(self, customer):
        from apps.technician_portal.models import UnitRepairCount
        return dict(
            UnitRepairCount.objects
            .filter(tenant=self.tenant, customer=customer)
            .values_list('unit_number', 'repair_count')
        )

    def _run(self):
        rekey_mod.rekey_individual_counters(_RealApps, None)

    def test_shared_empty_row_is_split_per_vehicle(self):
        """The state this migration exists to repair."""
        from apps.technician_portal.models import UnitRepairCount

        self._complete(self.individual, vehicle_year=2019,
                       vehicle_make='Ford', vehicle_model='F-150')
        self._complete(self.individual, vehicle_year=2022,
                       vehicle_make='Toyota', vehicle_model='Camry')

        # Force the pre-fix shape: one row keyed '' holding both cars.
        UnitRepairCount.objects.filter(customer=self.individual).delete()
        UnitRepairCount.objects.create(
            tenant=self.tenant, customer=self.individual,
            unit_number='', repair_count=2)

        self._run()

        self.assertEqual(
            self._counts(self.individual),
            {'2019 Ford F-150': 1, '2022 Toyota Camry': 1})

    def test_fleet_rows_are_never_touched(self):
        from apps.technician_portal.models import UnitRepairCount

        self._complete(self.fleet, unit_number='4521')
        UnitRepairCount.objects.filter(
            customer=self.fleet, unit_number='4521'
        ).update(repair_count=7)  # a hand-adjusted count

        self._run()

        self.assertEqual(self._counts(self.fleet), {'4521': 7})

    def test_soft_deleted_repairs_are_not_counted(self):
        from django.utils import timezone

        keep = self._complete(self.individual, vehicle_year=2019,
                              vehicle_make='Ford', vehicle_model='F-150')
        gone = self._complete(self.individual, vehicle_year=2019,
                              vehicle_make='Ford', vehicle_model='F-150')
        self.Repair.objects.filter(pk=gone.pk).update(
            deleted_at=timezone.now())

        self._run()

        self.assertEqual(self._counts(self.individual), {'2019 Ford F-150': 1})
        self.assertTrue(self.Repair.objects.filter(pk=keep.pk).exists())

    def test_rerunning_is_a_no_op(self):
        self._complete(self.individual, vehicle_year=2019,
                       vehicle_make='Ford', vehicle_model='F-150')
        self._run()
        first = self._counts(self.individual)
        self._run()
        self.assertEqual(self._counts(self.individual), first)
