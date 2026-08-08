"""
Readiness check for a shop's Stripe Connect account.

Answers one question end-to-end: *can this shop's customers actually pay an
invoice online right now?* It pulls live state from Stripe (so it does not
trust possibly-stale tenant columns), then reports every gate that sits
between a shop and a working "Pay Now" button.

Usage:
    python manage.py check_connect_status                    # every active tenant
    python manage.py check_connect_status --tenant my-shop   # one shop (slug or id)
    python manage.py check_connect_status --no-sync          # read DB only, no Stripe calls
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Check whether a shop is ready to accept invoice payments via Stripe Connect"

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            help='Tenant slug or numeric id. Omit to check every active tenant.',
        )
        parser.add_argument(
            '--no-sync',
            action='store_true',
            help='Report stored values only; do not call Stripe.',
        )

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options.get('tenant'))
        if not tenants:
            raise CommandError('No matching tenants found.')

        stripe_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
        if not stripe_key:
            self.stdout.write(self.style.ERROR(
                'STRIPE_SECRET_KEY is not set — no shop can accept payments in this '
                'environment. Set it and re-run.'
            ))
        elif not options['no_sync']:
            self.stdout.write(self.style.SUCCESS('Stripe key present — syncing live status.\n'))

        ready = 0
        for tenant in tenants:
            if self._report(tenant, sync=bool(stripe_key) and not options['no_sync']):
                ready += 1

        self.stdout.write(
            f"\n{ready}/{len(tenants)} shop(s) ready to accept payments."
        )

    # ------------------------------------------------------------------

    def _resolve_tenants(self, ident):
        if not ident:
            return list(Tenant.objects.filter(is_active=True).order_by('name'))
        qs = Tenant.objects.filter(slug=ident)
        if not qs.exists() and str(ident).isdigit():
            qs = Tenant.objects.filter(id=int(ident))
        return list(qs)

    def _report(self, tenant, sync):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{tenant.name} ({tenant.slug})"))

        requirements = {}
        if sync and tenant.stripe_connect_account_id:
            from apps.tenants.services.connect_service import ConnectService, ConnectError
            try:
                status = ConnectService().sync_account_status(tenant)
                requirements = status.get('requirements') or {}
                tenant.refresh_from_db()
            except ConnectError as e:
                self.stdout.write(self.style.WARNING(
                    f"  ! Could not reach Stripe ({e}) — reporting stored values."
                ))

        if not tenant.stripe_connect_account_id:
            self.stdout.write(self.style.ERROR(
                '  NOT READY — no Stripe Connect account.\n'
                '    Fix: sign in as the shop owner and visit '
                '/owner/payments/setup/ → "Connect with Stripe".'
            ))
            return False

        self.stdout.write(f"  account:            {tenant.stripe_connect_account_id}")
        self.stdout.write(f"  onboarding status:  {tenant.stripe_onboarding_status}")
        self.stdout.write(f"  details submitted:  {tenant.stripe_connect_onboarding_complete}")
        self.stdout.write(f"  charges enabled:    {tenant.stripe_connect_charges_enabled}")
        self.stdout.write(f"  payouts enabled:    {tenant.stripe_connect_payouts_enabled}")

        if requirements.get('disabled_reason'):
            self.stdout.write(f"  disabled reason:    {requirements['disabled_reason']}")
        for key in ('past_due', 'currently_due', 'eventually_due'):
            items = requirements.get(key) or []
            if items:
                self.stdout.write(f"  {key}: {', '.join(items)}")

        # platform_fee_percent = 0.00 is an explicit "no fee" override, distinct
        # from NULL ("use PlatformConfig default"). Tenants predating migration
        # tenants/0012 were written as 0.00 and silently pay nothing.
        if tenant.platform_fee_percent is None:
            self.stdout.write("  platform fee:       (uses PlatformConfig default)")
        else:
            self.stdout.write(f"  platform fee:       {tenant.platform_fee_percent}% (tenant override)")

        if tenant.can_accept_payments:
            self.stdout.write(self.style.SUCCESS('  READY — customers can pay invoices online.'))
            if not tenant.stripe_connect_payouts_enabled:
                self.stdout.write(self.style.WARNING(
                    '    Note: payouts are NOT enabled — Stripe will hold the funds '
                    'until bank/identity details are verified.'
                ))
            return True

        if not tenant.stripe_connect_onboarding_complete:
            fix = 'Onboarding was never finished — resume it at /owner/payments/setup/.'
        elif tenant.stripe_onboarding_status in ('restricted', 'disabled'):
            fix = 'Stripe restricted the account — clear the requirements listed above.'
        elif not tenant.stripe_connect_charges_enabled:
            fix = 'Stripe has not enabled charges yet — usually verification still pending.'
        else:
            fix = (
                f"Stored status is '{tenant.stripe_onboarding_status}', not 'active'. "
                "Re-run without --no-sync to refresh from Stripe."
            )
        self.stdout.write(self.style.ERROR(f'  NOT READY — {fix}'))
        return False
