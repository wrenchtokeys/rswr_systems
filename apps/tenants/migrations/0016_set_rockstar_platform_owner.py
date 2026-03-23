"""Set Rockstar Windshield Repair as platform owner with permanent pro plan."""

from django.db import migrations


def set_platform_owner(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    try:
        tenant = Tenant.objects.get(slug='rockstar-windshield')
        tenant.is_platform_owner = True
        tenant.plan = 'pro'
        tenant.subscription_status = 'active'
        tenant.save(update_fields=['is_platform_owner', 'plan', 'subscription_status'])
    except Tenant.DoesNotExist:
        pass  # Not on this environment


def unset_platform_owner(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    try:
        tenant = Tenant.objects.get(slug='rockstar-windshield')
        tenant.is_platform_owner = False
        tenant.save(update_fields=['is_platform_owner'])
    except Tenant.DoesNotExist:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('tenants', '0015_add_is_platform_owner'),
    ]

    operations = [
        migrations.RunPython(set_platform_owner, unset_platform_owner),
    ]
