"""
Celery tasks for the notification system.

This module contains all asynchronous tasks for:
- Email delivery
- SMS delivery
- Retry logic for failed deliveries
- Daily digest emails
- Cleanup of old delivery logs
"""

import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from core.services.email_service import EmailService
from core.services.sms_service import SMSService
from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_notification_email(
    self,
    notification_id: int,
    recipient_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    attempt_number: int = 1
):
    """
    Send notification email via AWS SES.

    This task is queued by NotificationService when creating notifications.
    It uses EmailService to send the actual email and track delivery.

    Args:
        notification_id: ID of Notification object (None for digests)
        recipient_email: Recipient email address
        subject: Email subject line
        html_content: HTML email body
        text_content: Plain text email body
        attempt_number: Current delivery attempt (1-indexed)

    Raises:
        Exception: Retries task on failure up to max_retries
    """
    try:
        logger.info(
            f"Sending email for notification {notification_id} "
            f"to {recipient_email} (attempt {attempt_number})"
        )

        success, delivery_log = EmailService.send_notification_email(
            notification_id=notification_id,
            recipient_email=recipient_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            attempt_number=attempt_number
        )

        if success:
            logger.info(
                f"Email sent successfully (notification {notification_id})"
            )
        else:
            logger.warning(
                f"Email send failed (notification {notification_id}), "
                f"will retry if attempts remain"
            )

        return success

    except Exception as e:
        logger.exception(
            f"Error in send_notification_email task: {e}"
        )
        # Retry task with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_notification_sms(
    self,
    notification_id: int,
    recipient_phone: str,
    message: str,
    attempt_number: int = 1
):
    """
    Send notification SMS via AWS SNS.

    This task is queued by NotificationService when creating notifications.
    It uses SMSService to send the actual SMS and track delivery.

    Args:
        notification_id: ID of Notification object
        recipient_phone: Recipient phone number (E.164 format)
        message: SMS message text (max 160 chars)
        attempt_number: Current delivery attempt (1-indexed)

    Raises:
        Exception: Retries task on failure up to max_retries
    """
    try:
        logger.info(
            f"Sending SMS for notification {notification_id} "
            f"to {recipient_phone} (attempt {attempt_number})"
        )

        success, delivery_log = SMSService.send_notification_sms(
            notification_id=notification_id,
            recipient_phone=recipient_phone,
            message=message,
            attempt_number=attempt_number
        )

        if success:
            logger.info(
                f"SMS sent successfully (notification {notification_id})"
            )
        else:
            logger.warning(
                f"SMS send failed (notification {notification_id}), "
                f"will retry if attempts remain"
            )

        return success

    except Exception as e:
        logger.exception(
            f"Error in send_notification_sms task: {e}"
        )
        # Retry task with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task
def retry_failed_notifications():
    """
    Periodic task to retry failed email and SMS deliveries.

    Runs every 5 minutes (configured in celery.py beat_schedule).
    Checks for delivery logs with status='pending_retry' and
    next_retry_at <= now, then re-queues them.

    This task is idempotent and safe to run multiple times.
    """
    logger.info("Starting retry_failed_notifications task")

    # Get pending retries for email
    email_retries = EmailService.get_pending_retries()
    email_count = 0

    for log in email_retries:
        if EmailService.retry_failed_delivery(log):
            email_count += 1

    # Get pending retries for SMS
    sms_retries = SMSService.get_pending_retries()
    sms_count = 0

    for log in sms_retries:
        if SMSService.retry_failed_delivery(log):
            sms_count += 1

    logger.info(
        f"Retry task completed: {email_count} emails, {sms_count} SMS "
        f"queued for retry"
    )

    return {
        'email_retries': email_count,
        'sms_retries': sms_count
    }


