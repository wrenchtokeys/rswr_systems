from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician
from core.models import Customer
from rs_systems.admin_dashboard import get_dashboard_context


class UserTenantFilter(admin.SimpleListFilter):
    """Filter users by their associated tenant (via Technician or CustomerUser)."""
    title = 'tenant / shop'
    parameter_name = 'tenant'

    def lookups(self, request, model_admin):
        from apps.tenants.models import Tenant
        tenants = Tenant.objects.filter(is_active=True).order_by('name')
        return [(str(t.id), t.name) for t in tenants]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        tech_user_ids = Technician.objects.filter(
            tenant_id=self.value()
        ).values_list('user_id', flat=True)
        cu_user_ids = CustomerUser.objects.filter(
            customer__tenant_id=self.value()
        ).values_list('user_id', flat=True)
        from django.db.models import Q
        return queryset.filter(Q(id__in=tech_user_ids) | Q(id__in=cu_user_ids))


# Extend the User admin
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'get_role', 'get_tenant', 'is_active', 'date_joined']
    list_filter = ['is_staff', 'is_active', 'date_joined', 'groups', UserTenantFilter]
    actions = ['make_technician', 'make_customer', 'make_dual_role', 'deactivate_users', 'activate_users', 'bulk_delete_users']

    def get_queryset(self, request):
        """
        Prefetch Technician and CustomerUser reverse relations to eliminate N+1
        queries in get_role() and get_tenant().

        Without this fix, every row in the 25-user changelist issued up to 4 extra
        queries (2× exists()/first() for role + 2× first() for tenant) — up to 100
        queries per page load.  prefetch_related collapses all of those to 2 extra
        bulk queries regardless of page size. (CODE-097 N+1 fix)

        Both Technician and CustomerUser have OneToOneField → User, so Django's
        prefetch_related works via the reverse descriptor names 'technician' and
        'customeruser'.  After prefetching, accessing obj.technician or
        obj.customeruser hits the in-process cache, not the database.
        """
        from django.db.models import Prefetch
        qs = super().get_queryset(request)
        return qs.prefetch_related(
            Prefetch(
                'technician',
                queryset=Technician.objects.select_related('tenant'),
            ),
            Prefetch(
                'customeruser',
                queryset=CustomerUser.objects.select_related('customer__tenant'),
            ),
        )

    def get_role(self, obj):
        """
        Display the user's role (Technician, Customer, or Admin).

        Uses the prefetch_related cache populated by get_queryset() — no extra
        DB queries per row.
        """
        if obj.is_staff and obj.is_superuser:
            return 'Admin'

        # Access reverse OneToOneField via prefetch cache.  Django raises
        # RelatedObjectDoesNotExist (a subclass of AttributeError) when the
        # related object doesn't exist — use getattr with a sentinel to detect.
        _missing = object()
        tech = getattr(obj, 'technician', _missing)
        cu = getattr(obj, 'customeruser', _missing)
        is_technician = tech is not _missing and tech is not None
        is_customer = cu is not _missing and cu is not None

        if is_technician and is_customer:
            return 'Tech & Customer'
        elif is_technician:
            return 'Technician'
        elif is_customer:
            return 'Customer'

        return 'Unassigned'
    get_role.short_description = 'Role'

    def get_tenant(self, obj):
        """
        Display the user's tenant/shop via Technician or CustomerUser.

        Uses the prefetch_related cache populated by get_queryset() — no extra
        DB queries per row.
        """
        _missing = object()
        tech = getattr(obj, 'technician', _missing)
        if tech is not _missing and tech is not None and tech.tenant:
            return tech.tenant.name
        cu = getattr(obj, 'customeruser', _missing)
        if cu is not _missing and cu is not None and cu.customer and cu.customer.tenant:
            return cu.customer.tenant.name
        return '—'
    get_tenant.short_description = 'Tenant / Shop'

    def make_technician(self, request, queryset):
        """
        Disabled: creating a Technician requires specifying a tenant/shop.
        Use Technicians → Add Technician instead.
        """
        self.message_user(
            request,
            'Cannot auto-assign technician role from here: a tenant/shop must be '
            'specified for each technician. Please create technician records directly '
            'via Technicians → Add Technician and pick the correct shop.',
            level=messages.WARNING,
        )
    make_technician.short_description = 'Convert selected users to technicians (requires tenant — see warning)'

    def make_customer(self, request, queryset):
        """
        Disabled: creating a CustomerUser requires specifying a tenant-scoped customer.
        Use Customer Portal → Add Customer User instead.
        """
        self.message_user(
            request,
            'Cannot auto-assign customer role from here: a specific tenant/shop and '
            'customer account must be selected. Please create customer user records '
            'directly via Customer Portal → Customer Users → Add.',
            level=messages.WARNING,
        )
    make_customer.short_description = 'Convert selected users to customers (requires tenant — see warning)'

    def make_dual_role(self, request, queryset):
        """
        Disabled: assigning dual roles requires tenant-aware technician and customer records.
        Create them directly via their respective admin sections.
        """
        self.message_user(
            request,
            'Cannot auto-assign dual roles from here: both the Technician and '
            'CustomerUser records require a specific tenant/shop. Please create them '
            'directly via Technicians → Add Technician and Customer Portal → Customer Users → Add.',
            level=messages.WARNING,
        )
    make_dual_role.short_description = 'Give selected users both technician and customer roles (requires tenant — see warning)'
    
    def deactivate_users(self, request, queryset):
        """Deactivate selected users"""
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} users were successfully deactivated.')
    deactivate_users.short_description = 'Deactivate selected users'
    
    def activate_users(self, request, queryset):
        """Activate selected users"""
        count = queryset.update(is_active=True)
        self.message_user(request, f'{count} users were successfully activated.')
    activate_users.short_description = 'Activate selected users'

    @admin.action(description='🗑️ Bulk delete selected users (superuser only)')
    def bulk_delete_users(self, request, queryset):
        """
        Hard-delete selected users.

        Superuser-only. Protects against accidental deletion by skipping:
        - The requesting user themselves
        - Superusers and staff users
        - Tenant owners (deleting an owner would orphan the tenant)
        """
        from apps.tenants.models import Tenant

        if not request.user.is_superuser:
            self.message_user(
                request,
                '❌ Only superusers can bulk-delete users.',
                level=messages.ERROR,
            )
            return

        owner_ids = set(Tenant.objects.values_list('owner_id', flat=True))

        # Build safe set: exclude self, staff/superusers, and tenant owners
        safe = queryset.exclude(
            id=request.user.id
        ).exclude(
            is_staff=True
        ).exclude(
            is_superuser=True
        ).exclude(
            id__in=owner_ids
        )

        skipped = queryset.count() - safe.count()
        deleted = safe.count()
        safe.delete()

        msg = f'🗑️ {deleted} user(s) deleted.'
        if skipped:
            msg += f' ⚠️ {skipped} user(s) skipped (self, staff, superusers, or tenant owners).'
        self.message_user(request, msg)
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('user-management/', self.admin_site.admin_view(self.user_management_view), name='user_management'),
        ]
        return custom_urls + urls
    
    def user_management_view(self, request):
        """Custom view for comprehensive user management"""
        # Get role filter
        role_filter = request.GET.get('role', 'all')
        
        # Get users based on filter
        if role_filter == 'technician':
            users = User.objects.filter(id__in=Technician.objects.values_list('user_id', flat=True))
        elif role_filter == 'customer':
            users = User.objects.filter(id__in=CustomerUser.objects.values_list('user_id', flat=True))
        elif role_filter == 'dual':
            users = User.objects.filter(
                id__in=Technician.objects.values_list('user_id', flat=True)
            ).filter(
                id__in=CustomerUser.objects.values_list('user_id', flat=True)
            )
        elif role_filter == 'admin':
            users = User.objects.filter(is_superuser=True)
        elif role_filter == 'unassigned':
            tech_ids = set(Technician.objects.values_list('user_id', flat=True))
            cust_ids = set(CustomerUser.objects.values_list('user_id', flat=True))
            admin_ids = set(User.objects.filter(is_superuser=True).values_list('id', flat=True))
            all_role_ids = tech_ids.union(cust_ids).union(admin_ids)
            users = User.objects.exclude(id__in=all_role_ids)
        else:
            users = User.objects.all()
        
        # Stats to display
        stats = {
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(is_active=True).count(),
            'technicians': Technician.objects.count(),
            'customers': CustomerUser.objects.count(),
            'admins': User.objects.filter(is_superuser=True).count(),
            'dual_role': User.objects.filter(
                id__in=Technician.objects.values_list('user_id', flat=True)
            ).filter(
                id__in=CustomerUser.objects.values_list('user_id', flat=True)
            ).count(),
            'unassigned': User.objects.count() - (
                User.objects.filter(
                    id__in=Technician.objects.values_list('user_id', flat=True)
                ).count() +
                User.objects.filter(
                    id__in=CustomerUser.objects.values_list('user_id', flat=True)
                ).count() -
                User.objects.filter(
                    id__in=Technician.objects.values_list('user_id', flat=True)
                ).filter(
                    id__in=CustomerUser.objects.values_list('user_id', flat=True)
                ).count() +
                User.objects.filter(is_superuser=True).count()
            )
        }
        
        # Get the recent or filtered users
        if role_filter == 'all':
            display_users = User.objects.order_by('-date_joined')[:20]
        else:
            display_users = users.order_by('-date_joined')[:50]
        
        context = {
            'stats': stats,
            'users': display_users,
            'role_filter': role_filter,
            'opts': self.model._meta,
            'title': 'User Management Dashboard',
        }
        
        return render(request, 'admin/user_management.html', context)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Customize admin site
