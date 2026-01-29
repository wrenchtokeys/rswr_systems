"""
SaaS UI URL Configuration

Author: Amelia (Clawdbot AI)
"""

from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('signup/', views.signup_view, name='signup'),
    path('pricing/', views.pricing_view, name='pricing'),

    # Post-signup onboarding
    path('onboarding/', views.onboarding_view, name='onboarding'),

    # Owner dashboard & billing
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('owner/billing/', views.billing_view, name='billing_settings'),
    path('owner/billing/update/', views.billing_update_plan, name='billing_update_plan'),
    path('owner/billing/cancel/', views.billing_cancel, name='billing_cancel'),
    path('owner/billing/portal/', views.billing_portal_redirect, name='billing_portal_redirect'),

    # Owner settings & team
    path('owner/settings/', views.owner_settings_view, name='owner_settings'),
    path('owner/settings/invite/', views.invite_member, name='owner_invite_member'),

    # Replacement management
    path('tech/replacement/new/', views.replacement_create, name='replacement_create'),
    path('tech/replacement/<int:pk>/', views.replacement_detail, name='replacement_detail'),
]
