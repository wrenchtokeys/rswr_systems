"""
CODE-038 Regression: N+1 queries in billing API views.

Bug 1 (list_invoices):
  The serialization loop called `inv.line_items.count()` per-invoice — one
  extra DB round-trip per invoice on every list request.  For 50 invoices
  that's 50 extra COUNT queries.

  Fix: `.annotate(line_item_count=Count('line_items'))` on the queryset so
  Django computes the count in the initial SELECT (zero extra queries).

Bug 2 (send_invoice_email_batch):
  The batch loop called `Invoice.objects.get(id=inv_id, tenant=tenant)`
  once per invoice ID, then accessed `invoice.customer.email` via a lazy FK
  load — producing 2×N DB round-trips (N SELECTs for invoices + N SELECTs
  for customers).  For 10 invoices: 20 extra queries.

  Fix: prefetch all invoices with `select_related('customer')` and
  `prefetch_related('line_items')` in a single queryset before the loop.

Tests:
  1. list_invoices: annotated line_item_count is correct (matches actual count)
  2. list_invoices: zero additional queries after annotate (no per-row COUNT)
  3. list_invoices: tenant isolation — only this tenant's invoices returned
  4. list_invoices: customer_id filter works with annotation present
  5. send_invoice_email_batch: all found invoices returned as success/skip
  6. send_invoice_email_batch: unknown invoice IDs return 'Not found' entry
  7. send_invoice_email_batch: query count is bounded (2 queries regardless of N)
  8. send_invoice_email_batch: cross-tenant invoice IDs are treated as 'Not found'
"""

import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.billing.models import Invoice, InvoiceLineItem, BillingConfig
from apps.technician_portal.models import Repair, Technician
from core.models import Customer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(slug):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name='Test Plan',
        defaults={
            'stripe_price_id': 'price_test',
            'monthly_price': Decimal('0.00'),
            'annual_price': Decimal('0.00'),
            'max_technicians': 10,
            'max_repairs_per_month': 200,
        },
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}', password='pass', email=f'owner@{slug}.com'
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.get_or_create(
        user=owner, tenant=tenant,
        defaults={'role': 'owner', 'is_active': True},
    )
    BillingConfig.objects.get_or_create(tenant=tenant)
    return tenant, owner


def _make_customer(tenant, name='Test Fleet', email='fleet@example.com'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=email,
    )


def _make_invoice(tenant, customer, n_line_items=2, status='DRAFT'):
    inv = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-{uuid.uuid4().hex[:8].upper()}',
        invoice_date=timezone.now().date(),
        status=status,
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        amount_paid=Decimal('0.00'),
        # amount_due is a @property (total - amount_paid), not a DB field
    )
    for i in range(n_line_items):
        InvoiceLineItem.objects.create(
            invoice=inv,
            description=f'Line item {i}',
            quantity=1,
            unit_price=Decimal('50.00'),
            amount=Decimal('50.00'),
        )
    return inv


def _authed_request(factory, user, tenant, path='/'):
    request = factory.get(path)
    request.user = user
    request.tenant = tenant
    return request


# ---------------------------------------------------------------------------
# Tests: list_invoices
# ---------------------------------------------------------------------------

class ListInvoicesAnnotationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tenant, self.owner = _make_tenant('billing-list')
        self.customer = _make_customer(self.tenant)

    def _get(self, params=''):
        from apps.billing.views import list_invoices
        req = self.factory.get(f'/api/billing/invoices/{params}')
        req.user = self.owner
        req.tenant = self.tenant
        return list_invoices(req)

    def test_line_item_count_correct(self):
        """Annotated line_item_count matches actual number of line items."""
        _make_invoice(self.tenant, self.customer, n_line_items=3)
        _make_invoice(self.tenant, self.customer, n_line_items=1)

        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.content)
        counts = sorted(i['line_item_count'] for i in data['invoices'])
        self.assertEqual(counts, [1, 3])

    def test_no_extra_count_queries(self):
        """Serialization loop should NOT fire extra COUNT queries per invoice."""
        for _ in range(5):
            _make_invoice(self.tenant, self.customer, n_line_items=2)

        from apps.billing.views import list_invoices
        req = self.factory.get('/api/billing/invoices/')
        req.user = self.owner
        req.tenant = self.tenant

        with CaptureQueriesContext(connection) as ctx:
            resp = list_invoices(req)
        self.assertEqual(resp.status_code, 200)

        # All queries combined: 1 annotated SELECT (invoices + count join)
        # There must be NO separate COUNT(*) queries for individual invoices.
        count_queries = [
            q for q in ctx.captured_queries
            if 'COUNT' in q['sql'].upper()
            and 'line_items' in q['sql'].lower()
            and 'GROUP BY' not in q['sql'].upper()
            # GROUP BY = the annotate aggregation (good); bare COUNT = the old per-row (bad)
        ]
        self.assertEqual(
            len(count_queries), 0,
            f"Found {len(count_queries)} per-row COUNT queries: {count_queries}"
        )

    def test_tenant_isolation(self):
        """list_invoices only returns invoices for the request tenant."""
        tenant2, owner2 = _make_tenant('billing-list-other')
        customer2 = _make_customer(tenant2, name='Other Fleet', email='other@fleet.com')

        _make_invoice(self.tenant, self.customer, n_line_items=1)
        _make_invoice(tenant2, customer2, n_line_items=1)

        resp = self._get()
        import json
        data = json.loads(resp.content)
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['invoices'][0]['customer']['name'], 'Test Fleet')

    def test_customer_id_filter(self):
        """customer_id query param still works after annotation."""
        customer2 = _make_customer(self.tenant, name='Fleet B', email='b@fleet.com')
        _make_invoice(self.tenant, self.customer, n_line_items=2)
        _make_invoice(self.tenant, customer2, n_line_items=4)

        resp = self._get(f'?customer_id={customer2.id}')
        import json
        data = json.loads(resp.content)
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['invoices'][0]['line_item_count'], 4)


