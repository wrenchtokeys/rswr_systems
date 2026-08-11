"""
Webhook idempotency, ordering, and dead-lettering.

Both Stripe endpoints used to be fire-and-forget: no record that an event had
arrived, no check that it had already been handled, and a blanket
`except Exception: return 200` so Stripe would never retry. Three failure
modes followed from that, all silent:

1. **Replay.** Stripe redelivers on any non-2xx, on manual resend, and
   occasionally on its own. Every redelivery re-ran the handler and re-sent
   the customer-facing email.

2. **Out-of-order.** Delivery order is not guaranteed. A retried
   `invoice.payment_failed` arriving after `invoice.paid` flipped a paying
   tenant back to `past_due`. Harmless while past_due was warn-only;
   a lockout once it isn't.

3. **Permanent loss.** Returning 200 on a transient DB or SES error told
   Stripe "handled, don't retry" — so the event was gone for good, with a
   log line as the only trace.

The fix is this module plus `StripeWebhookEvent`:

- `claim()` records the event and says whether to process it.
- `should_apply()` is the ordering guard, compared against
  `Tenant.subscription_synced_at`.
- `mark_processed` / `mark_ignored` / `mark_failed` close the record.

`WebhookPermanentError` means "understood, nothing to do" (unknown customer,
event type we don't handle) and maps to 200. Everything else maps to 500 so
Stripe retries on its own backoff, with `attempts` making a poison event
visible instead of infinite.
"""

import logging
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class WebhookPermanentError(Exception):
    """Understood, but nothing to do. Do NOT ask Stripe to retry.

    Use for genuinely terminal conditions: an unknown customer, a tenant that
    no longer exists, an event type we deliberately ignore. Anything that
    might succeed on a retry -- a DB error, a timeout -- must NOT use this.
    """


def _as_datetime(value):
    """Accept a Stripe unix timestamp OR a datetime; return an aware datetime.

    The reconciler stamps its own retrieve time (a datetime) through the same
    watermark as webhook events (unix seconds), so both forms are supported.
    """
    if not value:
        return None
    if hasattr(value, 'tzinfo'):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    try:
        # datetime.timezone.utc, not django.utils.timezone.utc -- the latter
        # was removed in Django 5.
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def claim(event, endpoint):
    """Record an event and decide whether to process it.

    Returns (row, should_process). `should_process` is False when this exact
    event id has already been processed or ignored -- the idempotency guard.
    A previously *failed* event is retried, with `attempts` incremented.

    Never raises on a logging problem: losing the audit row must not cost us
    the event. In that case we return (None, True) and process anyway.
    """
    from apps.billing.models import StripeWebhookEvent

    event_id = event.get('id') or ''
    if not event_id:
        # Nothing to key on -- process it, but say so loudly.
        logger.warning(
            "Stripe webhook with no event id on %s endpoint; cannot dedupe",
            endpoint,
        )
        return None, True

    defaults = {
        'event_type': event.get('type') or '',
        'endpoint': endpoint,
        'api_version': event.get('api_version') or '',
        'account_id': event.get('account') or '',
        'livemode': bool(event.get('livemode', True)),
        'created_ts': event.get('created'),
        'payload': event,
        'status': 'processing',
    }

    try:
        with transaction.atomic():
            row, created = StripeWebhookEvent.objects.select_for_update().get_or_create(
                event_id=event_id, defaults=defaults,
            )
            if not created and row.status in ('processed', 'ignored'):
                logger.info(
                    "Stripe webhook %s [%s] already %s; skipping duplicate",
                    row.event_type, event_id, row.status,
                )
                return row, False

            row.attempts = (row.attempts or 0) + 1
            row.status = 'processing'
            row.save(update_fields=['attempts', 'status'])
            return row, True
    except Exception:
        logger.exception(
            "Could not record Stripe webhook %s; processing without a log row",
            event_id,
        )
        return None, True


def should_apply(tenant, event_created_ts):
    """True when this event is not older than the last one we applied.

    Strict `<` so two events in the same second both apply -- Stripe's
    `created` has one-second resolution and a create/update pair routinely
    shares a timestamp.
    """
    if not event_created_ts or tenant is None:
        return True
    watermark = getattr(tenant, 'subscription_synced_at', None)
    if not watermark:
        return True
    event_dt = _as_datetime(event_created_ts)
    if event_dt is None:
        return True
    return not (event_dt < watermark)


def stamp_synced(tenant, event_created_ts, update_fields=None):
    """Advance the tenant's watermark to this event's timestamp.

    Returns the field name when it should be persisted, so callers can append
    it to an existing `update_fields` list rather than issuing a second write.
    """
    event_dt = _as_datetime(event_created_ts)
    if event_dt is None:
        return None
    current = getattr(tenant, 'subscription_synced_at', None)
    if current and current >= event_dt:
        return None
    tenant.subscription_synced_at = event_dt
    if update_fields is not None and 'subscription_synced_at' not in update_fields:
        update_fields.append('subscription_synced_at')
    return 'subscription_synced_at'


def _close(row, status, error=''):
    if row is None:
        return
    try:
        row.status = status
        row.processed_at = timezone.now()
        if error:
            row.last_error = error[:5000]
        row.save(update_fields=['status', 'processed_at', 'last_error'])
    except Exception:
        logger.exception("Could not close Stripe webhook log row %s", row.pk)


def mark_processed(row):
    _close(row, 'processed')


def mark_ignored(row, reason=''):
    _close(row, 'ignored', reason)


def mark_failed(row, exc):
    _close(row, 'failed', f"{type(exc).__name__}: {exc}")


def recent_failures(hours=24):
    """Failed events in the last N hours -- feeds the daily alert digest."""
    from apps.billing.models import StripeWebhookEvent

    cutoff = timezone.now() - timezone.timedelta(hours=hours)
    return StripeWebhookEvent.objects.filter(
        status='failed', first_seen_at__gte=cutoff,
    )
