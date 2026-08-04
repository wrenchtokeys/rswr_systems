"""
Tests for job-level extra charges (JobCharge) and saved fee presets.

Covers:
- Model helpers (extra_charges_total / total_with_charges)
- Invoicing: charges become their own free-form lines with correct totals/tax
- Job→invoice price sync never rewrites charge lines
- Quick job form creates charges; bad rows bounce with an error
- Repair edit: charges editable pre-invoice, locked once invoiced
- FeePreset settings management + chips on the job form
"""

from decimal import Decimal

from django.test import TestCase, Client, override_settings

from apps.billing.models import Invoice, InvoiceLineItem, TaxRate
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.technician_portal.models import FeePreset, JobCharge, Repair, Technician
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.dummy.EmailBackend',
}


def make_shop(business_name, email, first_name):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name=first_name, last_name='Owner',
    )


class ChargeTestBase(TestCase):
    shop_name = 'Charge Shop'
    shop_email = 'chargeowner@test.com'
    shop_first = 'Charge'

    def setUp(self):
        result = make_shop(self.shop_name, self.shop_email, self.shop_first)
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@test.com'
        )
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def make_repair(self, **kwargs):
        defaults = dict(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='U-100', damage_type='chip',
            queue_status='COMPLETED', cost_override=Decimal('50.00'),
        )
        defaults.update(kwargs)
        return Repair.objects.create(**defaults)

    def add_charge(self, repair, description='Trip charge', amount='25.00', taxable=True):
        return JobCharge.objects.create(
            tenant=self.tenant, repair=repair,
            description=description, amount=Decimal(amount), taxable=taxable,
        )


@override_settings(**TEST_OVERRIDES)
class ChargeModelTests(ChargeTestBase):
    shop_name = 'Model Shop'
    shop_email = 'modelowner@test.com'
    shop_first = 'Model'

    def test_totals_helpers(self):
        repair = self.make_repair()
        self.assertEqual(repair.extra_charges_total, Decimal('0.00'))
        self.add_charge(repair, amount='25.00')
        self.add_charge(repair, description='Disposal', amount='10.00')
        self.assertEqual(repair.extra_charges_total, Decimal('35.00'))
        self.assertEqual(repair.total_with_charges, repair.cost + Decimal('35.00'))


@override_settings(**TEST_OVERRIDES)
class InvoiceChargeLinesTests(ChargeTestBase):
    shop_name = 'Invoice Charge Shop'
    shop_email = 'invchargeowner@test.com'
    shop_first = 'Invcharge'

    def test_invoice_includes_charge_lines(self):
        repair = self.make_repair()
        self.add_charge(repair, 'Trip charge', '25.00')
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [repair]
        )
        lines = list(invoice.line_items.order_by('id'))
        self.assertEqual(len(lines), 2)
        job_line, charge_line = lines
        self.assertEqual(job_line.repair_id, repair.id)
        self.assertIsNone(charge_line.repair_id)
        self.assertIsNone(charge_line.replacement_id)
        self.assertEqual(charge_line.description, 'Trip charge')
        self.assertEqual(charge_line.amount, Decimal('25.00'))
        self.assertEqual(charge_line.unit_number, repair.unit_number)
        self.assertEqual(invoice.subtotal, Decimal('75.00'))
        self.assertEqual(invoice.total, Decimal('75.00'))

    def test_charge_tax_flows_through(self):
        TaxRate.objects.create(
            tenant=self.tenant, city='Little Rock', state='AR',
            state_rate=Decimal('10.000'), is_active=True,
        )
        from apps.billing.models import BillingConfig
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = True
        config.tax_configured = True
        config.save()

        repair = self.make_repair()
        repair.refresh_from_db()
        self.add_charge(repair, 'Trip charge', '25.00', taxable=True)
        self.add_charge(repair, 'Untaxed fee', '10.00', taxable=False)
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [repair]
        )
        # Taxable base = job amount + taxable charge; the untaxed fee is excluded
        job_line = invoice.line_items.get(repair=repair)
        expected_taxable = job_line.amount + Decimal('25.00')
        self.assertEqual(
            invoice.tax_amount,
            (expected_taxable * Decimal('10') / Decimal('100')).quantize(Decimal('0.01')),
        )
        untaxed_line = invoice.line_items.get(description='Untaxed fee')
        self.assertFalse(untaxed_line.taxable)

    def test_sync_never_rewrites_charge_lines(self):
        from apps.billing.services.invoice_sync import sync_lines_for_service
        repair = self.make_repair()
        self.add_charge(repair, 'Trip charge', '25.00')
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [repair]
        )
        # Reprice the job, then sync — only the job line should change
        Repair.objects.filter(pk=repair.pk).update(cost=Decimal('60.00'))
        repair.refresh_from_db()
        sync_lines_for_service(repair)
        charge_line = invoice.line_items.get(description='Trip charge')
        self.assertEqual(charge_line.amount, Decimal('25.00'))
        job_line = invoice.line_items.get(repair=repair)
        self.assertEqual(job_line.amount, Decimal('60.00'))


