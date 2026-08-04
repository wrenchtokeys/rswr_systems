"""
Customer management views for the technician portal.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Q, Count
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.technician_portal.models import Technician, Repair, UnitRepairCount
from core.models import Customer
from apps.technician_portal.forms import CustomerForm
from apps.technician_portal.decorators import technician_required, admin_required, is_tenant_admin

import logging

logger = logging.getLogger(__name__)


def _save_billing_preferences(customer, cleaned_data):
    """Create CustomerRepairPreference if any billing fields were provided.

    If all billing fields are empty (e.g. the details section was never opened),
    no record is created — the customer uses shop defaults.
    """
    invoice_pref = cleaned_data.get('invoice_preference', '')
    payment_terms = cleaned_data.get('payment_terms', '')
    billing_email = cleaned_data.get('billing_email', '')
    batch_day = cleaned_data.get('batch_invoice_day')

    # Treat all-empty as "use shop defaults" — don't create a record
    if not any([invoice_pref, payment_terms, billing_email, batch_day]):
        return

    from apps.customer_portal.models import CustomerRepairPreference
    defaults = {}
    if invoice_pref:
        defaults['invoice_preference'] = invoice_pref
    if payment_terms:
        defaults['payment_terms'] = payment_terms
    if billing_email:
        defaults['billing_email'] = billing_email
    if batch_day is not None:
        defaults['batch_invoice_day'] = batch_day

    CustomerRepairPreference.objects.update_or_create(
        customer=customer,
        defaults=defaults,
    )


@technician_required
def create_customer(request):
    """Create a new customer with optional portal invitation."""
    tenant = getattr(request, 'tenant', None)

    # Usage limit check
    if tenant:
        from apps.tenants.services.usage_service import UsageService
        can_create, limit_msg = UsageService(tenant).can_add_customer()
        if not can_create:
            messages.warning(request, limit_msg)
            return redirect('technician_dashboard')

    if request.method == 'POST':
        form = CustomerForm(request.POST, tenant=tenant)
        if form.is_valid():
            customer = form.save(commit=False)
            if tenant:
                customer.tenant = tenant
            # tenant is assigned after form validation, so the DB unique
            # constraints (fleet name / email per tenant) are only enforced
            # here — surface them as form errors, not a 500.
            from django.db import IntegrityError, transaction as db_transaction
            try:
                with db_transaction.atomic():
                    customer.save()
            except IntegrityError:
                form.add_error(
                    None,
                    f"A customer with this name or email already exists for your shop. "
                    f"Check the customer list (including Recently Deleted) before re-adding."
                )
                return render(request, 'technician_portal/customer_form.html', {'form': form, 'tenant': tenant})

            # Handle billing preferences if any were provided
            _save_billing_preferences(customer, form.cleaned_data)

            # Handle portal invitation if requested
            invite_email = form.cleaned_data.get('invite_email')
            send_invitation = form.cleaned_data.get('send_invitation', False)

            if invite_email and send_invitation:
                from apps.customer_portal.services.invitation_service import CustomerInvitationService
                try:
                    invitation = CustomerInvitationService.create_invitation(
                        customer=customer,
                        email=invite_email,
                        invited_by=request.user,
                        first_name=form.cleaned_data.get('invite_first_name', ''),
                        last_name=form.cleaned_data.get('invite_last_name', ''),
                        is_primary_contact=form.cleaned_data.get('is_primary_contact', True),
                    )
                    if CustomerInvitationService.send_invitation_email(invitation, request):
                        messages.success(
                            request, 
                            f"Customer '{customer.name}' created and invitation sent to {invite_email}."
                        )
                    else:
                        messages.warning(
                            request,
                            f"Customer '{customer.name}' created, but failed to send invitation email. "
                            f"You can resend from the customer details page."
                        )
                except Exception as e:
                    logger.error(f"Failed to create/send invitation: {e}")
                    messages.warning(
                        request,
                        f"Customer '{customer.name}' created, but invitation could not be sent."
                    )
            else:
                messages.success(request, f"Customer '{customer.name}' has been created successfully.")
            
            return redirect('technician_dashboard')
    else:
        form = CustomerForm(tenant=tenant)
    return render(request, 'technician_portal/customer_form.html', {'form': form, 'tenant': tenant})


@technician_required
def customer_list(request):
    """List all customers accessible to the current technician."""
    tenant = getattr(request, 'tenant', None)

    # Admins and working managers see all customers in their tenant
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    # Scope the Technician lookup to the current tenant so that a manager at Shop A
    # cannot bypass this check when acting in Shop B's context. (CODE-076)
    _scoped_tech = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech and _scoped_tech.is_manager)

    if is_admin or is_mgr:
        customers = Customer.objects.all()
        if tenant:
            customers = customers.filter(tenant=tenant)

        else:
            customers = customers.none()
        customers = customers.order_by('name')
    else:
        # Use tenant-scoped Technician lookup so that a user who is a Technician
        # at Shop A but has a TenantMembership at Shop B (without a Technician record
        # there) doesn't resolve to Shop A's Technician here. Unscoped
        # request.user.technician would return the wrong shop's record — correct
        # downstream tenant filtering masks the actual issue, but using the wrong
        # Technician PK to filter repairs means a cross-tenant user sees no customers
        # at Shop B even if they have repairs there (broken UX). (CODE-088)
        if tenant:
            technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
        elif hasattr(request.user, 'technician'):
            try:
                technician = request.user.technician
            except Technician.DoesNotExist:
                technician = None
        else:
            technician = None

        if technician:
            repair_qs = Repair.objects.filter(technician=technician)
            if tenant:
                repair_qs = repair_qs.filter(tenant=tenant)

            else:
                repair_qs = repair_qs.none()
            customer_ids = repair_qs.values_list('customer_id', flat=True).distinct()
            customers = Customer.objects.filter(id__in=customer_ids)
            if tenant:
                customers = customers.filter(tenant=tenant)

            else:
                customers = customers.none()
            customers = customers.order_by('name')
        else:
            customers = Customer.objects.none()

    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # Fleet vs Individual filter chips (mirrors the job list's mapping:
    # "individual" covers both RETAIL and WALK_IN)
    type_filter = request.GET.get('type', '')
    if type_filter == 'fleet':
        customers = customers.filter(customer_type='FLEET')
    elif type_filter == 'individual':
        customers = customers.filter(customer_type__in=['RETAIL', 'WALK_IN'])

    # Annotate with active repair counts in a single query (avoids N+1)
    customers = customers.annotate(
        active_repairs_count=Count(
            'repair',
            filter=~Q(repair__queue_status='COMPLETED')
        )
    )

    return render(request, 'technician_portal/customer_list.html', {
        'customers': customers,
        'search_query': search_query,
        'type_filter': type_filter,
        'is_admin': is_admin or is_mgr,
    })


@technician_required
def customer_details(request, customer_id):
    """View customer details with unit listing for current technician."""
    tenant = getattr(request, 'tenant', None)
    
    # Get technician if exists (owners/managers may not have one).
    # Scope to the current tenant — request.user.technician resolves via OneToOneField
    # without tenant scope, so a manager at Shop A would incorrectly pass is_mgr checks
    # when acting in Shop B's context.  (CODE-076)
    technician = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None

    qs = Customer.objects.select_related('primary_technician__user').all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    # Determine if user is admin/owner/manager (can see all repairs)
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    is_mgr = bool(technician and technician.is_manager)
    
    # Build repairs query
    if is_admin or is_mgr:
        # Admins/managers see all repairs for this customer
        repairs = Repair.objects.filter(customer=customer)
    elif technician:
        # Regular techs see only their own repairs
        repairs = Repair.objects.filter(
            technician=technician,
            customer=customer
        )
    else:
        # No technician record and not admin - show empty
        repairs = Repair.objects.none()
    
    repairs = repairs.exclude(queue_status__in=['REQUESTED', 'PENDING'])
    if tenant:
        repairs = repairs.filter(tenant=tenant)

    else:
        repairs = repairs.none()

    unit_search = request.GET.get('unit_search', '')
    if unit_search:
        repairs = repairs.filter(unit_number__icontains=unit_search)

    units = repairs.exclude(unit_number__in=['', None]).values_list('unit_number', flat=True).distinct()

    # Determine if user can edit primary technician (admin, owner, or manager)
    can_edit_customer = is_admin or is_mgr

    # Provide available technicians for the primary tech dropdown
    available_technicians = Technician.objects.select_related('user').filter(is_active=True)
    if tenant:
        available_technicians = available_technicians.filter(tenant=tenant)

    else:
        available_technicians = available_technicians.none()
    available_technicians = available_technicians.order_by('user__first_name')

    # Portal access info (for admins/managers)
    portal_users = []
    removed_portal_users = []
    pending_invitations = []
    if can_edit_customer:
        from apps.customer_portal.models import CustomerUser, CustomerInvitation
        portal_users = CustomerUser.objects.filter(
            customer=customer, deactivated_at__isnull=True
        ).select_related('user')
        # Removed within the 30-day restore window
        removed_portal_users = CustomerUser.objects.filter(
            customer=customer,
            deactivated_at__gte=timezone.now() - timezone.timedelta(days=30),
        ).select_related('user')
        pending_invitations = CustomerInvitation.objects.filter(
            customer=customer,
            status='pending'
        ).order_by('-created_at')

    # Individuals rarely have unit numbers, so the fleet units view renders
    # empty for them even with plenty of history. Show a job list instead:
    # repairs + replacements, newest first, same visibility rules as above.
    jobs = []
    if customer.customer_type != 'FLEET':
        from apps.technician_portal.models import Replacement
        replacements = Replacement.objects.filter(customer=customer)
        if not (is_admin or is_mgr):
            replacements = (
                replacements.filter(technician=technician)
                if technician else Replacement.objects.none()
            )
        replacements = replacements.exclude(queue_status__in=['REQUESTED', 'PENDING'])
        if tenant:
            replacements = replacements.filter(tenant=tenant)
        else:
            replacements = replacements.none()

        from django.utils import timezone as tz
        jobs = sorted(
            [{'kind': 'repair', 'obj': r} for r in repairs] +
            [{'kind': 'replacement', 'obj': r} for r in replacements],
            key=lambda j: j['obj'].service_date or tz.now(),
            reverse=True,
        )

    # Loyalty: shared company balance + recent activity, shown to all shop
    # staff when the program is on. Redeeming on the customer's behalf is
    # manager/owner-only (mirrors price-override authorization).
    loyalty = None
    try:
        from apps.rewards_referrals.models import LoyaltyConfig, RewardRedemption
        from apps.rewards_referrals.services import LoyaltyService, RewardService

        config = LoyaltyConfig.get_for_tenant(tenant) if tenant else None
        if config and config.is_active:
            available = RewardService.get_available_rewards(customer)
            loyalty = {
                'balance': LoyaltyService.get_balance(customer),
                'recent_transactions': LoyaltyService.get_transaction_history(customer, limit=5),
                'pending_redemptions': RewardRedemption.objects.filter(
                    reward__customer=customer, status='PENDING',
                ).select_related('reward_option'),
                'affordable_options': available['available'],
                'program_name': config.program_name,
                'can_redeem': is_admin or is_mgr,
            }
    except Exception:
        logger.error('customer_details: loyalty card failed for customer=%s', customer_id, exc_info=True)

    return render(request, 'technician_portal/customer_details.html', {
        'customer': customer,
        'units': units,
        'unit_search': unit_search,
        'jobs': jobs,
        'can_edit_customer': can_edit_customer,
        'available_technicians': available_technicians,
        'portal_users': portal_users,
        'removed_portal_users': removed_portal_users,
        'pending_invitations': pending_invitations,
        'loyalty': loyalty,
    })


@technician_required
def unit_details(request, customer_id, unit_number):
    """View all repairs and replacements for a specific unit."""
    tenant = getattr(request, 'tenant', None)
    
    # Check if user is admin/manager (can see all).
    # Scope the Technician lookup to the current tenant — request.user.technician resolves
    # via OneToOneField with no tenant guard, so a manager at Shop A would incorrectly
    # pass is_mgr checks when acting in Shop B's context.  (CODE-076)
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    _scoped_tech_unit = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech_unit and _scoped_tech_unit.is_manager)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    # Get repairs for this unit.
    # Must guard _scoped_tech_unit=None: if a user has a 'technician' TenantMembership
    # role but no Technician record, passing technician=None to the filter would return
    # every *unassigned* repair for the customer — data leakage.  Mirror the safe pattern
    # from customer_details() which uses Repair.objects.none() in that case.  (CODE-187)
    if is_admin or is_mgr:
        repairs = Repair.objects.filter(customer=customer, unit_number=unit_number)
    elif _scoped_tech_unit:
        repairs = Repair.objects.filter(
            technician=_scoped_tech_unit,
            customer=customer,
            unit_number=unit_number
        )
    else:
        # No Technician record at this tenant — show nothing (safe default)
        repairs = Repair.objects.none()

    repairs = repairs.exclude(
        queue_status__in=['REQUESTED', 'PENDING']
    ).select_related('customer', 'technician__user')
    if tenant:
        repairs = repairs.filter(tenant=tenant)

    else:
        repairs = repairs.none()
    
    # Get replacements for this unit.
    # Same guard: _scoped_tech_unit=None → none() to prevent unassigned-record leakage.
    from apps.technician_portal.models import Replacement
    if is_admin or is_mgr:
        replacements = Replacement.objects.filter(customer=customer, unit_number=unit_number)
    elif _scoped_tech_unit:
        replacements = Replacement.objects.filter(
            technician=_scoped_tech_unit,
            customer=customer,
            unit_number=unit_number
        )
    else:
        replacements = Replacement.objects.none()
    
    if tenant:
        replacements = replacements.filter(tenant=tenant)

    
    else:
        replacements = replacements.none()
    replacements = replacements.select_related('customer', 'technician__user')

    return render(request, 'technician_portal/unit_details.html', {
        'customer': customer,
        'unit_number': unit_number,
        'repairs': repairs,
        'replacements': replacements,
    })


@technician_required
@require_POST
def mark_unit_replaced(request, customer_id, unit_number):
    """Mark a unit's windshield as replaced, resetting repair count and creating a Replacement record."""
    tenant = getattr(request, 'tenant', None)
    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)
    
    # Get or create the unit repair count record.
    # Include tenant in the lookup (not just defaults) so the lookup itself is
    # tenant-scoped.  Having tenant only in defaults means a NULL-tenant row
    # from an older codepath would match and the correct tenant would never be set.
    unit_repair_count, created = UnitRepairCount.objects.get_or_create(
        tenant=tenant,
        customer=customer,
        unit_number=unit_number,
        defaults={'repair_count': 0}
    )
    
    # Get the technician (current user or fallback).
    # Scope to the current tenant to avoid cross-tenant Technician contamination
    # on Replacement records (same pattern as CODE-076 through CODE-085).
    technician = None
    if tenant:
        technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
    if technician is None:
        # For admins without a technician record, fall back to customer's primary tech
        technician = customer.primary_technician
    
    if not technician:
        # Fallback: get any active technician
        technician = Technician.objects.filter(tenant=tenant, is_active=True).first()
    
    if technician:
        # Create a Replacement record to track this
        from apps.technician_portal.models import Replacement
        from django.utils import timezone
        
        replacement = Replacement.objects.create(
            tenant=tenant,
            customer=customer,
            technician=technician,
            unit_number=unit_number,
            glass_position='WINDSHIELD',
            queue_status='COMPLETED',
            service_date=timezone.now(),
            description=f"Windshield replacement for unit #{unit_number}",
            cost=0,  # Can be updated later if needed
        )
        messages.success(
            request, 
            f"Unit #{unit_number} windshield replacement recorded. Repair count reset to 0."
        )
    else:
        messages.warning(
            request,
            f"Unit #{unit_number} repair count reset, but no technician available to record replacement."
        )
    
    # Reset the repair count
    unit_repair_count.repair_count = 0
    unit_repair_count.save()
    
    return redirect('unit_details', customer_id=customer_id, unit_number=unit_number)


