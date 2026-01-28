from django.contrib import admin
from .models import Tenant, TenantMembership, SubscriptionPlan


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 1
    raw_id_fields = ['user']


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'slug', 'owner', 'plan', 'subscription_plan',
        'subscription_status', 'is_active', 'created_at',
    ]
    list_filter = ['is_active', 'plan', 'subscription_status']
    search_fields = ['name', 'slug', 'subdomain']
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ['owner']
    inlines = [TenantMembershipInline]
    readonly_fields = ['created_at', 'updated_at', 'trial_started_at']
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'subdomain', 'owner'),
        }),
        ('Business Info', {
            'fields': ('business_phone', 'business_email', 'business_address', 'logo'),
        }),
        ('Subscription', {
            'fields': (
                'plan', 'subscription_plan', 'subscription_status',
                'trial_started_at',
                'stripe_customer_id', 'stripe_subscription_id',
            ),
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at'),
        }),
    )


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'tenant', 'role', 'is_active', 'joined_at']
    list_filter = ['role', 'is_active']
    search_fields = ['user__username', 'user__email', 'tenant__name']
    raw_id_fields = ['user', 'tenant']


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
