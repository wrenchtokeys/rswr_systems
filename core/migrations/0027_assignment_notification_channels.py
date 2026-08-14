"""
Fieldops N1: make technician assignment notifications actually deliver.

1. Adds NotificationTemplate.channels_override — an explicit per-template
   channel list that beats the priority→channel mapping. repair_assigned is
   priority HIGH, and HIGH maps to ['in_app', 'sms'] — email was structurally
   impossible for assignment notifications no matter what templates existed.

2. Sets repair_assigned's channels to in_app+email+sms, and backfills the
   email template paths on rows seeded by migration 0018 (which seeded
   in-app/action fields only — DBs seeded that way rendered empty emails).

3. Seeds two bulk-assignment summary templates so bulk reassign can notify
   each affected tech once instead of once per repair.
"""

from django.db import migrations, models


ASSIGNMENT_CHANNELS = ['in_app', 'email', 'sms']

# Canonical email wiring for the two per-job assignment templates.
# Matches setup_notification_templates (the command remains the full source
# of truth; this backfill only fills fields migration 0018 left blank).
EMAIL_BACKFILL = {
    'repair_assigned': {
        'email_subject_template': 'New Repair Assignment - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_assigned.html',
        'email_text_template': 'emails/notifications/repair_assigned.txt',
        'sms_template': (
            'New assignment: Unit {{ unit_number }} ({{ customer_name }}). '
            'Status: {{ status }}. View: {{ action_url }}'
        ),
    },
    'repair_reassigned_away': {
        'email_subject_template': 'Repair Reassigned - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_reassigned_away.html',
        'email_text_template': 'emails/notifications/repair_reassigned_away.txt',
        'sms_template': 'Unit {{ unit_number }} reassigned to {{ new_technician_name }}.',
    },
}

BULK_TEMPLATES = [
    {
        'name': 'jobs_bulk_assigned',
        'description': 'Technician summary notification for a bulk assignment',
        'category': 'assignment',
        'default_priority': 'HIGH',
        'channels_override': ASSIGNMENT_CHANNELS,
        'title_template': (
            'You have been assigned {{ job_count }} job{{ job_count|pluralize }}'
        ),
        'message_template': (
            'You have been assigned {{ job_count }} job{{ job_count|pluralize }}: '
            '{{ job_summary }}.'
        ),
        'email_subject_template': (
            'You have been assigned {{ job_count }} job{{ job_count|pluralize }}'
        ),
        'email_html_template': 'emails/notifications/jobs_bulk_assigned.html',
        'email_text_template': 'emails/notifications/jobs_bulk_assigned.txt',
        'sms_template': (
            'You have been assigned {{ job_count }} job{{ job_count|pluralize }}. '
            'View: {{ action_url }}'
        ),
        'action_url_template': '/tech/jobs/',
        'required_context': ['job_count', 'job_summary', 'technician_name'],
    },
    {
        'name': 'jobs_bulk_reassigned_away',
        'description': 'Technician summary notification when jobs are bulk-reassigned away',
        'category': 'assignment',
        'default_priority': 'MEDIUM',
        'channels_override': [],
        'title_template': (
            '{{ job_count }} job{{ job_count|pluralize }} reassigned to '
            '{{ new_technician_name }}'
        ),
        'message_template': (
            '{{ job_count }} of your job{{ job_count|pluralize }} '
            '({{ job_summary }}) {{ job_count|pluralize:"was,were" }} reassigned '
            'to {{ new_technician_name }}.'
        ),
        'email_subject_template': (
            '{{ job_count }} job{{ job_count|pluralize }} reassigned to '
            '{{ new_technician_name }}'
        ),
        'email_html_template': 'emails/notifications/jobs_bulk_reassigned_away.html',
        'email_text_template': 'emails/notifications/jobs_bulk_reassigned_away.txt',
        'sms_template': '',
        'action_url_template': '/tech/jobs/',
        'required_context': ['job_count', 'job_summary', 'new_technician_name'],
    },
]


def apply_channels(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')

    # repair_assigned: explicit channels + email backfill
    for name, fields in EMAIL_BACKFILL.items():
        tpl = NotificationTemplate.objects.filter(name=name).first()
        if not tpl:
            continue
        changed = []
        for field, value in fields.items():
            if not getattr(tpl, field):
                setattr(tpl, field, value)
                changed.append(field)
        if name == 'repair_assigned':
            tpl.channels_override = ASSIGNMENT_CHANNELS
            changed.append('channels_override')
        if changed:
            tpl.save(update_fields=changed + ['updated_at'])

    for data in BULK_TEMPLATES:
        NotificationTemplate.objects.get_or_create(
            name=data['name'], defaults=data
        )


def revert_channels(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(
        name__in=[t['name'] for t in BULK_TEMPLATES]
    ).delete()
    NotificationTemplate.objects.filter(name='repair_assigned').update(
        channels_override=[]
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_merge_20260810_1635'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationtemplate',
            name='channels_override',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    'Explicit delivery channels for this template, e.g. '
                    '["in_app", "email", "sms"]. Empty = derive channels '
                    'from priority.'
                ),
            ),
        ),
        migrations.RunPython(apply_channels, revert_channels),
    ]
