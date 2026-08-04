# Customer-anchored loyalty, step 2 of 3: data backfill + balance merge.
#
# 1. PointTransaction.customer is backfilled from customer_user.customer.
# 2. Reward rows are merged per Customer: a company whose portal users each
#    held their own balance gets ONE row with the SUMMED balance. The oldest
#    row survives; RewardRedemption FKs are repointed to the survivor BEFORE
#    duplicates are deleted (RewardRedemption.reward is CASCADE — deleting
#    first would silently destroy redemption/fulfillment history).
#
# Irreversible by design (reverse = noop): once balances are merged there is
# no per-user split to restore. Run `reconcile_loyalty_balances --fix` BEFORE
# deploying so no pre-existing drift is baked into the merge.

import logging

from django.db import migrations
from django.db.models import Count

logger = logging.getLogger(__name__)


def backfill_and_merge(apps, schema_editor):
    Reward = apps.get_model('rewards_referrals', 'Reward')
    PointTransaction = apps.get_model('rewards_referrals', 'PointTransaction')
    RewardRedemption = apps.get_model('rewards_referrals', 'RewardRedemption')
    CustomerUser = apps.get_model('customer_portal', 'CustomerUser')
    Customer = apps.get_model('core', 'Customer')

    cu_to_customer = dict(CustomerUser.objects.values_list('id', 'customer_id'))
    customer_tenants = dict(Customer.objects.values_list('id', 'tenant_id'))

    # --- 1. Ledger backfill -------------------------------------------------
    for cu_id, customer_id in cu_to_customer.items():
        PointTransaction.objects.filter(
            customer_user_id=cu_id, customer_id__isnull=True,
        ).update(customer_id=customer_id)

    orphaned = PointTransaction.objects.filter(customer_id__isnull=True).count()
    if orphaned:
        # Should be impossible (customer_user was non-null before 0016), but
        # 0018 makes customer non-null — fail loudly rather than there.
        raise RuntimeError(
            f'{orphaned} PointTransaction rows could not be assigned a customer.'
        )

    # --- 2. Reward merge ----------------------------------------------------
    rewards_by_customer = {}
    for reward in Reward.objects.order_by('created_at', 'pk'):
        customer_id = cu_to_customer.get(reward.customer_user_id)
        if customer_id is None:
            raise RuntimeError(
                f'Reward pk={reward.pk} has no resolvable customer '
                f'(customer_user_id={reward.customer_user_id}).'
            )
        rewards_by_customer.setdefault(customer_id, []).append(reward)

    for customer_id, rewards in rewards_by_customer.items():
        survivor, dupes = rewards[0], rewards[1:]
        survivor.customer_id = customer_id
        survivor.points = sum(r.points for r in rewards)
        if survivor.tenant_id is None:
            survivor.tenant_id = customer_tenants.get(customer_id)
        survivor.save(update_fields=['customer', 'points', 'tenant'])

        if dupes:
            dupe_ids = [r.pk for r in dupes]
            repointed = RewardRedemption.objects.filter(
                reward_id__in=dupe_ids,
            ).update(reward_id=survivor.pk)
            Reward.objects.filter(pk__in=dupe_ids).delete()
            logger.info(
                'Loyalty merge: customer %s — merged %d reward rows into pk=%s '
                '(balance %d, %d redemptions repointed)',
                customer_id, len(rewards), survivor.pk, survivor.points, repointed,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('rewards_referrals', '0016_customer_anchor_schema'),
    ]

    operations = [
        migrations.RunPython(backfill_and_merge, migrations.RunPython.noop),
    ]
