"""What the dispatch board flags, and what it deliberately does not (S5).

Conflict display here is **informational**. Nothing in this module blocks a
write — a shop that wants to promise two fleets the same hour is allowed to,
because it might genuinely have two people. The board's job is to make sure
nobody does it by accident.

Four signals, and the reasoning behind each is the interesting part:

1. **Double-booked (per row).** Two jobs on one technician's day whose booked
   windows overlap. Only flagged when *both* windows are narrow — see
   ``PRECISE_WINDOW_MAX``. This is the one that matters: a fleet promised
   04:30–05:45 and another promised 05:00–06:00 is a broken promise already.

2. **Over-committed (per technician).** Nominal work (``NOMINAL_JOB_LENGTH``
   per job) exceeding the span of the day it was booked into. This is what
   catches the coarse case that (1) deliberately ignores.

3. **Off the customer's ask (per row).** The booked time doesn't satisfy the
   date/window the customer requested in S4. Actionable in a way an overlap
   isn't: someone can still call them.

4. **Outside the technician's declared hours (per row, S8).** The booking
   falls outside what the shop said this person works — or lands on a day
   they don't work at all. Silent for anyone with no hours on file, which is
   every technician until a shop says otherwise.

**Why (1) is not plain interval overlap.** S4 books a preset window into real
clock hours — MORNING is 08:00–12:00, ANYTIME is 08:00–17:00. Every pair of
jobs booked "morning" therefore overlaps exactly, and a board that flagged
that would flag a normal day end to end, which is the same as flagging
nothing. Narrow windows are the only ones that assert a clock time, so they
are the only ones where an overlap means something. The coarse case is real
too — it is just a *capacity* question, not a collision, and signal (2) is
where it belongs.

**What availability does and does not mean here (S8).** ``Technician.
working_hours`` is a weekly pattern and nothing more: no PTO, no date-ranged
time off, no capacity model. An empty record means **undeclared**, never
"never works" — every row in every shop holds one until somebody fills the
form in, so a reader that treats blank as unavailable would flag every job in
the shop on the day it deployed. Undeclared therefore produces no signal at
all, and ``covers()`` returns ``None`` rather than ``False`` to force the
question. ``NOMINAL_JOB_LENGTH`` is still a placeholder, not a measurement —
nothing models how long a job actually takes.
"""

from datetime import timedelta

from django.utils import timezone
from django.utils.dateformat import format as format_date

from apps.technician_portal.models import PREFERRED_WINDOW_HOURS
from apps.technician_portal.services import working_hours
from apps.technician_portal.services.schedule_booking import NOMINAL_JOB_LENGTH

# A booked window at or under this length is a promise to a clock; anything
# longer is a bucket ("morning", "any time") and overlapping buckets are the
# normal shape of a working day, not a mistake.
PRECISE_WINDOW_MAX = timedelta(hours=2)


def _bounds(job):
    """(start, end) for a booked job, or None. End falls back to nominal."""
    if not job.scheduled_for:
        return None
    end = job.scheduled_window_end or job.scheduled_for + NOMINAL_JOB_LENGTH
    if end <= job.scheduled_for:
        # Hand-edited or legacy data. Treat as nominal rather than negative.
        end = job.scheduled_for + NOMINAL_JOB_LENGTH
    return job.scheduled_for, end


def _clock(value):
    return format_date(timezone.localtime(value), 'g:i A')


def _who(job):
    name = job.customer.name if job.customer_id else 'Walk-in'
    return name


def _tech_name(tech):
    """First name — chips are read at a glance, and the board is 1–5 people."""
    name = (tech.user.get_full_name() or tech.user.username or '').strip()
    return name.split()[0] if name else 'This technician'


def annotate_conflicts(jobs):
    """Attach ``job.conflicts`` (a list of short strings) to each booked job.

    ``jobs`` is one technician's day, in any order. Returns the same list so
    callers can chain. Rows with nothing to say get an empty list rather than
    no attribute, so the template never needs a ``default``.
    """
    booked = []
    for job in jobs:
        job.conflicts = []
        bounds = _bounds(job)
        if bounds:
            booked.append((job, bounds))

    # --- 1. double-booked -------------------------------------------------
    precise = [
        (job, start, end) for job, (start, end) in booked
        if end - start <= PRECISE_WINDOW_MAX
    ]
    precise.sort(key=lambda row: (row[1], row[0].pk))
    # Collected per row, then rendered as ONE chip. Three jobs stacked on the
    # same hour would otherwise print the same sentence twice on every row,
    # and a wall of identical warnings reads as decoration.
    partners = {}
    for i, (job, start, end) in enumerate(precise):
        for other, other_start, _other_end in precise[i + 1:]:
            if other_start >= end:
                break  # sorted by start — nothing later can overlap either
            if getattr(job, 'repair_batch_id', None) and (
                    getattr(job, 'repair_batch_id', None)
                    == getattr(other, 'repair_batch_id', None)):
                continue  # one physical visit, booked as one by design (S4)
            partners.setdefault(job.pk, []).append((other, other_start))
            partners.setdefault(other.pk, []).append((job, start))

    for job, (start, _end) in booked:
        overlapping = partners.get(job.pk)
        if not overlapping:
            continue
        if len(overlapping) == 1:
            other, other_start = overlapping[0]
            job.conflicts.append(
                f"Overlaps {_who(other)} at {_clock(other_start)}")
        else:
            job.conflicts.append(
                f"Overlaps {len(overlapping)} other jobs at this time")

    # --- 3. off the customer's ask ---------------------------------------
    for job, (start, end) in booked:
        missed = describe_missed_preference(job, start, end)
        if missed:
            job.conflicts.append(missed)

    # --- 4. outside the technician's hours (S8) ---------------------------
    for job, (start, end) in booked:
        outside = describe_outside_hours(job, start, end)
        if outside:
            job.conflicts.append(outside)

    return jobs


