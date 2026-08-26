"""
Day / agenda view (FIELD_OPS S3), and the writes that turned it into a
dispatch board (S4 book, S5 assign, S7 swap).

A technician sees their day in scheduled order; owners and managers see every
tech's day, with unscheduled work surfaced for triage. For a manager this page
*is* the dispatch board — S5 added the missing half of a dispatch decision
(who) beside the one S4 shipped (when), so a job can go from the rail to a
named tech at a named time in one click, and made the collisions that creates
visible. Every write is a thin endpoint over a service:
``services/schedule_swap`` (S7), ``services/schedule_booking`` (S4) and
``services/dispatch`` (S5, which composes the other two with N1's
``assign_job``). None of them duplicates another's rules.
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
from apps.technician_portal.services.dispatch import (
    DispatchError, apply_dispatch, parse_dispatch_request,
)
from apps.technician_portal.services.schedule_conflicts import (
    annotate_conflicts, technician_load,
)
from apps.technician_portal.services import working_hours
from apps.technician_portal.services.quick_job import (
    QuickJobError, allowed_service_types, create_job,
)

# What belongs on a day sheet: work that is a go, plus what already got done
# that day (a schedule with its finished jobs missing looks un-run, not run).
#
# REQUESTED is here as of S10, and the reason is worth keeping. S3 excluded it
# ("the shop hasn't accepted it yet") and put it in the triage rail instead —
# but the rail selects on `scheduled_for__isnull=True`, while
# `confirm_appointment` happily books a REQUESTED job (it is in
# BOOKABLE_STATUSES). So booking one out of the rail dropped it from the rail
# *and* never added it to the day: the job vanished from both lists. S3's
# rationale still holds for *unscheduled* requests, which the rail's own
# filter keeps there. The refined rule: a REQUESTED job with a booked time
# belongs on the sheet, marked, because somebody in the shop deliberately put
# it there. Booking does NOT promote it to APPROVED — that would bypass
# resolve_initial_shop_status and the approve/deny flow.
DAY_STATUSES = ('REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS', 'COMPLETED')
ACTIVE_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS')
TRIAGE_STATUSES = ('REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS')

TRIAGE_RAIL_CAP = 8


def _resolve_viewer(request, tenant):
    """Who is looking, and do they see the whole shop?

    Tenant-scoped Technician lookup — same rule as the dashboard (CODE-081):
    never resolve request.user.technician globally when a tenant is known.
    Shared by the day view and every write endpoint so they cannot disagree
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


def _can_assign(request, tenant, technician, sees_whole_shop):
    """Moving work between people needs more than seeing the whole shop.

    ``assign_repair`` has always gated on ``can_assign_work`` on top of
    ``is_manager`` (CODE-079); the board is a second door to the same action
    and must not be a weaker one. Owners/admins keep the bypass they have
    there — a shop with one owner and no manager still has to be able to
    dispatch.
    """
    if not sees_whole_shop:
        return False
    if is_tenant_admin(request.user, tenant=tenant):
        return True
    return bool(technician and technician.can_assign_work)


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
    roster = []
    if sees_whole_shop:
        by_tech = {}
        for job in jobs:
            by_tech.setdefault(job.technician_id, []).append(job)
        group_techs = {t.pk: t for t in Technician.objects.filter(
            tenant=tenant, is_active=True).select_related('user')} if tenant else {}
        # The roster is who a job can be dispatched TO: active techs only. An
        # inactive tech may still appear as a group below (they hold work
        # today) without being a place to send more.
        roster = list(group_techs.values())
        for job_list in by_tech.values():
            tech = job_list[0].technician
            group_techs.setdefault(tech.pk, tech)
        # S8: resolve the day's declared hours once per technician. Both the
        # group header and the dispatch picker read these off the instance —
        # the roster holds the same objects, so it is annotated by this loop
        # too. Anyone with nothing on file gets '' and False, which is what
        # keeps the board silent for a shop that never filled the form in.
        for tech in group_techs.values():
            tech.hours_today = working_hours.describe_day(
                tech.working_hours, day)
            tech.off_today = working_hours.is_off_on(tech.working_hours, day)
        groups = [
            {'technician': tech, 'jobs': by_tech.get(pk, []),
             # S5: conflicts are per-technician-day, so they are computed
             # here, once per group, rather than per row in the template.
             'load': technician_load(annotate_conflicts(by_tech.get(pk, [])))}
            for pk, tech in group_techs.items()
        ]
        groups.sort(key=lambda g: (
            0 if technician and g['technician'].pk == technician.pk else 1,
            (g['technician'].user.get_full_name()
             or g['technician'].user.username).lower(),
        ))
    else:
        # A tech's own day gets the same flags — being double-booked is
        # something the person driving to both should see first, and a job
        # sitting outside their own hours is something to query now rather
        # than at 6 AM.
        annotate_conflicts(jobs)

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
    # S5: the rail is the pile a manager works down, so it has to be possible
    # to see all of it. The cap stays the default — an 80-row rail above the
    # day would bury the day itself — but "show all" now expands in place
    # instead of bouncing to the job list, which loses the wish, the tech
    # picker and the Book button.
    show_all_rail = request.GET.get('rail') == 'all'
    triage_jobs = []
    if sees_whole_shop:
        triage_jobs = (unscheduled if show_all_rail
                       else unscheduled[:TRIAGE_RAIL_CAP])

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
        'show_all_rail': show_all_rail,
        'can_swap': sees_whole_shop,
        # S4: the rail's inline book control. Same permission as the swap —
        # scheduling is a dispatch decision, and plain techs cannot even see
        # REQUESTED work (CODE-081).
        'can_book': sees_whole_shop,
        # S5: the who half. Strictly narrower than can_book — a manager
        # without can_assign_work schedules the shop's work but does not move
        # it between people.
        'can_assign': _can_assign(request, tenant, technician, sees_whole_shop),
        'roster': roster,
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
        key, pk, day, window, start_time, end_time, expected = (
            parse_booking_request(payload))
        result = perform_booking(
            tenant=tenant, service_type=key, pk=pk, day=day, window=window,
            start_time=start_time, end_time=end_time,
            expected=expected, actor_user=request.user,
        )
    except BookingError as exc:
        return JsonResponse({'ok': False, 'error': exc.message},
                            status=exc.status)

    return JsonResponse({'ok': True, 'message': result['message']})


