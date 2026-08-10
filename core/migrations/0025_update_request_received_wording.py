"""
Update repair_request_received wording for auto-accepted customer requests.

Customer-submitted repair requests are now auto-accepted (REQUESTED -> APPROVED
at submission) instead of waiting for shop review, so the confirmation
notification must say "scheduled" rather than "we will review it". Mirrors the
wording in setup_notification_templates and the email templates.
"""

from django.db import migrations

NEW_MESSAGE = (
    'Your repair request for unit {{ unit_number }} has been received '
    'and added to the schedule.'
)
NEW_SMS = (
    'Your repair request for unit {{ unit_number }} has been received '
    'and added to the schedule.'
)

OLD_MESSAGE = (
    'Your repair request for unit {{ unit_number }} has been received. '
    'We will review it and get back to you shortly.'
)
OLD_SMS = (
    'Your repair request for unit {{ unit_number }} has been received.'
)


def update_wording(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(name='repair_request_received').update(
        message_template=NEW_MESSAGE,
        sms_template=NEW_SMS,
    )


def revert_wording(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(name='repair_request_received').update(
        message_template=OLD_MESSAGE,
        sms_template=OLD_SMS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_remove_customer_unique_customer_email_per_tenant_and_more'),
    ]

    operations = [
        migrations.RunPython(update_wording, revert_wording),
    ]
