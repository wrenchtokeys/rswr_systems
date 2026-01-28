"""
Notification management views for the technician portal.

Includes preferences, history, verification, and AJAX endpoints.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.core.paginator import Paginator
from django.core.cache import cache
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
import logging

from apps.technician_portal.models import Technician
from apps.technician_portal.forms import TechnicianNotificationPreferenceForm
from apps.technician_portal.decorators import technician_required
from core.models import Notification, TechnicianNotificationPreference

logger = logging.getLogger(__name__)


@login_required
def notification_preferences(request):
    """Technician notification preferences management page."""
    try:
        technician = request.user.technician
    except Technician.DoesNotExist:
        messages.error(request, "Technician profile not found.")
        return redirect('technician_dashboard')

    preferences, created = TechnicianNotificationPreference.objects.get_or_create(
        technician=technician
    )

    if request.method == 'POST':
        form = TechnicianNotificationPreferenceForm(request.POST, instance=preferences)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification preferences updated successfully!")
            return redirect('notification_preferences')
    else:
        form = TechnicianNotificationPreferenceForm(instance=preferences)

    technician_ct = ContentType.objects.get_for_model(Technician)
    unread_count = Notification.objects.filter(
        recipient_type=technician_ct,
        recipient_id=technician.id,
        read=False
    ).count()

    total_notifications = Notification.objects.filter(
        recipient_type=technician_ct,
        recipient_id=technician.id
    ).count()

    context = {
        'form': form,
        'preferences': preferences,
        'technician': technician,
        'unread_count': unread_count,
        'total_notifications': total_notifications,
    }

    return render(request, 'technician_portal/notification_preferences.html', context)


@login_required
def notification_history(request):
    """View all notifications for technician with pagination and filters."""
    try:
        technician = request.user.technician
    except Technician.DoesNotExist:
        messages.error(request, "Technician profile not found.")
        return redirect('technician_dashboard')

    technician_ct = ContentType.objects.get_for_model(Technician)

    notifications = Notification.objects.filter(
        recipient_type=technician_ct,
        recipient_id=technician.id
    ).select_related(
        'repair',
        'customer',
        'template'
    ).order_by('-created_at')

    show_read = request.GET.get('show_read', 'false') == 'true'
    category = request.GET.get('category', '')

    if not show_read:
        notifications = notifications.filter(read=False)

    if category:
        notifications = notifications.filter(category=category)

    paginator = Paginator(notifications, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'notifications': page_obj,
        'show_read': show_read,
        'category': category,
        'categories': Notification.CATEGORY_CHOICES,
        'technician': technician,
    }

    return render(request, 'technician_portal/notification_history.html', context)


@technician_required
def mark_notification_read(request, notification_id):
    """Mark single notification as read."""
    try:
        technician = request.user.technician
        technician_ct = ContentType.objects.get_for_model(Technician)

        notification = Notification.objects.get(
            id=notification_id,
            recipient_type=technician_ct,
            recipient_id=technician.id
        )

        notification.mark_as_read()
        return JsonResponse({'success': True})

    except Notification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
def mark_all_read(request):
    """Mark all notifications as read for technician."""
    try:
        technician = request.user.technician
        technician_ct = ContentType.objects.get_for_model(Technician)

        updated = Notification.objects.filter(
            recipient_type=technician_ct,
            recipient_id=technician.id,
            read=False
        ).update(read=True, read_at=timezone.now())

        return JsonResponse({'success': True, 'count': updated})

    except Exception as e:
        logger.error(f"Error marking all notifications as read: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
def get_unread_count(request):
    """AJAX endpoint for notification bell polling with caching."""
    try:
        technician = request.user.technician
        technician_ct = ContentType.objects.get_for_model(Technician)

        cache_key = f'notif_unread_count:tech:{technician.id}'
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            return JsonResponse(cached_data)

        count = Notification.objects.filter(
            recipient_type=technician_ct,
            recipient_id=technician.id,
            read=False
        ).count()

        recent_notifications = Notification.objects.filter(
            recipient_type=technician_ct,
            recipient_id=technician.id
        ).select_related('template').order_by('-created_at')[:5]

        notifications_data = [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'created_at': n.created_at.isoformat(),
            'read': n.read,
            'action_url': n.action_url or '#',
        } for n in recent_notifications]

        response_data = {
            'success': True,
            'count': count,
            'notifications': notifications_data
        }

        cache.set(cache_key, response_data, timeout=120)

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def verify_email(request):
    """Send email verification link to technician."""
    try:
        technician = request.user.technician
        preferences = technician.notification_preferences
    except (Technician.DoesNotExist, TechnicianNotificationPreference.DoesNotExist):
        messages.error(request, "Unable to verify email.")
        return redirect('notification_preferences')

    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes

    token = default_token_generator.make_token(request.user)
    uid = urlsafe_base64_encode(force_bytes(request.user.pk))

    verification_url = request.build_absolute_uri(
        reverse('confirm_email_verification', kwargs={'uidb64': uid, 'token': token})
    )

    from django.core.mail import send_mail
    from django.conf import settings

    try:
        send_mail(
            subject='Verify your email address - RS Systems',
            message=f'Click this link to verify your email address: {verification_url}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
            fail_silently=False,
        )
        messages.success(request, f"Verification email sent to {request.user.email}")
    except Exception as e:
        logger.error(f"Failed to send verification email: {str(e)}")
        messages.error(request, "Failed to send verification email. Please try again later.")

    return redirect('notification_preferences')


@login_required
def verify_phone(request):
    """Send SMS verification code to technician."""
    try:
        technician = request.user.technician
        preferences = technician.notification_preferences
    except (Technician.DoesNotExist, TechnicianNotificationPreference.DoesNotExist):
        messages.error(request, "Unable to verify phone.")
        return redirect('notification_preferences')

    if not technician.phone_number:
        messages.error(request, "Please add a phone number first.")
        return redirect('notification_preferences')

    import random
    code = f"{random.randint(100000, 999999)}"

    request.session['phone_verification_code'] = code
    request.session['phone_verification_number'] = technician.phone_number
    request.session['phone_verification_expires'] = (timezone.now() + timedelta(minutes=10)).isoformat()

    from core.services.sms_service import SMSService
    message = f"Your RS Systems verification code is: {code}. This code expires in 10 minutes."

    try:
        from django.conf import settings
        if hasattr(settings, 'SMS_ENABLED') and settings.SMS_ENABLED:
            SMSService.send_sms(
                phone_number=technician.phone_number,
                message=message
            )
            messages.success(request, f"Verification code sent to {technician.phone_number}")
        else:
            messages.info(request, f"Development mode: Your verification code is {code}")
    except Exception as e:
        logger.error(f"Failed to send SMS verification: {str(e)}")
        messages.error(request, "Failed to send verification code. Please try again later.")

    return redirect('notification_preferences')


def confirm_email_verification(request, uidb64, token):
    """Process email verification token (no login required)."""
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode
    from django.contrib.auth.models import User

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        try:
            technician = user.technician
            technician.email_verified = True
            technician.email_verified_at = timezone.now()
            technician.save()

            prefs, created = TechnicianNotificationPreference.objects.get_or_create(
                technician=technician
            )
            prefs.email_verified = True
            prefs.email_verified_at = timezone.now()
            prefs.save()

            messages.success(request, "Email verified successfully! You can now receive email notifications.")
        except Technician.DoesNotExist:
            messages.error(request, "Technician profile not found.")
    else:
        messages.error(request, "Invalid or expired verification link. Please request a new verification email.")

    if request.user.is_authenticated:
        return redirect('notification_preferences')
    else:
        return redirect('technician_login')


@login_required
def confirm_phone_verification(request):
    """Process phone verification code."""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        stored_code = request.session.get('phone_verification_code')
        stored_number = request.session.get('phone_verification_number')
        expires_str = request.session.get('phone_verification_expires')

        if not all([stored_code, stored_number, expires_str]):
            messages.error(request, "No verification code found. Please request a new code.")
            return redirect('notification_preferences')

        from dateutil import parser
        expires = parser.isoparse(expires_str)
        if timezone.now() > expires:
            messages.error(request, "Verification code has expired. Please request a new code.")
            request.session.pop('phone_verification_code', None)
            request.session.pop('phone_verification_number', None)
            request.session.pop('phone_verification_expires', None)
            return redirect('notification_preferences')

        if code == stored_code:
            try:
                technician = request.user.technician
                if technician.phone_number == stored_number:
                    technician.phone_verified = True
                    technician.phone_verified_at = timezone.now()
                    technician.save()
                    messages.success(request, "Phone number verified successfully!")

                    request.session.pop('phone_verification_code', None)
                    request.session.pop('phone_verification_number', None)
                    request.session.pop('phone_verification_expires', None)
                else:
                    messages.error(request, "Phone number has changed. Please request a new verification code.")
            except Technician.DoesNotExist:
                messages.error(request, "Technician profile not found.")
        else:
            messages.error(request, "Invalid verification code. Please try again.")

    return redirect('notification_preferences')
