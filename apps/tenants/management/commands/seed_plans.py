"""
Seed subscription plans into the database.

Usage:
    python manage.py seed_plans

Creates or updates the 4 standard subscription tiers:
- Trial (free, 30 days)
- Starter ($49/mo)
- Pro ($99/mo)
- Enterprise ($249/mo)

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from apps.tenants.models import SubscriptionPlan


PLANS = [
    {
        'slug': 'trial',
        'name': 'Trial',
        'monthly_price': Decimal('0.00'),
        'annual_price': None,
        'max_repairs_per_month': 50,
        'max_technicians': 2,
        'max_customers': 10,
        'max_storage_mb': 100,
        'trial_days': 30,
        'features': {
            'invoicing': True,
            'customer_portal': True,
            'rewards': False,
            'api_access': False,
            'priority_support': False,
            'custom_branding': False,
            'support': 'Email support',
        },
        'display_order': 0,
    },
    {
        'slug': 'starter',
        'name': 'Starter',
        'monthly_price': Decimal('49.00'),
        'annual_price': Decimal('470.00'),
        'max_repairs_per_month': 200,
        'max_technicians': 5,
        'max_customers': 50,
        'max_storage_mb': 500,
        'trial_days': 0,
        'features': {
            'invoicing': True,
            'customer_portal': True,
            'rewards': True,
            'api_access': False,
            'priority_support': False,
            'custom_branding': False,
            'support': 'Email support',
        },
        'display_order': 1,
    },
    {
        'slug': 'pro',
        'name': 'Pro',
        'monthly_price': Decimal('99.00'),
        'annual_price': Decimal('950.00'),
        'max_repairs_per_month': None,  # Unlimited
        'max_technicians': 15,
        'max_customers': None,  # Unlimited
        'max_storage_mb': 2000,
        'trial_days': 0,
        'features': {
            'invoicing': True,
            'customer_portal': True,
            'rewards': True,
            'api_access': False,
            'priority_support': False,
            'custom_branding': True,
            'support': 'Priority email support',
        },
        'display_order': 2,
    },
    {
        'slug': 'enterprise',
        'name': 'Enterprise',
        'monthly_price': Decimal('249.00'),
        'annual_price': Decimal('2390.00'),
        'max_repairs_per_month': None,  # Unlimited
        'max_technicians': None,  # Unlimited
        'max_customers': None,  # Unlimited
        'max_storage_mb': 10000,
        'trial_days': 0,
        'features': {
            'invoicing': True,
            'customer_portal': True,
            'rewards': True,
            'api_access': True,
            'priority_support': True,
            'custom_branding': True,
            'support': 'Priority email support',
        },
        'display_order': 3,
    },
]


class Command(BaseCommand):
    help = 'Seed the 4 standard subscription plans (Trial, Starter, Pro, Enterprise)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite existing plans (update if slug exists)',
        )
    
    def handle(self, *args, **options):
        force = options.get('force', False)
        created_count = 0
        updated_count = 0
        skipped_count = 0
        
        for plan_data in PLANS:
            slug = plan_data['slug']
            
            existing = SubscriptionPlan.objects.filter(slug=slug).first()
            
            if existing and not force:
                self.stdout.write(
                    self.style.WARNING(f"  Skipped '{slug}' — already exists (use --force to update)")
                )
                skipped_count += 1
                continue
            
            if existing and force:
                for key, value in plan_data.items():
                    setattr(existing, key, value)
                existing.save()
                self.stdout.write(
                    self.style.SUCCESS(f"  Updated '{slug}'")
                )
                updated_count += 1
            else:
                SubscriptionPlan.objects.create(**plan_data)
                self.stdout.write(
                    self.style.SUCCESS(f"  Created '{slug}'")
                )
                created_count += 1
        
        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}"
            )
        )
