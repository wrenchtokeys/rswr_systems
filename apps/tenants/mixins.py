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


class PlanEnforcementMixin:
    """
    Mixin that enforces subscription plan limits before creating objects.
    
    Checks:
    1. Trial expiry — expired trial tenants are read-only
    2. Resource limits — repairs/month, technicians, customers
    
    Usage for DRF views:
        class RepairCreateView(PlanEnforcementMixin, CreateAPIView):
            resource_type = 'repair'  # or 'technician' or 'customer'
    
    Usage for Django CBVs:
        class RepairCreateView(PlanEnforcementMixin, CreateView):
            resource_type = 'repair'
    
    Set resource_type to one of: 'repair', 'technician', 'customer'
    """
    
    resource_type = None  # Must be set: 'repair', 'technician', 'customer'
    
    def _check_plan_limits(self, request):
        """
        Check plan limits for the current tenant.
        Returns (allowed: bool, error_response: dict or None)
        """
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return True, None  # No tenant context = no limits to enforce

        # Platform owners are always exempt from all limits
        if tenant.is_platform_owner:
            return True, None

        # Check trial expiry
        if tenant.plan == 'trial' and tenant.is_trial_expired:
            return False, {
                'error': 'trial_expired',
                'message': (
                    'Your free trial has expired. '
                    'Please subscribe to a plan to continue using RS Systems.'
                ),
                'upgrade_url': '/api/tenants/subscribe/',
            }
        
        # Check subscription status
        if tenant.subscription_status == 'expired':
            return False, {
                'error': 'subscription_expired',
                'message': (
                    'Your subscription has expired. '
                    'Please renew to continue using RS Systems.'
                ),
                'upgrade_url': '/api/tenants/subscribe/',
            }
        
        # Check resource-specific limits
        if not self.resource_type or not tenant.subscription_plan:
            return True, None
        
        from apps.tenants.services.usage_service import UsageService
        usage = UsageService(tenant)
        
        check_methods = {
            'repair': usage.can_create_repair,
            'technician': usage.can_add_technician,
            'customer': usage.can_add_customer,
        }
        
        check = check_methods.get(self.resource_type)
        if check:
            allowed, message = check()
            if not allowed:
                return False, {
                    'error': 'plan_limit_reached',
                    'message': message,
                    'resource_type': self.resource_type,
                    'upgrade_url': '/api/tenants/subscribe/',
                }
        
        return True, None
    
    def check_permissions(self, request):
        """Override for DRF views — check plan limits before other permissions."""
        super().check_permissions(request)
        
        # Only enforce on create/write operations
        if request.method in ('POST', 'PUT', 'PATCH'):
            allowed, error = self._check_plan_limits(request)
            if not allowed:
                from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
                raise DRFPermissionDenied(detail=error)
    
    def dispatch(self, request, *args, **kwargs):
        """Override for Django CBVs — check plan limits on POST."""
        if request.method == 'POST':
            allowed, error = self._check_plan_limits(request)
            if not allowed:
                return JsonResponse(error, status=403)
        
        return super().dispatch(request, *args, **kwargs)


def check_plan_limit(tenant, resource_type):
    """
    Functional helper for checking plan limits in function-based views.
    
    Usage:
        allowed, error = check_plan_limit(request.tenant, 'repair')
        if not allowed:
            return JsonResponse(error, status=403)
    
    Args:
        tenant: Tenant instance (or None)
        resource_type: 'repair', 'technician', or 'customer'
        
    Returns:
        (allowed: bool, error: dict or None)
    """
    if not tenant:
        return True, None

    # Platform owners are always exempt from all limits
    if tenant.is_platform_owner:
        return True, None

    # Check trial expiry
    if tenant.plan == 'trial' and tenant.is_trial_expired:
        return False, {
            'error': 'trial_expired',
            'message': (
                'Your free trial has expired. '
                'Please subscribe to a plan to continue using RS Systems.'
            ),
            'upgrade_url': '/api/tenants/subscribe/',
        }
    
    # Check subscription status
    if tenant.subscription_status == 'expired':
        return False, {
            'error': 'subscription_expired',
            'message': (
                'Your subscription has expired. '
                'Please renew to continue using RS Systems.'
            ),
            'upgrade_url': '/api/tenants/subscribe/',
        }
    
    if not tenant.subscription_plan:
        return True, None
    
    from apps.tenants.services.usage_service import UsageService
    usage = UsageService(tenant)
    
    check_methods = {
        'repair': usage.can_create_repair,
        'technician': usage.can_add_technician,
        'customer': usage.can_add_customer,
    }
    
    check = check_methods.get(resource_type)
    if check:
        allowed, message = check()
        if not allowed:
            return False, {
                'error': 'plan_limit_reached',
                'message': message,
                'resource_type': resource_type,
                'upgrade_url': '/api/tenants/subscribe/',
            }
    
    return True, None
