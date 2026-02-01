"""
Billing template tags — invoice/payment status lookups for repair detail pages.

Usage:
    {% load billing_tags %}
    {% get_invoice_status repair as inv_status %}
    {% if inv_status %}
        {{ inv_status.status }}  — PAID, SENT, OVERDUE, etc.
        {{ inv_status.invoice_number }}
        {{ inv_status.total }}
        {{ inv_status.amount_due }}
        {{ inv_status.stripe_url }}
    {% endif %}

Author: Amelia (Clawdbot AI)
"""

from django import template

register = template.Library()


@register.simple_tag
def get_invoice_status(repair):
    """
    Look up the invoice status for a repair.
    Returns a dict with invoice info, or None if not invoiced.
    """
    try:
        from apps.billing.models import InvoiceLineItem

        line_item = InvoiceLineItem.objects.filter(
            repair=repair,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'],
        ).select_related('invoice').first()

        if not line_item:
            return None

        invoice = line_item.invoice
        return {
            'invoice_id': invoice.id,
            'status': invoice.status,
            'invoice_number': invoice.invoice_number,
            'total': invoice.total,
            'amount_paid': invoice.amount_paid,
            'amount_due': invoice.amount_due,
            'due_date': invoice.due_date,
            'stripe_url': invoice.stripe_hosted_url or '',
            'payment_terms': invoice.get_payment_terms_display(),
        }
    except Exception:
        return None
