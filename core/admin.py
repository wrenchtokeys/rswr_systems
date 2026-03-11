from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.safestring import mark_safe
from core.models import (
    Notification,
    NotificationDeliveryLog,
    NotificationTemplate,
    TechnicianNotificationPreference,
    CustomerNotificationPreference,
    EmailBrandingConfig,
)

# Note: Customer model is already registered in apps/customer_portal/admin.py
# We don't register it here to avoid conflicts


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Enhanced admin for notifications with stats"""

    list_display = [
        'id',
        'title_truncated',
        'recipient_display',
        'priority_badge',
        'category',
        'delivery_status',
        'created_at',
        'read_status'
    ]

    list_filter = [
        'priority',
        'category',
        'read',
        'email_sent',
        'sms_sent',
        'created_at'
    ]

    search_fields = [
        'title',
        'message',
        'recipient_id'
    ]

    readonly_fields = [
        'created_at',
        'read_at',
        'template_context'
    ]

    actions = ['mark_as_read', 'mark_as_unread', 'retry_delivery']
    list_per_page = 25

    def title_truncated(self, obj):
        return obj.title[:50] + '...' if len(obj.title) > 50 else obj.title
    title_truncated.short_description = 'Title'

    def recipient_display(self, obj):
        return f"{obj.recipient_type.model} #{obj.recipient_id}"
    recipient_display.short_description = 'Recipient'

    def priority_badge(self, obj):
        colors = {
            'URGENT': 'red',
            'HIGH': 'orange',
            'MEDIUM': 'blue',
            'LOW': 'gray'
        }
        color = colors.get(obj.priority, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.priority
        )
    priority_badge.short_description = 'Priority'

    def delivery_status(self, obj):
        status = []
        if obj.email_sent:
            status.append('📧')
        if obj.sms_sent:
            status.append('📱')
        return ' '.join(status) or '—'
    delivery_status.short_description = 'Delivered'

    def read_status(self, obj):
        return '✓' if obj.read else '—'
    read_status.short_description = 'Read'

    def mark_as_read(self, request, queryset):
        """Bulk action to mark notifications as read"""
        updated = queryset.filter(read=False).count()
        for notification in queryset.filter(read=False):
            notification.mark_as_read()
        self.message_user(request, f"Marked {updated} notifications as read")
    mark_as_read.short_description = "Mark selected as read"

    def mark_as_unread(self, request, queryset):
        """Bulk action to mark notifications as unread"""
        updated = queryset.update(read=False, read_at=None)
        self.message_user(request, f"Marked {updated} notifications as unread")
    mark_as_unread.short_description = "Mark selected as unread"

    def retry_delivery(self, request, queryset):
        """Bulk action to retry delivery for failed notifications"""
        from core.tasks import send_notification_email, send_notification_sms

        retried = 0
        for notification in queryset:
            # Only retry if not successfully delivered
            if not notification.email_sent or not notification.sms_sent:
                # Re-queue email delivery if needed
                if not notification.email_sent and notification.should_send_email():
                    send_notification_email.apply_async(
                        args=[notification.id],
                        countdown=5  # Wait 5 seconds before retrying
                    )
                    retried += 1

                # Re-queue SMS delivery if needed
                if not notification.sms_sent and notification.should_send_sms():
                    send_notification_sms.apply_async(
                        args=[notification.id],
                        countdown=5
                    )
                    retried += 1

        self.message_user(
            request,
            f"Queued {retried} notification(s) for retry delivery. Check Celery logs for results.",
            level='success' if retried > 0 else 'warning'
        )
    retry_delivery.short_description = "Retry delivery for selected notifications"

    def changelist_view(self, request, extra_context=None):
        """Add statistics to change list page"""
        extra_context = extra_context or {}

        # Aggregate stats
        stats = Notification.objects.aggregate(
            total=Count('id'),
            unread=Count('id', filter=Q(read=False)),
            urgent=Count('id', filter=Q(priority='URGENT')),
            email_sent=Count('id', filter=Q(email_sent=True)),
            sms_sent=Count('id', filter=Q(sms_sent=True)),
        )

        extra_context['stats'] = stats
        return super().changelist_view(request, extra_context)


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    """Admin for notification templates with preview"""

    list_display = [
        'name',
        'category',
        'default_priority',
        'version',
        'active',
        'created_at'
    ]

    list_filter = [
        'category',
        'default_priority',
        'active',
        'created_at'
    ]

    search_fields = [
        'name',
        'description',
        'title_template',
        'message_template'
    ]

    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'category', 'default_priority', 'active', 'version')
        }),
        ('In-App Templates', {
            'fields': ('title_template', 'message_template', 'action_url_template')
        }),
        ('Email Templates', {
            'fields': ('email_subject_template', 'email_html_template', 'email_text_template'),
            'classes': ('collapse',)
        }),
        ('SMS Template', {
            'fields': ('sms_template',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('required_context', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(NotificationDeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    """Admin for delivery logs with retry actions"""

    list_display = [
        'id',
        'notification_id',
        'channel',
        'status_badge',
        'recipient',
        'attempt_number',
        'cost_display',
        'created_at'
    ]

    list_filter = [
        'channel',
        'status',
        'created_at',
        'provider_name'
    ]

    search_fields = [
        'notification__title',
        'recipient_email',
        'recipient_phone',
        'provider_message_id'
    ]

    readonly_fields = [
        'notification',
        'provider_response',
        'created_at',
        'sent_at',
        'failed_at'
    ]

    actions = ['retry_failed_deliveries']

    def status_badge(self, obj):
        colors = {
            'sent': 'green',
            'failed': 'red',
            'pending': 'orange',
            'bounced': 'red',
            'opted_out': 'gray',
            'skipped': 'blue'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper()
        )
    status_badge.short_description = 'Status'

    def recipient(self, obj):
        return obj.recipient_email or obj.recipient_phone
    recipient.short_description = 'Recipient'

    def cost_display(self, obj):
        """Display cost with currency formatting"""
        if obj.cost and obj.cost > 0:
            return f"${obj.cost:.4f}"
        return "—"
    cost_display.short_description = 'Cost'

    def retry_failed_deliveries(self, request, queryset):
        """Admin action to retry failed deliveries"""
        from core.tasks import send_notification_email, send_notification_sms

        # Filter to only failed deliveries that haven't exceeded retry limit
        failed_logs = queryset.filter(status='failed', attempt_number__lt=3)
        count = 0

        for log in failed_logs:
            notification = log.notification

            # Re-queue based on channel
            if log.channel == 'email' and notification:
                send_notification_email.apply_async(
                    args=[notification.id],
                    countdown=10  # Wait 10 seconds before retrying
                )
                count += 1
            elif log.channel == 'sms' and notification:
                send_notification_sms.apply_async(
                    args=[notification.id],
                    countdown=10
                )
                count += 1

        self.message_user(
            request,
            f"Queued {count} failed delivery/deliveries for retry. Check Celery logs for results.",
            level='success' if count > 0 else 'warning'
        )
    retry_failed_deliveries.short_description = "Retry failed deliveries"


# Inline admin for notification preferences
class TechnicianNotificationPreferenceInline(admin.StackedInline):
    """Inline admin for technician notification preferences"""
    model = TechnicianNotificationPreference
    can_delete = False
    verbose_name_plural = 'Notification Preferences'

    fieldsets = (
        ('Delivery Channels', {
            'fields': ('receive_email_notifications', 'receive_sms_notifications', 'receive_in_app_notifications')
        }),
        ('Categories', {
            'fields': ('notify_repair_status', 'notify_new_assignments', 'notify_reassignments',
                      'notify_customer_approvals', 'notify_reward_redemptions', 'notify_system'),
            'classes': ('collapse',)
        }),
        ('Quiet Hours', {
            'fields': ('quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end'),
            'classes': ('collapse',)
        }),
        ('Contact Verification', {
            'fields': ('email_verified', 'email_verified_at', 'phone_verified', 'phone_verified_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EmailBrandingConfig)
class EmailBrandingConfigAdmin(admin.ModelAdmin):
    """
    Admin interface for Email Branding Configuration.

    Features:
    - Singleton enforcement (only one config allowed)
    - Organized fieldsets by category
    - Live logo preview
    - Color picker integration via custom JavaScript
    - Prevent deletion
    """

    list_display = [
        'company_name',
        'logo_preview',
        'color_preview',
        'last_updated',
        'updated_by_user'
    ]

    readonly_fields = [
        'created_at',
        'updated_at',
        'logo_preview_large',
        'color_swatches',
    ]

    fieldsets = (
        ('Logo Settings', {
            'fields': ('logo', 'logo_preview_large', 'logo_width'),
            'description': 'Upload your company logo. It will be optimized for email compatibility (max 400px width).'
        }),
        ('Color Scheme', {
            'fields': (
                'color_swatches',
                ('primary_color', 'secondary_color'),
                ('success_color', 'danger_color'),
                ('text_color', 'background_color'),
            ),
            'description': 'Customize the color scheme for all email templates. Use the color pickers or enter hex codes.'
        }),
        ('Company Information', {
            'fields': (
                'company_name',
                'company_address',
                ('support_email', 'support_phone'),
                'website_url',
            ),
            'description': 'This information appears in email footers.'
        }),
        ('Social Media Links', {
            'fields': ('facebook_url', 'twitter_url', 'linkedin_url'),
            'classes': ('collapse',),
            'description': 'Optional social media links for email footers.'
        }),
        ('Footer Content', {
            'fields': ('footer_text',),
            'description': 'Custom footer text displayed in all emails.'
        }),
        ('Typography & Styling', {
            'fields': (
                ('heading_font', 'body_font'),
                'button_border_radius',
            ),
            'classes': ('collapse',),
            'description': 'Advanced styling options.'
        }),
        ('Metadata', {
            'fields': ('updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    class Media:
        css = {
            'all': ('admin/css/email_branding.css',)
        }
        js = ('admin/js/color_picker.js',)

    def has_add_permission(self, request):
        """Only allow creation if no config exists (singleton pattern)"""
        return not EmailBrandingConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of branding config"""
        return False

    def save_model(self, request, obj, form, change):
        """Track who updated the branding configuration"""
        if change:  # Only on updates
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    def logo_preview(self, obj):
        """Small logo preview for list view"""
        if obj.logo:
            return format_html(
                '<img src="{}" style="max-height: 30px; max-width: 100px;" />',
                obj.logo.url
            )
        return '—'
    logo_preview.short_description = 'Logo'

    def logo_preview_large(self, obj):
        """Large logo preview for edit page"""
        if obj.logo:
            return format_html(
                '<div style="margin: 10px 0;">'
                '<img src="{}" style="max-width: 400px; border: 1px solid #ddd; padding: 10px; background: white;" />'
                '<p style="color: #666; font-size: 12px; margin-top: 5px;">Current logo (will be displayed at {}px width in emails)</p>'
                '</div>',
                obj.logo.url,
                obj.logo_width
            )
        return format_html('<p style="color: #999;">No logo uploaded</p>')
    logo_preview_large.short_description = 'Current Logo'

    def color_preview(self, obj):
        """Color swatches for list view"""
        return format_html(
            '<div style="display: flex; gap: 3px;">'
            '<div style="width: 20px; height: 20px; background: {}; border: 1px solid #ddd;" title="Primary"></div>'
            '<div style="width: 20px; height: 20px; background: {}; border: 1px solid #ddd;" title="Secondary"></div>'
            '<div style="width: 20px; height: 20px; background: {}; border: 1px solid #ddd;" title="Success"></div>'
            '</div>',
            obj.primary_color,
            obj.secondary_color,
            obj.success_color
        )
    color_preview.short_description = 'Colors'

    def color_swatches(self, obj):
        """Large color swatches for edit page"""
        colors = [
            ('Primary', obj.primary_color),
            ('Secondary', obj.secondary_color),
            ('Success', obj.success_color),
            ('Danger', obj.danger_color),
            ('Text', obj.text_color),
            ('Background', obj.background_color),
        ]

        # Build swatches using format_html for each item
        swatch_items = []
        for name, color in colors:
            swatch_items.append(format_html(
                '<div style="text-align: center;">'
                '<div style="width: 60px; height: 60px; background: {}; border: 2px solid #ddd; border-radius: 4px; margin-bottom: 5px;"></div>'
                '<div style="font-size: 11px; color: #666;">{}</div>'
                '<div style="font-size: 10px; font-family: monospace; color: #999;">{}</div>'
                '</div>',
                color, name, color
            ))

        from django.utils.html import mark_safe
        return mark_safe(
            '<div style="display: flex; gap: 15px; flex-wrap: wrap; margin: 10px 0;">'
            + ''.join(str(s) for s in swatch_items)
            + '</div>'
        )
    color_swatches.short_description = 'Current Color Scheme'

    def last_updated(self, obj):
        """Formatted last update time"""
        return obj.updated_at.strftime('%b %d, %Y at %I:%M %p')
    last_updated.short_description = 'Last Updated'

    def updated_by_user(self, obj):
        """Show who last updated the config"""
        if obj.updated_by:
            return obj.updated_by.get_full_name() or obj.updated_by.username
        return '—'
    updated_by_user.short_description = 'Updated By'

    def changelist_view(self, request, extra_context=None):
        """Add helpful message to list view"""
        extra_context = extra_context or {}
        extra_context['title'] = 'Email Branding Configuration'
        extra_context['subtitle'] = 'Customize the appearance of all system email notifications'
        return super().changelist_view(request, extra_context)


class CustomerNotificationPreferenceInline(admin.StackedInline):
    """Inline admin for customer notification preferences"""
    model = CustomerNotificationPreference
    can_delete = False
    verbose_name_plural = 'Notification Preferences'

    fieldsets = (
        ('Delivery Channels', {
            'fields': ('receive_email_notifications', 'receive_sms_notifications', 'receive_in_app_notifications')
        }),
        ('Categories', {
            'fields': ('notify_repair_status', 'notify_new_requests', 'notify_pending_approvals',
                      'notify_completions', 'notify_in_progress', 'notify_system'),
            'classes': ('collapse',)
        }),
        ('Quiet Hours', {
            'fields': ('quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end'),
            'classes': ('collapse',)
        }),
        ('Contact Verification', {
            'fields': ('email_verified', 'email_verified_at', 'phone_verified', 'phone_verified_at'),
            'classes': ('collapse',)
        }),
    )
