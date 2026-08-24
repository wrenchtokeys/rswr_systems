"""Technician working hours — the shape, and how to read it (FIELD_OPS S8).

``Technician.working_hours`` has existed since migration ``0007`` as a
schema-less ``JSONField(default=dict)`` with no reader and no writer anywhere
in the codebase: every row in every tenant holds ``{}``. This module gives it
meaning without a migration, and the first rule is the one that makes that
deploy safe:

    ``{}`` means **undeclared** — never "never works".

A technician with no hours on file is available whenever, and every surface
that consults this module must then say nothing about them at all. Getting
that backwards would put a warning on every job in every shop on day one.

The stored shape is the one the Django admin fieldset has documented — and
been the only possible writer of — since ``0007``::

    {"monday": ["08:00", "17:00"], "tuesday": null, ...}

A day that is absent, ``null`` or empty is a day off. Times are **wall clock**
in the shop's timezone (there is still no per-tenant ``TIME_ZONE``), so they
are stored as strings and only ever compared after ``timezone.localtime()``.
Never store a UTC hour here: the app's one pre-existing "business hours"
setting — ``ReviewConfig.business_hours_start/end`` — compares UTC hours by
mistake, which is why review emails go out at 4 AM local.

Reading is **total**. Unknown keys, wrong types and unparseable clock strings
are dropped, and a record with no parseable day at all reads as *undeclared*
rather than as "works no days" — the admin box is a raw JSON textarea in
production, so nonsense is reachable and must never 500 a dispatch board.
"""

from datetime import time

# Index matches ``date.weekday()`` — Monday is 0. The keys are the admin's.
WEEKDAY_KEYS = (
    'monday', 'tuesday', 'wednesday', 'thursday',
    'friday', 'saturday', 'sunday',
)
WEEKDAY_LABELS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
WEEKDAY_FULL = (
    'Monday', 'Tuesday', 'Wednesday', 'Thursday',
    'Friday', 'Saturday', 'Sunday',
)

# What the editor pre-fills for someone who has never had hours set. Nothing
# in the app assumes it — it is a starting point for a form, not a fallback
# for a missing record, because a missing record means "available whenever".
DEFAULT_WORKING_HOURS = {
    'monday': ['08:00', '17:00'],
    'tuesday': ['08:00', '17:00'],
    'wednesday': ['08:00', '17:00'],
    'thursday': ['08:00', '17:00'],
    'friday': ['08:00', '17:00'],
}


def parse_clock(value):
    """``"9:00"`` / ``"08:00"`` / ``"17:00:00"`` → ``time``; None if unusable.

    Deliberately forgiving about the single-digit hour: that is the form the
    admin's own help text shows, so any hand-entered row in production spells
    it that way.
    """
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        return None
    parts = value.strip().split(':')
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def read(raw):
    """``{weekday_index: (start, end)}`` for the days actually worked.

    Returns ``{}`` for an undeclared record — which includes garbage. Days off
    are simply absent from the result, so ``read()`` alone cannot tell "off on
    Tuesday" from "no hours on file"; ask :func:`is_declared` first, or use
    the helpers below, which do.
    """
    if not isinstance(raw, dict):
        return {}

    days = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            index = WEEKDAY_KEYS.index(key.strip().lower())
        except ValueError:
            continue
        if isinstance(value, dict):
            value = [value.get('start'), value.get('end')]
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue  # absent / null / [] / nonsense — the day is simply off
        start = parse_clock(value[0])
        end = parse_clock(value[1])
        if start is None or end is None or end <= start:
            continue
        days[index] = (start, end)
    return days


def is_declared(raw):
    """True when this technician has usable hours on file."""
    return bool(read(raw))


def hours_on(raw, day):
    """``(start, end)`` for a ``date``, or None for a day off / undeclared."""
    return read(raw).get(day.weekday())


