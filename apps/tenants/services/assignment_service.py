"""
Auto-Assignment Service

Assigns technicians to repairs/replacements based on the tenant's
configured assignment strategy.

Strategies:
  - manual:        No auto-assignment; manager assigns all work.
  - primary_first: Assign to the customer's primary technician if eligible.
  - auto:          Primary tech first, then lowest-workload eligible tech.
  - round_robin:   Rotate evenly through eligible technicians.

Two entry points, because callers arrive at two different moments:

  * ``auto_assign_repair`` / ``auto_assign_replacement`` — the job row
    already exists (customer-portal requests create it with a provisional
    technician, since ``GlassService.technician`` is NOT NULL).  These write.
  * ``select_technician`` — decision only, no writes, for callers choosing a
    technician *before* the row exists (in-app quick job creation).

When a strategy declines to assign — Manual always, Primary Tech First with
no eligible primary tech, or a shop with nobody eligible — the job is not
silently left with whoever the caller provisionally picked.  It is flagged
``needs_assignment``, which is what the manager's Unassigned queue lists and
what suppresses the "you've been assigned" notification.  (CODE-279)

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
        Technician instance if assigned, None if the strategy declined (the
        repair is flagged ``needs_assignment``) or there is no tenant.
    """
    return _auto_assign(repair, 'repair')


def auto_assign_replacement(replacement):
    """
    Auto-assign a technician to a replacement based on the tenant's strategy.
    Filters for technicians with ``can_replace=True``.
    """
    return _auto_assign(replacement, 'replacement')


def select_technician(tenant, *, customer=None, service_type='repair',
                      exclude_pk=None):
    """The technician this tenant's strategy picks, deciding nothing else.

    No database writes and no job instance required, so a caller can consult
    the shop's strategy while building a job that does not exist yet.

    Returns None when the strategy declines to assign (Manual, or Primary
    Tech First with no eligible primary) or when no eligible technician
    exists.  A None here means "flag it for the Unassigned queue", not "any
    technician will do".

    Args:
        tenant: the Tenant whose strategy applies.
        customer: the job's customer — only Primary Tech First and Smart
            Auto-Assign consult it.
        service_type: 'repair' or 'replacement'.
        exclude_pk: pk of a job to leave out of workload counts and the
            round-robin anchor — the job being assigned, when it already
            exists.  Callers deciding before creation pass nothing.
    """
    if not tenant:
        return None

    strategy = tenant.assignment_strategy

    if strategy == 'primary_first':
        return _pick_primary(customer, tenant, service_type)
    if strategy == 'auto':
        return (_pick_primary(customer, tenant, service_type)
                or _pick_lowest_workload(tenant, service_type, exclude_pk))
    if strategy == 'round_robin':
        return _pick_round_robin(tenant, service_type, exclude_pk)

    # 'manual', and any value a future migration adds but this service does
    # not know yet: decline rather than guess.
    return None


# ---------------------------------------------------------------------------
# Internal helpers — assignment (write)
# ---------------------------------------------------------------------------

def _auto_assign(service, service_type):
    """Shared body of auto_assign_repair / auto_assign_replacement."""
    tenant = service.tenant
    if not tenant:
        return None

    tech = select_technician(
        tenant,
        customer=service.customer,
        service_type=service_type,
        exclude_pk=service.pk,
    )
    if tech is None:
        _leave_unassigned(service, service_type, tenant.assignment_strategy)
        return None

    return _apply(service, tech, service_type, tenant.assignment_strategy)


def _apply(service, tech, service_type, strategy):
    """Put *tech* on *service* and save."""
    service.technician = tech
    # The Repair/Replacement post_save assignment signal notifies the tech
    # (dashboard row + bell + email) — no hand-rolled notification here.
    # GlassService.save() clears needs_assignment if it was set.
    service.save(update_fields=['technician'])
    logger.info(
        "Auto-assigned %s #%s to %s (strategy=%s)",
        service_type, service.id, tech, strategy,
    )
    return tech


def _leave_unassigned(service, service_type, strategy):
    """Flag *service* for the manager's Unassigned queue.

    ``technician`` is NOT NULL, so the caller's provisional pick stays on the
    row: the flag, not an empty column, is what "nobody has picked this yet"
    means here.  Without it, Manual quietly assigned every customer request
    to whoever ``get_available_technician`` happened to return, and the
    settings page's promise that "a manager must manually assign every
    repair" was simply untrue.  (CODE-279)
    """
    if service.needs_assignment:
        return
    service.needs_assignment = True
    service.save(update_fields=['needs_assignment'])
    logger.info(
        "Left %s #%s unassigned for manager review (strategy=%s)",
        service_type, service.id, strategy,
    )

    from apps.technician_portal.services.assignments import (
        notify_needs_assignment,
    )
    notify_needs_assignment(service)


# ---------------------------------------------------------------------------
# Internal helpers — selection (read-only)
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


def _pick_primary(customer, tenant, service_type='repair'):
    """The customer's primary tech, if they have one and it is eligible."""
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

    return tech


def _pick_lowest_workload(tenant, service_type='repair', exclude_pk=None):
    """The eligible tech with the fewest active jobs of this service type."""
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
    if exclude_pk is not None:
        load_filter &= ~Q(**{f'{count_field}__pk': exclude_pk})

    return _get_eligible_techs(tenant, service_type).annotate(
        active_repairs=Count(count_field, filter=load_filter)
    ).order_by('active_repairs', 'id').first()


def _pick_round_robin(tenant, service_type='repair', exclude_pk=None):
    """The next eligible technician in ID order after the last one assigned.

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

    Jobs flagged ``needs_assignment`` are excluded from the anchor as well.
    Their technician is a provisional placeholder nobody chose and nobody was
    told about — letting one anchor the rotation would skip a real turn for
    the tech who follows them.  (CODE-279)

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
    anchor_qs = model.objects.filter(
        tenant=tenant, technician__isnull=False, needs_assignment=False)
    if exclude_pk is not None:
        anchor_qs = anchor_qs.exclude(pk=exclude_pk)
    last_tech_id = (
        anchor_qs.order_by('-id')
        .values_list('technician_id', flat=True)
        .first()
    )

    eligible_ids = [t.id for t in eligible_list]
    if last_tech_id in eligible_ids:
        next_idx = (eligible_ids.index(last_tech_id) + 1) % len(eligible_list)
        return eligible_list[next_idx]
    return eligible_list[0]


# ---------------------------------------------------------------------------
# Back-compat wrappers
# ---------------------------------------------------------------------------
# The strategy-specific entry points predate select_technician and are still
# the names the CODE-163/CODE-172/CODE-278 regression tests reach for.

def _assign_primary_first(service, tenant, service_type='repair'):
    """Assign to the customer's primary tech if one exists and is eligible."""
    tech = _pick_primary(service.customer, tenant, service_type)
    return _apply(service, tech, service_type, 'primary_first') if tech else None


def _assign_smart(service, tenant, service_type='repair'):
    """Primary tech first → then lowest-workload eligible tech."""
    tech = (_pick_primary(service.customer, tenant, service_type)
            or _pick_lowest_workload(tenant, service_type, service.pk))
    return _apply(service, tech, service_type, 'auto') if tech else None


def _assign_round_robin(service, tenant, service_type='repair'):
    """Rotate through eligible technicians by ID order."""
    tech = _pick_round_robin(tenant, service_type, service.pk)
    return _apply(service, tech, service_type, 'round_robin') if tech else None
