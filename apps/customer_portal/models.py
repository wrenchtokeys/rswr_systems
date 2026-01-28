from django.db import models
from django.contrib.auth.models import User
from core.models import Customer
from apps.technician_portal.models import Repair, Replacement

class CustomerUser(models.Model):
    """Links a Django User account to a Customer (company) for portal access."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    is_primary_contact = models.BooleanField(default=False)

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
                repair_date__date=visit_date,
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