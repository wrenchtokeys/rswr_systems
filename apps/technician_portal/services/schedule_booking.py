"""Turn a customer's requested time into a real booking (FIELD_OPS S4).

A customer can now say *when* they want the work done. That wish lands in
``GlassService.preferred_date`` / ``preferred_window`` and goes no further on
its own — this module is the only thing that promotes it to ``scheduled_for``,
and it only runs when someone in the shop asks for it.

Why the separation matters: a customer repair request auto-approves to
APPROVED milliseconds after creation (``_auto_accept_customer_repair``), and
APPROVED is in the day view's ``DAY_STATUSES``. The single thing keeping an
unagreed time off a technician's day sheet is that ``scheduled_for`` is null.
Defaulting it to the wish would publish an appointment the shop never made.

The write rules are S7's, and for the same reasons — see
``services/schedule_swap.py`` for the long form:

1. **Never ``save()`` to set a time.** ``GlassService.save()`` re-prices the
   job (``TaxService`` runs on every Repair save) and pushes the price onto
   any live invoice through ``invoice_sync``. Booking a time must not touch
   money, so the write is a queryset ``.update()``.

2. **``.update()`` skips every model-layer check**, so whatever is not
   validated here is unvalidated.

3. **One submission, one visit.** A multi-break repair is several rows of one
   physical visit (``repair_batch_id``), so confirming books the whole batch
   in one transaction at one time. S7 refuses to drag a batched job for
   exactly this reason; a per-row confirm would reintroduce the split.

4. **Notifications fire on commit**, never inside the transaction holding the
   row locks.

The optimistic lock is the same trick as S7's: the caller sends the time it
believed the job had (normally "none"), that expectation is folded into the
``.update()`` WHERE clause, and the returned row count *is* the lock. Two
managers confirming the same request at once is the realistic race.
"""

import logging
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.utils.dateparse import parse_date, parse_datetime

from apps.technician_portal.models import (
    PREFERRED_WINDOW_HOURS, PREFERRED_WINDOW_SHORT,
)

logger = logging.getLogger(__name__)

# A time can be booked onto work that is still open. COMPLETED and DENIED are
# excluded: promising to arrive for work that is finished or dead is
# meaningless. REQUESTED *is* included — a replacement sits there until the
# shop prices it, and scheduling the visit is part of accepting it.
BOOKABLE_STATUSES = ('REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS')


def _job_models():
    from apps.technician_portal.models import Repair, Replacement
    return {'repair': Repair, 'replacement': Replacement}


class BookingError(Exception):
    """A refusal the caller should render as JSON, with an HTTP status."""

    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def window_bounds(day, window):
    """(start, end) aware datetimes for a (date, window) pair.

    Built in the shop's local timezone and combined per-day, the same
    convention the day view uses for its day boundaries — storage stays UTC.
    An unknown window falls back to ANYTIME rather than raising, so a stale
    choice in a form POST books a sane full day instead of failing.

    Both ends are wall-clock times combined with the date, so "8 AM to noon"
    stays 8 AM to noon on a DST-transition day.
    """
    start_hour, end_hour = PREFERRED_WINDOW_HOURS.get(
        window, PREFERRED_WINDOW_HOURS['ANYTIME'])
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time(start_hour, 0)), tz)
    end = timezone.make_aware(datetime.combine(day, time(end_hour, 0)), tz)
    return start, end


def parse_booking_request(payload):
    """Validate the client's ``{type, id, date, window, expected}`` payload.

    ``expected`` is what the caller believed ``scheduled_for`` held — the
    string ``''``/absent means "this job is unscheduled", which is the normal
    case for a confirm. Anything else must be an ISO-8601 datetime.
    """
    if not isinstance(payload, dict):
        raise BookingError("Reload the schedule and try again.")

    key = str(payload.get('type') or '').strip().lower()
    if key not in _job_models():
        raise BookingError("Unknown job type.")

    try:
        pk = int(payload.get('id'))
    except (TypeError, ValueError):
        raise BookingError("Missing the job.")

    day = parse_date(str(payload.get('date') or '').strip())
    if day is None:
        raise BookingError("Pick a date for this visit.")

    window = str(payload.get('window') or '').strip().upper()
    if window not in PREFERRED_WINDOW_HOURS:
        raise BookingError("Pick a time of day for this visit.")

    raw_expected = str(payload.get('expected') or '').strip()
    expected = None
    if raw_expected:
        expected = parse_datetime(raw_expected)
        # Rows are stored aware (USE_TZ); a naive expectation can never compare
        # equal, so refuse rather than fail the WHERE clause later.
        if expected is None or timezone.is_naive(expected):
            raise BookingError("Reload the schedule and try again.", status=409)

    return key, pk, day, window, expected


