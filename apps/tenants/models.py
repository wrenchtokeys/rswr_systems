"""
Multi-Tenant Models

Provides Tenant, TenantMembership, SubscriptionPlan, and InviteToken
models for isolating business data and managing SaaS billing across
multiple glass shops on the RS Systems platform.

Author: Amelia (Clawdbot AI)
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.text import slugify

from rs_systems.model_mixins import AutoUpdateTimestampMixin


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


class Tenant(AutoUpdateTimestampMixin, models.Model):
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
    brand_color = models.CharField(
        max_length=7,
        blank=True,
        default='',
        validators=[RegexValidator(r'^#[0-9a-fA-F]{6}$', 'Enter a hex color like #3b82f6.')],
        help_text="Shop's brand color, used on invoices, emails, and the customer portal. Blank = platform default.",
    )
    
    # Assignment strategy
    ASSIGNMENT_STRATEGY_CHOICES = [
        ('manual', 'Manual — manager assigns all repairs'),
        ('primary_first', 'Primary Tech First — auto-assign if customer has a primary tech, otherwise queue'),
        ('auto', 'Smart Auto-Assign — auto-assign based on workload and abilities'),
        ('round_robin', 'Round Robin — rotate evenly through eligible techs'),
    ]
    assignment_strategy = models.CharField(
        max_length=20,
        choices=ASSIGNMENT_STRATEGY_CHOICES,
        default='primary_first',
        help_text="How new repair requests are assigned to technicians"
    )

    # Services this shop offers (drives nav, dashboards, customer portal,
    # and default technician abilities)
    SERVICES_CHOICES = [
        ('repair', 'Repairs only'),
        ('replacement', 'Replacements only'),
        ('both', 'Both repairs and replacements'),
    ]
    services_offered = models.CharField(
        max_length=20,
        choices=SERVICES_CHOICES,
        default='both',
        help_text="Which services this shop performs"
    )

    # Settings
    is_active = models.BooleanField(default=True)
    auto_invoice_enabled = models.BooleanField(
        default=True,
        help_text="When enabled, invoices are auto-generated on repair completion (per customer preference). Disable for testing."
    )
    use_progressive_pricing = models.BooleanField(
        default=True,
        help_text="When enabled, repair prices decrease with each subsequent repair on a unit. When disabled, every repair uses first-repair pricing."
    )
    
    # Configurable pricing tiers (used when progressive pricing is enabled)
    repair_price_1 = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('50.00'),
        help_text="Price for 1st repair on a unit"
    )
    repair_price_2 = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('40.00'),
        help_text="Price for 2nd repair on a unit"
    )
    repair_price_3 = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('35.00'),
        help_text="Price for 3rd repair on a unit"
    )
    repair_price_4 = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('30.00'),
        help_text="Price for 4th repair on a unit"
    )
    repair_price_5_plus = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('25.00'),
        help_text="Price for 5th+ repairs on a unit"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Plan intent (chosen at signup, used to pre-select on upgrade)
    intended_plan = models.CharField(
        max_length=20, blank=True,
        help_text='Plan slug chosen during signup, used to pre-select on upgrade'
    )

    # Stripe billing
    stripe_customer_id = models.CharField(
        max_length=50, blank=True, db_index=True,
        help_text="Stripe Customer ID for platform billing"
    )
    stripe_subscription_id = models.CharField(
        max_length=50, blank=True, db_index=True,
        help_text="Stripe Subscription ID for platform billing"
    )

    # Stripe Connect — for receiving customer invoice payments
    STRIPE_ONBOARDING_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('pending', 'Onboarding Started'),
        ('in_review', 'In Review'),
        ('active', 'Active'),
        ('restricted', 'Restricted'),
        ('disabled', 'Disabled'),
    ]

    stripe_connect_account_id = models.CharField(
        max_length=50, blank=True, db_index=True,
        help_text="Stripe Connect Account ID (acct_...) for receiving invoice payments"
    )
    stripe_onboarding_status = models.CharField(
        max_length=20,
        choices=STRIPE_ONBOARDING_STATUS_CHOICES,
        default='not_started',
        help_text="Current Stripe Connect onboarding status"
    )
    stripe_connect_onboarding_complete = models.BooleanField(
        default=False,
        help_text="Whether Stripe Connect onboarding (KYC, bank account) is fully complete"
    )
    stripe_connect_charges_enabled = models.BooleanField(
        default=False,
        help_text="Whether the connected account can accept charges"
    )
    stripe_connect_payouts_enabled = models.BooleanField(
        default=False,
        help_text="Whether the connected account can receive payouts to their bank"
    )
    stripe_connected_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the Stripe Connect account first became active"
    )
    platform_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Override global platform fee for this tenant. Null = use global default."
    )

    # Platform owner flag — exempt from subscription billing
    is_platform_owner = models.BooleanField(
        default=False,
        help_text="Platform owner tenant — permanent pro plan, no subscription required"
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

    # Grace period tracking
    grace_period_end = models.DateTimeField(
        null=True, blank=True,
        help_text="End of the 30-day read-only grace period after subscription expiry"
    )

    # Subscription alert tracking (avoids duplicate emails)
    subscription_alerts_sent = models.JSONField(
        default=dict, blank=True,
        help_text="Tracks which subscription alert emails have been sent, keyed by alert type"
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

        # AutoUpdateTimestampMixin handles updated_at injection for
        # save(update_fields=...) calls. (CODE-253 → CODE-254)
        super().save(*args, **kwargs)
    
    def get_upload_prefix(self):
        """Return S3 path prefix for tenant-scoped uploads."""
        return f"tenants/{self.slug}"
    
    @property
    def offers_repairs(self):
        """Whether this shop performs chip/crack repairs."""
        return self.services_offered in ('repair', 'both')

    @property
    def offers_replacements(self):
        """Whether this shop performs glass replacements."""
        return self.services_offered in ('replacement', 'both')

    @property
    def branding_enabled(self):
        """
        Whether this shop's custom branding (logo + brand color) is applied
        to the portals, emails and invoice PDFs.

        Sold as the plans' `custom_branding` feature (Pro and up — see
        seed_plans / the pricing page). Uploaded logo/color are kept either
        way; they just don't render until the plan includes the feature.
        """
        if self.is_platform_owner:
            return True
        if self.plan in ('pro', 'enterprise'):
            return True
        plan = self.subscription_plan
        return bool(plan and plan.has_feature('custom_branding'))

    def _get_trial_days(self):
        """Return number of trial days for this tenant's plan."""
        if self.subscription_plan and self.subscription_plan.trial_days:
            return self.subscription_plan.trial_days
        return 30

    @property
    def trial_expiry(self):
        """Datetime when the trial expires (or None if not on trial)."""
        if self.plan != 'trial' or not self.trial_started_at:
            return None
        return self.trial_started_at + timezone.timedelta(days=self._get_trial_days())

    @property
    def is_trial_expired(self):
        """Check if the free trial period has ended."""
        if self.is_platform_owner:
            return False
        expiry = self.trial_expiry
        if expiry is None:
            return False
        return timezone.now() > expiry

    @property
    def trial_days_remaining(self):
        """Days left in the trial period (0 if expired or not on trial)."""
        expiry = self.trial_expiry
        if expiry is None:
            return 0
        remaining = (expiry - timezone.now()).days
        return max(0, remaining)

    @property
    def effective_grace_period_end(self):
        """
        The actual end of the grace period after subscription expiry.

        Grace period applies only when explicitly set (via _handle_subscription_deleted
        webhook) for paid subscriptions. Free trials do NOT get a dynamic grace period
        because their trial duration already serves that purpose.

        Returns the grace_period_end datetime, or None if no grace period applies.
        """
        if self.grace_period_end:
            return self.grace_period_end
        return None

    @property
    def is_in_grace_period(self):
        """True if we're in the 30-day read-only grace period after expiry."""
        grace_end = self.effective_grace_period_end
        if grace_end is None:
            return False
        return timezone.now() <= grace_end

    @property
    def grace_days_remaining(self):
        """Days remaining in grace period (0 if ended or not in grace period)."""
        grace_end = self.effective_grace_period_end
        if grace_end is None:
            return 0
        remaining = (grace_end - timezone.now()).days
        return max(0, remaining)

    @property
    def had_paid_subscription(self):
        """True if this tenant ever had a paid Stripe subscription."""
        return bool(self.stripe_subscription_id)

    @property
    def can_accept_payments(self):
        """True if this tenant's Stripe Connect account can accept invoice payments."""
        return (
            bool(self.stripe_connect_account_id)
            and self.stripe_onboarding_status == 'active'
            and self.stripe_connect_charges_enabled
        )

    @property
    def can_receive_payouts(self):
        """True if this tenant's Stripe Connect account can pay out to their bank."""
        return (
            bool(self.stripe_connect_account_id)
            and self.stripe_connect_payouts_enabled
        )


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


