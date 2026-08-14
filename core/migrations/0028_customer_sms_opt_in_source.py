# N4 (SMS opt-in compliance): record WHO recorded consent. Everything opted
# in before this migration came through shop-side surfaces (customer form,
# invoice-send dialog), so existing consent backfills as SHOP-attested.
# First-party consent (the customer's own screen — public invoice page)
# writes CUSTOMER and is what toll-free registration v2 points at.

from django.db import migrations, models


def backfill_shop_source(apps, schema_editor):
    Customer = apps.get_model('core', 'Customer')
    Customer.objects.filter(sms_opt_in=True, sms_opt_in_source='').update(
        sms_opt_in_source='SHOP'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_assignment_notification_channels'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='sms_opt_in_source',
            field=models.CharField(
                blank=True,
                choices=[
                    ('SHOP', 'Shop recorded (customer agreed off-platform)'),
                    ('CUSTOMER', 'Customer self-opt-in (first-party)'),
                ],
                default='',
                help_text="Who recorded the SMS consent — first-party (customer's own screen) or shop-attested",
                max_length=10,
            ),
        ),
        migrations.RunPython(backfill_shop_source, migrations.RunPython.noop),
    ]
