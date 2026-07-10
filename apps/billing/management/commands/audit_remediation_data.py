"""
Read-only data-drift audit for the 2026-07 remediation (A1, A2, A3, C2).

The code fixes on branch fix/audit-remediation-2026-07 stop NEW damage;
this command sizes the EXISTING damage so a human can decide on cleanup.
It writes nothing. Run it against production (or a restored backup):

    python manage.py audit_remediation_data

Corrective SQL lives in scripts/remediation_data_cleanup.sql — to be run
manually, in a transaction, against a backup first, after reviewing this
command's output.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, F


class Command(BaseCommand):
    help = "Read-only audit of data drift from bugs A1/A2/A3/C2 (remediation plan 2026-07-09)"

    def handle(self, *args, **options):
        from apps.billing.models import Invoice, InvoiceLineItem, Payment
        from apps.technician_portal.models import Repair, UnitRepairCount
        from apps.tenants.models import Tenant

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== A1: repair.cost drifted from invoiced amount ==="
        ))
        drifted = (
            InvoiceLineItem.objects
            .exclude(repair__isnull=True)
            .filter(quantity=1)
            .exclude(repair__cost=F('unit_price'))
            .select_related('repair', 'invoice')
        )
        count = drifted.count()
        self.stdout.write(f"{count} invoice line item(s) whose repair.cost no longer matches unit_price")
        for li in drifted[:20]:
            self.stdout.write(
                f"  invoice={li.invoice.invoice_number} repair_id={li.repair_id} "
                f"repair.cost={li.repair.cost} invoiced unit_price={li.unit_price}"
            )
        if count > 20:
            self.stdout.write(f"  ... and {count - 20} more")
        if count:
            self.stdout.write(self.style.WARNING(
                "Recommended: back-fill repair.cost from the invoice line item "
                "(the invoice is what the customer actually paid)."
            ))

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== A2: UnitRepairCount vs actual completed repairs ==="
        ))
        mismatches = 0
        for urc in UnitRepairCount.objects.select_related('customer').iterator():
            actual = Repair.objects.filter(
                customer_id=urc.customer_id,
                unit_number=urc.unit_number,
                queue_status='COMPLETED',
            )
            if urc.tenant_id:
                actual = actual.filter(tenant_id=urc.tenant_id)
            actual_count = actual.count()
            if actual_count != urc.repair_count:
                mismatches += 1
                self.stdout.write(
                    f"  urc_id={urc.id} customer={urc.customer.name!r} "
                    f"unit={urc.unit_number!r}: stored={urc.repair_count} "
                    f"actual_completed={actual_count}"
                )
        self.stdout.write(f"{mismatches} UnitRepairCount row(s) out of sync")
        if mismatches:
            self.stdout.write(self.style.WARNING(
                "Note: retail/walk-in and non-progressive customers legitimately "
                "skip increments, so rows where stored < actual may be intentional. "
                "Rows where stored > actual are the convert_to_batch double-counts."
            ))

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== A3: stale grace_period_end on live tenants ==="
        ))
        stale = Tenant.objects.filter(
            grace_period_end__isnull=False,
            subscription_status__in=['active', 'trialing'],
        )
        self.stdout.write(f"{stale.count()} tenant(s) carrying a grace stamp while active/trialing")
        for t in stale:
            self.stdout.write(
                f"  id={t.id} {t.name!r} status={t.subscription_status} "
                f"grace_period_end={t.grace_period_end}"
            )
        if stale.exists():
            self.stdout.write(self.style.WARNING(
                "These are the lockout time bombs — null them (SQL in the cleanup script)."
            ))

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== C2: duplicate stripe_payment_id rows (MUST be resolved "
            "before migration 0022 can apply in production) ==="
        ))
        dups = (
            Payment.objects
            .exclude(stripe_payment_id='')
            .values('stripe_payment_id')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )
        self.stdout.write(f"{dups.count()} duplicated stripe_payment_id value(s)")
        for d in dups:
            rows = Payment.objects.filter(
                stripe_payment_id=d['stripe_payment_id']
            ).select_related('invoice')
            for p in rows:
                self.stdout.write(
                    f"  payment_id={p.id} invoice={p.invoice.invoice_number} "
                    f"amount={p.amount} stripe_id={p.stripe_payment_id}"
                )
            self.stdout.write(self.style.WARNING(
                "  -> keep one row per stripe_payment_id, delete the extras, and "
                "re-check invoice.amount_paid afterwards."
            ))

        self.stdout.write(self.style.SUCCESS("\nAudit complete — nothing was modified."))
