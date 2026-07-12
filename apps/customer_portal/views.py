from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.conf import settings
from django.core.cache import cache
from django.contrib.contenttypes.models import ContentType
from core.models import Customer
from apps.technician_portal.models import Repair, Replacement, UnitRepairCount, TechnicianNotification, Technician
from apps.rewards_referrals.models import ReferralCode, RewardOption, RewardRedemption, Referral
from apps.rewards_referrals.services import LoyaltyService, ReferralService, RewardService
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
from django.db import models, transaction, IntegrityError
from django.contrib.auth import update_session_auth_hash
from functools import wraps
from django.http import HttpResponse, JsonResponse
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
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from core.services.sms_service import SMSService

logger = logging.getLogger(__name__)

# Custom decorator to ensure only customers can access views
def _get_customer_user_for_tenant(request):
    """
    Return the CustomerUser for the current user scoped to the current tenant.

    CustomerUser.user is a OneToOneField so at most one CustomerUser record can
    exist per user.  The per-tenant scope (customer__tenant=tenant) is still
    important: it validates that the user's CustomerUser actually belongs to the
    shop currently in the request context.  Without this check, a customer at
    Shop A who navigates to Shop B's customer portal URL would get their
    CustomerUser back (for Shop A) and the view would silently operate on the
    wrong shop's data.  (CODE-102)

    Returns None if:
    - The user has no CustomerUser record at all, OR
    - The user's CustomerUser belongs to a different tenant than the current one.

    Falls back to a simple filter (no tenant scope) when there is no tenant
    context on the request (tests, admin-only environments).
    """
    tenant = getattr(request, 'tenant', None)
    if tenant:
        return CustomerUser.objects.filter(
            user=request.user, customer__tenant=tenant
        ).select_related('customer__tenant').first()
    # No tenant context — fall back to unscoped lookup (tests / admin-only paths)
    return CustomerUser.objects.filter(user=request.user).select_related('customer__tenant').first()


