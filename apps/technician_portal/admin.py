import csv

from django.contrib import admin
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db.models import Prefetch
from django.http import HttpResponse
from django.urls import path
from django.shortcuts import render
from django.contrib.auth.models import User
from django.utils.html import format_html
from django import forms
from .models import Technician, Repair, Replacement, UnitRepairCount, Customer, ViscosityRecommendation, TechnicianNotification
from rs_systems.admin_mixins import TenantFilterMixin


@admin.register(Technician)
class TechnicianAdmin(TenantFilterMixin, admin.ModelAdmin):
    list_display = ['user', 'tenant', 'get_email', 'get_full_name', 'phone_number', 'expertise', 'is_manager', 'is_active', 'repairs_completed']
    list_filter = ['tenant', 'expertise', 'is_manager', 'is_active', 'can_assign_work', 'can_override_pricing']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name', 'phone_number']
    list_select_related = ['user', 'tenant']  # 'tenant' prevents N+1 when rendering list_display
    filter_horizontal = ['managed_technicians']
    list_per_page = 25

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and not obj.is_manager:
            if 'managed_technicians' in form.base_fields:
                form.base_fields['managed_technicians'].widget = forms.HiddenInput()
        if 'managed_technicians' in form.base_fields:
            # Always filter managed_technicians to the same tenant as the manager
            # being edited. This prevents cross-tenant tech assignment via the
            # admin M2M picker, even for superusers.
            queryset = Technician.objects.filter(is_active=True).order_by('user__first_name')
            if obj:
                queryset = queryset.exclude(id=obj.id)
                if obj.tenant_id:
                    queryset = queryset.filter(tenant=obj.tenant)
            form.base_fields['managed_technicians'].queryset = queryset
            form.base_fields['managed_technicians'].widget = FilteredSelectMultiple('Managed Technicians', False)
        return form

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.is_manager:
            obj.managed_technicians.clear()

    def save_related(self, request, form, formsets, change):
        """After M2M relations are written, enforce same-tenant constraint."""
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if obj.is_manager:
            try:
                obj.validate_managed_technicians()
            except Exception:
                # validate_managed_technicians removes cross-tenant techs and
                # raises ValidationError — we silently absorb it here because
                # the admin message framework isn't easily accessible in
                # save_related; the invalid techs are already removed.
                pass

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
        return render(request, 'admin/register_technician.html', {})


