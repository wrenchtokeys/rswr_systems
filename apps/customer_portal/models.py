import uuid
from django.db import models
from django.contrib.auth.models import User
from core.models import Customer
from apps.technician_portal.models import Repair, Replacement
import secrets
from datetime import timedelta
from django.utils import timezone

class CustomerUser(models.Model):
    """Links a Django User account to a Customer (company) for portal access."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    is_primary_contact = models.BooleanField(default=False)
    review_opt_out = models.BooleanField(
        default=False,
        help_text="If True, this user will never receive review request emails.",
    )

    class Meta:
        verbose_name = 'Customer User'
        verbose_name_plural = 'Customer Users'

    def __str__(self):
        return f"{self.user.username} - {self.customer.name}"


class CustomerPreference(models.Model):
    """Stores customer preferences for the portal display and notifications."""
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE)
    receive_email_notifications = models.BooleanField(default=True)
    receive_sms_notifications = models.BooleanField(default=False)
    default_view = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending Repairs'), ('completed', 'Completed Repairs')],
        default='pending'
    )

    class Meta:
        verbose_name = 'Customer Preference'
        verbose_name_plural = 'Customer Preferences'

    def __str__(self):
        return f"Preferences for {self.customer.name}"

class CustomerRepairPreference(models.Model):
    """Stores customer preferences for field repair approval workflow and invoicing"""

    APPROVAL_MODE_CHOICES = [
        ('AUTO_APPROVE', 'Auto-approve all field repairs'),
        ('REQUIRE_APPROVAL', 'Require approval for all field repairs'),
        ('UNIT_THRESHOLD', 'Auto-approve up to unit threshold per visit'),
    ]

    LOT_WALKING_FREQUENCY_CHOICES = [
        ('WEEKLY', 'Weekly'),
        ('BIWEEKLY', 'Bi-weekly (Every 2 weeks)'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly (Every 3 months)'),
    ]

    # Invoice preference choices
    INVOICE_PREFERENCE_CHOICES = [
        ('per_ticket', 'Invoice per repair (auto-generate when completed)'),
        ('batch', 'Batch invoicing (group repairs together)'),
        ('manual', 'Manual only (never auto-generate)'),
    ]

    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='repair_preferences')

    # Field repair approval workflow
    field_repair_approval_mode = models.CharField(
        max_length=20,
        choices=APPROVAL_MODE_CHOICES,
        default='REQUIRE_APPROVAL',
        help_text="How should field-discovered repairs be handled?"
    )

    # Threshold setting (only used when mode is UNIT_THRESHOLD)
    units_per_visit_threshold = models.IntegerField(
        default=5,
        blank=True,
        null=True,
        help_text="Max number of units technician can repair per visit without approval (only applies in Unit Threshold mode)"
    )

    # Lot walking service configuration
    lot_walking_enabled = models.BooleanField(
        default=False,
        help_text="Enable scheduled lot walking service for this customer"
    )

    lot_walking_frequency = models.CharField(
        max_length=20,
        choices=LOT_WALKING_FREQUENCY_CHOICES,
        default='WEEKLY',
        blank=True,
        null=True,
        help_text="How often should technicians walk your lot?"
    )

    lot_walking_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Preferred time for lot walking (e.g., 9:00 AM)"
    )

    lot_walking_days = models.JSONField(
        default=list,
        blank=True,
        help_text="Preferred days of week for lot walking (stored as list)"
    )

    # Invoice preferences
    invoice_preference = models.CharField(
        max_length=20,
        choices=INVOICE_PREFERENCE_CHOICES,
        default='batch',
        help_text="How should invoices be generated for this customer?"
    )
    billing_email = models.EmailField(
        null=True,
        blank=True,
        help_text="Email for invoices (uses customer email if blank)"
    )
    auto_email_invoices = models.BooleanField(
        default=False,
        help_text="Automatically email invoices when generated?"
    )
    include_photos_in_invoice = models.BooleanField(
        default=True,
        help_text="Include repair photos in invoice emails?"
    )

    # Payment terms override (uses shop default if blank)
    PAYMENT_TERMS_CHOICES = [
        ('', '(use shop default)'),
        ('COD', 'Cash on Delivery (COD)'),
        ('DUE_ON_RECEIPT', 'Due on Receipt'),
        ('NET15', 'Net 15'),
        ('NET30', 'Net 30'),
        ('NET45', 'Net 45'),
        ('NET60', 'Net 60'),
    ]
    payment_terms = models.CharField(
        max_length=20,
        choices=PAYMENT_TERMS_CHOICES,
        default='',
        blank=True,
        help_text="Payment terms for this customer (blank = use shop default)"
    )
    batch_invoice_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Day to run batch invoicing for this customer (1-28 for monthly). Blank = use shop default."
    )

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Customer Repair Preference'
        verbose_name_plural = 'Customer Repair Preferences'

    def __str__(self):
        return f"{self.customer.name} - {self.get_field_repair_approval_mode_display()}"

    def should_auto_approve(self, technician, visit_date=None):
        """
        Determine if a field repair should be auto-approved for this customer.

        Args:
            technician: The technician creating the repair
            visit_date: The date of the visit (defaults to today)

        Returns:
            bool: True if repair should be auto-approved, False if it needs customer approval
        """
        if self.field_repair_approval_mode == 'AUTO_APPROVE':
            return True
        elif self.field_repair_approval_mode == 'REQUIRE_APPROVAL':
            return False
        elif self.field_repair_approval_mode == 'UNIT_THRESHOLD':
            # Count how many units this tech has already repaired for this customer today
            from django.utils import timezone
            from django.db.models import Count

            if visit_date is None:
                visit_date = timezone.now().date()

            # Count unique units repaired by this tech for this customer on this visit date
            units_repaired_today = Repair.objects.filter(
                customer=self.customer,
                technician=technician,
                service_date__date=visit_date,
                queue_status__in=['APPROVED', 'IN_PROGRESS', 'COMPLETED']
            ).values('unit_number').distinct().count()

            # Auto-approve if under threshold
            return units_repaired_today < self.units_per_visit_threshold

        # Default to requiring approval
        return False

class RepairApproval(models.Model):
    """Tracks customer approvals for repairs"""
    repair = models.OneToOneField(Repair, on_delete=models.CASCADE)
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(CustomerUser, on_delete=models.SET_NULL, null=True, blank=True)
    approval_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        status = "Approved" if self.approved else "Pending"
        return f"{status} - {self.repair}"


class CustomerInvitation(models.Model):
    """
    Manages invitations for fleet managers to access the customer portal.
    Owner creates customer -> sends invite -> fleet manager accepts -> account created
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invitations')
    email = models.EmailField(help_text="Email address to send the invitation to")
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    is_primary_contact = models.BooleanField(default=False, help_text="Set this user as the primary contact for the customer")
    token = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    
    # Who created/accepted
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='customer_invites_sent')
    accepted_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='customer_invite_accepted')

    class Meta:
        verbose_name = 'Customer Invitation'
        verbose_name_plural = 'Customer Invitations'
        ordering = ['-created_at']

    def __str__(self):
        return f"Invite to {self.email} for {self.customer.name} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        """Check if invitation is still valid (pending and not expired)"""
        if self.status != 'pending':
            return False
        if timezone.now() > self.expires_at:
            self.status = 'expired'
            self.save(update_fields=['status'])
            return False
        return True

    def mark_accepted(self, user):
        """Mark invitation as accepted and link to user"""
        self.status = 'accepted'
        self.accepted_at = timezone.now()
        self.accepted_user = user
        self.save(update_fields=['status', 'accepted_at', 'accepted_user'])

class ApprovalToken(models.Model):
    """
    Single-use tokenized links for one-click repair approval/denial from emails.
    
    Tokens are UUID4 (unguessable), expire after 72 hours, and are marked
    as used after consumption. Each repair gets a pair (approve + deny).
    """
    ACTION_CHOICES = [
        ('approve', 'Approve'),
        ('deny', 'Deny'),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    repair = models.ForeignKey(Repair, on_delete=models.CASCADE, related_name='approval_tokens')
    customer_user = models.ForeignKey(CustomerUser, on_delete=models.CASCADE, related_name='approval_tokens')
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Approval Token'
        verbose_name_plural = 'Approval Tokens'

    def __str__(self):
        return f"{self.action} token for Repair #{self.repair_id} ({'used' if self.used_at else 'active'})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=72)
        super().save(*args, **kwargs)

    def is_valid(self):
        """Token is valid if not used and not expired."""
        return self.used_at is None and timezone.now() < self.expires_at

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])

    @classmethod
    def create_pair(cls, repair, customer_user):
        """
        Create both approve and deny tokens for a repair.
        Returns dict with token objects.
        """
        approve_token = cls.objects.create(
            repair=repair,
            customer_user=customer_user,
            action='approve',
        )
        deny_token = cls.objects.create(
            repair=repair,
            customer_user=customer_user,
            action='deny',
        )
        return {
            'approve_token': approve_token,
            'deny_token': deny_token,
        }
