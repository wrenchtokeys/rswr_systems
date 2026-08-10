"""
Review request models — ReviewConfig (per-tenant) and ReviewRequest.

Part of the Review Request System (Phase 1).
See docs/proposals/review-request-system.md for full design.
"""
import uuid

from django.db import models
from common.models import TenantConfig


class ReviewConfig(TenantConfig):
    """Per-tenant configuration for automated review requests."""

    is_enabled = models.BooleanField(
        default=False,
        help_text="Enable automated review requests after completed repairs.",
    )
    google_review_url = models.URLField(
        blank=True,
        help_text="Direct Google review URL (e.g. from Google Business dashboard).",
    )
    send_to_fleet = models.BooleanField(
        default=False,
        help_text=(
            "Also send review requests to fleet accounts. Off by default — "
            "requests go only to individual (retail / walk-in) customers."
        ),
    )

    # Email customisation
    email_subject = models.CharField(
        max_length=200,
        default="How was your experience with {shop_name}?",
    )
    email_body_template = models.TextField(
        blank=True,
        help_text="Custom message body. Leave blank for default template.",
    )

    # SMS channel — when on, customers who agreed to texts (and have a
    # mobile number) get the review request as a text instead of an email.
    # Texts convert far better and also reach customers with no portal
    # account or email on file.
    sms_enabled = models.BooleanField(
        default=False,
        help_text="Send review requests by text when the customer has agreed to texts.",
    )

    # Throttling
    retail_cooldown_days = models.PositiveIntegerField(
        default=90,
        help_text="Min days between review requests for repeat retail customers.",
    )
    fleet_cooldown_days = models.PositiveIntegerField(
        default=180,
        help_text="Min days between review requests for fleet accounts.",
    )

    # Timing
    send_delay_hours = models.PositiveIntegerField(
        default=2,
        help_text="Hours after repair completion before sending review request.",
    )
    business_hours_start = models.PositiveIntegerField(
        default=9,
        help_text="Earliest hour (0-23) to send review requests.",
    )
    business_hours_end = models.PositiveIntegerField(
        default=19,
        help_text="Latest hour (0-23) to send review requests.",
    )

    class Meta(TenantConfig.Meta):
        verbose_name = "Review Configuration"

    def __str__(self):
        return f"ReviewConfig for {self.tenant}"


class ReviewRequest(models.Model):
    """Tracks an individual review request sent (or suppressed) for a repair."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('clicked', 'Clicked'),
        ('reviewed', 'Reviewed'),       # Black-box until Google API Phase 3
        ('skipped', 'Skipped'),
        ('suppressed', 'Suppressed'),
    ]

    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='review_requests',
    )
    customer = models.ForeignKey(
        'core.Customer', on_delete=models.CASCADE, related_name='review_requests',
    )
    customer_user = models.ForeignKey(
        'customer_portal.CustomerUser',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='review_requests',
    )
    repair = models.ForeignKey(
        'technician_portal.Repair',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='review_requests',
    )

    CHANNEL_CHOICES = [
        ('email', 'Email'),
        ('sms', 'Text message'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    skip_reason = models.CharField(max_length=100, blank=True)
    channel = models.CharField(
        max_length=8, choices=CHANNEL_CHOICES, default='email',
        help_text="How this request goes out (chosen at scheduling time).",
    )

    # Token for opt-out / click-tracking links (unguessable)
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    scheduled_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'customer', '-created_at']),
            models.Index(fields=['status', 'scheduled_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"ReviewRequest #{self.pk} ({self.status}) for {self.customer}"
