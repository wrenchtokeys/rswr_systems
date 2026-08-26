"""
Every crop that existed before P3 was placed by a technician's finger.

confirmed_by_human defaults to False so a machine suggestion is untrusted
unless something says otherwise — which makes the default wrong for every
row already in the table. Left unfixed, P4's export would treat the entire
hand-labeled P1/P2 dataset as unconfirmed guesses, which is exactly
backwards: those rows are the good ones.

See docs/strategy/PHOTO_ML_SESSIONS.md.
"""
from django.db import migrations


def mark_existing_as_confirmed(apps, schema_editor):
    RepairPhotoCrop = apps.get_model('technician_portal', 'RepairPhotoCrop')
    RepairPhotoCrop.objects.update(confirmed_by_human=True)


def unmark(apps, schema_editor):
    # Reversing can only restore the field default; the distinction this
    # migration adds does not exist in the earlier schema.
    RepairPhotoCrop = apps.get_model('technician_portal', 'RepairPhotoCrop')
    RepairPhotoCrop.objects.update(confirmed_by_human=False)


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0058_photocrop_suggestions'),
    ]

    operations = [
        migrations.RunPython(mark_existing_as_confirmed, unmark),
    ]
