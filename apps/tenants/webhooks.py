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

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


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
                event = stripe.Event.construct_from(
                    json.loads(payload), stripe.api_key
                )
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
    
    event_type = event['type']
    data_object = event['data']['object']
    
    logger.info(f"Stripe webhook received: {event_type} [{event.get('id', 'unknown')}]")
    
    # Route to handler
    handlers = {
        'checkout.session.completed': _handle_checkout_completed,
        'invoice.paid': _handle_invoice_paid,
        'invoice.payment_failed': _handle_invoice_payment_failed,
        'customer.subscription.updated': _handle_subscription_updated,
        'customer.subscription.deleted': _handle_subscription_deleted,
    }
    
    handler = handlers.get(event_type)
    if handler:
        try:
            handler(data_object)
        except Exception as e:
            logger.exception(f"Error processing webhook {event_type}: {e}")
            # Return 200 anyway so Stripe doesn't retry
            # (we log the error for investigation)
            return JsonResponse({
                'status': 'error',
                'message': f'Error processing {event_type}',
            }, status=200)
    else:
        logger.debug(f"Unhandled webhook event type: {event_type}")
    
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

def _handle_checkout_completed(session):
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
        logger.warning(
            f"checkout.session.completed: No tenant found for customer {customer_id} "
            f"or metadata tenant_id"
        )
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
    
    tenant.save(update_fields=update_fields)


def _handle_invoice_paid(invoice):
    """
    Handle invoice.paid — subscription payment was successful.
    
    This fires when:
    - A new subscription's first invoice is paid
    - A recurring subscription invoice is paid
    """
    customer_id = invoice.get('customer')
    subscription_id = invoice.get('subscription')
    
    if not subscription_id:
        # Not a subscription invoice (might be a one-off)
        logger.debug(f"invoice.paid for non-subscription invoice {invoice.get('id')}")
        return
    
    tenant = _find_tenant_by_customer_id(customer_id)
    if not tenant:
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
            lines = invoice.get('lines', {}).get('data', [])
            price_id = ''
            if lines:
                price_id = (lines[0].get('price') or {}).get('id', '')
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


def _handle_invoice_payment_failed(invoice):
    """
    Handle invoice.payment_failed — subscription payment failed.
    
    Marks the tenant as past_due. Stripe will retry automatically
    based on their retry schedule. The shop owner should update their
    payment method via the Billing Portal.
    """
    customer_id = invoice.get('customer')
    subscription_id = invoice.get('subscription')
    
    if not subscription_id:
        return
    
    tenant = _find_tenant_by_customer_id(customer_id)
    if not tenant:
        return
    
    tenant.subscription_status = 'past_due'
    tenant.save(update_fields=['subscription_status'])
    
    logger.warning(
        f"invoice.payment_failed: Tenant {tenant.slug} payment failed. "
        f"Invoice: {invoice.get('id')}. Attempt: {invoice.get('attempt_count', '?')}"
    )
    
    # Notify shop owners AND managers about failed payment
    _notify_owners_and_managers(tenant, 'payment_failed', {
        'invoice_id': invoice.get('id'),
        'attempt_count': invoice.get('attempt_count', 1),
    })


