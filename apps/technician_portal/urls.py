from django.urls import path
from . import views

urlpatterns = [
    # Main technician portal entry points
    path('', views.technician_dashboard, name='technician_dashboard'),  # /tech/ now goes directly to dashboard
    path('dashboard/', views.technician_dashboard, name='technician_dashboard_alt'),  # alternative URL
    
    # Technician profile management
    path('profile/', views.update_technician_profile, name='technician_profile'),

    # Global search (navbar box on every portal page)
    path('search/', views.global_search, name='global_search'),
    
    # Unified jobs surface (repairs + replacements)
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/new/', views.job_create, name='job_create'),
    path('repairs/<int:repair_id>/complete-and-invoice/', views.repair_complete_and_invoice, name='repair_complete_and_invoice'),

    # Repair management (repair_list is a redirect shim to job_list)
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
    path('repairs/<int:repair_id>/collect-payment/', views.tech_collect_payment, name='tech_collect_payment'),
    path('repairs/<int:repair_id>/delete/', views.delete_repair, name='delete_repair'),
    path('repairs/<int:repair_id>/restore/', views.restore_repair, name='restore_repair'),
    path('repairs/archived/', views.archived_repairs, name='archived_repairs'),
    path('check-existing-repair/', views.check_existing_repair, name='check_existing_repair'),
    path('repairs/bulk-action/', views.bulk_repair_action, name='tech_bulk_repair_action'),
    path('repairs/<int:repair_id>/reassign/', views.admin_reassign_repair, name='admin_reassign_repair'),
    path('repairs/bulk-reassign/', views.portal_bulk_reassign, name='portal_bulk_reassign'),
    path('api/batch-pricing/', views.get_batch_pricing_json, name='get_batch_pricing'),
    path('api/viscosity-suggestion/', views.get_viscosity_suggestion, name='get_viscosity_suggestion'),

    # Multi-break batch management (technician portal)
    path('batch/<uuid:batch_id>/', views.technician_batch_detail, name='technician_batch_detail'),
    path('batch/<uuid:batch_id>/start-work/', views.technician_batch_start_work, name='technician_batch_start_work'),
    path('batch/<uuid:batch_id>/complete-all/', views.batch_complete_all, name='batch_complete_all'),
    
    # Customer management
    path('customers/', views.customer_list, name='technician_customers'),
    path('customers/create/', views.create_customer, name='create_customer'),
    path('customers/<int:customer_id>/', views.customer_details, name='customer_detail'),
    path('customers/<int:customer_id>/edit/', views.edit_customer, name='edit_customer'),
    path('customers/<int:customer_id>/delete/', views.delete_customer, name='delete_customer'),
    path('customers/<int:customer_id>/primary-tech/', views.update_primary_technician, name='update_primary_technician'),
    path('customers/<int:customer_id>/units/<str:unit_number>/', views.unit_details, name='unit_details'),
    path('customers/<int:customer_id>/units/<str:unit_number>/replace/', views.mark_unit_replaced, name='mark_unit_replaced'),
    path('customers/<int:customer_id>/invite/', views.send_customer_invitation, name='send_customer_invitation'),
    path('invitations/<int:invitation_id>/resend/', views.resend_customer_invitation, name='resend_customer_invitation'),
    path('invitations/<int:invitation_id>/cancel/', views.cancel_customer_invitation, name='cancel_customer_invitation'),
    path('customers/<int:customer_id>/portal-users/<int:cu_id>/set-primary/', views.set_primary_contact, name='set_primary_contact'),
    
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

    # Warranty Claim
    path('repairs/<int:repair_id>/warranty-claim/', views.create_warranty_claim, name='create_warranty_claim'),

    # Manager Settings
    path('settings/', views.manager_settings_dashboard, name='manager_settings_dashboard'),
    path('settings/viscosity/', views.manage_viscosity_rules, name='manage_viscosity_rules'),
    path('settings/team/', views.team_overview, name='team_overview'),
    path('settings/warranty/', views.manage_warranty_policies, name='manage_warranty_policies'),

    # Manager Settings API endpoints
    path('settings/api/viscosity/create/', views.create_viscosity_rule, name='create_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/', views.get_viscosity_rule, name='get_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/update/', views.update_viscosity_rule, name='update_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/delete/', views.delete_viscosity_rule, name='delete_viscosity_rule'),
    path('settings/api/viscosity/<int:rule_id>/toggle/', views.toggle_viscosity_rule, name='toggle_viscosity_rule'),

    # Warranty Policy API endpoints
    path('settings/api/warranty/create/', views.create_warranty_policy, name='create_warranty_policy'),
    path('settings/api/warranty/<int:policy_id>/', views.get_warranty_policy, name='get_warranty_policy'),
    path('settings/api/warranty/<int:policy_id>/update/', views.update_warranty_policy, name='update_warranty_policy'),
    path('settings/api/warranty/<int:policy_id>/delete/', views.delete_warranty_policy, name='delete_warranty_policy'),
    path('settings/api/warranty/<int:policy_id>/toggle/', views.toggle_warranty_policy, name='toggle_warranty_policy'),
]
