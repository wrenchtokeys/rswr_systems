"""Fieldops S4: let a fleet ask for a window to the minute.

The first cut offered three coarse buckets (morning / afternoon / anytime).
That is the wrong granularity for the customers this portal actually serves:
a trucking company whose unit rolls at 06:00 and sits in the yard from 04:30
to 05:45 cannot express that as "morning", and a shop reading "morning"
cannot tell it apart from a retail customer with no constraint at all.

`preferred_window='EXACT'` now reads these two columns instead of a fixed hour
pair. `preferred_time_end` doubles as a fleet's hard cutoff — "done by 05:45"
is the same fact as "the window ends at 05:45".

Additive only, both job tables. Existing rows keep their preset window and are
untouched.
"""

from django.db import migrations, models


PREFERRED_WINDOW_CHOICES = [
    ('MORNING', 'Morning (8:00 AM – 12:00 PM)'),
    ('AFTERNOON', 'Afternoon (12:00 PM – 5:00 PM)'),
    ('ANYTIME', 'Any time that day'),
    ('EXACT', 'A specific window'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0055_customer_time_preference'),
    ]

    operations = [
        migrations.AddField(
            model_name='repair',
            name='preferred_time_start',
            field=models.TimeField(
                blank=True, null=True,
                help_text='Earliest the vehicle is available. Only with window=EXACT.'),
        ),
        migrations.AddField(
            model_name='repair',
            name='preferred_time_end',
            field=models.TimeField(
                blank=True, null=True,
                help_text="Latest the work can run to — a fleet's hard cutoff."),
        ),
        migrations.AddField(
            model_name='replacement',
            name='preferred_time_start',
            field=models.TimeField(
                blank=True, null=True,
                help_text='Earliest the vehicle is available. Only with window=EXACT.'),
        ),
        migrations.AddField(
            model_name='replacement',
            name='preferred_time_end',
            field=models.TimeField(
                blank=True, null=True,
                help_text="Latest the work can run to — a fleet's hard cutoff."),
        ),
        migrations.AlterField(
            model_name='repair',
            name='preferred_window',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=PREFERRED_WINDOW_CHOICES,
                help_text='Part of the day the customer asked for.'),
        ),
        migrations.AlterField(
            model_name='replacement',
            name='preferred_window',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=PREFERRED_WINDOW_CHOICES,
                help_text='Part of the day the customer asked for.'),
        ),
    ]
