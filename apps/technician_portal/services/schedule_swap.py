"""Trade the booked times of two appointments (FIELD_OPS S7).

The day changes by phone call, not by form. "Put Acme first" used to mean
opening two job forms, editing two datetime fields, and checking by eye that
you didn't collide. This module is the single write path behind that gesture;
the S5 dispatch board is expected to reuse it rather than grow a second one.

Four rules shape everything here, each of them expensive to rediscover:

1. **Never call ``save()`` to move a time.** ``GlassService.save()`` re-prices
   the job (``TaxService`` runs on every Repair save) and pushes the new price
   onto any live invoice through ``invoice_sync``. A schedule change must not
   touch money, so the write is a queryset ``.update()``.

2. **Each job keeps its own duration.** The new window end is
   ``new_start + (old_end - old_start)``, never the other job's end — swapping
   the pair wholesale would graft a three-hour replacement window onto a
   thirty-minute repair. NULL stays NULL.

3. **Because ``.update()`` skips every model-layer check, whatever is not
   validated here is unvalidated.** The status machine and the batch integrity
   rules live in ``save()`` and do not run. Hence the explicit guards below.

4. **Notifications fire on commit, never inside the transaction.**
   ``NotificationService`` sends email synchronously and re-raises; inside the
   transaction that means an SMTP round-trip while holding two row locks, and
   a mail hiccup would roll back a swap the manager already watched happen.

Concurrency: the two rows are locked with separate ``select_for_update()``
gets issued in a deterministic ``(model, pk)`` order — ``filter(pk__in=[a, b])``
locks in DB-scan order rather than ours, and ``pk`` alone collides because
Repair 5 and Replacement 5 both exist. That ordering is the deadlock guard
when two managers swap the same pair in opposite directions. On top of it,
the expected current time is folded into the ``.update()`` WHERE clause and
the returned row count *is* the optimistic lock: ``count != 1`` means someone
moved the job first, which closes the read-then-check gap for free.
"""

import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.dateformat import format as format_date

logger = logging.getLogger(__name__)

# A job can only trade places while it is still open work. COMPLETED rows
# stay on the day sheet (dimmed) but are not draggable and not drop targets —
# moving the promise for work that already happened is meaningless.
SWAPPABLE_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS')


def _job_models():
    from apps.technician_portal.models import Repair, Replacement
    return {'repair': Repair, 'replacement': Replacement}


class SwapError(Exception):
    """A refusal the caller should render as JSON, with an HTTP status."""

    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def parse_ref(raw, label):
    """Validate one ``{type, id, scheduled_for}`` reference from the client.

    Returns ``(model_key, pk, expected_start)``. The expected start is
    required: it is what makes a stale drag a 409 instead of a silent
    overwrite of whatever the row holds now.
    """
    if not isinstance(raw, dict):
        raise SwapError(f"Missing the {label} job.")

    key = str(raw.get('type') or '').strip().lower()
    if key not in _job_models():
        raise SwapError(f"Unknown job type for the {label} job.")

    try:
        pk = int(raw.get('id'))
    except (TypeError, ValueError):
        raise SwapError(f"Missing the {label} job.")

    expected = parse_datetime(str(raw.get('scheduled_for') or ''))
    if expected is None:
        raise SwapError("Reload the schedule and try again.", status=409)
    if timezone.is_naive(expected):
        # Rows are stored aware (USE_TZ); a naive expectation can never
        # compare equal, so refuse rather than fail the WHERE clause later.
        raise SwapError("Reload the schedule and try again.", status=409)

    return key, pk, expected


def _shifted_end(job, new_start):
    """Preserve this job's own window length across the move."""
    if job.scheduled_window_end is None:
        return None
    return new_start + (job.scheduled_window_end - job.scheduled_for)


def _display_name(job):
    return job.customer.name if job.customer_id else 'Walk-in'


def _display_time(when):
    return format_date(timezone.localtime(when), 'g:i A')


