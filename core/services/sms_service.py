"""
SMS Service for sending notification messages via AWS SNS.

This service handles:
- Sending SMS messages via AWS SNS
- Phone number validation (E.164 format)
- Message truncation to 160 characters
- Tracking delivery status and costs
- Error handling and retry scheduling
"""

import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Optional, Tuple
from django.conf import settings
from django.utils import timezone
from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog
from core.utils.logging import mask_phone

logger = logging.getLogger(__name__)

# SMS cost per message (AWS SNS pricing for US)
SMS_COST_PER_MESSAGE = Decimal('0.00645')


class SMSService:
    """
    Service for sending notification SMS messages via AWS SNS.

    Usage:
        success, log = SMSService.send_notification_sms(
            notification_id=123,
            recipient_phone='+15551234567',
            message='Your repair has been approved!'
        )
    """

    # E.164 phone format regex: +[country code][number]
    E164_PATTERN = re.compile(r'^\+[1-9]\d{1,14}$')

    # Retry delays in minutes (exponential backoff)
    RETRY_DELAYS = [5, 10, 20]  # Retry at 5, 15, and 35 minutes total
    MAX_RETRIES = 3

    # SMS character limit
    MAX_SMS_LENGTH = 160

    @staticmethod
    def send_notification_sms(
        notification_id: Optional[int],
        recipient_phone: str,
        message: str,
        attempt_number: int = 1
    ) -> Tuple[bool, Optional[NotificationDeliveryLog]]:
        """
        Send notification SMS via AWS SNS.

        Args:
            notification_id: ID of related Notification
            recipient_phone: Recipient phone number (E.164 format)
            message: SMS message text
            attempt_number: Current delivery attempt number (1-indexed)

        Returns:
            Tuple of (success: bool, log: NotificationDeliveryLog or None)
        """
        notification = None
        if notification_id:
            try:
                notification = Notification.objects.get(id=notification_id)
            except Notification.DoesNotExist:
                logger.error(f"Notification {notification_id} not found")
                return False, None

        # Validate phone number
        if not SMSService._validate_phone(recipient_phone):
            logger.error(
                f"Invalid phone number format: {mask_phone(recipient_phone)}. "
                f"Must be E.164 format (e.g., +15551234567)"
            )
            return False, None

        # Truncate message to SMS limit
        if len(message) > SMSService.MAX_SMS_LENGTH:
            original_length = len(message)
            message = message[:SMSService.MAX_SMS_LENGTH - 3] + '...'
            logger.warning(
                f"SMS message truncated from {original_length} to "
                f"{len(message)} characters"
            )

        # Create delivery log
        delivery_log = NotificationDeliveryLog.objects.create(
            notification=notification,
            channel='sms',
            recipient_phone=recipient_phone,
            status='pending',
            attempt_number=attempt_number,
            cost=SMS_COST_PER_MESSAGE,
            next_retry_at=None
        )

        try:
            # Send SMS via AWS SNS
            message_id = SMSService._send_via_sns(recipient_phone, message)

            # Success
            delivery_log.status = 'delivered'
            delivery_log.delivered_at = timezone.now()
            delivery_log.provider_message_id = message_id
            delivery_log.save()

            # Update notification
            if notification:
                notification.sms_sent = True
                notification.save(update_fields=['sms_sent'])

            logger.info(
                f"SMS sent successfully to {mask_phone(recipient_phone)} "
                f"(notification {notification_id}, message_id {message_id})"
            )
            return True, delivery_log

        except Exception as e:
            # Handle failure
            error_message = str(e)
            logger.error(
                f"Failed to send SMS to {mask_phone(recipient_phone)}: {error_message}"
            )

            # Update delivery log
            delivery_log.status = 'failed'
            delivery_log.error_message = error_message[:500]  # Truncate to fit
            delivery_log.failed_at = timezone.now()

            # Determine if we should retry
            if attempt_number < SMSService.MAX_RETRIES:
                # Schedule retry with exponential backoff
                retry_delay_minutes = SMSService.RETRY_DELAYS[attempt_number - 1]
                delivery_log.next_retry_at = timezone.now() + timedelta(
                    minutes=retry_delay_minutes
                )
                delivery_log.status = 'pending_retry'

                logger.info(
                    f"Scheduled SMS retry {attempt_number + 1} "
                    f"in {retry_delay_minutes} minutes"
                )

            else:
                # Max retries exceeded
                delivery_log.status = 'failed_permanent'
                logger.error(
                    f"SMS to {mask_phone(recipient_phone)} failed after "
                    f"{SMSService.MAX_RETRIES} attempts"
                )

            delivery_log.save()
            return False, delivery_log

    @staticmethod
    def _validate_phone(phone: str) -> bool:
        """
        Validate phone number is in E.164 format.

        Args:
            phone: Phone number string

        Returns:
            True if valid E.164 format, False otherwise
        """
        if not phone:
            return False

        return bool(SMSService.E164_PATTERN.match(phone))

    @staticmethod
    def _send_via_sns(phone: str, message: str) -> str:
        """
        Send SMS via AWS SNS.

        Args:
            phone: Recipient phone number (E.164 format)
            message: Message text

        Returns:
            AWS SNS message ID

        Raises:
            Exception: If SNS send fails
        """
        try:
            import boto3
            from botocore.exceptions import ClientError

            # Initialize SNS client
            sns_client = boto3.client(
                'sns',
                region_name=getattr(settings, 'AWS_SNS_REGION_NAME', 'us-east-1'),
                aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
            )

            # Send SMS
            response = sns_client.publish(
                PhoneNumber=phone,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SenderID': {
                        'DataType': 'String',
                        'StringValue': 'RS_Systems'  # Optional: shows as sender name
                    },
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'  # Higher priority, higher cost
                    }
                }
            )

            message_id = response.get('MessageId', '')
            logger.debug(f"SNS publish successful: {message_id}")
            return message_id

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"SNS ClientError {error_code}: {error_message}")
            raise Exception(f"SNS error: {error_code} - {error_message}")

        except Exception as e:
            logger.exception(f"Unexpected error sending SMS: {e}")
            raise

    @staticmethod
    def get_pending_retries():
        """
        Get SMS delivery logs that are ready for retry.

        Returns:
            QuerySet of NotificationDeliveryLog objects ready for retry
        """
        now = timezone.now()
        return NotificationDeliveryLog.objects.filter(
            channel='sms',
            status='pending_retry',
            next_retry_at__lte=now,
            attempt_number__lt=SMSService.MAX_RETRIES
        )

    @staticmethod
    def retry_failed_delivery(log: NotificationDeliveryLog) -> bool:
        """
        Retry a failed SMS delivery.

        Args:
            log: NotificationDeliveryLog to retry

        Returns:
            True if retry was queued, False otherwise
        """
        if log.channel != 'sms':
            logger.warning(f"Delivery log {log.id} is not for SMS channel")
            return False

        if log.attempt_number >= SMSService.MAX_RETRIES:
            logger.warning(
                f"Delivery log {log.id} has exceeded max retries"
            )
            return False

        if not log.notification:
            logger.warning(f"Delivery log {log.id} has no linked notification")
            return False

        # Queue retry task
        try:
            from core.tasks import send_notification_sms

            # Get SMS message from notification template
            if log.notification.template:
                rendered = log.notification.template.render(
                    log.notification.template_context
                )
                sms_message = rendered.get('sms', log.notification.message[:160])
            else:
                sms_message = log.notification.message[:160]

            send_notification_sms.delay(
                notification_id=log.notification.id,
                recipient_phone=log.recipient_phone,
                message=sms_message,
                attempt_number=log.attempt_number + 1
            )

            logger.info(
                f"Queued retry {log.attempt_number + 1} for "
                f"delivery log {log.id}"
            )
            return True

        except Exception as e:
            logger.exception(f"Error queueing retry: {e}")
            return False

        return False
