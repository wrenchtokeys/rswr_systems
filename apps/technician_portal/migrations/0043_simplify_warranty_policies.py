# Data migration: collapse per-damage-type warranty policies into one
# 'repairs' policy per scope, and seed a 'replacements' policy per tenant.

from collections import defaultdict

from django.db import migrations

REPLACEMENT_SEED_NAME = 'Replacement Warranty'
REPAIR_SEED_NAME = 'Standard Warranty'


def simplify_policies(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    WarrantyPolicy = apps.get_model('technician_portal', 'WarrantyPolicy')

    # ------------------------------------------------------------------
    # 1. Collapse legacy damage-type / 'all_repairs' policies → 'repairs'.
    #    Within each (tenant, customer) scope keep ONE active policy —
    #    prefer the old 'all_repairs' default — and deactivate the rest.
    # ------------------------------------------------------------------
    groups = defaultdict(list)
    for policy in WarrantyPolicy.objects.exclude(applies_to='replacements').order_by('pk'):
        groups[(policy.tenant_id, policy.customer_id)].append(policy)

    for policies in groups.values():
        pool = [p for p in policies if p.is_active] or policies

        def preference(p):
            if p.applies_to == 'all_repairs' and p.is_default:
                rank = 0
            elif p.applies_to == 'all_repairs':
                rank = 1
            elif p.is_default:
                rank = 2
            else:
                rank = 3
            return (rank, p.pk)

        canonical = sorted(pool, key=preference)[0]
        for p in policies:
            p.applies_to = 'repairs'
            if p.pk != canonical.pk:
                p.is_active = False
            p.save(update_fields=['applies_to', 'is_active'])

    # ------------------------------------------------------------------
    # 2. Every tenant gets a tenant-wide policy for BOTH service types.
    # ------------------------------------------------------------------
    for tenant in Tenant.objects.all():
        if not WarrantyPolicy.objects.filter(
            tenant=tenant, customer__isnull=True, applies_to='repairs',
        ).exists():
            WarrantyPolicy.objects.create(
                tenant=tenant,
                name=_unique_name(WarrantyPolicy, tenant, REPAIR_SEED_NAME),
                applies_to='repairs',
                duration_type='custom_days',
                duration_days=365,
                coverage_description=(
                    'One year warranty on all repairs against defects '
                    'in workmanship.'
                ),
                covers_labor=True,
                covers_materials=True,
                is_default=False,
                is_active=True,
            )

        if not WarrantyPolicy.objects.filter(
            tenant=tenant, customer__isnull=True, applies_to='replacements',
        ).exists():
            WarrantyPolicy.objects.create(
                tenant=tenant,
                name=_unique_name(WarrantyPolicy, tenant, REPLACEMENT_SEED_NAME),
                applies_to='replacements',
                duration_type='custom_days',
                duration_days=365,
                coverage_description=(
                    'One year warranty on all glass replacements against '
                    'leaks and defects in workmanship.'
                ),
                covers_labor=True,
                covers_materials=True,
                is_default=False,
                is_active=True,
            )


def _unique_name(WarrantyPolicy, tenant, base_name):
    """(tenant, name) is unique — suffix if the seed name is taken."""
    name = base_name
    counter = 2
    while WarrantyPolicy.objects.filter(tenant=tenant, name=name).exists():
        name = f'{base_name} {counter}'
        counter += 1
    return name


def reverse_simplify(apps, schema_editor):
    """Best-effort reverse: restore 'all_repairs' and drop seeded replacement policies."""
    WarrantyPolicy = apps.get_model('technician_portal', 'WarrantyPolicy')
    WarrantyPolicy.objects.filter(
        applies_to='replacements',
        name__startswith=REPLACEMENT_SEED_NAME,
    ).delete()
    WarrantyPolicy.objects.filter(applies_to='repairs').update(applies_to='all_repairs')


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0042_replacement_is_warranty_claim_and_more'),
        ('tenants', '0001_create_tenant_and_membership'),
    ]

    operations = [
        migrations.RunPython(simplify_policies, reverse_simplify),
    ]
