"""
Data migration: Set live Stripe Price IDs for subscription plans.

Monthly prices created in Stripe live mode on 2026-03-15.
Annual prices created on 2026-03-18.
"""

from django.db import migrations


def set_stripe_price_ids(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')

    plans = {
        'starter': {
            'stripe_price_id': 'price_1SzU3L1JK8PzBpGPu7PsHY12',           # $49/mo
            'stripe_annual_price_id': 'price_1TCOtV1JK8PzBpGPNnuzccVT',     # $470/yr
        },
        'pro': {
            'stripe_price_id': 'price_1SzU3i1JK8PzBpGPiCYpafCW',            # $99/mo
            'stripe_annual_price_id': 'price_1TCOtW1JK8PzBpGPIP7s5P5e',     # $950/yr
        },
        'enterprise': {
            'stripe_price_id': 'price_1SzU411JK8PzBpGPXPKeV9aG',            # $249/mo
            'stripe_annual_price_id': 'price_1TCOtW1JK8PzBpGP8Q2yCAwz',     # $2390/yr
        },
    }

    for slug, prices in plans.items():
        updated = SubscriptionPlan.objects.filter(slug=slug).update(**prices)
        if updated:
            print(f"  Set {slug}: monthly={prices['stripe_price_id']}, annual={prices['stripe_annual_price_id']}")


def clear_stripe_price_ids(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    SubscriptionPlan.objects.filter(
        slug__in=['starter', 'pro', 'enterprise']
    ).update(stripe_price_id='', stripe_annual_price_id='')


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0012_tenant_stripe_connected_at_and_more'),
    ]

    operations = [
        migrations.RunPython(set_stripe_price_ids, clear_stripe_price_ids),
    ]