@override_settings(**TEST_OVERRIDES)
class QuickJobChargeTests(ChargeTestBase):
    shop_name = 'Quick Charge Shop'
    shop_email = 'quickchargeowner@test.com'
    shop_first = 'Quickcharge'

    def _post_job(self, charge_rows, **extra):
        data = {
            'service_type': 'repair',
            'customer': self.customer.id,
            'price': '50.00',
            'charge_desc': [d for d, a in charge_rows],
            'charge_amount': [a for d, a in charge_rows],
        }
        data.update(extra)
        return self.client.post('/tech/jobs/new/', data)

    def test_job_created_with_charges(self):
        resp = self._post_job([('Trip charge', '25.00'), ('Disposal', '10.00')])
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(customer=self.customer)
        charges = list(repair.extra_charges.order_by('id'))
        self.assertEqual(len(charges), 2)
        self.assertEqual(charges[0].description, 'Trip charge')
        self.assertEqual(charges[0].amount, Decimal('25.00'))
        self.assertEqual(charges[0].tenant, self.tenant)
        self.assertEqual(repair.total_with_charges, repair.cost + Decimal('35.00'))

    def test_blank_rows_skipped(self):
        resp = self._post_job([('', ''), ('Trip charge', '25.00')])
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(customer=self.customer)
        self.assertEqual(repair.extra_charges.count(), 1)

    def test_bad_amount_bounces(self):
        resp = self._post_job([('Trip charge', 'abc')])
        self.assertEqual(resp.status_code, 200)  # re-rendered with error
        self.assertEqual(Repair.objects.filter(customer=self.customer).count(), 0)
        self.assertContains(resp, 'Trip charge')  # typed row preserved

    def test_missing_description_bounces(self):
        resp = self._post_job([('', '25.00')])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Repair.objects.filter(customer=self.customer).count(), 0)

    def test_preset_chips_render(self):
        FeePreset.objects.create(tenant=self.tenant, label='Trip charge', amount=Decimal('25.00'))
        resp = self.client.get('/tech/jobs/new/')
        self.assertContains(resp, 'Trip charge')
        self.assertContains(resp, 'addChargeRow')


@override_settings(**TEST_OVERRIDES)
class UpdateRepairChargeTests(ChargeTestBase):
    shop_name = 'Edit Charge Shop'
    shop_email = 'editchargeowner@test.com'
    shop_first = 'Editcharge'

    def _update_payload(self, repair, charge_rows):
        # Minimal RepairForm payload — post back the existing values
        return {
            'customer': self.customer.id,
            'unit_number': repair.unit_number,
            'damage_type': 'Chip',
            'queue_status': repair.queue_status,
            'repair_date': repair.service_date.strftime('%Y-%m-%dT%H:%M'),
            'cost_override': '50.00',
            'override_reason': 'test price',
            'technician': self.technician.id,
            'charge_desc': [d for d, a in charge_rows],
            'charge_amount': [a for d, a in charge_rows],
        }

    def test_charges_saved_on_edit(self):
        repair = self.make_repair(queue_status='APPROVED')
        resp = self.client.post(
            f'/tech/repairs/{repair.id}/update/',
            self._update_payload(repair, [('Trip charge', '25.00')]),
        )
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and str(resp.context.get('form').errors))
        self.assertEqual(repair.extra_charges.count(), 1)

    def test_charges_replaced_not_duplicated(self):
        repair = self.make_repair(queue_status='APPROVED')
        self.add_charge(repair, 'Old fee', '5.00')
        self.client.post(
            f'/tech/repairs/{repair.id}/update/',
            self._update_payload(repair, [('Trip charge', '25.00')]),
        )
        charges = list(repair.extra_charges.all())
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges[0].description, 'Trip charge')

    def test_invoiced_job_charges_locked(self):
        repair = self.make_repair()
        self.add_charge(repair, 'Trip charge', '25.00')
        InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [repair]
        )
        # Post an edit WITHOUT charge rows — must not wipe the charges
        resp = self.client.post(
            f'/tech/repairs/{repair.id}/update/',
            self._update_payload(repair, []),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(repair.extra_charges.count(), 1)

    def test_locked_note_rendered(self):
        repair = self.make_repair()
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [repair]
        )
        resp = self.client.get(f'/tech/repairs/{repair.id}/update/')
        self.assertContains(resp, invoice.invoice_number)


