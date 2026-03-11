from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
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