@admin.register(Repair)
class RepairAdmin(TenantFilterMixin, admin.ModelAdmin):
    list_display = ['id', 'tenant', 'customer', 'unit_number', 'technician', 'get_status_badge', 'get_price_display', 'service_date']
    list_filter = ['tenant', 'queue_status', 'service_date', 'technician']
    search_fields = ['customer__name', 'unit_number', 'damage_type', 'technician__user__username', 'tenant__name']
    readonly_fields = ['service_date']
    date_hierarchy = 'service_date'
    list_select_related = ['customer', 'technician', 'technician__user', 'tenant']
    list_per_page = 25
    actions = ['export_csv', 'bulk_delete_repairs']

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

    @admin.action(description='📥 Export selected repairs as CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="repairs.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Tenant', 'Customer', 'Unit #', 'Technician',
            'Status', 'Damage Type', 'Cost', 'Service Date',
        ])
        for repair in queryset.select_related('customer', 'technician__user', 'tenant'):
            writer.writerow([
                repair.id,
                repair.tenant.name if repair.tenant else '',
                repair.customer.name if repair.customer else '',
                repair.unit_number,
                repair.technician.user.get_full_name() if repair.technician else '',
                repair.get_queue_status_display(),
                repair.damage_type,
                repair.cost,
                repair.service_date,
            ])
        return response

    @admin.action(description='🗑️ Bulk delete selected repairs (hard delete)')
    def bulk_delete_repairs(self, request, queryset):
        """
        Hard-delete selected repairs.

        This bypasses Django's default soft-delete manager because we're in the
        admin and superusers sometimes need to permanently remove test or bad data.
        Invoiced repairs (linked to InvoiceLineItems on active invoices) are skipped
        to avoid orphaning billing records.

        IMPORTANT: For each COMPLETED repair deleted, we must decrement the
        UnitRepairCount.repair_count for that (tenant, customer, unit_number) tuple.
        Without this, future repairs to that unit are priced as though the deleted
        repairs still happened — giving incorrect progressive pricing discounts.
        (CODE-161)
        """
        from apps.billing.models import InvoiceLineItem
        from collections import defaultdict

        invoiced_ids = set(
            InvoiceLineItem.objects
            .filter(repair__in=queryset, invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID'])
            .values_list('repair_id', flat=True)
        )
        safe_to_delete = queryset.exclude(id__in=invoiced_ids)

        # Before deletion, tally how many COMPLETED repairs we're removing per
        # (tenant, customer, unit_number) so we can decrement UnitRepairCount.
        # Only COMPLETED repairs incremented the count (see Repair.save() logic),
        # and only when progressive pricing was active (non-retail, use_progressive=True).
        # We conservatively decrement for any deleted COMPLETED repair to avoid
        # leaving inflated counts that produce incorrect future pricing.
        completed_repairs = (
            safe_to_delete
            .filter(queue_status='COMPLETED')
            .select_related('tenant', 'customer')
            .values('tenant_id', 'customer_id', 'unit_number')
        )
        decrement_map = defaultdict(int)
        for r in completed_repairs:
            key = (r['tenant_id'], r['customer_id'], r['unit_number'])
            decrement_map[key] += 1

        deleted_count = safe_to_delete.count()
        skipped_count = len(invoiced_ids)

        safe_to_delete.delete()

        # Decrement UnitRepairCount for all affected (tenant, customer, unit) combos.
        # Clamp at 0 to avoid negative counts.
        for (tenant_id, customer_id, unit_number), count in decrement_map.items():
            try:
                urc = UnitRepairCount.objects.get(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    unit_number=unit_number,
                )
                urc.repair_count = max(0, urc.repair_count - count)
                urc.save(update_fields=['repair_count'])
            except UnitRepairCount.DoesNotExist:
                pass  # Already missing — nothing to decrement

        msg = f'✅ Deleted {deleted_count} repair(s).'
        if skipped_count:
            msg += f' ⚠️ {skipped_count} repair(s) skipped — linked to active invoices.'
        self.message_user(request, msg)

    def delete_queryset(self, request, queryset):
        """
        Override the default admin 'Delete selected' action so it applies the
        same safety logic as bulk_delete_repairs:

          1. Skip repairs linked to active invoices (DRAFT/SENT/PARTIAL/PAID)
             to avoid orphaning billing records.
          2. Decrement UnitRepairCount for each COMPLETED repair deleted, so
             future repairs to that unit are priced correctly.

        Without this override, Django's default QuerySet.delete() would:
          - Delete invoiced repairs (data-integrity violation)
          - Leave UnitRepairCount inflated (progressive-pricing bug, CODE-161)

        (CODE-167)
        """
        from apps.billing.models import InvoiceLineItem
        from collections import defaultdict

        invoiced_ids = set(
            InvoiceLineItem.objects
            .filter(repair__in=queryset, invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID'])
            .values_list('repair_id', flat=True)
        )
        safe_to_delete = queryset.exclude(id__in=invoiced_ids)

        # Tally COMPLETED repairs to decrement UnitRepairCount after deletion.
        completed_repairs = (
            safe_to_delete
            .filter(queue_status='COMPLETED')
            .select_related('tenant', 'customer')
            .values('tenant_id', 'customer_id', 'unit_number')
        )
        decrement_map = defaultdict(int)
        for r in completed_repairs:
            key = (r['tenant_id'], r['customer_id'], r['unit_number'])
            decrement_map[key] += 1

        safe_to_delete.delete()

        # Decrement UnitRepairCount, clamped at 0.
        for (tenant_id, customer_id, unit_number), count in decrement_map.items():
            try:
                urc = UnitRepairCount.objects.get(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    unit_number=unit_number,
                )
                urc.repair_count = max(0, urc.repair_count - count)
                urc.save(update_fields=['repair_count'])
            except UnitRepairCount.DoesNotExist:
                pass


@admin.register(Replacement)
class ReplacementAdmin(TenantFilterMixin, admin.ModelAdmin):
    list_display = ['id', 'tenant', 'customer', 'unit_number', 'glass_position', 'technician', 'get_status_badge', 'get_price_display', 'service_date']
    list_filter = ['tenant', 'queue_status', 'service_date', 'technician', 'glass_position', 'requires_adas_calibration']
    search_fields = ['customer__name', 'unit_number', 'nags_number', 'technician__user__username', 'tenant__name']
    readonly_fields = ['service_date']
    date_hierarchy = 'service_date'
    list_select_related = ['customer', 'technician', 'technician__user', 'tenant']
    list_per_page = 25

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


@admin.register(Customer)
class CustomerAdmin(TenantFilterMixin, admin.ModelAdmin):
    list_display = ['name', 'tenant', 'email', 'phone', 'address', 'tax_exempt', 'get_primary_contact']
    search_fields = ['name', 'email', 'phone', 'tenant__name']
    list_filter = ['tenant', 'customer_type', 'tax_exempt']
    list_select_related = ['tenant']
    list_per_page = 25
    actions = ['export_csv', 'generate_invoices']

    def get_queryset(self, request):
        """
        Prefetch primary CustomerUser contacts to avoid an N+1 query in
        get_primary_contact().  Without this, every row in the changelist
        issues its own SELECT against customeruser; with 25-50 customers per
        page that's 25-50 extra round-trips.
        """
        from apps.customer_portal.models import CustomerUser
        qs = super().get_queryset(request)
        primary_contact_qs = (
            CustomerUser.objects
            .filter(is_primary_contact=True)
            .select_related('user')
        )
        return qs.prefetch_related(
            Prefetch(
                'customeruser_set',
                queryset=primary_contact_qs,
                to_attr='_primary_contacts',
            )
        )

    def get_primary_contact(self, obj):
        """Return the primary contact name/email, using the prefetched cache."""
        try:
            # _primary_contacts is populated by get_queryset()'s Prefetch;
            # fall back to a live query only if the attribute is somehow absent.
            if hasattr(obj, '_primary_contacts'):
                contacts = obj._primary_contacts
            else:
                from apps.customer_portal.models import CustomerUser
                contacts = list(
                    CustomerUser.objects.filter(
                        customer=obj, is_primary_contact=True
                    ).select_related('user')
                )
            if contacts:
                primary = contacts[0]
                return f"{primary.user.get_full_name()} ({primary.user.email})"
            return "No primary contact"
        except Exception:
            return "Error retrieving contact"
    get_primary_contact.short_description = 'Primary Contact'

    @admin.action(description='📥 Export selected customers as CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="customers.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Name', 'Tenant', 'Email', 'Phone', 'Address',
            'Customer Type', 'Tax Exempt',
        ])
        for customer in queryset.select_related('tenant'):
            writer.writerow([
                customer.id,
                customer.name,
                customer.tenant.name if customer.tenant else '',
                customer.email,
                customer.phone,
                customer.address,
                getattr(customer, 'customer_type', ''),
                customer.tax_exempt,
            ])
        return response

    @admin.action(description='🧾 Generate draft invoices for selected customers')
    def generate_invoices(self, request, queryset):
        """
        For each selected customer, find completed repairs not yet on any invoice
        and create a single DRAFT invoice containing all of them.

        Delegates to InvoiceTrackingService.create_invoice_from_repairs() so
        that discounts (reward redemptions) and tax (TaxService) are applied
        correctly — matching the normal billing flow.  The previous inline
        implementation hardcoded tax_rate=0, tax_amount=0 and skipped
        get_discounted_cost(), so admin-generated invoices always had $0 tax
        and wrong totals for customers with reward discounts. (CODE-121)
        """
        from apps.billing.models import InvoiceLineItem
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        from apps.technician_portal.models import Repair

        invoices_created = 0
        repairs_billed = 0
        skipped = 0
        errors = 0

        for customer in queryset.select_related('tenant'):
            # Find completed repairs not yet on any active (non-cancelled) invoice.
            # We intentionally do NOT exclude repairs linked to CANCELLED invoices —
            # those repairs should be re-invoiceable.
            # We also skip repairs flagged as skip_invoicing (already accounted for
            # outside the normal billing flow).
            invoiced_repair_ids = InvoiceLineItem.objects.filter(
                repair__isnull=False,
                invoice__tenant=customer.tenant,
                invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID'],
            ).values_list('repair_id', flat=True)

            unbilled_repairs = list(
                Repair.objects
                .filter(customer=customer, queue_status='COMPLETED', skip_invoicing=False)
                .exclude(id__in=invoiced_repair_ids)
                .order_by('service_date')
            )

            if not unbilled_repairs:
                skipped += 1
                continue

            try:
                # InvoiceTrackingService handles:
                #   - invoice number generation (race-condition-safe loop)
                #   - payment terms from BillingConfig
                #   - get_discounted_cost() for reward-based line-item discounts
                #   - TaxService for correct tax_rate / tax_amount / component fields
                #   - atomic creation of invoice + line items
                svc = InvoiceTrackingService(tenant=customer.tenant)
                invoice = svc.create_invoice_from_repairs(
                    customer=customer,
                    repairs=unbilled_repairs,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    f"Admin generate_invoices: failed for customer {customer.id} "
                    f"({customer.name}): {e}"
                )
                errors += 1
                continue

            repairs_billed += len(unbilled_repairs)
            invoices_created += 1

        if invoices_created:
            msg = (
                f"✅ Created {invoices_created} draft invoice(s) covering {repairs_billed} repair(s). "
                f"{skipped} customer(s) had no unbilled completed repairs."
            )
            if errors:
                msg += f" ⚠️ {errors} customer(s) failed — check server logs."
            self.message_user(request, msg, level='success')
        else:
            msg = f"No new invoices created — {skipped} customer(s) had no unbilled completed repairs."
            if errors:
                msg += f" ⚠️ {errors} customer(s) failed — check server logs."
            self.message_user(request, msg, level='warning')


@admin.register(UnitRepairCount)
class UnitRepairCountAdmin(TenantFilterMixin, admin.ModelAdmin):
    list_display = ['tenant', 'customer', 'unit_number', 'repair_count']
    list_filter = ['tenant', 'customer']
    search_fields = ['customer__name', 'unit_number', 'tenant__name']
    list_select_related = ['tenant', 'customer']
    list_per_page = 25


@admin.register(ViscosityRecommendation)
class ViscosityRecommendationAdmin(TenantFilterMixin, admin.ModelAdmin):
    list_display = ['tenant', 'name', 'get_temp_range_display', 'recommended_viscosity', 'get_badge_preview', 'display_order', 'is_active']
    list_filter = ['tenant', 'badge_color', 'is_active']
    search_fields = ['name', 'recommended_viscosity', 'suggestion_text', 'tenant__name']
    list_editable = ['display_order', 'is_active']
    ordering = ['tenant', 'display_order', 'id']
    list_select_related = ['tenant']
    list_per_page = 25

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'is_active', 'display_order'),
            'description': 'Give this rule a descriptive name and set its priority (lower number = higher priority)'
        }),
        ('Temperature Range', {
            'fields': ('min_temperature', 'max_temperature'),
            'description': 'Set the temperature range in °F. Leave blank for no limit.'
        }),
        ('Recommendation', {
            'fields': ('recommended_viscosity', 'suggestion_text', 'badge_color'),
            'description': 'Configure what viscosity to recommend and the message technicians will see'
        }),
    )

    def get_temp_range_display(self, obj):
        return obj._get_temp_range_display()
    get_temp_range_display.short_description = 'Temperature Range'

    def get_badge_preview(self, obj):
        color_map = {
            'blue': '#1e40af', 'green': '#065f46', 'orange': '#9a3412',
            'red': '#991b1b', 'yellow': '#92400e', 'purple': '#6b21a8',
        }
        bg_color_map = {
            'blue': '#dbeafe', 'green': '#d1fae5', 'orange': '#fed7aa',
            'red': '#fee2e2', 'yellow': '#fef3c7', 'purple': '#e9d5ff',
        }
        color = color_map.get(obj.badge_color, '#4b5563')
        bg = bg_color_map.get(obj.badge_color, '#f3f4f6')
        return format_html(
            '<span style="display: inline-block; padding: 4px 12px; background-color: {}; color: {}; border-radius: 4px; font-size: 12px; font-weight: 500;">{}</span>',
            bg, color, obj.recommended_viscosity
        )
    get_badge_preview.short_description = 'Badge Preview'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            self.message_user(request, f'Created viscosity rule: {obj.name}', level='success')


