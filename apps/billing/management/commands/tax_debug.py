"""
Quick diagnostic: run `python manage.py tax_debug` to check tax setup.
Iterates over all tenants (or a specific one via --tenant <id|slug>).
"""
from django.core.management.base import BaseCommand
from decimal import Decimal


class Command(BaseCommand):
    help = 'Diagnose tax configuration issues for all tenants (or one with --tenant)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            help='Tenant ID or slug to check (default: all tenants)',
        )

    def handle(self, *args, **options):
        from apps.billing.models import BillingConfig, TaxRate
        from apps.billing.services.tax_service import TaxService
        from apps.tenants.models import Tenant
        from core.models import Customer
        from django.core.cache import cache

        cache.delete_pattern('billing_config_tax_*')
        # Fallback for backends without delete_pattern
        self.stdout.write("\n=== TAX DIAGNOSTIC ===\n")

        # Determine which tenants to check
        tenant_filter = options.get('tenant')
        if tenant_filter:
            try:
                tenant_filter = int(tenant_filter)
                tenants = Tenant.objects.filter(pk=tenant_filter)
            except ValueError:
                tenants = Tenant.objects.filter(slug=tenant_filter)
            if not tenants.exists():
                self.stdout.write(self.style.ERROR(f"No tenant found for: {options['tenant']}"))
                return
        else:
            tenants = Tenant.objects.all().order_by('id')

        if not tenants.exists():
            self.stdout.write(self.style.WARNING("No tenants found in database."))
            return

        for tenant in tenants:
            self.stdout.write(f"\n{'='*50}")
            self.stdout.write(f"Tenant: {tenant.name} (id={tenant.id}, slug={tenant.slug})")
            self.stdout.write('='*50)

            # 1. BillingConfig
            try:
                config = BillingConfig.get_for_tenant(tenant)
                self.stdout.write(f"✓ BillingConfig exists")
                self.stdout.write(f"  tax_enabled:      {config.tax_enabled}")
                self.stdout.write(f"  company_city:     '{config.company_city}'")
                self.stdout.write(f"  company_state:    '{config.company_state}'")
                self.stdout.write(f"  company_zip:      '{config.company_zip}'")
                self.stdout.write(f"  default_tax_rate: {config.default_tax_rate}")

                if not config.tax_enabled:
                    self.stdout.write(self.style.ERROR(
                        "\n✗ PROBLEM: tax_enabled is False. Run:\n"
                        f"  BillingConfig.get_for_tenant(Tenant.objects.get(id={tenant.id})).tax_enabled = True\n"
                        "  (and save it)"
                    ))

                if not config.company_city or not config.company_state:
                    self.stdout.write(self.style.ERROR(
                        "\n✗ PROBLEM: Shop city/state not set. Tax can't look up a rate.\n"
                        "  Set company_city and company_state in Django admin → Billing Configuration\n"
                        "  OR go to Settings → Billing & Tax → Shop Location"
                    ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ BillingConfig error: {e}"))
                continue

            # 2. Tax rates for this tenant
            all_rates = TaxRate.objects.filter(tenant=tenant, is_active=True)
            self.stdout.write(f"\n--- Tax Rates ---")
            self.stdout.write(f"  Total active rates: {all_rates.count()}")

            if config.company_city and config.company_state:
                matching = all_rates.filter(
                    city__iexact=config.company_city.strip(),
                    state__iexact=config.company_state.strip(),
                )
                self.stdout.write(
                    f"  Matching '{config.company_city}, {config.company_state}': {matching.count()}"
                )
                for r in matching:
                    self.stdout.write(f"    → {r.city}, {r.state} = {r.total_rate}%")

                if matching.count() == 0:
                    self.stdout.write(self.style.ERROR(
                        f"\n✗ PROBLEM: No tax rate for '{config.company_city}, {config.company_state}'\n"
                        "  Add one in Settings → Billing & Tax → Add Tax Rate"
                    ))
                    sample = all_rates[:5]
                    if sample:
                        self.stdout.write("  You have rates for:")
                        for r in sample:
                            self.stdout.write(f"    {r.city}, {r.state} = {r.total_rate}%")
            else:
                self.stdout.write(self.style.WARNING("  Skipping match — no shop city/state set"))

            # 3. Test calculation for this tenant
            self.stdout.write(f"\n--- Test Calculation ---")
            svc = TaxService(tenant=tenant)
            result = svc.calculate_tax(Decimal('100.00'))
            self.stdout.write(
                f"  $100 invoice → rate={result['rate']}%, tax=${result['amount']}, enabled={result['enabled']}"
            )

            if result['amount'] == 0 and config.tax_enabled:
                self.stdout.write(self.style.ERROR("✗ Tax is enabled but calculating $0. Check issues above."))
            elif result['amount'] > 0:
                self.stdout.write(self.style.SUCCESS(f"✓ Tax is working! ${result['amount']} on $100"))

            # 4. Test with customers for this tenant
            self.stdout.write(f"\n--- Customers ---")
            for c in Customer.objects.filter(tenant=tenant)[:5]:
                r = svc.calculate_tax(Decimal('100.00'), customer=c)
                exempt = " [TAX EXEMPT]" if r['exempt'] else ""
                self.stdout.write(f"  {c.name}: rate={r['rate']}%, tax=${r['amount']}{exempt}")

        self.stdout.write("")