@technician_required
@require_POST
def dispatch_job(request):
    """Set who and/or when for a job in one motion (fieldops S5).

    The board's single write. Same shape and reasoning as the two endpoints
    above — JSON for every outcome including refusals, authorization in-body
    rather than via a redirecting decorator, and the caller must check
    ``response.ok`` and the content type because
    SubscriptionEnforcementMiddleware redirects a read-only tenant's POST
    instead of answering JSON.

    Two gates, not one: booking needs ``sees_whole_shop``, moving work between
    people additionally needs ``can_assign_work``. A payload carrying a
    technician is refused for a manager who only has the first.
    """
    tenant = getattr(request, 'tenant', None)
    technician, sees_whole_shop = _resolve_viewer(request, tenant)
    if not sees_whole_shop:
        return JsonResponse(
            {'ok': False, 'error': "Only managers can dispatch jobs."},
            status=403,
        )

    try:
        payload = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse(
            {'ok': False, 'error': "Reload the board and try again."},
            status=400,
        )

    try:
        parsed = parse_dispatch_request(payload)
        if (parsed['technician_id'] is not None
                and not _can_assign(request, tenant, technician,
                                    sees_whole_shop)):
            return JsonResponse(
                {'ok': False,
                 'error': "You can schedule work but not reassign it."},
                status=403,
            )
        result = apply_dispatch(
            tenant=tenant, actor_user=request.user, **parsed)
    except DispatchError as exc:
        return JsonResponse({'ok': False, 'error': exc.message},
                            status=exc.status)

    return JsonResponse({'ok': True, 'message': result['message']})


def _row_context(request, tenant, technician, sees_whole_shop, day):
    """The context keys `includes/schedule_row.html` needs, matching the day
    view exactly so a row inserted by JS is the same row a reload renders."""
    roster = list(Technician.objects.filter(
        tenant=tenant, is_active=True).select_related('user')) if tenant else []
    for tech in roster:
        tech.hours_today = working_hours.describe_day(tech.working_hours, day)
        tech.off_today = working_hours.is_off_on(tech.working_hours, day)
    return {
        'day': day,
        'can_swap': sees_whole_shop,
        'can_book': sees_whole_shop,
        'can_assign': _can_assign(request, tenant, technician, sees_whole_shop),
        'roster': roster,
        'preferred_windows': PREFERRED_WINDOW_CHOICES,
        'booking_default_date': day.isoformat(),
    }


