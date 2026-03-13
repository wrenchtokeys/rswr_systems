"""
Management command: process_batch_invoices

Scheduled batch invoice generation for fleet customers.
Run via cron: 0 6 * * * manage.py process_batch_invoices

Respects BillingConfig.batch_invoice_frequency settings; will
skip internally if today is not the configured run day.

Replaces the former Celery task billing.process_batch_invoices.
"""

import logging
from django.core.management.base import BaseCommand
from apps.billing.tasks import process_batch_invoices as _process_batch_invoices

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate batch invoices for fleet customers (runs on configured schedule)'

    def handle(self, *args, **options):
        self.stdout.write('Processing batch invoices...')
        result = _process_batch_invoices()
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {result['invoices_created']} batch invoices."
            )
        )
