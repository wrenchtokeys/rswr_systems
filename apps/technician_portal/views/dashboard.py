"""
Dashboard and registration views for the technician portal.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
import logging

from apps.technician_portal.models import Technician, Repair, TechnicianNotification
from apps.customer_portal.models import RepairApproval
from apps.rewards_referrals.models import RewardRedemption
from core.models import Customer, Notification
from apps.technician_portal.forms import TechnicianRegistrationForm
from apps.technician_portal.decorators import technician_required

logger = logging.getLogger(__name__)


def register_technician(request):
    """Handle technician registration."""
    if request.method == 'POST':
        form = TechnicianRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Account created for {user.username}')
            return redirect('admin:index')
    else:
        form = TechnicianRegistrationForm()
    return render(request, 'registration/register_technician.html', {'form': form})


@technician_required
def technician_dashboard(request):
    """Main technician dashboard with work queues, notifications, and stats."""
    # Get technician profile or None for admin users without a profile
    technician = None
    if hasattr(request.user, 'technician'):
        technician = request.user.technician

    # Get customer-requested repairs (ONLY for managers)
    if technician:
        # Only MANAGERS can see REQUESTED repairs (for assignment purposes)
        if technician.is_manager:
            customer_requested_repairs = Repair.objects.filter(
                queue_status='REQUESTED'
            ).select_related('customer', 'technician').order_by('-repair_date')
        else:
            customer_requested_repairs = Repair.objects.none()

        # Get assigned reward redemptions for this technician
        assigned_redemptions = RewardRedemption.objects.filter(
            assigned_technician=technician,
            status='PENDING'
        ).order_by('-created_at')

        # Get all pending redemptions (visible to all technicians)
        all_pending_redemptions = RewardRedemption.objects.filter(
            status='PENDING'
        ).exclude(
            id__in=[r.id for r in assigned_redemptions]
        ).order_by('-created_at')[:5]

        # Get unread notifications
        unread_notifications = technician.notifications.filter(read=False).order_by('-created_at')

        # Get recently approved repairs for this technician (approved in last 24 hours)
        recent_approvals = RepairApproval.objects.filter(
            approved=True,
            approval_date__gte=timezone.now() - timedelta(hours=24)
        ).values_list('repair_id', flat=True)

        repairs_recently_approved = Repair.objects.filter(
            id__in=recent_approvals,
            technician=technician,
            queue_status='APPROVED'
        ).select_related('customer').order_by('-repair_date')

        # Group batch repairs and separate individual repairs
        batch_repairs_approved = {}
        individual_repairs_approved = []

        for repair in repairs_recently_approved[:10]:
            if repair.is_part_of_batch:
                if repair.repair_batch_id not in batch_repairs_approved:
                    try:
                        batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            batch_repairs_approved[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
            else:
                individual_repairs_approved.append(repair)

        individual_repairs_approved = individual_repairs_approved[:5]

        # Get active work (IN_PROGRESS and APPROVED)
        repairs_active = Repair.objects.filter(
            technician=technician,
            queue_status__in=['IN_PROGRESS', 'APPROVED']
        ).select_related('customer').order_by('-repair_date')

        batch_repairs_in_progress = {}
        individual_repairs_in_progress = []

        for repair in repairs_active[:30]:
            if repair.is_part_of_batch:
                if repair.repair_batch_id not in batch_repairs_in_progress:
                    try:
                        batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            incomplete_count = batch_summary.get('in_progress_count', 0) + batch_summary.get('approved_count', 0)
                            if incomplete_count > 0 and repair.repair_batch_id not in batch_repairs_approved:
                                batch_repairs_in_progress[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
            else:
                if repair.queue_status == 'IN_PROGRESS':
                    individual_repairs_in_progress.append(repair)

        individual_repairs_in_progress = individual_repairs_in_progress[:5]

        # Get recently completed batch repairs (completed in last 7 days)
        recent_completions = Repair.objects.filter(
            technician=technician,
            queue_status='COMPLETED',
            repair_date__gte=timezone.now() - timedelta(days=7)
        ).select_related('customer').order_by('-repair_date')

        batch_repairs_completed = {}
        individual_repairs_completed = []

        for repair in recent_completions[:20]:
            if repair.is_part_of_batch:
                if repair.repair_batch_id not in batch_repairs_completed:
                    try:
                        batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            if batch_summary.get('completed_count', 0) == batch_summary.get('break_count', 0):
                                batch_repairs_completed[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
            else:
                individual_repairs_completed.append(repair)

        individual_repairs_completed = individual_repairs_completed[:5]

        summary_stats = {
            'batches_in_progress': len(batch_repairs_in_progress),
            'individual_in_progress': len(individual_repairs_in_progress),
            'pending_approval': len(batch_repairs_approved) + len(individual_repairs_approved),
            'completed_this_week': recent_completions.count(),
            'total_active_work': len(batch_repairs_in_progress) + len(individual_repairs_in_progress) + len(batch_repairs_approved) + len(individual_repairs_approved),
        }
    else:
        # For admins without a technician profile
        customer_requested_repairs = Repair.objects.filter(
            queue_status='REQUESTED'
        ).select_related('customer', 'technician').order_by('-repair_date')

        assigned_redemptions = []
        all_pending_redemptions = RewardRedemption.objects.filter(
            status='PENDING'
        ).order_by('-created_at')

        unread_notifications = None
        batch_repairs_approved = {}
        individual_repairs_approved = []
        batch_repairs_in_progress = {}
        individual_repairs_in_progress = []
        batch_repairs_completed = {}
        individual_repairs_completed = []
        summary_stats = {
            'batches_in_progress': 0,
            'individual_in_progress': 0,
            'pending_approval': 0,
            'completed_this_week': 0,
            'total_active_work': 0,
        }

    # Extra data for admin users
    is_admin = request.user.is_staff
    admin_data = None

    if is_admin:
        admin_data = {
            'total_repairs': Repair.objects.count(),
            'pending_repairs': Repair.objects.filter(queue_status='PENDING').count(),
            'customers': Customer.objects.count(),
            'technicians': Technician.objects.count(),
            'pending_redemptions': RewardRedemption.objects.filter(status='PENDING').count()
        }

    # Get notification bell data
    if technician:
        technician_ct = ContentType.objects.get_for_model(Technician)
        unread_count = Notification.objects.filter(
            recipient_type=technician_ct,
            recipient_id=technician.id,
            read=False
        ).count()
        recent_notifications = Notification.objects.filter(
            recipient_type=technician_ct,
            recipient_id=technician.id
        ).order_by('-created_at')[:5]
    else:
        unread_count = 0
        recent_notifications = []

    return render(request, 'technician_portal/dashboard.html', {
        'technician': technician,
        'customer_requested_repairs': customer_requested_repairs,
        'assigned_redemptions': assigned_redemptions,
        'all_pending_redemptions': all_pending_redemptions,
        'unread_notifications': unread_notifications,
        'unread_count': unread_count,
        'recent_notifications': recent_notifications,
        'batch_repairs_approved': batch_repairs_approved.values() if batch_repairs_approved else [],
        'individual_repairs_approved': individual_repairs_approved,
        'batch_repairs_in_progress': batch_repairs_in_progress.values() if batch_repairs_in_progress else [],
        'individual_repairs_in_progress': individual_repairs_in_progress,
        'batch_repairs_completed': batch_repairs_completed.values() if batch_repairs_completed else [],
        'individual_repairs_completed': individual_repairs_completed,
        'is_admin': is_admin,
        'admin_data': admin_data,
        'summary_stats': summary_stats,
    })
