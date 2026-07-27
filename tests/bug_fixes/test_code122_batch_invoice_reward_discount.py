"""
CODE-122 regression tests: _create_batch_invoice() must apply
get_discounted_cost() for reward-based discounts, not raw repair.cost.

Bug:  _create_batch_invoice() used `repair.cost` directly when building line
      items.  Customers with REPAIR_DISCOUNT or FREE_SERVICE reward redemptions
      were overbilled — their earned discounts were silently ignored on every
      batch invoice.

Fix:  Use repair.get_discounted_cost() (same pattern as
      InvoiceTrackingService.create_invoice_from_repairs).  The invoice
      discount field and total are updated accordingly.  Tax is computed on
      the discounted net (subtotal − discount) so customers aren't charged
      sales tax on savings they already earned.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.tenants.models import Tenant
from core.models import Customer
from apps.technician_portal.models import Repair, Technician
from apps.customer_portal.models import CustomerRepairPreference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_counter = [0]


def _uid():
    _counter[0] += 1
    return _counter[0]


def _make_tenant(name=None):
    i = _uid()
    name = name or f'BatchDiscountShop{i}'
    owner = User.objects.create_user(username=f'owner_bd{i}', password='x')
    tenant = Tenant.objects.create(
        name=name,
        slug=f'bd-shop-{i}',
        owner=owner,
        is_active=True,
    )
    config, _ = BillingConfig.objects.get_or_create(tenant=tenant)
    config.batch_invoice_frequency = 'weekly'
    config.batch_invoice_day = 0
    config.batch_invoice_auto_send = False  # don't try to email in tests
    config.default_payment_terms = 'NET30'
    config.tax_enabled = False
    config.invoice_number_prefix = 'INV'
    config.save()
    return tenant, config


def _make_customer(tenant, email='fleet@example.com'):
    i = _uid()
    c = Customer.objects.create(tenant=tenant, name=f'Fleet Co {i}', email=email)
    # Set batch invoice preference so _create_batch_invoice includes this customer
    CustomerRepairPreference.objects.create(customer=c, invoice_preference='batch')
    return c


def _make_tech(tenant):
    i = _uid()
    u = User.objects.create_user(username=f'tech_bd{i}', password='x')
    return Technician.objects.create(tenant=tenant, user=u, is_active=True)


def _make_repair(tenant, customer, tech, cost=Decimal('50.00'), status='COMPLETED'):
    i = _uid()
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=tech,
        unit_number=f'T-{i:03d}',
        damage_type='Chip',
        queue_status=status,
        cost=cost,
        service_date=timezone.now().date(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class BatchInvoiceRewardDiscountTests(TestCase):
    """CODE-122: batch invoice applies get_discounted_cost() for rewards."""

    def setUp(self):
        self.tenant, self.config = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.tech = _make_tech(self.tenant)

    # ------------------------------------------------------------------
    # 1. No reward → line item amount == repair.cost
    # ------------------------------------------------------------------

    def test_no_discount_line_item_equals_cost(self):
        """When no reward is applied, line item amount == repair.cost (whatever pricing set it to)."""
        repair = _make_repair(self.tenant, self.customer, self.tech)
        # Refresh to get the actual cost (pricing service may recalculate during save)
        repair.refresh_from_db()
        expected_cost = repair.cost

        from apps.billing.tasks import _create_batch_invoice
        invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        self.assertIsNotNone(invoice, "Invoice should be created")
        items = InvoiceLineItem.objects.filter(invoice=invoice)
        self.assertEqual(items.count(), 1)
        item = items.first()
        self.assertEqual(item.amount, expected_cost)
        self.assertEqual(item.unit_price, expected_cost)
        self.assertEqual(item.discount, Decimal('0.00'))
        self.assertEqual(invoice.discount, Decimal('0.00'))
        self.assertEqual(invoice.total, expected_cost)

    # ------------------------------------------------------------------
    # 2. Discount via get_discounted_cost() → line item reflects savings
    # ------------------------------------------------------------------

    def test_discount_applied_to_line_item(self):
        """When get_discounted_cost() returns a discount, line item and invoice totals reflect it."""
        repair = _make_repair(self.tenant, self.customer, self.tech, cost=Decimal('100.00'))

        discounted_data = {
            'original_cost': Decimal('100.00'),
            'final_cost': Decimal('75.00'),
            'discount_applied': True,
            'discount_description': '25% off',
            'savings': Decimal('25.00'),
        }

        from apps.billing.tasks import _create_batch_invoice
        with patch.object(
            repair.__class__,
            'get_discounted_cost',
            return_value=discounted_data,
        ):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        self.assertIsNotNone(invoice)
        item = InvoiceLineItem.objects.get(invoice=invoice)
        self.assertEqual(item.unit_price, Decimal('100.00'), "unit_price = original cost")
        self.assertEqual(item.discount, Decimal('25.00'), "discount = savings")
        self.assertEqual(item.amount, Decimal('75.00'), "amount = final cost after discount")

        # Invoice-level fields
        invoice.refresh_from_db()
        self.assertEqual(invoice.subtotal, Decimal('100.00'))
        self.assertEqual(invoice.discount, Decimal('25.00'))
        self.assertEqual(invoice.total, Decimal('75.00'))

    # ------------------------------------------------------------------
    # 3. FREE_SERVICE (100% off) → total=0, discount=original cost
    # ------------------------------------------------------------------

    def test_free_service_discount(self):
        """A FREE reward results in line item amount=0 and invoice total=0."""
        repair = _make_repair(self.tenant, self.customer, self.tech, cost=Decimal('50.00'))

        free_data = {
            'original_cost': Decimal('50.00'),
            'final_cost': Decimal('0.00'),
            'discount_applied': True,
            'discount_description': 'Free repair',
            'savings': Decimal('50.00'),
        }

        from apps.billing.tasks import _create_batch_invoice
        with patch.object(repair.__class__, 'get_discounted_cost', return_value=free_data):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        self.assertIsNotNone(invoice)
        item = InvoiceLineItem.objects.get(invoice=invoice)
        self.assertEqual(item.amount, Decimal('0.00'))
        self.assertEqual(item.discount, Decimal('50.00'))

        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal('0.00'))
        self.assertEqual(invoice.discount, Decimal('50.00'))

    # ------------------------------------------------------------------
    # 4. Tax is computed on discounted net, not pre-discount subtotal
    # ------------------------------------------------------------------

    def test_tax_computed_on_discounted_net(self):
        """Tax base = subtotal - discount (not raw subtotal)."""
        from apps.billing.models import TaxRate
        # Tax overhaul: the config flag decides IF tax applies
        self.config.tax_enabled = True
        self.config.save()
        TaxRate.objects.create(
            tenant=self.tenant,
            city='TestCity',
            state='AR',
            state_rate=Decimal('6.5'),
            county_rate=Decimal('1.0'),
            city_rate=Decimal('0.0'),
            special_rate=Decimal('0.0'),
            is_active=True,
        )

        repair = _make_repair(self.tenant, self.customer, self.tech, cost=Decimal('100.00'))

        discounted_data = {
            'original_cost': Decimal('100.00'),
            'final_cost': Decimal('80.00'),  # $20 discount
            'discount_applied': True,
            'discount_description': '20% off',
            'savings': Decimal('20.00'),
        }

        from apps.billing.tasks import _create_batch_invoice
        with patch.object(repair.__class__, 'get_discounted_cost', return_value=discounted_data):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        invoice.refresh_from_db()
        # Taxable base = $80 (discounted net)
        # Tax rate = 7.5% (state 6.5% + county 1.0%)
        expected_tax = (Decimal('80.00') * Decimal('7.5') / Decimal('100')).quantize(Decimal('0.01'))
        self.assertAlmostEqual(float(invoice.tax_amount), float(expected_tax), places=2,
                               msg="Tax should be computed on discounted net, not original subtotal")
        # Total = 80 + tax (not 100 + tax)
        self.assertAlmostEqual(float(invoice.total), float(Decimal('80.00') + expected_tax), places=2)

    # ------------------------------------------------------------------
    # 5. Multi-repair batch — discounts cumulate correctly
    # ------------------------------------------------------------------

    def test_multi_repair_batch_cumulative_discount(self):
        """Multiple repairs: each discount is summed into invoice.discount."""
        repair1 = _make_repair(self.tenant, self.customer, self.tech)
        repair2 = _make_repair(self.tenant, self.customer, self.tech)
        repair1.refresh_from_db()
        repair2.refresh_from_db()
        cost1 = repair1.cost
        cost2 = repair2.cost
        # First repair gets $10 discount, second has none
        discount_amt = Decimal('10.00')
        final1 = cost1 - discount_amt

        r1_id = repair1.id

        def _side_effect_discounted(self_repair):
            if self_repair.id == r1_id:
                return {
                    'original_cost': cost1,
                    'final_cost': final1,
                    'discount_applied': True,
                    'discount_description': '$10 off',
                    'savings': discount_amt,
                }
            return {
                'original_cost': cost2,
                'final_cost': cost2,
                'discount_applied': False,
                'discount_description': '',
                'savings': Decimal('0.00'),
            }

        from apps.billing.tasks import _create_batch_invoice
        with patch.object(Repair, 'get_discounted_cost', _side_effect_discounted):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        invoice.refresh_from_db()
        expected_subtotal = cost1 + cost2
        expected_total = expected_subtotal - discount_amt
        self.assertEqual(invoice.subtotal, expected_subtotal)
        self.assertEqual(invoice.discount, discount_amt)
        self.assertEqual(invoice.total, expected_total)

    # ------------------------------------------------------------------
    # 6. Before fix: raw repair.cost would overbill discounted customers
    #    This test proves the old path would have produced wrong totals.
    # ------------------------------------------------------------------

    def test_old_path_would_overbill(self):
        """
        Demonstrates that using repair.cost directly (old code) produces
        a higher total than the fix. The fix produces the correct discounted total.
        """
        repair = _make_repair(self.tenant, self.customer, self.tech, cost=Decimal('100.00'))

        discounted_data = {
            'original_cost': Decimal('100.00'),
            'final_cost': Decimal('70.00'),
            'discount_applied': True,
            'discount_description': '30% off',
            'savings': Decimal('30.00'),
        }

        from apps.billing.tasks import _create_batch_invoice
        with patch.object(repair.__class__, 'get_discounted_cost', return_value=discounted_data):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        invoice.refresh_from_db()
        # Correct: customer should pay $70
        self.assertEqual(invoice.total, Decimal('70.00'),
                         "Customer should be billed discounted price, not full price")
        # Overbill sanity check: total must NOT equal the full $100
        self.assertNotEqual(invoice.total, Decimal('100.00'),
                            "Bug regression: batch invoice must not ignore reward discounts")
