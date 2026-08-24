"""
Repair CRUD, list, detail, and status management views.
"""

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from decimal import Decimal, InvalidOperation
import logging
import uuid

from apps.technician_portal.models import Technician, Repair, TechnicianNotification
from apps.customer_portal.models import RepairApproval, CustomerUser
from core.models import Customer
from apps.technician_portal.forms import RepairForm
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from apps.technician_portal.services.assignments import (
    assign_job, notify_bulk_assignment,
)
from common.auth import get_user_role
from common.utils import convert_heic_to_jpeg
from core.notification_text import on_vehicle

logger = logging.getLogger(__name__)


def can_view_repair(repair, technician, user_is_admin=False):
    """Whether this user may open the repair's detail page.

    Mirrors the access gate in repair_detail() below, minus its HTTP_REFERER
    escape hatch — so this is deliberately the more conservative of the two.
    Erring towards False only costs a redirect to the dashboard, whereas
    erring towards True would bounce the user twice and stack two error
    messages on top of each other.
    """
    if user_is_admin:
        return True
    if not technician:
        return False
    if repair.queue_status == 'PENDING':
        return repair.technician == technician or technician.is_manager
    if repair.queue_status == 'REQUESTED':
        return technician.is_manager
    if repair.technician == technician:
        return True
    return bool(
        technician.is_manager
        and repair.technician
        and technician.manages_technician(repair.technician)
    )


def deny(request, message, repair=None, technician=None, user_is_admin=False):
    """Refuse an action without throwing the user out of context.

    Being told "only managers can do that" and landing on the dashboard means
    losing your place and navigating back to the job by hand — on a phone, in
    a parking lot. When the user can still see the repair, keep them on it so
    the message lands next to the thing it is about.
    """
    messages.error(request, message)
    if repair is not None and can_view_repair(repair, technician, user_is_admin):
        return redirect('repair_detail', repair_id=repair.id)
    return redirect('technician_dashboard')


def _check_duplicate_individual(form, tenant):
    """Duplicate-suggest flow for the repair form's individual toggle.

    If the new individual's name/phone matches an existing individual and the
    tech hasn't confirmed "different person", attach a field error suggesting
    the existing record (with history) — people share names, so we never
    error-and-block or silently create "John Smith (2)" anymore.
    """
    from apps.technician_portal.services.customer_service import (
        find_individual_matches, service_summary,
    )
    if not form.cleaned_data.get('is_walkin'):
        return
    if form.cleaned_data.get('confirmed_new_customer'):
        return
    matches = find_individual_matches(
        tenant,
        name=form.cleaned_data.get('walkin_name'),
        phone=form.cleaned_data.get('walkin_phone'),
    )
    if matches:
        m = matches[0]
        summary = service_summary(m)
        detail = f" — {summary}" if summary else ""
        form.add_error(
            'walkin_name',
            f'Looks like {m.name} is already a customer{detail}. '
            f'Pick them from the customer dropdown instead, or check '
            f'"This is a different person" to add a new record.',
        )


def _invoice_recipient_email(customer):
    """Recipient the send-invoice confirmation dialog should display."""
    from apps.billing.services.invoice_send_service import InvoiceSendService
    return InvoiceSendService.resolve_recipient(customer)


def _invoice_sms_context(customer, tenant):
    """Context the send-invoice dialog needs to offer "Also text it"."""
    from apps.billing.services.invoice_send_service import InvoiceSendService
    return {
        'invoice_sms_ready': InvoiceSendService.sms_ready(tenant),
        'invoice_sms_phone': InvoiceSendService.resolve_recipient_phone(customer),
    }


@technician_required
def repair_detail(request, repair_id):
    """Display repair details with permission checks and batch context."""
    tenant = getattr(request, 'tenant', None)
    # Cache the admin check to avoid a duplicate TenantMembership query in the
    # permission block (line ~193) and the context dict (line ~248).
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)
    qs = Repair.objects.select_related('customer', 'technician__user', 'warranty_policy')
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repair = get_object_or_404(qs, id=repair_id)

    can_update_status = False
    can_assign_repair = False
    can_reassign_to_self = False
    technician = None

    if hasattr(request.user, 'technician'):
        # Use tenant-scoped lookup so a manager at Shop A doesn't pass
        # is_manager checks when viewing Shop B's repairs. (CODE-077)
        technician = (
            Technician.objects.filter(user=request.user, tenant=tenant).first()
            if tenant else request.user.technician
        )

        if technician:
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

    if not user_is_admin:
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
            batch_summary = Repair.get_batch_summary(repair.repair_batch_id, tenant=tenant)
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

    # Check if this repair has already been invoiced (for Generate Invoice button)
    is_invoiced = False
    invoice_id = None
    if repair.queue_status == 'COMPLETED':
        from apps.billing.models import InvoiceLineItem
        line_item = InvoiceLineItem.objects.filter(
            repair=repair,
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
        ).select_related('invoice').first()
        if line_item:
            is_invoiced = True
            invoice_id = line_item.invoice_id

    # Default payment terms for generate-invoice dropdown (CODE-153)
    default_payment_terms = 'COD'
    if tenant:
        try:
            from apps.billing.models import BillingConfig
            bc = BillingConfig.get_for_tenant(tenant)
            default_payment_terms = bc.default_payment_terms
        except Exception:
            pass

    available_technicians = []
    if tenant:
        available_technicians = Technician.objects.filter(
            tenant=tenant, is_active=True
        ).select_related('user').order_by('user__first_name')

    return render(request, 'technician_portal/repair_detail.html', {
        'repair': repair,
        'TIME_ZONE': timezone.get_current_timezone_name(),
        'is_admin': user_is_admin,
        'can_update_status': can_update_status,
        'can_assign_repair': can_assign_repair,
        'can_reassign_to_self': can_reassign_to_self,
        'technician': technician,
        'batch_info': batch_info,
        'next_break': next_break,
        'is_invoiced': is_invoiced,
        'invoice_id': invoice_id,
        'default_payment_terms': default_payment_terms,
        'available_technicians': available_technicians,
        'invoice_recipient_email': _invoice_recipient_email(repair.customer),
        **_invoice_sms_context(repair.customer, tenant),
    })


