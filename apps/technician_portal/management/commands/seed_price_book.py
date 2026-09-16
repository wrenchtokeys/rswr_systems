"""
Fill each shop's price book from its completed replacements (B6).

The book learns on its own from the day it deploys; this reads in what a
shop did *before* that day, so the first job after the deploy already has
a price to offer. Idempotent — LEARNED and QUOTE rows are rebuilt from
scratch, PINNED rows are kept (see services/price_book.rebuild_for_tenant).
The owner has the same button on the price book page.

    python manage.py seed_price_book --dry-run
    python manage.py seed_price_book --tenant the-glass-guy
"""
from django.core.management.base import BaseCommand, CommandError

from apps.technician_portal.models import Replacement
from apps.technician_portal.price_book_models import PriceBookEntry
from apps.technician_portal.services.price_book import rebuild_for_tenant
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Rebuild every shop's price book from its completed replacements."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what each shop would learn from; write nothing.')
        parser.add_argument('--tenant', default=None,
                            help='Only this shop (slug or id).')

    def handle(self, *args, **options):
        tenants = Tenant.objects.all().order_by('pk')
        if options['tenant']:
            key = options['tenant']
            tenants = tenants.filter(pk=key) if key.isdigit() else tenants.filter(slug=key)
            if not tenants.exists():
                raise CommandError(f'No tenant matches {key!r}.')

        for tenant in tenants:
            learnable = (
                Replacement.objects.filter(tenant=tenant, queue_status='COMPLETED')
                .exclude(vehicle_make='').exclude(vehicle_model='').count()
            )
            pinned = PriceBookEntry.objects.filter(
                tenant=tenant, source=PriceBookEntry.SOURCE_PINNED,
            ).count()
            if options['dry_run']:
                self.stdout.write(
                    f'{tenant.slug}: {learnable} completed replacement(s) with a vehicle, '
                    f'{pinned} pinned row(s) would be kept',
                )
                continue
            read, rows = rebuild_for_tenant(tenant)
            self.stdout.write(self.style.SUCCESS(
                f'{tenant.slug}: read {read} job(s) → {rows} row(s) ({pinned} pinned kept)',
            ))
