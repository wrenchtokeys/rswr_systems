from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from .models import Technician, Repair, UnitRepairCount, TechnicianNotification
from core.models import Customer, Notification, TechnicianNotificationPreference
from .forms import TechnicianForm, RepairForm, CustomerForm, TechnicianRegistrationForm, TechnicianNotificationPreferenceForm
from django.db.models import Count, F, Q
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.utils import timezone
from django.http import JsonResponse
from django.db import transaction, models
from datetime import timedelta
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from apps.customer_portal.models import RepairApproval, CustomerUser, CustomerRepairPreference
from apps.rewards_referrals.models import RewardRedemption
from apps.rewards_referrals.services import RewardFulfillmentService
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
import logging
import uuid
from django.core.paginator import Paginator
from functools import wraps
from common.utils import convert_heic_to_jpeg
from .services.batch_pricing_service import calculate_batch_pricing, get_batch_pricing_preview

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Add a helper function to safely check if a user has technician access
def has_technician_access(user):
    """Helper function to check if a user has technician access through profile or admin privileges"""
    # Admin users always have access
    if user.is_staff:
        return True

    # Check if user is in the Technicians group
    if user.groups.filter(name='Technicians').exists():
        return True

    # Non-admin users need a technician profile
    try:
        return hasattr(user, 'technician') and user.technician is not None
    except:
        return False

def is_working_manager(user):
    """
    Helper function to check if a user is a working manager.
    A working manager is someone who:
    1. Has a technician profile AND
    2. Has is_manager=True flag

    This allows them to both assign work AND complete repairs themselves.
    """
    if not hasattr(user, 'technician'):
        return False
    try:
        technician = user.technician
        return technician is not None and technician.is_manager
    except:
        return False

# Custom decorator to ensure only technicians can access views
def technician_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access the technician portal.")
            return redirect('login')
        
        # Check if user has technician access
        if has_technician_access(request.user):
            return view_func(request, *args, **kwargs)
            
        # User doesn't have access
        messages.warning(request, "Your account does not have technician access. Please contact an administrator if you believe this is an error.")
        return redirect('home')
    return _wrapped_view

# Admin required decorator
def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access this feature.")
            return redirect('login')
        
        # Check if user is admin
        if not request.user.is_staff:
            messages.warning(request, "This action requires administrator privileges.")
            return redirect('technician_dashboard')
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def register_technician(request):
    if request.method == 'POST':
        form = TechnicianRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Account created for {user.username}')
            return redirect('admin:index')
    else:
        form = TechnicianRegistrationForm()
    return render(request, 'registration/register_technician.html', {'form': form})

