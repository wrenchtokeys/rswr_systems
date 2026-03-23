"""
Tenant Subscription API Views

Endpoints for managing SaaS subscriptions:
- Signup (new shop owner registration)
- Subscribe to a plan
- Update (upgrade/downgrade)
- Cancel / Reactivate
- View usage & status
- Billing portal redirect

Author: Amelia (Clawdbot AI)
"""

import logging
import os
import re
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.throttling import SimpleRateThrottle

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.subscription_service import (
    SubscriptionService,
    SubscriptionError,
)
from apps.tenants.services.usage_service import UsageService

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Custom Throttle for Signup
# ------------------------------------------------------------------

class SignupRateThrottle(SimpleRateThrottle):
    """
    Aggressive rate limit on signup to prevent abuse.
    Uses the client IP as the identifier.
    """
    scope = 'signup'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_tenant(request):
    """Extract tenant from request, returning error Response if missing."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return None, Response(
            {'error': 'No tenant context. Set X-Tenant-Slug header or log in.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    return tenant, None


def _require_owner(request):
    """
    Verify the request user is an owner of the current tenant.

    Returns:
        (tenant, None) on success
        (None, Response) with 403 if not owner or no tenant context
    """
    tenant, error = _get_tenant(request)
    if error:
        return None, error

    is_owner = TenantMembership.objects.filter(
        tenant=tenant,
        user=request.user,
        role='owner',
        is_active=True,
    ).exists()

    if not is_owner:
        return None, Response(
            {'error': 'Only the shop owner can manage billing and subscriptions.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    return tenant, None


def _generate_unique_slug(business_name):
    """Generate a unique slug from business name, appending a suffix if needed."""
    base_slug = slugify(business_name)[:50]
    slug = base_slug
    counter = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def _send_welcome_email(user, tenant, trial_days=30):
    """Send a welcome email via SendGrid/SMTP if configured."""
    sendgrid_key = os.environ.get('SENDGRID_API_KEY')
    if not sendgrid_key:
        logger.info(f"No SENDGRID_API_KEY — skipping welcome email for {user.email}")
        return

    try:
        from core.email_utils import send_branded_email

        send_branded_email(
            subject=f"Welcome to RS Systems, {user.first_name}! 🎉",
            recipient_list=[user.email],
            headline=f'Welcome to RS Systems!',
            body_paragraphs=[
                f"Hi {user.first_name},",
                f'Your shop "{tenant.name}" is set up and your {trial_days}-day free trial has started.',
                "Your trial includes up to 50 repairs/month, 2 technician seats, 10 customer accounts, full invoicing & billing, and 100 MB photo storage.",
                "Quick start: Log in, add your first customer, create a repair record, and generate an invoice in one click.",
                f"Your trial expires in {trial_days} days. Upgrade anytime to keep your data.",
            ],
            button_text='🚀 Get Started',
            button_url='https://rssystems.io/login/',
            tenant=tenant,
            fail_silently=True,
        )
        logger.info(f"Welcome email sent to {user.email}")
    except Exception as e:
        logger.warning(f"Failed to send welcome email to {user.email}: {e}")


# ------------------------------------------------------------------
# Signup (public)
# ------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([SignupRateThrottle])
def signup(request):
    """
    POST /api/tenants/signup/

    Register a new shop owner with a 30-day free trial.

    Body:
        {
            "business_name": "Quick Fix Auto Glass",
            "email": "owner@quickfix.com",
            "password": "securepass123",
            "first_name": "John",
            "last_name": "Smith",
            "phone": "555-123-4567"  // optional
        }

    Returns user info, tenant info, trial details, and auth token.
    """
    data = request.data

    # --- Input extraction & sanitization ---
    business_name = str(data.get('business_name', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    password = data.get('password', '')
    first_name = str(data.get('first_name', '')).strip()
    last_name = str(data.get('last_name', '')).strip()
    phone = str(data.get('phone', '')).strip()

    # --- Validation ---
    errors = {}

    # Business name
    if not business_name:
        errors['business_name'] = 'Business name is required.'
    elif len(business_name) < 2:
        errors['business_name'] = 'Business name must be at least 2 characters.'
    elif len(business_name) > 200:
        errors['business_name'] = 'Business name must be 200 characters or fewer.'

    # Email
    if not email:
        errors['email'] = 'Email is required.'
    else:
        try:
            validate_email(email)
        except DjangoValidationError:
            errors['email'] = 'Enter a valid email address.'

    if email and User.objects.filter(email=email).exists():
        errors['email'] = 'An account with this email already exists.'

    # Password
    if not password:
        errors['password'] = 'Password is required.'
    else:
        try:
            # Build a temporary user object for similarity check
            temp_user = User(username='temp', email=email,
                             first_name=first_name, last_name=last_name)
            validate_password(password, user=temp_user)
        except DjangoValidationError as e:
            errors['password'] = list(e.messages)

    # Names
    if not first_name:
        errors['first_name'] = 'First name is required.'
    if not last_name:
        errors['last_name'] = 'Last name is required.'

    if errors:
        return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    # --- Create everything via shared signup service ---
    try:
        from apps.tenants.services.signup_service import create_tenant_with_owner, SignupError
        result = create_tenant_with_owner(
            business_name=business_name,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )
        user = result['user']
        tenant = result['tenant']

        # Create auth token (API-specific — UI uses session auth)
        token, _ = Token.objects.get_or_create(user=user)

        # Send welcome email (non-blocking)
        trial_plan = tenant.subscription_plan
        trial_days = trial_plan.trial_days if trial_plan else 30
        _send_welcome_email(user, tenant, trial_days)

        logger.info(
            f"New signup: {user.email} — tenant '{tenant.name}' (slug={tenant.slug})"
        )

        return Response({
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.get_full_name(),
            },
            'tenant': {
                'id': tenant.id,
                'name': tenant.name,
                'slug': tenant.slug,
            },
            'plan': {
                'name': trial_plan.name if trial_plan else 'Trial',
                'days_remaining': trial_days,
            },
            'token': token.key,
            'message': 'Welcome to RS Systems! Your 30-day free trial has started.',
        }, status=status.HTTP_201_CREATED)

    except SignupError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Signup failed for {email}: {e}")
        return Response(
            {'error': 'An unexpected error occurred during signup. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ------------------------------------------------------------------
# Tenant Status (dashboard-friendly)
# ------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tenant_status(request):
    """
    GET /api/tenants/status/

    Returns current tenant status in a dashboard-friendly format.
    Includes plan info, trial status, usage summary, and upgrade URL.
    """
    tenant, error = _get_tenant(request)
    if error:
        return error

    plan = tenant.subscription_plan
    usage_svc = UsageService(tenant)
    usage_summary = usage_svc.get_summary()

    # Trial info
    trial_info = None
    if tenant.plan == 'trial' and tenant.trial_started_at:
        trial_days = plan.trial_days if plan else 30
        expires_at = tenant.trial_started_at + timezone.timedelta(days=trial_days)
        trial_info = {
            'active': not tenant.is_trial_expired,
            'days_remaining': tenant.trial_days_remaining,
            'expires_at': expires_at.strftime('%Y-%m-%d'),
        }

    # Plan details
    plan_info = {
        'name': plan.name if plan else 'No Plan',
        'slug': plan.slug if plan else None,
        'price': f"${plan.monthly_price}" if plan else '$0',
    }

    return Response({
        'tenant': {
            'name': tenant.name,
            'slug': tenant.slug,
        },
        'plan': plan_info,
        'subscription_status': tenant.subscription_status,
        'trial': trial_info,
        'usage': usage_summary,
        'upgrade_url': '/api/tenants/subscribe/',
    })


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
    Owner-only: only the shop owner can subscribe.
    
    Body:
        {
            "plan": "starter",       // required: plan slug
            "billing_period": "monthly"  // optional: "monthly" or "annual"
        }
    
    Returns subscription details including client_secret for
    completing payment on the frontend.
    """
    tenant, error = _require_owner(request)
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
        base_url = request.build_absolute_uri('/').rstrip('/')
        result = svc.create_subscription(tenant, plan_slug, billing_period, base_url=base_url)
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
    Owner-only: only the shop owner can change plans.
    
    Body:
        {
            "plan": "pro"  // required: new plan slug
        }
    """
    tenant, error = _require_owner(request)
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
    Owner-only: only the shop owner can cancel.
    The tenant retains access until the period ends.
    """
    tenant, error = _require_owner(request)
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
    Owner-only: only the shop owner can reactivate.
    """
    tenant, error = _require_owner(request)
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
    Owner-only: only the shop owner can access billing.
    The frontend should redirect the user to this URL.
    
    Query params:
        return_url — URL to redirect to after leaving the portal
                     (defaults to the Referer header or '/')
    """
    tenant, error = _require_owner(request)
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
