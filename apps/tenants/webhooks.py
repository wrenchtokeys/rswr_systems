"""
Stripe Webhook Handler for SaaS Subscriptions

Processes Stripe webhook events to keep tenant subscription state
in sync with Stripe. Verifies webhook signatures for security.

Events handled:
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
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    
    # Verify webhook signature
    if webhook_secret:
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
    else:
        # No webhook secret configured — parse without verification (dev only)
        try:
            event = stripe.Event.construct_from(
                json.loads(payload), stripe.api_key
            )
        except (ValueError, json.JSONDecodeError):
            logger.error("Stripe webhook: could not parse payload")
            return HttpResponse("Invalid payload", status=400)
        logger.warning(
            "Stripe webhook: STRIPE_WEBHOOK_SECRET not set — "
            "signature verification skipped (dev mode only)"
        )
    
    event_type = event['type']
    data_object = event['data']['object']
    
    logger.info(f"Stripe webhook received: {event_type} [{event.get('id', 'unknown')}]")
    
    # Route to handler
    handlers = {
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
    
    # Update tenant status to active
    tenant.subscription_status = 'active'
    
    # Update subscription ID if it changed
    if subscription_id and tenant.stripe_subscription_id != subscription_id:
        tenant.stripe_subscription_id = subscription_id
    
    tenant.save(update_fields=['subscription_status', 'stripe_subscription_id'])
    
    logger.info(
        f"invoice.paid: Tenant {tenant.slug} subscription payment successful. "
        f"Invoice: {invoice.get('id')}"
    )


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
    
    # Notify shop owner about failed payment
    _notify_owner(tenant, 'payment_failed', {
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
        'incomplete': 'active',  # Payment in progress
        'incomplete_expired': 'expired',
        'unpaid': 'past_due',
    }
    new_status = status_map.get(stripe_status, tenant.subscription_status)
    
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
    
    # Handle cancel_at_period_end
    if subscription.get('cancel_at_period_end'):
        new_status = 'canceled'
    
    tenant.subscription_status = new_status
    tenant.stripe_subscription_id = subscription_id
    tenant.save(update_fields=[
        'subscription_status', 'stripe_subscription_id',
        'plan', 'subscription_plan',
    ])
    
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
    
    # Try to set subscription_plan to trial plan
    trial_plan = SubscriptionPlan.objects.filter(slug='trial').first()
    if trial_plan:
        tenant.subscription_plan = trial_plan
    
    tenant.save(update_fields=[
        'subscription_status', 'plan', 'subscription_plan',
    ])
    
    logger.info(
        f"subscription.deleted: Tenant {tenant.slug} subscription ended. "
        f"Reverted to trial plan."
    )
    
    # Notify shop owner their subscription has ended
    _notify_owner(tenant, 'subscription_ended', {})


def _notify_owner(tenant, event_type, context):
    """
    Send email notification to shop owner about subscription events.
    
    Uses SendGrid if configured, otherwise logs a warning.
    """
    try:
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        
        owner = tenant.owner
        if not owner or not owner.email:
            logger.warning(f"Cannot notify owner for tenant {tenant.slug}: no owner email")
            return
        
        subjects = {
            'payment_failed': f'⚠️ Payment failed for {tenant.name}',
            'subscription_ended': f'Your {tenant.name} subscription has ended',
        }
        
        messages = {
            'payment_failed': (
                f"Hi {owner.first_name or 'there'},\n\n"
                f"We were unable to process your payment for {tenant.name}.\n"
                f"Attempt #{context.get('attempt_count', 1)}.\n\n"
                f"Please update your payment method to avoid service interruption.\n"
                f"Go to your billing settings to update: /owner/billing/\n\n"
                f"— RS Systems"
            ),
            'subscription_ended': (
                f"Hi {owner.first_name or 'there'},\n\n"
                f"Your subscription for {tenant.name} has been cancelled.\n"
                f"Your account has been reverted to the free trial plan.\n\n"
                f"You can resubscribe anytime from your billing settings: /owner/billing/\n\n"
                f"— RS Systems"
            ),
        }
        
        subject = subjects.get(event_type, f'RS Systems notification for {tenant.name}')
        body = messages.get(event_type, f'A subscription event occurred for {tenant.name}.')
        
        from_email = getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'notifications@rockstarwindshield.repair')
        
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[owner.email],
            fail_silently=True,
        )
        logger.info(f"Sent {event_type} notification to {owner.email} for tenant {tenant.slug}")
        
    except Exception as e:
        logger.error(f"Failed to send {event_type} notification for tenant {tenant.slug}: {e}")
