"""One-off command to reset Stripe Connect fields for a tenant."""
from django.core.management.base import BaseCommand
from apps.tenants.models import Tenant

class Command(BaseCommand):
    help = 'Reset Stripe Connect fields for a tenant (clears stale test-mode account)'

    def add_arguments(self, parser):
        parser.add_argument('tenant_id', type=int)
        parser.add_argument('--apply', action='store_true', help='Actually apply (dry-run by default)')

    def handle(self, *args, **options):
        t = Tenant.objects.get(id=options['tenant_id'])
        self.stdout.write(f"Tenant: {t.name} (id={t.id})")
        self.stdout.write(f"  connect_account_id: {t.stripe_connect_account_id}")
        self.stdout.write(f"  onboarding_status: {t.stripe_onboarding_status}")
        self.stdout.write(f"  charges_enabled: {t.stripe_connect_charges_enabled}")
        self.stdout.write(f"  payouts_enabled: {t.stripe_connect_payouts_enabled}")
        self.stdout.write(f"  onboarding_complete: {t.stripe_connect_onboarding_complete}")

        if not options['apply']:
            self.stdout.write("\nDry run — pass --apply to reset")
            return

        t.stripe_connect_account_id = ''
        t.stripe_onboarding_status = 'not_started'
        t.stripe_connect_charges_enabled = False
        t.stripe_connect_payouts_enabled = False
        t.stripe_connect_onboarding_complete = False
        t.stripe_connected_at = None
        t.save(update_fields=[
            'stripe_connect_account_id', 'stripe_onboarding_status',
            'stripe_connect_charges_enabled', 'stripe_connect_payouts_enabled',
            'stripe_connect_onboarding_complete', 'stripe_connected_at'
        ])
        self.stdout.write(self.style.SUCCESS(f"\nConnect fields reset for {t.name}"))
