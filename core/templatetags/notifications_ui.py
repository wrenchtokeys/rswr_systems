"""Shared presentation layer for the in-app notification surfaces.

The bell dropdown and both notification-history pages render the same row.
Everything a row needs that is *not* a model field — its icon, its icon tint,
its short category label, and its two time formats — is decided here so the
three surfaces cannot drift. Load with {% load notifications_ui %}.

Mirrors the ui.py / email_ui.py pattern: one tone table, no per-template
colour decisions.
"""
from django import template
from django.utils import timezone

register = template.Library()

# Notification.CATEGORY_CHOICES → (icon key, tint classes, short label).
#
# The tints are the same six-colour ladder email_ui.py uses for status pills, so
# an approval reads amber in the bell and amber in the email. The short label is
# what the history page's category column shows: CATEGORY_CHOICES' own labels
# ("Repair Status Change", "Assignment/Reassignment") are preference-screen
# copy — too long for a column and phrased for a settings form, not a list.
CATEGORY_STYLES = {
    'repair_status': ('wrench', 'bg-indigo-100 text-indigo-800', 'Job'),
    'assignment':    ('clipboard', 'bg-blue-100 text-blue-800', 'Assignment'),
    'approval':      ('clock', 'bg-amber-100 text-amber-800', 'Approval'),
    'reward':        ('gift', 'bg-green-100 text-green-800', 'Reward'),
    'system':        ('info', 'bg-gray-100 text-gray-700', 'System'),
}

_DEFAULT_STYLE = ('info', 'bg-gray-100 text-gray-700', 'Notification')


def _style(category):
    return CATEGORY_STYLES.get(category, _DEFAULT_STYLE)


@register.filter
def notification_icon(category):
    """Icon key for a category — resolves to an inline SVG in the row partial."""
    return _style(category)[0]


@register.filter
def notification_tint(category):
    """Tailwind background+foreground classes for the row's icon tile."""
    return _style(category)[1]


@register.filter
def notification_category_label(category):
    """Short column label ("Approval"), not the preference-screen label."""
    return _style(category)[2]


@register.filter
def short_age(value):
    """Compact age for the bell's right column: "Just now", "9m", "1h", "3d".

    Django's `timesince` renders "0 minutes" for anything under a minute, so
    the bell has been showing "0 minutes ago" on the notification a tech is
    most likely to be looking at — the one that just arrived.
    """
    if not value:
        return ''
    delta = timezone.now() - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return 'Just now'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m'
    hours = minutes // 60
    if hours < 24:
        return f'{hours}h'
    days = hours // 24
    if days < 7:
        return f'{days}d'
    weeks = days // 7
    if weeks < 52:
        return f'{weeks}w'
    return f'{days // 365}y'


@register.filter
def notification_clock(value):
    """Absolute time for the history page: "9:14 AM".

    The history page is a record, not a feed. A row that says "3 days ago"
    cannot be matched against a customer saying "you called me Tuesday
    morning"; the day group header carries the date and this carries the time.
    """
    if not value:
        return ''
    return timezone.localtime(value).strftime('%-I:%M %p')


@register.filter
def notification_day(value):
    """Day-group heading: "Today", "Yesterday", "Monday", "August 4, 2026".

    A weekday name only carries inside the last week — past that it stops being
    a date and starts being ambiguous, so it becomes an explicit one.
    """
    if not value:
        return ''
    local = timezone.localtime(value).date()
    today = timezone.localdate()
    delta = (today - local).days
    if delta == 0:
        return 'Today'
    if delta == 1:
        return 'Yesterday'
    if 0 < delta < 7:
        return timezone.localtime(value).strftime('%A')
    return timezone.localtime(value).strftime('%B %-d, %Y')
