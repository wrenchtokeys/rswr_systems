"""
Unit tests for Celery tasks in the notification system.

Tests cover:
- send_notification_email task
- send_notification_sms task
- retry_failed_notifications periodic task
- send_daily_digests periodic task
- cleanup_old_delivery_logs periodic task
- send_scheduled_notifications task
"""

from datetime import timedelta
from unittest.mock import patch, MagicMock, call
from django.test import TestCase
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog
from core.models.notification_template import NotificationTemplate
from core.models.notification_preferences import TechnicianNotificationPreference
from core.tasks import (
    send_notification_email,
    send_notification_sms,
    retry_failed_notifications,
    send_daily_digests,
    cleanup_old_delivery_logs,
    send_scheduled_notifications
)
from apps.technician_portal.models import Technician
from django.contrib.auth.models import User


class SendNotificationEmailTaskTest(TestCase):
    """Test cases for send_notification_email Celery task."""

    def setUp(self):
        """Set up test data."""
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

        self.notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM
        )

    @patch('core.services.email_service.EmailService.send_notification_email')
    def test_send_email_task_success(self, mock_send):
        """Test successful email sending task."""
        mock_send.return_value = (True, MagicMock())

        result = send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test'
        )

        self.assertTrue(result)
        mock_send.assert_called_once_with(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test',
            attempt_number=1
        )

    @patch('core.services.email_service.EmailService.send_notification_email')
    def test_send_email_task_failure(self, mock_send):
        """Test email sending task failure."""
        mock_send.return_value = (False, MagicMock())

        result = send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test'
        )

        self.assertFalse(result)

    @patch('core.services.email_service.EmailService.send_notification_email')
    def test_send_email_task_with_attempt_number(self, mock_send):
        """Test email task passes attempt number to service."""
        mock_send.return_value = (True, MagicMock())

        send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test',
            attempt_number=2
        )

        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['attempt_number'], 2)


class SendNotificationSMSTaskTest(TestCase):
    """Test cases for send_notification_sms Celery task."""

    def setUp(self):
        """Set up test data."""
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

        self.notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_URGENT
        )

    @patch('core.services.sms_service.SMSService.send_notification_sms')
    def test_send_sms_task_success(self, mock_send):
        """Test successful SMS sending task."""
        mock_send.return_value = (True, MagicMock())

        result = send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test SMS'
        )

        self.assertTrue(result)
        mock_send.assert_called_once_with(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test SMS',
            attempt_number=1
        )

    @patch('core.services.sms_service.SMSService.send_notification_sms')
    def test_send_sms_task_failure(self, mock_send):
        """Test SMS sending task failure."""
        mock_send.return_value = (False, MagicMock())

        result = send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test SMS'
        )

        self.assertFalse(result)

    @patch('core.services.sms_service.SMSService.send_notification_sms')
    def test_send_sms_task_with_attempt_number(self, mock_send):
        """Test SMS task passes attempt number to service."""
        mock_send.return_value = (True, MagicMock())

        send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test SMS',
            attempt_number=3
        )

        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['attempt_number'], 3)