def is_off_on(raw, day):
    """True only when hours ARE declared and this day is not one of them.

    Undeclared returns False: nobody is "off" on a day the shop never said
    anything about.
    """
    days = read(raw)
    return bool(days) and day.weekday() not in days


def covers(raw, start, end):
    """Do declared hours contain this booked window?

    ``start`` / ``end`` are aware datetimes. Returns None when there is
    nothing on file — the caller must treat that as "no opinion" and stay
    silent, not as a miss.
    """
    from django.utils import timezone

    days = read(raw)
    if not days:
        return None

    local_start = timezone.localtime(start)
    local_end = timezone.localtime(end)
    window = days.get(local_start.date().weekday())
    if window is None:
        return False
    if local_end.date() != local_start.date():
        # A booking that runs past midnight cannot sit inside one day's hours.
        return False
    return window[0] <= local_start.time() and local_end.time() <= window[1]


def format_clock(value):
    """``time(8, 0)`` → ``"8:00 AM"`` — how the product writes times."""
    hour = value.hour % 12 or 12
    meridiem = 'AM' if value.hour < 12 else 'PM'
    return f"{hour}:{value.minute:02d} {meridiem}"


def describe_day(raw, day):
    """One day, for a row: ``"8:00 AM – 5:00 PM"``, ``"Off"``, or ``""``."""
    if not is_declared(raw):
        return ''
    window = hours_on(raw, day)
    if window is None:
        return 'Off'
    return f"{format_clock(window[0])} – {format_clock(window[1])}"


def summary(raw):
    """The whole week in one line: ``"Mon–Fri 8:00 AM – 5:00 PM"``.

    Consecutive days sharing the same window collapse into a range, because
    the answer a shop owner is scanning for is "the usual, or not".
    Undeclared returns ``''`` so callers can render their own empty state.
    """
    days = read(raw)
    if not days:
        return ''

    runs = []
    for index in sorted(days):
        window = days[index]
        if runs and runs[-1][1] == index - 1 and runs[-1][2] == window:
            runs[-1][1] = index
        else:
            runs.append([index, index, window])

    parts = []
    for first, last, (start, end) in runs:
        if first == last:
            label = WEEKDAY_LABELS[first]
        elif last == first + 1:
            label = f"{WEEKDAY_LABELS[first]}, {WEEKDAY_LABELS[last]}"
        else:
            label = f"{WEEKDAY_LABELS[first]}–{WEEKDAY_LABELS[last]}"
        parts.append(f"{label} {format_clock(start)} – {format_clock(end)}")
    return ' · '.join(parts)


def to_storage(days):
    """``{weekday_index: (start, end)}`` → the stored JSON dict.

    Days off are written as explicit ``null`` rather than omitted so the row
    reads the same way in the admin box as it does in the editor.
    """
    stored = {}
    for index, key in enumerate(WEEKDAY_KEYS):
        window = days.get(index)
        if window is None:
            stored[key] = None
        else:
            start, end = window
            stored[key] = [f"{start.hour:02d}:{start.minute:02d}",
                           f"{end.hour:02d}:{end.minute:02d}"]
    return stored


def editor_rows(raw):
    """What the edit form renders: one row per day, pre-filled.

    A technician with nothing on file gets :data:`DEFAULT_WORKING_HOURS`
    shown but *unchecked* — the shop should have to say "yes, these are the
    hours", not inherit them by opening a form.
    """
    days = read(raw)
    declared = bool(days)
    defaults = read(DEFAULT_WORKING_HOURS)
    rows = []
    for index, key in enumerate(WEEKDAY_KEYS):
        window = days.get(index) or defaults.get(index) or (time(8, 0), time(17, 0))
        rows.append({
            'key': key,
            'label': WEEKDAY_FULL[index],
            'short': WEEKDAY_LABELS[index],
            'works': index in days,
            'start': f"{window[0].hour:02d}:{window[0].minute:02d}",
            'end': f"{window[1].hour:02d}:{window[1].minute:02d}",
        })
    return {'rows': rows, 'declared': declared}
