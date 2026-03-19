"""
Multi-break batch repair views for the technician portal.

Handles batch creation, conversion, detail viewing, and batch work management.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.db import transaction
from decimal import Decimal, InvalidOperation
import logging
import uuid

from apps.technician_portal.models import Technician, Repair, UnitRepairCount, TechnicianNotification
from apps.customer_portal.models import CustomerRepairPreference
from core.models import Customer
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from common.auth import get_user_role
from apps.technician_portal.services.batch_pricing_service import calculate_batch_pricing
from common.utils import convert_heic_to_jpeg

logger = logging.getLogger(__name__)


@technician_required
def technician_batch_detail(request, batch_id):
    """Display all repairs in a batch with batch actions for technician."""
    # Admins/owners without a Technician profile are allowed by @technician_required;
    # guard with getattr to avoid RelatedObjectDoesNotExist for those users.
    technician = getattr(request.user, 'technician', None)
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    # Pass tenant so cross-tenant batch access is blocked at the DB layer.
    batch_summary = Repair.get_batch_summary(batch_id, tenant=tenant)
    if not batch_summary:
        messages.error(request, "Batch not found.")
        return redirect('technician_dashboard')

    repairs = batch_summary['all_repairs']

    can_view = False
    can_start_work = False

    if user_is_admin:
        can_view = True
        can_start_work = True
    elif technician:
        for repair in repairs:
            if repair.technician == technician:
                can_view = True
                if repair.queue_status == 'APPROVED':
                    can_start_work = True
                break

        if not can_view and technician.is_manager:
            for repair in repairs:
                if repair.technician and technician.manages_technician(repair.technician):
                    can_view = True
                    break

    if not can_view:
        messages.error(request, "You don't have permission to view this batch.")
        return redirect('technician_dashboard')

    # Auto-mark batch notifications as read
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
        'repairs': batch_summary['repairs'],
        'technician': technician,
        'can_start_work': can_start_work,
        'is_admin': user_is_admin,
    })


@technician_required
@transaction.atomic
def technician_batch_start_work(request, batch_id):
    """Start work on all repairs in a batch at once."""
    # Guard: admin/owner users without a Technician record are allowed through
    # @technician_required but don't have a .technician reverse relation.
    technician = getattr(request.user, 'technician', None)
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    batch_summary = Repair.get_batch_summary(batch_id, tenant=tenant)
    if not batch_summary:
        messages.error(request, "Batch not found.")
        return redirect('technician_dashboard')

    repairs = batch_summary['all_repairs']
    started_count = 0

    for repair in repairs:
        if repair.queue_status != 'APPROVED':
            continue
        # Admins/owners can start any repair in the batch.
        # Technicians (and managers) can only start repairs assigned to them.
        if user_is_admin or repair.technician == technician:
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

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'started_count': started_count,
            'batch_id': str(batch_id),
        })

    return redirect('technician_batch_detail', batch_id=batch_id)


@technician_required
def create_multi_break_repair(request):
    """Create multiple repairs (breaks) on the same unit in one session."""
    user_is_admin = is_tenant_admin(request.user, tenant=getattr(request, 'tenant', None))
    if request.method == 'POST':
        try:
            customer_id = request.POST.get('customer')
            unit_number = request.POST.get('unit_number')
            repair_date_str = request.POST.get('repair_date', request.POST.get('service_date'))
            breaks_count = int(request.POST.get('breaks_count', 0))

            logger.info(f"[MULTI-BREAK] Request received - customer_id={customer_id}, unit={unit_number}, date={repair_date_str}, breaks={breaks_count}")

            if not all([customer_id, unit_number, repair_date_str, breaks_count > 0]):
                error_msg = "Missing required information. Please ensure you've added at least one break."
                logger.warning(f"[MULTI-BREAK] Validation failed - customer_id={customer_id}, unit={unit_number}, date={repair_date_str}, breaks={breaks_count}")
                messages.error(request, error_msg)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                return redirect('create_multi_break_repair')

            tenant = getattr(request, 'tenant', None)
            try:
                customer_qs = Customer.objects.select_related('tenant')
                if tenant:
                    customer_qs = customer_qs.filter(tenant=tenant)

                else:
                    customer_qs = customer_qs.none()
                customer = customer_qs.get(id=customer_id)
                logger.info(f"[MULTI-BREAK] Customer found: {customer.name} (ID: {customer.id})")
            except Customer.DoesNotExist:
                error_msg = f"Invalid customer selected (ID: {customer_id})."
                logger.error(f"[MULTI-BREAK] Customer not found - ID={customer_id}")
                messages.error(request, error_msg)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                return redirect('create_multi_break_repair')

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

            # Calculate pricing for all breaks
            pricing_breakdown = calculate_batch_pricing(customer, unit_number, breaks_count)

            batch_id = uuid.uuid4()
            created_repairs = []

            # Determine technician — always use tenant-scoped lookup to prevent
            # cross-tenant Technician assignment (CODE-084 / same family as CODE-082).
            if user_is_admin:
                tech_id = request.POST.get('technician_id')
                if not tech_id:
                    # Admin who is also a technician — look up their tenant-scoped record.
                    technician = Technician.objects.filter(
                        user=request.user, tenant=tenant
                    ).first() if tenant else None
                    if not technician:
                        error_msg = "As an admin, you must select a technician."
                        messages.error(request, error_msg)
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': error_msg}, status=400)
                        return redirect('create_multi_break_repair')
                else:
                    try:
                        tech_qs = Technician.objects.filter(id=tech_id)
                        if tenant:
                            tech_qs = tech_qs.filter(tenant=tenant)
                        else:
                            tech_qs = tech_qs.none()
                        technician = tech_qs.get()
                    except Technician.DoesNotExist:
                        error_msg = "Invalid technician selected."
                        messages.error(request, error_msg)
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': error_msg}, status=400)
                        return redirect('create_multi_break_repair')
            else:
                # Non-admin: scope lookup to current tenant to avoid assigning a
                # cross-tenant Technician record to this shop's repair.
                technician = Technician.objects.filter(
                    user=request.user, tenant=tenant
                ).first() if tenant else None
                if not technician:
                    error_msg = "You don't have a technician profile to create repairs."
                    messages.error(request, error_msg)
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'error': error_msg}, status=400)
                    return redirect('technician_dashboard')

            logger.info(f"[MULTI-BREAK] Starting atomic transaction for {breaks_count} breaks")
            with transaction.atomic():
                for i in range(breaks_count):
                    damage_type = request.POST.get(f'breaks[{i}][damage_type]', '')
                    notes = request.POST.get(f'breaks[{i}][notes]', '')

                    logger.debug(f"[MULTI-BREAK] Break {i+1}/{breaks_count} - damage_type='{damage_type}', notes_length={len(notes)}")

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

                    # Manager override fields
                    cost_override = request.POST.get(f'breaks[{i}][cost_override]', '')
                    override_reason = request.POST.get(f'breaks[{i}][override_reason]', '')

                    # Photo uploads
                    photo_before = request.FILES.get(f'breaks[{i}][photo_before]')
                    photo_after = request.FILES.get(f'breaks[{i}][photo_after]')

                    if photo_before:
                        photo_before = convert_heic_to_jpeg(photo_before)
                    if photo_after:
                        photo_after = convert_heic_to_jpeg(photo_after)

                    break_price = pricing_breakdown[i]['price']

                    # Handle manager price override
                    if cost_override:
                        try:
                            override_amount = Decimal(cost_override)
                            # Determine the *requesting user's* role (not the assigned technician's).
                            # Previously this checked `technician.is_manager` which is wrong when an
                            # owner/admin assigns a repair to a plain tech: the assigned tech's
                            # permissions were checked instead of the submitter's. (CODE-042)
                            _req_tenant = getattr(request, 'tenant', None)
                            requesting_role = get_user_role(request.user, tenant=_req_tenant)
                            if requesting_role in ('superuser', 'owner'):
                                # Owners/superusers can always override; no approval_limit applies.
                                pass
                            elif requesting_role == 'manager':
                                # Managers: must have override permission, reason, and stay within limit.
                                # Use tenant-scoped Technician lookup so a manager from another
                                # shop cannot bleed their can_override_pricing=True into this tenant.
                                requesting_tech = (
                                    Technician.objects.filter(user=request.user, tenant=_req_tenant).first()
                                    if _req_tenant else None
                                )
                                if not (requesting_tech and requesting_tech.can_override_pricing):
                                    messages.error(request, f"Break {i+1}: You don't have permission to override prices.")
                                    return redirect('create_multi_break_repair')
                                if not override_reason:
                                    messages.error(request, f"Break {i+1}: Override reason is required when setting a custom price.")
                                    return redirect('create_multi_break_repair')
                                if requesting_tech.approval_limit and override_amount > requesting_tech.approval_limit:
                                    messages.error(
                                        request,
                                        f"Break {i+1}: Override amount ${override_amount} exceeds your approval limit of ${requesting_tech.approval_limit}."
                                    )
                                    return redirect('create_multi_break_repair')
                            else:
                                # Technicians and viewers cannot override pricing.
                                messages.error(request, f"Break {i+1}: You don't have permission to override prices.")
                                return redirect('create_multi_break_repair')
                            break_price = override_amount
                        except (ValueError, InvalidOperation):
                            messages.error(request, f"Break {i+1}: Invalid override price format.")
                            return redirect('create_multi_break_repair')

                    repair = Repair(
                        tenant=tenant,
                        technician=technician,
                        customer=customer,
                        unit_number=unit_number,
                        service_date=repair_date,
                        damage_type=damage_type,
                        drilled_before_repair=drilled_before,
                        windshield_temperature=Decimal(windshield_temp) if windshield_temp else None,
                        resin_viscosity=resin_viscosity,
                        technician_notes=notes,
                        damage_photo_before=photo_before,
                        damage_photo_after=photo_after,
                        cost_override=Decimal(cost_override) if cost_override else None,
                        override_reason=override_reason,
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
                        pass

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
                        raise

            total_cost = sum(r.cost for r in created_repairs)
            logger.info(f"[MULTI-BREAK] Transaction complete - {len(created_repairs)} repairs created, total_cost=${total_cost}")

            status = created_repairs[0].queue_status
            is_auto_approved = status == 'APPROVED'

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
        # GET request
        tenant = getattr(request, 'tenant', None)
        customer_qs = Customer.objects.select_related('tenant')
        if tenant:
            customer_qs = customer_qs.filter(tenant=tenant)

        else:
            customer_qs = customer_qs.none()
        # Get technicians for admin selector
        technicians = []
        if user_is_admin:
            tech_qs = Technician.objects.filter(is_active=True).select_related('user')
            if tenant:
                tech_qs = tech_qs.filter(tenant=tenant)
            technicians = tech_qs.order_by('user__first_name')

        return render(request, 'technician_portal/multi_break_repair_form.html', {
            'is_admin': user_is_admin,
            'customers': customer_qs.order_by('name'),
            'damage_types': Repair.DAMAGE_TYPE_CHOICES,
            'technicians': technicians,
        })


@technician_required
@transaction.atomic
def convert_to_batch(request, repair_id):
    """Convert a single repair into a multi-break batch by adding additional breaks."""
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)
    qs = Repair.objects.select_related('customer', 'technician__user', 'tenant')
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    original_repair = get_object_or_404(qs, id=repair_id)

    if not user_is_admin:
        # Scope the Technician lookup to the current tenant — unscoped
        # request.user.technician resolves via OneToOneField and could return
        # a record from a different shop (CODE-084 / same family as CODE-082).
        current_tech = Technician.objects.filter(
            user=request.user, tenant=tenant
        ).first() if tenant else None
        if not current_tech:
            messages.error(request, "You don't have permission to modify this repair.")
            return redirect('repair_detail', repair_id=repair_id)

        if original_repair.technician_id != current_tech.id:
            messages.error(request, "You can only modify repairs assigned to you.")
            return redirect('repair_detail', repair_id=repair_id)

    if original_repair.repair_batch_id:
        messages.error(request, "This repair is already part of a batch.")
        return redirect('technician_batch_detail', batch_id=original_repair.repair_batch_id)

    if original_repair.queue_status not in ['APPROVED', 'IN_PROGRESS']:
        messages.error(request, "Only approved or in-progress repairs can be converted to batches.")
        return redirect('repair_detail', repair_id=repair_id)

    if request.method == 'POST':
        try:
            additional_breaks = int(request.POST.get('additional_breaks', 0))

            if additional_breaks < 1:
                messages.error(request, "You must add at least 1 additional break.")
                return redirect('convert_to_batch', repair_id=repair_id)

            batch_id = uuid.uuid4()
            total_breaks_in_batch = 1 + additional_breaks

            original_repair.repair_batch_id = batch_id
            original_repair.break_number = 1
            original_repair.total_breaks_in_batch = total_breaks_in_batch
            original_repair.save()

            logger.info(f"Converted repair {repair_id} to batch {batch_id}, adding {additional_breaks} breaks")

            unit_count = UnitRepairCount.objects.get_or_create(
                tenant=original_repair.tenant,
                customer=original_repair.customer,
                unit_number=original_repair.unit_number
            )[0]
            starting_count = unit_count.repair_count

            created_repairs = [original_repair]

            for i in range(additional_breaks):
                break_number = i + 2
                repair_count_for_this_break = starting_count + break_number

                damage_type = request.POST.get(f'damage_type_{i}')
                if not damage_type:
                    raise ValueError(f"Damage type is required for break {break_number}")

                from apps.technician_portal.services import pricing_service
                cost = pricing_service.calculate_repair_cost(
                    original_repair.customer,
                    repair_count_for_this_break
                )

                override_cost = request.POST.get(f'override_cost_{i}')
                override_reason = request.POST.get(f'override_reason_{i}')

                if override_cost:
                    try:
                        override_cost_decimal = Decimal(override_cost)

                        # Determine the *requesting user's* role (not the assigned
                        # technician's).  Previously this checked
                        # `request.user.technician.is_manager` which is wrong for two
                        # reasons:
                        # 1. The attribute is not tenant-scoped — a user who is Manager
                        #    at Shop A but plain Technician at Shop B could have
                        #    is_manager=True from the OneToOne Technician record for Shop A
                        #    and bypass the price-override guard on Shop B repairs.
                        # 2. Owners/superusers who have no Technician record would
                        #    AttributeError at `request.user.technician` if user_is_admin
                        #    were ever False (defensive fix).
                        # (CODE-059)
                        requesting_role = get_user_role(request.user, tenant=tenant)
                        if requesting_role in ('superuser', 'owner'):
                            # Owners/superusers can always override; no approval_limit.
                            cost = override_cost_decimal
                        elif requesting_role == 'manager':
                            # Use tenant-scoped lookup so a manager from another shop
                            # cannot bleed their can_override_pricing=True into this
                            # tenant via the OneToOne Technician relation. (CODE-059)
                            requesting_tech = (
                                Technician.objects.filter(user=request.user, tenant=tenant).first()
                                if tenant else None
                            )
                            if not (requesting_tech and requesting_tech.can_override_pricing):
                                raise ValueError("You don't have permission to override prices")
                            # approval_limit=None means unlimited; comparison requires non-None
                            if requesting_tech.approval_limit is not None and override_cost_decimal > requesting_tech.approval_limit:
                                raise ValueError(f"Override amount ${override_cost} exceeds your approval limit of ${requesting_tech.approval_limit}")
                            cost = override_cost_decimal
                        else:
                            raise ValueError("Only managers with override pricing permission can override prices")

                        if not override_reason:
                            raise ValueError("Override reason is required when overriding price")

                    except (InvalidOperation, ValueError) as e:
                        raise ValueError(f"Invalid override cost for break {break_number}: {str(e)}")

                new_repair = Repair(
                    tenant=original_repair.tenant,  # Copy tenant from original repair
                    customer=original_repair.customer,
                    unit_number=original_repair.unit_number,
                    technician=original_repair.technician,
                    damage_type=damage_type,
                    service_date=original_repair.service_date,
                    cost=cost,
                    queue_status=original_repair.queue_status,
                    repair_batch_id=batch_id,
                    break_number=break_number,
                    total_breaks_in_batch=total_breaks_in_batch,
                    technician_notes=request.POST.get(f'notes_{i}', ''),
                    windshield_temperature=request.POST.get(f'windshield_temperature_{i}') or None,
                    resin_viscosity=request.POST.get(f'resin_viscosity_{i}') or '',
                    drilled_before_repair=request.POST.get(f'drilled_before_repair_{i}') == 'on',
                    override_reason=override_reason if override_cost else '',
                )

                photo_before = request.FILES.get(f'photo_before_{i}')
                photo_after = request.FILES.get(f'photo_after_{i}')

                if photo_before:
                    new_repair.damage_photo_before = convert_heic_to_jpeg(photo_before)
                if photo_after:
                    new_repair.damage_photo_after = convert_heic_to_jpeg(photo_after)

                new_repair.save()
                created_repairs.append(new_repair)

                unit_count.repair_count += 1
                unit_count.save()

                logger.info(f"Created additional repair {new_repair.id} - Break {break_number}/{total_breaks_in_batch}")

            total_cost = sum(r.cost for r in created_repairs)

            messages.success(
                request,
                f"Successfully converted to batch! Added {additional_breaks} break{'s' if additional_breaks > 1 else ''} "
                f"to Unit {original_repair.unit_number} (${total_cost:.2f} total)."
            )

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
        return render(request, 'technician_portal/convert_to_batch_form.html', {
            'repair': original_repair,
            'damage_types': Repair.DAMAGE_TYPE_CHOICES,
            'is_admin': user_is_admin,
        })
