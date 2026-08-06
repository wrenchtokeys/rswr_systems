"""
Admin for guide feedback — the read-out for the "Was this helpful?" thumbs.

Votes are recorded automatically; this is where Drake sees which guides
fail people. Phase 3's support console will surface the same data next to
SupportMessage.
"""

from django.contrib import admin

from .models import GuideFeedback


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
