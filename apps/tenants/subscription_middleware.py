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
    '/help/',             # Guides + /help/contact/ — an expired shop is exactly who needs support
    '/app/invite/',       # Customer invitation acceptance (may be unauthenticated)
    '/subscription-blocked/',  # The blocked page itself
    '/sms/',              # Public SMS program disclosure (carrier registration evidence)
)

# Paths for static/media
STATIC_PREFIXES = (
    '/static/',
    '/media/',
    '/favicon',
)

# HTTP methods that modify state (blocked during grace period)
WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

# Writes a portal customer keeps even while the shop is restricted.
#
# Paying an invoice moves money TO the shop — taking that button away
# punishes both the shop we want reactivated and the customer who owes it.
# The rest is the customer's own state: their notification read-state and
# their own contact verification.
#
# /app/account/ is deliberately NOT here. It looks like "their own account
# settings", but its POST handler also saves a RepairPreferenceForm, which
# writes field_repair_approval_mode (whether the shop's jobs auto-approve or
# land as PENDING) plus invoice_preference / auto_email_invoices /
# billing_email. That is shop workflow and invoicing configuration, and it
# would take effect the moment the shop came back. The cost of leaving it
# out is that a password or profile edit also waits for the shop to be
# restored, which is the right trade against a view having to know about
# subscription state.
CUSTOMER_ALLOWED_WRITE_PREFIXES = (
    '/app/invoices/',        # pay / Stripe checkout
    '/app/notifications/',   # mark-read is their own read state
    '/app/verify-email/',
    '/app/verify-phone/',
)

# Roles that ARE the shop's customers, as opposed to roles we merely failed
# to place. Only these skip the hard block; see the middleware for why the
# distinction matters.
PORTAL_CUSTOMER_ROLES = frozenset({'customer', 'viewer'})


def subscription_audience(user, tenant):
    """Who is asking — decides how much of the shop's billing state they see.

    The subscription is a contract between RS Systems and the shop, so:

    'owner'    – owner / manager / superuser: the only people who can pay,
                 and the only ones who get amounts, dates and upgrade links.
    'staff'    – technician: told the shop is locked and to ask the owner.
                 Never a plan name, a countdown or a payment reason — they
                 work on a tablet a customer can read over their shoulder.
    'customer' – the shop's own customer: never told the shop's billing
                 state exists. To them the portal is the shop's product.

    This answers "how much may they be TOLD", and nothing else. Whether
    someone may be hard-blocked is a separate question with a separate
    default — see PORTAL_CUSTOMER_ROLES.
    """
    from common.auth import get_user_role

    return audience_for_role(get_user_role(user, tenant))


def audience_for_role(role):
    """`subscription_audience` for a role string already in hand.

    'viewer' lands in 'customer' with everything else unrecognised —
    common/auth calls viewers "external customers" and gives them no
    internal areas. An unplaceable role (no membership, no CustomerUser)
    lands there too: say the least to whoever we cannot identify.
    """
    if role in ('superuser', 'owner', 'manager'):
        return 'owner'
    if role == 'technician':
        return 'staff'
    return 'customer'


