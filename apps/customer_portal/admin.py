import csv

from django.contrib import admin
from django.http import HttpResponse
from django import forms
from .models import CustomerUser, CustomerPreference, RepairApproval, CustomerRepairPreference, CustomerInvitation
from .pricing_models import CustomerPricing


# ---------------------------------------------------------------------------
# Helper mixin for models that reach their tenant through customer → tenant
# ---------------------------------------------------------------------------

class CustomerTenantFilterMixin:
    """
    Mixin for admin classes whose models don't have a direct tenant FK but
    reach a tenant through a `customer` FK: model → customer → tenant.

    Superusers see all records. Non-superusers see only their own tenant(s).
    Adds tenant to list_filter for superusers only.
    """

    # Override this if the path to customer differs (e.g. 'repair__customer')
    customer_path: str = 'customer'

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
        return qs.filter(**{f"{self.customer_path}__tenant__in": tenant_ids})

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if request.user.is_superuser:
            tenant_filter = f'{self.customer_path}__tenant'
            if tenant_filter not in filters:
                filters = [tenant_filter] + filters
        return filters

    def get_tenant_display(self, obj):
        """Helper for list_display: shows tenant name."""
        try:
            customer = obj
            for part in self.customer_path.split('__'):
                customer = getattr(customer, part)
            return customer.tenant.name
        except AttributeError:
            return '—'
    get_tenant_display.short_description = 'Tenant'


@admin.register(CustomerUser)
class CustomerUserAdmin(CustomerTenantFilterMixin, admin.ModelAdmin):
    list_display = ['user', 'get_tenant_display', 'customer', 'get_email', 'get_full_name', 'is_primary_contact']
    list_filter = ['is_primary_contact', 'customer']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name', 'customer__name', 'customer__tenant__name']
    list_select_related = ['user', 'customer', 'customer__tenant']
    list_per_page = 25

    def get_email(self, obj):
        return obj.user.email
    get_email.short_description = 'Email'
    get_email.admin_order_field = 'user__email'

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
    get_full_name.short_description = 'Full Name'
    get_full_name.admin_order_field = 'user__first_name'

    fieldsets = (
        (None, {
            'fields': ('user', 'customer', 'is_primary_contact')
        }),
    )


@admin.register(CustomerPreference)
class CustomerPreferenceAdmin(CustomerTenantFilterMixin, admin.ModelAdmin):
    list_display = ['get_tenant_display', 'customer', 'receive_email_notifications', 'receive_sms_notifications', 'default_view']
    list_filter = ['receive_email_notifications', 'receive_sms_notifications', 'default_view']
    search_fields = ['customer__name', 'customer__tenant__name']
    list_select_related = ['customer', 'customer__tenant']
    list_per_page = 25


@admin.register(RepairApproval)
class RepairApprovalAdmin(CustomerTenantFilterMixin, admin.ModelAdmin):
    # RepairApproval → repair → customer → tenant
    customer_path = 'repair__customer'

    list_display = ['repair', 'get_tenant_display', 'approved', 'approved_by', 'approval_date']
    list_filter = ['approved', 'approval_date']
    search_fields = ['repair__id', 'repair__customer__name', 'approved_by__user__username', 'repair__customer__tenant__name']
    readonly_fields = ['approval_date']
    list_select_related = ['repair', 'repair__customer', 'repair__customer__tenant', 'approved_by']
    list_per_page = 25