@technician_required
def create_repair(request):
    """Create a new single repair."""
    # Usage limit check
    tenant = getattr(request, 'tenant', None)
    if tenant and not tenant.offers_repairs:
        # New repairs only for shops that offer them (existing ones stay
        # viewable via repair_list/detail for history).
        messages.info(request, 'Your shop is set to replacements only. You can change this under Settings → What does your shop do?')
        return redirect('technician_dashboard')
    if tenant:
        from apps.tenants.services.usage_service import UsageService
        can_create, limit_msg = UsageService(tenant).can_create_repair()
        if not can_create:
            messages.warning(request, limit_msg)
            return redirect('technician_dashboard')

    # Cache the admin check — avoids duplicate TenantMembership query in the POST branch.
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    # Guard: admin/owner with no technicians yet — show friendly error instead of
    # broken empty-dropdown form (BUG-001).
    if user_is_admin:
        has_active_technicians = Technician.objects.filter(
            tenant=tenant, is_active=True
        ).exists() if tenant else Technician.objects.filter(is_active=True).exists()
        if not has_active_technicians:
            messages.warning(
                request,
                "No active technicians found. Please add at least one technician "
                "before creating repairs."
            )
            return redirect('technician_dashboard')

    # Guard: non-admin user without a technician profile — redirect gracefully
    # instead of crashing on POST with an AttributeError (BUG-001).
    # Use tenant-scoped lookup so a technician from Shop A visiting Shop B's portal
    # doesn't slip through as if they belong here. (CODE-082)
    else:
        _scoped_tech = (
            Technician.objects.filter(user=request.user, tenant=tenant).first()
            if tenant else None
        )
        if not _scoped_tech:
            messages.error(
                request,
                "You don't have a technician profile yet. "
                "Please contact an administrator to set up your account."
            )
            return redirect('technician_dashboard')

    if request.method == 'POST':
        # Convert HEIC images to JPEG
        if 'damage_photo_before' in request.FILES:
            request.FILES['damage_photo_before'] = convert_heic_to_jpeg(request.FILES['damage_photo_before'])
        if 'damage_photo_after' in request.FILES:
            request.FILES['damage_photo_after'] = convert_heic_to_jpeg(request.FILES['damage_photo_after'])

        form = RepairForm(request.POST, request.FILES, user=request.user, tenant=getattr(request, 'tenant', None))
        from apps.technician_portal.views.jobs import _parse_extra_charges, _save_extra_charges
        charges, charge_error = _parse_extra_charges(request)
        if form.is_valid():
            # Suggest an existing individual before creating a duplicate; adds
            # a field error (making the form invalid) when a match is found.
            _check_duplicate_individual(form, getattr(request, 'tenant', None))
        if form.is_valid() and charge_error:
            form.add_error(None, charge_error)
        if form.is_valid():
            # Individual repair: auto-create an individual Customer record
            # from the provided name/phone so downstream pricing, approval, and
            # invoicing behave exactly like any other individual customer.
            walkin_customer = None
            if form.cleaned_data.get('is_walkin'):
                from apps.technician_portal.services.customer_service import create_individual
                walkin_customer = create_individual(
                    getattr(request, 'tenant', None),
                    name=form.cleaned_data.get('walkin_name') or 'Walk-in Customer',
                    phone=form.cleaned_data.get('walkin_phone'),
                    email=form.cleaned_data.get('walkin_email'),
                )
            if user_is_admin:
                if form.cleaned_data.get('technician'):
                    repair = form.save(commit=False)
                    repair.technician = form.cleaned_data.get('technician')
                    repair.tenant = getattr(request, 'tenant', None)
                    if walkin_customer:
                        repair.customer = walkin_customer

                    # Repair.save() auto-approves shop-created work unless the
                    # customer explicitly requires approval
                    repair._assignment_actor_user_id = request.user.id
                    repair.save()
                    form.save_m2m()
                    if repair.queue_status == 'PENDING':
                        messages.warning(request, "This customer requires approval for repairs. Repair submitted for customer approval.")
                    messages.success(request, f"Repair has been created and assigned to {repair.technician.user.get_full_name()}")
                else:
                    messages.error(request, "As an admin, you must select a technician to assign the repair to.")
                    tenant = getattr(request, 'tenant', None)
                    from apps.technician_portal.models import FeePreset as _FeePreset
                    return render(request, 'technician_portal/repair_form.html', {
                        'form': form,
                        'is_admin': True,
                        'technicians': Technician.objects.filter(
                            tenant=tenant, can_repair=True, is_active=True
                        ) if tenant else Technician.objects.filter(can_repair=True, is_active=True),
                        'show_charges_editor': True,
                        'charge_rows': charges,
                        'fee_presets': _FeePreset.objects.filter(tenant=tenant, is_active=True) if tenant else [],
                    })
            else:
                try:
                    repair = form.save(commit=False)
                    # Use the tenant-scoped Technician cached above — avoids assigning
                    # a cross-tenant Technician (Shop A) to a Shop B repair. (CODE-082)
                    repair.technician = _scoped_tech
                    repair.tenant = getattr(request, 'tenant', None)
                    if walkin_customer:
                        repair.customer = walkin_customer

                    # Repair.save() auto-approves shop-created work unless the
                    # customer explicitly requires approval
                    repair._assignment_actor_user_id = request.user.id
                    repair.save()
                    form.save_m2m()
                    if repair.queue_status == 'PENDING':
                        messages.warning(request, "This customer requires approval for field repairs. Repair submitted for customer approval.")

                    # If no technician was explicitly set (shouldn't happen here
                    # since we default to request.user.technician, but safety net)
                    if not repair.technician_id:
                        from apps.tenants.services.assignment_service import auto_assign_repair
                        auto_assign_repair(repair)

                except AttributeError:
                    messages.error(request, "You don't have a technician profile to create repairs.")
                    return redirect('technician_dashboard')

            if charges:
                _save_extra_charges(repair, charges, tenant, taxable=not repair.no_tax)

            messages.success(request, f'Repair #{repair.id} created successfully!')
            return redirect('repair_detail', repair_id=repair.id)
        else:
            logger.debug(f"Form errors: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        initial = {}
        customer_id = request.GET.get('customer_id')
        if customer_id and tenant:
            try:
                customer = Customer.objects.get(id=customer_id, tenant=tenant)
                initial['customer'] = customer.id
                if customer.primary_technician_id:
                    initial['technician'] = customer.primary_technician_id
            except Customer.DoesNotExist:
                pass
        form = RepairForm(user=request.user, tenant=getattr(request, 'tenant', None), initial=initial)

    pending_repair_warning = form.errors.get('__all__')

    expected_cost = None
    if hasattr(form, 'instance') and form.instance.customer and form.instance.unit_number:
        expected_cost = form.instance.get_expected_price()

    admin = user_is_admin  # already computed above; reuse cached value

    # Build customer types dict for JavaScript
    import json
    # No tenant context → no customers (never leak other shops' data)
    customers_qs = Customer.objects.filter(tenant=tenant) if tenant else Customer.objects.none()
    customer_types_json = json.dumps({
        str(c.id): c.customer_type for c in customers_qs
    })
    # Map customer → primary technician ID for JS auto-selection on repair form
    customer_primary_tech_json = json.dumps({
        str(c.id): c.primary_technician_id
        for c in customers_qs if c.primary_technician_id
    })
    # Tenant-scoped Technician for the current user — used by the template to
    # check is_manager without falling back to the unscoped OneToOneField
    # reverse accessor (user.technician) which could return a record from a
    # different shop.  (CODE-108)
    current_technician = (
        Technician.objects.filter(user=request.user, tenant=tenant).first()
        if tenant else None
    )
    from apps.technician_portal.models import FeePreset
    context = {
        'form': form,
        'pending_repair_warning': pending_repair_warning,
        'is_admin': admin,
        'expected_cost': expected_cost,
        'customer_types_json': customer_types_json,
        'customer_primary_tech_json': customer_primary_tech_json,
        'current_technician': current_technician,
        'show_charges_editor': True,
        'charge_rows': [
            (d.strip(), a.strip())
            for d, a in zip(request.POST.getlist('charge_desc'),
                            request.POST.getlist('charge_amount'))
            if d.strip() or a.strip()
        ] if request.method == 'POST' else [],
        'fee_presets': FeePreset.objects.filter(tenant=tenant, is_active=True) if tenant else [],
    }
    if admin:
        context['technicians'] = Technician.objects.filter(
            tenant=tenant, can_repair=True, is_active=True
        ) if tenant else Technician.objects.filter(can_repair=True, is_active=True)
    try:
        return render(request, 'technician_portal/repair_form.html', context)
    except Exception as e:
        logger.error(f"[REPAIR-FORM] Template render error: {e}", exc_info=True)
        from django.http import HttpResponse
        if settings.DEBUG:
            raise
        return HttpResponse(f"<h1>Repair Form Error</h1><pre>{e}</pre>", status=500)


@technician_required
def update_repair(request, repair_id):
    """Update an existing repair with permission and security checks."""
    tenant = getattr(request, 'tenant', None)
    # Cache admin check — called up to 4× in this view.
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    if not user_is_admin:
        if not hasattr(request.user, 'technician'):
            messages.error(request, "You don't have a technician profile to manage repairs.")
            return redirect('technician_dashboard')

        qs = Repair.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        else:
            qs = qs.none()
        repair = get_object_or_404(qs, id=repair_id)
        logger.info(f"UPDATE_REPAIR: Got repair #{repair.id}, technician_id={repair.technician_id}")

        # Scope Technician lookup to current tenant to prevent cross-tenant is_manager bypass (CODE-076)
        _scoped_tech_ur = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
        user_is_manager = bool(_scoped_tech_ur and _scoped_tech_ur.is_manager)
        if repair.queue_status in ['COMPLETED', 'DENIED'] and not user_is_manager:
            messages.error(request, "This repair is closed and cannot be edited. Contact a manager if photos need to be added.")
            return redirect('repair_detail', repair_id=repair.id)

        if not repair.technician_id:
            messages.error(request, "This repair has not been assigned yet and cannot be edited by technicians.")
            return redirect('repair_detail', repair_id=repair.id)

        # Use the tenant-scoped record computed above (_scoped_tech_ur) so that a
        # technician from Shop A cannot pass this gate when editing Shop B repairs.
        # request.user.technician would return Shop A's Technician (wrong shop). (CODE-082)
        if not _scoped_tech_ur or repair.technician_id != _scoped_tech_ur.id:
            messages.error(request, "You can only edit repairs assigned to you.")
            return redirect('repair_detail', repair_id=repair.id)
    else:
        qs = Repair.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        else:
            qs = qs.none()
        repair = get_object_or_404(qs, id=repair_id)

    if request.method == 'POST':
        logger.info(f"UPDATE_REPAIR POST: Processing form for repair #{repair.id}")

        if 'damage_photo_before' in request.FILES:
            request.FILES['damage_photo_before'] = convert_heic_to_jpeg(request.FILES['damage_photo_before'])
        if 'damage_photo_after' in request.FILES:
            request.FILES['damage_photo_after'] = convert_heic_to_jpeg(request.FILES['damage_photo_after'])

        original_technician_id = repair.technician_id
        logger.info(f"UPDATE_REPAIR: Saved original_technician_id={original_technician_id}")

        # Capture BEFORE form binding — RepairForm(instance=repair) mutates
        # this same instance in place.
        was_completed_before = repair.queue_status == 'COMPLETED'

        form = RepairForm(request.POST, request.FILES, instance=repair, user=request.user, tenant=getattr(request, 'tenant', None))

        # Extra charges are editable until the job lands on a live invoice;
        # after that they're managed on the invoice (Add Line Item).
        from apps.billing.services.invoice_sync import live_invoice_number_for_service
        from apps.technician_portal.views.jobs import _parse_extra_charges, _save_extra_charges
        charges_locked_invoice = live_invoice_number_for_service(repair)
        charges, charge_error = _parse_extra_charges(request)
        if not charges_locked_invoice and charge_error and form.is_valid():
            form.add_error(None, charge_error)

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

            if not user_is_admin:
                logger.info(f"UPDATE_REPAIR: Restoring technician_id from original_technician_id={original_technician_id}")
                updated_repair.technician_id = original_technician_id
            elif form.cleaned_data.get('technician'):
                updated_repair.technician = form.cleaned_data.get('technician')

            # Auto-complete if IN_PROGRESS with after photo
            if updated_repair.queue_status == 'IN_PROGRESS' and updated_repair.damage_photo_after:
                updated_repair.queue_status = 'COMPLETED'
                logger.info(f"UPDATE_REPAIR: Auto-completing repair #{updated_repair.id} (has after photo)")
                messages.success(request, "Repair marked as COMPLETED! (After photo uploaded)")

            # Use a waiting reward the user picked on the form. Applied BEFORE
            # save so a completion in this same save fulfills it and the
            # invoice picks up the discount.
            apply_redemption_id = request.POST.get('apply_redemption_id')
            if apply_redemption_id:
                from apps.rewards_referrals.models import RewardRedemption
                chosen = RewardRedemption.objects.filter(
                    pk=apply_redemption_id,
                    reward__customer=updated_repair.customer,
                    reward__customer__tenant=tenant,
                    status='PENDING',
                    applied_to_repair__isnull=True,
                    applied_to_replacement__isnull=True,
                ).select_related('reward_option').first()
                if chosen is not None:
                    acting_tech = (
                        Technician.objects.filter(user=request.user, tenant=tenant).first()
                        if tenant else None
                    )
                    applied_ok, apply_msg = updated_repair.apply_reward(
                        chosen, technician=acting_tech,
                    )
                    if applied_ok:
                        messages.success(request, f"Reward applied: {chosen.reward_option.name}.")
                    else:
                        messages.error(request, apply_msg)
                else:
                    messages.error(request, "That reward is no longer available to apply.")

            # Assignment signal: if the admin changed the technician on this
            # form, notify the techs — but never the actor about themselves.
            updated_repair._assignment_actor_user_id = request.user.id
            updated_repair.save()
            form.save_m2m()

            # Completed just now and the customer still has an unused waiting
            # reward? Say so — nothing is applied silently anymore.
            if updated_repair.queue_status == 'COMPLETED' and not was_completed_before:
                from apps.rewards_referrals.models import RewardRedemption
                leftover = RewardRedemption.objects.filter(
                    reward__customer=updated_repair.customer,
                    status='PENDING',
                    applied_to_repair__isnull=True,
                    applied_to_replacement__isnull=True,
                    reward_option__reward_type__category__in=['REPAIR_DISCOUNT', 'FREE_SERVICE'],
                ).select_related('reward_option').first()
                if leftover is not None:
                    messages.info(
                        request,
                        f"{updated_repair.customer.name} still has a waiting reward "
                        f"({leftover.reward_option.name}) — it stays available for a future job.",
                    )

            if not charges_locked_invoice:
                _save_extra_charges(
                    updated_repair, charges, tenant,
                    taxable=not updated_repair.no_tax,
                )

            messages.success(request, "Repair has been updated successfully.")

            # Batch navigation
            if updated_repair.repair_batch_id:
                batch_summary = Repair.get_batch_summary(updated_repair.repair_batch_id, tenant=tenant)
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
        form = RepairForm(instance=repair, user=request.user, tenant=getattr(request, 'tenant', None))

        if repair.queue_status == 'COMPLETED':
            # Scope Technician lookup to current tenant to prevent cross-tenant bypass (CODE-076)
            _scoped_tech_ur2 = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
            user_is_manager = (user_is_admin or bool(_scoped_tech_ur2 and _scoped_tech_ur2.is_manager))
            if user_is_manager:
                messages.info(request, "You're editing a completed repair. You can add or update photos for documentation/AI training purposes.")

    expected_cost = repair.get_expected_price() if repair.customer and repair.unit_number else None

    batch_id = request.GET.get('batch_id') or request.POST.get('batch_id')
    batch_repairs = []
    if batch_id and repair.repair_batch_id:
        batch_repairs = Repair.objects.filter(
            repair_batch_id=repair.repair_batch_id
        ).order_by('break_number')

    admin = user_is_admin  # reuse cached value
    # Tenant-scoped Technician for the current user — prevents the template from
    # using the bare user.technician OneToOneField which could resolve to a
    # Technician from a different shop.  (CODE-108)
    current_technician = (
        Technician.objects.filter(user=request.user, tenant=tenant).first()
        if tenant else None
    )
    # Extra-charge editor state (shared by GET render and bounced POST render)
    from apps.billing.services.invoice_sync import live_invoice_number_for_service as _live_inv
    from apps.technician_portal.models import FeePreset
    charges_locked_invoice = _live_inv(repair)
    if request.method == 'POST' and not charges_locked_invoice:
        charge_rows = [
            (d.strip(), a.strip())
            for d, a in zip(request.POST.getlist('charge_desc'),
                            request.POST.getlist('charge_amount'))
            if d.strip() or a.strip()
        ]
    else:
        charge_rows = [(c.description, c.amount) for c in repair.extra_charges.all()]

    # Waiting discount rewards the user can choose to put on this job.
    # Replaces the old silent auto-apply-on-completion (see
    # Repair.apply_available_rewards / LoyaltyConfig.auto_apply_rewards).
    pending_reward_redemptions = []
    if repair.customer_id and not repair.applied_rewards.exists():
        from apps.rewards_referrals.models import RewardRedemption
        pending_reward_redemptions = list(
            RewardRedemption.objects.filter(
                reward__customer_id=repair.customer_id,
                status='PENDING',
                applied_to_repair__isnull=True,
                applied_to_replacement__isnull=True,
                reward_option__reward_type__category__in=['REPAIR_DISCOUNT', 'FREE_SERVICE'],
            ).select_related('reward_option', 'reward_option__reward_type').order_by('created_at')
        )

    update_context = {
        'form': form,
        'repair': repair,
        'is_admin': admin,
        'expected_cost': expected_cost,
        'batch_id': batch_id,
        'batch_repairs': batch_repairs,
        'current_technician': current_technician,
        'show_charges_editor': True,
        'charges_locked_invoice': charges_locked_invoice,
        'charge_rows': charge_rows,
        'fee_presets': FeePreset.objects.filter(tenant=tenant, is_active=True) if tenant else [],
        'pending_reward_redemptions': pending_reward_redemptions,
    }
    if admin:
        update_context['technicians'] = Technician.objects.filter(
            tenant=tenant, can_repair=True, is_active=True
        ) if tenant else Technician.objects.filter(can_repair=True, is_active=True)
    return render(request, 'technician_portal/repair_form.html', update_context)


@technician_required
def update_queue_status(request, repair_id):
    """Update repair queue status with permission checks."""
    tenant = getattr(request, 'tenant', None)
    # Cache admin check — called twice in this view (permission gate + POST branch).
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)
    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repair = get_object_or_404(qs, id=repair_id)

    if not user_is_admin:
        # Use tenant-scoped lookup — prevents a technician from Shop A passing permission
        # checks on Shop B repairs via the unscoped OneToOneField reverse relation. (CODE-082)
        technician = (
            Technician.objects.filter(user=request.user, tenant=tenant).first()
            if tenant else None
        )
        if not technician:
            messages.error(request, "You don't have a technician profile to update repairs.")
            return redirect('technician_dashboard')

        if repair.queue_status == 'PENDING':
            return deny(
                request,
                "This repair is pending customer approval, so it can't be changed yet.",
                repair, technician,
            )

        if repair.queue_status == 'REQUESTED':
            if not technician.is_manager:
                return deny(
                    request,
                    "Only managers can assign customer-requested repairs.",
                    repair, technician,
                )
        else:
            can_update = False
            if repair.technician == technician:
                can_update = True
            elif technician.is_manager and repair.technician and technician.manages_technician(repair.technician):
                # repair_detail sets can_reassign_to_self for exactly this case,
                # so the "Reassign to me" action is waiting where we land.
                return deny(
                    request,
                    "This job is assigned to another technician. Use \"Reassign to me\" to take it over.",
                    repair, technician,
                )

            if not can_update:
                return deny(
                    request,
                    "You don't have permission to update this repair.",
                    repair, technician,
                )

    old_status = repair.queue_status

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Repair.QUEUE_CHOICES):
            # D1: friendly rejection before the model layer raises. The
            # model's state machine (Repair.ALLOWED_STATUS_TRANSITIONS) is
            # the real enforcement — this just turns a would-be 500 into a
            # message. Blocks e.g. COMPLETED -> APPROVED -> COMPLETED
            # cycling, which re-awarded loyalty points on every cycle.
            if new_status != old_status:
                _allowed = Repair.ALLOWED_STATUS_TRANSITIONS.get(old_status, set())
                if new_status not in _allowed:
                    messages.error(
                        request,
                        f"Cannot change a {repair.get_queue_status_display()} "
                        f"repair to {dict(Repair.QUEUE_CHOICES)[new_status]}."
                    )
                    return redirect('repair_detail', repair_id=repair.id)
            if old_status == 'REQUESTED':
                # Auto-assign to the manager accepting the repair.
                # Use the tenant-scoped `technician` already resolved above so we
                # don't accidentally assign a cross-tenant Technician record. (CODE-082)
                if not user_is_admin and technician:
                    repair.technician = technician
                    messages.info(request, "Repair assigned to you.")

                repair.queue_status = new_status
                repair.save()

                # Create automatic approval record
                customer_users = CustomerUser.objects.filter(customer=repair.customer)
                customer_user = customer_users.filter(is_primary_contact=True).first()
                if not customer_user and customer_users.exists():
                    customer_user = customer_users.first()

                if customer_user:
                    RepairApproval.objects.update_or_create(
                        repair=repair,
                        defaults={
                            'approved': True,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': "Auto-approved as customer initiated the request",
                        }
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
                            override_amount = Decimal(cost_override)
                            # Permission check: only owners/superusers and authorised managers
                            # may set a custom price.  Plain technicians cannot override pricing
                            # regardless of what they POST. (CODE-058)
                            requesting_role = get_user_role(request.user, tenant=tenant)
                            override_allowed = False
                            if requesting_role in ('superuser', 'owner'):
                                override_allowed = True
                            elif requesting_role == 'manager':
                                # Use tenant-scoped lookup to prevent a cross-tenant
                                # manager from bleeding manager privileges into a shop
                                # where they're only a plain technician. (CODE-059;
                                # can_override_pricing is deprecated — never set by
                                # any signup/team path.)
                                requesting_tech = (
                                    Technician.objects.filter(user=request.user, tenant=tenant).first()
                                    if tenant else None
                                )
                                if requesting_tech:
                                    # Use `is not None` so approval_limit=0 still enforces the
                                    # limit; a truthy check would treat 0 as "no limit". (CODE-114)
                                    if requesting_tech.approval_limit is not None and override_amount > requesting_tech.approval_limit:
                                        messages.warning(
                                            request,
                                            f"Override amount ${override_amount} exceeds your approval limit of "
                                            f"${requesting_tech.approval_limit}. Price override was not applied."
                                        )
                                    else:
                                        override_allowed = True
                                else:
                                    messages.warning(request, "You don't have permission to override prices. Price override was not applied.")
                            else:
                                messages.warning(request, "You don't have permission to override prices. Price override was not applied.")

                            if override_allowed:
                                repair.cost_override = override_amount
                                repair.override_reason = override_reason or "Manual price adjustment"
                                messages.info(request, f"Custom price of ${cost_override} has been applied.")
                        except (ValueError, TypeError, InvalidOperation):
                            messages.warning(request, "Invalid custom price. Using automatic pricing.")

                repair.save()

                # CODE-262: Batch propagation — when admin approves/denies a
                # PENDING repair that's part of a batch, apply to all siblings.
                # Only for PENDING→APPROVED or PENDING→DENIED transitions (admin override).
                if (old_status == 'PENDING' and new_status in ('APPROVED', 'DENIED')
                        and repair.is_part_of_batch and repair.repair_batch_id and tenant):
                    sibling_repairs = Repair.objects.filter(
                        repair_batch_id=repair.repair_batch_id,
                        tenant=tenant,
                        queue_status='PENDING',
                    ).exclude(pk=repair.pk)
                    # D2: per-repair save(), not a queryset .update(). Bulk
                    # update skips Repair.save() and post_save signals, so
                    # siblings silently changed status with no customer
                    # notification and no tax/pricing bookkeeping. N+1 is
                    # acceptable at batch sizes (<= 20 breaks).
                    sibling_count = 0
                    with transaction.atomic():
                        for sibling in sibling_repairs:
                            sibling.queue_status = new_status
                            sibling.save()
                            sibling_count += 1
                    if sibling_count > 0:
                        action = 'approved' if new_status == 'APPROVED' else 'denied'
                        messages.info(request, f"Also {action} {sibling_count} other break(s) in this batch.")

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
    # Cache admin check — called twice in this view.
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    # Load the repair before the permission gate so a refusal can send the user
    # back to it instead of to the dashboard. Still tenant-scoped, so this
    # leaks nothing a later check would have caught.
    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repair = get_object_or_404(qs, id=repair_id)

    tech = None
    if not user_is_admin:
        # Scope to current tenant — prevents a manager from Shop A from acting
        # as manager in Shop B's portal context. (CODE-079)
        tech = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
        if not tech or not tech.is_manager:
            return deny(request, "Only managers can assign repairs.", repair, tech)
        if not tech.can_assign_work:
            return deny(request, "You do not have permission to assign repairs.", repair, tech)

    if repair.queue_status != 'REQUESTED':
        messages.error(request, "Only REQUESTED repairs can be assigned. This repair is already assigned.")
        return redirect('repair_detail', repair_id=repair.id)

    if request.method == 'POST':
        technician_id = request.POST.get('technician_id')

        if not technician_id:
            messages.error(request, "Please select a technician.")
            return redirect('assign_repair', repair_id=repair.id)

        try:
            tech_qs = Technician.objects.filter(id=technician_id)
            if tenant:
                tech_qs = tech_qs.filter(tenant=tenant)
            else:
                tech_qs = tech_qs.none()
            assigned_tech = tech_qs.get()

            if not user_is_admin:
                manager = Technician.objects.filter(user=request.user, tenant=tenant).first()
                if not manager or (assigned_tech.id != manager.id and not manager.manages_technician(assigned_tech)):
                    messages.error(request, "You can only assign repairs to yourself or technicians you manage.")
                    return redirect('assign_repair', repair_id=repair.id)

            # force_notify_new: the tech may already be provisionally set on
            # the REQUESTED job — accepting it is still news to them.
            assign_job(
                repair, assigned_tech,
                assigned_by=request.user,
                queue_status='APPROVED',
                force_notify_new=True,
            )

            # Create approval record
            customer_users = CustomerUser.objects.filter(customer=repair.customer)
            customer_user = customer_users.filter(is_primary_contact=True).first()
            if not customer_user and customer_users.exists():
                customer_user = customer_users.first()

            if customer_user:
                RepairApproval.objects.update_or_create(
                    repair=repair,
                    defaults={
                        'approved': True,
                        'approved_by': customer_user,
                        'approval_date': timezone.now(),
                        'notes': "Auto-approved - customer requested repair",
                    }
                )

            messages.success(request, f"Repair #{repair.id} assigned to {assigned_tech.user.get_full_name()}")
            return redirect('repair_detail', repair_id=repair.id)

        except Technician.DoesNotExist:
            messages.error(request, "Selected technician not found.")
            return redirect('assign_repair', repair_id=repair.id)

    # GET request
    if user_is_admin:
        tech_qs = Technician.objects.filter(is_active=True)
        if tenant:
            tech_qs = tech_qs.filter(tenant=tenant)
        else:
            tech_qs = tech_qs.none()
        available_technicians = tech_qs.order_by('user__first_name')
    else:
        # `tech` is already resolved and gated as a manager above.
        manager = tech
        managed_techs = manager.managed_technicians.filter(is_active=True)
        # Always apply tenant filter as defense-in-depth so that even if a
        # cross-tenant tech somehow ended up in managed_technicians (e.g. via
        # admin bypass or direct DB edit), they cannot appear in the assign
        # dropdown and cannot be assigned to this shop's repairs.
        tech_qs = Technician.objects.filter(
            Q(id=manager.id) | Q(id__in=managed_techs)
        ).filter(is_active=True)
        if tenant:
            tech_qs = tech_qs.filter(tenant=tenant)
        else:
            tech_qs = tech_qs.none()
        available_technicians = tech_qs.order_by('user__first_name')

    return render(request, 'technician_portal/assign_repair.html', {
        'repair': repair,
        'available_technicians': available_technicians,
    })


@technician_required
def reassign_to_self(request, repair_id):
    """Manager reassigns a team member's repair to themselves."""
    tenant = getattr(request, 'tenant', None)
    # Cache admin check — called 3× in this view.
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    # Load the repair first so a refusal can return the user to it, and resolve
    # the manager once — this view previously re-queried the same Technician row
    # three separate times.
    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repair = get_object_or_404(qs, id=repair_id)

    manager = None
    if not user_is_admin:
        # Scope to current tenant — prevents cross-tenant is_manager bypass. (CODE-079)
        manager = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
        if not manager or not manager.is_manager:
            return deny(request, "Only managers can reassign repairs.", repair, manager)
        if not manager.can_assign_work:
            return deny(request, "You do not have permission to reassign repairs.", repair, manager)

        if not repair.technician or not manager.manages_technician(repair.technician):
            return deny(
                request,
                "You can only reassign repairs from your managed technicians.",
                repair, manager,
            )

        if repair.technician.id == manager.id:
            return deny(request, "This repair is already assigned to you.", repair, manager)

    if request.method == 'POST':
        old_technician = repair.technician

        if not user_is_admin:
            # Notifies the old tech (repair_reassigned_away) and marks their
            # stale unread rows read; the manager assigned themselves, so no
            # self-notification.
            assign_job(repair, manager, assigned_by=request.user)

            messages.success(request, f"Repair reassigned from {old_technician.user.get_full_name()} to you.")
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
    else:
        qs = qs.none()
    existing_repair = qs.first()

    if existing_repair:
        return JsonResponse({
            'existing_repair': True,
            'status': existing_repair.get_queue_status_display(),
            'repair_id': existing_repair.id,
            'warning_message': f"There is already a {existing_repair.get_queue_status_display()} repair for this unit."
        })
    return JsonResponse({'existing_repair': False})


@technician_required
def bulk_repair_action(request):
    """Handle bulk approve or deny actions for multiple repairs (technician/manager)."""
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('job_list')

    tenant = getattr(request, 'tenant', None)
    is_admin = is_tenant_admin(request.user, tenant=tenant)

    # Use tenant-scoped Technician lookup so that a user who is is_manager=True
    # at Shop A cannot pass this gate while visiting Shop B's portal.
    # request.user.technician (bare OneToOneField) resolves globally — it would
    # return the Shop A Technician even on Shop B's request, allowing a cross-
    # tenant manager to bulk-approve Shop B repairs and be assigned as their
    # technician.  Fix: always scope to the current request tenant. (CODE-081)
    technician = (
        Technician.objects.filter(user=request.user, tenant=tenant).first()
        if tenant else None
    )

    # Admins (owners/managers via TenantMembership) may not have a Technician record —
    # that's fine.  Plain technicians without is_manager must be blocked.
    if not is_admin:
        if not technician:
            messages.error(request, "You don't have a technician profile.")
            return redirect('technician_dashboard')
        if not technician.is_manager:
            messages.error(request, "Only managers can perform bulk actions on repairs.")
            return redirect('job_list')

    action = request.POST.get('action')
    if action not in ['approve', 'deny', 'reset_to_pending']:
        messages.error(request, "Invalid action specified.")
        return redirect('job_list')

    repair_ids = request.POST.getlist('repair_ids')
    if not repair_ids:
        messages.error(request, "No repairs selected.")
        return redirect('job_list')

    with transaction.atomic():
        # Get repairs that are PENDING or REQUESTED (or any non-COMPLETED for reset)
        if action == 'reset_to_pending':
            repairs = Repair.objects.filter(
                id__in=repair_ids,
            ).exclude(queue_status='COMPLETED').select_related('customer', 'technician')
        else:
            repairs = Repair.objects.filter(
                id__in=repair_ids,
                queue_status__in=['PENDING', 'REQUESTED']
            ).select_related('customer', 'technician')

        if tenant:
            repairs = repairs.filter(tenant=tenant)
        else:
            repairs = repairs.none()

        if not repairs.exists():
            messages.error(request, "No valid repairs found to process.")
            return redirect('job_list')

        processed_count = 0

        for repair in repairs:
            if action == 'approve':
                # For REQUESTED repairs, assign to the acting technician (only if they have a
                # Technician record — admin-only users may not have one).
                if repair.queue_status == 'REQUESTED' and not repair.technician and technician:
                    repair.technician = technician

                repair.queue_status = 'APPROVED'
                # Assignment signal: don't notify the actor about jobs they
                # just assigned to themselves; do notify a pre-set tech that
                # their REQUESTED job is now approved.
                repair._assignment_actor_user_id = request.user.id
                repair.save()

                # Build actor display name for audit notes
                actor_name = (
                    technician.user.get_full_name() if technician
                    else request.user.get_full_name() or request.user.username
                )

                # Create approval record
                customer_users = CustomerUser.objects.filter(customer=repair.customer)
                customer_user = customer_users.filter(is_primary_contact=True).first()
                if not customer_user and customer_users.exists():
                    customer_user = customer_users.first()

                if customer_user:
                    RepairApproval.objects.update_or_create(
                        repair=repair,
                        defaults={
                            'approved': True,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': f'Bulk approved by {actor_name}'
                        }
                    )

                # Notify assigned technician if different from actor
                if repair.technician and repair.technician != technician:
                    TechnicianNotification.objects.create(
                        technician=repair.technician,
                        message=f"Repair #{repair.id} approved — {repair.customer.name}"
                        f"{on_vehicle(repair)}.",
                        read=False,
                        repair=repair
                    )

            elif action == 'deny':
                repair.queue_status = 'DENIED'
                repair.save()

                # Build actor display name for audit notes
                actor_name = (
                    technician.user.get_full_name() if technician
                    else request.user.get_full_name() or request.user.username
                )

                # Create denial record
                customer_users = CustomerUser.objects.filter(customer=repair.customer)
                customer_user = customer_users.filter(is_primary_contact=True).first()
                if not customer_user and customer_users.exists():
                    customer_user = customer_users.first()

                if customer_user:
                    RepairApproval.objects.update_or_create(
                        repair=repair,
                        defaults={
                            'approved': False,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': f'Bulk denied by {actor_name}'
                        }
                    )

                # Notify assigned technician if different from actor
                if repair.technician and repair.technician != technician:
                    TechnicianNotification.objects.create(
                        technician=repair.technician,
                        message=f"Repair #{repair.id} declined — {repair.customer.name}"
                        f"{on_vehicle(repair)}.",
                        read=False,
                        repair=repair
                    )

            elif action == 'reset_to_pending':
                if repair.queue_status == 'COMPLETED':
                    continue  # Skip completed
                repair.queue_status = 'PENDING'
                repair.save()

            processed_count += 1

        action_word = {"approve": "approved", "deny": "denied", "reset_to_pending": "reset to pending"}[action]
        messages.success(
            request,
            f"Successfully {action_word} {processed_count} repair{'' if processed_count == 1 else 's'}."
        )

    return redirect('job_list')


@technician_required
def tech_collect_payment(request, repair_id):
    """Record a payment collected by a technician on-site."""
    if request.method != 'POST':
        return redirect('repair_detail', repair_id=repair_id)

    tenant = getattr(request, 'tenant', None)
    qs = Repair.objects.select_related('customer')
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repair = get_object_or_404(qs, id=repair_id)

    # Find the invoice for this repair
    try:
        from apps.billing.models import InvoiceLineItem, Payment
        line_item = InvoiceLineItem.objects.filter(
            repair=repair,
            invoice__status__in=['SENT', 'PARTIAL', 'OVERDUE'], invoice__deleted_at__isnull=True,
        ).select_related('invoice').first()

        if not line_item:
            messages.error(request, "No unpaid invoice found for this repair.")
            return redirect('repair_detail', repair_id=repair_id)

        invoice = line_item.invoice

        # Parse and validate amount (basic sanity checks before acquiring the lock)
        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (InvalidOperation, ValueError):
            messages.error(request, "Invalid payment amount.")
            return redirect('repair_detail', repair_id=repair_id)

        if amount <= 0:
            messages.error(request, "Payment amount must be greater than zero.")
            return redirect('repair_detail', repair_id=repair_id)

        payment_method = request.POST.get('payment_method', 'CASH')
        valid_methods = ['CASH', 'CHECK', 'CREDIT_CARD', 'OTHER']
        if payment_method not in valid_methods:
            payment_method = 'CASH'

        reference_number = request.POST.get('reference_number', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Get tech name for the note
        tech_name = request.user.get_full_name() or request.user.username
        if notes:
            notes = f"Collected on-site by {tech_name}. {notes}"
        else:
            notes = f"Collected on-site by {tech_name}"

        # NOTE: The amount_due check must happen INSIDE a transaction with a row-level
        # lock to prevent a TOCTOU race where a concurrent Stripe webhook payment and
        # an on-site cash payment both read the same stale amount_due, both pass
        # validation, and both create payments — resulting in amount_paid > invoice.total.
        # This is the same pattern used in owner_record_payment (CODE-056 / CODE-059).
        payment = None
        try:
            with transaction.atomic():
                # Re-read the invoice under an exclusive row lock so our amount_due
                # check reflects any payment that may have committed since we fetched
                # the line_item above (e.g. a Stripe webhook payment_intent.succeeded).
                from apps.billing.models import Invoice
                invoice_locked = Invoice.objects.select_for_update().get(pk=invoice.pk)

                # Re-check status inside the lock (it could have become PAID concurrently)
                if invoice_locked.status in ('PAID', 'CANCELLED'):
                    raise ValueError(
                        f"Cannot record payment — invoice is {invoice_locked.get_status_display()}."
                    )

                if amount > invoice_locked.amount_due:
                    raise ValueError(
                        f"Amount exceeds balance due (${invoice_locked.amount_due:.2f})."
                    )

                payment = Payment.objects.create(
                    invoice=invoice_locked,
                    amount=amount,
                    payment_method=payment_method,
                    reference_number=reference_number,
                    payment_date=timezone.now().date(),
                    notes=notes,
                    recorded_by=request.user,
                )
                # Payment.save() already calls _update_invoice_totals() with its own lock

        except ValueError as e:
            messages.error(request, str(e))
            return redirect('repair_detail', repair_id=repair_id)

        # Send confirmation emails (best effort, outside the transaction)
        if payment:
            try:
                from apps.billing.services.payment_notification_service import PaymentNotificationService
                notification_svc = PaymentNotificationService()
                notification_svc.notify_payment(payment)
            except Exception as e:
                logger.warning(f"Payment notification failed for payment {payment.id}: {e}")

            messages.success(
                request,
                f"Payment of ${amount:.2f} ({payment.get_payment_method_display()}) recorded for invoice {invoice.invoice_number}."
            )

    except Exception as e:
        logger.error(f"Error recording tech payment for repair {repair_id}: {e}", exc_info=True)
        messages.error(request, "An error occurred recording the payment. Please try again.")

    return redirect('repair_detail', repair_id=repair_id)


# =============================================================================
# SOFT-DELETE / RESTORE / ARCHIVED VIEWS
# =============================================================================

@technician_required
def delete_repair(request, repair_id):
    """
    Soft-delete a repair. Owner/manager only.
    Also soft-deletes all invoices that have line items pointing to this repair.
    Payments stay intact so a restore brings everything back; they're purged
    with the invoice after the 30-day window.
    POST only.
    """
    from django.views.decorators.http import require_POST
    from apps.billing.models import Invoice

    if request.method != 'POST':
        return redirect('repair_detail', repair_id=repair_id)

    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user, tenant=tenant):
        messages.error(request, "Only owners and managers can delete repairs.")
        return redirect('repair_detail', repair_id=repair_id)

    qs = Repair.objects.filter(tenant=tenant) if tenant else Repair.objects.none()
    repair = get_object_or_404(qs, id=repair_id)

    customer_id = repair.customer_id
    repair_was_completed = repair.queue_status == 'COMPLETED'
    repair_customer = repair.customer

    with transaction.atomic():
        now = timezone.now()
        repair.deleted_at = now
        repair.save(update_fields=['deleted_at'])

        # Soft-delete invoices that have line items for this repair.  Recorded
        # payments used to block deletion outright; now they simply ride along
        # (kept intact for restore, purged with the invoice after 30 days).
        Invoice.objects.filter(
            line_items__repair=repair
        ).distinct().update(deleted_at=now)

    # Rebuild UnitRepairCount for this customer if the deleted repair was
    # COMPLETED and therefore affected progressive pricing.  Without this,
    # the unit's repair count stays inflated by 1, and every subsequent
    # repair on that unit is priced as if the deleted one still happened.
    # (CODE-068)
    if repair_was_completed and repair_customer:
        try:
            from apps.customer_portal.views import rebuild_unit_repair_counts
            rebuild_unit_repair_counts(repair_customer)
        except Exception:
            pass  # Never block the delete; pricing rebuild is best-effort

    messages.success(request, f"Repair #{repair.id} has been deleted.")
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
def restore_repair(request, repair_id):
    """
    Restore a soft-deleted repair. Owner/manager only.
    Clears deleted_at on the repair and its invoices.
    Only available within 30 days of deletion.
    POST only.
    """
    from apps.billing.models import Invoice

    if request.method != 'POST':
        return redirect('archived_repairs')

    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user, tenant=tenant):
        messages.error(request, "Only owners and managers can restore repairs.")
        return redirect('archived_repairs')

    # Use all_objects to find deleted repairs
    qs = Repair.all_objects.filter(tenant=tenant) if tenant else Repair.all_objects.none()
    repair = get_object_or_404(qs, id=repair_id)

    if repair.deleted_at is None:
        messages.info(request, "That repair is not deleted.")
        return redirect('repair_detail', repair_id=repair_id)

    cutoff = timezone.now() - timezone.timedelta(days=30)
    if repair.deleted_at < cutoff:
        messages.error(request, "Cannot restore repairs deleted more than 30 days ago.")
        return redirect('archived_repairs')

    repair_was_completed = repair.queue_status == 'COMPLETED'
    repair_customer = repair.customer

    with transaction.atomic():
        repair.deleted_at = None
        repair.save(update_fields=['deleted_at'])

        # Restore invoices that were soft-deleted along with this repair
        Invoice.all_objects.filter(
            line_items__repair=repair,
            deleted_at__isnull=False
        ).distinct().update(deleted_at=None)

    # Rebuild UnitRepairCount so the restored COMPLETED repair is counted
    # again in progressive pricing.  Without this, the unit's count stays
    # at the value it had after the delete (missing +1 for this repair),
    # and the next repair on that unit is under-priced.  (CODE-068)
    if repair_was_completed and repair_customer:
        try:
            from apps.customer_portal.views import rebuild_unit_repair_counts
            rebuild_unit_repair_counts(repair_customer)
        except Exception:
            pass  # Never block the restore; pricing rebuild is best-effort

    messages.success(request, f"Repair #{repair.id} has been restored.")
    return redirect('repair_detail', repair_id=repair_id)