@technician_required
@require_POST
def update_primary_technician(request, customer_id):
    """Update the primary technician for a customer (manager/admin only)."""
    tenant = getattr(request, 'tenant', None)

    # Scope the Technician lookup to the current tenant so that a manager at Shop A
    # cannot bypass this gate when acting in Shop B's context.  (CODE-076)
    _scoped_tech_upt = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    if not is_tenant_admin(request.user, tenant=tenant):
        if not (_scoped_tech_upt and _scoped_tech_upt.is_manager):
            messages.error(request, "Only managers or admins can change a customer's primary technician.")
            return redirect('customer_detail', customer_id=customer_id)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    tech_id = request.POST.get('primary_technician')
    if tech_id:
        # Filter by tenant to prevent cross-tenant assignment
        tech_qs = Technician.objects.filter(is_active=True)
        if tenant:
            tech_qs = tech_qs.filter(tenant=tenant)

        else:
            tech_qs = tech_qs.none()
        tech = get_object_or_404(tech_qs, id=tech_id)
        customer.primary_technician = tech
        customer.save(update_fields=['primary_technician'])
        messages.success(request, f"Primary technician set to {tech.user.get_full_name()}.")
    else:
        customer.primary_technician = None
        customer.save(update_fields=['primary_technician'])
        messages.success(request, "Primary technician cleared.")

    return redirect('customer_detail', customer_id=customer_id)


