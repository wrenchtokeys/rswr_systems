"""
Tests for CODE-134: Customer portal displaying "None" for blank nullable fields.

Three bugs:
1. dashboard.html — showed "Phone: None", "Email: None", "Address: None"
   when customer has no phone/email/address. Template lacked {% if %} guards.

2. repair_detail.html — showed "Description: None" when repair.description
   is blank. Template lacked {% if repair.description %} guard.

3. invoice_detail.html — tax breakdown showed "—" for individual tax
   line amounts (state, county, city, special) instead of calculated values.
   The model had per-rate fields but no per-amount fields or properties.

Fixes:
- dashboard.html: wrap email/phone/address rows in {% if %} guards.
- repair_detail.html: wrap description row in {% if repair.description %}.
- billing/models.py: add state_tax_amount, county_tax_amount, city_tax_amount,
  special_tax_amount properties (rate × subtotal / 100).
- invoice_detail.html: replace "—" with {{ invoice.*_tax_amount|floatformat:2 }},
  and only render the state tax row when state_tax_rate > 0 (was always shown).
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice
from core.models import Customer

User = get_user_model()


def _make_plan(slug):
    return SubscriptionPlan.objects.create(
        name=f'Plan {slug}', slug=slug, monthly_price=50, is_active=True
    )


def _make_tenant(plan, slug):
    owner = User.objects.create_user(
        username=f'owner_{slug}', password='test', email=f'{slug}@example.com'
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}', slug=slug,
        subscription_plan=plan,
        business_email=f'{slug}@example.com',
        owner=owner,
    )
    TenantMembership.objects.create(
        tenant=tenant, user=owner, role='owner', is_active=True
    )
    return tenant


class InvoiceTaxAmountPropertiesTest(TestCase):
    """
    Unit tests for the four new tax amount properties on Invoice.
    These should compute rate × subtotal / 100.
    """

    def setUp(self):
        plan = _make_plan('tax-prop-134')
        self.tenant = _make_tenant(plan, 'tax-prop-134')
        self.customer = Customer.objects.create(
            name='Test Customer', tenant=self.tenant
        )

    def _make_invoice(self, subtotal, state_rate=0, county_rate=0, city_rate=0, special_rate=0):
        combined = state_rate + county_rate + city_rate + special_rate
        tax_amount = (subtotal * Decimal(str(combined)) / Decimal('100')).quantize(Decimal('0.01'))
        return Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=f'INV-T-{Invoice.objects.count()+1}',
            subtotal=subtotal,
            total=subtotal + tax_amount,
            tax_rate=Decimal(str(combined)),
            state_tax_rate=Decimal(str(state_rate)),
            county_tax_rate=Decimal(str(county_rate)),
            city_tax_rate=Decimal(str(city_rate)),
            special_tax_rate=Decimal(str(special_rate)),
            tax_amount=tax_amount,
        )

    def test_state_tax_amount_calculated(self):
        """state_tax_amount = subtotal * state_tax_rate / 100."""
        inv = self._make_invoice(Decimal('100.00'), state_rate=6)
        self.assertEqual(inv.state_tax_amount, Decimal('6.00'))

    def test_county_tax_amount_calculated(self):
        """county_tax_amount = subtotal * county_tax_rate / 100."""
        inv = self._make_invoice(Decimal('200.00'), county_rate=2)
        self.assertEqual(inv.county_tax_amount, Decimal('4.00'))

    def test_city_tax_amount_calculated(self):
        """city_tax_amount = subtotal * city_tax_rate / 100."""
        inv = self._make_invoice(Decimal('150.00'), city_rate=1)
        self.assertEqual(inv.city_tax_amount, Decimal('1.50'))

    def test_special_tax_amount_calculated(self):
        """special_tax_amount = subtotal * special_tax_rate / 100."""
        inv = self._make_invoice(Decimal('100.00'), special_rate=0.5)
        self.assertEqual(inv.special_tax_amount, Decimal('0.50'))

    def test_all_four_rates_combined(self):
        """All four properties work together; individual amounts sum to tax_amount."""
        inv = self._make_invoice(
            Decimal('100.00'), state_rate=6, county_rate=2, city_rate=1, special_rate=0.5
        )
        total_by_parts = (
            inv.state_tax_amount +
            inv.county_tax_amount +
            inv.city_tax_amount +
            inv.special_tax_amount
        )
        # Sum should match the stored combined tax_amount (within rounding)
        self.assertAlmostEqual(float(total_by_parts), float(inv.tax_amount), places=1)

    def test_zero_rate_returns_zero(self):
        """A rate of zero returns Decimal('0.00'), not an error."""
        inv = self._make_invoice(Decimal('200.00'))  # no rates set
        self.assertEqual(inv.state_tax_amount, Decimal('0.00'))
        self.assertEqual(inv.county_tax_amount, Decimal('0.00'))
        self.assertEqual(inv.city_tax_amount, Decimal('0.00'))
        self.assertEqual(inv.special_tax_amount, Decimal('0.00'))

    def test_zero_subtotal_returns_zero(self):
        """Subtotal of zero returns zero amounts without errors."""
        inv = self._make_invoice(Decimal('0.00'), state_rate=6)
        self.assertEqual(inv.state_tax_amount, Decimal('0.00'))

    def test_fractional_rate_rounds_to_cents(self):
        """Fractional rates round to 2 decimal places (cents)."""
        # 6.375% of $100 = $6.375 → rounds to $6.38
        inv = self._make_invoice(Decimal('100.00'), state_rate=6.375)
        self.assertEqual(inv.state_tax_amount, Decimal('6.38'))


class CustomerPortalNullDisplayTest(TestCase):
    """
    Smoke tests that the Customer model fields don't become 'None' strings.
    These verify the model fields are nullable (template guards must handle display).
    """

    def setUp(self):
        plan = _make_plan('null-display-134')
        self.tenant = _make_tenant(plan, 'null-display-134')

    def test_customer_phone_nullable(self):
        """Customer.phone can be None — template must guard before displaying."""
        customer = Customer.objects.create(
            name='No Phone Corp', tenant=self.tenant, phone=None
        )
        self.assertIsNone(customer.phone)
        # The string representation of None would be "None" — verify field is actual None
        self.assertNotEqual(str(customer.phone), '')  # None is not ""
        self.assertEqual(str(customer.phone), 'None')  # This is what template would show

    def test_customer_email_nullable(self):
        """Customer.email can be None — template must guard before displaying."""
        customer = Customer.objects.create(
            name='No Email Corp', tenant=self.tenant, email=None
        )
        self.assertIsNone(customer.email)

    def test_customer_address_nullable(self):
        """Customer.address can be None — template must guard before displaying."""
        customer = Customer.objects.create(
            name='No Address Corp', tenant=self.tenant, address=None
        )
        self.assertIsNone(customer.address)
