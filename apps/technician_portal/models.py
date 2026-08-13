from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.validators import FileExtensionValidator, RegexValidator
from decimal import Decimal
from core.models import Customer
from apps.tenants.managers import TenantManager
from rs_systems.model_mixins import AutoUpdateTimestampMixin
import logging

logger = logging.getLogger(__name__)

class Technician(models.Model):
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='technicians',
        null=True,  # Nullable during migration transition
        blank=True,
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="Phone number must be entered in format: '+999999999'. Up to 15 digits allowed."
            )
        ],
        help_text="Contact phone number in E.164 format (e.g., +12025551234)"
    )
    expertise = models.CharField(max_length=100, blank=True)

    # Contact verification fields (added for notification system)
    email_verified = models.BooleanField(
        default=False,
        help_text="Whether email address has been verified"
    )
    phone_verified = models.BooleanField(
        default=False,
        help_text="Whether phone number has been verified"
    )
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When email address was verified"
    )
    phone_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When phone number was verified"
    )

    # Technician Abilities
    can_repair = models.BooleanField(
        default=True,
        help_text="Can perform chip/crack repairs"
    )
    can_replace = models.BooleanField(
        default=False,
        help_text="Can perform glass replacements"
    )

    # Dual Role Support
    is_manager = models.BooleanField(
        default=False,
        help_text="Can this technician perform manager functions?"
    )
    approval_limit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum repair amount this manager can approve"
    )
    can_assign_work = models.BooleanField(
        default=False,
        help_text="Can assign repairs to other technicians"
    )
    can_override_pricing = models.BooleanField(
        default=False,
        help_text="Can override automatic pricing calculations"
    )
    managed_technicians = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        related_name='managers',
        help_text="Technicians managed by this manager (must be same tenant)"
    )

    # Performance Tracking
    repairs_completed = models.IntegerField(
        default=0,
        help_text="Total number of repairs completed"
    )
    average_repair_time = models.DurationField(
        null=True,
        blank=True,
        help_text="Average time to complete a repair"
    )
    customer_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average customer rating (1.00-5.00)"
    )

    # Availability
    is_active = models.BooleanField(
        default=True,
        help_text="Is this technician currently active/available?"
    )
    working_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text="Working hours schedule (JSON format)"
    )

    # Tenant-aware manager
    objects = TenantManager()

    class Meta:
        ordering = ['user__first_name', 'user__last_name']
        verbose_name = 'Technician'
        verbose_name_plural = 'Technicians'

    def __str__(self):
        role = " (Manager)" if self.is_manager else ""
        return f"{self.user.get_full_name()} - {self.expertise}{role}"

    def clean(self):
        """Validate technician data before saving."""
        from django.core.exceptions import ValidationError

        # If not a manager, clear manager-specific fields
        if not self.is_manager:
            self.approval_limit = None
            self.can_assign_work = False
            self.can_override_pricing = False

    def validate_managed_technicians(self):
        """
        Validate managed_technicians M2M after save.
        Call this after adding to managed_technicians to ensure
        all managed techs belong to the same tenant.
        
        M2M fields can't be validated in clean() (not yet saved),
        so this must be called explicitly.
        """
        from django.core.exceptions import ValidationError
        
        if not self.pk or not self.tenant:
            return
        
        cross_tenant = self.managed_technicians.exclude(tenant=self.tenant)
        if cross_tenant.exists():
            bad_techs = list(cross_tenant.values_list('user__email', flat=True))
            # Remove the cross-tenant techs
            self.managed_technicians.remove(*cross_tenant)
            raise ValidationError(
                f"Cannot manage technicians from a different shop. "
                f"Removed: {', '.join(bad_techs)}"
            )

    def get_managed_technicians_count(self):
        """Get the number of technicians this manager supervises"""
        return self.managed_technicians.count()

    def can_approve_amount(self, amount):
        """Check if this manager can override pricing up to a given amount.

        ``approval_limit=None`` means no cap (unlimited).  A truthy check would
        also block managers with approval_limit=0, but 0 is a valid "zero cap"
        value so we use an explicit ``is None`` test instead.  (CODE-114)
        """
        if not self.is_manager:
            return False
        if self.approval_limit is None:
            # No cap set — any amount is allowed.
            return True
        return amount <= self.approval_limit

    def manages_technician(self, technician):
        """Check if this manager manages a specific technician"""
        if not self.is_manager:
            return False
        return self.managed_technicians.filter(id=technician.id).exists()

    def get_team_repairs(self):
        """Get all repairs assigned to technicians this manager supervises.

        Always scoped to this manager's tenant — prevents cross-tenant data
        leakage even if a cross-tenant Technician somehow ended up in the
        managed_technicians M2M (e.g. via admin bypass or direct DB edit).
        (CODE-255)
        """
        if not self.is_manager:
            return Repair.objects.none()
        managed_tech_ids = self.managed_technicians.values_list('id', flat=True)
        qs = Repair.objects.filter(technician_id__in=managed_tech_ids)
        if self.tenant_id:
            qs = qs.filter(tenant_id=self.tenant_id)
        else:
            qs = qs.none()
        return qs

    def update_performance_stats(self):
        """Update performance statistics based on completed repairs.

        Scoped to this technician's tenant for defence-in-depth. (CODE-255)
        """
        from django.db.models import Avg
        completed_repairs = self.repair_set.filter(queue_status='COMPLETED')
        if self.tenant_id:
            completed_repairs = completed_repairs.filter(tenant_id=self.tenant_id)
        self.repairs_completed = completed_repairs.count()
        # Note: average_repair_time calculation would need repair start/end timestamps
        self.save()

    @receiver(post_save, sender=User)
    def save_technician(sender, instance, **kwargs):
        # Only save the technician if it exists
        if hasattr(instance, 'technician'):
            instance.technician.save()

class UnitRepairCount(models.Model):
    """Tracks the number of repairs per unit per customer for progressive pricing."""
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='unit_repair_counts',
        null=True,  # Nullable during migration transition
        blank=True,
    )
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    unit_number = models.CharField(max_length=50)
    repair_count = models.IntegerField(default=0)

    # Tenant-aware manager
    objects = TenantManager()

    class Meta:
        verbose_name = 'Unit Repair Count'
        verbose_name_plural = 'Unit Repair Counts'
        indexes = [
            models.Index(fields=['customer', 'unit_number']),
            models.Index(fields=['repair_count']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'customer', 'unit_number'],
                name='unique_unit_repair_count_per_tenant',
            ),
        ]

    def __str__(self):
        return f"{self.customer.name} - Unit #{self.unit_number} - Repairs: {self.repair_count}"


# =============================================================================
# ABSTRACT BASE CLASS: GlassService
# =============================================================================

