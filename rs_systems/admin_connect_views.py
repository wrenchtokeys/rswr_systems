"""
Admin views for Stripe Connect accounts and Platform configuration.

Accessible via /admin/connect-accounts/ and /admin/platform-config/.
The admin_site.admin_view wrapper enforces staff-only access; both views
additionally require superuser, because they expose (and in the config
view, mutate) platform-wide financial data: every tenant's Stripe account
status and the platform fee percentages.

Author: Amelia (Clawdbot AI)
"""

import logging
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


def _require_superuser(request):
    if not (request.user.is_active and request.user.is_superuser):
        raise PermissionDenied


def admin_connect_accounts_view(request):
    """
    GET /admin/connect-accounts/

    List all tenants with their Stripe Connect status, account ID,
    and charges/payouts enabled flags. Superuser-only.
    """
    _require_superuser(request)
    from apps.tenants.models import Tenant

    tenants = Tenant.objects.filter(is_active=True).order_by('name').values(
        'id', 'name', 'slug',
        'stripe_connect_account_id',
        'stripe_onboarding_status',
        'stripe_connect_charges_enabled',
        'stripe_connect_payouts_enabled',
        'stripe_connect_onboarding_complete',
        'stripe_connected_at',
        'platform_fee_percent',
    )

    STATUS_COLORS = {
        'not_started': 'gray',
        'pending': 'yellow',
        'in_review': 'yellow',
        'active': 'green',
        'restricted': 'red',
        'disabled': 'red',
    }

    tenant_list = []
    for t in tenants:
        t['status_color'] = STATUS_COLORS.get(t['stripe_onboarding_status'], 'gray')
        tenant_list.append(t)

    from django.contrib import admin
    context = {
        **admin.site.each_context(request),
        'title': 'Stripe Connect Accounts',
        'tenants': tenant_list,
        'total': len(tenant_list),
        'active_count': sum(1 for t in tenant_list if t['stripe_onboarding_status'] == 'active'),
        'pending_count': sum(1 for t in tenant_list if t['stripe_onboarding_status'] in ('pending', 'in_review')),
    }
    return render(request, 'admin/connect_accounts.html', context)


def admin_platform_config_view(request):
    """
    GET/POST /admin/platform-config/

    View and edit the PlatformConfig singleton (default_fee_percent,
    competition_pool_enabled, competition_pool_fee_percent). Superuser-only —
    a non-superuser staff account must never be able to change platform fees.
    """
    _require_superuser(request)
    from apps.billing.models import PlatformConfig

    config = PlatformConfig.get_solo()

    if request.method == 'POST':
        try:
            def _dec(field, default='0'):
                val = request.POST.get(field, default) or default
                try:
                    return Decimal(str(val)).quantize(Decimal('0.01'))
                except (InvalidOperation, ValueError):
                    return Decimal(default)

            def _int(field, default=0):
                try:
                    return max(0, int(request.POST.get(field, default) or default))
                except (TypeError, ValueError):
                    return default

            # The master switch. Turning fees on must be a deliberate act,
            # not a side effect of saving a percentage.
            config.fee_enabled = request.POST.get('fee_enabled') == 'on'
            config.default_fee_percent = _dec('default_fee_percent', '0.00')
            config.default_fee_fixed_cents = _int('default_fee_fixed_cents', 0)
            config.competition_pool_enabled = request.POST.get('competition_pool_enabled') == 'on'
            config.competition_pool_fee_percent = _dec('competition_pool_fee_percent', '0.00')
            config.save()
            messages.success(request, 'Platform configuration saved.')
            return redirect('/admin/platform-config/')
        except Exception as e:
            logger.error(f"Failed to save PlatformConfig: {e}")
            messages.error(request, f'Failed to save: {e}')

    from django.contrib import admin
    context = {
        **admin.site.each_context(request),
        'title': 'Platform Configuration',
        'config': config,
    }
    return render(request, 'admin/platform_config.html', context)


def admin_platform_fees_view(request):
    """
    GET /admin/platform-fees/

    What the platform has actually collected. Superuser-only.

    Existed nowhere before: the fee plumbing was correct (direct charges
    with application_fee_amount, which lands in the platform's own Stripe
    balance) but nothing in the product could answer "how much have we
    taken, from whom, this month" without opening the Stripe Dashboard.

    The gap check at the bottom is the important part. If a Connect-enabled
    tenant has Stripe payments with no matching PlatformFeeRecord, fees are
    being skipped -- the same "if this ever fires, something is broken"
    signal the reconcile sweep logs.
    """
    _require_superuser(request)

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from apps.billing.models import Payment, PlatformConfig, PlatformFeeRecord
    from apps.tenants.models import Tenant

    config = PlatformConfig.get_solo()

    by_month = list(
        PlatformFeeRecord.objects
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('fee_amount'), gross=Sum('gross_amount'),
                  count=Count('id'))
        .order_by('-month')[:24]
    )

    by_tenant = list(
        PlatformFeeRecord.objects
        .values('tenant__name', 'tenant__slug')
        .annotate(total=Sum('fee_amount'), gross=Sum('gross_amount'),
                  count=Count('id'))
        .order_by('-total')[:50]
    )

    recent = list(
        PlatformFeeRecord.objects
        .select_related('tenant', 'invoice')
        .order_by('-created_at')[:50]
    )

    totals = PlatformFeeRecord.objects.aggregate(
        total=Sum('fee_amount'), gross=Sum('gross_amount'), count=Count('id'),
    )

    # Gap check: Stripe-paid invoices on Connect-active tenants that have no
    # fee record. Non-zero means fees are being missed.
    connect_tenant_ids = list(
        Tenant.objects
        .filter(stripe_connect_charges_enabled=True,
                stripe_onboarding_status='active')
        .values_list('id', flat=True)
    )
    recorded_pis = set(
        PlatformFeeRecord.objects.values_list('payment_intent_id', flat=True)
    )
    gap_qs = (
        Payment.objects
        .filter(invoice__tenant_id__in=connect_tenant_ids)
        .exclude(stripe_payment_id='')
        .exclude(stripe_payment_id__isnull=True)
        .select_related('invoice', 'invoice__tenant')
        .order_by('-payment_date')[:200]
    )
    gaps = [p for p in gap_qs if p.stripe_payment_id not in recorded_pis]

    from django.contrib import admin
    context = {
        **admin.site.each_context(request),
        'title': 'Platform Fees Collected',
        'config': config,
        'fee_enabled': config.fee_enabled,
        'by_month': by_month,
        'by_tenant': by_tenant,
        'recent': recent,
        'totals': totals,
        'gaps': gaps,
        'gap_count': len(gaps),
    }
    return render(request, 'admin/platform_fees.html', context)