@admin.register(CustomerPricing)
class CustomerPricingAdmin(CustomerTenantFilterMixin, admin.ModelAdmin):
    list_display = ['get_tenant_display', 'customer', 'use_custom_pricing', 'created_at', 'created_by']
    list_filter = ['use_custom_pricing', 'created_at']
    search_fields = ['customer__name', 'notes', 'customer__tenant__name']
    list_select_related = ['customer', 'customer__tenant', 'created_by']
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 25

    fieldsets = (
        ('Customer & Settings', {
            'fields': ('customer', 'use_custom_pricing', 'notes')
        }),
        ('Custom Repair Pricing', {
            'fields': ('repair_1_price', 'repair_2_price', 'repair_3_price',
                      'repair_4_price', 'repair_5_plus_price'),
            'description': 'Set custom prices for each repair tier. Leave blank to use default pricing.'
        }),
        ('Volume Discounts', {
            'fields': ('volume_discount_threshold', 'volume_discount_percentage'),
            'description': 'Configure volume discounts for high-volume customers.'
        }),
        ('Tracking', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# Custom form for CustomerRepairPreference with conditional validation
class CustomerRepairPreferenceForm(forms.ModelForm):
    """
    Enhanced form for CustomerRepairPreference model with lot walking configuration.
    """

    DAYS_OF_WEEK = [
        ('Monday', 'Monday'),
        ('Tuesday', 'Tuesday'),
        ('Wednesday', 'Wednesday'),
        ('Thursday', 'Thursday'),
        ('Friday', 'Friday'),
        ('Saturday', 'Saturday'),
        ('Sunday', 'Sunday'),
    ]

    lot_walking_days_choices = forms.MultipleChoiceField(
        choices=DAYS_OF_WEEK,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Preferred Days for Lot Walking",
        help_text="Select all days that work for your schedule"
    )

    class Meta:
        model = CustomerRepairPreference
        fields = '__all__'
        widgets = {
            'lot_walking_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'vTimeField'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.lot_walking_days:
            self.fields['lot_walking_days_choices'].initial = self.instance.lot_walking_days

    def clean(self):
        cleaned_data = super().clean()
        approval_mode = cleaned_data.get('field_repair_approval_mode')
        threshold = cleaned_data.get('units_per_visit_threshold')
        lot_walking_enabled = cleaned_data.get('lot_walking_enabled')
        lot_walking_frequency = cleaned_data.get('lot_walking_frequency')

        if approval_mode == 'UNIT_THRESHOLD' and not threshold:
            raise forms.ValidationError({
                'units_per_visit_threshold': 'This field is required when using Unit Threshold mode.'
            })

        if approval_mode != 'UNIT_THRESHOLD' and threshold is not None:
            cleaned_data['units_per_visit_threshold'] = None

        if lot_walking_enabled:
            if not lot_walking_frequency:
                raise forms.ValidationError({
                    'lot_walking_frequency': 'Frequency is required when lot walking is enabled.'
                })

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.lot_walking_days = self.cleaned_data.get('lot_walking_days_choices', [])
        if commit:
            instance.save()
        return instance


@admin.register(CustomerRepairPreference)
class CustomerRepairPreferenceAdmin(CustomerTenantFilterMixin, admin.ModelAdmin):
    form = CustomerRepairPreferenceForm
    list_display = ['get_tenant_display', 'customer', 'field_repair_approval_mode', 'units_per_visit_threshold', 'invoice_preference', 'payment_terms', 'auto_email_invoices', 'lot_walking_enabled', 'updated_at']
    list_filter = ['field_repair_approval_mode', 'invoice_preference', 'auto_email_invoices', 'lot_walking_enabled', 'lot_walking_frequency', 'updated_at']
    search_fields = ['customer__name', 'customer__tenant__name']
    list_select_related = ['customer', 'customer__tenant']
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 25

    fieldsets = (
        ('Customer', {
            'fields': ('customer',)
        }),
        ('Field Repair Approval Settings', {
            'fields': ('field_repair_approval_mode', 'units_per_visit_threshold'),
            'description': 'Configure how field-discovered repairs should be handled for this customer.'
        }),
        ('Lot Walking Service Settings', {
            'fields': ('lot_walking_enabled', 'lot_walking_frequency', 'lot_walking_time', 'lot_walking_days_choices'),
            'description': 'Configure scheduled lot walking service for this customer.'
        }),
        ('Invoice Settings', {
            'fields': (
                'invoice_preference', 'billing_email', 'auto_email_invoices', 'include_photos_in_invoice',
                'payment_terms', 'batch_invoice_day',
            ),
            'description': (
                'Configure how invoices should be generated and delivered for this customer. '
                '"Per repair" = auto-generate when each repair completes. '
                '"Batch" = group repairs together (manual trigger). '
                '"Manual" = never auto-generate. '
                '"Payment Terms" overrides the shop default for this customer (blank = use shop default). '
                '"Batch Invoice Day" overrides the monthly batch day for this customer (blank = use shop default).'
            )
        }),
        ('Tracking', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CustomerInvitation)
class CustomerInvitationAdmin(CustomerTenantFilterMixin, admin.ModelAdmin):
    list_display = ['get_tenant_display', 'email', 'customer', 'status', 'created_at', 'expires_at', 'sent_at']
    list_filter = ['status', 'created_at']
    search_fields = ['email', 'customer__name', 'first_name', 'last_name', 'customer__tenant__name']
    readonly_fields = ['token', 'created_at', 'sent_at', 'accepted_at', 'accepted_user']
    # customer and invited_by have search_fields on their target admins → use autocomplete
    autocomplete_fields = ['customer', 'invited_by']
    raw_id_fields = ['accepted_user']  # User is rarely searched by accepted_user context
    ordering = ['-created_at']
    list_select_related = ['customer', 'customer__tenant']
    list_per_page = 25

    fieldsets = (
        ('Invitation Details', {
            'fields': ('customer', 'email', 'first_name', 'last_name', 'status')
        }),
        ('Token & Expiry', {
            'fields': ('token', 'expires_at'),
        }),
        ('Tracking', {
            'fields': ('invited_by', 'created_at', 'sent_at', 'accepted_at', 'accepted_user'),
            'classes': ('collapse',)
        }),
    )
