"""
Management command: purge_deleted_records

Hard-deletes records that were soft-deleted more than --days days ago
(default: 30): Invoices (payments included), Repairs, Replacements,
Customers, and removed portal user accounts.

Deletion order matters because of PROTECT foreign keys:
    payments → line items → invoices → repairs/replacements
    → portal users → customers

**Safety rule (CODE-258):** Repairs/replacements that are still referenced by
line items on active (non-soft-deleted) invoices are EXCLUDED from purging.
Deleting those line items would corrupt the active invoice's financial data —
line items would vanish from a SENT or PAID invoice, breaking the
total/subtotal relationship and audit trail.  Similarly, customers that still
have any invoice rows left after the invoice purge are skipped (PROTECT on
Invoice.customer).

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
    help = (
        "Hard-delete soft-deleted invoices, repairs, replacements, customers, "
        "and removed portal users older than --days (default 30). "
        "Dry-run unless --apply passed."
    )

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

        from django.contrib.auth.models import User
        from apps.billing.models import Invoice, InvoiceLineItem, Payment
        from apps.technician_portal.models import Repair, Replacement, Technician
        from apps.customer_portal.models import CustomerUser
        from apps.tenants.models import TenantMembership
        from core.models import Customer

        # --- Invoices to purge ---
        old_invoices = Invoice.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        invoice_count = old_invoices.count()
        invoice_ids = list(old_invoices.values_list('id', flat=True))

        # Payments on purged invoices (PROTECT — must go first)
        payment_count = Payment.objects.filter(invoice_id__in=invoice_ids).count()

        # --- Repairs to purge ---
        # Start with all soft-deleted repairs past the cutoff.
        old_repairs_qs = Repair.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        repair_ids_candidate = list(old_repairs_qs.values_list('id', flat=True))

        # Exclude repairs still referenced by line items on ACTIVE invoices
        # (i.e. invoices that are NOT in the purge set).  Deleting those line
        # items would corrupt the active invoice's financial data.  (CODE-258)
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

        # --- Replacements to purge (same safety rule as repairs) ---
        old_replacements_qs = Replacement.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        replacement_ids_candidate = list(old_replacements_qs.values_list('id', flat=True))

        blocked_replacement_ids = set()
        if replacement_ids_candidate:
            blocked_replacement_ids = set(
                InvoiceLineItem.objects
                .filter(replacement_id__in=replacement_ids_candidate)
                .exclude(invoice_id__in=invoice_ids)
                .exclude(invoice__deleted_at__isnull=False)
                .values_list('replacement_id', flat=True)
                .distinct()
            )

        safe_replacement_ids = [
            rid for rid in replacement_ids_candidate if rid not in blocked_replacement_ids
        ]
        replacement_count = len(safe_replacement_ids)
        skipped_replacement_count = len(blocked_replacement_ids)

        # --- Line items to purge ---
        # Only delete line items on invoices being purged, PLUS line items on
        # soft-deleted invoices that reference safe-to-purge jobs.  Never
        # touch line items on active invoices.
        line_items_filter = (
            Q(invoice_id__in=invoice_ids)
            | Q(repair_id__in=safe_repair_ids, invoice__deleted_at__isnull=False)
            | Q(replacement_id__in=safe_replacement_ids, invoice__deleted_at__isnull=False)
        )
        line_item_count = InvoiceLineItem.objects.filter(line_items_filter).count()

        # --- Removed portal users to purge ---
        old_customer_users = CustomerUser.objects.filter(
            deactivated_at__isnull=False,
            deactivated_at__lt=cutoff,
        ).select_related('user')
        cu_count = old_customer_users.count()

        # --- Customers to purge ---
        old_customers_qs = Customer.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff,
        )
        customer_ids_candidate = list(old_customers_qs.values_list('id', flat=True))

        # Skip customers that will still have invoice rows after this run's
        # invoice purge (Invoice.customer is PROTECT).  Those invoices are
        # either active or not yet aged out; the customer purges later.
        blocked_customer_ids = set()
        if customer_ids_candidate:
            blocked_customer_ids = set(
                Invoice.all_objects
                .filter(customer_id__in=customer_ids_candidate)
                .exclude(id__in=invoice_ids)
                .values_list('customer_id', flat=True)
                .distinct()
            )
            # Also keep customers whose jobs are being retained this run
            # (blocked by active invoices) — deleting the customer would
            # orphan those jobs via SET_NULL (the CODE-073 bug).
            if blocked_repair_ids:
                blocked_customer_ids |= set(
                    Repair.all_objects.filter(id__in=blocked_repair_ids)
                    .values_list('customer_id', flat=True)
                )
            if blocked_replacement_ids:
                blocked_customer_ids |= set(
                    Replacement.all_objects.filter(id__in=blocked_replacement_ids)
                    .values_list('customer_id', flat=True)
                )
            blocked_customer_ids.discard(None)
        safe_customer_ids = [
            cid for cid in customer_ids_candidate if cid not in blocked_customer_ids
        ]
        customer_count = len(safe_customer_ids)
        skipped_customer_count = len(blocked_customer_ids)

        self.stdout.write(f"\n{'DRY RUN — ' if not apply else ''}Purge cutoff: {cutoff.strftime('%Y-%m-%d %H:%M UTC')}")
        self.stdout.write(f"  Payments to purge:      {payment_count}")
        self.stdout.write(f"  Invoices to purge:      {invoice_count}")
        self.stdout.write(f"  Line items to purge:    {line_item_count}")
        self.stdout.write(f"  Repairs to purge:       {repair_count}")
        self.stdout.write(f"  Replacements to purge:  {replacement_count}")
        self.stdout.write(f"  Portal users to purge:  {cu_count}")
        self.stdout.write(f"  Customers to purge:     {customer_count}")
        if skipped_count:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {skipped_count} repair(s) skipped — still referenced by active invoices. "
                f"They will be purged once the invoice is also soft-deleted and aged."
            ))
        if skipped_replacement_count:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {skipped_replacement_count} replacement(s) skipped — still referenced by active invoices."
            ))
        if skipped_customer_count:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {skipped_customer_count} customer(s) skipped — still have invoices outside this purge."
            ))

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDry run complete. Pass --apply to perform actual deletions."
            ))
            return

        if not any([invoice_count, repair_count, replacement_count, customer_count, cu_count]):
            self.stdout.write(self.style.SUCCESS("Nothing to purge."))
            return

        with transaction.atomic():
            # 1. Payments on purged invoices (PROTECT on Payment.invoice)
            deleted_pay, _ = Payment.objects.filter(invoice_id__in=invoice_ids).delete()

            # 2. Line items (PROTECT on repair/replacement FKs)
            deleted_li, _ = InvoiceLineItem.objects.filter(line_items_filter).delete()

            # 3. Invoices — instance loop so Invoice.delete() fires and cleans
            #    up the S3 PDF object (QuerySet.delete() bypasses it, CODE-152)
            deleted_inv = 0
            for inv in Invoice.all_objects.filter(id__in=invoice_ids):
                inv.delete()
                deleted_inv += 1

            # 4. Jobs
            deleted_rep, _ = Repair.all_objects.filter(id__in=safe_repair_ids).delete()
            deleted_repl, _ = Replacement.all_objects.filter(id__in=safe_replacement_ids).delete()

            # 5. Removed portal users — delete the auth User (cascades the
            #    CustomerUser link) unless the account is also staff or a
            #    technician/owner somewhere, in which case only the portal
            #    link is removed.
            deleted_users = 0
            for cu in old_customer_users:
                user = cu.user
                keep_user = (
                    user.is_staff or user.is_superuser
                    or Technician.objects.filter(user=user).exists()
                    or TenantMembership.objects.filter(user=user).exists()
                )
                if keep_user:
                    cu.delete()
                else:
                    user.delete()
                deleted_users += 1

            # 6. Customers (remaining relations cascade or SET_NULL)
            deleted_cust, _ = Customer.all_objects.filter(id__in=safe_customer_ids).delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nPurged: {deleted_pay} payments, {deleted_li} line items, {deleted_inv} invoices, "
            f"{deleted_rep} repairs, {deleted_repl} replacements, {deleted_users} portal users, "
            f"{deleted_cust} customers."
        ))
        if skipped_count:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_count} repair(s) retained — referenced by active invoices."
            ))
        if skipped_replacement_count:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_replacement_count} replacement(s) retained — referenced by active invoices."
            ))
        if skipped_customer_count:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_customer_count} customer(s) retained — still have invoices outside this purge."
            ))