@technician_required
def restore_replacement(request, replacement_id):
    """
    Restore a soft-deleted replacement. Owner/manager only.
    Clears deleted_at on the replacement and its invoices.
    Only available within 30 days of deletion. POST only.
    """
    from apps.billing.models import Invoice
    from apps.technician_portal.models import Replacement

    if request.method != 'POST':
        return redirect('archived_repairs')

    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user, tenant=tenant):
        messages.error(request, "Only owners and managers can restore replacements.")
        return redirect('archived_repairs')

    qs = Replacement.all_objects.filter(tenant=tenant) if tenant else Replacement.all_objects.none()
    replacement = get_object_or_404(qs, id=replacement_id)

    if replacement.deleted_at is None:
        messages.info(request, "That replacement is not deleted.")
        return redirect('replacement_detail', pk=replacement_id)

    cutoff = timezone.now() - timezone.timedelta(days=30)
    if replacement.deleted_at < cutoff:
        messages.error(request, "Cannot restore replacements deleted more than 30 days ago.")
        return redirect('archived_repairs')

    with transaction.atomic():
        replacement.deleted_at = None
        replacement.save(update_fields=['deleted_at'])

        Invoice.all_objects.filter(
            line_items__replacement=replacement,
            deleted_at__isnull=False
        ).distinct().update(deleted_at=None)

    messages.success(request, f"Replacement #{replacement.id} has been restored.")
    return redirect('replacement_detail', pk=replacement_id)


