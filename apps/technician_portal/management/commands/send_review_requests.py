"""
Management command: send_review_requests

Sends all pending ReviewRequests whose scheduled_at has arrived.
Intended to run via cron every 15-30 minutes.

Usage:
    python manage.py send_review_requests
    python manage.py send_review_requests --dry-run
"""
from django.core.management.base import BaseCommand

from apps.technician_portal.review_service import ReviewRequestService


class Command(BaseCommand):
    help = "Send pending review request emails whose scheduled time has arrived."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Show how many requests would be sent without actually sending.",
        )

    def handle(self, *args, **options):
        if options['dry_run']:
            from django.utils import timezone
            from apps.technician_portal.review_models import ReviewRequest

            count = ReviewRequest.objects.filter(
                status='pending',
                scheduled_at__lte=timezone.now(),
            ).count()
            self.stdout.write(f"Dry run: {count} review request(s) ready to send.")
            return

        sent = ReviewRequestService.send_pending_requests()
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} review request(s)."))
