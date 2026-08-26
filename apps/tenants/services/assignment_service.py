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
    """Return a queryset of active technicians eligible for *service_type*.

    ``user`` is joined in: every caller logs the tech (``Technician.__str__``
    reads ``user``) and the views then print ``tech.user.get_full_name()``.
    """
    from apps.technician_portal.models import Technician

    qs = Technician.objects.filter(
        tenant=tenant, is_active=True).select_related('user')
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

    active_statuses = ['PENDING', 'APPROVED', 'IN_PROGRESS', 'REQUESTED']
    # The reverse relation from Technician → Repair/Replacement uses Django's
    # default lowercase model name ('repair', 'replacement'), NOT 'repairs'/'replacements'.
    # Using 'repairs' raises FieldError at runtime; fixed to 'repair'/'replacement'. (CODE-163)
    count_field = 'replacement' if service_type == 'replacement' else 'repair'
    # The job being assigned is already in the database — callers create it
    # with a provisional technician — and REQUESTED is one of the statuses
    # counted here, so leaving it in inflates the provisional tech's workload
    # by one and pushes the job away from the very tech the count was meant to
    # favour.  Balance against everything EXCEPT this job.  (CODE-278)
    load_filter = Q(**{f'{count_field}__queue_status__in': active_statuses})
    if service.pk is not None:
        load_filter &= ~Q(**{f'{count_field}__pk': service.pk})

    tech = _get_eligible_techs(tenant, service_type).annotate(
        active_repairs=Count(count_field, filter=load_filter)
    ).order_by('active_repairs', 'id').first()

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

    The anchor must also exclude the job being assigned right now.  Callers
    create the job with a provisional technician before handing it here, and
    ``technician`` is a non-null FK, so that brand-new row IS the most recent
    one — the rotation was anchoring on itself and returning "provisional
    pick + 1" every time.  Because the provisional pick is the lowest-workload
    tech, and this rotation then moves the job off them, that tech never
    accumulates work and is picked again next time: every customer request
    landed on the same neighbour, with the rest of the shop getting none.
    (CODE-278)

    Order by ``-id``, not ``-service_date``: ``service_date`` is the date of
    service, editable from the job form (``repair_date``), so backdating or
    forward-dating a job would drag the rotation anchor with it.  ``-id`` is
    creation order, which is what "last assigned" means here.  (CODE-278)
    """
    from apps.technician_portal.models import Repair, Replacement

    eligible_list = list(
        _get_eligible_techs(tenant, service_type).order_by('id'))
    if not eligible_list:
        return None

    model = Replacement if service_type == 'replacement' else Repair
    anchor_qs = model.objects.filter(tenant=tenant, technician__isnull=False)
    if service.pk is not None:
        anchor_qs = anchor_qs.exclude(pk=service.pk)
    last_tech_id = (
        anchor_qs.order_by('-id')
        .values_list('technician_id', flat=True)
        .first()
    )

    eligible_ids = [t.id for t in eligible_list]
    if last_tech_id in eligible_ids:
        next_idx = (eligible_ids.index(last_tech_id) + 1) % len(eligible_list)
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
