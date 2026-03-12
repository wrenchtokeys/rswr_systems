"""
Custom Admin Dashboard for RS Systems.

Overrides the default Django admin index view to show real business metrics:
- Subscription overview (active, trialing, grace period, expired)
- This month's stats (repairs, invoices, revenue, outstanding)
- Recent activity (last 10 repairs, last 5 invoices)
- Quick links to common admin tasks

Author: Amelia
"""

from django.utils import timezone
from django.db.models import Sum, Count, Q


def get_dashboard_context():
    """
    Collect all metrics needed for the admin dashboard.
    Returns a dict that gets merged into the admin index template context.
    Gracefully handles missing models/data.
    """
    ctx = {}

    # -------------------------------------------------------------------------
    # Subscription overview
    # -------------------------------------------------------------------------
    try:
        from apps.tenants.models import Tenant
        now = timezone.now()

        ctx['tenant_active_count'] = Tenant.objects.filter(subscription_status='active').count()
        ctx['tenant_expired_count'] = Tenant.objects.filter(subscription_status='expired').count()
        ctx['tenant_canceled_count'] = Tenant.objects.filter(subscription_status='canceled').count()

        # Trialing - expiring within 7 days
        trial_tenants = Tenant.objects.filter(plan='trial', subscription_status='trialing')
        ctx['tenant_trial_count'] = trial_tenants.count()
        ctx['tenant_trial_expiring_soon'] = sum(
            1 for t in trial_tenants if t.trial_days_remaining <= 7
        )

        # Grace period
        ctx['tenant_grace_count'] = sum(
            1 for t in Tenant.objects.exclude(grace_period_end=None) if t.is_in_grace_period
        )

        ctx['tenant_total'] = Tenant.objects.count()
    except Exception:
        ctx.update({
            'tenant_active_count': 0, 'tenant_expired_count': 0,
            'tenant_canceled_count': 0, 'tenant_trial_count': 0,
            'tenant_trial_expiring_soon': 0, 'tenant_grace_count': 0,
            'tenant_total': 0,
        })

    # -------------------------------------------------------------------------
    # This month's stats
    # -------------------------------------------------------------------------
    try:
        from apps.technician_portal.models import Repair
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        ctx['repairs_this_month'] = Repair.objects.filter(
            service_date__gte=month_start,
            queue_status='COMPLETED'
        ).count()
    except Exception:
        ctx['repairs_this_month'] = 0

    try:
        from apps.billing.models import Invoice
        ctx['invoices_this_month'] = Invoice.objects.filter(
            invoice_date__gte=month_start
        ).count()

        revenue = Invoice.objects.filter(
            invoice_date__gte=month_start,
            status__in=['PAID', 'PARTIAL']
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        ctx['revenue_this_month'] = f"${revenue:,.2f}"

        outstanding = Invoice.objects.filter(
            status__in=['SENT', 'PARTIAL', 'OVERDUE']
        ).aggregate(
            due=Sum('total')
        )['due'] or 0
        ctx['outstanding_balance'] = f"${outstanding:,.2f}"
    except Exception:
        ctx['invoices_this_month'] = 0
        ctx['revenue_this_month'] = '$0.00'
        ctx['outstanding_balance'] = '$0.00'

    # -------------------------------------------------------------------------
    # Recent activity
    # -------------------------------------------------------------------------
    try:
        from apps.technician_portal.models import Repair
        ctx['recent_repairs'] = (
            Repair.objects
            .select_related('customer', 'technician__user', 'tenant')
            .order_by('-service_date')[:10]
        )
    except Exception:
        ctx['recent_repairs'] = []

    try:
        from apps.billing.models import Invoice
        ctx['recent_invoices'] = (
            Invoice.objects
            .select_related('customer')
            .order_by('-invoice_date')[:5]
        )
    except Exception:
        ctx['recent_invoices'] = []

    return ctx
