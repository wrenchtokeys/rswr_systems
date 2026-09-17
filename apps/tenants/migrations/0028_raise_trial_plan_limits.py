"""Raise the existing Trial plan row to Starter's limits.

`seed_plans` never touches limits on a plan that already exists without
`--force` (PR #260), so editing the PLANS dict alone would leave every
deployed database on the old 10 customers / 50 jobs. This migration moves
the row itself.

Raise-only on purpose: if someone has already hand-tuned a limit above
these numbers, a deploy must not quietly walk it back down. `None` means
unlimited and always wins.
"""

from django.db import migrations

TRIAL_FLOOR = {
    'max_repairs_per_month': 200,
    'max_technicians': 5,
    'max_customers': 50,
    'max_storage_mb': 500,
}


def raise_trial_limits(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    for plan in SubscriptionPlan.objects.filter(slug='trial'):
        changed = []
        for field, floor in TRIAL_FLOOR.items():
            current = getattr(plan, field)
            if current is None:
                continue  # already unlimited
            if current < floor:
                setattr(plan, field, floor)
                changed.append(field)
        if changed:
            plan.save(update_fields=changed)


def noop_reverse(apps, schema_editor):
    """No down-migration.

    Lowering a live trial's caps would start hard-blocking shops that are
    mid-evaluation and already over the old numbers. Reverting the code is
    enough; the data stays generous.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0027_alter_tenant_subscription_status'),
    ]

    operations = [
        migrations.RunPython(raise_trial_limits, noop_reverse),
    ]
