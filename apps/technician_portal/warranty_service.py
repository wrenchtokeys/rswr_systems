"""
WarrantyService — business logic for warranty assignment, validation, and queries.

All methods enforce tenant scoping and use select_for_update() for state mutations.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


class WarrantyService:
    """Service layer for warranty operations on Repair objects."""

    @staticmethod
    def get_service_type(service):
        """'repairs' or 'replacements' — the applies_to bucket for a service."""
        return 'replacements' if type(service).__name__ == 'Replacement' else 'repairs'

    @staticmethod
    def assign_warranty(service, policy=None):
        """
        Assign a warranty to a completed repair or replacement.

        Args:
            service: Repair or Replacement instance (must be COMPLETED).
            policy: Optional WarrantyPolicy. If None, uses the tenant's policy
                    for the service type (per-customer override wins).

        Returns:
            The updated service instance.

        Raises:
            ValueError: If service is not COMPLETED or no policy can be found.
        """
        from apps.technician_portal.models import WarrantyPolicy

        service_type = WarrantyService.get_service_type(service)

        if service.queue_status != 'COMPLETED':
            raise ValueError(
                f"Cannot assign warranty to {service_type[:-1]} pk={service.pk} — "
                f"status is '{service.queue_status}', must be COMPLETED."
            )

        if policy is None:
            # Per-customer override wins over the tenant-wide policy
            if service.customer_id:
                policy = WarrantyPolicy.objects.filter(
                    tenant=service.tenant,
                    customer=service.customer,
                    is_active=True,
                    applies_to=service_type,
                ).first()

            if not policy:
                policy = WarrantyPolicy.objects.filter(
                    tenant=service.tenant,
                    customer__isnull=True,
                    is_active=True,
                    applies_to=service_type,
                ).first()

        if not policy:
            raise ValueError(
                f"No active warranty policy found for tenant "
                f"'{service.tenant}' and service type '{service_type}'."
            )

        if policy.duration_type == 'none':
            # Policy explicitly says no warranty
            return service

        with transaction.atomic():
            locked_service = (
                type(service).objects.select_for_update()
                .get(pk=service.pk)
            )

            locked_service.warranty_policy = policy
            completion_date = locked_service.service_date or timezone.now()
            locked_service.warranty_expires_at = policy.get_expiry_date(completion_date)
            locked_service.save(update_fields=[
                'warranty_policy', 'warranty_expires_at',
            ])

        # Refresh the caller's instance
        service.refresh_from_db()

        logger.info(
            "Warranty assigned: %s pk=%s, policy='%s', expires=%s",
            service_type[:-1], service.pk, policy.name, service.warranty_expires_at,
        )
        return service

    @staticmethod
    def get_active_warranty(repair):
        """
        Return warranty info dict for a repair, or None if no warranty.

        Returns:
            dict with keys: policy_name, coverage_description, expires_at,
            is_lifetime, days_remaining, is_active.
            Or None if no warranty is set.
        """
        if not repair.warranty_policy_id:
            return None

        is_lifetime = repair.warranty_expires_at is None
        is_voided = repair.warranty_void
        now = timezone.now()

        if is_lifetime:
            is_active = not is_voided
            days_remaining = None
        elif repair.warranty_expires_at:
            is_active = (not is_voided) and (repair.warranty_expires_at > now)
            days_remaining = max(0, (repair.warranty_expires_at - now).days) if is_active else 0
        else:
            is_active = False
            days_remaining = 0

        return {
            'policy_name': repair.warranty_policy.name,
            'coverage_description': repair.warranty_policy.coverage_description,
            'expires_at': repair.warranty_expires_at,
            'is_lifetime': is_lifetime,
            'days_remaining': days_remaining,
            'is_active': is_active,
            'is_voided': is_voided,
            'void_reason': repair.warranty_void_reason,
        }

    @staticmethod
    def void_warranty(repair, reason, voided_by_user=None):
        """
        Void a repair's warranty with a reason.

        Args:
            repair: Repair instance.
            reason: String explaining why the warranty is voided.
            voided_by_user: Optional User who voided the warranty (for audit).

        Returns:
            The updated Repair instance.

        Raises:
            ValueError: If repair has no warranty or is already voided.
        """
        from apps.technician_portal.models import Repair

        if not repair.warranty_policy_id:
            raise ValueError(
                f"Cannot void warranty on repair pk={repair.pk} — no warranty assigned."
            )
        if repair.warranty_void:
            raise ValueError(
                f"Warranty on repair pk={repair.pk} is already voided."
            )
        if not reason or not reason.strip():
            raise ValueError("A reason is required to void a warranty.")

        with transaction.atomic():
            locked_repair = (
                Repair.objects.select_for_update()
                .get(pk=repair.pk)
            )
            locked_repair.warranty_void = True
            locked_repair.warranty_void_reason = reason.strip()
            locked_repair.save(update_fields=[
                'warranty_void', 'warranty_void_reason',
            ])

        repair.refresh_from_db()

        logger.info(
            "Warranty voided: repair pk=%s, reason='%s', by user=%s",
            repair.pk, reason, voided_by_user,
        )
        return repair

    @staticmethod
    def check_warranty_valid(repair):
        """
        Check if a repair's warranty is currently valid.

        Returns:
            bool — True if warranty is active, not voided, and not expired.
        """
        if not repair.warranty_policy_id:
            return False
        if repair.warranty_void:
            return False
        # Lifetime warranty (expires_at is None with a policy)
        if repair.warranty_expires_at is None:
            return True
        return repair.warranty_expires_at > timezone.now()

    @staticmethod
    def get_warranties_expiring_soon(tenant, days=30):
        """
        Return a QuerySet of repairs with warranties expiring within `days` days.

        Only returns repairs with non-voided, non-lifetime warranties.
        """
        from apps.technician_portal.models import Repair

        now = timezone.now()
        cutoff = now + timedelta(days=days)
        return Repair.objects.filter(
            tenant=tenant,
            warranty_policy__isnull=False,
            warranty_void=False,
            warranty_expires_at__isnull=False,
            warranty_expires_at__gt=now,
            warranty_expires_at__lte=cutoff,
        ).select_related('warranty_policy', 'customer', 'technician__user')

    @staticmethod
    def get_all_warranty_repairs(tenant):
        """
        Return a QuerySet of all repairs with active warranties for a tenant.

        Includes lifetime warranties (expires_at=None) and non-expired timed
        warranties. Excludes voided warranties.
        """
        from apps.technician_portal.models import Repair

        now = timezone.now()
        return Repair.objects.filter(
            tenant=tenant,
            warranty_policy__isnull=False,
            warranty_void=False,
        ).filter(
            Q(warranty_expires_at__isnull=True) |
            Q(warranty_expires_at__gt=now)
        ).select_related('warranty_policy', 'customer', 'technician__user')

    STATS_CACHE_KEY = 'warranty_stats_{tenant_pk}'
    STATS_CACHE_TTL = 3600  # 1 hour

    @staticmethod
    def get_warranty_stats(tenant, period_days=30, use_cache=True):
        """
        Warranty analytics for the owner dashboard.

        Returns cached stats (1-hour TTL) unless use_cache=False.
        """
        from apps.technician_portal.models import Repair

        cache_key = WarrantyService.STATS_CACHE_KEY.format(tenant_pk=tenant.pk)
        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        cutoff = timezone.now() - timedelta(days=period_days)

        claims = Repair.objects.filter(
            tenant=tenant,
            is_warranty_claim=True,
            service_date__gte=cutoff,
        )

        total_repairs = Repair.objects.filter(
            tenant=tenant,
            queue_status='COMPLETED',
            service_date__gte=cutoff,
        ).count()

        stats = {
            'claims_this_period': claims.count(),
            'total_repairs': total_repairs,
            'warranty_rate': round(
                (claims.count() / total_repairs * 100) if total_repairs else 0, 1
            ),
            'by_technician': list(claims.values(
                'technician__user__first_name',
            ).annotate(count=Count('id')).order_by('-count')),
            'by_damage_type': list(claims.values(
                'damage_type',
            ).annotate(count=Count('id')).order_by('-count')),
        }

        cache.set(cache_key, stats, WarrantyService.STATS_CACHE_TTL)
        return stats
