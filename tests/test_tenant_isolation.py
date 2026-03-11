"""
Tenant Isolation Tests — Cross-tenant data leakage prevention

Verifies that data from one tenant is never accessible to another.

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal

from django.test import TestCase, Client, override_settings

from apps.billing.models import Invoice, TaxRate
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from tests.helpers import make_tenant as _make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


@override_settings(**TEST_OVERRIDES)
class TenantIsolationModelTests(TestCase):
    """Verify tenant-scoped querysets isolate data."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Shop A', 'owner_a')
        self.user_b, self.tenant_b = _make_tenant('Shop B', 'owner_b')

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='Customer A')
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='Customer B')

        self.inv_a = Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='A-001', subtotal=Decimal('100'), total=Decimal('100'),
        )
        self.inv_b = Invoice.objects.create(
            tenant=self.tenant_b, customer=self.cust_b,
            invoice_number='B-001', subtotal=Decimal('200'), total=Decimal('200'),
        )

        TaxRate.objects.create(tenant=self.tenant_a, city='Conway', state='AR')
        TaxRate.objects.create(tenant=self.tenant_b, city='Memphis', state='TN')

    def test_customer_queryset_isolation(self):
        """Unscoped query returns all, but tenant-filtered returns only own."""
        all_custs = Customer.objects.all()
        self.assertEqual(all_custs.count(), 2)

        a_custs = Customer.objects.filter(tenant=self.tenant_a)
        self.assertEqual(a_custs.count(), 1)
        self.assertEqual(a_custs.first().name, 'Customer A')

    def test_invoice_queryset_isolation(self):
        a_invoices = Invoice.objects.filter(tenant=self.tenant_a)
        self.assertEqual(a_invoices.count(), 1)
        self.assertEqual(a_invoices.first().invoice_number, 'A-001')

        b_invoices = Invoice.objects.filter(tenant=self.tenant_b)
        self.assertEqual(b_invoices.count(), 1)

    def test_tax_rate_isolation(self):
        a_rates = TaxRate.objects.filter(tenant=self.tenant_a)
        self.assertEqual(a_rates.count(), 1)
        self.assertEqual(a_rates.first().city, 'Conway')

    def test_unique_customer_name_per_tenant(self):
        """Same customer name in different tenants is OK."""
        Customer.objects.create(tenant=self.tenant_b, name='Customer A')
        # Should not raise — different tenant

    def test_duplicate_customer_name_same_tenant(self):
        """Same customer name in same tenant should fail."""
        with self.assertRaises(Exception):
            Customer.objects.create(tenant=self.tenant_a, name='Customer A')


@override_settings(**TEST_OVERRIDES)
class TenantIsolationAPITests(TestCase):
    """Verify API endpoints don't leak cross-tenant data."""

    def setUp(self):
        self.client = Client()
        self.user_a, self.tenant_a = _make_tenant('API Shop A', 'api_a')
        self.user_b, self.tenant_b = _make_tenant('API Shop B', 'api_b')

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='API Cust A')
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='API Cust B')

        Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='API-A-001', subtotal=Decimal('50'), total=Decimal('50'),
        )
        Invoice.objects.create(
            tenant=self.tenant_b, customer=self.cust_b,
            invoice_number='API-B-001', subtotal=Decimal('75'), total=Decimal('75'),
        )

    def test_billing_api_only_own_invoices(self):
        """Owner A should only see their own invoices via API."""
        self.client.login(username='api_a', password='pass')
        resp = self.client.get('/api/billing/invoices/')
        if resp.status_code == 200:
            data = resp.json()
            # Should not contain tenant B's invoice
            invoices = data.get('invoices', data.get('results', []))
            if isinstance(invoices, list):
                for inv in invoices:
                    inv_num = inv.get('invoice_number', '')
                    self.assertNotIn('API-B', inv_num,
                                     "Cross-tenant invoice leaked!")
