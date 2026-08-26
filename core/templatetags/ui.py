"""Shared UI component template tags.

Single source of truth for status badge, service-type chip and icon markup —
see docs/development/UI_DESIGN_GUIDE.md. Load with {% load ui %}.
"""
import logging

from django import template
from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import mark_safe

from core.icons import resolve as resolve_icon

logger = logging.getLogger(__name__)

register = template.Library()

# GlassService.STATUS_CHOICES (shared by Repair and Replacement).
# Colors match the established list-page badge conventions.
SERVICE_STATUS_STYLES = {
    'REQUESTED': ('bg-yellow-200 text-yellow-900', 'Customer Requested'),
    'PENDING': ('bg-amber-100 text-amber-800', 'Approval Pending'),
    'APPROVED': ('bg-indigo-100 text-indigo-800', 'Approved'),
    'IN_PROGRESS': ('bg-blue-100 text-blue-800', 'In Progress'),
    'COMPLETED': ('bg-green-100 text-green-800', 'Completed'),
    'DENIED': ('bg-red-100 text-red-800', 'Denied by Customer'),
}

# Invoice.STATUS_CHOICES (apps/billing).
INVOICE_STATUS_STYLES = {
    'DRAFT': ('bg-gray-100 text-gray-800', 'Draft'),
    'SENT': ('bg-blue-100 text-blue-800', 'Sent'),
    'PAID': ('bg-green-100 text-green-800', 'Paid'),
    'PARTIAL': ('bg-yellow-100 text-yellow-800', 'Partially Paid'),
    'OVERDUE': ('bg-red-100 text-red-800', 'Overdue'),
    'CANCELLED': ('bg-gray-100 text-gray-800', 'Cancelled'),
}

_DEFAULT_STYLE = ('bg-gray-100 text-gray-800', None)

# Label overrides for customer-facing pages. The shop labels describe the queue
# from the shop's perspective ("Customer Requested"); customers reading their own
# jobs need the same statuses phrased from theirs.
CUSTOMER_SERVICE_LABEL_OVERRIDES = {
    'REQUESTED': 'Submitted',
    'PENDING': 'Needs Your Approval',
    'DENIED': 'Declined',
}


@register.inclusion_tag('components/status_badge.html')
def status_badge(status, label=None, kind='service', variant='shop', optimistic=False):
    """Render a status pill.

    {% status_badge repair.queue_status %}
    {% status_badge invoice.status kind='invoice' %}
    {% status_badge repair.queue_status label=repair.get_queue_status_display %}
    {% status_badge repair.queue_status variant='customer' %}  — customer-facing labels
    {% status_badge inv.status kind='invoice' optimistic=True %}  — see below

    `optimistic=True` marks the pill as the one static/js/optimistic.js
    repaints while a status change is in flight, and as the slot the success
    tick draws into (UI_MAGIC S11). Only list rows that carry
    `data-optimistic-row` need it; anywhere else it is inert markup.
    """
    styles = INVOICE_STATUS_STYLES if kind == 'invoice' else SERVICE_STATUS_STYLES
    classes, default_label = styles.get(status, _DEFAULT_STYLE)
    if kind != 'invoice' and variant == 'customer':
        default_label = CUSTOMER_SERVICE_LABEL_OVERRIDES.get(status, default_label)
    return {
        'classes': classes,
        'label': label or default_label or (status or '').replace('_', ' ').title(),
        'optimistic': optimistic,
    }


@register.inclusion_tag('components/service_type_chip.html')
def service_type_chip(service_type):
    """Render a REPAIR / REPLACEMENT type chip.

    {% service_type_chip 'REPAIR' %} or {% service_type_chip item.item_type %}
    Accepts 'REPAIR'/'REPLACEMENT' case-insensitively.
    """
    is_replacement = (service_type or '').upper() == 'REPLACEMENT'
    return {
        'label': 'Replacement' if is_replacement else 'Repair',
        'icon': 'fa-car' if is_replacement else 'fa-tools',
        'classes': 'bg-purple-100 text-purple-800' if is_replacement else 'bg-sky-100 text-sky-800',
    }


# The stroke-only frame every icon is drawn in. It is here rather than in each
# entry of core/icons.py so that a new icon cannot arrive with a different
# stroke weight — the one difference that makes a mixed icon set look broken.
# `focusable="false"` is for IE-era focus behaviour that Edge still inherits in
# some enterprise configurations; it costs nine bytes and removes a tab stop.
_SVG = (
    '<svg class="icon{extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'focusable="false" {a11y}>{body}</svg>'
)


@register.simple_tag
def icon(name, label=None, **attrs):
    """Render a line icon from `core.icons` (UI_MAGIC S13).

    {% icon 'check' %}
    {% icon 'trash' class="w-5 h-5 text-red-600" %}
    {% icon 'trash' label="Delete job" %}   — an icon that IS the button text
    {% icon item.status_icon %}             — dynamic names are fine

    Sized in `em`, so it is a drop-in for the `<i class="fas fa-…">` it
    replaces: it tracks the surrounding font-size and `text-lg` on the parent
    still works. Pass Tailwind sizing in `class` to override — utilities beat
    the `.icon` component rule.

    **Decorative by default.** An icon next to its own label is noise to a
    screen reader, so the default is `aria-hidden`. Pass `label` only when the
    icon is the only thing naming the control; then it announces as an image
    with that name.

    An unknown name is a template bug, not a data problem: it raises under
    DEBUG (so dev and the test suite catch it on the spot) and, in production,
    logs and renders an empty box of the right size rather than 500-ing a page
    over a typo in a decoration.
    """
    body = resolve_icon(name)
    if body is None:
        if settings.DEBUG:
            raise template.TemplateSyntaxError(
                f"{{% icon %}}: unknown icon {name!r}. Add it to core/icons.py "
                f"(or alias it there) — see UI_MAGIC_SESSIONS.md S13."
            )
        logger.warning("Unknown icon %r requested by {%% icon %%}", name)
        body = ''

    extra = attrs.get('class') or ''
    a11y = (
        f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    )
    return mark_safe(_SVG.format(
        extra=f' {escape(extra)}' if extra else '',
        a11y=a11y,
        body=body,
    ))
