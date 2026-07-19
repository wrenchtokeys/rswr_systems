"""
Invoices and emails now brand from the Tenant (logo + brand_color) instead of
the platform-wide EmailBrandingConfig singleton, which was leaking the
platform owner's logo/colors onto every shop's documents. Copy the
singleton's logo and header color onto the platform-owner tenant so its own
invoices/emails look the same after the switch.
"""
from django.db import migrations


def copy_platform_branding(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    EmailBrandingConfig = apps.get_model('core', 'EmailBrandingConfig')

    config = EmailBrandingConfig.objects.filter(singleton_id=True).first()
    if not config:
        return

    for tenant in Tenant.objects.filter(is_platform_owner=True):
        updates = []
        if not tenant.logo and config.logo:
            # Reference the same stored file; no copy needed.
            tenant.logo = config.logo.name
            updates.append('logo')
        if not tenant.brand_color and config.secondary_color:
            # secondary_color was the invoice header color pre-switch.
            tenant.brand_color = config.secondary_color
            updates.append('brand_color')
        if updates:
            tenant.save(update_fields=updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0019_tenant_brand_color'),
        ('core', '0004_emailbrandingconfig'),
    ]

    operations = [
        migrations.RunPython(copy_platform_branding, migrations.RunPython.noop),
    ]
