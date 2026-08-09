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


def tax_fields_for_service(service, cost):
    """Recompute a job's tax fields for a new cost, mirroring Repair/Replacement.save().

    The invoice→job write-back paths (owner line-item editor,
    sync_job_prices_from_invoices) update via queryset .update() to skip
    save() side effects — but that also skipped the tax recalculation inside
    save(), leaving tax_rate/tax_amount frozen at the job's original price
    (e.g. a $50 repair edited down to $1 kept its $4.88 tax). Include this
    dict in the .update() so the tax fields follow the cost.

    Returns {'tax_rate': ..., 'tax_amount': ...}, or {} if tax can't be
    computed (billing config unavailable) — same keep-existing fallback as
    save().
    """
    if service.no_tax or not cost or cost <= 0:
        return {'tax_rate': Decimal('0.000'), 'tax_amount': Decimal('0.00')}
    try:
        from apps.billing.services.tax_service import TaxService
        tax_result = TaxService(tenant=service.tenant).calculate_tax(
            subtotal=cost, customer=service.customer
        )
        return {'tax_rate': tax_result['rate'], 'tax_amount': tax_result['amount']}
    except Exception:
        return {}


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


def create_charge_lines(invoice, service):
    """Create free-form invoice lines for a job's extra charges (JobCharge).

    The lines deliberately carry NO repair/replacement FK: sync_lines_for_service
    rewrites job-linked lines to service.cost, which would corrupt a charge
    line. Free-form lines are ignored by the sync and editable/deletable
    through the invoice line-item endpoints. Returns the created lines.
    """
    from apps.billing.models import InvoiceLineItem

    customer = invoice.customer
    lines = []
    for charge in service.extra_charges.all():
        taxable = charge.taxable and not (customer and customer.tax_exempt)
        repair_date = getattr(service, 'repair_date', None)
        lines.append(InvoiceLineItem.objects.create(
            invoice=invoice,
            description=charge.description,
            quantity=1,
            unit_price=charge.amount,
            discount=Decimal('0.00'),
            amount=charge.amount,
            repair_date=repair_date.date() if repair_date else None,
            unit_number=getattr(service, 'unit_number', '') or '',
            taxable=taxable,
        ))
    return lines


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


def live_invoice_number_for_service(service):
    """Invoice number of any live (non-cancelled) invoice this job is on, or None.

    Used to lock the job's extra-charge editor: once invoiced, charges are
    managed on the invoice itself (Add Line Item) so the ticket and the
    invoice can't quietly disagree.
    """
    from apps.billing.models import InvoiceLineItem

    if service.pk is None:
        return None
    field = 'repair' if type(service).__name__ == 'Repair' else 'replacement'
    line = (
        InvoiceLineItem.objects
        .filter(**{field: service})
        .filter(invoice__deleted_at__isnull=True)
        .exclude(invoice__status='CANCELLED')
        .select_related('invoice')
        .first()
    )
    return line.invoice.invoice_number if line else None


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
