"""Assign and schedule in one motion — the dispatch board's write (FIELD_OPS S5).

S3 gave managers a day sheet, S4 gave the triage rail a Book button, S7 gave
booked rows a drag to trade times. What was missing is the other half of a
dispatch decision: *who*. This module is that motion — one click that can set
the technician, the day and the window together.

It writes nothing of its own. ``assign_job`` (N1) is still the only thing that
changes a technician and ``confirm_appointment`` (S4) is still the only thing
that writes ``scheduled_for``; this composes them inside one transaction so a
dispatch cannot half-apply, and decides the *single* notification that comes
out of it.

Three rules it adds on top of theirs:

1. **One motion, one message.** Assigning and booking in the same click used
   to be two notifications ("you have a new job" + "your job has a time") for
   one decision. When both happen, the assignment notification carries the
   booked time instead — ``notify_assignment_change(..., when=...)``.

2. **Who is locked the same way when is.** The caller sends the technician it
   believed the job had; a mismatch is a 409, exactly like S4's stale-time
   refusal. Two managers dispatching the same rail row at once is the same
   race S4 already found, and losing it silently is how a job ends up with the
   tech neither of them picked.

3. **One visit, one technician.** A multi-break repair is several rows of one
   physical visit, so a dispatch reassigns every row of the batch — the same
   reason S4 books the whole batch at one time.

The assignment half goes through ``job.save()`` (N1's helper), which re-prices
the job and syncs live invoices. That is not a regression of S4's
"booking must not touch money" rule: booking is still a bare ``.update()``,
and changing a technician has always been a full save everywhere else in the
app. What must never happen is the reverse — reaching for ``save()`` to set a
time.
"""

import logging

from django.db import transaction

from apps.technician_portal.services.schedule_booking import (
    BOOKABLE_STATUSES, BookingError, confirm_appointment, parse_booking_request,
)

logger = logging.getLogger(__name__)


class DispatchError(Exception):
    """A refusal the caller should render as JSON, with an HTTP status."""

    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _job_models():
    from apps.technician_portal.models import Repair, Replacement
    return {'repair': Repair, 'replacement': Replacement}


def parse_dispatch_request(payload):
    """Validate the board's payload into keyword arguments for ``apply_dispatch``.

    Shape is S4's booking payload plus ``technician_id`` /
    ``expected_technician_id``. Both halves are optional but not both absent:

    * date + window, no technician  → a plain booking (the rail's Book button)
    * technician, no date           → a reassignment of an already-booked row
    * both                          → the dispatch motion

    A booking's fields are validated by S4's parser so the two endpoints cannot
    drift on what a valid date/window/exact-pair is.
    """
    if not isinstance(payload, dict):
        raise DispatchError("Reload the board and try again.")

    key = str(payload.get('type') or '').strip().lower()
    if key not in _job_models():
        raise DispatchError("Unknown job type.")

    try:
        pk = int(payload.get('id'))
    except (TypeError, ValueError):
        raise DispatchError("Missing the job.")

    technician_id = _optional_int(payload.get('technician_id'), "technician")
    expected_technician_id = _optional_int(
        payload.get('expected_technician_id'), "technician")

    wants_booking = bool(str(payload.get('date') or '').strip())
    booking = None
    if wants_booking:
        try:
            # Reuse S4's parser wholesale — including its EXACT-window rules —
            # then drop the (type, id) it re-derives, which we already have.
            _key, _pk, day, window, start_time, end_time, expected = (
                parse_booking_request(dict(payload, type=key, id=pk)))
        except BookingError as exc:
            raise DispatchError(exc.message, status=exc.status)
        booking = {
            'day': day, 'window': window, 'start_time': start_time,
            'end_time': end_time, 'expected': expected,
        }

    if technician_id is None and booking is None:
        raise DispatchError("Pick a technician or a time.")

    return {
        'service_type': key,
        'pk': pk,
        'technician_id': technician_id,
        'expected_technician_id': expected_technician_id,
        'booking': booking,
    }


def _optional_int(raw, noun):
    if raw in (None, '', 'null'):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise DispatchError(f"That {noun} didn't look right. Reload the board.")


def _batch_pks(job, tenant, model):
    """Every row of this job's physical visit, pk-ordered, this one included."""
    batch_id = getattr(job, 'repair_batch_id', None)
    if not batch_id:
        return [job.pk]
    return list(
        model.objects.filter(tenant=tenant, repair_batch_id=batch_id)
        .order_by('pk').values_list('pk', flat=True)
    )


def _tech_name(technician):
    user = technician.user
    return user.get_full_name() or user.username