@technician_required
def restore_invoice(request, invoice_id):
    """
    Restore a soft-deleted invoice. Owner/manager only.
    Only available within 30 days of deletion. POST only.
    """
    from apps.billing.models import Invoice

    if request.method != 'POST':
        return redirect('archived_repairs')

    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user, tenant=tenant):
        messages.error(request, "Only owners and managers can restore invoices.")
        return redirect('archived_repairs')

    qs = Invoice.all_objects.filter(tenant=tenant) if tenant else Invoice.all_objects.none()
    invoice = get_object_or_404(qs, id=invoice_id)

    if invoice.deleted_at is None:
        messages.info(request, "That invoice is not deleted.")
        return redirect('archived_repairs')

    cutoff = timezone.now() - timezone.timedelta(days=30)
    if invoice.deleted_at < cutoff:
        messages.error(request, "Cannot restore invoices deleted more than 30 days ago.")
        return redirect('archived_repairs')

    invoice.deleted_at = None
    invoice.save(update_fields=['deleted_at'])

    messages.success(request, f"Invoice {invoice.invoice_number} has been restored.")
    return redirect('archived_repairs')


@technician_required
def archived_repairs(request):
    """
    Recently Deleted — owner/manager only.
    Shows customers, repairs, replacements, and invoices deleted in the
    last 30 days with the option to restore each.
    """
    from apps.billing.models import Invoice
    from apps.technician_portal.models import Replacement
    from core.models import Customer

    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user, tenant=tenant):
        messages.error(request, "Only owners and managers can view deleted records.")
        return redirect('job_list')

    cutoff = timezone.now() - timezone.timedelta(days=30)

    # Deleted customers (within 30-day restore window)
    deleted_customers = Customer.all_objects.filter(
        tenant=tenant,
        deleted_at__isnull=False,
        deleted_at__gte=cutoff
    ).order_by('-deleted_at')

    # Deleted repairs (within 30-day restore window)
    deleted_repairs = Repair.all_objects.filter(
        tenant=tenant,
        deleted_at__isnull=False,
        deleted_at__gte=cutoff
    ).select_related('customer', 'technician').order_by('-deleted_at')

    # Deleted replacements (within 30-day window)
    deleted_replacements = Replacement.all_objects.filter(
        tenant=tenant,
        deleted_at__isnull=False,
        deleted_at__gte=cutoff
    ).select_related('customer', 'technician').order_by('-deleted_at')

    # Deleted invoices (within 30-day window)
    deleted_invoices = Invoice.all_objects.filter(
        tenant=tenant,
        deleted_at__isnull=False,
        deleted_at__gte=cutoff
    ).select_related('customer').order_by('-deleted_at')

    context = {
        'deleted_customers': deleted_customers,
        'deleted_repairs': deleted_repairs,
        'deleted_replacements': deleted_replacements,
        'deleted_invoices': deleted_invoices,
        'is_admin': True,
    }
    return render(request, 'technician_portal/archived_repairs.html', context)


