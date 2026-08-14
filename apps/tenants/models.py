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

from django.conf import settings
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
    Limits are enforced by UsageService, called directly from the views
    that create the resource. There is no decorator or mixin layer.
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

    def price_id_for(self, interval):
        """Stripe price id for a billing interval ('month' or 'year').

        Plan changes used to write `stripe_price_id` unconditionally, which
        silently converted an annual subscriber to monthly billing on any
        upgrade or downgrade. Read the live interval off the subscription
        and pass it here.

        Falls back to the monthly price when no annual price is configured,
        so a half-configured plan degrades to "billed monthly" rather than
        sending Stripe an empty price id.
        """
        if interval in ('year', 'annual', 'yearly') and self.stripe_annual_price_id:
            return self.stripe_annual_price_id
        return self.stripe_price_id

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
    # NULL means "use the global default". A literal 0.00 means "explicitly
    # zero-rated" (a comped shop) and beats the global.
    #
    # That distinction was broken for two years: migration 0011 added this
    # column as `default=0` NOT NULL, and 0012 made it nullable without
    # backfilling, so every pre-0012 tenant carried an explicit 0.00 that
    # silently overrode any global rate. Migration 0026 clears those.
    #
    # The percent and fixed fields resolve together as a unit -- see
    # Tenant.effective_platform_fee.
    platform_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Override global platform fee % for this tenant. Null = use global default."
    )
    platform_fee_fixed_cents = models.PositiveIntegerField(
        null=True, blank=True,
        help_text=(
            "Override the global fixed fee component, in cents. Resolved as a "
            "unit with platform_fee_percent: setting either one makes this "
            "tenant use its own pair, treating the unset half as 0."
        )
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
            ('paused', 'Paused'),
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

    # When the FIRST failed payment landed. Never overwritten by subsequent
    # failures (Stripe retries several times for the same lapse); cleared on
    # recovery. Drives the read-only ladder in subscription_middleware --
    # past_due used to show a banner and nothing else, so a shop whose card
    # died kept full write access indefinitely, for free.
    past_due_since = models.DateTimeField(
        null=True, blank=True,
        help_text="When this tenant first went past_due. Cleared on recovery."
    )

    # Watermark for out-of-order webhook protection.
    #
    # Stripe does not guarantee delivery order, and a retry can arrive minutes
    # after a later event. Without this, a late invoice.payment_failed landing
    # after invoice.paid flips a paying shop back to past_due -- which, once
    # past_due actually restricts access, locks out a customer who paid.
    #
    # Every handler that writes subscription state stamps this from the
    # event's `created` timestamp and refuses to apply anything older.
    subscription_synced_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp of the newest Stripe event applied to this "
                  "tenant's subscription state. Older events are ignored."
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
        return self.has_feature('custom_branding', plans=('pro', 'enterprise'))

    def has_feature(self, feature_name, plans=()):
        """Whether this tenant's plan includes a feature.

        Generalised from branding_enabled, which is the only caller of
        SubscriptionPlan.has_feature in the whole app. The other flags
        (`rewards`, `api_access`, `invoicing`, `customer_portal`,
        `priority_support`) appear solely in the pricing table and gate
        nothing.

        Leave it that way unless a feature is genuinely paid-tier-only.
        `rewards` in particular is seeded False on the Trial plan, but the
        pricing page excludes Trial as a tier -- "every plan starts with a
        30-day free trial" -- so enforcing that flag would hide the loyalty
        program from every shop evaluating the product.

        `plans` is an optional slug shortcut for tiers that always include
        the feature, so a tenant whose subscription_plan FK is missing still
        gets what they pay for.
        """
        if self.is_platform_owner:
            return True
        if plans and self.plan in plans:
            return True
        plan = self.subscription_plan
        return bool(plan and plan.has_feature(feature_name))

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
        The actual end of the read-only grace period after expiry.

        An explicit grace_period_end (set by the subscription.deleted webhook
        for a paid subscription that ended) always wins.

        Otherwise an expired TRIAL gets a computed grace period. It used to
        get none at all: grace_period_end was only ever written by the
        deletion webhook, so a shop that never subscribed was hard-blocked
        the instant its trial clock ran out -- no read-only window, no chance
        to export anything, straight to the upgrade wall. That also made
        check_subscription_alerts' "30 days of read-only access" copy untrue,
        which its own comment admitted.

        Trials get TRIAL_GRACE_DAYS (14) rather than the 30 a paid lapse
        gets: they never paid us. A tenant whose trial expired long ago
        computes a grace end already in the past, so they stay blocked --
        this grants nothing retroactively.
        """
        if self.grace_period_end:
            return self.grace_period_end
        # Only once the trial has actually EXPIRED. Returning a computed end
        # for a live trial would make is_in_grace_period true for every
        # tenant still inside their trial -- they'd see a "read-only access
        # remaining" banner while nothing of the sort was happening.
        if (self.plan == 'trial' and not self.had_paid_subscription
                and self.is_trial_expired):
            expiry = self.trial_expiry
            if expiry:
                return expiry + timezone.timedelta(
                    days=getattr(settings, 'TRIAL_GRACE_DAYS', 14)
                )
        return None

    @property
    def days_past_due(self):
        """Whole days since the first failed payment (0 if not past due)."""
        if not self.past_due_since:
            return 0
        return max(0, (timezone.now() - self.past_due_since).days)

    @property
    def past_due_is_read_only(self):
        """True once a past_due tenant has run out of full-access days.

        Stripe's smart retries run ~3 weeks. Restricting at day 0 would
        punish an innocently expired card; never restricting (the old
        behaviour) means a non-paying shop keeps full access for as long as
        it likes. PAST_DUE_GRACE_DAYS (14) sits between the two and still
        leaves a week of automatic retries after the restriction lands.
        """
        if self.subscription_status != 'past_due' or not self.past_due_since:
            return False
        if self.is_platform_owner:
            return False
        limit = getattr(settings, 'PAST_DUE_GRACE_DAYS', 14)
        return self.days_past_due >= limit

    @property
    def past_due_days_until_read_only(self):
        """Full-access days left before a past_due tenant goes read-only."""
        if self.subscription_status != 'past_due' or not self.past_due_since:
            return None
        limit = getattr(settings, 'PAST_DUE_GRACE_DAYS', 14)
        return max(0, limit - self.days_past_due)

    def mark_subscription_active(self, status='active', subscription_id=None,
                                 plan=None, extra_fields=None):
        """Move the tenant to a live state and clear every lapse marker.

        Three near-identical reactivation blocks used to do this by hand and
        each forgot something. The one that mattered: subscription_alerts_sent
        was never cleared, so a tenant who lapsed, resubscribed, and lapsed
        again received NO lifecycle emails the second time -- the dedup keys
        from the first lapse were still there, permanently suppressing them.
        """
        self.subscription_status = status
        self.grace_period_end = None
        self.past_due_since = None
        self.subscription_alerts_sent = {}
        update_fields = [
            'subscription_status', 'grace_period_end', 'past_due_since',
            'subscription_alerts_sent',
        ]
        if subscription_id and self.stripe_subscription_id != subscription_id:
            self.stripe_subscription_id = subscription_id
            update_fields.append('stripe_subscription_id')
        if plan is not None:
            self.plan = plan.slug
            self.subscription_plan = plan
            update_fields.extend(['plan', 'subscription_plan'])
        if extra_fields:
            update_fields.extend(
                f for f in extra_fields if f not in update_fields
            )
        return update_fields

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

    @property
    def effective_platform_fee(self):
        """The platform fee that applies to this tenant's invoice payments.

        Returns (percent: Decimal, fixed_cents: int, source: str).

        Resolution order:
          1. Platform owner        -> 0. We do not charge ourselves, and
             this is the tenant most likely to be sitting on a legacy 0.00.
          2. Fees globally off     -> 0. The master switch wins over
             everything, so turning fees off is always one click.
          3. Tenant override       -> the tenant's pair.
          4. Global default        -> PlatformConfig's pair.

        Percent and fixed resolve AS A UNIT. Mixing a tenant percent with a
        global fixed produces a rate nobody configured and no one can
        explain to a shop owner asking why they were charged what they were.

        This is the only place the fee is decided. There used to be three
        implementations -- two of them dead, and one writing a different
        metadata key than the reader expected, which is what caused CODE-069.
        """
        from decimal import Decimal

        if self.is_platform_owner:
            return Decimal('0'), 0, 'platform_owner'

        from apps.billing.models import PlatformConfig
        config = PlatformConfig.get()

        if not config.fee_enabled:
            return Decimal('0'), 0, 'disabled'

        has_override = (
            self.platform_fee_percent is not None
            or self.platform_fee_fixed_cents is not None
        )
        if has_override:
            return (
                self.platform_fee_percent or Decimal('0'),
                self.platform_fee_fixed_cents or 0,
                'tenant',
            )

        return (
            config.default_fee_percent or Decimal('0'),
            config.default_fee_fixed_cents or 0,
            'global',
        )

    @property
    def platform_fee_label(self):
        """Human-readable fee, for the Connect setup and billing pages.

        Shops are told about this before they onboard, not after they have
        completed KYC.
        """
        percent, fixed_cents, source = self.effective_platform_fee
        if not percent and not fixed_cents:
            return 'No platform fee'
        parts = []
        if percent:
            parts.append(f"{percent.normalize():f}%".replace('.0%', '%'))
        if fixed_cents:
            parts.append(f"${fixed_cents / 100:.2f}")
        return ' + '.join(parts) + ' per transaction'


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
