"""
Signals for Core App

Automatic setup for new customers and notification preferences.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Customer
from core.models.notification_preferences import CustomerNotificationPreference


@receiver(post_save, sender=Customer)
def create_customer_notification_preferences(sender, instance, created, **kwargs):
    """
    Auto-create CustomerNotificationPreference when new Customer is created.

    Sets defaults based on user requirements:
    - notify_pending_approvals: True (repairs need approval)
    - notify_completions: True (repairs completed)
    - notify_new_requests: True (new repair created)
    - All other categories: True (avoid missing notifications)
    - Channels: email=True, sms=False (opt-in), in_app=True
    - Batch mode: False (individual notifications)
    - Quiet hours: False (disabled)
    """
    if created:
        CustomerNotificationPreference.objects.get_or_create(
            customer=instance,
            defaults={
                'receive_email_notifications': True,
                'receive_sms_notifications': False,  # Opt-in for SMS
                'receive_in_app_notifications': True,
                # User-specified defaults
                'notify_pending_approvals': True,
                'notify_completions': True,
                'notify_new_requests': True,
                # Other categories
                'notify_in_progress': True,
                'notify_repair_status': True,
                'notify_rewards': True,
                'notify_system': True,
                # Batch mode
                'batch_pending_approvals': False,  # Individual notifications by default
                # Quiet hours disabled
                'quiet_hours_enabled': False,
            }
        )