@technician_required
def create_warranty_claim(request, repair_id):
    """Create a warranty claim repair linked to the original."""
    if request.method != 'POST':
        return redirect('repair_detail', repair_id=repair_id)

    tenant = getattr(request, 'tenant', None)
    qs = Repair.objects.select_related('customer', 'technician__user')
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    original_repair = get_object_or_404(qs, id=repair_id)

    if not original_repair.has_warranty:
        messages.error(request, "This repair is not under warranty.")
        return redirect('repair_detail', repair_id=repair_id)

    claim_reason = request.POST.get('claim_reason', '').strip()
    if not claim_reason:
        messages.error(request, "Please provide a reason for the warranty claim.")
        return redirect('repair_detail', repair_id=repair_id)

    technician_id = request.POST.get('technician_id')
    tech = None
    if technician_id:
        tech = Technician.objects.filter(id=technician_id, tenant=tenant, is_active=True).first()
    if not tech:
        tech = original_repair.technician

    # CODE-263: If "claim_batch" is checked and repair is part of a batch,
    # create warranty claims for ALL completed+warranty-eligible siblings.
    claim_batch = request.POST.get('claim_batch') == 'on'
    repairs_to_claim = [original_repair]

    if claim_batch and original_repair.is_part_of_batch and original_repair.repair_batch_id:
        batch_siblings = Repair.objects.filter(
            repair_batch_id=original_repair.repair_batch_id,
            tenant=tenant,
            queue_status='COMPLETED',
        ).exclude(pk=original_repair.pk).select_related('technician__user')
        # Only include siblings that are actually under warranty
        for sibling in batch_siblings:
            if sibling.has_warranty:
                repairs_to_claim.append(sibling)

    # If claiming multiple, group them under a new batch ID
    claim_batch_id = uuid.uuid4() if len(repairs_to_claim) > 1 else None
    claims = []

    for idx, orig in enumerate(repairs_to_claim, 1):
        claim_tech = tech if orig == original_repair else (orig.technician or tech)
        claim = Repair.objects.create(
            tenant=tenant,
            customer=orig.customer,
            technician=claim_tech,
            unit_number=orig.unit_number,
            damage_type=orig.damage_type,
            damage_location_x=orig.damage_location_x,
            damage_location_y=orig.damage_location_y,
            queue_status='REQUESTED',
            cost=Decimal('0.00'),
            cost_override=Decimal('0.00'),
            override_reason=f'Warranty claim against Repair #{orig.pk}',
            description=(
                f'WARRANTY CLAIM: {claim_reason}\n'
                f'Original Repair: #{orig.pk} '
                f'({orig.repair_date.strftime("%b %d, %Y") if orig.repair_date else "N/A"})'
            ),
            skip_invoicing=True,
            is_warranty_claim=True,
            warranty_original_repair=orig,
            repair_batch_id=claim_batch_id,
            break_number=idx if claim_batch_id else None,
            total_breaks_in_batch=len(repairs_to_claim) if claim_batch_id else None,
        )
        claims.append(claim)

    if len(claims) > 1:
        messages.success(request, f"Warranty claims created for {len(claims)} repairs in this batch (all $0.00)")
    else:
        messages.success(request, f"Warranty claim created as Repair #{claims[0].id} ($0.00)")
    if len(claims) > 1 and claim_batch_id:
        return redirect('technician_batch_detail', batch_id=claim_batch_id)
    return redirect('repair_detail', repair_id=claims[0].id)


