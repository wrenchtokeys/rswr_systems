"""
SaaS UI URL Configuration

Author: Amelia (Clawdbot AI)
"""

from django.urls import path
from . import views

urlpatterns = [
    # Subscription blocked (role-aware)
    path('subscription-blocked/', views.subscription_blocked_view, name='subscription_blocked'),

    # Email confirmation for new shop owner accounts (is_active=False until clicked)
    path('confirm-email/<str:uidb64>/<str:token>/', views.owner_confirm_email, name='owner_confirm_email'),
    path('confirm-email/<str:uidb64>/resend/', views.resend_confirmation_email, name='resend_confirmation_email'),

    # Email verification for shop owners (already-active accounts, e.g. shop_join flow)
    path('verify-email/<str:uidb64>/<str:token>/', views.owner_confirm_email_verification, name='owner_confirm_email_verification'),

    # Public pages
    path('signup/', views.signup_view, name='signup'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('terms/', views.terms_of_service, name='terms_of_service'),
    path('privacy/', views.privacy_policy, name='privacy_policy'),

    # Post-signup onboarding
    path('onboarding/', views.onboarding_view, name='onboarding'),

    # Owner dashboard & billing
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('owner/billing/', views.billing_view, name='billing_settings'),
    path('owner/billing/update/', views.billing_update_plan, name='billing_update_plan'),
    path('owner/billing/cancel/', views.billing_cancel, name='billing_cancel'),

    # Stripe Connect (receive invoice payments)
    path('owner/payments/setup/', views.connect_setup, name='connect_setup'),
    path('owner/payments/setup/return/', views.connect_return, name='connect_return'),
    path('owner/payments/setup/refresh/', views.connect_refresh, name='connect_refresh'),
    path('owner/payments/dashboard/', views.connect_dashboard, name='connect_dashboard'),
    path('owner/update-payment-method/', views.update_payment_method, name='update_payment_method'),
    path('owner/billing/portal/', views.billing_portal_redirect, name='billing_portal_redirect'),

    # Owner settings & team
    path('owner/settings/', views.owner_settings_view, name='owner_settings'),
    path('owner/settings/invite/', views.invite_member, name='owner_invite_member'),

    # Team management (Phase 6)
    path('owner/team/<int:membership_id>/update/', views.update_team_member, name='update_team_member'),
    path('owner/team/<int:membership_id>/deactivate/', views.deactivate_team_member, name='deactivate_team_member'),
    path('owner/team/<int:membership_id>/resend-invite/', views.resend_invite, name='resend_invite'),

    # Owner invoice management & manual payments
    path('owner/invoices/', views.owner_invoice_list, name='owner_invoice_list'),
    path('owner/invoices/<int:invoice_id>/', views.owner_invoice_detail, name='owner_invoice_detail'),
    path('owner/invoices/<int:invoice_id>/record-payment/', views.owner_record_payment, name='owner_record_payment'),
    path('owner/invoices/bulk/', views.owner_invoice_bulk_action, name='owner_invoice_bulk_action'),
    path('owner/invoices/<int:invoice_id>/pdf/', views.owner_invoice_pdf, name='owner_invoice_pdf'),
    path('owner/invoices/<int:invoice_id>/send/', views.owner_send_invoice, name='owner_send_invoice'),
    path('owner/invoices/<int:invoice_id>/email/', views.owner_email_invoice, name='owner_email_invoice'),
    path('owner/invoices/<int:invoice_id>/reminder/', views.owner_send_reminder, name='owner_send_reminder'),
    path('owner/invoices/<int:invoice_id>/void/', views.owner_invoice_void, name='owner_invoice_void'),
    path('owner/invoices/generate-from-repair/<int:repair_id>/', views.owner_generate_invoice_from_repair, name='owner_generate_invoice_from_repair'),

    # Aging report (Phase 6)
    path('owner/billing/aging/', views.owner_aging_report_json, name='owner_aging_report'),
    path('owner/billing/aging/export/', views.owner_aging_report_csv, name='owner_aging_report_csv'),

    # Statement of Account (Phase 6)
    path('owner/customers/<int:customer_id>/statement/', views.owner_customer_statement, name='owner_customer_statement'),

    # Unified setup page
    path('owner/setup/', views.owner_setup_view, name='owner_setup'),
    path('owner/setup/save/business/', views.owner_setup_save_business, name='owner_setup_save_business'),
    path('owner/setup/save/pricing/', views.owner_setup_save_pricing, name='owner_setup_save_pricing'),
    path('owner/setup/save/tax/', views.owner_setup_save_tax, name='owner_setup_save_tax'),
    path('owner/setup/save/billing/', views.owner_setup_save_billing, name='owner_setup_save_billing'),
    path('owner/setup/save/viscosity/', views.owner_setup_save_viscosity, name='owner_setup_save_viscosity'),
    path('owner/setup/save/assignment/', views.owner_setup_save_assignment, name='owner_setup_save_assignment'),

    # Loyalty Phase 2: Manual point adjustment + liability report (CODE-197)
    path('owner/loyalty/', views.owner_loyalty_dashboard, name='owner_loyalty_dashboard'),
    path('owner/loyalty/config/', views.owner_loyalty_save_config, name='owner_loyalty_save_config'),
    path('owner/loyalty/customers/<int:customer_user_id>/adjust/', views.owner_loyalty_adjust_points, name='owner_loyalty_adjust_points'),
    path('owner/loyalty/liability/', views.owner_loyalty_liability_report, name='owner_loyalty_liability_report'),

    # Tax rate management
    path('owner/tax-rates/', views.owner_tax_rates, name='owner_tax_rates'),
    path('owner/tax-rates/add/', views.owner_add_tax_rate, name='owner_add_tax_rate'),
    path('owner/tax-rates/<int:rate_id>/edit/', views.owner_edit_tax_rate, name='owner_edit_tax_rate'),
    path('owner/tax-rates/<int:rate_id>/delete/', views.owner_delete_tax_rate, name='owner_delete_tax_rate'),
    path('owner/tax-rates/toggle/', views.owner_toggle_tax, name='owner_toggle_tax'),

    # Warranty policy management (owner/manager)
    path('owner/settings/warranty/create/', views.owner_warranty_create, name='owner_warranty_create'),
    path('owner/settings/warranty/<int:policy_id>/edit/', views.owner_warranty_edit, name='owner_warranty_edit'),
    path('owner/settings/warranty/<int:policy_id>/toggle/', views.owner_warranty_toggle, name='owner_warranty_toggle'),

    # Replacement management
    path('tech/replacements/', views.replacement_list, name='replacement_list'),
    path('tech/replacement/new/', views.replacement_create, name='replacement_create'),
    path('tech/replacement/<int:pk>/', views.replacement_detail, name='replacement_detail'),
    path('tech/replacement/<int:pk>/edit/', views.replacement_edit, name='replacement_edit'),
    path('tech/replacement/<int:pk>/update-status/', views.replacement_update_status, name='replacement_update_status'),
]
