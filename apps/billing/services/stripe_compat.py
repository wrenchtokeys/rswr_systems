"""
Version-tolerant accessors for Stripe objects.

Two independent things drift underneath this app, and they drift separately:

1. **The SDK version.** `requirements.txt` allowed `stripe>=8.0.0,<16`, and
   production silently resolved to 15.4.0 while a dev machine sat on 14.3.0.
   stripe-python 15.x also removed dict inheritance from `StripeObject`, so
   `.get()` raises `AttributeError` on a real API response (a plain dict is
   fine). `_field` below uses `__getitem__`, which works on every version and
   on both object kinds.

2. **The API version**, which decides the *shape* of the payload. Outbound
   calls use `settings.STRIPE_API_VERSION`; inbound webhook payloads are
   shaped by whatever the Stripe Dashboard has pinned on the endpoint (or the
   account default). These are configured in different places and are NOT
   guaranteed to match.

The 2025-03-31 "Basil" release moved three fields this app depends on:

    pre-Basil                      Basil and later
    -------------------------      ----------------------------------------
    invoice.subscription           invoice.parent.subscription_details
                                       .subscription
    subscription.current_period_*  subscription.items.data[].current_period_*
    invoice.lines.data[].price     invoice.lines.data[].pricing
                                       .price_details.price

Production runs 2026-07-29.dahlia, which is past all three. Reading these
fields directly is what silently disabled downgrades and the plan self-heal.

Every accessor here tries the new shape and the old one and returns None
rather than raising, because the callers are webhook handlers: a shape we
do not recognise must degrade to "unknown", never to a 500 that Stripe
retries forever.
"""

import logging

logger = logging.getLogger(__name__)


def configure_stripe():
    """Apply the pinned API version (and key) to the global stripe module.

    Called once from BillingConfig.ready() and again from each service
    __init__, because tests and management commands instantiate services
    directly without going through app startup. Setting these is idempotent.

    Without the version pin, `stripe.api_version` is whatever the installed
    SDK defaults to, which makes payload shapes a function of the last
    `pip install` rather than a deliberate choice.
    """
    from django.conf import settings

    try:
        import stripe
    except ImportError:  # pragma: no cover - stripe is a hard dependency
        return None

    key = getattr(settings, 'STRIPE_SECRET_KEY', '')
    if key:
        stripe.api_key = key

    version = getattr(settings, 'STRIPE_API_VERSION', '')
    if version:
        stripe.api_version = version
    return stripe


def _field(obj, key, default=None):
    """Version-proof field access on a Stripe object OR plain dict.

    stripe-python 15.x removed dict inheritance from StripeObject, so
    .get() is not safe; __getitem__ works on every version and on dicts.
    """
    try:
        value = obj[key]
    except (KeyError, TypeError, IndexError, AttributeError):
        return default
    return default if value is None else value


def _dig(obj, *keys, default=None):
    """Walk a chain of keys, returning `default` the moment one is missing."""
    current = obj
    for key in keys:
        current = _field(current, key)
        if current is None:
            return default
    return current


def _id_of(value, default=None):
    """Stripe expandable fields are either an id string or the object."""
    if value is None:
        return default
    if isinstance(value, str):
        return value or default
    return _field(value, 'id', default)


def _first_line(invoice):
    lines = _dig(invoice, 'lines', 'data', default=None)
    try:
        return lines[0]
    except (TypeError, IndexError, KeyError):
        return None


def _items(subscription):
    items = _dig(subscription, 'items', 'data', default=None)
    return items if isinstance(items, (list, tuple)) else []


# ----------------------------------------------------------------------
# Invoice
# ----------------------------------------------------------------------

def invoice_subscription_id(invoice, default=None):
    """The subscription this invoice bills, across all API versions.

    Basil moved this to invoice.parent.subscription_details.subscription;
    the line item carries it too, which covers invoices whose parent block
    is absent.
    """
    # Pre-Basil top-level field.
    found = _id_of(_field(invoice, 'subscription'))
    if found:
        return found

    # Basil+ parent block.
    found = _id_of(_dig(invoice, 'parent', 'subscription_details', 'subscription'))
    if found:
        return found

    # Last resort: the line item's own parent block.
    line = _first_line(invoice)
    if line is not None:
        found = _id_of(
            _dig(line, 'parent', 'subscription_item_details', 'subscription')
        )
        if found:
            return found
        found = _id_of(_field(line, 'subscription'))
        if found:
            return found

    return default


def invoice_price_id(invoice, default=''):
    """The price id billed by an invoice's first line item.

    Basil replaced line.price with line.pricing.price_details.price.
    Used to self-heal a tenant's plan when the checkout webhook was lost.
    """
    line = _first_line(invoice)
    if line is None:
        return default

    # Basil+ pricing block (a plain id string, not an object).
    found = _id_of(_dig(line, 'pricing', 'price_details', 'price'))
    if found:
        return found

    # Pre-Basil price object.
    found = _id_of(_field(line, 'price'))
    if found:
        return found

    # Older still: the plan object.
    return _id_of(_field(line, 'plan'), default) or default


def invoice_next_attempt(invoice, default=None):
    """Unix ts of Stripe's next automatic retry, or None if this was the last.

    Drives accurate dunning copy — never hardcode an attempt count.
    """
    return _field(invoice, 'next_payment_attempt', default)


def invoice_attempt_count(invoice, default=0):
    return _field(invoice, 'attempt_count', default)


# ----------------------------------------------------------------------
# Subscription
# ----------------------------------------------------------------------

def subscription_period_end(subscription, default=None):
    """End of the current billing period, across all API versions.

    Basil removed current_period_end from Subscription entirely and put it
    on each SubscriptionItem. We take the max: a subscription schedule's
    phase must not end before any item's paid-through date.
    """
    found = _field(subscription, 'current_period_end')
    if found:
        return found

    ends = [
        end for end in (
            _field(item, 'current_period_end') for item in _items(subscription)
        ) if end
    ]
    return max(ends) if ends else default


def subscription_item_id(subscription, default=None):
    """The first item's id — needed to swap a price on Subscription.modify."""
    items = _items(subscription)
    return _field(items[0], 'id', default) if items else default


def subscription_price_id(subscription, default=''):
    items = _items(subscription)
    if not items:
        return default
    found = _id_of(_field(items[0], 'price'))
    if found:
        return found
    return _id_of(_field(items[0], 'plan'), default) or default


def subscription_interval(subscription, default='month'):
    """'month' or 'year' for the live subscription.

    Read this before writing a price on a plan change; otherwise an annual
    subscriber is silently converted to monthly.
    """
    items = _items(subscription)
    if not items:
        return default
    interval = _dig(items[0], 'price', 'recurring', 'interval')
    if interval:
        return interval
    interval = _dig(items[0], 'plan', 'interval')
    return interval or default