@technician_required
@require_POST
def quick_job(request):
    """Create a job and book it in one submit (fieldops S10).

    The motion this exists for: a customer calls, and the shop puts them on
    tomorrow without leaving the schedule. Before this, that took Jobs → New
    Job → save → land on the job ticket → navigate to Schedule → find it in
    the rail → set date/window/tech → Book.

    Same shape as the three write endpoints above — JSON for every outcome
    including refusals, authorization checked in-body rather than with
    @manager_required (which redirects to HTML and queues a stray
    messages.warning), and the caller must check ``response.ok`` and the
    content type, because SubscriptionEnforcementMiddleware redirects POSTs
    from a read-only tenant instead of answering JSON.

    Two writes, one transaction, and they are deliberately different in kind:

    * **Creating the job goes through ``save()``** — pricing, TaxService and
      ``resolve_initial_shop_status`` (auto-approve) all live there, so a job
      built any other way diverges on money and on status. The no-``save()``
      house rule governs moving a *time*, not creating a job.
    * **The time is written by S4's ``confirm_appointment``**, so there stays
      exactly one answer to "how does a time get onto a job", and
      ``scheduled_window_end`` gets set like every other booked job.

    A booking failure rolls the job back rather than leaving an unscheduled
    orphan behind: the shop asked for a job *on a day*, and half of that is
    not a useful outcome.
    """
    from django.db import transaction
    from django.template.loader import render_to_string
    from apps.technician_portal.forms import QuickJobForm
    from apps.tenants.services.usage_service import limit_message_for

    tenant = getattr(request, 'tenant', None)
    technician, sees_whole_shop = _resolve_viewer(request, tenant)
    if not tenant:
        return JsonResponse({'ok': False, 'error': 'No shop selected.'},
                            status=403)
    # Same gate as book_appointment: this control books a time, and plain
    # techs cannot even see REQUESTED work (CODE-081).
    if not sees_whole_shop:
        return JsonResponse(
            {'ok': False, 'error': 'Only managers can add jobs to the schedule.'},
            status=403,
        )

    try:
        payload = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse(
            {'ok': False, 'error': 'Reload the schedule and try again.'},
            status=400,
        )

    # Validation reuses QuickJobForm rather than re-deriving its rules: it
    # tenant-scopes the customer and technician querysets in __init__, owns
    # the "existing customer XOR new individual" rule, and refuses a
    # replacement with no price. `scheduled_for` is deliberately NOT sent
    # through it — the modal's date/window go around the form into
    # confirm_appointment, which is what sets a window end too.
    form = QuickJobForm(
        {k: v for k, v in payload.items() if k != 'scheduled_for'},
        tenant=tenant, allowed_types=allowed_service_types(tenant),
    )
    if not form.is_valid():
        first = next(iter(form.errors.values()))[0]
        return JsonResponse(
            {'ok': False, 'error': first, 'errors': form.errors},
            status=400,
        )

    try:
        with transaction.atomic():
            service = create_job(
                tenant=tenant, actor_user=request.user,
                data=form.cleaned_data,
                # One motion, one message. The booking notification below
                # names the job, the tech and the time; an assignment notice
                # fired a millisecond earlier would say strictly less about
                # the same event.
                notify_assignment=False,
            )
            key = ('repair' if form.cleaned_data['service_type'] == 'repair'
                   else 'replacement')
            _k, _pk, day, window, start_time, end_time, _expected = (
                parse_booking_request({
                    'type': key,
                    'id': service.pk,
                    'date': payload.get('date'),
                    'window': payload.get('window'),
                    'start_time': payload.get('start_time'),
                    'end_time': payload.get('end_time'),
                    'expected': None,
                }))
            booking = perform_booking(
                tenant=tenant, service_type=key, pk=service.pk, day=day,
                window=window, start_time=start_time, end_time=end_time,
                expected=None, actor_user=request.user,
            )
    except QuickJobError as exc:
        error = (limit_message_for(request.user, tenant, exc.message)
                 if exc.status == 403 else exc.message)
        return JsonResponse(
            {'ok': False, 'error': error,
             'needs_confirmation': bool(exc.suggestions),
             'suggestions': exc.suggestions},
            status=exc.status,
        )
    except BookingError as exc:
        return JsonResponse({'ok': False, 'error': exc.message},
                            status=exc.status)

    service.refresh_from_db()
    service.service_type = key

    # The day currently on screen, so the caller knows whether the new row
    # belongs on it. Booking onto another day is a normal thing to do from
    # here (the customer asked for Friday), and silently inserting a Friday
    # row into Tuesday's list would be a lie.
    try:
        on_screen_day = datetime.strptime(
            payload.get('on_screen_date') or '', '%Y-%m-%d').date()
    except (ValueError, TypeError):
        on_screen_day = None

    row_html = ''
    if on_screen_day == day:
        annotate_conflicts([service])
        row_html = render_to_string(
            'technician_portal/includes/schedule_row.html',
            {'job': service,
             **_row_context(request, tenant, technician, sees_whole_shop, day)},
            request=request,
        )

    return JsonResponse({
        'ok': True,
        'message': booking['message'],
        'job': {
            'key': f'{key}-{service.pk}',
            'url': service.get_absolute_url() if hasattr(service, 'get_absolute_url') else '',
            'technician_id': service.technician_id,
            'scheduled_for': service.scheduled_for.isoformat() if service.scheduled_for else None,
        },
        'day': {
            'date': day.isoformat(),
            'on_screen': on_screen_day == day,
            'row_html': row_html,
        },
    })
