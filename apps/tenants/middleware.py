"""
Tenant Middleware

Determines the current tenant for each request and sets request.tenant.

Resolution order:
1. X-Tenant-Slug header (for API clients)
2. Session-stored tenant_id (for portal users)
3. User's first active TenantMembership (fallback)

Future: subdomain-based routing (rockstar.rssystems.com)
"""

import logging
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class TenantMiddleware(MiddlewareMixin):
    """
    Sets request.tenant based on available context.
    
    Non-blocking: if no tenant can be determined, request.tenant = None.
    Views/APIs that require a tenant should check and return 403 if missing.
    """
    
    def process_request(self, request):
        request.tenant = None
        
        # Skip for unauthenticated requests and admin
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return None
        
        if request.path.startswith('/admin/'):
            return None
        
        # 1. Check X-Tenant-Slug header (API clients)
        tenant_slug = request.META.get('HTTP_X_TENANT_SLUG')
        if tenant_slug:
            tenant = self._get_tenant_by_slug(tenant_slug, request.user)
            if tenant:
                request.tenant = tenant
                return None
        
        # 2. Check session
        tenant_id = request.session.get('tenant_id')
        if tenant_id:
            tenant = self._get_tenant_by_id(tenant_id, request.user)
            if tenant:
                request.tenant = tenant
                return None
            else:
                # Stale session value — clear it
                del request.session['tenant_id']
        
        # 3. Fallback: user's first active membership
        tenant = self._get_default_tenant(request.user)
        if tenant:
            request.tenant = tenant
            request.session['tenant_id'] = tenant.id
            return None
        
        # 4. Fallback: customer portal users (have CustomerUser, not TenantMembership)
        tenant = self._get_customer_tenant(request.user)
        if tenant:
            request.tenant = tenant
            request.session['tenant_id'] = tenant.id
        
        return None
    
    def _get_tenant_by_slug(self, slug, user):
        """Resolve tenant by slug, verifying user has access."""
        from apps.tenants.models import Tenant, TenantMembership
        try:
            tenant = Tenant.objects.get(slug=slug, is_active=True)
            # Superusers get access to everything
            if user.is_superuser:
                return tenant
            # Check membership
            if TenantMembership.objects.filter(
                tenant=tenant, user=user, is_active=True
            ).exists():
                return tenant
        except Tenant.DoesNotExist:
            pass
        return None
    
    def _get_tenant_by_id(self, tenant_id, user):
        """Resolve tenant by ID, verifying user has access."""
        from apps.tenants.models import Tenant, TenantMembership
        try:
            tenant = Tenant.objects.get(id=tenant_id, is_active=True)
            if user.is_superuser:
                return tenant
            if TenantMembership.objects.filter(
                tenant=tenant, user=user, is_active=True
            ).exists():
                return tenant
        except Tenant.DoesNotExist:
            pass
        return None
    
    def _get_customer_tenant(self, user):
        """Get tenant from CustomerUser record (for customer portal users)."""
        try:
            from apps.customer_portal.models import CustomerUser
            cu = CustomerUser.objects.select_related('customer__tenant').filter(
                user=user,
                customer__tenant__is_active=True,
            ).first()
            if cu and cu.customer and cu.customer.tenant:
                return cu.customer.tenant
        except Exception:
            logger.exception("Unexpected error resolving tenant from CustomerUser for user=%s", user.pk if user else None)
        return None

    def _get_default_tenant(self, user):
        """Get the user's first active tenant membership."""
        from apps.tenants.models import TenantMembership
        membership = (
            TenantMembership.objects
            .filter(user=user, is_active=True, tenant__is_active=True)
            .select_related('tenant')
            .first()
        )
        if membership:
            return membership.tenant
        return None
