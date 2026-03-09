from django.contrib import admin
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.utils.html import format_html
from django import forms
from .models import Technician, Repair, Replacement, UnitRepairCount, Customer, ViscosityRecommendation

class TechnicianAdmin(admin.ModelAdmin):
    list_display = ['user', 'get_email', 'get_full_name', 'phone_number', 'expertise', 'is_manager', 'is_active', 'repairs_completed']
    list_filter = ['expertise', 'is_manager', 'is_active', 'can_assign_work', 'can_override_pricing']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name', 'phone_number']
    list_select_related = ['user']
    filter_horizontal = ['managed_technicians']

    def get_form(self, request, obj=None, **kwargs):
        """Customize form based on manager status"""
        form = super().get_form(request, obj, **kwargs)

        # If editing an existing non-manager, hide managed_technicians field
        if obj and not obj.is_manager:
            if 'managed_technicians' in form.base_fields:
                form.base_fields['managed_technicians'].widget = forms.HiddenInput()

        # For managers, show only active technicians (exclude self)
        if 'managed_technicians' in form.base_fields:
            queryset = Technician.objects.filter(is_active=True).order_by('user__first_name')
            if obj:
                # Exclude self from managed_technicians options
                queryset = queryset.exclude(id=obj.id)
            form.base_fields['managed_technicians'].queryset = queryset
            # Use FilteredSelectMultiple for better UX with many technicians
            form.base_fields['managed_technicians'].widget = FilteredSelectMultiple('Managed Technicians', False)

        return form

    def save_model(self, request, obj, form, change):
        """Validate and save technician, clearing managed_technicians for non-managers"""
        # Save first to ensure object has a pk for M2M access
        super().save_model(request, obj, form, change)

        # Clear managed technicians for non-managers (must happen after save)
        if not obj.is_manager:
            obj.managed_technicians.clear()

    def get_email(self, obj):
        return obj.user.email
    get_email.short_description = 'Email'
    get_email.admin_order_field = 'user__email'

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
    get_full_name.short_description = 'Full Name'
    get_full_name.admin_order_field = 'user__first_name'

    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'phone_number', 'expertise', 'is_active')
        }),
        ('Manager Capabilities', {
            'fields': ('is_manager', 'approval_limit', 'can_assign_work', 'can_override_pricing', 'managed_technicians'),
            'description': 'Configure manager-level permissions and responsibilities.'
        }),
        ('Performance Metrics', {
            'fields': ('repairs_completed', 'average_repair_time', 'customer_rating'),
            'classes': ('collapse',),
            'description': 'Performance tracking data (automatically updated).'
        }),
        ('Schedule & Availability', {
            'fields': ('working_hours',),
            'classes': ('collapse',),
            'description': 'Working hours in JSON format: {"monday": ["9:00", "17:00"], ...}'
        }),
    )
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('register-technician/', self.register_technician_view, name='register-technician'),
        ]
        return custom_urls + urls
    
    def register_technician_view(self, request):
        # This is a placeholder for your registration view
        return render(request, 'admin/register_technician.html', {})

class RepairAdmin(admin.ModelAdmin):
    list_display = ['id', 'tenant', 'customer', 'unit_number', 'technician', 'get_status_badge', 'get_price_display', 'service_date']
    list_filter = ['tenant', 'queue_status', 'service_date', 'technician']
    search_fields = ['customer__name', 'unit_number', 'damage_type', 'technician__user__username', 'tenant__name']
    readonly_fields = ['service_date']
    date_hierarchy = 'service_date'
    list_select_related = ['customer', 'technician', 'technician__user']
    
    def get_status_badge(self, obj):
        status_colors = {
            'REQUESTED': 'bg-secondary',
            'PENDING': 'bg-warning',
            'APPROVED': 'bg-info',
            'IN_PROGRESS': 'bg-primary',
            'COMPLETED': 'bg-success',
            'DENIED': 'bg-danger'
        }
        color = status_colors.get(obj.queue_status, 'bg-secondary')
        return format_html('<span class="badge {}">{}</span>', color, obj.get_queue_status_display())
    get_status_badge.short_description = 'Status'
    get_status_badge.admin_order_field = 'queue_status'

    def get_price_display(self, obj):
        if obj.has_price_override():
            return format_html(
                '<span style="color: #ff6b6b;" title="Manual override: {}">${} ⚠️</span>',
                obj.override_reason or "No reason provided",
                f"{obj.cost:.2f}"
            )
        return f"${obj.cost:.2f}"
    get_price_display.short_description = 'Price'
    get_price_display.admin_order_field = 'cost'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('technician', 'customer', 'unit_number', 'service_date')
        }),
        ('Repair Details', {
            'fields': ('damage_type', 'description', 'queue_status')
        }),
        ('Pricing', {
            'fields': ('cost', 'cost_override', 'override_reason'),
            'description': 'Cost is normally calculated automatically based on repair count. Admins can manually adjust the cost field directly, or use override fields to document custom pricing with a reason.'
        }),
        ('Technical Data', {
            'fields': ('drilled_before_repair', 'windshield_temperature', 'resin_viscosity'),
            'classes': ('collapse',),
        }),
    )


