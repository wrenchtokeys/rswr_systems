"""
Unit tests for NotificationService and NotificationBatchService.

Tests cover:
- Notification creation with templates
- User preference enforcement
- Quiet hours checking
- Delivery channel selection by priority
- Template rendering
- Batch notification creation
"""

import logging
from datetime import time, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models.notification import Notification
from core.models.notification_template import NotificationTemplate
from core.models.notification_preferences import TechnicianNotificationPreference
from core.services.notification_service import NotificationService, NotificationBatchService
from apps.technician_portal.models import Technician
from django.contrib.auth.models import User


class NotificationServiceTest(TestCase):
    """Test cases for NotificationService."""

    def setUp(self):
        """Set up test data."""
        # Create test user and technician
        self.user = User.objects.create_user(
            username='testtech',
            email='tech@example.com',
            first_name='Test',
            last_name='Technician'
        )
        self.technician = Technician.objects.create(
            user=self.user,
            phone_number='+15551234567',
            expertise='Windshield Repair'
        )

        # Create test template
        self.template = NotificationTemplate.objects.create(
            name='test_template',
            category=Notification.CATEGORY_REPAIR_STATUS,
            default_priority=Notification.PRIORITY_MEDIUM,
            title_template='Test: {{ repair_id }}',
            message_template='Repair {{ repair_id }} status: {{ status }}',
            email_subject_template='Repair {{ repair_id }}',
            email_html_template='<p>Repair {{ repair_id }}: {{ status }}</p>',
            email_text_template='Repair {{ repair_id }}: {{ status }}',
            sms_template='Repair {{ repair_id }}: {{ status }}',
            action_url_template='/repairs/{{ repair_id }}/',
            active=True
        )

        # Create notification preferences
        self.prefs = TechnicianNotificationPreference.objects.create(
            technician=self.technician,
            receive_email_notifications=True,
            receive_sms_notifications=True,
            notify_repair_status=True,
            notify_assignments=True,
            notify_approvals=True,
            notify_rewards=True,
            notify_system=True,
            quiet_hours_enabled=False,
            email_verified=True,
            phone_verified=True
        )

    def test_create_notification_success(self):
        """Test successful notification creation."""
        context = {
            'repair_id': '123',
            'status': 'approved'
        }

        with patch('core.services.notification_service.NotificationService._queue_delivery'):
            notification = NotificationService.create_notification(
                recipient=self.technician,
                template_name='test_template',
                context=context
            )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.title, 'Test: 123')
        self.assertEqual(notification.message, 'Repair 123 status: approved')
        self.assertEqual(notification.category, Notification.CATEGORY_REPAIR_STATUS)
        self.assertEqual(notification.priority, Notification.PRIORITY_MEDIUM)
        self.assertEqual(notification.action_url, '/repairs/123/')

    def test_create_notification_template_not_found(self):
        """Test notification creation with non-existent template."""
        notification = NotificationService.create_notification(
            recipient=self.technician,
            template_name='nonexistent_template',
            context={}
        )

        self.assertIsNone(notification)

    def test_create_notification_inactive_template(self):
        """Test notification creation with inactive template."""
        self.template.active = False
        self.template.save()

        notification = NotificationService.create_notification(
            recipient=self.technician,
            template_name='test_template',
            context={'repair_id': '123', 'status': 'approved'}
        )

        self.assertIsNone(notification)

    def test_create_notification_custom_priority(self):
        """Test notification creation with custom priority override."""
        context = {'repair_id': '123', 'status': 'approved'}

        with patch('core.services.notification_service.NotificationService._queue_delivery'):
            notification = NotificationService.create_notification(
                recipient=self.technician,
                template_name='test_template',
                context=context,
                priority=Notification.PRIORITY_URGENT
            )

        self.assertEqual(notification.priority, Notification.PRIORITY_URGENT)

    def test_create_notification_custom_category(self):
        """Test notification creation with custom category override."""
        context = {'repair_id': '123', 'status': 'approved'}

        with patch('core.services.notification_service.NotificationService._queue_delivery'):
            notification = NotificationService.create_notification(
                recipient=self.technician,
                template_name='test_template',
                context=context,
                category=Notification.CATEGORY_SYSTEM
            )

        self.assertEqual(notification.category, Notification.CATEGORY_SYSTEM)

    def test_get_preferences_for_technician(self):
        """Test getting preferences for Technician object."""
        prefs = NotificationService._get_preferences(self.technician)

        self.assertIsNotNone(prefs)
        self.assertEqual(prefs.technician, self.technician)

    def test_get_preferences_creates_if_not_exists(self):
        """Test that preferences are created if they don't exist."""
        # Delete existing preferences
        TechnicianNotificationPreference.objects.filter(
            technician=self.technician
        ).delete()

        prefs = NotificationService._get_preferences(self.technician)

        self.assertIsNotNone(prefs)
        self.assertEqual(prefs.technician, self.technician)
        # Check defaults
        self.assertTrue(prefs.receive_email_notifications)
        self.assertFalse(prefs.receive_sms_notifications)  # SMS is opt-in due to cost

    def test_should_deliver_category_disabled(self):
        """Test that delivery is blocked when category is disabled."""
        self.prefs.notify_repair_status = False
        self.prefs.save()

        notification = Notification(
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM
        )

        should_deliver = NotificationService._should_deliver(
            notification,
            self.prefs
        )

        self.assertFalse(should_deliver)

    def test_should_deliver_urgent_approval_always(self):
        """Test that URGENT approvals always go through regardless of preferences."""
        self.prefs.notify_approvals = False
        self.prefs.save()

        notification = Notification(
            category=Notification.CATEGORY_APPROVAL,
            priority=Notification.PRIORITY_URGENT
        )

        should_deliver = NotificationService._should_deliver(
            notification,
            self.prefs
        )

        # URGENT approvals should always deliver
        self.assertTrue(should_deliver)

    def test_should_deliver_category_enabled(self):
        """Test that delivery proceeds when category is enabled."""
        notification = Notification(
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM
        )

        should_deliver = NotificationService._should_deliver(
            notification,
            self.prefs
        )

        self.assertTrue(should_deliver)

    def test_is_quiet_hours_disabled(self):
        """Test quiet hours when disabled."""
        self.prefs.quiet_hours_enabled = False
        self.prefs.save()

        is_quiet = NotificationService._is_quiet_hours(self.prefs)

        self.assertFalse(is_quiet)

    def test_is_quiet_hours_within_range(self):
        """Test quiet hours when current time is within range."""
        # Set quiet hours 22:00 to 08:00
        self.prefs.quiet_hours_enabled = True
        self.prefs.quiet_hours_start = time(22, 0)
        self.prefs.quiet_hours_end = time(8, 0)
        self.prefs.save()

        # Mock current time to 23:00 (within quiet hours)
        with patch('core.services.notification_service.timezone.localtime') as mock_time:
            mock_time.return_value.time.return_value = time(23, 0)

            is_quiet = NotificationService._is_quiet_hours(self.prefs)

        self.assertTrue(is_quiet)

    def test_is_quiet_hours_outside_range(self):
        """Test quiet hours when current time is outside range."""
        # Set quiet hours 22:00 to 08:00
        self.prefs.quiet_hours_enabled = True
        self.prefs.quiet_hours_start = time(22, 0)
        self.prefs.quiet_hours_end = time(8, 0)
        self.prefs.save()

        # Mock current time to 14:00 (outside quiet hours)
        with patch('core.services.notification_service.timezone.localtime') as mock_time:
            mock_time.return_value.time.return_value = time(14, 0)

            is_quiet = NotificationService._is_quiet_hours(self.prefs)

        self.assertFalse(is_quiet)

    def test_is_quiet_hours_overnight_early_morning(self):
        """Test overnight quiet hours (early morning within range)."""
        # Set quiet hours 22:00 to 08:00
        self.prefs.quiet_hours_enabled = True
        self.prefs.quiet_hours_start = time(22, 0)
        self.prefs.quiet_hours_end = time(8, 0)
        self.prefs.save()

        # Mock current time to 02:00 (within quiet hours)
        with patch('core.services.notification_service.timezone.localtime') as mock_time:
            mock_time.return_value.time.return_value = time(2, 0)

            is_quiet = NotificationService._is_quiet_hours(self.prefs)

        self.assertTrue(is_quiet)

    def test_quiet_hours_blocks_non_urgent(self):
        """Test that quiet hours blocks non-urgent notifications."""
        self.prefs.quiet_hours_enabled = True
        self.prefs.quiet_hours_start = time(22, 0)
        self.prefs.quiet_hours_end = time(8, 0)
        self.prefs.save()

        notification = Notification(
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM
        )

        # Mock current time to within quiet hours
        with patch('core.services.notification_service.timezone.localtime') as mock_time:
            mock_time.return_value.time.return_value = time(23, 0)

            should_deliver = NotificationService._should_deliver(
                notification,
                self.prefs
            )

        self.assertFalse(should_deliver)

    def test_quiet_hours_allows_urgent(self):
        """Test that quiet hours allows URGENT notifications."""
        self.prefs.quiet_hours_enabled = True
        self.prefs.quiet_hours_start = time(22, 0)
        self.prefs.quiet_hours_end = time(8, 0)
        self.prefs.save()

        notification = Notification(
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_URGENT
        )

        # Mock current time to within quiet hours
        with patch('core.services.notification_service.timezone.localtime') as mock_time:
            mock_time.return_value.time.return_value = time(23, 0)

            should_deliver = NotificationService._should_deliver(
                notification,
                self.prefs
            )

        # URGENT should go through even during quiet hours
        self.assertTrue(should_deliver)

    def test_get_recipient_email_from_user(self):
        """Test extracting email from User object."""
        email = NotificationService._get_recipient_email(self.user)

        self.assertEqual(email, 'tech@example.com')

    def test_get_recipient_email_from_technician(self):
        """Test extracting email from Technician object."""
        email = NotificationService._get_recipient_email(self.technician)

        self.assertEqual(email, 'tech@example.com')

    def test_get_recipient_phone_from_technician(self):
        """Test extracting phone from Technician object."""
        phone = NotificationService._get_recipient_phone(self.technician)

        # Technician model uses phone_number field
        self.assertEqual(phone, '+15551234567')

    @patch('core.services.email_service.EmailService.send_notification_email')
    @patch('core.tasks.send_notification_sms.delay')
    def test_queue_delivery_urgent_priority(
        self,
        mock_sms,
        mock_email
    ):
        """Test that URGENT priority queues both email and SMS."""
        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_URGENT
        )

        rendered = {
            'title': 'Test',
            'message': 'Test message',
            'email_subject': 'Test',
            'email_html': '<p>Test</p>',
            'email_text': 'Test',
            'sms': 'Test'
        }

        NotificationService._queue_delivery(
            notification,
            self.technician,
            rendered
        )

        # Both email and SMS should be queued for URGENT
        self.assertTrue(mock_email.called)
        self.assertTrue(mock_sms.called)

    @patch('core.services.email_service.EmailService.send_notification_email')
    @patch('core.tasks.send_notification_sms.delay')
    def test_queue_delivery_medium_priority(
        self,
        mock_sms,
        mock_email
    ):
        """Test that MEDIUM priority queues only email and in-app."""
        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM
        )

        rendered = {
            'title': 'Test',
            'message': 'Test message',
            'email_subject': 'Test',
            'email_html': '<p>Test</p>',
            'email_text': 'Test',
            'sms': 'Test'
        }

        NotificationService._queue_delivery(
            notification,
            self.technician,
            rendered
        )

        # Only email should be queued for MEDIUM (SMS not included)
        self.assertTrue(mock_email.called)
        self.assertFalse(mock_sms.called)

    @patch('core.services.email_service.EmailService.send_notification_email')
    @patch('core.tasks.send_notification_sms.delay')
    def test_queue_delivery_respects_email_preference(
        self,
        mock_sms,
        mock_email
    ):
        """Test that email delivery respects user preference."""
        self.prefs.receive_email_notifications = False
        self.prefs.save()

        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_URGENT
        )

        rendered = {
            'email_subject': 'Test',
            'email_html': '<p>Test</p>',
            'email_text': 'Test',
            'sms': 'Test'
        }

        NotificationService._queue_delivery(
            notification,
            self.technician,
            rendered
        )

        # Email should not be queued
        self.assertFalse(mock_email.called)
        # But SMS should still be queued (URGENT priority)
        self.assertTrue(mock_sms.called)

    @patch('core.tasks.send_notification_sms.delay')
    def test_queue_delivery_requires_phone_verification(
        self,
        mock_sms
    ):
        """Test that SMS delivery requires verified phone."""
        self.prefs.phone_verified = False
        self.prefs.save()

        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_URGENT
        )

        rendered = {'sms': 'Test'}

        NotificationService._queue_delivery(
            notification,
            self.technician,
            rendered
        )

        # SMS should not be queued without phone verification
        self.assertFalse(mock_sms.called)

    def test_scheduled_notification_not_queued(self):
        """Test that future-scheduled notifications are not queued immediately."""
        future_time = timezone.now() + timedelta(hours=2)
        context = {'repair_id': '123', 'status': 'approved'}

        with patch('core.services.notification_service.NotificationService._queue_delivery') as mock_queue:
            notification = NotificationService.create_notification(
                recipient=self.technician,
                template_name='test_template',
                context=context,
                scheduled_for=future_time
            )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.scheduled_for, future_time)
        # Should NOT queue delivery for future notifications
        mock_queue.assert_not_called()


