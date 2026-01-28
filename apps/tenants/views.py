"""
Tenant Subscription API Views

Endpoints for managing SaaS subscriptions:
- Subscribe to a plan
- Update (upgrade/downgrade)
- Cancel / Reactivate
- View usage
- Billing portal redirect

Author: Amelia (Clawdbot AI)
"""

import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.subscription_service import (
    SubscriptionService,
    SubscriptionError,
)
from apps.tenants.services.usage_service import UsageService

logger = logging.getLogger(__name__)


def _get_tenant(request):
    """Extract tenant from request, returning error Response if missing."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return None, Response(
            {'error': 'No tenant context. Set X-Tenant-Slug header or log in.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    return tenant, None


# ------------------------------------------------------------------
# Plans listing (public)
# ------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([AllowAny])
def list_plans(request):
    """
    GET /api/tenants/plans/
    
    List all active subscription plans with pricing and limits.
    """
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('display_order')
    
    data = []
    for plan in plans:
        data.append({
            'slug': plan.slug,
            'name': plan.name,
            'monthly_price': str(plan.monthly_price),
            'annual_price': str(plan.annual_price) if plan.annual_price else None,
            'max_repairs_per_month': plan.max_repairs_per_month,
            'max_technicians': plan.max_technicians,
            'max_customers': plan.max_customers,
            'max_storage_mb': plan.max_storage_mb,
            'features': plan.features,
            'trial_days': plan.trial_days,
            'is_free': plan.is_free,
        })
    
    return Response({'plans': data})


# ------------------------------------------------------------------
# Subscribe
# ------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def subscribe(request):
    """
    POST /api/tenants/subscribe/
    
    Start a subscription for the current tenant.
    
    Body:
        {
            "plan": "starter",       // required: plan slug
            "billing_period": "monthly"  // optional: "monthly" or "annual"
        }
    
    Returns subscription details including client_secret for
    completing payment on the frontend.
    """
    tenant, error = _get_tenant(request)
    if error:
        return error
    
    plan_slug = request.data.get('plan')
    if not plan_slug:
        return Response(
            {'error': 'Missing required field: plan'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    billing_period = request.data.get('billing_period', 'monthly')
    if billing_period not in ('monthly', 'annual'):
        return Response(
            {'error': 'billing_period must be "monthly" or "annual"'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    svc = SubscriptionService()
    try:
        result = svc.create_subscription(tenant, plan_slug, billing_period)
        return Response(result, status=status.HTTP_201_CREATED)
    except SubscriptionError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ------------------------------------------------------------------
# Update (upgrade / downgrade)
# ------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_subscription(request):
    """
    POST /api/tenants/subscription/update/
    
    Change the current subscription plan (upgrade or downgrade).
    
    Body:
        {
            "plan": "pro"  // required: new plan slug
        }
    """
    tenant, error = _get_tenant(request)
    if error:
        return error
    
    new_plan_slug = request.data.get('plan')
    if not new_plan_slug:
        return Response(
            {'error': 'Missing required field: plan'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    svc = SubscriptionService()
    try:
        result = svc.update_subscription(tenant, new_plan_slug)
        return Response(result)
    except SubscriptionError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ------------------------------------------------------------------
# Cancel
# ------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_subscription(request):
    """
    POST /api/tenants/subscription/cancel/
    
    Cancel the subscription at end of current billing period.
    The tenant retains access until the period ends.
    """
    tenant, error = _get_tenant(request)
    if error:
        return error
    
    svc = SubscriptionService()
    try:
        result = svc.cancel_subscription(tenant)
        return Response(result)
    except SubscriptionError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ------------------------------------------------------------------
# Reactivate
# ------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reactivate_subscription(request):
    """
    POST /api/tenants/subscription/reactivate/
    
    Un-cancel a subscription that was set to cancel at period end.
    """
    tenant, error = _get_tenant(request)
    if error:
        return error
    
    svc = SubscriptionService()
    try:
        result = svc.reactivate_subscription(tenant)
        return Response(result)
    except SubscriptionError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def usage(request):
    """
    GET /api/tenants/usage/
    
    Returns current resource usage vs plan limits.
    """
    tenant, error = _get_tenant(request)
    if error:
        return error
    
    usage_svc = UsageService(tenant)
    summary = usage_svc.get_summary()
    return Response(summary)


# ------------------------------------------------------------------
# Billing Portal
# ------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def billing_portal(request):
    """
    GET /api/tenants/billing-portal/
    
    Creates a Stripe Billing Portal session and returns the URL.
    The frontend should redirect the user to this URL.
    
    Query params:
        return_url — URL to redirect to after leaving the portal
                     (defaults to the Referer header or '/')
    """
    tenant, error = _get_tenant(request)
    if error:
        return error
    
    return_url = (
        request.query_params.get('return_url')
        or request.META.get('HTTP_REFERER')
        or '/'
    )
    
    svc = SubscriptionService()
    try:
        portal_url = svc.create_billing_portal_session(tenant, return_url)
        return Response({'url': portal_url})
    except SubscriptionError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
