"""
Data migration: Seed the 4 standard subscription plans.

Trial, Starter, Pro, Enterprise.
"""

from decimal import Decimal
from django.db import migrations


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
            'rewards': False,
            'api_access': False,
            'priority_support': False,
            'custom_branding': False,
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
            'rewards': True,
            'api_access': False,
            'priority_support': False,
            'custom_branding': False,
        },
        'display_order': 1,
    },
    {
        'slug': 'pro',
        'name': 'Pro',
        'monthly_price': Decimal('99.00'),
        'annual_price': Decimal('950.00'),
        'max_repairs_per_month': None,
        'max_technicians': 15,
        'max_customers': None,
        'max_storage_mb': 2000,
        'trial_days': 0,
        'features': {
            'invoicing': True,
            'rewards': True,
            'api_access': False,
            'priority_support': False,
            'custom_branding': True,
        },
        'display_order': 2,
    },
    {
        'slug': 'enterprise',
        'name': 'Enterprise',
        'monthly_price': Decimal('249.00'),
        'annual_price': Decimal('2390.00'),
        'max_repairs_per_month': None,
        'max_technicians': None,
        'max_customers': None,
        'max_storage_mb': 10000,
        'trial_days': 0,
        'features': {
            'invoicing': True,
            'rewards': True,
            'api_access': True,
            'priority_support': True,
            'custom_branding': True,
        },
        'display_order': 3,
    },
]


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    for plan_data in PLANS:
        SubscriptionPlan.objects.update_or_create(
            slug=plan_data['slug'],
            defaults=plan_data,
        )


def remove_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    SubscriptionPlan.objects.filter(
        slug__in=['trial', 'starter', 'pro', 'enterprise']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_add_subscription_plan_model_and_billing_fields'),
    ]

    operations = [
        migrations.RunPython(seed_plans, remove_plans),
    ]