@technician_required
def edit_customer(request, customer_id):
    """Edit customer details (manager/admin only)."""
    tenant = getattr(request, 'tenant', None)
    
    # Check permissions — scope Technician lookup to current tenant (CODE-076)
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    _scoped_tech_ec = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech_ec and _scoped_tech_ec.is_manager)
    
    if not (is_admin or is_mgr):
        messages.error(request, "Only managers or admins can edit customers.")
        return redirect('customer_detail', customer_id=customer_id)
    
    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)
    
    from apps.technician_portal.forms import CustomerEditForm
    
    if request.method == 'POST':
        form = CustomerEditForm(request.POST, instance=customer, tenant=tenant)
        if form.is_valid():
            try:
                # Savepoint so a constraint violation doesn't poison the
                # surrounding transaction before we re-render the form.
                with transaction.atomic():
                    form.save()
            except IntegrityError:
                # Safety net for races the form's clean_email check can miss —
                # the conditional unique constraints on (tenant, email) and
                # (tenant, name) otherwise surface as a 500.
                form.add_error(
                    None,
                    'Another customer already uses that name or email. '
                    'Please choose a different one.'
                )
            else:
                messages.success(request, f"Customer '{customer.name}' updated successfully.")
                return redirect('customer_detail', customer_id=customer_id)
    else:
        form = CustomerEditForm(instance=customer, tenant=tenant)
    
    return render(request, 'technician_portal/customer_edit.html', {
        'form': form,
        'customer': customer,
    })


