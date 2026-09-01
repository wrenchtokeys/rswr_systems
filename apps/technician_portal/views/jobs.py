"""
Unified "Jobs" views — repairs + replacements as one surface.

Repair and Replacement stay separate models; unification happens here at the
view layer using the same merge pattern as the customer portal's services page
(apps/customer_portal/views.py customer_services).
"""

from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.auth import can_access
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from apps.technician_portal.models import Technician, Repair, Replacement
from apps.technician_portal.services.job_flow import (
    JobFlowError, complete_job, invoice_and_send,
)


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


# Fields that live behind the job form's "More details" disclosure. If one of
# them fails validation the panel must be opened on re-render, or the user sees
# "please correct the errors" with every visible field looking fine.
_ADVANCED_JOB_FIELDS = frozenset({
    'technician', 'vehicle_year', 'vehicle_make', 'vehicle_model',
    'service_address', 'service_city', 'service_state', 'service_zip',
    'damage_photo_before', 'damage_photo_after', 'customer_notes', 'internal_notes',
    'windshield_temperature', 'resin_viscosity', 'drilled_before_repair',
    'requires_adas_calibration', 'adas_calibration_cost',
    'insurance_claim', 'insurance_company', 'claim_number', 'deductible',
})


def _advanced_has_errors(form):
    return any(name in _ADVANCED_JOB_FIELDS for name in getattr(form, 'errors', {}))


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
    customer_type_filter = request.GET.get('customer_type', 'all')
    if customer_type_filter not in ('all', 'fleet', 'individual'):
        customer_type_filter = 'all'
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
        if customer_type_filter == 'fleet':
            qs = qs.filter(customer__customer_type='FLEET')
        elif customer_type_filter == 'individual':
            qs = qs.filter(customer__customer_type__in=['RETAIL', 'WALK_IN'])
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
                # `technician` is NOT NULL, so this filter matched nothing at
                # all until needs_assignment existed — the dropdown option was
                # decorative. It now lists the jobs the shop's strategy
                # declined to assign, waiting on a manager. (CODE-279)
                qs = qs.filter(needs_assignment=True)
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

    # Count for the "Filters" button badge — only the filters that live behind
    # the disclosure, not the always-visible type/status/search controls.
    active_filter_count = sum([
        customer_type_filter != 'all',
        bool(unit_search),
        damage_type_filter != 'all',
        bool(date_from),
        bool(date_to),
        assignment_filter != 'all',
    ])

    # How many damage photos still have no break marked on them (P4a.1).
    # This is the only entry point to the burn-down queue — the nav has no
    # room and the arc's whole problem was that nobody knew the backlog was
    # there. Bounded by QUEUE_LIMIT, and it goes through the same permission
    # filter the queue itself uses so the number can't promise more than the
    # page will show.
    from apps.technician_portal.services.photo_backlog import backlog_size
    unmarked_photo_count = backlog_size(request, tenant)

    context = {
        'jobs': page_obj,
        'page_obj': page_obj,
        'total_jobs': total_jobs,
        'stats': stats,
        'unmarked_photo_count': unmarked_photo_count,
        'type_filter': type_filter,
        'customer_search': customer_search,
        'customer_type_filter': customer_type_filter,
        'status_filter': status_filter,
        'unit_search': unit_search,
        'damage_type_filter': damage_type_filter,
        'date_from': date_from,
        'date_to': date_to,
        'assignment_filter': assignment_filter,
        'active_filter_count': active_filter_count,
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


def _job_detail_redirect(service):
    if isinstance(service, Repair):
        return redirect('repair_detail', repair_id=service.id)
    return redirect('replacement_detail', pk=service.id)


def _job_form_sms_ready(tenant):
    """Whether the send-invoice dialog may offer "Also text it"."""
    from apps.billing.services.invoice_send_service import InvoiceSendService
    return InvoiceSendService.sms_ready(tenant)


def _copy_to_email(request):
    """BCC address for "Send me a copy", or None when not requested /
    the acting user has no email on their account."""
    if request.POST.get('send_me_copy') and request.user.email:
        return request.user.email
    return None


def notify_invoice_outcome(request, invoice, created, result, excluded):
    """Consistent messages for the quick-invoice actions."""
    if excluded:
        messages.warning(
            request,
            f'{excluded} batch repair(s) are not yet completed and were '
            f'excluded from this invoice.'
        )
    if result.sent:
        messages.success(request, result.message)
    elif result.reason == 'no_email':
        messages.warning(
            request,
            f'Invoice {invoice.invoice_number} saved as a draft — add an '
            f'email address below to send it.'
        )
    elif result.reason == 'not_draft' and not created:
        messages.info(
            request,
            f'This job is already on invoice {invoice.invoice_number}.'
        )
    else:
        messages.error(request, result.message)


def _parse_extra_charges(request):
    """Parse the repeatable extra-charge rows (charge_desc[] / charge_amount[]).

    Returns (charges, error): charges is a list of (description, Decimal)
    tuples; error is a user-facing message or None. Fully blank rows are
    skipped.
    """
    from decimal import InvalidOperation

    descs = request.POST.getlist('charge_desc')
    amounts = request.POST.getlist('charge_amount')
    charges = []
    for desc, raw_amount in zip(descs, amounts):
        desc = desc.strip()
        raw_amount = (raw_amount or '').strip()
        if not desc and not raw_amount:
            continue
        if not desc:
            return [], 'Each extra charge needs a description.'
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, TypeError):
            return [], f'Enter a valid amount for the "{desc}" charge.'
        if amount <= 0:
            return [], f'The "{desc}" charge must be more than zero.'
        charges.append((desc[:200], amount.quantize(Decimal('0.01'))))
    return charges, None


