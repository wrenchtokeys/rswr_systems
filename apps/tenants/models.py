"""
Multi-Tenant Models

Provides Tenant, TenantMembership, and SubscriptionPlan models for
isolating business data and managing SaaS billing across multiple
glass shops on the RS Systems platform.

Author: Amelia (Clawdbot AI)
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify


class SubscriptionPlan(models.Model):
    """
    Defines a SaaS subscription tier with pricing, limits, and features.
    
    Plans: Trial (free), Starter ($49/mo), Pro ($99/mo), Enterprise ($249/mo).
    Limits are enforced by PlanEnforcementMixin and usage_service.
    null limit values mean unlimited.
    """
    
    name = models.CharField(max_length=50)  # "Trial", "Starter", "Pro", "Enterprise"
    slug = models.SlugField(unique=True)
    stripe_price_id = models.CharField(
        max_length=100, blank=True,
        help_text="Stripe Price ID for monthly billing"
    )
    stripe_annual_price_id = models.CharField(
        max_length=100, blank=True,
        help_text="Stripe Price ID for annual billing"
    )
    
    # Pricing
    monthly_price = models.DecimalField(max_digits=8, decimal_places=2)
    annual_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    
    # Limits (null = unlimited)
    max_repairs_per_month = models.IntegerField(
        null=True, blank=True,
        help_text="Max repairs per month. null = unlimited."
    )
    max_technicians = models.IntegerField(
        null=True, blank=True,
        help_text="Max active technicians. null = unlimited."
    )
    max_customers = models.IntegerField(
        null=True, blank=True,
        help_text="Max customer accounts. null = unlimited."
    )
    max_storage_mb = models.IntegerField(
        default=500,
        help_text="Max storage in MB for photos/documents."
    )
    
    # Features
    features = models.JSONField(
        default=dict,
        help_text='Feature flags, e.g. {"invoicing": true, "rewards": true, "api_access": false}'
    )
    
    # Trial-specific
    trial_days = models.IntegerField(
        default=0,
        help_text="Number of trial days (0 = not a trial plan)"
    )
    
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['display_order', 'monthly_price']
        verbose_name = 'Subscription Plan'
        verbose_name_plural = 'Subscription Plans'
    
    def __str__(self):
        return f"{self.name} (${self.monthly_price}/mo)"
    
    @property
    def is_free(self):
        return self.monthly_price == 0
    
    def has_feature(self, feature_name):
        """Check if this plan includes a specific feature."""
        return self.features.get(feature_name, False)


class Tenant(models.Model):
    """
    Represents a glass shop business on the RS Systems platform.
    
    Each tenant gets isolated data — customers, repairs, invoices, etc.
    All business models carry a tenant FK for data isolation.
    """
    
    PLAN_CHOICES = [
        ('trial', 'Free Trial'),
        ('starter', 'Starter'),
        ('pro', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]
    
    # Identity
    name = models.CharField(
        max_length=200,
        help_text="Business name (e.g., 'Rockstar Windshield Repair')"
    )
    slug = models.SlugField(
        unique=True,
        help_text="URL-safe identifier (e.g., 'rockstar-windshield')"
    )
    subdomain = models.CharField(
        max_length=63,
        unique=True,
        help_text="For future subdomain-based routing (e.g., 'rockstar')"
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='owned_tenants',
        help_text="The primary owner of this business"
    )
    
    # Business info
    business_phone = models.CharField(max_length=20, blank=True)
    business_email = models.EmailField(blank=True)
    business_address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='tenants/logos/', blank=True)
    
    # Settings
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Stripe billing
    stripe_customer_id = models.CharField(
        max_length=50, blank=True,
        help_text="Stripe Customer ID for platform billing"
    )
    stripe_subscription_id = models.CharField(
        max_length=50, blank=True,
        help_text="Stripe Subscription ID for platform billing"
    )
    
    # Plan (for Phase 3 billing)
    plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default='trial',
    )
    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='tenants',
        help_text="Current subscription plan (detailed limits & features)"
    )
    
    # Trial tracking
    trial_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the free trial began"
    )
    subscription_status = models.CharField(
        max_length=20,
        choices=[
            ('trialing', 'Trialing'),
            ('active', 'Active'),
            ('past_due', 'Past Due'),
            ('canceled', 'Canceled'),
            ('expired', 'Expired'),
        ],
        default='trialing',
        help_text="Current subscription lifecycle status"
    )
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.subdomain:
            self.subdomain = self.slug
        super().save(*args, **kwargs)
    
    def get_upload_prefix(self):
        """Return S3 path prefix for tenant-scoped uploads."""
        return f"tenants/{self.slug}"
    
    @property
    def is_trial_expired(self):
        """Check if the free trial period has ended."""
        if self.plan != 'trial' or not self.trial_started_at:
            return False
        trial_days = 30
        if self.subscription_plan and self.subscription_plan.trial_days:
            trial_days = self.subscription_plan.trial_days
        expiry = self.trial_started_at + timezone.timedelta(days=trial_days)
        return timezone.now() > expiry
    
    @property
    def trial_days_remaining(self):
        """Days left in the trial period (0 if expired or not on trial)."""
        if self.plan != 'trial' or not self.trial_started_at:
            return 0
        trial_days = 30
        if self.subscription_plan and self.subscription_plan.trial_days:
            trial_days = self.subscription_plan.trial_days
        expiry = self.trial_started_at + timezone.timedelta(days=trial_days)
        remaining = (expiry - timezone.now()).days
        return max(0, remaining)


class TenantMembership(models.Model):
    """
    Links users to tenants with role-based access.
    
    A user can belong to multiple tenants (e.g., a tech who works for
    two shops). Each membership has a role that determines permissions.
    """
    
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('manager', 'Manager'),
        ('technician', 'Technician'),
        ('viewer', 'Viewer'),
    ]
    
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tenant_memberships',
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='viewer',
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['tenant', 'user']
        ordering = ['tenant', 'role']
        verbose_name = 'Tenant Membership'
        verbose_name_plural = 'Tenant Memberships'
    
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} — {self.tenant.name} ({self.get_role_display()})"
