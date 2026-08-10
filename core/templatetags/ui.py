"""Shared UI component template tags.

Single source of truth for status badge and service-type chip styling —
see docs/development/UI_DESIGN_GUIDE.md. Load with {% load ui %}.
"""
from django import template

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
def status_badge(status, label=None, kind='service', variant='shop'):
    """Render a status pill.

    {% status_badge repair.queue_status %}
    {% status_badge invoice.status kind='invoice' %}
    {% status_badge repair.queue_status label=repair.get_queue_status_display %}
    {% status_badge repair.queue_status variant='customer' %}  — customer-facing labels
    """
    styles = INVOICE_STATUS_STYLES if kind == 'invoice' else SERVICE_STATUS_STYLES
    classes, default_label = styles.get(status, _DEFAULT_STYLE)
    if kind != 'invoice' and variant == 'customer':
        default_label = CUSTOMER_SERVICE_LABEL_OVERRIDES.get(status, default_label)
    return {
        'classes': classes,
        'label': label or default_label or (status or '').replace('_', ' ').title(),
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
