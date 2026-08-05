# Deferred referral payout: referrals are recorded as PENDING at signup and
# only pay out (status → AWARDED) when the referred customer's first job
# completes. Existing rows were paid at signup under the old behavior, so
# they are backfilled as AWARDED to prevent the payout hook double-paying.

from django.db import migrations, models


def mark_existing_awarded(apps, schema_editor):
    Referral = apps.get_model('rewards_referrals', 'Referral')
    Referral.objects.all().update(status='AWARDED')


class Migration(migrations.Migration):

    dependencies = [
        ('rewards_referrals', '0018_customer_anchor_constraints'),
    ]

    operations = [
        migrations.AddField(
            model_name='referral',
            name='status',
            field=models.CharField(
                choices=[('PENDING', 'Pending first job'), ('AWARDED', 'Awarded')],
                default='PENDING',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='referral',
            name='awarded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_awarded, migrations.RunPython.noop),
    ]
