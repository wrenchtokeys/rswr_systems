"""
Management command to load tax rates from a CSV file.

Usage:
    python manage.py load_tax_rates --file rates.csv
    python manage.py load_tax_rates --file rates.csv --clear   # clear existing first
    python manage.py load_tax_rates --file rates.csv --tenant 1  # for a specific tenant

CSV format:
    city,county,state,zip_code,state_rate,county_rate,city_rate,special_rate
    Little Rock,,AR,72201,6.500,1.250,1.250,0.000

Note: total_rate auto-calculates from component rates. You don't need a total column.
"""

import csv
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand, CommandError
from apps.billing.models import TaxRate


class Command(BaseCommand):
    help = 'Load tax rates from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, help='Path to CSV file')
        parser.add_argument('--clear', action='store_true', help='Clear existing rates before loading')
        parser.add_argument('--tenant', type=int, help='Tenant ID to associate rates with')

    def handle(self, *args, **options):
        file_path = options['file']
        clear = options['clear']
        tenant_id = options.get('tenant')

        tenant = None
        if tenant_id:
            from apps.tenants.models import Tenant
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise CommandError(f'Tenant {tenant_id} not found')

        if clear:
            qs = TaxRate.objects.all()
            if tenant:
                qs = qs.filter(tenant=tenant)
            count = qs.count()
            qs.delete()
            self.stdout.write(f'Cleared {count} existing rates')

        try:
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                created = 0
                errors = 0
                for row in reader:
                    try:
                        TaxRate.objects.create(
                            tenant=tenant,
                            city=row.get('city', '').strip(),
                            county=row.get('county', '').strip(),
                            state=row.get('state', 'AR').strip().upper(),
                            zip_code=row.get('zip_code', '').strip(),
                            state_rate=Decimal(row.get('state_rate', '0')),
                            county_rate=Decimal(row.get('county_rate', '0')),
                            city_rate=Decimal(row.get('city_rate', '0')),
                            special_rate=Decimal(row.get('special_rate', '0')),
                        )
                        created += 1
                    except (InvalidOperation, ValueError, KeyError) as e:
                        errors += 1
                        self.stderr.write(f'Error on row: {row} — {e}')

                self.stdout.write(self.style.SUCCESS(
                    f'Loaded {created} tax rates ({errors} errors)'
                ))
        except FileNotFoundError:
            raise CommandError(f'File not found: {file_path}')