class GlassService(models.Model):
    """
    Abstract base class for all glass service types (repairs and replacements).
    
    Contains shared fields: customer, technician, vehicle, dates, pricing,
    photos, notes, insurance, and status tracking.
    """
    
    STATUS_CHOICES = [
        ('REQUESTED', 'Customer Requested'),
        ('PENDING', 'Approval Pending'),
        ('APPROVED', 'Approved'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('DENIED', 'Denied by Customer'),
    ]
    
    # --- Multi-tenant support ---
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='%(class)ss',  # 'repairs' for Repair, 'replacements' for Replacement
        null=True,  # Nullable during migration transition
        blank=True,
    )
    
    # --- Core fields ---
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True)
    vehicle = models.ForeignKey(
        'core.Vehicle', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(class)ss',  # 'repairs' for Repair, 'replacements' for Replacement
        help_text="Link to vehicle record (optional — unit_number still works for fleets)"
    )
    unit_number = models.CharField(max_length=50, blank=True)  # For fleet customers
    
    # Vehicle info for retail/walk-in customers (alternative to unit_number)
    vehicle_year = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Vehicle year (e.g., 2019)"
    )
    vehicle_make = models.CharField(
        max_length=50, blank=True,
        help_text="Vehicle make (e.g., Ford, Toyota, Chevrolet)"
    )
    vehicle_model = models.CharField(
        max_length=50, blank=True,
        help_text="Vehicle model (e.g., F-150, Camry, Silverado)"
    )
    
    service_date = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True, null=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Manual price override (overrides automatic pricing)"
    )
    override_reason = models.TextField(
        blank=True,
        help_text="Reason for price override (required when using custom price)"
    )
    queue_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    
    # Photo documentation fields
    customer_submitted_photo = models.ImageField(
        upload_to='repair_photos/customer_submitted/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif'])],
        help_text="Photo uploaded by customer when submitting repair request (supports JPEG, PNG, WebP, HEIC)"
    )
    damage_photo_before = models.ImageField(
        upload_to='repair_photos/before/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif'])],
        help_text="Photo of damage before repair taken by technician (supports JPEG, PNG, WebP, HEIC)"
    )
    damage_photo_after = models.ImageField(
        upload_to='repair_photos/after/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif'])],
        help_text="Photo of repair after completion taken by technician (supports JPEG, PNG, WebP, HEIC)"
    )
    additional_photos = models.JSONField(
        default=list,
        blank=True,
        help_text="Additional photos related to the repair (stored as list of URLs)"
    )
    
    # Notes
    customer_notes = models.TextField(
        blank=True,
        help_text="Notes provided by the customer during repair request or approval process"
    )
    technician_notes = models.TextField(
        blank=True,
        help_text="Work notes added by technicians — included in the invoice line description the customer sees"
    )
    internal_notes = models.TextField(
        blank=True,
        help_text="Private shop notes — never shown to the customer (not on invoices, emails, or the customer portal)"
    )
    
    # Insurance fields
    insurance_claim = models.BooleanField(
        default=False,
        help_text="Is this an insurance claim?"
    )
    insurance_company = models.CharField(
        max_length=100, blank=True,
        help_text="Insurance company name"
    )
    claim_number = models.CharField(
        max_length=50, blank=True,
        help_text="Insurance claim number"
    )
    deductible = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Customer's deductible amount"
    )
    authorization_number = models.CharField(
        max_length=50, blank=True,
        help_text="Insurance authorization/approval number"
    )

    # --- Warranty tracking (shared by repairs and replacements) ---
    warranty_policy = models.ForeignKey(
        'WarrantyPolicy', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='%(class)ss',
        help_text="Warranty policy applied to this service on completion",
    )
    warranty_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Warranty expiration. Null with a policy = lifetime warranty.",
    )
    warranty_void = models.BooleanField(default=False)
    warranty_void_reason = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Reason warranty was voided (e.g. new impact damage)",
    )
    is_warranty_claim = models.BooleanField(
        default=False,
        help_text="This service is a warranty claim against an original service",
    )

    class Meta:
        abstract = True

    @property
    def has_warranty(self):
        """True if this service has an active, non-expired, non-voided warranty."""
        if not self.warranty_policy_id:
            return False
        if self.warranty_void:
            return False
        # Lifetime warranty: expires_at is None but policy exists
        if self.warranty_expires_at is None:
            return True
        return self.warranty_expires_at > timezone.now()

    @property
    def warranty_expiring_soon(self):
        """True if warranty expires within 30 days (for badge display)."""
        if not self.has_warranty:
            return False
        if self.warranty_expires_at is None:
            return False  # Lifetime — never expiring
        days_left = (self.warranty_expires_at - timezone.now()).days
        return 0 < days_left <= 30
    
    def has_photos(self):
        """Check if this service has any associated photos."""
        return bool(self.damage_photo_before or self.damage_photo_after)
    
    def get_photo_count(self):
        """Get the total number of photos associated with this service."""
        count = 0
        if self.customer_submitted_photo:
            count += 1
        if self.damage_photo_before:
            count += 1
        if self.damage_photo_after:
            count += 1
        if self.additional_photos:
            count += len(self.additional_photos)
        return count

    # ---- Vehicle identity -------------------------------------------------
    # A fleet is identified by unit number, an individual by their vehicle,
    # and the two are never interchangeable. The job form's one "Vehicle /
    # unit" box writes to unit_number for both, so an individual's invoice
    # used to read "Unit #Silver Camry" — the shop's own field note wearing a
    # fleet label. Everything customer-facing goes through these three.

    @property
    def is_for_individual(self):
        """True when this job belongs to a person rather than a fleet account."""
        return bool(self.customer and self.customer.is_individual)

    @property
    def vehicle_description(self):
        """'2019 Ford F-150' from the year/make/model fields, or ''."""
        parts = [self.vehicle_year, self.vehicle_make, self.vehicle_model]
        return ' '.join(str(p).strip() for p in parts if p).strip()

    def get_vehicle_identifier(self):
        """Bare identifier for a column whose header already says what it is.

        Fleet      -> '4521'
        Individual -> '2019 Ford F-150', falling back to whatever free text
                      the tech typed in the vehicle box ('Silver Camry').
        '' when there is nothing to show.
        """
        unit = (self.unit_number or '').strip()
        if self.is_for_individual:
            return self.vehicle_description or unit
        return unit

    def get_vehicle_label(self):
        """Self-describing identifier for inline prose (invoice descriptions).

        Fleet      -> 'Unit #4521'
        Individual -> '2019 Ford F-150' (no unit-number framing, ever)
        '' when there is nothing to show, so callers drop the whole segment
        rather than printing a bare 'Unit #'.
        """
        identifier = self.get_vehicle_identifier()
        if not identifier:
            return ''
        return identifier if self.is_for_individual else f"Unit #{identifier}"


# =============================================================================
# WARRANTY POLICY MODEL
# =============================================================================

