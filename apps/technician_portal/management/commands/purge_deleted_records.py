"""
Management command: purge_deleted_records

Hard-deletes Repair and Invoice records that were soft-deleted more than
--days days ago (default: 30). Handles the PROTECT FK constraint by deleting
InvoiceLineItems first, then Invoices, then Repairs.

Usage:
    python manage.py purge_deleted_records                  # dry-run by default
    python manage.py purge_deleted_records --apply          # execute deletions
    python manage.py purge_deleted_records --days 60        # older than 60 days
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Q


class Command(BaseCommand):
    help = "Hard-delete soft-deleted repairs and invoices older than --days (default 30). Dry-run unless --apply passed."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Hard-delete records soft-deleted more than this many days ago (default: 30)',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually perform the deletions. Without this flag the command only reports what would be deleted.',
        )

    def handle(self, *args, **options):
        days = options['days']
        apply = options['apply']
        cutoff = timezone.now() - timezone.timedelta(days=days)

        from apps.billing.models import Invoice
        from apps.technician_portal.models import Repair
        from apps.billing.models import InvoiceLineItem

        # --- Invoices to purge ---
        old_invoices = Invoice.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        invoice_count = old_invoices.count()

        # --- Repairs to purge ---
        old_repairs = Repair.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        repair_count = old_repairs.count()

        # --- Line items to purge ---
        # Must delete ALL InvoiceLineItems referencing repairs OR invoices being
        # purged — not just those on soft-deleted invoices.  InvoiceLineItem has
        # on_delete=PROTECT on both its repair and invoice FKs.  A soft-deleted
        # repair can still be referenced by a line item on an *active* invoice
        # (e.g. repair was soft-deleted after the invoice was sent/paid).
        # Failing to clear those line items causes ProtectedError when step 3
        # tries to hard-delete the repairs, which rolls back the entire
        # transaction and purges nothing.  (CODE-234)
        invoice_ids = list(old_invoices.values_list('id', flat=True))
        repair_ids = list(old_repairs.values_list('id', flat=True))
        line_items_to_delete = InvoiceLineItem.objects.filter(
            Q(invoice_id__in=invoice_ids) | Q(repair_id__in=repair_ids)
        )
        line_item_count = line_items_to_delete.count()

        # Count repairs that will be skipped (referenced by active invoices)
        repairs_with_active_invoice_refs = 0
        if repair_ids:
            repairs_with_active_invoice_refs = (
                InvoiceLineItem.objects
                .filter(repair_id__in=repair_ids)
                .exclude(invoice_id__in=invoice_ids)
                .values_list('repair_id', flat=True)
                .distinct()
                .count()
            )

        self.stdout.write(f"\n{'DRY RUN — ' if not apply else ''}Purge cutoff: {cutoff.strftime('%Y-%m-%d %H:%M UTC')}")
        self.stdout.write(f"  Invoices to purge:     {invoice_count}")
        self.stdout.write(f"  Line items to purge:   {line_item_count}")
        self.stdout.write(f"  Repairs to purge:      {repair_count}")
        if repairs_with_active_invoice_refs:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {repairs_with_active_invoice_refs} repair(s) still referenced by active invoices — "
                f"their line item links will be cleared to allow purge."
            ))

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDry run complete. Pass --apply to perform actual deletions."
            ))
            return

        if invoice_count == 0 and repair_count == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to purge."))
            return

        with transaction.atomic():
            # 1. Delete ALL InvoiceLineItems linked to purged invoices OR purged
            #    repairs (PROTECT constraint on both FKs).
            deleted_li, _ = InvoiceLineItem.objects.filter(
                Q(invoice_id__in=invoice_ids) | Q(repair_id__in=repair_ids)
            ).delete()

            # 2. Delete Invoices
            deleted_inv, _ = old_invoices.delete()

            # 3. Delete Repairs
            deleted_rep, _ = old_repairs.delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nPurged: {deleted_li} line items, {deleted_inv} invoices, {deleted_rep} repairs."
        ))
