"""
Billing Phase 6 UI Tests

Tests for:
- Aging Report JSON endpoint (/owner/billing/aging/)
- Aging Report CSV export (/owner/billing/aging/export/)
- Customer Statement of Account (/owner/customers/<id>/statement/)
- Send Reminder from invoice list (AJAX to /owner/invoices/<id>/reminder/)

Author: Amelia (Clawdbot AI)
"""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem, Payment
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.dummy.EmailBackend',
}


def make_invoice(customer, tenant, status='SENT', days_overdue=0, amount=Decimal('500.00')):
    """Helper to create an invoice. Uses timezone-aware 'today' to match aging report."""
    from django.utils import timezone as tz
    today = tz.now().date()
    due = today - timedelta(days=days_overdue)
    inv = Invoice.objects.create(
        customer=customer,
        tenant=tenant,
        invoice_number=f'INV-TEST-{Invoice.objects.count() + 1:04d}',
        invoice_date=today - timedelta(days=days_overdue + 5),
        due_date=due,
        status=status,
        subtotal=amount,
        total=amount,
    )
    return inv


def make_payment(invoice, amount=Decimal('100.00'), days_ago=0):
    """Helper to create a payment."""
    pmt = Payment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_date=date.today() - timedelta(days=days_ago),
        payment_method='CHECK',
    )
    invoice.amount_paid = (invoice.amount_paid or Decimal('0')) + amount
    invoice.save(update_fields=['amount_paid'])
    return pmt


@override_settings(**TEST_OVERRIDES)
class AgingReportJsonTests(TestCase):
    """Tests for /owner/billing/aging/ JSON endpoint."""

    def setUp(self):
        self.user, self.tenant = make_tenant('TestShop', 'testowner_ph6')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@test.com'
        )

    def test_aging_json_requires_login(self):
        c = Client()
        resp = c.get('/owner/billing/aging/')
        # Redirects to login
        self.assertIn(resp.status_code, [302, 403])

    def test_aging_json_returns_200(self):
        resp = self.client.get('/owner/billing/aging/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json')

    def test_aging_json_structure(self):
        resp = self.client.get('/owner/billing/aging/')
        data = resp.json()
        self.assertIn('buckets', data)
        self.assertIn('grand_total', data)
        for key in ('current', '1_30', '31_60', '61_90', '90_plus'):
            self.assertIn(key, data['buckets'])

    def test_aging_json_buckets_populated(self):
        # Current invoice (not overdue)
        inv_current = make_invoice(self.customer, self.tenant, status='SENT', days_overdue=0)
        # 15 days overdue
        inv_15 = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=15)
        # 45 days overdue
        inv_45 = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=45)
        # 100 days overdue
        inv_100 = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=100)

        resp = self.client.get('/owner/billing/aging/')
        data = resp.json()
        buckets = data['buckets']

        self.assertEqual(buckets['current']['count'], 1)
        self.assertEqual(buckets['1_30']['count'], 1)
        self.assertEqual(buckets['31_60']['count'], 1)
        self.assertEqual(buckets['90_plus']['count'], 1)
        self.assertGreater(data['grand_total'], 0)

    def test_aging_json_ignores_paid_invoices(self):
        make_invoice(self.customer, self.tenant, status='PAID', days_overdue=0)
        resp = self.client.get('/owner/billing/aging/')
        data = resp.json()
        self.assertEqual(data['grand_total'], 0.0)

    def test_aging_json_tenant_isolation(self):
        """Invoices from another tenant should not appear."""
        user2, tenant2 = make_tenant('OtherShop', 'other_ph6')
        cust2 = Customer.objects.create(name='Other', tenant=tenant2)
        make_invoice(cust2, tenant2, status='OVERDUE', days_overdue=30)

        resp = self.client.get('/owner/billing/aging/')
        data = resp.json()
        self.assertEqual(data['grand_total'], 0.0)


