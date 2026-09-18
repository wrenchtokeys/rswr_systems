"""
Re-send the emails a support message should have produced but didn't.

The contact forms are record-first: the SupportMessage row is saved, THEN
the admin notification and the sender's acknowledgement are attempted, and
a mail failure never fails the request. That is the right trade — a cry for
help must not be lost to an SES blip — but it means a row can sit in the
admin with emailed_ok=False and nobody is told. This sweep is the telling.

    python manage.py sweep_support_messages --dry-run
    python manage.py sweep_support_messages

Runs every 20 minutes from EB cron (12_reviews_cron.config) through
run-cron.sh. Rows younger than 15 minutes are left alone so a request that
is mid-flight is never double-sent.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.support.models import SupportMessage
from apps.support.services import notify_admins, send_acknowledgement

MIN_AGE = timedelta(minutes=15)


class Command(BaseCommand):
    help = 'Re-send admin notifications / acknowledgements for support messages whose email failed.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be re-sent; send nothing.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        cutoff = timezone.now() - MIN_AGE
        stale = SupportMessage.objects.filter(created_at__lte=cutoff)
        unnotified = list(stale.filter(emailed_ok=False).order_by('created_at'))
        unacked = list(stale.filter(acknowledged=False).order_by('created_at'))

        self.stdout.write(
            f"{len(unnotified)} message(s) never reached the admins, "
            f"{len(unacked)} sender(s) never got an acknowledgement"
            f"{' (dry run — nothing sent)' if dry_run else ''}."
        )
        for record in unnotified:
            self.stdout.write(f"  admin   #{record.pk}  {record.created_at:%Y-%m-%d %H:%M}  {record.email}")
        for record in unacked:
            self.stdout.write(f"  ack     #{record.pk}  {record.created_at:%Y-%m-%d %H:%M}  {record.email}")
        if dry_run:
            return

        sent_admin = sum(1 for record in unnotified if notify_admins(record))
        sent_ack = sum(1 for record in unacked if send_acknowledgement(record))
        still = SupportMessage.objects.filter(created_at__lte=cutoff, emailed_ok=False).count()
        self.stdout.write(self.style.SUCCESS(
            f"Re-sent {sent_admin} admin notification(s) and {sent_ack} acknowledgement(s); "
            f"{still} still failing."
        ))
