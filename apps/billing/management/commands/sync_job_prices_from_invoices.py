"""
Back-fill job prices from invoice line items.

The invoice is what the customer was actually charged, so it is the source
of truth when a Repair/Replacement's cost has drifted from its invoiced
amount (the pre-fix line-item editor updated the invoice without writing
back to the job — the drift audit_remediation_data measures).

Dry run by default; pass --apply to write. Mirrors the write-back semantics
of the owner invoice line-item editor (apps/billing/views.py
update_invoice_line_item): cost = invoiced per-unit amount, cost_override
stored pre-account-discount so a future save() re-derives the same cost.

    python manage.py sync_job_prices_from_invoices                     # report all drift
    python manage.py sync_job_prices_from_invoices --customer penske   # one customer
    python manage.py sync_job_prices_from_invoices --invoice RS-0042   # one invoice
    python manage.py sync_job_prices_from_invoices --customer penske --apply
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "Back-fill Repair/Replacement cost from invoiced amounts (dry run unless --apply)"

    def add_arguments(self, parser):
        parser.add_argument('--customer', help='Only customers whose name contains this (case-insensitive)')
        parser.add_argument('--invoice', help='Only this invoice number (case-insensitive exact match)')
        parser.add_argument('--apply', action='store_true', help='Write changes (default is dry run)')

    def handle(self, *args, **options):
        from apps.billing.models import InvoiceLineItem

        # Invoice.objects excludes soft-deleted invoices; exclude cancelled
        # ones too — a voided invoice is not a price the customer pays.
        items = (
            InvoiceLineItem.objects
            .filter(Q(repair__isnull=False) | Q(replacement__isnull=False))
            .filter(invoice__deleted_at__isnull=True)
            .exclude(invoice__status='CANCELLED')
            .select_related('invoice', 'repair__customer', 'replacement__customer')
            .order_by('invoice__invoice_date', 'invoice__id')
        )
        if options['customer']:
            items = items.filter(
                Q(repair__customer__name__icontains=options['customer'])
                | Q(replacement__customer__name__icontains=options['customer'])
            )
        if options['invoice']:
            items = items.filter(invoice__invoice_number__iexact=options['invoice'])

        # One job can only carry one price: if it appears on several live
        # invoices, the LAST invoice wins (same as re-editing the line item),
        # but flag it so a human can double-check.
        by_service = {}
        for li in items:
            service = li.repair or li.replacement
            key = (type(service).__name__, service.pk)
            if key in by_service:
                self.stdout.write(self.style.WARNING(
                    f"  note: {key[0]} #{service.pk} appears on multiple invoices "
                    f"({by_service[key].invoice.invoice_number} and {li.invoice.invoice_number}); "
                    f"using {li.invoice.invoice_number}"
                ))
            by_service[key] = li

        from apps.billing.services.invoice_sync import tax_fields_for_line

        drifted, synced = [], 0
        for (model_name, pk), li in sorted(by_service.items()):
            if not li.quantity:
                continue
            service = li.repair or li.replacement
            per_unit = (Decimal(li.amount) / li.quantity).quantize(Decimal('0.01'))
            # Tax drift: the write-back used to skip tax recalc, so a job can
            # match its invoiced price yet keep tax computed from its old
            # cost. Expected tax comes from the invoice's own rate — jobs on
            # a no-tax invoice stay at zero tax, whatever the shop's current
            # tax settings are.
            tax_fields = tax_fields_for_line(li, per_unit)
            tax_stale = (
                service.tax_rate != tax_fields['tax_rate']
                or service.tax_amount != tax_fields['tax_amount']
            )
            if service.cost == per_unit and not tax_stale:
                continue
            drifted.append((model_name, service, li, per_unit, tax_fields))
            detail = f"job cost {service.cost} -> invoiced {per_unit}"
            if tax_stale:
                detail += f", tax {service.tax_amount} -> {tax_fields['tax_amount']}"
            self.stdout.write(
                f"  {model_name} #{pk} ({service.customer.name}, unit {service.unit_number or '-'}): "
                f"{detail} [invoice {li.invoice.invoice_number}]"
            )

        if not drifted:
            self.stdout.write(self.style.SUCCESS("No drift found — jobs match their invoices."))
            return

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                f"\nDry run: {len(drifted)} job(s) out of sync. Re-run with --apply to fix."
            ))
            return

        for model_name, service, li, per_unit, tax_fields in drifted:
            override = per_unit
            pct = service.customer.get_effective_discount_percentage() if service.customer else 0
            if pct and 0 < pct < 100:
                override = (per_unit * Decimal('100') / (Decimal('100') - pct)).quantize(Decimal('0.01'))
            # queryset .update() skips save() side effects (hooks), exactly
            # like the line-item editor's write-back — so tax fields are
            # written explicitly alongside the cost.
            type(service).objects.filter(pk=service.pk).update(
                cost=per_unit,
                cost_override=override,
                override_reason=f'Priced on invoice {li.invoice.invoice_number}',
                **tax_fields,
            )
            synced += 1

        self.stdout.write(self.style.SUCCESS(f"\nSynced {synced} job(s) to their invoiced price."))