def apply_dispatch(*, tenant, service_type, pk, technician_id=None,
                   expected_technician_id=None, booking=None, actor_user=None):
    """Set who and/or when for a job (and its whole batch) in one transaction.

    Returns ``{'message': str, 'count': int}``. Raises ``DispatchError`` for
    every refusal, including the ones S4's booking service raises — the board
    speaks one error language.
    """
    from apps.technician_portal.models import Technician
    from apps.technician_portal.services.assignments import (
        assign_job, notify_assignment_change,
    )

    if tenant is None:
        raise DispatchError("No shop selected.", status=403)

    model = _job_models().get(service_type)
    if model is None:
        raise DispatchError("Unknown job type.")

    new_technician = None
    if technician_id is not None:
        new_technician = Technician.objects.filter(
            pk=technician_id, tenant=tenant, is_active=True,
        ).select_related('user').first()
        if new_technician is None:
            raise DispatchError(
                "That technician isn't on this shop's active roster.")

    with transaction.atomic():
        try:
            anchor = model.objects.select_for_update().get(pk=pk, tenant=tenant)
        except model.DoesNotExist:
            raise DispatchError(
                "That job is no longer here. Reload and try again.", status=404)

        # Lock the whole visit pk-ascending — S4/S7's deadlock guard. No
        # select_related under FOR UPDATE: Postgres refuses the nullable side
        # of an outer join and `customer` is nullable.
        jobs = []
        for job_pk in _batch_pks(anchor, tenant, model):
            try:
                jobs.append(model.objects.select_for_update().get(
                    pk=job_pk, tenant=tenant))
            except model.DoesNotExist:
                raise DispatchError(
                    "That job is no longer here. Reload and try again.",
                    status=404)

        for job in jobs:
            if job.queue_status not in BOOKABLE_STATUSES:
                raise DispatchError(
                    "Only open jobs can be dispatched — that one is "
                    f"{job.get_queue_status_display().lower()}.")

        anchor = next(job for job in jobs if job.pk == pk)
        old_technician = anchor.technician
        reassigned = (new_technician is not None
                      and old_technician.pk != new_technician.pk)

        if not reassigned and booking is None:
            # The picker was submitted unchanged and no time came with it.
            # Say so rather than flashing a success for a write that did not
            # happen — the board reloads, and a green toast over an unchanged
            # row is how a manager comes to distrust the whole screen.
            raise DispatchError(
                f"Nothing to change — that job is already "
                f"{_tech_name(old_technician)}'s.")

        if reassigned:
            # Same optimistic-lock discipline as the booked time: the row the
            # manager clicked has to still hold the technician their screen
            # showed. `None` means the caller didn't claim to know.
            if (expected_technician_id is not None
                    and old_technician.pk != expected_technician_id):
                raise DispatchError(
                    "Someone else moved this job while you were looking at "
                    "it. Reload and try again.",
                    status=409,
                )
            for job in jobs:
                # notify=False: the one message for this motion is decided
                # below, after the booking half has run.
                assign_job(job, new_technician, assigned_by=actor_user,
                           notify=False)

        booked = None
        if booking is not None:
            try:
                booked = confirm_appointment(
                    tenant=tenant, service_type=service_type, pk=pk,
                    day=booking['day'], window=booking['window'],
                    start_time=booking['start_time'],
                    end_time=booking['end_time'],
                    expected=booking['expected'], actor_user=actor_user,
                    # When this motion also reassigned, the tech hears about
                    # both facts in one assignment notification instead.
                    notify=not reassigned,
                )
            except BookingError as exc:
                raise DispatchError(exc.message, status=exc.status)

        if reassigned:
            for job in jobs:
                job.refresh_from_db()
            anchor = next(job for job in jobs if job.pk == pk)

            def _notify(anchor=anchor, old_technician=old_technician,
                        new_technician=new_technician):
                try:
                    # N1's rules apply unchanged, including its silence on
                    # REQUESTED work: a tech who cannot open the job yet
                    # (CODE-081) should not be told it is theirs. Same silence
                    # S4's booking notification already has.
                    notify_assignment_change(
                        anchor, old_technician, new_technician,
                        assigned_by=actor_user,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send dispatch notification for %s#%s",
                        service_type, anchor.pk,
                    )

            transaction.on_commit(_notify)

    logger.info(
        "fieldops S5 dispatch: tenant=%s actor=%s %s#%s rows=%s tech=%s->%s "
        "booked=%s",
        getattr(tenant, 'pk', None), getattr(actor_user, 'pk', None),
        service_type, pk, len(jobs),
        old_technician.pk if old_technician else None,
        new_technician.pk if reassigned else None,
        booked['scheduled_for'].isoformat() if booked else None,
    )

    return {
        'message': _message(anchor, jobs, reassigned, new_technician, booked),
        'count': len(jobs),
    }


def _message(anchor, jobs, reassigned, new_technician, booked):
    """What the board flashes back. One sentence covering what changed."""
    name = anchor.customer.name if anchor.customer_id else 'Walk-in'
    if booked and reassigned:
        # confirm_appointment's message already names the customer and the
        # time; adding the tech to it keeps the whole decision in one line.
        return booked['message'].rstrip('.') + f", {_tech_name(new_technician)}."
    if booked:
        return booked['message']
    suffix = f" ({len(jobs)} breaks)" if len(jobs) > 1 else ''
    return f"{name} moved to {_tech_name(new_technician)}{suffix}."