@technician_required
@require_POST
def delete_customer(request, customer_id):
    """Soft-delete a customer and their entire history (admin only).

    Everything is stamped with the same deleted_at so a restore can bring
    back exactly this cascade: the customer's repairs, replacements, and
    invoices are soft-deleted (payments stay intact), and portal user logins
    are deactivated.  Restorable from Recently Deleted for 30 days, then
    purge_deleted_records hard-deletes the lot.
    """
    from apps.billing.models import Invoice
    from apps.technician_portal.models import Replacement
    from apps.customer_portal.models import CustomerUser

    tenant = getattr(request, 'tenant', None)

    # Only admins can delete
    if not is_tenant_admin(request.user, tenant=getattr(request, "tenant", None)):
        messages.error(request, "Only shop owners can delete customers.")
        return redirect('customer_detail', customer_id=customer_id)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    customer_name = customer.name

    with transaction.atomic():
        now = timezone.now()
        customer.deleted_at = now
        customer.save(update_fields=['deleted_at'])

        # Soft-delete active jobs and invoices.  Rows deleted earlier keep
        # their original (older) deleted_at, so restoring this customer
        # doesn't resurrect things that were already in the trash.
        Repair.objects.filter(customer=customer).update(deleted_at=now)
        Replacement.objects.filter(customer=customer).update(deleted_at=now)
        Invoice.objects.filter(customer=customer).update(deleted_at=now)

        # Deactivate portal logins (restore reactivates them; purge deletes
        # the User rows after 30 days).
        for cu in CustomerUser.objects.filter(
            customer=customer, deactivated_at__isnull=True
        ).select_related('user'):
            cu.deactivated_at = now
            cu.save(update_fields=['deactivated_at'])
            cu.user.is_active = False
            cu.user.save(update_fields=['is_active'])

    messages.success(
        request,
        f"Customer '{customer_name}' and all their jobs, invoices, and portal accounts "
        "have been deleted. You can restore them from Recently Deleted for 30 days."
    )
    return redirect('technician_customers')


