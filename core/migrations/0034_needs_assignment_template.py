"""Seed the `needs_assignment` template — the Unassigned queue's only reach.

CODE-279 gave the shop a queue and told its managers about it with a
`TechnicianNotification` row: the dashboard's unread list and nowhere else.
No bell, no email, because `NotificationService` needs a template row and
none existed for this event. A shop that did not open the dashboard on a
given afternoon never learned a customer request was sitting unassigned —
which is the one thing Manual assignment depends on somebody noticing.

Named for the event, not the audience: `needs_assignment` is what happened,
and the call site decides who hears about it (JOB_QUEUE_SESSIONS Q4).

Priority HIGH with an explicit `channels_override`, for the reason
FIELD_OPS N1 documents: HIGH maps to ['in_app', 'sms'] and SMS is dark
until N2, so a HIGH template with no override is a body no channel can
deliver. SMS is left off the override rather than staged — when N2 lights
the number up, adding it here is one line, and `test_fieldops_n3` will not
let this row go stranded in the meantime.

The definition is duplicated from
core/management/commands/setup_notification_templates.py rather than
imported: a migration must keep doing what it did the day it was written.

Idempotent both ways, matching 0032.
"""
from django.db import migrations


TEMPLATE = {
    'name': 'needs_assignment',
    'description': (
        'Manager alert that a job is sitting in the Unassigned queue'
    ),
    'category': 'assignment',
    'default_priority': 'HIGH',
    'title_template': 'A {{ job_type|lower }} needs assigning',
    'message_template': (
        '{{ customer_name }}\'s {{ job_type|lower }}'
        '{% if vehicle_identifier %} on {{ vehicle_identifier }}'
        '{% elif unit_number %} on Unit {{ unit_number }}{% endif %} '
        'is waiting to be assigned. Nobody has been told about it yet.'
    ),
    'email_subject_template': (
        'A {{ job_type|lower }} for {{ customer_name }} needs assigning'
    ),
    'email_html_template': 'emails/notifications/needs_assignment.html',
    'email_text_template': 'emails/notifications/needs_assignment.txt',
    'sms_template': '',
    'channels_override': ['in_app', 'email'],
    # Blank: repairs and replacements have different detail routes, so the
    # call site passes action_url. A template-level default would be right
    # for one job type and a 404 for the other.
    'action_url_template': '',
    'required_context': ['job_id', 'job_type', 'customer_name'],
}


def seed(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.update_or_create(
        name=TEMPLATE['name'],
        defaults={**{k: v for k, v in TEMPLATE.items() if k != 'name'},
                  'active': True},
    )


def unseed(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(name=TEMPLATE['name']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_backfill_notification_email_wiring'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