class RetryFailedNotificationsTaskTest(TestCase):
    """Test cases for retry_failed_notifications periodic task."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testtech',
            email='tech@example.com',
            first_name='Test',
            last_name='Technician'
        )
        self.technician = Technician.objects.create(
            user=self.user,
            phone_number='+15551234567'
        )

        self.template = NotificationTemplate.objects.create(
            name='test',
            category=Notification.CATEGORY_REPAIR_STATUS,
            default_priority=Notification.PRIORITY_MEDIUM,
            title_template='Test',
            message_template='Test',
            active=True
        )

        self.notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM,
            template=self.template,
            template_context={'test': 'value'}
        )

    @patch('core.services.sms_service.SMSService.retry_failed_delivery')
    @patch('core.services.email_service.EmailService.retry_failed_delivery')
    def test_retry_task_processes_pending_retries(self, mock_email_retry, mock_sms_retry):
        """Test that retry task processes pending retries."""
        now = timezone.now()

        # Create pending email retry
        email_log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=5)
        )

        # Create pending SMS retry
        sms_log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15551234567',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=5)
        )

        mock_email_retry.return_value = True
        mock_sms_retry.return_value = True

        result = retry_failed_notifications()

        self.assertEqual(result['email_retries'], 1)
        self.assertEqual(result['sms_retries'], 1)
        mock_email_retry.assert_called_once()
        mock_sms_retry.assert_called_once()

    @patch('core.services.sms_service.SMSService.retry_failed_delivery')
    @patch('core.services.email_service.EmailService.retry_failed_delivery')
    def test_retry_task_with_no_pending(self, mock_email_retry, mock_sms_retry):
        """Test retry task when no retries are pending."""
        result = retry_failed_notifications()

        self.assertEqual(result['email_retries'], 0)
        self.assertEqual(result['sms_retries'], 0)
        mock_email_retry.assert_not_called()
        mock_sms_retry.assert_not_called()

    @patch('core.services.email_service.EmailService.retry_failed_delivery')
    def test_retry_task_skips_failed_retries(self, mock_email_retry):
        """Test that retry task continues even if some retries fail."""
        now = timezone.now()

        # Create two pending retries
        log1 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test1@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=5)
        )

        log2 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test2@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=5)
        )

        # First retry succeeds, second fails
        mock_email_retry.side_effect = [True, False]

        result = retry_failed_notifications()

        # Should still report 1 success
        self.assertEqual(result['email_retries'], 1)


class SendDailyDigestsTaskTest(TestCase):
    """Test cases for send_daily_digests periodic task."""

    def setUp(self):
        """Set up test data."""
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

        self.prefs = TechnicianNotificationPreference.objects.create(
            technician=self.technician,
            receive_email_notifications=True,
            digest_enabled=True
        )

    @patch('core.services.notification_service.NotificationBatchService.send_daily_digest')
    def test_digest_task_sends_to_users_with_unread(self, mock_send):
        """Test that digest is sent to users with unread notifications."""
        # Create unread notifications from past 24 hours
        yesterday = timezone.now() - timedelta(hours=12)

        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM,
            read=False,
            created_at=yesterday
        )

        mock_send.return_value = True

        result = send_daily_digests()

        self.assertEqual(result['digests_sent'], 1)
        mock_send.assert_called_once()

        # Verify correct notifications were passed
        call_args = mock_send.call_args
        notifications_list = call_args[1]['notifications']
        self.assertEqual(len(notifications_list), 1)
        self.assertEqual(notifications_list[0].id, notification.id)

    @patch('core.services.notification_service.NotificationBatchService.send_daily_digest')
    def test_digest_task_skips_users_without_unread(self, mock_send):
        """Test that digest is not sent to users without unread notifications."""
        result = send_daily_digests()

        self.assertEqual(result['digests_sent'], 0)
        mock_send.assert_not_called()

    @patch('core.services.notification_service.NotificationBatchService.send_daily_digest')
    def test_digest_task_skips_digest_disabled(self, mock_send):
        """Test that digest is not sent when email notifications are disabled."""
        self.prefs.receive_email_notifications = False
        self.prefs.save()

        # Create unread notification
        Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            read=False
        )

        result = send_daily_digests()

        self.assertEqual(result['digests_sent'], 0)
        mock_send.assert_not_called()

    @patch('core.services.notification_service.NotificationBatchService.send_daily_digest')
    def test_digest_task_skips_email_disabled(self, mock_send):
        """Test that digest is not sent when email is disabled."""
        self.prefs.receive_email_notifications = False
        self.prefs.save()

        # Create unread notification
        Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            read=False
        )

        result = send_daily_digests()

        self.assertEqual(result['digests_sent'], 0)
        mock_send.assert_not_called()


class CleanupOldDeliveryLogsTaskTest(TestCase):
    """Test cases for cleanup_old_delivery_logs periodic task."""

    def setUp(self):
        """Set up test data."""
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

        self.notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM
        )

    def test_cleanup_deletes_old_delivered_logs(self):
        """Test that cleanup deletes old delivered logs."""
        # Create log and manually update created_at (can't set in create due to auto_now_add)
        old_log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='delivered'
        )

        # Manually update created_at to 100 days ago
        old_date = timezone.now() - timedelta(days=100)
        NotificationDeliveryLog.objects.filter(id=old_log.id).update(
            created_at=old_date
        )

        result = cleanup_old_delivery_logs()

        self.assertEqual(result['logs_deleted'], 1)
        self.assertFalse(
            NotificationDeliveryLog.objects.filter(id=old_log.id).exists()
        )

    def test_cleanup_keeps_recent_delivered_logs(self):
        """Test that cleanup keeps recent delivered logs."""
        # Create log less than 90 days old
        recent_date = timezone.now() - timedelta(days=30)
        recent_log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='delivered',
            created_at=recent_date
        )

        result = cleanup_old_delivery_logs()

        self.assertEqual(result['logs_deleted'], 0)
        self.assertTrue(
            NotificationDeliveryLog.objects.filter(id=recent_log.id).exists()
        )

    def test_cleanup_keeps_old_failed_logs(self):
        """Test that cleanup keeps old failed logs for analysis."""
        # Create old failed log
        old_date = timezone.now() - timedelta(days=100)
        failed_log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='failed_permanent',
            created_at=old_date
        )

        result = cleanup_old_delivery_logs()

        self.assertEqual(result['logs_deleted'], 0)
        self.assertTrue(
            NotificationDeliveryLog.objects.filter(id=failed_log.id).exists()
        )

    def test_cleanup_keeps_pending_retry_logs(self):
        """Test that cleanup keeps pending retry logs."""
        # Create old pending retry log
        old_date = timezone.now() - timedelta(days=100)
        pending_log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=1,
            created_at=old_date
        )

        result = cleanup_old_delivery_logs()

        self.assertEqual(result['logs_deleted'], 0)
        self.assertTrue(
            NotificationDeliveryLog.objects.filter(id=pending_log.id).exists()
        )


class SendScheduledNotificationsTaskTest(TestCase):
    """Test cases for send_scheduled_notifications task."""

    def setUp(self):
        """Set up test data."""
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

        self.template = NotificationTemplate.objects.create(
            name='scheduled_test',
            category=Notification.CATEGORY_REPAIR_STATUS,
            default_priority=Notification.PRIORITY_MEDIUM,
            title_template='Scheduled Test',
            message_template='Test message',
            active=True
        )

    @patch('core.services.notification_service.NotificationService._queue_delivery')
    def test_scheduled_task_processes_due_notifications(self, mock_queue):
        """Test that scheduled notifications are processed when due."""
        # Create notification scheduled for the past
        past_time = timezone.now() - timedelta(hours=1)
        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Scheduled Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM,
            template=self.template,
            template_context={'test': 'value'},
            scheduled_for=past_time,
            email_sent=False,
            sms_sent=False
        )

        result = send_scheduled_notifications()

        self.assertEqual(result['notifications_queued'], 1)
        mock_queue.assert_called_once()

    @patch('core.services.notification_service.NotificationService._queue_delivery')
    def test_scheduled_task_skips_future_notifications(self, mock_queue):
        """Test that future scheduled notifications are not processed."""
        # Create notification scheduled for the future
        future_time = timezone.now() + timedelta(hours=2)
        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Future Test',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM,
            template=self.template,
            template_context={'test': 'value'},
            scheduled_for=future_time,
            email_sent=False,
            sms_sent=False
        )

        result = send_scheduled_notifications()

        self.assertEqual(result['notifications_queued'], 0)
        mock_queue.assert_not_called()

    @patch('core.services.notification_service.NotificationService._queue_delivery')
    def test_scheduled_task_skips_already_sent(self, mock_queue):
        """Test that already-sent scheduled notifications are skipped."""
        # Create notification already sent
        past_time = timezone.now() - timedelta(hours=1)
        notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Already Sent',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM,
            template=self.template,
            template_context={'test': 'value'},
            scheduled_for=past_time,
            email_sent=True,  # Already sent
            sms_sent=False
        )

        result = send_scheduled_notifications()

        self.assertEqual(result['notifications_queued'], 0)
        mock_queue.assert_not_called()