class WarrantyPolicy(AutoUpdateTimestampMixin, models.Model):
    """
    Per-tenant warranty terms — one policy for repairs, one for replacements.

    A shop normally has exactly two tenant-wide policies (applies_to='repairs'
    and applies_to='replacements'). Per-customer overrides are supported via
    the customer FK but have no UI yet.
    """
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='warranty_policies',
    )

    APPLIES_TO_CHOICES = [
        ('repairs', 'Repairs'),
        ('replacements', 'Replacements'),
    ]
    applies_to = models.CharField(max_length=30, choices=APPLIES_TO_CHOICES, default='repairs')

    name = models.CharField(max_length=200, help_text="e.g. 'Standard Glass Warranty'")

    WARRANTY_DURATION_CHOICES = [
        ('lifetime', 'Lifetime'),
        ('custom_days', 'Custom (days)'),
        ('none', 'No Warranty'),
    ]
    duration_type = models.CharField(
        max_length=20, choices=WARRANTY_DURATION_CHOICES, default='custom_days',
    )
    duration_days = models.PositiveIntegerField(
        default=365,
        help_text="Days from completion. Ignored if duration_type is lifetime or none.",
    )

    coverage_description = models.TextField(
        blank=True,
        help_text="Customer-facing warranty terms shown on invoices/emails",
    )

    covers_labor = models.BooleanField(default=True)
    covers_materials = models.BooleanField(default=True)

    is_default = models.BooleanField(
        default=False,
        help_text="If True, this policy applies when no damage-type-specific policy exists.",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Per-customer override — if set, this policy applies only to that customer.
    # Null = tenant-wide policy (applies to all customers).
    customer = models.ForeignKey(
        'core.Customer', on_delete=models.CASCADE,
        null=True, blank=True, related_name='warranty_policies',
        help_text="If set, this policy applies only to this customer (fleet override).",
    )

    objects = TenantManager()

    class Meta:
        unique_together = ['tenant', 'name']
        ordering = ['applies_to']
        verbose_name_plural = 'warranty policies'

    def __str__(self):
        suffix = f" [{self.customer.name}]" if self.customer_id else ""
        return f"{self.name} ({self.tenant.name}){suffix}"

    def save(self, *args, **kwargs):
        # Enforce only one default per tenant
        if self.is_default:
            WarrantyPolicy.objects.filter(
                tenant=self.tenant, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def get_expiry_date(self, completion_date):
        """Calculate warranty expiration from repair completion date."""
        if self.duration_type == 'lifetime':
            return None  # Never expires
        if self.duration_type == 'none':
            return completion_date  # Already expired
        return completion_date + timedelta(days=self.duration_days)

    @property
    def terms_summary(self):
        """One-line summary of warranty terms for invoices."""
        if self.duration_type == 'lifetime':
            duration = "Lifetime"
        elif self.duration_type == 'none':
            return ""
        else:
            duration = f"{self.duration_days} days"
        parts = [f"{self.name}: {duration}"]
        coverage = []
        if self.covers_labor:
            coverage.append("labor")
        if self.covers_materials:
            coverage.append("materials")
        if coverage:
            parts.append(f"covers {' + '.join(coverage)}")
        return " — ".join(parts)


def resolve_initial_shop_status(service):
    """Decide the initial queue_status for shop-created work (entered PENDING).

    Shop-created repairs/replacements auto-approve — the shop is entering its
    own work, so there's nobody else to ask. The exception is a customer whose
    CustomerRepairPreference is explicitly set to REQUIRE_APPROVAL (or an
    over-threshold UNIT_THRESHOLD): their work stays PENDING for the
    Approve/Deny flow. That preference is the customer-portal "I want to
    approve work before it starts" control — today the shop approves on the
    customer's behalf; once customers are invited to the portal they approve
    there themselves. Customer-portal requests enter as REQUESTED and never
    pass through this gate.
    """
    import datetime as _dt
    from apps.customer_portal.models import CustomerRepairPreference

    visit_date = service.service_date
    if isinstance(visit_date, _dt.datetime):
        visit_date = visit_date.date()

    try:
        preferences = service.customer.repair_preferences
        if preferences.should_auto_approve(service.technician, visit_date):
            return 'APPROVED'
        return 'PENDING'
    except CustomerRepairPreference.DoesNotExist:
        # No preferences set — auto-approve by default
        return 'APPROVED'


# =============================================================================
# REPAIR MODEL
# =============================================================================

class RepairSoftDeleteManager(TenantManager):
    """
    Default manager for Repair — automatically excludes soft-deleted records.
    Use Repair.all_objects for unfiltered access (including deleted).
    """
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Repair(GlassService):
    """
    A windshield chip/crack repair job.
    
    Uses progressive pricing based on repair count per unit.
    Supports batch repairs (multiple breaks on same windshield).
    
    Works with ALL customer types:
    - Fleet: identified by unit_number
    - Retail: identified by vehicle (year/make/model)
    - Walk-in: minimal info
    """

    # Soft-delete manager (default — excludes deleted records)
    objects = RepairSoftDeleteManager()
    # Unfiltered manager — use when you need deleted records too
    all_objects = TenantManager()

    # Keep QUEUE_CHOICES as alias for backward compatibility
    QUEUE_CHOICES = GlassService.STATUS_CHOICES

    # D1: legal status transitions, enforced in save(). The load-bearing
    # rule is that COMPLETED is TERMINAL: completion increments the unit
    # repair counter, prices the repair, and awards loyalty points — a
    # COMPLETED -> APPROVED -> COMPLETED cycle re-fires all of those
    # (original_status refreshes on every save, defeating the hooks'
    # idempotency guards) and lets points/counters be inflated at will.
    # Forward jumps are deliberately permissive (a manager can accept a
    # REQUESTED repair straight to COMPLETED for on-the-spot field work);
    # DENIED can be re-opened but must pass through approval again.
    ALLOWED_STATUS_TRANSITIONS = {
        'REQUESTED': {'PENDING', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'DENIED'},
        'PENDING': {'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'DENIED'},
        'APPROVED': {'PENDING', 'IN_PROGRESS', 'COMPLETED', 'DENIED'},
        'IN_PROGRESS': {'APPROVED', 'COMPLETED'},
        'COMPLETED': set(),  # terminal — never leaves COMPLETED
        'DENIED': {'PENDING', 'APPROVED'},
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_status = self.queue_status
    
    DAMAGE_TYPE_CHOICES = [
        ('', 'Unknown / Not Sure'),
        ('Chip', 'Chip'),
        ('Crack', 'Crack'),
        ('Star Break', 'Star Break'),
        ('Bull\'s Eye', 'Bull\'s Eye'),
        ('Combination Break', 'Combination Break'),
        ('Half-Moon', 'Half-Moon'),
        ('Other', 'Other'),
    ]
    
    # Repair-specific fields
    damage_type = models.CharField(max_length=100, choices=DAMAGE_TYPE_CHOICES, default='')
    damage_location_x = models.FloatField(
        null=True, blank=True,
        help_text="X coordinate of damage on windshield (0-100%)"
    )
    damage_location_y = models.FloatField(
        null=True, blank=True,
        help_text="Y coordinate of damage on windshield (0-100%)"
    )
    drilled_before_repair = models.BooleanField(default=False)
    windshield_temperature = models.FloatField(null=True, blank=True)
    resin_viscosity = models.CharField(max_length=20, blank=True)

    # Batch repair tracking fields
    repair_batch_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="UUID linking repairs created together in one multi-break session"
    )
    break_number = models.PositiveIntegerField(
        default=1,
        null=True,
        blank=True,
        help_text="Break number within this batch (1, 2, 3, etc.)"
    )
    total_breaks_in_batch = models.PositiveIntegerField(
        default=1,
        null=True,
        blank=True,
        help_text="Total number of breaks in this repair batch"
    )
    is_multi_break_estimate = models.BooleanField(
        default=False,
        help_text="True if customer indicated multiple breaks exist but didn't specify exact count"
    )

    # Tax fields — calculated from BillingConfig rates when cost is set
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="Tax rate applied to this repair (percentage, e.g. 6.500 = 6.5%)"
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Tax amount in dollars"
    )
    no_tax = models.BooleanField(
        default=False,
        help_text="Don't charge sales tax on this job (e.g. cash deal, exempt sale)"
    )

    # Invoice skip flag — for legacy repairs that were paid outside the system
    skip_invoicing = models.BooleanField(
        default=False,
        help_text="Skip this repair when listing uninvoiced work (e.g., already paid outside system)"
    )

    # Soft-delete — set to a timestamp to mark as deleted (not visible in default queryset)
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When set, this repair is soft-deleted and excluded from normal querysets"
    )

    # =========================================================================
    # WARRANTY TRACKING FIELDS
    # (warranty_policy, warranty_expires_at, warranty_void, warranty_void_reason,
    #  is_warranty_claim live on GlassService — shared with Replacement)
    # =========================================================================
    warranty_original_repair = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='warranty_claims',
        help_text="Original repair this warranty claim is for",
    )

    # Goodwill repair — out-of-warranty courtesy repair (not a warranty claim)
    is_goodwill_repair = models.BooleanField(
        default=False,
        help_text="Courtesy repair outside warranty — excluded from loyalty points",
    )

    # =========================================================================
    # BACKWARD COMPATIBILITY: repair_date property
    # The field was renamed to service_date in the abstract base class.
    # This property ensures all existing code referencing repair_date still works.
    # =========================================================================
    
    @property
    def repair_date(self):
        """Backward-compatible alias for service_date."""
        return self.service_date
    
    @repair_date.setter
    def repair_date(self, value):
        """Backward-compatible alias for service_date."""
        self.service_date = value

    @property
    def total_with_tax(self):
        """Cost + tax amount."""
        cost = self.cost or Decimal('0.00')
        tax = self.tax_amount or Decimal('0.00')
        return cost + tax

    def save(self, *args, **kwargs):
        # D1: enforce the status state machine at the MODEL layer so the
        # admin, batch flows, and API paths can't bypass it (a view-only
        # check would). Applies only to real transitions on existing rows;
        # creation may start at any status (field repairs are created
        # directly as COMPLETED).
        if self.pk and self.original_status != self.queue_status:
            from django.core.exceptions import ValidationError
            allowed = self.ALLOWED_STATUS_TRANSITIONS.get(self.original_status, set())
            if self.queue_status not in allowed:
                raise ValidationError(
                    f"Illegal repair status transition "
                    f"{self.original_status} → {self.queue_status}. "
                    f"Completed repairs cannot change status."
                    if self.original_status == 'COMPLETED' else
                    f"Illegal repair status transition "
                    f"{self.original_status} → {self.queue_status}."
                )

        # BATCH INTEGRITY VALIDATION: Ensure batch data is consistent
        if self.repair_batch_id:
            # If part of a batch, break_number and total_breaks_in_batch must be set
            if not self.break_number or not self.total_breaks_in_batch:
                raise ValueError(
                    f"Batch repairs must have break_number and total_breaks_in_batch set. "
                    f"Got break_number={self.break_number}, total_breaks_in_batch={self.total_breaks_in_batch}"
                )

            # Validate break_number is within range
            if self.break_number < 1 or self.break_number > self.total_breaks_in_batch:
                raise ValueError(
                    f"Invalid break_number {self.break_number} for batch with {self.total_breaks_in_batch} breaks. "
                    f"break_number must be between 1 and {self.total_breaks_in_batch}."
                )

        # Ensure we have a customer before trying to access UnitRepairCount
        if self.customer:
            # Check if this is a new repair (not an update)
            is_new_repair = self.pk is None

            # Shop-created work auto-approves unless the customer explicitly
            # requires approval (see resolve_initial_shop_status)
            if is_new_repair and self.queue_status == 'PENDING':
                self.queue_status = resolve_initial_shop_status(self)

            # Get or create the unit repair count.
            # IMPORTANT: include tenant in the lookup so the created row is
            # tenant-scoped.  Omitting tenant caused new rows to be saved with
            # tenant=NULL (the field is nullable for migration compat), which
            # breaks TenantManager scoping and could produce duplicate NULL-tenant
            # rows on PostgreSQL (where NULL != NULL in unique constraints).
            unit_repair_count, created = UnitRepairCount.objects.get_or_create(
                tenant=self.tenant,
                customer=self.customer,
                unit_number=self.unit_number,
                defaults={'repair_count': 0}
            )

            # --- REPAIR PRICING (progressive logic) ---
            # Progressive pricing can be disabled at tenant level or per-customer
            # Retail/Walk-in customers don't get sequential discounts (always first repair price)
            # UNLESS it's a multi-break repair (same batch_id)
            is_retail = self.customer and self.customer.customer_type in ('RETAIL', 'WALK_IN')
            is_multi_break = self.repair_batch_id is not None
            # Check tenant-level setting first, then customer-level
            tenant_allows_progressive = getattr(self.tenant, 'use_progressive_pricing', True) if self.tenant else True
            customer_wants_progressive = getattr(self.customer, 'use_progressive_pricing', True)
            use_progressive = tenant_allows_progressive and customer_wants_progressive
            skip_progressive = is_retail or not use_progressive
            
            if self.queue_status == 'COMPLETED':
                # A repair is priced exactly once — on its first transition into
                # COMPLETED. Any later save (edit form attaching a photo, a
                # COMPLETED→COMPLETED status post, the Django admin) must not
                # re-price it: the UnitRepairCount has moved on since, so a
                # recalculation would silently reprice repair #1 at the tier of
                # repair #N, diverging from the invoice already sent. (A1)
                is_first_completion = not self.pk or self.original_status != 'COMPLETED'

                if is_first_completion and not skip_progressive:
                    # Atomic read-modify-write under a row lock. The plain
                    # `+= 1; save()` was a lost-update race: two technicians
                    # completing repairs on the same unit concurrently could
                    # both read count=2 and both write 3 — one increment lost,
                    # both repairs priced at the same tier, and every future
                    # repair on the unit overpriced by one tier. The lock also
                    # serializes the pricing read below, so each completion
                    # prices with its own unique post-increment value. (C5)
                    from django.db import transaction as db_transaction
                    with db_transaction.atomic():
                        locked_count = UnitRepairCount.objects.select_for_update().get(
                            pk=unit_repair_count.pk
                        )
                        locked_count.repair_count += 1
                        locked_count.save()
                    unit_repair_count.repair_count = locked_count.repair_count

                # Use override price if provided, otherwise use pricing service
                if self.cost_override is not None:
                    from .services.pricing_service import apply_account_discount
                    # A linked account's discount is automatic and total — it
                    # applies even to a manually entered price. Idempotent: cost
                    # is re-derived from cost_override on every save.
                    self.cost = apply_account_discount(self.cost_override, self.customer)
                elif not is_first_completion:
                    # Already priced when it first completed — never re-price.
                    pass
                elif self.pk and is_multi_break and self.cost:
                    # BATCH REPAIR FIX: Preserve batch pricing calculated at creation time.
                    # Batch pricing is set correctly by calculate_batch_pricing() when the
                    # batch is first created. Re-saving should not recalculate because the
                    # UnitRepairCount has already been incremented by all breaks in the batch,
                    # which would shift every break to the wrong pricing tier.
                    # (Largely redundant now that the not-first-completion guard above
                    # exists, but it still protects the pk-set completion path for
                    # batches whose cost was fixed at creation.)
                    pass
                else:
                    from .services.pricing_service import calculate_repair_cost
                    if skip_progressive and not is_multi_break:
                        # No progressive pricing - always first repair price
                        self.cost = calculate_repair_cost(self.customer, 1)
                    else:
                        # Progressive pricing enabled
                        self.cost = calculate_repair_cost(self.customer, unit_repair_count.repair_count)
            else:
                # For non-completed repairs, show expected cost for preview
                if self.cost_override is not None:
                    from .services.pricing_service import apply_account_discount
                    self.cost = apply_account_discount(self.cost_override, self.customer)
                # BATCH REPAIR FIX: Preserve pre-calculated batch pricing
                elif is_multi_break:
                    pass
                else:
                    from .services.pricing_service import calculate_repair_cost
                    if skip_progressive:
                        # No progressive pricing - always first repair price
                        self.cost = calculate_repair_cost(self.customer, 1)
                    else:
                        next_repair_count = unit_repair_count.repair_count + 1
                        self.cost = calculate_repair_cost(self.customer, next_repair_count)

            # Calculate tax from BillingConfig rates.
            # no_tax zeroes the fields unconditionally (outside the try) so a
            # job flipped to no_tax can never keep stale tax via the except.
            if self.no_tax:
                self.tax_rate = Decimal('0.000')
                self.tax_amount = Decimal('0.00')
            elif self.cost and self.cost > 0:
                try:
                    from apps.billing.services.tax_service import TaxService
                    tax_result = TaxService(tenant=self.tenant).calculate_tax(
                        subtotal=self.cost, customer=self.customer
                    )
                    self.tax_rate = tax_result['rate']
                    self.tax_amount = tax_result['amount']
                except Exception:
                    pass  # Keep $0 tax if billing app unavailable

            # Save after the cost calculation
            super().save(*args, **kwargs)

            # Apply rewards and run post-completion hooks AFTER save (requires
            # pk to access relationships).
            # IMPORTANT: update original_status AFTER calling apply_available_rewards()
            # and post_completion_hooks() so that hooks can distinguish a first-time
            # COMPLETED transition from a re-save of an already-COMPLETED repair.
            # Previously, original_status was updated BEFORE the calls, so the guard
            # inside loyalty_hook (`if original_status == 'COMPLETED': return`)
            # always fired on first completion — customers never earned points. (CODE-166)
            if self.queue_status == 'COMPLETED':
                # Check for available rewards to apply automatically.
                self.apply_available_rewards()

                # Run all post-completion hooks (loyalty, warranty, review
                # requests, etc.) via the orchestrator.  Each hook is isolated —
                # a failure in one does NOT block the others.
                # original_status is intentionally still set to the PRE-save
                # status here so hooks can detect a first-time COMPLETED
                # transition. It is updated below, after hooks complete.
                from apps.technician_portal.hooks import post_completion_hooks
                post_completion_hooks(self)

            # Update the original status AFTER rewards/points processing so that
            # any subsequent save() on the same in-memory instance (e.g. in tests)
            # correctly identifies it as already-COMPLETED and skips re-awarding.
            self.original_status = self.queue_status
        else:
            # Just save without updating repair counts
            super().save(*args, **kwargs)

        # Keep any live invoice line equal to this job's price (job→invoice
        # half of the price sync; the invoice→job half is the owner line-item
        # editor). Paid/cancelled invoices are financial history — untouched.
        try:
            from apps.billing.services.invoice_sync import sync_lines_for_service
            sync_lines_for_service(self)
        except Exception:
            pass  # never block a repair save on billing

    def apply_available_rewards(self):
        """
        Reward handling on completion.

        1. A redemption someone explicitly applied to this repair (job form,
           Apply Reward page) is finalized: marked FULFILLED so the ledger
           and history agree with the invoice discount.
        2. Auto-applying a waiting redemption the shop never chose is
           OPT-IN per shop (LoyaltyConfig.auto_apply_rewards, default off) —
           silently consuming a customer's saved "50% off" on a $30 chip
           repair surprised everyone. When off, the job form asks instead.

        Called during the repair save process when status changes to COMPLETED.
        """
        try:
            from apps.rewards_referrals.models import LoyaltyConfig, RewardRedemption
            from apps.rewards_referrals.services import RewardFulfillmentService

            # Finalize explicitly-applied redemptions — that decision was
            # already made deliberately.
            if self.applied_rewards.exists():
                if self.queue_status == 'COMPLETED':
                    for redemption in self.applied_rewards.filter(status='PENDING'):
                        RewardFulfillmentService.mark_as_fulfilled(
                            redemption,
                            self.technician,
                            "Fulfilled when repair was completed",
                        )
                return

            # Auto-apply is opt-in.
            if self.tenant is None:
                return
            config = LoyaltyConfig.get_for_tenant(self.tenant)
            if not (config.is_active and config.auto_apply_rewards):
                return

            # Check for pending reward redemptions that can be applied to repairs
            # Only include rewards that are repair-related (not merchandise like donuts/pizza)
            pending_redemptions = RewardRedemption.objects.filter(
                reward__customer=self.customer,
                status='PENDING',
                applied_to_repair__isnull=True,  # Not already applied to another repair
                reward_option__reward_type__category__in=[
                    'REPAIR_DISCOUNT',
                    'FREE_SERVICE'
                ]  # Only auto-apply repair-related rewards, NOT merchandise like donuts/pizza
            ).order_by('created_at')

            # Apply the oldest pending redemption to this repair
            if pending_redemptions.exists():
                redemption = pending_redemptions.first()
                redemption.applied_to_repair = self

                # If there's a technician on the repair, assign them
                if not redemption.assigned_technician and hasattr(self, 'technician'):
                    redemption.assigned_technician = self.technician

                redemption.save()

                # Automatically mark as fulfilled if completing the repair
                if self.queue_status == 'COMPLETED':
                    RewardFulfillmentService.mark_as_fulfilled(
                        redemption,
                        self.technician,
                        "Automatically applied when repair was completed"
                    )
        except Exception as e:
            # Log the error but don't fail the save
            logger.error(f"Error auto-applying rewards: {e}")
    

    def get_damage_location_label(self):
        """Return human-readable damage location from X/Y coordinates.
        
        The windshield diagram is 0-100% on both axes:
        - X: 0 = driver side, 100 = passenger side
        - Y: 0 = top (roof), 100 = bottom (hood)
        """
        if self.damage_location_x is None or self.damage_location_y is None:
            return ''
        
        x = self.damage_location_x
        y = self.damage_location_y
        
        # Horizontal position
        if x < 35:
            h_pos = 'driver side'
        elif x > 65:
            h_pos = 'passenger side'
        else:
            h_pos = 'center'
        
        # Vertical position
        if y < 35:
            v_pos = 'upper'
        elif y > 65:
            v_pos = 'lower'
        else:
            v_pos = ''
        
        if v_pos:
            return f"{v_pos} {h_pos}"
        return h_pos

    def get_invoice_description(self):
        """Generate a descriptive line item string for invoices.
        
        Includes break number (for batches) and damage location if available.
        The vehicle segment follows the customer type — fleets get a unit
        number, individuals get their vehicle — and is dropped entirely when
        there is nothing to name.
        Examples:
            'Windshield repair - Unit #100 - Chip'
            'Windshield repair - 2019 Ford F-150 - Chip'
            'Windshield repair - Unit #100 - Break 2 of 3 - Chip (passenger side)'
        """
        parts = ['Windshield repair']
        vehicle = self.get_vehicle_label()
        if vehicle:
            parts.append(vehicle)

        if self.is_part_of_batch and self.break_number:
            if self.total_breaks_in_batch:
                parts.append(f"Break {self.break_number} of {self.total_breaks_in_batch}")
            else:
                parts.append(f"Break {self.break_number}")
        
        damage = self.get_damage_type_display() or 'Repair'
        location = self.get_damage_location_label()
        if location:
            parts.append(f"{damage} ({location})")
        else:
            parts.append(damage)
        
        return ' - '.join(parts)

    def get_progressive_pricing_info(self):
        """Return progressive pricing context for this repair.
        
        Returns dict with base_rate, actual_cost, is_discounted, and explanation.
        Used to show customers why break 2 costs $40 instead of $50.
        """
        from decimal import Decimal
        
        if not self.is_part_of_batch or not self.break_number:
            return {
                'base_rate': self.cost,
                'actual_cost': self.cost,
                'is_discounted': False,
                'explanation': '',
            }
        
        # Get the first-break price for comparison
        tenant = self.tenant
        try:
            from apps.technician_portal.services.pricing_service import get_tenant_repair_price
            first_break_price = get_tenant_repair_price(tenant, 1)
        except Exception:
            first_break_price = Decimal('50.00')
        
        is_discounted = self.cost < first_break_price
        explanation = ''
        if is_discounted:
            savings = first_break_price - self.cost
            explanation = f"Multi-break discount (break {self.break_number}): -${savings}"
        
        return {
            'base_rate': first_break_price,
            'actual_cost': self.cost,
            'is_discounted': is_discounted,
            'explanation': explanation,
        }

    # Batch repair helper methods
    @property
    def is_part_of_batch(self):
        """Check if this repair is part of a multi-break batch or is a multi-break estimate."""
        return (self.repair_batch_id is not None and self.total_breaks_in_batch and self.total_breaks_in_batch > 1) or self.is_multi_break_estimate

    @classmethod
    def get_batch_repairs(cls, batch_id, tenant=None):
        """Get all repairs in a batch, ordered by break number.

        Args:
            batch_id: UUID of the batch.
            tenant: Tenant instance to scope the lookup. When provided, only repairs
                    belonging to that tenant are returned. Callers with a request
                    context SHOULD pass ``tenant`` to prevent cross-tenant batch
                    access (IDOR via batch UUID).
        """
        if not batch_id:
            return cls.objects.none()
        qs = cls.objects.filter(repair_batch_id=batch_id)
        if tenant is not None:
            qs = qs.filter(tenant=tenant)
        return qs.order_by('break_number')

    @classmethod
    def get_batch_summary(cls, batch_id, tenant=None):
        """
        Get summary information for a batch of repairs.
        Returns dict with: total_cost, break_count, unit_number, customer, statuses, all_repairs

        Args:
            batch_id: UUID of the batch.
            tenant: Tenant instance to scope the lookup. Pass this whenever a request
                    context is available so cross-tenant batch access is impossible.
        """
        if not batch_id:
            return None

        repairs = cls.get_batch_repairs(batch_id, tenant=tenant)
        if not repairs.exists():
            return None

        first_repair = repairs.first()

        # CRITICAL FIX: Explicitly check first_repair is not None
        if not first_repair:
            return None

        # CRITICAL FIX: Use Decimal('0') as start value to avoid int + Decimal TypeError
        # Previously: sum(repair.cost for repair in repairs) defaulted to int 0
        total_cost = sum((repair.cost for repair in repairs), Decimal('0'))
        # Use order_by() to clear the queryset ordering before calling .distinct() so
        # that PostgreSQL doesn't include break_number in the SELECT alongside
        # queue_status.  Without this, DISTINCT ON (queue_status, break_number) returns
        # one row per repair even when all have the same status — making all_same_status
        # always False for normal batches (pre-existing bug; also fixed in CODE-142).
        statuses = list(repairs.order_by().values_list('queue_status', flat=True).distinct())

        # Calculate progress
        repairs_list = list(repairs)
        completed_count = sum(1 for r in repairs_list if r.queue_status == 'COMPLETED')
        in_progress_count = sum(1 for r in repairs_list if r.queue_status == 'IN_PROGRESS')
        approved_count = sum(1 for r in repairs_list if r.queue_status == 'APPROVED')
        total_repairs = len(repairs_list)
        progress_percentage = int((completed_count / total_repairs * 100)) if total_repairs > 0 else 0

        # Use the MAX break_number as the definitive break count (handles data inconsistencies)
        # Fall back to total_breaks_in_batch if break_number is not set
        max_break_number = max((r.break_number for r in repairs_list if r.break_number), default=None)
        if max_break_number:
            break_count = max_break_number
        else:
            # Fallback: use total_breaks_in_batch from first repair or count
            break_count = first_repair.total_breaks_in_batch if first_repair.total_breaks_in_batch else repairs.count()

        return {
            'batch_id': batch_id,
            'customer': first_repair.customer,
            'unit_number': first_repair.unit_number,
            'service_date': first_repair.service_date,
            'break_count': break_count,
            'total_cost': total_cost,
            'statuses': statuses,
            'all_same_status': len(statuses) == 1,
            'current_status': statuses[0] if len(statuses) == 1 else 'MIXED',
            'all_repairs': list(repairs),
            'repairs': repairs_list,  # Add this for template access
            'completed_count': completed_count,
            'in_progress_count': in_progress_count,
            'approved_count': approved_count,
            'progress_percentage': progress_percentage,
        }

    @classmethod
    def build_batch_summary_from_repairs(cls, batch_id, repairs_list):
        """
        Build the same summary dict as ``get_batch_summary()`` from a pre-fetched list
        of repairs (already loaded from the DB).  Avoids any additional DB queries.

        Used by the technician dashboard to bulk-fetch all batch repairs in a single
        query and then compute summaries in Python — eliminating the N+1 that occurred
        when ``get_batch_summary()`` was called once per batch inside a loop (CODE-142).

        Args:
            batch_id: UUID of the batch (used as the 'batch_id' key in the result).
            repairs_list: Iterable of Repair instances belonging to this batch.
                          Must be non-empty. Caller is responsible for pre-loading
                          'customer' via select_related if the customer attribute is used.

        Returns:
            dict matching the shape returned by ``get_batch_summary()``, or None if
            ``repairs_list`` is empty.
        """
        if not repairs_list:
            return None

        first_repair = repairs_list[0]

        total_cost = sum((r.cost for r in repairs_list), Decimal('0'))

        # Collect distinct statuses preserving insertion order (dict trick keeps order in Python 3.7+).
        # Using a set would work for the count but loses the deterministic first-element needed
        # for current_status when all_same_status is True.
        statuses_set = list(dict.fromkeys(r.queue_status for r in repairs_list))
        completed_count = sum(1 for r in repairs_list if r.queue_status == 'COMPLETED')
        in_progress_count = sum(1 for r in repairs_list if r.queue_status == 'IN_PROGRESS')
        approved_count = sum(1 for r in repairs_list if r.queue_status == 'APPROVED')
        total_count = len(repairs_list)
        progress_percentage = int((completed_count / total_count * 100)) if total_count > 0 else 0

        max_break_number = max((r.break_number for r in repairs_list if r.break_number), default=None)
        if max_break_number:
            break_count = max_break_number
        else:
            break_count = first_repair.total_breaks_in_batch if first_repair.total_breaks_in_batch else total_count

        return {
            'batch_id': batch_id,
            'customer': first_repair.customer,
            'unit_number': first_repair.unit_number,
            'service_date': first_repair.service_date,
            'break_count': break_count,
            'total_cost': total_cost,
            'statuses': statuses_set,
            'all_same_status': len(statuses_set) == 1,
            'current_status': statuses_set[0] if len(statuses_set) == 1 else 'MIXED',
            'all_repairs': repairs_list,
            'repairs': repairs_list,
            'completed_count': completed_count,
            'in_progress_count': in_progress_count,
            'approved_count': approved_count,
            'progress_percentage': progress_percentage,
        }

    def get_discounted_cost(self):
        """Calculate the final cost with any applied rewards/discounts"""
        from decimal import Decimal
        
        # Start with the base cost
        base_cost = self.cost
        final_cost = base_cost
        discount_applied = False
        discount_description = ""
        
        # Check for any applied rewards - include both FULFILLED and PENDING rewards
        applied_rewards = self.applied_rewards.filter(status__in=['FULFILLED', 'PENDING'])
        
        for redemption in applied_rewards:
            if redemption.reward_option.reward_type:
                reward_type = redemption.reward_option.reward_type

                # Only apply discounts for repair-related rewards
                # Skip MERCHANDISE (donuts/pizza), GIFT_CARD, and OTHER categories
                if reward_type.category not in ['REPAIR_DISCOUNT', 'FREE_SERVICE']:
                    continue

                # Apply discount based on the reward type
                if reward_type.discount_type == 'PERCENTAGE':
                    # Percentage discount
                    discount_amount = (base_cost * Decimal(reward_type.discount_value)) / Decimal(100)
                    final_cost = base_cost - discount_amount
                    discount_description = f"{int(reward_type.discount_value)}% off"
                    discount_applied = True

                elif reward_type.discount_type == 'FIXED_AMOUNT':
                    # Fixed amount discount
                    discount_amount = Decimal(reward_type.discount_value)
                    final_cost = max(base_cost - discount_amount, Decimal(0))
                    discount_description = f"${reward_type.discount_value} off"
                    discount_applied = True

                elif reward_type.discount_type == 'FREE':
                    # Free (100% off)
                    final_cost = Decimal(0)
                    discount_description = "Free repair"
                    discount_applied = True

                # Only apply one discount (the first one found)
                break
        
        return {
            'original_cost': base_cost,
            'final_cost': final_cost,
            'discount_applied': discount_applied,
            'discount_description': discount_description,
            'savings': base_cost - final_cost
        }

    def get_expected_price(self):
        """Get the expected price before completion (for preview purposes)"""
        # If override is set, return that
        if self.cost_override is not None:
            return self.cost_override

        # Otherwise calculate based on customer type and repair count
        if self.customer:
            from .services.pricing_service import get_expected_repair_cost, get_retail_repair_price
            
            # Retail/Walk-in: always first repair price (no sequential discounts)
            if self.customer.customer_type in ('RETAIL', 'WALK_IN'):
                return get_retail_repair_price(self.customer)
            
            # Fleet: progressive pricing based on unit repair count
            expected_cost, _ = get_expected_repair_cost(self.customer, self.unit_number)
            return expected_cost
        return 0

    def has_price_override(self):
        """Check if this repair has a manual price override"""
        return self.cost_override is not None

    @property
    def extra_charges_total(self):
        """Sum of one-off extra charges (trip fees etc.) on this job."""
        from django.db.models import Sum
        from decimal import Decimal
        return self.extra_charges.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def total_with_charges(self):
        """Job price plus extra charges — what the ticket actually costs."""
        from decimal import Decimal
        return (self.cost or Decimal('0.00')) + self.extra_charges_total

    class Meta:
        ordering = ['-service_date']
        verbose_name = 'Repair'
        verbose_name_plural = 'Repairs'
        indexes = [
            models.Index(fields=['queue_status']),
            models.Index(fields=['customer', 'unit_number']),
            models.Index(fields=['technician']),
            models.Index(fields=['service_date']),
            # Partial index for soft-delete filter: RepairSoftDeleteManager always
            # appends deleted_at__isnull=True.  Without an index every query
            # does a post-filter pass on an unindexed column.  The partial index
            # covers only live (non-deleted) repairs — which is 99%+ of queries.
            # The composite (tenant_id, queue_status) covers the most common
            # portal filter pattern: tenant + status.  (CODE-109)
            models.Index(
                fields=['tenant', 'queue_status'],
                condition=models.Q(deleted_at__isnull=True),
                name='repair_live_tenant_status_idx',
            ),
        ]

    def __str__(self):
        return f"Repair {self.id} - {self.customer.name} - Unit #{self.unit_number} - {self.service_date.strftime('%Y-%m-%d')} - {self.queue_status}"

    def apply_reward(self, redemption, technician=None, auto_fulfill=False):
        """Manually apply a reward to this repair"""
        if redemption.applied_to_repair:
            # This reward is already applied to a repair
            return False, "This reward is already applied to another repair"
        
        # Check if this is a merchandise reward that should not be applied to repairs
        if redemption.reward_option.reward_type and redemption.reward_option.reward_type.category == 'MERCHANDISE':
            return False, "Merchandise rewards (like donuts and pizza) cannot be applied to repair costs. These are fulfilled separately by technicians."
        
        # Apply the reward to this repair
        redemption.applied_to_repair = self
        
        # Update technician if provided
        if technician and not redemption.assigned_technician:
            redemption.assigned_technician = technician
            
        redemption.save()
        
        # Auto-fulfill if requested and repair is completed
        if auto_fulfill and self.queue_status == 'COMPLETED':
            from apps.rewards_referrals.services import RewardFulfillmentService
            RewardFulfillmentService.mark_as_fulfilled(
                redemption, 
                technician or self.technician, 
                "Applied and fulfilled by technician"
            )
            
        return True, "Reward successfully applied to repair"