@transaction.atomic
def swap_appointments(*, tenant, ref_a, ref_b, actor_user=None):
    """Trade the start times of two jobs in one technician's day.

    ``ref_a``/``ref_b`` are ``parse_ref`` triples. Raises ``SwapError`` for
    every refusal; on success returns a dict with a human summary.
    """
    models = _job_models()

    if tenant is None:
        raise SwapError("No shop selected.", status=403)

    a_key, a_pk, a_expected = ref_a
    b_key, b_pk, b_expected = ref_b
    if (a_key, a_pk) == (b_key, b_pk):
        raise SwapError("Drop a job onto a different job to trade times.")

    # Deterministic lock order — see the module docstring. Sorting the two
    # (model key, pk) tuples is the whole deadlock guard.
    refs = sorted([(a_key, a_pk), (b_key, b_pk)])
    locked = {}
    for key, pk in refs:
        model = models[key]
        try:
            # No select_related here: Postgres refuses FOR UPDATE against the
            # nullable side of an outer join, and Repair.customer is nullable.
            locked[(key, pk)] = model.objects.select_for_update().get(
                pk=pk, tenant=tenant)
        except model.DoesNotExist:
            raise SwapError(
                "That job is no longer on this schedule. Reload and try again.",
                status=404,
            )

    job_a = locked[(a_key, a_pk)]
    job_b = locked[(b_key, b_pk)]

    for job in (job_a, job_b):
        if job.scheduled_for is None:
            raise SwapError(
                "Both jobs need a booked time before they can trade places.")
        if job.queue_status not in SWAPPABLE_STATUSES:
            raise SwapError(
                "Only open jobs can be moved — that one is "
                f"{job.get_queue_status_display().lower()}.")
        # Multi-break repairs are one physical visit split across several
        # rows. Moving a single break would silently split the visit, so the
        # whole batch is refused; the job form is still the way to move it.
        if getattr(job, 'repair_batch_id', None):
            raise SwapError(
                "Multi-break jobs move together — open the job to change its time.")

    if job_a.technician_id != job_b.technician_id:
        raise SwapError(
            "Jobs can only trade times within one technician's day. "
            "To move work to another tech, reassign it.")

    if (timezone.localtime(job_a.scheduled_for).date()
            != timezone.localtime(job_b.scheduled_for).date()):
        raise SwapError("Those two jobs are on different days.")

    a_start, b_start = job_a.scheduled_for, job_b.scheduled_for
    plan = (
        (job_a, a_key, a_expected, b_start, _shifted_end(job_a, b_start)),
        (job_b, b_key, b_expected, a_start, _shifted_end(job_b, a_start)),
    )

    for job, key, expected, new_start, new_end in plan:
        # The row count is the optimistic lock: folding the expected time and
        # the allowed statuses into WHERE means a job someone else already
        # moved (or closed) updates zero rows instead of being overwritten.
        updated = models[key].objects.filter(
            pk=job.pk,
            tenant=tenant,
            scheduled_for=expected,
            queue_status__in=SWAPPABLE_STATUSES,
        ).update(scheduled_for=new_start, scheduled_window_end=new_end)
        if updated != 1:
            raise SwapError(
                "This schedule changed while you were looking at it. "
                "Reload and try again.",
                status=409,
            )

    # .update() leaves the in-memory objects holding the OLD times, so every
    # message built from here on must read the refreshed rows.
    job_a.refresh_from_db()
    job_b.refresh_from_db()

    # The only record that this happened: GlassService has no updated_at, no
    # history model, and .update() fires no signal.
    logger.info(
        "fieldops S7 schedule swap: tenant=%s actor=%s technician=%s "
        "%s#%s %s->%s | %s#%s %s->%s",
        getattr(tenant, 'pk', None),
        getattr(actor_user, 'pk', None),
        job_a.technician_id,
        a_key, job_a.pk, a_start.isoformat(), job_a.scheduled_for.isoformat(),
        b_key, job_b.pk, b_start.isoformat(), job_b.scheduled_for.isoformat(),
    )

    message = (
        f"{_display_name(job_a)} moved to {_display_time(job_a.scheduled_for)}, "
        f"{_display_name(job_b)} to {_display_time(job_b.scheduled_for)}."
    )

    def _notify():
        from apps.technician_portal.services.assignments import (
            notify_schedule_swap,
        )
        try:
            notify_schedule_swap(job_a, job_b, actor_user=actor_user)
        except Exception:
            logger.exception(
                "Failed to send schedule-swap notification for %s#%s / %s#%s",
                a_key, job_a.pk, b_key, job_b.pk,
            )

    transaction.on_commit(_notify)

    return {'message': message}
