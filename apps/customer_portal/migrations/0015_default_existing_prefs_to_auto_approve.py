# One-time flip of existing preference rows to AUTO_APPROVE.
#
# Every existing CustomerRepairPreference row was created implicitly (by
# _save_billing_preferences when an owner set any billing field, or by the
# customer-portal preferences view) with the old REQUIRE_APPROVAL default —
# no one ever explicitly chose to require approval. Now that the default is
# AUTO_APPROVE, align existing rows so shop-created work auto-approves
# everywhere. From here on, REQUIRE_APPROVAL is a genuinely explicit choice
# (the future customer-portal "customer prefers to approve work" setting).

from django.db import migrations


def flip_to_auto_approve(apps, schema_editor):
    CustomerRepairPreference = apps.get_model('customer_portal', 'CustomerRepairPreference')
    CustomerRepairPreference.objects.filter(
        field_repair_approval_mode='REQUIRE_APPROVAL'
    ).update(field_repair_approval_mode='AUTO_APPROVE')


def noop(apps, schema_editor):
    # Irreversible in spirit — we can't know which rows were explicit.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('customer_portal', '0014_alter_customerrepairpreference_field_repair_approval_mode'),
    ]

    operations = [
        migrations.RunPython(flip_to_auto_approve, noop),
    ]