def _save_extra_charges(service, charges, tenant, taxable=True):
    """Replace the job's extra charges with the parsed rows.

    The implementation moved to services/quick_job.py with the rest of the
    creation path (S10). This name stays because four call sites outside this
    module import it — repairs.py twice, saas/views.py twice — and a second
    copy of the logic is exactly what that extraction was for.
    """
    from apps.technician_portal.services.quick_job import save_extra_charges

    return save_extra_charges(service, charges, tenant, taxable=taxable)


@technician_required
def job_create(request):
    """Quick job + invoice: one short form, optionally straight to a sent
    invoice ("Save & Send Invoice")."""
    from apps.technician_portal.forms import QuickJobForm
    from apps.tenants.services.usage_service import (
        UsageService, limit_message_for,
    )
    from apps.technician_portal.services.quick_job import (
        QuickJobError, allowed_service_types, create_job, shop_tax_state,
    )

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        return redirect('technician_dashboard')

    allowed_types = allowed_service_types(tenant)

    # Checked here as well as inside create_job so the shop is turned away at
    # the door rather than after filling the whole form in.
    can_create, limit_msg = UsageService(tenant).can_create_repair()
    if not can_create:
        messages.warning(
            request, limit_message_for(request.user, tenant, limit_msg))
        return redirect('job_list')

    user_can_invoices = can_access(request.user, 'invoices', tenant)

    # Shop-level tax state drives the "Charge sales tax" checkbox: hidden
    # entirely when the shop doesn't charge tax.
    shop_tax_enabled, shop_tax_rate = shop_tax_state(tenant)

    from apps.technician_portal.models import FeePreset
    fee_presets = FeePreset.objects.filter(tenant=tenant, is_active=True)

    if request.method == 'POST':
        # request.FILES: the "More details" panel takes damage photos, so this
        # form is multipart now. HEIC is converted before the form sees the
        # files, same as create_repair and the batch views.
        from common.utils import convert_heic_to_jpeg
        for _photo_field in ('damage_photo_before', 'damage_photo_after'):
            if _photo_field in request.FILES:
                request.FILES[_photo_field] = convert_heic_to_jpeg(
                    request.FILES[_photo_field])
        form = QuickJobForm(
            request.POST, request.FILES, tenant=tenant, allowed_types=allowed_types,
        )
        charges, charge_error = _parse_extra_charges(request)
        if form.is_valid() and charge_error:
            form.add_error(None, charge_error)
        if form.is_valid():
            data = form.cleaned_data

            # Everything from "resolve the customer" to service.save() lives
            # in services/quick_job.py, shared with the schedule page's
            # quick-add endpoint. This view's remaining job is to turn a
            # QuickJobError back into the form's own idiom: a message and a
            # redirect, or the duplicate-suggestion re-render.
            try:
                service = create_job(
                    tenant=tenant,
                    actor_user=request.user,
                    data=data,
                    charges=charges,
                    # A walk-in being logged after the work is done has no
                    # assignment to announce.
                    notify_assignment=not data['already_completed'],
                )
            except QuickJobError as exc:
                if exc.suggestions:
                    # Duplicate guard: suggest the existing person instead of
                    # erroring or silently creating "John Smith (2)". A
                    # confirmed resubmit ("No, this is a different person")
                    # goes through.
                    return render(request, 'technician_portal/job_form.html', {
                        'invoice_sms_ready': _job_form_sms_ready(tenant),
                        'form': form,
                        'allowed_types': allowed_types,
                        'user_can_invoices': user_can_invoices,
                        'advanced_has_errors': _advanced_has_errors(form),
                        'duplicate_suggestions': exc.suggestions,
                        'shop_tax_enabled': shop_tax_enabled,
                        'shop_tax_rate': shop_tax_rate,
                        'fee_presets': fee_presets,
                        'charge_rows': charges,
                    })
                if exc.status == 403:
                    messages.warning(
                        request,
                        limit_message_for(request.user, tenant, exc.message))
                else:
                    messages.error(request, exc.message)
                return redirect('job_list')

            # Tap-to-crop (PHOTO_ML P1, #211): save a labeled close-up of
            # the break beside the photo. Reads the tap coordinates off
            # request.POST, which is why it stays in the view rather than
            # moving into create_job with the rest of the creation path —
            # the quick-add modal takes no photos.
            #
            # Replacements included since P4a. This used to be gated on
            # service_type == 'repair', which was the single biggest reason
            # the dataset held nothing but repairable damage: the busiest
            # capture surface in the app declined to label the negative
            # class. See docs/strategy/PHOTO_ML_SESSIONS.md.
            from apps.technician_portal.services.photo_crops import (
                process_tap_coordinates,
            )
            process_tap_coordinates(
                service, request.POST, technician=service.technician,
            )

            send_requested = 'save_and_send' in request.POST and user_can_invoices
            if data['already_completed'] or send_requested:
                try:
                    # Legal forward jump APPROVED → COMPLETED; fires the
                    # completion side effects exactly once.
                    complete_job(service)
                except JobFlowError as e:
                    messages.warning(request, str(e))
                    return _job_detail_redirect(service)

            if send_requested and service.queue_status == 'COMPLETED':
                invoice, created, result, excluded = invoice_and_send(
                    service, tenant,
                    submitted_email=request.POST.get('email', ''),
                    copy_to_email=_copy_to_email(request),
                    send_sms=bool(request.POST.get('send_sms')))
                notify_invoice_outcome(request, invoice, created, result, excluded)
                return redirect('owner_invoice_detail', invoice_id=invoice.id)

            messages.success(
                request,
                f"{'Job' if len(allowed_types) > 1 else data['service_type'].title()} "
                f"saved{' and marked complete' if service.queue_status == 'COMPLETED' else ''}."
            )
            return _job_detail_redirect(service)
    else:
        initial = {}
        if request.GET.get('customer'):
            initial['customer'] = request.GET.get('customer')
        if request.GET.get('unit'):
            initial['unit_number'] = request.GET.get('unit')
        if request.GET.get('type') in allowed_types:
            initial['service_type'] = request.GET.get('type')
        form = QuickJobForm(initial=initial, tenant=tenant, allowed_types=allowed_types)

    # On a bounced POST, re-render whatever charge rows were typed so they
    # aren't silently lost with the validation error.
    charge_rows = []
    if request.method == 'POST':
        charge_rows = [
            (d.strip(), a.strip())
            for d, a in zip(request.POST.getlist('charge_desc'),
                            request.POST.getlist('charge_amount'))
            if d.strip() or a.strip()
        ]

    # First-run tour (owner/manager only — completion is per-tenant and the
    # completion endpoint is owner-gated). Never on a bounced POST: a coach
    # popover over a validation error would bury the error. ?tour=1 forces
    # a replay (linked from the help pages).
    tour_slug = ''
    if request.method == 'GET' and is_tenant_admin(request.user, tenant=tenant):
        from apps.tenants.models import OnboardingState
        if (request.GET.get('tour') == '1'
                or not OnboardingState.get_for_tenant(tenant).has_completed_tour('job-form')):
            tour_slug = 'job-form'

    return render(request, 'technician_portal/job_form.html', {
        'invoice_sms_ready': _job_form_sms_ready(tenant),
        'form': form,
        'allowed_types': allowed_types,
        'user_can_invoices': user_can_invoices,
        'advanced_has_errors': _advanced_has_errors(form),
        'shop_tax_enabled': shop_tax_enabled,
        'shop_tax_rate': shop_tax_rate,
        'fee_presets': fee_presets,
        'charge_rows': charge_rows,
        'tour_slug': tour_slug,
    })


