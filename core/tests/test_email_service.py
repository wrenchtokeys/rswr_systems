"""
Unit tests for EmailService.

Tests cover:
- Email sending via AWS SES
- Delivery tracking in NotificationDeliveryLog
- Retry logic with exponential backoff
- Error handling
- Pending retry queries
- Failed delivery retry queueing
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMultiAlternatives

from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog
from core.models.notification_template import NotificationTemplate
from core.services.email_service import EmailService
from apps.technician_portal.models import Technician
from django.contrib.auth.models import User


class EmailServiceTest(TestCase):
    """Test cases for EmailService."""

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
            name='test_email',
            category=Notification.CATEGORY_REPAIR_STATUS,
            default_priority=Notification.PRIORITY_MEDIUM,
            title_template='Test Email',
            message_template='Test message',
            active=True
        )

        # Create test notification
        self.notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test Notification',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_MEDIUM,
            template=self.template
        )

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_success(self, mock_send):
        """Test successful email sending."""
        mock_send.return_value = 1  # Django send() returns 1 on success

        success, log = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test Subject',
            html_content='<p>Test HTML</p>',
            text_content='Test Text'
        )

        self.assertTrue(success)
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'delivered')
        self.assertEqual(log.channel, 'email')
        self.assertEqual(log.recipient_email, 'test@example.com')
        self.assertEqual(log.attempt_number, 1)
        self.assertIsNotNone(log.delivered_at)

        # Check notification was updated
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.email_sent)

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_failure(self, mock_send):
        """Test email sending failure."""
        mock_send.side_effect = Exception("SMTP connection failed")

        success, log = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test Subject',
            html_content='<p>Test HTML</p>',
            text_content='Test Text',
            attempt_number=1
        )

        self.assertFalse(success)
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'pending_retry')
        self.assertIsNotNone(log.failed_at)
        self.assertIn('SMTP connection failed', log.error_message)
        self.assertIsNotNone(log.next_retry_at)

        # Check notification was NOT marked as sent
        self.notification.refresh_from_db()
        self.assertFalse(self.notification.email_sent)

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_retry_scheduling(self, mock_send):
        """Test that retry is scheduled with correct delay."""
        mock_send.side_effect = Exception("Temporary failure")

        # Attempt 1: should schedule retry in 5 minutes
        success, log = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test',
            attempt_number=1
        )

        self.assertEqual(log.status, 'pending_retry')
        expected_retry = timezone.now() + timedelta(minutes=5)
        # Allow 10-second window for timing
        self.assertAlmostEqual(
            log.next_retry_at.timestamp(),
            expected_retry.timestamp(),
            delta=10
        )

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_max_retries(self, mock_send):
        """Test that max retries marks as failed_permanent."""
        mock_send.side_effect = Exception("Permanent failure")

        # Attempt 3 (last attempt)
        success, log = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test',
            attempt_number=3
        )

        self.assertFalse(success)
        self.assertEqual(log.status, 'failed_permanent')
        self.assertIsNone(log.next_retry_at)  # No more retries

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_creates_multipart(self, mock_send):
        """Test that email is created as multipart (HTML + text)."""
        mock_send.return_value = 1

        with patch('core.services.email_service.EmailMultiAlternatives') as mock_email_class:
            mock_email_instance = MagicMock()
            mock_email_class.return_value = mock_email_instance
            mock_email_instance.send.return_value = 1
            mock_email_instance.extra_headers = {'Message-ID': 'test-msg-id'}

            EmailService.send_notification_email(
                notification_id=self.notification.id,
                recipient_email='test@example.com',
                subject='Test Subject',
                html_content='<p>Test HTML</p>',
                text_content='Test Text'
            )

            # Verify EmailMultiAlternatives was created correctly
            mock_email_class.assert_called_once()
            call_kwargs = mock_email_class.call_args[1]
            self.assertEqual(call_kwargs['subject'], 'Test Subject')
            self.assertEqual(call_kwargs['body'], 'Test Text')
            self.assertEqual(call_kwargs['to'], ['test@example.com'])

            # Verify HTML alternative was attached
            mock_email_instance.attach_alternative.assert_called_once_with(
                '<p>Test HTML</p>',
                "text/html"
            )

    def test_send_email_notification_not_found(self):
        """Test sending email for non-existent notification."""
        success, log = EmailService.send_notification_email(
            notification_id=999999,  # Non-existent
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test'
        )

        self.assertFalse(success)
        self.assertIsNone(log)

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_without_notification(self, mock_send):
        """Test sending email without notification (e.g., digest)."""
        mock_send.return_value = 1

        success, log = EmailService.send_notification_email(
            notification_id=None,  # No notification (digest email)
            recipient_email='test@example.com',
            subject='Daily Digest',
            html_content='<p>Digest</p>',
            text_content='Digest'
        )

        self.assertTrue(success)
        self.assertIsNotNone(log)
        self.assertIsNone(log.notification)
        self.assertEqual(log.status, 'delivered')

    def test_get_pending_retries(self):
        """Test querying pending retries."""
        # Create delivery logs with various statuses
        now = timezone.now()

        # Should be returned (ready for retry)
        log1 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test1@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=1)  # Past
        )

        # Should NOT be returned (future retry)
        log2 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test2@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now + timedelta(minutes=10)  # Future
        )

        # Should NOT be returned (max retries)
        log3 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test3@example.com',
            status='pending_retry',
            attempt_number=3,  # Max retries
            next_retry_at=now - timedelta(minutes=1)
        )

        # Should NOT be returned (wrong channel)
        log4 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15551234567',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=1)
        )

        # Should NOT be returned (already delivered)
        log5 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test5@example.com',
            status='delivered',
            attempt_number=1
        )

        pending = EmailService.get_pending_retries()

        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.first().id, log1.id)

    @patch('core.tasks.send_notification_email.delay')
    def test_retry_failed_delivery(self, mock_task):
        """Test retrying a failed delivery."""
        # Create failed delivery log
        log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=timezone.now()
        )

        # Set template context for retry
        self.notification.template_context = {
            'repair_id': '123',
            'status': 'approved'
        }
        self.notification.save()

        success = EmailService.retry_failed_delivery(log)

        self.assertTrue(success)
        self.assertTrue(mock_task.called)

        # Check task was called with attempt_number incremented
        call_kwargs = mock_task.call_args[1]
        self.assertEqual(call_kwargs['attempt_number'], 2)

    def test_retry_failed_delivery_wrong_channel(self):
        """Test that retry fails for non-email channel."""
        log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',  # Wrong channel
            recipient_phone='+15551234567',
            status='pending_retry',
            attempt_number=1
        )

        success = EmailService.retry_failed_delivery(log)

        self.assertFalse(success)

    def test_retry_failed_delivery_max_retries(self):
        """Test that retry fails when max retries exceeded."""
        log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=3  # Max retries
        )

        success = EmailService.retry_failed_delivery(log)

        self.assertFalse(success)

    def test_retry_failed_delivery_no_notification(self):
        """Test that retry fails when notification is missing."""
        log = NotificationDeliveryLog.objects.create(
            notification=None,  # No notification
            channel='email',
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=1
        )

        success = EmailService.retry_failed_delivery(log)

        self.assertFalse(success)

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_exponential_backoff_delays(self, mock_send):
        """Test that retry delays follow exponential backoff pattern."""
        mock_send.side_effect = Exception("Fail")

        # Attempt 1: 5 minutes
        success1, log1 = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test',
            attempt_number=1
        )

        expected1 = timezone.now() + timedelta(minutes=5)
        self.assertAlmostEqual(
            log1.next_retry_at.timestamp(),
            expected1.timestamp(),
            delta=10
        )

        # Attempt 2: 10 minutes
        success2, log2 = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test',
            attempt_number=2
        )

        expected2 = timezone.now() + timedelta(minutes=10)
        self.assertAlmostEqual(
            log2.next_retry_at.timestamp(),
            expected2.timestamp(),
            delta=10
        )

    @patch('core.services.email_service.EmailMultiAlternatives.send')
    def test_send_email_returns_zero(self, mock_send):
        """Test handling when send() returns 0 (no emails sent)."""
        mock_send.return_value = 0  # No emails sent

        success, log = EmailService.send_notification_email(
            notification_id=self.notification.id,
            recipient_email='test@example.com',
            subject='Test',
            html_content='<p>Test</p>',
            text_content='Test'
        )

        self.assertFalse(success)
        self.assertEqual(log.status, 'pending_retry')
        self.assertIn('Email send returned 0', log.error_message)
