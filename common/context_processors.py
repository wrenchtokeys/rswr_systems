"""
Common context processors for templates.
"""


def portal_access(request):
    """Add portal access flags to template context."""
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {}

    user = request.user
    ctx = {}

    # Check technician access (cached on request to avoid repeat queries)
    if not hasattr(request, '_has_tech_access'):
        from apps.technician_portal.decorators import has_technician_access
        request._has_tech_access = has_technician_access(user)
    ctx['has_tech_access'] = request._has_tech_access

    # Check owner/manager access
    if not hasattr(request, '_is_owner_or_manager'):
        if user.is_staff:
            request._is_owner_or_manager = True
        else:
            try:
                from apps.tenants.models import TenantMembership
                request._is_owner_or_manager = TenantMembership.objects.filter(
                    user=user, is_active=True, role__in=['owner', 'manager']
                ).exists()
            except Exception:
                request._is_owner_or_manager = False
    ctx['is_owner_or_manager'] = request._is_owner_or_manager

    return ctx
