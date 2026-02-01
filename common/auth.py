"""
Unified Permission System for RS Systems.

Single source of truth for all access control decisions.
Replaces: technician_required, admin_required, manager_required,
owner_or_manager_required, has_technician_access, is_tenant_admin,
is_staff/is_superuser checks, and Technicians group checks.

Author: Amelia (Clawdbot AI)
"""

import logging
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

logger = logging.getLogger(__name__)

# Areas that can be checked
AREAS = ('repairs', 'customers', 'invoices', 'reports', 'team', 'settings')

# Role → allowed areas mapping
ROLE_PERMISSIONS = {
    'owner': AREAS,  # all areas
    'manager': AREAS,  # all areas
    'technician': ('repairs', 'customers'),
    'viewer': (),  # customer portal only — no internal areas
}


def _get_membership(user, tenant=None):
    """Get the user's TenantMembership, resolving tenant if needed."""
    from apps.tenants.models import TenantMembership

    if tenant:
        return TenantMembership.objects.filter(
            user=user, tenant=tenant, is_active=True
        ).first()

    # No tenant given — find highest-privilege membership
    return (
        TenantMembership.objects
        .filter(user=user, is_active=True)
        .order_by(
            # owner=0, manager=1, technician=2, viewer=3
        )
        .first()
    )


def can_access(user, area, tenant=None):
    """
    Can this user access this area?

    Areas: 'repairs', 'customers', 'invoices', 'reports', 'team', 'settings'

    Rules:
    - Superusers: yes to everything
    - Owner/Manager TenantMembership: yes to everything
    - Technician TenantMembership: repairs, customers
    - Viewer TenantMembership: nothing (they're external customers)
    - CustomerUser: customer portal only (no internal areas)
    - No membership: no access

    Args:
        user: Django User instance
        area: string, one of AREAS
        tenant: optional Tenant instance for scoping

    Returns:
        bool
    """
    if area not in AREAS:
        logger.warning(f"can_access called with unknown area: {area}")
        return False

    if not user or not user.is_authenticated:
        return False

    # Superusers bypass everything
    if user.is_superuser:
        return True

    # Django staff gets full access (legacy admin support)
    if user.is_staff:
        return True

    # Look up membership
    membership = _get_membership(user, tenant)
    if not membership:
        return False

    allowed = ROLE_PERMISSIONS.get(membership.role, ())
    return area in allowed


def get_user_role(user, tenant=None):
    """
    Get the user's effective role string.

    Returns: 'superuser', 'owner', 'manager', 'technician', 'viewer',
             'customer', or None
    """
    if not user or not user.is_authenticated:
        return None

    if user.is_superuser:
        return 'superuser'

    if user.is_staff:
        return 'owner'  # staff treated as owner-level

    membership = _get_membership(user, tenant)
    if membership:
        return membership.role

    # Check if they're a CustomerUser without membership
    try:
        from apps.customer_portal.models import CustomerUser
        if CustomerUser.objects.filter(user=user).exists():
            return 'customer'
    except Exception:
        pass

    return None


def redirect_to_portal(user):
    """
    Send user to their correct home page.

    Returns a redirect response.
    """
    if not user or not user.is_authenticated:
        return redirect('login')

    role = get_user_role(user)

    if role in ('superuser', 'owner', 'manager'):
        return redirect('owner_dashboard')
    elif role == 'technician':
        return redirect('technician_dashboard')
    elif role in ('viewer', 'customer'):
        return redirect('customer_dashboard')
    else:
        # Don't redirect back to login for authenticated users (causes loop)
        # Superusers/staff go to admin, everyone else to owner dashboard
        if user.is_staff:
            return redirect('/admin/')
        return redirect('owner_dashboard')


def requires(area):
    """
    Decorator that replaces all existing permission decorators.

    Usage:
        @requires('repairs')
        def create_repair(request): ...

        @requires('invoices')
        def create_invoice(request): ...

        @requires('team')
        def invite_member(request): ...

        @requires('settings')
        def owner_settings(request): ...

    Checks login, then checks can_access(). On failure, redirects
    to the user's correct portal with a message.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Must be logged in
            if not request.user.is_authenticated:
                messages.info(request, "Please log in to access this page.")
                return redirect('login')

            tenant = getattr(request, 'tenant', None)

            if can_access(request.user, area, tenant):
                return view_func(request, *args, **kwargs)

            # Access denied — route to their correct portal
            messages.warning(
                request,
                "You don't have permission to access this page."
            )
            return redirect_to_portal(request.user)

        return _wrapped_view
    return decorator
