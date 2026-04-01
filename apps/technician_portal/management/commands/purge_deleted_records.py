"""
Management command: purge_deleted_records

Hard-deletes Repair and Invoice records that were soft-deleted more than
--days days ago (default: 30). Handles the PROTECT FK constraint by deleting
InvoiceLineItems first, then Invoices, then Repairs.

**Safety rule (CODE-258):** Repairs that are still referenced by line items on
active (non-soft-deleted) invoices are EXCLUDED from purging.  The previous
implementation deleted those line items to bypass the PROTECT constraint, which
corrupted the active invoice's financial data — line items would vanish from a
SENT or PAID invoice, breaking the total/subtotal relationship and audit trail.

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
        invoice_ids = list(old_invoices.values_list('id', flat=True))

        # --- Repairs to purge ---
        # Start with all soft-deleted repairs past the cutoff.
        old_repairs_qs = Repair.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        repair_ids_candidate = list(old_repairs_qs.values_list('id', flat=True))

        # Exclude repairs still referenced by line items on ACTIVE invoices
        # (i.e. invoices that are NOT in the purge set).  Deleting those line
        # items would corrupt the active invoice's financial data — the line
        # items would vanish from a SENT or PAID invoice, breaking the
        # total/subtotal relationship and audit trail.  (CODE-258)
        #
        # These repairs will be purged in a future run once their parent
        # invoice is also soft-deleted and aged past the cutoff.
        blocked_repair_ids = set()
        if repair_ids_candidate:
            blocked_repair_ids = set(
                InvoiceLineItem.objects
                .filter(repair_id__in=repair_ids_candidate)
                .exclude(invoice_id__in=invoice_ids)  # not being purged
                .exclude(invoice__deleted_at__isnull=False)  # not soft-deleted
                .values_list('repair_id', flat=True)
                .distinct()
            )

        safe_repair_ids = [rid for rid in repair_ids_candidate if rid not in blocked_repair_ids]
        repair_count = len(safe_repair_ids)
        skipped_count = len(blocked_repair_ids)

        # --- Line items to purge ---
        # Only delete line items on invoices being purged, PLUS line items on
        # soft-deleted invoices that reference safe-to-purge repairs.  Never
        # touch line items on active invoices.
        line_items_to_delete = InvoiceLineItem.objects.filter(
            Q(invoice_id__in=invoice_ids) | Q(repair_id__in=safe_repair_ids, invoice__deleted_at__isnull=False)
        )
        line_item_count = line_items_to_delete.count()

        self.stdout.write(f"\n{'DRY RUN — ' if not apply else ''}Purge cutoff: {cutoff.strftime('%Y-%m-%d %H:%M UTC')}")
        self.stdout.write(f"  Invoices to purge:     {invoice_count}")
        self.stdout.write(f"  Line items to purge:   {line_item_count}")
        self.stdout.write(f"  Repairs to purge:      {repair_count}")
        if skipped_count:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {skipped_count} repair(s) skipped — still referenced by active invoices. "
                f"They will be purged once the invoice is also soft-deleted and aged."
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
            # 1. Delete InvoiceLineItems on purged invoices + soft-deleted invoices
            #    referencing purged repairs (PROTECT constraint on both FKs).
            deleted_li, _ = InvoiceLineItem.objects.filter(
                Q(invoice_id__in=invoice_ids) | Q(repair_id__in=safe_repair_ids, invoice__deleted_at__isnull=False)
            ).delete()

            # 2. Delete Invoices
            deleted_inv, _ = old_invoices.delete()

            # 3. Delete Repairs (only the safe ones — active-invoice-referenced ones are excluded)
            deleted_rep, _ = Repair.all_objects.filter(id__in=safe_repair_ids).delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nPurged: {deleted_li} line items, {deleted_inv} invoices, {deleted_rep} repairs."
        ))
        if skipped_count:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_count} repair(s) retained — referenced by active invoices."
            ))
