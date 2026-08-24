"""
FIELD_OPS N3: make the seeded lifecycle emails deliverable.

Two independent faults, both of which only show on a database built by
migrations -- which is every deployed one:

1. **Six templates have no email body wired.** Migration 0018 seeded the
   repair lifecycle with in-app/action fields only; it sets no
   `email_html_template` at all. Migration 0027 noticed and backfilled
   exactly the two rows fieldops N1 needed (`repair_assigned`,
   `repair_reassigned_away`) and left the rest. So `repair_completed`,
   `repair_pending_approval`, `repair_approved`, `repair_denied`,
   `repair_in_progress` and `batch_approved` still render `email_html` as ''.
   `EmailService` guards its `attach_alternative` on a truthy body, so the
   mail goes out as bare plain text with the in-app `message_template` for a
   body -- none of the designed HTML from PR #200 has ever reached a
   recipient on those six events.

2. **Three templates have a body they can never send.** They are priority
   HIGH, and HIGH maps to ['in_app', 'sms'] -- and nothing texts anybody
   until the toll-free number clears review. `repair_request_submitted` is
   the shop's "a customer just asked for work"; `repair_pending_approval`
   asks a customer to approve work; `repair_completed` tells the customer the
   job is done AND is the owner's and every manager's copy of the same event.
   All three get the `channels_override` treatment 0027 gave the assignment
   templates.

   **This one is shop-visible.** These two customer emails have never sent on
   a deployed database, so the first effect of this migration is customers
   receiving mail they have not had before. Drake's call, 2026-08-24.

Both fixes are idempotent and additive: wiring is only written where the
column is currently blank, so a database that was set up through
`setup_notification_templates` (the documented full source of truth, whose
values these are copied from verbatim) is left exactly as it is. Copy is not
touched -- subjects are the ones that command already installs.
"""

from django.db import migrations


# Copied verbatim from core/management/commands/setup_notification_templates.py
# so the two cannot disagree. Only applied where the row's field is blank.
EMAIL_WIRING = {
    'repair_pending_approval': {
        'email_subject_template': 'Repair Approval Needed - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_pending_approval.html',
        'email_text_template': 'emails/notifications/repair_pending_approval.txt',
        'sms_template': (
            'Repair approval needed for unit {{ unit_number }}. '
            'Cost: ${{ estimated_cost }}. Review at {{ action_url }}'
        ),
    },
    'repair_approved': {
        'email_subject_template': 'Repair Approved - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_approved.html',
        'email_text_template': 'emails/notifications/repair_approved.txt',
        'sms_template': (
            'Repair APPROVED for unit {{ unit_number }}. Proceed with repair. '
            'Details: {{ action_url }}'
        ),
    },
    'repair_denied': {
        'email_subject_template': 'Repair Denied - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_denied.html',
        'email_text_template': 'emails/notifications/repair_denied.txt',
        'sms_template': (
            'Repair DENIED for unit {{ unit_number }}. '
            '{% if denial_reason %}Reason: {{ denial_reason }}{% endif %}'
        ),
    },
    'repair_in_progress': {
        'email_subject_template': 'Repair In Progress - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_in_progress.html',
        'email_text_template': 'emails/notifications/repair_in_progress.txt',
        'sms_template': 'Repair started for unit {{ unit_number }} by {{ technician_name }}.',
    },
    'repair_completed': {
        'email_subject_template': 'Repair Completed - Unit {{ unit_number }}',
        'email_html_template': 'emails/notifications/repair_completed.html',
        'email_text_template': 'emails/notifications/repair_completed.txt',
        'sms_template': (
            'Repair COMPLETED for unit {{ unit_number }}. '
            'Cost: ${{ final_cost }}. View: {{ action_url }}'
        ),
    },
    'batch_approved': {
        'email_subject_template': 'Batch Repairs Approved - {{ repair_count }} repairs',
        'email_html_template': 'emails/notifications/batch_approved.html',
        'email_text_template': 'emails/notifications/batch_approved.txt',
        'sms_template': (
            'APPROVED: {{ repair_count }} repairs for unit {{ unit_number }}. '
            'Total: ${{ total_cost }}.'
        ),
    },
}

# Events whose recipient needs mail, not just a bell they may never look at.
# 'sms' rides along the way every other override does -- it stays inert until
# fieldops N2 lights the toll-free number up.
EMAIL_CHANNELS = ['in_app', 'email', 'sms']
NEEDS_EMAIL_CHANNEL = [
    'repair_request_submitted',
    'repair_pending_approval',
    'repair_completed',
]


def wire_email_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')

    for name, wiring in EMAIL_WIRING.items():
        for template in NotificationTemplate.objects.filter(name=name):
            updates = [
                field for field, value in wiring.items()
                if not (getattr(template, field, '') or '').strip()
            ]
            if not updates:
                continue
            for field in updates:
                setattr(template, field, wiring[field])
            template.save(update_fields=updates)

    NotificationTemplate.objects.filter(
        name__in=NEEDS_EMAIL_CHANNEL, channels_override=[],
    ).update(channels_override=EMAIL_CHANNELS)


def unwire_email_templates(apps, schema_editor):
    """Reverse is deliberately a no-op.

    Blanking these columns again would restore the delivery bug, and there is
    no record of which rows this migration wrote versus which the setup
    command had already filled.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_replacement_notification_templates'),
    ]

    operations = [
        migrations.RunPython(wire_email_templates, unwire_email_templates),
    ]
