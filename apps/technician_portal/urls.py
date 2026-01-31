from django.urls import path
from . import views

urlpatterns = [
    # Main technician portal entry points
    path('', views.technician_dashboard, name='technician_dashboard'),  # /tech/ now goes directly to dashboard
    path('dashboard/', views.technician_dashboard, name='technician_dashboard_alt'),  # alternative URL
    
    # Technician profile management
    path('profile/', views.update_technician_profile, name='technician_profile'),
    
    # Repair management
    path('repairs/', views.repair_list, name='repair_list'),
    path('repairs/assigned/', views.repair_list, name='assigned_repairs'),
    path('repairs/<int:repair_id>/', views.repair_detail, name='repair_detail'),
    path('repairs/<int:repair_id>/assign/', views.assign_repair, name='assign_repair'),
    path('repairs/<int:repair_id>/reassign-to-self/', views.reassign_to_self, name='reassign_to_self'),
    path('repairs/<int:repair_id>/apply-reward/', views.apply_reward_to_repair, name='apply_reward_to_repair'),
    path('repairs/create/', views.create_repair, name='create_repair'),
    path('repairs/create-multi-break/', views.create_multi_break_repair, name='create_multi_break_repair'),
    path('repairs/<int:repair_id>/convert-to-batch/', views.convert_to_batch, name='convert_to_batch'),
    path('repairs/<int:repair_id>/update/', views.update_repair, name='update_repair'),
    path('repairs/<int:repair_id>/update-status/', views.update_queue_status, name='update_queue_status'),
    path('check-existing-repair/', views.check_existing_repair, name='check_existing_repair'),
    path('repairs/bulk-action/', views.bulk_repair_action, name='tech_bulk_repair_action'),
    path('api/batch-pricing/', views.get_batch_pricing_json, name='get_batch_pricing'),
    path('api/viscosity-suggestion/', views.get_viscosity_suggestion, name='get_viscosity_suggestion'),

    # Multi-break batch management (technician portal)
    path('batch/<uuid:batch_id>/', views.technician_batch_detail, name='technician_batch_detail'),
    path('batch/<uuid:batch_id>/start-work/', views.technician_batch_start_work, name='technician_batch_start_work'),
    
    # Customer management
    path('customers/', views.customer_list, name='technician_customers'),
    path('customers/create/', views.create_customer, name='create_customer'),
    path('customers/<int:customer_id>/', views.customer_details, name='customer_detail'),
    path('customers/<int:customer_id>/primary-tech/', views.update_primary_technician, name='update_primary_technician'),
    path('customers/<int:customer_id>/units/<str:unit_number>/', views.unit_details, name='unit_details'),
    path('customers/<int:customer_id>/units/<str:unit_number>/replace/', views.mark_unit_replaced, name='mark_unit_replaced'),
    
    # Rewards and notifications
    path('reward-fulfillment/<int:redemption_id>/', views.reward_fulfillment_detail, name='reward_fulfillment_detail'),

    # Notification Management (Phase 5)
    path('notifications/preferences/', views.notification_preferences, name='notification_preferences'),
    path('notifications/history/', views.notification_history, name='notification_history'),
    path('notifications/<int:notification_id>/mark-read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_read, name='mark_all_read'),
    path('notifications/unread-count/', views.get_unread_count, name='get_unread_count'),
    path('verify-email/', views.verify_email, name='verify_email'),
    path('verify-phone/', views.verify_phone, name='verify_phone'),
    path('verify-email/<str:uidb64>/<str:token>/', views.confirm_email_verification, name='confirm_email_verification'),
    path('verify-phone/confirm/', views.confirm_phone_verification, name='confirm_phone_verification'),

    # Manager Settings
    path('settings/', views.manager_settings_dashboard, name='manager_settings_dashboard'),
    path('settings/viscosity/', views.manage_viscosity_rules, name='manage_viscosity_rules'),
    path('settings/team/', views.team_overview, name='team_overview'),

    # Manager Settings API endpoints
    path('settings/api/viscosity/create/', views.create_viscosity_rule, name='create_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/', views.get_viscosity_rule, name='get_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/update/', views.update_viscosity_rule, name='update_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/delete/', views.delete_viscosity_rule, name='delete_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/toggle/', views.toggle_viscosity_rule, name='toggle_viscosity_rule'),
]
