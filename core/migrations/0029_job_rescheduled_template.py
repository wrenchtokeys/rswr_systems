"""Fieldops S7: the first schedule-change notification template.

Seeds ``job_rescheduled`` — sent to the assigned technician when a manager
swaps two of their appointments on the day view.

Category is ``assignment`` deliberately: it reuses the existing
``TechnicianNotificationPreference`` opt-out field, so a tech who has muted
assignment mail is not surprised by a new un-mutable channel. A new category
would need a matching preference field or techs could not opt out at all.

Priority is MEDIUM, not HIGH: HIGH maps to ['in_app', 'sms'] and would make
email structurally impossible (the N1 bug). MEDIUM yields in_app + email,
which is what a "your day moved" notice should be; SMS waits for N2.
"""

from django.db import migrations


TEMPLATE = {
    'name': 'job_rescheduled',
    'description': 'Technician notice that two of their jobs traded times',
    'category': 'assignment',
    'default_priority': 'MEDIUM',
    'channels_override': [],
    'title_template': 'Schedule change for {{ day }}',
    'message_template': '{{ summary }}.',
    'email_subject_template': 'Your schedule changed for {{ day }}',
    'email_html_template': 'emails/notifications/job_rescheduled.html',
    'email_text_template': 'emails/notifications/job_rescheduled.txt',
    'sms_template': (
        'Schedule change {{ day }}: {{ first_job }} now {{ first_time }}, '
        '{{ second_job }} now {{ second_time }}.'
    ),
    'action_url_template': '/tech/schedule/',
    'required_context': ['day', 'summary'],
}


def seed_template(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.get_or_create(
        name=TEMPLATE['name'], defaults=TEMPLATE
    )


def unseed_template(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(name=TEMPLATE['name']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_customer_sms_opt_in_source'),
    ]

    operations = [
        migrations.RunPython(seed_template, unseed_template),
    ]
