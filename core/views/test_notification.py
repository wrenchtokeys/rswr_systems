from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from core.services.notification_service import NotificationService
from core.models import Notification
from django.utils import timezone


@login_required
def test_notification(request):
    """
    Test endpoint to manually trigger a notification.
    Access at: /test-notification/

    This will create a test notification and attempt to send it via email.
    Returns JSON with diagnostic information.
    """
    user = request.user

    # Get notification preferences
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

    # Create test notification
    try:
        notification = NotificationService.create_notification(
            recipient=recipient,
            template_name='system_announcement',
            context={
                'message': 'This is a test notification sent at ' + str(timezone.now()),
                'subject': 'Test Notification',
            },
            priority=Notification.PRIORITY_MEDIUM,
            category=Notification.CATEGORY_SYSTEM
        )

        return JsonResponse({
            'success': True,
            'notification_id': notification.id if notification else None,
            'recipient_type': recipient_type,
            'recipient_email': user.email,
            'email_verified': prefs.email_verified,
            'can_send_email': prefs.can_send_email(),
            'receive_email_notifications': prefs.receive_email_notifications,
            'message': 'Test notification created. Check your email and the notification diagnostic for delivery status.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Failed to create notification: {str(e)}'
        })
