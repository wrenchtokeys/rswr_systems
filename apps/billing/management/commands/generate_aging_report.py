"""
Management command: generate_aging_report

On-demand accounts-receivable aging report.

Usage:
    python manage.py generate_aging_report
    python manage.py generate_aging_report --tenant-id 1

Replaces the former Celery task billing.generate_aging_report.
"""

import json
import logging
from django.core.management.base import BaseCommand
from apps.billing.tasks import generate_aging_report as _generate_aging_report

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate accounts-receivable aging report'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            type=int,
            default=None,
            help='Limit report to a specific tenant ID (default: all tenants)',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            default=False,
            help='Output raw JSON instead of formatted table',
        )

    def handle(self, *args, **options):
        tenant_id = options.get('tenant_id')
        as_json = options.get('json')

        self.stdout.write('Generating aging report...')
        reports = _generate_aging_report(tenant_id=tenant_id)

        if as_json:
            self.stdout.write(json.dumps(reports, indent=2))
            return

        for slug, data in reports.items():
            self.stdout.write(self.style.SUCCESS(f"\n=== {data['tenant_name']} ==="))
            self.stdout.write(f"Generated: {data['generated_at']}")
            self.stdout.write(f"{'Bucket':<15} {'Count':>6}  {'Total':>12}")
            self.stdout.write('-' * 38)
            bucket_labels = {
                'current':  'Current',
                '1_30':     '1-30 days',
                '31_60':    '31-60 days',
                '61_90':    '61-90 days',
                '90_plus':  '90+ days',
            }
            for key, label in bucket_labels.items():
                b = data['buckets'][key]
                self.stdout.write(f"{label:<15} {b['count']:>6}  ${b['total']:>11,.2f}")
            self.stdout.write('-' * 38)
            self.stdout.write(f"{'TOTAL':<15} {'':>6}  ${data['grand_total']:>11,.2f}")
