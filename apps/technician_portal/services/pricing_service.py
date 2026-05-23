"""
Pricing service for calculating repair costs based on customer pricing configurations.

This service centralizes pricing logic and supports:
- Customer-specific pricing tiers
- Volume discounts
- Fallback to default pricing
- Manager override capabilities
"""

from decimal import Decimal
from typing import Optional, Tuple
from core.models import Customer
from apps.customer_portal.pricing_models import CustomerPricing
from apps.technician_portal.models import UnitRepairCount


# Default pricing tiers (used when tenant has no custom pricing)
DEFAULT_PRICING = {
    1: Decimal('50.00'),
    2: Decimal('40.00'),
    3: Decimal('35.00'),
    4: Decimal('30.00'),
}
DEFAULT_PRICE_5_PLUS = Decimal('25.00')


def get_tenant_repair_price(tenant, repair_count: int) -> Decimal:
    """
    Get the repair price for a given repair count tier from tenant settings.

    Args:
        tenant: The Tenant object (or None for system defaults)
        repair_count: The repair number for this unit (1, 2, 3, 4, 5+)

    Returns:
        Decimal: The repair cost based on tenant configuration

    Note: Tenant repair_price fields are non-nullable DecimalFields with a
    positive default, so they are never None.  However we must NOT use a bare
    truthiness check (``tenant.repair_price_1 or DEFAULT_PRICING[1]``) because
    ``Decimal('0.00')`` is falsy — a tenant that deliberately sets a $0 price
    tier (e.g. for free-service or warranty accounts) would silently receive
    the $50 system default instead.  Checking ``is not None`` is the correct
    pattern (documented in AGENTS.md: "Decimal('0.00') is falsy in Python").
    """
    if tenant:
        if repair_count == 1:
            val = tenant.repair_price_1
            return val if val is not None else DEFAULT_PRICING[1]
        elif repair_count == 2:
            val = tenant.repair_price_2
            return val if val is not None else DEFAULT_PRICING[2]
        elif repair_count == 3:
            val = tenant.repair_price_3
            return val if val is not None else DEFAULT_PRICING[3]
        elif repair_count == 4:
            val = tenant.repair_price_4
            return val if val is not None else DEFAULT_PRICING[4]
        else:
            val = tenant.repair_price_5_plus
            return val if val is not None else DEFAULT_PRICE_5_PLUS

    return DEFAULT_PRICING.get(repair_count, DEFAULT_PRICE_5_PLUS)


def get_default_repair_price(repair_count: int) -> Decimal:
    """
    Get the default repair price for a given repair count tier.

    Progressive pricing: 1st=$50, 2nd=$40, 3rd=$35, 4th=$30, 5+=$25.

    Args:
        repair_count: The repair number for this unit (1, 2, 3, 4, 5+)

    Returns:
        Decimal: The default repair cost
    """
    return DEFAULT_PRICING.get(repair_count, DEFAULT_PRICE_5_PLUS)


def calculate_repair_cost(customer: Customer, repair_count: int, tenant=None) -> Decimal:
    """
    Calculate the cost for a repair based on customer pricing configuration.

    Checks for customer-specific pricing first, then tenant pricing, then defaults.

    Args:
        customer: The Customer object
        repair_count: The number of repairs for this unit (1, 2, 3, 4, 5+)
        tenant: Optional Tenant object for shop-specific pricing

    Returns:
        Decimal: The calculated repair cost
    """
    # First check customer-specific pricing
    try:
        pricing = CustomerPricing.objects.get(customer=customer, use_custom_pricing=True)
        custom_price = pricing.get_repair_price(repair_count)

        if custom_price is not None:
            return Decimal(str(custom_price))

    except CustomerPricing.DoesNotExist:
        pass

    # Fall back to tenant pricing, then system defaults
    if tenant is None and customer:
        tenant = getattr(customer, 'tenant', None)
    
    return get_tenant_repair_price(tenant, repair_count)


def calculate_repair_cost_with_volume_discount(customer: Customer, repair_count: int, total_customer_repairs: int) -> Tuple[Decimal, bool, Decimal]:
    """
    Calculate repair cost with volume discount consideration.

    Args:
        customer: The Customer object
        repair_count: The number of repairs for this unit
        total_customer_repairs: Total repairs completed for this customer

    Returns:
        Tuple of (final_price, discount_applied, discount_amount)
    """
    base_price = calculate_repair_cost(customer, repair_count)

    try:
        pricing = CustomerPricing.objects.get(customer=customer, use_custom_pricing=True)

        if pricing.has_volume_discount(total_customer_repairs):
            discounted_price = pricing.apply_volume_discount(base_price, total_customer_repairs)
            discount_amount = base_price - discounted_price
            return discounted_price, True, discount_amount

    except CustomerPricing.DoesNotExist:
        pass

    return base_price, False, Decimal('0.00')


def get_retail_repair_price(customer: Customer) -> Decimal:
    """
    Get the default repair price for retail/walk-in customers.
    
    Retail customers always pay the first repair price (no sequential discounts).
    This can be overridden with customer-specific pricing if configured.
    
    Args:
        customer: The Customer object
        
    Returns:
        Decimal: The retail repair price
    """
    # Always use first repair price for retail (no sequential discounts)
    return calculate_repair_cost(customer, 1)


