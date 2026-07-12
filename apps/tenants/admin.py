from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import ViscosityRecommendation
from apps.billing.models import BillingConfig
from rs_systems.admin_mixins import TenantFilterMixin


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 1
    autocomplete_fields = ['user']


class ViscosityRecommendationInline(admin.TabularInline):
    """Inline viscosity rules so admins can manage them directly on the Tenant page."""
    model = ViscosityRecommendation
    extra = 0
    fields = ['name', 'min_temperature', 'max_temperature', 'recommended_viscosity', 'display_order', 'is_active']
    ordering = ['display_order']
    show_change_link = True


class BillingConfigInline(admin.StackedInline):
    """Inline billing config so admins can view/edit it directly on the Tenant page."""
    model = BillingConfig
    extra = 0
    max_num = 1
    can_delete = False
    show_change_link = True
    fields = [
        'company_name', 'company_address', 'company_city', 'company_state',
        'company_zip', 'company_phone', 'company_email',
        'default_payment_terms', 'invoice_number_prefix',
        'tax_enabled', 'default_tax_rate',
    ]


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'slug', 'owner', 'plan', 'subscription_plan',
        'subscription_status', 'grace_period_end', 'had_paid_subscription_display',
        'is_active', 'created_at',
    ]
    list_filter = ['is_active', 'plan', 'subscription_status']
    search_fields = ['name', 'slug', 'subdomain']
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ['owner']
    inlines = [TenantMembershipInline, ViscosityRecommendationInline, BillingConfigInline]
    # Prevent N+1 queries for 'owner' (FK→User) and 'subscription_plan' (FK→SubscriptionPlan)
    # in the list view.  Without this, Django fires 2 extra SELECTs per tenant row.
    list_select_related = ['owner', 'subscription_plan']
    list_per_page = 25
    readonly_fields = [
        'created_at', 'updated_at', 'trial_started_at',
        'grace_period_end', 'had_paid_subscription_display',
        'is_in_grace_period_display', 'grace_days_remaining_display',
    ]
    actions = [
        'extend_trial_7_days',
        'extend_trial_30_days',
        'activate_subscription',
        'deactivate_subscription',
        'bulk_delete_tenants',
    ]
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'subdomain', 'owner'),
        }),
        ('Business Info', {
            'fields': ('business_phone', 'business_email', 'business_address', 'logo'),
        }),
        ('Subscription', {
            'fields': (
                'is_platform_owner',
                'plan', 'subscription_plan', 'subscription_status',
                'trial_started_at',
                'grace_period_end',
                'stripe_customer_id', 'stripe_subscription_id',
                'had_paid_subscription_display',
                'is_in_grace_period_display',
                'grace_days_remaining_display',
            ),
        }),
        ('Stripe Connect (Payment Processing)', {
            'fields': (
                'stripe_connect_account_id',
                'stripe_onboarding_status',
                'stripe_connect_charges_enabled',
                'stripe_connect_payouts_enabled',
                'stripe_connect_onboarding_complete',
                'stripe_connected_at',
                'platform_fee_percent',
            ),
            'classes': ('collapse',),
        }),
        ('Alerts', {
            'fields': ('subscription_alerts_sent',),
            'classes': ('collapse',),
            'description': 'Tracks which subscription alert emails have been sent.',
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at'),
        }),
    )

    # -------------------------------------------------------------------------
    # Computed display fields
    # -------------------------------------------------------------------------

    def had_paid_subscription_display(self, obj):
        if obj.had_paid_subscription:
            return format_html('<span style="color: green;">✓ Yes</span>')
        return format_html('<span style="color: #999;">No</span>')
    had_paid_subscription_display.short_description = 'Had Paid Sub?'
    had_paid_subscription_display.boolean = False

    def is_in_grace_period_display(self, obj):
        if obj.is_in_grace_period:
            days = obj.grace_days_remaining
            return format_html(
                '<span style="color: orange;">⏳ Yes ({} days left)</span>', days
            )
        return format_html('<span style="color: #999;">No</span>')
    is_in_grace_period_display.short_description = 'In Grace Period?'

    def grace_days_remaining_display(self, obj):
        days = obj.grace_days_remaining
        if days > 0:
            return format_html('<strong>{}</strong> days', days)
        return '—'
    grace_days_remaining_display.short_description = 'Grace Days Remaining'

    # -------------------------------------------------------------------------
    # Admin actions — Subscription management (Phase 3)
    # -------------------------------------------------------------------------

    @admin.action(description='⏱ Extend trial by 7 days')
    def extend_trial_7_days(self, request, queryset):
        updated = 0
        for tenant in queryset.filter(plan='trial'):
            if not tenant.trial_started_at:
                tenant.trial_started_at = timezone.now()
            # Extend by shifting trial_started_at forward 7 days
            tenant.trial_started_at = tenant.trial_started_at + timezone.timedelta(days=7)
            tenant.save(update_fields=['trial_started_at'])
            updated += 1
        self.message_user(request, f'{updated} trial(s) extended by 7 days.')

    @admin.action(description='⏱ Extend trial by 30 days')
    def extend_trial_30_days(self, request, queryset):
        updated = 0
        for tenant in queryset.filter(plan='trial'):
            if not tenant.trial_started_at:
                tenant.trial_started_at = timezone.now()
            tenant.trial_started_at = tenant.trial_started_at + timezone.timedelta(days=30)
            tenant.save(update_fields=['trial_started_at'])
            updated += 1
        self.message_user(request, f'{updated} trial(s) extended by 30 days.')

    @admin.action(description='✅ Activate subscription')
    def activate_subscription(self, request, queryset):
        # grace_period_end=None: activation clears any grace period from a
        # previous lapse, matching the webhook reactivation paths. (A3)
        updated = queryset.update(
            subscription_status='active', is_active=True, grace_period_end=None,
        )
        self.message_user(request, f'{updated} tenant(s) activated.')

    @admin.action(description='🚫 Deactivate subscription (set expired + 30-day grace)')
    def deactivate_subscription(self, request, queryset):
        grace_end = timezone.now() + timezone.timedelta(days=30)
        updated = 0
        for tenant in queryset:
            tenant.subscription_status = 'expired'
            tenant.grace_period_end = grace_end
            tenant.save(update_fields=['subscription_status', 'grace_period_end'])
            updated += 1
        self.message_user(request, f'{updated} tenant(s) deactivated with 30-day grace period.')

    @admin.action(description='🗑️ Bulk delete selected tenants (irreversible — test shops only)')
    def bulk_delete_tenants(self, request, queryset):
        """
        Hard-delete selected tenants and all related data (CASCADE).

        This is a superuser-only safety valve for removing test shops.
        Real production shops should be deactivated, not deleted.
        Only tenants with no active Stripe subscription are eligible.
        """
        from django.contrib import messages as _msgs

        if not request.user.is_superuser:
            self.message_user(
                request,
                '❌ Only superusers can bulk-delete tenants.',
                level=_msgs.ERROR,
            )
            return

        # Skip tenants with active Stripe subscriptions to prevent billing orphans
        skipped_stripe = queryset.exclude(stripe_subscription_id='').exclude(
            stripe_subscription_id__isnull=True
        ).count()
        safe = queryset.filter(
            stripe_subscription_id__in=['', None]
        )

        deleted = safe.count()
        safe.delete()

        msg = f'🗑️ {deleted} tenant(s) deleted.'
        if skipped_stripe:
            msg += f' ⚠️ {skipped_stripe} tenant(s) skipped — active Stripe subscription. Cancel in Stripe first.'
        self.message_user(request, msg)


