from django.contrib import admin
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

# Extend the User admin
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'get_role', 'is_active', 'date_joined']
    list_filter = ['is_staff', 'is_active', 'date_joined', 'groups']
    actions = ['make_technician', 'make_customer', 'make_dual_role', 'deactivate_users', 'activate_users']
    
    def get_role(self, obj):
        """Display the user's role (Technician, Customer, or Admin)"""
        if obj.is_staff and obj.is_superuser:
            return 'Admin'
        
        is_technician = Technician.objects.filter(user=obj).exists()
        is_customer = CustomerUser.objects.filter(user=obj).exists()
        
        if is_technician and is_customer:
            return 'Tech & Customer'
        elif is_technician:
            return 'Technician'
        elif is_customer:
            return 'Customer'
            
        return 'Unassigned'
    get_role.short_description = 'Role'
    
    def make_technician(self, request, queryset):
        """Convert selected users to technicians (if they aren't already)"""
        count = 0
        for user in queryset:
            # Skip users who are already technicians
            if Technician.objects.filter(user=user).exists():
                continue
                
            # Create technician record
            Technician.objects.create(
                user=user,
                phone_number='',
                expertise='General'
            )
            count += 1
            
        self.message_user(request, f'{count} users were successfully converted to technicians.')
    make_technician.short_description = 'Convert selected users to technicians'
    
    def make_customer(self, request, queryset):
        """Convert selected users to customers (if they aren't already)"""
        count = 0
        # Need to check if there's at least one company in the system
        if not Customer.objects.exists():
            self.message_user(request, 'Error: You need to create at least one company first.', level=messages.ERROR)
            return
            
        default_company = Customer.objects.first()
        
        for user in queryset:
            # Skip users who are already customers
            if CustomerUser.objects.filter(user=user).exists():
                continue
                
            # Create customer user record
            CustomerUser.objects.create(
                user=user,
                customer=default_company,
                is_primary_contact=False
            )
            count += 1
            
        self.message_user(request, f'{count} users were successfully converted to customers and associated with {default_company.name}.')
    make_customer.short_description = 'Convert selected users to customers'
    
    def make_dual_role(self, request, queryset):
        """Make selected users both technicians and customers"""
        tech_count = 0
        cust_count = 0
        
        # Need to check if there's at least one company in the system
        if not Customer.objects.exists():
            self.message_user(request, 'Error: You need to create at least one company first.', level=messages.ERROR)
            return
            
        default_company = Customer.objects.first()
        
        for user in queryset:
            # Add technician role if needed
            if not Technician.objects.filter(user=user).exists():
                Technician.objects.create(
                    user=user,
                    phone_number='',
                    expertise='General'
                )
                tech_count += 1
                
            # Add customer role if needed
            if not CustomerUser.objects.filter(user=user).exists():
                CustomerUser.objects.create(
                    user=user,
                    customer=default_company,
                    is_primary_contact=False
                )
                cust_count += 1
                
        self.message_user(request, f'Users updated: {tech_count} new technician roles and {cust_count} new customer roles assigned.')
    make_dual_role.short_description = 'Give selected users both technician and customer roles'
    
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
    """
    query = request.GET.get('q', '').strip()
    results = {}

    if query:
        from apps.billing.models import Invoice
        from apps.technician_portal.models import Repair
        from django.db.models import Q

        customers = Customer.objects.filter(
            Q(name__icontains=query) | Q(email__icontains=query)
        ).select_related('tenant')[:20]

        repairs = Repair.objects.filter(
            Q(unit_number__icontains=query) | Q(customer__name__icontains=query)
        ).select_related('customer', 'tenant')[:20]

        invoices = Invoice.objects.filter(
            Q(invoice_number__icontains=query) | Q(customer__name__icontains=query)
        ).select_related('customer', 'tenant')[:20]

        users = User.objects.filter(
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
    custom = [
        path('search/', self.admin_view(_global_search_view), name='global_search'),
    ]
    return custom + original_urls


admin.AdminSite.get_urls = _custom_get_urls
