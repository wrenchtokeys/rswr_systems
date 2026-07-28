from django.db import models
from django.core.validators import RegexValidator
from apps.tenants.managers import TenantManager


class CustomerSoftDeleteManager(TenantManager):
    """
    Default manager for Customer — automatically excludes soft-deleted records.
    Use Customer.all_objects for unfiltered access (including deleted).
    """
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Customer(models.Model):
    """
    A customer account. Supports three types:
    
    FLEET:    Business with multiple vehicles (EOS Trucking, Penske)
              Identified by business name. Has unit numbers for vehicles.
              Billed on account. Existing behavior.
              
    RETAIL:   Individual person with their own vehicle (John's F-150)
              Identified by person name. Has vehicle details.
              Usually one-time or occasional service.
              
    WALK_IN:  One-time customer with minimal info.
              Quick service, minimal data capture needed.
    """
    
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='customers',
        null=True,  # Nullable during migration transition
        blank=True,
    )
    
    CUSTOMER_TYPE_CHOICES = [
        ('FLEET', 'Fleet Account'),
        ('RETAIL', 'Individual / Retail'),
        ('WALK_IN', 'Walk-In'),
    ]
    
    customer_type = models.CharField(
        max_length=10,
        choices=CUSTOMER_TYPE_CHOICES,
        default='FLEET',
        db_index=True,
        help_text="Fleet = business account. Retail = individual person. Walk-in = one-time."
    )

    # Fleet-linked discount (1-to-many): an individual can be linked to a fleet
    # account and inherit its discount (e.g. a trucking company whose employees
    # get a discount on their personal cars). See get_effective_discount_percentage.
    parent_account = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_accounts',
        help_text="Fleet account this individual is linked to, for its discount.",
    )
    account_discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Flat % off this account's work. Individuals linked to this "
                  "account inherit it (e.g. 20.00 for 20% off).",
    )

    name = models.CharField(max_length=100)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Contact phone number"
    )
    address = models.TextField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    zip_code = models.CharField(max_length=100, null=True, blank=True)

    # Contact verification fields (added for notification system)
    email_verified = models.BooleanField(
        default=False,
        help_text="Whether email address has been verified"
    )
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When email address was verified"
    )
    phone_verified = models.BooleanField(
        default=False,
        help_text="Whether phone number has been verified"
    )
    phone_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When phone number was verified"
    )

    # Primary technician assignment
    primary_technician = models.ForeignKey(
        'technician_portal.Technician',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_customers',
        help_text="Default technician assigned to this customer's repairs"
    )

    # Tax exemption
    tax_exempt = models.BooleanField(
        default=False,
        help_text="Customer is exempt from sales tax (government, reseller, etc.)"
    )
    tax_exempt_certificate = models.CharField(
        max_length=100, blank=True,
        help_text="Tax exemption certificate number"
    )

    # Pricing model
    use_progressive_pricing = models.BooleanField(
        default=True,
        help_text="If enabled, repairs get cheaper with each subsequent repair on a unit. If disabled, every repair uses first-repair pricing."
    )

    # Stripe integration
    stripe_customer_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Stripe Customer ID for billing integration"
    )

    # Soft-delete — set to a timestamp to mark as deleted (hidden from normal
    # querysets, restorable for 30 days, then purged by purge_deleted_records)
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When set, this customer is soft-deleted and excluded from normal querysets"
    )

    # Soft-delete manager (default — excludes deleted records)
    objects = CustomerSoftDeleteManager()
    # Unfiltered manager — use when you need deleted records too
    all_objects = TenantManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'
        constraints = [
            # Business names must be unique per shop; PEOPLE share names, so
            # individuals (RETAIL/WALK_IN) are exempt — duplicate handling for
            # them is a suggest-the-existing-record flow in customer_service,
            # not a constraint (kills the old "John Smith (2)" suffix hack).
            # Soft-deleted rows are exempt too, so a shop can recreate a fleet
            # while the old one sits in Recently Deleted.
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_fleet_name_per_tenant',
                condition=models.Q(customer_type='FLEET', deleted_at__isnull=True),
            ),
            models.UniqueConstraint(
                fields=['tenant', 'email'],
                name='unique_customer_email_per_tenant',
                condition=models.Q(email__isnull=False, deleted_at__isnull=True),
            ),
        ]

    def __str__(self):
        return self.name

    def get_effective_discount_percentage(self):
        """Flat discount % that applies to this customer's work.

        Resolution: the customer's own discount if set (> 0), otherwise the
        discount granted by its linked fleet ``parent_account``, otherwise 0.
        Returns a Decimal. A plain individual with no parent still honors its
        own ``account_discount_percentage``, so this doubles as a simple
        per-customer discount when no fleet linking is used.
        """
        from decimal import Decimal
        own = self.account_discount_percentage or Decimal('0')
        if own > 0:
            return own
        if self.parent_account_id and self.parent_account:
            return self.parent_account.account_discount_percentage or Decimal('0')
        return Decimal('0')

    def save(self, *args, **kwargs):
        # Preserve original casing — lowercasing names like "EOS Trucking"
        # or "Penske" is incorrect for display
        if self.name:
            self.name = self.name.strip()
        # Store "no email" as NULL, never ''. The unique_customer_email_per_tenant
        # constraint only ignores NULL, so a second customer saved with '' raises
        # IntegrityError (500) even though both have "no email".
        if self.email is not None:
            self.email = self.email.strip() or None
        super().save(*args, **kwargs)
