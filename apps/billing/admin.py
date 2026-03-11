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

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from django.urls import reverse
from decimal import Decimal

from .models import BillingConfig, Invoice, InvoiceLineItem, Payment, TaxRate


# =============================================================================
# BILLING CONFIGURATION (Singleton)
# =============================================================================

@admin.register(BillingConfig)
class BillingConfigAdmin(admin.ModelAdmin):
    """
    Singleton billing settings — company address, payment terms, invoice defaults.
    Always shows the single instance; Add button is hidden when it exists.
    """

    fieldsets = (
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

    list_display = ['__str__', 'company_name', 'default_payment_terms', 'updated_at']

    def has_add_permission(self, request):
        # Only allow adding if no instance exists yet
        return not BillingConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """Redirect list view straight to the singleton edit page."""
        instance = BillingConfig.get_instance()
        from django.shortcuts import redirect
        return redirect(
            reverse('admin:billing_billingconfig_change', args=[instance.pk])
        )


# =============================================================================
# INVOICES
# =============================================================================


class InvoiceLineItemInline(admin.TabularInline):
    """Inline display of line items on invoice."""
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ['repair_link', 'repair_date', 'unit_number']
    fields = ['description', 'quantity', 'unit_price', 'discount', 'amount', 'repair_link']
    
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
class InvoiceAdmin(admin.ModelAdmin):
    """Admin for Invoice model."""
    
    list_display = [
        'invoice_number', 'customer_link', 'invoice_date', 'due_date',
        'payment_terms',
        'total_display', 'amount_paid_display', 'amount_due_display', 
        'status_badge', 'line_item_count'
    ]
    list_filter = ['status', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'customer__name']
    date_hierarchy = 'invoice_date'
    list_select_related = ['customer']
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
            return format_html('<span style="color: red;">${:,.2f}</span>', due)
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
        return obj.line_items.count()
    line_item_count.short_description = 'Items'
    
    actions = ['mark_as_sent', 'mark_as_overdue', 'export_csv']

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
                inv.invoice_number,
                inv.customer.name if inv.customer else '',
                inv.invoice_date,
                inv.due_date,
                inv.payment_terms,
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


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Admin for Payment model."""
    
    list_display = [
        'id', 'invoice_link', 'amount_display', 'payment_date', 
        'payment_method', 'reference_number', 'created_at'
    ]
    list_filter = ['payment_method', 'payment_date']
    search_fields = ['invoice__invoice_number', 'reference_number', 'notes']
    date_hierarchy = 'payment_date'
    readonly_fields = ['created_at']
    list_select_related = ['invoice']
    list_per_page = 25
    
    def invoice_link(self, obj):
        url = reverse('admin:billing_invoice_change', args=[obj.invoice.id])
        return format_html('<a href="{}">{}</a>', url, obj.invoice.invoice_number)
    invoice_link.short_description = 'Invoice'
    invoice_link.admin_order_field = 'invoice__invoice_number'
    
    def amount_display(self, obj):
        return f"${obj.amount:,.2f}"
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'


# =============================================================================
# TAX RATES
# =============================================================================

@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    """Admin for viewing/editing sales tax rates."""

    list_display = ['city', 'county', 'state', 'total_rate', 'is_active', 'effective_date']
    list_filter = ['state', 'is_active', 'county']
    search_fields = ['city', 'county', 'zip_code']
    list_editable = ['is_active']
    list_per_page = 50
    ordering = ['state', 'city']
    readonly_fields = ['total_rate']

    fieldsets = (
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
