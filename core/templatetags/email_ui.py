"""Template helpers for the email chassis (templates/emails/).

Load with {% load email_ui %}. These exist so an email badge and the badge
on the job page cannot drift: the tone → colour table below is the same set
of pairs as SERVICE_STATUS_STYLES / INVOICE_STATUS_STYLES in
core/templatetags/ui.py, expressed as hex because email has no Tailwind.

ui.py stays the source of truth for what colour a status IS. This module
only translates that decision into inline styles, and maps a status onto a
tone so a template never hardcodes one.
"""
from decimal import Decimal, InvalidOperation

from django import template
from django.utils import formats

register = template.Library()

# tone -> (background, foreground). Same pairs as ui.py's Tailwind classes:
# green = green-100/green-800, amber = amber-100/amber-800, and so on.
PILL_TONES = {
    'green': ('#dcfce7', '#166534'),
    'amber': ('#fef3c7', '#92400e'),
    'blue': ('#dbeafe', '#1e40af'),
    'indigo': ('#e0e7ff', '#3730a3'),
    'red': ('#fee2e2', '#991b1b'),
    'yellow': ('#fef08a', '#713f12'),
    'yellow_soft': ('#fef9c3', '#854d0e'),
    'gray': ('#f3f4f6', '#1f2937'),
}
_DEFAULT_TONE = 'gray'

# GlassService.STATUS_CHOICES -> tone. Mirrors SERVICE_STATUS_STYLES.
SERVICE_STATUS_TONES = {
    'REQUESTED': 'yellow',
    'PENDING': 'amber',
    'APPROVED': 'indigo',
    'IN_PROGRESS': 'blue',
    'COMPLETED': 'green',
    'DENIED': 'red',
}

# Invoice.STATUS_CHOICES -> tone. Mirrors INVOICE_STATUS_STYLES.
INVOICE_STATUS_TONES = {
    'DRAFT': 'gray',
    'SENT': 'blue',
    'PAID': 'green',
    'PARTIAL': 'yellow_soft',
    'OVERDUE': 'red',
    'CANCELLED': 'gray',
}

# Service-type chip -> (background, foreground). Mirrors service_type_chip.
TYPE_CHIPS = {
    'REPAIR': ('#e0f2fe', '#075985'),
    'REPLACEMENT': ('#f3e8ff', '#6b21a8'),
}


@register.filter
def pill_bg(tone):
    """Background hex for a pill tone."""
    return PILL_TONES.get(tone or _DEFAULT_TONE, PILL_TONES[_DEFAULT_TONE])[0]


@register.filter
def pill_fg(tone):
    """Foreground hex for a pill tone."""
    return PILL_TONES.get(tone or _DEFAULT_TONE, PILL_TONES[_DEFAULT_TONE])[1]


@register.filter
def status_tone(status, kind='service'):
    """Tone for a job or invoice status.

    {% include "emails/components/pill.html" with label=job.get_queue_status_display tone=job.queue_status|status_tone %}
    {% include "emails/components/pill.html" with label="Paid" tone=invoice.status|status_tone:"invoice" %}
    """
    table = INVOICE_STATUS_TONES if kind == 'invoice' else SERVICE_STATUS_TONES
    return table.get(status, _DEFAULT_TONE)


@register.filter
def type_chip_bg(service_type):
    """Background hex for a REPAIR / REPLACEMENT chip."""
    return TYPE_CHIPS.get((service_type or '').upper(), TYPE_CHIPS['REPAIR'])[0]


@register.filter
def type_chip_fg(service_type):
    """Foreground hex for a REPAIR / REPLACEMENT chip."""
    return TYPE_CHIPS.get((service_type or '').upper(), TYPE_CHIPS['REPAIR'])[1]


@register.filter
def money(value):
    """'$84.75' — or '' when there is nothing to show.

    Email templates cannot build "$" + a formatted number inside an
    {% include %} argument, and the old ones papered over that by writing
    a literal '$' in front of {{ repair.total_cost }} — a field that does
    not exist on Repair, so every one of them rendered a bare '$'. Return
    '' for None so a caller's {% if %} drops the row instead.
    """
    if value is None or value == '':
        return ''
    try:
        return f"${Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return ''


@register.filter
def warranty_text(job):
    """'Lifetime' / 'Through March 4, 2027' / '' for a job's warranty.

    A policy with no expiry is a lifetime warranty (see
    GlassService.has_warranty). '' when there is no live warranty, so the
    row drops rather than claiming one that was voided or has run out.
    """
    try:
        if not job.has_warranty:
            return ''
    except Exception:
        return ''
    expires = getattr(job, 'warranty_expires_at', None)
    if expires is None:
        return 'Lifetime'
    return f"Through {formats.date_format(expires, 'F j, Y')}"


@register.filter
def pad_label(value, width=14):
    """Left-align a label in a fixed column for plain-text emails.

    The plain-text half lines values up with two-space indentation and a
    fixed label column, which is what replaced the rows of '=' rulers. A
    label longer than the column still renders, just wider.
    """
    text = str(value or '')
    try:
        width = int(width)
    except (TypeError, ValueError):
        width = 14
    return text.ljust(width)
