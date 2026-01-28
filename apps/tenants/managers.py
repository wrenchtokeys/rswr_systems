"""
Tenant-scoped QuerySet and Manager.

TenantManager automatically filters querysets by the current tenant
when accessed through views that set request.tenant.

Usage in models:
    class Customer(models.Model):
        tenant = models.ForeignKey(Tenant, ...)
        objects = TenantManager()

Usage in views:
    # Automatically scoped if using TenantQuerysetMixin
    Customer.objects.tenant_filter(tenant).all()
"""

from django.db import models


class TenantQuerySet(models.QuerySet):
    """QuerySet that supports tenant filtering."""
    
    def for_tenant(self, tenant):
        """Filter queryset to a specific tenant."""
        if tenant is None:
            return self
        return self.filter(tenant=tenant)


class TenantManager(models.Manager):
    """Manager that provides tenant-scoped queries."""
    
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)
    
    def for_tenant(self, tenant):
        """Convenience method: filter by tenant."""
        return self.get_queryset().for_tenant(tenant)
