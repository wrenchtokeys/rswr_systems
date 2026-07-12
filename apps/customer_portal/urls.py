from django.urls import path
from . import views

urlpatterns = [
    # Customer Invitation (must be before auth-required routes)
    path('invite/<str:token>/', views.accept_customer_invitation, name='accept_customer_invitation'),
    
    # Main customer portal entry points
    path('', views.customer_dashboard, name='customer_dashboard'),  # /app/ now goes directly to dashboard
    path('dashboard/', views.customer_dashboard, name='customer_dashboard_alt'),  # alternative URL
    
    # User onboarding and registration
    path('register/', views.customer_register, name='customer_register'),
    path('profile/create/', views.profile_creation, name='profile_creation'),
    
    # Repairs management
    path('repairs/', views.customer_repairs, name='customer_repairs'),
    path('repairs/<int:repair_id>/', views.customer_repair_detail, name='customer_repair_detail'),
    path('repairs/<int:repair_id>/approve/', views.customer_repair_approve, name='customer_repair_approve'),
    path('repairs/<int:repair_id>/deny/', views.customer_repair_deny, name='customer_repair_deny'),
    path('repairs/request/', views.request_repair, name='customer_request_repair'),
    path('repairs/<int:repair_id>/apply-reward/', views.customer_apply_reward, name='customer_apply_reward'),
    path('repairs/bulk-action/', views.customer_bulk_action, name='customer_bulk_action'),

    # Replacements management
    path('replacements/', views.customer_replacements, name='customer_replacements'),
    path('replacements/<int:replacement_id>/', views.customer_replacement_detail, name='customer_replacement_detail'),
    path('replacements/<int:replacement_id>/approve/', views.customer_replacement_approve, name='customer_replacement_approve'),
    path('replacements/<int:replacement_id>/deny/', views.customer_replacement_deny, name='customer_replacement_deny'),
    path('replacements/request/', views.request_replacement, name='customer_request_replacement'),

    # Multi-break batch management
    path('batch/<uuid:batch_id>/', views.customer_batch_detail, name='customer_batch_detail'),
    path('batch/<uuid:batch_id>/approve/', views.customer_batch_approve, name='customer_batch_approve'),
    path('batch/<uuid:batch_id>/deny/', views.customer_batch_deny, name='customer_batch_deny'),
    
    # Invoices
    path('invoices/', views.customer_invoices, name='customer_invoices'),
    path('invoices/<int:invoice_id>/', views.customer_invoice_detail, name='customer_invoice_detail'),
    path('invoices/<int:invoice_id>/pdf/', views.customer_invoice_pdf, name='customer_invoice_pdf'),
    path('invoices/<int:invoice_id>/pay/', views.customer_invoice_pay, name='customer_invoice_pay'),

    # Company and account management
    path('company/edit/', views.edit_company, name='edit_company'),
    path('account/settings/', views.account_settings, name='customer_account_settings'),
    
    # Team management (self-service)
    path('team/', views.customer_team, name='customer_team'),
    path('team/invite/', views.customer_invite_team_member, name='customer_invite_team_member'),
    path('team/invitations/<int:invitation_id>/cancel/', views.customer_cancel_invitation, name='customer_cancel_invitation'),
    path('team/invitations/<int:invitation_id>/resend/', views.customer_resend_invitation, name='customer_resend_invitation'),
    
    # Rewards and referrals dashboard
    path('rewards/', views.customer_rewards_redirect, name='customer_rewards'),
    path('rewards/points-history/', views.customer_points_history, name='customer_points_history'),
    
    # API endpoints for data visualization
    path('api/unit-repair-data/', views.unit_repair_data_api, name='unit_repair_data_api'),
    path('api/repair-cost-data/', views.repair_cost_data_api, name='repair_cost_data_api'),
    path('api/repair-pricing/', views.repair_pricing_api, name='repair_pricing_api'),

    # Notification Management
    path('notifications/preferences/', views.customer_notification_preferences, name='customer_notification_preferences'),
    path('notifications/history/', views.customer_notification_history, name='customer_notification_history'),
    path('notifications/<int:notification_id>/mark-read/', views.customer_mark_notification_read, name='customer_mark_notification_read'),
    path('notifications/mark-all-read/', views.customer_mark_all_read, name='customer_mark_all_read'),
    path('notifications/unread-count/', views.customer_get_unread_count, name='customer_get_unread_count'),

    # One-Click Approval (no login required — token-based)
    path('quick-approve/<uuid:token>/', views.quick_approve_repair, name='quick_approve'),
    path('quick-deny/<uuid:token>/', views.quick_deny_repair, name='quick_deny'),

    # Contact Verification
    path('verify-email/', views.customer_verify_email, name='customer_verify_email'),
    path('verify-phone/', views.customer_verify_phone, name='customer_verify_phone'),
    path('verify-email/<str:uidb64>/<str:token>/', views.customer_confirm_email_verification, name='customer_confirm_email_verification'),
    path('verify-phone/confirm/', views.customer_confirm_phone_verification, name='customer_confirm_phone_verification'),
]
