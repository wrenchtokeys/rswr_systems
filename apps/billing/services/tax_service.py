"""
Tax Service — Sales tax calculation for RS Systems invoices.

Tax is calculated at invoice creation time and stored on the invoice.
The same total applies whether they pay via Stripe, check, or cash.

Shop owners add tax rates for the areas they serve (no pre-loaded data).
Total rate auto-calculates from state + county + city + special on save.

Lookup priority:
1. City + State (case-insensitive, tenant-scoped)
2. ZIP code (tenant-scoped)
3. BillingConfig.default_tax_rate fallback
4. Zero

Author: Amelia (Clawdbot AI)
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cache keys
_BILLING_CONFIG_CACHE_KEY = 'billing_config_tax'
_BILLING_CONFIG_CACHE_TTL = 300  # 5 minutes


class TaxService:
    """
    Tax calculation service. Looks up rate by city+state, applies to invoice.

    Usage:
        tax_svc = TaxService()
        rate = tax_svc.get_tax_rate(city='Little Rock', state='AR')
        tax_amount = tax_svc.calculate_tax(subtotal=Decimal('150.00'), city='Little Rock', state='AR')
    """

    def _get_billing_config(self):
        """
        Get the BillingConfig singleton with caching.
        Returns the instance or None.
        """
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

    def get_tax_rate(self, city=None, state='AR', zip_code=None, tenant=None):
        """
        Look up the tax rate. Returns Decimal percentage or 0 if not found.

        Lookup order:
        1. City + State — tenant-specific, then global (tenant=None)
        2. ZIP code — tenant-specific, then global
        3. BillingConfig.default_tax_rate
        4. Decimal('0.000')
        """
        from apps.billing.models import TaxRate

        active_qs = TaxRate.objects.filter(is_active=True)

        # Build list of querysets: tenant-specific first, then global fallback
        querysets = []
        if tenant:
            querysets.append(active_qs.filter(tenant=tenant))
        querysets.append(active_qs.filter(tenant__isnull=True))

        # Try city + state first (most accurate)
        if city and state:
            city_clean = city.strip()
            state_clean = state.strip()
            for qs in querysets:
                try:
                    rate = qs.filter(
                        city__iexact=city_clean,
                        state__iexact=state_clean,
                    ).values_list('total_rate', flat=True).first()
                    if rate is not None:
                        return rate
                except Exception as e:
                    logger.warning(f"Tax rate lookup by city failed: {e}")

        # Fall back to zip code
        if zip_code:
            zip_clean = zip_code.strip()
            for qs in querysets:
                try:
                    rate = qs.filter(
                        zip_code=zip_clean,
                    ).values_list('total_rate', flat=True).first()
                    if rate is not None:
                        return rate
                except Exception as e:
                    logger.warning(f"Tax rate lookup by zip failed: {e}")

        return Decimal('0.000')

    def calculate_tax(self, subtotal, city=None, state=None, zip_code=None, customer=None, tenant=None):
        """
        Calculate tax for an amount.

        Tax rate is determined by the SHOP's location (BillingConfig company
        address), not the customer's address. This is correct for mobile
        service businesses where the shop's jurisdiction applies.

        Lookup priority for location:
        1. Explicit city/state/zip passed by caller
        2. BillingConfig company_city / company_state / company_zip
        3. Fallback to default_tax_rate

        Returns dict:
            {
                'rate': Decimal,      # Tax rate percentage
                'amount': Decimal,    # Tax amount in dollars
                'exempt': bool,       # Whether customer is tax exempt
                'enabled': bool,      # Whether tax is enabled globally
                'city': str,          # City used for lookup
                'state': str,         # State used for lookup
            }

        If customer is tax_exempt, returns amount=0.
        If BillingConfig.tax_enabled is False, returns amount=0.
        """
        result = {
            'rate': Decimal('0.000'),
            'amount': Decimal('0.00'),
            'exempt': False,
            'enabled': False,
            'city': city or '',
            'state': state or '',
        }

        # Check if tax is enabled globally
        if not self.is_tax_enabled():
            return result
        result['enabled'] = True

        # Check customer exemption
        if customer is not None:
            if getattr(customer, 'tax_exempt', False):
                result['exempt'] = True
                return result

        # Get billing config for shop location and default rate
        config = self._get_billing_config()

        # Use shop location from BillingConfig if not explicitly provided
        if not city or not state:
            if config:
                if not city and config.company_city:
                    city = config.company_city
                if not state and config.company_state:
                    state = config.company_state
                if not zip_code and config.company_zip:
                    zip_code = config.company_zip
            result['city'] = city or ''
            result['state'] = state or ''

        # If a default tax rate is set, use it directly — simplest setup.
        # City-specific TaxRate entries override this if they exist.
        if config and config.default_tax_rate > 0:
            rate = config.default_tax_rate
        else:
            rate = Decimal('0.000')

        # Derive tenant from customer if not provided
        if tenant is None and customer is not None:
            tenant = getattr(customer, 'tenant', None)

        # Try city-specific rate (overrides default if found)
        city_rate = self.get_tax_rate(city=city, state=state, zip_code=zip_code, tenant=tenant)
        if city_rate > 0:
            rate = city_rate
        result['rate'] = rate

        if rate > 0 and subtotal > 0:
            # Calculate: tax_amount = round(subtotal * rate / 100, 2)
            tax_amount = (subtotal * rate / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            result['amount'] = tax_amount

        return result

    def apply_tax_to_invoice(self, invoice):
        """
        Calculate and apply tax to an existing invoice.
        Uses customer's city/state for rate lookup.
        Updates invoice.tax_rate, invoice.tax_amount, invoice.total.

        This method does NOT call invoice.save() — the caller is responsible
        for saving (so it can be part of a larger transaction).
        """
        customer = invoice.customer

        # Calculate taxable amount = subtotal - discount
        taxable = invoice.subtotal - invoice.discount

        # Calculate tax
        tenant = getattr(invoice, 'tenant', None) or getattr(customer, 'tenant', None)
        tax_result = self.calculate_tax(
            subtotal=taxable,
            customer=customer,
            tenant=tenant,
        )

        # Apply to invoice
        invoice.tax_rate = tax_result['rate']
        invoice.tax_amount = tax_result['amount']
        invoice.total = taxable + tax_result['amount']

        logger.debug(
            f"Tax applied to invoice {getattr(invoice, 'invoice_number', '?')}: "
            f"taxable=${taxable}, rate={tax_result['rate']}%, "
            f"tax=${tax_result['amount']}, total=${invoice.total}"
        )

        return tax_result
