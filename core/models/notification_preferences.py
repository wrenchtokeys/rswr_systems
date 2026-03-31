from django.db import models
from django.contrib.auth.models import User

from rs_systems.model_mixins import AutoUpdateTimestampMixin


class BaseNotificationPreference(AutoUpdateTimestampMixin, models.Model):
    """
    Abstract base class for notification preferences.

    Provides common fields for controlling notification delivery
    across different user types (technicians, customers, managers).
    """

    # Global preferences
    receive_email_notifications = models.BooleanField(
        default=True,
        help_text="Receive email notifications (MEDIUM/URGENT priority)"
    )
    receive_sms_notifications = models.BooleanField(
        default=False,  # Opt-in for SMS due to cost
        help_text="Receive SMS notifications (HIGH/URGENT priority)"
    )
    receive_in_app_notifications = models.BooleanField(
        default=True,
        help_text="Show in-app notifications (cannot disable URGENT)"
    )

    # Category-specific preferences (can disable non-critical categories)
    notify_repair_status = models.BooleanField(
        default=True,
        help_text="Notifications for repair status changes"
    )
    notify_assignments = models.BooleanField(
        default=True,
        help_text="Notifications for repair assignments/reassignments"
    )
    notify_approvals = models.BooleanField(
        default=True,
        help_text="Notifications for approvals/denials (URGENT - cannot fully disable)"
    )
    notify_rewards = models.BooleanField(
        default=True,
        help_text="Notifications for rewards and referrals"
    )
    notify_system = models.BooleanField(
        default=True,
        help_text="System notifications and announcements"
    )

    # Quiet hours (optional - don't send non-urgent notifications during these hours)
    quiet_hours_enabled = models.BooleanField(
        default=False,
        help_text="Enable quiet hours for non-urgent notifications"
    )
    quiet_hours_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Start of quiet hours (e.g., 22:00)"
    )
    quiet_hours_end = models.TimeField(
        null=True,
        blank=True,
        help_text="End of quiet hours (e.g., 08:00)"
    )

    # Contact verification
    email_verified = models.BooleanField(
        default=False,
        help_text="Whether email address has been verified"
    )
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When email was verified"
    )
    phone_verified = models.BooleanField(
        default=False,
        help_text="Whether phone number has been verified"
    )
    phone_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When phone was verified"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def can_send_email(self):
        """Check if email notifications are enabled and verified"""
        return self.receive_email_notifications and self.email_verified

    def can_send_sms(self):
        """Check if SMS notifications are enabled and verified"""
        return self.receive_sms_notifications and self.phone_verified

    def is_in_quiet_hours(self):
        """Check if current time is within quiet hours"""
        if not self.quiet_hours_enabled:
            return False

        from django.utils import timezone
        now = timezone.localtime().time()

        # Handle quiet hours that span midnight
        if self.quiet_hours_start < self.quiet_hours_end:
            return self.quiet_hours_start <= now <= self.quiet_hours_end
        else:
            return now >= self.quiet_hours_start or now <= self.quiet_hours_end


class TechnicianNotificationPreference(BaseNotificationPreference):
    """
    Notification preferences for technicians.

    Extends base preferences with technician-specific options.
    """
    technician = models.OneToOneField(
        'technician_portal.Technician',
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )

    # Technician-specific preferences
    notify_new_assignments = models.BooleanField(
        default=True,
        help_text="Get notified when assigned new repairs"
    )
    notify_reassignments = models.BooleanField(
        default=True,
        help_text="Get notified when repairs are reassigned away"
    )
    notify_customer_approvals = models.BooleanField(
        default=True,
        help_text="Get notified when customers approve/deny repairs"
    )
    notify_reward_redemptions = models.BooleanField(
        default=True,
        help_text="Get notified of reward redemptions to fulfill"
    )

    # Batch notification preferences
    digest_enabled = models.BooleanField(
        default=False,
        help_text="Receive daily digest instead of individual notifications"
    )
    digest_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Time to send daily digest (e.g., 09:00)"
    )

    class Meta:
        verbose_name = "Technician Notification Preference"
        verbose_name_plural = "Technician Notification Preferences"

    def __str__(self):
        return f"Preferences for {self.technician.user.get_full_name()}"


class CustomerNotificationPreference(BaseNotificationPreference):
    """
    Notification preferences for customers.

    Extends base preferences with customer-specific options.
    """
    customer = models.OneToOneField(
        'core.Customer',
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )

    # Customer-specific preferences
    notify_new_requests = models.BooleanField(
        default=True,
        help_text="Get notified when repair requests are submitted"
    )
    notify_pending_approvals = models.BooleanField(
        default=True,
        help_text="Get notified when repairs need approval"
    )
    notify_completions = models.BooleanField(
        default=True,
        help_text="Get notified when repairs are completed"
    )
    notify_in_progress = models.BooleanField(
        default=True,
        help_text="Get notified when repairs start"
    )

    # Batch notifications
    batch_pending_approvals = models.BooleanField(
        default=False,
        help_text="Receive one notification for all pending approvals (daily)"
    )

    class Meta:
        verbose_name = "Customer Notification Preference"
        verbose_name_plural = "Customer Notification Preferences"

    def __str__(self):
        return f"Preferences for {self.customer.name}"
