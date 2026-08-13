"""
Subscription reconciliation — the safety net for lost subscription webhooks.

The invoice side has had one of these since the stripe-python 15.x outage
(`apps/billing/services/stripe_reconcile.py`). Subscriptions had nothing: a
webhook that was never delivered, or was delivered and swallowed by the old
blanket `return 200`, left the tenant's plan and status permanently wrong
with no process that would ever notice.

That mattered more than it looks. The failure isn't "a status field is
stale" — it's a shop that paid and is still on `plan='trial'`, getting
locked out when the trial clock runs down, or a shop that cancelled months
ago still enjoying full access.

This module mirrors stripe_reconcile's shape deliberately:

- `apply_subscription_state()` is the single place subscription state is
  mapped onto a Tenant. The `customer.subscription.updated` webhook calls it,
  and so does the sweep, so a repaired tenant lands in exactly the state the
  webhook would have produced.
- `reconcile_tenant()` asks Stripe directly for one tenant.
- `reconcile_all()` is the cron sweep.

Never let a Stripe outage corrupt local state: when Stripe cannot be reached
we raise `StripeUnavailable` and change nothing, the same contract
stripe_reconcile uses.
"""

import logging

from django.utils import timezone

from apps.billing.services import webhook_log
from apps.billing.services.stripe_compat import (
    subscription_interval,
    subscription_price_id,
)
from apps.tenants.models import SubscriptionPlan, Tenant

logger = logging.getLogger(__name__)

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:  # pragma: no cover
    STRIPE_AVAILABLE = False


class StripeUnavailable(Exception):
    """Stripe could not be reached / is not configured. Change nothing."""


# Stripe subscription status -> Tenant.subscription_status.
#
# 'incomplete' = checkout started but never paid. Map to 'trialing' (access
# unchanged) rather than storing a value that isn't in the field's choices;
# 'active' arrives via invoice.paid once payment clears. (CODE-228)
#
# 'unpaid' is Stripe's TERMINAL "retries exhausted" state. Mapping it to
# 'past_due' (warn-only) let a tenant keep full access indefinitely, for
# free, until Stripe eventually deleted the subscription. It maps to the
# blocking 'expired' instead, with a grace period granted below so the owner
# gets read-only access and the upgrade path rather than a hard lockout. (D4)
#
# 'paused' is Stripe's paused-collection / paused-trial state. It used to be
# missing from this table, and an unmapped status falls back to the tenant's
# CURRENT status — so pausing a subscription changed nothing at all and the
# shop kept full paid access indefinitely, silently. It maps to a real stored
# status now, which the middleware treats as read-only rather than a hard
# block: a pause is deliberate, not a lapse.
STATUS_MAP = {
    'active': 'active',
    'past_due': 'past_due',
    'paused': 'paused',
    'canceled': 'canceled',
    'trialing': 'trialing',
    'incomplete': 'trialing',
    'incomplete_expired': 'expired',
    'unpaid': 'expired',
}

GRACE_DAYS_AFTER_UNPAID = 30


def _stripe_ready():
    from django.conf import settings
    return STRIPE_AVAILABLE and bool(getattr(settings, 'STRIPE_SECRET_KEY', None))


def plan_for_price(price_id):
    """Match a Stripe price id to a SubscriptionPlan (monthly or annual)."""
    if not price_id:
        return None
    return (
        SubscriptionPlan.objects.filter(stripe_price_id=price_id).first()
        or SubscriptionPlan.objects.filter(stripe_annual_price_id=price_id).first()
    )


