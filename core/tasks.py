"""
Notification delivery functions (synchronous).

Previously Celery tasks; now called directly (inline during request or
from management commands).  All email/SMS sending is synchronous and
wrapped in try/except so failures never crash the caller.
"""

import logging
from datetime import timedelta
from django.utils import timezone
from core.services.email_service import EmailService
from core.services.sms_service import SMSService
from core.models.notification import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog

logger = logging.getLogger(__name__)


def send_notification_email(
    notification_id: int,
    recipient_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    attempt_number: int = 1
) -> bool:
    """
    Send a notification email synchronously.

    Args:
        notification_id: ID of Notification object (None for digests)
        recipient_email: Recipient email address
        subject: Email subject line
        html_content: HTML email body
        text_content: Plain text email body
        attempt_number: Current delivery attempt (1-indexed)

    Returns:
        True if sent successfully, False otherwise
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
            logger.info(f"Email sent successfully (notification {notification_id})")
        else:
            logger.warning(f"Email send failed (notification {notification_id})")

        return success

    except Exception as e:
        logger.exception(f"Error in send_notification_email: {e}")
        return False


def send_notification_sms(
    notification_id: int,
    recipient_phone: str,
    message: str,
    attempt_number: int = 1
) -> bool:
    """
    Send a notification SMS synchronously.

    Args:
        notification_id: ID of Notification object
        recipient_phone: Recipient phone number (E.164 format)
        message: SMS message text (max 160 chars)
        attempt_number: Current delivery attempt (1-indexed)

    Returns:
        True if sent successfully, False otherwise
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
            logger.info(f"SMS sent successfully (notification {notification_id})")
        else:
            logger.warning(f"SMS send failed (notification {notification_id})")

        return success

    except Exception as e:
        logger.exception(f"Error in send_notification_sms: {e}")
        return False


def retry_failed_notifications() -> dict:
    """
    Retry failed email and SMS deliveries.

    Check for delivery logs with status='pending_retry' and
    next_retry_at <= now, then re-attempt delivery synchronously.

    Returns:
        dict with email_retries and sms_retries counts
    """
    logger.info("Starting retry_failed_notifications")

    email_retries = EmailService.get_pending_retries()
    email_count = 0
    for log in email_retries:
        if EmailService.retry_failed_delivery(log):
            email_count += 1

    sms_retries = SMSService.get_pending_retries()
    sms_count = 0
    for log in sms_retries:
        if SMSService.retry_failed_delivery(log):
            sms_count += 1

    logger.info(
        f"Retry completed: {email_count} emails, {sms_count} SMS retried"
    )
    return {'email_retries': email_count, 'sms_retries': sms_count}


def send_daily_digests() -> dict:
    """
    Send daily digest emails to users with unread notifications.

    Collects unread notifications from the past 24 hours and sends
    a summary email. Call from a cron management command daily at 9 AM.

    Returns:
        dict with digests_sent count
    """
    logger.info("Starting send_daily_digests")

    from core.models.notification_preferences import (
        TechnicianNotificationPreference,
        CustomerNotificationPreference
    )
    from core.services.notification_service import NotificationBatchService

    digest_count = 0
    yesterday = timezone.now() - timedelta(days=1)

    # Process technician digests
    tech_prefs = TechnicianNotificationPreference.objects.filter(
        receive_email_notifications=True
    ).select_related('technician', 'technician__user')

    for pref in tech_prefs:
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

    # Process customer digests
    customer_prefs = CustomerNotificationPreference.objects.filter(
        receive_email_notifications=True
    ).select_related('customer')

    for pref in customer_prefs:
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

    logger.info(f"Daily digest completed: {digest_count} digests sent")
    return {'digests_sent': digest_count}


def cleanup_old_delivery_logs() -> dict:
    """
    Clean up old delivery logs to prevent database bloat.

    Deletes successful delivery logs older than 90 days.
    Keeps failed logs for debugging.

    Returns:
        dict with logs_deleted count
    """
    logger.info("Starting cleanup_old_delivery_logs")

    cutoff_date = timezone.now() - timedelta(days=90)
    deleted_count, _ = NotificationDeliveryLog.objects.filter(
        created_at__lt=cutoff_date,
        status='delivered'
    ).delete()

    logger.info(f"Cleanup completed: {deleted_count} old delivery logs deleted")
    return {'logs_deleted': deleted_count}


def send_scheduled_notifications() -> dict:
    """
    Process notifications scheduled for future delivery.

    Finds notifications with scheduled_for <= now and delivers them.
    Call from a cron management command periodically (e.g. every 15 min).

    Returns:
        dict with notifications_queued count
    """
    logger.info("Starting send_scheduled_notifications")

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
            recipient = notification.recipient

            if notification.template:
                rendered = notification.template.render(notification.template_context)

                from core.services.notification_service import NotificationService
                NotificationService._queue_delivery(notification, recipient, rendered)
                count += 1
                logger.info(f"Queued scheduled notification {notification.id}")

        except Exception as e:
            logger.exception(f"Error processing scheduled notification {notification.id}: {e}")

    logger.info(f"Scheduled notifications completed: {count} notifications processed")
    return {'notifications_queued': count}
