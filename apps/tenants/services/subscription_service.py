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
from apps.billing.services.stripe_compat import (
    subscription_item_id,
    subscription_period_end,
)

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = getattr(settings, 'STRIPE_API_VERSION', '') or stripe.api_version


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
    
    def create_subscription(self, tenant, plan_slug, billing_period='monthly', base_url=None):
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
            # Step 0: Void any incomplete subscriptions from previous attempts
            # This prevents stale invoices piling up when users change their mind
            if tenant.stripe_subscription_id:
                try:
                    old_sub = stripe.Subscription.retrieve(tenant.stripe_subscription_id)
                    if old_sub.status in ('incomplete', 'incomplete_expired'):
                        stripe.Subscription.delete(tenant.stripe_subscription_id)
                        tenant.stripe_subscription_id = ''
                        tenant.save(update_fields=['stripe_subscription_id'])
                        logger.info(
                            f"Voided incomplete subscription for tenant {tenant.slug} "
                            f"before creating new checkout"
                        )
                except stripe.error.InvalidRequestError:
                    # Subscription doesn't exist or already canceled
                    tenant.stripe_subscription_id = ''
                    tenant.save(update_fields=['stripe_subscription_id'])
            
            # Step 1: Create or retrieve Stripe Customer
            customer = None
            if tenant.stripe_customer_id:
                try:
                    customer = stripe.Customer.retrieve(tenant.stripe_customer_id)
                    logger.info(f"Retrieved Stripe customer {customer.id} for tenant {tenant.slug}")
                except stripe.error.InvalidRequestError as e:
                    if 'No such customer' in str(e):
                        logger.warning(
                            f"Stale stripe_customer_id '{tenant.stripe_customer_id}' "
                            f"for tenant {tenant.slug} — clearing and creating new customer"
                        )
                        tenant.stripe_customer_id = ''
                        tenant.stripe_subscription_id = ''
                    else:
                        raise

            if not customer:
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
            
            # Step 2: Create Stripe Checkout Session for subscription
            # (Using Checkout instead of direct subscription creation due to 
            # Stripe API change removing payment_intent from Invoice objects)
            
            # Determine base URL for success/cancel redirects
            if base_url:
                redirect_base = base_url.rstrip('/')
            elif hasattr(settings, 'EB_HOSTNAME') and settings.EB_HOSTNAME:
                redirect_base = f"https://{settings.EB_HOSTNAME}"
            else:
                redirect_base = "https://rssystems.io"  # fallback
            
            checkout_session = stripe.checkout.Session.create(
                customer=customer.id,
                mode='subscription',
                line_items=[{'price': price_id, 'quantity': 1}],
                success_url=f"{redirect_base}/owner/billing/?success=true",
                cancel_url=f"{redirect_base}/owner/billing/?canceled=true",
                metadata={
                    'tenant_id': str(tenant.id),
                    'tenant_slug': tenant.slug,
                    'plan_slug': plan.slug,
                    'billing_period': billing_period,
                },
                subscription_data={
                    'metadata': {
                        'tenant_id': str(tenant.id),
                        'tenant_slug': tenant.slug,
                    }
                },
            )
            
            # Step 3: Only save customer ID now — plan updates via webhook AFTER payment
            # DO NOT update plan/subscription_plan here to prevent unpaid access
            tenant.save(update_fields=['stripe_customer_id'])
            
            logger.info(
                f"Created checkout session {checkout_session.id} for tenant {tenant.slug} "
                f"to subscribe to {plan.name} ({billing_period})"
            )
            
            # Return checkout URL for redirect
            return {
                'checkout_url': checkout_session.url,
                'session_id': checkout_session.id,
                'plan': plan.name,
                'billing_period': billing_period,
            }
            
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
        
        - Upgrades: Immediate via Stripe, but plan access waits for webhook confirmation
        - Downgrades: Scheduled for end of billing period (user keeps current access)
        
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
                # Clear stale subscription ID and tell user to start fresh
                tenant.stripe_subscription_id = ''
                tenant.save(update_fields=['stripe_subscription_id'])
                raise SubscriptionError(
                    "Previous subscription was canceled. Please select a plan to subscribe."
                )
            
            # If subscription is incomplete (never paid), void it and start fresh
            if subscription.status == 'incomplete':
                stripe.Subscription.delete(tenant.stripe_subscription_id)
                tenant.stripe_subscription_id = ''
                tenant.save(update_fields=['stripe_subscription_id'])
                logger.info(
                    f"Voided incomplete subscription for tenant {tenant.slug} "
                    f"during plan change"
                )
                raise SubscriptionError(
                    "Previous subscription was not completed. Please start a new subscription."
                )
            
            # Determine if this is an upgrade or downgrade BEFORE making changes
            current_plan = tenant.subscription_plan
            is_upgrade = (
                current_plan is None or 
                new_plan.monthly_price > (current_plan.monthly_price or 0)
            )
            
            if is_upgrade:
                # UPGRADES: Apply immediately, but don't update local plan until
                # webhook confirms. This prevents unpaid access to higher tier.
                stripe.Subscription.modify(
                    tenant.stripe_subscription_id,
                    items=[{
                        'id': subscription_item_id(subscription),
                        'price': new_plan.stripe_price_id,
                    }],
                    proration_behavior='create_prorations',
                    metadata={
                        'plan_slug': new_plan.slug,
                    },
                )
                
                logger.info(
                    f"Upgrade requested for tenant {tenant.slug} to plan {new_plan.name}. "
                    f"Waiting for webhook confirmation."
                )
                
                return {
                    'subscription_id': tenant.stripe_subscription_id,
                    'new_plan': new_plan.name,
                    'status': 'pending',
                    'message': (
                        f'Upgrading to {new_plan.name}... '
                        'Your new features will be available momentarily.'
                    ),
                }
            else:
                # DOWNGRADES: Schedule for end of billing period.
                # User keeps current tier access since they paid for this period.
                # Use Stripe Subscription Schedule to defer the change.
                
                if not current_plan or not current_plan.stripe_price_id:
                    raise SubscriptionError(
                        "Cannot determine current plan. Please contact support."
                    )
                
                # Create a subscription schedule from the current subscription
                schedule = stripe.SubscriptionSchedule.create(
                    from_subscription=tenant.stripe_subscription_id,
                )
                
                # Configure schedule: current plan now, new plan at period end.
                # Basil removed current_period_end from Subscription and put
                # it on each item, so reading the attribute directly raised
                # AttributeError and every downgrade failed.
                current_period_end = subscription_period_end(subscription)
                if not current_period_end:
                    raise SubscriptionError(
                        "Could not determine your current billing period. "
                        "Please contact support."
                    )
                stripe.SubscriptionSchedule.modify(
                    schedule.id,
                    end_behavior='release',  # Release back to regular subscription after
                    phases=[
                        {
                            # Current phase: keep current plan until period end.
                            # IMPORTANT: start_date must NOT be in the past.
                            # 'now' is the correct token for "start immediately"
                            # when the phase covers an already-active period.
                            # Using subscription.current_period_start (a past
                            # Unix timestamp) causes Stripe to reject the request
                            # with InvalidRequestError.  (CODE-229)
                            'items': [{'price': current_plan.stripe_price_id}],
                            'start_date': 'now',
                            'end_date': current_period_end,
                        },
                        {
                            # Next phase: switch to new (lower) plan
                            'items': [{'price': new_plan.stripe_price_id}],
                            'start_date': current_period_end,
                        },
                    ],
                )
                
                logger.info(
                    f"Downgrade scheduled for tenant {tenant.slug} to plan {new_plan.name}. "
                    f"Access continues until period end ({current_period_end})."
                )
                
                return {
                    'subscription_id': tenant.stripe_subscription_id,
                    'new_plan': new_plan.name,
                    'status': 'scheduled',
                    'current_period_end': current_period_end,
                    'message': (
                        f'Your plan will change to {new_plan.name} at the end of your '
                        f'current billing period. You\'ll keep full access until then.'
                    ),
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
                'current_period_end': subscription_period_end(subscription),
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
            # Clear any grace period from a previous lapse — a stale stamp
            # locks the tenant out on their next cancellation. (A3)
            tenant.grace_period_end = None
            tenant.save(update_fields=['subscription_status', 'grace_period_end'])

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
    
    def create_billing_portal_session(self, tenant, return_url, flow=None):
        """
        Create a Stripe Billing Portal session for the tenant.

        The Billing Portal lets shop owners manage payment methods,
        view invoices, and update their subscription.

        Args:
            tenant: Tenant model instance
            return_url: URL to redirect to after leaving the portal
            flow: optional deep-link, e.g. 'payment_method_update'. Without
                it the owner lands on the portal home and has to find the
                card themselves -- a needless step when the email that sent
                them there said "update your payment method".

        Returns:
            str: The portal session URL
        """
        if not tenant.stripe_customer_id:
            raise SubscriptionError(
                "No billing account found. Please subscribe to a plan first."
            )

        params = {
            'customer': tenant.stripe_customer_id,
            'return_url': return_url,
        }
        if flow:
            params['flow_data'] = {
                'type': flow,
                'after_completion': {
                    'type': 'redirect',
                    'redirect': {'return_url': return_url},
                },
            }

        try:
            try:
                session = stripe.billing_portal.Session.create(**params)
            except stripe.error.InvalidRequestError:
                if not flow:
                    raise
                # flow_data requires a portal configuration that permits it.
                # A misconfigured Dashboard must not 500 an owner who is
                # trying to pay us -- fall back to the plain portal.
                logger.warning(
                    f"Billing portal flow {flow!r} rejected for {tenant.slug}; "
                    f"falling back to the plain portal", exc_info=True,
                )
                params.pop('flow_data', None)
                session = stripe.billing_portal.Session.create(**params)

            logger.info(f"Created billing portal session for tenant {tenant.slug}")
            return session.url


        except stripe.error.InvalidRequestError as e:
            error_str = str(e)
            logger.error(f"Invalid request creating billing portal for {tenant.slug}: {e}")
            # Stale customer ID from a different Stripe mode (test vs live)
            if 'No such customer' in error_str:
                logger.warning(
                    f"Clearing stale stripe_customer_id '{tenant.stripe_customer_id}' "
                    f"for tenant {tenant.slug} (wrong Stripe mode)"
                )
                tenant.stripe_customer_id = ''
                tenant.stripe_subscription_id = ''
                tenant.save(update_fields=['stripe_customer_id', 'stripe_subscription_id'])
                raise SubscriptionError(
                    "Your billing account was linked to a previous Stripe environment. "
                    "It has been reset — please subscribe to a plan to set up billing."
                )
            raise SubscriptionError(f"Could not open billing portal: {error_str}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating billing portal for {tenant.slug}: {e}")
            raise SubscriptionError("Payment service error. Please try again later.")
