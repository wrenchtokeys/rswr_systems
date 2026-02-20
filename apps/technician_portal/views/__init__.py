"""
Technician portal views package.

Split from a single 2700-line views.py into logical modules:
- dashboard: Registration and dashboard
- repairs: Repair CRUD, list, detail, status, assignment
- batch: Multi-break batch repair operations
- customers: Customer management
- rewards: Reward fulfillment and application
- settings: Manager settings (viscosity rules, team overview)
- notifications: Notification preferences, history, verification
- api: JSON API endpoints (pricing, viscosity, profile)
"""

# Dashboard & registration
from .dashboard import register_technician, technician_dashboard

# Repair management
from .repairs import (
    repair_list,
    repair_detail,
    create_repair,
    update_repair,
    update_queue_status,
    assign_repair,
    reassign_to_self,
    check_existing_repair,
    bulk_repair_action,
    tech_collect_payment,
)

# Multi-break batch operations
from .batch import (
    technician_batch_detail,
    technician_batch_start_work,
    create_multi_break_repair,
    convert_to_batch,
)

# Customer management
from .customers import (
    create_customer,
    customer_list,
    customer_details,
    edit_customer,
    delete_customer,
    unit_details,
    mark_unit_replaced,
    update_primary_technician,
    send_customer_invitation,
    resend_customer_invitation,
    cancel_customer_invitation,
)

# Reward management
from .rewards import (
    reward_fulfillment_detail,
    apply_reward_to_repair,
)

# Manager settings
from .settings import (
    manager_settings_dashboard,
    manage_viscosity_rules,
    get_viscosity_rule,
    create_viscosity_rule,
    update_viscosity_rule,
    delete_viscosity_rule,
    toggle_viscosity_rule,
    team_overview,
)

# Notifications
from .notifications import (
    notification_preferences,
    notification_history,
    mark_notification_read,
    mark_all_read,
    get_unread_count,
    verify_email,
    verify_phone,
    confirm_email_verification,
    confirm_phone_verification,
)

# API endpoints
from .api import (
    get_batch_pricing_json,
    get_viscosity_suggestion,
    update_technician_profile,
)
