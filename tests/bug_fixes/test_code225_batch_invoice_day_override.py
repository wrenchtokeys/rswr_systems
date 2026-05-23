"""
CODE-225: Regression test — process_batch_invoices() ignores per-customer
batch_invoice_day override in CustomerRepairPreference.

Bug: CustomerRepairPreference.batch_invoice_day is a per-customer override
for the day of the month to generate their batch invoice.  However,
process_batch_invoices() in billing/tasks.py called _should_run_batch_today()
once per tenant using only the shop's BillingConfig.batch_invoice_day.  The
result was:

  1. If today == shop day: ALL batch customers were invoiced, even those whose
     override day is different from today.
  2. If today != shop day: ALL batch customers were skipped, even those whose
     override day matches today.

Fix (CODE-225): For monthly frequency, iterate batch customers with their
preferences and apply per-customer effective_day:
  effective_day = pref.batch_invoice_day or config.batch_invoice_day

Each customer is only invoiced when today.day == effective_day.

For weekly/biweekly: customer-level override not applicable (field is 1-28
monthly only), so the original single-gate logic is preserved.

Tests verify:
1. Customer with no override is invoiced on the shop default day.
2. Customer with no override is NOT invoiced on a non-matching day.
3. Customer with override IS invoiced on their override day (even when shop day != today).
4. Customer with override is NOT invoiced when neither shop day nor override day matches.
5. Two customers with different override days are each invoiced only on their own day.
6. Weekly batch: all-or-none gate (original behavior preserved).

NOTE: All tests use ``django.utils.timezone.now().date()`` (not ``datetime.date.today()``)
to determine "today" — the same source used inside ``process_batch_invoices()``.  Using
``date.today()`` would fail at UTC midnight when the local date lags UTC.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from apps.billing.models import BillingConfig, Invoice
from apps.billing.tasks import process_batch_invoices
from apps.customer_portal.models import CustomerRepairPreference
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.technician_portal.models import Repair, Technician


# =============================================================================
# Helpers
# =============================================================================

def _today():
    """Return today's date using the same source as process_batch_invoices()."""
    return timezone.now().date()


def _make_tenant(name='Shop A'):
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "_")}',
        email=f'owner_{name.lower().replace(" ", "_")}@test.com',
        password='pass',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        owner=owner,
        is_active=True,
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    BillingConfig.objects.create(
        tenant=tenant,
        batch_invoice_frequency='monthly',
        batch_invoice_day=1,          # shop default: invoice on the 1st
        default_payment_terms='NET30',
        batch_invoice_auto_send=False,
    )
    return tenant


def _make_customer(tenant, name='Fleet Co', with_prefs=True, batch_day_override=None):
    customer = Customer.objects.create(
        tenant=tenant,
        name=name,
        email=f'{name.lower().replace(" ", "")}@fleet.com',
    )
    if with_prefs:
        CustomerRepairPreference.objects.create(
            customer=customer,
            invoice_preference='batch',
            batch_invoice_day=batch_day_override,   # None = use shop default
        )
    return customer


def _make_completed_repair(tenant, customer):
    """Create a minimal completed repair so there is something to invoice."""
    tech_user = User.objects.create_user(
        username=f'tech_c{customer.id}',
        email=f'tech_c{customer.id}@test.com',
        password='pass',
    )
    tech = Technician.objects.create(user=tech_user, tenant=tenant, is_active=True)
    repair = Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=tech,
        unit_number='UNIT-1',
        damage_type='chip',
        queue_status='COMPLETED',
        cost=Decimal('45.00'),
    )
    return repair


# =============================================================================
# Tests
# =============================================================================

