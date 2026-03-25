"""
common/models.py — Platform-wide abstract base models.

These base classes define patterns that recur across the codebase.
New per-tenant config models MUST inherit from TenantConfig.
"""
import logging

from django.db import models

logger = logging.getLogger(__name__)


class TenantConfig(models.Model):
    """
    Abstract base class for all per-tenant configuration models.

    Every tenant config model should:
    - Inherit from TenantConfig
    - Have a unique related_name (auto-generated from class name)
    - Override get_for_tenant() if custom defaults are needed

    Usage:
        class MyConfig(TenantConfig):
            some_field = models.CharField(...)

            class Meta(TenantConfig.Meta):
                verbose_name = "My Configuration"

        config = MyConfig.get_for_tenant(tenant)
    """
    tenant = models.OneToOneField(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="%(class)s",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @classmethod
    def get_for_tenant(cls, tenant):
        """
        Fetch or create the config record for a tenant.

        Always returns a config object. Uses get_or_create to ensure
        exactly one record per tenant.
        """
        obj, _created = cls.objects.get_or_create(tenant=tenant)
        return obj