admin.site.site_header = 'RSWR Systems Administration'
admin.site.site_title = 'RSWR Admin Portal'
admin.site.index_title = 'Administration Dashboard'

# ── Phase 2: Custom Dashboard ─────────────────────────────────────────────────
# Wire up custom index template and inject dashboard metrics.

# Point admin to our custom index template
admin.site.index_template = 'admin/index.html'

# Monkey-patch the index view to inject dashboard context
_original_index = admin.AdminSite.index


def _dashboard_index(self, request, extra_context=None):
    extra_context = extra_context or {}
    try:
        extra_context.update(get_dashboard_context())
    except Exception:
        pass  # Never let dashboard errors break the admin
    return _original_index(self, request, extra_context)


admin.AdminSite.index = _dashboard_index


# =============================================================================
# Phase 6b: Audit Log — nice view over Django's built-in LogEntry
# =============================================================================

@admin.register(LogEntry)
class AuditLogAdmin(admin.ModelAdmin):
    """
    Read-only admin view over Django's built-in action log.
    Shows who changed what and when, across all admin-managed models.

    Tenant scoping (CODE-231):
    LogEntry has no direct tenant FK, but every entry records which user
    performed the action.  Non-superuser staff should only see log entries
    made by users who belong to the same tenant(s) — otherwise a Shop A
    admin could read object_repr strings revealing Shop B's customer names,
    invoice numbers, and repair details.

    Superusers see all log entries across all tenants.
    """

    list_display = [
        'action_time', 'user_link', 'action_badge', 'content_type',
        'object_repr_short', 'change_message_short',
    ]
    list_filter = ['action_flag', 'content_type', 'action_time']
    search_fields = ['user__username', 'user__email', 'object_repr', 'change_message']
    date_hierarchy = 'action_time'
    list_select_related = ['user', 'content_type']
    list_per_page = 50
    ordering = ['-action_time']

    def get_queryset(self, request):
        """
        Scope audit log entries to the current user's tenant(s).

        Non-superusers only see log entries made by users who share at least
        one active TenantMembership with them.  This prevents cross-tenant
        data leakage through object_repr and change_message strings.
        """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        from apps.tenants.models import TenantMembership
        # Get all tenant IDs the current user belongs to
        my_tenant_ids = (
            TenantMembership.objects
            .filter(user=request.user, is_active=True)
            .values_list('tenant_id', flat=True)
        )
        # Get all user IDs who are members of those same tenants
        co_tenant_user_ids = (
            TenantMembership.objects
            .filter(tenant_id__in=my_tenant_ids, is_active=True)
            .values_list('user_id', flat=True)
        )
        return qs.filter(user_id__in=co_tenant_user_ids)

    # No adding, editing, or deleting audit records
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def user_link(self, obj):
        url = f"/admin/auth/user/{obj.user_id}/change/"
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username)
    user_link.short_description = 'User'
    user_link.admin_order_field = 'user__username'

    def action_badge(self, obj):
        flag_map = {
            ADDITION: ('Added', '#28a745'),
            CHANGE: ('Changed', '#007bff'),
            DELETION: ('Deleted', '#dc3545'),
        }
        label, color = flag_map.get(obj.action_flag, ('Unknown', '#6c757d'))
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color, label,
        )
    action_badge.short_description = 'Action'
    action_badge.admin_order_field = 'action_flag'

    def object_repr_short(self, obj):
        return obj.object_repr[:60] + ('…' if len(obj.object_repr) > 60 else '')
    object_repr_short.short_description = 'Object'

    def change_message_short(self, obj):
        msg = obj.get_change_message()
        return msg[:100] + ('…' if len(msg) > 100 else '') if msg else '—'
    change_message_short.short_description = 'Changes'


