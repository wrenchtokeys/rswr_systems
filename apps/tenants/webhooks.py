"""
Stripe Webhook Handler for SaaS Subscriptions

Processes Stripe webhook events to keep tenant subscription state
in sync with Stripe. Verifies webhook signatures for security.

Events handled:
- checkout.session.completed — customer completed Stripe Checkout
- invoice.paid — subscription payment successful
- invoice.payment_failed — payment failed (past_due)
- customer.subscription.updated — plan changes, renewals
- customer.subscription.deleted — subscription fully canceled

Author: Amelia (Clawdbot AI)
"""

import json
import logging
import stripe
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.tenants.models import Tenant, SubscriptionPlan
from apps.billing.services import webhook_log
from apps.billing.services.stripe_compat import (
    invoice_price_id,
    invoice_next_attempt,
    invoice_subscription_id,
    subscription_price_id,
)
from apps.billing.services.webhook_log import WebhookPermanentError

logger = logging.getLogger(__name__)


# Stripe billing_reason values that only ever appear on subscription
# invoices. Used as a backstop when the subscription id cannot be located
# in any known payload shape -- better to process by customer than to drop
# a payment on the floor because a field moved.
_SUBSCRIPTION_BILLING_REASONS = {
    'subscription',
    'subscription_create',
    'subscription_cycle',
    'subscription_threshold',
    'subscription_update',
    'upcoming',
}


def _is_subscription_invoice(invoice):
    """True when the invoice is subscription-related regardless of shape."""
    return invoice.get('billing_reason') in _SUBSCRIPTION_BILLING_REASONS

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = getattr(settings, 'STRIPE_API_VERSION', '') or stripe.api_version


