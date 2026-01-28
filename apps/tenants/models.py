"""
Multi-Tenant Models

Provides Tenant and TenantMembership models for isolating business data
across multiple glass shops on the RS Systems SaaS platform.

Author: Amelia (Clawdbot AI)
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify


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
