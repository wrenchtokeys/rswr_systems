"""
Customer management views for the technician portal.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Q, Count
from django.views.decorators.http import require_POST

from apps.technician_portal.models import Technician, Repair, UnitRepairCount
from core.models import Customer
from apps.technician_portal.forms import CustomerForm
from apps.technician_portal.decorators import technician_required, admin_required, is_tenant_admin

import logging

logger = logging.getLogger(__name__)


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
            customer.save()
            
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
                        last_name=form.cleaned_data.get('invite_last_name', '')
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
    return render(request, 'technician_portal/customer_form.html', {'form': form})


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
        if hasattr(request.user, 'technician'):
            technician = request.user.technician
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

    units = repairs.values_list('unit_number', flat=True).distinct()

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
    pending_invitations = []
    if can_edit_customer:
        from apps.customer_portal.models import CustomerUser, CustomerInvitation
        portal_users = CustomerUser.objects.filter(customer=customer).select_related('user')
        pending_invitations = CustomerInvitation.objects.filter(
            customer=customer,
            status='pending'
        ).order_by('-created_at')

    return render(request, 'technician_portal/customer_details.html', {
        'customer': customer,
        'units': units,
        'unit_search': unit_search,
        'can_edit_customer': can_edit_customer,
        'available_technicians': available_technicians,
        'portal_users': portal_users,
        'pending_invitations': pending_invitations,
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

    # Get repairs for this unit
    if is_admin or is_mgr:
        repairs = Repair.objects.filter(customer=customer, unit_number=unit_number)
    else:
        repairs = Repair.objects.filter(
            technician=_scoped_tech_unit,
            customer=customer,
            unit_number=unit_number
        )
    
    repairs = repairs.exclude(
        queue_status__in=['REQUESTED', 'PENDING']
    ).select_related('customer', 'technician__user')
    if tenant:
        repairs = repairs.filter(tenant=tenant)

    else:
        repairs = repairs.none()
    
    # Get replacements for this unit
    from apps.technician_portal.models import Replacement
    if is_admin or is_mgr:
        replacements = Replacement.objects.filter(customer=customer, unit_number=unit_number)
    else:
        replacements = Replacement.objects.filter(
            technician=_scoped_tech_unit,
            customer=customer,
            unit_number=unit_number
        )
    
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
    
    # Get the technician (current user or fallback)
    technician = None
    if hasattr(request.user, 'technician'):
        technician = request.user.technician
    else:
        # For admins without technician record, try to get customer's primary tech
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
            form.save()
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
    """Delete a customer (admin only). Requires confirmation."""
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
    
    # Check for related repairs — use all_objects to include soft-deleted repairs.
    # Repair.objects uses RepairSoftDeleteManager which excludes deleted records.
    # A customer with only soft-deleted repairs would pass the Repair.objects count
    # check (count=0), allowing deletion and orphaning those archived repairs
    # (customer FK becomes NULL since GlassService.customer is SET_NULL).
    # We must block deletion whenever ANY repair — active OR archived — exists.
    repair_count = Repair.all_objects.filter(customer=customer, tenant=tenant).count()
    
    if repair_count > 0:
        # Soft approach: don't delete, show error
        messages.error(
            request, 
            f"Cannot delete '{customer.name}' — they have {repair_count} repair(s) on record. "
            "Delete or reassign their repairs first."
        )
        return redirect('customer_detail', customer_id=customer_id)
    
    customer_name = customer.name
    customer.delete()
    messages.success(request, f"Customer '{customer_name}' has been deleted.")
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

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can resend invitations.")
        return redirect('technician_dashboard')

    # Scope the lookup to this tenant directly — never fetch the record first and
    # check the tenant afterwards, because a missing/None tenant would skip the check.
    invitation = get_object_or_404(
        CustomerInvitation, id=invitation_id, customer__tenant=tenant
    )

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

    if not (is_admin or is_mgr):
        messages.error(request, "Only managers can cancel invitations.")
        return redirect('technician_dashboard')

    # Scope the lookup to this tenant directly — same defence-in-depth reasoning
    # as resend: never rely on a post-fetch `if tenant and ...` guard.
    invitation = get_object_or_404(
        CustomerInvitation, id=invitation_id, customer__tenant=tenant
    )

    customer_id = invitation.customer_id

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
