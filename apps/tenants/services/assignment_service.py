"""
Auto-Assignment Service

Assigns technicians to repairs/replacements based on the tenant's
configured assignment strategy.

Strategies:
  - manual:        No auto-assignment; manager assigns all work.
  - primary_first: Assign to the customer's primary technician if eligible.
  - auto:          Primary tech first, then lowest-workload eligible tech.
  - round_robin:   Rotate evenly through eligible technicians.

Author: Amelia (Clawdbot AI)
"""

import logging

from django.db.models import Count, Q

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_assign_repair(repair):
    """
    Auto-assign a technician to a repair based on the tenant's strategy.

    Args:
        repair: Repair instance (must have customer and tenant set).

    Returns:
        Technician instance if assigned, None if manual / no eligible tech.
    """
    tenant = repair.tenant
    if not tenant:
        return None

    strategy = tenant.assignment_strategy

    if strategy == 'manual':
        return None
    if strategy == 'primary_first':
        return _assign_primary_first(repair, tenant)
    if strategy == 'auto':
        return _assign_smart(repair, tenant)
    if strategy == 'round_robin':
        return _assign_round_robin(repair, tenant)

    return None


def auto_assign_replacement(replacement):
    """
    Auto-assign a technician to a replacement based on the tenant's strategy.
    Filters for technicians with ``can_replace=True``.
    """
    tenant = replacement.tenant
    if not tenant:
        return None

    strategy = tenant.assignment_strategy

    if strategy == 'manual':
        return None
    if strategy == 'primary_first':
        return _assign_primary_first(replacement, tenant, service_type='replacement')
    if strategy == 'auto':
        return _assign_smart(replacement, tenant, service_type='replacement')
    if strategy == 'round_robin':
        return _assign_round_robin(replacement, tenant, service_type='replacement')

    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_eligible_techs(tenant, service_type='repair'):
    """Return a queryset of active technicians eligible for *service_type*."""
    from apps.technician_portal.models import Technician

    qs = Technician.objects.filter(tenant=tenant, is_active=True)
    if service_type == 'replacement':
        qs = qs.filter(can_replace=True)
    else:
        qs = qs.filter(can_repair=True)
    return qs


def _assign_primary_first(service, tenant, service_type='repair'):
    """Assign to the customer's primary tech if one exists and is eligible."""
    customer = service.customer
    if not customer or not customer.primary_technician:
        return None

    tech = customer.primary_technician

    # Eligibility checks
    if not tech.is_active:
        return None
    if tech.tenant_id != tenant.id:
        return None
    if service_type == 'replacement' and not tech.can_replace:
        return None
    if service_type == 'repair' and not tech.can_repair:
        return None

    service.technician = tech
    # The Repair/Replacement post_save assignment signal notifies the tech
    # (dashboard row + bell + email) — no hand-rolled notification here.
    service.save(update_fields=['technician'])
    logger.info(
        "Auto-assigned %s #%s to primary tech %s for customer %s",
        service_type, service.id, tech, customer,
    )
    return tech


def _assign_smart(service, tenant, service_type='repair'):
    """Primary tech first → then lowest-workload eligible tech."""
    result = _assign_primary_first(service, tenant, service_type)
    if result:
        return result

    eligible = _get_eligible_techs(tenant, service_type)
    if not eligible.exists():
        return None

    active_statuses = ['PENDING', 'APPROVED', 'IN_PROGRESS', 'REQUESTED']
    # The reverse relation from Technician → Repair/Replacement uses Django's
    # default lowercase model name ('repair', 'replacement'), NOT 'repairs'/'replacements'.
    # Using 'repairs' raises FieldError at runtime; fixed to 'repair'/'replacement'. (CODE-163)
    count_field = 'replacement' if service_type == 'replacement' else 'repair'
    tech_with_load = eligible.annotate(
        active_repairs=Count(
            count_field,
            filter=Q(**{f'{count_field}__queue_status__in': active_statuses}),
        )
    ).order_by('active_repairs', 'id')

    tech = tech_with_load.first()
    if tech:
        service.technician = tech
        service.save(update_fields=['technician'])
        logger.info(
            "Smart-assigned %s #%s to %s (lowest workload)",
            service_type, service.id, tech,
        )
        return tech

    return None


def _assign_round_robin(service, tenant, service_type='repair'):
    """Rotate through eligible technicians by ID order.

    The "last assigned" anchor must come from the same service type being
    assigned.  Using Repair history when assigning a Replacement (and vice
    versa) breaks the rotation for tenants that only do one service type —
    ``last_service`` is always None and the same technician always receives
    the first slot.  It also cross-contaminates rotation state between the
    two service types for tenants that do both.  (CODE-172)
    """
    from apps.technician_portal.models import Repair, Replacement

    eligible = _get_eligible_techs(tenant, service_type)
    if not eligible.exists():
        return None

    # Find the most recently assigned tech for the same service type.
    # Both Repair and Replacement inherit service_date from GlassService (no
    # created_at on either model).  Order by ('-service_date', '-id') so ties
    # are broken deterministically.
    if service_type == 'replacement':
        last_service = Replacement.objects.filter(
            tenant=tenant,
            technician__isnull=False,
        ).order_by('-service_date', '-id').first()
    else:
        last_service = Repair.objects.filter(
            tenant=tenant,
            technician__isnull=False,
        ).order_by('-service_date', '-id').first()

    eligible_list = list(eligible.order_by('id'))

    if last_service and last_service.technician in eligible_list:
        last_idx = eligible_list.index(last_service.technician)
        next_idx = (last_idx + 1) % len(eligible_list)
        tech = eligible_list[next_idx]
    else:
        tech = eligible_list[0]

    service.technician = tech
    service.save(update_fields=['technician'])
    logger.info(
        "Round-robin assigned %s #%s to %s",
        service_type, service.id, tech,
    )
    return tech
