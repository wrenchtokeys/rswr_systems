"""
Usage Tracking Service

Tracks tenant resource usage against their subscription plan limits.
Called directly from the views that create repairs, technicians and
customers, and by the /api/tenants/usage/ endpoint.

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum

logger = logging.getLogger(__name__)


class UsageService:
    """
    Measures a tenant's current resource usage and checks plan limits.
    
    Usage:
        usage = UsageService(tenant)
        summary = usage.get_summary()
        can_create, msg = usage.can_create_repair()
    """
    
    def __init__(self, tenant):
        self.tenant = tenant
        self.plan = self._resolve_plan(tenant)

    @staticmethod
    def _resolve_plan(tenant):
        """Find the tenant's plan, falling back rather than giving up.

        `Tenant.subscription_plan` is a SET_NULL FK, and every limit check
        below used to return "allowed" when it was None -- so a null FK meant
        unlimited everything, silently. That is reachable by deleting a
        SubscriptionPlan row, and by any tenant created before seed_plans was
        run. Fall back to the plan matching `tenant.plan`, then to trial.
        """
        from apps.tenants.models import SubscriptionPlan

        if tenant.subscription_plan_id:
            return tenant.subscription_plan
        return (
            SubscriptionPlan.objects.filter(slug=tenant.plan).first()
            or SubscriptionPlan.objects.filter(slug='trial').first()
        )

    # ------------------------------------------------------------------
    # Remaining-quota helpers
    # ------------------------------------------------------------------

    def remaining_repairs(self):
        """Jobs left this month, or None when unlimited."""
        if self.tenant.is_platform_owner or not self.plan:
            return None
        limit = self.plan.max_repairs_per_month
        if limit is None:
            return None
        return max(0, limit - self.count_repairs_this_month())

    def can_create_repairs(self, count):
        """Quantity-aware version of can_create_repair.

        The binary "are you at the cap?" check let a batch overshoot: a
        tenant at 199/200 passed the gate and then created up to
        MAX_BREAKS_PER_UNIT (20) rows in one request, landing at 219.
        Callers creating N rows must ask for N.
        """
        if count <= 1:
            return self.can_create_repair()

        remaining = self.remaining_repairs()
        if remaining is None:
            return True, ""
        if remaining >= count:
            return True, ""

        if remaining == 0:
            return False, (
                f"Your {self.plan.name} plan allows "
                f"{self.plan.max_repairs_per_month} jobs/month and you've "
                f"used them all. Upgrade to Pro for unlimited jobs."
            )
        return False, (
            f"This would create {count} jobs but your {self.plan.name} plan "
            f"has only {remaining} left this month. Reduce the number of "
            f"breaks or upgrade to Pro for unlimited jobs."
        )

    def check_against_plan(self, plan):
        """Which of `plan`'s limits this tenant already exceeds.

        Used as a downgrade pre-flight. Returns a list of human-readable
        violations; empty means the downgrade is safe.

        Deliberately ignores max_repairs_per_month: the monthly count is
        historical and cannot be reduced, so blocking on it would trap a
        busy shop on an expensive plan until the calendar turned over.
        """
        violations = []
        if plan is None or self.tenant.is_platform_owner:
            return violations

        if plan.max_technicians is not None:
            used = self.count_active_technicians()
            if used > plan.max_technicians:
                violations.append(
                    f"You have {used} active technicians but {plan.name} "
                    f"allows {plan.max_technicians}. Deactivate "
                    f"{used - plan.max_technicians} before downgrading."
                )

        if plan.max_customers is not None:
            used = self.count_customers()
            if used > plan.max_customers:
                violations.append(
                    f"You have {used} customers but {plan.name} allows "
                    f"{plan.max_customers}."
                )

        return violations
    
    # ------------------------------------------------------------------
    # Counting methods
    # ------------------------------------------------------------------
    
    def count_repairs_this_month(self):
        """Count repairs (and replacements) created this calendar month."""
        from apps.technician_portal.models import Repair, Replacement
        
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        repairs = Repair.objects.filter(
            tenant=self.tenant,
            service_date__gte=month_start,
        ).count()
        
        replacements = Replacement.objects.filter(
            tenant=self.tenant,
            service_date__gte=month_start,
        ).count()
        
        return repairs + replacements
    
    def count_active_technicians(self):
        """Count active technicians for this tenant.

        A technician is only counted if BOTH the Technician record AND
        the underlying user account are active.  Deactivated technicians
        (tech.is_active=False) must not consume plan seats so shop owners
        can swap seasonal staff without hitting artificial seat limits.
        """
        from apps.technician_portal.models import Technician
        return Technician.objects.filter(
            tenant=self.tenant,
            is_active=True,
            user__is_active=True,
        ).count()
    
    def count_customers(self):
        """Count customer accounts for this tenant."""
        from core.models import Customer
        return Customer.objects.filter(tenant=self.tenant).count()
    
    def calculate_storage_mb(self):
        """Estimate storage used by the tenant in MB.

        Counts photo file sizes from repairs/replacements.

        NOT reported in get_summary and NOT enforced anywhere. It walks every
        photo and touches .size, which is one S3 HEAD request per object --
        unaffordable on a dashboard load, for a limit no tenant has ever
        approached. get_summary used to report a hardcoded `storage_used = 0`,
        i.e. a permanent 0% gauge that told the owner nothing true. Kept for
        ad-hoc use; wire it to a background job if a real quota is needed.
        """
        from apps.technician_portal.models import Repair, Replacement
        
        # Sum up photo file sizes (stored as ImageField)
        total_bytes = 0
        
        for Model in [Repair, Replacement]:
            # Get all image fields
            image_fields = [
                f.name for f in Model._meta.get_fields()
                if hasattr(f, 'get_internal_type') and f.get_internal_type() == 'FileField'
            ]
            
            for field_name in image_fields:
                qs = Model.objects.filter(tenant=self.tenant).exclude(
                    **{field_name: ''}
                ).exclude(**{field_name: None})
                
                for obj in qs.only(field_name).iterator():
                    try:
                        f = getattr(obj, field_name)
                        if f and hasattr(f, 'size'):
                            total_bytes += f.size
                    except Exception:
                        # File might not exist in storage
                        pass
        
        return round(total_bytes / (1024 * 1024), 1)
    
    # ------------------------------------------------------------------
    # Limit checks
    # ------------------------------------------------------------------
    
    def can_create_repair(self):
        """
        Check if the tenant can create another repair this month.
        Returns (allowed: bool, message: str).
        """
        if self.tenant.is_platform_owner:
            return True, ""
        if not self.plan:
            return True, ""
        
        limit = self.plan.max_repairs_per_month
        if limit is None:
            return True, ""
        
        used = self.count_repairs_this_month()
        if used >= limit:
            return False, (
                f"Your {self.plan.name} plan allows {limit} jobs/month. "
                f"You've used {used}. Upgrade to Pro for unlimited jobs."
            )
        
        return True, ""
    
    def can_add_technician(self):
        """
        Check if the tenant can add another technician.
        Returns (allowed: bool, message: str).
        """
        if self.tenant.is_platform_owner:
            return True, ""
        if not self.plan:
            return True, ""
        
        limit = self.plan.max_technicians
        if limit is None:
            return True, ""
        
        used = self.count_active_technicians()
        if used >= limit:
            return False, (
                f"Your {self.plan.name} plan allows {limit} technicians. "
                f"You have {used}. Upgrade your plan for more technician seats."
            )
        
        return True, ""
    
    def can_add_customer(self):
        """
        Check if the tenant can add another customer.
        Returns (allowed: bool, message: str).
        """
        if self.tenant.is_platform_owner:
            return True, ""
        if not self.plan:
            return True, ""
        
        limit = self.plan.max_customers
        if limit is None:
            return True, ""
        
        used = self.count_customers()
        if used >= limit:
            return False, (
                f"Your {self.plan.name} plan allows {limit} customers. "
                f"You have {used}. Upgrade your plan for more customer accounts."
            )
        
        return True, ""
    
    def is_within_limits(self):
        """
        Check all limits at once. Returns (all_ok: bool, messages: list[str]).
        """
        messages = []
        
        ok, msg = self.can_create_repair()
        if not ok:
            messages.append(msg)
        
        ok, msg = self.can_add_technician()
        if not ok:
            messages.append(msg)
        
        ok, msg = self.can_add_customer()
        if not ok:
            messages.append(msg)
        
        return len(messages) == 0, messages
    
    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    
    def _usage_percentage(self, used, limit):
        """Calculate usage percentage. Returns None if unlimited.

        Clamped to 100 — over-limit tenants (e.g. 7 techs on a 2-tech plan,
        grandfathered before a downgrade) fed raw >100% widths straight into
        the dashboard progress bars, which overflowed the card.
        """
        if limit is None:
            return None
        if limit == 0:
            return 100.0
        return min(100.0, round((used / limit) * 100, 1))
    
    def get_summary(self):
        """
        Full usage summary with counts, limits, and percentages.
        
        Returns dict like:
        {
            "repairs": {"used": 45, "limit": 200, "percent": 22.5},
            "technicians": {"used": 3, "limit": 5, "percent": 60.0},
            "customers": {"used": 12, "limit": 50, "percent": 24.0},
            "plan": "Starter",
            "trial_days_remaining": null,
        }
        """
        repairs_used = self.count_repairs_this_month()
        techs_used = self.count_active_technicians()
        customers_used = self.count_customers()
        
        plan_name = self.plan.name if self.plan else "No Plan"
        repair_limit = self.plan.max_repairs_per_month if self.plan else None
        tech_limit = self.plan.max_technicians if self.plan else None
        cust_limit = self.plan.max_customers if self.plan else None
        
        return {
            "repairs": {
                "used": repairs_used,
                "limit": repair_limit,
                "percent": self._usage_percentage(repairs_used, repair_limit),
            },
            "technicians": {
                "used": techs_used,
                "limit": tech_limit,
                "percent": self._usage_percentage(techs_used, tech_limit),
            },
            "customers": {
                "used": customers_used,
                "limit": cust_limit,
                "percent": self._usage_percentage(customers_used, cust_limit),
            },
            "plan": plan_name,
            "subscription_status": self.tenant.subscription_status,
            "trial_days_remaining": (
                self.tenant.trial_days_remaining
                if self.tenant.plan == 'trial' else None
            ),
        }