@override_settings(**TEST_OVERRIDES)
class ReplacementChargeTests(ChargeTestBase):
    shop_name = 'Replace Charge Shop'
    shop_email = 'replchargeowner@test.com'
    shop_first = 'Replcharge'

    def make_replacement(self, **kwargs):
        from apps.technician_portal.models import Replacement
        defaults = dict(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='R-100', glass_position='WINDSHIELD',
            parts_cost=Decimal('250.00'), labor_cost=Decimal('150.00'),
            queue_status='COMPLETED',
        )
        defaults.update(kwargs)
        return Replacement.objects.create(**defaults)

    def _edit_payload(self, replacement, charge_rows):
        return {
            'customer': self.customer.id,
            'technician': self.technician.id,
            'unit_number': replacement.unit_number,
            'glass_position': replacement.glass_position,
            'parts_cost': '250.00',
            'labor_cost': '150.00',
            'charge_desc': [d for d, a in charge_rows],
            'charge_amount': [a for d, a in charge_rows],
        }

    def test_create_with_charges(self):
        resp = self.client.post('/tech/replacement/new/', {
            'customer': self.customer.id,
            'technician': self.technician.id,
            'unit_number': 'R-200',
            'glass_position': 'WINDSHIELD',
            'parts_cost': '250.00',
            'labor_cost': '150.00',
            'charge_desc': ['Trip charge'],
            'charge_amount': ['25.00'],
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and str(resp.context.get('form').errors))
        from apps.technician_portal.models import Replacement
        replacement = Replacement.objects.get(unit_number='R-200')
        charges = list(replacement.extra_charges.all())
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges[0].description, 'Trip charge')
        self.assertEqual(charges[0].amount, Decimal('25.00'))
        self.assertEqual(replacement.total_with_charges,
                         replacement.cost + Decimal('25.00'))

    def test_edit_saves_charges(self):
        replacement = self.make_replacement(queue_status='APPROVED')
        resp = self.client.post(
            f'/tech/replacement/{replacement.pk}/edit/',
            self._edit_payload(replacement, [('Trip charge', '25.00')]),
        )
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and str(resp.context.get('form').errors))
        self.assertEqual(replacement.extra_charges.count(), 1)

    def test_invoiced_replacement_charges_locked(self):
        replacement = self.make_replacement()
        JobCharge.objects.create(
            tenant=self.tenant, replacement=replacement,
            description='Trip charge', amount=Decimal('25.00'),
        )
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [replacement]
        )
        # Edit without charge rows must not wipe the charges
        resp = self.client.post(
            f'/tech/replacement/{replacement.pk}/edit/',
            self._edit_payload(replacement, []),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(replacement.extra_charges.count(), 1)
        # And the edit page shows the lock note
        resp = self.client.get(f'/tech/replacement/{replacement.pk}/edit/')
        self.assertContains(resp, invoice.invoice_number)

    def test_replacement_invoice_includes_charge_line(self):
        replacement = self.make_replacement()
        JobCharge.objects.create(
            tenant=self.tenant, replacement=replacement,
            description='Trip charge', amount=Decimal('25.00'),
        )
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [replacement]
        )
        charge_line = invoice.line_items.get(description='Trip charge')
        self.assertIsNone(charge_line.repair_id)
        self.assertIsNone(charge_line.replacement_id)
        self.assertEqual(invoice.subtotal, replacement.cost + Decimal('25.00'))

    def test_preset_chips_render_on_replacement_form(self):
        FeePreset.objects.create(tenant=self.tenant, label='Trip charge', amount=Decimal('25.00'))
        resp = self.client.get('/tech/replacement/new/')
        self.assertContains(resp, 'Trip charge')
        self.assertContains(resp, 'addChargeRow')


@override_settings(**TEST_OVERRIDES)
class FeePresetSettingsTests(ChargeTestBase):
    shop_name = 'Preset Shop'
    shop_email = 'presetowner@test.com'
    shop_first = 'Preset'

    def test_add_preset(self):
        resp = self.client.post('/owner/settings/', {
            'form_type': 'add_fee_preset',
            'label': 'Trip charge',
            'amount': '25.00',
        })
        self.assertEqual(resp.status_code, 302)
        preset = FeePreset.objects.get(tenant=self.tenant)
        self.assertEqual(preset.label, 'Trip charge')
        self.assertEqual(preset.amount, Decimal('25.00'))

    def test_add_preset_requires_valid_amount(self):
        self.client.post('/owner/settings/', {
            'form_type': 'add_fee_preset', 'label': 'Bad', 'amount': '-5',
        })
        self.assertEqual(FeePreset.objects.count(), 0)

    def test_delete_preset(self):
        preset = FeePreset.objects.create(
            tenant=self.tenant, label='Trip charge', amount=Decimal('25.00'))
        self.client.post('/owner/settings/', {
            'form_type': 'delete_fee_preset', 'preset_id': preset.id,
        })
        self.assertEqual(FeePreset.objects.count(), 0)

    def test_cannot_delete_other_tenants_preset(self):
        other = make_shop('Other Preset Shop', 'otherpreset@test.com', 'Otherpreset')
        foreign = FeePreset.objects.create(
            tenant=other['tenant'], label='Foreign', amount=Decimal('9.00'))
        self.client.post('/owner/settings/', {
            'form_type': 'delete_fee_preset', 'preset_id': foreign.id,
        })
        self.assertTrue(FeePreset.objects.filter(id=foreign.id).exists())

    def test_settings_page_lists_presets(self):
        FeePreset.objects.create(
            tenant=self.tenant, label='After-hours', amount=Decimal('40.00'))
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertContains(resp, 'After-hours')
        self.assertContains(resp, 'Saved Fees')
