"""
Admin Mixins for RS Systems — Phase 5: Tenant-Aware Filtering

Provides TenantFilterMixin that makes admin views multi-tenant aware:
- Superusers: see all data across all tenants, plus a tenant list_filter
- Non-superusers: see only their own tenant's data (via TenantMembership)

Author: Amelia
"""


class TenantFilterMixin:
    """
    Mixin for ModelAdmin classes that have a 'tenant' FK.

    Behaviour:
    - Superusers: full access to all data; 'tenant' is added to list_filter
    - Non-superusers: queryset is restricted to the user's active tenant(s)
      via TenantMembership; 'tenant' filter is hidden (would be useless anyway)

    Usage:
        class RepairAdmin(TenantFilterMixin, admin.ModelAdmin):
            tenant_field = 'tenant'          # default — override if path differs
            ...
    """

    # The ORM field path that reaches the Tenant.
    # For direct FKs: 'tenant'
    # For indirect: e.g. 'invoice__customer__tenant'
    tenant_field: str = 'tenant'

    # ------------------------------------------------------------------ helpers

    def _get_user_tenants(self, request):
        """Return a queryset of Tenant objects the current user belongs to."""
        from apps.tenants.models import TenantMembership
        return (
            TenantMembership.objects
            .filter(user=request.user, is_active=True)
            .values_list('tenant', flat=True)
        )

    # ------------------------------------------------------------------ overrides

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        tenant_ids = self._get_user_tenants(request)
        return qs.filter(**{f"{self.tenant_field}__in": tenant_ids})

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if request.user.is_superuser:
            # Add 'tenant' filter for superusers if not already present
            if 'tenant' not in filters and self.tenant_field == 'tenant':
                filters = ['tenant'] + filters
        else:
            # Remove 'tenant' filter for non-superusers
            filters = [f for f in filters if f != 'tenant']
        return filters