# =============================================================================
# TECHNICIAN NOTIFICATIONS (Debugging / Audit)
# =============================================================================

class TechnicianTenantFilterMixin:
    """
    Mixin for models that reach tenant through technician → tenant.
    TechnicianNotification has no direct tenant FK but is scoped
    via technician → tenant.
    """

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
        return qs.filter(technician__tenant__in=tenant_ids)

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if request.user.is_superuser and 'technician__tenant' not in filters:
            filters = ['technician__tenant'] + filters
        return filters


@admin.register(TechnicianNotification)
class TechnicianNotificationAdmin(TechnicianTenantFilterMixin, admin.ModelAdmin):
    """
    Read-only admin for in-app technician notifications.

    Useful for debugging notification delivery issues, auditing what
    messages were sent, and bulk-clearing stale unread notifications.
    Notifications are created programmatically — add is disabled.
    """
    list_display = [
        'id', 'get_tenant', 'technician', 'message_preview',
        'read', 'get_notification_type', 'created_at',
    ]
    list_filter = ['read', 'created_at']
    search_fields = ['technician__user__username', 'technician__user__email', 'message']
    readonly_fields = [
        'technician', 'message', 'read', 'created_at',
        'redemption', 'repair', 'repair_batch_id',
    ]
    date_hierarchy = 'created_at'
    list_select_related = ['technician', 'technician__user', 'technician__tenant']
    list_per_page = 50
    ordering = ['-created_at']
    actions = ['mark_as_read', 'mark_as_unread']

    def has_add_permission(self, request):
        # Notifications are created by business logic, not manually.
        return False

    def has_change_permission(self, request, obj=None):
        # Content is immutable — only read/unread status via actions.
        return False

    def get_tenant(self, obj):
        try:
            return obj.technician.tenant.name
        except AttributeError:
            return '—'
    get_tenant.short_description = 'Tenant'
    get_tenant.admin_order_field = 'technician__tenant__name'

    def message_preview(self, obj):
        """Truncate long messages for the list view."""
        if len(obj.message) > 80:
            return obj.message[:80] + '…'
        return obj.message
    message_preview.short_description = 'Message'

    def get_notification_type(self, obj):
        """Show what kind of notification this is (batch / repair / reward / general)."""
        if obj.repair_batch_id:
            return '📦 Batch'
        if obj.repair_id:
            return '🔧 Repair'
        if obj.redemption_id:
            return '🎁 Reward'
        return '📣 General'
    get_notification_type.short_description = 'Type'

    @admin.action(description='✅ Mark selected notifications as read')
    def mark_as_read(self, request, queryset):
        updated = queryset.filter(read=False).update(read=True)
        self.message_user(request, f'✅ {updated} notification(s) marked as read.')

    @admin.action(description='🔔 Mark selected notifications as unread')
    def mark_as_unread(self, request, queryset):
        updated = queryset.filter(read=True).update(read=False)
        self.message_user(request, f'🔔 {updated} notification(s) marked as unread.')
