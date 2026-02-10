"""
Unit tests for SMSService.

Tests cover:
- SMS sending via AWS SNS
- Phone number validation (E.164 format)
- Message truncation to 160 characters
- Delivery tracking with cost calculation
- Retry logic with exponential backoff
- Error handling
- Pending retry queries
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog
from core.models.notification_template import NotificationTemplate
from core.services.sms_service import SMSService, SMS_COST_PER_MESSAGE
from apps.technician_portal.models import Technician
from django.contrib.auth.models import User


class SMSServiceTest(TestCase):
    """Test cases for SMSService."""

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
            name='test_sms',
            category=Notification.CATEGORY_REPAIR_STATUS,
            default_priority=Notification.PRIORITY_URGENT,
            title_template='Test SMS',
            message_template='Test message',
            sms_template='Repair approved!',
            active=True
        )

        # Create test notification
        self.notification = Notification.objects.create(
            recipient_type=ContentType.objects.get_for_model(self.technician),
            recipient_id=self.technician.id,
            title='Test Notification',
            message='Test message',
            category=Notification.CATEGORY_REPAIR_STATUS,
            priority=Notification.PRIORITY_URGENT,
            template=self.template
        )

    def test_validate_phone_valid_us(self):
        """Test phone validation with valid US number."""
        valid = SMSService._validate_phone('+15551234567')
        self.assertTrue(valid)

    def test_validate_phone_valid_uk(self):
        """Test phone validation with valid UK number."""
        valid = SMSService._validate_phone('+447911123456')
        self.assertTrue(valid)

    def test_validate_phone_invalid_no_plus(self):
        """Test phone validation rejects number without + prefix."""
        valid = SMSService._validate_phone('15551234567')
        self.assertFalse(valid)

    def test_validate_phone_invalid_too_short(self):
        """Test phone validation rejects too-short number."""
        # E.164 regex allows +[1-9]\d{1,14}$ (2-15 digits total)
        # Test with just country code (no subscriber number)
        valid = SMSService._validate_phone('+1')
        self.assertFalse(valid)

    def test_validate_phone_invalid_too_long(self):
        """Test phone validation rejects too-long number."""
        valid = SMSService._validate_phone('+1234567890123456')  # 16 digits
        self.assertFalse(valid)

    def test_validate_phone_invalid_starts_with_zero(self):
        """Test phone validation rejects country code starting with 0."""
        valid = SMSService._validate_phone('+05551234567')
        self.assertFalse(valid)

    def test_validate_phone_invalid_empty(self):
        """Test phone validation rejects empty string."""
        valid = SMSService._validate_phone('')
        self.assertFalse(valid)

    def test_validate_phone_invalid_none(self):
        """Test phone validation rejects None."""
        valid = SMSService._validate_phone(None)
        self.assertFalse(valid)

    def test_validate_phone_invalid_contains_letters(self):
        """Test phone validation rejects phone with letters."""
        valid = SMSService._validate_phone('+1555ABC4567')
        self.assertFalse(valid)

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_success(self, mock_sns):
        """Test successful SMS sending."""
        mock_sns.return_value = 'test-message-id-123'

        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test SMS message'
        )

        self.assertTrue(success)
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'delivered')
        self.assertEqual(log.channel, 'sms')
        self.assertEqual(log.recipient_phone, '+15551234567')
        self.assertEqual(log.attempt_number, 1)
        self.assertEqual(log.estimated_cost, SMS_COST_PER_MESSAGE)
        self.assertEqual(log.provider_message_id, 'test-message-id-123')
        self.assertIsNotNone(log.delivered_at)

        # Check notification was updated
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.sms_sent)

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_failure(self, mock_sns):
        """Test SMS sending failure."""
        mock_sns.side_effect = Exception("SNS error: Throttling")

        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test SMS',
            attempt_number=1
        )

        self.assertFalse(success)
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'pending_retry')
        self.assertIsNotNone(log.failed_at)
        self.assertIn('SNS error: Throttling', log.error_message)
        self.assertIsNotNone(log.next_retry_at)

        # Check notification was NOT marked as sent
        self.notification.refresh_from_db()
        self.assertFalse(self.notification.sms_sent)

    def test_send_sms_invalid_phone(self):
        """Test SMS sending with invalid phone number."""
        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='invalid-phone',  # Invalid format
            message='Test SMS'
        )

        self.assertFalse(success)
        self.assertIsNone(log)

        # No delivery log should be created for invalid phone
        self.assertEqual(
            NotificationDeliveryLog.objects.filter(
                notification=self.notification
            ).count(),
            0
        )

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_message_truncation(self, mock_sns):
        """Test that long messages are truncated to 160 characters."""
        mock_sns.return_value = 'test-message-id'

        # Create message longer than 160 characters
        long_message = 'A' * 200

        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message=long_message
        )

        # Check that SNS was called with truncated message
        sent_message = mock_sns.call_args[0][1]
        self.assertEqual(len(sent_message), 160)
        self.assertTrue(sent_message.endswith('...'))

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_exact_160_chars(self, mock_sns):
        """Test that 160-character message is not truncated."""
        mock_sns.return_value = 'test-message-id'

        # Create message exactly 160 characters
        message = 'A' * 160

        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message=message
        )

        # Message should not be truncated
        sent_message = mock_sns.call_args[0][1]
        self.assertEqual(len(sent_message), 160)
        self.assertFalse(sent_message.endswith('...'))

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_retry_scheduling(self, mock_sns):
        """Test that retry is scheduled with correct delay."""
        mock_sns.side_effect = Exception("Temporary failure")

        # Attempt 1: should schedule retry in 5 minutes
        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test',
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

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_max_retries(self, mock_sns):
        """Test that max retries marks as failed_permanent."""
        mock_sns.side_effect = Exception("Permanent failure")

        # Attempt 3 (last attempt)
        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test',
            attempt_number=3
        )

        self.assertFalse(success)
        self.assertEqual(log.status, 'failed_permanent')
        self.assertIsNone(log.next_retry_at)  # No more retries

    def test_send_sms_notification_not_found(self):
        """Test sending SMS for non-existent notification."""
        success, log = SMSService.send_notification_sms(
            notification_id=999999,  # Non-existent
            recipient_phone='+15551234567',
            message='Test'
        )

        self.assertFalse(success)
        self.assertIsNone(log)

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_send_sms_cost_tracking(self, mock_sns):
        """Test that SMS cost is tracked correctly."""
        mock_sns.return_value = 'test-message-id'

        success, log = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test'
        )

        self.assertEqual(log.estimated_cost, Decimal('0.00645'))

    @patch('boto3.client')
    def test_send_via_sns_success(self, mock_boto_client):
        """Test AWS SNS publish call."""
        mock_sns_client = MagicMock()
        mock_boto_client.return_value = mock_sns_client
        mock_sns_client.publish.return_value = {'MessageId': 'test-id-456'}

        message_id = SMSService._send_via_sns('+15551234567', 'Test message')

        self.assertEqual(message_id, 'test-id-456')

        # Verify SNS publish was called with correct parameters
        mock_sns_client.publish.assert_called_once()
        call_kwargs = mock_sns_client.publish.call_args[1]
        self.assertEqual(call_kwargs['PhoneNumber'], '+15551234567')
        self.assertEqual(call_kwargs['Message'], 'Test message')
        self.assertEqual(
            call_kwargs['MessageAttributes']['AWS.SNS.SMS.SMSType']['StringValue'],
            'Transactional'
        )

    @patch('boto3.client')
    def test_send_via_sns_client_error(self, mock_boto_client):
        """Test AWS SNS ClientError handling."""
        from botocore.exceptions import ClientError

        mock_sns_client = MagicMock()
        mock_boto_client.return_value = mock_sns_client

        # Simulate ClientError
        mock_sns_client.publish.side_effect = ClientError(
            {'Error': {'Code': 'InvalidParameter', 'Message': 'Invalid phone'}},
            'publish'
        )

        with self.assertRaises(Exception) as context:
            SMSService._send_via_sns('+15551234567', 'Test')

        self.assertIn('InvalidParameter', str(context.exception))

    def test_get_pending_retries(self):
        """Test querying pending retries."""
        now = timezone.now()

        # Should be returned (ready for retry)
        log1 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15551111111',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=1)  # Past
        )

        # Should NOT be returned (future retry)
        log2 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15552222222',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now + timedelta(minutes=10)  # Future
        )

        # Should NOT be returned (max retries)
        log3 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15553333333',
            status='pending_retry',
            attempt_number=3,  # Max retries
            next_retry_at=now - timedelta(minutes=1)
        )

        # Should NOT be returned (wrong channel)
        log4 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=1,
            next_retry_at=now - timedelta(minutes=1)
        )

        # Should NOT be returned (already delivered)
        log5 = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15555555555',
            status='delivered',
            attempt_number=1
        )

        pending = SMSService.get_pending_retries()

        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.first().id, log1.id)

    @patch('core.tasks.send_notification_sms.delay')
    def test_retry_failed_delivery(self, mock_task):
        """Test retrying a failed delivery."""
        # Create failed delivery log
        log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15551234567',
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

        success = SMSService.retry_failed_delivery(log)

        self.assertTrue(success)
        self.assertTrue(mock_task.called)

        # Check task was called with attempt_number incremented
        call_kwargs = mock_task.call_args[1]
        self.assertEqual(call_kwargs['attempt_number'], 2)

    def test_retry_failed_delivery_wrong_channel(self):
        """Test that retry fails for non-SMS channel."""
        log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',  # Wrong channel
            recipient_email='test@example.com',
            status='pending_retry',
            attempt_number=1
        )

        success = SMSService.retry_failed_delivery(log)

        self.assertFalse(success)

    def test_retry_failed_delivery_max_retries(self):
        """Test that retry fails when max retries exceeded."""
        log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='sms',
            recipient_phone='+15551234567',
            status='pending_retry',
            attempt_number=3  # Max retries
        )

        success = SMSService.retry_failed_delivery(log)

        self.assertFalse(success)

    def test_retry_failed_delivery_no_notification(self):
        """Test that retry fails when notification is missing."""
        log = NotificationDeliveryLog.objects.create(
            notification=None,  # No notification
            channel='sms',
            recipient_phone='+15551234567',
            status='pending_retry',
            attempt_number=1
        )

        success = SMSService.retry_failed_delivery(log)

        self.assertFalse(success)

    @patch('core.services.sms_service.SMSService._send_via_sns')
    def test_exponential_backoff_delays(self, mock_sns):
        """Test that retry delays follow exponential backoff pattern."""
        mock_sns.side_effect = Exception("Fail")

        # Attempt 1: 5 minutes
        success1, log1 = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test',
            attempt_number=1
        )

        expected1 = timezone.now() + timedelta(minutes=5)
        self.assertAlmostEqual(
            log1.next_retry_at.timestamp(),
            expected1.timestamp(),
            delta=10
        )

        # Attempt 2: 10 minutes
        success2, log2 = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test',
            attempt_number=2
        )

        expected2 = timezone.now() + timedelta(minutes=10)
        self.assertAlmostEqual(
            log2.next_retry_at.timestamp(),
            expected2.timestamp(),
            delta=10
        )

        # Attempt 3: 20 minutes
        success3, log3 = SMSService.send_notification_sms(
            notification_id=self.notification.id,
            recipient_phone='+15551234567',
            message='Test',
            attempt_number=3
        )

        # Attempt 3 is the last, so it should be marked failed_permanent
        self.assertEqual(log3.status, 'failed_permanent')
        self.assertIsNone(log3.next_retry_at)
