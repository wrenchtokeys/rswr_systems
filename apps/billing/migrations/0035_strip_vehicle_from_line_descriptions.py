"""Drop the vehicle segment from existing invoice line descriptions.

Every surface that renders ``InvoiceLineItem.description`` also renders the
vehicle in its own column or sub-line, so a description that named the vehicle
printed it twice on the same row:

    Vehicle              Description
    2022 Toyota Camry    Windshield repair - 2022 Toyota Camry - Crack
    (walk-in, no unit)   Rear Window Replacement - Unit #N/A

``get_invoice_description()`` no longer emits it, which fixes every invoice
from here on. This migration handles the ones already on file.

Scope, deliberately narrow:

* Only invoices that are still live. PAID and CANCELLED invoices are settled
  documents and are never rewritten — the same rule invoice_sync follows.
  Soft-deleted invoices are skipped for the same reason.
* Only line items with a linked job, since the job is the authority on how its
  customer names the vehicle.
* Only ``' - '``-delimited segments that EXACTLY match one of that job's known
  vehicle spellings. Anything an owner typed by hand survives untouched, and
  the leading service name is never removed.

Reverse is a no-op: the vehicle is still on the job and still rendered in its
own column, so there is nothing to restore.
"""
from django.db import migrations


# Customer types that are a person with their own vehicle rather than a fleet.
# Mirrors core.Customer.INDIVIDUAL_TYPES, which a historical model can't reach.
INDIVIDUAL_TYPES = ('RETAIL', 'WALK_IN')

SETTLED_STATUSES = ('PAID', 'CANCELLED')


def _vehicle_segments(job):
    """Every spelling of this job's vehicle that a description may contain.

    Covers the two legacy formats ('Unit #100', 'Unit #N/A', and the
    'Unit #Silver Camry' that started this whole bug) plus the bare identifier.
    """
    unit = (job.unit_number or '').strip()
    parts = [job.vehicle_year, job.vehicle_make, job.vehicle_model]
    described = ' '.join(str(p).strip() for p in parts if p).strip()

    is_individual = bool(
        job.customer_id
        and job.customer
        and job.customer.customer_type in INDIVIDUAL_TYPES
    )
    identifier = (described or unit) if is_individual else unit

    candidates = {'Unit #', 'Unit #N/A'}
    for value in (unit, described, identifier):
        if value:
            candidates.add(value)
            candidates.add(f'Unit #{value}')
    return candidates


def _strip_vehicle(description, segments):
    """Remove vehicle-only segments, never the leading service name."""
    parts = description.split(' - ')
    kept = [parts[0]] + [p for p in parts[1:] if p.strip() not in segments]
    return ' - '.join(kept)


def strip_vehicle_from_descriptions(apps, schema_editor):
    InvoiceLineItem = apps.get_model('billing', 'InvoiceLineItem')

    line_items = (
        InvoiceLineItem.objects
        .exclude(invoice__status__in=SETTLED_STATUSES)
        .filter(invoice__deleted_at__isnull=True)
        .exclude(repair__isnull=True, replacement__isnull=True)
        .select_related(
            'repair', 'repair__customer',
            'replacement', 'replacement__customer',
        )
    )

    updated = []
    for line in line_items.iterator(chunk_size=500):
        job = line.repair or line.replacement
        if job is None or not line.description:
            continue
        cleaned = _strip_vehicle(line.description, _vehicle_segments(job))
        if cleaned != line.description:
            line.description = cleaned
            updated.append(line)

    if updated:
        InvoiceLineItem.objects.bulk_update(updated, ['description'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0034_platformconfig_default_fee_fixed_cents_and_more'),
        ('technician_portal', '0050_merge_20260810_1635'),
    ]

    operations = [
        migrations.RunPython(
            strip_vehicle_from_descriptions,
            migrations.RunPython.noop,
        ),
    ]
