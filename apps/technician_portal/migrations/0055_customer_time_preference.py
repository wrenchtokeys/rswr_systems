"""Fieldops S4: what the customer asked for, kept apart from what was booked.

Additive only, both job tables. `preferred_date` / `preferred_window` record a
customer's wish; `scheduled_for` (S1) records the shop's promise. They are
deliberately separate columns because a customer repair request auto-approves
to APPROVED on submit, and APPROVED is on the day sheet — writing the wish
straight into `scheduled_for` would publish an appointment nobody agreed to.
"""

from django.db import migrations, models


PREFERRED_WINDOW_CHOICES = [
    ('MORNING', 'Morning (8:00 AM – 12:00 PM)'),
    ('AFTERNOON', 'Afternoon (12:00 PM – 5:00 PM)'),
    ('ANYTIME', 'Any time that day'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0054_service_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='repair',
            name='preferred_date',
            field=models.DateField(
                blank=True, null=True,
                help_text='Day the customer asked for. A request, not a booking.'),
        ),
        migrations.AddField(
            model_name='repair',
            name='preferred_window',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=PREFERRED_WINDOW_CHOICES,
                help_text='Part of the day the customer asked for.'),
        ),
        migrations.AddField(
            model_name='replacement',
            name='preferred_date',
            field=models.DateField(
                blank=True, null=True,
                help_text='Day the customer asked for. A request, not a booking.'),
        ),
        migrations.AddField(
            model_name='replacement',
            name='preferred_window',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=PREFERRED_WINDOW_CHOICES,
                help_text='Part of the day the customer asked for.'),
        ),
    ]