def _batch_siblings(job, tenant):
    """Every row of this job's physical visit, this one included.

    Only repairs batch. Returns a pk-ordered list so the lock order below is
    deterministic.
    """
    from apps.technician_portal.models import Repair

    batch_id = getattr(job, 'repair_batch_id', None)
    if not batch_id:
        return [job.pk]
    return list(
        Repair.objects.filter(tenant=tenant, repair_batch_id=batch_id)
        .order_by('pk').values_list('pk', flat=True)
    )


def _display_name(job):
    return job.customer.name if job.customer_id else 'Walk-in'


@transaction.atomic
def confirm_appointment(*, tenant, service_type, pk, day, window,
                        expected=None, actor_user=None):
    """Book ``day`` + ``window`` onto a job (and its whole batch).

    Returns ``{'message': str, 'count': int, 'scheduled_for': datetime}``.
    Raises ``BookingError`` for every refusal.
    """
    models = _job_models()

    if tenant is None:
        raise BookingError("No shop selected.", status=403)

    model = models.get(service_type)
    if model is None:
        raise BookingError("Unknown job type.")

    if window not in PREFERRED_WINDOW_HOURS:
        raise BookingError("Pick a time of day for this visit.")

    # Lock the whole visit, pk-ascending — the same deterministic ordering S7
    # uses as its deadlock guard. Repairs only ever batch with repairs, so one
    # model is enough here.
    try:
        anchor = model.objects.get(pk=pk, tenant=tenant)
    except model.DoesNotExist:
        raise BookingError(
            "That job is no longer here. Reload and try again.", status=404)

    pks = _batch_siblings(anchor, tenant)
    jobs = []
    for job_pk in pks:
        try:
            # No select_related under FOR UPDATE: Postgres refuses the
            # nullable side of an outer join and Repair.customer is nullable.
            jobs.append(model.objects.select_for_update().get(
                pk=job_pk, tenant=tenant))
        except model.DoesNotExist:
            raise BookingError(
                "That job is no longer here. Reload and try again.", status=404)

    for job in jobs:
        if job.queue_status not in BOOKABLE_STATUSES:
            raise BookingError(
                "Only open jobs can be booked — that one is "
                f"{job.get_queue_status_display().lower()}.")

    start, end = window_bounds(day, window)

    for job in jobs:
        # The row count IS the optimistic lock. `expected` applies to the row
        # the caller actually clicked; the rest of a batch must match it too,
        # so a batch half-moved by someone else refuses rather than splitting.
        updated = model.objects.filter(
            pk=job.pk,
            tenant=tenant,
            scheduled_for=expected,
            queue_status__in=BOOKABLE_STATUSES,
        ).update(scheduled_for=start, scheduled_window_end=end)
        if updated != 1:
            raise BookingError(
                "This job's time changed while you were looking at it. "
                "Reload and try again.",
                status=409,
            )

    # .update() leaves the in-memory rows holding the OLD time.
    for job in jobs:
        job.refresh_from_db()

    anchor = jobs[0]
    logger.info(
        "fieldops S4 appointment confirmed: tenant=%s actor=%s %s#%s "
        "rows=%s wished=%s/%s booked=%s",
        getattr(tenant, 'pk', None), getattr(actor_user, 'pk', None),
        service_type, pk, len(jobs),
        anchor.preferred_date.isoformat() if anchor.preferred_date else None,
        anchor.preferred_window or None,
        start.isoformat(),
    )

    when = format_date(timezone.localtime(start), 'D, M j')
    window_label = PREFERRED_WINDOW_SHORT.get(window, 'any time')
    suffix = f" ({len(jobs)} breaks)" if len(jobs) > 1 else ''
    message = (
        f"{_display_name(anchor)} booked for {when}, {window_label}{suffix}."
    )

    def _notify():
        from apps.technician_portal.services.assignments import (
            notify_appointment_set,
        )
        try:
            notify_appointment_set(anchor, job_count=len(jobs),
                                   actor_user=actor_user)
        except Exception:
            logger.exception(
                "Failed to send booking notification for %s#%s",
                service_type, anchor.pk,
            )

    transaction.on_commit(_notify)

    return {'message': message, 'count': len(jobs), 'scheduled_for': start}
