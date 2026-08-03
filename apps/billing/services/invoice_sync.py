"""
Job → invoice price synchronization.

The invoice → job half lives in the owner line-item editor
(apps/billing/views.py update_invoice_line_item): editing a job-linked line
writes the new price back to the Repair/Replacement. This module is the
other direction: when a job's price changes, its line on any live invoice
follows, so the two sides can never drift apart again
(sync_job_prices_from_invoices measures and back-fills historical drift).

Paid and cancelled invoices are financial history and are never touched;
RepairForm locks the job's price fields instead (see forms.py).
"""

from decimal import Decimal


def recalculate_invoice_totals(invoice):
    """Recompute subtotal/discount/tax/total from the invoice's line items.

    Tax applies to taxable lines only (no_tax jobs, exempt sales); the
    total includes every line.
    """
    all_items = invoice.line_items.all()
    invoice.subtotal = sum((item.unit_price * item.quantity for item in all_items), Decimal('0.00'))
    invoice.discount = sum((item.discount for item in all_items), Decimal('0.00'))
    after_discount = invoice.subtotal - invoice.discount
    if invoice.tax_rate and invoice.tax_rate > 0:
        taxable = sum((item.amount for item in all_items if item.taxable), Decimal('0.00'))
        invoice.tax_amount = (taxable * invoice.tax_rate / Decimal('100')).quantize(Decimal('0.01'))
    else:
        invoice.tax_amount = Decimal('0.00')
    invoice.total = after_discount + invoice.tax_amount
    invoice.save(update_fields=['subtotal', 'discount', 'tax_amount', 'total'])


def sync_lines_for_service(service):
    """Update the service's line on every live invoice to match service.cost.

    A line already charging service.cost is left untouched (including its
    unit_price/discount presentation); a stale line is rewritten to the
    simple form the line-item editor uses: unit_price = the price, no
    discount. Returns the number of lines updated.
    """
    from apps.billing.models import InvoiceLineItem

    if service.pk is None or service.cost is None:
        return 0

    field = 'repair' if type(service).__name__ == 'Repair' else 'replacement'
    lines = (
        InvoiceLineItem.objects
        .filter(**{field: service})
        .filter(invoice__deleted_at__isnull=True)
        .exclude(invoice__status__in=('PAID', 'CANCELLED'))
        .select_related('invoice')
    )

    synced = 0
    for line in lines:
        quantity = line.quantity or 1
        per_unit = (Decimal(line.amount) / quantity).quantize(Decimal('0.01'))
        if per_unit == service.cost:
            continue
        line.unit_price = service.cost
        line.discount = Decimal('0.00')
        line.amount = service.cost * quantity
        line.save(update_fields=['unit_price', 'discount', 'amount'])
        recalculate_invoice_totals(line.invoice)
        synced += 1
    return synced


def paid_invoice_number_for_service(service):
    """Invoice number of a PAID invoice this job is billed on, or None.

    Used to lock the job's price fields: once the customer has paid,
    changing the job's price would silently disagree with the money that
    actually changed hands.
    """
    from apps.billing.models import InvoiceLineItem

    if service.pk is None:
        return None
    field = 'repair' if type(service).__name__ == 'Repair' else 'replacement'
    line = (
        InvoiceLineItem.objects
        .filter(**{field: service})
        .filter(invoice__deleted_at__isnull=True, invoice__status='PAID')
        .select_related('invoice')
        .first()
    )
    return line.invoice.invoice_number if line else None