# =============================================================================
# Phase 6c: Global Admin Search
# =============================================================================

def _global_search_view(request):
    """
    Search across Customers, Repairs, Invoices, and Users in one shot.
    Results are grouped by model type.
    Accessible at /admin/search/

    Tenant scoping (CODE-157):
    - Superusers see all data across all tenants.
    - Non-superuser staff see only data belonging to their own tenant(s)
      (via TenantMembership). Without this restriction a staff user from
      Shop A could discover customers, repairs, invoices, and user accounts
      from Shop B simply by searching.
    """
    query = request.GET.get('q', '').strip()
    results = {}

    if query:
        from apps.billing.models import Invoice
        from apps.technician_portal.models import Repair
        from django.db.models import Q

        if request.user.is_superuser:
            # Superusers: unrestricted access across all tenants.
            tenant_ids = None
        else:
            # Non-superuser staff: restrict to their own tenant(s).
            from apps.tenants.models import TenantMembership
            tenant_ids = list(
                TenantMembership.objects
                .filter(user=request.user, is_active=True)
                .values_list('tenant_id', flat=True)
            )

        def _scope_qs(qs, tenant_field):
            """Apply tenant filter to queryset unless user is superuser."""
            if tenant_ids is None:
                return qs
            return qs.filter(**{f"{tenant_field}__in": tenant_ids})

        customers = _scope_qs(
            Customer.objects.filter(
                Q(name__icontains=query) | Q(email__icontains=query)
            ).select_related('tenant'),
            'tenant',
        )[:20]

        repairs = _scope_qs(
            Repair.objects.filter(
                Q(unit_number__icontains=query) | Q(customer__name__icontains=query)
            ).select_related('customer', 'tenant'),
            'tenant',
        )[:20]

        invoices = _scope_qs(
            Invoice.objects.filter(
                Q(invoice_number__icontains=query) | Q(customer__name__icontains=query)
            ).select_related('customer', 'tenant'),
            'tenant',
        )[:20]

        # Users: superusers see all; non-superusers see only users in their tenant(s)
        # (technicians and customer users belonging to the same shop).
        if tenant_ids is None:
            users = User.objects.filter(
                Q(username__icontains=query) | Q(email__icontains=query) |
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
            )[:20]
        else:
            from apps.customer_portal.models import CustomerUser as _CU
            tech_user_ids = Technician.objects.filter(
                tenant_id__in=tenant_ids
            ).values_list('user_id', flat=True)
            cu_user_ids = _CU.objects.filter(
                customer__tenant_id__in=tenant_ids
            ).values_list('user_id', flat=True)
            users = User.objects.filter(
                Q(id__in=tech_user_ids) | Q(id__in=cu_user_ids)
            ).filter(
                Q(username__icontains=query) | Q(email__icontains=query) |
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
            )[:20]

        results = {
            'customers': customers,
            'repairs': repairs,
            'invoices': invoices,
            'users': users,
        }

    context = {
        **admin.site.each_context(request),
        'title': 'Global Search',
        'query': query,
        'results': results,
    }
    return render(request, 'admin/global_search.html', context)


# Monkey-patch get_urls to add our search URL
_original_get_urls = admin.AdminSite.get_urls


def _custom_get_urls(self):
    original_urls = _original_get_urls(self)
    from rs_systems.admin_connect_views import admin_connect_accounts_view, admin_platform_config_view
    custom = [
        path('search/', self.admin_view(_global_search_view), name='global_search'),
        path('connect-accounts/', self.admin_view(admin_connect_accounts_view), name='admin_connect_accounts'),
        path('platform-config/', self.admin_view(admin_platform_config_view), name='admin_platform_config'),
    ]
    return custom + original_urls


admin.AdminSite.get_urls = _custom_get_urls
