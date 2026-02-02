"""
Quick diagnostic: run `python manage.py tax_debug` to check tax setup.
"""
from django.core.management.base import BaseCommand
from decimal import Decimal


class Command(BaseCommand):
    help = 'Diagnose tax configuration issues'

    def handle(self, *args, **options):
        from apps.billing.models import BillingConfig, TaxRate
        from apps.billing.services.tax_service import TaxService
        from core.models import Customer
        from django.core.cache import cache

        cache.delete('billing_config_tax')
        self.stdout.write("\n=== TAX DIAGNOSTIC ===\n")

        # 1. BillingConfig
        try:
            config = BillingConfig.get_instance()
            self.stdout.write(f"✓ BillingConfig exists")
            self.stdout.write(f"  tax_enabled:      {config.tax_enabled}")
            self.stdout.write(f"  company_city:     '{config.company_city}'")
            self.stdout.write(f"  company_state:    '{config.company_state}'")
            self.stdout.write(f"  company_zip:      '{config.company_zip}'")
            self.stdout.write(f"  default_tax_rate: {config.default_tax_rate}")

            if not config.tax_enabled:
                self.stdout.write(self.style.ERROR("\n✗ PROBLEM: tax_enabled is False. Run:"))
                self.stdout.write("  BillingConfig.get_instance().tax_enabled = True")
                self.stdout.write("  BillingConfig.get_instance().save()")

            if not config.company_city or not config.company_state:
                self.stdout.write(self.style.ERROR("\n✗ PROBLEM: Shop city/state not set. Tax can't look up a rate."))
                self.stdout.write("  Set company_city and company_state in Django admin → Billing Configuration")
                self.stdout.write("  OR go to Settings → Billing & Tax → Shop Location")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ No BillingConfig found: {e}"))
            self.stdout.write("  Create one in Django admin → Billing → Billing Configuration")
            return

        # 2. Tax rates
        all_rates = TaxRate.objects.filter(is_active=True)
        self.stdout.write(f"\n--- Tax Rates ---")
        self.stdout.write(f"  Total active rates: {all_rates.count()}")

        if config.company_city and config.company_state:
            matching = all_rates.filter(
                city__iexact=config.company_city.strip(),
                state__iexact=config.company_state.strip(),
            )
            self.stdout.write(f"  Matching '{config.company_city}, {config.company_state}': {matching.count()}")
            for r in matching:
                self.stdout.write(f"    → {r.city}, {r.state} = {r.total_rate}% (tenant_id={r.tenant_id})")

            if matching.count() == 0:
                self.stdout.write(self.style.ERROR(f"\n✗ PROBLEM: No tax rate for '{config.company_city}, {config.company_state}'"))
                self.stdout.write("  Add one in Settings → Billing & Tax → Add Tax Rate")
                # Show sample rates
                sample = all_rates[:5]
                if sample:
                    self.stdout.write(f"\n  You have rates for:")
                    for r in sample:
                        self.stdout.write(f"    {r.city}, {r.state} = {r.total_rate}%")
        else:
            self.stdout.write(self.style.WARNING("  Skipping match — no shop city/state set"))

        # 3. Test calculation
        self.stdout.write(f"\n--- Test Calculation ---")
        svc = TaxService()
        result = svc.calculate_tax(Decimal('100.00'))
        self.stdout.write(f"  $100 invoice → rate={result['rate']}%, tax=${result['amount']}, enabled={result['enabled']}")
        self.stdout.write(f"  Looked up: city='{result['city']}', state='{result['state']}'")

        if result['amount'] == 0 and config.tax_enabled:
            self.stdout.write(self.style.ERROR("\n✗ Tax is enabled but calculating $0. Check issues above."))
        elif result['amount'] > 0:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Tax is working! ${result['amount']} on $100"))

        # 4. Test with a customer
        self.stdout.write(f"\n--- Customers ---")
        for c in Customer.objects.all()[:5]:
            r = svc.calculate_tax(Decimal('100.00'), customer=c)
            exempt = " [TAX EXEMPT]" if r['exempt'] else ""
            self.stdout.write(f"  {c.name}: rate={r['rate']}%, tax=${r['amount']}{exempt}")

        self.stdout.write("")