# ---------------------------------------------------------------------------
# Tests: send_invoice_email_batch
# ---------------------------------------------------------------------------

class SendInvoiceEmailBatchTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tenant, self.owner = _make_tenant('billing-batch')
        self.customer = _make_customer(self.tenant, email='fleet@example.com')

    def _post(self, body):
        import json as _json
        from apps.billing.views import send_invoice_email_batch
        req = self.factory.post(
            '/api/billing/invoices/send-batch/',
            data=_json.dumps(body),
            content_type='application/json',
        )
        req.user = self.owner
        req.tenant = self.tenant
        return send_invoice_email_batch(req)

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_found_invoices_are_processed(self, mock_send):
        """Valid invoice IDs get emailed and returned as success."""
        inv1 = _make_invoice(self.tenant, self.customer, n_line_items=2, status='SENT')
        inv2 = _make_invoice(self.tenant, self.customer, n_line_items=1, status='DRAFT')

        resp = self._post({'invoice_ids': [inv1.id, inv2.id]})
        import json
        data = json.loads(resp.content)

        self.assertEqual(data['sent'], 2)
        self.assertEqual(data['failed'], 0)
        self.assertEqual(mock_send.call_count, 2)

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_unknown_invoice_ids_return_not_found(self, mock_send):
        """Invoice IDs that don't exist in the tenant return 'Not found' entry."""
        resp = self._post({'invoice_ids': [99999, 88888]})
        import json
        data = json.loads(resp.content)

        self.assertEqual(data['sent'], 0)
        self.assertEqual(data['failed'], 2)
        for r in data['results']:
            self.assertEqual(r['error'], 'Not found')
        mock_send.assert_not_called()

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_query_count_bounded_regardless_of_n(self, mock_send):
        """Batch fetch should use at most 2 DB queries regardless of invoice count."""
        invoices = [
            _make_invoice(self.tenant, self.customer, n_line_items=1, status='SENT')
            for _ in range(6)
        ]
        ids = [inv.id for inv in invoices]

        from apps.billing.views import send_invoice_email_batch
        import json as _json
        req = self.factory.post(
            '/api/billing/invoices/send-batch/',
            data=_json.dumps({'invoice_ids': ids}),
            content_type='application/json',
        )
        req.user = self.owner
        req.tenant = self.tenant

        with CaptureQueriesContext(connection) as ctx:
            resp = send_invoice_email_batch(req)

        import json
        data = json.loads(resp.content)
        self.assertEqual(data['sent'], 6)

        # The key invariant: the number of queries targeting the invoices/
        # line_items tables must be O(1), not O(N) — two queries regardless
        # of how many invoice IDs were requested.
        # (Setup queries like TenantMembership, BillingConfig, EmailBranding
        # are allowed; we only assert the invoice-fetching is batched.)
        invoice_queries = [
            q for q in ctx.captured_queries
            if 'billing_invoice' in q['sql'] and 'SELECT' in q['sql'].upper()
        ]
        self.assertLessEqual(
            len(invoice_queries), 2,
            f"Expected ≤2 invoice-related queries for batch of 6, "
            f"got {len(invoice_queries)}: "
            f"{[q['sql'][:100] for q in invoice_queries]}"
        )

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_cross_tenant_invoice_treated_as_not_found(self, mock_send):
        """Invoice from a different tenant must not be processed."""
        tenant2, owner2 = _make_tenant('billing-batch-other')
        customer2 = _make_customer(tenant2, name='Other', email='other@test.com')
        inv_other = _make_invoice(tenant2, customer2, n_line_items=1, status='SENT')

        resp = self._post({'invoice_ids': [inv_other.id]})
        import json
        data = json.loads(resp.content)

        self.assertEqual(data['sent'], 0)
        self.assertEqual(data['failed'], 1)
        self.assertEqual(data['results'][0]['error'], 'Not found')
        mock_send.assert_not_called()
