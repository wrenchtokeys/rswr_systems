"""One-off: Set stripe_connect_account_id for Rockstar tenant."""
from django.core.management.base import BaseCommand
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Fix missing stripe_connect_account_id for Rockstar'

    def handle(self, *args, **options):
        try:
            t = Tenant.objects.get(slug='rockstar-windshield')
            old = t.stripe_connect_account_id
            if not old:
                t.stripe_connect_account_id = 'acct_1TDdeQ0vAQGksYFw'
                t.stripe_connect_payouts_enabled = True
                t.save(update_fields=[
                    'stripe_connect_account_id',
                    'stripe_connect_payouts_enabled',
                ])
                self.stdout.write(self.style.SUCCESS(
                    f'Set stripe_connect_account_id to acct_1TDdeQ0vAQGksYFw'
                ))
            else:
                self.stdout.write(f'Already set: {old}')
            
            self.stdout.write(f'can_accept_payments: {t.can_accept_payments}')
        except Tenant.DoesNotExist:
            self.stdout.write('Rockstar tenant not found')