@csrf_exempt
@require_POST
def stripe_subscription_webhook(request):
    """
    POST /api/tenants/webhooks/stripe/
    
    Receives and processes Stripe webhook events for subscription billing.
    Verifies the webhook signature before processing.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    webhook_secret = getattr(settings, 'STRIPE_SUBSCRIPTION_WEBHOOK_SECRET', None) or getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

    # SECURITY: Require webhook secret in production
    if not webhook_secret:
        if not settings.DEBUG:
            logger.error(
                "Stripe subscription webhook: STRIPE_SUBSCRIPTION_WEBHOOK_SECRET is required in production. "
                "Configure this environment variable to enable webhook verification."
            )
            return HttpResponse(
                "Webhook secret not configured",
                status=500
            )
        else:
            # Development only: allow without verification (with warning)
            try:
                event = json.loads(payload)
            except (ValueError, json.JSONDecodeError):
                logger.error("Stripe webhook: could not parse payload")
                return HttpResponse("Invalid payload", status=400)
            logger.warning(
                "Stripe subscription webhook: STRIPE_SUBSCRIPTION_WEBHOOK_SECRET not set — "
                "signature verification skipped (dev mode only)"
            )
    else:
        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError:
            logger.error("Stripe webhook: invalid payload")
            return HttpResponse("Invalid payload", status=400)
        except stripe.error.SignatureVerificationError:
            logger.error("Stripe webhook: invalid signature")
            return HttpResponse("Invalid signature", status=400)

    # stripe-python v15 removed dict inheritance from StripeObject, so
    # session.get(...) in the handlers raises AttributeError on real events.
    # The signature is already verified — re-parse the raw payload so the
    # handlers work on plain dicts regardless of SDK version.
    if not isinstance(event, dict):
        event = json.loads(payload)

    event_type = event['type']
    data_object = event['data']['object']
    event_id = event.get('id', 'unknown')

    logger.info(f"Stripe webhook received: {event_type} [{event_id}]")

    # Idempotency: a redelivery of an event we already handled must not
    # re-run the handler or re-send its email.
    row, should_process = webhook_log.claim(event, 'subscription')
    if not should_process:
        return JsonResponse({'status': 'ok', 'duplicate': True})

    handler = get_subscription_handler(event_type)
    if not handler:
        logger.debug(f"Unhandled webhook event type: {event_type}")
        webhook_log.mark_ignored(row, f"no handler for {event_type}")
        return JsonResponse({'status': 'ok', 'handled': False})

    try:
        handler(data_object, event=event)
    except WebhookPermanentError as e:
        # Understood, nothing to do. Retrying would not help.
        logger.info(f"Webhook {event_type} [{event_id}] ignored: {e}")
        webhook_log.mark_ignored(row, str(e))
        return JsonResponse({'status': 'ok', 'handled': False, 'reason': str(e)})
    except Exception as e:
        # Anything that might succeed later gets a 500 so Stripe retries on
        # its own backoff (~3 days). Returning 200 here used to destroy the
        # event permanently on a transient DB or SES blip.
        logger.exception(f"Error processing webhook {event_type} [{event_id}]: {e}")
        webhook_log.mark_failed(row, e)
        return JsonResponse({
            'status': 'error',
            'message': f'Error processing {event_type}; retry expected',
        }, status=500)

    webhook_log.mark_processed(row)
    return JsonResponse({'status': 'ok'})


def _find_tenant_by_customer_id(customer_id):
    """Look up a tenant by their Stripe customer ID."""
    try:
        return Tenant.objects.get(stripe_customer_id=customer_id)
    except Tenant.DoesNotExist:
        logger.warning(f"No tenant found for Stripe customer {customer_id}")
        return None
    except Tenant.MultipleObjectsReturned:
        logger.error(f"Multiple tenants found for Stripe customer {customer_id}")
        return Tenant.objects.filter(stripe_customer_id=customer_id).first()


def _find_tenant_by_subscription_id(subscription_id):
    """Look up a tenant by their Stripe subscription ID."""
    try:
        return Tenant.objects.get(stripe_subscription_id=subscription_id)
    except Tenant.DoesNotExist:
        logger.warning(f"No tenant found for Stripe subscription {subscription_id}")
        return None


# ------------------------------------------------------------------
# Event Handlers
# ------------------------------------------------------------------

def _event_created(event):
    """Stripe's event.created (unix seconds), or None if we weren't given it."""
    if not event:
        return None
    try:
        return event.get('created')
    except AttributeError:
        return None


def _apply_in_order(tenant, event, event_type):
    """False when this event predates the last one applied to the tenant.

    Stripe does not guarantee delivery order and retries can arrive late.
    Without this, a redelivered invoice.payment_failed landing after
    invoice.paid marks a paying shop past_due.
    """
    created = _event_created(event)
    if webhook_log.should_apply(tenant, created):
        return True
    logger.warning(
        "Ignoring out-of-order %s for tenant %s: event created %s predates "
        "last applied state at %s",
        event_type, tenant.slug, created, tenant.subscription_synced_at,
    )
    return False


def _handle_checkout_completed(session, event=None):
    """
    Handle checkout.session.completed — customer completed Stripe Checkout.
    
    This fires when a customer finishes the Checkout flow and payment succeeds.
    We update the tenant with the subscription ID AND the plan (payment confirmed).
    """
    customer_id = session.get('customer')
    subscription_id = session.get('subscription')
    metadata = session.get('metadata', {})
    
    if not subscription_id:
        # Not a subscription checkout (might be a one-time payment)
        logger.debug(f"checkout.session.completed without subscription: {session.get('id')}")
        return

    # Stripe fires checkout.session.completed even when payment_status is
    # 'unpaid' (async payment methods — money hasn't arrived). Only activate
    # on 'paid' or 'no_payment_required' (trial/zero-amount); otherwise the
    # invoice.paid event that fires when the money clears will activate.
    payment_status = session.get('payment_status')
    if payment_status not in (None, 'paid', 'no_payment_required'):
        logger.info(
            f"checkout.session.completed with payment_status={payment_status!r} "
            f"for customer {customer_id} — deferring activation to invoice.paid"
        )
        return

    # Try to find tenant by customer ID
    tenant = _find_tenant_by_customer_id(customer_id)
    
    # Fallback: check metadata for tenant_id
    if not tenant:
        tenant_id = metadata.get('tenant_id')
        if tenant_id:
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                pass
    
    if not tenant:
        raise WebhookPermanentError(
            f"checkout.session.completed: no tenant for customer {customer_id} "
            f"or metadata tenant_id"
        )

    if not _apply_in_order(tenant, event, 'checkout.session.completed'):
        return

    # Get plan from metadata
    plan_slug = metadata.get('plan_slug')
    plan = None
    if plan_slug:
        plan = SubscriptionPlan.objects.filter(slug=plan_slug).first()
    
    # Update tenant with subscription info AND plan (payment is now confirmed)
    tenant.stripe_subscription_id = subscription_id
    tenant.subscription_status = 'active'
    # Reactivation clears any grace period from a previous lapse. A stale
    # grace_period_end left on an active tenant makes the middleware treat
    # their NEXT "cancel at period end" as an immediate lockout. (A3)
    tenant.grace_period_end = None

    update_fields = ['stripe_subscription_id', 'subscription_status', 'grace_period_end']
    
    if plan:
        tenant.plan = plan.slug
        tenant.subscription_plan = plan
        update_fields.extend(['plan', 'subscription_plan'])
        logger.info(
            f"checkout.session.completed: Tenant {tenant.slug} upgraded to {plan.name}. "
            f"Subscription: {subscription_id}"
        )
    else:
        logger.info(
            f"checkout.session.completed: Tenant {tenant.slug} subscribed. "
            f"Subscription: {subscription_id}"
        )

    webhook_log.stamp_synced(tenant, _event_created(event), update_fields)
    tenant.save(update_fields=update_fields)


def _handle_invoice_paid(invoice, event=None):
    """
    Handle invoice.paid — subscription payment was successful.
    
    This fires when:
    - A new subscription's first invoice is paid
    - A recurring subscription invoice is paid
    """
    customer_id = invoice.get('customer')
    # Basil (2025-03-31) moved this to parent.subscription_details.subscription.
    # Reading invoice['subscription'] directly meant a payload from a newer
    # API version silently returned here and no payment was ever processed.
    subscription_id = invoice_subscription_id(invoice)

    if not subscription_id and not _is_subscription_invoice(invoice):
        # Genuinely not a subscription invoice (a one-off charge).
        logger.debug(f"invoice.paid for non-subscription invoice {invoice.get('id')}")
        return

    tenant = _find_tenant_by_customer_id(customer_id)
    if not tenant:
        raise WebhookPermanentError(f"no tenant for customer {customer_id}")

    if not _apply_in_order(tenant, event, 'invoice.paid'):
        return

    # Check previous status before updating (for payment_recovered detection)
    previous_status = tenant.subscription_status

    # Update tenant status to active
    tenant.subscription_status = 'active'
    # A successful payment reactivates: clear any grace period left over
    # from a previous lapse so it can't lock the tenant out later. (A3)
    tenant.grace_period_end = None

    # Update subscription ID if it changed
    if subscription_id and tenant.stripe_subscription_id != subscription_id:
        tenant.stripe_subscription_id = subscription_id

    update_fields = ['subscription_status', 'stripe_subscription_id', 'grace_period_end']

    # Self-heal the plan from the invoice's price ID. If the original
    # checkout.session.completed was lost (endpoint misconfig, transient
    # error), the tenant would otherwise pay every month while stuck on
    # plan='trial' — and get locked out when the trial clock runs out.
    if tenant.plan == 'trial':
        try:
            # Basil replaced line.price with line.pricing.price_details.price,
            # so the old lookup returned '' and the self-heal never fired --
            # exactly when it was needed most.
            price_id = invoice_price_id(invoice)
            if price_id:
                plan = SubscriptionPlan.objects.filter(
                    stripe_price_id=price_id
                ).first() or SubscriptionPlan.objects.filter(
                    stripe_annual_price_id=price_id
                ).first()
                if plan and plan.slug != 'trial':
                    tenant.plan = plan.slug
                    tenant.subscription_plan = plan
                    update_fields.extend(['plan', 'subscription_plan'])
                    logger.warning(
                        f"invoice.paid: Tenant {tenant.slug} was paying while on "
                        f"plan='trial' — self-healed to {plan.name} from price {price_id}"
                    )
        except Exception as e:
            logger.warning(f"invoice.paid plan self-heal failed for {tenant.slug}: {e}")

    webhook_log.stamp_synced(tenant, _event_created(event), update_fields)
    tenant.save(update_fields=update_fields)

    logger.info(
        f"invoice.paid: Tenant {tenant.slug} subscription payment successful. "
        f"Invoice: {invoice.get('id')}"
    )

    # If transitioning from past_due → active, send payment recovered email
    if previous_status == 'past_due':
        _notify_owners_and_managers(tenant, 'payment_recovered', {
            'invoice_id': invoice.get('id'),
        })


def _handle_invoice_payment_failed(invoice, event=None):
    """
    Handle invoice.payment_failed — subscription payment failed.
    
    Marks the tenant as past_due. Stripe will retry automatically
    based on their retry schedule. The shop owner should update their
    payment method via the Billing Portal.
    """
    customer_id = invoice.get('customer')
    # See _handle_invoice_paid: reading invoice['subscription'] directly is
    # not safe across API versions, and returning early here would silently
    # stop every past_due transition and every dunning email.
    subscription_id = invoice_subscription_id(invoice)

    if not subscription_id and not _is_subscription_invoice(invoice):
        return

    tenant = _find_tenant_by_customer_id(customer_id)
    if not tenant:
        raise WebhookPermanentError(f"no tenant for customer {customer_id}")

    # The ordering guard matters most here: a retried payment_failed
    # arriving after invoice.paid would otherwise flip a paying shop back
    # to past_due -- and past_due now restricts access.
    if not _apply_in_order(tenant, event, 'invoice.payment_failed'):
        return

    tenant.subscription_status = 'past_due'
    update_fields = ['subscription_status']
    webhook_log.stamp_synced(tenant, _event_created(event), update_fields)
    tenant.save(update_fields=update_fields)
    
    logger.warning(
        f"invoice.payment_failed: Tenant {tenant.slug} payment failed. "
        f"Invoice: {invoice.get('id')}. Attempt: {invoice.get('attempt_count', '?')}"
    )
    
    # Notify shop owners AND managers about failed payment
    _notify_owners_and_managers(tenant, 'payment_failed', {
        'invoice_id': invoice.get('id'),
        'attempt_count': invoice.get('attempt_count', 1),
    })


def _handle_subscription_updated(subscription, event=None):
    """
    Handle customer.subscription.updated — plan changes, status updates.

    This fires when:
    - Subscription status changes (active, past_due, etc.)
    - Plan is changed (upgrade/downgrade)
    - Subscription is set to cancel at period end

    The mapping itself lives in subscription_reconcile.apply_subscription_state
    so the hourly reconcile sweep repairs drift using exactly the same rules
    a webhook would have applied. One mapping, two callers.
    """
    from apps.tenants.services.subscription_reconcile import (
        apply_subscription_state,
    )

    subscription_id = subscription.get('id')
    customer_id = subscription.get('customer')

    tenant = (
        _find_tenant_by_subscription_id(subscription_id)
        or _find_tenant_by_customer_id(customer_id)
    )
    if not tenant:
        raise WebhookPermanentError(
            f"no tenant for subscription {subscription_id} / customer {customer_id}"
        )

    if not _apply_in_order(tenant, event, 'customer.subscription.updated'):
        return

    apply_subscription_state(
        tenant, subscription, source='webhook',
        synced_at=_event_created(event),
    )


def _handle_subscription_deleted(subscription, event=None):
    """
    Handle customer.subscription.deleted — subscription fully canceled.
    
    The subscription has ended (past the cancellation period).
    Tenant loses access to paid features.
    """
    subscription_id = subscription.get('id')
    customer_id = subscription.get('customer')
    
    tenant = (
        _find_tenant_by_subscription_id(subscription_id)
        or _find_tenant_by_customer_id(customer_id)
    )
    if not tenant:
        raise WebhookPermanentError(
            f"no tenant for subscription {subscription_id} / customer {customer_id}"
        )

    if not _apply_in_order(tenant, event, 'customer.subscription.deleted'):
        return

    tenant.subscription_status = 'expired'
    tenant.plan = 'trial'  # Revert to trial-level access

    # Set 30-day grace period from now — unless one is already running.
    # Webhook replays / duplicate deliveries must not keep extending free
    # read-only access. (A successful payment clears grace_period_end, so
    # a genuine second lapse still gets a fresh grace period.)
    if not tenant.grace_period_end:
        tenant.grace_period_end = timezone.now() + timezone.timedelta(days=30)

    # Try to set subscription_plan to trial plan
    trial_plan = SubscriptionPlan.objects.filter(slug='trial').first()
    if trial_plan:
        tenant.subscription_plan = trial_plan

    update_fields = [
        'subscription_status', 'plan', 'subscription_plan', 'grace_period_end',
    ]
    webhook_log.stamp_synced(tenant, _event_created(event), update_fields)
    tenant.save(update_fields=update_fields)

    logger.info(
        f"subscription.deleted: Tenant {tenant.slug} subscription ended. "
        f"Reverted to trial plan. Grace period until {tenant.grace_period_end}."
    )

    # Notify shop owners AND managers their subscription has ended
    _notify_owners_and_managers(tenant, 'subscription_ended', {})


# ----------------------------------------------------------------------
# Revenue-visibility events
#
# Deliberately NOT handled, with reasons:
#   customer.subscription.trial_will_end -- trials here are local
#     (trial_started_at + plan.trial_days), never Stripe trials, so Stripe
#     never fires it. check_subscription_alerts already covers this.
#   subscription_schedule.*  -- the resulting customer.subscription.updated
#     already carries the state change.
#   payment_method.attached  -- no local state to mirror.
#   charge.refunded          -- rare enough to handle by hand.
# ----------------------------------------------------------------------

def _handle_invoice_upcoming(invoice, event=None):
    """Stripe's ~3-day heads-up before it charges the card again.

    A renewal that arrives with no warning is a chargeback risk and a
    support ticket. Notifying costs nothing and pre-empts both.
    """
    tenant = _find_tenant_by_customer_id(invoice.get('customer'))
    if not tenant:
        raise WebhookPermanentError(
            f"no tenant for customer {invoice.get('customer')}"
        )

    _notify_owners_and_managers(tenant, 'renewal_upcoming', {
        'invoice_id': invoice.get('id'),
        'amount_due': invoice.get('amount_due'),
        'next_payment_attempt': invoice_next_attempt(invoice),
    })


def _handle_invoice_action_required(invoice, event=None):
    """3DS / bank confirmation needed before the payment can complete.

    Previously invisible: the charge simply never completed and the shop
    found out when they hit past_due.
    """
    tenant = _find_tenant_by_customer_id(invoice.get('customer'))
    if not tenant:
        raise WebhookPermanentError(
            f"no tenant for customer {invoice.get('customer')}"
        )

    _notify_owners_and_managers(tenant, 'payment_action_required', {
        'invoice_id': invoice.get('id'),
        'hosted_invoice_url': invoice.get('hosted_invoice_url'),
    })


def _handle_invoice_uncollectible(invoice, event=None):
    """Stripe gave up on this invoice. Terminal, same as 'unpaid'.

    Reuses the expired + grace-period treatment so the owner keeps
    read-only access and a reactivation path instead of a hard lockout.
    """
    tenant = _find_tenant_by_customer_id(invoice.get('customer'))
    if not tenant:
        raise WebhookPermanentError(
            f"no tenant for customer {invoice.get('customer')}"
        )

    if not _apply_in_order(tenant, event, 'invoice.marked_uncollectible'):
        return

    tenant.subscription_status = 'expired'
    update_fields = ['subscription_status']
    if not tenant.grace_period_end:
        tenant.grace_period_end = timezone.now() + timezone.timedelta(days=30)
        update_fields.append('grace_period_end')

    webhook_log.stamp_synced(tenant, _event_created(event), update_fields)
    tenant.save(update_fields=update_fields)

    logger.warning(
        f"invoice.marked_uncollectible: Tenant {tenant.slug} written off. "
        f"Invoice: {invoice.get('id')}"
    )
    _notify_owners_and_managers(tenant, 'subscription_ended', {
        'invoice_id': invoice.get('id'),
    })


def _handle_dispute_created(dispute, event=None):
    """A subscription chargeback. Alerts the PLATFORM, not the shop.

    This is our money and our Stripe account's risk profile, not something
    to ask the shop about. Deliberately does not touch tenant state --
    disputing is not the same as cancelling.
    """
    charge_id = dispute.get('charge')
    amount = dispute.get('amount')
    reason = dispute.get('reason')

    logger.error(
        f"STRIPE DISPUTE opened: charge={charge_id} amount={amount} "
        f"reason={reason} status={dispute.get('status')}. "
        f"Respond in the Stripe Dashboard before the evidence deadline."
    )

    alert_to = getattr(settings, 'PLATFORM_ALERT_EMAIL', '') or getattr(
        settings, 'DEFAULT_FROM_EMAIL', ''
    )
    if not alert_to:
        return

    try:
        from core.email_utils import send_branded_email
        send_branded_email(
            subject="Stripe dispute opened",
            recipient_list=[alert_to],
            headline="A payment has been disputed",
            body_paragraphs=[
                f"Charge {charge_id} was disputed for "
                f"{(amount or 0) / 100:.2f} ({reason}).",
                "Respond in the Stripe Dashboard before the evidence "
                "deadline or the dispute is lost by default.",
            ],
            fail_silently=True,
        )
    except Exception:
        logger.exception("Could not send dispute alert")


def _get_owner_and_manager_emails(tenant):
    """Return a list of email addresses for all owners and managers of a tenant."""
    from apps.tenants.models import TenantMembership
    emails = set()
    if tenant.owner and tenant.owner.email:
        emails.add(tenant.owner.email)
    manager_emails = (
        TenantMembership.objects
        .filter(tenant=tenant, role='manager', is_active=True)
        .exclude(user__email='')
        .values_list('user__email', flat=True)
    )
    emails.update(manager_emails)
    return list(emails)


def _notify_owner(tenant, event_type, context):
    """
    Send email notification to shop owner about subscription events.
    Kept for backward compatibility — delegates to _notify_owners_and_managers.
    """
    _notify_owners_and_managers(tenant, event_type, context)


# Event type -> handler name. Both the dedicated subscription endpoint and
# the billing endpoint's fallback delegation dispatch through here.
#
# Names, not function objects: a dict of objects binds at import time, so a
# test patching `webhooks._handle_invoice_paid` would silently keep hitting
# the original. Resolving per call also keeps the table readable as a plain
# list of what we accept.
SUBSCRIPTION_HANDLER_NAMES = {
    'checkout.session.completed': '_handle_checkout_completed',
    'invoice.paid': '_handle_invoice_paid',
    'invoice.payment_failed': '_handle_invoice_payment_failed',
    'customer.subscription.updated': '_handle_subscription_updated',
    'customer.subscription.deleted': '_handle_subscription_deleted',
    # Revenue visibility
    'invoice.upcoming': '_handle_invoice_upcoming',
    'invoice.payment_action_required': '_handle_invoice_action_required',
    'invoice.marked_uncollectible': '_handle_invoice_uncollectible',
    'charge.dispute.created': '_handle_dispute_created',
}


def get_subscription_handler(event_type):
    """Resolve a handler by event type, or None if we don't handle it."""
    name = SUBSCRIPTION_HANDLER_NAMES.get(event_type)
    return globals().get(name) if name else None


