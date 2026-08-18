"""
Day / agenda view (FIELD_OPS S3) and the drag-to-swap endpoint (S7).

A technician sees their day in scheduled order; owners and managers see
every tech's day, with unscheduled work surfaced for triage. The day view
itself is read-only — entries link to the detail pages, and the S2 map/call
actions ride along on each row. The one write here is ``swap_appointments``,
which lets a manager drag one booked job onto another in the same tech's day
so the two trade times; all of its logic lives in ``services/schedule_swap``.
"""

import json
from datetime import date as date_cls, datetime, time, timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.technician_portal.models import (
    PREFERRED_WINDOW_CHOICES, Technician, Repair, Replacement,
)
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from apps.technician_portal.services.schedule_swap import (
    SwapError, parse_ref, swap_appointments as perform_swap,
)
from apps.technician_portal.services.schedule_booking import (
    BookingError, confirm_appointment as perform_booking, parse_booking_request,
)

# What belongs on a day sheet: work that is a go, plus what already got done
# that day (a schedule with its finished jobs missing looks un-run, not run).
# REQUESTED stays off the sheet — the shop hasn't accepted it yet; for
# managers it shows in the triage rail instead.
DAY_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS', 'COMPLETED')
ACTIVE_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS')
TRIAGE_STATUSES = ('REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS')

TRIAGE_RAIL_CAP = 8


def _resolve_viewer(request, tenant):
    """Who is looking, and do they see the whole shop?

    Tenant-scoped Technician lookup — same rule as the dashboard (CODE-081):
    never resolve request.user.technician globally when a tenant is known.
    Shared by the day view and the swap endpoint so the two cannot disagree
    about who is a manager.
    """
    technician = None
    if hasattr(request.user, 'technician'):
        if tenant:
            technician = Technician.objects.filter(
                user=request.user, tenant=tenant).first()
        else:
            technician = request.user.technician

    is_admin = is_tenant_admin(request.user, tenant=tenant)
    sees_whole_shop = is_admin or bool(technician and technician.is_manager)
    return technician, sees_whole_shop


@technician_required
def day_schedule(request):
    """One day of booked work, grouped by technician for managers."""
    tenant = getattr(request, 'tenant', None)
    technician, sees_whole_shop = _resolve_viewer(request, tenant)

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
    # Soonest wish first, then newest (S4). The rail is capped at 8, so
    # sorting purely by recency buried a customer who asked for tomorrow
    # underneath eight requests that named no day at all.
    def _rail_key(job):
        return (
            job.preferred_date is None,
            job.preferred_date or date_cls.max,
            -(job.service_date.timestamp() if job.service_date else 0),
        )

    unscheduled.sort(key=_rail_key)
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
        'can_swap': sees_whole_shop,
        # S4: the rail's inline book control. Same permission as the swap —
        # scheduling is a dispatch decision, and plain techs cannot even see
        # REQUESTED work (CODE-081).
        'can_book': sees_whole_shop,
        'preferred_windows': PREFERRED_WINDOW_CHOICES,
        'booking_default_date': day.isoformat(),
    })


@technician_required
@require_POST
def swap_appointments(request):
    """Trade the booked times of two jobs (fieldops S7).

    Answers JSON for every outcome, including refusals. Authorization is
    checked in-body rather than with @manager_required on purpose: that
    decorator redirects to HTML *and* queues a messages.warning, which would
    surface as a stray banner on the manager's next page load. It also
    resolves request.user.technician globally, which this view deliberately
    avoids (CODE-081).

    Note for the caller: SubscriptionEnforcementMiddleware blocks every POST
    from a read-only/grace tenant before this view runs, and returns JSON only
    for paths under /api/ — otherwise it redirects. The client must check
    response.ok and the content type before parsing.
    """
    tenant = getattr(request, 'tenant', None)
    _technician, sees_whole_shop = _resolve_viewer(request, tenant)
    if not sees_whole_shop:
        return JsonResponse(
            {'ok': False, 'error': "Only managers can move booked times."},
            status=403,
        )

    try:
        payload = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse(
            {'ok': False, 'error': "Reload the schedule and try again."},
            status=400,
        )

    try:
        ref_a = parse_ref(payload.get('a'), 'first')
        ref_b = parse_ref(payload.get('b'), 'second')
        result = perform_swap(
            tenant=tenant, ref_a=ref_a, ref_b=ref_b, actor_user=request.user,
        )
    except SwapError as exc:
        return JsonResponse({'ok': False, 'error': exc.message},
                            status=exc.status)

    return JsonResponse({'ok': True, 'message': result['message']})


@technician_required
@require_POST
def book_appointment(request):
    """Turn a customer's requested time into a real booking (fieldops S4).

    Same shape and the same reasoning as ``swap_appointments`` above: JSON for
    every outcome including refusals, authorization checked in-body rather
    than with @manager_required (which redirects to HTML and queues a stray
    messages.warning), and the caller must check ``response.ok`` and the
    content type — SubscriptionEnforcementMiddleware redirects POSTs from a
    read-only tenant instead of answering JSON.
    """
    tenant = getattr(request, 'tenant', None)
    _technician, sees_whole_shop = _resolve_viewer(request, tenant)
    if not sees_whole_shop:
        return JsonResponse(
            {'ok': False, 'error': "Only managers can book times."},
            status=403,
        )

    try:
        payload = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse(
            {'ok': False, 'error': "Reload the schedule and try again."},
            status=400,
        )

    try:
        key, pk, day, window, expected = parse_booking_request(payload)
        result = perform_booking(
            tenant=tenant, service_type=key, pk=pk, day=day, window=window,
            expected=expected, actor_user=request.user,
        )
    except BookingError as exc:
        return JsonResponse({'ok': False, 'error': exc.message},
                            status=exc.status)

    return JsonResponse({'ok': True, 'message': result['message']})
