# Backfill Technician.can_replace for replacement-offering shops.
#
# can_replace defaults to False, which was fine while replacement views were
# owner/manager-only. Now that technicians can work replacements directly,
# every existing technician at a shop whose services_offered includes
# replacements would stay locked out without this backfill. Owners can still
# switch individual technicians off in Team settings.

from django.db import migrations


def backfill_can_replace(apps, schema_editor):
    Technician = apps.get_model('technician_portal', 'Technician')
    Technician.objects.filter(
        is_active=True,
        tenant__services_offered__in=['replacement', 'both'],
        can_replace=False,
    ).update(can_replace=True)


def noop(apps, schema_editor):
    # Irreversible in spirit (we can't know which techs were manually False),
    # but safe to leave values in place on rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0043_simplify_warranty_policies'),
        ('tenants', '0018_tenant_services_offered'),
    ]

    operations = [
        migrations.RunPython(backfill_can_replace, noop),
    ]
