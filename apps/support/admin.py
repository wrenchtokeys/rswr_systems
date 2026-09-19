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
    # `who` rather than `tenant`: a message from the public form has no
    # tenant at all, and a blank column would read as a broken row.
    list_display = ('created_at', 'name', 'email', 'who', 'source', 'topic', 'preview', 'status', 'emailed_ok')
    list_editable = ('status',)
    list_filter = ('status', 'source', 'topic', 'emailed_ok', 'acknowledged', 'tenant')
    search_fields = ('name', 'email', 'message', 'tenant__name', 'shop_name')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('tenant', 'shop_name', 'user', 'role', 'source', 'name', 'email', 'topic', 'message',
                       'page_label', 'page', 'emailed_ok', 'acknowledged', 'created_at')
    fields = ('status',) + readonly_fields

    @admin.display(description='Shop', ordering='tenant__name')
    def who(self, obj):
        """The sender's shop, or what a visitor typed into the public form."""
        if obj.tenant:
            return obj.tenant.name
        if obj.shop_name:
            return f'{obj.shop_name} (visitor)'
        return '(visitor)'

    @admin.display(description='Where they were')
    def page_label(self, obj):
        # `page` is document.referrer — a URL. Say which guide or settings
        # tab that is, so "which page were they on" reads at a glance.
        from .views import describe_page
        return describe_page(obj.page)

    @admin.display(description='Message')
    def preview(self, obj):
        return (obj.message[:80] + '…') if len(obj.message) > 80 else obj.message

    def has_add_permission(self, request):
        return False  # messages come from the contact form, never typed in here


def feedback_rollup():
    """Per-guide totals: slug, title, up, down, % helpful, last vote.

    Sorted by down-votes desc so the guide that fails most is first. One
    aggregate query; no new model.
    """
    from django.db.models import Count, Max, Q

    from .views import HELP_TOPICS

    rows = (
        GuideFeedback.objects.values('slug')
        .annotate(
            up=Count('id', filter=Q(helpful=True)),
            down=Count('id', filter=Q(helpful=False)),
            last=Max('updated_at'),
        )
    )
    out = []
    for row in rows:
        total = row['up'] + row['down']
        topic = HELP_TOPICS.get(row['slug'])
        out.append({
            'slug': row['slug'],
            'title': topic['title'] if topic else row['slug'],
            'up': row['up'],
            'down': row['down'],
            'pct': round(100 * row['up'] / total) if total else None,
            'last': row['last'],
        })
    out.sort(key=lambda r: (-r['down'], -(r['up'] + r['down']), r['slug']))
    return out


@admin.register(GuideFeedback)
class GuideFeedbackAdmin(admin.ModelAdmin):
    change_list_template = 'admin/support/guidefeedback/change_list.html'
    list_display = ('slug', 'helpful', 'reason', 'user', 'tenant', 'updated_at')
    list_filter = ('helpful', 'slug', 'tenant')
    search_fields = ('slug', 'reason', 'user__username', 'user__email', 'tenant__name')
    date_hierarchy = 'updated_at'
    ordering = ('-updated_at',)
    readonly_fields = ('user', 'tenant', 'slug', 'helpful', 'reason', 'updated_at')

    def has_add_permission(self, request):
        return False  # votes come from the help pages, never typed in here

    def changelist_view(self, request, extra_context=None):
        extra_context = dict(extra_context or {}, rollup=feedback_rollup())
        return super().changelist_view(request, extra_context=extra_context)
