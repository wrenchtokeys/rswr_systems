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

    # Create test notification using a real template
    # We'll use the repair_completed template with dummy data
    import logging
    import traceback
    logger = logging.getLogger(__name__)

    try:
        from apps.technician_portal.models import Repair
        from core.models import NotificationTemplate

        # Check if template exists
        template = NotificationTemplate.objects.filter(
            name='repair_completed',
            active=True
        ).first()

        if not template:
            return JsonResponse({
                'success': False,
                'error': 'Template repair_completed not found or inactive',
                'available_templates': list(NotificationTemplate.objects.filter(active=True).values_list('name', flat=True))
            })

        # Get any repair to use as test data, or create minimal context
        repair = Repair.objects.first()

        if repair:
            # IMPORTANT: Only pass JSON-serializable values (strings, numbers, booleans)
            # DO NOT pass Django model objects - they cannot be stored in JSONField
            context = {
                'repair_id': repair.pk,
                'unit_number': repair.unit_number,
                'customer_name': repair.customer.name if repair.customer else 'Test Customer',
                'technician_name': repair.technician.user.get_full_name() if repair.technician else 'Test Technician',
                'estimated_cost': float(repair.cost) if repair.cost else 0.0,
                'damage_type': repair.get_damage_type_display() or 'Unknown',
                'action_url': f'/app/repairs/{repair.pk}/',
            }
        else:
            # Fallback context if no repairs exist
            context = {
                'unit_number': 'TEST',
                'customer_name': 'Test Customer',
                'technician_name': 'Test Technician',
                'estimated_cost': 0.0,
                'damage_type': 'Unknown',
                'action_url': '/app/repairs/',
            }

        logger.info(f"Attempting to create notification for {recipient_type} with template repair_completed")
        logger.info(f"Context: {context}")

        notification = NotificationService.create_notification(
            recipient=recipient,
            template_name='repair_completed',
            context=context,
            priority=Notification.PRIORITY_MEDIUM
        )

        logger.info(f"Notification creation result: {notification}")

        return JsonResponse({
            'success': True,
            'notification_id': notification.id if notification else None,
            'notification_created': notification is not None,
            'recipient_type': recipient_type,
            'recipient_email': user.email,
            'email_verified': prefs.email_verified,
            'can_send_email': prefs.can_send_email(),
            'receive_email_notifications': prefs.receive_email_notifications,
            'template_found': True,
            'message': 'Test notification created. Check your email and the notification diagnostic for delivery status.' if notification else 'Notification was not created - check logs for details.'
        })
    except Exception as e:
        logger.error(f"Failed to create test notification: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': f'Failed to create notification: {str(e)}',
            'traceback': traceback.format_exc()
        })
