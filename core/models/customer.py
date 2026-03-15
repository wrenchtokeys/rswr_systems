from django.db import models
from django.core.validators import RegexValidator
from apps.tenants.managers import TenantManager


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

    # Default manager + tenant-aware manager
    objects = TenantManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_customer_name_per_tenant',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'email'],
                name='unique_customer_email_per_tenant',
                condition=models.Q(email__isnull=False),
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Preserve original casing — lowercasing names like "EOS Trucking"
        # or "Penske" is incorrect for display
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)
