"""
Proof of an online payment, for the shop.

A Stripe webhook tells RS Systems "invoice N was paid" and the invoice page
used to say exactly that and nothing more. The shop then had the same proof
a customer has: a line that says "paid online". Everything a shop actually
wants to know lives one object deeper on their own Connect account —

    PaymentIntent  → latest_charge          card brand / last4, receipt_url
    Charge         → balance_transaction    gross, Stripe's fee, net,
                                            available_on
    Payout                                  when it reached the bank

— so this module reads those once and caches them on `StripePaymentDetail`
beside the `Payment` row. Three entry points:

* `sync_from_stripe(payment)` — one PaymentIntent retrieve (with the charge
  and balance transaction expanded) on the shop's account. Called right
  after a payment is recorded and lazily from the invoice page for anything
  recorded before this existed. Idempotent; failures are stored, never
  raised, and retried no more than hourly.
* `apply_payout(payout, account_id)` — stamps every detail whose charge the
  payout carried. Fed by the `payout.*` webhooks on the Connect endpoint
  and by `find_payout()` when a page is opened before those events arrive.
* `refresh_for_payments(payments, tenant)` — what the invoice view calls.
  Bounded: at most one charge sync per payment per hour on failure, one
  payout search per payment every six hours while the money is on its way.

Every number shown is Stripe's own. Nothing here derives a fee from a
percentage — a shop reconciles these lines against its bank statement, and
a close guess is worse than a blank.
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.billing.services.stripe_compat import (
    _dig, _field, _id_of, configure_stripe,
)

try:
    import stripe
except ImportError:  # pragma: no cover - stripe is a hard dependency
    stripe = None

logger = logging.getLogger(__name__)

# A failed charge sync is retried no sooner than this.
RETRY_SYNC_AFTER = timedelta(hours=1)
# While a payment waits for its payout, look for one no more often than this.
PAYOUT_LOOKUP_EVERY = timedelta(hours=6)
# Payouts are searched from the day the funds became available for this long.
# Stripe's slowest automatic schedule is monthly; 35 days covers it.
PAYOUT_SEARCH_WINDOW = timedelta(days=35)
# Hard cap on Stripe calls one page view may spend chasing a payout.
PAYOUT_SEARCH_MAX_CALLS = 12
BALANCE_TXN_PAGE = 100
BALANCE_TXN_MAX_PAGES = 5


def stripe_ready():
    """True when there is a secret key to call Stripe with."""
    return bool(stripe) and bool(getattr(settings, 'STRIPE_SECRET_KEY', None))


def _cents_to_dollars(value):
    if value is None:
        return None
    try:
        return (Decimal(int(value)) / 100).quantize(Decimal('0.01'))
    except (TypeError, ValueError):
        return None


def _ts_to_date(value):
    """Stripe's available_on / arrival_date are midnight-UTC timestamps."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _date_to_ts(day):
    return int(datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc).timestamp())


def _account_for(payment):
    tenant = getattr(payment.invoice, 'tenant', None)
    return (tenant.stripe_connect_account_id if tenant else '') or ''


def detail_for(payment):
    """The cached detail for a payment, or None. Never calls Stripe."""
    try:
        return payment.stripe_detail
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Charge-level facts: card, receipt, fees, net, available_on
# ---------------------------------------------------------------------------

def sync_from_stripe(payment, force=False):
    """Fill (or refresh) the StripePaymentDetail for one STRIPE payment.

    Returns the detail row, or None for a payment that cannot have one
    (manual method, no PaymentIntent id, shop with no Connect account).
    Never raises on Stripe's account: the error is stored on the row and
    the page shows "not available yet" instead of a 500.
    """
    from apps.billing.models import StripePaymentDetail

    if payment.payment_method != 'STRIPE' or not payment.stripe_payment_id:
        return None
    account_id = _account_for(payment)
    if not account_id:
        return None

    detail, _created = StripePaymentDetail.objects.get_or_create(
        payment=payment,
        defaults={
            'payment_intent_id': payment.stripe_payment_id,
            'stripe_account_id': account_id,
        },
    )
    # A payment loaded with select_related('stripe_detail') before the row
    # existed caches "none"; point it at the row so the template sees it.
    payment.stripe_detail = detail

    if not force:
        if detail.has_charge:
            return detail
        if detail.sync_error and detail.synced_at and (
            timezone.now() - detail.synced_at < RETRY_SYNC_AFTER
        ):
            return detail

    if not stripe_ready():
        return detail

    configure_stripe()
    try:
        intent = stripe.PaymentIntent.retrieve(
            payment.stripe_payment_id,
            expand=['latest_charge.balance_transaction'],
            stripe_account=account_id,
        )
        charge = _field(intent, 'latest_charge')
        if isinstance(charge, str):
            # Not expanded (older API behaviour) — one more call.
            charge = stripe.Charge.retrieve(
                charge, expand=['balance_transaction'], stripe_account=account_id,
            )
    except stripe.error.StripeError as exc:
        detail.sync_error = str(exc)[:300]
        detail.synced_at = timezone.now()
        detail.save(update_fields=['sync_error', 'synced_at'])
        logger.warning(
            f"Stripe detail sync failed for payment #{payment.id} "
            f"({payment.stripe_payment_id}): {exc}"
        )
        return detail

    apply_payment_intent(detail, intent, charge, account_id)
    return detail