class ReplacementAdmin(admin.ModelAdmin):
    list_display = ['id', 'tenant', 'customer', 'unit_number', 'glass_position', 'technician', 'get_status_badge', 'get_price_display', 'service_date']
    list_filter = ['tenant', 'queue_status', 'service_date', 'technician', 'glass_position', 'requires_adas_calibration']
    search_fields = ['customer__name', 'unit_number', 'nags_number', 'technician__user__username', 'tenant__name']
    readonly_fields = ['service_date']
    date_hierarchy = 'service_date'
    list_select_related = ['customer', 'technician', 'technician__user']
    
    def get_status_badge(self, obj):
        status_colors = {
            'REQUESTED': 'bg-secondary',
            'PENDING': 'bg-warning',
            'APPROVED': 'bg-info',
            'IN_PROGRESS': 'bg-primary',
            'COMPLETED': 'bg-success',
            'DENIED': 'bg-danger'
        }
        color = status_colors.get(obj.queue_status, 'bg-secondary')
        return format_html('<span class="badge {}">{}</span>', color, obj.get_queue_status_display())
    get_status_badge.short_description = 'Status'
    get_status_badge.admin_order_field = 'queue_status'

    def get_price_display(self, obj):
        if obj.has_price_override():
            return format_html(
                '<span style="color: #ff6b6b;" title="Manual override: {}">${} ⚠️</span>',
                obj.override_reason or "No reason provided",
                f"{obj.cost:.2f}"
            )
        return f"${obj.cost:.2f}"
    get_price_display.short_description = 'Price'
    get_price_display.admin_order_field = 'cost'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('technician', 'customer', 'unit_number', 'service_date')
        }),
        ('Replacement Details', {
            'fields': ('glass_position', 'glass_type', 'nags_number', 'description', 'queue_status')
        }),
        ('Pricing', {
            'fields': ('parts_cost', 'labor_cost', 'requires_adas_calibration', 'adas_calibration_cost', 'cost', 'cost_override', 'override_reason'),
            'description': 'Cost is calculated from parts + labor + ADAS. Admins can manually override.'
        }),
        ('Insurance', {
            'fields': ('insurance_claim', 'insurance_company', 'claim_number', 'deductible', 'authorization_number'),
            'classes': ('collapse',),
        }),
    )


class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'tenant', 'email', 'phone', 'address', 'tax_exempt', 'get_primary_contact']
    search_fields = ['name', 'email', 'phone', 'tenant__name']
    list_filter = ['tenant', 'customer_type', 'tax_exempt']
    
    def get_primary_contact(self, obj):
        from apps.customer_portal.models import CustomerUser
        try:
            primary = CustomerUser.objects.filter(customer=obj, is_primary_contact=True).first()
            if primary:
                return f"{primary.user.get_full_name()} ({primary.user.email})"
            return "No primary contact"
        except:
            return "Error retrieving contact"
    get_primary_contact.short_description = 'Primary Contact'

class UnitRepairCountAdmin(admin.ModelAdmin):
    list_display = ['customer', 'unit_number', 'repair_count']
    list_filter = ['customer']
    search_fields = ['customer__name', 'unit_number']

class ViscosityRecommendationAdmin(admin.ModelAdmin):
    list_display = ['name', 'get_temp_range_display', 'recommended_viscosity', 'get_badge_preview', 'display_order', 'is_active']
    list_filter = ['badge_color', 'is_active']
    search_fields = ['name', 'recommended_viscosity', 'suggestion_text']
    list_editable = ['display_order', 'is_active']
    ordering = ['display_order', 'id']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'is_active', 'display_order'),
            'description': 'Give this rule a descriptive name and set its priority (lower number = higher priority)'
        }),
        ('Temperature Range', {
            'fields': ('min_temperature', 'max_temperature'),
            'description': 'Set the temperature range in °F. Leave blank for no limit (e.g., blank min = applies to all temps below max)'
        }),
        ('Recommendation', {
            'fields': ('recommended_viscosity', 'suggestion_text', 'badge_color'),
            'description': 'Configure what viscosity to recommend and the message technicians will see'
        }),
    )

    def get_temp_range_display(self, obj):
        """Display temperature range in a readable format"""
        return obj._get_temp_range_display()
    get_temp_range_display.short_description = 'Temperature Range'

    def get_badge_preview(self, obj):
        """Show a preview of the badge color"""
        color_map = {
            'blue': '#1e40af',
            'green': '#065f46',
            'orange': '#9a3412',
            'red': '#991b1b',
            'yellow': '#92400e',
            'purple': '#6b21a8',
        }
        bg_color_map = {
            'blue': '#dbeafe',
            'green': '#d1fae5',
            'orange': '#fed7aa',
            'red': '#fee2e2',
            'yellow': '#fef3c7',
            'purple': '#e9d5ff',
        }
        color = color_map.get(obj.badge_color, '#4b5563')
        bg = bg_color_map.get(obj.badge_color, '#f3f4f6')

        return format_html(
            '<span style="display: inline-block; padding: 4px 12px; background-color: {}; color: {}; border-radius: 4px; font-size: 12px; font-weight: 500;">{}</span>',
            bg, color, obj.recommended_viscosity
        )
    get_badge_preview.short_description = 'Badge Preview'

    def save_model(self, request, obj, form, change):
        """Add helpful validation messages"""
        super().save_model(request, obj, form, change)
        if not change:  # New object
            self.message_user(request, f'Created viscosity rule: {obj.name}', level='success')

# Register the models
admin.site.register(Technician, TechnicianAdmin)
admin.site.register(Repair, RepairAdmin)
admin.site.register(Replacement, ReplacementAdmin)
admin.site.register(UnitRepairCount, UnitRepairCountAdmin)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(ViscosityRecommendation, ViscosityRecommendationAdmin)
