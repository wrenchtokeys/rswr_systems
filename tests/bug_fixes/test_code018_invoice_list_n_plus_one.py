"""
Regression tests for CODE-018: N+1 queries in owner_invoice_list — uninvoiced_customers loop.

Problem:
    owner_invoice_list built the `uninvoiced_customers` sidebar widget by
    calling InvoiceTrackingService.get_uninvoiced_repairs(cust) inside a
    Python for-loop over all customers. Each call issued 3+ queries:
      - Repair.objects.filter(customer=cust, tenant=tenant, ...)
      - InvoiceLineItem.objects.filter(...) to get invoiced IDs
      - .count() on the queryset
      - iteration for cost sum
    With N customers → O(N) queries just for the sidebar widget.

Fix:
    Replaced the loop with 2 bulk queries:
      1. Fetch all invoiced_repair_ids for the tenant in one query.
      2. Fetch all uninvoiced completed repairs for the tenant in one query
         (.values('customer_id', 'cost')).
      3. Group + aggregate in Python — zero per-customer DB hits.

These tests verify:
1. The sidebar correctly identifies customers with uninvoiced repairs.
2. Customers with no uninvoiced repairs are excluded.
3. Query count does NOT grow with additional customers (O(1) extra queries
   for the sidebar, regardless of customer count).
4. Invoiced repairs are correctly excluded from the sidebar widget.

Author: Amelia
"""

import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, Client, override_settings
from django.test.utils import CaptureQueriesContext

from apps.billing.models import Invoice, InvoiceLineItem
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(slug, plan='pro'):
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@test.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_tech(tenant, suffix=''):
    user = User.objects.create_user(
        username=f'tech_{tenant.slug}{suffix}',
        email=f'tech_{tenant.slug}{suffix}@test.com',
        password='x',
    )
    tech, _ = Technician.objects.get_or_create(
        user=user, tenant=tenant, defaults={'is_active': True}
    )
    return tech


def _make_customer(tenant, name):
    return Customer.objects.create(tenant=tenant, name=name)


def _make_repair(tenant, customer, tech, cost=50, invoiced=False):
    repair = Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=tech,
        queue_status='COMPLETED',
        skip_invoicing=False,
        service_date=datetime.date.today(),
        cost=Decimal(str(cost)),
    )
    if invoiced:
        inv = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number=f'INV-T{tenant.id}-R{repair.id}',
            invoice_date=datetime.date.today(),
            due_date=datetime.date.today(),
            status='SENT',
            total=Decimal(str(cost)),
        )
        InvoiceLineItem.objects.create(
            invoice=inv,
            repair=repair,
            description='Repair',
            quantity=1,
            unit_price=Decimal(str(cost)),
            amount=Decimal(str(cost)),
        )
    return repair


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class TestInvoiceListUninvoicedBulkQuery(TestCase):
    """Verify correctness and query-efficiency of the uninvoiced_customers widget."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('c018main')
        self.tech = _make_tech(self.tenant)
        self.client = Client()
        self.client.force_login(self.owner)

    def test_uninvoiced_customer_appears_in_context(self):
        """Customer with uninvoiced completed repairs should appear in widget."""
        cust = _make_customer(self.tenant, 'Cust018A')
        repair = _make_repair(self.tenant, cust, self.tech, invoiced=False)
        # Reload from DB — save() may have recalculated cost via pricing rules
        repair.refresh_from_db()

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)

        uninvoiced = resp.context['uninvoiced_customers']
        cust_ids = [uc['customer'].id for uc in uninvoiced]
        self.assertIn(cust.id, cust_ids, "Customer with uninvoiced repairs should appear in widget")

        entry = next(uc for uc in uninvoiced if uc['customer'].id == cust.id)
        self.assertEqual(entry['count'], 1)
        # Total should match the actual saved cost (pricing rules applied on save)
        self.assertEqual(entry['total'], repair.cost or 0)

    def test_fully_invoiced_customer_excluded(self):
        """Customer whose repairs are all invoiced should NOT appear in widget."""
        cust = _make_customer(self.tenant, 'Cust018B')
        _make_repair(self.tenant, cust, self.tech, invoiced=True)

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)

        uninvoiced = resp.context['uninvoiced_customers']
        cust_ids = [uc['customer'].id for uc in uninvoiced]
        self.assertNotIn(cust.id, cust_ids, "Fully-invoiced customer should not appear in widget")

    def test_mixed_repairs_partial_uninvoiced(self):
        """Customer with one invoiced + one uninvoiced repair: widget shows count=1."""
        cust = _make_customer(self.tenant, 'Cust018C')
        _make_repair(self.tenant, cust, self.tech, invoiced=True)
        repair2 = _make_repair(self.tenant, cust, self.tech, invoiced=False)
        repair2.refresh_from_db()

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)

        uninvoiced = resp.context['uninvoiced_customers']
        cust_ids = [uc['customer'].id for uc in uninvoiced]
        self.assertIn(cust.id, cust_ids)
        entry = next(uc for uc in uninvoiced if uc['customer'].id == cust.id)
        self.assertEqual(entry['count'], 1, "Only uninvoiced repair should count")
        self.assertEqual(entry['total'], repair2.cost or 0)

    def test_query_count_does_not_grow_with_customers(self):
        """
        The uninvoiced_customers widget should use a fixed number of queries
        regardless of how many customers exist — O(1) not O(N).

        We measure the query count delta between a 2-customer tenant and a
        7-customer tenant. The delta should be <= 2 (noise allowance), NOT
        5+ as it would be with the N+1 bug.
        """
        # Baseline: 2 customers, no repairs
        tenant_base, owner_base = _make_tenant('c018base')
        for i in range(2):
            _make_customer(tenant_base, f'BaseCust{i}')
        client_base = Client()
        client_base.force_login(owner_base)

        with CaptureQueriesContext(connection) as ctx_base:
            resp = client_base.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        baseline_count = len(ctx_base)

        # Scaled: 7 customers, no repairs
        tenant_scaled, owner_scaled = _make_tenant('c018scaled')
        for i in range(7):
            _make_customer(tenant_scaled, f'ScaledCust{i}')
        client_scaled = Client()
        client_scaled.force_login(owner_scaled)

        with CaptureQueriesContext(connection) as ctx_scaled:
            resp = client_scaled.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        scaled_count = len(ctx_scaled)

        delta = scaled_count - baseline_count
        self.assertLessEqual(
            delta, 2,
            f"Query count grew too much: baseline={baseline_count}, scaled={scaled_count}, "
            f"delta={delta}. Likely N+1 still present."
        )