# =============================================================================
# REPLACEMENT MODEL
# =============================================================================

class ReplacementSoftDeleteManager(TenantManager):
    """
    Default manager for Replacement — automatically excludes soft-deleted
    records. Use Replacement.all_objects for unfiltered access.
    """
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Replacement(GlassService):
    """
    A glass replacement job — full glass swap.

    Pricing is based on parts + labor + optional ADAS calibration.
    Insurance fields from GlassService are commonly used here.

    Works with ALL customer types:
    - Fleet: identified by unit_number
    - Retail: identified by vehicle (year/make/model)
    - Walk-in: minimal info
    """

    # Soft-delete manager (default — excludes deleted records)
    objects = ReplacementSoftDeleteManager()
    # Unfiltered manager — use when you need deleted records too
    all_objects = TenantManager()
    
    # Keep QUEUE_CHOICES as alias for consistency with Repair
    QUEUE_CHOICES = GlassService.STATUS_CHOICES
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_status = self.queue_status
    
    # Glass position choices
    GLASS_POSITION_CHOICES = [
        ('WINDSHIELD', 'Windshield'),
        ('FRONT_LEFT', 'Front Left Window'),
        ('FRONT_RIGHT', 'Front Right Window'),
        ('REAR_LEFT', 'Rear Left Window'),
        ('REAR_RIGHT', 'Rear Right Window'),
        ('REAR', 'Rear Window'),
        ('QUARTER_LEFT', 'Left Quarter Glass'),
        ('QUARTER_RIGHT', 'Right Quarter Glass'),
        ('SUNROOF', 'Sunroof / Moonroof'),
        ('OTHER', 'Other'),
    ]
    
    GLASS_TYPE_CHOICES = [
        ('OEM', 'OEM'),
        ('AFTERMARKET', 'Aftermarket'),
        ('', 'Not specified'),
    ]
    
    # Replacement-specific fields
    glass_position = models.CharField(
        max_length=20,
        choices=GLASS_POSITION_CHOICES,
        blank=True,
        help_text="Which glass is being replaced (windshield, side, rear, etc.)"
    )
    glass_type = models.CharField(
        max_length=15,
        choices=GLASS_TYPE_CHOICES,
        blank=True,
        help_text="OEM = original manufacturer glass. Aftermarket = third-party."
    )
    nags_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="NAGS part number for the glass (industry standard identifier)"
    )
    parts_cost = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Cost of replacement glass and materials"
    )
    labor_cost = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Labor cost for replacement"
    )
    requires_adas_calibration = models.BooleanField(
        default=False,
        help_text="Does this replacement require ADAS sensor recalibration?"
    )
    adas_calibration_cost = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Cost for ADAS recalibration if required"
    )

    # Tax fields — calculated from BillingConfig rates when cost is set
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="Tax rate applied to this replacement (percentage, e.g. 6.500 = 6.5%)"
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Tax amount in dollars"
    )
    no_tax = models.BooleanField(
        default=False,
        help_text="Don't charge sales tax on this job (e.g. cash deal, exempt sale)"
    )

    # Invoice skip flag — for replacements that were paid outside the system
    skip_invoicing = models.BooleanField(
        default=False,
        help_text="Skip this replacement when listing uninvoiced work (e.g., already paid outside system)"
    )

    # Soft-delete — set to a timestamp to mark as deleted (not visible in default queryset)
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When set, this replacement is soft-deleted and excluded from normal querysets"
    )

    # =========================================================================
    # BACKWARD COMPATIBILITY: repair_date property
    # =========================================================================
    
    @property
    def repair_date(self):
        """Backward-compatible alias for service_date."""
        return self.service_date
    
    @repair_date.setter
    def repair_date(self, value):
        """Backward-compatible alias for service_date."""
        self.service_date = value

    @property
    def total_with_tax(self):
        """Cost + tax amount."""
        cost = self.cost or Decimal('0.00')
        tax = self.tax_amount or Decimal('0.00')
        return cost + tax

    def save(self, *args, **kwargs):
        # Ensure we have a customer
        if self.customer:
            is_new = self.pk is None
            
            # Shop-created work auto-approves unless the customer explicitly
            # requires approval (see resolve_initial_shop_status)
            if is_new and self.queue_status == 'PENDING':
                self.queue_status = resolve_initial_shop_status(self)
            
            # --- REPLACEMENT PRICING ---
            # Replacements use parts + labor + ADAS, not progressive repair pricing.
            # A linked account's flat discount (0% default = no-op) is applied to
            # the freshly resolved cost — but NOT to the "keep existing cost"
            # branch, so a re-save never discounts twice.
            from .services.pricing_service import apply_account_discount
            if self.cost_override is not None:
                self.cost = apply_account_discount(self.cost_override, self.customer)
            else:
                total = Decimal('0.00')
                if self.parts_cost:
                    total += self.parts_cost
                if self.labor_cost:
                    total += self.labor_cost
                if self.requires_adas_calibration and self.adas_calibration_cost:
                    total += self.adas_calibration_cost
                if total > 0:
                    self.cost = apply_account_discount(total, self.customer)
                # else: keep existing cost (may have been set manually)

            # Calculate tax from BillingConfig rates.
            # no_tax zeroes the fields unconditionally (outside the try) so a
            # job flipped to no_tax can never keep stale tax via the except.
            if self.no_tax:
                self.tax_rate = Decimal('0.000')
                self.tax_amount = Decimal('0.00')
            elif self.cost and self.cost > 0:
                try:
                    from apps.billing.services.tax_service import TaxService
                    tax_result = TaxService(tenant=self.tenant).calculate_tax(
                        subtotal=self.cost, customer=self.customer
                    )
                    self.tax_rate = tax_result['rate']
                    self.tax_amount = tax_result['amount']
                except Exception:
                    pass  # Keep $0 tax if billing app unavailable

            # Reset repair count when replacement is completed
            # A new windshield means fresh repair pricing for that unit
            if self.queue_status == 'COMPLETED' and self.original_status != 'COMPLETED':
                try:
                    # Include tenant in the filter to respect tenant isolation.
                    # Without this, completing a replacement for Tenant A could
                    # reset Tenant B's repair count if both share a customer
                    # with the same unit_number.  The Repair model's save()
                    # already includes tenant= in its UnitRepairCount lookup
                    # (see line ~756) — this brings Replacement into parity.
                    # (CODE-230)
                    unit_repair_count = UnitRepairCount.objects.filter(
                        tenant=self.tenant,
                        customer=self.customer,
                        unit_number=self.unit_number
                    ).first()
                    if unit_repair_count:
                        unit_repair_count.repair_count = 0
                        unit_repair_count.save()
                except Exception:
                    pass  # Don't fail replacement save if reset fails

        super().save(*args, **kwargs)

        # Keep any live invoice line equal to this job's price (job→invoice
        # half of the price sync — see Repair.save for the same hook).
        try:
            from apps.billing.services.invoice_sync import sync_lines_for_service
            sync_lines_for_service(self)
        except Exception:
            pass  # never block a replacement save on billing

        # Auto-assign warranty on first-time COMPLETED transition (mirrors the
        # Repair post-completion warranty_hook). Silent no-op if the shop has
        # no active replacement warranty policy.
        if (
            self.queue_status == 'COMPLETED'
            and self.original_status != 'COMPLETED'
            and not self.warranty_policy_id
        ):
            try:
                from apps.technician_portal.warranty_service import WarrantyService
                WarrantyService.assign_warranty(self)
            except ValueError:
                pass  # No policy configured — warranty is optional
            except Exception:
                logger.error(
                    "Warranty assignment failed for replacement pk=%s",
                    self.pk, exc_info=True,
                )

        # Loyalty points on first-time COMPLETED (mirrors the Repair
        # loyalty_hook; the hook's own guard reads original_status, so this
        # must run BEFORE original_status is refreshed below). We deliberately
        # do not run the full post_completion_hooks orchestrator: warranty is
        # handled inline above and review requests stay repair-only for now.
        if self.queue_status == 'COMPLETED' and self.original_status != 'COMPLETED':
            from apps.technician_portal.hooks import loyalty_hook
            loyalty_hook(self)

        self.original_status = self.queue_status

    def has_price_override(self):
        """Check if this replacement has a manual price override"""
        return self.cost_override is not None

    @property
    def extra_charges_total(self):
        """Sum of one-off extra charges (trip fees etc.) on this job."""
        from django.db.models import Sum
        return self.extra_charges.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def total_with_charges(self):
        """Job price plus extra charges — what the ticket actually costs."""
        return (self.cost or Decimal('0.00')) + self.extra_charges_total

    def get_discounted_cost(self):
        """Final cost with any applied reward redemption (mirrors Repair's)."""
        base_cost = self.cost or Decimal('0.00')
        final_cost = base_cost
        discount_applied = False
        discount_description = ""

        applied_rewards = self.applied_rewards.filter(status__in=['FULFILLED', 'PENDING'])
        for redemption in applied_rewards:
            reward_type = redemption.reward_option.reward_type
            if not reward_type:
                continue
            if reward_type.category not in ['REPLACEMENT_DISCOUNT', 'FREE_SERVICE']:
                continue

            if reward_type.discount_type == 'PERCENTAGE':
                discount_amount = (base_cost * Decimal(reward_type.discount_value)) / Decimal(100)
                final_cost = base_cost - discount_amount
                discount_description = f"{int(reward_type.discount_value)}% off"
                discount_applied = True
            elif reward_type.discount_type == 'FIXED_AMOUNT':
                discount_amount = Decimal(reward_type.discount_value)
                final_cost = max(base_cost - discount_amount, Decimal(0))
                discount_description = f"${reward_type.discount_value} off"
                discount_applied = True
            elif reward_type.discount_type == 'FREE':
                final_cost = Decimal(0)
                discount_description = "Free replacement"
                discount_applied = True

            # Only apply one discount (the first one found)
            break

        return {
            'original_cost': base_cost,
            'final_cost': final_cost,
            'discount_applied': discount_applied,
            'discount_description': discount_description,
            'savings': base_cost - final_cost,
        }

    def get_invoice_description(self):
        """Generate a descriptive line item string for invoices.

        The vehicle segment follows the customer type (see
        GlassService.get_vehicle_label) and is dropped when there is nothing
        to name — the old 'Unit #N/A' was noise on every walk-in.
        Examples:
            'Windshield Replacement - Unit #100'
            'Windshield Replacement - 2019 Ford F-150'
            'Rear Window Replacement'
        """
        position = self.get_glass_position_display() if self.glass_position else 'Glass'
        vehicle = self.get_vehicle_label()
        if vehicle:
            return f"{position} Replacement - {vehicle}"
        return f"{position} Replacement"

    class Meta:
        ordering = ['-service_date']
        verbose_name = 'Replacement'
        verbose_name_plural = 'Replacements'
        indexes = [
            models.Index(fields=['queue_status']),
            models.Index(fields=['customer', 'unit_number']),
            models.Index(fields=['technician']),
            models.Index(fields=['service_date']),
        ]

    def __str__(self):
        pos = self.get_glass_position_display() if self.glass_position else 'Glass'
        return f"Replacement {self.id} - {self.customer.name} - {pos} - {self.service_date.strftime('%Y-%m-%d')} - {self.queue_status}"


