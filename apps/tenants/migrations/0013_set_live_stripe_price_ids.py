"""
Data migration: Set live Stripe Price IDs for subscription plans.

These price IDs were created in Stripe live mode on 2026-03-15.
"""

from django.db import migrations


def set_stripe_price_ids(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')

    price_map = {
        'starter': 'price_1SzU3L1JK8PzBpGPu7PsHY12',      # $49/mo
        'pro': 'price_1SzU3i1JK8PzBpGPiCYpafCW',            # $99/mo
        'enterprise': 'price_1SzU411JK8PzBpGPXPKeV9aG',      # $249/mo
    }

    for slug, price_id in price_map.items():
        updated = SubscriptionPlan.objects.filter(slug=slug).update(
            stripe_price_id=price_id
        )
        if updated:
            print(f"  Set {slug} stripe_price_id = {price_id}")


def clear_stripe_price_ids(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    SubscriptionPlan.objects.filter(
        slug__in=['starter', 'pro', 'enterprise']
    ).update(stripe_price_id='')


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0012_tenant_stripe_connected_at_and_more'),
    ]

    operations = [
        migrations.RunPython(set_stripe_price_ids, clear_stripe_price_ids),
    ]
