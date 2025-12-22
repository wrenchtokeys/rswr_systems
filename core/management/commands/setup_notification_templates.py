"""
Management command to create NotificationTemplate database records.

This command populates the database with all notification templates
needed for the Phase 4 notification system.

Usage:
    python manage.py setup_notification_templates
    python manage.py setup_notification_templates --update  # Update existing
"""

from django.core.management.base import BaseCommand
from core.models.notification import Notification
from core.models.notification_template import NotificationTemplate


class Command(BaseCommand):
    help = 'Create NotificationTemplate records for the notification system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help='Update existing templates instead of skipping them',
        )

    def handle(self, *args, **options):
        update_existing = options['update']

        self.stdout.write(
            self.style.SUCCESS('\nSetting up notification templates...\n')
        )

        templates = [
            # 1. REPAIR PENDING APPROVAL (Customer)
            {
                'name': 'repair_pending_approval',
                'description': 'Customer notification when repair needs approval',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_HIGH,
                'title_template': 'Repair Approval Needed - Unit {{ unit_number }}',
                'message_template': (
                    'A windshield repair request for unit {{ unit_number }} has been '
                    'submitted by {{ technician_name }} and requires your approval. '
                    'Estimated cost: ${{ estimated_cost }}.'
                ),
                'email_subject_template': 'Repair Approval Needed - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_pending_approval.html',
                'email_text_template': 'emails/notifications/repair_pending_approval.txt',
                'sms_template': (
                    'Repair approval needed for unit {{ unit_number }}. '
                    'Cost: ${{ estimated_cost }}. Review at {{ action_url }}'
                ),
                'action_url_template': '/app/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'technician_name', 'estimated_cost',
                    'repair_id', 'customer_name'
                ],
            },

            # 2. REPAIR APPROVED (Technician)
            {
                'name': 'repair_approved',
                'description': 'Technician notification when repair is approved',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_URGENT,
                'title_template': 'Repair Approved - Unit {{ unit_number }}',
                'message_template': (
                    'Your repair request for unit {{ unit_number }} has been approved '
                    'by {{ customer_name }}. You can proceed with the repair.'
                ),
                'email_subject_template': 'Repair Approved - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_approved.html',
                'email_text_template': 'emails/notifications/repair_approved.txt',
                'sms_template': (
                    'Repair APPROVED for unit {{ unit_number }}. Proceed with repair. '
                    'Details: {{ action_url }}'
                ),
                'action_url_template': '/tech/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'customer_name', 'repair_id',
                    'estimated_cost', 'technician_name'
                ],
            },

            # 3. REPAIR DENIED (Technician)
            {
                'name': 'repair_denied',
                'description': 'Technician notification when repair is denied',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_URGENT,
                'title_template': 'Repair Denied - Unit {{ unit_number }}',
                'message_template': (
                    'Your repair request for unit {{ unit_number }} has been denied '
                    'by {{ customer_name }}.'
                    '{% if denial_reason %} Reason: {{ denial_reason }}{% endif %}'
                ),
                'email_subject_template': 'Repair Denied - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_denied.html',
                'email_text_template': 'emails/notifications/repair_denied.txt',
                'sms_template': (
                    'Repair DENIED for unit {{ unit_number }}. '
                    '{% if denial_reason %}Reason: {{ denial_reason }}{% endif %}'
                ),
                'action_url_template': '/tech/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'customer_name', 'repair_id',
                    'technician_name'
                ],
            },

            # 4. TECHNICIAN ASSIGNED (Technician)
            {
                'name': 'repair_assigned',
                'description': 'Technician notification when assigned to repair',
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_HIGH,
                'title_template': 'New Repair Assignment - Unit {{ unit_number }}',
                'message_template': (
                    'You have been assigned to repair unit {{ unit_number }} '
                    'for {{ customer_name }}. Status: {{ status }}.'
                ),
                'email_subject_template': 'New Repair Assignment - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_assigned.html',
                'email_text_template': 'emails/notifications/repair_assigned.txt',
                'sms_template': (
                    'New assignment: Unit {{ unit_number }} ({{ customer_name }}). '
                    'Status: {{ status }}. View: {{ action_url }}'
                ),
                'action_url_template': '/tech/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'customer_name', 'repair_id',
                    'status', 'technician_name'
                ],
            },

            # 5. REPAIR IN PROGRESS (Customer)
            {
                'name': 'repair_in_progress',
                'description': 'Customer notification when repair work starts',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_MEDIUM,
                'title_template': 'Repair In Progress - Unit {{ unit_number }}',
                'message_template': (
                    '{{ technician_name }} has started working on the windshield '
                    'repair for unit {{ unit_number }}.'
                ),
                'email_subject_template': 'Repair In Progress - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_in_progress.html',
                'email_text_template': 'emails/notifications/repair_in_progress.txt',
                'sms_template': (
                    'Repair started for unit {{ unit_number }} by {{ technician_name }}.'
                ),
                'action_url_template': '/app/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'technician_name', 'repair_id',
                    'customer_name'
                ],
            },

            # 6. REPAIR COMPLETED (Customer)
            {
                'name': 'repair_completed',
                'description': 'Customer notification when repair is finished',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_HIGH,
                'title_template': 'Repair Completed - Unit {{ unit_number }}',
                'message_template': (
                    'The windshield repair for unit {{ unit_number }} has been '
                    'completed by {{ technician_name }}. Total cost: ${{ final_cost }}.'
                ),
                'email_subject_template': 'Repair Completed - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_completed.html',
                'email_text_template': 'emails/notifications/repair_completed.txt',
                'sms_template': (
                    'Repair COMPLETED for unit {{ unit_number }}. '
                    'Cost: ${{ final_cost }}. View: {{ action_url }}'
                ),
                'action_url_template': '/app/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'technician_name', 'repair_id',
                    'final_cost', 'customer_name'
                ],
            },

            # 7. BATCH APPROVED (Technician)
            {
                'name': 'batch_approved',
                'description': 'Technician notification when batch repairs approved',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_URGENT,
                'title_template': 'Batch Repairs Approved - Unit {{ unit_number }}',
                'message_template': (
                    'Your batch of {{ repair_count }} repairs for unit {{ unit_number }} '
                    'has been approved by {{ customer_name }}. Total cost: ${{ total_cost }}.'
                ),
                'email_subject_template': (
                    'Batch Repairs Approved - {{ repair_count }} repairs'
                ),
                'email_html_template': 'emails/notifications/batch_approved.html',
                'email_text_template': 'emails/notifications/batch_approved.txt',
                'sms_template': (
                    'APPROVED: {{ repair_count }} repairs for unit {{ unit_number }}. '
                    'Total: ${{ total_cost }}.'
                ),
                'action_url_template': '/tech/repairs/?batch={{ batch_id }}',
                'required_context': [
                    'unit_number', 'customer_name', 'repair_count',
                    'total_cost', 'batch_id', 'technician_name'
                ],
            },

            # 8. TECHNICIAN REASSIGNED (Old Technician)
            {
                'name': 'repair_reassigned_away',
                'description': 'Notification when repair is reassigned to another tech',
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_MEDIUM,
                'title_template': 'Repair Reassigned - Unit {{ unit_number }}',
                'message_template': (
                    'The repair for unit {{ unit_number }} has been reassigned '
                    'to {{ new_technician_name }}.'
                ),
                'email_subject_template': 'Repair Reassigned - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_reassigned_away.html',
                'email_text_template': 'emails/notifications/repair_reassigned_away.txt',
                'sms_template': (
                    'Unit {{ unit_number }} reassigned to {{ new_technician_name }}.'
                ),
                'action_url_template': '/tech/repairs/{{ repair_id }}/',
                'required_context': [
                    'unit_number', 'new_technician_name', 'repair_id',
                    'customer_name'
                ],
            },

            # 9. REPAIR REQUEST RECEIVED (Customer - from customer portal)
            {
                'name': 'repair_request_received',
                'description': 'Customer confirmation when they submit a repair request',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_MEDIUM,
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
            },

            # 10. REPAIR REQUEST SUBMITTED (Technician/Manager - from customer portal)
            {
                'name': 'repair_request_submitted',
                'description': 'Technician/Manager notification when customer submits repair request',
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_HIGH,
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
            },
        ]

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for template_data in templates:
            name = template_data['name']

            # Check if template exists
            existing = NotificationTemplate.objects.filter(name=name).first()

            if existing and not update_existing:
                self.stdout.write(
                    self.style.WARNING(f'  ⏭  Skipping existing: {name}')
                )
                skipped_count += 1
                continue

            if existing and update_existing:
                # Update existing template
                for key, value in template_data.items():
                    setattr(existing, key, value)
                existing.save()

                self.stdout.write(
                    self.style.SUCCESS(f'  ✓  Updated: {name}')
                )
                updated_count += 1

            else:
                # Create new template
                NotificationTemplate.objects.create(**template_data)

                self.stdout.write(
                    self.style.SUCCESS(f'  ✓  Created: {name}')
                )
                created_count += 1

        # Summary
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(
            self.style.SUCCESS(f'\nTemplate setup complete!')
        )
        self.stdout.write(f'  Created: {created_count}')
        self.stdout.write(f'  Updated: {updated_count}')
        self.stdout.write(f'  Skipped: {skipped_count}')
        self.stdout.write(f'  Total templates: {len(templates)}\n')
