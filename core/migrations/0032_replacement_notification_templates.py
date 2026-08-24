"""Seed the replacement lifecycle notification templates.

Every template seeded before this one was repair_*, so a customer booking
the shop's most expensive job — a full glass replacement — heard nothing
after submitting the request, while a $40 chip repair sent five emails.
The only replacement notification in the codebase was a one-off in
apps/customer_portal/views.py that emailed the shop and nobody else.

The definitions here are duplicated from
core/management/commands/setup_notification_templates.py rather than
imported: a migration must keep doing what it did the day it was written,
and importing a live definition would make this migration's behaviour
change every time someone edits the command.

Idempotent both ways. Forward uses update_or_create so re-running it on a
database that already has a row is safe; reverse deletes only the rows this
migration introduced.
"""
from django.db import migrations


TEMPLATES = [
    {
        'name': 'replacement_request_received',
        'description': 'Customer confirmation that a replacement request arrived',
        'category': 'repair_status',
        'default_priority': 'MEDIUM',
        'title_template': 'Replacement request received',
        'message_template': (
            'We have your replacement request'
            '{% if vehicle_identifier %} for {{ vehicle_identifier }}{% endif %}. '
            'We will confirm the glass and the price before any work begins.'
        ),
        'email_subject_template': 'We have your replacement request',
        'email_html_template': 'emails/notifications/replacement_request_received.html',
        'email_text_template': 'emails/notifications/replacement_request_received.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/app/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
    {
        'name': 'replacement_request_submitted',
        'description': 'Shop notification that a customer wants a replacement',
        'category': 'repair_status',
        'default_priority': 'HIGH',
        'title_template': 'New replacement request',
        'message_template': (
            '{{ customer_name }} requested a replacement'
            '{% if glass_position %} — {{ glass_position|lower }}{% endif %}'
            '{% if vehicle_identifier %} on {{ vehicle_identifier }}{% endif %}. '
            'It needs a price.'
        ),
        'email_subject_template': 'New replacement request from {{ customer_name }}',
        'email_html_template': 'emails/notifications/replacement_request_submitted.html',
        'email_text_template': 'emails/notifications/replacement_request_submitted.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/tech/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
    {
        'name': 'replacement_pending_approval',
        'description': 'Customer approval needed for a priced replacement',
        'category': 'approval',
        'default_priority': 'HIGH',
        'title_template': 'Replacement needs your approval',
        'message_template': (
            'Your glass replacement is priced'
            '{% if job_cost_display %} at {{ job_cost_display }}{% endif %}. '
            'Nothing is ordered until you approve it.'
        ),
        'email_subject_template': 'Your glass replacement is priced',
        'email_html_template': 'emails/notifications/replacement_pending_approval.html',
        'email_text_template': 'emails/notifications/replacement_pending_approval.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/app/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
    {
        'name': 'replacement_approved',
        'description': 'Technician notification when a replacement is approved',
        'category': 'approval',
        'default_priority': 'HIGH',
        'title_template': 'Replacement approved',
        'message_template': (
            '{{ customer_name }} approved the replacement'
            '{% if vehicle_identifier %} on {{ vehicle_identifier }}{% endif %}. '
            'The glass can be ordered.'
        ),
        'email_subject_template': 'Replacement approved — {{ customer_name }}',
        'email_html_template': 'emails/notifications/replacement_approved.html',
        'email_text_template': 'emails/notifications/replacement_approved.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/tech/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
    {
        'name': 'replacement_denied',
        'description': 'Technician notification when a replacement is declined',
        'category': 'approval',
        'default_priority': 'URGENT',
        'title_template': 'Replacement declined',
        'message_template': (
            '{{ customer_name }} declined the replacement'
            '{% if vehicle_identifier %} on {{ vehicle_identifier }}{% endif %}.'
            '{% if denial_reason %} {{ denial_reason }}{% endif %}'
        ),
        'email_subject_template': 'Replacement declined — {{ customer_name }}',
        'email_html_template': 'emails/notifications/replacement_denied.html',
        'email_text_template': 'emails/notifications/replacement_denied.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/tech/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
    {
        'name': 'replacement_in_progress',
        'description': 'Customer notification that replacement work started',
        'category': 'repair_status',
        'default_priority': 'MEDIUM',
        'title_template': 'Replacement in progress',
        'message_template': (
            '{% if technician_name %}{{ technician_name }} has started'
            '{% else %}Work has started{% endif %} on your glass replacement'
            '{% if vehicle_identifier %} for {{ vehicle_identifier }}{% endif %}.'
        ),
        'email_subject_template': 'Work has started on your glass',
        'email_html_template': 'emails/notifications/replacement_in_progress.html',
        'email_text_template': 'emails/notifications/replacement_in_progress.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/app/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
    {
        'name': 'replacement_completed',
        'description': 'Customer notification that a replacement is finished',
        'category': 'repair_status',
        'default_priority': 'HIGH',
        'title_template': 'Replacement completed',
        'message_template': (
            'Your glass replacement is done'
            '{% if vehicle_identifier %} — {{ vehicle_identifier }}{% endif %}.'
        ),
        'email_subject_template': 'Your glass replacement is done',
        'email_html_template': 'emails/notifications/replacement_completed.html',
        'email_text_template': 'emails/notifications/replacement_completed.txt',
        'sms_template': '',
        'channels_override': ['in_app', 'email'],
        'action_url_template': '/app/replacements/{{ replacement_id }}/',
        'required_context': ['replacement_id', 'customer_name'],
    },
]


def seed(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    for spec in TEMPLATES:
        NotificationTemplate.objects.update_or_create(
            name=spec['name'],
            defaults={**{k: v for k, v in spec.items() if k != 'name'},
                      'active': True},
        )


def unseed(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(
        name__in=[spec['name'] for spec in TEMPLATES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0031_fix_request_template_priorities'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
