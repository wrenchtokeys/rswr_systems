"""
Tax overhaul end-to-end tests.

Covers the new contract:
- Tutorial banner: every shop sees "Set up sales tax" until the owner
  explicitly answers (tax_configured); answering dismisses it.
- Per-ticket no_tax: quick job form checkbox → Repair/Replacement.no_tax →
  zero tax on the job → invoice taxes only the taxable lines while the
  total still includes every line.
- Data migration backfill: tax_enabled is synced to whether active TaxRate
  rows existed (the old source of truth), so no shop silently starts or
  stops charging on deploy.
"""

from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase

from apps.billing.models import BillingConfig, TaxRate, InvoiceLineItem
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.billing.services.tax_service import TaxService
from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


def _make_shop(name='Tax Overhaul Shop', email='owner@taxoverhaul.test'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name=name, email=email,
        password='testpass123!', first_name='Tax', last_name='Owner',
    )
    return result['user'], result['tenant']


class TaxSetupBannerTests(TestCase):
    def setUp(self):
        self.user, self.tenant = _make_shop()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_new_shop_sees_banner_on_dashboard(self):
        response = self.client.get('/owner/')
        self.assertContains(response, 'Set up sales tax')
        self.assertContains(response, 'no tax')

    def test_banner_gone_after_answering_no(self):
        self.client.post('/owner/settings/', {
            'form_type': 'tax_settings',
            'charges_tax': 'no',
        })
        response = self.client.get('/owner/')
        self.assertNotContains(response, 'Set up sales tax')

    def test_banner_gone_after_answering_yes(self):
        self.client.post('/owner/settings/', {
            'form_type': 'tax_settings',
            'charges_tax': 'yes',
            'tax_rate_percent': '8.25',
        })
        response = self.client.get('/owner/')
        self.assertNotContains(response, 'Set up sales tax')
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)
        self.assertEqual(config.default_tax_rate, Decimal('8.25'))

    def test_existing_shop_with_silent_rate_keeps_charging_but_sees_banner(self):
        """The pre-overhaul silently-created 6.5% shops: rate stays active
        (backfill keeps tax_enabled=True), banner shows until confirmed."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = True
        config.default_tax_rate = Decimal('6.500')
        config.state_tax_rate = Decimal('6.500')
        config.save()
        TaxRate.objects.create(
            tenant=self.tenant, city='Hensley', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )

        response = self.client.get('/owner/')
        self.assertContains(response, 'Set up sales tax')
        self.assertContains(response, '6.5')  # banner shows the current rate
        self.assertTrue(TaxService(tenant=self.tenant).is_tax_enabled())


class NoTaxPerTicketTests(TestCase):
    def setUp(self):
        self.user, self.tenant = _make_shop(
            name='NoTax Shop', email='owner@notax.test')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = True
        config.tax_configured = True
        config.default_tax_rate = Decimal('10.000')
        config.state_tax_rate = Decimal('10.000')
        config.save()
        TaxRate.objects.create(
            tenant=self.tenant, city='Testville', state='AR',
            state_rate=Decimal('10.000'), is_active=True,
        )

        self.technician = Technician.objects.filter(tenant=self.tenant).first()
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Cash Fleet', customer_type='FLEET',
        )

    def _repair(self, no_tax=False, unit='U-1'):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.technician, unit_number=unit,
            queue_status='COMPLETED', cost_override=Decimal('100.00'),
            no_tax=no_tax,
        )

    def test_repair_save_zeroes_tax_when_no_tax(self):
        taxed = self._repair(no_tax=False, unit='U-T')
        untaxed = self._repair(no_tax=True, unit='U-N')

        self.assertEqual(taxed.tax_rate, Decimal('10.000'))
        self.assertEqual(taxed.tax_amount, Decimal('10.00'))
        self.assertEqual(untaxed.tax_rate, Decimal('0.000'))
        self.assertEqual(untaxed.tax_amount, Decimal('0.00'))

    def test_flipping_no_tax_on_resave_clears_stale_tax(self):
        repair = self._repair(no_tax=False, unit='U-F')
        self.assertEqual(repair.tax_amount, Decimal('10.00'))
        repair.no_tax = True
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.tax_amount, Decimal('0.00'))
        self.assertEqual(repair.tax_rate, Decimal('0.000'))

    def test_mixed_invoice_taxes_only_taxable_lines(self):
        taxed = self._repair(no_tax=False, unit='U-A')
        untaxed = self._repair(no_tax=True, unit='U-B')

        svc = InvoiceTrackingService(tenant=self.tenant)
        invoice = svc.create_invoice_from_services(
            self.customer, [taxed, untaxed])

        lines = {li.unit_number: li for li in invoice.line_items.all()}
        self.assertTrue(lines['U-A'].taxable)
        self.assertFalse(lines['U-B'].taxable)

        # Tax on the $100 taxable line only; total covers both lines
        self.assertEqual(invoice.tax_amount, Decimal('10.00'))
        self.assertEqual(invoice.total, Decimal('210.00'))

    def test_line_item_edit_recalc_preserves_taxable_split(self):
        taxed = self._repair(no_tax=False, unit='U-C')
        untaxed = self._repair(no_tax=True, unit='U-D')
        svc = InvoiceTrackingService(tenant=self.tenant)
        invoice = svc.create_invoice_from_services(self.customer, [taxed, untaxed])

        line = invoice.line_items.get(unit_number='U-C')
        response = self.client.post(
            f'/api/billing/invoices/{invoice.id}/line-items/{line.id}/update/',
            data='{"unit_price": 200.00}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        invoice.refresh_from_db()
        # Tax on the edited taxable line only ($200 × 10%); total includes
        # the untaxed $100 line as well.
        self.assertEqual(invoice.tax_amount, Decimal('20.00'))
        self.assertEqual(invoice.total, Decimal('320.00'))

    def test_exempt_customer_still_untaxed_everywhere(self):
        exempt = Customer.objects.create(
            tenant=self.tenant, name='Exempt Fleet', customer_type='FLEET',
            tax_exempt=True,
        )
        repair = Repair.objects.create(
            tenant=self.tenant, customer=exempt,
            technician=self.technician, unit_number='U-E',
            queue_status='COMPLETED', cost_override=Decimal('100.00'),
        )
        self.assertEqual(repair.tax_amount, Decimal('0.00'))

        svc = InvoiceTrackingService(tenant=self.tenant)
        invoice = svc.create_invoice_from_services(exempt, [repair])
        self.assertEqual(invoice.tax_amount, Decimal('0.00'))
        self.assertFalse(invoice.line_items.first().taxable)

    def test_quick_job_form_uncheck_creates_no_tax_job(self):
        response = self.client.post('/tech/jobs/new/', {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-QJ',
            'work_done': 'Chip repair',
            'price': '100.00',
            # charge_tax deliberately absent = unchecked
        })
        self.assertEqual(response.status_code, 302)
        repair = Repair.objects.get(unit_number='U-QJ')
        self.assertTrue(repair.no_tax)
        self.assertEqual(repair.tax_amount, Decimal('0.00'))

    def test_quick_job_form_checked_charges_tax(self):
        response = self.client.post('/tech/jobs/new/', {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-QJ2',
            'work_done': 'Chip repair',
            'price': '100.00',
            'charge_tax': 'on',
        })
        self.assertEqual(response.status_code, 302)
        repair = Repair.objects.get(unit_number='U-QJ2')
        self.assertFalse(repair.no_tax)
        self.assertEqual(repair.tax_amount, Decimal('10.00'))

    def test_job_form_shows_tax_checkbox_when_enabled(self):
        response = self.client.get('/tech/jobs/new/')
        self.assertContains(response, 'Charge sales tax')

    def test_job_form_hides_tax_checkbox_when_disabled(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = False
        config.save()
        response = self.client.get('/tech/jobs/new/')
        self.assertNotContains(response, 'Charge sales tax')


class BackfillTaxEnabledMigrationTests(TestCase):
    """The 0027 backfill: tax_enabled must end up matching actual pre-deploy
    behavior (active TaxRate rows), not whatever the flag happened to say."""

    def _run_backfill(self):
        from apps.billing.migrations import (  # noqa: F401 (import for path check)
            __name__ as _pkg,
        )
        import importlib
        module = importlib.import_module(
            'apps.billing.migrations.0027_backfill_tax_enabled')
        module.backfill_tax_enabled(django_apps, None)

    def test_flag_enabled_without_rows_gets_disabled(self):
        _user, tenant = _make_shop(name='Backfill A', email='a@backfill.test')
        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = True  # flag said on, but no rows = wasn't charging
        config.save()

        self._run_backfill()

        config.refresh_from_db()
        self.assertFalse(config.tax_enabled)

    def test_flag_disabled_with_active_rows_gets_enabled(self):
        _user, tenant = _make_shop(name='Backfill B', email='b@backfill.test')
        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = False  # flag said off, but rows = WAS charging
        config.save()
        TaxRate.objects.create(
            tenant=tenant, city='Hensley', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )

        self._run_backfill()

        config.refresh_from_db()
        self.assertTrue(config.tax_enabled)
