from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.conf import settings
from django.core.cache import cache
from django.contrib.contenttypes.models import ContentType
from core.models import Customer
from apps.technician_portal.models import Repair, Replacement, UnitRepairCount, TechnicianNotification, Technician
from apps.rewards_referrals.models import ReferralCode, RewardOption, RewardRedemption, Referral
from apps.rewards_referrals.services import ReferralService, RewardService
from apps.billing.models import Invoice
from .forms import RepairPreferenceForm, CustomerNotificationPreferenceForm
from .models import CustomerRepairPreference
from .models import CustomerUser, RepairApproval, CustomerInvitation, ApprovalToken
from core.models.notification import Notification
from core.models.notification_preferences import CustomerNotificationPreference
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate
from django.utils import timezone
from django.db.models import Sum, Q, Count
from django.db import models, transaction
from django.contrib.auth import update_session_auth_hash
from functools import wraps
from django.http import JsonResponse
from collections import defaultdict
from datetime import datetime, timedelta
from django.urls import reverse
from django_ratelimit.decorators import ratelimit
import logging
import re
import random
from common.utils import convert_heic_to_jpeg
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from core.services.sms_service import SMSService

logger = logging.getLogger(__name__)

# Custom decorator to ensure only customers can access views
def customer_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access the customer portal.")
            return redirect('login')
            
        # Check if user has a customer profile
        try:
            customer_user = CustomerUser.objects.get(user=request.user)
            return view_func(request, *args, **kwargs)
        except CustomerUser.DoesNotExist:
            # Redirect user to profile creation if they don't have a profile
            messages.info(request, "Please complete your profile setup to access customer features.")
            return redirect('profile_creation')
    return _wrapped_view

def rebuild_unit_repair_counts(customer):
    """Rebuild the UnitRepairCount data for a customer"""
    from apps.technician_portal.models import UnitRepairCount
    
    # Get counts of completed repairs by unit (scoped to tenant for isolation)
    repair_counts = Repair.objects.filter(
        customer=customer,
        tenant=customer.tenant,
        queue_status='COMPLETED'
    ).values('unit_number').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Delete existing counts for this customer
    UnitRepairCount.objects.filter(customer=customer).delete()
    
    # Create new counts (include tenant so rows are properly scoped)
    for repair in repair_counts:
        UnitRepairCount.objects.create(
            tenant=customer.tenant,
            customer=customer,
            unit_number=repair['unit_number'],
            repair_count=repair['count']
        )
    
    return len(repair_counts)

@customer_required
def customer_dashboard(request):
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Check if we need to rebuild unit repair counts for this customer
        # This is done once per customer
        unit_count = UnitRepairCount.objects.filter(customer=customer).count()
        
        if unit_count == 0:
            # No unit repair counts exist, rebuild them
            rebuild_unit_repair_counts(customer)
        
        # Get statistics for the customer dashboard
        # Filter by both customer AND tenant to prevent cross-tenant leakage
        tenant = customer.tenant
        base_qs = Repair.objects.filter(customer=customer, tenant=tenant)
        active_repairs = base_qs.exclude(queue_status='COMPLETED').exclude(queue_status='DENIED').count()
        completed_repairs = base_qs.filter(queue_status='COMPLETED').count()
        pending_approval = base_qs.filter(queue_status='PENDING').count()
        
        # Get total spent on completed repairs
        total_spent = base_qs.filter(queue_status='COMPLETED').aggregate(sum=Sum('cost'))['sum'] or 0
        
        # Get recent repairs (limited to 5) for the customer
        recent_repairs = base_qs.select_related('technician__user').order_by('-service_date')[:5]
        
        # Check which of the recent repairs were customer-initiated
        repair_ids = [repair.id for repair in recent_repairs]
        customer_initiated_approvals = RepairApproval.objects.filter(
            repair_id__in=repair_ids, 
            notes="Auto-approved as customer initiated the request"
        ).values_list('repair_id', flat=True)
        
        # Add a flag to each repair indicating if it was customer initiated
        for repair in recent_repairs:
            repair.customer_initiated = repair.id in customer_initiated_approvals
        
        # Get repairs that are awaiting customer approval
        repairs_awaiting_approval = base_qs.filter(
            queue_status='PENDING'
        ).select_related('technician__user').order_by('-service_date')

        # Group batched repairs and separate individual repairs
        batch_repairs = {}  # Dictionary: batch_id -> batch_summary
        individual_repairs = []  # List of non-batched repairs

        for repair in repairs_awaiting_approval:
            if repair.is_part_of_batch:
                # Only add batch summary once (for the first repair in batch we encounter)
                if repair.repair_batch_id not in batch_repairs:
                    batch_summary = Repair.get_batch_summary(repair.repair_batch_id, tenant=tenant)
                    if batch_summary:
                        batch_repairs[repair.repair_batch_id] = batch_summary
            else:
                individual_repairs.append(repair)

        # Get detailed repair statistics for visualizations
        stats = {
            'active_repairs': active_repairs,
            'completed_repairs': completed_repairs,
            'pending_approval': pending_approval,
            'total_spent': total_spent,
            # Detailed repair status counts for the visualization
            'repairs_requested': base_qs.filter(queue_status='REQUESTED').count(),
            'repairs_pending': pending_approval,
            'repairs_approved': base_qs.filter(queue_status='APPROVED').count(),
            'repairs_in_progress': base_qs.filter(queue_status='IN_PROGRESS').count(),
            'repairs_completed': completed_repairs,
            'repairs_denied': base_qs.filter(queue_status='DENIED').count(),
        }
        
        # Get referral and reward information
        # Get user's referral code (or None if they don't have one)
        referral_code = ReferralCode.objects.filter(customer_user=customer_user).first()
        referral_code_value = referral_code.code if referral_code else None
        
        # Get number of successful referrals
        referral_count = ReferralService.get_referral_count(customer_user)
        
        # Get reward points balance
        reward_points = RewardService.get_reward_balance(customer_user)
        
        # Get outstanding invoices for the customer
        outstanding_invoices = Invoice.objects.filter(
            customer=customer,
            status__in=['SENT', 'OVERDUE', 'PARTIAL']
        ).order_by('due_date')[:5]
        outstanding_total = outstanding_invoices.aggregate(
            total=Sum('total')
        )['total'] or 0
        overdue_count = Invoice.objects.filter(
            customer=customer,
            status='OVERDUE'
        ).count()
        
        context = {
            'customer': customer,
            'stats': stats,
            'active_repairs_count': active_repairs,
            'completed_repairs_count': completed_repairs,
            'pending_approval_count': pending_approval,
            'recent_repairs': recent_repairs,
            'pending_approval_repairs': repairs_awaiting_approval,
            'customer_user': customer_user,
            'customer_initiated_repair_ids': list(customer_initiated_approvals),
            # Batch repairs for grouped display
            'batch_repairs': list(batch_repairs.values()),
            'individual_repairs': individual_repairs,
            # Reward and referral data
            'referral_code': referral_code_value,
            'referral_count': referral_count,
            'reward_points': reward_points,
            # Invoice data
            'outstanding_invoices': outstanding_invoices,
            'outstanding_total': outstanding_total,
            'overdue_count': overdue_count,
        }

        # Add notification context
        context.update(get_notification_context(customer))

        return render(request, 'customer_portal/dashboard.html', context)
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@login_required
def profile_creation(request):
    # Check if user already has a CustomerUser profile
    if CustomerUser.objects.filter(user=request.user).exists():
        return redirect('customer_dashboard')

    tenant = getattr(request, 'tenant', None)
    tenant_customers = Customer.objects.filter(tenant=tenant) if tenant else Customer.objects.none()

    if request.method == 'POST':
        # Process the form submission
        is_new_company = request.POST.get('is_new_company') == 'yes'

        if is_new_company:
            # Create a new customer
            company_name = request.POST.get('company_name')
            company_email = request.POST.get('company_email')
            company_phone = request.POST.get('company_phone')
            company_address = request.POST.get('company_address')

            try:
                # Create new customer — associate with tenant
                customer = Customer.objects.create(
                    name=company_name,
                    email=company_email,
                    phone=company_phone,
                    address=company_address,
                    tenant=tenant,
                )
            except Exception as e:
                messages.error(request, f"Error creating company: {str(e)}")
                return render(request, 'customer_portal/profile_creation.html', {'customers': tenant_customers})
        else:
            # Use existing customer
            customer_id = request.POST.get('customer')
            try:
                customer = tenant_customers.get(id=customer_id)
            except Customer.DoesNotExist:
                messages.error(request, "Selected company does not exist.")
                return render(request, 'customer_portal/profile_creation.html', {'customers': tenant_customers})
        
        # Create CustomerUser record
        try:
            customer_user = CustomerUser.objects.create(
                user=request.user,
                customer=customer,
                is_primary_contact=request.POST.get('is_primary_contact') == 'True'
            )
            
            # Process referral code if it exists in the session
            referral_code = request.session.get('referral_code')
            if referral_code:
                # Validate and process the referral
                referral_code_obj = ReferralService.validate_referral_code(referral_code)
                if referral_code_obj:
                    # Process the referral and give points to both users
                    success = ReferralService.process_referral(referral_code_obj, customer_user)
                    if success:
                        messages.success(
                            request, 
                            "Thanks for using a referral code! You and your referrer have received bonus points."
                        )
                    else:
                        messages.warning(
                            request, 
                            "The referral code was valid, but we couldn't process it. Perhaps it's already been used."
                        )
                else:
                    messages.warning(request, "The referral code you entered was not valid.")
                
                # Clear the referral code from the session
                del request.session['referral_code']
            
            messages.success(request, "Profile created successfully!")
            return redirect('customer_dashboard')
        except Exception as e:
            messages.error(request, f"Error creating profile: {str(e)}")
    
    return render(request, 'customer_portal/profile_creation.html', {'customers': tenant_customers})

