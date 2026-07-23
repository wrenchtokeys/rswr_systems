"""
Unified "Jobs" views — repairs + replacements as one surface.

Repair and Replacement stay separate models; unification happens here at the
view layer using the same merge pattern as the customer portal's services page
(apps/customer_portal/views.py customer_services).
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone

from apps.technician_portal.decorators import technician_required, is_tenant_admin
from apps.technician_portal.models import Technician, Repair, Replacement


def _visible_jobs(model, tenant, technician, user_is_admin):
    """Role-scoped queryset for either service model.

    Mirrors the repair_list visibility matrix: admins see everything, managers
    see their team's work plus all customer requests, plain technicians see
    only their own work (customer requests are a manager concern).
    """
    if user_is_admin:
        qs = model.objects.all()
    elif technician is None:
        return model.objects.none()
    elif technician.is_manager:
        managed_tech_ids = list(technician.managed_technicians.values_list('id', flat=True))
        managed_tech_ids.append(technician.id)
        qs = model.objects.filter(
            Q(technician_id__in=managed_tech_ids) | Q(queue_status='REQUESTED')
        )
    else:
        qs = model.objects.filter(technician=technician).exclude(queue_status='REQUESTED')

    if tenant:
        return qs.filter(tenant=tenant)
    return model.objects.none()


_STATS_AGG = dict(
    total_count=Count('id'),
    total_active=Count('id', filter=~Q(queue_status__in=['COMPLETED', 'DENIED'])),
    pending_approval=Count('id', filter=Q(queue_status='REQUESTED')),
    in_progress=Count('id', filter=Q(queue_status='IN_PROGRESS')),
)


@technician_required
def job_list(request):
    """Unified repairs + replacements list with filtering, sorting, pagination.

    Replaces repair_list and replacement_list (both now redirect here). The
    merged list is fully evaluated per request — accepted precedent from
    customer_services; if a tenant ever holds tens of thousands of rows, the
    escape hatch is a two-pass merge (fetch only (id, service_date, type) for
    sorting, then fetch the current page's objects).
    """
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    technician = None
    if not user_is_admin:
        # Tenant-scoped lookup so a manager at Shop A stays a plain tech at
        # Shop B (CODE-077).
        technician = Technician.objects.filter(
            user=request.user, tenant=tenant
        ).first() if tenant else getattr(request.user, 'technician', None)
        if not technician:
            messages.error(request, "You don't have a technician profile for this shop.")
            return redirect('technician_dashboard')
    elif hasattr(request.user, 'technician'):
        technician = Technician.objects.filter(
            user=request.user, tenant=tenant
        ).first() if tenant else request.user.technician

    # --- Filters ---
    type_filter = request.GET.get('type', 'all')
    if type_filter not in ('all', 'repair', 'replacement'):
        type_filter = 'all'
    customer_search = request.GET.get('customer_search', '')
    status_filter = request.GET.get('status', 'all')
    unit_search = request.GET.get('unit_search', '')
    damage_type_filter = request.GET.get('damage_type', 'all')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    assignment_filter = request.GET.get('assignment', 'all')

    # Damage type only exists on repairs — filtering by it implies repairs.
    if damage_type_filter != 'all':
        type_filter = 'repair'

    def apply_filters(qs):
        if customer_search:
            qs = qs.filter(customer__name__icontains=customer_search)
        if status_filter != 'all':
            qs = qs.filter(queue_status__in=status_filter.split(','))
        if unit_search:
            qs = qs.filter(unit_number__icontains=unit_search)
        if date_from:
            try:
                from datetime import datetime
                qs = qs.filter(service_date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass
        if date_to:
            try:
                from datetime import datetime
                qs = qs.filter(service_date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass
        if technician and (user_is_admin or technician.is_manager):
            if assignment_filter == 'mine':
                qs = qs.filter(technician=technician)
            elif assignment_filter == 'unassigned':
                qs = qs.filter(technician__isnull=True)
            elif assignment_filter == 'team' and technician.is_manager:
                managed = list(technician.managed_technicians.values_list('id', flat=True))
                qs = qs.filter(technician_id__in=managed)
        return qs

    repairs_qs = Repair.objects.none()
    replacements_qs = Replacement.objects.none()
    if type_filter in ('all', 'repair'):
        repairs_qs = apply_filters(
            _visible_jobs(Repair, tenant, technician, user_is_admin)
        )
        if damage_type_filter != 'all':
            repairs_qs = repairs_qs.filter(damage_type=damage_type_filter)
        repairs_qs = repairs_qs.select_related('customer', 'technician__user', 'warranty_policy')
    if type_filter in ('all', 'replacement'):
        replacements_qs = apply_filters(
            _visible_jobs(Replacement, tenant, technician, user_is_admin)
        )
        replacements_qs = replacements_qs.select_related('customer', 'technician__user', 'warranty_policy')

    # Stats — one aggregate per model (CODE-151 pattern), summed.
    _week_start = timezone.now().date() - timezone.timedelta(days=7)
    _completed_week = dict(completed_this_week=Count(
        'id', filter=Q(queue_status='COMPLETED', service_date__gte=_week_start)
    ))
    repair_agg = repairs_qs.aggregate(**_STATS_AGG, **_completed_week)
    repl_agg = replacements_qs.aggregate(**_STATS_AGG, **_completed_week)
    total_jobs = repair_agg['total_count'] + repl_agg['total_count']
    stats = {
        'total_active': repair_agg['total_active'] + repl_agg['total_active'],
        'pending_approval': repair_agg['pending_approval'] + repl_agg['pending_approval'],
        'in_progress': repair_agg['in_progress'] + repl_agg['in_progress'],
        'completed_this_week': repair_agg['completed_this_week'] + repl_agg['completed_this_week'],
    }

    # --- Merge + in-memory sort (both lists already filtered at DB level) ---
    jobs = []
    for r in repairs_qs:
        r.service_type = 'repair'
        jobs.append(r)
    for r in replacements_qs:
        r.service_type = 'replacement'
        jobs.append(r)

    sort_by = request.GET.get('sort', '-service_date')
    if sort_by in ('repair_date', '-repair_date'):  # legacy param name
        sort_by = sort_by.replace('repair_date', 'service_date')
    field = sort_by.lstrip('-')
    reverse_sort = sort_by.startswith('-')
    sort_keys = {
        # (is None, value) tuples keep None-valued rows comparable (same
        # trick as customer_services).
        'service_date': lambda j: (j.service_date is None, j.service_date),
        'customer__name': lambda j: (j.customer.name.lower() if j.customer_id else ''),
        'unit_number': lambda j: (j.unit_number or ''),
        'cost': lambda j: (j.cost is None, j.cost),
        'queue_status': lambda j: j.queue_status,
    }
    key = sort_keys.get(field)
    if key is None:
        key, reverse_sort = sort_keys['service_date'], True
        sort_by = '-service_date'
    jobs.sort(key=key, reverse=reverse_sort)

    # Pagination — page_size guard (CODE-205).
    try:
        page_size = int(request.GET.get('page_size', 50))
    except (ValueError, TypeError):
        page_size = 50
    if page_size not in [20, 50, 100]:
        page_size = 50
    paginator = Paginator(jobs, page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'jobs': page_obj,
        'page_obj': page_obj,
        'total_jobs': total_jobs,
        'stats': stats,
        'type_filter': type_filter,
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
        'damage_types': Repair.DAMAGE_TYPE_CHOICES,
        'is_admin': user_is_admin,
        'technician': technician,
    }
    return render(request, 'technician_portal/job_list.html', context)


def _redirect_to_job_list(request, extra=None):
    params = request.GET.copy()
    for key, value in (extra or {}).items():
        params[key] = value
    url = reverse('job_list')
    query = params.urlencode()
    return redirect(f'{url}?{query}' if query else url)


@technician_required
def repair_list(request):
    """Legacy /tech/repairs/ — now redirects to the unified job list."""
    extra = {}
    if request.GET.get('damage_type', 'all') != 'all':
        extra['type'] = 'repair'
    return _redirect_to_job_list(request, extra)
