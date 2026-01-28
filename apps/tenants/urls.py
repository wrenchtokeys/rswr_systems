"""
Tenant Subscription URL Configuration

SaaS billing endpoints at /api/tenants/.

Author: Amelia (Clawdbot AI)
"""

from django.urls import path
from . import views
from . import webhooks

app_name = 'tenants'

urlpatterns = [
    # Plan listing (public)
    path('plans/', views.list_plans, name='plans_list'),
    
    # Subscription management (authenticated)
    path('subscribe/', views.subscribe, name='subscribe'),
    path('subscription/update/', views.update_subscription, name='subscription_update'),
    path('subscription/cancel/', views.cancel_subscription, name='subscription_cancel'),
    path('subscription/reactivate/', views.reactivate_subscription, name='subscription_reactivate'),
    
    # Usage
    path('usage/', views.usage, name='usage'),
    
    # Billing portal
    path('billing-portal/', views.billing_portal, name='billing_portal'),
    
    # Stripe webhook
    path('webhooks/stripe/', webhooks.stripe_subscription_webhook, name='stripe_subscription_webhook'),
]
