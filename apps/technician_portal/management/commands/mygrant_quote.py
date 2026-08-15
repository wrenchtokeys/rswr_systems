"""
One-off Mygrant quote from the command line — the "staging first" proof step.

The day a shop's API key arrives, verify the pipeline before any tech touches
the UI:

    # Free: staging + EnvironmentID=TEST (spec sample part works there)
    python manage.py mygrant_quote --tenant 15 --nags DW01658 --staging

    # Real account — may incur the shop's per-search charge, so it asks first
    python manage.py mygrant_quote --tenant 15 --nags DW01658

Read-only against Mygrant: this sends an Inquiry, never an Order.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.technician_portal import mygrant_service
from apps.technician_portal.parts_models import MygrantConfig
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Run one Mygrant NAGS Inquiry for a tenant (staging or production)."

    def add_arguments(self, parser):
        parser.add_argument('--tenant', required=True, help="Tenant id or slug")
        parser.add_argument('--nags', required=True, help="NAGS number, e.g. DW01658")
        parser.add_argument(
            '--staging', action='store_true',
            help="Use Mygrant's staging host + EnvironmentID=TEST (no charge).",
        )

    def handle(self, *args, **options):
        lookup = options['tenant']
        try:
            tenant = (
                Tenant.objects.get(id=int(lookup))
                if lookup.isdigit() else Tenant.objects.get(slug=lookup)
            )
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant {lookup!r}")

        config = MygrantConfig.get_for_tenant(tenant)
        if not config.is_enabled():
            raise CommandError(
                f"Tenant {tenant} has no complete Mygrant connection "
                "(credentials + API key). Connect it in Owner Settings → Parts."
            )

        environment = 'TEST' if options['staging'] else 'PROD'
        if environment == 'PROD':
            answer = input(
                "PRODUCTION inquiry on the shop's real Mygrant account — "
                "searches may bill (~$1). Type 'yes' to continue: "
            )
            if answer.strip().lower() != 'yes':
                self.stdout.write("Aborted, nothing sent.")
                return

        try:
            skus = mygrant_service.quote_nags(
                config, options['nags'], environment=environment,
            )
        except mygrant_service.MygrantError as exc:
            raise CommandError(str(exc))

        if not skus:
            self.stdout.write(self.style.WARNING("Mygrant returned no SKUs."))
            return
        self.stdout.write(self.style.SUCCESS(f"{len(skus)} SKU(s) [{environment}]:"))
        for sku in skus:
            self.stdout.write(
                f"  {sku['part'] or sku['product_id']:24} {sku['brand']:6} "
                f"qty={sku['qty_available']:4} my=${sku['customer_price']} "
                f"list=${sku['list_price']} {sku['branch']} "
                f"[{sku['notes'] or sku['response_code']}]"
            )