def apply_payment_intent(detail, intent, charge, account_id):
    """Write what a PaymentIntent (+ expanded charge) says onto the detail."""
    detail.payment_intent_id = _field(intent, 'id', detail.payment_intent_id) or ''
    detail.stripe_account_id = account_id

    charge = charge if not isinstance(charge, str) else None
    if charge is not None:
        detail.charge_id = _field(charge, 'id', '') or ''
        detail.receipt_url = (_field(charge, 'receipt_url', '') or '')[:600]
        card = _dig(charge, 'payment_method_details', 'card', default=None)
        if card is not None:
            detail.card_brand = (_field(card, 'brand', '') or '')[:30]
            detail.card_last4 = (_field(card, 'last4', '') or '')[:4]
            detail.wallet = (_dig(card, 'wallet', 'type', default='') or '')[:30]
        detail.currency = (_field(charge, 'currency', '') or detail.currency or 'usd')[:3]

        txn = _field(charge, 'balance_transaction')
        if txn is not None and not isinstance(txn, str):
            detail.balance_transaction_id = _field(txn, 'id', '') or ''
            detail.gross_amount = _cents_to_dollars(_field(txn, 'amount'))
            detail.stripe_fee = _cents_to_dollars(_field(txn, 'fee'))
            detail.net_amount = _cents_to_dollars(_field(txn, 'net'))
            detail.funds_available_on = _ts_to_date(_field(txn, 'available_on'))
            detail.currency = (_field(txn, 'currency', '') or detail.currency)[:3]
            app_fee = None
            for part in (_field(txn, 'fee_details', []) or []):
                if _field(part, 'type') == 'application_fee':
                    app_fee = (app_fee or 0) + int(_field(part, 'amount', 0) or 0)
            if app_fee is not None:
                detail.platform_fee = _cents_to_dollars(app_fee)
        elif isinstance(txn, str):
            detail.balance_transaction_id = txn

    if detail.platform_fee is None:
        detail.platform_fee = _cents_to_dollars(_field(intent, 'application_fee_amount'))
    if detail.gross_amount is None:
        detail.gross_amount = _cents_to_dollars(_field(intent, 'amount_received'))

    detail.sync_error = ''
    detail.synced_at = timezone.now()
    detail.save()

    payment = detail.payment
    if detail.charge_id and payment.stripe_charge_id != detail.charge_id:
        payment.stripe_charge_id = detail.charge_id
        payment.save(update_fields=['stripe_charge_id'])
    return detail


# ---------------------------------------------------------------------------
# Payouts: when the money reached the bank
# ---------------------------------------------------------------------------

def _payout_charge_ids(payout_id, account_id):
    """Source ids (ch_…/py_…) of every balance transaction in a payout."""
    ids = set()
    starting_after = None
    for _ in range(BALANCE_TXN_MAX_PAGES):
        params = {
            'payout': payout_id,
            'limit': BALANCE_TXN_PAGE,
            'stripe_account': account_id,
        }
        if starting_after:
            params['starting_after'] = starting_after
        page = stripe.BalanceTransaction.list(**params)
        data = _field(page, 'data', []) or []
        for txn in data:
            source = _id_of(_field(txn, 'source'))
            if source:
                ids.add(source)
        if not _field(page, 'has_more') or not data:
            break
        starting_after = _field(data[-1], 'id')
        if not starting_after:
            break
    return ids


