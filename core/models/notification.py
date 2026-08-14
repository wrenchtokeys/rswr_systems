from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone


class Notification(models.Model):
    """
    Unified notification model supporting all recipient types.

    Uses Django's ContentType framework for polymorphic recipients:
    - Can link to User, CustomerUser, Technician, or any other model
    - Enables querying all notifications regardless of recipient type
    - Supports batch operations and consistent notification behavior
    """

    # Priority levels (determines delivery channels)
    PRIORITY_URGENT = 'URGENT'    # SMS + Email + In-app
    PRIORITY_HIGH = 'HIGH'        # SMS + In-app
    PRIORITY_MEDIUM = 'MEDIUM'    # Email + In-app
    PRIORITY_LOW = 'LOW'          # In-app only

    PRIORITY_CHOICES = [
        (PRIORITY_URGENT, 'Urgent - SMS + Email'),
        (PRIORITY_HIGH, 'High - SMS'),
        (PRIORITY_MEDIUM, 'Medium - Email'),
        (PRIORITY_LOW, 'Low - In-app only'),
    ]

    # Notification categories for filtering and preferences
    CATEGORY_REPAIR_STATUS = 'repair_status'
    CATEGORY_ASSIGNMENT = 'assignment'
    CATEGORY_APPROVAL = 'approval'
    CATEGORY_REWARD = 'reward'
    CATEGORY_SYSTEM = 'system'

    CATEGORY_CHOICES = [
        (CATEGORY_REPAIR_STATUS, 'Repair Status Change'),
        (CATEGORY_ASSIGNMENT, 'Assignment/Reassignment'),
        (CATEGORY_APPROVAL, 'Approval/Denial'),
        (CATEGORY_REWARD, 'Reward/Referral'),
        (CATEGORY_SYSTEM, 'System Notification'),
    ]

    # Polymorphic recipient (User, CustomerUser, Technician, etc.)
    recipient_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text="The type of recipient (User, CustomerUser, Technician)"
    )
    recipient_id = models.PositiveIntegerField(
        help_text="The ID of the recipient object"
    )
    recipient = GenericForeignKey('recipient_type', 'recipient_id')

    # Notification content
    title = models.CharField(
        max_length=200,
        help_text="Short notification title (shown in list views)"
    )
    message = models.TextField(
        help_text="Full notification message (supports markdown)"
    )
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        db_index=True,
        help_text="Category for filtering and preference management"
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        db_index=True,
        help_text="Priority level determines delivery channels"
    )

    # Delivery tracking
    read = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether recipient has marked as read"
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when notification was read"
    )
    email_sent = models.BooleanField(
        default=False,
        help_text="Whether email was successfully sent"
    )
    sms_sent = models.BooleanField(
        default=False,
        help_text="Whether SMS was successfully sent"
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional: schedule notification for future delivery"
    )

    # Related objects (optional links to repair, customer, etc.)
    repair = models.ForeignKey(
        'technician_portal.Repair',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_records',
        help_text="Link to related repair if applicable"
    )
    repair_batch_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Link to batch of repairs if applicable"
    )
    customer = models.ForeignKey(
        'core.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_records',
        help_text="Link to customer if applicable"
    )

    # Template support (for reusable notifications)
    template = models.ForeignKey(
        'NotificationTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional: template used to generate this notification"
    )
    template_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Context data used with template (stored for audit)"
    )

    # Action URL (optional deep link)
    action_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL to navigate to when notification clicked"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient_type', 'recipient_id', '-created_at']),
            models.Index(fields=['priority', 'created_at']),
            models.Index(fields=['category', 'read']),
            models.Index(fields=['repair_batch_id']),
        ]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"[{self.priority}] {self.title} → {self.recipient}"

    def mark_as_read(self):
        """Mark notification as read with timestamp"""
        if not self.read:
            self.read = True
            self.read_at = timezone.now()
            self.save(update_fields=['read', 'read_at'])

    def get_delivery_channels(self):
        """Return list of delivery channels based on priority.

        A template with channels_override set wins over the priority mapping —
        that's how repair_assigned (HIGH) sends email without changing what
        HIGH means for every other template.
        """
        if self.template_id and self.template.channels_override:
            channels = list(self.template.channels_override)
            if 'in_app' not in channels:
                channels.insert(0, 'in_app')
            return channels

        channels = ['in_app']  # Always include in-app

        if self.priority == self.PRIORITY_URGENT:
            channels.extend(['email', 'sms'])
        elif self.priority == self.PRIORITY_HIGH:
            channels.append('sms')
        elif self.priority == self.PRIORITY_MEDIUM:
            channels.append('email')

        return channels

    def should_send_email(self):
        """Check if this notification should be sent via email based on priority"""
        return 'email' in self.get_delivery_channels()

    def should_send_sms(self):
        """Check if this notification should be sent via SMS based on priority"""
        return 'sms' in self.get_delivery_channels()
