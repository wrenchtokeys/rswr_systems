"""
Management command to generate and cache warranty statistics for all tenants.

Can be run on a cron schedule (e.g. hourly) to keep cached stats fresh,
or on demand for a specific tenant.

Usage:
    python manage.py generate_warranty_report              # All tenants
    python manage.py generate_warranty_report --tenant=5   # Specific tenant
    python manage.py generate_warranty_report --json       # JSON output
"""

import json as json_lib

from django.core.management.base import BaseCommand

from apps.tenants.models import Tenant
from apps.technician_portal.warranty_service import WarrantyService


class Command(BaseCommand):
    help = 'Generate and cache warranty statistics for tenants'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant', type=int, default=None,
            help='Tenant PK to generate report for (default: all tenants)',
        )
        parser.add_argument(
            '--period', type=int, default=30,
            help='Period in days for stats (default: 30)',
        )
        parser.add_argument(
            '--json', action='store_true',
            help='Output stats as JSON',
        )

    def handle(self, *args, **options):
        tenant_pk = options['tenant']
        period = options['period']
        output_json = options['json']

        if tenant_pk:
            tenants = Tenant.objects.filter(pk=tenant_pk)
        else:
            tenants = Tenant.objects.filter(is_active=True)

        results = {}
        for tenant in tenants:
            stats = WarrantyService.get_warranty_stats(
                tenant, period_days=period, use_cache=False,
            )
            results[tenant.name] = stats

            if not output_json:
                self.stdout.write(
                    f"\n{tenant.name} (last {period} days):\n"
                    f"  Claims: {stats['claims_this_period']}\n"
                    f"  Total completed: {stats['total_repairs']}\n"
                    f"  Warranty rate: {stats['warranty_rate']}%\n"
                )

        if output_json:
            self.stdout.write(json_lib.dumps(results, indent=2, default=str))

        if not output_json:
            self.stdout.write(self.style.SUCCESS(
                f"\nDone — cached stats for {len(results)} tenant(s) (TTL: 1 hour)"
            ))