@technician_required
@require_POST
def repair_complete_and_invoice(request, repair_id):
    """One click: complete the repair (if needed), invoice it (whole batch),
    and email the invoice."""
    tenant = getattr(request, 'tenant', None)
    repair = get_object_or_404(
        Repair.objects.filter(tenant=tenant) if tenant else Repair.objects.none(),
        id=repair_id,
    )

    if not can_access(request.user, 'invoices', tenant):
        messages.warning(request, "You don't have access to invoicing.")
        return redirect('repair_detail', repair_id=repair.id)

    if not is_tenant_admin(request.user, tenant=tenant):
        technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
        if not technician or (not technician.is_manager
                              and repair.technician_id != technician.id):
            messages.warning(request, "You don't have access to this repair.")
            return redirect('job_list')

    try:
        complete_job(repair)
    except JobFlowError as e:
        messages.warning(request, str(e))
        return redirect('repair_detail', repair_id=repair.id)

    try:
        invoice, created, result, excluded = invoice_and_send(
            repair, tenant,
            submitted_email=request.POST.get('email', ''),
            copy_to_email=_copy_to_email(request),
            send_sms=bool(request.POST.get('send_sms')))
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('repair_detail', repair_id=repair.id)
    notify_invoice_outcome(request, invoice, created, result, excluded)
    return redirect('owner_invoice_detail', invoice_id=invoice.id)
