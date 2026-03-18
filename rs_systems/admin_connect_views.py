"""
Admin views for Stripe Connect accounts and Platform configuration.

Accessible via /admin/connect-accounts/ and /admin/platform-config/
(staff/superuser only — enforced by admin_site.admin_view wrapper).

Author: Amelia (Clawdbot AI)
"""

import logging
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


def admin_connect_accounts_view(request):
    """
    GET /admin/connect-accounts/

    List all tenants with their Stripe Connect status, account ID,
    and charges/payouts enabled flags.
    """
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

    context = {
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
    competition_pool_enabled, competition_pool_fee_percent).
    """
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

            config.default_fee_percent = _dec('default_fee_percent', '0.00')
            config.competition_pool_enabled = request.POST.get('competition_pool_enabled') == 'on'
            config.competition_pool_fee_percent = _dec('competition_pool_fee_percent', '0.00')
            config.save()
            messages.success(request, 'Platform configuration saved.')
            return redirect('/admin/platform-config/')
        except Exception as e:
            logger.error(f"Failed to save PlatformConfig: {e}")
            messages.error(request, f'Failed to save: {e}')

    context = {
        'title': 'Platform Configuration',
        'config': config,
    }
    return render(request, 'admin/platform_config.html', context)