class InviteToken(models.Model):
    """Token for invited users to set their password and join a shop."""
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='invite_tokens')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invite_tokens')
    role = models.CharField(max_length=20, choices=TenantMembership.ROLE_CHOICES)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_invites')
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invite for {self.user.email} to {self.tenant.name} ({self.role})"

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)


class OnboardingState(models.Model):
    """
    Per-tenant first-run state: wizard progress, checklist/banner dismissals,
    and which interactive tours have been completed.

    Fetch via OnboardingState.get_for_tenant(tenant) — lazy-created like
    BillingConfig. Session state is deliberately NOT used here: the wizard
    must be resumable across logins and devices.
    """

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='onboarding_state',
    )
    # 1-based wizard step the owner should resume at; 0 means never started.
    wizard_step = models.PositiveSmallIntegerField(default=0)
    wizard_completed_at = models.DateTimeField(null=True, blank=True)
    checklist_dismissed_at = models.DateTimeField(null=True, blank=True)
    trial_banner_dismissed_at = models.DateTimeField(null=True, blank=True)
    # {"<tour-slug>": "<ISO timestamp>"} — skipping counts as completing,
    # so a tour never re-nags. New tours need no migration.
    tours_completed = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Onboarding State'
        verbose_name_plural = 'Onboarding States'

    def __str__(self):
        return f"Onboarding state for {self.tenant.name}"

    @classmethod
    def get_for_tenant(cls, tenant):
        """Get (or create with defaults) the OnboardingState for this tenant."""
        instance, _ = cls.objects.get_or_create(tenant=tenant)
        return instance

    @property
    def wizard_completed(self):
        return self.wizard_completed_at is not None

    def mark_tour_completed(self, slug):
        self.tours_completed[slug] = timezone.now().isoformat()
        self.save(update_fields=['tours_completed', 'updated_at'])

    def has_completed_tour(self, slug):
        return slug in self.tours_completed
