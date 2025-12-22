from django.http import JsonResponse
from django.contrib.auth.decorators import login_required


@login_required
def check_notification_prefs(request):
    """
    Check all notification preference settings for the current user.
    Access at: /check-notification-prefs/
    """
    user = request.user

    try:
        if hasattr(user, 'technician'):
            recipient = user.technician
            prefs = recipient.notification_preferences
            recipient_type = 'technician'
        elif hasattr(user, 'customeruser'):
            recipient = user.customeruser.customer
            prefs = recipient.notification_preferences
            recipient_type = 'customer'
        else:
            return JsonResponse({
                'success': False,
                'error': 'User is not a technician or customer'
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Could not get notification preferences: {str(e)}'
        })

    # Get all preference fields
    return JsonResponse({
        'success': True,
        'recipient_type': recipient_type,
        'recipient_email': user.email,
        'preferences': {
            # Global preferences
            'receive_email_notifications': prefs.receive_email_notifications,
            'receive_sms_notifications': prefs.receive_sms_notifications,
            'receive_in_app_notifications': prefs.receive_in_app_notifications,

            # Category preferences
            'notify_repair_status': prefs.notify_repair_status,
            'notify_assignments': prefs.notify_assignments,
            'notify_approvals': prefs.notify_approvals,
            'notify_rewards': prefs.notify_rewards,
            'notify_system': prefs.notify_system,

            # Verification status
            'email_verified': prefs.email_verified,
            'phone_verified': prefs.phone_verified,

            # Quiet hours
            'quiet_hours_enabled': prefs.quiet_hours_enabled,
            'quiet_hours_start': str(prefs.quiet_hours_start) if prefs.quiet_hours_start else None,
            'quiet_hours_end': str(prefs.quiet_hours_end) if prefs.quiet_hours_end else None,

            # Computed properties
            'can_send_email': prefs.can_send_email(),
            'can_send_sms': prefs.can_send_sms(),
            'is_in_quiet_hours': prefs.is_in_quiet_hours(),
        }
    })
