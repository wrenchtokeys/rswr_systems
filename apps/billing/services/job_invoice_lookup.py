"""
Which jobs already sit on a live invoice.

The Jobs list needs this for every row on the page and for the "Not
invoiced" filter; the detail pages ask it one job at a time. One definition
of "live" (not voided, not in the trash) so the list, the detail page and
the generators cannot disagree about whether a job has been ticketed.
"""

from apps.billing.models import InvoiceLineItem

# An invoice that still counts: a CANCELLED or soft-deleted one releases its
# jobs so they can be invoiced again.
LIVE_INVOICE_STATUSES = ('DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE')


def live_invoices_by_job(tenant):
    """Return ``(by_repair_id, by_replacement_id)``.

    Each maps a job id to ``{'id': invoice_id, 'number': invoice_number}``
    for the live invoice the job is a line on. Two queries, however many
    jobs the shop has.
    """
    rows = (
        InvoiceLineItem.objects.filter(
            invoice__tenant=tenant,
            invoice__status__in=LIVE_INVOICE_STATUSES,
            invoice__deleted_at__isnull=True,
        )
        .exclude(repair__isnull=True, replacement__isnull=True)
        .values_list('repair_id', 'replacement_id', 'invoice_id', 'invoice__invoice_number')
    )
    by_repair, by_replacement = {}, {}
    for repair_id, replacement_id, invoice_id, number in rows:
        ref = {'id': invoice_id, 'number': number}
        if repair_id:
            by_repair[repair_id] = ref
        elif replacement_id:
            by_replacement[replacement_id] = ref
    return by_repair, by_replacement


def needs_invoice(job, live_ref):
    """A finished job with no live invoice, unless the shop said to skip it."""
    return (
        job.queue_status == 'COMPLETED'
        and not getattr(job, 'skip_invoicing', False)
        and live_ref is None
    )