def _handle_subscription_updated(subscription):
    """
    Handle customer.subscription.updated — plan changes, status updates.
    
    This fires when:
    - Subscription status changes (active, past_due, etc.)
    - Plan is changed (upgrade/downgrade)
    - Subscription is set to cancel at period end
    """
    subscription_id = subscription.get('id')
    customer_id = subscription.get('customer')
    
    tenant = (
        _find_tenant_by_subscription_id(subscription_id)
        or _find_tenant_by_customer_id(customer_id)
    )
    if not tenant:
        return
    
    # Update subscription status
    stripe_status = subscription.get('status', '')
    status_map = {
        'active': 'active',
        'past_due': 'past_due',
        'canceled': 'canceled',
        'trialing': 'trialing',
        # 'incomplete' = checkout started but not paid.  Don't upgrade plan.
        # Map to 'trialing' (current access unchanged) rather than storing the
        # invalid value 'incomplete' which is not in Tenant.subscription_status
        # choices.  The 'active' status arrives via invoice.paid webhook once
        # payment clears.  (CODE-228)
        'incomplete': 'trialing',
        'incomplete_expired': 'expired',
        # 'unpaid' is Stripe's TERMINAL "payment retries exhausted" state.
        # Mapping it to 'past_due' (warn-only) let the tenant keep full
        # access indefinitely, for free, until Stripe eventually deleted
        # the subscription. Map to 'expired' — a blocking state; the grace
        # period is granted below so the owner gets read-only access and
        # the upgrade path instead of a hard lockout. (D4)
        'unpaid': 'expired',
    }
    new_status = status_map.get(stripe_status, tenant.subscription_status)
    
    # SECURITY: Only update plan if subscription is actually active (payment confirmed)
    # 'incomplete' means checkout started but not paid — don't upgrade yet!
    if stripe_status not in ('active', 'trialing'):
        # Just update status, don't change plan
        tenant.subscription_status = new_status
        tenant.stripe_subscription_id = subscription_id
        update_fields = ['subscription_status', 'stripe_subscription_id']
        # D4: 'unpaid' maps to the blocking 'expired' state — grant the
        # standard 30-day read-only grace period (if none is running) so
        # the owner can still reach their data and the reactivation flow,
        # matching what _handle_subscription_deleted does.
        if stripe_status == 'unpaid' and not tenant.grace_period_end:
            tenant.grace_period_end = timezone.now() + timezone.timedelta(days=30)
            update_fields.append('grace_period_end')
        tenant.save(update_fields=update_fields)
        logger.info(
            f"subscription.updated: Tenant {tenant.slug} status={new_status} "
            f"(plan unchanged, waiting for payment)"
        )
        return
    
    # Check if plan changed (look at the price ID)
    items = subscription.get('items', {}).get('data', [])
    if items:
        price_id = items[0].get('price', {}).get('id', '')
        if price_id:
            # Try to match the price ID to a SubscriptionPlan
            plan = SubscriptionPlan.objects.filter(
                stripe_price_id=price_id
            ).first() or SubscriptionPlan.objects.filter(
                stripe_annual_price_id=price_id
            ).first()
            
            if plan and tenant.subscription_plan != plan:
                tenant.plan = plan.slug
                tenant.subscription_plan = plan
                logger.info(
                    f"subscription.updated: Tenant {tenant.slug} plan changed to {plan.name}"
                )
    
    # Handle cancel_at_period_end: subscription is scheduled to cancel but is still
    # active.  Keep the status as 'canceled' (matching cancel_subscription() which
    # sets it when the owner clicks "Cancel").  The middleware now treats 'canceled'
    # without a grace_period_end as still-active, so no access loss occurs here.
    # The customer.subscription.deleted webhook fires when it truly expires, setting
    # status='expired' and grace_period_end at that point.  (CODE-130)
    if subscription.get('cancel_at_period_end'):
        new_status = 'canceled'

    tenant.subscription_status = new_status
    tenant.stripe_subscription_id = subscription_id
    update_fields = [
        'subscription_status', 'stripe_subscription_id',
        'plan', 'subscription_plan',
    ]
    # Moving to a live status clears any grace period left from a previous
    # lapse (see _handle_checkout_completed). Do NOT clear when the status
    # is 'canceled' (cancel_at_period_end) — a currently-running grace
    # period must keep its read-only semantics. (A3)
    if new_status in ('active', 'trialing'):
        tenant.grace_period_end = None
        update_fields.append('grace_period_end')
    tenant.save(update_fields=update_fields)

    logger.info(
        f"subscription.updated: Tenant {tenant.slug} status={new_status}"
    )


def _handle_subscription_deleted(subscription):
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

    tenant.save(update_fields=[
        'subscription_status', 'plan', 'subscription_plan', 'grace_period_end',
    ])

    logger.info(
        f"subscription.deleted: Tenant {tenant.slug} subscription ended. "
        f"Reverted to trial plan. Grace period until {tenant.grace_period_end}."
    )

    # Notify shop owners AND managers their subscription has ended
    _notify_owners_and_managers(tenant, 'subscription_ended', {})


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


def handle_subscription_event(event_type, data_object):
    """
    Process a subscription-related Stripe webhook event.
    
    Called from the unified billing webhook endpoint to handle
    SaaS subscription events without needing a separate webhook URL.
    
    Returns dict with 'success' and 'handled' keys.
    """
    handlers = {
        'checkout.session.completed': _handle_checkout_completed,
        'invoice.paid': _handle_invoice_paid,
        'invoice.payment_failed': _handle_invoice_payment_failed,
        'customer.subscription.updated': _handle_subscription_updated,
        'customer.subscription.deleted': _handle_subscription_deleted,
    }
    
    handler = handlers.get(event_type)
    if not handler:
        return {'success': True, 'handled': False}
    
    try:
        handler(data_object)
        return {'success': True, 'handled': True, 'event_type': event_type}
    except Exception as e:
        logger.exception(f"Error processing subscription webhook {event_type}: {e}")
        # Return success so Stripe doesn't retry (error is logged)
        return {'success': True, 'handled': True, 'event_type': event_type, 'error': str(e)}


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
                subject=f'⚠️ Payment failed for {tenant.name}',
                recipient_list=recipient_list,
                headline='Payment Failed',
                body_paragraphs=[
                    f"Hi {owner_name},",
                    f"We were unable to process your payment for {tenant.name} (attempt #{attempt_count}).",
                    retry_text,
                ],
                button_text='💳 Update Payment Method',
                button_url=f'{base_url}/owner/update-payment-method/',
                tenant=tenant,
                fail_silently=True,
            )
        elif event_type == 'payment_recovered':
            send_branded_email(
                subject=f'✅ Payment successful for {tenant.name}',
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
                button_text='🔄 Resubscribe Now',
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