@technician_required
def admin_reassign_repair(request, repair_id):
    """Admin reassigns a repair to any active technician."""
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    qs = Repair.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repair = get_object_or_404(qs, id=repair_id)

    if not user_is_admin:
        # A manager who lands here can usually still see the job — send them
        # back to it rather than to the dashboard.
        technician = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
        return deny(request, "Only admins can reassign repairs.", repair, technician)

    if repair.queue_status == 'COMPLETED':
        messages.error(request, "Cannot reassign completed repairs.")
        return redirect('repair_detail', repair_id=repair.id)

    if request.method == 'POST':
        technician_id = request.POST.get('technician_id')
        if not technician_id:
            messages.error(request, "Please select a technician.")
            return redirect('admin_reassign_repair', repair_id=repair.id)

        try:
            tech_qs = Technician.objects.filter(id=technician_id, is_active=True)
            if tenant:
                tech_qs = tech_qs.filter(tenant=tenant)
            else:
                tech_qs = tech_qs.none()
            new_tech = tech_qs.get()

            # Notifies the new tech (repair_assigned) and the old tech
            # (repair_reassigned_away) through the one assignment path.
            assign_job(repair, new_tech, assigned_by=request.user)

            messages.success(request, f"Repair #{repair.id} reassigned to {new_tech.user.get_full_name()}")
            return redirect('repair_detail', repair_id=repair.id)

        except Technician.DoesNotExist:
            messages.error(request, "Selected technician not found.")
            return redirect('admin_reassign_repair', repair_id=repair.id)

    # GET
    tech_qs = Technician.objects.filter(is_active=True)
    if tenant:
        tech_qs = tech_qs.filter(tenant=tenant)
    else:
        tech_qs = tech_qs.none()
    available_technicians = tech_qs.select_related('user').order_by('user__first_name')

    return render(request, 'technician_portal/admin_reassign_repair.html', {
        'repair': repair,
        'available_technicians': available_technicians,
    })