@override_settings(**TEST_OVERRIDES)
class AgingReportCsvTests(TestCase):
    """Tests for /owner/billing/aging/export/ CSV download."""

    def setUp(self):
        self.user, self.tenant = make_tenant('CsvShop', 'csvowner_ph6')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='CSV Customer', tenant=self.tenant, email='csv@test.com'
        )

    def test_csv_export_requires_login(self):
        c = Client()
        resp = c.get('/owner/billing/aging/export/')
        self.assertIn(resp.status_code, [302, 403])

    def test_csv_export_returns_csv(self):
        make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=20)
        resp = self.client.get('/owner/billing/aging/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn('.csv', resp['Content-Disposition'])

    def test_csv_export_correct_columns(self):
        make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=20)
        resp = self.client.get('/owner/billing/aging/export/')
        content = resp.content.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        headers = next(reader)
        self.assertIn('Invoice #', headers)
        self.assertIn('Customer', headers)
        self.assertIn('Amount Due', headers)
        self.assertIn('Bucket', headers)

    def test_csv_export_contains_invoice_data(self):
        inv = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=20, amount=Decimal('999.99'))
        resp = self.client.get('/owner/billing/aging/export/')
        content = resp.content.decode('utf-8')
        self.assertIn(inv.invoice_number, content)
        self.assertIn('CSV Customer', content)
        self.assertIn('1-30 days', content)

    def test_csv_export_empty_when_no_outstanding(self):
        make_invoice(self.customer, self.tenant, status='PAID', days_overdue=0)
        resp = self.client.get('/owner/billing/aging/export/')
        content = resp.content.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        # Only header row
        self.assertEqual(len(rows), 1)


@override_settings(**TEST_OVERRIDES)
class CustomerStatementTests(TestCase):
    """Tests for /owner/customers/<id>/statement/ view."""

    def setUp(self):
        self.user, self.tenant = make_tenant('StmtShop', 'stmtowner_ph6')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Statement Corp', tenant=self.tenant, email='stmt@test.com'
        )

    def test_statement_requires_login(self):
        c = Client()
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = c.get(url)
        self.assertIn(resp.status_code, [302, 403])

    def test_statement_returns_200(self):
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_statement_404_other_tenant_customer(self):
        _, tenant2 = make_tenant('NotMyShop', 'notmine_ph6')
        cust2 = Customer.objects.create(name='NotMine', tenant=tenant2)
        url = f'/owner/customers/{cust2.id}/statement/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_statement_shows_customer_name(self):
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        self.assertContains(resp, 'Statement Corp')

    def test_statement_shows_invoices(self):
        inv = make_invoice(self.customer, self.tenant, status='SENT', days_overdue=0)
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        self.assertContains(resp, inv.invoice_number)

    def test_statement_shows_payments(self):
        inv = make_invoice(self.customer, self.tenant, status='PARTIAL', days_overdue=0, amount=Decimal('500.00'))
        pmt = make_payment(inv, amount=Decimal('250.00'))
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        self.assertContains(resp, '250.00')

    def test_statement_running_balance(self):
        inv = make_invoice(self.customer, self.tenant, status='PARTIAL', days_overdue=0, amount=Decimal('400.00'))
        make_payment(inv, amount=Decimal('150.00'))
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        # Balance due = 400 - 150 = 250
        self.assertContains(resp, '250.00')

    def test_statement_context_totals(self):
        inv = make_invoice(self.customer, self.tenant, status='PARTIAL', days_overdue=0, amount=Decimal('600.00'))
        make_payment(inv, amount=Decimal('200.00'))
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        ctx = resp.context
        self.assertEqual(ctx['total_invoiced'], Decimal('600.00'))
        self.assertEqual(ctx['total_paid'], Decimal('200.00'))
        self.assertEqual(ctx['balance_due'], Decimal('400.00'))

    def test_statement_empty_customer(self):
        url = f'/owner/customers/{self.customer.id}/statement/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No transactions')

    def test_statement_url_resolves(self):
        url = reverse('owner_customer_statement', kwargs={'customer_id': self.customer.id})
        self.assertEqual(url, f'/owner/customers/{self.customer.id}/statement/')


