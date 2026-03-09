"""
Subscription Enforcement Middleware

Blocks access when a tenant's trial has expired or subscription is
canceled/past_due. Read-only API access is allowed so users can still
view their data and manage billing, but write operations and core
feature access are gated.

Author: Amelia (Clawdbot AI)
"""

import logging
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.contrib import messages

logger = logging.getLogger(__name__)

# Paths that are ALWAYS allowed regardless of subscription status
# (billing, auth, public pages, admin, health checks)
EXEMPT_PREFIXES = (
    '/admin/',
    '/api/tenants/',      # Subscription management endpoints
    '/api/billing/',      # Billing/payment endpoints (need to pay!)
    '/api/schema/',
    '/health/',
    '/login/',
    '/accounts/login/',
    '/logout/',
    '/signup/',
    '/pricing/',
    '/onboarding/',
    '/invite/',
    '/join/',
    '/password-reset/',
    '/clawdbot/',
    '/payment-complete',
    '/payment-cancelled',
    '/owner/billing/',    # Must be accessible to upgrade/reactivate
    '/app/invite/',       # Customer invitation acceptance (may be unauthenticated)
)

# Paths for static/media
STATIC_PREFIXES = (
    '/static/',
    '/media/',
    '/favicon',
)


class SubscriptionEnforcementMiddleware:
    """
    Enforce subscription status after tenant is resolved.

    Must run AFTER TenantMiddleware in the middleware stack.

    Behavior:
    - trialing + not expired: ALLOW
    - trialing + expired: BLOCK (upgrade prompt)
    - active: ALLOW
    - past_due: WARN (grace period, show banner)
    - canceled / expired: BLOCK (reactivate prompt)
    - No tenant: ALLOW (public pages, pre-signup)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for unauthenticated users
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return self.get_response(request)

        # Skip exempt paths
        path = request.path
        if any(path.startswith(p) for p in EXEMPT_PREFIXES + STATIC_PREFIXES):
            return self.get_response(request)

        # Superusers bypass all checks
        if request.user.is_superuser:
            return self.get_response(request)

        # If authenticated + non-exempt + no tenant → block access
        # This prevents data leaks when tenant context is missing
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.warning(
                "Authenticated user %s has no tenant context on %s",
                request.user, path
            )
            if request.path.startswith('/api/'):
                return JsonResponse({
                    'error': 'No tenant context. Contact support.',
                }, status=403)
            try:
                messages.error(request, "Unable to determine your shop. Please log in again.")
            except Exception:
                pass
            return redirect('/login/')

        # Check subscription status
        status = tenant.subscription_status
        is_trial = tenant.plan == 'trial'

        if is_trial and tenant.is_trial_expired:
            return self._block(request, 'trial_expired')

        if status in ('canceled', 'expired'):
            return self._block(request, status)

        # past_due gets a warning but isn't blocked (grace period)
        if status == 'past_due':
            try:
                messages.warning(
                    request,
                    "⚠️ Your payment is past due. Please update your billing info to avoid service interruption."
                )
            except Exception:
                pass

        return self.get_response(request)

    def _block(self, request, reason):
        """Block access with appropriate response based on request type."""
        reason_messages = {
            'trial_expired': "Your free trial has expired. Please upgrade to continue using RS Systems.",
            'canceled': "Your subscription has been canceled. Please reactivate to continue.",
            'expired': "Your subscription has expired. Please renew to continue.",
        }
        msg = reason_messages.get(reason, "Your subscription is inactive.")

        # API requests get JSON
        if request.path.startswith('/api/'):
            return JsonResponse({
                'error': msg,
                'subscription_status': reason,
                'upgrade_url': '/pricing/',
            }, status=402)  # 402 Payment Required

        # HTML requests get redirect to pricing/upgrade page
        try:
            messages.error(request, msg)
        except Exception:
            pass

        return redirect('/pricing/')