logger = logging.getLogger(__name__)
@technician_required
def technician_dashboard(request):
    # Get technician profile or None for admin users without a profile
    technician = None
    if hasattr(request.user, 'technician'):
        technician = request.user.technician
    
    # Get customer-requested repairs (ONLY for managers)
    if technician:
        # Only MANAGERS can see REQUESTED repairs (for assignment purposes)
        # Regular technicians should NOT see these
        if technician.is_manager:
            customer_requested_repairs = Repair.objects.filter(
                queue_status='REQUESTED'
            ).order_by('-repair_date')
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
        ).order_by('-created_at')[:5]  # Limit to 5 most recent
        
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
        batch_repairs_approved = {}  # Dictionary: batch_id -> batch_summary
        individual_repairs_approved = []  # List of non-batched repairs

        for repair in repairs_recently_approved[:10]:  # Check up to 10 for grouping
            if repair.is_part_of_batch:
                # Only add batch summary once (for the first repair in batch we encounter)
                if repair.repair_batch_id not in batch_repairs_approved:
                    try:
                        batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            batch_repairs_approved[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
                        # Continue gracefully - don't show this batch but don't crash
            else:
                individual_repairs_approved.append(repair)

        # Limit individual repairs to prevent dashboard overflow
        individual_repairs_approved = individual_repairs_approved[:5]

        # Get active work (IN_PROGRESS and APPROVED that aren't in the recently approved section)
        # We need APPROVED repairs here to properly detect batches in progress
        repairs_active = Repair.objects.filter(
            technician=technician,
            queue_status__in=['IN_PROGRESS', 'APPROVED']
        ).select_related('customer').order_by('-repair_date')

        # Group batch repairs and separate individual repairs for active work
        batch_repairs_in_progress = {}  # Dictionary: batch_id -> batch_summary
        individual_repairs_in_progress = []  # List of non-batched repairs (IN_PROGRESS only for display)

        for repair in repairs_active[:30]:  # Check more repairs to find all active batches
            if repair.is_part_of_batch:
                # Only add batch summary once
                if repair.repair_batch_id not in batch_repairs_in_progress:
                    try:
                        batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            # Include batches that have any incomplete work (IN_PROGRESS or APPROVED)
                            # This keeps the batch visible during the transition from starting to completing
                            incomplete_count = batch_summary.get('in_progress_count', 0) + batch_summary.get('approved_count', 0)
                            # Only show if NOT in recently approved section (avoid duplicates)
                            if incomplete_count > 0 and repair.repair_batch_id not in batch_repairs_approved:
                                batch_repairs_in_progress[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
                        # Continue gracefully - don't show this batch but don't crash
            else:
                # Individual repairs that are IN_PROGRESS (not APPROVED, those go in approved section)
                if repair.queue_status == 'IN_PROGRESS':
                    individual_repairs_in_progress.append(repair)

        # Limit individual in-progress repairs
        individual_repairs_in_progress = individual_repairs_in_progress[:5]

        # Get recently completed batch repairs (completed in last 7 days)
        # Note: Using repair_date as proxy for completion since there's no completed_date field
        recent_completions = Repair.objects.filter(
            technician=technician,
            queue_status='COMPLETED',
            repair_date__gte=timezone.now() - timedelta(days=7)
        ).select_related('customer').order_by('-repair_date')

        # Group batch repairs that are completed
        batch_repairs_completed = {}  # Dictionary: batch_id -> batch_summary
        individual_repairs_completed = []  # List of non-batched completed repairs

        for repair in recent_completions[:20]:  # Check up to 20 completed repairs
            if repair.is_part_of_batch:
                # Only add batch summary once
                if repair.repair_batch_id not in batch_repairs_completed:
                    try:
                        batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            # Only show batches where ALL repairs are completed
                            if batch_summary.get('completed_count', 0) == batch_summary.get('break_count', 0):
                                batch_repairs_completed[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
                        # Continue gracefully - don't show this batch but don't crash
            else:
                # Individual completed repairs
                individual_repairs_completed.append(repair)

        # Limit individual completed repairs
        individual_repairs_completed = individual_repairs_completed[:5]

        # Calculate summary statistics for dashboard widgets
        summary_stats = {
            'batches_in_progress': len(batch_repairs_in_progress),
            'individual_in_progress': len(individual_repairs_in_progress),
            'pending_approval': len(batch_repairs_approved) + len(individual_repairs_approved),
            'completed_this_week': recent_completions.count(),  # Actual count from database, not limited display list
            'total_active_work': len(batch_repairs_in_progress) + len(individual_repairs_in_progress) + len(batch_repairs_approved) + len(individual_repairs_approved),
        }
    else:
        # For admins without a technician profile, show all requested repairs (for assignment)
        customer_requested_repairs = Repair.objects.filter(
            queue_status='REQUESTED'
        ).order_by('-repair_date')

        # For admins, show all pending redemptions
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
        # Get data that only admins should see
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

@technician_required
def repair_list(request):
    # For regular technicians, only show their repairs or their team's repairs if they're a manager
    if not request.user.is_staff:
        # Ensure user has a technician profile
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to view repairs.")
            return redirect('technician_dashboard')

        technician = request.user.technician

        # If manager, show their team's repairs + their own + REQUESTED repairs
        if technician.is_manager:
            # Get repairs for managed technicians + own repairs
            managed_tech_ids = list(technician.managed_technicians.values_list('id', flat=True))
            managed_tech_ids.append(technician.id)  # Include own repairs
            repairs = Repair.objects.filter(
                Q(technician_id__in=managed_tech_ids) | Q(queue_status='REQUESTED')
            )
        else:
            # Regular technician - only their own repairs, EXCLUDING REQUESTED and PENDING
            repairs = Repair.objects.filter(
                technician=technician
            ).exclude(queue_status__in=['REQUESTED', 'PENDING'])
    else:
        # For admins, show all repairs
        repairs = Repair.objects.all()
        technician = None

    # Optimize query with select_related and prefetch_related for better performance
    repairs = repairs.select_related('customer', 'technician__user').order_by('-repair_date')

    # Get filter parameters
    customer_search = request.GET.get('customer_search', '')
    status_filter = request.GET.get('status', 'all')
    unit_search = request.GET.get('unit_search', '')
    damage_type_filter = request.GET.get('damage_type', 'all')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    assignment_filter = request.GET.get('assignment', 'all')

    # Apply customer filter if provided
    if customer_search:
        repairs = repairs.filter(customer__name__icontains=customer_search)

    # Apply status filter if provided
    if status_filter != 'all':
        # Support multiple status selection (comma-separated)
        status_list = status_filter.split(',')
        repairs = repairs.filter(queue_status__in=status_list)

    # Apply unit number filter
    if unit_search:
        repairs = repairs.filter(unit_number__icontains=unit_search)

    # Apply damage type filter
    if damage_type_filter != 'all':
        repairs = repairs.filter(damage_type=damage_type_filter)

    # Apply date range filter
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            repairs = repairs.filter(repair_date__gte=date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            repairs = repairs.filter(repair_date__lte=date_to_obj)
        except ValueError:
            pass

    # Apply assignment filter (only for admins/managers)
    if technician and (request.user.is_staff or technician.is_manager):
        if assignment_filter == 'mine':
            repairs = repairs.filter(technician=technician)
        elif assignment_filter == 'unassigned':
            repairs = repairs.filter(technician__isnull=True)
        elif assignment_filter == 'team' and technician.is_manager:
            managed_tech_ids = list(technician.managed_technicians.values_list('id', flat=True))
            repairs = repairs.filter(technician_id__in=managed_tech_ids)

    # Calculate summary statistics
    total_repairs = repairs.count()
    stats = {
        'total_active': repairs.exclude(queue_status='COMPLETED').count(),
        'pending_approval': repairs.filter(queue_status='REQUESTED').count(),
        'in_progress': repairs.filter(queue_status='IN_PROGRESS').count(),
        'completed_this_week': repairs.filter(
            queue_status='COMPLETED',
            repair_date__gte=timezone.now().date() - timezone.timedelta(days=7)
        ).count()
    }

    # Get sorting parameters
    sort_by = request.GET.get('sort', '-repair_date')  # Default: newest first

    # Validate sort field
    valid_sorts = ['repair_date', '-repair_date', 'customer__name', '-customer__name',
                   'unit_number', '-unit_number', 'cost', '-cost', 'queue_status', '-queue_status']
    if sort_by in valid_sorts:
        repairs = repairs.order_by(sort_by)

    # Pagination - get page size from request or use default
    page_size = int(request.GET.get('page_size', 50))
    if page_size not in [20, 50, 100]:
        page_size = 50

    paginator = Paginator(repairs, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Get unique damage types for filter dropdown
    damage_types = Repair.DAMAGE_TYPE_CHOICES

    # Build context
    context = {
        'repairs': page_obj,
        'page_obj': page_obj,
        'total_repairs': total_repairs,
        'stats': stats,
        'customer_search': customer_search,
        'status_filter': status_filter,
        'unit_search': unit_search,
        'damage_type_filter': damage_type_filter,
        'date_from': date_from,
        'date_to': date_to,
        'assignment_filter': assignment_filter,
        'sort_by': sort_by,
        'page_size': page_size,
        'queue_choices': Repair.QUEUE_CHOICES,
        'damage_types': damage_types,
        'is_admin': request.user.is_staff,
        'technician': technician,
    }

    return render(request, 'technician_portal/repair_list.html', context)

@technician_required
def repair_detail(request, repair_id):
    # First get the repair to check its status
    repair = get_object_or_404(Repair, id=repair_id)

    # Initialize permission flags
    can_update_status = False
    can_assign_repair = False
    can_reassign_to_self = False
    technician = None

    # Get technician profile if available
    if hasattr(request.user, 'technician'):
        technician = request.user.technician

        # AUTO-MARK NOTIFICATIONS AS READ when viewing repair (Hybrid approach)
        # Mark any unread notifications about this repair as read when viewed
        unread_notifications = TechnicianNotification.objects.filter(
            technician=technician,
            repair=repair,
            read=False
        )
        if unread_notifications.exists():
            unread_count = unread_notifications.count()
            unread_notifications.update(read=True)
            logger.info(f"Auto-marked {unread_count} notification(s) as read for technician {technician.user.username} viewing repair #{repair.id}")

    # For regular technicians
    if not request.user.is_staff:
        # Ensure user has a technician profile
        if not technician:
            messages.error(request, "You don't have a technician profile to view repairs.")
            return redirect('technician_dashboard')

        # BLOCK all techs from viewing PENDING repairs (customer approval only)
        if repair.queue_status == 'PENDING':
            messages.error(request, "This repair is pending customer approval and cannot be viewed by technicians.")
            return redirect('technician_dashboard')

        # Only MANAGERS can view REQUESTED repairs (for assignment or self-completion)
        if repair.queue_status == 'REQUESTED':
            if not technician.is_manager:
                messages.error(request, "Only managers can view customer-requested repairs.")
                return redirect('technician_dashboard')
            # Working managers can update REQUESTED repairs directly
            can_update_status = True
            can_assign_repair = True
        else:
            # Check if technician can view this repair
            can_view = False

            # Can view own repairs
            if repair.technician == technician:
                can_view = True
                can_update_status = True  # Can update own repairs
            # Managers can view repairs from their managed technicians
            elif technician.is_manager and repair.technician and technician.manages_technician(repair.technician):
                can_view = True
                can_reassign_to_self = True  # Manager can reassign team repair to themselves
            # Special case: viewing from form warning link
            elif '/create/' in request.META.get('HTTP_REFERER', '') or '/update/' in request.META.get('HTTP_REFERER', ''):
                can_view = True

            if not can_view:
                messages.error(request, "You don't have permission to view this repair.")
                return redirect('technician_dashboard')
    else:
        # Admins can do everything
        can_update_status = True
        can_assign_repair = repair.queue_status == 'REQUESTED'

    # Add batch context if this repair is part of a batch
    batch_info = None
    next_break = None
    if repair.is_part_of_batch:
        try:
            batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
            if batch_summary:
                batch_info = batch_summary
                # Find the next break that needs work (not COMPLETED or DENIED)
                # Sort by break_number to ensure correct ordering
                incomplete_repairs = [
                    r for r in sorted(batch_summary['all_repairs'], key=lambda x: x.break_number or 0)
                    if r.queue_status not in ['COMPLETED', 'DENIED'] and r.id != repair.id
                ]
                if incomplete_repairs:
                    next_break = incomplete_repairs[0]  # Get the first incomplete break by break_number
        except Exception as e:
            logger.error(f"Error getting batch summary for repair {repair.id} in batch {repair.repair_batch_id}: {e}", exc_info=True)
            # Continue without batch info - page will still render

    return render(request, 'technician_portal/repair_detail.html', {
        'repair': repair,
        'TIME_ZONE': timezone.get_current_timezone_name(),
        'is_admin': request.user.is_staff,
        'can_update_status': can_update_status,
        'can_assign_repair': can_assign_repair,
        'can_reassign_to_self': can_reassign_to_self,
        'technician': technician,
        'batch_info': batch_info,
        'next_break': next_break,
    })

@technician_required
def technician_batch_detail(request, batch_id):
    """Display all repairs in a batch with batch actions for technician"""
    technician = request.user.technician

    # Get batch summary
    batch_summary = Repair.get_batch_summary(batch_id)

    if not batch_summary:
        messages.error(request, "Batch not found.")
        return redirect('technician_dashboard')

    # Get all repairs in batch (from batch_summary to avoid duplication)
    repairs = batch_summary['all_repairs']

    # Check if technician has access to this batch
    # Technicians can view batches assigned to them or if they're managers
    can_view = False
    can_start_work = False

    if request.user.is_staff:
        can_view = True
        can_start_work = True
    elif technician:
        # Check if any repair in batch is assigned to this technician
        for repair in repairs:
            if repair.technician == technician:
                can_view = True
                # Can start work if repair is APPROVED and not yet started
                if repair.queue_status == 'APPROVED':
                    can_start_work = True
                break

        # Managers can view batches assigned to their team
        if not can_view and technician.is_manager:
            for repair in repairs:
                if repair.technician and technician.manages_technician(repair.technician):
                    can_view = True
                    break

    if not can_view:
        messages.error(request, "You don't have permission to view this batch.")
        return redirect('technician_dashboard')

    # AUTO-MARK batch notifications as read when viewing batch
    if technician:
        unread_batch_notifications = TechnicianNotification.objects.filter(
            technician=technician,
            repair_batch_id=batch_id,
            read=False
        )
        if unread_batch_notifications.exists():
            unread_count = unread_batch_notifications.count()
            unread_batch_notifications.update(read=True)
            logger.info(f"Auto-marked {unread_count} batch notification(s) as read for technician {technician.user.username}")

    return render(request, 'technician_portal/batch_detail.html', {
        'batch_summary': batch_summary,
        'repairs': batch_summary['repairs'],  # Use the repairs from batch_summary to avoid duplication
        'technician': technician,
        'can_start_work': can_start_work,
        'is_admin': request.user.is_staff,
    })

@technician_required
@transaction.atomic
def technician_batch_start_work(request, batch_id):
    """Start work on all repairs in a batch at once"""
    technician = request.user.technician

    # Get batch summary
    batch_summary = Repair.get_batch_summary(batch_id)

    if not batch_summary:
        messages.error(request, "Batch not found.")
        return redirect('technician_dashboard')

    repairs = batch_summary['all_repairs']
    started_count = 0

    # Start work on all APPROVED repairs in the batch
    for repair in repairs:
        if repair.queue_status == 'APPROVED' and repair.technician == technician:
            repair.queue_status = 'IN_PROGRESS'
            repair.save()
            started_count += 1

    if started_count > 0:
        messages.success(
            request,
            f"Started work on {started_count} break{'s' if started_count > 1 else ''} in Unit {batch_summary['unit_number']} batch."
        )
    else:
        messages.warning(request, "No repairs were started. They may already be in progress or not assigned to you.")

    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'started_count': started_count,
            'batch_id': str(batch_id),
        })

    return redirect('technician_batch_detail', batch_id=batch_id)

@technician_required
def create_repair(request):
    if request.method == 'POST':
        # Convert HEIC images to JPEG for browser compatibility
        if 'damage_photo_before' in request.FILES:
            request.FILES['damage_photo_before'] = convert_heic_to_jpeg(request.FILES['damage_photo_before'])
        if 'damage_photo_after' in request.FILES:
            request.FILES['damage_photo_after'] = convert_heic_to_jpeg(request.FILES['damage_photo_after'])

        form = RepairForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            # For admin users, use the selected technician
            if request.user.is_staff:
                if form.cleaned_data.get('technician'):
                    # Set technician before saving
                    repair = form.save(commit=False)
                    repair.technician = form.cleaned_data.get('technician')
                    repair.save()
                    # Save the form to handle file uploads and many-to-many fields
                    form.save_m2m()
                    messages.success(request, f"Repair has been created and assigned to {repair.technician.user.get_full_name()}")
                else:
                    messages.error(request, "As an admin, you must select a technician to assign the repair to.")
                    return render(request, 'technician_portal/repair_form.html', {
                        'form': form,
                        'is_admin': True
                    })
            else:
                # Regular technicians create repairs assigned to themselves
                try:
                    # Set technician before saving
                    repair = form.save(commit=False)
                    repair.technician = request.user.technician

                    # SECURITY: Check customer preferences for ALL tech-created repairs
                    # Technicians cannot bypass approval by setting status to anything other than PENDING
                    # Only customer REQUESTED repairs (created by customers) should skip this check

                    # Force check customer preferences regardless of what status tech tried to set
                    try:
                        preferences = repair.customer.repair_preferences
                        # Check if repair should be auto-approved
                        if preferences.should_auto_approve(repair.technician, repair.repair_date.date() if repair.repair_date else None):
                            repair.queue_status = 'APPROVED'
                            messages.info(request, "Repair auto-approved based on customer preferences.")
                        else:
                            # Force to PENDING - customer must approve
                            # This prevents technicians from setting status to COMPLETED/APPROVED to bypass approval
                            repair.queue_status = 'PENDING'
                            messages.warning(request, "This customer requires approval for field repairs. Repair submitted for customer approval.")
                    except CustomerRepairPreference.DoesNotExist:
                        # No preferences set - default to requiring approval for security
                        repair.queue_status = 'PENDING'
                        messages.warning(request, "Repair submitted for customer approval (customer preferences not configured).")

                    repair.save()
                    # Save the form to handle file uploads and many-to-many fields
                    form.save_m2m()
                except AttributeError:
                    messages.error(request, "You don't have a technician profile to create repairs.")
                    return redirect('technician_dashboard')

            # Add success message
            messages.success(request, f'Repair #{repair.id} created successfully!')

            return redirect('repair_detail', repair_id=repair.id)
        else:
            logger.debug(f"Form errors: {form.errors}")
            # Add form errors to messages so user can see them
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        # Create a form with the current user
        form = RepairForm(user=request.user)
    
    pending_repair_warning = form.errors.get('__all__')

    # Calculate expected cost for the template if we have customer/unit info
    expected_cost = None
    if hasattr(form, 'instance') and form.instance.customer and form.instance.unit_number:
        expected_cost = form.instance.get_expected_price()

    return render(request, 'technician_portal/repair_form.html', {
        'form': form,
        'pending_repair_warning': pending_repair_warning,
        'is_admin': request.user.is_staff,
        'expected_cost': expected_cost
    })


@technician_required
def create_multi_break_repair(request):
    """
    View for creating multiple repairs (breaks) on the same unit in one session.
    Uses modal-based interface with progressive pricing calculation.
    """
    logger = logging.getLogger(__name__)

    if request.method == 'POST':
        try:
            # Extract base information
            customer_id = request.POST.get('customer')
            unit_number = request.POST.get('unit_number')
            repair_date_str = request.POST.get('repair_date')
            breaks_count = int(request.POST.get('breaks_count', 0))

            # DIAGNOSTIC: Log incoming request
            logger.info(f"[MULTI-BREAK] Request received - customer_id={customer_id}, unit={unit_number}, date={repair_date_str}, breaks={breaks_count}")

            # Validate required fields
            if not all([customer_id, unit_number, repair_date_str, breaks_count > 0]):
                error_msg = "Missing required information. Please ensure you've added at least one break."
                logger.warning(f"[MULTI-BREAK] Validation failed - customer_id={customer_id}, unit={unit_number}, date={repair_date_str}, breaks={breaks_count}")
                messages.error(request, error_msg)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                return redirect('create_multi_break_repair')

            # Get customer and validate
            try:
                customer = Customer.objects.get(id=customer_id)
                logger.info(f"[MULTI-BREAK] Customer found: {customer.name} (ID: {customer.id})")
            except Customer.DoesNotExist:
                error_msg = f"Invalid customer selected (ID: {customer_id})."
                logger.error(f"[MULTI-BREAK] Customer not found - ID={customer_id}")
                messages.error(request, error_msg)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                return redirect('create_multi_break_repair')

            # Parse repair date
            try:
                repair_date = timezone.datetime.fromisoformat(repair_date_str.replace('Z', '+00:00'))
                logger.info(f"[MULTI-BREAK] Repair date parsed: {repair_date}")
            except (ValueError, AttributeError) as date_error:
                error_msg = f"Invalid date format: {repair_date_str}. Error: {str(date_error)}"
                logger.error(f"[MULTI-BREAK] Date parsing failed - date_str={repair_date_str}, error={date_error}")
                messages.error(request, error_msg)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                return redirect('create_multi_break_repair')

            # Get current repair count for pricing calculation
            try:
                unit_count = UnitRepairCount.objects.get(customer=customer, unit_number=unit_number)
                base_repair_count = unit_count.repair_count
            except UnitRepairCount.DoesNotExist:
                base_repair_count = 0

            # Calculate pricing for all breaks
            pricing_breakdown = calculate_batch_pricing(customer, unit_number, breaks_count)

            # Generate batch ID for linking all repairs
            batch_id = uuid.uuid4()
            created_repairs = []

            # Determine technician
            if request.user.is_staff:
                # Admin must provide technician
                tech_id = request.POST.get('technician_id')
                if not tech_id:
                    messages.error(request, "As an admin, you must select a technician.")
                    return redirect('create_multi_break_repair')
                try:
                    technician = Technician.objects.get(id=tech_id)
                except Technician.DoesNotExist:
                    messages.error(request, "Invalid technician selected.")
                    return redirect('create_multi_break_repair')
            else:
                # Regular technician creates repairs for themselves
                try:
                    technician = request.user.technician
                except AttributeError:
                    messages.error(request, "You don't have a technician profile to create repairs.")
                    return redirect('technician_dashboard')

            # Create all repairs atomically (all or nothing)
            logger.info(f"[MULTI-BREAK] Starting atomic transaction for {breaks_count} breaks")
            with transaction.atomic():
                for i in range(breaks_count):
                    # Extract data for this break
                    damage_type = request.POST.get(f'breaks[{i}][damage_type]', '')
                    notes = request.POST.get(f'breaks[{i}][notes]', '')

                    # DIAGNOSTIC: Log break data
                    logger.debug(f"[MULTI-BREAK] Break {i+1}/{breaks_count} - damage_type='{damage_type}', notes_length={len(notes)}")

                    # Validate damage_type is not empty
                    if not damage_type or damage_type.strip() == '':
                        error_msg = f"Break {i+1} is missing damage type. All breaks must have a damage type selected."
                        logger.error(f"[MULTI-BREAK] Validation failed - Break {i+1} has empty damage_type")
                        messages.error(request, error_msg)
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': error_msg}, status=400)
                        return redirect('create_multi_break_repair')

                    # Extract technical fields
                    drilled_before = request.POST.get(f'breaks[{i}][drilled_before_repair]', 'false').lower() == 'true'
                    windshield_temp = request.POST.get(f'breaks[{i}][windshield_temperature]', '')
                    resin_viscosity = request.POST.get(f'breaks[{i}][resin_viscosity]', '')

                    # Extract manager override fields
                    cost_override = request.POST.get(f'breaks[{i}][cost_override]', '')
                    override_reason = request.POST.get(f'breaks[{i}][override_reason]', '')

                    # Handle photo uploads
                    photo_before_key = f'breaks[{i}][photo_before]'
                    photo_after_key = f'breaks[{i}][photo_after]'

                    photo_before = request.FILES.get(photo_before_key)
                    photo_after = request.FILES.get(photo_after_key)

                    # Convert HEIC to JPEG if needed
                    if photo_before:
                        photo_before = convert_heic_to_jpeg(photo_before)
                    if photo_after:
                        photo_after = convert_heic_to_jpeg(photo_after)

                    # Get pricing for this break from precalculated breakdown
                    break_price = pricing_breakdown[i]['price']

                    # Handle manager price override
                    if cost_override:
                        try:
                            override_amount = Decimal(cost_override)

                            # Validate manager authorization
                            if not (technician.is_manager and technician.can_override_pricing):
                                messages.error(request, f"Break {i+1}: You don't have permission to override prices.")
                                return redirect('create_multi_break_repair')

                            # Require override reason
                            if not override_reason:
                                messages.error(request, f"Break {i+1}: Override reason is required when setting a custom price.")
                                return redirect('create_multi_break_repair')

                            # Check approval limit if set
                            if technician.approval_limit and override_amount > technician.approval_limit:
                                messages.error(
                                    request,
                                    f"Break {i+1}: Override amount ${override_amount} exceeds your approval limit of ${technician.approval_limit}."
                                )
                                return redirect('create_multi_break_repair')

                            # Use override price
                            break_price = override_amount

                        except (ValueError, InvalidOperation):
                            messages.error(request, f"Break {i+1}: Invalid override price format.")
                            return redirect('create_multi_break_repair')

                    # Create repair instance
                    repair = Repair(
                        technician=technician,
                        customer=customer,
                        unit_number=unit_number,
                        repair_date=repair_date,
                        damage_type=damage_type,
                        drilled_before_repair=drilled_before,
                        windshield_temperature=Decimal(windshield_temp) if windshield_temp else None,
                        resin_viscosity=resin_viscosity,  # CharField, use empty string not None
                        technician_notes=notes,
                        damage_photo_before=photo_before,
                        damage_photo_after=photo_after,
                        cost_override=Decimal(cost_override) if cost_override else None,
                        override_reason=override_reason,  # CharField, use empty string not None
                        repair_batch_id=batch_id,
                        break_number=i + 1,
                        total_breaks_in_batch=breaks_count,
                        cost=break_price,
                        queue_status='PENDING'
                    )

                    # Check customer preferences for auto-approval
                    try:
                        preferences = customer.repair_preferences
                        if preferences.should_auto_approve(technician, repair_date.date() if repair_date else None):
                            repair.queue_status = 'APPROVED'
                    except CustomerRepairPreference.DoesNotExist:
                        pass  # Stay as PENDING

                    try:
                        repair.save()
                        created_repairs.append(repair)
                        logger.info(f"[MULTI-BREAK] Created repair {repair.id} - Break {i+1}/{breaks_count} in batch {batch_id}, cost=${repair.cost}")
                    except Exception as save_error:
                        error_msg = f"Failed to save Break {i+1}: {str(save_error)}"
                        logger.error(f"[MULTI-BREAK] Repair.save() failed for break {i+1} - error={save_error}", exc_info=True)
                        messages.error(request, error_msg)
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': error_msg}, status=500)
                        raise  # Re-raise to trigger transaction rollback

            # Calculate total cost for message
            total_cost = sum(r.cost for r in created_repairs)
            logger.info(f"[MULTI-BREAK] Transaction complete - {len(created_repairs)} repairs created, total_cost=${total_cost}")

            # Determine status for response
            status = created_repairs[0].queue_status
            is_auto_approved = status == 'APPROVED'

            # Success message
            if is_auto_approved:
                messages.success(
                    request,
                    f"Successfully created {len(created_repairs)} repairs for Unit {unit_number} "
                    f"(${total_cost:.2f} total). Auto-approved based on customer preferences."
                )
            else:
                messages.success(
                    request,
                    f"Successfully created {len(created_repairs)} repairs for Unit {unit_number} "
                    f"(${total_cost:.2f} total). Submitted for customer approval."
                )

            # Return JSON for AJAX requests, redirect for regular form submissions
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'batch_id': str(batch_id),
                    'unit_number': unit_number,
                    'break_count': len(created_repairs),
                    'total_cost': float(total_cost),
                    'status': status,
                    'is_auto_approved': is_auto_approved,
                    'message': f"Successfully created {len(created_repairs)} repairs for Unit {unit_number}",
                })

            # Redirect to repair list filtered by this customer (fallback for non-AJAX)
            return redirect(f"{'/tech/repairs/'}?customer={customer.name}")

        except ValueError as e:
            error_detail = str(e)
            logger.error(f"[MULTI-BREAK] ValueError in batch creation: {error_detail}", exc_info=True)
            messages.error(request, f"Invalid data provided: {error_detail}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f"Invalid data: {error_detail}",
                    'error_type': 'ValueError'
                }, status=400)
            return redirect('create_multi_break_repair')

        except Exception as e:
            error_detail = str(e)
            error_type = type(e).__name__
            logger.error(f"[MULTI-BREAK] {error_type} in batch creation: {error_detail}", exc_info=True)
            messages.error(request, f"Error creating repairs: {error_detail}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f"{error_type}: {error_detail}",
                    'error_type': error_type
                }, status=500)
            return redirect('create_multi_break_repair')

    else:
        # GET request - show the form
        return render(request, 'technician_portal/multi_break_repair_form.html', {
            'is_admin': request.user.is_staff,
            'customers': Customer.objects.all().order_by('name'),
            'damage_types': Repair.DAMAGE_TYPE_CHOICES,
        })