@technician_required
@require_POST
def send_customer_invitation(request, customer_id):
    """Send or resend a customer portal invitation."""
    tenant = getattr(request, 'tenant', None)
    
    # Only admins/managers can send invitations — scope Technician to current tenant (CODE-076)
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    _scoped_tech_sci = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech_sci and _scoped_tech_sci.is_manager)
    
    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can send customer invitations.")
        return redirect('customer_detail', customer_id=customer_id)
    
    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)

    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)
    
    email = request.POST.get('email', '').strip()
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    is_primary = request.POST.get('is_primary_contact') == '1'
    
    if not email:
        messages.error(request, "Email address is required.")
        return redirect('customer_detail', customer_id=customer_id)
    
    from apps.customer_portal.services.invitation_service import CustomerInvitationService
    
    try:
        invitation = CustomerInvitationService.create_invitation(
            customer=customer,
            email=email,
            invited_by=request.user,
            first_name=first_name,
            last_name=last_name,
            is_primary_contact=is_primary,
        )
        
        if CustomerInvitationService.send_invitation_email(invitation, request):
            messages.success(request, f"Invitation sent to {email}")
        else:
            messages.warning(request, f"Invitation created but email failed to send. You can try again.")
    except Exception as e:
        logger.error(f"Failed to send customer invitation: {e}")
        messages.error(request, "Failed to send invitation. Please try again.")
    
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
@require_POST
def resend_customer_invitation(request, invitation_id):
    """Resend an existing customer invitation."""
    from apps.customer_portal.models import CustomerInvitation
    from apps.customer_portal.services.invitation_service import CustomerInvitationService

    tenant = getattr(request, 'tenant', None)

    # Reject early if no tenant context — we cannot safely scope the lookup.
    if not tenant:
        messages.error(request, "No shop context found. Please log out and back in.")
        return redirect('technician_dashboard')

    # Only admins/managers can resend invitations — scope Technician to current tenant (CODE-076)
    is_admin = is_tenant_admin(request.user, tenant=tenant)
    _scoped_tech_rci = Technician.objects.filter(user=request.user, tenant=tenant).first()
    is_mgr = bool(_scoped_tech_rci and _scoped_tech_rci.is_manager)

    # Scope the lookup to this tenant directly — never fetch the record first and
    # check the tenant afterwards, because a missing/None tenant would skip the check.
    # Resolved before the permission gate so a refusal can return the user to the
    # customer they were looking at, which is where success already lands.
    invitation = get_object_or_404(
        CustomerInvitation, id=invitation_id, customer__tenant=tenant
    )

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can resend invitations.")
        return redirect('customer_detail', customer_id=invitation.customer_id)

    if CustomerInvitationService.resend_invitation(invitation, request):
        messages.success(request, f"Invitation resent to {invitation.email}")
    else:
        messages.error(request, "Failed to resend invitation.")

    return redirect('customer_detail', customer_id=invitation.customer_id)


