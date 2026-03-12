"""
Management command: process_overdue_invoices

Daily check for overdue invoices and reminder emails.
Run via cron: 0 8 * * * manage.py process_overdue_invoices

Replaces the former Celery task billing.process_overdue_invoices.
"""

import logging
from django.core.management.base import BaseCommand
from apps.billing.tasks import process_overdue_invoices as _process_overdue_invoices

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update overdue invoice statuses and send reminder emails'

    def handle(self, *args, **options):
        self.stdout.write('Processing overdue invoices...')
        result = _process_overdue_invoices()
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Updated {result['updated']} invoices to OVERDUE, "
                f"sent {result['reminders_sent']} reminders."
            )
        )
