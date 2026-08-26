"""
Let a photo crop hang off a Replacement as well as a Repair.

Purely additive and safe on existing data: every pre-P4a row has `repair`
set and `replacement` null, which is exactly what the new CheckConstraint
requires. Nothing is backfilled and no file moves.

The point is the negative class. A crop of a repair is by definition a photo
of damage that WAS repaired, so a repairs-only table could only ever hold one
class of the repairable-vs-not dataset this arc exists to build. See
docs/strategy/PHOTO_ML_SESSIONS.md (P4a).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0059_backfill_confirmed_crops'),
        ('tenants', '0027_alter_tenant_subscription_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='repairphotocrop',
            name='replacement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='photo_crops', to='technician_portal.replacement'),
        ),
        migrations.AlterField(
            model_name='repairphotocrop',
            name='repair',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='photo_crops', to='technician_portal.repair'),
        ),
        migrations.AddConstraint(
            model_name='repairphotocrop',
            constraint=models.UniqueConstraint(fields=('replacement', 'source_field'), name='uniq_photocrop_per_replacement_field'),
        ),
        migrations.AddConstraint(
            model_name='repairphotocrop',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('repair__isnull', False), ('replacement__isnull', True)), models.Q(('repair__isnull', True), ('replacement__isnull', False)), _connector='OR'), name='photocrop_exactly_one_service'),
        ),
    ]
