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
    def assign_warranty(repair, policy=None):
        """
        Assign a warranty to a completed repair.

        Args:
            repair: Repair instance (must be COMPLETED).
            policy: Optional WarrantyPolicy. If None, uses the default for
                    the repair's tenant (matched by damage_type first, then
                    the 'all_repairs' default).

        Returns:
            The updated Repair instance.

        Raises:
            ValueError: If repair is not COMPLETED or no policy can be found.
        """
        from apps.technician_portal.models import Repair, WarrantyPolicy

        if repair.queue_status != 'COMPLETED':
            raise ValueError(
                f"Cannot assign warranty to repair pk={repair.pk} — "
                f"status is '{repair.queue_status}', must be COMPLETED."
            )

        if policy is None:
            # Priority: per-customer policy > tenant-wide policy
            # 1. Per-customer, damage-type-specific
            if repair.customer_id:
                policy = WarrantyPolicy.objects.filter(
                    tenant=repair.tenant,
                    customer=repair.customer,
                    is_active=True,
                    applies_to=repair.damage_type,
                ).first()
                # 2. Per-customer, all_repairs
                if not policy:
                    policy = WarrantyPolicy.objects.filter(
                        tenant=repair.tenant,
                        customer=repair.customer,
                        is_active=True,
                        applies_to='all_repairs',
                    ).first()

            # 3. Tenant-wide, damage-type-specific
            if not policy:
                policy = WarrantyPolicy.objects.filter(
                    tenant=repair.tenant,
                    customer__isnull=True,
                    is_active=True,
                    applies_to=repair.damage_type,
                ).first()

            # 4. Tenant-wide, 'all_repairs' default
            if not policy:
                policy = WarrantyPolicy.objects.filter(
                    tenant=repair.tenant,
                    customer__isnull=True,
                    is_active=True,
                    applies_to='all_repairs',
                ).first()

            # 5. Tenant-wide default (customer=None only).
            # Per-customer defaults must NOT bleed over to other customers.
            # Only step 1-2 above may match per-customer policies; this step is
            # strictly a tenant-wide fallback.  (CODE-269)
            if not policy:
                policy = WarrantyPolicy.objects.filter(
                    tenant=repair.tenant,
                    customer__isnull=True,
                    is_active=True,
                    is_default=True,
                ).first()

        if not policy:
            raise ValueError(
                f"No active warranty policy found for tenant "
                f"'{repair.tenant}' and damage type '{repair.damage_type}'."
            )

        if policy.duration_type == 'none':
            # Policy explicitly says no warranty
            return repair

        with transaction.atomic():
            locked_repair = (
                Repair.objects.select_for_update()
                .get(pk=repair.pk)
            )

            locked_repair.warranty_policy = policy
            completion_date = locked_repair.service_date or timezone.now()
            locked_repair.warranty_expires_at = policy.get_expiry_date(completion_date)
            locked_repair.save(update_fields=[
                'warranty_policy', 'warranty_expires_at',
            ])

        # Refresh the caller's instance
        repair.refresh_from_db()

        logger.info(
            "Warranty assigned: repair pk=%s, policy='%s', expires=%s",
            repair.pk, policy.name, repair.warranty_expires_at,
        )
        return repair

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