def apply_subscription_state(tenant, subscription, source='webhook', synced_at=None):
    """Map a Stripe Subscription onto a Tenant. The single source of truth.

    Args:
        tenant: Tenant instance
        subscription: Stripe Subscription object or dict (either API shape)
        source: 'webhook' or 'reconcile' — for logging only
        synced_at: unix ts (webhook event.created) or datetime (reconcile
            retrieve time). Advances the out-of-order watermark.

    Returns a dict describing what changed, so the sweep can report drift.
    """
    subscription_id = subscription.get('id') if hasattr(subscription, 'get') \
        else subscription['id']
    stripe_status = _get(subscription, 'status', '')
    new_status = STATUS_MAP.get(stripe_status, tenant.subscription_status)
    if stripe_status not in STATUS_MAP:
        # Falling back to the current status means "do nothing", which is the
        # safe default but an invisible one. Say so: a status Stripe added
        # and we never mapped will otherwise leave a tenant frozen in
        # whatever access level it had, forever, with a clean log.
        logger.warning(
            f"[{source}] Unmapped Stripe subscription status {stripe_status!r} "
            f"for tenant {tenant.slug} — access left at "
            f"{tenant.subscription_status!r}. Add it to STATUS_MAP."
        )

    before = {
        'status': tenant.subscription_status,
        'plan': tenant.plan,
        'subscription_id': tenant.stripe_subscription_id,
    }

    # SECURITY: only touch the plan when payment is confirmed. 'incomplete'
    # means checkout started but was never paid — upgrading there would hand
    # out a paid tier for free.
    if stripe_status not in ('active', 'trialing'):
        tenant.subscription_status = new_status
        tenant.stripe_subscription_id = subscription_id
        update_fields = ['subscription_status', 'stripe_subscription_id']

        if stripe_status == 'unpaid' and not tenant.grace_period_end:
            tenant.grace_period_end = (
                timezone.now() + timezone.timedelta(days=GRACE_DAYS_AFTER_UNPAID)
            )
            update_fields.append('grace_period_end')

        webhook_log.stamp_synced(tenant, synced_at, update_fields)
        tenant.save(update_fields=update_fields)
        logger.info(
            f"[{source}] Tenant {tenant.slug} status={new_status} "
            f"(plan unchanged, waiting for payment)"
        )
        return _changes(before, tenant)

    price_id = subscription_price_id(subscription)
    plan = plan_for_price(price_id)
    if plan and tenant.subscription_plan != plan:
        tenant.plan = plan.slug
        tenant.subscription_plan = plan
        logger.info(f"[{source}] Tenant {tenant.slug} plan changed to {plan.name}")
    elif price_id and not plan:
        # Worth shouting about: a live price we cannot map means a plan was
        # created in Stripe without its id being recorded here, and every
        # future sync for this tenant will silently skip the plan update.
        logger.warning(
            f"[{source}] Tenant {tenant.slug} is on Stripe price {price_id} "
            f"which matches no SubscriptionPlan — plan left as {tenant.plan!r}"
        )

    # cancel_at_period_end: scheduled to cancel but still active and paid up.
    # Keep 'canceled' (matching cancel_subscription()); the middleware treats
    # 'canceled' without a current grace period as still-active, so there is
    # no access loss here. customer.subscription.deleted flips it to 'expired'
    # when it actually ends. (CODE-130)
    if _get(subscription, 'cancel_at_period_end', False):
        new_status = 'canceled'

    tenant.subscription_status = new_status
    tenant.stripe_subscription_id = subscription_id
    update_fields = [
        'subscription_status', 'stripe_subscription_id',
        'plan', 'subscription_plan',
    ]

    # A live status clears a grace period left over from a previous lapse.
    # Do NOT clear on 'canceled' — a running grace period must keep its
    # read-only semantics. (A3)
    if new_status in ('active', 'trialing'):
        tenant.grace_period_end = None
        update_fields.append('grace_period_end')

    webhook_log.stamp_synced(tenant, synced_at, update_fields)
    tenant.save(update_fields=update_fields)

    logger.info(f"[{source}] Tenant {tenant.slug} status={new_status}")
    return _changes(before, tenant)


def _get(obj, key, default=None):
    """Field access that works on dicts and 15.x StripeObjects alike."""
    try:
        value = obj[key]
    except (KeyError, TypeError, IndexError, AttributeError):
        return default
    return default if value is None else value


def _changes(before, tenant):
    after = {
        'status': tenant.subscription_status,
        'plan': tenant.plan,
        'subscription_id': tenant.stripe_subscription_id,
    }
    return {
        'changed': before != after,
        'before': before,
        'after': after,
    }


