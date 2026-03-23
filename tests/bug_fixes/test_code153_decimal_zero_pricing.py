"""
CODE-153: Regression tests for Decimal('0.00') falsy bug in pricing service.

Two locations used bare truthiness checks on Decimal fields:

1. CustomerPricing.get_repair_price() — "if self.repair_1_price:" treated
   Decimal('0.00') as "not configured", returning None and falling back to the
   standard $50 rate instead of honouring the intentional $0 custom price.

2. get_tenant_repair_price() — "tenant.repair_price_1 or DEFAULT_PRICING[1]"
   silently replaced a $0 tenant tier with the $50 system default.

This is the same Decimal-falsy anti-pattern fixed in CODE-132 (approval_limit)
and CODE-151 (InvoiceLineItem.save).  Both are documented in AGENTS.md.

Impact:
  - Customers configured for free service (warranty, goodwill, etc.) were
    silently charged the standard rate when a technician created a repair.
  - Tenants that set a $0 pricing tier (e.g. for promotional periods) always
    received the default price instead.
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User

from apps.customer_portal.pricing_models import CustomerPricing
from apps.technician_portal.services.pricing_service import (
    get_tenant_repair_price,
    calculate_repair_cost,
)
from core.models import Customer
from apps.tenants.models import Tenant


def _make_tenant(name, slug):
    """Create a Tenant with a required owner user."""
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='testpass',
    )
    return Tenant.objects.create(name=name, slug=slug, owner=owner)


class CustomerPricingZeroTest(TestCase):
    """CustomerPricing.get_repair_price() must treat Decimal('0.00') as a valid price."""

    def setUp(self):
        self.tenant = _make_tenant('Test Shop', 'test-shop')
        self.customer = Customer.objects.create(
            name='Free Service Fleet',
            tenant=self.tenant,
        )
        self.pricing = CustomerPricing.objects.create(
            customer=self.customer,
            use_custom_pricing=True,
            repair_1_price=Decimal('0.00'),
            repair_2_price=Decimal('0.00'),
            repair_3_price=Decimal('0.00'),
            repair_4_price=Decimal('0.00'),
            repair_5_plus_price=Decimal('0.00'),
        )

    def test_zero_price_tier1_not_treated_as_unset(self):
        """$0 custom price for tier 1 must return 0.00, not None."""
        result = self.pricing.get_repair_price(1)
        self.assertIsNotNone(result, "Decimal('0.00') must not be treated as None")
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_price_tier2_not_treated_as_unset(self):
        result = self.pricing.get_repair_price(2)
        self.assertIsNotNone(result)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_price_tier3_not_treated_as_unset(self):
        result = self.pricing.get_repair_price(3)
        self.assertIsNotNone(result)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_price_tier4_not_treated_as_unset(self):
        result = self.pricing.get_repair_price(4)
        self.assertIsNotNone(result)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_price_tier5plus_not_treated_as_unset(self):
        result = self.pricing.get_repair_price(5)
        self.assertIsNotNone(result)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_price_tier5plus_for_count_10(self):
        result = self.pricing.get_repair_price(10)
        self.assertIsNotNone(result)
        self.assertEqual(result, Decimal('0.00'))

    def test_null_price_tier_returns_none(self):
        """Null (unset) tier should still return None (fall back to default)."""
        pricing_partial = CustomerPricing.objects.create(
            customer=Customer.objects.create(name='Partial Fleet', tenant=self.tenant, email='partial@example.com'),
            use_custom_pricing=True,
            repair_1_price=Decimal('45.00'),
            repair_2_price=None,   # not configured
        )
        self.assertEqual(pricing_partial.get_repair_price(1), Decimal('45.00'))
        self.assertIsNone(pricing_partial.get_repair_price(2))

    def test_calculate_repair_cost_uses_zero_custom_price(self):
        """calculate_repair_cost() must propagate $0 custom price through to caller."""
        cost = calculate_repair_cost(self.customer, 1, self.tenant)
        self.assertEqual(cost, Decimal('0.00'),
                         "repair cost should be $0.00 for free-service account, not default $50")

    def test_non_zero_custom_price_unaffected(self):
        """Normal positive custom prices still work correctly."""
        pricing_normal = CustomerPricing.objects.create(
            customer=Customer.objects.create(name='Normal Fleet', tenant=self.tenant, email='normal@example.com'),
            use_custom_pricing=True,
            repair_1_price=Decimal('42.00'),
        )
        result = pricing_normal.get_repair_price(1)
        self.assertEqual(result, Decimal('42.00'))

    def test_custom_pricing_disabled_returns_none(self):
        """When use_custom_pricing=False, get_repair_price should return None regardless."""
        pricing_off = CustomerPricing.objects.create(
            customer=Customer.objects.create(name='Default Fleet', tenant=self.tenant, email='default@example.com'),
            use_custom_pricing=False,
            repair_1_price=Decimal('0.00'),
        )
        self.assertIsNone(pricing_off.get_repair_price(1))


class TenantPricingZeroTest(TestCase):
    """get_tenant_repair_price() must treat Decimal('0.00') as a valid configured price."""

    def setUp(self):
        self.tenant = _make_tenant('Zero Price Shop', 'zero-shop')
        # Set all pricing tiers to $0
        self.tenant.repair_price_1 = Decimal('0.00')
        self.tenant.repair_price_2 = Decimal('0.00')
        self.tenant.repair_price_3 = Decimal('0.00')
        self.tenant.repair_price_4 = Decimal('0.00')
        self.tenant.repair_price_5_plus = Decimal('0.00')
        self.tenant.save()

    def test_zero_tenant_price_tier1(self):
        result = get_tenant_repair_price(self.tenant, 1)
        self.assertEqual(result, Decimal('0.00'),
                         "Tenant $0 tier-1 price must not fall back to $50 default")

    def test_zero_tenant_price_tier2(self):
        result = get_tenant_repair_price(self.tenant, 2)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_tenant_price_tier3(self):
        result = get_tenant_repair_price(self.tenant, 3)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_tenant_price_tier4(self):
        result = get_tenant_repair_price(self.tenant, 4)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_tenant_price_tier5plus(self):
        result = get_tenant_repair_price(self.tenant, 5)
        self.assertEqual(result, Decimal('0.00'))

    def test_zero_tenant_price_tier5plus_high_count(self):
        result = get_tenant_repair_price(self.tenant, 20)
        self.assertEqual(result, Decimal('0.00'))

    def test_none_tenant_uses_default(self):
        """When no tenant, default pricing should apply."""
        result = get_tenant_repair_price(None, 1)
        self.assertEqual(result, Decimal('50.00'))

    def test_normal_tenant_prices_unaffected(self):
        """Normal positive tenant prices work as before."""
        normal_tenant = _make_tenant('Normal Shop', 'normal-shop')
        normal_tenant.repair_price_1 = Decimal('55.00')
        normal_tenant.save()
        result = get_tenant_repair_price(normal_tenant, 1)
        self.assertEqual(result, Decimal('55.00'))
