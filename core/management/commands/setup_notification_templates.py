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
                # HIGH maps to in_app+sms; assignment must email too
                # (fieldops N1 — staff notifications are default-ON).
                'channels_override': ['in_app', 'email', 'sms'],
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
                    'Your repair request for unit {{ unit_number }} has been received '
                    'and added to the schedule.'
                ),
                'email_subject_template': 'Repair Request Received - Unit {{ unit_number }}',
                'email_html_template': 'emails/notifications/repair_request_received.html',
                'email_text_template': 'emails/notifications/repair_request_received.txt',
                'sms_template': (
                    'Your repair request for unit {{ unit_number }} has been received '
                    'and added to the schedule.'
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

            # 11. BULK ASSIGNED (Technician) — one summary per bulk reassign
            {
                'name': 'jobs_bulk_assigned',
                'description': 'Technician summary notification for a bulk assignment',
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_HIGH,
                'channels_override': ['in_app', 'email', 'sms'],
                'title_template': (
                    'You have been assigned {{ job_count }} '
                    'job{{ job_count|pluralize }}'
                ),
                'message_template': (
                    'You have been assigned {{ job_count }} '
                    'job{{ job_count|pluralize }}: {{ job_summary }}.'
                ),
                'email_subject_template': (
                    'You have been assigned {{ job_count }} '
                    'job{{ job_count|pluralize }}'
                ),
                'email_html_template': 'emails/notifications/jobs_bulk_assigned.html',
                'email_text_template': 'emails/notifications/jobs_bulk_assigned.txt',
                'sms_template': (
                    'You have been assigned {{ job_count }} '
                    'job{{ job_count|pluralize }}. View: {{ action_url }}'
                ),
                'action_url_template': '/tech/jobs/',
                'required_context': ['job_count', 'job_summary', 'technician_name'],
            },

            # 12. BULK REASSIGNED AWAY (Technician)
            {
                'name': 'jobs_bulk_reassigned_away',
                'description': 'Technician summary notification when jobs are bulk-reassigned away',
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_MEDIUM,
                'title_template': (
                    '{{ job_count }} job{{ job_count|pluralize }} reassigned '
                    'to {{ new_technician_name }}'
                ),
                'message_template': (
                    '{{ job_count }} of your job{{ job_count|pluralize }} '
                    '({{ job_summary }}) {{ job_count|pluralize:"was,were" }} '
                    'reassigned to {{ new_technician_name }}.'
                ),
                'email_subject_template': (
                    '{{ job_count }} job{{ job_count|pluralize }} reassigned '
                    'to {{ new_technician_name }}'
                ),
                'email_html_template': 'emails/notifications/jobs_bulk_reassigned_away.html',
                'email_text_template': 'emails/notifications/jobs_bulk_reassigned_away.txt',
                'sms_template': '',
                'action_url_template': '/tech/jobs/',
                'required_context': ['job_count', 'job_summary', 'new_technician_name'],
            },

            # 13. JOB RESCHEDULED (Technician) — one template for every
            # "your day changed" event: the S7 day-view swap and the S4
            # booking confirm. One stream, one opt-out. Category 'assignment'
            # so it reuses the existing technician opt-out; MEDIUM so email is
            # actually a channel (HIGH is in_app+sms only).
            {
                'name': 'job_rescheduled',
                'description': 'Technician notice that their booked times changed',
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_MEDIUM,
                'title_template': 'Schedule change for {{ day }}',
                'message_template': '{{ summary }}.',
                'email_subject_template': 'Your schedule changed for {{ day }}',
                'email_html_template': 'emails/notifications/job_rescheduled.html',
                'email_text_template': 'emails/notifications/job_rescheduled.txt',
                'sms_template': 'Schedule change {{ day }}: {{ summary }}.',
                'action_url_template': '/tech/schedule/',
                'required_context': ['day', 'summary'],
            },

            # 14. NEEDS ASSIGNMENT (Managers) — the Unassigned queue's only
            # reach outside the dashboard. Named for the event, not the
            # audience: the call site decides who hears it. Category
            # 'assignment' reuses the existing technician opt-out; HIGH
            # carries an explicit channels_override because HIGH alone maps
            # to ['in_app', 'sms'] and SMS is dark until fieldops N2, which
            # would leave the email body undeliverable.
            {
                'name': 'needs_assignment',
                'description': (
                    'Manager alert that a job is sitting in the Unassigned queue'
                ),
                'category': Notification.CATEGORY_ASSIGNMENT,
                'default_priority': Notification.PRIORITY_HIGH,
                'channels_override': ['in_app', 'email'],
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
                # Blank: repairs and replacements have different detail
                # routes, so the call site passes action_url. A template
                # default would be right for one job type and a 404 for
                # the other.
                'action_url_template': '',
                'required_context': ['job_id', 'job_type', 'customer_name'],
            },

            # ---- REPLACEMENTS -------------------------------------------
            # The shop's most valuable job had no lifecycle notifications at
            # all: every template above is repair_*, so a customer booking a
            # $600 replacement heard less than one booking a $40 chip repair.
            # Vehicle wording comes from vehicle_label/vehicle_identifier,
            # which notification_service.job_display_context() derives — an
            # individual's car is never called a "Unit".

            # 15. REPLACEMENT REQUEST RECEIVED (Customer)
            {
                'name': 'replacement_request_received',
                'description': 'Customer confirmation that a replacement request arrived',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_MEDIUM,
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

            # 16. REPLACEMENT REQUEST SUBMITTED (Shop)
            {
                'name': 'replacement_request_submitted',
                'description': 'Shop notification that a customer wants a replacement',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_HIGH,
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

            # 17. REPLACEMENT NEEDS APPROVAL (Customer)
            {
                'name': 'replacement_pending_approval',
                'description': 'Customer approval needed for a priced replacement',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_HIGH,
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

            # 18. REPLACEMENT APPROVED (Technician)
            {
                'name': 'replacement_approved',
                'description': 'Technician notification when a replacement is approved',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_HIGH,
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

            # 19. REPLACEMENT DECLINED (Technician)
            {
                'name': 'replacement_denied',
                'description': 'Technician notification when a replacement is declined',
                'category': Notification.CATEGORY_APPROVAL,
                'default_priority': Notification.PRIORITY_URGENT,
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

            # 20. REPLACEMENT IN PROGRESS (Customer)
            {
                'name': 'replacement_in_progress',
                'description': 'Customer notification that replacement work started',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_MEDIUM,
                'title_template': 'Replacement in progress',
                'message_template': (
                    '{% if technician_name %}{{ technician_name }} has started{% else %}Work has started{% endif %} '
                    'on your glass replacement'
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

            # 21. REPLACEMENT COMPLETED (Customer)
            {
                'name': 'replacement_completed',
                'description': 'Customer notification that a replacement is finished',
                'category': Notification.CATEGORY_REPAIR_STATUS,
                'default_priority': Notification.PRIORITY_HIGH,
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