def handle_subscription_event(event_type, data_object, event=None):
    """
    Process a subscription-related Stripe webhook event.

    Called from the unified billing webhook endpoint to handle SaaS
    subscription events without needing a separate webhook URL.

    Returns a dict with 'success' and 'handled' keys. `retryable` is True
    when the caller should surface a 5xx so Stripe redelivers -- this used
    to always report success, which told Stripe to discard an event we had
    in fact failed to process.
    """
    handler = get_subscription_handler(event_type)
    if not handler:
        return {'success': True, 'handled': False}

    try:
        handler(data_object, event=event)
        return {'success': True, 'handled': True, 'event_type': event_type}
    except WebhookPermanentError as e:
        logger.info(f"Subscription webhook {event_type} ignored: {e}")
        return {
            'success': True, 'handled': True, 'event_type': event_type,
            'ignored': True, 'reason': str(e),
        }
    except Exception as e:
        logger.exception(f"Error processing subscription webhook {event_type}: {e}")
        return {
            'success': False, 'handled': True, 'event_type': event_type,
            'error': str(e), 'retryable': True,
        }


def _notify_owners_and_managers(tenant, event_type, context):
    """
    Send email notification to ALL owners AND managers about subscription events.

    Uses the configured email backend (Amazon SES over SMTP).
    """
    try:
        from django.conf import settings as django_settings
        from core.email_utils import send_branded_email

        recipient_list = _get_owner_and_manager_emails(tenant)
        if not recipient_list:
            logger.warning(f"Cannot notify owners/managers for tenant {tenant.slug}: no emails found")
            return

        owner = tenant.owner
        owner_name = (owner.first_name or 'there') if owner else 'there'
        base_url = getattr(django_settings, 'BASE_URL', 'https://rssystems.io')

        if event_type == 'payment_failed':
            attempt_count = context.get('attempt_count', 1)
            max_attempts = 4
            retry_text = (
                f"This was attempt {attempt_count} of {max_attempts}. "
                "Stripe will retry automatically, but we recommend updating "
                "your payment method now to avoid service interruption."
            )
            send_branded_email(
                subject=f'Payment failed for {tenant.name}',
                recipient_list=recipient_list,
                headline='Payment Failed',
                body_paragraphs=[
                    f"Hi {owner_name},",
                    f"We were unable to process your payment for {tenant.name} (attempt #{attempt_count}).",
                    retry_text,
                ],
                button_text='Update Payment Method',
                button_url=f'{base_url}/owner/update-payment-method/',
                tenant=tenant,
                fail_silently=True,
            )
        elif event_type == 'payment_recovered':
            send_branded_email(
                subject=f'Payment successful for {tenant.name}',
                recipient_list=recipient_list,
                headline='Good news!',
                body_paragraphs=[
                    f"Hi {owner_name},",
                    f"Your payment for {tenant.name} has been successfully processed. "
                    "Your account is back to active status.",
                    "No further action is needed — thank you for being a valued customer!",
                ],
                button_text='Go to Dashboard',
                button_url=f'{base_url}/owner/',
                tenant=tenant,
                fail_silently=True,
            )
        elif event_type == 'subscription_ended':
            send_branded_email(
                subject=f'Your {tenant.name} subscription has ended',
                recipient_list=recipient_list,
                headline='Subscription Ended',
                body_paragraphs=[
                    f"Hi {owner_name},",
                    f"Your subscription for {tenant.name} has ended.",
                    "Your account has been moved to read-only mode for 30 days. During this time you can view your data but cannot make changes.",
                    "Resubscribe anytime to restore full access.",
                ],
                button_text='Resubscribe Now',
                button_url=f'{base_url}/owner/billing/',
                tenant=tenant,
                fail_silently=True,
            )
        else:
            send_branded_email(
                subject=f'RS Systems notification for {tenant.name}',
                recipient_list=recipient_list,
                headline='Account Notification',
                body_paragraphs=[
                    f"Hi {owner_name},",
                    f"A subscription event occurred for {tenant.name}.",
                ],
                tenant=tenant,
                fail_silently=True,
            )

        logger.info(
            f"Sent {event_type} notification to {recipient_list} for tenant {tenant.slug}"
        )

    except Exception as e:
        logger.error(f"Failed to send {event_type} notification for tenant {tenant.slug}: {e}")