@technician_required
@require_POST
def cancel_customer_invitation(request, invitation_id):
    """Cancel a pending customer invitation."""
    from apps.customer_portal.models import CustomerInvitation
    from apps.customer_portal.services.invitation_service import CustomerInvitationService

    tenant = getattr(request, 'tenant', None)

    # Reject early if no tenant context — we cannot safely scope the lookup.
    if not tenant:
        messages.error(request, "No shop context found. Please log out and back in.")
        return redirect('technician_dashboard')

    # Only admins/managers can cancel invitations — scope Technician to current tenant (CODE-076)
    is_admin = is_tenant_admin(request.user, tenant=tenant)
    _scoped_tech_cci = Technician.objects.filter(user=request.user, tenant=tenant).first()
    is_mgr = bool(_scoped_tech_cci and _scoped_tech_cci.is_manager)

    # Scope the lookup to this tenant directly — same defence-in-depth reasoning
    # as resend: never rely on a post-fetch `if tenant and ...` guard. Resolved
    # before the permission gate so a refusal returns to the customer page.
    invitation = get_object_or_404(
        CustomerInvitation, id=invitation_id, customer__tenant=tenant
    )

    customer_id = invitation.customer_id

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can cancel invitations.")
        return redirect('customer_detail', customer_id=customer_id)

    if CustomerInvitationService.cancel_invitation(invitation):
        messages.success(request, f"Invitation to {invitation.email} cancelled.")
    else:
        messages.error(request, "Could not cancel this invitation.")

    return redirect('customer_detail', customer_id=customer_id)


