"""What this shop has done to a fleet unit's CURRENT windshield.

The progressive ladder counts repairs per unit (UnitRepairCount) and starts
over when the windshield is replaced. Two surfaces show where the count
stands, and they must agree, so both read it from here:

- the job form, under the unit box (``views.api.get_windshield_history`` ->
  static/js/windshield_history.js), where "New windshield" starts the unit
  over when the earlier repairs aren't on the glass;
- the unit page (``views.customers.unit_details``), above the full history.

"The repairs on this glass" are the ``count`` most recent completed repairs
on the unit — the count is the authority, because a reset by tap leaves no
row behind to date it from.
"""

from apps.technician_portal.models import Repair, UnitRepairCount


def progressive_applies(tenant, customer):
    """Whether the count moves the price for this customer at all.

    Same rule as Repair.save(): an individual always pays the first-repair
    price, and either the shop or the customer can turn the ladder off.
    """
    if customer is None or customer.is_individual:
        return False
    return bool(getattr(tenant, 'use_progressive_pricing', True)
                and getattr(customer, 'use_progressive_pricing', True))


def current_windshield(tenant, customer, unit_number):
    """Count, last visit, marked spots and next price for a fleet unit.

    Returns None when the unit has no repairs on its current glass. Prices
    are None when progressive pricing does not apply to this customer — the
    count is still true, it just doesn't change what anyone pays.
    """
    from apps.technician_portal.services.pricing_service import calculate_repair_cost

    unit = (unit_number or '').strip()
    if tenant is None or customer is None or not unit:
        return None
    # A fleet job's counter key is its unit number (UnitRepairCount.key_for).
    row = UnitRepairCount.objects.filter(
        tenant=tenant, customer=customer,
        unit_number=unit[:UnitRepairCount.KEY_MAX_LENGTH],
    ).first()
    count = row.repair_count if row else 0
    if count < 1:
        return None

    repairs = list(
        Repair.objects.filter(
            tenant=tenant, customer=customer, unit_number=unit,
            queue_status='COMPLETED',
        ).order_by('-service_date', '-pk')[:count]
    )
    spots = [
        {'x': max(0.0, min(100.0, r.damage_location_x)),
         'y': max(0.0, min(100.0, r.damage_location_y))}
        for r in repairs
        if r.damage_location_x is not None and r.damage_location_y is not None
    ]
    priced = progressive_applies(tenant, customer)
    return {
        'repair_count': count,
        'next_number': count + 1,
        'next_price': calculate_repair_cost(customer, count + 1) if priced else None,
        'first_price': calculate_repair_cost(customer, 1) if priced else None,
        'last_repaired': repairs[0].service_date if repairs else None,
        'spots': spots,
    }
