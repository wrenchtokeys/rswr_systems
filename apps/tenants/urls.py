"""
Tenant Subscription URL Configuration

SaaS billing & onboarding endpoints at /api/tenants/.

Author: Amelia (Clawdbot AI)
"""

from django.urls import path
from . import views, webhooks

app_name = 'tenants'

urlpatterns = [
    # Onboarding (public)
    path('signup/', views.signup, name='signup'),
    
    # Plan listing (public)
    path('plans/', views.list_plans, name='plans_list'),
    
    # Tenant status (authenticated)
    path('status/', views.tenant_status, name='tenant_status'),
    
    # Subscription management (authenticated, owner-only)
    path('subscribe/', views.subscribe, name='subscribe'),
    path('subscription/update/', views.update_subscription, name='subscription_update'),
    path('subscription/cancel/', views.cancel_subscription, name='subscription_cancel'),
    path('subscription/reactivate/', views.reactivate_subscription, name='subscription_reactivate'),
    
    # Usage (authenticated)
    path('usage/', views.usage, name='usage'),
    
    # Billing portal (authenticated, owner-only)
    path('billing-portal/', views.billing_portal, name='billing_portal'),
    
    # Stripe subscription webhook (separate from billing webhook)
    path('webhooks/stripe/', webhooks.stripe_subscription_webhook, name='stripe_subscription_webhook'),
]
