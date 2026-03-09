"""
Data migration: seed all repair notification templates.

These templates are referenced by signals.py for repair lifecycle events.
Previously only repair_request_received and repair_request_submitted were
seeded via migration; the rest existed only in manually-populated DBs.
"""

from django.db import migrations


TEMPLATES = [
    {
        'name': 'repair_pending_approval',
        'description': 'Customer notification when repair needs approval',
        'category': 'approval',
        'default_priority': 'HIGH',
        'title_template': 'Repair Approval Needed - Unit {{ unit_number }}',
        'message_template': (
            'A windshield repair request for unit {{ unit_number }} has been submitted by '
            '{{ technician_name }} and requires your approval. Estimated cost: ${{ estimated_cost }}.'
        ),
        'action_url_template': '/app/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'technician_name', 'estimated_cost', 'repair_id', 'customer_name'],
    },
    {
        'name': 'repair_approved',
        'description': 'Technician notification when repair is approved',
        'category': 'approval',
        'default_priority': 'URGENT',
        'title_template': 'Repair Approved - Unit {{ unit_number }}',
        'message_template': (
            'Your repair request for unit {{ unit_number }} has been approved by {{ customer_name }}. '
            'You can proceed with the repair.'
        ),
        'action_url_template': '/tech/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'customer_name', 'repair_id', 'estimated_cost', 'technician_name'],
    },
    {
        'name': 'repair_denied',
        'description': 'Technician notification when repair is denied',
        'category': 'approval',
        'default_priority': 'URGENT',
        'title_template': 'Repair Denied - Unit {{ unit_number }}',
        'message_template': (
            'Your repair request for unit {{ unit_number }} has been denied by {{ customer_name }}.'
            '{% if denial_reason %} Reason: {{ denial_reason }}{% endif %}'
        ),
        'action_url_template': '/tech/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'customer_name', 'repair_id', 'technician_name'],
    },
    {
        'name': 'repair_assigned',
        'description': 'Technician notification when assigned to repair',
        'category': 'assignment',
        'default_priority': 'HIGH',
        'title_template': 'New Repair Assignment - Unit {{ unit_number }}',
        'message_template': (
            'You have been assigned to repair unit {{ unit_number }} for {{ customer_name }}. '
            'Status: {{ status }}.'
        ),
        'action_url_template': '/tech/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'customer_name', 'repair_id', 'status', 'technician_name'],
    },
    {
        'name': 'repair_reassigned_away',
        'description': 'Notification when repair is reassigned to another tech',
        'category': 'assignment',
        'default_priority': 'MEDIUM',
        'title_template': 'Repair Reassigned - Unit {{ unit_number }}',
        'message_template': (
            'The repair for unit {{ unit_number }} has been reassigned to {{ new_technician_name }}.'
        ),
        'action_url_template': '/tech/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'new_technician_name', 'repair_id', 'customer_name'],
    },
    {
        'name': 'repair_in_progress',
        'description': 'Customer notification when repair work starts',
        'category': 'repair_status',
        'default_priority': 'MEDIUM',
        'title_template': 'Repair In Progress - Unit {{ unit_number }}',
        'message_template': (
            '{{ technician_name }} has started working on the windshield repair for unit {{ unit_number }}.'
        ),
        'action_url_template': '/app/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'technician_name', 'repair_id', 'customer_name'],
    },
    {
        'name': 'repair_completed',
        'description': 'Customer notification when repair is finished',
        'category': 'repair_status',
        'default_priority': 'HIGH',
        'title_template': 'Repair Completed - Unit {{ unit_number }}',
        'message_template': (
            'The windshield repair for unit {{ unit_number }} has been completed by {{ technician_name }}. '
            'Total cost: ${{ final_cost }}.'
        ),
        'action_url_template': '/app/repairs/{{ repair_id }}/',
        'required_context': ['unit_number', 'technician_name', 'repair_id', 'final_cost', 'customer_name'],
    },
    {
        'name': 'batch_approved',
        'description': 'Technician notification when batch repairs approved',
        'category': 'approval',
        'default_priority': 'URGENT',
        'title_template': 'Batch Repairs Approved - Unit {{ unit_number }}',
        'message_template': (
            'Your batch of {{ repair_count }} repairs for unit {{ unit_number }} has been approved by '
            '{{ customer_name }}. Total cost: ${{ total_cost }}.'
        ),
        'action_url_template': '/tech/repairs/?batch={{ batch_id }}',
        'required_context': ['unit_number', 'customer_name', 'repair_count', 'total_cost', 'batch_id', 'technician_name'],
    },
]


def seed_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    for data in TEMPLATES:
        NotificationTemplate.objects.get_or_create(
            name=data['name'],
            defaults=data,
        )


def unseed_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    names = [t['name'] for t in TEMPLATES]
    NotificationTemplate.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_add_progressive_pricing_flag'),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