@customer_required
def customer_repairs(request):
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Get filter parameters
        status_filter = request.GET.get('status', 'all')
        sort_by = request.GET.get('sort', '-service_date')  # Default: newest first
        unit_search = request.GET.get('unit_search', '')
        damage_type_filter = request.GET.get('damage_type', 'all')
        date_from = request.GET.get('date_from', '')
        date_to = request.GET.get('date_to', '')

        # Get all repairs for this customer with optimization
        # Also filter by tenant to prevent cross-tenant data leakage
        repairs = Repair.objects.filter(
            customer=customer,
            tenant=customer.tenant,
        ).select_related('technician__user')

        # Apply status filters
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

        # Apply sorting — accept both repair_date (legacy) and service_date (new field)
        if sort_by in ('repair_date', '-repair_date'):
            sort_by = sort_by.replace('repair_date', 'service_date')
        valid_sorts = ['service_date', '-service_date', 'unit_number', '-unit_number',
                       'cost', '-cost', 'queue_status', '-queue_status']
        if sort_by in valid_sorts:
            repairs = repairs.order_by(sort_by)

        # Calculate summary statistics
        total_repairs = repairs.count()
        stats = {
            'total_repairs': total_repairs,
            'pending_approval': repairs.filter(queue_status='PENDING').count(),
            'in_progress': repairs.filter(queue_status__in=['APPROVED', 'IN_PROGRESS']).count(),
            'completed_this_month': repairs.filter(
                queue_status='COMPLETED',
                service_date__gte=timezone.now().date().replace(day=1)
            ).count(),
            'total_cost': repairs.filter(queue_status='COMPLETED').aggregate(
                total=models.Sum('cost')
            )['total'] or 0
        }

        # Check which repairs were customer-initiated and mark them
        repair_ids = list(repairs.values_list('id', flat=True))
        customer_initiated_approvals = RepairApproval.objects.filter(
            repair_id__in=repair_ids,
            notes="Auto-approved as customer initiated the request"
        ).values_list('repair_id', flat=True)

        # Add a flag to each repair indicating if it was customer initiated
        for repair in repairs:
            repair.customer_initiated = repair.id in customer_initiated_approvals

        # Group batch repairs for better presentation
        batch_groups = {}  # batch_id -> list of repairs
        individual_repairs_list = []

        for repair in repairs:
            if repair.is_part_of_batch:
                batch_id = str(repair.repair_batch_id)
                if batch_id not in batch_groups:
                    batch_groups[batch_id] = []
                batch_groups[batch_id].append(repair)
            else:
                individual_repairs_list.append(repair)

        # Create batch summaries for display
        batch_summaries = []
        for batch_id, batch_repairs in batch_groups.items():
            if batch_repairs:
                # Sort by break number
                batch_repairs.sort(key=lambda r: r.break_number)
                first_repair = batch_repairs[0]

                # Calculate totals
                total_cost = sum(r.cost or 0 for r in batch_repairs)
                pending_count = sum(1 for r in batch_repairs if r.queue_status == 'PENDING')
                completed_count = sum(1 for r in batch_repairs if r.queue_status == 'COMPLETED')

                # Determine overall status
                if all(r.queue_status == 'COMPLETED' for r in batch_repairs):
                    overall_status = 'COMPLETED'
                elif all(r.queue_status == 'DENIED' for r in batch_repairs):
                    overall_status = 'DENIED'
                elif pending_count > 0:
                    overall_status = 'PENDING'
                elif any(r.queue_status == 'IN_PROGRESS' for r in batch_repairs):
                    overall_status = 'IN_PROGRESS'
                elif all(r.queue_status == 'APPROVED' for r in batch_repairs):
                    overall_status = 'APPROVED'
                else:
                    overall_status = batch_repairs[0].queue_status

                batch_summaries.append({
                    'batch_id': batch_id,
                    'unit_number': first_repair.unit_number,
                    'service_date': first_repair.repair_date,
                    'break_count': len(batch_repairs),
                    'total_cost': total_cost,
                    'overall_status': overall_status,
                    'repairs': batch_repairs,
                    'pending_count': pending_count,
                    'completed_count': completed_count,
                    'can_approve_all': pending_count == len(batch_repairs) and pending_count > 0,
                    'repair_ids': ','.join(str(r.id) for r in batch_repairs),  # For bulk actions
                })

        # Sort batch summaries by date (newest first)
        batch_summaries.sort(key=lambda b: b['service_date'], reverse=True)

        # Pagination - combine batches and individual repairs for display
        # Each batch counts as 1 item, each individual repair counts as 1 item
        all_items = batch_summaries + [{'type': 'individual', 'repair': r} for r in individual_repairs_list]

        page_size = int(request.GET.get('page_size', 50))
        if page_size not in [20, 50, 100]:
            page_size = 50

        paginator = Paginator(all_items, page_size)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        # Get unique damage types for filter dropdown
        damage_types = Repair.DAMAGE_TYPE_CHOICES

        return render(request, 'customer_portal/repairs.html', {
            'items': page_obj,  # Mixed batch summaries and individual repairs
            'page_obj': page_obj,
            'total_repairs': total_repairs,
            'stats': stats,
            'customer': customer,
            'status_filter': status_filter,
            'sort_by': sort_by,
            'unit_search': unit_search,
            'damage_type_filter': damage_type_filter,
            'date_from': date_from,
            'date_to': date_to,
            'page_size': page_size,
            'damage_types': damage_types,
            'customer_initiated_repair_ids': list(customer_initiated_approvals),
            'batch_count': len(batch_summaries),
            'individual_count': len(individual_repairs_list),
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_repair_detail(request, repair_id):
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Get the repair and ensure it belongs to this customer (tenant-scoped)
        repair = get_object_or_404(Repair, id=repair_id, customer=customer, tenant=customer.tenant)
        
        # Get approval record if it exists
        try:
            approval = RepairApproval.objects.get(repair=repair)
            customer_initiated = approval.notes == "Auto-approved as customer initiated the request"
        except RepairApproval.DoesNotExist:
            approval = None
            customer_initiated = False
        
        # Mark if this was a customer-initiated repair
        repair.customer_initiated = customer_initiated
        
        return render(request, 'customer_portal/repair_detail.html', {
            'repair': repair,
            'customer': customer,
            'approval': approval
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_repair_approve(request, repair_id):
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Get the repair and ensure it belongs to this customer (tenant-scoped)
        repair = get_object_or_404(Repair, id=repair_id, customer=customer, tenant=customer.tenant)
        
        if request.method == 'POST':
            notes = request.POST.get('notes', '')
            
            # Create or update the approval
            approval, created = RepairApproval.objects.get_or_create(
                repair=repair,
                defaults={
                    'approved': True,
                    'approved_by': customer_user,
                    'approval_date': timezone.now(),
                    'notes': notes
                }
            )
            
            if not created:
                approval.approved = True
                approval.approved_by = customer_user
                approval.approval_date = timezone.now()
                approval.notes = notes
                approval.save()
            
            # Update the repair status
            repair.queue_status = 'APPROVED'

            # IMPORTANT: Ensure technician is preserved
            # PENDING repairs should already have a technician (the one who found the damage)
            # This prevents NULL technician errors later
            if not repair.technician:
                # This shouldn't happen, but log it for debugging
                logger = logging.getLogger(__name__)
                logger.warning(f"Repair #{repair.id} approved but has no technician assigned")

            repair.save()

            # Create notification for technician
            if repair.technician:
                TechnicianNotification.objects.create(
                    technician=repair.technician,
                    message=f"✅ Repair #{repair.id} APPROVED by {customer.name} - Unit {repair.unit_number}. You can now complete the work.",
                    read=False,
                    repair=repair
                )

            messages.success(request, "Repair has been approved successfully. The technician can now complete the work.")
            return redirect('customer_repair_detail', repair_id=repair.id)
        
        return render(request, 'customer_portal/repair_approve.html', {
            'repair': repair,
            'customer': customer
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_repair_deny(request, repair_id):
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Get the repair and ensure it belongs to this customer (tenant-scoped)
        repair = get_object_or_404(Repair, id=repair_id, customer=customer, tenant=customer.tenant)
        
        if request.method == 'POST':
            reason = request.POST.get('reason', '')
            
            # Create or update the approval record to mark as denied
            approval, created = RepairApproval.objects.get_or_create(
                repair=repair,
                defaults={
                    'approved': False,
                    'approved_by': customer_user,
                    'approval_date': timezone.now(),
                    'notes': reason
                }
            )
            
            if not created:
                approval.approved = False
                approval.approved_by = customer_user
                approval.approval_date = timezone.now()
                approval.notes = reason
                approval.save()
            
            # Update the repair status to indicate it was denied
            # Using a special value for DENIED to distinguish from regular PENDING
            repair.queue_status = 'DENIED'  # You'll need to add this to the model choices
            repair.save()

            # Create notification for technician
            if repair.technician:
                denial_message = f"❌ Repair #{repair.id} DENIED by {customer.name} - Unit {repair.unit_number}."
                if reason:
                    denial_message += f" Reason: {reason}"
                TechnicianNotification.objects.create(
                    technician=repair.technician,
                    message=denial_message,
                    read=False,
                    repair=repair
                )

            messages.success(request, "Repair request has been denied.")
            return redirect('customer_repair_detail', repair_id=repair.id)
        
        return render(request, 'customer_portal/repair_deny.html', {
            'repair': repair,
            'customer': customer
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")

# Multi-Break Batch Views
@customer_required
def customer_batch_detail(request, batch_id):
    """Display all repairs in a batch with batch approval options"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Scope batch lookup to this customer's tenant so cross-tenant batch
        # access via guessed UUID is blocked at the DB layer.
        batch_summary = Repair.get_batch_summary(batch_id, tenant=customer.tenant)

        if not batch_summary or batch_summary['customer'] != customer:
            messages.error(request, "Batch not found or you don't have access to it.")
            return redirect('customer_dashboard')

        return render(request, 'customer_portal/batch_detail.html', {
            'batch_summary': batch_summary,
            'customer': customer,
            'repairs': batch_summary['all_repairs'],
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
@transaction.atomic
def customer_batch_approve(request, batch_id):
    """Approve all repairs in a batch (all-or-nothing transaction)"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Scope to tenant to prevent cross-tenant IDOR via batch UUID.
        batch_summary = Repair.get_batch_summary(batch_id, tenant=customer.tenant)

        if not batch_summary or batch_summary['customer'] != customer:
            messages.error(request, "Batch not found or you don't have access to it.")
            return redirect('customer_dashboard')

        if request.method == 'POST':
            repairs = batch_summary['all_repairs']
            approved_count = 0
            technician = None

            # Approve all repairs in the batch
            for repair in repairs:
                # Create or update approval record
                approval, created = RepairApproval.objects.get_or_create(
                    repair=repair,
                    defaults={
                        'approved': True,
                        'approved_by': customer_user,
                        'approval_date': timezone.now(),
                        'notes': f'Batch approval for {batch_summary["break_count"]} breaks'
                    }
                )

                if not created:
                    approval.approved = True
                    approval.approved_by = customer_user
                    approval.approval_date = timezone.now()
                    approval.notes = f'Batch approval for {batch_summary["break_count"]} breaks'
                    approval.save()

                # Update repair status
                repair.queue_status = 'APPROVED'
                repair.save()

                # Track technician for batch notification
                if repair.technician:
                    technician = repair.technician

                approved_count += 1

            # Create single grouped notification for the entire batch
            if technician:
                TechnicianNotification.objects.create(
                    technician=technician,
                    message=f"✅ Batch of {batch_summary['break_count']} breaks APPROVED by {customer.name} - Unit {batch_summary['unit_number']} (${batch_summary['total_cost']:.2f} total)",
                    read=False,
                    repair=repairs[0],  # Link to first repair in batch
                    repair_batch_id=batch_id  # Store batch_id for batch notification
                )

            messages.success(
                request,
                f"Successfully approved all {approved_count} breaks for Unit {batch_summary['unit_number']} (${batch_summary['total_cost']:.2f} total)."
            )
            return redirect('customer_dashboard')

        # GET request - show confirmation page
        return render(request, 'customer_portal/batch_approve_confirm.html', {
            'batch_summary': batch_summary,
            'customer': customer,
        })

    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
@transaction.atomic
def customer_batch_deny(request, batch_id):
    """Deny all repairs in a batch (all-or-nothing transaction)"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Scope to tenant to prevent cross-tenant IDOR via batch UUID.
        batch_summary = Repair.get_batch_summary(batch_id, tenant=customer.tenant)

        if not batch_summary or batch_summary['customer'] != customer:
            messages.error(request, "Batch not found or you don't have access to it.")
            return redirect('customer_dashboard')

        if request.method == 'POST':
            reason = request.POST.get('reason', '')
            repairs = batch_summary['all_repairs']
            denied_count = 0
            technician = None

            # Deny all repairs in the batch
            for repair in repairs:
                # Create or update approval record
                approval, created = RepairApproval.objects.get_or_create(
                    repair=repair,
                    defaults={
                        'approved': False,
                        'approved_by': customer_user,
                        'approval_date': timezone.now(),
                        'notes': reason or f'Batch denial for {batch_summary["break_count"]} breaks'
                    }
                )

                if not created:
                    approval.approved = False
                    approval.approved_by = customer_user
                    approval.approval_date = timezone.now()
                    approval.notes = reason or f'Batch denial for {batch_summary["break_count"]} breaks'
                    approval.save()

                # Update repair status
                repair.queue_status = 'DENIED'
                repair.save()

                # Track technician for batch notification
                if repair.technician:
                    technician = repair.technician

                denied_count += 1

            # Create single grouped notification for the entire batch
            if technician:
                denial_message = f"❌ Batch of {batch_summary['break_count']} breaks DENIED by {customer.name} - Unit {batch_summary['unit_number']}"
                if reason:
                    denial_message += f" - Reason: {reason}"
                TechnicianNotification.objects.create(
                    technician=technician,
                    message=denial_message,
                    read=False,
                    repair=repairs[0],  # Link to first repair in batch
                    repair_batch_id=batch_id  # Store batch_id for batch notification
                )

            messages.success(
                request,
                f"Denied all {denied_count} breaks for Unit {batch_summary['unit_number']}."
            )
            return redirect('customer_dashboard')

        # GET request - show confirmation page
        return render(request, 'customer_portal/batch_deny_confirm.html', {
            'batch_summary': batch_summary,
            'customer': customer,
        })

    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


# =============================================================================
# REPLACEMENT VIEWS - Customer portal for glass replacements
# =============================================================================

@customer_required
def customer_replacements(request):
    """List all glass replacements for this customer."""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Get filter parameters
        status_filter = request.GET.get('status', '')

        # Get all replacements for this customer (tenant-scoped)
        replacements = Replacement.objects.filter(customer=customer, tenant=customer.tenant).select_related(
            'technician__user'
        ).order_by('-service_date', '-id')

        # Apply status filter
        if status_filter:
            replacements = replacements.filter(queue_status=status_filter)

        # Calculate stats
        stats = {
            'total': replacements.count(),
            'pending': Replacement.objects.filter(customer=customer, tenant=customer.tenant, queue_status='PENDING').count(),
            'in_progress': Replacement.objects.filter(customer=customer, tenant=customer.tenant, queue_status__in=['APPROVED', 'IN_PROGRESS']).count(),
            'completed': Replacement.objects.filter(customer=customer, tenant=customer.tenant, queue_status='COMPLETED').count(),
        }

        # Pagination
        paginator = Paginator(replacements, 25)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        # Status choices for filter
        status_choices = [
            ('', 'All Statuses'),
            ('REQUESTED', 'Customer Requested'),
            ('PENDING', 'Approval Pending'),
            ('APPROVED', 'Approved'),
            ('IN_PROGRESS', 'In Progress'),
            ('COMPLETED', 'Completed'),
            ('DENIED', 'Denied'),
        ]

        return render(request, 'customer_portal/replacements.html', {
            'page_obj': page_obj,
            'customer': customer,
            'stats': stats,
            'status_filter': status_filter,
            'status_choices': status_choices,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_replacement_detail(request, replacement_id):
    """View details of a single replacement."""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        replacement = get_object_or_404(Replacement, id=replacement_id, customer=customer, tenant=customer.tenant)

        return render(request, 'customer_portal/replacement_detail.html', {
            'replacement': replacement,
            'customer': customer,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_replacement_approve(request, replacement_id):
    """Approve a pending replacement."""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        replacement = get_object_or_404(Replacement, id=replacement_id, customer=customer, tenant=customer.tenant)

        # Only allow approval of pending replacements
        if replacement.queue_status not in ['PENDING', 'REQUESTED']:
            messages.warning(request, "This replacement cannot be approved - it's not pending.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        if request.method == 'POST':
            notes = request.POST.get('notes', '')

            # Update replacement status
            replacement.queue_status = 'APPROVED'
            replacement.save()

            # Create notification for technician
            if replacement.technician:
                TechnicianNotification.objects.create(
                    technician=replacement.technician,
                    message=f"✅ Replacement #{replacement.id} APPROVED by {customer.name} - {replacement.get_glass_position_display()} on Unit {replacement.unit_number}",
                    read=False,
                )

            messages.success(request, "Replacement has been approved. The technician can now proceed.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        return render(request, 'customer_portal/replacement_approve.html', {
            'replacement': replacement,
            'customer': customer,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_replacement_deny(request, replacement_id):
    """Deny a pending replacement."""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        replacement = get_object_or_404(Replacement, id=replacement_id, customer=customer, tenant=customer.tenant)

        # Only allow denial of pending replacements
        if replacement.queue_status not in ['PENDING', 'REQUESTED']:
            messages.warning(request, "This replacement cannot be denied - it's not pending.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        if request.method == 'POST':
            reason = request.POST.get('reason', '')

            # Update replacement status
            replacement.queue_status = 'DENIED'
            replacement.save()

            # Create notification for technician
            if replacement.technician:
                denial_message = f"❌ Replacement #{replacement.id} DENIED by {customer.name} - {replacement.get_glass_position_display()} on Unit {replacement.unit_number}"
                if reason:
                    denial_message += f". Reason: {reason}"
                TechnicianNotification.objects.create(
                    technician=replacement.technician,
                    message=denial_message,
                    read=False,
                )

            messages.success(request, "Replacement has been denied.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        return render(request, 'customer_portal/replacement_deny.html', {
            'replacement': replacement,
            'customer': customer,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


def is_suspicious_username(username):
    """Check if username looks like a bot/spam registration"""
    # Check for random character patterns like 'ygzwnplsgv'
    if len(username) >= 8:
        # Check if it's all lowercase letters with no recognizable pattern
        if username.isalpha() and username.islower():
            # Check for lack of vowels or too many consonants in a row
            vowels = set('aeiou')
            consonant_run = 0
            vowel_count = 0
            for char in username:
                if char in vowels:
                    vowel_count += 1
                    consonant_run = 0
                else:
                    consonant_run += 1
                    if consonant_run > 4:  # More than 4 consonants in a row is suspicious
                        return True

            # If less than 20% vowels, likely bot
            if vowel_count < len(username) * 0.2:
                return True

    # Check for common bot patterns
    bot_patterns = [
        r'^[a-z]{10,}$',  # All lowercase, 10+ chars
        r'^[0-9a-f]{8,}$',  # Hex strings
        r'^user[0-9]{5,}$',  # Generic userNNNNN
    ]

    for pattern in bot_patterns:
        if re.match(pattern, username.lower()):
            return True

    return False

def customer_register(request):
    if request.user.is_authenticated:
        return redirect('customer_dashboard')

    # Helper to render with form data preserved
    def render_with_form_data(error_message=None):
        if error_message:
            messages.error(request, error_message)
        return render(request, 'customer_portal/register.html', {
            'form_data': request.POST if request.method == 'POST' else {}
        })

    # Check if rate limited
    if getattr(request, 'limited', False):
        messages.error(request, "Too many registration attempts. Please try again later.")
        return render(request, 'customer_portal/register.html')

    if request.method == 'POST':
        # Honeypot field check (bot trap)
        honeypot = request.POST.get('website', '')  # Hidden field that bots might fill
        if honeypot:
            # Bot detected, silently reject
            messages.error(request, "Registration failed. Please try again.")
            return render(request, 'customer_portal/register.html')

        # Get form data
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        referral_code = request.POST.get('referral_code')

        # Check for suspicious username patterns
        if is_suspicious_username(username):
            return render_with_form_data("This username is not allowed. Please choose a different username.")

        # Validation
        if len(username) < 3:
            return render_with_form_data("Username must be at least 3 characters long")

        if password != confirm_password:
            return render_with_form_data("Passwords do not match")

        if len(password) < 8:
            return render_with_form_data("Password must be at least 8 characters long")

        if User.objects.filter(username=username).exists():
            return render_with_form_data("Username already exists")

        if User.objects.filter(email=email).exists():
            return render_with_form_data("Email already exists")

        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        # Log user in
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            messages.success(request, f"Account created successfully! Welcome, {first_name}.")

            # Store referral code in session if provided
            if referral_code:
                request.session['referral_code'] = referral_code
                # We'll process this after the CustomerUser is created in the profile_creation view

            return redirect('profile_creation')

    return render(request, 'customer_portal/register.html')

@customer_required
def edit_company(request):
    # Get the customer user record
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        if request.method == 'POST':
            # Update customer information
            customer.name = request.POST.get('name', '').lower()
            customer.email = request.POST.get('email', '')
            customer.phone = request.POST.get('phone', '')
            customer.address = request.POST.get('address', '')
            customer.city = request.POST.get('city', '')
            customer.state = request.POST.get('state', '')
            customer.zip_code = request.POST.get('zip_code', '')
            
            try:
                customer.save()
                messages.success(request, "Company information updated successfully!")
                return redirect('customer_dashboard')
            except Exception as e:
                messages.error(request, f"Error updating company: {str(e)}")
        
        # Render the edit form
        return render(request, 'customer_portal/edit_company.html', {
            'customer': customer
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def request_repair(request):
    """
    Handle customer repair requests with multi-unit batch submission support.

    Supports both single and batch repair submissions:
    - Single: Traditional form submission
    - Batch: Multiple units submitted at once via AJAX

    Returns:
        - GET: Render repair request form
        - POST: Process form submission and create repair request(s)
    """
    # Get the customer user record
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        if request.method == 'POST':
            # Check if this is a batch submission
            is_batch = request.POST.get('batch_submission') == 'true'

            if is_batch:
                return handle_batch_repair_request(request, customer)
            else:
                # Legacy single repair submission (for backwards compatibility)
                return handle_single_repair_request(request, customer)

        # Render the repair request form
        return render(request, 'customer_portal/request_repair.html')
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


def handle_single_repair_request(request, customer):
    """Handle traditional single repair request submission"""
    unit_number = request.POST.get('unit_number', '')
    description = request.POST.get('description', '')
    damage_type = request.POST.get('damage_type', '')
    damage_photo = request.FILES.get('damage_photo_before')

    if not unit_number:
        messages.error(request, "Unit number is required.")
        return render(request, 'customer_portal/request_repair.html')

    # Provide defaults for optional fields
    if not damage_type:
        damage_type = "Unknown"
    if not description:
        description = "Customer repair request - details to be determined by technician"

    # Validate and convert photo
    if damage_photo:
        photo_valid, photo_error = validate_repair_photo(damage_photo)
        if not photo_valid:
            messages.error(request, photo_error)
            return render(request, 'customer_portal/request_repair.html')
        damage_photo = convert_heic_to_jpeg(damage_photo)

    # Find available technician (scoped to tenant)
    tenant = getattr(request, 'tenant', None)
    technician = get_available_technician(tenant=tenant)
    if not technician:
        messages.error(request, "No technicians available. Please try again later.")
        return render(request, 'customer_portal/request_repair.html')

    # Create the repair
    try:
        repair = Repair.objects.create(
            tenant=tenant,
            technician=technician,
            customer=customer,
            unit_number=unit_number,
            description=description,
            damage_type=damage_type,
            customer_submitted_photo=damage_photo,
            customer_notes=description,
            queue_status='REQUESTED'
        )

        # Auto-assign technician based on tenant strategy
        from apps.tenants.services.assignment_service import auto_assign_repair
        assigned_tech = auto_assign_repair(repair)
        if assigned_tech:
            messages.info(request, f'Your repair has been assigned to {assigned_tech.user.get_full_name()}.')

        messages.success(request, "Repair request submitted successfully! A technician will review your request.")
        return redirect('customer_dashboard')
    except Exception as e:
        messages.error(request, f"Error creating repair request: {str(e)}")
        return render(request, 'customer_portal/request_repair.html')


def handle_batch_repair_request(request, customer):
    """Handle multi-unit batch repair request submission"""
    import json
    import uuid

    try:
        # Parse units data from JSON
        units_data_json = request.POST.get('units_data')
        if not units_data_json:
            messages.error(request, "No repair data provided.")
            return render(request, 'customer_portal/request_repair.html')

        units_data = json.loads(units_data_json)

        if not units_data or len(units_data) == 0:
            messages.error(request, "Please add at least one unit to submit.")
            return render(request, 'customer_portal/request_repair.html')

        # Find available technician (scoped to tenant)
        tenant = getattr(request, 'tenant', None)
        technician = get_available_technician(tenant=tenant)
        if not technician:
            messages.error(request, "No technicians available. Please try again later.")
            return render(request, 'customer_portal/request_repair.html')

        # Create all repairs atomically
        created_repairs = []
        with transaction.atomic():
            for index, unit_data in enumerate(units_data):
                unit_number = unit_data.get('unitNumber', '').strip()
                damage_type = unit_data.get('damageType', 'Unknown')
                notes = unit_data.get('notes', '')
                has_photo = unit_data.get('hasPhoto', False)
                has_multiple_breaks = unit_data.get('hasMultipleBreaks', False)
                break_count = unit_data.get('breakCount')

                if not unit_number:
                    continue  # Skip invalid entries

                # Get photo if provided
                photo_file = None
                if has_photo:
                    photo_key = f'photo_{index}'
                    photo_file = request.FILES.get(photo_key)
                    if photo_file:
                        photo_valid, photo_error = validate_repair_photo(photo_file)
                        if photo_valid:
                            photo_file = convert_heic_to_jpeg(photo_file)
                        else:
                            photo_file = None  # Skip invalid photos

                # Set description
                description = notes if notes else "Customer repair request - details to be determined by technician"

                # Handle multi-break repairs
                if has_multiple_breaks and break_count and break_count > 1:
                    # Create multiple repair records with batch tracking
                    batch_id = uuid.uuid4()
                    for break_num in range(1, break_count + 1):
                        repair = Repair.objects.create(
                            tenant=tenant,
                            technician=technician,
                            customer=customer,
                            unit_number=unit_number,
                            description=f"{description} (Break {break_num} of {break_count})",
                            damage_type=damage_type,
                            customer_submitted_photo=photo_file if break_num == 1 else None,  # Only attach photo to first break
                            customer_notes=notes,
                            queue_status='REQUESTED',
                            repair_batch_id=batch_id,
                            break_number=break_num,
                            total_breaks_in_batch=break_count
                        )
                        created_repairs.append(repair)
                elif has_multiple_breaks:
                    # Multi-break estimate (unknown count)
                    repair = Repair.objects.create(
                        tenant=tenant,
                        technician=technician,
                        customer=customer,
                        unit_number=unit_number,
                        description=f"{description} (Multiple breaks - count TBD)",
                        damage_type=damage_type,
                        customer_submitted_photo=photo_file,
                        customer_notes=notes,
                        queue_status='REQUESTED',
                        is_multi_break_estimate=True
                    )
                    created_repairs.append(repair)
                else:
                    # Single break repair (no batch fields)
                    repair = Repair.objects.create(
                        tenant=tenant,
                        technician=technician,
                        customer=customer,
                        unit_number=unit_number,
                        description=description,
                        damage_type=damage_type,
                        customer_submitted_photo=photo_file,
                        customer_notes=notes,
                        queue_status='REQUESTED'
                    )
                    created_repairs.append(repair)

        # Auto-assign technicians based on tenant strategy
        from apps.tenants.services.assignment_service import auto_assign_repair as _auto_assign
        assigned_any = False
        for repair in created_repairs:
            assigned_tech = _auto_assign(repair)
            if assigned_tech and not assigned_any:
                assigned_any = True
                messages.info(
                    request,
                    f'Repairs have been assigned to {assigned_tech.user.get_full_name()}.'
                )

        # Success message
        count = len(created_repairs)
        messages.success(
            request,
            f"Successfully submitted {count} repair request{'s' if count != 1 else ''}! A technician will review your requests."
        )

        # Return JSON for AJAX requests (check if multipart form data from fetch)
        if 'multipart/form-data' in request.content_type or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f"Successfully submitted {count} repair request{'s' if count != 1 else ''}!",
                'repair_count': count,
                'redirect_url': '/app/'
            })

        return redirect('customer_dashboard')

    except json.JSONDecodeError:
        messages.error(request, "Invalid request data format.")
        # Return JSON error for AJAX requests
        if 'multipart/form-data' in request.content_type or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'Invalid request data format.'
            }, status=400)
        return render(request, 'customer_portal/request_repair.html')
    except Exception as e:
        logging.error(f"Error creating batch repair request: {str(e)}")
        messages.error(request, f"Error creating repair requests: {str(e)}")
        # Return JSON error for AJAX requests
        if 'multipart/form-data' in request.content_type or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f"Error creating repair requests: {str(e)}"
            }, status=500)
        return render(request, 'customer_portal/request_repair.html')


def validate_repair_photo(photo_file):
    """
    Validate photo file for repair request

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Check file size (limit to 5MB)
    if photo_file.size > 5 * 1024 * 1024:
        return False, "Photo file size must be less than 5MB."

    # Check file type - includes HEIC for iPhone photos
    allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic', 'image/heif']
    file_ext = photo_file.name.lower().split('.')[-1] if '.' in photo_file.name else ''

    # Accept file if content_type is valid OR if file extension is valid
    is_valid_content_type = photo_file.content_type in allowed_types
    is_valid_extension = file_ext in ['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif']

    if not (is_valid_content_type or is_valid_extension):
        return False, "Please upload a valid image file (JPEG, PNG, WebP, or HEIC)."

    return True, ""


def get_available_technician(tenant=None):
    """
    Get an available technician using round-robin assignment.
    Scoped to tenant if provided.

    Returns:
        Technician object or None if no technicians available
    """
    technicians = Technician.objects.all()
    if tenant:
        technicians = technicians.filter(tenant=tenant)
    else:
        technicians = technicians.none()
    technicians = technicians.annotate(
        active_repairs=Count('repair', filter=Q(repair__queue_status__in=['REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS']))
    ).order_by('active_repairs', 'id')

    return technicians.first() if technicians.exists() else None


@customer_required
def repair_pricing_api(request):
    """
    API endpoint to get pricing estimates for repair requests.

    POST /app/api/repair-pricing/
    Body: {
        "units": [
            {
                "unit_number": "1001",
                "has_multiple_breaks": false,
                "break_count": null
            }
        ]
    }

    Returns:
        JSON with pricing information for each unit including multi-break breakdown
    """
    import json
    from apps.technician_portal.services.pricing_service import get_expected_repair_cost
    from apps.technician_portal.services.batch_pricing_service import calculate_batch_pricing, calculate_batch_total
    from apps.customer_portal.pricing_models import CustomerPricing
    from decimal import Decimal

    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=405)

    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Parse request body
        data = json.loads(request.body)
        units_data = data.get('units', [])

        # Backward compatibility: support old format with unit_numbers
        if not units_data and 'unit_numbers' in data:
            units_data = [{'unit_number': un, 'has_multiple_breaks': False, 'break_count': None}
                         for un in data.get('unit_numbers', [])]

        if not units_data:
            return JsonResponse({'error': 'No unit data provided'}, status=400)

        # Check if customer uses custom pricing
        uses_custom_pricing = CustomerPricing.objects.filter(
            customer=customer,
            use_custom_pricing=True
        ).exists()

        # Calculate pricing for each unit
        units_pricing = []
        for unit_data in units_data:
            unit_number = unit_data.get('unit_number', '').strip()
            has_multiple_breaks = unit_data.get('has_multiple_breaks', False)
            break_count = unit_data.get('break_count')

            if not unit_number:
                continue

            # Handle multi-break pricing
            if has_multiple_breaks and break_count and break_count > 1:
                # Exact count: Calculate progressive pricing breakdown
                pricing_breakdown = calculate_batch_pricing(customer, unit_number, break_count)
                batch_total = calculate_batch_total(pricing_breakdown)

                units_pricing.append({
                    'unit_number': unit_number,
                    'has_multiple_breaks': True,
                    'break_count': break_count,
                    'total_price': float(batch_total['total_cost']),
                    'total_price_formatted': f'${batch_total["total_cost"]:.2f}',
                    'breakdown': [
                        {
                            'break_number': item['break_number'],
                            'price': float(item['price']),
                            'price_formatted': item['price_formatted'],
                            'repair_number': item['repair_tier']
                        }
                        for item in pricing_breakdown
                    ],
                    'uses_custom_pricing': uses_custom_pricing
                })
            elif has_multiple_breaks:
                # Unknown count: Calculate range estimate (2-4 breaks)
                min_breaks = 2
                max_breaks = 4

                min_pricing = calculate_batch_pricing(customer, unit_number, min_breaks)
                max_pricing = calculate_batch_pricing(customer, unit_number, max_breaks)

                min_total = calculate_batch_total(min_pricing)
                max_total = calculate_batch_total(max_pricing)

                units_pricing.append({
                    'unit_number': unit_number,
                    'has_multiple_breaks': True,
                    'break_count': None,
                    'is_estimate': True,
                    'min_price': float(min_total['total_cost']),
                    'max_price': float(max_total['total_cost']),
                    'min_price_formatted': f'${min_total["total_cost"]:.2f}',
                    'max_price_formatted': f'${max_total["total_cost"]:.2f}',
                    'range_formatted': f'${min_total["total_cost"]:.2f} - ${max_total["total_cost"]:.2f}',
                    'min_breaks': min_breaks,
                    'max_breaks': max_breaks,
                    'uses_custom_pricing': uses_custom_pricing
                })
            else:
                # Single repair
                expected_cost, next_repair_count = get_expected_repair_cost(customer, unit_number)

                units_pricing.append({
                    'unit_number': unit_number,
                    'has_multiple_breaks': False,
                    'price': float(expected_cost),
                    'price_formatted': f'${expected_cost:.2f}',
                    'repair_count': next_repair_count - 1,  # Current count
                    'next_repair_number': next_repair_count,
                    'uses_custom_pricing': uses_custom_pricing
                })

        return JsonResponse({
            'units': units_pricing,
            'customer_name': customer.name,
            'uses_custom_pricing': uses_custom_pricing
        })

    except CustomerUser.DoesNotExist:
        return JsonResponse({'error': 'Customer profile not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logging.error(f"Error in repair_pricing_api: {str(e)}\n{error_trace}")
        return JsonResponse({
            'error': 'An error occurred while calculating pricing'
        }, status=500)

@customer_required
def account_settings(request):
    # Get the customer user record
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        user = request.user
        customer = customer_user.customer

        # Get or create the customer's repair preferences
        repair_prefs, created = CustomerRepairPreference.objects.get_or_create(
            customer=customer,
            defaults={
                'field_repair_approval_mode': 'REQUIRE_APPROVAL',
                'units_per_visit_threshold': 5,
            }
        )

        if request.method == 'POST':
            # Handle repair preference form
            repair_form = RepairPreferenceForm(request.POST, instance=repair_prefs)
            if repair_form.is_valid():
                repair_form.save()
                messages.success(request, "Repair preferences updated successfully!")

            # Update user information
            first_name = request.POST.get('first_name', '')
            last_name = request.POST.get('last_name', '')
            email = request.POST.get('email', '')
            phone = request.POST.get('phone', '')
            is_primary_contact = request.POST.get('is_primary_contact') == 'on'

            # Update password if provided
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            
            # Validate and save user info
            if email and email != user.email:
                if User.objects.filter(email=email).exclude(id=user.id).exists():
                    messages.error(request, "This email is already in use by another account.")
                    repair_form = RepairPreferenceForm(instance=repair_prefs)
                    return render(request, 'customer_portal/account_settings.html', {
                        'customer_user': customer_user,
                        'repair_form': repair_form,
                    })
                user.email = email
                # Reset email verification when email changes
                if customer.email_verified:
                    messages.info(request, "Email address changed. Please verify your new email address.")
                customer.email_verified = False
                customer.email_verified_at = None
                # Also update notification preferences
                prefs, created = CustomerNotificationPreference.objects.get_or_create(customer=customer)
                prefs.email_verified = False
                prefs.email_verified_at = None
                prefs.save()
            
            user.first_name = first_name
            user.last_name = last_name

            # Handle phone number update
            if phone != customer.phone:
                if customer.phone_verified:
                    messages.info(request, "Phone number changed. Please verify your new phone number.")
                customer.phone = phone
                customer.phone_verified = False
                customer.phone_verified_at = None
                # Also update notification preferences
                prefs, created = CustomerNotificationPreference.objects.get_or_create(customer=customer)
                prefs.phone_verified = False
                prefs.phone_verified_at = None
                prefs.save()

            # Handle password change if provided
            if current_password and new_password and confirm_password:
                if not user.check_password(current_password):
                    messages.error(request, "Current password is incorrect.")
                    repair_form = RepairPreferenceForm(instance=repair_prefs)
                    return render(request, 'customer_portal/account_settings.html', {
                        'customer_user': customer_user,
                        'repair_form': repair_form,
                    })

                if new_password != confirm_password:
                    messages.error(request, "New passwords don't match.")
                    repair_form = RepairPreferenceForm(instance=repair_prefs)
                    return render(request, 'customer_portal/account_settings.html', {
                        'customer_user': customer_user,
                        'repair_form': repair_form,
                    })

                if len(new_password) < 8:
                    messages.error(request, "Password must be at least 8 characters long.")
                    repair_form = RepairPreferenceForm(instance=repair_prefs)
                    return render(request, 'customer_portal/account_settings.html', {
                        'customer_user': customer_user,
                        'repair_form': repair_form,
                    })
                
                user.set_password(new_password)
                update_session_auth_hash(request, user)  # Keep user logged in
            
            # Update primary contact status
            customer_user.is_primary_contact = is_primary_contact
            
            try:
                user.save()
                customer_user.save()
                customer.save()  # Save phone changes and verification status
                messages.success(request, "Account settings updated successfully!")
                return redirect('customer_dashboard')
            except Exception as e:
                messages.error(request, f"Error updating account: {str(e)}")

        # Create form instance for GET requests
        repair_form = RepairPreferenceForm(instance=repair_prefs)

        # Render the account settings form
        return render(request, 'customer_portal/account_settings.html', {
            'customer_user': customer_user,
            'repair_form': repair_form,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def unit_repair_data_api(request):
    """API endpoint to provide unit repair data for visualizations"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Get all unit repair counts for this customer
        unit_repairs = UnitRepairCount.objects.filter(customer=customer)
        
        # If no unit repair counts exist, create them from repairs data
        if not unit_repairs.exists():
            # Get counts directly from Repair model (tenant-scoped)
            repair_counts = Repair.objects.filter(
                customer=customer,
                tenant=customer.tenant,
                queue_status='COMPLETED'  # Only count completed repairs
            ).values('unit_number').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Create UnitRepairCount records if needed
            for repair in repair_counts:
                UnitRepairCount.objects.update_or_create(
                    customer=customer,
                    unit_number=repair['unit_number'],
                    defaults={'repair_count': repair['count']}
                )
            
            # Refresh the queryset
            unit_repairs = UnitRepairCount.objects.filter(customer=customer)
        
        # Format the data for the chart
        data = [
            {
                'unit_number': unit.unit_number,
                'count': unit.repair_count
            }
            for unit in unit_repairs
        ]
        
        logger.debug(f"API Response (unit-repair-data): {len(data)} units")

        return JsonResponse(data, safe=False)
    except CustomerUser.DoesNotExist:
        return JsonResponse({'error': 'Customer profile not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in unit_repair_data_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@customer_required
def repair_cost_data_api(request):
    """API endpoint to provide repair frequency data for visualizations"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Get all repairs for this customer (tenant-scoped)
        repairs = Repair.objects.filter(
            customer=customer,
            tenant=customer.tenant,
        ).order_by('service_date')
        
        # Group repairs by month and count them
        monthly_counts = defaultdict(int)
        
        # Count repairs by month
        for repair in repairs:
            # Format as YYYY-MM
            month_key = repair.repair_date.strftime('%Y-%m')
            monthly_counts[month_key] += 1
        
        # Ensure we have at least 3 months of data
        if len(monthly_counts) < 3:
            # Add some placeholder months if needed
            now = datetime.now()
            
            # Add current month if empty
            current_month = now.strftime('%Y-%m')
            if current_month not in monthly_counts:
                monthly_counts[current_month] = 0
                
            # Add previous months if needed
            for i in range(1, 3):
                prev_month = (now - timedelta(days=30*i)).strftime('%Y-%m')
                if prev_month not in monthly_counts:
                    monthly_counts[prev_month] = 0
        
        # Format the data for the chart
        data = [
            {
                'date': f"{month}-01",  # Add day to make it a valid date for D3
                'count': count
            }
            for month, count in sorted(monthly_counts.items())
        ]
        
        logger.debug(f"API Response (repair-cost-data): {len(data)} months")

        return JsonResponse(data, safe=False)
    except CustomerUser.DoesNotExist:
        return JsonResponse({'error': 'Customer profile not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in repair_cost_data_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@customer_required
def customer_rewards_redirect(request):
    """Customer rewards and referrals dashboard"""
    try:
        customer_user = CustomerUser.objects.select_related('customer__tenant').get(user=request.user)
        customer = customer_user.customer
        tenant = customer.tenant

        # Get referral and reward information
        # Get user's referral code (or None if they don't have one)
        referral_code = ReferralCode.objects.filter(customer_user=customer_user).first()
        referral_code_value = referral_code.code if referral_code else None
        
        # Get number of successful referrals
        referral_count = ReferralService.get_referral_count(customer_user)
        
        # Get reward points balance
        reward_points = RewardService.get_reward_balance(customer_user)
        
        # Get available reward options — scoped to this customer's tenant
        reward_options = RewardOption.objects.filter(is_active=True, tenant=tenant).order_by('points_required')
        
        # Get recent referrals (people this customer referred)
        recent_referrals = Referral.objects.filter(
            referral_code__customer_user=customer_user
        ).order_by('-created_at')[:5]
        
        # Get recent redemptions
        recent_redemptions = RewardRedemption.objects.filter(
            reward__customer_user=customer_user
        ).order_by('-created_at')[:5]
        
        context = {
            'referral_code': referral_code_value,
            'referral_count': referral_count,
            'reward_points': reward_points,
            'points': reward_points,  # For template compatibility
            'reward_options': reward_options,
            'referrals': recent_referrals,
            'redemptions': recent_redemptions,
            'has_code': referral_code is not None,
        }
        
        return render(request, 'customer_portal/referrals/dashboard.html', context)
        
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_bulk_action(request):
    """Handle bulk approve or deny actions for multiple repairs"""
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('customer_repairs')

    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        # Get action type (approve or deny)
        action = request.POST.get('action')
        if action not in ['approve', 'deny']:
            messages.error(request, "Invalid action specified.")
            return redirect('customer_repairs')

        # Get repair IDs (comes as list from form)
        repair_ids = request.POST.getlist('repair_ids')

        if not repair_ids:
            messages.error(request, "No repairs selected.")
            return redirect('customer_repairs')

        # Validate and process repairs with transaction safety
        with transaction.atomic():
            # Get all repairs and ensure they belong to this customer (tenant-scoped)
            repairs = Repair.objects.filter(
                id__in=repair_ids,
                customer=customer,
                tenant=customer.tenant,
                queue_status='PENDING'
            ).select_related('technician')

            if not repairs.exists():
                messages.error(request, "No valid repairs found to process.")
                return redirect('customer_repairs')

            processed_count = 0

            for repair in repairs:
                if action == 'approve':
                    # Create or update approval
                    approval, created = RepairApproval.objects.get_or_create(
                        repair=repair,
                        defaults={
                            'approved': True,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': f'Bulk approved via multi-select'
                        }
                    )

                    if not created:
                        approval.approved = True
                        approval.approved_by = customer_user
                        approval.approval_date = timezone.now()
                        approval.notes = f'Bulk approved via multi-select'
                        approval.save()

                    # Update repair status
                    repair.queue_status = 'APPROVED'
                    repair.save()

                    # Create notification for technician
                    if repair.technician:
                        TechnicianNotification.objects.create(
                            technician=repair.technician,
                            message=f"✅ Repair #{repair.id} APPROVED by {customer.name} - Unit {repair.unit_number}. You can now complete the work.",
                            read=False,
                            repair=repair
                        )

                else:  # deny
                    # Create or update approval record to mark as denied
                    approval, created = RepairApproval.objects.get_or_create(
                        repair=repair,
                        defaults={
                            'approved': False,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': f'Bulk denied via multi-select'
                        }
                    )

                    if not created:
                        approval.approved = False
                        approval.approved_by = customer_user
                        approval.approval_date = timezone.now()
                        approval.notes = f'Bulk denied via multi-select'
                        approval.save()

                    # Update repair status
                    repair.queue_status = 'DENIED'
                    repair.save()

                    # Create notification for technician
                    if repair.technician:
                        TechnicianNotification.objects.create(
                            technician=repair.technician,
                            message=f"❌ Repair #{repair.id} DENIED by {customer.name} - Unit {repair.unit_number}.",
                            read=False,
                            repair=repair
                        )

                processed_count += 1

            # Success message
            action_word = "approved" if action == 'approve' else "denied"
            messages.success(
                request,
                f"Successfully {action_word} {processed_count} repair{'' if processed_count == 1 else 's'}."
            )

        return redirect('customer_repairs')

    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('customer_repairs')


# ============================================================================
# NOTIFICATION HELPER FUNCTION
# ============================================================================

def get_notification_context(customer):
    """
    Helper to get notification context for customer portal views.

    Args:
        customer: Customer object

    Returns:
        Dictionary with unread_count and recent_notifications
    """
    customer_ct = ContentType.objects.get_for_model(Customer)

    unread_count = Notification.objects.filter(
        recipient_type=customer_ct,
        recipient_id=customer.id,
        read=False
    ).count()

    recent_notifications = Notification.objects.filter(
        recipient_type=customer_ct,
        recipient_id=customer.id
    ).select_related('template').order_by('-created_at')[:5]

    return {
        'unread_count': unread_count,
        'recent_notifications': list(recent_notifications)
    }


# ============================================================================
# NOTIFICATION MANAGEMENT (Customer Portal)
# ============================================================================

@login_required
@customer_required
def customer_notification_preferences(request):
    """
    Customer notification preferences management page.

    Allows customers to:
    - Enable/disable notification channels (email, SMS, in-app)
    - Configure quiet hours
    - Set category preferences
    - Enable batch mode for pending approvals
    """
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
    except CustomerUser.DoesNotExist:
        messages.error(request, "Customer profile not found.")
        return redirect('customer_dashboard')

    # Get or create preferences for the customer (company-level)
    preferences, created = CustomerNotificationPreference.objects.get_or_create(
        customer=customer
    )

    if request.method == 'POST':
        form = CustomerNotificationPreferenceForm(request.POST, instance=preferences)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification preferences updated successfully!")
            return redirect('customer_notification_preferences')
    else:
        form = CustomerNotificationPreferenceForm(instance=preferences)

    # Get notification statistics
    customer_ct = ContentType.objects.get_for_model(Customer)
    unread_count = Notification.objects.filter(
        recipient_type=customer_ct,
        recipient_id=customer.id,
        read=False
    ).count()

    total_notifications = Notification.objects.filter(
        recipient_type=customer_ct,
        recipient_id=customer.id
    ).count()

    context = {
        'form': form,
        'preferences': preferences,
        'customer': customer,
        'customer_user': customer_user,
        'unread_count': unread_count,
        'total_notifications': total_notifications,
    }

    return render(request, 'customer_portal/notification_preferences.html', context)


# ============================================================================
# CONTACT VERIFICATION VIEWS
# ============================================================================

@login_required
@customer_required
def customer_verify_email(request):
    """
    Send email verification link to customer.
    Adapted from technician portal verify_email view.
    """
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
    except CustomerUser.DoesNotExist:
        messages.error(request, "Unable to verify email.")
        return redirect('customer_notification_preferences')

    # Generate verification token (Django's default_token_generator)
    token = default_token_generator.make_token(request.user)
    uid = urlsafe_base64_encode(force_bytes(request.user.pk))

    # Build verification URL
    verification_url = request.build_absolute_uri(
        reverse('customer_confirm_email_verification', kwargs={'uidb64': uid, 'token': token})
    )

    # Send verification email
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

    return redirect('customer_notification_preferences')


@login_required
@customer_required
def customer_verify_phone(request):
    """
    Send SMS verification code to customer.
    Adapted from technician portal verify_phone view.
    """
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
    except CustomerUser.DoesNotExist:
        messages.error(request, "Unable to verify phone.")
        return redirect('customer_notification_preferences')

    # Note: Customer model uses 'phone' field, not 'phone_number'
    if not customer.phone:
        messages.error(request, "Please add a phone number first.")
        return redirect('customer_account_settings')  # redirect to account settings

    # Generate 6-digit code
    code = f"{random.randint(100000, 999999)}"

    # Store code in session with customer_ prefix to avoid collision
    request.session['customer_phone_verification_code'] = code
    request.session['customer_phone_verification_number'] = customer.phone
    request.session['customer_phone_verification_expires'] = (timezone.now() + timedelta(minutes=10)).isoformat()

    # Send verification SMS
    message = f"Your RS Systems verification code is: {code}. This code expires in 10 minutes."

    try:
        if hasattr(settings, 'SMS_ENABLED') and settings.SMS_ENABLED:
            SMSService.send_sms(
                phone_number=customer.phone,
                message=message
            )
            messages.success(request, f"Verification code sent to {customer.phone}")
        else:
            # Development mode - show code in message
            messages.info(request, f"Development mode: Your verification code is {code}")
    except Exception as e:
        logger.error(f"Failed to send SMS verification: {str(e)}")
        messages.error(request, "Failed to send verification code. Please try again later.")

    # Redirect to notification preferences which will show verification modal
    return redirect('customer_notification_preferences')


def customer_confirm_email_verification(request, uidb64, token):
    """
    Process email verification token for customer.

    Note: No @login_required - verification links should work even if user is logged out.
    The token itself authenticates the request.
    """
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        try:
            customer_user = CustomerUser.objects.get(user=user)
            customer = customer_user.customer

            # Update both Customer and CustomerNotificationPreference
            customer.email_verified = True
            customer.email_verified_at = timezone.now()
            customer.save()

            # Also update notification preferences if they exist
            prefs, created = CustomerNotificationPreference.objects.get_or_create(
                customer=customer
            )
            prefs.email_verified = True
            prefs.email_verified_at = timezone.now()
            prefs.save()

            messages.success(request, "Email verified successfully! You can now receive email notifications.")
        except CustomerUser.DoesNotExist:
            messages.error(request, "Customer profile not found.")
    else:
        messages.error(request, "Invalid or expired verification link. Please request a new verification email.")

    # Redirect based on authentication status
    if request.user.is_authenticated:
        return redirect('customer_notification_preferences')
    else:
        return redirect('customer_login')


@login_required
@customer_required
def customer_confirm_phone_verification(request):
    """Process phone verification code for customer"""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        stored_code = request.session.get('customer_phone_verification_code')
        stored_number = request.session.get('customer_phone_verification_number')
        expires_str = request.session.get('customer_phone_verification_expires')

        if not all([stored_code, stored_number, expires_str]):
            messages.error(request, "No verification code found. Please request a new code.")
            return redirect('customer_notification_preferences')

        # Check expiration
        from dateutil import parser
        expires = parser.isoparse(expires_str)
        if timezone.now() > expires:
            messages.error(request, "Verification code has expired. Please request a new code.")
            # Clean up session
            request.session.pop('customer_phone_verification_code', None)
            request.session.pop('customer_phone_verification_number', None)
            request.session.pop('customer_phone_verification_expires', None)
            return redirect('customer_notification_preferences')

        # Verify code
        if code == stored_code:
            try:
                customer_user = CustomerUser.objects.get(user=request.user)
                customer = customer_user.customer

                if customer.phone == stored_number:
                    # Update both Customer and CustomerNotificationPreference
                    customer.phone_verified = True
                    customer.phone_verified_at = timezone.now()
                    customer.save()

                    # Also update notification preferences
                    prefs, created = CustomerNotificationPreference.objects.get_or_create(
                        customer=customer
                    )
                    prefs.phone_verified = True
                    prefs.phone_verified_at = timezone.now()
                    prefs.save()

                    messages.success(request, "Phone number verified successfully!")

                    # Clean up session
                    request.session.pop('customer_phone_verification_code', None)
                    request.session.pop('customer_phone_verification_number', None)
                    request.session.pop('customer_phone_verification_expires', None)
                else:
                    messages.error(request, "Phone number has changed. Please request a new verification code.")
            except CustomerUser.DoesNotExist:
                messages.error(request, "Customer profile not found.")
        else:
            messages.error(request, "Invalid verification code. Please try again.")

    return redirect('customer_notification_preferences')


@login_required
@customer_required
def customer_notification_history(request):
    """
    View all notifications for customer.

    Paginated list with filters (read/unread, category).
    """
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
    except CustomerUser.DoesNotExist:
        messages.error(request, "Customer profile not found.")
        return redirect('customer_dashboard')

    customer_ct = ContentType.objects.get_for_model(Customer)

    # Get notifications with optimized query
    notifications = Notification.objects.filter(
        recipient_type=customer_ct,
        recipient_id=customer.id
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
    paginator = Paginator(notifications, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'notifications': page_obj,
        'show_read': show_read,
        'category': category,
        'categories': Notification.CATEGORY_CHOICES,
        'customer': customer,
        'customer_user': customer_user,
    }

    return render(request, 'customer_portal/notification_history.html', context)


@login_required
@customer_required
def customer_mark_notification_read(request, notification_id):
    """Mark single notification as read (customer portal)"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        customer_ct = ContentType.objects.get_for_model(Customer)

        notification = Notification.objects.get(
            id=notification_id,
            recipient_type=customer_ct,
            recipient_id=customer.id
        )

        notification.mark_as_read()

        # Clear cache
        cache_key = f'notif_unread_count:customer:{customer.id}'
        cache.delete(cache_key)

        return JsonResponse({'success': True})

    except Notification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@customer_required
def customer_mark_all_read(request):
    """Mark all notifications as read for customer"""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        customer_ct = ContentType.objects.get_for_model(Customer)

        updated = Notification.objects.filter(
            recipient_type=customer_ct,
            recipient_id=customer.id,
            read=False
        ).update(read=True, read_at=timezone.now())

        # Clear cache
        cache_key = f'notif_unread_count:customer:{customer.id}'
        cache.delete(cache_key)

        return JsonResponse({'success': True, 'count': updated})

    except Exception as e:
        logger.error(f"Error marking all notifications as read: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@customer_required
def customer_get_unread_count(request):
    """
    AJAX endpoint for notification bell polling (customer portal).

    Implements caching to reduce database queries.
    Cache TTL: 2 minutes (same as technician portal).
    """
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        customer_ct = ContentType.objects.get_for_model(Customer)

        # Cache key for unread count
        cache_key = f'notif_unread_count:customer:{customer.id}'

        # Try to get from cache first
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            return JsonResponse(cached_data)

        # Cache miss - query database
        count = Notification.objects.filter(
            recipient_type=customer_ct,
            recipient_id=customer.id,
            read=False
        ).count()

        # Get recent notifications for dropdown
        recent_notifications = Notification.objects.filter(
            recipient_type=customer_ct,
            recipient_id=customer.id
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

        # Cache for 2 minutes
        cache.set(cache_key, response_data, 120)

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# INVOICES
# =============================================================================

@customer_required
def customer_invoices(request):
    """List all invoices for the logged-in customer (excluding drafts)."""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        invoices = Invoice.objects.filter(
            customer=customer
        ).exclude(status='DRAFT').order_by('-invoice_date', '-created_at')

        return render(request, 'customer_portal/invoices.html', {
            'invoices': invoices,
            'customer': customer,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_invoice_detail(request, invoice_id):
    """Full receipt view for a single invoice."""
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        invoice = get_object_or_404(Invoice, id=invoice_id, customer=customer)

        # Don't let customers see draft invoices
        if invoice.status == 'DRAFT':
            messages.warning(request, "This invoice is not available.")
            return redirect('customer_invoices')

        line_items = invoice.line_items.all().order_by('id')
        payments = invoice.payments.all().order_by('-payment_date')

        # Build PDF URL if s3_key exists
        pdf_url = None
        if invoice.s3_key:
            pdf_url = f"https://rs-systems-media-20251029.s3.amazonaws.com/{invoice.s3_key}"

        return render(request, 'customer_portal/invoice_detail.html', {
            'invoice': invoice,
            'line_items': line_items,
            'payments': payments,
            'pdf_url': pdf_url,
            'customer': customer,
        })
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_invoice_pay(request, invoice_id):
    """Create a Stripe checkout session and redirect to payment."""
    if request.method != 'POST':
        return redirect('customer_invoice_detail', invoice_id=invoice_id)

    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer

        invoice = get_object_or_404(Invoice, id=invoice_id, customer=customer)

        # Validate the invoice can be paid
        if invoice.status in ('CANCELLED', 'PAID', 'DRAFT'):
            messages.warning(request, "This invoice cannot be paid.")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        if invoice.amount_due <= 0:
            messages.info(request, "This invoice is already fully paid.")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        # If there's already a Stripe hosted URL, redirect there
        if invoice.stripe_hosted_url:
            return redirect(invoice.stripe_hosted_url)

        # Create a Stripe checkout session — prefer connected routing when the
        # shop has completed Stripe Connect onboarding.  Without this, customer
        # payments go to the platform account (Drake's) instead of the shop's
        # connected account, bypassing all platform-fee and payout logic.
        # (BUG: CODE-051 — missing Connect routing in customer portal pay view)
        from apps.billing.services.stripe_service import StripeService

        stripe_svc = StripeService()

        if not stripe_svc.is_enabled():
            messages.error(request, "Online payments are not currently available. Please contact us for payment options.")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
        success_url = f"{base_url}/app/invoices/{invoice.id}/?payment=success"
        cancel_url = f"{base_url}/app/invoices/{invoice.id}/?payment=cancelled"

        result = None

        # Use Stripe Connect (tenant-routed) checkout when shop is set up
        tenant = getattr(invoice, 'tenant', None)
        if tenant and tenant.can_accept_payments:
            try:
                from apps.tenants.services.connect_service import ConnectService
                connect_svc = ConnectService()
                result = connect_svc.create_connected_checkout_session(
                    invoice,
                    success_url=success_url,
                    cancel_url=cancel_url,
                )
            except Exception as e:
                logger.warning(
                    f"Connected checkout failed for {invoice.invoice_number}, "
                    f"falling back to platform: {e}"
                )
                result = None

        # Fall back to platform (Drake's account) checkout
        if not result or not result.get('success'):
            result = stripe_svc.create_checkout_session(
                invoice,
                success_url=success_url,
                cancel_url=cancel_url,
            )

        if result.get('success'):
            return redirect(result['checkout_url'])
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Stripe checkout failed for invoice {invoice.invoice_number}: {error_msg}")
            messages.error(request, f"Could not initiate payment: {error_msg}")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


# ============================================================================
# Customer Invitation Views
# ============================================================================

def accept_customer_invitation(request, token):
    """
    Accept a customer portal invitation.
    Creates account and links to customer.
    """
    from .models import CustomerInvitation
    from .services.invitation_service import CustomerInvitationService
    from apps.tenants.services.signup_service import generate_unique_username
    
    invitation = CustomerInvitationService.get_invitation_by_token(token)
    
    if not invitation:
        return render(request, 'customer_portal/invitation_invalid.html')
    
    # If user is already logged in
    if request.user.is_authenticated:
        from common.auth import get_user_role
        role = get_user_role(request.user)
        
        # Owners/managers already have full access — don't create CustomerUser
        if role in ('superuser', 'owner', 'manager'):
            invitation.mark_accepted(request.user)
            messages.info(
                request,
                f"Invitation accepted. You already have full access to "
                f"{invitation.customer.name} as a shop {role}."
            )
            return redirect('owner_dashboard')
        
        # Check if they already have a CustomerUser record
        existing = CustomerUser.objects.filter(user=request.user).first()
        if existing:
            if existing.customer == invitation.customer:
                messages.info(request, f"You're already set up for {invitation.customer.name}.")
            else:
                messages.warning(
                    request, 
                    f"You're already linked to {existing.customer.name}. "
                    f"Contact support if you need access to {invitation.customer.name}."
                )
            return redirect('customer_dashboard')
        
        # Link existing user to customer
        # Primary status is set explicitly by the owner when sending the invite.
        # No auto-promotion — the owner decides who is primary.
        if invitation.is_primary_contact:
            CustomerUser.objects.filter(
                customer=invitation.customer, is_primary_contact=True
            ).update(is_primary_contact=False)
        CustomerUser.objects.create(
            user=request.user,
            customer=invitation.customer,
            is_primary_contact=invitation.is_primary_contact,
        )
        invitation.mark_accepted(request.user)
        messages.success(request, f"Welcome! You now have access to {invitation.customer.name}.")
        return redirect('customer_dashboard')
    
    # Handle form submission for new user creation
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', invitation.email).strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        
        errors = []
        
        # Validate
        if not first_name:
            errors.append("First name is required.")
        if not password:
            errors.append("Password is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != password_confirm:
            errors.append("Passwords do not match.")
        if User.objects.filter(email__iexact=email).exists():
            errors.append("An account with this email already exists. Please log in instead.")
        
        if errors:
            return render(request, 'customer_portal/invitation_accept.html', {
                'invitation': invitation,
                'errors': errors,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
            })
        
        try:
            with transaction.atomic():
                # Create the user
                username = generate_unique_username(first_name or email.split('@')[0])
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                
                # Create CustomerUser link
                # Primary status is set explicitly by the owner when sending the invite.
                # No auto-promotion — the owner decides who is primary.
                if invitation.is_primary_contact:
                    CustomerUser.objects.filter(
                        customer=invitation.customer, is_primary_contact=True
                    ).update(is_primary_contact=False)
                CustomerUser.objects.create(
                    user=user,
                    customer=invitation.customer,
                    is_primary_contact=invitation.is_primary_contact,
                )
                
                # Mark invitation as accepted
                invitation.mark_accepted(user)
                
                # Log them in
                login(request, user)
                
                messages.success(
                    request, 
                    f"Welcome to {invitation.customer.name}! Your account has been created."
                )
                return redirect('customer_dashboard')
                
        except Exception as e:
            logger.error(f"Failed to create user from invitation: {e}")
            errors.append("An error occurred creating your account. Please try again.")
            return render(request, 'customer_portal/invitation_accept.html', {
                'invitation': invitation,
                'errors': errors,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
            })
    
    # GET request - show the form
    return render(request, 'customer_portal/invitation_accept.html', {
        'invitation': invitation,
        'first_name': invitation.first_name,
        'last_name': invitation.last_name,
        'email': invitation.email,
    })


# ============================================================================
# TEAM MANAGEMENT (Customer Self-Service)
# ============================================================================

@customer_required
def customer_team(request):
    """
    Team management page - list team members and pending invitations.
    Allows customers to invite their own team members (dispatchers, managers).
    """
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Get all team members (CustomerUser records for this customer)
        team_members = CustomerUser.objects.filter(customer=customer).select_related('user')
        
        # Get pending invitations
        pending_invitations = CustomerInvitation.objects.filter(
            customer=customer,
            status='pending'
        ).order_by('-created_at')
        
        # Mark expired invitations
        for inv in pending_invitations:
            if not inv.is_valid:
                inv.status = 'expired'
                inv.save(update_fields=['status'])
        
        # Refresh to get updated statuses
        pending_invitations = CustomerInvitation.objects.filter(
            customer=customer,
            status='pending'
        ).order_by('-created_at')
        
        return render(request, 'customer_portal/team.html', {
            'team_members': team_members,
            'pending_invitations': pending_invitations,
            'current_user': customer_user,
        })
        
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_invite_team_member(request):
    """
    Send an invitation to a new team member.
    """
    if request.method != 'POST':
        return redirect('customer_team')
    
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        email = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        
        # Validation
        if not email:
            messages.error(request, "Email address is required.")
            return redirect('customer_team')
        
        # Basic email format check
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            messages.error(request, "Please enter a valid email address.")
            return redirect('customer_team')
        
        # Check if already a team member
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user:
            existing_customer_user = CustomerUser.objects.filter(
                user=existing_user,
                customer=customer
            ).first()
            if existing_customer_user:
                messages.warning(request, f"{email} is already a team member.")
                return redirect('customer_team')
        
        # Check for existing pending invitation
        existing_invite = CustomerInvitation.objects.filter(
            customer=customer,
            email__iexact=email,
            status='pending'
        ).first()
        
        if existing_invite and existing_invite.is_valid:
            messages.info(request, f"An invitation to {email} is already pending.")
            return redirect('customer_team')
        
        # Create and send invitation
        from .services.invitation_service import CustomerInvitationService
        
        invitation = CustomerInvitationService.create_invitation(
            customer=customer,
            email=email,
            invited_by=request.user,
            first_name=first_name,
            last_name=last_name
        )
        
        # Send the email
        email_sent = CustomerInvitationService.send_invitation_email(invitation, request)
        
        if email_sent:
            messages.success(request, f"Invitation sent to {email}!")
        else:
            messages.warning(request, f"Invitation created but email could not be sent. They can still use the invite link.")
        
        return redirect('customer_team')
        
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')
    except Exception as e:
        logger.error(f"Error sending team invitation: {e}")
        messages.error(request, "An error occurred. Please try again.")
        return redirect('customer_team')


@customer_required
def customer_cancel_invitation(request, invitation_id):
    """
    Cancel a pending invitation.
    """
    if request.method != 'POST':
        return redirect('customer_team')
    
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        invitation = get_object_or_404(
            CustomerInvitation,
            id=invitation_id,
            customer=customer,
            status='pending'
        )
        
        from .services.invitation_service import CustomerInvitationService
        CustomerInvitationService.cancel_invitation(invitation)
        
        messages.success(request, f"Invitation to {invitation.email} cancelled.")
        return redirect('customer_team')
        
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_resend_invitation(request, invitation_id):
    """
    Resend a pending invitation (extends expiry).
    """
    if request.method != 'POST':
        return redirect('customer_team')
    
    try:
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        invitation = get_object_or_404(
            CustomerInvitation,
            id=invitation_id,
            customer=customer
        )
        
        if invitation.status == 'accepted':
            messages.warning(request, "This invitation has already been accepted.")
            return redirect('customer_team')
        
        from .services.invitation_service import CustomerInvitationService
        success = CustomerInvitationService.resend_invitation(invitation, request)
        
        if success:
            messages.success(request, f"Invitation resent to {invitation.email}!")
        else:
            messages.error(request, "Could not resend invitation.")
        
        return redirect('customer_team')
        
    except CustomerUser.DoesNotExist:
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


# =============================================================================
# ONE-CLICK APPROVAL VIEWS (no login required — token-based)
# =============================================================================

def quick_approve_repair(request, token):
    """One-click repair approval via tokenized email link."""
    try:
        approval_token = ApprovalToken.objects.select_related(
            'repair', 'repair__customer', 'repair__technician', 'customer_user'
        ).get(token=token, action='approve')
    except ApprovalToken.DoesNotExist:
        return render(request, 'customer_portal/quick_action_expired.html', {
            'reason': 'This approval link is invalid or has already been used.'
        })

    if not approval_token.is_valid():
        reason = 'This approval link has already been used.' if approval_token.used_at else 'This approval link has expired.'
        return render(request, 'customer_portal/quick_action_expired.html', {'reason': reason})

    repair = approval_token.repair
    if repair.queue_status not in ('PENDING', 'REQUESTED'):
        return render(request, 'customer_portal/quick_action_expired.html', {
            'reason': f'This repair has already been {repair.get_queue_status_display().lower()}.'
        })

    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        customer_user = approval_token.customer_user

        try:
            with transaction.atomic():
                # Re-fetch token under a row lock to prevent double-submission race
                locked_token = ApprovalToken.objects.select_for_update().get(
                    pk=approval_token.pk
                )
                if not locked_token.is_valid():
                    # Another concurrent request already consumed this token
                    return render(request, 'customer_portal/quick_action_expired.html', {
                        'reason': 'This approval link has already been used.'
                    })

                # Re-check repair status inside the lock
                locked_repair = Repair.objects.select_for_update().get(pk=repair.pk)
                if locked_repair.queue_status not in ('PENDING', 'REQUESTED'):
                    return render(request, 'customer_portal/quick_action_expired.html', {
                        'reason': f'This repair has already been {locked_repair.get_queue_status_display().lower()}.'
                    })

                # Create or update approval
                approval, created = RepairApproval.objects.get_or_create(
                    repair=locked_repair,
                    defaults={
                        'approved': True,
                        'approved_by': customer_user,
                        'approval_date': timezone.now(),
                        'notes': notes,
                    }
                )
                if not created:
                    approval.approved = True
                    approval.approved_by = customer_user
                    approval.approval_date = timezone.now()
                    approval.notes = notes
                    approval.save()

                locked_repair.queue_status = 'APPROVED'
                locked_repair.save()

                # Notify technician
                if locked_repair.technician:
                    TechnicianNotification.objects.create(
                        technician=locked_repair.technician,
                        message=f"✅ Repair #{locked_repair.id} APPROVED by {locked_repair.customer.name} - Unit {locked_repair.unit_number}. You can now complete the work.",
                        read=False,
                        repair=locked_repair,
                    )

                locked_token.mark_used()

                # Also invalidate the corresponding deny token
                ApprovalToken.objects.filter(
                    repair=locked_repair, customer_user=customer_user, action='deny', used_at__isnull=True
                ).update(used_at=timezone.now())

        except Repair.DoesNotExist:
            return render(request, 'customer_portal/quick_action_expired.html', {
                'reason': 'This repair no longer exists.'
            })

        return render(request, 'customer_portal/quick_approve_success.html', {'repair': repair})

    return render(request, 'customer_portal/quick_approve_confirm.html', {
        'repair': repair,
        'token': token,
    })


def quick_deny_repair(request, token):
    """One-click repair denial via tokenized email link."""
    try:
        approval_token = ApprovalToken.objects.select_related(
            'repair', 'repair__customer', 'repair__technician', 'customer_user'
        ).get(token=token, action='deny')
    except ApprovalToken.DoesNotExist:
        return render(request, 'customer_portal/quick_action_expired.html', {
            'reason': 'This denial link is invalid or has already been used.'
        })

    if not approval_token.is_valid():
        reason = 'This link has already been used.' if approval_token.used_at else 'This link has expired.'
        return render(request, 'customer_portal/quick_action_expired.html', {'reason': reason})

    repair = approval_token.repair
    if repair.queue_status not in ('PENDING', 'REQUESTED'):
        return render(request, 'customer_portal/quick_action_expired.html', {
            'reason': f'This repair has already been {repair.get_queue_status_display().lower()}.'
        })

    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        customer_user = approval_token.customer_user

        try:
            with transaction.atomic():
                # Re-fetch token under a row lock to prevent double-submission race
                locked_token = ApprovalToken.objects.select_for_update().get(
                    pk=approval_token.pk
                )
                if not locked_token.is_valid():
                    # Another concurrent request already consumed this token
                    return render(request, 'customer_portal/quick_action_expired.html', {
                        'reason': 'This denial link has already been used.'
                    })

                # Re-check repair status inside the lock
                locked_repair = Repair.objects.select_for_update().get(pk=repair.pk)
                if locked_repair.queue_status not in ('PENDING', 'REQUESTED'):
                    return render(request, 'customer_portal/quick_action_expired.html', {
                        'reason': f'This repair has already been {locked_repair.get_queue_status_display().lower()}.'
                    })

                approval, created = RepairApproval.objects.get_or_create(
                    repair=locked_repair,
                    defaults={
                        'approved': False,
                        'approved_by': customer_user,
                        'approval_date': timezone.now(),
                        'notes': reason,
                    }
                )
                if not created:
                    approval.approved = False
                    approval.approved_by = customer_user
                    approval.approval_date = timezone.now()
                    approval.notes = reason
                    approval.save()

                locked_repair.queue_status = 'DENIED'
                locked_repair.save()

                # Notify technician
                if locked_repair.technician:
                    denial_message = f"❌ Repair #{locked_repair.id} DENIED by {locked_repair.customer.name} - Unit {locked_repair.unit_number}."
                    if reason:
                        denial_message += f" Reason: {reason}"
                    TechnicianNotification.objects.create(
                        technician=locked_repair.technician,
                        message=denial_message,
                        read=False,
                        repair=locked_repair,
                    )

                locked_token.mark_used()

                # Invalidate the corresponding approve token
                ApprovalToken.objects.filter(
                    repair=locked_repair, customer_user=customer_user, action='approve', used_at__isnull=True
                ).update(used_at=timezone.now())

        except Repair.DoesNotExist:
            return render(request, 'customer_portal/quick_action_expired.html', {
                'reason': 'This repair no longer exists.'
            })

        return render(request, 'customer_portal/quick_deny_success.html', {'repair': repair})

    return render(request, 'customer_portal/quick_deny_confirm.html', {
        'repair': repair,
        'token': token,
    })