@technician_required
@transaction.atomic
def convert_to_batch(request, repair_id):
    """Convert a single repair into a multi-break batch by adding additional breaks"""
    logger = logging.getLogger(__name__)

    # Get the original repair
    original_repair = get_object_or_404(Repair, id=repair_id)

    # Security: Check if user has permission to modify this repair
    if not request.user.is_staff:
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have permission to modify this repair.")
            return redirect('repair_detail', repair_id=repair_id)

        if original_repair.technician_id != request.user.technician.id:
            messages.error(request, "You can only modify repairs assigned to you.")
            return redirect('repair_detail', repair_id=repair_id)

    # Check if repair is already part of a batch
    if original_repair.repair_batch_id:
        messages.error(request, "This repair is already part of a batch.")
        return redirect('technician_batch_detail', batch_id=original_repair.repair_batch_id)

    # Check if repair status allows conversion
    if original_repair.queue_status not in ['APPROVED', 'IN_PROGRESS']:
        messages.error(request, "Only approved or in-progress repairs can be converted to batches.")
        return redirect('repair_detail', repair_id=repair_id)

    if request.method == 'POST':
        try:
            # Get form data
            additional_breaks = int(request.POST.get('additional_breaks', 0))

            if additional_breaks < 1:
                messages.error(request, "You must add at least 1 additional break.")
                return redirect('convert_to_batch', repair_id=repair_id)

            # Generate batch ID
            batch_id = uuid.uuid4()
            total_breaks_in_batch = 1 + additional_breaks

            # Update the original repair to be part of the batch
            original_repair.repair_batch_id = batch_id
            original_repair.break_number = 1
            original_repair.total_breaks_in_batch = total_breaks_in_batch
            original_repair.save()

            logger.info(f"Converted repair {repair_id} to batch {batch_id}, adding {additional_breaks} breaks")

            # Get current repair count for progressive pricing
            unit_count = UnitRepairCount.objects.get_or_create(
                customer=original_repair.customer,
                unit_number=original_repair.unit_number
            )[0]
            starting_count = unit_count.repair_count

            # Create additional repairs
            created_repairs = [original_repair]

            for i in range(additional_breaks):
                break_number = i + 2  # Starting from 2 since original is 1
                repair_count_for_this_break = starting_count + break_number

                # Get damage type
                damage_type = request.POST.get(f'damage_type_{i}')
                if not damage_type:
                    raise ValueError(f"Damage type is required for break {break_number}")

                # Calculate cost for this break
                from apps.technician_portal.services import pricing_service
                cost = pricing_service.calculate_repair_cost(
                    original_repair.customer,
                    repair_count_for_this_break
                )

                # Handle manager price override
                override_cost = request.POST.get(f'override_cost_{i}')
                override_reason = request.POST.get(f'override_reason_{i}')

                if override_cost:
                    try:
                        override_cost_decimal = Decimal(override_cost)

                        # Validate manager authorization
                        if request.user.is_staff:
                            cost = override_cost_decimal
                        elif hasattr(request.user, 'technician') and request.user.technician.is_manager:
                            if override_cost_decimal <= request.user.technician.approval_limit:
                                cost = override_cost_decimal
                            else:
                                raise ValueError(f"Override amount ${override_cost} exceeds your approval limit")
                        else:
                            raise ValueError("Only managers can override prices")

                        if not override_reason:
                            raise ValueError("Override reason is required when overriding price")

                    except (InvalidOperation, ValueError) as e:
                        raise ValueError(f"Invalid override cost for break {break_number}: {str(e)}")

                # Create the new repair
                new_repair = Repair(
                    customer=original_repair.customer,
                    unit_number=original_repair.unit_number,
                    technician=original_repair.technician,
                    damage_type=damage_type,
                    repair_date=original_repair.repair_date,
                    cost=cost,
                    queue_status=original_repair.queue_status,
                    repair_batch_id=batch_id,
                    break_number=break_number,
                    total_breaks_in_batch=total_breaks_in_batch,
                    technician_notes=request.POST.get(f'notes_{i}', ''),
                    windshield_temperature=request.POST.get(f'windshield_temperature_{i}') or None,
                    resin_viscosity=request.POST.get(f'resin_viscosity_{i}') or None,
                    drilled_before_repair=request.POST.get(f'drilled_before_repair_{i}') == 'on',
                    override_reason=override_reason if override_cost else None,
                )

                # Handle photo uploads
                photo_before = request.FILES.get(f'photo_before_{i}')
                photo_after = request.FILES.get(f'photo_after_{i}')

                if photo_before:
                    new_repair.damage_photo_before = convert_heic_to_jpeg(photo_before)
                if photo_after:
                    new_repair.damage_photo_after = convert_heic_to_jpeg(photo_after)

                new_repair.save()
                created_repairs.append(new_repair)

                # Increment unit repair count
                unit_count.repair_count += 1
                unit_count.save()

                logger.info(f"Created additional repair {new_repair.id} - Break {break_number}/{total_breaks_in_batch}")

            # Calculate total cost
            total_cost = sum(r.cost for r in created_repairs)

            messages.success(
                request,
                f"Successfully converted to batch! Added {additional_breaks} break{'s' if additional_breaks > 1 else ''} "
                f"to Unit {original_repair.unit_number} (${total_cost:.2f} total)."
            )

            # Redirect to batch detail
            return redirect('technician_batch_detail', batch_id=batch_id)

        except ValueError as e:
            logger.error(f"Value error in convert_to_batch: {e}")
            messages.error(request, f"Invalid data: {str(e)}")
            return redirect('convert_to_batch', repair_id=repair_id)

        except Exception as e:
            logger.error(f"Error converting to batch: {e}", exc_info=True)
            messages.error(request, f"Error converting to batch: {str(e)}")
            return redirect('convert_to_batch', repair_id=repair_id)

    else:
        # GET request - show the form
        return render(request, 'technician_portal/convert_to_batch_form.html', {
            'repair': original_repair,
            'damage_types': Repair.DAMAGE_TYPE_CHOICES,
            'is_admin': request.user.is_staff,
        })


