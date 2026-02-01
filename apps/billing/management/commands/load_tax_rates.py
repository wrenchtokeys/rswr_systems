"""
Load Arkansas sales tax rates from built-in JSON or external CSV.

Usage:
    python manage.py load_tax_rates              # loads from built-in JSON
    python manage.py load_tax_rates --file rates.csv  # loads from CSV
    python manage.py load_tax_rates --clear       # clear existing and reload

CSV format (header row required):
    city,county,state,total_rate
    Little Rock,Pulaski,AR,9.000

Author: Amelia (Clawdbot AI)
"""

import csv
import json
import os
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.models import TaxRate


# Path to the built-in JSON data file
DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data',
    'arkansas_tax_rates.json',
)

AR_STATE_RATE = Decimal('6.500')


class Command(BaseCommand):
    help = 'Load sales tax rates from built-in JSON or external CSV file.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=None,
            help='Path to a CSV file with tax rate data.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing tax rates before loading.',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        clear = options['clear']

        # Clear existing rates if requested
        if clear:
            count = TaxRate.objects.all().delete()[0]
            self.stdout.write(self.style.WARNING(f'Deleted {count} existing tax rate(s).'))

        # Load data
        if file_path:
            rates = self._load_csv(file_path)
        else:
            rates = self._load_json()

        if not rates:
            raise CommandError('No tax rate data found to load.')

        # Insert/update rates
        created = 0
        updated = 0

        for entry in rates:
            city = entry.get('city', '').strip()
            county = entry.get('county', '').strip()
            state = entry.get('state', 'AR').strip().upper()

            try:
                total_rate = Decimal(str(entry.get('total_rate', '0')))
            except (InvalidOperation, ValueError):
                self.stderr.write(
                    self.style.ERROR(f'Invalid total_rate for {city}, {state}: {entry.get("total_rate")}')
                )
                continue

            if not city:
                self.stderr.write(self.style.ERROR(f'Skipping entry with empty city: {entry}'))
                continue

            # Calculate component rates
            state_rate = Decimal(str(entry.get('state_rate', AR_STATE_RATE)))
            local_rate = total_rate - state_rate
            county_rate = Decimal(str(entry.get('county_rate', '0.000')))
            city_rate = Decimal(str(entry.get('city_rate', '0.000')))
            special_rate = Decimal(str(entry.get('special_rate', '0.000')))

            # If no component breakdown provided, put all local into county_rate
            if county_rate == 0 and city_rate == 0 and special_rate == 0 and local_rate > 0:
                county_rate = local_rate

            zip_code = entry.get('zip_code', '').strip()

            obj, was_created = TaxRate.objects.update_or_create(
                city__iexact=city,
                state=state,
                defaults={
                    'city': city,
                    'county': county,
                    'state': state,
                    'zip_code': zip_code,
                    'state_rate': state_rate,
                    'county_rate': county_rate,
                    'city_rate': city_rate,
                    'special_rate': special_rate,
                    'total_rate': total_rate,
                    'effective_date': timezone.now().date(),
                    'is_active': True,
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done! Created {created}, updated {updated} tax rate(s). '
            f'Total active: {TaxRate.objects.filter(is_active=True).count()}'
        ))

    def _load_json(self):
        """Load from the built-in JSON data file."""
        if not os.path.exists(DEFAULT_DATA_FILE):
            raise CommandError(f'Built-in data file not found: {DEFAULT_DATA_FILE}')

        self.stdout.write(f'Loading from {DEFAULT_DATA_FILE}')
        with open(DEFAULT_DATA_FILE, 'r') as f:
            return json.load(f)

    def _load_csv(self, path):
        """Load from an external CSV file."""
        if not os.path.exists(path):
            raise CommandError(f'CSV file not found: {path}')

        self.stdout.write(f'Loading from {path}')
        rates = []
        with open(path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rates.append(row)
        return rates
