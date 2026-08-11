"""
Tenant View Mixins

Provides mixins for Django views to:
- Automatically scope querysets to the current tenant
- Enforce subscription plan limits on create operations
- Block writes for expired trials

Author: Amelia (Clawdbot AI)
"""

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse


class TenantQuerysetMixin:
    """
    Mixin for Django class-based views that auto-filters querysets by tenant.
    
    Usage:
        class CustomerListView(TenantQuerysetMixin, ListView):
            model = Customer
    
    The queryset will be filtered to only show objects belonging to
    request.tenant. If no tenant is set, raises PermissionDenied.
    """
    
    tenant_field = 'tenant'  # Override if FK is named differently
    require_tenant = True  # Set False to allow views without tenant
    
    def get_queryset(self):
        qs = super().get_queryset()
        tenant = getattr(self.request, 'tenant', None)
        
        if tenant is None:
            if self.require_tenant:
                raise PermissionDenied("No tenant context. Cannot access data.")
            return qs
        
        return qs.filter(**{self.tenant_field: tenant})
    
    def get_tenant(self):
        """Convenience method to get current tenant."""
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None and self.require_tenant:
            raise PermissionDenied("No tenant context.")
        return tenant


class TenantCreateMixin:
    """
    Mixin that auto-sets the tenant FK when creating objects.
    
    Usage:
        class CustomerCreateView(TenantCreateMixin, CreateView):
            model = Customer
    """
    
    tenant_field = 'tenant'
    
    def form_valid(self, form):
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None:
            raise PermissionDenied("No tenant context. Cannot create objects.")
        
        setattr(form.instance, self.tenant_field, tenant)
        return super().form_valid(form)


# ----------------------------------------------------------------------
# PlanEnforcementMixin and check_plan_limit() were deleted here.
#
# Neither had a single production caller -- every real enforcement site
# is a direct UsageService call in a view. They also carried a THIRD
# copy of the limit logic, including the same bug UsageService had:
# `if not tenant.subscription_plan: return True` meant a null plan FK
# granted unlimited everything. Dead code that silently disagrees with
# the live implementation is worse than no code.
#
# Enforce limits with UsageService directly:
#     allowed, msg = UsageService(tenant).can_create_repair()
# ----------------------------------------------------------------------
