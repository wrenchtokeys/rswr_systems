"""
Billing Admin - Invoice and Payment management

Provides admin interfaces for:
- Billing configuration (company address, payment terms)
- Viewing and managing invoices
- Recording payments
- Tracking outstanding balances

Author: Amelia (Clawdbot AI)
"""

import csv

from django.contrib import admin, messages
from django.db.models import Count
from django.http import HttpResponse
from django.utils.html import format_html
from django.urls import reverse
from decimal import Decimal


def _csv_safe(value):
    """
    Neutralise CSV formula injection.

    Spreadsheet applications treat a cell value as a formula when it starts
    with '=', '+', '-', or '@'.  Prefix such strings with a single-quote (')
    to force text mode.  Mirrors the same helper in technician_portal/admin.py
    and saas/views.py (CODE-214).
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value

from .models import BillingConfig, Invoice, InvoiceLineItem, Payment, TaxRate, PlatformConfig, PlatformFeeRecord
from rs_systems.admin_mixins import TenantFilterMixin


# =============================================================================
# BILLING CONFIGURATION (Per-Tenant)
# =============================================================================

@admin.register(BillingConfig)
class BillingConfigAdmin(TenantFilterMixin, admin.ModelAdmin):
    """
    Per-tenant billing settings — company address, payment terms, invoice defaults.
    Superusers see all tenants' configs. Non-superusers only see their own tenant's config.
    """

    fieldsets = (
        ('Tenant', {
            'fields': ('tenant',),
        }),
        ('Company Information (shown on invoices)', {
            'fields': (
                'company_name',
                'company_address', 'company_city', 'company_state', 'company_zip',
                'company_phone', 'company_email', 'company_website',
            ),
        }),
        ('Default Payment Terms', {
            'fields': ('default_payment_terms', 'default_due_days'),
            'description': (
                'These defaults apply to new invoices. COD = Cash on Delivery (due immediately). '
                'NET30 = 30 days to pay, etc.'
            ),
        }),
        ('Invoice Defaults', {
            'fields': ('invoice_footer_note', 'invoice_number_prefix'),
        }),
        ('Sales Tax', {
            'fields': ('tax_enabled', 'default_tax_rate'),
            'description': (
                'Enable sales tax calculation on invoices. When enabled, tax is looked up by '
                'customer city/state from the Tax Rates table. The default rate is used as a '
                'fallback if no city match is found.'
            ),
        }),
    )

    list_display = ['tenant', 'company_name', 'default_payment_terms', 'updated_at']
    list_select_related = ['tenant']

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Non-superusers only see their own tenant's config
        tenant = getattr(request, 'tenant', None)
        if tenant:
            return qs.filter(tenant=tenant)
        return qs.none()

    def has_add_permission(self, request):
        # Superusers can always add; non-superusers can add only if their tenant lacks a config
        if request.user.is_superuser:
            return True
        tenant = getattr(request, 'tenant', None)
        if tenant:
            return not BillingConfig.objects.filter(tenant=tenant).exists()
        return False


# =============================================================================
# INVOICES
# =============================================================================


class InvoiceLineItemInline(admin.TabularInline):
    """Inline display of line items on invoice.

    repair_date and unit_number are stored on the line item itself (denormalized
    from the linked repair at creation time) so they persist even if the repair
    is edited later.  They were listed in readonly_fields but NOT in fields,
    which meant Django never rendered them in the tabular inline — admins had no
    way to see which date/unit a line item corresponded to without clicking
    through to the repair.  Added to fields so they actually appear.  (CODE-197)
    """
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ['repair_link', 'repair_date', 'unit_number']
    fields = ['description', 'unit_number', 'repair_date', 'quantity', 'unit_price', 'discount', 'amount', 'repair_link']
    
    def repair_link(self, obj):
        if obj.repair:
            url = reverse('admin:technician_portal_repair_change', args=[obj.repair.id])
            return format_html('<a href="{}">Repair #{}</a>', url, obj.repair.id)
        return '-'
    repair_link.short_description = 'Repair'


class PaymentInline(admin.TabularInline):
    """Inline display of payments on invoice."""
    model = Payment
    extra = 0
    readonly_fields = ['created_at']
    fields = ['amount', 'payment_date', 'payment_method', 'reference_number', 'notes']


@admin.register(Invoice)
class InvoiceAdmin(TenantFilterMixin, admin.ModelAdmin):
    """Admin for Invoice model."""
    
    list_display = [
        'invoice_number', 'get_tenant', 'customer_link', 'invoice_date', 'due_date',
        'payment_terms',
        'total_display', 'amount_paid_display', 'amount_due_display', 
        'status_badge', 'line_item_count'
    ]
    list_filter = ['tenant', 'status', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'customer__name']
    date_hierarchy = 'invoice_date'
    list_select_related = ['customer', 'tenant']
    list_per_page = 25
    readonly_fields = [
        'invoice_number', 'created_at', 'updated_at', 'amount_paid', 
        'sent_at', 'paid_at'
    ]
    
    fieldsets = (
        ('Invoice Details', {
            'fields': ('invoice_number', 'customer', 'status', 'payment_terms')
        }),
        ('Dates', {
            'fields': ('invoice_date', 'due_date', 'sent_at', 'paid_at')
        }),
        ('Amounts', {
            'fields': ('subtotal', 'discount', 'tax_rate', 'tax_amount', 'total', 'amount_paid')
        }),
        ('Storage & Integration', {
            'fields': ('s3_key', 'stripe_invoice_id', 'stripe_hosted_url'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes', 'internal_notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [InvoiceLineItemInline, PaymentInline]

    def get_queryset(self, request):
        """Annotate each invoice with line_items_count to avoid N+1 queries."""
        qs = super().get_queryset(request)
        return qs.annotate(_line_items_count=Count('line_items'))

    def get_tenant(self, obj):
        return obj.tenant.name if obj.tenant else '—'
    get_tenant.short_description = 'Tenant'
    get_tenant.admin_order_field = 'tenant__name'

    def customer_link(self, obj):
        url = reverse('admin:core_customer_change', args=[obj.customer.id])
        return format_html('<a href="{}">{}</a>', url, obj.customer.name)
    customer_link.short_description = 'Customer'
    customer_link.admin_order_field = 'customer__name'
    
    def total_display(self, obj):
        return f"${obj.total:,.2f}"
    total_display.short_description = 'Total'
    total_display.admin_order_field = 'total'
    
    def amount_paid_display(self, obj):
        return f"${obj.amount_paid:,.2f}"
    amount_paid_display.short_description = 'Paid'
    amount_paid_display.admin_order_field = 'amount_paid'
    
    def amount_due_display(self, obj):
        due = obj.amount_due
        if due > 0:
            # format_html wraps args with conditional_escape() before applying
            # format specs, converting Decimal → SafeString first, which makes
            # {:,.2f} fail with "Unknown format code 'f' for object of type
            # 'SafeString'".  Pre-format the number so format_html gets a plain
            # string to escape-and-insert. (CODE-076)
            return format_html('<span style="color: red;">${}</span>', f'{due:,.2f}')
        return format_html('<span style="color: green;">$0.00</span>')
    amount_due_display.short_description = 'Due'
    
    def status_badge(self, obj):
        colors = {
            'DRAFT': '#6c757d',
            'SENT': '#007bff',
            'PAID': '#28a745',
            'PARTIAL': '#ffc107',
            'OVERDUE': '#dc3545',
            'CANCELLED': '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'
    
    def line_item_count(self, obj):
        # Use the queryset annotation from get_queryset() to avoid an extra
        # COUNT query per invoice row (N+1 problem).
        # NOTE: getattr's default arg is always evaluated, so use hasattr instead.
        if hasattr(obj, '_line_items_count'):
            return obj._line_items_count
        return obj.line_items.count()
    line_item_count.short_description = 'Items'
    line_item_count.admin_order_field = '_line_items_count'
    
    actions = ['mark_as_sent', 'mark_as_overdue', 'bulk_mark_as_paid', 'bulk_void', 'bulk_delete_invoices', 'export_csv']

    @admin.action(description='📥 Export selected invoices as CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="invoices.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Invoice #', 'Customer', 'Invoice Date', 'Due Date',
            'Payment Terms', 'Status', 'Subtotal', 'Tax', 'Total',
            'Amount Paid', 'Amount Due',
        ])
        for inv in queryset.select_related('customer'):
            writer.writerow([
                _csv_safe(inv.invoice_number),
                _csv_safe(inv.customer.name if inv.customer else ''),
                inv.invoice_date,
                inv.due_date,
                _csv_safe(inv.payment_terms),
                inv.status,
                inv.subtotal,
                inv.tax_amount,
                inv.total,
                inv.amount_paid,
                inv.amount_due,
            ])
        return response

    @admin.action(description='Mark selected invoices as Sent')
    def mark_as_sent(self, request, queryset):
        updated = 0
        for invoice in queryset.filter(status='DRAFT'):
            invoice.mark_sent()
            updated += 1
        self.message_user(request, f'{updated} invoice(s) marked as sent.')
    
    @admin.action(description='Mark selected invoices as Overdue')
    def mark_as_overdue(self, request, queryset):
        updated = queryset.filter(
            status__in=['SENT', 'PARTIAL']
        ).update(status='OVERDUE')
        self.message_user(request, f'{updated} invoice(s) marked as overdue.')

    @admin.action(description='✅ Bulk mark selected invoices as Paid')
    def bulk_mark_as_paid(self, request, queryset):
        """
        Create a Payment record for each unpaid invoice so payment history and
        paid_at are correctly set.  Mirrors the logic in owner_invoice_bulk_action.
        """
        from django.utils import timezone as _tz
        from django.db import transaction

        payable = queryset.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE', 'DRAFT'])
        updated = 0
        for inv in payable:
            remaining = inv.amount_due
            if remaining <= 0:
                continue
            try:
                with transaction.atomic():
                    Payment.objects.create(
                        invoice=inv,
                        amount=remaining,
                        payment_method='OTHER',
                        notes='Bulk marked as paid via admin',
                        recorded_by=request.user,
                        payment_date=_tz.now().date(),
                    )
                updated += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Admin bulk_mark_as_paid: could not create payment for invoice {inv.id}: {e}"
                )
        self.message_user(request, f'✅ {updated} invoice(s) marked as paid.')

    @admin.action(description='🚫 Bulk void (cancel) selected invoices')
    def bulk_void(self, request, queryset):
        """
        Void invoices that aren't already PAID, CANCELLED, or PARTIAL.
        PARTIAL invoices are skipped — they have recorded payments that would be
        orphaned.  Owners must remove payments first.
        """
        voidable = queryset.exclude(status__in=['PAID', 'PARTIAL', 'CANCELLED'])
        voided = voidable.count()
        skipped_paid = queryset.filter(status__in=['PAID', 'CANCELLED']).count()
        skipped_partial = queryset.filter(status='PARTIAL').count()
        voidable.update(status='CANCELLED')
        msg = f'🚫 {voided} invoice(s) voided.'
        if skipped_paid:
            msg += f' {skipped_paid} already-paid/voided invoice(s) skipped.'
        if skipped_partial:
            msg += f' {skipped_partial} partially-paid invoice(s) skipped — remove payments first.'
        self.message_user(request, msg)

    @admin.action(description='🗑️ Bulk delete DRAFT and CANCELLED invoices')
    def bulk_delete_invoices(self, request, queryset):
        """
        Delete draft and voided (cancelled) invoices that have no payments.
        Active/paid invoices and invoices with payment records are skipped.
        """
        from django.db.models import ProtectedError

        candidates = queryset.filter(status__in=['DRAFT', 'CANCELLED'])
        has_payments_ids = set(
            Payment.objects.filter(invoice__in=candidates)
            .values_list('invoice_id', flat=True)
            .distinct()
        )
        safe = candidates.exclude(id__in=has_payments_ids)
        skipped_active = queryset.exclude(status__in=['DRAFT', 'CANCELLED']).count()
        skipped_payments = len(has_payments_ids)
        deleted = safe.count()

        # Use instance loop so Invoice.delete() fires and S3 cleanup runs.
        # QuerySet.delete() bypasses model overrides (see AGENTS.md gotcha).
        # (CODE-158: mirrors the same fix applied to owner_invoice_bulk_action
        # in saas/views.py via CODE-152; the admin action was missed then.)
        try:
            for inv in safe:
                inv.delete()
        except ProtectedError:
            self.message_user(
                request,
                '❌ Delete failed: one or more invoices have payment records.',
                level=messages.ERROR,
            )
            return

        msg = f'🗑️ {deleted} invoice(s) deleted.'
        if skipped_active:
            msg += f' {skipped_active} active invoice(s) skipped (void first).'
        if skipped_payments:
            msg += f' {skipped_payments} voided invoice(s) with payments skipped.'
        self.message_user(request, msg)

    def delete_queryset(self, request, queryset):
        """
        Override the default admin 'Delete selected' action to apply the same
        safety logic as bulk_delete_invoices.

        Django's default QuerySet.delete() bypasses Python-level model .delete()
        overrides, so without this:
          1. ANY invoice status could be deleted (including PAID/SENT/PARTIAL) —
             not just DRAFT/CANCELLED.
          2. Invoice.delete() (which calls _delete_s3_object()) never fires,
             orphaning PDF objects in S3.
          3. Payment records are NOT checked — invoices with payments could be
             deleted, leaving orphaned Payment rows pointing at a ghost invoice.

        This mirrors the same bug fixed for RepairAdmin (CODE-167) and
        PaymentAdmin.  InvoiceAdmin was the last admin class with a bulk-delete
        action that lacked a matching delete_queryset() override.

        (CODE-168)
        """
        candidates = queryset.filter(status__in=['DRAFT', 'CANCELLED'])
        has_payments_ids = set(
            Payment.objects.filter(invoice__in=candidates)
            .values_list('invoice_id', flat=True)
            .distinct()
        )
        safe = candidates.exclude(id__in=has_payments_ids)

        # Iterate instance-by-instance so Invoice.delete() fires for each row,
        # which calls _delete_s3_object() to clean up PDF objects in S3.
        for inv in safe:
            inv.delete()


@admin.register(Payment)
class PaymentAdmin(TenantFilterMixin, admin.ModelAdmin):
    """Admin for Payment model."""

    # Payments have no direct tenant FK; filter through invoice -> customer -> tenant
    tenant_field = 'invoice__customer__tenant'

    list_display = [
        'id', 'get_tenant', 'invoice_link', 'amount_display', 'payment_date', 
        'payment_method', 'reference_number', 'created_at'
    ]
    list_filter = ['payment_method', 'payment_date']
    search_fields = ['invoice__invoice_number', 'reference_number', 'notes']
    date_hierarchy = 'payment_date'
    readonly_fields = ['created_at']
    list_select_related = ['invoice', 'invoice__customer', 'invoice__customer__tenant']
    list_per_page = 25

    def get_tenant(self, obj):
        try:
            return obj.invoice.customer.tenant.name
        except AttributeError:
            return '—'
    get_tenant.short_description = 'Tenant'
    get_tenant.admin_order_field = 'invoice__customer__tenant__name'
    
    def invoice_link(self, obj):
        url = reverse('admin:billing_invoice_change', args=[obj.invoice.id])
        return format_html('<a href="{}">{}</a>', url, obj.invoice.invoice_number)
    invoice_link.short_description = 'Invoice'
    invoice_link.admin_order_field = 'invoice__invoice_number'
    
    def amount_display(self, obj):
        return f"${obj.amount:,.2f}"
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'

    def delete_queryset(self, request, queryset):
        """
        Override admin bulk-delete to call Payment.delete() on each instance.

        Django's default QuerySet.delete() fires a SQL DELETE directly, bypassing
        Python-level model .delete() overrides.  Payment.delete() (added in
        CODE-118) reconciles invoice.amount_paid / status after each payment is
        removed — without this override, bulk deletion via the admin changelist
        would leave invoices stuck as PAID with $0 payments, or with stale
        amount_paid balances.

        We iterate instance-by-instance here to ensure the reconciliation logic
        fires for every deleted row.  This is safe because admin bulk-delete is
        low-frequency (it's a manual superuser action) and the dataset is small.
        """
        for payment in queryset:
            payment.delete()


# =============================================================================
# TAX RATES
# =============================================================================

@admin.register(TaxRate)
class TaxRateAdmin(TenantFilterMixin, admin.ModelAdmin):
    """Admin for viewing/editing sales tax rates."""

    list_display = ['tenant', 'city', 'county', 'state', 'total_rate', 'is_active', 'effective_date']
    list_filter = ['tenant', 'state', 'is_active', 'county']
    search_fields = ['city', 'county', 'zip_code', 'tenant__name']
    list_editable = ['is_active']
    list_select_related = ['tenant']
    list_per_page = 50
    ordering = ['tenant', 'state', 'city']
    readonly_fields = ['total_rate']

    fieldsets = (
        ('Tenant', {
            'fields': ('tenant',),
        }),
        ('Location', {
            'fields': ('city', 'county', 'state', 'zip_code'),
        }),
        ('Rates (total auto-calculates)', {
            'fields': ('state_rate', 'county_rate', 'city_rate', 'special_rate', 'total_rate'),
        }),
        ('Status', {
            'fields': ('effective_date', 'is_active'),
        }),
    )


# =============================================================================
# PLATFORM CONFIGURATION (Singleton)
# =============================================================================

@admin.register(PlatformConfig)
class PlatformConfigAdmin(admin.ModelAdmin):
    """
    Admin for the global platform Stripe Connect fee configuration.
    This is a singleton model — only one record ever exists (pk=1).
    Only superusers should edit this.
    """
    list_display = ['default_fee_percent', 'competition_pool_enabled', 'competition_pool_fee_percent', 'updated_at']
    readonly_fields = ['updated_at']

    fieldsets = (
        ('Stripe Connect Fees', {
            'fields': ('default_fee_percent',),
            'description': (
                'Platform fee percentage charged on each connected-account invoice payment '
                '(e.g. 2.50 = 2.5%). Set to 0.00 to disable.'
            ),
        }),
        ('Competition Pool', {
            'fields': ('competition_pool_enabled', 'competition_pool_fee_percent'),
            'description': (
                'When enabled, a portion of subscription revenue is routed to a competition prize pool.'
            ),
        }),
        ('Metadata', {
            'fields': ('updated_at',),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        # Prevent manual creation via admin — singleton is auto-created on first access.
        # Allow add only if no record exists yet (e.g. fresh DB).
        return request.user.is_superuser and not PlatformConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # PlatformConfig.delete() raises ValidationError — reflect that in admin.
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


# =============================================================================
# PLATFORM FEE RECORDS (Audit Log)
# =============================================================================

@admin.register(PlatformFeeRecord)
class PlatformFeeRecordAdmin(TenantFilterMixin, admin.ModelAdmin):
    """
    Read-only admin for platform fee collection records.

    PlatformFeeRecord is created automatically when a connected-account Stripe
    payment succeeds. This admin provides superusers with an audit trail and
    lets shop owners see their own fee history.
    """
    list_display = [
        'id', 'tenant', 'invoice_link', 'fee_amount_display', 'fee_percent',
        'gross_amount_display', 'stripe_account_id', 'created_at',
    ]
    list_filter = ['tenant', 'created_at']
    search_fields = ['tenant__name', 'payment_intent_id', 'invoice__invoice_number', 'stripe_account_id']
    readonly_fields = [
        'tenant', 'invoice', 'payment_intent_id', 'gross_amount', 'fee_amount',
        'fee_percent', 'stripe_account_id', 'created_at',
    ]
    date_hierarchy = 'created_at'
    list_select_related = ['tenant', 'invoice']
    list_per_page = 50
    ordering = ['-created_at']

    def has_add_permission(self, request):
        # Fee records are created programmatically — never manually.
        return False

    def has_delete_permission(self, request, obj=None):
        # Fee records are audit trail — superusers only.
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        # Read-only — fee records must not be edited.
        return False

    def invoice_link(self, obj):
        if obj.invoice:
            url = reverse('admin:billing_invoice_change', args=[obj.invoice.id])
            return format_html('<a href="{}">{}</a>', url, obj.invoice.invoice_number)
        return '—'
    invoice_link.short_description = 'Invoice'
    invoice_link.admin_order_field = 'invoice__invoice_number'

    def fee_amount_display(self, obj):
        return f"${obj.fee_amount:,.2f}"
    fee_amount_display.short_description = 'Fee'
    fee_amount_display.admin_order_field = 'fee_amount'

    def gross_amount_display(self, obj):
        return f"${obj.gross_amount:,.2f}"
    gross_amount_display.short_description = 'Gross'
    gross_amount_display.admin_order_field = 'gross_amount'