def _retrieve_subscription(tenant):
    """Current subscription for a tenant, by id then by customer.

    Falling back to the customer lookup matters: the stored subscription id
    goes stale whenever a subscription is replaced (a cancel-then-resubscribe
    cycle), and that is exactly the tenant most likely to have drifted.
    """
    from apps.billing.services.stripe_compat import configure_stripe
    configure_stripe()

    if tenant.stripe_subscription_id:
        try:
            return stripe.Subscription.retrieve(tenant.stripe_subscription_id)
        except stripe.error.InvalidRequestError:
            logger.info(
                f"Reconcile: subscription {tenant.stripe_subscription_id} for "
                f"{tenant.slug} no longer exists; falling back to customer lookup"
            )
        except stripe.error.StripeError as e:
            raise StripeUnavailable(str(e))

    if not tenant.stripe_customer_id:
        return None

    try:
        subs = stripe.Subscription.list(
            customer=tenant.stripe_customer_id, status='all', limit=10,
        )
    except stripe.error.StripeError as e:
        raise StripeUnavailable(str(e))

    data = _get(subs, 'data', []) or []
    if not data:
        return None

    # Prefer a live subscription over a dead one.
    live = [s for s in data
            if _get(s, 'status') in ('active', 'trialing', 'past_due', 'unpaid')]
    return (live or data)[0]


def reconcile_tenant(tenant, apply=True):
    """Verify one tenant's subscription state against Stripe.

    Returns a summary dict. Raises StripeUnavailable rather than guessing.
    """
    if not _stripe_ready():
        raise StripeUnavailable("Stripe is not configured")

    result = {
        'tenant': tenant.slug,
        'checked': True,
        'changed': False,
        'action': 'none',
    }

    subscription = _retrieve_subscription(tenant)
    if subscription is None:
        result['action'] = 'no_subscription_in_stripe'
        return result

    # The reconciler reads Stripe's *current* state, which is by definition
    # newer than any event still in flight. Stamping the retrieve time stops
    # a webhook created before this read from later overwriting it.
    retrieved_at = timezone.now()

    if not apply:
        stripe_status = _get(subscription, 'status', '')
        mapped = STATUS_MAP.get(stripe_status, tenant.subscription_status)
        plan = plan_for_price(subscription_price_id(subscription))
        would_change = (
            mapped != tenant.subscription_status
            or (plan and plan != tenant.subscription_plan)
            or _get(subscription, 'id') != tenant.stripe_subscription_id
        )
        result.update({
            'action': 'would_update' if would_change else 'in_sync',
            'changed': bool(would_change),
            'stripe_status': stripe_status,
            'local_status': tenant.subscription_status,
            'stripe_plan': plan.slug if plan else None,
            'local_plan': tenant.plan,
            'interval': subscription_interval(subscription),
        })
        return result

    changes = apply_subscription_state(
        tenant, subscription, source='reconcile', synced_at=retrieved_at,
    )
    result.update({
        'action': 'updated' if changes['changed'] else 'in_sync',
        'changed': changes['changed'],
        'before': changes['before'],
        'after': changes['after'],
    })

    if changes['changed']:
        # If this ever fires, a webhook was lost. That is the signal worth
        # watching -- the repair itself is routine.
        logger.warning(
            f"Reconcile repaired subscription drift for {tenant.slug}: "
            f"{changes['before']} -> {changes['after']}"
        )
    return result


def reconcile_all(apply=True, tenant_slug=None):
    """Sweep every tenant that has a Stripe customer. Cron entry point."""
    qs = Tenant.objects.exclude(stripe_customer_id='').exclude(
        stripe_customer_id__isnull=True,
    )
    if tenant_slug:
        qs = qs.filter(slug=tenant_slug)

    summary = {
        'checked': 0, 'updated': 0, 'in_sync': 0,
        'no_subscription': 0, 'errors': 0, 'results': [],
    }

    for tenant in qs.iterator():
        try:
            result = reconcile_tenant(tenant, apply=apply)
        except StripeUnavailable as e:
            # A Stripe outage must not be mistaken for "nothing to do".
            logger.error(f"Reconcile: Stripe unavailable for {tenant.slug}: {e}")
            summary['errors'] += 1
            summary['results'].append(
                {'tenant': tenant.slug, 'error': str(e), 'action': 'unavailable'}
            )
            continue
        except Exception as e:
            logger.exception(f"Reconcile failed for {tenant.slug}: {e}")
            summary['errors'] += 1
            summary['results'].append(
                {'tenant': tenant.slug, 'error': str(e), 'action': 'error'}
            )
            continue

        summary['checked'] += 1
        action = result.get('action')
        if action in ('updated', 'would_update'):
            summary['updated'] += 1
        elif action == 'in_sync':
            summary['in_sync'] += 1
        elif action == 'no_subscription_in_stripe':
            summary['no_subscription'] += 1
        summary['results'].append(result)

    return summary
