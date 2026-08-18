"""Fieldops S4: `job_rescheduled` now covers a booking, not just a swap.

S7 seeded this template for one writer — a manager dragging two of a tech's
jobs so they trade times. S4 adds a second: confirming a customer's requested
time onto an unscheduled job. Both are "your day changed", both go to the
assigned technician, and both should honour the same opt-out — so this reuses
the template instead of starting a second schedule-change stream a tech would
have to mute separately.

Only the SMS body changes here: it named a second job unconditionally, which
reads as a truncated sentence when there is only one. The HTML/text bodies
live in files (`emails/notifications/job_rescheduled.*`) and were generalized
in the same change with a `lead` variable and a guarded second row.
"""

from django.db import migrations


NEW_SMS = 'Schedule change {{ day }}: {{ summary }}.'
OLD_SMS = (
    'Schedule change {{ day }}: {{ first_job }} now {{ first_time }}, '
    '{{ second_job }} now {{ second_time }}.'
)


def widen(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(name='job_rescheduled').update(
        description='Technician notice that their booked times changed',
        sms_template=NEW_SMS,
    )


def narrow(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(name='job_rescheduled').update(
        description='Technician notice that two of their jobs traded times',
        sms_template=OLD_SMS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_job_rescheduled_template'),
    ]

    operations = [
        migrations.RunPython(widen, narrow),
    ]
