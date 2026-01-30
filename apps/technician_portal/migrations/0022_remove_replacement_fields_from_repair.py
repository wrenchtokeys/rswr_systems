# Part 2: Remove replacement-specific columns from Repair, update indexes.
# Split into separate migration to avoid PostgreSQL "pending trigger events" issue.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_expand_data_model'),
        ('technician_portal', '0021_replacement_alter_repair_options_and_more'),
    ]

    operations = [
        # Remove replacement-specific columns from Repair
        migrations.RemoveField(
            model_name='repair',
            name='adas_calibration_cost',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='glass_position',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='glass_type',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='labor_cost',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='nags_number',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='parts_cost',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='requires_adas_calibration',
        ),
        migrations.RemoveField(
            model_name='repair',
            name='service_type',
        ),
        
        # Update vehicle FK related_name
        migrations.AlterField(
            model_name='repair',
            name='vehicle',
            field=models.ForeignKey(
                blank=True,
                help_text='Link to vehicle record (optional — unit_number still works for fleets)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='%(class)ss',
                to='core.vehicle',
            ),
        ),
        
        # Add new indexes
        migrations.AddIndex(
            model_name='repair',
            index=models.Index(fields=['service_date'], name='technician__service_961d7d_idx'),
        ),
        migrations.AddIndex(
            model_name='replacement',
            index=models.Index(fields=['queue_status'], name='technician__queue_s_7c2ea2_idx'),
        ),
        migrations.AddIndex(
            model_name='replacement',
            index=models.Index(fields=['customer', 'unit_number'], name='technician__custome_bf28ec_idx'),
        ),
        migrations.AddIndex(
            model_name='replacement',
            index=models.Index(fields=['technician'], name='technician__technic_86d4f6_idx'),
        ),
        migrations.AddIndex(
            model_name='replacement',
            index=models.Index(fields=['service_date'], name='technician__service_2f51df_idx'),
        ),
    ]