@admin.register(TenantMembership)
class TenantMembershipAdmin(TenantFilterMixin, admin.ModelAdmin):
    """
    Admin for TenantMembership.

    Uses TenantFilterMixin so that non-superuser staff only see memberships
    for their own shop(s). Without this, a staff-level admin user at Shop A
    could read (and modify) Shop B's team roster — a tenant data leak.
    (CODE-125)
    """

    list_display = ['user', 'tenant', 'role', 'is_active', 'joined_at']
    # 'tenant' is intentionally omitted here — TenantFilterMixin.get_list_filter()
    # adds it automatically for superusers and strips it for non-superusers.
    list_filter = ['role', 'is_active']
    search_fields = ['user__username', 'user__email', 'tenant__name']
    autocomplete_fields = ['user', 'tenant']
    list_select_related = ['user', 'tenant']
    list_per_page = 25


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'slug', 'monthly_price', 'annual_price',
        'max_repairs_per_month', 'max_technicians', 'max_customers',
        'is_active', 'display_order',
    ]
    list_filter = ['is_active']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['display_order', 'is_active']
    list_per_page = 25
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'is_active', 'display_order'),
        }),
        ('Pricing', {
            'fields': ('monthly_price', 'annual_price'),
        }),
        ('Stripe', {
            'fields': ('stripe_price_id', 'stripe_annual_price_id'),
        }),
        ('Limits', {
            'fields': (
                'max_repairs_per_month', 'max_technicians',
                'max_customers', 'max_storage_mb',
            ),
            'description': 'Leave blank/null for unlimited.',
        }),
        ('Features', {
            'fields': ('features', 'trial_days'),
        }),
    )
