"""Re-key individuals' progressive-pricing counters onto their actual vehicle.

``UnitRepairCount.unit_number`` is the vehicle key. An individual's job leaves
the ``unit_number`` COLUMN blank (their car lives in vehicle_year/make/model),
so every car a person owns collapsed into one row keyed ''. A customer with two
cars had one shared counter: the second car's first repair counted as their
third.

``UnitRepairCount.key_for()`` now builds the key for every write path. This
rebuilds the rows already on file.

Only individual (RETAIL/WALK_IN) customers are touched. A fleet's key is its
unit number either way, so fleet rows are left exactly as they are — including
any hand-adjusted counts, which a blanket rebuild would silently discard.
"""
from django.db import migrations


# Mirrors core.Customer.INDIVIDUAL_TYPES, which a historical model can't reach.
INDIVIDUAL_TYPES = ('RETAIL', 'WALK_IN')


def _vehicle_key(repair, is_individual):
    """Historical-model stand-in for UnitRepairCount.key_for().

    Mirrors it exactly, including the fleet branch this migration never takes,
    so tests/test_vehicle_backfill_migrations.py can hold the two in step.
    """
    unit = (repair.unit_number or '').strip()
    if not is_individual:
        return unit[:50]
    parts = [repair.vehicle_year, repair.vehicle_make, repair.vehicle_model]
    described = ' '.join(str(p).strip() for p in parts if p).strip()
    return (described or unit)[:50]


def rekey_individual_counters(apps, schema_editor):
    Customer = apps.get_model('core', 'Customer')
    Repair = apps.get_model('technician_portal', 'Repair')
    UnitRepairCount = apps.get_model('technician_portal', 'UnitRepairCount')

    individuals = Customer.objects.filter(customer_type__in=INDIVIDUAL_TYPES)

    for customer in individuals.iterator(chunk_size=200):
        # Historical models carry a plain manager, so soft-deleted repairs are
        # visible here — exclude them to match rebuild_unit_repair_counts().
        completed = Repair.objects.filter(
            customer=customer,
            tenant_id=customer.tenant_id,
            queue_status='COMPLETED',
            deleted_at__isnull=True,
        )

        counts = {}
        for repair in completed.iterator(chunk_size=500):
            key = _vehicle_key(repair, is_individual=True)
            counts[key] = counts.get(key, 0) + 1

        existing = UnitRepairCount.objects.filter(customer=customer)
        if not existing.exists() and not counts:
            continue

        # Rebuild wholesale: the old rows are keyed on a column that never
        # identified this customer's vehicles, so there is nothing in them
        # worth merging.
        existing.delete()
        UnitRepairCount.objects.bulk_create([
            UnitRepairCount(
                tenant_id=customer.tenant_id,
                customer=customer,
                unit_number=unit_number,
                repair_count=count,
            )
            for unit_number, count in counts.items()
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0050_merge_20260810_1635'),
        # Needs Customer.customer_type, added in core/0011.
        ('core', '0011_expand_data_model'),
    ]

    operations = [
        migrations.RunPython(
            rekey_individual_counters,
            migrations.RunPython.noop,
        ),
    ]