@technician_required
def get_batch_pricing_json(request):
    """
    AJAX endpoint for getting pricing preview for multi-break batches.
    Returns JSON with pricing breakdown for frontend display.
    """
    customer_id = request.GET.get('customer_id')
    unit_number = request.GET.get('unit_number')
    breaks_count = request.GET.get('breaks_count')

    if not all([customer_id, unit_number, breaks_count]):
        return JsonResponse({'error': 'Missing required parameters'}, status=400)

    try:
        breaks_count = int(breaks_count)
        if breaks_count < 1 or breaks_count > 20:
            return JsonResponse({'error': 'Breaks count must be between 1 and 20'}, status=400)

        pricing_data = get_batch_pricing_preview(int(customer_id), unit_number, breaks_count)

        if pricing_data is None:
            return JsonResponse({'error': 'Customer not found'}, status=404)

        return JsonResponse(pricing_data)

    except ValueError:
        return JsonResponse({'error': 'Invalid parameters'}, status=400)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error calculating batch pricing: {e}")
        return JsonResponse({'error': 'Server error calculating pricing'}, status=500)


@technician_required
def get_viscosity_suggestion(request):
    """
    API endpoint to get viscosity recommendation based on temperature.
    GET /tech/api/viscosity-suggestion/?temperature=72.5

    Returns JSON:
    {
        "recommendation": "Medium",
        "suggestion_text": "Medium viscosity recommended for optimal conditions",
        "badge_color": "green"
    }
    """
    from .models import ViscosityRecommendation
    import logging
    logger = logging.getLogger(__name__)

    temperature = request.GET.get('temperature')

    if not temperature:
        return JsonResponse({'error': 'Temperature parameter is required'}, status=400)

    try:
        # Convert to float for validation
        temp_value = float(temperature)

        # Get recommendation using the model's class method
        recommendation = ViscosityRecommendation.get_recommendation_for_temperature(temp_value)

        if recommendation:
            return JsonResponse({
                'success': True,
                'recommendation': recommendation['recommendation'],
                'suggestion_text': recommendation['suggestion_text'],
                'badge_color': recommendation['badge_color'],
            })
        else:
            # No matching rule found
            return JsonResponse({
                'success': True,
                'recommendation': None,
                'suggestion_text': 'No recommendation available for this temperature',
                'badge_color': 'gray',
            })

    except ValueError:
        logger.warning(f"Invalid temperature value: {temperature}")
        return JsonResponse({'error': 'Invalid temperature value'}, status=400)
    except Exception as e:
        logger.error(f"Error getting viscosity suggestion: {e}", exc_info=True)
        return JsonResponse({'error': 'Server error getting viscosity suggestion'}, status=500)


