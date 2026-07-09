# Convert Customer.email == '' to NULL.
#
# The unique_customer_email_per_tenant constraint only exempts NULL emails
# (condition=Q(email__isnull=False)). Customers created through forms with a
# blank email were saved with '' — so the FIRST no-email customer per tenant
# occupied the '' slot and every subsequent no-email customer (or edit) hit an
# IntegrityError → production 500. Customer.save() now normalizes '' → None;
# this migration fixes rows that already exist.

from django.db import migrations


def null_blank_emails(apps, schema_editor):
    Customer = apps.get_model('core', 'Customer')
    Customer.objects.filter(email='').update(email=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_relax_phone_validation'),
    ]

    operations = [
        migrations.RunPython(null_blank_emails, noop),
    ]
