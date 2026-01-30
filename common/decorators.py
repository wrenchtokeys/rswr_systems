"""
Common view decorators for portal access control.
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def owner_or_manager_required(view_func):
    """Restrict view to tenant owners and managers (or Django staff)."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access this page.")
            return redirect('login')

        if request.user.is_staff:
            return view_func(request, *args, **kwargs)

        try:
            from apps.tenants.models import TenantMembership
            if TenantMembership.objects.filter(
                user=request.user, is_active=True, role__in=['owner', 'manager']
            ).exists():
                return view_func(request, *args, **kwargs)
        except Exception:
            pass

        messages.warning(request, "You don't have access to the owner dashboard.")
        # Route to the right place
        try:
            from apps.customer_portal.models import CustomerUser
            if CustomerUser.objects.filter(user=request.user).exists():
                return redirect('customer_dashboard')
        except Exception:
            pass
        try:
            from apps.technician_portal.decorators import has_technician_access
            if has_technician_access(request.user):
                return redirect('technician_dashboard')
        except Exception:
            pass
        return redirect('login')

    return _wrapped_view
