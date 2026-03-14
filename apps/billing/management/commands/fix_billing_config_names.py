"""
Management command: fix_billing_config_names

Updates each BillingConfig's company_name to match its Tenant's name,
fixing the issue where the initial migration copied "Rockstar Windshield Repair"
as the company name for all tenants.

Usage:
    python manage.py fix_billing_config_names          # show what would change
    python manage.py fix_billing_config_names --apply  # apply the changes
"""

from django.core.management.base import BaseCommand
from apps.billing.models import BillingConfig


class Command(BaseCommand):
    help = (
        "Fix BillingConfig company_name to match each tenant's actual name. "
        "Run with --apply to commit changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually apply the changes (default: dry-run)',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        configs = BillingConfig.objects.select_related('tenant').all()

        if not configs.exists():
            self.stdout.write(self.style.WARNING("No BillingConfig records found."))
            return

        updated = 0
        skipped = 0

        for config in configs:
            if not config.tenant:
                self.stdout.write(
                    self.style.WARNING(f"  BillingConfig #{config.pk} has no tenant — skipping")
                )
                skipped += 1
                continue

            tenant_name = config.tenant.name
            current_name = config.company_name or ''

            if current_name == tenant_name:
                self.stdout.write(f"  ✓ BillingConfig #{config.pk} ({tenant_name}) — already correct")
                skipped += 1
                continue

            self.stdout.write(
                f"  {'APPLY' if apply else 'DRY-RUN'} BillingConfig #{config.pk}: "
                f"'{current_name}' → '{tenant_name}'"
            )

            if apply:
                config.company_name = tenant_name
                config.save(update_fields=['company_name'])
                updated += 1
            else:
                updated += 1

        self.stdout.write("")
        if apply:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Updated {updated} BillingConfig record(s). {skipped} unchanged."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run complete. {updated} record(s) would be updated, {skipped} unchanged. "
                    "Run with --apply to commit."
                )
            )
