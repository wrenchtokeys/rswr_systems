"""
Stripe reconciliation — the safety net between "Stripe charged the card"
and "the invoice knows about it".

Webhooks are the primary signal, but they can be lost (the stripe-python
15.x outage of Aug 2026 dropped every delivery for four days). This module
lets the app ask Stripe directly, using the StripeCheckoutAttempt rows
recorded when each checkout session is created:

- guard_manual_payment(invoice): called BEFORE any manual (cash/check)
  payment is recorded. If a checkout session already got paid, the Stripe
  payment is recorded instead (dedup-safe against webhook retries, which
  match on the same payment_intent id). If a session is still open, it is
  expired on Stripe so the customer cannot pay again after handing over
  cash. If Stripe cannot be reached while sessions are pending, manual
  recording is blocked — never leave double-payment to chance.

- reconcile_open_attempts(): the cron sweep. Verifies recent OPEN attempts
  against Stripe and records any paid ones the webhook missed.

- resolve_session(session_id): used by the payment-complete landing page
  to record the payment the moment the customer bounces back from Stripe,
  even if the webhook never arrives.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:  # pragma: no cover
    STRIPE_AVAILABLE = False


class StripeUnavailable(Exception):
    """Stripe could not be reached / is not configured while verification
    was required. Callers must treat this as 'do not proceed'."""


def _stripe_ready():
    from django.conf import settings
    return STRIPE_AVAILABLE and bool(getattr(settings, 'STRIPE_SECRET_KEY', None))


def _field(obj, key, default=None):
    """Version-proof field access on a Stripe object OR plain dict.

    stripe-python 15.x removed dict inheritance from StripeObject, so
    .get() is not safe; __getitem__ works on every version and on dicts.
    """
    try:
        value = obj[key]
    except (KeyError, TypeError, IndexError):
        return default
    return default if value is None else value


def _retrieve_session(attempt):
    """Fetch the checkout session for an attempt from the shop's account."""
    from django.conf import settings
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.checkout.Session.retrieve(
        attempt.session_id,
        stripe_account=attempt.stripe_account_id,
    )


def _record_paid_session(attempt, session):
    """Record the payment behind a paid session (idempotent).

    Goes through StripeService's recording path so the same dedup guard,
    platform-fee record, receipts, and in-portal notification apply whether
    the payment arrives by webhook, sweep, or landing page. The webhook and
    this path both key on the payment_intent id, so whichever runs second
    is a no-op.
    """
    from django.conf import settings
    from apps.billing.services.stripe_service import StripeService

    pi_id = _field(session, 'payment_intent') or ''
    amount_cents = _field(session, 'amount_total', 0) or 0

    application_fee = None
    on_behalf_of = None
    if pi_id:
        try:
            pi = stripe.PaymentIntent.retrieve(
                pi_id, stripe_account=attempt.stripe_account_id,
            )
            amount_cents = _field(pi, 'amount_received', amount_cents)
            application_fee = _field(pi, 'application_fee_amount')
            on_behalf_of = _field(pi, 'on_behalf_of')
        except stripe.error.StripeError:
            logger.warning(
                f"Reconcile: could not retrieve PI {pi_id} for "
                f"{attempt.session_id}; recording from session amount",
                exc_info=True,
            )

    svc = StripeService()
    # The recording path itself needs no Stripe API access, only the
    # metadata below — so it works even when reconcile runs in a context
    # where StripeService would report disabled (belt and braces).
    result = svc._handle_payment_succeeded(
        {
            'id': pi_id,
            'amount_received': amount_cents,
            'application_fee_amount': application_fee,
            'on_behalf_of': on_behalf_of,
            'metadata': {'rs_invoice_id': str(attempt.invoice_id)},
        },
        event_account=attempt.stripe_account_id,
    )
    logger.info(
        f"Reconcile: session {attempt.session_id} paid → recorded on "
        f"invoice #{attempt.invoice_id} (result: "
        f"{ {k: result.get(k) for k in ('success', 'duplicate', 'flagged')} })"
    )
    return result


def _mark_attempt(attempt, status, pi_id=''):
    attempt.status = status
    if pi_id:
        attempt.payment_intent_id = pi_id
    if status in ('COMPLETE', 'EXPIRED') and not attempt.resolved_at:
        attempt.resolved_at = timezone.now()
    attempt.save(update_fields=['status', 'payment_intent_id', 'resolved_at'])


