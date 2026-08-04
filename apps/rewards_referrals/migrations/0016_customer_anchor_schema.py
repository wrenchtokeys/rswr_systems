# Customer-anchored loyalty, step 1 of 3: additive schema changes.
#
# Adds the nullable Reward.customer / PointTransaction.customer FKs and
# demotes PointTransaction.customer_user to a nullable SET_NULL attribution
# field. Data backfill happens in 0017; constraints flip in 0018.
#
# The customer_user demotion also fixes a data-loss bug: purge_deleted_records
# hard-deletes CustomerUser rows 30 days after portal-access removal, and the
# previous CASCADE destroyed the customer's entire point ledger with them.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rewards_referrals', '0015_pointtransaction_related_replacement_and_more'),
        ('core', '0024_remove_customer_unique_customer_email_per_tenant_and_more'),
        ('customer_portal', '0016_customeruser_deactivated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='reward',
            name='customer',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='rewards',
                to='core.customer',
            ),
        ),
        migrations.AddField(
            model_name='pointtransaction',
            name='customer',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='point_transactions',
                to='core.customer',
            ),
        ),
        migrations.AlterField(
            model_name='pointtransaction',
            name='customer_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='point_transactions',
                help_text='Portal user who triggered this transaction, if any (attribution only)',
                to='customer_portal.customeruser',
            ),
        ),
        migrations.AddField(
            model_name='loyaltyconfig',
            name='show_balance_in_emails',
            field=models.BooleanField(
                default=True,
                help_text='Include the customer point balance in invoice and review emails',
            ),
        ),
    ]
