"""
Custom decorators for technician portal views.

These now delegate to common.auth for the single source of truth.
Kept as thin wrappers for backward compatibility during transition.
"""
import logging
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist

from common.auth import can_access, get_user_role, redirect_to_portal

logger = logging.getLogger(__name__)


def is_tenant_admin(user):
    """
    Check if user has admin-level access for their tenant.

    Returns True if user is superuser, staff, owner, or manager.
    """
    role = get_user_role(user)
    return role in ('superuser', 'owner', 'manager')


def has_technician_access(user):
    """Check if a user has technician access (repairs or customers)."""
    if not user or not user.is_authenticated:
        return False
    return can_access(user, 'repairs') or can_access(user, 'customers')


def is_working_manager(user):
    """
    Check if a user is a working manager (has technician profile + is_manager).
    """
    if not hasattr(user, 'technician'):
        return False
    try:
        technician = user.technician
        return technician is not None and technician.is_manager
    except (AttributeError, ObjectDoesNotExist):
        return False


def technician_required(view_func):
    """Decorator: user must be able to access repairs or customers."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access the technician portal.")
            return redirect('login')

        tenant = getattr(request, 'tenant', None)
        if can_access(request.user, 'repairs', tenant) or can_access(request.user, 'customers', tenant):
            return view_func(request, *args, **kwargs)

        messages.warning(
            request,
            "Your account does not have technician access. "
            "Please contact an administrator if you believe this is an error."
        )
        return redirect_to_portal(request.user)

    return _wrapped_view


def manager_required(view_func):
    """Decorator: user must be owner, manager, or staff."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access this feature.")
            return redirect('login')

        if is_tenant_admin(request.user):
            return view_func(request, *args, **kwargs)

        # Also allow technicians with is_manager flag
        if hasattr(request.user, 'technician'):
            try:
                if request.user.technician and request.user.technician.is_manager:
                    return view_func(request, *args, **kwargs)
            except (AttributeError, ObjectDoesNotExist):
                pass
            except Exception as e:
                # Log unexpected errors for debugging
                logger.warning(
                    f"Unexpected error checking manager status for user {request.user.id}: {e}"
                )

        messages.warning(request, "This page requires manager privileges.")
        return redirect_to_portal(request.user)

    return _wrapped_view


def admin_required(view_func):
    """Decorator: user must be staff or owner/manager."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access this feature.")
            return redirect('login')

        if is_tenant_admin(request.user):
            return view_func(request, *args, **kwargs)

        messages.warning(request, "This action requires administrator privileges.")
        return redirect_to_portal(request.user)

    return _wrapped_view
