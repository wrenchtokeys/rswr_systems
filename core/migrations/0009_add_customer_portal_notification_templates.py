"""
Data migration to add customer portal notification templates and verify customer email preferences.

This migration:
1. Adds repair_request_received template (customer confirmation)
2. Adds repair_request_submitted template (technician/manager notification)
3. Sets email_verified=True for all CustomerNotificationPreference records with valid customer emails
"""

from django.db import migrations


def add_notification_templates(apps, schema_editor):
    """Add the new customer portal notification templates."""
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')

    templates = [
        # REPAIR REQUEST RECEIVED (Customer - from customer portal)
        {
            'name': 'repair_request_received',
            'description': 'Customer confirmation when they submit a repair request',
            'category': 'repair_status',
            'default_priority': 'medium',
            'title_template': 'Repair Request Received - Unit {{ unit_number }}',
            'message_template': (
                'Your repair request for unit {{ unit_number }} has been received. '
                'We will review it and get back to you shortly.'
            ),
            'email_subject_template': 'Repair Request Received - Unit {{ unit_number }}',
            'email_html_template': 'emails/notifications/repair_request_received.html',
            'email_text_template': 'emails/notifications/repair_request_received.txt',
            'sms_template': (
                'Your repair request for unit {{ unit_number }} has been received.'
            ),
            'action_url_template': '/app/repairs/{{ repair_id }}/',
            'required_context': [
                'unit_number', 'repair_id', 'customer_name',
                'damage_type'
            ],
            'active': True,
            'version': 1,
        },
        # REPAIR REQUEST SUBMITTED (Technician/Manager - from customer portal)
        {
            'name': 'repair_request_submitted',
            'description': 'Technician/Manager notification when customer submits repair request',
            'category': 'assignment',
            'default_priority': 'high',
            'title_template': 'New Repair Request - Unit {{ unit_number }}',
            'message_template': (
                '{{ customer_name }} has submitted a repair request for unit '
                '{{ unit_number }}. Damage type: {{ damage_type }}.'
            ),
            'email_subject_template': 'New Repair Request from {{ customer_name }}',
            'email_html_template': 'emails/notifications/repair_request_submitted.html',
            'email_text_template': 'emails/notifications/repair_request_submitted.txt',
            'sms_template': (
                'New repair request from {{ customer_name }} for unit {{ unit_number }}.'
            ),
            'action_url_template': '/tech/repairs/{{ repair_id }}/',
            'required_context': [
                'unit_number', 'repair_id', 'customer_name',
                'damage_type', 'technician_name'
            ],
            'active': True,
            'version': 1,
        },
    ]

    for template_data in templates:
        # Only create if doesn't exist
        if not NotificationTemplate.objects.filter(name=template_data['name']).exists():
            NotificationTemplate.objects.create(**template_data)
            print(f"  Created notification template: {template_data['name']}")
        else:
            print(f"  Template already exists: {template_data['name']}")


def verify_customer_email_preferences(apps, schema_editor):
    """Set email_verified=True for customers with valid emails."""
    Customer = apps.get_model('core', 'Customer')
    CustomerNotificationPreference = apps.get_model('core', 'CustomerNotificationPreference')

    verified_count = 0
    for customer in Customer.objects.filter(email__isnull=False).exclude(email=''):
        # Get or create preference
        pref, created = CustomerNotificationPreference.objects.get_or_create(
            customer=customer,
            defaults={'email_verified': True, 'receive_email_notifications': True}
        )

        if not pref.email_verified:
            pref.email_verified = True
            pref.save()
            verified_count += 1

    if verified_count > 0:
        print(f"  Verified email preferences for {verified_count} customers")


def reverse_migration(apps, schema_editor):
    """Remove the templates added by this migration."""
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    NotificationTemplate.objects.filter(
        name__in=['repair_request_received', 'repair_request_submitted']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_customer_email_verified_at_and_more'),
    ]

    operations = [
        migrations.RunPython(add_notification_templates, reverse_migration),
        migrations.RunPython(verify_customer_email_preferences, migrations.RunPython.noop),
    ]