@technician_required
def update_repair(request, repair_id):
    logger = logging.getLogger(__name__)

    # For regular technicians, they can only edit their own repairs
    if not request.user.is_staff:
        # Ensure user has a technician profile
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to manage repairs.")
            return redirect('technician_dashboard')

        # First get the repair WITHOUT filtering by technician (to avoid crash on NULL technician)
        repair = get_object_or_404(Repair, id=repair_id)
        logger.info(f"UPDATE_REPAIR: Got repair #{repair.id}, technician_id={repair.technician_id}")

        # SECURITY: Check if repair is in a final/locked state
        # Allow managers to edit photos on completed repairs (for adding missing photos)
        # Regular technicians cannot edit completed/denied repairs
        user_is_manager = request.user.technician.is_manager if hasattr(request.user, 'technician') else False
        if repair.queue_status in ['COMPLETED', 'DENIED'] and not user_is_manager:
            messages.error(request, "This repair is closed and cannot be edited. Contact a manager if photos need to be added.")
            return redirect('repair_detail', repair_id=repair.id)

        # SECURITY: Check if technician is assigned to this repair
        # Customer-submitted repairs (REQUESTED) have no technician yet - block editing
        # Use technician_id to avoid RelatedObjectDoesNotExist error
        if not repair.technician_id:
            messages.error(request, "This repair has not been assigned yet and cannot be edited by technicians.")
            return redirect('repair_detail', repair_id=repair.id)

        # SECURITY: Only allow editing own repairs
        if repair.technician_id != request.user.technician.id:
            messages.error(request, "You can only edit repairs assigned to you.")
            return redirect('repair_detail', repair_id=repair.id)
    else:
        # Admins can edit any repair
        repair = get_object_or_404(Repair, id=repair_id)
    
    if request.method == 'POST':
        logger.info(f"UPDATE_REPAIR POST: Processing form for repair #{repair.id}")

        # Convert HEIC images to JPEG for browser compatibility
        if 'damage_photo_before' in request.FILES:
            request.FILES['damage_photo_before'] = convert_heic_to_jpeg(request.FILES['damage_photo_before'])
        if 'damage_photo_after' in request.FILES:
            request.FILES['damage_photo_after'] = convert_heic_to_jpeg(request.FILES['damage_photo_after'])

        # CRITICAL FIX: Save the technician_id BEFORE creating the form
        # because form.save(commit=False) will modify the original instance
        original_technician_id = repair.technician_id
        logger.info(f"UPDATE_REPAIR: Saved original_technician_id={original_technician_id}")

        form = RepairForm(request.POST, request.FILES, instance=repair, user=request.user)
        if form.is_valid():
            logger.info(f"UPDATE_REPAIR: Form is valid, calling save(commit=False)")
            updated_repair = form.save(commit=False)
            logger.info(f"UPDATE_REPAIR: After form.save(), updated_repair.technician_id={updated_repair.technician_id}")

            # Handle photo deletion
            for field_name in ['damage_photo_before', 'damage_photo_after']:
                delete_flag = request.POST.get(f'{field_name}-DELETE')
                if delete_flag == 'true':
                    # Delete the photo if it exists
                    current_photo = getattr(updated_repair, field_name)
                    if current_photo:
                        current_photo.delete(save=False)  # Delete the file
                        setattr(updated_repair, field_name, None)  # Clear the field

            # For non-admin users, preserve the existing technician (form hides this field)
            if not request.user.is_staff:
                # CRITICAL FIX: form.save(commit=False) sets technician to NULL when field is hidden
                # We must restore the original technician_id that we saved before creating the form
                logger.info(f"UPDATE_REPAIR: Restoring technician_id from original_technician_id={original_technician_id}")
                updated_repair.technician_id = original_technician_id
                logger.info(f"UPDATE_REPAIR: Set updated_repair.technician_id={updated_repair.technician_id}")
            # For admin users, update the technician if changed
            elif form.cleaned_data.get('technician'):
                updated_repair.technician = form.cleaned_data.get('technician')

            # AUTO-COMPLETE: If repair is IN_PROGRESS and has after photo, automatically mark as COMPLETED
            # This ensures batch progress tracking works correctly
            if updated_repair.queue_status == 'IN_PROGRESS' and updated_repair.damage_photo_after:
                updated_repair.queue_status = 'COMPLETED'
                logger.info(f"UPDATE_REPAIR: Auto-completing repair #{updated_repair.id} (has after photo)")
                messages.success(request, "Repair marked as COMPLETED! (After photo uploaded)")

            # Save the repair with all form data including uploaded files
            logger.info(f"UPDATE_REPAIR: About to save repair, technician_id={updated_repair.technician_id}")
            updated_repair.save()
            logger.info(f"UPDATE_REPAIR: Save successful!")
            # Also save many-to-many fields if any exist
            form.save_m2m()

            messages.success(request, "Repair has been updated successfully.")

            # BATCH NAVIGATION: If this repair is part of a batch, show repair detail with navigation options
            # This allows technician to see completion status and choose to continue to next break
            if updated_repair.repair_batch_id:
                # Check if all breaks are complete
                batch_summary = Repair.get_batch_summary(updated_repair.repair_batch_id)
                if batch_summary and batch_summary['completed_count'] == batch_summary['break_count']:
                    messages.success(request, "All breaks in this batch are complete!")

                # Always go to repair_detail which shows "Next Break" button if available
                return redirect('repair_detail', repair_id=updated_repair.id)

            return redirect('repair_detail', repair_id=repair.id)
        else:
            # FORM VALIDATION FAILED - ensure error messages are clear
            logger.warning(f"UPDATE_REPAIR: Form validation failed for repair #{repair.id}. Errors: {form.errors}")
            logger.warning(f"UPDATE_REPAIR: Form data - customer: {request.POST.get('customer')}, unit_number: {request.POST.get('unit_number')}, status: {request.POST.get('queue_status')}")

            # Log photo field states for debugging
            logger.warning(f"UPDATE_REPAIR: Photo states - damage_photo_before in FILES: {'damage_photo_before' in request.FILES}, damage_photo_after in FILES: {'damage_photo_after' in request.FILES}")
            logger.warning(f"UPDATE_REPAIR: Instance has existing photos - before: {bool(repair.damage_photo_before)}, after: {bool(repair.damage_photo_after)}")

            # Add a user-friendly message about what went wrong
            if form.errors:
                # Show specific error messages for each field
                for field, errors in form.errors.items():
                    for error in errors:
                        if field == '__all__':
                            messages.error(request, str(error))
                        else:
                            messages.error(request, f"{field.replace('_', ' ').title()}: {error}")

            # CRITICAL: Ensure the form instance still has the original repair data
            # This prevents fields from being reset when validation fails
            # The form is already bound with POST data, so it will show the submitted values
            # But we need to ensure the instance maintains its original values for reference
    else:
        form = RepairForm(instance=repair, user=request.user)

        # Inform managers/admins when editing completed repairs (for photo additions)
        if repair.queue_status == 'COMPLETED':
            user_is_manager = (request.user.is_staff or
                             (hasattr(request.user, 'technician') and request.user.technician.is_manager))
            if user_is_manager:
                messages.info(request, "You're editing a completed repair. You can add or update photos for documentation/AI training purposes.")

    # Calculate expected cost for the template
    expected_cost = repair.get_expected_price() if repair.customer and repair.unit_number else None

    # BATCH CONTEXT: Check if we're editing from batch detail page
    # Check both GET (initial load) and POST (after form submission) for batch_id
    batch_id = request.GET.get('batch_id') or request.POST.get('batch_id')
    batch_repairs = []
    if batch_id and repair.repair_batch_id:
        # Get all repairs in this batch for navigation
        batch_repairs = Repair.objects.filter(
            repair_batch_id=repair.repair_batch_id
        ).order_by('break_number')

    return render(request, 'technician_portal/repair_form.html', {
        'form': form,
        'repair': repair,
        'is_admin': request.user.is_staff,
        'expected_cost': expected_cost,
        'batch_id': batch_id,
        'batch_repairs': batch_repairs,
    })

@technician_required
def update_queue_status(request, repair_id):
    # First get the repair to check its status
    repair = get_object_or_404(Repair, id=repair_id)
    
    # For regular technicians
    if not request.user.is_staff:
        # Ensure user has a technician profile
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to update repairs.")
            return redirect('technician_dashboard')

        technician = request.user.technician

        # BLOCK all techs from PENDING repairs (customer approval only)
        if repair.queue_status == 'PENDING':
            messages.error(request, "This repair is pending customer approval. Technicians cannot modify it.")
            return redirect('technician_dashboard')

        # Only MANAGERS can handle REQUESTED repairs
        # Working managers can update REQUESTED repairs directly (auto-assigns to them)
        if repair.queue_status == 'REQUESTED':
            if not technician.is_manager:
                messages.error(request, "Only managers can assign customer-requested repairs.")
                return redirect('technician_dashboard')
            # If manager is updating a REQUESTED repair, allow it (will auto-assign to manager)
        else:
            # Check if technician can update this repair
            can_update = False

            # Can update own repairs (assigned to them)
            if repair.technician == technician:
                can_update = True
            # Managers can only update team repairs if they've been reassigned to the manager
            # They cannot directly modify repairs assigned to other team members
            elif technician.is_manager and repair.technician and technician.manages_technician(repair.technician):
                # If repair is assigned to a team member (not the manager), block modification
                messages.error(request, "You cannot modify repairs assigned to other technicians. Use the reassign feature to take over this repair.")
                return redirect('repair_detail', repair_id=repair.id)

            if not can_update:
                messages.error(request, "You don't have permission to update this repair.")
                return redirect('technician_dashboard')
    # else: Admins can update any repair (no additional check needed)
        
    old_status = repair.queue_status
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Repair.QUEUE_CHOICES):
            # Special handling for customer-requested repairs
            if old_status == 'REQUESTED':
                # Auto-assign to the manager who is accepting the repair
                if not request.user.is_staff and hasattr(request.user, 'technician'):
                    repair.technician = request.user.technician
                    messages.info(request, f"Repair assigned to you.")

                # Update status
                repair.queue_status = new_status
                repair.save()

                # Create an automatic approval record since the customer already implicitly approved it

                # Find the customer user who would be the primary contact
                customer_users = CustomerUser.objects.filter(customer=repair.customer)
                customer_user = customer_users.filter(is_primary_contact=True).first()
                if not customer_user and customer_users.exists():
                    customer_user = customer_users.first()

                if customer_user:
                    # Create an approval record
                    RepairApproval.objects.create(
                        repair=repair,
                        approved=True,
                        approved_by=customer_user,
                        approval_date=timezone.now(),
                        notes="Auto-approved as customer initiated the request"
                    )

                messages.success(request, f"Repair request has been accepted and added to your schedule. The customer has been notified.")
            else:
                repair.queue_status = new_status
                # Auto-update repair date when marking as completed
                if new_status == 'COMPLETED':
                    repair.repair_date = timezone.now()

                    # Handle price override if provided
                    cost_override = request.POST.get('cost_override')
                    override_reason = request.POST.get('override_reason')

                    if cost_override:
                        try:
                            repair.cost_override = float(cost_override)
                            repair.override_reason = override_reason or "Manual price adjustment"
                            messages.info(request, f"Custom price of ${cost_override} has been applied.")
                        except (ValueError, TypeError):
                            messages.warning(request, "Invalid custom price. Using automatic pricing.")

                repair.save()

                # AUTO-CLEANUP: Mark notifications as read when repair is completed
                if new_status == 'COMPLETED' and repair.technician:
                    # Mark all notifications related to this repair as read for the assigned technician
                    completed_notifications = TechnicianNotification.objects.filter(
                        technician=repair.technician,
                        repair=repair,
                        read=False
                    )
                    if completed_notifications.exists():
                        completed_count = completed_notifications.count()
                        completed_notifications.update(read=True)
                        logger.info(f"Auto-marked {completed_count} notification(s) as read for technician {repair.technician.user.username} after completing repair #{repair.id}")

                messages.success(request, f"Repair status updated to {repair.get_queue_status_display()}")

    return redirect('repair_detail', repair_id=repair.id)