@technician_required
@require_POST
def set_primary_contact(request, customer_id, cu_id):
    """Set a customer portal user as the primary contact."""
    from apps.customer_portal.models import CustomerUser

    tenant = getattr(request, 'tenant', None)

    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    # Scope Technician lookup to current tenant — prevents cross-tenant is_manager bypass (CODE-076)
    _scoped_tech_spc = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech_spc and _scoped_tech_spc.is_manager)

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can change the primary contact.")
        return redirect('customer_detail', customer_id=customer_id)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    cu = get_object_or_404(CustomerUser, id=cu_id, customer=customer)

    # Demote all existing primaries for this customer
    CustomerUser.objects.filter(
        customer=customer, is_primary_contact=True
    ).update(is_primary_contact=False)

    # Promote the selected user
    cu.is_primary_contact = True
    cu.save(update_fields=['is_primary_contact'])

    messages.success(request, f"{cu.user.get_full_name() or cu.user.username} is now the primary contact.")
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
@require_POST
def restore_customer(request, customer_id):
    """Restore a soft-deleted customer and the history deleted with them.

    Only rows stamped at (or after) the customer's own deleted_at come back —
    jobs or invoices the shop deleted separately, before deleting the
    customer, stay in the trash with their original timestamps.
    Admin only, within the 30-day window.
    """
    from apps.billing.models import Invoice
    from apps.technician_portal.models import Replacement
    from apps.customer_portal.models import CustomerUser

    tenant = getattr(request, 'tenant', None)

    if not is_tenant_admin(request.user, tenant=getattr(request, "tenant", None)):
        messages.error(request, "Only shop owners can restore customers.")
        return redirect('archived_repairs')

    qs = Customer.all_objects.filter(tenant=tenant) if tenant else Customer.all_objects.none()
    customer = get_object_or_404(qs, id=customer_id)

    if customer.deleted_at is None:
        messages.info(request, "That customer is not deleted.")
        return redirect('customer_detail', customer_id=customer_id)

    cutoff = timezone.now() - timezone.timedelta(days=30)
    if customer.deleted_at < cutoff:
        messages.error(request, "Cannot restore customers deleted more than 30 days ago.")
        return redirect('archived_repairs')

    stamp = customer.deleted_at

    # The unique constraints (fleet name / email per tenant) exempt
    # soft-deleted rows, so a shop can recreate "Acme Trucking" while the
    # old one sits in Recently Deleted. Restoring the old one then collides —
    # surface a message instead of a 500.
    from django.db import IntegrityError
    try:
        with transaction.atomic():
            customer.deleted_at = None
            customer.save(update_fields=['deleted_at'])
    except IntegrityError:
        messages.error(
            request,
            f"Can't restore '{customer.name}' — another customer with the same "
            f"name or email now exists. Rename or remove that customer first."
        )
        return redirect('archived_repairs')

    with transaction.atomic():
        Repair.all_objects.filter(customer=customer, deleted_at__gte=stamp).update(deleted_at=None)
        Replacement.all_objects.filter(customer=customer, deleted_at__gte=stamp).update(deleted_at=None)
        Invoice.all_objects.filter(customer=customer, deleted_at__gte=stamp).update(deleted_at=None)

        for cu in CustomerUser.objects.filter(
            customer=customer, deactivated_at__gte=stamp
        ).select_related('user'):
            cu.deactivated_at = None
            cu.save(update_fields=['deactivated_at'])
            cu.user.is_active = True
            cu.user.save(update_fields=['is_active'])

    messages.success(
        request,
        f"Customer '{customer.name}' and their jobs, invoices, and portal accounts have been restored."
    )
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
@require_POST
def remove_portal_user(request, customer_id, cu_id):
    """Remove a customer portal user by deactivating their login.

    The account can be restored for 30 days (see restore_portal_user);
    after that purge_deleted_records deletes the User row for good.
    """
    from apps.customer_portal.models import CustomerUser

    tenant = getattr(request, 'tenant', None)

    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    _scoped_tech = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech and _scoped_tech.is_manager)

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can remove portal users.")
        return redirect('customer_detail', customer_id=customer_id)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    cu = get_object_or_404(CustomerUser, id=cu_id, customer=customer, deactivated_at__isnull=True)
    display = cu.user.get_full_name() or cu.user.username

    cu.deactivated_at = timezone.now()
    cu.save(update_fields=['deactivated_at'])
    cu.user.is_active = False
    cu.user.save(update_fields=['is_active'])

    messages.success(
        request,
        f"Portal access for {display} has been removed. "
        "You can restore it for 30 days."
    )
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
@require_POST
def restore_portal_user(request, customer_id, cu_id):
    """Reactivate a removed portal user (within the 30-day window)."""
    from apps.customer_portal.models import CustomerUser

    tenant = getattr(request, 'tenant', None)

    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    _scoped_tech = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    is_mgr = bool(_scoped_tech and _scoped_tech.is_manager)

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can restore portal users.")
        return redirect('customer_detail', customer_id=customer_id)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    else:
        qs = qs.none()
    customer = get_object_or_404(qs, id=customer_id)

    cu = get_object_or_404(CustomerUser, id=cu_id, customer=customer, deactivated_at__isnull=False)

    cutoff = timezone.now() - timezone.timedelta(days=30)
    if cu.deactivated_at < cutoff:
        messages.error(request, "Cannot restore portal users removed more than 30 days ago.")
        return redirect('customer_detail', customer_id=customer_id)

    cu.deactivated_at = None
    cu.save(update_fields=['deactivated_at'])
    cu.user.is_active = True
    cu.user.save(update_fields=['is_active'])

    display = cu.user.get_full_name() or cu.user.username
    messages.success(request, f"Portal access for {display} has been restored.")
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
def customer_search_api(request):
    """GET /tech/api/customers/search/?type=individual|fleet&q=<name-or-phone>

    Tenant-scoped JSON search backing the customer picker on the job forms.
    Individual results carry a history line ("3 previous jobs · last visit
    May 12, 2026") so a returning person is picked, not re-created.
    """
    from django.http import JsonResponse
    from apps.technician_portal.services.customer_service import (
        INDIVIDUAL_TYPES, individuals_queryset, normalize_phone, service_summary,
    )

    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return JsonResponse({'results': []})

    kind = (request.GET.get('type') or 'individual').strip().lower()
    query = (request.GET.get('q') or '').strip()

    if kind == 'fleet':
        qs = Customer.objects.filter(tenant=tenant, customer_type='FLEET')
    else:
        qs = individuals_queryset(tenant)

    if query:
        digits = normalize_phone(query)
        name_q = Q(name__icontains=query)
        if digits and len(digits) >= 4:
            # Phones are stored formatted ("(555) 123-4567") — compare on a
            # digits-only basis, which means a Python-side pass.
            candidates = qs.filter(
                name_q | (Q(phone__isnull=False) & ~Q(phone=''))
            ).order_by('name')[:200]
            rows = [
                c for c in candidates
                if query.lower() in c.name.lower()
                or digits in normalize_phone(c.phone)
            ][:20]
        else:
            rows = qs.filter(name_q).order_by('name')[:20]
    else:
        rows = qs.order_by('name')[:20]

    results = []
    for c in rows:
        results.append({
            'id': c.id,
            'name': c.name,
            'phone': c.phone or '',
            'type': 'fleet' if c.customer_type == 'FLEET' else 'individual',
            'summary': service_summary(c) if c.customer_type in INDIVIDUAL_TYPES else '',
        })
    return JsonResponse({'results': results})