@shared_task
def send_daily_digests():
    """
    Send daily digest emails to users who have digest mode enabled.

    Runs daily at 9 AM (configured in celery.py beat_schedule).
    Collects unread notifications from the past 24 hours and sends
    a summary email to users with digest preferences enabled.

    This task queries both Technician and CustomerUser preferences.
    """
    logger.info("Starting send_daily_digests task")

    from core.models.notification_preferences import (
        TechnicianNotificationPreference,
        CustomerNotificationPreference
    )
    from core.services.notification_service import NotificationBatchService

    digest_count = 0
    yesterday = timezone.now() - timedelta(days=1)

    # Process technician digests (optimized with select_related)
    tech_prefs = TechnicianNotificationPreference.objects.filter(
        receive_email_notifications=True
    ).select_related('technician', 'technician__user')

    for pref in tech_prefs:
        # Get unread notifications from past 24 hours
        from django.contrib.contenttypes.models import ContentType
        tech_content_type = ContentType.objects.get_for_model(pref.technician)

        notifications = Notification.objects.filter(
            recipient_type=tech_content_type,
            recipient_id=pref.technician.id,
            read=False,
            created_at__gte=yesterday
        ).select_related('repair', 'customer', 'template').order_by('-created_at')

        if notifications.exists():
            success = NotificationBatchService.send_daily_digest(
                user=pref.technician,
                notifications=list(notifications)
            )
            if success:
                digest_count += 1

    # Process customer digests (optimized with select_related)
    customer_prefs = CustomerNotificationPreference.objects.filter(
        receive_email_notifications=True
    ).select_related('customer')

    for pref in customer_prefs:
        # Get unread notifications from past 24 hours
        from django.contrib.contenttypes.models import ContentType
        customer_type = ContentType.objects.get_for_model(pref.customer)

        notifications = Notification.objects.filter(
            recipient_type=customer_type,
            recipient_id=pref.customer.id,
            read=False,
            created_at__gte=yesterday
        ).select_related('repair', 'customer', 'template').order_by('-created_at')

        if notifications.exists():
            success = NotificationBatchService.send_daily_digest(
                user=pref.customer,
                notifications=list(notifications)
            )
            if success:
                digest_count += 1

    logger.info(
        f"Daily digest task completed: {digest_count} digests sent"
    )

    return {'digests_sent': digest_count}


@shared_task
def cleanup_old_delivery_logs():
    """
    Clean up old delivery logs to prevent database bloat.

    Runs weekly on Sunday at 2 AM (configured in celery.py beat_schedule).
    Deletes delivery logs older than 90 days.

    Keeps logs for:
    - Failed deliveries (for debugging)
    - Recent deliveries (< 90 days)

    This task is safe to run multiple times and is idempotent.
    """
    logger.info("Starting cleanup_old_delivery_logs task")

    # Delete logs older than 90 days
    cutoff_date = timezone.now() - timedelta(days=90)

    # Only delete successful deliveries (keep failures for analysis)
    deleted_count, _ = NotificationDeliveryLog.objects.filter(
        created_at__lt=cutoff_date,
        status='delivered'
    ).delete()

    logger.info(
        f"Cleanup task completed: {deleted_count} old delivery logs deleted"
    )

    return {'logs_deleted': deleted_count}


@shared_task
def send_scheduled_notifications():
    """
    Process notifications scheduled for future delivery.

    This task finds notifications with scheduled_for <= now and
    queues their delivery tasks.

    Can be run periodically (e.g., every 15 minutes) if scheduled
    notifications are needed.
    """
    logger.info("Starting send_scheduled_notifications task")

    now = timezone.now()
    scheduled_notifications = Notification.objects.filter(
        scheduled_for__isnull=False,
        scheduled_for__lte=now,
        email_sent=False,
        sms_sent=False
    )

    count = 0
    for notification in scheduled_notifications:
        try:
            # Get recipient and re-queue delivery
            recipient = notification.recipient

            if notification.template:
                rendered = notification.template.render(
                    notification.template_context
                )

                # Queue delivery using NotificationService
                from core.services.notification_service import NotificationService
                NotificationService._queue_delivery(
                    notification,
                    recipient,
                    rendered
                )

                count += 1
                logger.info(
                    f"Queued scheduled notification {notification.id}"
                )

        except Exception as e:
            logger.exception(
                f"Error processing scheduled notification {notification.id}: {e}"
            )

    logger.info(
        f"Scheduled notifications task completed: {count} notifications queued"
    )

    return {'notifications_queued': count}
