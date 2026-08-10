"""
Admin for the support app — Drake's support console.

SupportMessage: every /help/contact/ submission lands here (record-first,
even when the notification email failed — filter emailed_ok=No after an SES
incident). Reply from your inbox (the notification carries Reply-To), then
flip Status right in the list.

GuideFeedback: the read-out for the "Was this helpful?" thumbs — which
guides fail people before they write in.
"""

from django.contrib import admin

from .models import GuideFeedback, SupportMessage


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'name', 'email', 'tenant', 'topic', 'preview', 'status', 'emailed_ok')
    list_editable = ('status',)
    list_filter = ('status', 'topic', 'emailed_ok', 'tenant')
    search_fields = ('name', 'email', 'message', 'tenant__name')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('tenant', 'user', 'name', 'email', 'topic', 'message', 'page', 'emailed_ok', 'created_at')
    fields = ('status',) + readonly_fields

    @admin.display(description='Message')
    def preview(self, obj):
        return (obj.message[:80] + '…') if len(obj.message) > 80 else obj.message

    def has_add_permission(self, request):
        return False  # messages come from the contact form, never typed in here


@admin.register(GuideFeedback)
class GuideFeedbackAdmin(admin.ModelAdmin):
    list_display = ('slug', 'helpful', 'user', 'tenant', 'updated_at')
    list_filter = ('helpful', 'slug', 'tenant')
    search_fields = ('slug', 'user__username', 'user__email', 'tenant__name')
    date_hierarchy = 'updated_at'
    ordering = ('-updated_at',)
    readonly_fields = ('user', 'tenant', 'slug', 'helpful', 'updated_at')

    def has_add_permission(self, request):
        return False  # votes come from the help pages, never typed in here
