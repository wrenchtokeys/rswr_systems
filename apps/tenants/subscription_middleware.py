"""
Subscription Enforcement Middleware

Blocks access when a tenant's trial has expired or subscription is
canceled/past_due. Supports a 30-day read-only grace period where GET
requests are allowed but writes are blocked. After the grace period,
all access is blocked.

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
    '/subscription-blocked/',  # The blocked page itself
)

# Paths for static/media
STATIC_PREFIXES = (
    '/static/',
    '/media/',
    '/favicon',
)

# HTTP methods that modify state (blocked during grace period)
WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


class SubscriptionEnforcementMiddleware:
    """
    Enforce subscription status after tenant is resolved.

    Must run AFTER TenantMiddleware in the middleware stack.

    Behavior:
    - trialing + not expired: ALLOW
    - trialing + expired (in grace period): ALLOW GETs, BLOCK writes
    - trialing + expired (grace period ended): BLOCK ALL → /subscription-blocked/
    - active: ALLOW
    - past_due: WARN (show banner)
    - canceled / expired (in grace period): ALLOW GETs, BLOCK writes
    - canceled / expired (grace period ended): BLOCK ALL → /subscription-blocked/
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

        # 'canceled' has two distinct meanings in our system:
        #
        # 1. "Scheduled to cancel" (cancel_at_period_end=True): set by
        #    cancel_subscription() when the owner clicks "Cancel at period end".
        #    The shop still has paid time remaining. grace_period_end is NOT set.
        #    The Stripe `customer.subscription.deleted` webhook fires when it
        #    actually expires, at which point status becomes 'expired' and
        #    grace_period_end gets set.
        #
        # 2. "Access ended" — only reachable if something manually sets 'canceled'
        #    with a grace_period_end. In practice, our deletion webhook sets
        #    status='expired', so this case is rare.
        #
        # Bug: previously 'canceled' was unconditionally treated as expired,
        # causing shops to be locked out immediately when they clicked "Cancel"
        # even though they had paid days remaining. (CODE-130)
        #
        # Fix: treat 'canceled' as expired ONLY when grace_period_end is set,
        # confirming the subscription has actually ended (not just scheduled to).
        canceled_is_active = status == 'canceled' and not tenant.grace_period_end
        is_subscription_expired = (
            (is_trial and tenant.is_trial_expired)
            or (status in ('canceled', 'expired') and not canceled_is_active)
        )

        if is_subscription_expired:
            if tenant.is_in_grace_period:
                # Grace period: allow GETs, block writes
                return self._handle_grace_period(request, tenant)
            else:
                # Grace period ended: full block
                return self._block(request, tenant, status)

        # past_due gets a warning but isn't blocked
        if status == 'past_due':
            try:
                messages.warning(
                    request,
                    "⚠️ Your payment is past due. Please update your billing info to avoid service interruption."
                )
            except Exception:
                pass

        return self.get_response(request)

    def _handle_grace_period(self, request, tenant):
        """Handle requests during the 30-day read-only grace period."""
        days_remaining = tenant.grace_days_remaining

        # Block write operations
        if request.method in WRITE_METHODS:
            if request.path.startswith('/api/'):
                return JsonResponse({
                    'error': 'Your subscription has expired. You are in read-only mode.',
                    'grace_days_remaining': days_remaining,
                    'upgrade_url': '/owner/billing/',
                }, status=402)
            try:
                messages.error(
                    request,
                    f"⛔ Your subscription has expired. You have {days_remaining} day"
                    f"{'s' if days_remaining != 1 else ''} of read-only access remaining. "
                    "Upgrade to continue making changes."
                )
            except Exception:
                pass
            # Redirect back to the referring page or home
            referer = request.META.get('HTTP_REFERER', '/')
            return redirect(referer if referer.startswith('/') else '/')

        # Allow GET — set a flag for the template to show the grace period banner
        request.subscription_grace_period = True
        request.grace_days_remaining = days_remaining
        return self.get_response(request)

    def _block(self, request, tenant, reason):
        """Block access with appropriate response based on request type."""
        # Determine reason message for API responses
        if tenant.plan == 'trial' and tenant.is_trial_expired:
            if tenant.had_paid_subscription:
                api_reason = 'subscription_ended'
            else:
                api_reason = 'trial_expired'
        else:
            api_reason = reason

        reason_messages = {
            'trial_expired': "Your free trial has expired. Please upgrade to continue using RS Systems.",
            'subscription_ended': "Your subscription has ended. Please reactivate to continue.",
            'canceled': "Your subscription has been canceled. Please reactivate to continue.",
            'expired': "Your subscription has expired. Please renew to continue.",
        }
        msg = reason_messages.get(api_reason, "Your subscription is inactive.")

        # API requests get JSON
        if request.path.startswith('/api/'):
            return JsonResponse({
                'error': msg,
                'subscription_status': api_reason,
                'upgrade_url': '/owner/billing/',
            }, status=402)

        # HTML requests get redirected to role-aware blocked page
        # Note: ?source=pricing is kept for backward compatibility with any
        # existing links/bookmarks that pointed to /pricing/
        return redirect('/subscription-blocked/?source=pricing')