# =============================================================================
# SUPPORTING MODELS
# =============================================================================

class TechnicianNotification(models.Model):
    """In-app notification for technicians about repairs, batches, and rewards."""
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    redemption = models.ForeignKey('rewards_referrals.RewardRedemption', on_delete=models.SET_NULL, null=True, blank=True)
    repair = models.ForeignKey('Repair', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    repair_batch_id = models.UUIDField(null=True, blank=True, db_index=True, help_text="Links notification to a batch of repairs")

    def __str__(self):
        return f"Notification for {self.technician.user.username}: {self.message[:30]}..."

    @property
    def is_batch_notification(self):
        """Check if this notification is for a batch of repairs."""
        return self.repair_batch_id is not None

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Technician Notification'
        verbose_name_plural = 'Technician Notifications'


class ViscosityRecommendation(AutoUpdateTimestampMixin, models.Model):
    """
    Configurable temperature-based resin viscosity recommendations.
    Managers can configure these rules through the settings UI.
    """
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='viscosity_recommendations',
        null=True,  # Nullable during migration transition
        blank=True,
    )

    BADGE_COLOR_CHOICES = [
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('orange', 'Orange'),
        ('red', 'Red'),
        ('yellow', 'Yellow'),
        ('purple', 'Purple'),
    ]

    name = models.CharField(
        max_length=100,
        help_text="Descriptive name for this rule (e.g., 'Cold Weather', 'Standard Conditions')"
    )
    min_temperature = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Minimum temperature in °F (leave blank for no minimum)"
    )
    max_temperature = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Maximum temperature in °F (leave blank for no maximum)"
    )
    recommended_viscosity = models.CharField(
        max_length=50,
        help_text="Recommended viscosity level (e.g., 'Low', 'Medium', 'High')"
    )
    suggestion_text = models.TextField(
        help_text="The suggestion message shown to technicians (e.g., 'Low viscosity recommended for cold conditions')"
    )
    badge_color = models.CharField(
        max_length=20,
        choices=BADGE_COLOR_CHOICES,
        default='green',
        help_text="Color of the badge displayed with the suggestion"
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Order in which rules are evaluated (lower = higher priority)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this rule is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = 'Viscosity Recommendation'
        verbose_name_plural = 'Viscosity Recommendations'

    def __str__(self):
        temp_range = self._get_temp_range_display()
        return f"{self.name} ({temp_range}) → {self.recommended_viscosity}"

    def _get_temp_range_display(self):
        """Generate a human-readable temperature range."""
        if self.min_temperature is not None and self.max_temperature is not None:
            return f"{self.min_temperature}°F - {self.max_temperature}°F"
        elif self.min_temperature is not None:
            return f"≥ {self.min_temperature}°F"
        elif self.max_temperature is not None:
            return f"≤ {self.max_temperature}°F"
        else:
            return "Any temperature"

    def get_temp_range_display(self):
        """
        Public method for template access to temperature range display.
        Django templates cannot access methods starting with underscore.
        """
        return self._get_temp_range_display()

    def matches_temperature(self, temperature):
        """
        Check if a given temperature matches this rule's criteria.

        Args:
            temperature (Decimal or float): Temperature in Fahrenheit

        Returns:
            bool: True if the temperature matches this rule's range
        """
        if temperature is None:
            return False

        from decimal import Decimal
        temp = Decimal(str(temperature))

        # Check minimum temperature constraint
        if self.min_temperature is not None and temp < self.min_temperature:
            return False

        # Check maximum temperature constraint
        if self.max_temperature is not None and temp > self.max_temperature:
            return False

        return True

    @classmethod
    def get_recommendation_for_temperature(cls, temperature, tenant=None):
        """
        Get the appropriate viscosity recommendation for a given temperature.

        Args:
            temperature (Decimal or float): Temperature in Fahrenheit
            tenant: Tenant instance to scope rules to (required for multi-tenant)

        Returns:
            dict or None: Dictionary with recommendation details, or None if no match
        """
        if temperature is None:
            return None

        # Query active rules ordered by display_order, scoped to tenant
        active_rules = cls.objects.filter(is_active=True)
        if tenant:
            active_rules = active_rules.filter(tenant=tenant)
        active_rules = active_rules.order_by('display_order', 'id')

        # Find first matching rule
        for rule in active_rules:
            if rule.matches_temperature(temperature):
                return {
                    'recommendation': rule.recommended_viscosity,
                    'suggestion_text': rule.suggestion_text,
                    'badge_color': rule.badge_color,
                    'rule_name': rule.name,
                }

        return None


class JobCharge(models.Model):
    """
    A one-off extra charge on a job (trip charge, after-hours fee, disposal).

    Additive to the job's price — never touches Repair.cost / cost_override,
    so pricing sync and progressive pricing are unaffected. At invoicing time
    each charge becomes its own free-form line item on the invoice (no
    repair/replacement FK on the line, so job→invoice price sync leaves it
    alone). Once the job is invoiced, charges are managed on the invoice
    instead (Add Line Item on the invoice detail page).
    """
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='job_charges',
    )
    repair = models.ForeignKey(
        'Repair', on_delete=models.CASCADE, null=True, blank=True,
        related_name='extra_charges',
    )
    replacement = models.ForeignKey(
        'Replacement', on_delete=models.CASCADE, null=True, blank=True,
        related_name='extra_charges',
    )
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    taxable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Job Charge'
        verbose_name_plural = 'Job Charges'

    def __str__(self):
        return f"{self.description} (${self.amount})"


class FeePreset(models.Model):
    """
    A saved extra charge the shop applies often ("Trip charge — $25").
    Rendered as one-tap chips on the job form; managed in Settings → Billing.
    """
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='fee_presets',
    )
    label = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = 'Fee Preset'
        verbose_name_plural = 'Fee Presets'

    def __str__(self):
        return f"{self.label} (${self.amount})"


# Review request models live in a separate file to keep this module manageable.
from apps.technician_portal.review_models import ReviewConfig, ReviewRequest  # noqa: E402, F401
