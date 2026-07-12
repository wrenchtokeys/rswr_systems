"""
Notification Service for creating and managing notifications.

This service handles:
- Creating notifications with template rendering
- Checking user preferences and quiet hours
- Queuing email and SMS delivery tasks
- Batch notification operations
"""

import logging
from datetime import datetime, time
from typing import Optional, Dict, Any, List
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template
from django.utils import timezone
from core.models.notification import Notification
from core.models.notification_template import NotificationTemplate
from core.models.notification_preferences import (
    TechnicianNotificationPreference,
    CustomerNotificationPreference
)

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Main service for creating and delivering notifications.

    Usage:
        NotificationService.create_notification(
            recipient=technician,
            template_name='repair_approved',
            context={'repair': repair_obj},
            priority=Notification.PRIORITY_URGENT
        )
    """

    @staticmethod
    def create_notification(
        recipient: Any,
        template_name: str,
        context: Dict[str, Any],
        priority: Optional[str] = None,
        category: Optional[str] = None,
        repair=None,
        repair_batch_id=None,
        customer=None,
        action_url: str = '',
        scheduled_for: Optional[datetime] = None
    ) -> Optional[Notification]:
        """
        Create a notification and queue delivery tasks.

        Args:
            recipient: User, CustomerUser, or Technician object
            template_name: Name of NotificationTemplate to use
            context: Dictionary of variables for template rendering
            priority: Override template's default priority
            category: Override template's default category
            repair: Optional related Repair object
            repair_batch_id: Optional UUID for batch repairs
            customer: Optional related Customer object
            action_url: Optional URL override for notification action
            scheduled_for: Optional datetime to schedule delivery

        Returns:
            Created Notification object or None if delivery not allowed
        """
        try:
            # Get template
            template = NotificationTemplate.objects.filter(
                name=template_name,
                active=True
            ).first()

            if not template:
                logger.error(f"Template '{template_name}' not found or inactive")
                return None

            # Use template defaults if not provided
            if priority is None:
                priority = template.default_priority
            if category is None:
                category = template.category

            # Inject tenant-scoped email branding so templates extending
            # emails/base.html show the shop's identity, not the platform's.
            # Context is persisted on the Notification and re-rendered by the
            # email retry path, so this must happen before render.
            if 'branding' not in context:
                tenant = None
                if repair is not None and getattr(repair, 'tenant_id', None):
                    tenant = repair.tenant
                elif customer is not None and getattr(customer, 'tenant_id', None):
                    tenant = customer.tenant
                else:
                    tenant = getattr(recipient, 'tenant', None)
                from core.models.email_branding import EmailBrandingConfig
                context['branding'] = EmailBrandingConfig.get_tenant_context(tenant)

            # Render template content
            rendered = template.render(context)

            # Build action URL if not provided
            if not action_url and rendered.get('action_url'):
                action_url = rendered['action_url']

            # Get recipient content type
            recipient_type = ContentType.objects.get_for_model(recipient)

            # Create notification record
            notification = Notification.objects.create(
                recipient_type=recipient_type,
                recipient_id=recipient.id,
                title=rendered['title'],
                message=rendered['message'],
                category=category,
                priority=priority,
                repair=repair,
                repair_batch_id=repair_batch_id,
                customer=customer,
                template=template,
                template_context=context,
                action_url=action_url,
                scheduled_for=scheduled_for
            )

            logger.info(
                f"Created notification {notification.id}: "
                f"{template_name} for {recipient}"
            )

            # Queue delivery tasks if not scheduled for future
            if not scheduled_for or scheduled_for <= timezone.now():
                NotificationService._queue_delivery(notification, recipient, rendered)

            return notification

        except Exception as e:
            logger.exception(f"Error creating notification: {e}")
            # Re-raise in production for debugging (we'll catch in view)
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise  # Re-raise so we can see the actual error

    @staticmethod
    def _queue_delivery(
        notification: Notification,
        recipient: Any,
        rendered: Dict[str, str]
    ) -> None:
        """
        Queue email and SMS delivery tasks based on priority and preferences.

        Args:
            notification: Notification object to deliver
            recipient: Recipient user object
            rendered: Rendered template content dict
        """
        # Get user preferences
        preferences = NotificationService._get_preferences(recipient)

        if not preferences:
            logger.warning(f"No preferences found for {recipient}")
            return

        # Check if we should deliver based on preferences
        should_deliver = NotificationService._should_deliver(
            notification,
            preferences
        )

        if not should_deliver:
            logger.info(
                f"Notification {notification.id} blocked by user preferences"
            )
            return

        # Get delivery channels based on priority
        channels = notification.get_delivery_channels()

        # Send email if channel enabled
        if 'email' in channels and preferences.can_send_email():
            email = NotificationService._get_recipient_email(recipient)
            if email:
                from core.services.email_service import EmailService

                try:
                    success, delivery_log = EmailService.send_notification_email(
                        notification_id=notification.id,
                        recipient_email=email,
                        subject=rendered.get('email_subject', notification.title),
                        html_content=rendered.get('email_html', ''),
                        text_content=rendered.get('email_text', notification.message)
                    )
                    if success:
                        logger.info(f"Email sent for notification {notification.id}")
                    else:
                        logger.warning(f"Email failed for notification {notification.id}")
                except Exception as e:
                    logger.error(f"Email error for notification {notification.id}: {e}")

        # Send SMS synchronously if channel enabled
        if 'sms' in channels and preferences.receive_sms_notifications:
            phone = NotificationService._get_recipient_phone(recipient)
            if phone and preferences.phone_verified:
                from core.tasks import send_notification_sms

                sms_message = rendered.get('sms', notification.message[:160])
                try:
                    send_notification_sms(
                        notification_id=notification.id,
                        recipient_phone=phone,
                        message=sms_message
                    )
                    logger.info(f"SMS sent for notification {notification.id}")
                except Exception as e:
                    logger.error(f"SMS error for notification {notification.id}: {e}")

    @staticmethod
    def _get_preferences(recipient: Any):
        """
        Get notification preferences for recipient.

        Args:
            recipient: User, Customer, or Technician object

        Returns:
            NotificationPreference object or None
        """
        from apps.technician_portal.models import Technician
        from core.models import Customer

        # Try Technician preferences
        if isinstance(recipient, Technician):
            prefs, _ = TechnicianNotificationPreference.objects.get_or_create(
                technician=recipient
            )
            return prefs

        # Try Customer preferences
        if isinstance(recipient, Customer):
            prefs, _ = CustomerNotificationPreference.objects.get_or_create(
                customer=recipient
            )
            return prefs

        # For generic User, check if they have a linked Technician
        if hasattr(recipient, 'technician'):
            prefs, _ = TechnicianNotificationPreference.objects.get_or_create(
                technician=recipient.technician
            )
            return prefs

        logger.warning(f"Could not find preferences for {recipient}")
        return None

    @staticmethod
    def _should_deliver(
        notification: Notification,
        preferences
    ) -> bool:
        """
        Check if notification should be delivered based on preferences.

        Args:
            notification: Notification to check
            preferences: User's notification preferences

        Returns:
            True if should deliver, False otherwise
        """
        # Check category preferences
        category_map = {
            Notification.CATEGORY_REPAIR_STATUS: preferences.notify_repair_status,
            Notification.CATEGORY_ASSIGNMENT: preferences.notify_assignments,
            Notification.CATEGORY_APPROVAL: preferences.notify_approvals,
            Notification.CATEGORY_REWARD: preferences.notify_rewards,
            Notification.CATEGORY_SYSTEM: preferences.notify_system,
        }

        # URGENT approvals always go through
        if (notification.priority == Notification.PRIORITY_URGENT and
            notification.category == Notification.CATEGORY_APPROVAL):
            return True

        # Check if category is enabled
        if not category_map.get(notification.category, True):
            return False

        # Check quiet hours for non-urgent notifications.
        # NOTE (D3): quiet hours SUPPRESSES the email/SMS — nothing ever
        # re-sends it later. The in-app Notification record has already
        # been created, so the user still sees it in their feed; they
        # opted in to not being emailed/texted during these hours.
        # A true deferred-delivery queue (send after quiet hours end)
        # does not exist yet — if built, hook it here. Until then the log
        # must not claim a "delay" that never resolves.
        if notification.priority != Notification.PRIORITY_URGENT:
            if NotificationService._is_quiet_hours(preferences):
                logger.info(
                    f"Notification {notification.id}: email/SMS suppressed by "
                    f"quiet hours (in-app notification remains; no deferred "
                    f"re-send is scheduled)"
                )
                return False

        return True

    @staticmethod
    def _is_quiet_hours(preferences) -> bool:
        """
        Check if current time is within user's quiet hours.

        Args:
            preferences: User's notification preferences

        Returns:
            True if currently in quiet hours, False otherwise
        """
        if not preferences.quiet_hours_enabled:
            return False

        if not preferences.quiet_hours_start or not preferences.quiet_hours_end:
            return False

        now = timezone.localtime().time()
        start = preferences.quiet_hours_start
        end = preferences.quiet_hours_end

        # Handle overnight quiet hours (e.g., 22:00 to 08:00)
        if start > end:
            return now >= start or now < end
        else:
            return start <= now < end

    @staticmethod
    def _get_recipient_email(recipient: Any) -> Optional[str]:
        """
        Extract email address from recipient object.

        Args:
            recipient: User, CustomerUser, or Technician object

        Returns:
            Email address string or None
        """
        # Try direct email attribute
        if hasattr(recipient, 'email'):
            return recipient.email

        # Try linked user
        if hasattr(recipient, 'user') and hasattr(recipient.user, 'email'):
            return recipient.user.email

        return None

    @staticmethod
    def _get_recipient_phone(recipient: Any) -> Optional[str]:
        """
        Extract phone number from recipient object.

        Args:
            recipient: User, CustomerUser, or Technician object

        Returns:
            Phone number string or None
        """
        # Try direct phone attribute
        if hasattr(recipient, 'phone'):
            return recipient.phone

        # Try phone_number attribute (some models use this)
        if hasattr(recipient, 'phone_number'):
            return recipient.phone_number

        return None


class NotificationBatchService:
    """
    Service for batch notification operations.

    Used for:
    - Sending daily digests
    - Batch approval notifications
    - Mass notifications
    """

    @staticmethod
    def create_batch_notifications(
        recipients: List[Any],
        template_name: str,
        context_builder: callable,
        **kwargs
    ) -> List[Notification]:
        """
        Create notifications for multiple recipients.

        Args:
            recipients: List of recipient objects
            template_name: Template to use for all notifications
            context_builder: Function that takes recipient and returns context dict
            **kwargs: Additional arguments passed to create_notification

        Returns:
            List of created Notification objects
        """
        notifications = []

        for recipient in recipients:
            try:
                context = context_builder(recipient)
                notification = NotificationService.create_notification(
                    recipient=recipient,
                    template_name=template_name,
                    context=context,
                    **kwargs
                )
                if notification:
                    notifications.append(notification)
            except Exception as e:
                logger.exception(
                    f"Error creating notification for {recipient}: {e}"
                )

        logger.info(
            f"Created {len(notifications)} batch notifications "
            f"from {len(recipients)} recipients"
        )
        return notifications

    @staticmethod
    def send_daily_digest(user, notifications: List[Notification]) -> bool:
        """
        Send daily digest email with unread notifications.

        Args:
            user: Recipient user object
            notifications: List of unread notifications to include

        Returns:
            True if sent successfully, False otherwise
        """
        if not notifications:
            return False

        try:
            # Import here to avoid circular dependency
            from core.tasks import send_notification_email

            # Build digest email
            email = NotificationService._get_recipient_email(user)
            if not email:
                return False

            # Group notifications by category
            grouped = {}
            for notif in notifications:
                category = notif.get_category_display()
                if category not in grouped:
                    grouped[category] = []
                grouped[category].append(notif)

            # Render digest template
            context = {
                'user': user,
                'notifications': notifications,
                'grouped_notifications': grouped,
                'count': len(notifications)
            }

            # Use Django template rendering
            from django.template.loader import render_to_string

            html_content = render_to_string(
                'emails/notifications/daily_digest.html',
                context
            )
            text_content = render_to_string(
                'emails/notifications/daily_digest.txt',
                context
            )

            # Send digest synchronously
            send_notification_email(
                notification_id=None,  # No specific notification
                recipient_email=email,
                subject=f"Daily Digest - {len(notifications)} updates",
                html_content=html_content,
                text_content=text_content
            )

            logger.info(f"Sent daily digest to {user} with {len(notifications)} notifications")
            return True

        except Exception as e:
            logger.exception(f"Error sending daily digest: {e}")
            return False