def describe_missed_preference(job, start=None, end=None):
    """'Asked for Tue, Aug 19 (morning)' when the booking doesn't honour it.

    Returns '' when there was no ask, or when the booking satisfies it. The
    booked window must fall *inside* what the customer offered — a fleet
    saying "04:30 to 05:45" is stating when the truck exists, not a
    preference to be approximated.
    """
    if not job.scheduled_for or not job.has_time_preference:
        return ''
    if start is None or end is None:
        bounds = _bounds(job)
        if not bounds:
            return ''
        start, end = bounds

    local_start = timezone.localtime(start)
    local_end = timezone.localtime(end)
    ok = True

    if job.preferred_date and local_start.date() != job.preferred_date:
        ok = False
    elif job.has_exact_time_preference:
        if job.preferred_time_start and local_start.time() < job.preferred_time_start:
            ok = False
        if job.preferred_time_end and local_end.time() > job.preferred_time_end:
            ok = False
    elif job.preferred_window and job.preferred_window != 'ANYTIME':
        open_hour, close_hour = PREFERRED_WINDOW_HOURS.get(
            job.preferred_window, PREFERRED_WINDOW_HOURS['ANYTIME'])
        if local_start.hour < open_hour or (
                local_end.hour > close_hour
                or (local_end.hour == close_hour and local_end.minute > 0)):
            ok = False

    if ok:
        return ''
    return f"Asked for {job.get_time_preference()}"


def describe_outside_hours(job, start=None, end=None):
    """'Outside Dana's hours' when a booking sits outside what she works.

    Returns '' when this technician has no hours on file — the common case,
    and the one that keeps the board quiet for every shop that never fills
    the form in. ``covers()`` answers None there, which is why it is checked
    for None before it is checked for falsity.
    """
    tech = job.technician if job.technician_id else None
    if tech is None:
        return ''
    if start is None or end is None:
        bounds = _bounds(job)
        if not bounds:
            return ''
        start, end = bounds

    covered = working_hours.covers(tech.working_hours, start, end)
    if covered is None or covered:
        return ''

    name = _tech_name(tech)
    local_day = timezone.localtime(start).date()
    if working_hours.is_off_on(tech.working_hours, local_day):
        # The weekday, not the date: "off Tuesdays" is the standing fact a
        # dispatcher needs, and it is the same sentence next week.
        return f"{name} is off {format_date(local_day, 'l')}s"
    window = working_hours.describe_day(tech.working_hours, local_day)
    if window:
        return f"Outside {name}'s hours ({window})"
    return f"Outside {name}'s hours"


def technician_load(jobs):
    """Summarize one technician's booked day.

    Returns ``{'count', 'nominal_hours', 'span_hours', 'available_hours',
    'basis', 'over_committed', 'summary'}``, or None when the tech has nothing
    booked. ``summary`` is the line the board prints; it is only worth
    printing when over-committed, so the caller checks that flag.

    **What the work is measured against (S8).** Declared working hours when
    this technician has them, the span the jobs happen to occupy when they
    don't. The span is a weak denominator and always was — two half-hour jobs
    booked back to back look over-committed under it, while a day booked
    07:00–19:00 never does — but it is the only honest answer for someone the
    shop has said nothing about. ``basis`` records which one was used.
    """
    bounds = [b for b in (_bounds(job) for job in jobs) if b]
    if not bounds:
        return None

    count = len(bounds)
    first_start = min(start for start, _e in bounds)
    span = max(end for _s, end in bounds) - first_start
    nominal = NOMINAL_JOB_LENGTH * count
    span_hours = span.total_seconds() / 3600
    nominal_hours = nominal.total_seconds() / 3600

    def hours(value):
        # '4h' / '4.5h' — a dispatcher reads this at a glance, and a decimal
        # point on a whole number is visual noise.
        return f"{value:g}h"

    tech = next((job.technician for job in jobs if job.technician_id), None)
    local_day = timezone.localtime(first_start).date()
    declared = (working_hours.hours_on(tech.working_hours, local_day)
                if tech is not None else None)
    off_day = (tech is not None
               and working_hours.is_off_on(tech.working_hours, local_day))

    if off_day:
        basis = 'day_off'
        available_hours = 0.0
        over = True
        summary = f"{hours(nominal_hours)} of work on a day off"
    elif declared:
        basis = 'hours'
        start_clock, end_clock = declared
        available_hours = (
            (end_clock.hour * 60 + end_clock.minute)
            - (start_clock.hour * 60 + start_clock.minute)) / 60
        over = nominal_hours > available_hours
        summary = (f"{hours(nominal_hours)} of work booked into "
                   f"{hours(available_hours)} on the clock")
    else:
        basis = 'span'
        available_hours = None
        over = nominal > span
        summary = (f"{hours(nominal_hours)} of work booked into "
                   f"{hours(span_hours)}")

    return {
        'count': count,
        'nominal_hours': nominal_hours,
        'span_hours': span_hours,
        'available_hours': available_hours,
        'basis': basis,
        'over_committed': over,
        'summary': summary,
    }
