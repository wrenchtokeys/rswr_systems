"""
Tax Service — Sales tax calculation for RS Systems invoices.

Dead simple: shop owner sets their tax rate in Settings → Billing & Tax.
That rate gets applied to every invoice (unless customer is tax-exempt).

No tax table lookups, no city matching, no complexity.
Rate is broken down into state/county/city/special for the invoice.

Author: Amelia (Clawdbot AI)
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.core.cache import cache

logger = logging.getLogger(__name__)

_BILLING_CONFIG_CACHE_KEY = 'billing_config_tax'
_BILLING_CONFIG_CACHE_TTL = 300  # 5 minutes


class TaxService:
    """
    Tax calculation service. Reads rate from BillingConfig, applies to invoices.

    Usage:
        tax_svc = TaxService()
        result = tax_svc.calculate_tax(subtotal=Decimal('150.00'))
        # result = {'rate': 9.5, 'amount': 14.25, 'state_rate': 6.5, ...}
    """

    def _get_billing_config(self):
        """Get the BillingConfig singleton with caching."""
        config = cache.get(_BILLING_CONFIG_CACHE_KEY)
        if config is not None:
            return config

        try:
            from apps.billing.models import BillingConfig
            config = BillingConfig.get_instance()
            cache.set(_BILLING_CONFIG_CACHE_KEY, config, _BILLING_CONFIG_CACHE_TTL)
            return config
        except Exception as e:
            logger.warning(f"Could not load BillingConfig: {e}")
            return None

    def is_tax_enabled(self):
        """Check whether tax calculation is enabled globally."""
        config = self._get_billing_config()
        if config is None:
            return False
        return config.tax_enabled

    def calculate_tax(self, subtotal, customer=None, **kwargs):
        """
        Calculate tax for an amount.

        Returns dict:
            {
                'rate': Decimal,          # Combined tax rate percentage
                'state_rate': Decimal,    # State portion
                'county_rate': Decimal,   # County portion
                'city_rate': Decimal,     # City portion
                'special_rate': Decimal,  # Special district portion
                'amount': Decimal,        # Tax amount in dollars
                'exempt': bool,           # Whether customer is tax exempt
                'enabled': bool,          # Whether tax is enabled globally
            }
        """
        result = {
            'rate': Decimal('0.000'),
            'state_rate': Decimal('0.000'),
            'county_rate': Decimal('0.000'),
            'city_rate': Decimal('0.000'),
            'special_rate': Decimal('0.000'),
            'amount': Decimal('0.00'),
            'exempt': False,
            'enabled': False,
        }

        # Check if tax is enabled
        config = self._get_billing_config()
        if config is None or not config.tax_enabled:
            return result
        result['enabled'] = True

        # Check customer exemption
        if customer is not None:
            if getattr(customer, 'tax_exempt', False):
                result['exempt'] = True
                return result

        # Read rates directly from BillingConfig
        rate = config.default_tax_rate or Decimal('0.000')
        result['rate'] = rate
        result['state_rate'] = getattr(config, 'state_tax_rate', Decimal('0.000')) or Decimal('0.000')
        result['county_rate'] = getattr(config, 'county_tax_rate', Decimal('0.000')) or Decimal('0.000')
        result['city_rate'] = getattr(config, 'city_tax_rate', Decimal('0.000')) or Decimal('0.000')
        result['special_rate'] = getattr(config, 'special_tax_rate', Decimal('0.000')) or Decimal('0.000')

        if rate > 0 and subtotal > 0:
            tax_amount = (subtotal * rate / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            result['amount'] = tax_amount

        return result

    def apply_tax_to_invoice(self, invoice):
        """
        Calculate and apply tax to an existing invoice.
        Updates tax fields on invoice. Does NOT call invoice.save().
        """
        customer = invoice.customer
        taxable = invoice.subtotal - invoice.discount

        tax_result = self.calculate_tax(subtotal=taxable, customer=customer)

        # Apply to invoice (total + component breakdown)
        invoice.tax_rate = tax_result['rate']
        invoice.state_tax_rate = tax_result['state_rate']
        invoice.county_tax_rate = tax_result['county_rate']
        invoice.city_tax_rate = tax_result['city_rate']
        invoice.special_tax_rate = tax_result['special_rate']
        invoice.tax_amount = tax_result['amount']
        invoice.total = taxable + tax_result['amount']

        logger.debug(
            f"Tax applied to invoice {getattr(invoice, 'invoice_number', '?')}: "
            f"taxable=${taxable}, rate={tax_result['rate']}%, "
            f"tax=${tax_result['amount']}, total=${invoice.total}"
        )

        return tax_result