@technician_required
def portal_bulk_reassign(request):
    """Admin bulk reassign repairs to a technician (portal version)."""
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)

    if not user_is_admin:
        messages.error(request, "Only admins can bulk reassign repairs.")
        return redirect('job_list')

    if request.method == 'POST':
        repair_ids = request.POST.getlist('repair_ids')
        technician_id = request.POST.get('technician_id')

        if not repair_ids or not technician_id:
            messages.error(request, "Please select repairs and a technician.")
            return redirect('job_list')

        try:
            tech_qs = Technician.objects.filter(id=technician_id, is_active=True)
            if tenant:
                tech_qs = tech_qs.filter(tenant=tenant)
            else:
                tech_qs = tech_qs.none()
            new_tech = tech_qs.get()
        except Technician.DoesNotExist:
            messages.error(request, "Selected technician not found.")
            return redirect('job_list')

        qs = Repair.objects.filter(id__in=repair_ids).exclude(queue_status='COMPLETED')
        if tenant:
            qs = qs.filter(tenant=tenant)
        else:
            qs = qs.none()

        count = 0
        gained = []          # jobs that actually changed hands to new_tech
        lost_by_tech = {}    # old Technician -> [jobs they lost]
        with transaction.atomic():
            for repair in qs:
                old_tech = repair.technician
                changed = old_tech is None or old_tech.pk != new_tech.pk
                # Per-job core notifications are suppressed (notify=False);
                # each affected tech gets ONE summary notification below
                # instead of one email per repair.
                assign_job(repair, new_tech, assigned_by=request.user, notify=False)
                count += 1

                if not changed:
                    continue
                gained.append(repair)
                if old_tech is not None:
                    lost_by_tech.setdefault(old_tech, []).append(repair)
                    TechnicianNotification.objects.filter(
                        technician=old_tech, repair=repair, read=False,
                    ).update(read=True)
                    TechnicianNotification.objects.create(
                        technician=old_tech,
                        message=f"Repair #{repair.id} for {repair.customer.name} - Unit {repair.unit_number} has been reassigned to {new_tech.user.get_full_name()}",
                        read=False,
                        repair=repair
                    )
                TechnicianNotification.objects.create(
                    technician=new_tech,
                    message=f"You have been assigned Repair #{repair.id} for {repair.customer.name} - Unit {repair.unit_number}",
                    read=False,
                    repair=repair
                )

        notify_bulk_assignment(
            new_tech, gained,
            assigned_by=request.user,
            reassigned_away=lost_by_tech,
        )

        messages.success(request, f"Reassigned {count} repair(s) to {new_tech.user.get_full_name()}")
        return redirect('job_list')

    # GET — collect repair IDs from query params
    repair_ids = request.GET.getlist('repair_ids')
    if not repair_ids:
        messages.error(request, "No repairs selected.")
        return redirect('job_list')

    qs = Repair.objects.filter(id__in=repair_ids).exclude(queue_status='COMPLETED').select_related('customer', 'technician__user')
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    repairs = list(qs)

    if not repairs:
        messages.error(request, "No valid repairs found to reassign.")
        return redirect('job_list')

    tech_qs = Technician.objects.filter(is_active=True)
    if tenant:
        tech_qs = tech_qs.filter(tenant=tenant)
    else:
        tech_qs = tech_qs.none()
    available_technicians = tech_qs.select_related('user').order_by('user__first_name')

    return render(request, 'technician_portal/portal_bulk_reassign.html', {
        'repairs': repairs,
        'available_technicians': available_technicians,
    })