def shop_unavailable_message(tenant):
    """The only thing a customer is ever told about a shop's lapse.

    No 'subscription', no 'payment', no 'read-only', no 'upgrade' — the
    shop's billing relationship with us is none of their customer's
    business, and 'their card was declined' is not a thing we say about a
    shop to the fleet manager it invoices.
    """
    name = (getattr(tenant, 'name', '') or 'This shop').strip()
    phone = (getattr(tenant, 'business_phone', '') or '').strip()
    if phone:
        return (
            f"{name} isn't taking online requests right now. "
            f"Please call {phone} to book or approve work."
        )
    return (
        f"{name} isn't taking online requests right now. "
        f"Please contact the shop directly to book or approve work."
    )


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
        # Fix: treat 'canceled' as expired ONLY when a grace period is
        # CURRENT (grace_period_end in the future), confirming the
        # subscription has actually ended (not just scheduled to).
        #
        # Raw truthiness is not enough: a lapse + resubscribe cycle can leave
        # a STALE grace_period_end in the past on a paying tenant (reactivation
        # paths now clear it, but pre-fix data exists). A past stamp on a
        # 'canceled' tenant means the old grace is history, not that this
        # cancellation has taken effect — treat it like no stamp at all.
        # For a genuinely 'expired' tenant the logic below is unchanged: a
        # past grace stamp still means BLOCKED. (A3)
        #
        # State table ('canceled' / 'expired' × grace stamp):
        #   canceled + none or past stamp   -> ACTIVE (paid days remain)
        #   canceled + future stamp         -> read-only grace
        #   expired  + future stamp         -> read-only grace
        #   expired  + none or past stamp   -> BLOCKED
        from django.utils import timezone
        _grace_end = tenant.effective_grace_period_end
        grace_is_current = bool(_grace_end and _grace_end >= timezone.now())
        canceled_is_active = status == 'canceled' and not grace_is_current
        is_subscription_expired = (
            (is_trial and tenant.is_trial_expired)
            or (status in ('canceled', 'expired') and not canceled_is_active)
        )

        # Resolving the audience costs a membership lookup, so only ask when
        # something is actually wrong. A healthy shop's requests never pay
        # for it.
        if not (is_subscription_expired or status in ('paused', 'past_due')):
            return self.get_response(request)

        # Two questions, two answers, deliberately not the same one.
        #
        # How much may they be TOLD? Unknown role -> 'customer', i.e. the
        # least. That default is conservative.
        #
        # May they be hard-BLOCKED? Only an affirmatively identified portal
        # customer is exempt. Reusing the disclosure answer here would have
        # made the same "we can't place you" default *permissive* about
        # access — an unplaceable user who used to hit the wall would
        # instead pass into the view layer read-only. The view decorators
        # would still refuse them, so it was defence-in-depth rather than a
        # hole, but a safe-looking default should not quietly widen access.
        from common.auth import get_user_role
        role = get_user_role(request.user, tenant)
        audience = audience_for_role(role)
        is_portal_customer = role in PORTAL_CUSTOMER_ROLES
        request.subscription_audience = audience

        if is_subscription_expired:
            if tenant.is_in_grace_period:
                # Grace period: allow GETs, block writes
                return self._handle_grace_period(
                    request, tenant, audience=audience,
                    is_portal_customer=is_portal_customer,
                )
            # Grace period is over. The shop's own people hit the wall — but
            # the shop's CUSTOMERS never do. Locking a fleet manager out of
            # their own repair history and invoices punishes the party that
            # didn't owe us anything, and it takes the "Pay this invoice"
            # button down with it. They stay read-only indefinitely instead.
            if is_portal_customer:
                return self._handle_grace_period(
                    request, tenant, days_remaining=0, reason='expired',
                    audience=audience, is_portal_customer=is_portal_customer,
                )
            return self._block(request, tenant, status)

        # paused: Stripe's pause_collection / paused trial. Read-only for the
        # shop rather than a hard block — a pause is not a lapse, and it is
        # usually something the owner (or we) did on purpose.
        if status == 'paused':
            return self._handle_grace_period(
                request, tenant, days_remaining=0, reason='paused',
                audience=audience, is_portal_customer=is_portal_customer,
            )

        # past_due: warn first, restrict later.
        #
        # This used to be warn-only forever — a shop whose card died kept
        # full write access for as long as it liked. It now escalates to
        # read-only after PAST_DUE_GRACE_DAYS (14), which still leaves about
        # a week of Stripe's automatic retries. /owner/billing/ is exempt,
        # so the fix is always one click away.
        if status == 'past_due':
            if tenant.past_due_is_read_only:
                return self._handle_grace_period(
                    request, tenant,
                    days_remaining=0,
                    reason='past_due',
                    audience=audience, is_portal_customer=is_portal_customer,
                )
            days_left = tenant.past_due_days_until_read_only
            # Warn-only means nothing is broken yet, so nobody but the person
            # who can fix it needs to hear about it. This used to message
            # every role, which told technicians and portal customers that
            # the shop's card had failed.
            if audience != 'owner':
                request.subscription_past_due = True
                request.past_due_days_until_read_only = days_left
                return self.get_response(request)
            try:
                if days_left is None:
                    warning = (
                        "⚠️ Your payment is past due. Please update your "
                        "billing info to avoid service interruption."
                    )
                else:
                    warning = (
                        f"⚠️ Your payment is past due. You have {days_left} day"
                        f"{'s' if days_left != 1 else ''} before your shop "
                        f"becomes read-only. Update your billing info to "
                        f"avoid interruption."
                    )
                messages.warning(request, warning)
            except Exception:
                pass
            request.subscription_past_due = True
            request.past_due_days_until_read_only = days_left

        return self.get_response(request)

    def _handle_grace_period(self, request, tenant, days_remaining=None,
                             reason='expired', audience='owner',
                             is_portal_customer=False):
        """Read-only mode: GETs pass, writes are blocked.

        Shared by every way write access goes away — an expired subscription
        working through its grace period, a past_due tenant that has used up
        its full-access days, a paused subscription, and a lapsed shop's
        customers (who never get blocked outright). Same mechanics; the copy
        depends on who is reading it. See `subscription_audience`.

        `audience` decides what they are TOLD; `is_portal_customer` decides
        what they may DO. Same split as the block decision in __call__, and
        for the same reason: an unrecognised role is told the least, which
        must not also hand it the customer write exemption.
        """
        if days_remaining is None:
            days_remaining = tenant.grace_days_remaining

        if audience == 'customer':
            api_error = ui_error = shop_unavailable_message(tenant)
        elif audience == 'staff':
            api_error = ui_error = (
                "This shop is read-only right now. Contact your shop owner "
                "to restore full access."
            )
        elif reason == 'past_due':
            api_error = (
                'Your payment is past due. Your shop is read-only until '
                'the payment is resolved.'
            )
            ui_error = (
                "⛔ Your shop is read-only because we could not collect "
                "payment. Update your payment method to restore full access."
            )
        elif reason == 'paused':
            api_error = 'Your subscription is paused. You are in read-only mode.'
            ui_error = (
                "⛔ Your subscription is paused, so your shop is read-only. "
                "Resume it to continue making changes."
            )
        else:
            api_error = 'Your subscription has expired. You are in read-only mode.'
            ui_error = (
                f"⛔ Your subscription has expired. You have {days_remaining} day"
                f"{'s' if days_remaining != 1 else ''} of read-only access remaining. "
                "Upgrade to continue making changes."
            )

        # Block write operations
        # An access decision, so it keys off who they ARE, not off how much
        # they get told. Gating this on `audience` would have handed an
        # unrecognised role the portal-customer write exemption -- letting
        # it POST to paths a technician on the same shop is refused.
        if request.method in WRITE_METHODS and not (
            is_portal_customer
            and request.path.startswith(CUSTOMER_ALLOWED_WRITE_PREFIXES)
        ):
            if request.path.startswith('/api/'):
                payload = {'error': api_error, 'reason': reason}
                if audience == 'owner':
                    payload['grace_days_remaining'] = days_remaining
                    payload['upgrade_url'] = '/owner/billing/'
                # 402 Payment Required is the shop's answer, not their
                # customer's — for a customer nothing is owed and nothing is
                # theirs to fix, so it's a plain "unavailable".
                status_code = 402 if audience == 'owner' else 503
                if audience == 'customer':
                    payload['reason'] = 'unavailable'
                return JsonResponse(payload, status=status_code)
            try:
                messages.error(request, ui_error)
            except Exception:
                pass
            # Redirect back to the referring page or home
            referer = request.META.get('HTTP_REFERER', '/')
            return redirect(referer if referer.startswith('/') else '/')

        # Allow GET — set a flag for the template to show the grace period banner
        request.subscription_grace_period = True
        request.grace_days_remaining = days_remaining
        request.subscription_readonly_reason = reason
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
