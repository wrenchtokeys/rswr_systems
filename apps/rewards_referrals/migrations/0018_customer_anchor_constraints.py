# Customer-anchored loyalty, step 3 of 3: constraints flip.
#
# customer becomes non-null on Reward + PointTransaction, uniqueness moves
# from per-CustomerUser to per-Customer, Reward.customer_user is dropped
# (post-merge a company balance has no single owner), and the ledger index
# follows the new anchor.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rewards_referrals', '0017_customer_anchor_backfill'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='pointtransaction',
            name='rewards_ref_custome_7ea25f_idx',
        ),
        migrations.RemoveConstraint(
            model_name='reward',
            name='unique_reward_per_customer_user',
        ),
        migrations.RemoveField(
            model_name='reward',
            name='customer_user',
        ),
        migrations.AlterField(
            model_name='reward',
            name='customer',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='rewards',
                to='core.customer',
            ),
        ),
        migrations.AlterField(
            model_name='pointtransaction',
            name='customer',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='point_transactions',
                to='core.customer',
            ),
        ),
        migrations.AddConstraint(
            model_name='reward',
            constraint=models.UniqueConstraint(
                fields=('customer',), name='unique_reward_per_customer',
            ),
        ),
        migrations.AddIndex(
            model_name='pointtransaction',
            index=models.Index(
                fields=['customer', '-created_at'], name='idx_pt_customer_created',
            ),
        ),
    ]
