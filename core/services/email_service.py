"""
Email Service for sending notification emails via AWS SES.

This service handles:
- Sending HTML/text multipart emails
- Tracking delivery status in NotificationDeliveryLog
- Error handling and retry scheduling
- Integration with AWS SES SMTP
"""

import logging
from datetime import timedelta
from typing import Optional, Tuple
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog
from core.utils.logging import mask_email

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending notification emails via AWS SES.

    Usage:
        success, log = EmailService.send_notification_email(
            notification_id=123,
            recipient_email='user@example.com',
            subject='Test',
            html_content='<p>Hello</p>',
            text_content='Hello'
        )
    """

    # Retry delays in minutes (exponential backoff)
    RETRY_DELAYS = [5, 10, 20]  # Retry at 5, 15, and 35 minutes total
    MAX_RETRIES = 3

    @staticmethod
    def send_notification_email(
        notification_id: Optional[int],
        recipient_email: str,
        subject: str,
        html_content: str,
        text_content: str,
        attempt_number: int = 1
    ) -> Tuple[bool, Optional[NotificationDeliveryLog]]:
        """
        Send notification email via AWS SES.

        Args:
            notification_id: ID of related Notification (None for digests)
            recipient_email: Recipient email address
            subject: Email subject line
            html_content: HTML email body
            text_content: Plain text email body
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

        # Create delivery log
        delivery_log = NotificationDeliveryLog.objects.create(
            notification=notification,
            channel='email',
            recipient_email=recipient_email,
            status='pending',
            attempt_number=attempt_number,
            next_retry_at=None
        )

        try:
            # Shop-branded sender: From shows the shop name (mail still goes
            # out through the platform's SES-verified address) and replies
            # route to the shop's own email. Branding was resolved per-tenant
            # by NotificationService and persisted on the notification.
            from core.email_utils import shop_sender
            branding = (notification.template_context or {}).get('branding', {}) if notification else {}
            from_email, reply_to = shop_sender(
                shop_name=branding.get('company_name'),
                reply_to_email=branding.get('support_email'),
            )

            # Create multipart email (HTML + plain text)
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=[recipient_email],
                reply_to=reply_to,
            )

            # Attach HTML version
            if html_content:
                email.attach_alternative(html_content, "text/html")

            # Send email
            result = email.send(fail_silently=False)

            if result == 1:
                # Success
                delivery_log.status = 'delivered'
                delivery_log.delivered_at = timezone.now()

                # Extract message ID if available
                if hasattr(email, 'extra_headers'):
                    delivery_log.provider_message_id = email.extra_headers.get(
                        'Message-ID',
                        ''
                    )

                delivery_log.save()

                # Update notification
                if notification:
                    notification.email_sent = True
                    notification.save(update_fields=['email_sent'])

                logger.info(
                    f"Email sent successfully to {mask_email(recipient_email)} "
                    f"(notification {notification_id})"
                )
                return True, delivery_log

            else:
                # Send returned 0 (no emails sent)
                raise Exception("Email send returned 0")

        except Exception as e:
            # Handle failure
            error_message = str(e)
            logger.error(
                f"Failed to send email to {mask_email(recipient_email)}: {error_message}"
            )

            # Update delivery log
            delivery_log.status = 'failed'
            delivery_log.error_message = error_message[:500]  # Truncate to fit
            delivery_log.failed_at = timezone.now()

            # Determine if we should retry
            if attempt_number < EmailService.MAX_RETRIES:
                # Schedule retry with exponential backoff
                retry_delay_minutes = EmailService.RETRY_DELAYS[attempt_number - 1]
                delivery_log.next_retry_at = timezone.now() + timedelta(
                    minutes=retry_delay_minutes
                )
                delivery_log.status = 'pending_retry'

                logger.info(
                    f"Scheduled email retry {attempt_number + 1} "
                    f"in {retry_delay_minutes} minutes"
                )

            else:
                # Max retries exceeded
                delivery_log.status = 'failed_permanent'
                logger.error(
                    f"Email to {mask_email(recipient_email)} failed after "
                    f"{EmailService.MAX_RETRIES} attempts"
                )

            delivery_log.save()
            return False, delivery_log

    @staticmethod
    def get_pending_retries():
        """
        Get email delivery logs that are ready for retry.

        Returns:
            QuerySet of NotificationDeliveryLog objects ready for retry
        """
        now = timezone.now()
        return NotificationDeliveryLog.objects.filter(
            channel='email',
            status='pending_retry',
            next_retry_at__lte=now,
            attempt_number__lt=EmailService.MAX_RETRIES
        )

    @staticmethod
    def retry_failed_delivery(log: NotificationDeliveryLog) -> bool:
        """
        Retry a failed email delivery.

        Args:
            log: NotificationDeliveryLog to retry

        Returns:
            True if retry was queued, False otherwise
        """
        if log.channel != 'email':
            logger.warning(f"Delivery log {log.id} is not for email channel")
            return False

        if log.attempt_number >= EmailService.MAX_RETRIES:
            logger.warning(
                f"Delivery log {log.id} has exceeded max retries"
            )
            return False

        if not log.notification:
            logger.warning(f"Delivery log {log.id} has no linked notification")
            return False

        # Queue retry task
        try:
            from core.tasks import send_notification_email

            # Get email content from notification template
            if log.notification.template:
                rendered = log.notification.template.render(
                    log.notification.template_context
                )

                send_notification_email.delay(
                    notification_id=log.notification.id,
                    recipient_email=log.recipient_email,
                    subject=rendered.get('email_subject', log.notification.title),
                    html_content=rendered.get('email_html', ''),
                    text_content=rendered.get('email_text', log.notification.message),
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
