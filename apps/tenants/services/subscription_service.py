"""
Subscription Service

Manages Stripe subscription lifecycle: create, update, cancel, reactivate.
All Stripe API calls are wrapped in proper error handling.

Author: Amelia (Clawdbot AI)
"""

import logging
import stripe
from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant, SubscriptionPlan

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


class SubscriptionError(Exception):
    """Raised when a subscription operation fails."""
    pass


class SubscriptionService:
    """
    Handles all subscription billing operations via Stripe.
    
    Usage:
        svc = SubscriptionService()
        svc.create_subscription(tenant, plan_slug='pro', billing_period='monthly')
        svc.cancel_subscription(tenant)
    """
    
    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    
    def create_subscription(self, tenant, plan_slug, billing_period='monthly'):
        """
        Create a Stripe customer + subscription for a tenant.
        
        Args:
            tenant: Tenant model instance
            plan_slug: slug of the SubscriptionPlan (e.g. 'starter', 'pro')
            billing_period: 'monthly' or 'annual'
        
        Returns:
            dict with subscription details
            
        Raises:
            SubscriptionError on any failure
        """
        try:
            plan = SubscriptionPlan.objects.get(slug=plan_slug, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            raise SubscriptionError(f"Plan '{plan_slug}' not found or inactive.")
        
        if plan.is_free:
            raise SubscriptionError(
                "Cannot create a paid subscription for the free Trial plan. "
                "Trial is activated automatically on signup."
            )
        
        # Determine which Stripe Price ID to use
        if billing_period == 'annual' and plan.stripe_annual_price_id:
            price_id = plan.stripe_annual_price_id
        else:
            price_id = plan.stripe_price_id
            billing_period = 'monthly'  # fallback
        
        if not price_id:
            raise SubscriptionError(
                f"Plan '{plan.name}' has no Stripe Price ID configured for {billing_period} billing."
            )
        
        try:
            # Step 1: Create or retrieve Stripe Customer
            if tenant.stripe_customer_id:
                customer = stripe.Customer.retrieve(tenant.stripe_customer_id)
                logger.info(f"Retrieved Stripe customer {customer.id} for tenant {tenant.slug}")
            else:
                customer = stripe.Customer.create(
                    name=tenant.name,
                    email=tenant.business_email or tenant.owner.email,
                    metadata={
                        'tenant_id': str(tenant.id),
                        'tenant_slug': tenant.slug,
                    }
                )
                tenant.stripe_customer_id = customer.id
                logger.info(f"Created Stripe customer {customer.id} for tenant {tenant.slug}")
            
            # Step 2: Create subscription
            subscription = stripe.Subscription.create(
                customer=customer.id,
                items=[{'price': price_id}],
                payment_behavior='default_incomplete',
                expand=['latest_invoice.payment_intent'],
                metadata={
                    'tenant_id': str(tenant.id),
                    'tenant_slug': tenant.slug,
                    'plan_slug': plan.slug,
                    'billing_period': billing_period,
                },
            )
            
            # Step 3: Update tenant
            tenant.stripe_subscription_id = subscription.id
            tenant.plan = plan.slug
            tenant.subscription_plan = plan
            tenant.subscription_status = subscription.status
            tenant.save(update_fields=[
                'stripe_customer_id', 'stripe_subscription_id',
                'plan', 'subscription_plan', 'subscription_status',
            ])
            
            logger.info(
                f"Created subscription {subscription.id} for tenant {tenant.slug} "
                f"on plan {plan.name} ({billing_period})"
            )
            
            # Return details the frontend needs to complete payment
            result = {
                'subscription_id': subscription.id,
                'status': subscription.status,
                'plan': plan.name,
                'billing_period': billing_period,
            }
            
            # Include client_secret if payment needs confirmation
            if subscription.status == 'incomplete':
                invoice = subscription.latest_invoice
                if invoice and invoice.payment_intent:
                    result['client_secret'] = invoice.payment_intent.client_secret
            
            return result
            
        except stripe.error.CardError as e:
            logger.error(f"Card error creating subscription for {tenant.slug}: {e}")
            raise SubscriptionError(f"Card error: {e.user_message}")
        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid Stripe request for {tenant.slug}: {e}")
            raise SubscriptionError(f"Billing configuration error: {str(e)}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating subscription for {tenant.slug}: {e}")
            raise SubscriptionError(f"Payment service error. Please try again later.")
    
    # ------------------------------------------------------------------
    # Update (upgrade / downgrade)
    # ------------------------------------------------------------------
    
    def update_subscription(self, tenant, new_plan_slug):
        """
        Change a tenant's subscription plan (upgrade or downgrade).
        
        Stripe handles proration automatically.
        
        Args:
            tenant: Tenant model instance
            new_plan_slug: slug of the target SubscriptionPlan
            
        Returns:
            dict with updated subscription details
        """
        if not tenant.stripe_subscription_id:
            raise SubscriptionError(
                "No active subscription. Please subscribe first."
            )
        
        try:
            new_plan = SubscriptionPlan.objects.get(slug=new_plan_slug, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            raise SubscriptionError(f"Plan '{new_plan_slug}' not found or inactive.")
        
        if new_plan.is_free:
            raise SubscriptionError(
                "Cannot switch to the free Trial plan. Use cancel instead."
            )
        
        if not new_plan.stripe_price_id:
            raise SubscriptionError(
                f"Plan '{new_plan.name}' is not configured for billing yet."
            )
        
        try:
            # Retrieve current subscription
            subscription = stripe.Subscription.retrieve(tenant.stripe_subscription_id)
            
            if subscription.status in ('canceled', 'incomplete_expired'):
                raise SubscriptionError(
                    "Your subscription has been canceled. Please create a new subscription."
                )
            
            # Update the subscription item to the new price
            stripe.Subscription.modify(
                tenant.stripe_subscription_id,
                items=[{
                    'id': subscription['items']['data'][0].id,
                    'price': new_plan.stripe_price_id,
                }],
                proration_behavior='create_prorations',
                metadata={
                    'plan_slug': new_plan.slug,
                },
            )
            
            # Update tenant
            tenant.plan = new_plan.slug
            tenant.subscription_plan = new_plan
            tenant.save(update_fields=['plan', 'subscription_plan'])
            
            logger.info(
                f"Updated subscription for tenant {tenant.slug} to plan {new_plan.name}"
            )
            
            return {
                'subscription_id': tenant.stripe_subscription_id,
                'new_plan': new_plan.name,
                'status': 'updated',
            }
            
        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid request updating subscription for {tenant.slug}: {e}")
            raise SubscriptionError(f"Could not update subscription: {str(e)}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error updating subscription for {tenant.slug}: {e}")
            raise SubscriptionError("Payment service error. Please try again later.")
    
    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    
    def cancel_subscription(self, tenant):
        """
        Cancel subscription at the end of the current billing period.
        The tenant keeps access until the period ends.
        
        Returns:
            dict with cancellation details
        """
        if not tenant.stripe_subscription_id:
            raise SubscriptionError("No active subscription to cancel.")
        
        try:
            subscription = stripe.Subscription.modify(
                tenant.stripe_subscription_id,
                cancel_at_period_end=True,
            )
            
            tenant.subscription_status = 'canceled'
            tenant.save(update_fields=['subscription_status'])
            
            logger.info(f"Subscription cancellation scheduled for tenant {tenant.slug}")
            
            return {
                'subscription_id': subscription.id,
                'status': 'canceling',
                'cancel_at': subscription.cancel_at,
                'current_period_end': subscription.current_period_end,
                'message': (
                    'Your subscription will be canceled at the end of the current '
                    'billing period. You retain full access until then.'
                ),
            }
            
        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid request canceling subscription for {tenant.slug}: {e}")
            raise SubscriptionError(f"Could not cancel subscription: {str(e)}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error canceling subscription for {tenant.slug}: {e}")
            raise SubscriptionError("Payment service error. Please try again later.")
    
    # ------------------------------------------------------------------
    # Reactivate
    # ------------------------------------------------------------------
    
    def reactivate_subscription(self, tenant):
        """
        Un-cancel a subscription that was set to cancel at period end.
        
        Returns:
            dict with reactivation details
        """
        if not tenant.stripe_subscription_id:
            raise SubscriptionError("No subscription to reactivate.")
        
        try:
            subscription = stripe.Subscription.retrieve(tenant.stripe_subscription_id)
            
            if not subscription.cancel_at_period_end:
                raise SubscriptionError("Subscription is not pending cancellation.")
            
            if subscription.status == 'canceled':
                raise SubscriptionError(
                    "Subscription has already been canceled. Please create a new subscription."
                )
            
            subscription = stripe.Subscription.modify(
                tenant.stripe_subscription_id,
                cancel_at_period_end=False,
            )
            
            tenant.subscription_status = 'active'
            tenant.save(update_fields=['subscription_status'])
            
            logger.info(f"Subscription reactivated for tenant {tenant.slug}")
            
            return {
                'subscription_id': subscription.id,
                'status': 'active',
                'message': 'Your subscription has been reactivated. You will continue to be billed normally.',
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error reactivating subscription for {tenant.slug}: {e}")
            raise SubscriptionError("Payment service error. Please try again later.")
    
    # ------------------------------------------------------------------
    # Trial management
    # ------------------------------------------------------------------
    
    def check_trial_expiry(self, tenant):
        """
        Check if a tenant's trial has expired.
        
        Returns:
            dict with trial status
        """
        if tenant.plan != 'trial':
            return {
                'is_trial': False,
                'expired': False,
                'days_remaining': None,
                'message': f'Active on {tenant.plan} plan.',
            }
        
        expired = tenant.is_trial_expired
        days_remaining = tenant.trial_days_remaining
        
        if expired and tenant.subscription_status != 'expired':
            tenant.subscription_status = 'expired'
            tenant.save(update_fields=['subscription_status'])
            logger.info(f"Trial expired for tenant {tenant.slug}")
        
        return {
            'is_trial': True,
            'expired': expired,
            'days_remaining': days_remaining,
            'message': (
                'Your free trial has expired. Please subscribe to continue using RS Systems.'
                if expired else
                f'{days_remaining} days remaining in your free trial.'
            ),
        }
    
    # ------------------------------------------------------------------
    # Usage summary (delegates to UsageService)
    # ------------------------------------------------------------------
    
    def get_usage(self, tenant):
        """
        Get current usage vs plan limits.
        Delegates to UsageService.
        """
        from apps.tenants.services.usage_service import UsageService
        return UsageService(tenant).get_summary()
    
    # ------------------------------------------------------------------
    # Billing Portal
    # ------------------------------------------------------------------
    
    def create_billing_portal_session(self, tenant, return_url):
        """
        Create a Stripe Billing Portal session for the tenant.
        
        The Billing Portal lets shop owners manage payment methods,
        view invoices, and update their subscription.
        
        Args:
            tenant: Tenant model instance  
            return_url: URL to redirect to after leaving the portal
            
        Returns:
            str: The portal session URL
        """
        if not tenant.stripe_customer_id:
            raise SubscriptionError(
                "No billing account found. Please subscribe to a plan first."
            )
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=tenant.stripe_customer_id,
                return_url=return_url,
            )
            
            logger.info(f"Created billing portal session for tenant {tenant.slug}")
            return session.url
            
        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid request creating billing portal for {tenant.slug}: {e}")
            raise SubscriptionError(f"Could not open billing portal: {str(e)}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating billing portal for {tenant.slug}: {e}")
            raise SubscriptionError("Payment service error. Please try again later.")
