"""
Custom decorators for technician portal views.
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def is_tenant_admin(user):
    """
    Check if user has admin-level access for their tenant.
    
    Returns True if:
    - Django staff/superuser (legacy admin access)
    - Tenant owner or manager (SaaS admin access)
    
    This replaces is_staff checks throughout the tech portal so that
    SaaS owners/managers get full access without needing Django staff status.
    """
    if user.is_staff:
        return True
    
    try:
        from apps.tenants.models import TenantMembership
        return TenantMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=['owner', 'manager']
        ).exists()
    except Exception:
        return False


def manager_required(view_func):
    """
    Decorator to restrict view access to managers and staff users only.

    Usage:
        @technician_required
        @manager_required
        def my_manager_view(request):
            # View logic here

    Permissions:
        - Staff users (is_staff=True) can always access
        - Technicians with is_manager=True can access
        - All others are redirected with error message
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Staff users always have access
        if request.user.is_staff:
            return view_func(request, *args, **kwargs)

        # Check if user has technician profile with manager status
        if hasattr(request.user, 'technician'):
            technician = request.user.technician
            if technician and technician.is_manager:
                return view_func(request, *args, **kwargs)

        # Access denied
        messages.warning(request, "This page requires manager privileges.")
        return redirect('technician_dashboard')

    return _wrapped_view

# Add a helper function to safely check if a user has technician access
def has_technician_access(user):
    """Helper function to check if a user has technician access through profile or admin privileges"""
    # Admin users always have access
    if user.is_staff:
        return True

    # Check if user is in the Technicians group
    if user.groups.filter(name='Technicians').exists():
        return True

    # Non-admin users need a technician profile
    try:
        return hasattr(user, 'technician') and user.technician is not None
    except:
        return False

def is_working_manager(user):
    """
    Helper function to check if a user is a working manager.
    A working manager is someone who:
    1. Has a technician profile AND
    2. Has is_manager=True flag

    This allows them to both assign work AND complete repairs themselves.
    """
    if not hasattr(user, 'technician'):
        return False
    try:
        technician = user.technician
        return technician is not None and technician.is_manager
    except:
        return False

# Custom decorator to ensure only technicians can access views
def technician_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access the technician portal.")
            return redirect('login')
        
        # Check if user has technician access
        if has_technician_access(request.user):
            return view_func(request, *args, **kwargs)
            
        # User doesn't have access
        messages.warning(request, "Your account does not have technician access. Please contact an administrator if you believe this is an error.")
        return redirect('home')
    return _wrapped_view

# Admin required decorator
def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access this feature.")
            return redirect('login')
        
        # Check if user is admin
        if not request.user.is_staff:
            messages.warning(request, "This action requires administrator privileges.")
            return redirect('technician_dashboard')
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view