def sync_attempt(attempt, expire_open=False):
    """Verify one attempt against Stripe.

    Returns one of: 'recorded' (session was paid; payment ensured in DB),
    'open' (customer may still pay; expired on Stripe when expire_open),
    'expired' (session dead, nothing owed).

    Raises StripeUnavailable when Stripe cannot confirm the state.
    """
    if not _stripe_ready():
        raise StripeUnavailable("Stripe is not configured")

    try:
        session = _retrieve_session(attempt)
    except stripe.error.InvalidRequestError:
        # Session unknown to Stripe (deleted test data, wrong account):
        # nothing can ever complete it — resolve as expired.
        logger.warning(
            f"Reconcile: session {attempt.session_id} not found on "
            f"{attempt.stripe_account_id}; marking expired", exc_info=True,
        )
        _mark_attempt(attempt, 'EXPIRED')
        return 'expired'
    except stripe.error.StripeError as e:
        raise StripeUnavailable(str(e))

    status = _field(session, 'status', 'open')
    payment_status = _field(session, 'payment_status', 'unpaid')

    if payment_status in ('paid', 'no_payment_required'):
        _record_paid_session(attempt, session)
        _mark_attempt(attempt, 'COMPLETE', _field(session, 'payment_intent') or '')
        return 'recorded'

    if status == 'expired':
        _mark_attempt(attempt, 'EXPIRED')
        return 'expired'

    # Still open. Optionally kill it so the customer can't pay after a
    # manual payment is recorded.
    if expire_open:
        try:
            stripe.checkout.Session.expire(
                attempt.session_id,
                stripe_account=attempt.stripe_account_id,
            )
            _mark_attempt(attempt, 'EXPIRED')
            return 'expired'
        except stripe.error.InvalidRequestError:
            # Lost the race: the customer completed payment between our
            # retrieve and expire. Re-check and record.
            try:
                session = _retrieve_session(attempt)
            except stripe.error.StripeError as e:
                raise StripeUnavailable(str(e))
            if _field(session, 'payment_status') in ('paid', 'no_payment_required'):
                _record_paid_session(attempt, session)
                _mark_attempt(
                    attempt, 'COMPLETE', _field(session, 'payment_intent') or '',
                )
                return 'recorded'
            raise StripeUnavailable(
                f"Could not expire open session {attempt.session_id}"
            )
        except stripe.error.StripeError as e:
            raise StripeUnavailable(str(e))

    return 'open'


def guard_manual_payment(invoice):
    """Run before recording a manual payment against `invoice`.

    Returns (allow, info) where info is a dict:
        recorded  – count of online payments found on Stripe and recorded now
        expired   – count of open checkout sessions cancelled to block double-pay
        message   – human-readable reason when allow is False

    Never allows a manual record while an online payment for the same
    invoice could still land: paid sessions get recorded first (the caller
    must re-check amount_due), open sessions get expired, and verification
    failure blocks the manual record outright.
    """
    from apps.billing.models import StripeCheckoutAttempt

    pending = list(
        StripeCheckoutAttempt.objects.filter(invoice=invoice, status='OPEN')
    )
    info = {'recorded': 0, 'expired': 0, 'message': None}
    if not pending:
        return True, info

    for attempt in pending:
        try:
            outcome = sync_attempt(attempt, expire_open=True)
        except StripeUnavailable as e:
            logger.warning(
                f"Manual-payment guard could not verify session "
                f"{attempt.session_id} for invoice {invoice.invoice_number}: {e}"
            )
            info['message'] = (
                "This invoice has an online payment in progress that could "
                "not be verified with Stripe just now. To prevent a double "
                "payment, the manual payment was not recorded — try again "
                "in a minute."
            )
            return False, info
        if outcome == 'recorded':
            info['recorded'] += 1
        elif outcome == 'expired':
            info['expired'] += 1

    return True, info


def resolve_session(session_id):
    """Payment-complete landing: verify one session and record if paid.

    Returns (invoice, state) where state is 'paid', 'processing', or
    'unknown'. Never raises — the landing page must always render.
    """
    from apps.billing.models import StripeCheckoutAttempt

    attempt = (
        StripeCheckoutAttempt.objects
        .select_related('invoice', 'invoice__tenant', 'invoice__customer')
        .filter(session_id=session_id)
        .first()
    )
    if attempt is None:
        return None, 'unknown'

    invoice = attempt.invoice
    if attempt.status == 'COMPLETE' or invoice.status == 'PAID':
        return invoice, 'paid'

    try:
        outcome = sync_attempt(attempt)
    except StripeUnavailable:
        return invoice, 'processing'

    if outcome == 'recorded':
        invoice.refresh_from_db()
        return invoice, 'paid'
    return invoice, 'processing'


def reconcile_open_attempts(max_age_days=7, apply=True):
    """Sweep recent OPEN attempts and record any paid sessions the webhook
    missed. Returns a summary dict. Used by the cron command."""
    from apps.billing.models import StripeCheckoutAttempt

    cutoff = timezone.now() - timezone.timedelta(days=max_age_days)
    attempts = (
        StripeCheckoutAttempt.objects
        .select_related('invoice')
        .filter(status='OPEN', created_at__gte=cutoff)
        .order_by('created_at')
    )

    summary = {'checked': 0, 'recorded': 0, 'expired': 0, 'open': 0, 'errors': 0}
    for attempt in attempts:
        summary['checked'] += 1
        if not apply:
            continue
        try:
            outcome = sync_attempt(attempt)
        except StripeUnavailable:
            summary['errors'] += 1
            continue
        key = {'recorded': 'recorded', 'expired': 'expired', 'open': 'open'}[outcome]
        summary[key] += 1

    if summary['recorded']:
        logger.warning(
            f"Reconcile sweep recorded {summary['recorded']} payment(s) the "
            f"webhook missed — check webhook health. Full summary: {summary}"
        )
    else:
        logger.info(f"Reconcile sweep: {summary}")
    return summary
