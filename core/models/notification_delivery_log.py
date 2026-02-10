from django.db import models
from django.utils import timezone


class NotificationDeliveryLog(models.Model):
    """
    Audit log for notification delivery attempts.

    Tracks every attempt to send notifications via email/SMS,
    including success/failure status, error messages, and retry attempts.
    Essential for debugging delivery issues and monitoring costs.
    """

    # Delivery channels
    CHANNEL_EMAIL = 'email'
    CHANNEL_SMS = 'sms'
    CHANNEL_IN_APP = 'in_app'

    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_SMS, 'SMS'),
        (CHANNEL_IN_APP, 'In-App'),
    ]

    # Delivery statuses
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_BOUNCED = 'bounced'
    STATUS_OPTED_OUT = 'opted_out'
    STATUS_SKIPPED = 'skipped'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent Successfully'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_BOUNCED, 'Bounced'),
        (STATUS_OPTED_OUT, 'User Opted Out'),
        (STATUS_SKIPPED, 'Skipped (preferences/quiet hours)'),
    ]

    # Related notification
    notification = models.ForeignKey(
        'Notification',
        on_delete=models.CASCADE,
        related_name='delivery_logs',
        null=True,
        blank=True
    )

    # Delivery details
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True
    )

    # Recipient contact info (snapshot at time of sending)
    recipient_email = models.EmailField(
        blank=True,
        help_text="Email address used for delivery"
    )
    recipient_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="Phone number used for delivery"
    )

    # Provider-specific details
    provider_name = models.CharField(
        max_length=50,
        blank=True,
        help_text="Service provider (AWS SES, AWS SNS, etc.)"
    )
    provider_message_id = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text="Provider's unique message ID for tracking"
    )
    provider_response = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full provider API response (for debugging)"
    )

    # Error tracking
    error_message = models.TextField(
        blank=True,
        help_text="Error message if delivery failed"
    )
    error_code = models.CharField(
        max_length=50,
        blank=True,
        help_text="Error code from provider"
    )

    # Retry tracking
    attempt_number = models.PositiveIntegerField(
        default=1,
        help_text="Delivery attempt number (1, 2, 3...)"
    )
    max_attempts = models.PositiveIntegerField(
        default=3,
        help_text="Maximum retry attempts"
    )
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled time for next retry attempt"
    )

    # Cost tracking (for SMS)
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Estimated cost in USD (primarily for SMS)"
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When notification was successfully sent"
    )
    failed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When delivery failed"
    )

    # Celery task tracking
    celery_task_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Celery task ID for async delivery tracking"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification', 'channel']),
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['provider_message_id']),
            models.Index(fields=['created_at', 'channel']),
        ]
        verbose_name = "Notification Delivery Log"
        verbose_name_plural = "Notification Delivery Logs"

    def __str__(self):
        return f"{self.channel} to {self.recipient_email or self.recipient_phone} - {self.status}"

    def mark_sent(self, provider_message_id=None, provider_response=None):
        """Mark delivery as successful"""
        self.status = self.STATUS_SENT
        self.sent_at = timezone.now()
        if provider_message_id:
            self.provider_message_id = provider_message_id
        if provider_response:
            self.provider_response = provider_response
        self.save(update_fields=['status', 'sent_at', 'provider_message_id', 'provider_response'])

    def mark_failed(self, error_message, error_code=None):
        """Mark delivery as failed and schedule retry if attempts remain"""
        self.status = self.STATUS_FAILED
        self.failed_at = timezone.now()
        self.error_message = error_message
        self.error_code = error_code or ''

        # Schedule retry with exponential backoff
        if self.attempt_number < self.max_attempts:
            from datetime import timedelta
            backoff_minutes = 5 * (2 ** (self.attempt_number - 1))  # 5, 10, 20 minutes
            self.next_retry_at = timezone.now() + timedelta(minutes=backoff_minutes)

        self.save(update_fields=['status', 'failed_at', 'error_message', 'error_code', 'next_retry_at'])

    def should_retry(self):
        """Check if this delivery should be retried"""
        return (
            self.status == self.STATUS_FAILED and
            self.attempt_number < self.max_attempts and
            self.next_retry_at and
            timezone.now() >= self.next_retry_at
        )