@technician_required
def update_technician_profile(request):
    technician = get_object_or_404(Technician, user=request.user)

    if request.method == 'POST':
        form = TechnicianForm(request.POST, user=request.user, technician=technician)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')

            # If password was changed, update session to prevent logout
            if form.cleaned_data.get('password1'):
                update_session_auth_hash(request, request.user)
                messages.info(request, 'Your password has been changed successfully.')

            return redirect('technician_dashboard')
    else:
        form = TechnicianForm(user=request.user, technician=technician)

    return render(request, 'technician_portal/update_profile.html', {
        'form': form,
        'technician': technician
    })

@admin_required
def create_customer(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            messages.success(request, f"Customer '{customer.name}' has been created successfully.")
            return redirect('technician_dashboard')
    else:
        form = CustomerForm()
    return render(request, 'technician_portal/customer_form.html', {'form': form})

@technician_required
def customer_list(request):
    """View to list all customers that a technician can access"""
    if request.user.is_staff:
        # Admin can see all customers
        customers = Customer.objects.all().order_by('name')
    else:
        # Regular technicians can only see customers with repairs assigned to them
        if hasattr(request.user, 'technician'):
            technician = request.user.technician
            # Get customer IDs from repairs assigned to this technician
            customer_ids = Repair.objects.filter(technician=technician).values_list('customer_id', flat=True).distinct()
            customers = Customer.objects.filter(id__in=customer_ids).order_by('name')
        else:
            customers = Customer.objects.none()
    
    # Handle search
    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) | 
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # Annotate each customer with active repairs count
    for customer in customers:
        active_repairs = Repair.objects.filter(
            customer=customer
        ).exclude(
            queue_status='COMPLETED'
        ).count()
        customer.active_repairs_count = active_repairs
    
    return render(request, 'technician_portal/customer_list.html', {
        'customers': customers,
        'search_query': search_query,
        'is_admin': request.user.is_staff
    })

@technician_required
def customer_details(request, customer_id):
    technician = get_object_or_404(Technician, user=request.user)
    customer = get_object_or_404(Customer, id=customer_id)

    # Only show repairs assigned to this technician, exclude REQUESTED and PENDING
    repairs = Repair.objects.filter(
        technician=technician,
        customer=customer
    ).exclude(queue_status__in=['REQUESTED', 'PENDING'])

    unit_search = request.GET.get('unit_search', '')
    if unit_search:
        repairs = repairs.filter(unit_number__icontains=unit_search)

    units = repairs.values_list('unit_number', flat=True).distinct()

    return render(request, 'technician_portal/customer_details.html', {
        'customer': customer,
        'units': units,
        'unit_search': unit_search,
    })

@technician_required
def unit_details(request, customer_id, unit_number):
    technician = get_object_or_404(Technician, user=request.user)
    customer = get_object_or_404(Customer, id=customer_id)

    # Only show repairs assigned to this technician, exclude REQUESTED and PENDING
    repairs = Repair.objects.filter(
        technician=technician,
        customer=customer,
        unit_number=unit_number
    ).exclude(queue_status__in=['REQUESTED', 'PENDING'])

    return render(request, 'technician_portal/unit_details.html', {
        'customer': customer,
        'unit_number': unit_number,
        'repairs': repairs,
    })

@technician_required
def mark_unit_replaced(request, customer_id, unit_number):
    customer = get_object_or_404(Customer, id=customer_id)
    unit_repair_count = get_object_or_404(UnitRepairCount, customer=customer, unit_number=unit_number)
    unit_repair_count.repair_count = 0
    unit_repair_count.save()
    messages.success(request, f"Unit #{unit_number} for {customer.name} has been marked as replaced. Repair count reset to 0.")
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
def check_existing_repair(request):
    customer_id = request.GET.get('customer')
    unit_number = request.GET.get('unit_number')
    existing_repair = Repair.objects.filter(
        customer_id=customer_id,
        unit_number=unit_number,
        queue_status__in=['PENDING', 'APPROVED', 'IN_PROGRESS']
    ).first()
    
    if existing_repair:
        return JsonResponse({
            'existing_repair': True,
            'status': existing_repair.get_queue_status_display(),
            'repair_id': existing_repair.id,
            'warning_message': f"There is already a {existing_repair.get_queue_status_display()} repair for this unit."
        })
    return JsonResponse({'existing_repair': False})

@technician_required
def reward_fulfillment_detail(request, redemption_id):
    """View details of a reward redemption and mark as fulfilled"""
    # Get the technician
    technician = get_object_or_404(Technician, user=request.user)
    
    # Get the redemption
    
    # Any technician can view reward details, but actions depend on assignment
    redemption = get_object_or_404(RewardRedemption, id=redemption_id)
    
    # Check if current technician is assigned to this redemption
    is_assigned_technician = (redemption.assigned_technician == technician)
    is_admin = request.user.is_staff
    can_fulfill = is_assigned_technician or is_admin
    
    # Get customer repairs for applying reward
    customer_repairs = []
    if redemption.reward and redemption.reward.customer_user and redemption.reward.customer_user.user:
        customer_email = redemption.reward.customer_user.user.email
        try:
            customer = Customer.objects.get(email=customer_email)
            customer_repairs = Repair.objects.filter(
                customer=customer,
                queue_status__in=['APPROVED', 'IN_PROGRESS']
            ).order_by('-repair_date')
        except Customer.DoesNotExist:
            pass
    
    if request.method == 'POST':
        # Only assigned technicians or admins can fulfill rewards
        if not can_fulfill:
            messages.error(request, "You don't have permission to fulfill this reward. Only the assigned technician or administrators can fulfill rewards.")
            return redirect('technician_dashboard')
        
        # Handle claim assignment action
        action = request.POST.get('action')
        if action == 'claim' and not redemption.assigned_technician:
            redemption.assigned_technician = technician
            redemption.save()
            messages.success(request, f'You have claimed the reward: {redemption.reward_option.name}')
            return redirect('reward_fulfillment_detail', redemption_id=redemption.id)
        
        # Process fulfillment
        notes = request.POST.get('notes', '')
        
        # Check if a repair was selected to apply the reward to
        repair_id = request.POST.get('apply_to_repair')
        if repair_id:
            try:
                repair = Repair.objects.get(id=repair_id)
                redemption.applied_to_repair = repair
            except Repair.DoesNotExist:
                pass
        
        RewardFulfillmentService.mark_as_fulfilled(redemption, technician, notes)
        
        messages.success(request, f'Reward {redemption.reward_option.name} has been marked as fulfilled.')
        return redirect('technician_dashboard')
    
    return render(request, 'technician_portal/reward_fulfillment.html', {
        'redemption': redemption,
        'customer_repairs': customer_repairs,
        'is_assigned_technician': is_assigned_technician,
        'can_fulfill': can_fulfill,
        'current_technician': technician,
        'is_admin': is_admin,
    })

@technician_required
def mark_notification_read(request, notification_id):
    """Mark a notification as read"""
    notification = get_object_or_404(TechnicianNotification, id=notification_id)
    
    # Ensure the notification belongs to this technician
    if notification.technician.user != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to access this notification.")
        return redirect('technician_dashboard')
    
    notification.read = True
    notification.save()
    
    # If notification is for a redemption, redirect to the redemption
    if notification.redemption:
        return redirect('reward_fulfillment_detail', redemption_id=notification.redemption.id)
    
    return redirect('technician_dashboard')

@technician_required
def assign_repair(request, repair_id):
    """Manager assigns a REQUESTED repair to a technician"""
    # Only managers can assign repairs
    if not request.user.is_staff:
        if not hasattr(request.user, 'technician') or not request.user.technician.is_manager:
            messages.error(request, "Only managers can assign repairs.")
            return redirect('technician_dashboard')

    repair = get_object_or_404(Repair, id=repair_id)

    # Can only assign REQUESTED repairs
    if repair.queue_status != 'REQUESTED':
        messages.error(request, "Only REQUESTED repairs can be assigned. This repair is already assigned.")
        return redirect('repair_detail', repair_id=repair.id)

    if request.method == 'POST':
        technician_id = request.POST.get('technician_id')

        if not technician_id:
            messages.error(request, "Please select a technician.")
            return redirect('assign_repair', repair_id=repair.id)

        try:
            assigned_tech = Technician.objects.get(id=technician_id)

            # If regular manager (not admin), verify they manage this technician OR assigning to themselves
            if not request.user.is_staff:
                manager = request.user.technician
                # Allow if assigning to themselves OR to a technician they manage
                if assigned_tech.id != manager.id and not manager.manages_technician(assigned_tech):
                    messages.error(request, "You can only assign repairs to yourself or technicians you manage.")
                    return redirect('assign_repair', repair_id=repair.id)

            # Assign the repair
            repair.technician = assigned_tech
            repair.queue_status = 'APPROVED'  # Customer already approved by requesting
            repair.save()

            # Create approval record

            customer_users = CustomerUser.objects.filter(customer=repair.customer)
            customer_user = customer_users.filter(is_primary_contact=True).first()
            if not customer_user and customer_users.exists():
                customer_user = customer_users.first()

            if customer_user:
                RepairApproval.objects.create(
                    repair=repair,
                    approved=True,
                    approved_by=customer_user,
                    approval_date=timezone.now(),
                    notes="Auto-approved - customer requested repair"
                )

            # Create notification for assigned technician
            TechnicianNotification.objects.create(
                technician=assigned_tech,
                message=f"You have been assigned Repair #{repair.id} for {repair.customer.name} - Unit {repair.unit_number}",
                read=False,
                repair=repair
            )

            messages.success(request, f"Repair #{repair.id} assigned to {assigned_tech.user.get_full_name()}")
            return redirect('repair_detail', repair_id=repair.id)

        except Technician.DoesNotExist:
            messages.error(request, "Selected technician not found.")
            return redirect('assign_repair', repair_id=repair.id)

    # GET request - show assignment form
    if request.user.is_staff:
        # Admins can assign to any technician
        available_technicians = Technician.objects.filter(is_active=True).order_by('user__first_name')
    else:
        # Managers can assign to technicians they manage OR to themselves
        manager = request.user.technician
        # Get managed technicians
        managed_techs = manager.managed_technicians.filter(is_active=True)
        # Include the manager themselves in the list
        available_technicians = Technician.objects.filter(
            Q(id=manager.id) | Q(id__in=managed_techs)
        ).filter(is_active=True).order_by('user__first_name')

    return render(request, 'technician_portal/assign_repair.html', {
        'repair': repair,
        'available_technicians': available_technicians,
    })

