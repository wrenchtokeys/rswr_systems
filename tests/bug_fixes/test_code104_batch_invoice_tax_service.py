"""
CODE-104: _create_batch_invoice() in billing/tasks.py calculated tax using
config.tax_enabled + config.default_tax_rate instead of TaxService.

Bug: TaxService.is_tax_enabled() checks TaxRate.objects.filter(tenant=tenant,
is_active=True).exists() — NOT BillingConfig.tax_enabled. _create_batch_invoice()
used BillingConfig directly, so:
1. Batch invoices charged tax even when an owner had "disabled" tax (which
   deactivates TaxRate rows via CODE-099 but doesn't clear BillingConfig.tax_enabled).
2. Batch invoices used config.default_tax_rate (flat percentage) instead of
   TaxRate.total_rate, missing per-customer city/state rate lookups.
3. Component breakdown fields (state_tax_rate, county_tax_rate, etc.) on the
   invoice were never populated.

Fix: Replace manual `config.tax_enabled + config.default_tax_rate` with
TaxService(tenant=tenant).calculate_tax(subtotal=subtotal, customer=customer).
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem, TaxRate
from apps.billing.services.tax_service import TaxService
from core.models import Customer
from apps.technician_portal.models import Technician, Repair


def _make_tenant(slug, owner):
    """Helper: create tenant + BillingConfig."""
    tenant = Tenant.objects.create(
        name=f"Batch Tax Test - {slug}",
        slug=slug,
        owner=owner,
        plan='trial',
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    BillingConfig.objects.create(
        tenant=tenant,
        company_name=f"Shop {slug}",
        default_payment_terms='NET30',
        tax_enabled=True,
        default_tax_rate=Decimal('8.500'),
        company_state='AR',
        company_city='Little Rock',
    )
    return tenant


def _make_customer(tenant, name, tax_exempt=False):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='fleet',
        tax_exempt=tax_exempt,
    )


def _make_technician(tenant, owner):
    return Technician.objects.create(
        tenant=tenant,
        user=owner,
        is_active=True,
    )


def _make_repair(tenant, customer, technician, cost):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        damage_type='Chip',
        queue_status='COMPLETED',
        cost=Decimal(str(cost)),
    )


class BatchInvoiceTaxServiceTest(TestCase):
    """
    Verify that _create_batch_invoice() uses TaxService for tax calculation.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_104',
            email='owner104@example.com',
            password='testpass123',
        )
        self.tenant = _make_tenant('batch-tax-104', self.owner)
        self.customer = _make_customer(self.tenant, 'Batch Tax Customer')
        self.tech = _make_technician(self.tenant, self.owner)

    def _invoke_create_batch_invoice(self, tenant, customer, repairs, replacements=None):
        """Call the private function directly."""
        from apps.billing.tasks import _create_batch_invoice
        return _create_batch_invoice(
            tenant=tenant,
            customer=customer,
            repairs_list=repairs,
            replacements_list=replacements or [],
        )

    def test_no_taxrate_row_means_no_tax_even_if_config_tax_enabled(self):
        """
        When TaxRate table has no active rows for this tenant,
        TaxService.is_tax_enabled() returns False — batch invoice should
        have $0 tax even though BillingConfig.tax_enabled=True.

        Previously: code checked config.tax_enabled (True) and applied
        config.default_tax_rate (8.5%), charging tax incorrectly.
        """
        # BillingConfig has tax_enabled=True + default_tax_rate=8.5%
        # But no TaxRate row → TaxService says disabled
        assert not TaxRate.objects.filter(tenant=self.tenant, is_active=True).exists()

        repair = _make_repair(self.tenant, self.customer, self.tech, '100.00')
        invoice = self._invoke_create_batch_invoice(
            self.tenant, self.customer, [repair]
        )

        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.tax_amount, Decimal('0.00'))
        self.assertEqual(invoice.total, Decimal('100.00'))
        self.assertEqual(invoice.tax_rate, Decimal('0.000'))

    def test_active_taxrate_row_applies_correct_rate(self):
        """
        When a TaxRate row exists with is_active=True, TaxService uses it.
        Batch invoice should use TaxRate.total_rate, not config.default_tax_rate.
        """
        # Create a TaxRate with a different rate than config.default_tax_rate
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            county_rate=Decimal('1.000'),
            city_rate=Decimal('1.000'),
            special_rate=Decimal('0.000'),
            is_active=True,
        )
        # total_rate should be 8.5%, same as config here — but that's coincidence;
        # what matters is TaxService is called, not config.default_tax_rate.
        # Use a clearly different total to verify.
        TaxRate.objects.filter(tenant=self.tenant).update(
            state_rate=Decimal('5.000'),
            county_rate=Decimal('0.500'),
            city_rate=Decimal('0.500'),
            special_rate=Decimal('0.000'),
        )
        expected_rate = Decimal('6.000')  # 5.0 + 0.5 + 0.5

        repair = _make_repair(self.tenant, self.customer, self.tech, '100.00')
        invoice = self._invoke_create_batch_invoice(
            self.tenant, self.customer, [repair]
        )

        self.assertIsNotNone(invoice)
        # TaxRate says 6.0%, config says 8.5% — should use TaxRate (6.0%)
        self.assertEqual(invoice.tax_rate, expected_rate)
        self.assertEqual(invoice.tax_amount, Decimal('6.00'))
        self.assertEqual(invoice.total, Decimal('106.00'))

    def test_tax_exempt_customer_gets_no_tax(self):
        """Tax-exempt customers should never have tax applied."""
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            county_rate=Decimal('1.000'),
            city_rate=Decimal('1.000'),
            special_rate=Decimal('0.000'),
            is_active=True,
        )
        exempt_customer = _make_customer(self.tenant, 'Exempt Fleet', tax_exempt=True)
        repair = _make_repair(self.tenant, exempt_customer, self.tech, '200.00')
        invoice = self._invoke_create_batch_invoice(
            self.tenant, exempt_customer, [repair]
        )

        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.tax_amount, Decimal('0.00'))
        self.assertEqual(invoice.total, Decimal('200.00'))

    def test_component_rates_populated_on_invoice(self):
        """
        Invoice.state_tax_rate, county_tax_rate, city_tax_rate, special_tax_rate
        should be set from TaxService result — not left at defaults.

        Previously these were never set by _create_batch_invoice.
        """
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            county_rate=Decimal('1.500'),
            city_rate=Decimal('0.750'),
            special_rate=Decimal('0.250'),
            is_active=True,
        )

        repair = _make_repair(self.tenant, self.customer, self.tech, '100.00')
        invoice = self._invoke_create_batch_invoice(
            self.tenant, self.customer, [repair]
        )

        self.assertIsNotNone(invoice)
        # Reload from DB to ensure saved values
        invoice.refresh_from_db()
        self.assertEqual(invoice.state_tax_rate, Decimal('6.500'))
        self.assertEqual(invoice.county_tax_rate, Decimal('1.500'))
        self.assertEqual(invoice.city_tax_rate, Decimal('0.750'))
        self.assertEqual(invoice.special_tax_rate, Decimal('0.250'))

    def test_deactivated_taxrate_no_tax(self):
        """
        When owner deactivates tax (CODE-099 sets is_active=False),
        batch invoices should NOT charge tax even if config.tax_enabled=True.

        This is the core regression for CODE-104.
        """
        # Create a TaxRate but deactivate it (simulates owner turning tax off via toggle)
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            county_rate=Decimal('1.000'),
            city_rate=Decimal('1.000'),
            special_rate=Decimal('0.000'),
            is_active=False,  # Owner disabled tax
        )
        # BillingConfig.tax_enabled is still True (CODE-099 only flips TaxRate, not BillingConfig)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)

        # TaxService should report disabled
        self.assertFalse(TaxService(tenant=self.tenant).is_tax_enabled())

        repair = _make_repair(self.tenant, self.customer, self.tech, '150.00')
        invoice = self._invoke_create_batch_invoice(
            self.tenant, self.customer, [repair]
        )

        self.assertIsNotNone(invoice)
        # Should NOT charge tax — the owner disabled it via TaxRate deactivation
        self.assertEqual(invoice.tax_amount, Decimal('0.00'))
        self.assertEqual(invoice.total, Decimal('150.00'))
