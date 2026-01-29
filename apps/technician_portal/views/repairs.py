"""
Repair CRUD, list, detail, and status management views.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.http import JsonResponse
from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation
import logging

from apps.technician_portal.models import Technician, Repair, TechnicianNotification
from apps.customer_portal.models import RepairApproval, CustomerUser, CustomerRepairPreference
from apps.technician_portal.forms import RepairForm
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from common.utils import convert_heic_to_jpeg

logger = logging.getLogger(__name__)


@technician_required
def repair_list(request):
    """List repairs with filtering, sorting, and pagination."""
    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user):
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to view repairs.")
            return redirect('technician_dashboard')

        technician = request.user.technician

        if technician.is_manager:
            managed_tech_ids = list(technician.managed_technicians.values_list('id', flat=True))
            managed_tech_ids.append(technician.id)
            repairs = Repair.objects.filter(
                Q(technician_id__in=managed_tech_ids) | Q(queue_status='REQUESTED')
            )
        else:
            repairs = Repair.objects.filter(
                technician=technician
            ).exclude(queue_status='REQUESTED')
    else:
        repairs = Repair.objects.all()
        technician = None

    # Tenant scoping
    if tenant:
        repairs = repairs.filter(tenant=tenant)

    # Optimize query with select_related
    repairs = repairs.select_related('customer', 'technician__user').order_by('-service_date')

    # Get filter parameters
    customer_search = request.GET.get('customer_search', '')
    status_filter = request.GET.get('status', 'all')
    unit_search = request.GET.get('unit_search', '')
    damage_type_filter = request.GET.get('damage_type', 'all')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    assignment_filter = request.GET.get('assignment', 'all')

    if customer_search:
        repairs = repairs.filter(customer__name__icontains=customer_search)

    if status_filter != 'all':
        status_list = status_filter.split(',')
        repairs = repairs.filter(queue_status__in=status_list)

    if unit_search:
        repairs = repairs.filter(unit_number__icontains=unit_search)

    if damage_type_filter != 'all':
        repairs = repairs.filter(damage_type=damage_type_filter)

    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            repairs = repairs.filter(service_date__gte=date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            repairs = repairs.filter(service_date__lte=date_to_obj)
        except ValueError:
            pass

    if technician and (is_tenant_admin(request.user) or technician.is_manager):
        if assignment_filter == 'mine':
            repairs = repairs.filter(technician=technician)
        elif assignment_filter == 'unassigned':
            repairs = repairs.filter(technician__isnull=True)
        elif assignment_filter == 'team' and technician.is_manager:
            managed_tech_ids = list(technician.managed_technicians.values_list('id', flat=True))
            repairs = repairs.filter(technician_id__in=managed_tech_ids)

    # Summary statistics
    total_repairs = repairs.count()
    stats = {
        'total_active': repairs.exclude(queue_status='COMPLETED').count(),
        'pending_approval': repairs.filter(queue_status='REQUESTED').count(),
        'in_progress': repairs.filter(queue_status='IN_PROGRESS').count(),
        'completed_this_week': repairs.filter(
            queue_status='COMPLETED',
            service_date__gte=timezone.now().date() - timezone.timedelta(days=7)
        ).count()
    }

    # Sorting
    sort_by = request.GET.get('sort', '-service_date')
    # Accept both repair_date (legacy templates) and service_date (new field name)
    if sort_by in ('repair_date', '-repair_date'):
        sort_by = sort_by.replace('repair_date', 'service_date')
    valid_sorts = ['service_date', '-service_date', 'customer__name', '-customer__name',
                   'unit_number', '-unit_number', 'cost', '-cost', 'queue_status', '-queue_status']
    if sort_by in valid_sorts:
        repairs = repairs.order_by(sort_by)

    # Pagination
    page_size = int(request.GET.get('page_size', 50))
    if page_size not in [20, 50, 100]:
        page_size = 50

    paginator = Paginator(repairs, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    damage_types = Repair.DAMAGE_TYPE_CHOICES

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
        'is_admin': is_tenant_admin(request.user),
        'technician': technician,
    }

    return render(request, 'technician_portal/repair_list.html', context)


@technician_required
def repair_detail(request, repair_id):
    """Display repair details with permission checks and batch context."""
    tenant = getattr(request, 'tenant', None)
    qs = Repair.objects.select_related('customer', 'technician__user')
    if tenant:
        qs = qs.filter(tenant=tenant)
    repair = get_object_or_404(qs, id=repair_id)

    can_update_status = False
    can_assign_repair = False
    can_reassign_to_self = False
    technician = None

    if hasattr(request.user, 'technician'):
        technician = request.user.technician

        # Auto-mark notifications as read when viewing repair
        unread_notifications = TechnicianNotification.objects.filter(
            technician=technician,
            repair=repair,
            read=False
        )
        if unread_notifications.exists():
            unread_count = unread_notifications.count()
            unread_notifications.update(read=True)
            logger.info(f"Auto-marked {unread_count} notification(s) as read for technician {technician.user.username} viewing repair #{repair.id}")

    if not is_tenant_admin(request.user):
        if not technician:
            messages.error(request, "You don't have a technician profile to view repairs.")
            return redirect('technician_dashboard')

        if repair.queue_status == 'PENDING':
            # Tech can view their own pending repairs but not others'
            if repair.technician != technician and not technician.is_manager:
                messages.error(request, "This repair is pending customer approval.")
                return redirect('technician_dashboard')

        if repair.queue_status == 'REQUESTED':
            if not technician.is_manager:
                messages.error(request, "Only managers can view customer-requested repairs.")
                return redirect('technician_dashboard')
            can_update_status = True
            can_assign_repair = True
        else:
            can_view = False
            if repair.technician == technician:
                can_view = True
                can_update_status = True
            elif technician.is_manager and repair.technician and technician.manages_technician(repair.technician):
                can_view = True
                can_reassign_to_self = True
            elif '/create/' in request.META.get('HTTP_REFERER', '') or '/update/' in request.META.get('HTTP_REFERER', ''):
                can_view = True

            if not can_view:
                messages.error(request, "You don't have permission to view this repair.")
                return redirect('technician_dashboard')
    else:
        can_update_status = True
        can_assign_repair = repair.queue_status == 'REQUESTED'

    # Add batch context
    batch_info = None
    next_break = None
    if repair.is_part_of_batch:
        try:
            batch_summary = Repair.get_batch_summary(repair.repair_batch_id)
            if batch_summary:
                batch_info = batch_summary
                incomplete_repairs = [
                    r for r in sorted(batch_summary['all_repairs'], key=lambda x: x.break_number or 0)
                    if r.queue_status not in ['COMPLETED', 'DENIED'] and r.id != repair.id
                ]
                if incomplete_repairs:
                    next_break = incomplete_repairs[0]
        except Exception as e:
            logger.error(f"Error getting batch summary for repair {repair.id} in batch {repair.repair_batch_id}: {e}", exc_info=True)

    return render(request, 'technician_portal/repair_detail.html', {
        'repair': repair,
        'TIME_ZONE': timezone.get_current_timezone_name(),
        'is_admin': is_tenant_admin(request.user),
        'can_update_status': can_update_status,
        'can_assign_repair': can_assign_repair,
        'can_reassign_to_self': can_reassign_to_self,
        'technician': technician,
        'batch_info': batch_info,
        'next_break': next_break,
    })


@technician_required
def create_repair(request):
    """Create a new single repair."""
    if request.method == 'POST':
        # Convert HEIC images to JPEG
        if 'damage_photo_before' in request.FILES:
            request.FILES['damage_photo_before'] = convert_heic_to_jpeg(request.FILES['damage_photo_before'])
        if 'damage_photo_after' in request.FILES:
            request.FILES['damage_photo_after'] = convert_heic_to_jpeg(request.FILES['damage_photo_after'])

        form = RepairForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            if is_tenant_admin(request.user):
                if form.cleaned_data.get('technician'):
                    repair = form.save(commit=False)
                    repair.technician = form.cleaned_data.get('technician')
                    repair.tenant = getattr(request, 'tenant', None)
                    repair.save()
                    form.save_m2m()
                    messages.success(request, f"Repair has been created and assigned to {repair.technician.user.get_full_name()}")
                else:
                    messages.error(request, "As an admin, you must select a technician to assign the repair to.")
                    return render(request, 'technician_portal/repair_form.html', {
                        'form': form,
                        'is_admin': True
                    })
            else:
                try:
                    repair = form.save(commit=False)
                    repair.technician = request.user.technician
                    repair.tenant = getattr(request, 'tenant', None)

                    # Check customer preferences for approval
                    try:
                        preferences = repair.customer.repair_preferences
                        if preferences.should_auto_approve(repair.technician, repair.repair_date.date() if repair.repair_date else None):
                            repair.queue_status = 'APPROVED'
                            messages.info(request, "Repair auto-approved based on customer preferences.")
                        else:
                            repair.queue_status = 'PENDING'
                            messages.warning(request, "This customer requires approval for field repairs. Repair submitted for customer approval.")
                    except CustomerRepairPreference.DoesNotExist:
                        repair.queue_status = 'PENDING'
                        messages.warning(request, "Repair submitted for customer approval (customer preferences not configured).")

                    repair.save()
                    form.save_m2m()

                    # If no technician was explicitly set (shouldn't happen here
                    # since we default to request.user.technician, but safety net)
                    if not repair.technician_id:
                        from apps.tenants.services.assignment_service import auto_assign_repair
                        auto_assign_repair(repair)

                except AttributeError:
                    messages.error(request, "You don't have a technician profile to create repairs.")
                    return redirect('technician_dashboard')

            messages.success(request, f'Repair #{repair.id} created successfully!')
            return redirect('repair_detail', repair_id=repair.id)
        else:
            logger.debug(f"Form errors: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = RepairForm(user=request.user)

    pending_repair_warning = form.errors.get('__all__')

    expected_cost = None
    if hasattr(form, 'instance') and form.instance.customer and form.instance.unit_number:
        expected_cost = form.instance.get_expected_price()

    return render(request, 'technician_portal/repair_form.html', {
        'form': form,
        'pending_repair_warning': pending_repair_warning,
        'is_admin': is_tenant_admin(request.user),
        'expected_cost': expected_cost
    })


@technician_required
def update_repair(request, repair_id):
    """Update an existing repair with permission and security checks."""
    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user):
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to manage repairs.")
            return redirect('technician_dashboard')

        qs = Repair.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        repair = get_object_or_404(qs, id=repair_id)
        logger.info(f"UPDATE_REPAIR: Got repair #{repair.id}, technician_id={repair.technician_id}")

        user_is_manager = request.user.technician.is_manager if hasattr(request.user, 'technician') else False
        if repair.queue_status in ['COMPLETED', 'DENIED'] and not user_is_manager:
            messages.error(request, "This repair is closed and cannot be edited. Contact a manager if photos need to be added.")
            return redirect('repair_detail', repair_id=repair.id)

        if not repair.technician_id:
            messages.error(request, "This repair has not been assigned yet and cannot be edited by technicians.")
            return redirect('repair_detail', repair_id=repair.id)

        if repair.technician_id != request.user.technician.id:
            messages.error(request, "You can only edit repairs assigned to you.")
            return redirect('repair_detail', repair_id=repair.id)
    else:
        qs = Repair.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        repair = get_object_or_404(qs, id=repair_id)

    if request.method == 'POST':
        logger.info(f"UPDATE_REPAIR POST: Processing form for repair #{repair.id}")

        if 'damage_photo_before' in request.FILES:
            request.FILES['damage_photo_before'] = convert_heic_to_jpeg(request.FILES['damage_photo_before'])
        if 'damage_photo_after' in request.FILES:
            request.FILES['damage_photo_after'] = convert_heic_to_jpeg(request.FILES['damage_photo_after'])

        original_technician_id = repair.technician_id
        logger.info(f"UPDATE_REPAIR: Saved original_technician_id={original_technician_id}")

        form = RepairForm(request.POST, request.FILES, instance=repair, user=request.user)
        if form.is_valid():
            logger.info(f"UPDATE_REPAIR: Form is valid, calling save(commit=False)")
            updated_repair = form.save(commit=False)

            # Handle photo deletion
            for field_name in ['damage_photo_before', 'damage_photo_after']:
                delete_flag = request.POST.get(f'{field_name}-DELETE')
                if delete_flag == 'true':
                    current_photo = getattr(updated_repair, field_name)
                    if current_photo:
                        current_photo.delete(save=False)
                        setattr(updated_repair, field_name, None)

            if not is_tenant_admin(request.user):
                logger.info(f"UPDATE_REPAIR: Restoring technician_id from original_technician_id={original_technician_id}")
                updated_repair.technician_id = original_technician_id
            elif form.cleaned_data.get('technician'):
                updated_repair.technician = form.cleaned_data.get('technician')

            # Auto-complete if IN_PROGRESS with after photo
            if updated_repair.queue_status == 'IN_PROGRESS' and updated_repair.damage_photo_after:
                updated_repair.queue_status = 'COMPLETED'
                logger.info(f"UPDATE_REPAIR: Auto-completing repair #{updated_repair.id} (has after photo)")
                messages.success(request, "Repair marked as COMPLETED! (After photo uploaded)")

            updated_repair.save()
            form.save_m2m()
            messages.success(request, "Repair has been updated successfully.")

            # Batch navigation
            if updated_repair.repair_batch_id:
                batch_summary = Repair.get_batch_summary(updated_repair.repair_batch_id)
                if batch_summary and batch_summary['completed_count'] == batch_summary['break_count']:
                    messages.success(request, "All breaks in this batch are complete!")
                return redirect('repair_detail', repair_id=updated_repair.id)

            return redirect('repair_detail', repair_id=repair.id)
        else:
            logger.warning(f"UPDATE_REPAIR: Form validation failed for repair #{repair.id}. Errors: {form.errors}")

            if form.errors:
                for field, errors in form.errors.items():
                    for error in errors:
                        if field == '__all__':
                            messages.error(request, str(error))
                        else:
                            messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
    else:
        form = RepairForm(instance=repair, user=request.user)

        if repair.queue_status == 'COMPLETED':
            user_is_manager = (is_tenant_admin(request.user) or
                             (hasattr(request.user, 'technician') and request.user.technician.is_manager))
            if user_is_manager:
                messages.info(request, "You're editing a completed repair. You can add or update photos for documentation/AI training purposes.")

    expected_cost = repair.get_expected_price() if repair.customer and repair.unit_number else None

    batch_id = request.GET.get('batch_id') or request.POST.get('batch_id')
    batch_repairs = []
    if batch_id and repair.repair_batch_id:
        batch_repairs = Repair.objects.filter(
            repair_batch_id=repair.repair_batch_id
        ).order_by('break_number')

    return render(request, 'technician_portal/repair_form.html', {
        'form': form,
        'repair': repair,
        'is_admin': is_tenant_admin(request.user),
        'expected_cost': expected_cost,
        'batch_id': batch_id,
        'batch_repairs': batch_repairs,
    })


@technician_required
def update_queue_status(request, repair_id):
    """Update repair queue status with permission checks."""
    tenant = getattr(request, 'tenant', None)
    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    repair = get_object_or_404(qs, id=repair_id)

    if not is_tenant_admin(request.user):
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to update repairs.")
            return redirect('technician_dashboard')

        technician = request.user.technician

        if repair.queue_status == 'PENDING':
            messages.error(request, "This repair is pending customer approval. Technicians cannot modify it.")
            return redirect('technician_dashboard')

        if repair.queue_status == 'REQUESTED':
            if not technician.is_manager:
                messages.error(request, "Only managers can assign customer-requested repairs.")
                return redirect('technician_dashboard')
        else:
            can_update = False
            if repair.technician == technician:
                can_update = True
            elif technician.is_manager and repair.technician and technician.manages_technician(repair.technician):
                messages.error(request, "You cannot modify repairs assigned to other technicians. Use the reassign feature to take over this repair.")
                return redirect('repair_detail', repair_id=repair.id)

            if not can_update:
                messages.error(request, "You don't have permission to update this repair.")
                return redirect('technician_dashboard')

    old_status = repair.queue_status

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Repair.QUEUE_CHOICES):
            if old_status == 'REQUESTED':
                # Auto-assign to the manager accepting the repair
                if not is_tenant_admin(request.user) and hasattr(request.user, 'technician'):
                    repair.technician = request.user.technician
                    messages.info(request, "Repair assigned to you.")

                repair.queue_status = new_status
                repair.save()

                # Create automatic approval record
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
                        notes="Auto-approved as customer initiated the request"
                    )

                messages.success(request, "Repair request has been accepted and added to your schedule. The customer has been notified.")
            else:
                repair.queue_status = new_status
                if new_status == 'COMPLETED':
                    repair.repair_date = timezone.now()

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

                # Auto-cleanup: mark notifications as read on completion
                if new_status == 'COMPLETED' and repair.technician:
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
def assign_repair(request, repair_id):
    """Manager assigns a REQUESTED repair to a technician."""
    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user):
        if not hasattr(request.user, 'technician') or not request.user.technician.is_manager:
            messages.error(request, "Only managers can assign repairs.")
            return redirect('technician_dashboard')

    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    repair = get_object_or_404(qs, id=repair_id)

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

            if not is_tenant_admin(request.user):
                manager = request.user.technician
                if assigned_tech.id != manager.id and not manager.manages_technician(assigned_tech):
                    messages.error(request, "You can only assign repairs to yourself or technicians you manage.")
                    return redirect('assign_repair', repair_id=repair.id)

            repair.technician = assigned_tech
            repair.queue_status = 'APPROVED'
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

    # GET request
    if is_tenant_admin(request.user):
        available_technicians = Technician.objects.filter(is_active=True).order_by('user__first_name')
    else:
        manager = request.user.technician
        managed_techs = manager.managed_technicians.filter(is_active=True)
        available_technicians = Technician.objects.filter(
            Q(id=manager.id) | Q(id__in=managed_techs)
        ).filter(is_active=True).order_by('user__first_name')

    return render(request, 'technician_portal/assign_repair.html', {
        'repair': repair,
        'available_technicians': available_technicians,
    })


@technician_required
def reassign_to_self(request, repair_id):
    """Manager reassigns a team member's repair to themselves."""
    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user):
        if not hasattr(request.user, 'technician') or not request.user.technician.is_manager:
            messages.error(request, "Only managers can reassign repairs.")
            return redirect('technician_dashboard')

    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    repair = get_object_or_404(qs, id=repair_id)

    if not is_tenant_admin(request.user):
        manager = request.user.technician

        if not repair.technician or not manager.manages_technician(repair.technician):
            messages.error(request, "You can only reassign repairs from your managed technicians.")
            return redirect('repair_detail', repair_id=repair.id)

        if repair.technician.id == manager.id:
            messages.error(request, "This repair is already assigned to you.")
            return redirect('repair_detail', repair_id=repair.id)

    if request.method == 'POST':
        old_technician = repair.technician

        if not is_tenant_admin(request.user):
            repair.technician = request.user.technician
            repair.save()

            messages.success(request, f"Repair reassigned from {old_technician.user.get_full_name()} to you.")

            # Auto-cleanup notifications
            old_tech_notifications = TechnicianNotification.objects.filter(
                technician=old_technician,
                repair=repair,
                read=False
            )
            if old_tech_notifications.exists():
                reassign_count = old_tech_notifications.count()
                old_tech_notifications.update(read=True)
                logger.info(f"Auto-marked {reassign_count} notification(s) as read for technician {old_technician.user.username} after reassigning repair #{repair.id}")

            TechnicianNotification.objects.create(
                technician=old_technician,
                message=f"Repair #{repair.id} for {repair.customer.name} - Unit {repair.unit_number} has been reassigned to {request.user.get_full_name()}",
                read=False,
                repair=repair
            )
        else:
            messages.info(request, "Admins should use the regular assignment interface.")
            return redirect('assign_repair', repair_id=repair.id)

        return redirect('repair_detail', repair_id=repair.id)

    return render(request, 'technician_portal/reassign_to_self.html', {
        'repair': repair,
    })


@technician_required
def check_existing_repair(request):
    """AJAX endpoint to check for existing active repairs on a unit."""
    tenant = getattr(request, 'tenant', None)
    customer_id = request.GET.get('customer')
    unit_number = request.GET.get('unit_number')
    qs = Repair.objects.filter(
        customer_id=customer_id,
        unit_number=unit_number,
        queue_status__in=['PENDING', 'APPROVED', 'IN_PROGRESS']
    )
    if tenant:
        qs = qs.filter(tenant=tenant)
    existing_repair = qs.first()

    if existing_repair:
        return JsonResponse({
            'existing_repair': True,
            'status': existing_repair.get_queue_status_display(),
            'repair_id': existing_repair.id,
            'warning_message': f"There is already a {existing_repair.get_queue_status_display()} repair for this unit."
        })
    return JsonResponse({'existing_repair': False})