def apply_payout(payout, account_id):
    """Stamp every detail whose charge this payout carried.

    `payout` is the Stripe Payout object (webhook payload or API result).
    Returns {'payout_id', 'status', 'matched'}; raises StripeError so a
    webhook caller can answer 5xx and have Stripe redeliver.
    """
    from apps.billing.models import StripePaymentDetail

    if not stripe:  # pragma: no cover
        return {'matched': 0}
    configure_stripe()

    payout_id = _field(payout, 'id', '') or ''
    status = (_field(payout, 'status', '') or '')[:20]
    arrival = _ts_to_date(_field(payout, 'arrival_date'))
    if not payout_id or not account_id:
        return {'payout_id': payout_id, 'status': status, 'matched': 0}

    charge_ids = _payout_charge_ids(payout_id, account_id)
    matched = 0
    if charge_ids:
        matched = StripePaymentDetail.objects.filter(
            stripe_account_id=account_id, charge_id__in=charge_ids,
        ).update(
            payout_id=payout_id,
            payout_status=status,
            payout_arrival_on=arrival,
        )
    # A payout we already know about (failed after paid, say) carries the
    # same charges; follow Stripe's latest word on it either way.
    if payout_id:
        StripePaymentDetail.objects.filter(
            stripe_account_id=account_id, payout_id=payout_id,
        ).exclude(payout_status=status).update(
            payout_status=status, payout_arrival_on=arrival,
        )
    logger.info(
        f"Payout {payout_id} ({status}) on {account_id}: "
        f"{matched} payment(s) stamped"
    )
    return {'payout_id': payout_id, 'status': status, 'matched': matched}


def find_payout(detail):
    """Look for the payout that carried this charge, from the day the funds
    became available. Bounded by PAYOUT_SEARCH_MAX_CALLS; stamps synced_at
    whether or not it finds one so the page does not repeat the search for
    six hours. Returns True if the detail now has a payout."""
    if not stripe_ready() or not detail.charge_id or not detail.funds_available_on:
        return False
    account_id = detail.stripe_account_id
    if not account_id:
        return False

    configure_stripe()
    calls = 0
    try:
        start = detail.funds_available_on - timedelta(days=1)
        end = detail.funds_available_on + PAYOUT_SEARCH_WINDOW
        page = stripe.Payout.list(
            limit=100,
            arrival_date={'gte': _date_to_ts(start), 'lte': _date_to_ts(end)},
            stripe_account=account_id,
        )
        calls += 1
        payouts = list(_field(page, 'data', []) or [])
        # Stripe lists newest first; the one we want is the earliest after
        # the funds cleared, so walk oldest-first.
        payouts.reverse()
        for payout in payouts:
            if calls >= PAYOUT_SEARCH_MAX_CALLS:
                break
            calls += 1
            apply_payout(payout, account_id)
            detail.refresh_from_db(fields=['payout_id', 'payout_status', 'payout_arrival_on'])
            if detail.payout_id:
                break
    except stripe.error.StripeError as exc:
        logger.warning(
            f"Payout lookup failed for charge {detail.charge_id} on "
            f"{account_id}: {exc}"
        )
    detail.synced_at = timezone.now()
    detail.save(update_fields=['synced_at'])
    return bool(detail.payout_id)


# ---------------------------------------------------------------------------
# What the invoice page calls
# ---------------------------------------------------------------------------

def refresh_for_payments(payments, tenant=None):
    """Make sure every STRIPE payment in `payments` carries what Stripe
    knows, spending as few calls as the cache allows. Safe to call on
    every page view; never raises."""
    now = timezone.now()
    today = timezone.localdate()
    for payment in payments:
        if payment.payment_method != 'STRIPE':
            continue
        try:
            existing = detail_for(payment)
            had_charge = bool(existing and existing.has_charge)
            detail = sync_from_stripe(payment)
            if detail is None or not detail.has_charge:
                continue
            if detail.payout_status == 'paid':
                continue
            if not detail.funds_available_on or detail.funds_available_on > today:
                continue
            # Just synced the charge: the funds are already available, so
            # look for the payout now rather than six hours from now.
            if had_charge and detail.synced_at and now - detail.synced_at < PAYOUT_LOOKUP_EVERY:
                continue
            find_payout(detail)
        except Exception:
            logger.exception(
                f"Could not refresh Stripe detail for payment #{payment.id}"
            )
