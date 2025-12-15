from django.urls import path
from . import views

urlpatterns = [
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
    path('repairs/bulk-action/', views.customer_bulk_action, name='customer_bulk_action'),

    # Multi-break batch management
    path('batch/<uuid:batch_id>/', views.customer_batch_detail, name='customer_batch_detail'),
    path('batch/<uuid:batch_id>/approve/', views.customer_batch_approve, name='customer_batch_approve'),
    path('batch/<uuid:batch_id>/deny/', views.customer_batch_deny, name='customer_batch_deny'),
    
    # Company and account management
    path('company/edit/', views.edit_company, name='edit_company'),
    path('account/settings/', views.account_settings, name='customer_account_settings'),
    
    # Rewards and referrals dashboard
    path('rewards/', views.customer_rewards_redirect, name='customer_rewards'),
    
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

    # Contact Verification
    path('verify-email/', views.customer_verify_email, name='customer_verify_email'),
    path('verify-phone/', views.customer_verify_phone, name='customer_verify_phone'),
    path('verify-email/<str:uidb64>/<str:token>/', views.customer_confirm_email_verification, name='customer_confirm_email_verification'),
    path('verify-phone/confirm/', views.customer_confirm_phone_verification, name='customer_confirm_phone_verification'),
]
