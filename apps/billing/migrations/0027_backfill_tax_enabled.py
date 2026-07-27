from django.db import migrations


def backfill_tax_enabled(apps, schema_editor):
    """
    Sync BillingConfig.tax_enabled to actual current behavior.

    Before this release, TaxService decided whether tax applied by checking
    for active TaxRate rows and IGNORED BillingConfig.tax_enabled. After this
    release, tax_enabled is the single source of truth. Without this backfill,
    a shop whose flag disagrees with its TaxRate rows would silently start or
    stop charging tax on deploy.

    tax_configured deliberately stays False for everyone: every existing shop
    sees the "set up sales tax" banner once and confirms its setting.
    """
    BillingConfig = apps.get_model('billing', 'BillingConfig')
    TaxRate = apps.get_model('billing', 'TaxRate')

    for config in BillingConfig.objects.exclude(tenant__isnull=True):
        charging_now = TaxRate.objects.filter(
            tenant=config.tenant_id, is_active=True
        ).exists()
        if config.tax_enabled != charging_now:
            config.tax_enabled = charging_now
            config.save(update_fields=['tax_enabled'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0026_billingconfig_tax_configured_invoicelineitem_taxable_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_tax_enabled, migrations.RunPython.noop),
    ]
