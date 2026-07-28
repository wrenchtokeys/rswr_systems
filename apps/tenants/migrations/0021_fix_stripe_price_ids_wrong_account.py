"""
Data migration: replace subscription-plan Stripe price IDs that pointed at
the WRONG Stripe account.

Migration 0013 wrote price IDs with account suffix ...1JK8PzBpGP, but the
production platform account is acct_1SuOa20zbBWahwkN (suffix ...0zbBWahwkN).
Stripe price IDs are account-scoped, so every subscription checkout failed
with "No such price" — no shop has ever been able to subscribe.

The IDs below were verified directly against the live account on 2026-07-28
(amounts match SubscriptionPlan.monthly_price/annual_price):

    RS Systems Starter     $49/mo   price_1TBOVk0zbBWahwkNapnUrfVx
    RS Systems Pro         $99/mo   price_1TBOVn0zbBWahwkNgDKWvEe4
    RS Systems Enterprise  $249/mo  price_1TBOVq0zbBWahwkN1uZvyhin
    RS Systems Starter     $470/yr  price_1TDYDM0zbBWahwkNjiUGHCrv
    RS Systems Pro         $950/yr  price_1TDYDN0zbBWahwkNqbohtNbs
    RS Systems Enterprise  $2390/yr price_1TDYDN0zbBWahwkN9JM3oE05

After deploying, confirm with:  python manage.py set_stripe_prices --verify
"""

from django.db import migrations


PLANS = {
    'starter': {
        'stripe_price_id': 'price_1TBOVk0zbBWahwkNapnUrfVx',           # $49/mo
        'stripe_annual_price_id': 'price_1TDYDM0zbBWahwkNjiUGHCrv',    # $470/yr
    },
    'pro': {
        'stripe_price_id': 'price_1TBOVn0zbBWahwkNgDKWvEe4',           # $99/mo
        'stripe_annual_price_id': 'price_1TDYDN0zbBWahwkNqbohtNbs',    # $950/yr
    },
    'enterprise': {
        'stripe_price_id': 'price_1TBOVq0zbBWahwkN1uZvyhin',           # $249/mo
        'stripe_annual_price_id': 'price_1TDYDN0zbBWahwkN9JM3oE05',    # $2390/yr
    },
}


def set_correct_price_ids(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    for slug, prices in PLANS.items():
        updated = SubscriptionPlan.objects.filter(slug=slug).update(**prices)
        if updated:
            print(f"  Fixed {slug}: monthly={prices['stripe_price_id']}, "
                  f"annual={prices['stripe_annual_price_id']}")


def restore_previous_price_ids(apps, schema_editor):
    # Reverse restores the 0013 values (known-broken, but faithful reversal).
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    old = {
        'starter': ('price_1SzU3L1JK8PzBpGPu7PsHY12', 'price_1TCOtV1JK8PzBpGPNnuzccVT'),
        'pro': ('price_1SzU3i1JK8PzBpGPiCYpafCW', 'price_1TCOtW1JK8PzBpGPIP7s5P5e'),
        'enterprise': ('price_1SzU411JK8PzBpGPXPKeV9aG', 'price_1TCOtW1JK8PzBpGP8Q2yCAwz'),
    }
    for slug, (monthly, annual) in old.items():
        SubscriptionPlan.objects.filter(slug=slug).update(
            stripe_price_id=monthly, stripe_annual_price_id=annual,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0020_copy_platform_branding_to_owner_tenant'),
    ]

    operations = [
        migrations.RunPython(set_correct_price_ids, restore_previous_price_ids),
    ]
