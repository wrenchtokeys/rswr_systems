"""
Day / agenda view (FIELD_OPS S3).

A technician sees their day in scheduled order; owners and managers see
every tech's day, with unscheduled work surfaced for triage. Read-mostly:
nothing here edits a job — entries link to the detail pages, and the S2
map/call actions ride along on each row.
"""

from datetime import date as date_cls, datetime, time, timedelta

from django.shortcuts import render
from django.utils import timezone

from apps.technician_portal.models import Technician, Repair, Replacement
from apps.technician_portal.decorators import technician_required, is_tenant_admin

# What belongs on a day sheet: work that is a go, plus what already got done
# that day (a schedule with its finished jobs missing looks un-run, not run).
# REQUESTED stays off the sheet — the shop hasn't accepted it yet; for
# managers it shows in the triage rail instead.
DAY_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS', 'COMPLETED')
ACTIVE_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS')
TRIAGE_STATUSES = ('REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS')

TRIAGE_RAIL_CAP = 8


@technician_required
def day_schedule(request):
    """One day of booked work, grouped by technician for managers."""
    tenant = getattr(request, 'tenant', None)

    # Tenant-scoped Technician lookup — same rule as the dashboard (CODE-081):
    # never resolve request.user.technician globally when a tenant is known.
    technician = None
    if hasattr(request.user, 'technician'):
        if tenant:
            technician = Technician.objects.filter(
                user=request.user, tenant=tenant).first()
        else:
            technician = request.user.technician

    is_admin = is_tenant_admin(request.user, tenant=tenant)
    sees_whole_shop = is_admin or bool(technician and technician.is_manager)

    local_today = timezone.localtime(timezone.now()).date()
    day = local_today
    raw_date = request.GET.get('date', '')
    if raw_date:
        try:
            day = date_cls.fromisoformat(raw_date)
        except ValueError:
            pass

    # Local-calendar day boundaries; storage is UTC (USE_TZ), so the window
    # must be built in the shop's timezone or evening jobs land on the wrong
    # sheet. Combining at midnight per-day (rather than start + 24h) keeps
    # DST-transition days honest.
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(day, time.min), tz)
    day_end = timezone.make_aware(
        datetime.combine(day + timedelta(days=1), time.min), tz)

    def _scoped(model, **filters):
        """Tenant + (for plain techs) own-jobs scoping shared by every query."""
        if not tenant:
            return model.objects.none()
        qs = model.objects.filter(tenant=tenant, **filters)
        if not sees_whole_shop:
            if technician is None:
                return model.objects.none()
            qs = qs.filter(technician=technician)
        return qs

    # Replacements are deliberately NOT gated on tenant.offers_replacements:
    # a booked replacement is a promise to a customer, and flipping the shop
    # toggle off must not make tomorrow's appointment vanish from the sheet.
    day_filters = dict(
        scheduled_for__gte=day_start,
        scheduled_for__lt=day_end,
        queue_status__in=DAY_STATUSES,
    )
    jobs = []
    for repair in _scoped(Repair, **day_filters).select_related(
            'customer', 'technician__user'):
        repair.service_type = 'repair'
        jobs.append(repair)
    for repl in _scoped(Replacement, **day_filters).select_related(
            'customer', 'technician__user'):
        repl.service_type = 'replacement'
        jobs.append(repl)
    jobs.sort(key=lambda j: (j.scheduled_for, j.pk))
    done_count = sum(1 for j in jobs if j.queue_status == 'COMPLETED')

    # Managers see one group per tech — every active tech, so "nobody booked
    # Marcus today" is visible, plus any inactive tech who still holds a job.
    groups = None
    if sees_whole_shop:
        by_tech = {}
        for job in jobs:
            by_tech.setdefault(job.technician_id, []).append(job)
        group_techs = {t.pk: t for t in Technician.objects.filter(
            tenant=tenant, is_active=True).select_related('user')} if tenant else {}
        for job_list in by_tech.values():
            tech = job_list[0].technician
            group_techs.setdefault(tech.pk, tech)
        groups = [
            {'technician': tech, 'jobs': by_tech.get(pk, [])}
            for pk, tech in group_techs.items()
        ]
        groups.sort(key=lambda g: (
            0 if technician and g['technician'].pk == technician.pk else 1,
            (g['technician'].user.get_full_name()
             or g['technician'].user.username).lower(),
        ))

    # Unscheduled work: the honest empty state for techs ("nothing scheduled
    # — 4 unscheduled jobs"), the triage rail for managers. Managers' rail
    # includes REQUESTED — that's the "seed of S5" to-schedule pile.
    rail_statuses = TRIAGE_STATUSES if sees_whole_shop else ACTIVE_STATUSES
    unscheduled = []
    for repair in _scoped(
            Repair, scheduled_for__isnull=True,
            queue_status__in=rail_statuses).select_related(
                'customer', 'technician__user'):
        repair.service_type = 'repair'
        unscheduled.append(repair)
    for repl in _scoped(
            Replacement, scheduled_for__isnull=True,
            queue_status__in=rail_statuses).select_related(
                'customer', 'technician__user'):
        repl.service_type = 'replacement'
        unscheduled.append(repl)
    # Newest first, same as the dashboard's request card.
    unscheduled.sort(
        key=lambda j: (j.service_date is not None, j.service_date), reverse=True)
    unscheduled_count = len(unscheduled)
    triage_jobs = unscheduled[:TRIAGE_RAIL_CAP] if sees_whole_shop else []

    return render(request, 'technician_portal/schedule.html', {
        'technician': technician,
        'sees_whole_shop': sees_whole_shop,
        'day': day,
        'prev_day': day - timedelta(days=1),
        'next_day': day + timedelta(days=1),
        'is_today': day == local_today,
        'jobs': jobs,
        'groups': groups,
        'done_count': done_count,
        'unscheduled_count': unscheduled_count,
        'triage_jobs': triage_jobs,
        'triage_overflow': max(0, unscheduled_count - len(triage_jobs)),
    })
