"""
Common view decorators for portal access control.

Delegates to common.auth for the single source of truth.
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

from common.auth import can_access, redirect_to_portal


def owner_or_manager_required(view_func):
    """Restrict view to tenant owners and managers (or Django staff/superuser)."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access this page.")
            return redirect('login')

        tenant = getattr(request, 'tenant', None)
        # Owner/manager means access to settings (which requires owner/manager)
        if can_access(request.user, 'settings', tenant):
            return view_func(request, *args, **kwargs)

        messages.warning(request, "You don't have access to the owner dashboard.")
        return redirect_to_portal(request.user)

    return _wrapped_view
