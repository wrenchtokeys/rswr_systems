"""
Batch Pricing Service for Multi-Break Repairs

Handles progressive pricing calculation for multiple breaks on the same unit
during a single repair session. Uses existing pricing_service.py functions
to ensure consistency with custom pricing tiers and volume discounts.
"""
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from apps.customer_portal.pricing_models import CustomerPricing
from apps.technician_portal.models import UnitRepairCount, Customer
from .pricing_service import calculate_repair_cost


def calculate_batch_pricing(
    customer: Customer,
    unit_number: str,
    breaks_count: int
) -> List[Dict]:
    """
    Calculate pricing for a batch of breaks on the same unit.

    Batches follow the same flat/progressive rules as single repairs
    (see get_expected_repair_cost): progressive tiers apply only when both
    the tenant and the customer have progressive pricing enabled and the
    customer isn't retail/walk-in. Otherwise every break is priced flat
    at the first-repair price.

    With progressive pricing, each break increments the repair count, so:
    - Break 1 priced as repair #N+1
    - Break 2 priced as repair #N+2
    - Break 3 priced as repair #N+3

    Args:
        customer: Customer object
        unit_number: Unit identifier
        breaks_count: Number of breaks in this batch

    Returns:
        List of dicts with pricing info for each break:
        [
            {
                'break_number': 1,
                'repair_tier': 3,  # This will be the unit's 3rd repair
                'price': Decimal('35.00'),
                'price_formatted': '$35.00'
            },
            ...
        ]
    """
    # Get tenant for pricing tiers
    tenant = getattr(customer, 'tenant', None) if customer else None
    
    # Get current repair count for this unit.
    # Include tenant= so the lookup matches the unique constraint
    # (tenant, customer, unit_number) and avoids hitting stale NULL-tenant
    # rows or raising MultipleObjectsReturned.  (CODE-257)
    try:
        lookup = {'customer': customer, 'unit_number': unit_number}
        if tenant is not None:
            lookup['tenant'] = tenant
        unit_count = UnitRepairCount.objects.get(**lookup)
        base_repair_count = unit_count.repair_count
    except UnitRepairCount.DoesNotExist:
        base_repair_count = 0

    # Same flat/progressive decision as get_expected_repair_cost
    tenant_allows_progressive = getattr(tenant, 'use_progressive_pricing', True) if tenant else True
    customer_wants_progressive = getattr(customer, 'use_progressive_pricing', True) if customer else True
    is_retail = bool(customer) and customer.customer_type in ('RETAIL', 'WALK_IN')
    use_progressive = tenant_allows_progressive and customer_wants_progressive and not is_retail

    # Calculate price for each break in sequence
    pricing_breakdown = []

    for i in range(breaks_count):
        # Each break increments the repair count (repair_tier stays the true
        # sequence number for UnitRepairCount bookkeeping even in flat mode)
        repair_tier = base_repair_count + i + 1

        # Use existing pricing service (handles custom pricing, tenant pricing, defaults)
        price = calculate_repair_cost(customer, repair_tier if use_progressive else 1, tenant)

        pricing_breakdown.append({
            'break_number': i + 1,
            'repair_tier': repair_tier,
            'price': price,
            'price_formatted': f'${price:.2f}'
        })

    return pricing_breakdown


def calculate_batch_total(pricing_breakdown: List[Dict]) -> Dict:
    """
    Calculate total cost and summary for a batch of repairs.

    Args:
        pricing_breakdown: Output from calculate_batch_pricing()

    Returns:
        Dict with batch summary:
        {
            'total_breaks': 3,
            'total_cost': Decimal('110.00'),
            'total_cost_formatted': '$110.00',
            'price_range': '$50.00 - $35.00',
            'breakdown': [...original pricing breakdown...]
        }
    """
    if not pricing_breakdown:
        return {
            'total_breaks': 0,
            'total_cost': Decimal('0.00'),
            'total_cost_formatted': '$0.00',
            'price_range': '$0.00',
            'breakdown': []
        }

    total_cost = sum(item['price'] for item in pricing_breakdown)

    # Get price range (highest to lowest)
    prices = [item['price'] for item in pricing_breakdown]
    max_price = max(prices)
    min_price = min(prices)

    if max_price == min_price:
        price_range = f'${max_price:.2f} each'
    else:
        price_range = f'${max_price:.2f} - ${min_price:.2f}'

    return {
        'total_breaks': len(pricing_breakdown),
        'total_cost': total_cost,
        'total_cost_formatted': f'${total_cost:.2f}',
        'price_range': price_range,
        'breakdown': pricing_breakdown
    }


def get_batch_pricing_preview(
    customer_id: int,
    unit_number: str,
    breaks_count: int,
    tenant=None,
) -> Optional[Dict]:
    """
    Get pricing preview for frontend display before batch submission.

    Args:
        customer_id: Customer ID
        unit_number: Unit identifier
        breaks_count: Number of breaks in batch

    Returns:
        Dict with pricing info or None if customer not found:
        {
            'customer_name': 'Acme Corp',
            'unit_number': '1001',
            'uses_custom_pricing': True,
            'total_breaks': 3,
            'total_cost': Decimal('110.00'),
            'total_cost_formatted': '$110.00',
            'price_range': '$50.00 - $35.00',
            'breakdown': [
                {
                    'break_number': 1,
                    'repair_tier': 3,
                    'price': Decimal('35.00'),
                    'price_formatted': '$35.00'
                },
                ...
            ]
        }
    """
    try:
        lookup = {'id': customer_id}
        if tenant is not None:
            lookup['tenant'] = tenant
        customer = Customer.objects.get(**lookup)
    except Customer.DoesNotExist:
        return None

    # Check if customer uses custom pricing
    uses_custom_pricing = CustomerPricing.objects.filter(
        customer=customer,
        use_custom_pricing=True
    ).exists()

    # Get pricing breakdown
    pricing_breakdown = calculate_batch_pricing(customer, unit_number, breaks_count)
    batch_total = calculate_batch_total(pricing_breakdown)

    return {
        'customer_name': customer.name,
        'unit_number': unit_number,
        'uses_custom_pricing': uses_custom_pricing,
        **batch_total
    }


def validate_batch_pricing_authorization(
    technician,
    total_cost: Decimal,
    proposed_override: Optional[Decimal] = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if technician is authorized to override batch pricing.

    Args:
        technician: Technician object
        total_cost: Calculated total batch cost
        proposed_override: Optional proposed override amount

    Returns:
        Tuple of (is_authorized, error_message)
    """
    if proposed_override is None:
        return True, None

    # Owners and managers may set custom prices. (can_override_pricing is
    # deprecated: no signup/team path ever set it, so requiring it locked
    # every real shop owner out of the price field.)
    if not technician.is_manager:
        return False, "Only owners and managers can set custom batch pricing"

    # Validate override amount is reasonable (not negative, not absurdly high)
    if proposed_override < 0:
        return False, "Override price cannot be negative"

    if proposed_override > total_cost * 2:
        return False, f"Override price ${proposed_override:.2f} is more than 2x calculated price ${total_cost:.2f}"

    return True, None
