from django.contrib import admin
from django.utils import timezone
from rs_systems.admin_mixins import TenantFilterMixin
from .models import ReferralCode, Referral, Reward, RewardOption, RewardRedemption, RewardType


# ---------------------------------------------------------------------------
# Helper mixin for models that reach tenant through CustomerUser → Customer → Tenant
# ---------------------------------------------------------------------------

class CustomerUserTenantFilterMixin:
    """
    Mixin for admin classes whose models reach their tenant via:
    customer_user → customer → tenant

    Override `customer_user_path` if the path to CustomerUser differs.
    """
    customer_user_path: str = 'customer_user'

    def _get_user_tenant_ids(self, request):
        from apps.tenants.models import TenantMembership
        return (
            TenantMembership.objects
            .filter(user=request.user, is_active=True)
            .values_list('tenant_id', flat=True)
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        tenant_ids = self._get_user_tenant_ids(request)
        return qs.filter(**{f"{self.customer_user_path}__customer__tenant__in": tenant_ids})

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if request.user.is_superuser:
            tenant_filter = f'{self.customer_user_path}__customer__tenant'
            if tenant_filter not in filters:
                filters = [tenant_filter] + filters
        return filters

    def get_tenant_display(self, obj):
        """Helper for list_display: shows tenant name."""
        try:
            cu = obj
            for part in self.customer_user_path.split('__'):
                cu = getattr(cu, part)
            return cu.customer.tenant.name
        except AttributeError:
            return '—'
    get_tenant_display.short_description = 'Tenant'


@admin.register(RewardOption)
class RewardOptionAdmin(TenantFilterMixin, admin.ModelAdmin):
    """
    Admin configuration for RewardOption model.
    RewardOption has a direct tenant FK.
    """
    list_display = ['tenant', 'name', 'points_required', 'get_reward_type', 'is_active']
    list_filter = ['tenant', 'is_active', 'reward_type__category']
    search_fields = ['name', 'description', 'tenant__name']
    list_editable = ['points_required', 'is_active']
    list_select_related = ['tenant', 'reward_type']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 25

    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'description', 'points_required', 'is_active']
        }),
        ('Reward Type', {
            'fields': ['reward_type']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def get_reward_type(self, obj):
        return obj.reward_type.name if obj.reward_type else "No Type"
    get_reward_type.short_description = 'Reward Type'


@admin.register(RewardRedemption)
class RewardRedemptionAdmin(admin.ModelAdmin):
    """
    Admin configuration for RewardRedemption model.

    RewardRedemption has no direct tenant FK but is scoped via reward_option → tenant
    for superuser filtering, and via reward → customer_user → customer → tenant
    for non-superuser access control.
    """
    list_display = [
        'id',
        'get_tenant_display',
        'get_customer_email',
        'reward_option',
        'status',
        'assigned_technician',
        'get_applied_to_repair',
        'created_at',
        'processed_at'
    ]
    list_filter = ['status', 'assigned_technician', 'created_at']
    search_fields = [
        'reward__customer_user__user__email',
        'reward_option__name',
        'notes'
    ]
    autocomplete_fields = ['reward_option', 'processed_by', 'assigned_technician', 'applied_to_repair']
    raw_id_fields = ['reward']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'processed_at', 'fulfilled_at']
    list_per_page = 25

    fieldsets = [
        ('Redemption Information', {
            'fields': ['reward', 'reward_option', 'status', 'notes']
        }),
        ('Assignment Details', {
            'fields': ['assigned_technician', 'applied_to_repair']
        }),
        ('Processing Details', {
            'fields': ['processed_by', 'processed_at', 'fulfilled_at'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at'],
            'classes': ['collapse']
        }),
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        from apps.tenants.models import TenantMembership
        tenant_ids = (
            TenantMembership.objects
            .filter(user=request.user, is_active=True)
            .values_list('tenant_id', flat=True)
        )
        return qs.filter(reward__customer_user__customer__tenant__in=tenant_ids)

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if request.user.is_superuser and 'reward_option__tenant' not in filters:
            filters = ['reward_option__tenant'] + filters
        return filters

    def get_tenant_display(self, obj):
        try:
            return obj.reward.customer_user.customer.tenant.name
        except AttributeError:
            return '—'
    get_tenant_display.short_description = 'Tenant'

    def get_customer_email(self, obj):
        return obj.reward.customer_user.user.email
    get_customer_email.short_description = 'Customer'
    get_customer_email.admin_order_field = 'reward__customer_user__user__email'

    def get_applied_to_repair(self, obj):
        if obj.applied_to_repair:
            return f"Unit #{obj.applied_to_repair.unit_number} - {obj.applied_to_repair.damage_type}"
        return "Not applied"
    get_applied_to_repair.short_description = 'Applied To Repair'

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            if obj.status in ['APPROVED', 'FULFILLED', 'REJECTED']:
                obj.processed_by = request.user
                obj.processed_at = timezone.now()
                if obj.status == 'FULFILLED' and not obj.fulfilled_at:
                    obj.fulfilled_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(Reward)
class RewardAdmin(CustomerUserTenantFilterMixin, admin.ModelAdmin):
    """
    Admin configuration for Reward model.
    Reward → customer_user → customer → tenant
    """
    list_display = ['get_tenant_display', 'customer_email', 'points', 'created_at', 'updated_at']
    search_fields = ['customer_user__user__email', 'customer_user__customer__tenant__name']
    list_filter = ['created_at']
    list_select_related = ['customer_user', 'customer_user__user', 'customer_user__customer', 'customer_user__customer__tenant']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    list_per_page = 25

    fieldsets = [
        ('Customer Information', {
            'fields': ['customer_user']
        }),
        ('Reward Points', {
            'fields': ['points']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def customer_email(self, obj):
        return obj.customer_user.user.email
    customer_email.short_description = 'Customer'
    customer_email.admin_order_field = 'customer_user__user__email'


@admin.register(ReferralCode)
class ReferralCodeAdmin(CustomerUserTenantFilterMixin, admin.ModelAdmin):
    """
    Admin configuration for ReferralCode model.
    ReferralCode → customer_user → customer → tenant
    """
    list_display = ['get_tenant_display', 'code', 'customer_email', 'created_at', 'get_referral_count']
    search_fields = ['code', 'customer_user__user__email', 'customer_user__customer__tenant__name']
    list_filter = ['created_at']
    list_select_related = ['customer_user', 'customer_user__user', 'customer_user__customer', 'customer_user__customer__tenant']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    list_per_page = 25

    fieldsets = [
        ('Referral Code', {
            'fields': ['code', 'customer_user']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def customer_email(self, obj):
        return obj.customer_user.user.email
    customer_email.short_description = 'Customer'
    customer_email.admin_order_field = 'customer_user__user__email'

    def get_referral_count(self, obj):
        return Referral.objects.filter(referral_code=obj).count()
    get_referral_count.short_description = 'Referral Count'


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    """
    Admin configuration for Referral model.
    Referral → customer_user → customer → tenant (both referrer and referred)
    """
    list_display = ['get_tenant_display', 'referrer_email', 'referred_email', 'created_at']
    search_fields = [
        'referral_code__customer_user__user__email',
        'customer_user__user__email',
        'referral_code__customer_user__customer__tenant__name',
    ]
    list_filter = ['created_at']
    list_select_related = [
        'referral_code__customer_user__user',
        'referral_code__customer_user__customer__tenant',
        'customer_user__user',
    ]
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    list_per_page = 25

    fieldsets = [
        ('Referral Details', {
            'fields': ['referral_code', 'customer_user']
        }),
        ('Timestamps', {
            'fields': ['created_at'],
            'classes': ['collapse']
        }),
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        from apps.tenants.models import TenantMembership
        tenant_ids = (
            TenantMembership.objects
            .filter(user=request.user, is_active=True)
            .values_list('tenant_id', flat=True)
        )
        return qs.filter(referral_code__customer_user__customer__tenant__in=tenant_ids)

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if request.user.is_superuser and 'referral_code__customer_user__customer__tenant' not in filters:
            filters = ['referral_code__customer_user__customer__tenant'] + filters
        return filters

    def get_tenant_display(self, obj):
        try:
            return obj.referral_code.customer_user.customer.tenant.name
        except AttributeError:
            return '—'
    get_tenant_display.short_description = 'Tenant'

    def referrer_email(self, obj):
        return obj.referral_code.customer_user.user.email
    referrer_email.short_description = 'Referrer'
    referrer_email.admin_order_field = 'referral_code__customer_user__user__email'

    def referred_email(self, obj):
        return obj.customer_user.user.email
    referred_email.short_description = 'Referred User'
    referred_email.admin_order_field = 'customer_user__user__email'


@admin.register(RewardType)
class RewardTypeAdmin(admin.ModelAdmin):
    """
    Admin configuration for RewardType model.
    RewardType is a global lookup table with no tenant FK (shared across tenants).
    """
    list_display = ['name', 'category', 'discount_type', 'discount_value', 'is_active']
    list_filter = ['category', 'discount_type', 'is_active']
    search_fields = ['name', 'description']
    list_editable = ['discount_value', 'is_active']
    list_per_page = 25

    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'description', 'is_active']
        }),
        ('Reward Classification', {
            'fields': ['category']
        }),
        ('Discount Details', {
            'fields': ['discount_type', 'discount_value']
        }),
    ]
