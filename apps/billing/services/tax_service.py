"""
Tax Service — Sales tax calculation for RS Systems invoices.

Tenant-aware: each shop manages their own tax rates via the TaxRate model.
Falls back to BillingConfig for backward compatibility with the original
single-tenant setup, but new tenants default to tax_enabled=False.

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
    Tax calculation service.

    Tenant-aware: pass tenant to constructor or calculate_tax().
    Uses the tenant's TaxRate entries for rate lookup.
    Falls back to BillingConfig singleton for legacy support.

    Usage:
        tax_svc = TaxService(tenant=request.tenant)
        result = tax_svc.calculate_tax(subtotal=Decimal('150.00'))
        # result = {'rate': 9.5, 'amount': 14.25, 'state_rate': 6.5, ...}
    """

    def __init__(self, tenant=None):
        self.tenant = tenant

    def _get_billing_config(self):
        """Get the BillingConfig singleton with caching (legacy fallback)."""
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

    def _get_tenant_default_tax_rate(self, tenant):
        """
        Get the default (most recently created active) TaxRate for this tenant.
        Returns None if tenant has no tax rates configured.
        """
        from apps.billing.models import TaxRate
        return (
            TaxRate.objects
            .filter(tenant=tenant, is_active=True)
            .order_by('-effective_date', '-id')
            .first()
        )

    def is_tax_enabled(self, tenant=None):
        """
        Check whether tax calculation is enabled for the given tenant.

        Tenant-aware: if a tenant has NO TaxRate entries, tax is disabled
        for that tenant regardless of the global BillingConfig setting.
        """
        tenant = tenant or self.tenant
        if tenant:
            from apps.billing.models import TaxRate
            return TaxRate.objects.filter(tenant=tenant, is_active=True).exists()

        # Legacy fallback: global BillingConfig
        config = self._get_billing_config()
        if config is None:
            return False
        return config.tax_enabled

    def calculate_tax(self, subtotal, customer=None, tenant=None, **kwargs):
        """
        Calculate tax for an amount.

        Tenant-aware: uses tenant's TaxRate entries.
        If no tenant or no rates configured, returns zero tax.

        Returns dict:
            {
                'rate': Decimal,          # Combined tax rate percentage
                'state_rate': Decimal,    # State portion
                'county_rate': Decimal,   # County portion
                'city_rate': Decimal,     # City portion
                'special_rate': Decimal,  # Special district portion
                'amount': Decimal,        # Tax amount in dollars
                'exempt': bool,           # Whether customer is tax exempt
                'enabled': bool,          # Whether tax is enabled
            }
        """
        tenant = tenant or self.tenant

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

        # Check customer exemption early
        if customer is not None and getattr(customer, 'tax_exempt', False):
            result['exempt'] = True
            return result

        # Tenant-aware path: use tenant's TaxRate
        if tenant:
            tax_rate = self._get_tenant_default_tax_rate(tenant)
            if tax_rate is None:
                # No tax rates configured for this tenant = tax disabled
                return result
            result['enabled'] = True
            result['rate'] = tax_rate.total_rate
            result['state_rate'] = tax_rate.state_rate
            result['county_rate'] = tax_rate.county_rate
            result['city_rate'] = tax_rate.city_rate
            result['special_rate'] = tax_rate.special_rate
        else:
            # Legacy fallback: global BillingConfig
            config = self._get_billing_config()
            if config is None or not config.tax_enabled:
                return result
            result['enabled'] = True
            result['rate'] = config.default_tax_rate or Decimal('0.000')
            result['state_rate'] = getattr(config, 'state_tax_rate', Decimal('0.000')) or Decimal('0.000')
            result['county_rate'] = getattr(config, 'county_tax_rate', Decimal('0.000')) or Decimal('0.000')
            result['city_rate'] = getattr(config, 'city_tax_rate', Decimal('0.000')) or Decimal('0.000')
            result['special_rate'] = getattr(config, 'special_tax_rate', Decimal('0.000')) or Decimal('0.000')

        rate = result['rate']
        if rate > 0 and subtotal > 0:
            tax_amount = (subtotal * rate / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            result['amount'] = tax_amount

        return result

    def apply_tax_to_invoice(self, invoice):
        """
        Calculate and apply tax to an existing invoice.
        Uses the invoice's tenant for rate lookup.
        Updates tax fields on invoice. Does NOT call invoice.save().
        """
        customer = invoice.customer
        taxable = invoice.subtotal - invoice.discount
        tenant = getattr(invoice, 'tenant', None) or self.tenant

        tax_result = self.calculate_tax(subtotal=taxable, customer=customer, tenant=tenant)

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
