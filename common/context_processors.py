"""
Common context processors for templates.

Provides portal access flags and per-area permission flags to all templates.
"""
from common.auth import can_access, get_user_role


def portal_access(request):
    """Add portal access flags and per-area permission flags to template context.

    Template variables:
        has_tech_access       – True if user can access tech portal (repairs or customers)
        is_owner_or_manager   – True if user is owner/manager/superuser/staff
        user_role             – 'superuser', 'owner', 'manager', 'technician', 'viewer', 'customer', or None
        user_can_repairs      – True if user can access repairs area
        user_can_customers    – True if user can access customers area
        user_can_invoices     – True if user can access invoices area
        user_can_reports      – True if user can access reports area
        user_can_team         – True if user can access team management area
        user_can_settings     – True if user can access settings area
        subscription_grace_period – True if tenant is in read-only grace period
        grace_days_remaining  – Days remaining in grace period (0 if not in grace period)
    """
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {}

    user = request.user
    tenant = getattr(request, 'tenant', None)

    # Compute per-area permissions
    repairs = can_access(user, 'repairs', tenant)
    customers = can_access(user, 'customers', tenant)
    invoices = can_access(user, 'invoices', tenant)
    reports = can_access(user, 'reports', tenant)
    team = can_access(user, 'team', tenant)
    settings = can_access(user, 'settings', tenant)

    role = get_user_role(user, tenant)

    # Grace period context (set by SubscriptionEnforcementMiddleware on GETs)
    in_grace_period = getattr(request, 'subscription_grace_period', False)
    grace_days = getattr(request, 'grace_days_remaining', 0)

    return {
        # Legacy flags (still used by some templates)
        'has_tech_access': repairs or customers,
        'is_owner_or_manager': role in ('superuser', 'owner', 'manager'),

        # New per-area flags
        'user_role': role,
        'user_can_repairs': repairs,
        'user_can_customers': customers,
        'user_can_invoices': invoices,
        'user_can_reports': reports,
        'user_can_team': team,
        'user_can_settings': settings,

        # Subscription grace period info
        'subscription_grace_period': in_grace_period,
        'grace_days_remaining': grace_days,
    }
