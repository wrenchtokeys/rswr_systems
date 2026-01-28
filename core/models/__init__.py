"""
Core models for the RS Systems.

This module exports all core models for easy import.
"""

# Import Customer and Vehicle models
from .customer import Customer
from .vehicle import Vehicle

# Import notification models
from .notification import Notification
from .notification_preferences import (
    BaseNotificationPreference,
    TechnicianNotificationPreference,
    CustomerNotificationPreference
)
from .notification_template import NotificationTemplate
from .notification_delivery_log import NotificationDeliveryLog
from .email_branding import EmailBrandingConfig

__all__ = [
    'Customer',
    'Vehicle',
    'Notification',
    'BaseNotificationPreference',
    'TechnicianNotificationPreference',
    'CustomerNotificationPreference',
    'NotificationTemplate',
    'NotificationDeliveryLog',
    'EmailBrandingConfig',
]