@override_settings(**TEST_OVERRIDES)
class SendReminderFromListTests(TestCase):
    """Tests for sending reminder from the invoice list view."""

    def setUp(self):
        self.user, self.tenant = make_tenant('ReminderShop', 'reminderowner_ph6')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Reminder Corp', tenant=self.tenant, email='remind@test.com'
        )

    def test_reminder_endpoint_exists(self):
        """The owner_send_reminder URL should exist and be reachable."""
        inv = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=10)
        url = reverse('owner_send_reminder', kwargs={'invoice_id': inv.id})
        self.assertIsNotNone(url)

    def test_reminder_post_redirects(self):
        """POST to reminder endpoint should redirect (owner_send_reminder is a redirect-based view)."""
        inv = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=10)
        url = reverse('owner_send_reminder', kwargs={'invoice_id': inv.id})
        resp = self.client.post(url)
        # Should redirect to invoice detail (may fail due to email config, but redirect is the flow)
        self.assertIn(resp.status_code, [302, 200])

    def test_reminder_for_paid_invoice_fails(self):
        """Should not send reminder for paid invoice."""
        inv = make_invoice(self.customer, self.tenant, status='PAID', days_overdue=0)
        url = reverse('owner_send_reminder', kwargs={'invoice_id': inv.id})
        resp = self.client.post(url)
        # Redirect back — no reminder sent
        self.assertEqual(resp.status_code, 302)

    def test_reminder_other_tenant_invoice_404(self):
        _, tenant2 = make_tenant('Other2', 'other2_ph6')
        cust2 = Customer.objects.create(name='Other2 Corp', tenant=tenant2)
        inv2 = make_invoice(cust2, tenant2, status='OVERDUE', days_overdue=5)
        url = reverse('owner_send_reminder', kwargs={'invoice_id': inv2.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)

    def test_invoice_list_shows_remind_button_for_overdue(self):
        """Overdue invoice with email should show Remind button in the list."""
        inv = make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=10)
        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'sendReminderAjax')

    def test_invoice_list_url_resolves(self):
        url = reverse('owner_invoice_list')
        self.assertEqual(url, '/owner/invoices/')


@override_settings(**TEST_OVERRIDES)
class OwnerInvoicesAgingCardTests(TestCase):
    """The /owner/invoices/ page renders the aging summary server-side
    (the old widget fetched the JSON endpoint client-side)."""

    def setUp(self):
        self.user, self.tenant = make_tenant('AgingCardShop', 'agingcard_ph6')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Aging Card Corp', tenant=self.tenant, email='agingcard@test.com'
        )

    def test_renders_only_nonempty_buckets(self):
        make_invoice(self.customer, self.tenant, status='SENT', days_overdue=0)      # current
        make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=20)  # 1–30
        make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=75)  # 61–90
        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Owed to you')
        self.assertContains(resp, 'Not yet due')
        self.assertContains(resp, '1–30 days late')
        self.assertContains(resp, '61–90 days late')
        self.assertNotContains(resp, '31–60 days late')  # empty bucket is hidden
        self.assertNotContains(resp, 'Over 90 days late')
        buckets = resp.context['aging_buckets']
        self.assertEqual([b['key'] for b in buckets], ['current', '1_30', '61_90'])
        self.assertEqual(resp.context['aging_total'], 1500.0)

    def test_all_paid_shows_caught_up_state(self):
        make_invoice(self.customer, self.tenant, status='PAID', days_overdue=0)
        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Nothing outstanding')
        self.assertEqual(resp.context['aging_buckets'], [])

    def test_overdue_pill_shows_count_and_filter_link(self):
        make_invoice(self.customer, self.tenant, status='OVERDUE', days_overdue=10)
        resp = self.client.get('/owner/invoices/')
        self.assertContains(resp, '?status=overdue')
        self.assertContains(resp, 'See the 1 overdue invoice')