def get_expected_repair_cost(customer: Customer, unit_number: str, tenant=None) -> Tuple[Decimal, int]:
    """
    Get the expected cost for the next repair on a specific unit.

    Args:
        customer: The Customer object
        unit_number: The unit number
        tenant: Optional Tenant object (defaults to customer.tenant)

    Returns:
        Tuple of (expected_cost, next_repair_count)
    """
    # Get tenant if not provided
    if tenant is None and customer:
        tenant = getattr(customer, 'tenant', None)
    
    # Check if progressive pricing is enabled
    tenant_allows_progressive = getattr(tenant, 'use_progressive_pricing', True) if tenant else True
    customer_wants_progressive = getattr(customer, 'use_progressive_pricing', True) if customer else True
    use_progressive = tenant_allows_progressive and customer_wants_progressive
    
    # Retail/Walk-in customers always pay first repair price (no sequential discounts)
    is_retail = customer and customer.customer_type in ('RETAIL', 'WALK_IN')
    
    # If progressive pricing disabled OR retail customer, always first repair price
    if is_retail or not use_progressive:
        return calculate_repair_cost(customer, 1, tenant), 1
    
    # Fleet customers with progressive pricing enabled
    # Include tenant in lookup so the created row is tenant-scoped (missing tenant
    # caused NULL-tenant rows to be created, breaking TenantManager scoping).
    unit_repair_count, created = UnitRepairCount.objects.get_or_create(
        tenant=tenant,
        customer=customer,
        unit_number=unit_number,
        defaults={'repair_count': 0}
    )

    next_repair_count = unit_repair_count.repair_count + 1
    expected_cost = calculate_repair_cost(customer, next_repair_count, tenant)

    return expected_cost, next_repair_count


def can_manager_override_price(technician, proposed_amount: Decimal) -> bool:
    """
    Check if a technician can override pricing for a given amount.

    Args:
        technician: Technician object
        proposed_amount: The proposed override amount

    Returns:
        bool: True if technician can override this amount
    """
    if not hasattr(technician, 'can_override_pricing') or not technician.can_override_pricing:
        return False

    if not technician.is_manager:
        return False

    # If technician has approval limit, check against it.
    # Use `is not None` — approval_limit=Decimal('0.00') is a valid "zero cap"
    # that blocks all overrides, but a bare truthiness check treats 0.00 as
    # "no limit" (Decimal falsy bug documented in AGENTS.md).
    if technician.approval_limit is not None:
        return proposed_amount <= technician.approval_limit

    # approval_limit is None → unlimited (senior managers)
    return True


def apply_pricing_to_repair(repair: 'Repair') -> None:
    """
    Apply appropriate pricing to a repair object.

    This function updates the repair's cost based on:
    1. Existing cost_override (if set)
    2. Customer-specific pricing
    3. Default pricing

    Args:
        repair: The Repair object to update
    """
    # If there's already a cost override, don't change it
    if repair.cost_override:
        repair.cost = repair.cost_override
        return

    # Get the current repair count for this unit.
    # Include tenant= so the lookup matches the unique constraint
    # (tenant, customer, unit_number) — consistent with get_or_create above
    # and avoids hitting stale NULL-tenant rows.  (CODE-257)
    try:
        lookup = {'customer': repair.customer, 'unit_number': repair.unit_number}
        tenant = getattr(repair, 'tenant', None)
        if tenant is not None:
            lookup['tenant'] = tenant
        unit_repair_count = UnitRepairCount.objects.get(**lookup)
        repair_count = unit_repair_count.repair_count
    except UnitRepairCount.DoesNotExist:
        repair_count = 1  # First repair for this unit

    # Calculate and apply the cost
    repair.cost = calculate_repair_cost(repair.customer, repair_count)


def get_pricing_info(customer: Customer) -> dict:
    """
    Get comprehensive pricing information for a customer.

    Args:
        customer: The Customer object

    Returns:
        dict: Pricing information including custom rates, volume discounts, etc.
    """
    info = {
        'has_custom_pricing': False,
        'pricing_tiers': {},
        'volume_discount': {
            'enabled': False,
            'threshold': 0,
            'percentage': 0
        },
        'default_pricing': {
            1: float(get_default_repair_price(1)),
            2: float(get_default_repair_price(2)),
            3: float(get_default_repair_price(3)),
            4: float(get_default_repair_price(4)),
            5: float(get_default_repair_price(5)),
        }
    }

    try:
        pricing = CustomerPricing.objects.get(customer=customer, use_custom_pricing=True)
        info['has_custom_pricing'] = True

        # Get custom pricing tiers
        if pricing.repair_1_price:
            info['pricing_tiers'][1] = float(pricing.repair_1_price)
        if pricing.repair_2_price:
            info['pricing_tiers'][2] = float(pricing.repair_2_price)
        if pricing.repair_3_price:
            info['pricing_tiers'][3] = float(pricing.repair_3_price)
        if pricing.repair_4_price:
            info['pricing_tiers'][4] = float(pricing.repair_4_price)
        if pricing.repair_5_plus_price:
            info['pricing_tiers'][5] = float(pricing.repair_5_plus_price)

        # Volume discount info
        if pricing.volume_discount_percentage > 0:
            info['volume_discount'] = {
                'enabled': True,
                'threshold': pricing.volume_discount_threshold,
                'percentage': float(pricing.volume_discount_percentage)
            }

    except CustomerPricing.DoesNotExist:
        pass

    return info