class NotificationBatchServiceTest(TestCase):
    """Test cases for NotificationBatchService."""

    def setUp(self):
        """Set up test data."""
        # Create test users and technicians
        self.user1 = User.objects.create_user(
            username='tech1',
            email='tech1@example.com',
            first_name='Tech',
            last_name='One'
        )
        self.tech1 = Technician.objects.create(
            user=self.user1,
            phone_number='+15551111111',
            expertise='Windshield Repair'
        )

        self.user2 = User.objects.create_user(
            username='tech2',
            email='tech2@example.com',
            first_name='Tech',
            last_name='Two'
        )
        self.tech2 = Technician.objects.create(
            user=self.user2,
            phone_number='+15552222222',
            expertise='Glass Repair'
        )

        # Create test template
        self.template = NotificationTemplate.objects.create(
            name='batch_test',
            category=Notification.CATEGORY_SYSTEM,
            default_priority=Notification.PRIORITY_MEDIUM,
            title_template='Hello {{ name }}',
            message_template='This is a test for {{ name }}',
            active=True
        )

    @patch('core.services.notification_service.NotificationService._queue_delivery')
    def test_create_batch_notifications(self, mock_queue):
        """Test creating batch notifications for multiple recipients."""
        recipients = [self.tech1, self.tech2]

        def context_builder(recipient):
            return {'name': recipient.user.first_name}

        notifications = NotificationBatchService.create_batch_notifications(
            recipients=recipients,
            template_name='batch_test',
            context_builder=context_builder
        )

        self.assertEqual(len(notifications), 2)
        self.assertEqual(notifications[0].title, 'Hello Tech')
        self.assertEqual(notifications[1].title, 'Hello Tech')

    @patch('core.services.notification_service.NotificationService._queue_delivery')
    def test_create_batch_notifications_handles_errors(self, mock_queue):
        """Test that batch creation continues even if one fails."""
        recipients = [self.tech1, self.tech2]

        def context_builder(recipient):
            if recipient == self.tech1:
                raise Exception("Test error")
            return {'name': recipient.user.first_name}

        # Should continue despite error for tech1
        notifications = NotificationBatchService.create_batch_notifications(
            recipients=recipients,
            template_name='batch_test',
            context_builder=context_builder
        )

        # Only tech2's notification should be created
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].message, 'This is a test for Tech')