@technician_required
def reassign_to_self(request, repair_id):
    """Manager reassigns a team member's repair to themselves"""
    # Only managers can reassign repairs
    if not request.user.is_staff:
        if not hasattr(request.user, 'technician') or not request.user.technician.is_manager:
            messages.error(request, "Only managers can reassign repairs.")
            return redirect('technician_dashboard')

    repair = get_object_or_404(Repair, id=repair_id)

    # Verify user has permission
    if not request.user.is_staff:
        manager = request.user.technician

        # Check if repair is assigned to one of their managed technicians
        if not repair.technician or not manager.manages_technician(repair.technician):
            messages.error(request, "You can only reassign repairs from your managed technicians.")
            return redirect('repair_detail', repair_id=repair.id)

        # Cannot reassign if already assigned to themselves
        if repair.technician.id == manager.id:
            messages.error(request, "This repair is already assigned to you.")
            return redirect('repair_detail', repair_id=repair.id)

    if request.method == 'POST':
        old_technician = repair.technician

        if not request.user.is_staff:
            # Reassign to the manager
            repair.technician = request.user.technician
            repair.save()

            messages.success(request, f"Repair reassigned from {old_technician.user.get_full_name()} to you.")

            # AUTO-CLEANUP: Mark old technician's notifications as read since repair is no longer their responsibility
            old_tech_notifications = TechnicianNotification.objects.filter(
                technician=old_technician,
                repair=repair,
                read=False
            )
            if old_tech_notifications.exists():
                reassign_count = old_tech_notifications.count()
                old_tech_notifications.update(read=True)
                logger.info(f"Auto-marked {reassign_count} notification(s) as read for technician {old_technician.user.username} after reassigning repair #{repair.id}")

            # Create notification for the old technician about the reassignment
            TechnicianNotification.objects.create(
                technician=old_technician,
                message=f"Repair #{repair.id} for {repair.customer.name} - Unit {repair.unit_number} has been reassigned to {request.user.get_full_name()}",
                read=False,
                repair=repair
            )
        else:
            # Admins would use the regular assign_repair view
            messages.info(request, "Admins should use the regular assignment interface.")
            return redirect('assign_repair', repair_id=repair.id)

        return redirect('repair_detail', repair_id=repair.id)

    # GET request - show confirmation
    return render(request, 'technician_portal/reassign_to_self.html', {
        'repair': repair,
    })

@technician_required
def apply_reward_to_repair(request, repair_id):
    """Apply a reward redemption to a specific repair"""
    # Get the repair
    if request.user.is_staff:
        repair = get_object_or_404(Repair, id=repair_id)
    else:
        # Non-admin technicians can only access their own repairs
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile.")
            return redirect('technician_dashboard')
        repair = get_object_or_404(Repair, id=repair_id, technician=request.user.technician)
    
    if request.method == 'POST':
        redemption_id = request.POST.get('redemption_id')
        auto_fulfill = request.POST.get('auto_fulfill') == 'on'
        
        if not redemption_id:
            messages.error(request, "No reward selected")
            return redirect('repair_detail', repair_id=repair.id)
        
        # Get the redemption
        redemption = get_object_or_404(RewardRedemption, id=redemption_id)
        
        # Validate that the reward belongs to the customer of this repair
        customer_users = CustomerUser.objects.filter(customer=repair.customer)
        reward_customer_user = redemption.reward.customer_user
        
        if not customer_users.filter(id=reward_customer_user.id).exists():
            messages.error(request, "This reward belongs to a different customer and cannot be applied to this repair.")
            return redirect('repair_detail', repair_id=repair.id)
        
        # Apply the reward to the repair
        success, message = repair.apply_reward(
            redemption,
            technician=getattr(request.user, 'technician', None),
            auto_fulfill=auto_fulfill
        )
        
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        
        return redirect('repair_detail', repair_id=repair.id)
    
    # GET request - show available rewards for this customer
    
    # Find CustomerUser records for this customer
    customer_users = CustomerUser.objects.filter(customer=repair.customer)
    
    # Get all pending rewards for these customer users
    available_redemptions = RewardRedemption.objects.filter(
        reward__customer_user__in=customer_users,
        status='PENDING',
        applied_to_repair__isnull=True  # Not already applied
    ).select_related('reward_option', 'reward_option__reward_type')
    
    return render(request, 'technician_portal/apply_reward.html', {
        'repair': repair,
        'available_redemptions': available_redemptions,
    })


# ============================================================================
# MANAGER SETTINGS VIEWS
# ============================================================================

from .decorators import manager_required
from .models import ViscosityRecommendation
import json


@technician_required
@manager_required
def manager_settings_dashboard(request):
    """
    Main manager settings dashboard with navigation tiles.
    Accessible to managers (is_manager=True) and staff users.
    """
    manager = request.user.technician if hasattr(request.user, 'technician') else None

    # Get stats for dashboard tiles
    viscosity_rules_count = ViscosityRecommendation.objects.filter(is_active=True).count()

    team_count = 0
    if manager:
        team_count = manager.managed_technicians.filter(is_active=True).count()

    context = {
        'is_admin': request.user.is_staff,
        'technician': manager,
        'viscosity_rules_count': viscosity_rules_count,
        'team_count': team_count,
    }

    return render(request, 'technician_portal/settings/settings_dashboard.html', context)


@technician_required
@manager_required
@ensure_csrf_cookie
def manage_viscosity_rules(request):
    """
    Manage viscosity recommendation rules with card-based interface.
    Supports CRUD operations via AJAX modals.

    Rules are displayed with auto-calculated priority positions (1st, 2nd, 3rd...)
    based on their display_order field.
    """
    manager = request.user.technician if hasattr(request.user, 'technician') else None

    # Get all rules ordered by display_order
    # Enumerate to get priority position (1st, 2nd, 3rd...)
    rules = ViscosityRecommendation.objects.all().order_by('display_order', 'id')
    rules_with_position = [
        {
            'rule': rule,
            'position': idx + 1,  # 1-indexed position for display
            'position_suffix': get_ordinal_suffix(idx + 1)  # "st", "nd", "rd", "th"
        }
        for idx, rule in enumerate(rules)
    ]

    context = {
        'is_admin': request.user.is_staff,
        'technician': manager,
        'rules_with_position': rules_with_position,
        'badge_colors': ViscosityRecommendation.BADGE_COLOR_CHOICES,
    }

    return render(request, 'technician_portal/settings/viscosity_rules.html', context)


def get_ordinal_suffix(n):
    """
    Returns the ordinal suffix for a number (st, nd, rd, th).
    Examples: 1 → "st", 2 → "nd", 3 → "rd", 4 → "th", 11 → "th"
    """
    if 10 <= n % 100 <= 20:
        return 'th'
    else:
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


