"""
Dashboard and registration views for the technician portal.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
import logging

from apps.technician_portal.models import Technician, Repair, Replacement, TechnicianNotification
from apps.customer_portal.models import RepairApproval
from apps.rewards_referrals.models import RewardRedemption
from core.models import Customer, Notification
from apps.technician_portal.forms import TechnicianRegistrationForm
from apps.technician_portal.decorators import technician_required, is_tenant_admin

logger = logging.getLogger(__name__)


def register_technician(request):
    """Handle technician registration.

    Legacy endpoint at /admin/register-technician/ — predates the invite system.
    MUST require staff/superuser access; without this gate any anonymous visitor
    can create a Django User + Technician record (tenant=NULL), polluting the
    user table and potentially causing cascading issues when the orphaned
    Technician record is resolved by the OneToOneField reverse accessor.

    (CODE-252: add authentication guard to legacy register_technician endpoint)
    """
    # Require authenticated staff/superuser — matches the "Admin Only" label
    # shown in the template and the /admin/ prefix in the URL.
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "This page requires administrator access.")
        return redirect('login')

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
    # Tenant scoping first — needed to scope the Technician lookup below.
    tenant = getattr(request, 'tenant', None)

    # Get technician profile scoped to the current tenant.
    # We deliberately avoid `request.user.technician` (unscoped OneToOneField)
    # because it resolves to whichever Technician row exists for the user
    # globally — a manager at Shop A would appear as manager on Shop B's dashboard
    # and see REQUESTED repairs they shouldn't (CODE-081 / same pattern as CODE-077).
    technician = None
    if hasattr(request.user, 'technician'):
        if tenant:
            technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
        else:
            technician = request.user.technician

    # Get customer-requested repairs (ONLY for managers)
    if technician:
        # Only MANAGERS can see REQUESTED repairs (for assignment purposes).
        # `technician` is already tenant-scoped above, so is_manager is correct.
        if technician.is_manager:
            qs = Repair.objects.filter(queue_status='REQUESTED')
            if tenant:
                qs = qs.filter(tenant=tenant)

            else:
                qs = qs.none()
            customer_requested_repairs = qs.select_related('customer', 'technician').order_by('-service_date')
        else:
            customer_requested_repairs = Repair.objects.none()

        # Get assigned reward redemptions for this technician
        assigned_redemptions = RewardRedemption.objects.filter(
            assigned_technician=technician,
            status='PENDING'
        ).order_by('-created_at')

        # Get all pending redemptions (visible to all technicians, tenant-scoped)
        pending_qs = RewardRedemption.objects.filter(
            status='PENDING'
        ).exclude(
            id__in=[r.id for r in assigned_redemptions]
        )
        if tenant:
            pending_qs = pending_qs.filter(
                reward__customer__tenant=tenant
            )
        all_pending_redemptions = pending_qs.order_by('-created_at')[:5]

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
        ).select_related('customer').order_by('-service_date')

        # Get active work (IN_PROGRESS and APPROVED)
        repairs_active = Repair.objects.filter(
            technician=technician,
            queue_status__in=['IN_PROGRESS', 'APPROVED']
        ).select_related('customer').order_by('-service_date')

        # Get recently completed batch repairs (completed in last 7 days)
        recent_completions = Repair.objects.filter(
            technician=technician,
            queue_status='COMPLETED',
            service_date__gte=timezone.now() - timedelta(days=7)
        ).select_related('customer').order_by('-service_date')

        # --- Bulk-fetch all batch repairs in a SINGLE query (CODE-142 N+1 fix) ---
        # Previously: get_batch_summary() was called once per batch inside each of
        # the three loops below, issuing ~4 DB queries per call (exists, first, list,
        # values_list).  With up to 60 unique batches across 3 sections that's
        # potentially ~240 DB queries per dashboard load.
        # Fix: collect all unique batch IDs from the three repair sets, fetch their
        # sibling repairs in one query, group in Python, then build summaries via
        # build_batch_summary_from_repairs() which does zero additional DB work.
        _approved_slice = list(repairs_recently_approved[:10])
        _active_slice = list(repairs_active[:30])
        _completed_slice = list(recent_completions[:20])

        _all_dashboard_repairs = _approved_slice + _active_slice + _completed_slice
        _batch_ids_needed = {
            r.repair_batch_id
            for r in _all_dashboard_repairs
            if r.is_part_of_batch and r.repair_batch_id
        }

        # One query for all sibling repairs across all batches on this dashboard
        _prefetched_batches: dict = {}  # batch_id → sorted list of repairs
        if _batch_ids_needed:
            sibling_qs = Repair.objects.filter(
                repair_batch_id__in=_batch_ids_needed,
            ).select_related('customer').order_by('break_number')
            if tenant:
                sibling_qs = sibling_qs.filter(tenant=tenant)
            for r in sibling_qs:
                _prefetched_batches.setdefault(r.repair_batch_id, []).append(r)

        def _batch_summary(batch_id):
            """Build summary from pre-fetched data; falls back to DB if not cached."""
            repairs_for_batch = _prefetched_batches.get(batch_id)
            if repairs_for_batch:
                return Repair.build_batch_summary_from_repairs(batch_id, repairs_for_batch)
            # Fallback (should not normally be hit after the bulk-fetch above)
            return Repair.get_batch_summary(batch_id, tenant=tenant)

        # Group recently-approved repairs and separate individual repairs
        batch_repairs_approved = {}
        individual_repairs_approved = []

        for repair in _approved_slice:
            if repair.is_part_of_batch:
                if repair.repair_batch_id not in batch_repairs_approved:
                    try:
                        batch_summary = _batch_summary(repair.repair_batch_id)
                        if batch_summary:
                            batch_repairs_approved[repair.repair_batch_id] = batch_summary
                    except Exception as e:
                        logger.error(f"Error getting batch summary for batch {repair.repair_batch_id}: {e}", exc_info=True)
            else:
                individual_repairs_approved.append(repair)

        individual_repairs_approved = individual_repairs_approved[:5]

        batch_repairs_in_progress = {}
        individual_repairs_in_progress = []

        for repair in _active_slice:
            if repair.is_part_of_batch:
                if repair.repair_batch_id not in batch_repairs_in_progress:
                    try:
                        batch_summary = _batch_summary(repair.repair_batch_id)
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

        batch_repairs_completed = {}
        individual_repairs_completed = []

        for repair in _completed_slice:
            if repair.is_part_of_batch:
                if repair.repair_batch_id not in batch_repairs_completed:
                    try:
                        batch_summary = _batch_summary(repair.repair_batch_id)
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

        # --- Today's Work Queue ---
        # Priority-ordered list of this tech's actionable work
        from django.db.models import Case, When, Value, IntegerField
        queue_qs = Repair.objects.filter(
            technician=technician,
            queue_status__in=['IN_PROGRESS', 'APPROVED', 'PENDING'],
        ).select_related('customer').annotate(
            priority=Case(
                When(queue_status='IN_PROGRESS', then=Value(0)),
                When(queue_status='APPROVED', then=Value(1)),
                When(queue_status='PENDING', then=Value(2)),
                output_field=IntegerField(),
            )
        ).order_by('priority', 'service_date')
        if tenant:
            queue_qs = queue_qs.filter(tenant=tenant)

        else:
            queue_qs = queue_qs.none()
        todays_queue = list(queue_qs[:20])
    else:
        # For admins without a technician profile
        qs = Repair.objects.filter(queue_status='REQUESTED')
        if tenant:
            qs = qs.filter(tenant=tenant)

        else:
            qs = qs.none()
        customer_requested_repairs = qs.select_related('customer', 'technician').order_by('-service_date')

        assigned_redemptions = []
        pending_qs = RewardRedemption.objects.filter(status='PENDING')
        if tenant:
            pending_qs = pending_qs.filter(
                reward__customer__tenant=tenant
            )
        all_pending_redemptions = pending_qs.order_by('-created_at')

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
        todays_queue = []

    # Extra data for admin users
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    admin_data = None

    if is_admin:
        repair_qs = Repair.objects.all()
        customer_qs = Customer.objects.all()
        tech_qs = Technician.objects.all()
        redemption_qs = RewardRedemption.objects.filter(status='PENDING')
        if tenant:
            repair_qs = repair_qs.filter(tenant=tenant)
            customer_qs = customer_qs.filter(tenant=tenant)
            tech_qs = tech_qs.filter(tenant=tenant)
            redemption_qs = redemption_qs.filter(
                reward__customer__tenant=tenant
            )
        else:
            repair_qs = repair_qs.none()
            customer_qs = customer_qs.none()
            tech_qs = tech_qs.none()
            redemption_qs = redemption_qs.none()
        admin_data = {
            'total_repairs': repair_qs.count(),
            'pending_repairs': repair_qs.filter(queue_status='PENDING').count(),
            'customers': customer_qs.count(),
            'technicians': tech_qs.count(),
            'pending_redemptions': redemption_qs.count()
        }

    # --- Replacements (only when the shop offers them) ---
    # Same shape as the repair queues: the tech's own active replacements,
    # plus customer-requested ones for managers/admins to assign.
    shop_offers_replacements = bool(tenant and tenant.offers_replacements)
    replacements_active = []
    customer_requested_replacements = []
    if shop_offers_replacements:
        if technician:
            replacements_active = list(
                Replacement.objects.filter(
                    tenant=tenant,
                    technician=technician,
                    queue_status__in=['PENDING', 'APPROVED', 'IN_PROGRESS'],
                ).select_related('customer').order_by('-service_date')[:10]
            )
        if is_admin or (technician and technician.is_manager):
            customer_requested_replacements = list(
                Replacement.objects.filter(
                    tenant=tenant,
                    queue_status='REQUESTED',
                ).select_related('customer', 'technician').order_by('-service_date')[:10]
            )

    # --- Unified queues: replacements join repairs in Today's Queue and the
    # customer-requests card. Legacy per-type context keys stay populated.
    _QUEUE_PRIORITY = {'IN_PROGRESS': 0, 'APPROVED': 1, 'PENDING': 2}
    for job in todays_queue:
        job.service_type = 'repair'
    if replacements_active:
        for repl in replacements_active:
            repl.service_type = 'replacement'
            repl.priority = _QUEUE_PRIORITY.get(repl.queue_status, 3)
        todays_queue = sorted(
            todays_queue + replacements_active,
            key=lambda j: (j.priority, (j.service_date is None, j.service_date)),
        )[:20]

    customer_requests = list(customer_requested_repairs)
    for req in customer_requests:
        req.service_type = 'repair'
    for repl in customer_requested_replacements:
        repl.service_type = 'replacement'
        customer_requests.append(repl)
    customer_requests.sort(
        key=lambda j: (j.service_date is not None, j.service_date), reverse=True
    )

    # --- Date-aware queue buckets (S1) ---
    # scheduled_for is the booking time ("when we said we'd come"); a null
    # means unscheduled. service_date is when work happened and plays no part
    # here. When nothing in the queue is scheduled, the order and rendering
    # are exactly the pre-S1 flat queue — the template only draws bucket
    # headers when queue_has_schedule is true.
    _local_today = timezone.localtime(timezone.now()).date()

    def _schedule_bucket(job):
        if job.scheduled_for is None:
            return 'unscheduled'
        scheduled_day = timezone.localtime(job.scheduled_for).date()
        if scheduled_day < _local_today:
            return 'overdue'
        if scheduled_day == _local_today:
            return 'today'
        return 'later'

    for job in todays_queue:
        job.schedule_bucket = _schedule_bucket(job)
    queue_has_schedule = any(
        j.schedule_bucket != 'unscheduled' for j in todays_queue)
    if queue_has_schedule:
        _BUCKET_ORDER = {'overdue': 0, 'today': 1, 'later': 2, 'unscheduled': 3}
        _now = timezone.now()
        # Scheduled buckets sort by booking time; unscheduled jobs all share
        # the same key, so the stable sort keeps their existing status-priority
        # order.
        todays_queue.sort(key=lambda j: (
            _BUCKET_ORDER[j.schedule_bucket], j.scheduled_for or _now,
        ))

    # Fold the tech's replacement workload into the summary tiles so a
    # replacement-only shop's dashboard isn't all zeros.
    if technician and shop_offers_replacements:
        _week_ago = timezone.now() - timedelta(days=7)
        _repl_agg = Replacement.objects.filter(
            tenant=tenant, technician=technician,
        ).aggregate(
            in_prog=Count('id', filter=Q(queue_status='IN_PROGRESS')),
            ready=Count('id', filter=Q(queue_status='APPROVED')),
            week=Count('id', filter=Q(
                queue_status='COMPLETED', service_date__gte=_week_ago,
            )),
        )
        summary_stats['individual_in_progress'] += _repl_agg['in_prog']
        summary_stats['pending_approval'] += _repl_agg['ready']
        summary_stats['completed_this_week'] += _repl_agg['week']
        summary_stats['total_active_work'] += _repl_agg['in_prog'] + _repl_agg['ready']

    if admin_data is not None:
        _admin_repl_qs = Replacement.objects.filter(tenant=tenant) if tenant else Replacement.objects.none()
        admin_data['total_jobs'] = admin_data['total_repairs'] + _admin_repl_qs.count()
        admin_data['pending_jobs'] = (
            admin_data['pending_repairs']
            + _admin_repl_qs.filter(queue_status='PENDING').count()
        )

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
        'bell_prefetched': True,
        'batch_repairs_approved': batch_repairs_approved.values() if batch_repairs_approved else [],
        'individual_repairs_approved': individual_repairs_approved,
        'batch_repairs_in_progress': batch_repairs_in_progress.values() if batch_repairs_in_progress else [],
        'individual_repairs_in_progress': individual_repairs_in_progress,
        'batch_repairs_completed': batch_repairs_completed.values() if batch_repairs_completed else [],
        'individual_repairs_completed': individual_repairs_completed,
        'is_admin': is_admin,
        'admin_data': admin_data,
        'summary_stats': summary_stats,
        'todays_queue': todays_queue,
        'queue_has_schedule': queue_has_schedule,
        'customer_requests': customer_requests,
        'replacements_active': replacements_active,
        'customer_requested_replacements': customer_requested_replacements,
    })
