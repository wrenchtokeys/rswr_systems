"""
Reconcile Stripe checkout sessions against invoices — the webhook safety net.

Checks recent OPEN StripeCheckoutAttempt rows directly with Stripe and
records any paid sessions the webhook missed (idempotent: keyed on the
payment_intent id, so a late webhook retry is a no-op afterwards). Run by
EB cron every 15 minutes (13_stripe_reconcile_cron.config); safe to run by
hand at any time.

If this command ever records a payment, webhook delivery is broken —
it logs at WARNING so the recovery is visible in the logs.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Verify recent Stripe checkout sessions and record any paid ones "
        "the webhook missed. Applies by default; --dry-run only counts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Only report how many open sessions would be checked.',
        )
        parser.add_argument(
            '--days', type=int, default=7,
            help='How many days back to look for open sessions (default 7).',
        )

    def handle(self, *args, **options):
        from apps.billing.services.stripe_reconcile import reconcile_open_attempts

        summary = reconcile_open_attempts(
            max_age_days=options['days'],
            apply=not options['dry_run'],
        )

        if options['dry_run']:
            self.stdout.write(
                f"[dry run] {summary['checked']} open session(s) would be checked"
            )
            return

        self.stdout.write(
            f"Checked {summary['checked']}: "
            f"{summary['recorded']} payment(s) recorded, "
            f"{summary['expired']} expired, "
            f"{summary['open']} still open, "
            f"{summary['errors']} error(s)"
        )
        if summary['recorded']:
            self.stdout.write(self.style.WARNING(
                "Recorded payments outside the webhook path — "
                "check Stripe webhook health!"
            ))