def customer_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.info(request, "Please log in to access the customer portal.")
            return redirect('login')

        # Check if user has a customer profile scoped to the current tenant.
        # Use the tenant-aware helper to avoid MultipleObjectsReturned for users
        # who have joined more than one shop. (CODE-102)
        customer_user = _get_customer_user_for_tenant(request)
        if customer_user is None:
            # Redirect user to profile creation if they don't have a profile
            messages.info(request, "Please complete your profile setup to access customer features.")
            return redirect('profile_creation')
        return view_func(request, *args, **kwargs)
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
        customer_user = _get_customer_user_for_tenant(request)
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

        # CODE-141: Collapse 7 individual COUNT/SUM queries into one aggregate() call.
        # Each separate .count()/.filter().count()/.aggregate() hit the DB independently.
        # A single annotated aggregate eliminates 6 round-trips per dashboard load.
        from decimal import Decimal as _Decimal
        from django.db.models import DecimalField as _DecimalField
        from django.db.models.functions import Coalesce
        agg = base_qs.aggregate(
            _requested=Count('id', filter=Q(queue_status='REQUESTED')),
            _pending=Count('id', filter=Q(queue_status='PENDING')),
            _approved=Count('id', filter=Q(queue_status='APPROVED')),
            _in_progress=Count('id', filter=Q(queue_status='IN_PROGRESS')),
            _completed=Count('id', filter=Q(queue_status='COMPLETED')),
            _denied=Count('id', filter=Q(queue_status='DENIED')),
            # Coalesce default must be Decimal to match Sum(DecimalField) output type.
            _total_spent=Coalesce(
                Sum('cost', filter=Q(queue_status='COMPLETED')),
                _Decimal('0'),
                output_field=_DecimalField(),
            ),
        )
        completed_repairs = agg['_completed']
        pending_approval = agg['_pending']
        active_repairs = agg['_requested'] + agg['_pending'] + agg['_approved'] + agg['_in_progress']
        total_spent = agg['_total_spent']
        
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

        # Replacement stats and lists — mirrors the repair aggregate above so
        # the dashboard covers both service types (replacement shops would
        # otherwise see an empty dashboard). All existing repair-only context
        # keys are preserved; the combined keys below are additive.
        repl_qs = Replacement.objects.filter(customer=customer, tenant=tenant)
        repl_agg = repl_qs.aggregate(
            _requested=Count('id', filter=Q(queue_status='REQUESTED')),
            _pending=Count('id', filter=Q(queue_status='PENDING')),
            _approved=Count('id', filter=Q(queue_status='APPROVED')),
            _in_progress=Count('id', filter=Q(queue_status='IN_PROGRESS')),
            _completed=Count('id', filter=Q(queue_status='COMPLETED')),
            _total_spent=Coalesce(
                Sum('cost', filter=Q(queue_status='COMPLETED')),
                _Decimal('0'),
                output_field=_DecimalField(),
            ),
        )
        active_replacements = (
            repl_agg['_requested'] + repl_agg['_pending']
            + repl_agg['_approved'] + repl_agg['_in_progress']
        )
        pending_approval_replacements = list(
            repl_qs.filter(queue_status='PENDING')
                   .select_related('technician__user').order_by('-service_date')
        )
        recent_replacements = list(
            repl_qs.select_related('technician__user').order_by('-service_date')[:5]
        )

        # Merge the two service types into one recency-ordered list for the
        # "Recent Services" section (same item_type tagging pattern as the
        # owner dashboard timeline).
        from itertools import chain
        for _r in recent_repairs:
            _r.service_type = 'repair'
        for _r in recent_replacements:
            _r.service_type = 'replacement'
        recent_services = sorted(
            chain(recent_repairs, recent_replacements),
            key=lambda s: s.service_date,
            reverse=True,
        )[:5]

        # Get repairs that are awaiting customer approval
        repairs_awaiting_approval = base_qs.filter(
            queue_status='PENDING'
        ).select_related('technician__user').order_by('-service_date')

        # Group batched repairs and separate individual repairs.
        # CODE-168: Bulk-fetch all batch siblings in ONE query to avoid ~4 DB
        # queries per unique batch ID (same N+1 fixed for technician dashboard
        # in CODE-142).  Strategy mirrors the technician dashboard fix:
        #   1. Collect all unique batch IDs from the PENDING repairs list.
        #   2. Fetch every sibling repair for those batches in a single queryset.
        #   3. Group in Python by batch_id.
        #   4. Build summaries via build_batch_summary_from_repairs() — zero
        #      additional DB queries.
        # Without this fix, a customer with N unique pending batches causes ~4N
        # DB queries on every dashboard load.
        _awaiting_list = list(repairs_awaiting_approval)
        _pending_batch_ids = {
            r.repair_batch_id
            for r in _awaiting_list
            if r.is_part_of_batch and r.repair_batch_id
        }

        _prefetched_pending_batches: dict = {}
        if _pending_batch_ids:
            _sibling_qs = Repair.objects.filter(
                repair_batch_id__in=_pending_batch_ids,
            ).select_related('customer', 'technician__user').order_by('break_number')
            if tenant:
                _sibling_qs = _sibling_qs.filter(tenant=tenant)
            for _r in _sibling_qs:
                _prefetched_pending_batches.setdefault(_r.repair_batch_id, []).append(_r)

        batch_repairs = {}  # Dictionary: batch_id -> batch_summary
        individual_repairs = []  # List of non-batched repairs

        for repair in _awaiting_list:
            if repair.is_part_of_batch:
                # Only add batch summary once (for the first repair in batch we encounter)
                if repair.repair_batch_id not in batch_repairs:
                    _siblings = _prefetched_pending_batches.get(repair.repair_batch_id)
                    if _siblings:
                        batch_summary = Repair.build_batch_summary_from_repairs(
                            repair.repair_batch_id, _siblings
                        )
                    else:
                        # Fallback to legacy path (should not be hit after bulk-fetch)
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
            # Detailed repair status counts for the visualization (from single aggregate — CODE-141)
            'repairs_requested': agg['_requested'],
            'repairs_pending': pending_approval,
            'repairs_approved': agg['_approved'],
            'repairs_in_progress': agg['_in_progress'],
            'repairs_completed': completed_repairs,
            'repairs_denied': agg['_denied'],
        }
        
        # Get referral and reward information
        # Get user's referral code (or None if they don't have one)
        referral_code = ReferralCode.objects.filter(customer_user=customer_user).first()
        referral_code_value = referral_code.code if referral_code else None
        
        # Get number of successful referrals
        referral_count = ReferralService.get_referral_count(customer_user)
        
        # Get reward points balance
        reward_points = RewardService.get_reward_balance(customer_user)
        
        # Get outstanding invoices for the customer.
        # CODE-149: aggregate on the FULL queryset BEFORE slicing so outstanding_total
        # reflects ALL unpaid invoices, not just the first 5 shown on the dashboard.
        # Slicing (`[:5]`) causes Django to wrap the queryset in a subquery, so
        # aggregate() on the sliced version only sums the limited rows, not all of them.
        # CODE-159: Use Sum('total') - Sum('amount_paid') to correctly reflect the
        # remaining balance for PARTIAL invoices.  Using Sum('total') alone overstates
        # the outstanding amount — a $500 invoice with $300 already paid would be
        # counted as $500 owed instead of $200.  Mirrors the correct formula used in
        # the owner invoice list (owner_invoice_list in saas/views.py).
        # CODE-262: Add tenant filter for defense-in-depth tenant isolation.
        # CODE-255 added tenant= to the invoice list/detail/pay views but
        # missed the dashboard's outstanding invoices query.
        _outstanding_qs = Invoice.objects.filter(
            customer=customer,
            tenant=tenant,
            status__in=['SENT', 'OVERDUE', 'PARTIAL']
        ).order_by('due_date')
        _outstanding_agg = _outstanding_qs.aggregate(
            _total=Sum('total'),
            _paid=Sum('amount_paid'),
        )
        outstanding_total = (
            (_outstanding_agg['_total'] or 0) - (_outstanding_agg['_paid'] or 0)
        )
        outstanding_invoices = _outstanding_qs[:5]  # Display slice AFTER aggregate
        overdue_count = Invoice.objects.filter(
            customer=customer,
            tenant=tenant,
            status='OVERDUE'
        ).count()
        
        # Greeting name — first_name can be blank (e.g. invited users who
        # skipped it), so fall back to the full name, then the company name.
        display_name = (
            request.user.first_name.strip()
            or request.user.get_full_name().strip()
            or customer.name
        )

        context = {
            'customer': customer,
            'stats': stats,
            'active_repairs_count': active_repairs,
            'completed_repairs_count': completed_repairs,
            'pending_approval_count': pending_approval,
            'recent_repairs': recent_repairs,
            'pending_approval_repairs': repairs_awaiting_approval,
            # Combined repair + replacement service data (additive — the
            # repair-only keys above are still used by older templates/tests)
            'display_name': display_name,
            'recent_services': recent_services,
            'pending_approval_replacements': pending_approval_replacements,
            'pending_services_count': pending_approval + repl_agg['_pending'],
            'active_services_count': active_repairs + active_replacements,
            'completed_services_count': completed_repairs + repl_agg['_completed'],
            'total_spent_services': total_spent + repl_agg['_total_spent'],
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
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@login_required
def profile_creation(request):
    # Check if user already has a CustomerUser profile scoped to THIS tenant.
    # CustomerUser.user is a OneToOneField (one per User globally), so we must
    # distinguish three cases to avoid an infinite redirect loop:
    #
    #   A) Already linked to this tenant → redirect to dashboard (setup done).
    #   B) Linked to a *different* shop → cannot create a second CustomerUser;
    #      show a clear message instead of looping dashboard ↔ profile_creation.
    #   C) No CustomerUser yet → let them proceed with the form.
    #
    # The old code used an *unscoped* .exists() check: a user with a CustomerUser
    # at Shop A visiting Shop B was redirected to customer_dashboard, which found
    # no profile for Shop B, then redirected back here — causing an infinite loop.
    # (CODE-107: fix redirect loop in profile_creation for cross-shop users)
    tenant = getattr(request, 'tenant', None)
    existing_cu = CustomerUser.objects.filter(user=request.user).select_related('customer__tenant').first()
    if existing_cu:
        if tenant and existing_cu.customer.tenant_id == tenant.id:
            # Case A — already set up for this shop.
            return redirect('customer_dashboard')
        # Case B — linked to a different shop; redirect with explanation.
        other_shop = existing_cu.customer.tenant
        messages.warning(
            request,
            f"Your account is already linked to {existing_cu.customer.name}"
            + (f" ({other_shop.name})" if other_shop and other_shop != tenant else "")
            + ". Customer portal accounts can only be linked to one shop. "
            "If you need access here, please ask the shop to invite you."
        )
        return redirect('login')
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
            is_primary = request.POST.get('is_primary_contact') == 'True'
            # If this user wants to be the primary contact, demote any existing
            # primary first.  Without this step, two CustomerUsers for the same
            # company can simultaneously hold is_primary_contact=True, making
            # notification routing non-deterministic.
            # This mirrors the demotion logic in:
            #   - account_settings() (CODE-116)
            #   - accept_customer_invitation() and set_primary_contact()
            # Only applies when joining an EXISTING company; new companies have
            # no existing primary to demote.
            if is_primary and not is_new_company:
                CustomerUser.objects.filter(
                    customer=customer, is_primary_contact=True
                ).update(is_primary_contact=False)
            customer_user = CustomerUser.objects.create(
                user=request.user,
                customer=customer,
                is_primary_contact=is_primary,
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
        customer_user = _get_customer_user_for_tenant(request)
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
        # CODE-249: Use a separate base queryset for stats so they always reflect
        # global totals, regardless of active filters. Previously stats were
        # computed on the filtered queryset — filtering to e.g. "COMPLETED"
        # made pending_approval=0, which is misleading. Mirrors the correct
        # pattern already used in customer_replacements().
        base_repairs = Repair.objects.filter(
            customer=customer,
            tenant=customer.tenant,
        )
        repairs = base_repairs.select_related('technician__user')

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

        # Calculate summary statistics from the UNFILTERED base queryset so
        # stat badges always show global totals. (CODE-249)
        from decimal import Decimal
        month_start = timezone.now().date().replace(day=1)
        stats_agg = base_repairs.aggregate(
            total_repairs=Count('id'),
            pending_approval=Count('id', filter=Q(queue_status='PENDING')),
            in_progress=Count('id', filter=Q(queue_status__in=['APPROVED', 'IN_PROGRESS'])),
            completed_this_month=Count(
                'id',
                filter=Q(queue_status='COMPLETED', service_date__gte=month_start),
            ),
            total_cost=Sum('cost', filter=Q(queue_status='COMPLETED')),
        )
        stats = {
            'total_repairs': stats_agg['total_repairs'] or 0,
            'pending_approval': stats_agg['pending_approval'] or 0,
            'in_progress': stats_agg['in_progress'] or 0,
            'completed_this_month': stats_agg['completed_this_month'] or 0,
            'total_cost': stats_agg['total_cost'] or Decimal('0.00'),
        }
        total_repairs = stats['total_repairs']

        # Evaluate the queryset once into a list.
        # The queryset is used in two consecutive loops (flag-setting, then
        # batch-grouping).  If we iterate the unevaluated queryset twice, Django
        # fires two separate DB queries AND the Python objects produced by loop 1
        # are discarded — loop 2 creates fresh objects that never received the
        # `.customer_initiated` attribute, so templates either raise AttributeError
        # or silently show the wrong value. (CODE-176)
        repairs = list(repairs)

        # Check which repairs were customer-initiated and mark them.
        # IDs are extracted in Python (free — list already in memory) instead of
        # firing a third DB round-trip via .values_list('id', flat=True).
        repair_ids = [r.id for r in repairs]
        customer_initiated_approvals = set(
            RepairApproval.objects.filter(
                repair_id__in=repair_ids,
                notes="Auto-approved as customer initiated the request"
            ).values_list('repair_id', flat=True)
        )

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

        # Guard: int() raises ValueError on non-numeric input (e.g. ?page_size=abc).
        # Without this guard, an invalid page_size causes a 500 error instead of
        # silently falling back to the default.  (CODE-205)
        try:
            page_size = int(request.GET.get('page_size', 50))
        except (ValueError, TypeError):
            page_size = 50
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
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_repair_detail(request, repair_id):
    try:
        customer_user = _get_customer_user_for_tenant(request)
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

        # Available monetary rewards the customer can apply (before invoicing)
        available_rewards = []
        is_invoiced = repair.invoice_line_items.exists()
        if not is_invoiced and repair.queue_status not in ('COMPLETED', 'DENIED'):
            # Only show APPROVED rewards — PENDING (not yet approved by shop),
            # REJECTED, and FULFILLED (already used) must not be selectable.
            # Previously this filtered status__in=['PENDING', 'FULFILLED'] which
            # showed unapproved and already-fulfilled rewards.  The correct status
            # is 'APPROVED', matching _get_available_monetary_rewards().  (CODE-251)
            available_rewards = RewardRedemption.objects.filter(
                reward__customer_user=customer_user,
                status='APPROVED',
                applied_to_repair__isnull=True,
                reward_option__reward_type__category__in=['REPAIR_DISCOUNT', 'FREE_SERVICE'],
            ).select_related('reward_option', 'reward_option__reward_type')

        return render(request, 'customer_portal/repair_detail.html', {
            'repair': repair,
            'customer': customer,
            'approval': approval,
            'available_rewards': available_rewards,
            'is_invoiced': is_invoiced,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_apply_reward(request, repair_id):
    """POST-only: customer applies a monetary reward to a repair before invoicing."""
    if request.method != 'POST':
        return redirect('customer_repair_detail', repair_id=repair_id)

    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        repair = get_object_or_404(Repair, id=repair_id, customer=customer, tenant=customer.tenant)

        # Guard: cannot apply after invoicing
        if repair.invoice_line_items.exists():
            messages.error(request, "This repair has already been invoiced. Rewards cannot be applied.")
            return redirect('customer_repair_detail', repair_id=repair_id)

        # Guard: cannot apply to denied/completed repairs
        if repair.queue_status in ('COMPLETED', 'DENIED'):
            messages.error(request, "Rewards cannot be applied to completed or denied repairs.")
            return redirect('customer_repair_detail', repair_id=repair_id)

        redemption_id = request.POST.get('redemption_id')
        if not redemption_id:
            messages.error(request, "No reward selected.")
            return redirect('customer_repair_detail', repair_id=repair_id)

        # Verify the redemption belongs to this customer, is APPROVED, and is
        # not yet applied.  The status='APPROVED' guard prevents applying a
        # PENDING (unapproved), REJECTED, or FULFILLED redemption via a crafted
        # POST.  Previously the status was not checked here — only the display
        # queryset filtered by status.  (CODE-251)
        redemption = get_object_or_404(
            RewardRedemption,
            id=redemption_id,
            reward__customer_user=customer_user,
            status='APPROVED',
            applied_to_repair__isnull=True,
            reward_option__reward_type__category__in=['REPAIR_DISCOUNT', 'FREE_SERVICE'],
        )

        # Check this repair doesn't already have a reward applied
        if repair.applied_rewards.exists():
            messages.error(request, "This repair already has a reward applied. Only one reward per repair.")
            return redirect('customer_repair_detail', repair_id=repair_id)

        # Apply the reward
        redemption.applied_to_repair = repair
        redemption.save()

        messages.success(request, f'Reward "{redemption.reward_option.name}" applied to Repair #{repair.id}.')
        return redirect('customer_repair_detail', repair_id=repair_id)

    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_repair_approve(request, repair_id):
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        
        # Get the repair and ensure it belongs to this customer (tenant-scoped)
        repair = get_object_or_404(Repair, id=repair_id, customer=customer, tenant=customer.tenant)

        # Guard: only PENDING or REQUESTED repairs can be approved by the customer.
        # The template hides the button for other statuses but there is no server-side
        # check, so a direct POST could corrupt COMPLETED, IN_PROGRESS, or DENIED
        # repairs by overwriting queue_status → 'APPROVED'. (CODE-061)
        if repair.queue_status not in ('PENDING', 'REQUESTED'):
            messages.warning(request, "This repair cannot be approved — it is not pending approval.")
            return redirect('customer_repair_detail', repair_id=repair.id)
        
        if request.method == 'POST':
            notes = request.POST.get('notes', '')
            
            # CODE-262: If repair is part of a batch, approve ALL siblings.
            # Fleet managers expect "approve" to cover the whole job, not one chip.
            is_batch = repair.is_part_of_batch
            batch_id = repair.repair_batch_id if is_batch else None

            with transaction.atomic():
                if is_batch and batch_id:
                    # Lock ALL batch siblings for atomic approval
                    repairs_to_approve = list(
                        Repair.objects.select_for_update().filter(
                            repair_batch_id=batch_id,
                            tenant=customer.tenant,
                            queue_status__in=('PENDING', 'REQUESTED'),
                        ).select_related('technician')
                    )
                else:
                    locked_repair = Repair.objects.select_for_update().get(pk=repair.pk)
                    if locked_repair.queue_status not in ('PENDING', 'REQUESTED'):
                        messages.warning(request, "This repair has already been processed.")
                        return redirect('customer_repair_detail', repair_id=repair.id)
                    repairs_to_approve = [locked_repair]

                if not repairs_to_approve:
                    messages.warning(request, "This repair has already been processed.")
                    return redirect('customer_repair_detail', repair_id=repair.id)

                for r in repairs_to_approve:
                    RepairApproval.objects.update_or_create(
                        repair=r,
                        defaults={
                            'approved': True,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': notes or (f'Batch approval ({len(repairs_to_approve)} breaks)' if is_batch else ''),
                        }
                    )
                    r.queue_status = 'APPROVED'
                    if not r.technician:
                        logger.warning(f"Repair #{r.id} approved but has no technician assigned")
                    r.save()

            # Create notification for technician (outside transaction — best effort)
            technician = repairs_to_approve[0].technician if repairs_to_approve else None
            if technician:
                if is_batch and len(repairs_to_approve) > 1:
                    TechnicianNotification.objects.create(
                        technician=technician,
                        message=f"✅ Batch of {len(repairs_to_approve)} breaks APPROVED by {customer.name} - Unit {repair.unit_number}.",
                        read=False,
                        repair=repairs_to_approve[0],
                        repair_batch_id=batch_id,
                    )
                else:
                    TechnicianNotification.objects.create(
                        technician=technician,
                        message=f"✅ Repair #{repair.id} APPROVED by {customer.name} - Unit {repair.unit_number}. You can now complete the work.",
                        read=False,
                        repair=repairs_to_approve[0],
                    )

            approved_count = len(repairs_to_approve)
            if is_batch and approved_count > 1:
                messages.success(request, f"All {approved_count} breaks in this batch have been approved. The technician can now complete the work.")
            else:
                messages.success(request, "Repair has been approved successfully. The technician can now complete the work.")
            return redirect('customer_repair_detail', repair_id=repair.id)
        
        return render(request, 'customer_portal/repair_approve.html', {
            'repair': repair,
            'customer': customer
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_repair_deny(request, repair_id):
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        
        # Get the repair and ensure it belongs to this customer (tenant-scoped)
        repair = get_object_or_404(Repair, id=repair_id, customer=customer, tenant=customer.tenant)

        # Guard: only PENDING or REQUESTED repairs can be denied by the customer.
        # Without this check, a direct POST could flip a COMPLETED repair to DENIED,
        # breaking invoicing and losing data. (CODE-061)
        if repair.queue_status not in ('PENDING', 'REQUESTED'):
            messages.warning(request, "This repair cannot be denied — it is not pending approval.")
            return redirect('customer_repair_detail', repair_id=repair.id)
        
        if request.method == 'POST':
            reason = request.POST.get('reason', '')
            
            # CODE-262: If repair is part of a batch, deny ALL siblings.
            is_batch = repair.is_part_of_batch
            batch_id = repair.repair_batch_id if is_batch else None

            restored = []
            with transaction.atomic():
                if is_batch and batch_id:
                    repairs_to_deny = list(
                        Repair.objects.select_for_update().filter(
                            repair_batch_id=batch_id,
                            tenant=customer.tenant,
                            queue_status__in=('PENDING', 'REQUESTED'),
                        ).select_related('technician')
                    )
                else:
                    locked_repair = Repair.objects.select_for_update().get(pk=repair.pk)
                    if locked_repair.queue_status not in ('PENDING', 'REQUESTED'):
                        messages.warning(request, "This repair has already been processed.")
                        return redirect('customer_repair_detail', repair_id=repair.id)
                    repairs_to_deny = [locked_repair]

                if not repairs_to_deny:
                    messages.warning(request, "This repair has already been processed.")
                    return redirect('customer_repair_detail', repair_id=repair.id)

                for r in repairs_to_deny:
                    RepairApproval.objects.update_or_create(
                        repair=r,
                        defaults={
                            'approved': False,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': reason or (f'Batch denial ({len(repairs_to_deny)} breaks)' if is_batch else ''),
                        }
                    )
                    r.queue_status = 'DENIED'
                    r.save()
                    restored.extend(_restore_reward_for_repair(r))

            for redemption in restored:
                messages.info(
                    request,
                    f'Your "{redemption.reward_option.name}" reward has been restored and can be used on your next repair.'
                )

            # Create notification for technician (outside transaction — best effort)
            technician = repairs_to_deny[0].technician if repairs_to_deny else None
            denied_count = len(repairs_to_deny)
            if technician:
                if is_batch and denied_count > 1:
                    denial_message = f"❌ Batch of {denied_count} breaks DENIED by {customer.name} - Unit {repair.unit_number}."
                    if reason:
                        denial_message += f" Reason: {reason}"
                else:
                    denial_message = f"❌ Repair #{repair.id} DENIED by {customer.name} - Unit {repair.unit_number}."
                    if reason:
                        denial_message += f" Reason: {reason}"
                # CODE-263: Use `technician` (extracted from repairs_to_deny[0]
                # above) instead of `locked_repair.technician`.  `locked_repair`
                # is only defined in the non-batch code path — in the batch path
                # it was a NameError that crashed the entire deny flow, leaving
                # repairs stuck in DENIED status with no technician notification.
                TechnicianNotification.objects.create(
                    technician=technician,
                    message=denial_message,
                    read=False,
                    repair=repairs_to_deny[0],
                    **({"repair_batch_id": batch_id} if is_batch and batch_id else {}),
                )

            if is_batch and denied_count > 1:
                messages.success(request, f"All {denied_count} breaks in this batch have been denied.")
            else:
                messages.success(request, "Repair request has been denied.")
            return redirect('customer_repair_detail', repair_id=repair.id)
        
        return render(request, 'customer_portal/repair_deny.html', {
            'repair': repair,
            'customer': customer
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

# Multi-Break Batch Views
@customer_required
def customer_batch_detail(request, batch_id):
    """Display all repairs in a batch with batch approval options"""
    try:
        customer_user = _get_customer_user_for_tenant(request)
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
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_batch_approve(request, batch_id):
    """Approve all repairs in a batch (all-or-nothing transaction)"""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        # Scope to tenant to prevent cross-tenant IDOR via batch UUID.
        batch_summary = Repair.get_batch_summary(batch_id, tenant=customer.tenant)

        if not batch_summary or batch_summary['customer'] != customer:
            messages.error(request, "Batch not found or you don't have access to it.")
            return redirect('customer_dashboard')

        # Guard: batch can only be approved when ALL repairs are pending approval.
        # Without this, a direct POST on a COMPLETED or DENIED batch would overwrite
        # every repair's queue_status back to APPROVED. (CODE-061)
        approvable_statuses = {'PENDING', 'REQUESTED'}
        batch_statuses = set(batch_summary.get('statuses', []))
        if not batch_statuses.issubset(approvable_statuses):
            messages.warning(request, "This batch cannot be approved — not all repairs are pending approval.")
            return redirect('customer_dashboard')

        if request.method == 'POST':
            # Use a transaction + row-level locks to prevent double-click race
            # conditions that create duplicate RepairApproval records and
            # TechnicianNotification records.  The single-repair views were
            # fixed in CODE-223 and replacements in CODE-234, but the batch
            # views were missed — they used @transaction.atomic without
            # select_for_update().  (CODE-254)
            technician = None
            approved_count = 0
            break_count = batch_summary['break_count']
            unit_number = batch_summary['unit_number']
            total_cost = batch_summary['total_cost']

            with transaction.atomic():
                # Re-fetch all batch repairs with row-level locks
                locked_repairs = list(
                    Repair.objects.select_for_update().filter(
                        repair_batch_id=batch_id,
                        tenant=customer.tenant,
                    ).select_related('technician')
                )

                if not locked_repairs:
                    messages.error(request, "Batch not found.")
                    return redirect('customer_dashboard')

                # Re-check ALL statuses inside the lock — a concurrent request
                # may have already approved/denied some or all repairs.
                for repair in locked_repairs:
                    if repair.queue_status not in ('PENDING', 'REQUESTED'):
                        messages.warning(request, "This batch has already been processed.")
                        return redirect('customer_dashboard')

                # All repairs are still pending — approve them
                for repair in locked_repairs:
                    approval, created = RepairApproval.objects.get_or_create(
                        repair=repair,
                        defaults={
                            'approved': True,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': f'Batch approval for {break_count} breaks'
                        }
                    )

                    if not created:
                        approval.approved = True
                        approval.approved_by = customer_user
                        approval.approval_date = timezone.now()
                        approval.notes = f'Batch approval for {break_count} breaks'
                        approval.save()

                    repair.queue_status = 'APPROVED'
                    repair.save()

                    if repair.technician:
                        technician = repair.technician

                    approved_count += 1

            # Create single grouped notification outside the transaction (best effort)
            if technician:
                TechnicianNotification.objects.create(
                    technician=technician,
                    message=f"✅ Batch of {break_count} breaks APPROVED by {customer.name} - Unit {unit_number} (${total_cost:.2f} total)",
                    read=False,
                    repair=locked_repairs[0],
                    repair_batch_id=batch_id
                )

            messages.success(
                request,
                f"Successfully approved all {approved_count} breaks for Unit {unit_number} (${total_cost:.2f} total)."
            )
            return redirect('customer_dashboard')

        # GET request - show confirmation page
        return render(request, 'customer_portal/batch_approve_confirm.html', {
            'batch_summary': batch_summary,
            'customer': customer,
        })

    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_batch_deny(request, batch_id):
    """Deny all repairs in a batch (all-or-nothing transaction)"""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        # Scope to tenant to prevent cross-tenant IDOR via batch UUID.
        batch_summary = Repair.get_batch_summary(batch_id, tenant=customer.tenant)

        if not batch_summary or batch_summary['customer'] != customer:
            messages.error(request, "Batch not found or you don't have access to it.")
            return redirect('customer_dashboard')

        # Guard: only deny batches that are still in a pending state.
        # Without this, a direct POST on a COMPLETED batch would overwrite every
        # repair's queue_status back to DENIED. (CODE-061)
        deniable_statuses = {'PENDING', 'REQUESTED'}
        batch_statuses = set(batch_summary.get('statuses', []))
        if not batch_statuses.issubset(deniable_statuses):
            messages.warning(request, "This batch cannot be denied — not all repairs are pending approval.")
            return redirect('customer_dashboard')

        if request.method == 'POST':
            reason = request.POST.get('reason', '')
            # Use a transaction + row-level locks to prevent double-click race
            # conditions.  Mirrors the fix applied to customer_batch_approve in
            # CODE-254.
            technician = None
            denied_count = 0
            break_count = batch_summary['break_count']
            unit_number = batch_summary['unit_number']
            restored_rewards = []

            with transaction.atomic():
                # Re-fetch all batch repairs with row-level locks
                locked_repairs = list(
                    Repair.objects.select_for_update().filter(
                        repair_batch_id=batch_id,
                        tenant=customer.tenant,
                    ).select_related('technician')
                )

                if not locked_repairs:
                    messages.error(request, "Batch not found.")
                    return redirect('customer_dashboard')

                # Re-check ALL statuses inside the lock
                for repair in locked_repairs:
                    if repair.queue_status not in ('PENDING', 'REQUESTED'):
                        messages.warning(request, "This batch has already been processed.")
                        return redirect('customer_dashboard')

                # All repairs are still pending — deny them
                for repair in locked_repairs:
                    approval, created = RepairApproval.objects.get_or_create(
                        repair=repair,
                        defaults={
                            'approved': False,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': reason or f'Batch denial for {break_count} breaks'
                        }
                    )

                    if not created:
                        approval.approved = False
                        approval.approved_by = customer_user
                        approval.approval_date = timezone.now()
                        approval.notes = reason or f'Batch denial for {break_count} breaks'
                        approval.save()

                    repair.queue_status = 'DENIED'
                    repair.save()

                    # Auto-restore any applied reward (CODE-210)
                    restored_rewards.extend(_restore_reward_for_repair(repair))

                    if repair.technician:
                        technician = repair.technician

                    denied_count += 1

            # Show restored reward messages outside transaction
            for redemption in restored_rewards:
                messages.info(
                    request,
                    f'Your "{redemption.reward_option.name}" reward has been restored and can be used on your next repair.'
                )

            # Create single grouped notification outside the transaction (best effort)
            if technician:
                denial_message = f"❌ Batch of {break_count} breaks DENIED by {customer.name} - Unit {unit_number}"
                if reason:
                    denial_message += f" - Reason: {reason}"
                TechnicianNotification.objects.create(
                    technician=technician,
                    message=denial_message,
                    read=False,
                    repair=locked_repairs[0],
                    repair_batch_id=batch_id
                )

            messages.success(
                request,
                f"Denied all {denied_count} breaks for Unit {unit_number}."
            )
            return redirect('customer_dashboard')

        # GET request - show confirmation page
        return render(request, 'customer_portal/batch_deny_confirm.html', {
            'batch_summary': batch_summary,
            'customer': customer,
        })

    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


# =============================================================================
# REPLACEMENT VIEWS - Customer portal for glass replacements
# =============================================================================

@customer_required
def customer_replacements(request):
    """List all glass replacements for this customer."""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        # Get filter parameters
        status_filter = request.GET.get('status', '')

        # Get all replacements for this customer (tenant-scoped) — unfiltered base
        # queryset used for stats so filter badge counts are always global totals.
        base_replacements = Replacement.objects.filter(
            customer=customer, tenant=customer.tenant
        )

        # One aggregated query for all stat counts (avoids 4 separate COUNTs).
        # pending = PENDING; in_progress = APPROVED + IN_PROGRESS; completed = COMPLETED.
        from django.db.models import Case, When, IntegerField, Value
        status_counts = base_replacements.aggregate(
            total=Count('id'),
            pending=Count(Case(When(queue_status='PENDING', then=1), output_field=IntegerField())),
            in_progress=Count(Case(When(queue_status__in=['APPROVED', 'IN_PROGRESS'], then=1), output_field=IntegerField())),
            completed=Count(Case(When(queue_status='COMPLETED', then=1), output_field=IntegerField())),
        )
        stats = {
            'total': status_counts['total'],
            'pending': status_counts['pending'],
            'in_progress': status_counts['in_progress'],
            'completed': status_counts['completed'],
        }

        # Build the display queryset (may be further filtered by status_filter)
        replacements = base_replacements.select_related('technician__user').order_by('-service_date', '-id')

        # Apply status filter for the list only — does NOT affect stats above
        if status_filter:
            replacements = replacements.filter(queue_status=status_filter)

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
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_replacement_detail(request, replacement_id):
    """View details of a single replacement."""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        replacement = get_object_or_404(Replacement, id=replacement_id, customer=customer, tenant=customer.tenant)

        return render(request, 'customer_portal/replacement_detail.html', {
            'replacement': replacement,
            'customer': customer,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_replacement_approve(request, replacement_id):
    """Approve a pending replacement."""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        replacement = get_object_or_404(Replacement, id=replacement_id, customer=customer, tenant=customer.tenant)

        # Only allow approval of pending replacements
        if replacement.queue_status not in ['PENDING', 'REQUESTED']:
            messages.warning(request, "This replacement cannot be approved - it's not pending.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        if request.method == 'POST':
            notes = request.POST.get('notes', '')

            # Use a transaction + row-level lock to prevent double-click races
            # that could create duplicate notifications or corrupt status.
            # Mirrors the select_for_update() pattern added to repair approve/deny
            # in CODE-223.  (CODE-234)
            with transaction.atomic():
                locked_replacement = Replacement.objects.select_for_update().get(pk=replacement.pk)

                # Re-check status inside the lock so a concurrent approval/denial
                # that committed between the initial get_object_or_404 and here
                # doesn't get overwritten.
                if locked_replacement.queue_status not in ['PENDING', 'REQUESTED']:
                    messages.warning(request, "This replacement has already been processed.")
                    return redirect('customer_replacement_detail', replacement_id=replacement.id)

                # Update replacement status
                locked_replacement.queue_status = 'APPROVED'
                locked_replacement.save()

            # Create notification for technician (outside transaction — best effort)
            if locked_replacement.technician:
                TechnicianNotification.objects.create(
                    technician=locked_replacement.technician,
                    message=f"✅ Replacement #{locked_replacement.id} APPROVED by {customer.name} - {locked_replacement.get_glass_position_display()} on Unit {locked_replacement.unit_number}",
                    read=False,
                )

            messages.success(request, "Replacement has been approved. The technician can now proceed.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        return render(request, 'customer_portal/replacement_approve.html', {
            'replacement': replacement,
            'customer': customer,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_replacement_deny(request, replacement_id):
    """Deny a pending replacement."""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        replacement = get_object_or_404(Replacement, id=replacement_id, customer=customer, tenant=customer.tenant)

        # Only allow denial of pending replacements
        if replacement.queue_status not in ['PENDING', 'REQUESTED']:
            messages.warning(request, "This replacement cannot be denied - it's not pending.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        if request.method == 'POST':
            reason = request.POST.get('reason', '')

            # Use a transaction + row-level lock to prevent double-click races.
            # Mirrors the select_for_update() pattern added to repair deny in
            # CODE-223.  (CODE-234)
            with transaction.atomic():
                locked_replacement = Replacement.objects.select_for_update().get(pk=replacement.pk)

                # Re-check status inside the lock
                if locked_replacement.queue_status not in ['PENDING', 'REQUESTED']:
                    messages.warning(request, "This replacement has already been processed.")
                    return redirect('customer_replacement_detail', replacement_id=replacement.id)

                # Update replacement status
                locked_replacement.queue_status = 'DENIED'
                locked_replacement.save()

            # Create notification for technician (outside transaction — best effort)
            if locked_replacement.technician:
                denial_message = f"❌ Replacement #{locked_replacement.id} DENIED by {customer.name} - {locked_replacement.get_glass_position_display()} on Unit {locked_replacement.unit_number}"
                if reason:
                    denial_message += f". Reason: {reason}"
                TechnicianNotification.objects.create(
                    technician=locked_replacement.technician,
                    message=denial_message,
                    read=False,
                )

            messages.success(request, "Replacement has been denied.")
            return redirect('customer_replacement_detail', replacement_id=replacement.id)

        return render(request, 'customer_portal/replacement_deny.html', {
            'replacement': replacement,
            'customer': customer,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
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

@ratelimit(key='ip', rate='10/h', method='POST', block=False)
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

        # Use Django's full password validators (CommonPasswordValidator,
        # NumericPasswordValidator, MinimumLengthValidator, etc.) instead of
        # a bare length check so weak passwords like "password1" are rejected.
        # (CODE-188: customer_register used len(password) < 8; this matches the
        # validation used in shop_join_view and accept_invite.)
        try:
            temp_user = User(username=username, email=email, first_name=first_name, last_name=last_name)
            validate_password(password, user=temp_user)
        except DjangoValidationError as e:
            return render_with_form_data(' '.join(e.messages))

        if User.objects.filter(username=username).exists():
            return render_with_form_data("Username already exists")

        # Case-insensitive check to prevent duplicate accounts with the
        # same email in different cases (e.g. "Test@example.com" vs
        # "test@example.com").  Matches the iexact check used in
        # accept_customer_invitation().  (CODE-264)
        if User.objects.filter(email__iexact=email).exists():
            return render_with_form_data("Email already exists")

        # Normalize email to lowercase before creating the user so lookups
        # and uniqueness checks are consistent regardless of input case.
        # (CODE-264)
        email = email.lower()

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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        
        if request.method == 'POST':
            # Update customer information
            # NOTE: Do NOT lowercase the name — customer names must preserve case
            # (e.g. "EOS Trucking" must not become "eos trucking"). The .lower()
            # that was here previously was a copy-paste bug from username
            # normalization logic.  (CODE-078)
            new_name = request.POST.get('name', '').strip()
            if not new_name:
                messages.error(request, "Company name is required.")
                return render(request, 'customer_portal/edit_company.html', {'customer': customer})
            customer.name = new_name
            customer.email = request.POST.get('email', '')
            customer.phone = request.POST.get('phone', '')
            customer.address = request.POST.get('address', '')
            customer.city = request.POST.get('city', '')
            customer.state = request.POST.get('state', '')
            customer.zip_code = request.POST.get('zip_code', '')
            
            try:
                # Savepoint so a constraint violation doesn't poison the
                # surrounding transaction before we re-render with an error.
                with transaction.atomic():
                    customer.save()
                messages.success(request, "Company information updated successfully!")
                return redirect('customer_dashboard')
            except IntegrityError:
                messages.error(
                    request,
                    "Another customer already uses that name or email. "
                    "Please contact your shop if you believe this is an error."
                )
            except Exception as e:
                messages.error(request, f"Error updating company: {str(e)}")
        
        # Render the edit form
        return render(request, 'customer_portal/edit_company.html', {
            'customer': customer
        })
    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        if request.method == 'POST':
            # Check if this is a batch submission
            is_batch = request.POST.get('batch_submission') == 'true'

            if is_batch:
                return handle_batch_repair_request(request, customer, customer_user)
            else:
                # Legacy single repair submission (for backwards compatibility)
                return handle_single_repair_request(request, customer, customer_user)

        # Fetch available monetary rewards (APPROVED, not yet applied to a repair)
        available_rewards = _get_available_monetary_rewards(customer_user)

        # Render the repair request form
        return render(request, 'customer_portal/request_repair.html', {
            'available_rewards': available_rewards,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def request_replacement(request):
    """
    Handle customer glass replacement requests.

    Replacements are one-vehicle jobs, so this is a simple single-form flow
    (no multi-unit batching like repairs). The customer supplies the vehicle,
    which glass, and what happened; the shop confirms the exact glass and
    sets parts/labor pricing after reviewing the request.
    """
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

    tenant = getattr(request, 'tenant', None)
    ctx = {'glass_positions': Replacement.GLASS_POSITION_CHOICES}

    if request.method != 'POST':
        return render(request, 'customer_portal/request_replacement.html', ctx)

    # Plan limit check — customer-submitted replacements count toward the
    # tenant's monthly cap, same as the owner-side replacement_create flow.
    if tenant:
        from apps.tenants.services.usage_service import UsageService
        can_create, _limit_msg = UsageService(tenant).can_create_repair()
        if not can_create:
            messages.warning(request, "This shop has reached its service limit for the month. Please contact the shop for assistance.")
            return render(request, 'customer_portal/request_replacement.html', ctx)

    unit_number = request.POST.get('unit_number', '').strip()
    glass_position = request.POST.get('glass_position', 'WINDSHIELD')
    description = request.POST.get('description', '').strip()
    damage_photo = request.FILES.get('damage_photo')

    if not unit_number:
        messages.error(request, "Vehicle or unit number is required.")
        return render(request, 'customer_portal/request_replacement.html', ctx)

    if glass_position not in dict(Replacement.GLASS_POSITION_CHOICES):
        glass_position = 'WINDSHIELD'

    if damage_photo:
        photo_valid, photo_error = validate_repair_photo(damage_photo)
        if not photo_valid:
            messages.error(request, photo_error)
            return render(request, 'customer_portal/request_replacement.html', ctx)
        damage_photo = convert_heic_to_jpeg(damage_photo)

    technician = get_available_technician(tenant=tenant, service_type='replacement')
    if not technician:
        messages.error(request, "No technicians available. Please try again later.")
        return render(request, 'customer_portal/request_replacement.html', ctx)

    try:
        # No parts/labor cost yet — Replacement.save() leaves cost at 0 and
        # skips tax until the shop prices the job.
        replacement = Replacement.objects.create(
            tenant=tenant,
            technician=technician,
            customer=customer,
            unit_number=unit_number,
            glass_position=glass_position,
            description=description or 'Customer replacement request - glass and pricing to be confirmed by the shop',
            customer_notes=description,
            customer_submitted_photo=damage_photo,
            queue_status='REQUESTED',
        )

        # Auto-assign technician based on tenant strategy (may keep the
        # round-robin pick if the strategy is manual)
        from apps.tenants.services.assignment_service import auto_assign_replacement
        assigned_tech = auto_assign_replacement(replacement)
        if assigned_tech:
            messages.info(request, f'Your request has been assigned to {assigned_tech.user.get_full_name()}.')

        _notify_shop_replacement_requested(request, replacement)

        messages.success(request, "Replacement request submitted! The shop will confirm the glass and price before any work begins.")
        return redirect('customer_dashboard')
    except Exception as e:
        messages.error(request, f"Error creating replacement request: {str(e)}")
        return render(request, 'customer_portal/request_replacement.html', ctx)


def _notify_shop_replacement_requested(request, replacement):
    """
    Best-effort in-app + email notification to the shop about a new customer
    replacement request. Replacements have no lifecycle NotificationTemplates
    yet, so without this the request would sit invisible until someone
    happened to browse the replacement list. Never raises — the customer's
    request must succeed even if notification delivery fails.
    """
    customer = replacement.customer

    try:
        if replacement.technician:
            TechnicianNotification.objects.create(
                technician=replacement.technician,
                message=f"🔔 New replacement request from {customer.name} - {replacement.get_glass_position_display()} on Unit {replacement.unit_number}",
                read=False,
            )
    except Exception:
        logger.warning("Failed to create technician notification for replacement request", exc_info=True)

    try:
        tenant = replacement.tenant
        recipients = []
        owner_email = getattr(getattr(tenant, 'owner', None), 'email', '') if tenant else ''
        if owner_email:
            recipients.append(owner_email)
        tech_email = getattr(replacement.technician.user, 'email', '') if replacement.technician else ''
        if tech_email and tech_email not in recipients:
            recipients.append(tech_email)
        if not recipients:
            return

        from core.email_utils import send_branded_email
        detail_rows = [
            ('Customer', customer.name),
            ('Unit / Vehicle', replacement.unit_number),
            ('Glass', replacement.get_glass_position_display()),
        ]
        if replacement.customer_notes:
            detail_rows.append(('Notes', replacement.customer_notes))
        send_branded_email(
            subject=f"New replacement request — {customer.name}",
            recipient_list=recipients,
            headline="New Replacement Request",
            body_paragraphs=[
                f"{customer.name} requested a {replacement.get_glass_position_display()} replacement for Unit {replacement.unit_number}.",
                "Review the request to confirm the glass and set pricing.",
            ],
            detail_rows=detail_rows,
            button_text="Review Request",
            button_url=request.build_absolute_uri(reverse('replacement_detail', args=[replacement.pk])),
            tenant=tenant,
        )
    except Exception:
        logger.warning("Failed to send replacement request email to shop", exc_info=True)


def _get_available_monetary_rewards(customer_user):
    """
    Return APPROVED, unapplied monetary redemptions for this customer.
    Monetary = REPAIR_DISCOUNT, REPLACEMENT_DISCOUNT, FREE_SERVICE.
    """
    monetary_categories = ('REPAIR_DISCOUNT', 'REPLACEMENT_DISCOUNT', 'FREE_SERVICE')
    return RewardRedemption.objects.filter(
        reward__customer_user=customer_user,
        status='APPROVED',
        applied_to_repair__isnull=True,
        reward_option__reward_type__category__in=monetary_categories,
    ).select_related('reward_option', 'reward_option__reward_type')


def _restore_reward_for_repair(repair):
    """
    If a repair has an applied reward redemption, unapply it and restore to APPROVED.
    Returns the redemption if restored, None otherwise.
    """
    redemptions = RewardRedemption.objects.filter(applied_to_repair=repair)
    restored = []
    for redemption in redemptions:
        redemption.applied_to_repair = None
        redemption.status = 'APPROVED'
        redemption.fulfilled_at = None
        redemption.save()
        restored.append(redemption)
    return restored


def handle_single_repair_request(request, customer, customer_user=None):
    """Handle traditional single repair request submission"""
    # Plan limit check — customer-submitted repairs count toward the tenant's
    # monthly cap just like technician-created ones (CODE-243).
    tenant = getattr(request, 'tenant', None)
    if tenant:
        from apps.tenants.services.usage_service import UsageService
        can_create, limit_msg = UsageService(tenant).can_create_repair()
        if not can_create:
            messages.warning(request, "This shop has reached its repair limit for the month. Please contact the shop for assistance.")
            return render(request, 'customer_portal/request_repair.html', {
                'available_rewards': _get_available_monetary_rewards(customer_user) if customer_user else [],
            })

    unit_number = request.POST.get('unit_number', '')
    description = request.POST.get('description', '')
    damage_type = request.POST.get('damage_type', '')
    damage_photo = request.FILES.get('damage_photo_before')

    # Pre-compute available rewards so ALL error-path renders include them.
    # CODE-211: Previously the error paths called render() with no context, so the
    # reward selection UI disappeared on validation failure — customers who had
    # selected a reward lost it from the form and were confused about what happened.
    _rewards_ctx = {
        'available_rewards': _get_available_monetary_rewards(customer_user) if customer_user else [],
    }

    if not unit_number:
        messages.error(request, "Unit number is required.")
        return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

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
            return render(request, 'customer_portal/request_repair.html', _rewards_ctx)
        damage_photo = convert_heic_to_jpeg(damage_photo)

    # Find available technician (scoped to tenant)
    tenant = getattr(request, 'tenant', None)
    technician = get_available_technician(tenant=tenant)
    if not technician:
        messages.error(request, "No technicians available. Please try again later.")
        return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

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

        # Apply selected monetary reward if provided
        apply_reward_id = request.POST.get('apply_reward')
        if apply_reward_id and customer_user:
            try:
                redemption = RewardRedemption.objects.get(
                    id=apply_reward_id,
                    reward__customer_user=customer_user,
                    status='APPROVED',
                    applied_to_repair__isnull=True,
                )
                redemption.applied_to_repair = repair
                redemption.save()
                messages.info(request, f'Reward "{redemption.reward_option.name}" applied to this repair.')
            except RewardRedemption.DoesNotExist:
                pass  # Silently skip if reward no longer available

        # Auto-assign technician based on tenant strategy
        from apps.tenants.services.assignment_service import auto_assign_repair
        assigned_tech = auto_assign_repair(repair)
        if assigned_tech:
            messages.info(request, f'Your repair has been assigned to {assigned_tech.user.get_full_name()}.')

        messages.success(request, "Repair request submitted successfully! A technician will review your request.")
        return redirect('customer_dashboard')
    except Exception as e:
        messages.error(request, f"Error creating repair request: {str(e)}")
        return render(request, 'customer_portal/request_repair.html', _rewards_ctx)


def handle_batch_repair_request(request, customer, customer_user=None):
    """Handle multi-unit batch repair request submission"""
    import json
    import uuid

    # Pre-compute available rewards so ALL error-path renders include them.
    # CODE-216: Without this, the reward section disappeared when batch submission
    # hit any validation error — mirrors the same fix applied to handle_single_repair_request
    # in CODE-211.
    _rewards_ctx = {
        'available_rewards': _get_available_monetary_rewards(customer_user) if customer_user else [],
    }

    # Plan limit check — customer-submitted batch repairs count toward the
    # tenant's monthly cap just like technician-created ones (CODE-243).
    tenant = getattr(request, 'tenant', None)
    if tenant:
        from apps.tenants.services.usage_service import UsageService
        can_create, limit_msg = UsageService(tenant).can_create_repair()
        if not can_create:
            messages.warning(request, "This shop has reached its repair limit for the month. Please contact the shop for assistance.")
            return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

    try:
        # Parse units data from JSON
        units_data_json = request.POST.get('units_data')
        if not units_data_json:
            messages.error(request, "No repair data provided.")
            return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

        units_data = json.loads(units_data_json)

        if not units_data or len(units_data) == 0:
            messages.error(request, "Please add at least one unit to submit.")
            return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

        # Guard against abuse: cap the number of units and breaks per request.
        # A windshield rarely has more than ~10 breaks; 20 is generous.  Without
        # this cap, a malicious POST with breakCount=10000 across 500 units
        # would create 5 million Repair rows in a single atomic transaction,
        # exhausting DB connections and disk.  (CODE-240)
        MAX_UNITS_PER_REQUEST = 50
        MAX_BREAKS_PER_UNIT = 20

        if len(units_data) > MAX_UNITS_PER_REQUEST:
            error_msg = f"Too many units submitted ({len(units_data)}). Maximum is {MAX_UNITS_PER_REQUEST} per request."
            messages.error(request, error_msg)
            if 'multipart/form-data' in request.content_type or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

        # Find available technician (scoped to tenant)
        tenant = getattr(request, 'tenant', None)
        technician = get_available_technician(tenant=tenant)
        if not technician:
            messages.error(request, "No technicians available. Please try again later.")
            return render(request, 'customer_portal/request_repair.html', _rewards_ctx)

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

                # Get damage location (optional)
                damage_loc_x = unit_data.get('damageLocationX')
                damage_loc_y = unit_data.get('damageLocationY')
                damage_location_x = float(damage_loc_x) if damage_loc_x else None
                damage_location_y = float(damage_loc_y) if damage_loc_y else None

                if not unit_number:
                    continue  # Skip invalid entries

                # Clamp break_count to prevent abuse (CODE-240)
                if break_count is not None:
                    try:
                        break_count = int(break_count)
                    except (ValueError, TypeError):
                        break_count = None
                    else:
                        if break_count > MAX_BREAKS_PER_UNIT:
                            break_count = MAX_BREAKS_PER_UNIT
                        elif break_count < 1:
                            break_count = None

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
                            total_breaks_in_batch=break_count,
                            damage_location_x=damage_location_x if break_num == 1 else None,
                            damage_location_y=damage_location_y if break_num == 1 else None,
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
                        is_multi_break_estimate=True,
                        damage_location_x=damage_location_x,
                        damage_location_y=damage_location_y,
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
                        queue_status='REQUESTED',
                        damage_location_x=damage_location_x,
                        damage_location_y=damage_location_y,
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
        return render(request, 'customer_portal/request_repair.html', _rewards_ctx)
    except Exception as e:
        logging.error(f"Error creating batch repair request: {str(e)}")
        messages.error(request, f"Error creating repair requests: {str(e)}")
        # Return JSON error for AJAX requests
        if 'multipart/form-data' in request.content_type or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f"Error creating repair requests: {str(e)}"
            }, status=500)
        return render(request, 'customer_portal/request_repair.html', _rewards_ctx)


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


def get_available_technician(tenant=None, service_type='repair'):
    """
    Get an available technician using round-robin assignment.
    Scoped to tenant if provided.

    Only returns technicians that are active and able to perform the
    requested service type. Without these filters, deactivated technicians
    or managers with can_repair=False could be assigned to customer-requested
    repairs — invisible to the correct technicians and alarming to the ones
    who no longer work at the shop. (CODE-160)

    For replacements, technicians with can_replace=True are preferred, but
    any active technician is an acceptable fallback: new shops only have the
    auto-created owner technician, whose can_replace defaults to False, and
    a customer replacement request must never dead-end unassignable.

    Returns:
        Technician object or None if no technicians available
    """
    technicians = Technician.objects.all()
    if tenant:
        technicians = technicians.filter(tenant=tenant)
    else:
        technicians = technicians.none()
    technicians = technicians.filter(is_active=True)

    if service_type == 'replacement':
        preferred = technicians.filter(can_replace=True)
        pool = preferred if preferred.exists() else technicians
        pool = pool.annotate(
            active_jobs=Count('replacement', filter=Q(replacement__queue_status__in=['REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS']))
        ).order_by('active_jobs', 'id')
        return pool.first()

    technicians = technicians.filter(can_repair=True)
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
        customer_user = _get_customer_user_for_tenant(request)
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

    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
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
            
            # --- PASSWORD VALIDATION FIRST ---
            # Must validate the password change BEFORE mutating and saving any
            # contact-verification state (prefs.email_verified, prefs.phone_verified).
            # Previously, prefs.save() was called eagerly inside the email/phone
            # change blocks, then the password check returned early — leaving
            # CustomerNotificationPreference.phone_verified=False while
            # Customer.phone_verified stayed True (desync). (CODE-154)
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

                # Use Django's full password validation (length, common passwords,
                # entirely numeric, etc.) instead of a bare length check.
                # Same pattern as customer_register() and accept_customer_invitation()
                # fixed in CODE-188. A bare `len() < 8` check accepted passwords
                # like "password1" or "12345678".  (CODE-190)
                from django.core.exceptions import ValidationError as DjangoValidationError
                try:
                    validate_password(new_password, user=user)
                except DjangoValidationError as e:
                    for msg in e.messages:
                        messages.error(request, msg)
                    repair_form = RepairPreferenceForm(instance=repair_prefs)
                    return render(request, 'customer_portal/account_settings.html', {
                        'customer_user': customer_user,
                        'repair_form': repair_form,
                    })

                user.set_password(new_password)
                update_session_auth_hash(request, user)  # Keep user logged in

            # --- VALIDATE AND STAGE all contact/user changes ---
            # Collect any notification-preference mutations into a pending dict so
            # we can save them together with customer/user at the very end.
            # This prevents partial state if a later step raises an exception.
            prefs_updates = {}  # field → value

            if email and email.lower() != user.email.lower():
                # Case-insensitive check to prevent duplicate accounts with the
                # same email in different cases.  Matches the iexact check used in
                # accept_customer_invitation().  (CODE-264)
                if User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                    messages.error(request, "This email is already in use by another account.")
                    repair_form = RepairPreferenceForm(instance=repair_prefs)
                    return render(request, 'customer_portal/account_settings.html', {
                        'customer_user': customer_user,
                        'repair_form': repair_form,
                    })
                # Normalize email to lowercase before saving so lookups
                # and uniqueness checks are consistent regardless of input case.
                # (CODE-265: account_settings was missed by CODE-264 which only
                # normalized in customer_register and accept_customer_invitation.)
                user.email = email.lower()
                # Reset email verification when email changes
                if customer.email_verified:
                    messages.info(request, "Email address changed. Please verify your new email address.")
                customer.email_verified = False
                customer.email_verified_at = None
                prefs_updates['email_verified'] = False
                prefs_updates['email_verified_at'] = None
            
            user.first_name = first_name
            user.last_name = last_name

            # Handle phone number update
            if phone != customer.phone:
                if customer.phone_verified:
                    messages.info(request, "Phone number changed. Please verify your new phone number.")
                customer.phone = phone
                customer.phone_verified = False
                customer.phone_verified_at = None
                prefs_updates['phone_verified'] = False
                prefs_updates['phone_verified_at'] = None
            
            # Update primary contact status.
            # If this user is claiming primary contact, first demote any existing
            # primary for this customer — mirrors the pattern used in the owner
            # portal's set_primary_contact() and accept_customer_invitation().
            # Without this demotion, multiple CustomerUsers can have
            # is_primary_contact=True simultaneously, causing ambiguous notification
            # routing (repairs.py filters to primary for approval records).
            # (CODE-116)
            if is_primary_contact and not customer_user.is_primary_contact:
                CustomerUser.objects.filter(
                    customer=customer, is_primary_contact=True
                ).exclude(pk=customer_user.pk).update(is_primary_contact=False)
            customer_user.is_primary_contact = is_primary_contact

            try:
                user.save()
                customer_user.save()
                customer.save()  # Save phone/email verification status changes
                # Apply notification-preference verification resets (collected above)
                # in one update so they are always in sync with the Customer row.
                if prefs_updates:
                    prefs_obj, _ = CustomerNotificationPreference.objects.get_or_create(
                        customer=customer
                    )
                    for field, value in prefs_updates.items():
                        setattr(prefs_obj, field, value)
                    prefs_obj.save(update_fields=list(prefs_updates.keys()))
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
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def unit_repair_data_api(request):
    """API endpoint to provide unit repair data for visualizations"""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        
        # Get all unit repair counts for this customer, scoped to the tenant.
        # Always include tenant in the filter to prevent cross-tenant data leakage
        # in edge cases where a user has CustomerUser records at multiple shops.
        tenant = customer.tenant
        unit_repairs = UnitRepairCount.objects.filter(customer=customer, tenant=tenant)

        # If no unit repair counts exist, create them from repairs data
        if not unit_repairs.exists():
            # Get counts directly from Repair model (tenant-scoped)
            repair_counts = Repair.objects.filter(
                customer=customer,
                tenant=tenant,
                queue_status='COMPLETED'  # Only count completed repairs
            ).values('unit_number').annotate(
                count=Count('id')
            ).order_by('-count')

            # Create UnitRepairCount records if needed.
            # Include tenant in the lookup keys (not just defaults) so the lookup
            # itself is tenant-scoped.  Omitting it would create NULL-tenant rows
            # or silently match a NULL-tenant row left by an older codepath, so the
            # correct tenant would never be set.  (Same pattern as customers.py mark_unit_replaced.)
            for repair in repair_counts:
                UnitRepairCount.objects.update_or_create(
                    tenant=tenant,
                    customer=customer,
                    unit_number=repair['unit_number'],
                    defaults={'repair_count': repair['count']}
                )

            # Refresh the queryset (tenant-scoped)
            unit_repairs = UnitRepairCount.objects.filter(customer=customer, tenant=tenant)
        
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
    except (CustomerUser.DoesNotExist, AttributeError):
        return JsonResponse({'error': 'Customer profile not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in unit_repair_data_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@customer_required
def repair_cost_data_api(request):
    """API endpoint to provide repair frequency data for visualizations"""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        
        # Get only COMPLETED repairs for this customer (tenant-scoped).
        # Previously this fetched ALL repairs regardless of queue_status, so
        # PENDING, DENIED, IN_PROGRESS, etc. were counted as "repairs done" in
        # the monthly frequency chart — inflating the numbers and making them
        # inconsistent with the unit_repair_data_api endpoint which correctly
        # filters on queue_status='COMPLETED'.  (CODE-215)
        repairs = Repair.objects.filter(
            customer=customer,
            tenant=customer.tenant,
            queue_status='COMPLETED',
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
    except (CustomerUser.DoesNotExist, AttributeError):
        return JsonResponse({'error': 'Customer profile not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in repair_cost_data_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@customer_required
def customer_rewards_redirect(request):
    """Customer rewards and referrals dashboard"""
    try:
        # Use tenant-scoped helper to prevent cross-tenant data leakage.
        # The old code used an unscoped CustomerUser.objects.get(user=request.user),
        # which bypassed tenant isolation: a user linked to Shop A visiting Shop B's
        # portal URL would have @customer_required deny them access, but if that
        # guard ever changes or has an edge case, the unscoped lookup could return
        # Shop A's CustomerUser and render Shop B's rewards page with Shop A data.
        # Using _get_customer_user_for_tenant() is the consistent, safe pattern
        # used throughout this file. (CODE-162)
        customer_user = _get_customer_user_for_tenant(request)
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
        
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_points_history(request):
    """Points transaction history for the current customer."""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        from apps.rewards_referrals.models import LoyaltyConfig
        tenant = customer_user.customer.tenant
        config = LoyaltyConfig.get_for_tenant(tenant)

        transactions = LoyaltyService.get_transaction_history(customer_user, limit=50)
        context = {
            'transactions': transactions,
            'points': LoyaltyService.get_balance(customer_user),
            'lifetime_earned': LoyaltyService.get_lifetime_earned(customer_user),
            'program_name': config.program_name,
        }
        return render(request, 'customer_portal/referrals/points_history.html', context)
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

@customer_required
def customer_bulk_action(request):
    """Handle bulk approve or deny actions for multiple repairs"""
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('customer_repairs')

    try:
        customer_user = _get_customer_user_for_tenant(request)
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

        # Validate and process repairs with transaction safety.
        # Use select_for_update() to prevent a double-click / concurrent request
        # race that could create duplicate TechnicianNotification records or
        # corrupt repair status.  The single-repair views were fixed in CODE-223
        # and replacements in CODE-234, but the bulk action was missed.  (CODE-236)
        notifications_to_create = []  # collect notifications outside the lock

        with transaction.atomic():
            # Get all repairs and ensure they belong to this customer (tenant-scoped).
            # Include REQUESTED repairs — customer-initiated repairs start as REQUESTED
            # and should be approvable via bulk action.  Consistent with single-repair
            # customer_repair_approve() which also accepts {'PENDING', 'REQUESTED'}.
            # (CODE-065: previously only 'PENDING', so REQUESTED repairs were silently
            # dropped from bulk actions without any warning to the user.)
            repairs = list(
                Repair.objects.select_for_update().filter(
                    id__in=repair_ids,
                    customer=customer,
                    tenant=customer.tenant,
                    queue_status__in=['PENDING', 'REQUESTED']
                ).select_related('technician')
            )

            if not repairs:
                messages.error(request, "No valid repairs found to process.")
                return redirect('customer_repairs')

            processed_count = 0

            for repair in repairs:
                # Re-check status inside the lock — a concurrent request may have
                # already transitioned this repair.
                if repair.queue_status not in ('PENDING', 'REQUESTED'):
                    continue

                if action == 'approve':
                    # Create or update approval
                    approval, created = RepairApproval.objects.get_or_create(
                        repair=repair,
                        defaults={
                            'approved': True,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': 'Bulk approved via multi-select'
                        }
                    )

                    if not created:
                        approval.approved = True
                        approval.approved_by = customer_user
                        approval.approval_date = timezone.now()
                        approval.notes = 'Bulk approved via multi-select'
                        approval.save()

                    # Update repair status
                    repair.queue_status = 'APPROVED'
                    repair.save()

                    # Queue notification for technician (created outside the lock)
                    if repair.technician:
                        notifications_to_create.append(
                            TechnicianNotification(
                                technician=repair.technician,
                                message=f"✅ Repair #{repair.id} APPROVED by {customer.name} - Unit {repair.unit_number}. You can now complete the work.",
                                read=False,
                                repair=repair,
                            )
                        )

                else:  # deny
                    # Create or update approval record to mark as denied
                    approval, created = RepairApproval.objects.get_or_create(
                        repair=repair,
                        defaults={
                            'approved': False,
                            'approved_by': customer_user,
                            'approval_date': timezone.now(),
                            'notes': 'Bulk denied via multi-select'
                        }
                    )

                    if not created:
                        approval.approved = False
                        approval.approved_by = customer_user
                        approval.approval_date = timezone.now()
                        approval.notes = 'Bulk denied via multi-select'
                        approval.save()

                    # Update repair status
                    repair.queue_status = 'DENIED'
                    repair.save()

                    # Queue notification for technician (created outside the lock)
                    if repair.technician:
                        notifications_to_create.append(
                            TechnicianNotification(
                                technician=repair.technician,
                                message=f"❌ Repair #{repair.id} DENIED by {customer.name} - Unit {repair.unit_number}.",
                                read=False,
                                repair=repair,
                            )
                        )

                processed_count += 1

        # Create technician notifications outside the transaction to avoid
        # holding the row lock longer than necessary (best effort, same
        # pattern as CODE-223 / CODE-234).
        for notif in notifications_to_create:
            try:
                notif.save()
            except Exception:
                logger.warning(
                    "Failed to create technician notification for repair %s",
                    notif.repair_id, exc_info=True,
                )

        # Success message — must be OUTSIDE the notification loop.
        # Previously this was indented inside the for-loop, causing:
        #   (a) one success toast per notification (duplicate messages), or
        #   (b) no toast at all when notifications_to_create was empty
        #       (e.g. repairs with no assigned technician).  (CODE-241)
        action_word = "approved" if action == 'approve' else "denied"
        messages.success(
            request,
            f"Successfully {action_word} {processed_count} repair{'' if processed_count == 1 else 's'}."
        )

        return redirect('customer_repairs')

    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
    except (CustomerUser.DoesNotExist, AttributeError):
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
        from core.email_utils import send_branded_email
        send_branded_email(
            subject='Verify your email address — RS Systems',
            recipient_list=[request.user.email],
            headline='Verify Your Email',
            body_paragraphs=[
                f'Hi {request.user.first_name or request.user.email},',
                'Please verify your email address by clicking the button below so you can receive invoices and notifications.',
                'This link will expire in 24 hours.',
            ],
            button_text='✅ Verify Email',
            button_url=verification_url,
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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
    except (CustomerUser.DoesNotExist, AttributeError):
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
        except (CustomerUser.DoesNotExist, AttributeError):
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
                customer_user = _get_customer_user_for_tenant(request)
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
            except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
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
        customer_user = _get_customer_user_for_tenant(request)
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
        customer_user = _get_customer_user_for_tenant(request)
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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        # CODE-255: Add tenant filter for defense-in-depth tenant isolation.
        # Customer FK is already tenant-scoped, but every query must include
        # an explicit tenant= filter per project conventions (AGENTS.md).
        invoices = list(
            Invoice.objects.filter(
                customer=customer,
                tenant=customer.tenant,
            ).exclude(status='DRAFT').order_by('-invoice_date', '-created_at')
        )

        # Pre-compute summary counts for the template — Django templates cannot
        # increment counters (|add in a loop just renders "1" each iteration).
        paid_count = sum(1 for inv in invoices if inv.status == 'PAID')
        outstanding_count = sum(
            1 for inv in invoices if inv.status in ('SENT', 'PARTIAL', 'OVERDUE')
        )
        overdue_count = sum(1 for inv in invoices if inv.status == 'OVERDUE')

        return render(request, 'customer_portal/invoices.html', {
            'invoices': invoices,
            'customer': customer,
            'paid_count': paid_count,
            'outstanding_count': outstanding_count,
            'overdue_count': overdue_count,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_invoice_detail(request, invoice_id):
    """Full receipt view for a single invoice."""
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        # CODE-255: Include tenant filter for defense-in-depth tenant isolation.
        invoice = get_object_or_404(Invoice, id=invoice_id, customer=customer, tenant=customer.tenant)

        # Don't let customers see draft invoices
        if invoice.status == 'DRAFT':
            messages.warning(request, "This invoice is not available.")
            return redirect('customer_invoices')

        line_items = invoice.line_items.all().order_by('id')
        payments = invoice.payments.all().order_by('-payment_date')

        # PDF download URL — always the ownership-checked Django view, never
        # a raw S3 object URL. Invoice keys are predictable and the bucket is
        # private on invoices/*; the view mints a short-TTL presigned URL
        # only after confirming this customer owns the invoice. (B1)
        pdf_url = reverse('customer_invoice_pdf', args=[invoice.id])

        # Determine if online payment is available (tenant has active Connect)
        can_pay_online = (
            invoice.tenant
            and invoice.tenant.can_accept_payments
        )

        return render(request, 'customer_portal/invoice_detail.html', {
            'invoice': invoice,
            'line_items': line_items,
            'payments': payments,
            'pdf_url': pdf_url,
            'customer': customer,
            'can_pay_online': can_pay_online,
        })
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')


@customer_required
def customer_invoice_pdf(request, invoice_id):
    """
    GET /app/invoices/<id>/pdf/ — serve the invoice PDF, ownership-checked.

    The ONLY sanctioned way to hand a customer their invoice PDF (B1):
    the customer/tenant scoping here is what keeps other companies'
    invoices unreachable. Never expose raw S3 object URLs — the keys are
    predictable and the bucket is private on invoices/*.
    """
    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
    except (CustomerUser.DoesNotExist, AttributeError):
        messages.warning(request, "Please complete your profile first.")
        return redirect('profile_creation')

    invoice = get_object_or_404(
        Invoice, id=invoice_id, customer=customer, tenant=customer.tenant
    )
    if invoice.status == 'DRAFT':
        messages.warning(request, "This invoice is not available.")
        return redirect('customer_invoices')

    if invoice.s3_key:
        try:
            from apps.billing.services.invoice_storage_service import InvoiceStorageService
            presigned = InvoiceStorageService().get_invoice_url(invoice.s3_key, expires_in=300)
            if presigned:
                return redirect(presigned)
        except Exception as e:
            logger.warning(f"Presigned URL failed for invoice {invoice.invoice_number}: {e}")
        # fall through to on-demand render

    try:
        from apps.billing.services.invoice_service import InvoiceService
        service = InvoiceService(tenant=customer.tenant)
        pdf_bytes, _ = service.generate_invoice_from_record(invoice)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response
    except Exception as e:
        logger.error(f"PDF generation failed for invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'Could not generate the invoice PDF.')
        return redirect('customer_invoice_detail', invoice_id=invoice.id)


@customer_required
def customer_invoice_pay(request, invoice_id):
    """Create a Stripe checkout session and redirect to payment."""
    if request.method != 'POST':
        return redirect('customer_invoice_detail', invoice_id=invoice_id)

    try:
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer

        # CODE-255: Include tenant filter for defense-in-depth tenant isolation.
        invoice = get_object_or_404(Invoice, id=invoice_id, customer=customer, tenant=customer.tenant)

        # Validate the invoice can be paid
        if invoice.status in ('CANCELLED', 'PAID', 'DRAFT'):
            messages.warning(request, "This invoice cannot be paid.")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        if invoice.amount_due <= 0:
            messages.info(request, "This invoice is already fully paid.")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        # HARD GATE: No online payments unless shop has active Stripe Connect.
        # This is the critical safety check — no Connect = no online payment.
        tenant = getattr(invoice, 'tenant', None)
        if not tenant or not tenant.can_accept_payments:
            messages.error(
                request,
                "Online payments are not available for this shop. "
                "Please contact them directly for payment options."
            )
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        # If there's already a Stripe hosted URL, redirect there
        if invoice.stripe_hosted_url:
            return redirect(invoice.stripe_hosted_url)

        # Create a direct charge checkout session on the shop's connected account
        from apps.tenants.services.connect_service import ConnectService, ConnectError

        connect_svc = ConnectService()

        if not connect_svc.is_enabled():
            messages.error(request, "Online payments are not currently available. Please contact the shop for payment options.")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
        success_url = f"{base_url}/app/invoices/{invoice.id}/?payment=success"
        cancel_url = f"{base_url}/app/invoices/{invoice.id}/?payment=cancelled"

        try:
            result = connect_svc.create_connected_checkout_session(
                invoice,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except ConnectError as e:
            logger.error(
                f"Connected checkout hard-blocked for {invoice.invoice_number}: {e}"
            )
            messages.error(
                request,
                "This shop has not completed payment setup. "
                "Please contact them directly for payment options."
            )
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

        if result.get('success'):
            return redirect(result['checkout_url'])
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Stripe checkout failed for invoice {invoice.invoice_number}: {error_msg}")
            messages.error(request, f"Could not initiate payment: {error_msg}")
            return redirect('customer_invoice_detail', invoice_id=invoice.id)

    except (CustomerUser.DoesNotExist, AttributeError):
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
        
        # Check if they already have a CustomerUser record.
        # CustomerUser.user is a OneToOneField — one CustomerUser per User globally.
        # We must check what shop they're already linked to:
        #   - Same customer → they're already set up here, redirect.
        #   - Different customer, same tenant → portal access at this shop (different account).
        #   - Different tenant → current schema doesn't support multi-shop customers;
        #     show a clear, actionable message instead of "Contact support".
        # (CODE-106: replaced unscoped .first() with explicit checks to surface the right
        # message in each case, and avoid the misleading "Contact support" dead-end.)
        existing = CustomerUser.objects.filter(user=request.user).first()
        invite_tenant = invitation.customer.tenant

        if existing:
            if existing.customer == invitation.customer:
                # Already linked to exactly this customer — nothing to do.
                messages.info(request, f"You're already set up for {invitation.customer.name}.")
                return redirect('customer_dashboard')

            if existing.customer.tenant == invite_tenant:
                # Linked to a *different* customer at the same shop — redirect with context.
                messages.info(
                    request,
                    f"You already have portal access to {invite_tenant.name} "
                    f"under {existing.customer.name}. Contact your shop admin to update your account."
                )
                return redirect('customer_dashboard')

            # Linked to a customer at a different shop.  The CustomerUser model uses a
            # OneToOneField to User, so a second CustomerUser row isn't possible.
            # Give a clear explanation instead of the unhelpful "Contact support" dead-end.
            messages.warning(
                request,
                f"Your account is currently linked to {existing.customer.name} "
                f"({existing.customer.tenant.name if existing.customer.tenant else 'another shop'}). "
                f"Customer portal accounts can only be linked to one shop. "
                f"If you need access to {invitation.customer.name}, please contact "
                f"{invite_tenant.name} and ask them to set up a new account for you."
            )
            return redirect('customer_dashboard')

        # No existing CustomerUser — safe to create one.
        # Link existing user to this invitation's customer.
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
        # Create a TenantMembership so the middleware can resolve this tenant
        # via session-based lookup (_get_tenant_by_id).  Without this, every
        # request falls back to _get_customer_tenant().first() — non-deterministic
        # for multi-shop customers and an extra DB round-trip per request.
        # Matches the pattern used in shop_join_view() (CODE-104).
        from apps.tenants.models import TenantMembership as _TM
        tenant_for_invite = invitation.customer.tenant
        if tenant_for_invite:
            _TM.objects.get_or_create(
                tenant=tenant_for_invite,
                user=request.user,
                defaults={'role': 'viewer', 'is_active': True},
            )
            request.session['tenant_id'] = tenant_for_invite.id
        invitation.mark_accepted(request.user)
        messages.success(request, f"Welcome! You now have access to {invitation.customer.name}.")
        return redirect('customer_dashboard')
    
    # Handle form submission for new user creation
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        # Normalize email to lowercase so lookups and uniqueness checks
        # are consistent regardless of input case.  (CODE-265: this path was
        # missed by CODE-264 which only normalized in customer_register.)
        email = request.POST.get('email', invitation.email).strip().lower()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        
        errors = []
        
        # Validate
        if not first_name:
            errors.append("First name is required.")
        if not password:
            errors.append("Password is required.")
        if password != password_confirm:
            errors.append("Passwords do not match.")
        # Use Django's full password validators instead of bare length check.
        # (CODE-188: accept_customer_invitation used len(password) < 8; this
        # matches the validation used in shop_join_view and accept_invite so
        # common/numeric passwords like "password1" are properly rejected.)
        if password and not errors:
            try:
                temp_user = User(
                    username='temp', email=email,
                    first_name=first_name, last_name=last_name,
                )
                validate_password(password, user=temp_user)
            except DjangoValidationError as e:
                errors.extend(e.messages)
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

                # Create a TenantMembership so the middleware can resolve this
                # tenant via session-based lookup (_get_tenant_by_id).
                # Without this, every request falls back to _get_customer_tenant()
                # which uses .first() — non-deterministic for multi-shop users
                # and an extra DB round-trip per request.
                # Matches the pattern used in shop_join_view() (CODE-104).
                from apps.tenants.models import TenantMembership as _TM
                tenant_for_invite = invitation.customer.tenant
                if tenant_for_invite:
                    _TM.objects.get_or_create(
                        tenant=tenant_for_invite,
                        user=user,
                        defaults={'role': 'viewer', 'is_active': True},
                    )
                    request.session['tenant_id'] = tenant_for_invite.id

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
        customer_user = _get_customer_user_for_tenant(request)
        customer = customer_user.customer
        
        # Get all team members (CustomerUser records for this customer)
        team_members = CustomerUser.objects.filter(customer=customer).select_related('user')
        
        # Get pending invitations
        pending_invitations = CustomerInvitation.objects.filter(
            customer=customer,
            status='pending'
        ).order_by('-created_at')
        
        # Bulk-expire stale invitations in a single UPDATE — avoids per-row
        # double-write caused by the old loop pattern where CustomerInvitation.is_valid
        # already saves when it detects expiry, and then the loop body saved a second
        # time.  (CODE-146)
        CustomerInvitation.objects.filter(
            customer=customer,
            status='pending',
            expires_at__lt=timezone.now(),
        ).update(status='expired')

        # Refresh to get non-expired pending invitations only
        pending_invitations = CustomerInvitation.objects.filter(
            customer=customer,
            status='pending'
        ).order_by('-created_at')
        
        return render(request, 'customer_portal/team.html', {
            'team_members': team_members,
            'pending_invitations': pending_invitations,
            'current_user': customer_user,
        })
        
    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
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
        
    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
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
        
    except (CustomerUser.DoesNotExist, AttributeError):
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
        customer_user = _get_customer_user_for_tenant(request)
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
        
    except (CustomerUser.DoesNotExist, AttributeError):
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