@technician_required
@manager_required
def get_viscosity_rule(request, rule_id):
    """
    AJAX endpoint to fetch a single viscosity recommendation rule.
    GET /tech/settings/api/viscosity/<id>/
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = get_object_or_404(ViscosityRecommendation, id=rule_id)

        return JsonResponse({
            'success': True,
            'rule': {
                'id': rule.id,
                'name': rule.name,
                'min_temperature': str(rule.min_temperature) if rule.min_temperature is not None else '',
                'max_temperature': str(rule.max_temperature) if rule.max_temperature is not None else '',
                'recommended_viscosity': rule.recommended_viscosity,
                'suggestion_text': rule.suggestion_text,
                'badge_color': rule.badge_color,
                'display_order': rule.display_order,
                'is_active': rule.is_active,
            }
        })

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f'Error fetching viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def create_viscosity_rule(request):
    """
    AJAX endpoint to create a new viscosity recommendation rule.
    POST /tech/settings/api/viscosity/create/

    Priority is auto-assigned: new rules get (max existing priority + 10)
    This leaves room for manual database adjustments if needed.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)

        # Validate required fields
        required_fields = ['name', 'recommended_viscosity', 'suggestion_text', 'badge_color']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }, status=400)

        # Auto-assign priority: get max existing display_order and add 10
        # This leaves room for manual reordering in database if needed
        max_order = ViscosityRecommendation.objects.aggregate(
            max_order=models.Max('display_order')
        )['max_order']
        next_order = (max_order or 0) + 10

        # Create new rule
        rule = ViscosityRecommendation.objects.create(
            name=data['name'],
            min_temperature=data.get('min_temperature') or None,
            max_temperature=data.get('max_temperature') or None,
            recommended_viscosity=data['recommended_viscosity'],
            suggestion_text=data['suggestion_text'],
            badge_color=data['badge_color'],
            display_order=next_order,  # Auto-assigned priority
            is_active=data.get('is_active', True)
        )

        return JsonResponse({
            'success': True,
            'message': 'Viscosity rule created successfully',
            'rule': {
                'id': rule.id,
                'name': rule.name,
                'temp_range': rule._get_temp_range_display(),
                'recommended_viscosity': rule.recommended_viscosity,
                'suggestion_text': rule.suggestion_text,
                'badge_color': rule.badge_color,
                'display_order': rule.display_order,
                'is_active': rule.is_active,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f'Error creating viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def update_viscosity_rule(request, rule_id):
    """
    AJAX endpoint to update an existing viscosity recommendation rule.
    PUT /tech/settings/api/viscosity/<id>/update/
    """
    if request.method not in ['PUT', 'POST']:  # Allow POST for compatibility
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = get_object_or_404(ViscosityRecommendation, id=rule_id)
        data = json.loads(request.body)

        # Update fields
        if 'name' in data:
            rule.name = data['name']
        if 'min_temperature' in data:
            rule.min_temperature = data['min_temperature'] or None
        if 'max_temperature' in data:
            rule.max_temperature = data['max_temperature'] or None
        if 'recommended_viscosity' in data:
            rule.recommended_viscosity = data['recommended_viscosity']
        if 'suggestion_text' in data:
            rule.suggestion_text = data['suggestion_text']
        if 'badge_color' in data:
            rule.badge_color = data['badge_color']
        if 'display_order' in data:
            rule.display_order = data['display_order']
        if 'is_active' in data:
            rule.is_active = data['is_active']

        rule.save()

        return JsonResponse({
            'success': True,
            'message': 'Viscosity rule updated successfully',
            'rule': {
                'id': rule.id,
                'name': rule.name,
                'temp_range': rule._get_temp_range_display(),
                'recommended_viscosity': rule.recommended_viscosity,
                'suggestion_text': rule.suggestion_text,
                'badge_color': rule.badge_color,
                'display_order': rule.display_order,
                'is_active': rule.is_active,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f'Error updating viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def delete_viscosity_rule(request, rule_id):
    """
    AJAX endpoint to delete a viscosity recommendation rule.
    DELETE /tech/settings/api/viscosity/<id>/delete/
    """
    if request.method not in ['DELETE', 'POST']:  # Allow POST for compatibility
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = get_object_or_404(ViscosityRecommendation, id=rule_id)
        rule_name = rule.name
        rule.delete()

        return JsonResponse({
            'success': True,
            'message': f'Viscosity rule "{rule_name}" deleted successfully'
        })

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f'Error deleting viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def toggle_viscosity_rule(request, rule_id):
    """
    AJAX endpoint to toggle active status of a viscosity recommendation rule.
    PATCH /tech/settings/api/viscosity/<id>/toggle/
    """
    if request.method not in ['PATCH', 'POST']:  # Allow POST for compatibility
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = get_object_or_404(ViscosityRecommendation, id=rule_id)
        rule.is_active = not rule.is_active
        rule.save()

        return JsonResponse({
            'success': True,
            'message': f'Viscosity rule {"activated" if rule.is_active else "deactivated"}',
            'is_active': rule.is_active
        })

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f'Error toggling viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def team_overview(request):
    """
    Team overview dashboard showing managed technicians and their stats.
    """
    manager = request.user.technician if hasattr(request.user, 'technician') else None

    if not manager:
        messages.warning(request, "Technician profile not found")
        return redirect('technician_dashboard')

    # Get managed technicians
    team_members = manager.managed_technicians.filter(is_active=True).select_related('user')

    # Calculate stats for each team member
    team_stats = []
    for tech in team_members:
        repairs = Repair.objects.filter(technician=tech)
        pending_repairs = repairs.filter(queue_status__in=['REQUESTED', 'PENDING', 'APPROVED'])
        completed_repairs = repairs.filter(queue_status='COMPLETED')

        total_count = repairs.count()
        completed_count = completed_repairs.count()
        completion_rate = (completed_count / total_count * 100) if total_count > 0 else 0

        team_stats.append({
            'technician': tech,
            'total_repairs': total_count,
            'pending_repairs': pending_repairs.count(),
            'completed_repairs': completed_count,
            'completion_rate': round(completion_rate, 1),
            'recent_repairs': repairs.order_by('-repair_date')[:5]
        })

    # Overall team stats
    total_team_repairs = sum(stat['total_repairs'] for stat in team_stats)
    total_team_pending = sum(stat['pending_repairs'] for stat in team_stats)
    total_team_completed = sum(stat['completed_repairs'] for stat in team_stats)

    context = {
        'is_admin': request.user.is_staff,
        'technician': manager,
        'team_stats': team_stats,
        'total_team_repairs': total_team_repairs,
        'total_team_pending': total_team_pending,
        'total_team_completed': total_team_completed,
        'team_members_count': team_members.count(),
    }

    return render(request, 'technician_portal/settings/team_overview.html', context)


# ============================================================================
# NOTIFICATION MANAGEMENT VIEWS (Phase 5)
# ============================================================================

@login_required
def notification_preferences(request):
    """
    Technician notification preferences management page.

    Allows technicians to:
    - Enable/disable notification channels (email, SMS, in-app)
    - Configure quiet hours
    - Set category preferences
    - Verify contact information
    - Enable daily digest mode
    """

    try:
        technician = request.user.technician
    except Technician.DoesNotExist:
        messages.error(request, "Technician profile not found.")
        return redirect('technician_dashboard')

    # Get or create preferences
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

    # Get notification statistics
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
    """
    View all notifications for technician.

    Paginated list with filters (read/unread, category, date range).
    """
    try:
        technician = request.user.technician
    except Technician.DoesNotExist:
        messages.error(request, "Technician profile not found.")
        return redirect('technician_dashboard')

    technician_ct = ContentType.objects.get_for_model(Technician)

    # Get notifications with optimized query (avoid N+1 queries)
    notifications = Notification.objects.filter(
        recipient_type=technician_ct,
        recipient_id=technician.id
    ).select_related(
        'repair',
        'customer',
        'template'
    ).order_by('-created_at')

    # Filters
    show_read = request.GET.get('show_read', 'false') == 'true'
    category = request.GET.get('category', '')

    if not show_read:
        notifications = notifications.filter(read=False)

    if category:
        notifications = notifications.filter(category=category)

    # Pagination
    paginator = Paginator(notifications, 25)  # 25 per page
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


@login_required
def mark_notification_read(request, notification_id):
    """Mark single notification as read"""
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


@login_required
def mark_all_read(request):
    """Mark all notifications as read for technician"""
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


@login_required
def get_unread_count(request):
    """
    AJAX endpoint for notification bell polling.

    Implements caching to reduce database queries (Phase 6 optimization).
    Cache TTL: 2 minutes (frequent polling requires shorter TTL).
    """
    try:
        technician = request.user.technician
        technician_ct = ContentType.objects.get_for_model(Technician)

        # Cache key for unread count
        cache_key = f'notif_unread_count:tech:{technician.id}'

        # Try to get from cache first
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            # Cache hit - return cached data
            return JsonResponse(cached_data)

        # Cache miss - query database
        count = Notification.objects.filter(
            recipient_type=technician_ct,
            recipient_id=technician.id,
            read=False
        ).count()

        # Also get recent notifications for dropdown
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

        # Cache for 2 minutes (120 seconds)
        # Note: Cache is invalidated by signals when notifications are created/updated
        cache.set(cache_key, response_data, timeout=120)

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def verify_email(request):
    """
    Send email verification link to technician.

    Sends verification email with unique token.
    """
    try:
        technician = request.user.technician
        preferences = technician.notification_preferences
    except (Technician.DoesNotExist, TechnicianNotificationPreference.DoesNotExist):
        messages.error(request, "Unable to verify email.")
        return redirect('notification_preferences')

    # Generate verification token
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes

    token = default_token_generator.make_token(request.user)
    uid = urlsafe_base64_encode(force_bytes(request.user.pk))

    # Build verification URL
    verification_url = request.build_absolute_uri(
        reverse('confirm_email_verification', kwargs={'uidb64': uid, 'token': token})
    )

    # Send verification email
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
    """
    Send SMS verification code to technician.

    Sends 6-digit verification code via SMS.
    """
    try:
        technician = request.user.technician
        preferences = technician.notification_preferences
    except (Technician.DoesNotExist, TechnicianNotificationPreference.DoesNotExist):
        messages.error(request, "Unable to verify phone.")
        return redirect('notification_preferences')

    if not technician.phone_number:
        messages.error(request, "Please add a phone number first.")
        return redirect('notification_preferences')

    # Generate 6-digit code
    import random
    code = f"{random.randint(100000, 999999)}"

    # Store code in session
    request.session['phone_verification_code'] = code
    request.session['phone_verification_number'] = technician.phone_number
    request.session['phone_verification_expires'] = (timezone.now() + timedelta(minutes=10)).isoformat()

    # Send verification SMS
    from core.services.sms_service import SMSService
    message = f"Your RS Systems verification code is: {code}. This code expires in 10 minutes."

    try:
        # Use SMS service if configured
        from django.conf import settings
        if hasattr(settings, 'SMS_ENABLED') and settings.SMS_ENABLED:
            SMSService.send_sms(
                phone_number=technician.phone_number,
                message=message
            )
            messages.success(request, f"Verification code sent to {technician.phone_number}")
        else:
            # Development mode - show code in message
            messages.info(request, f"Development mode: Your verification code is {code}")
    except Exception as e:
        logger.error(f"Failed to send SMS verification: {str(e)}")
        messages.error(request, "Failed to send verification code. Please try again later.")

    return redirect('notification_preferences')


def confirm_email_verification(request, uidb64, token):
    """
    Process email verification token.

    Note: No @login_required - verification links should work even if user is logged out.
    The token itself authenticates the request.
    """
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
            messages.success(request, "Email verified successfully! You can now receive email notifications.")
        except Technician.DoesNotExist:
            messages.error(request, "Technician profile not found.")
    else:
        messages.error(request, "Invalid or expired verification link. Please request a new verification email.")

    # Redirect based on authentication status
    if request.user.is_authenticated:
        return redirect('notification_preferences')
    else:
        return redirect('technician_login')


@login_required
def confirm_phone_verification(request):
    """Process phone verification code"""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        stored_code = request.session.get('phone_verification_code')
        stored_number = request.session.get('phone_verification_number')
        expires_str = request.session.get('phone_verification_expires')

        if not all([stored_code, stored_number, expires_str]):
            messages.error(request, "No verification code found. Please request a new code.")
            return redirect('notification_preferences')

        # Check expiration
        from dateutil import parser
        expires = parser.isoparse(expires_str)
        if timezone.now() > expires:
            messages.error(request, "Verification code has expired. Please request a new code.")
            # Clean up session
            request.session.pop('phone_verification_code', None)
            request.session.pop('phone_verification_number', None)
            request.session.pop('phone_verification_expires', None)
            return redirect('notification_preferences')

        # Verify code
        if code == stored_code:
            try:
                technician = request.user.technician
                if technician.phone_number == stored_number:
                    technician.phone_verified = True
                    technician.phone_verified_at = timezone.now()
                    technician.save()
                    messages.success(request, "Phone number verified successfully!")

                    # Clean up session
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
