"""
Tenant View Mixins

Provides mixins for Django views to automatically scope querysets 
to the current tenant.
"""

from django.core.exceptions import PermissionDenied


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