class BatchInvoiceDayOverrideTests(TestCase):
    """process_batch_invoices() respects CustomerRepairPreference.batch_invoice_day."""

    def setUp(self):
        self.tenant = _make_tenant('Override Shop')
        self.today = _today()

    def test_no_override_invoiced_on_shop_day(self):
        """Customer without override is invoiced when today == shop's batch_invoice_day."""
        customer = _make_customer(self.tenant, 'No Override Fleet', batch_day_override=None)
        _make_completed_repair(self.tenant, customer)

        # Set shop day to today so invoicing fires
        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_day = self.today.day
        config.save()

        result = process_batch_invoices()
        self.assertEqual(
            result['invoices_created'], 1,
            "Should invoice customer on their effective day (shop default)"
        )

    def test_no_override_not_invoiced_on_wrong_day(self):
        """Customer without override is NOT invoiced when today != shop's batch_invoice_day."""
        customer = _make_customer(self.tenant, 'Wrong Day Fleet', batch_day_override=None)
        _make_completed_repair(self.tenant, customer)

        # Set shop day to something that is NOT today
        wrong_day = (self.today.day % 28) + 1  # guaranteed != today.day for any valid day
        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_day = wrong_day
        config.save()

        result = process_batch_invoices()
        self.assertEqual(
            result['invoices_created'], 0,
            "Should NOT invoice customer when today != shop day and no override"
        )

    def test_override_customer_invoiced_on_override_day(self):
        """Customer with batch_invoice_day override is invoiced on THEIR day, not the shop day."""
        # Override day = today, shop day = something else
        customer_day = self.today.day
        shop_day = (self.today.day % 28) + 1  # != today.day

        customer = _make_customer(self.tenant, 'Override Fleet', batch_day_override=customer_day)
        _make_completed_repair(self.tenant, customer)

        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_day = shop_day   # shop day does NOT match today
        config.save()

        result = process_batch_invoices()
        self.assertEqual(
            result['invoices_created'], 1,
            "Customer with override matching today should be invoiced even when shop day doesn't match"
        )

    def test_override_customer_not_invoiced_on_wrong_day(self):
        """Customer with override is NOT invoiced when today matches neither shop day nor override day."""
        # Both shop day and customer day are NOT today
        shop_day = (self.today.day % 28) + 1
        customer_day = (shop_day % 28) + 1
        # Safety: ensure customer_day != today.day (edge case when all values wrap to today)
        if customer_day == self.today.day:
            self.skipTest("Date arithmetic collision; cannot construct non-today days on this date")

        customer = _make_customer(self.tenant, 'Bad Day Fleet', batch_day_override=customer_day)
        _make_completed_repair(self.tenant, customer)

        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_day = shop_day
        config.save()

        result = process_batch_invoices()
        self.assertEqual(
            result['invoices_created'], 0,
            "Should NOT invoice when today matches neither shop day nor customer override"
        )

    def test_two_customers_different_override_days(self):
        """Two customers with different override days are each invoiced only on their own day."""
        # Customer A's day = today; Customer B's day != today
        day_a = self.today.day
        day_b = (self.today.day % 28) + 1

        customer_a = _make_customer(self.tenant, 'Fleet A', batch_day_override=day_a)
        customer_b = _make_customer(self.tenant, 'Fleet B', batch_day_override=day_b)
        _make_completed_repair(self.tenant, customer_a)
        _make_completed_repair(self.tenant, customer_b)

        # Shop day doesn't match either customer (both have overrides)
        shop_day = (day_b % 28) + 1
        if shop_day == day_a:
            shop_day = (shop_day % 28) + 1
        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_day = shop_day
        config.save()

        result = process_batch_invoices()
        self.assertEqual(
            result['invoices_created'], 1,
            "Only Customer A (override=today) should be invoiced; Customer B (override!=today) should not"
        )
        # Verify it was customer_a that got invoiced, not customer_b
        self.assertTrue(
            Invoice.objects.filter(tenant=self.tenant, customer=customer_a).exists(),
            "Customer A should have an invoice"
        )
        self.assertFalse(
            Invoice.objects.filter(tenant=self.tenant, customer=customer_b).exists(),
            "Customer B should NOT have an invoice yet"
        )

    def test_weekly_frequency_all_or_none(self):
        """Weekly frequency uses shop day only (per-customer override not applicable)."""
        # Set shop to today's weekday
        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_frequency = 'weekly'
        config.batch_invoice_day = self.today.weekday()  # 0=Mon, 6=Sun
        config.save()

        customer_a = _make_customer(self.tenant, 'Weekly Fleet A', batch_day_override=None)
        customer_b = _make_customer(self.tenant, 'Weekly Fleet B', batch_day_override=15)  # override ignored for weekly
        _make_completed_repair(self.tenant, customer_a)
        _make_completed_repair(self.tenant, customer_b)

        result = process_batch_invoices()
        # Both should be invoiced because it's the shop's weekly day
        self.assertEqual(
            result['invoices_created'], 2,
            "Both customers should be invoiced on the shop's weekly day regardless of batch_invoice_day override"
        )

    def test_shop_default_used_when_no_override(self):
        """Customer with no override uses the shop's batch_invoice_day."""
        customer = _make_customer(self.tenant, 'No Override 2', batch_day_override=None)
        _make_completed_repair(self.tenant, customer)

        config = BillingConfig.objects.get(tenant=self.tenant)
        config.batch_invoice_day = self.today.day   # shop day = today → should invoice
        config.save()

        result = process_batch_invoices()
        self.assertEqual(result['invoices_created'], 1)
