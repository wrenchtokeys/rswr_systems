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
    
    name = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="Phone number must be entered in format: '+999999999'. Up to 15 digits allowed."
            )
        ],
        help_text="Contact phone number in E.164 format (e.g., +12025551234)"
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

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        super().save(*args, **kwargs)
