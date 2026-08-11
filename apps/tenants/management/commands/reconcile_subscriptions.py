"""
Reconcile tenant subscription state against Stripe — the webhook safety net.

The invoice side has had `reconcile_stripe_payments` since the stripe-python
15.x outage. Subscriptions had no equivalent, so a lost or swallowed webhook
left a tenant's plan and status permanently wrong with nothing to notice it:
a shop that paid could sit on plan='trial' until the trial clock locked them
out, and a shop that cancelled could keep full access indefinitely.

Applies by default; --dry-run reports drift without touching anything.
Run hourly by EB cron (11_billing_cron.config); safe to run by hand.

If this command ever changes a tenant, webhook delivery is broken — it logs
at WARNING so the recovery is visible.
"""

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Verify each tenant's subscription against Stripe and repair drift. "
        "Applies by default; --dry-run only reports."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report drift without writing anything.',
        )
        parser.add_argument(
            '--tenant', type=str, default=None,
            help='Limit to a single tenant slug.',
        )
        parser.add_argument(
            '--json', action='store_true',
            help='Emit the full summary as JSON (for log scraping).',
        )

    def handle(self, *args, **options):
        from apps.tenants.services.subscription_reconcile import reconcile_all

        apply = not options['dry_run']
        summary = reconcile_all(apply=apply, tenant_slug=options['tenant'])

        if options['json']:
            self.stdout.write(json.dumps(summary, default=str))
            return

        prefix = '[dry run] ' if options['dry_run'] else ''
        verb = 'would update' if options['dry_run'] else 'updated'
        self.stdout.write(
            f"{prefix}Checked {summary['checked']} tenant(s): "
            f"{summary['updated']} {verb}, "
            f"{summary['in_sync']} already in sync, "
            f"{summary['no_subscription']} with no Stripe subscription, "
            f"{summary['errors']} error(s)"
        )

        for result in summary['results']:
            if result.get('action') in ('updated', 'would_update'):
                before = result.get('before') or {
                    'status': result.get('local_status'),
                    'plan': result.get('local_plan'),
                }
                after = result.get('after') or {
                    'status': result.get('stripe_status'),
                    'plan': result.get('stripe_plan'),
                }
                self.stdout.write(f"  {result['tenant']}: {before} -> {after}")
            elif result.get('error'):
                self.stdout.write(self.style.ERROR(
                    f"  {result['tenant']}: {result['error']}"
                ))

        if summary['updated'] and apply:
            self.stdout.write(self.style.WARNING(
                "Subscription state was repaired outside the webhook path — "
                "check Stripe webhook health!"
            ))
        if summary['errors']:
            self.stdout.write(self.style.WARNING(
                "Some tenants could not be checked; Stripe may be unavailable. "
                "Local state was left untouched for those."
            ))
