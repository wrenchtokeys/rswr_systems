"""
CODE-151: Regression test — InvoiceLineItem.save() overrides explicit $0.00 amounts.

Bug: The `save()` method on InvoiceLineItem used `if not self.amount:` as the guard
before auto-computing amount from (unit_price × quantity - discount).

`Decimal('0.00')` is falsy in Python, so this guard fired for ANY $0.00 amount —
including amounts that were intentionally set to zero by the caller.

This broke FREE_SERVICE reward redemptions: when InvoiceTrackingService creates a
line item for a repair with a FREE reward applied, get_discounted_cost() returns
final_cost=Decimal('0.00'). The service explicitly passes amount=Decimal('0.00')
to InvoiceLineItem.objects.create(). But .save() immediately overrode it to
unit_price * 1 - 0 = unit_price (e.g. $50), effectively removing the customer's
free repair benefit from the invoice.

Fix: Changed the guard from `if not self.amount:` to `if self.amount is None:`.
Only None (the absence of any value) triggers the auto-calculation. An explicit
Decimal('0.00') is preserved as-is.

Tests verify:
1. Explicit amount=Decimal('0.00') is preserved through save() — not overridden.
2. amount=None triggers auto-calculation from (unit_price × quantity - discount).
3. Non-zero amounts are preserved unchanged.
4. A fully-discounted line item (discount == unit_price, amount=0) works correctly.
5. A FREE reward freebie line item (amount=0, discount=0) retains $0.00.
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User

from apps.tenants.models import Tenant
from core.models import Customer
from apps.billing.models import Invoice, InvoiceLineItem


def _make_invoice(tenant, suffix=""):
    """Create a minimal invoice for tests."""
    customer = Customer.objects.create(
        name=f"Test Customer 151 {suffix}",
        tenant=tenant,
    )
    invoice = Invoice.objects.create(
        tenant=tenant,
        invoice_number=f"INV-151-{suffix}",
        customer=customer,
        status='DRAFT',
        subtotal=Decimal('0.00'),
        total=Decimal('0.00'),
    )
    return invoice


class InvoiceLineItemZeroAmountTest(TestCase):
    """
    Verify that InvoiceLineItem.save() uses `is None` semantics so that
    explicit $0.00 amounts are not overridden by the auto-compute fallback.
    """

    def setUp(self):
        owner = User.objects.create_user(
            username="owner_151",
            password="testpass",
            email="owner_151@example.com",
        )
        self.tenant = Tenant.objects.create(
            name="LineItem Test Shop 151",
            slug="lineitem-test-shop-151",
            owner=owner,
        )

    def test_explicit_zero_amount_preserved(self):
        """
        Explicit amount=Decimal('0.00') must survive save().
        This is the core CODE-151 scenario: a FREE reward line item that
        costs $0 should NOT be overridden to unit_price.
        """
        invoice = _make_invoice(self.tenant, "a")
        line = InvoiceLineItem.objects.create(
            invoice=invoice,
            description="Free repair (reward)",
            quantity=1,
            unit_price=Decimal('50.00'),
            discount=Decimal('0.00'),
            amount=Decimal('0.00'),   # explicitly set to $0 by caller
        )
        line.refresh_from_db()
        self.assertEqual(
            line.amount,
            Decimal('0.00'),
            "Explicit amount=0.00 must be preserved; save() must not override it to unit_price.",
        )

    def test_none_amount_triggers_auto_calculate(self):
        """
        When amount is NOT provided (defaults to None), save() should
        auto-compute it from (unit_price × quantity) - discount.
        """
        invoice = _make_invoice(self.tenant, "b")
        line = InvoiceLineItem(
            invoice=invoice,
            description="Auto-calc line item",
            quantity=2,
            unit_price=Decimal('25.00'),
            discount=Decimal('5.00'),
        )
        # amount field defaults to None before first save
        self.assertIsNone(line.amount)
        line.save()
        line.refresh_from_db()
        # Expected: (25.00 × 2) − 5.00 = 45.00
        self.assertEqual(
            line.amount,
            Decimal('45.00'),
            "amount=None should auto-compute to (unit_price * qty) - discount.",
        )

    def test_nonzero_amount_preserved(self):
        """Non-zero explicit amounts should pass through unchanged."""
        invoice = _make_invoice(self.tenant, "c")
        line = InvoiceLineItem.objects.create(
            invoice=invoice,
            description="Partial discount line item",
            quantity=1,
            unit_price=Decimal('75.00'),
            discount=Decimal('10.00'),
            amount=Decimal('65.00'),   # explicitly set
        )
        line.refresh_from_db()
        self.assertEqual(
            line.amount,
            Decimal('65.00'),
            "Explicit non-zero amount must be preserved by save().",
        )

    def test_fully_discounted_line_item_zero_amount(self):
        """
        Line item where discount == unit_price → amount=0 should stay $0.
        This models a 100% discount scenario (different from FREE reward but
        same math).
        """
        invoice = _make_invoice(self.tenant, "d")
        line = InvoiceLineItem.objects.create(
            invoice=invoice,
            description="100% discounted repair",
            quantity=1,
            unit_price=Decimal('100.00'),
            discount=Decimal('100.00'),  # full discount
            amount=Decimal('0.00'),        # InvoiceTrackingService sets this explicitly
        )
        line.refresh_from_db()
        self.assertEqual(
            line.amount,
            Decimal('0.00'),
            "Fully-discounted line item (discount==unit_price, amount=0) must stay $0.",
        )

    def test_resave_preserves_zero_amount(self):
        """
        Re-saving a line item that was explicitly set to $0 must not
        recalculate the amount (e.g. when description or notes are updated).
        """
        invoice = _make_invoice(self.tenant, "e")
        line = InvoiceLineItem.objects.create(
            invoice=invoice,
            description="Free service",
            quantity=1,
            unit_price=Decimal('50.00'),
            discount=Decimal('0.00'),
            amount=Decimal('0.00'),
        )
        # Update an unrelated field and re-save
        line.description = "Free service (updated)"
        line.save()
        line.refresh_from_db()
        self.assertEqual(
            line.amount,
            Decimal('0.00'),
            "Re-saving a $0 line item must not override amount to unit_price.",
        )

    def test_auto_calculate_with_no_discount(self):
        """Auto-calc path with discount=0 gives unit_price × quantity."""
        invoice = _make_invoice(self.tenant, "f")
        line = InvoiceLineItem(
            invoice=invoice,
            description="Standard repair",
            quantity=1,
            unit_price=Decimal('50.00'),
            discount=Decimal('0.00'),
        )
        line.save()
        line.refresh_from_db()
        self.assertEqual(
            line.amount,
            Decimal('50.00'),
            "Auto-calc with no discount should give unit_price.",
        )
