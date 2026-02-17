"""
SaaS UI Views

Template-based views for signup, onboarding, owner dashboard,
pricing, billing settings, replacement form, shop join (customer
self-signup), and team management endpoints.

Author: Amelia (Clawdbot AI)
"""

import logging
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from common.decorators import owner_or_manager_required
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.tenants.models import InviteToken, SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.usage_service import UsageService
from apps.tenants.services.subscription_service import SubscriptionService, SubscriptionError
from apps.tenants.services.signup_service import create_tenant_with_owner, SignupError
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.customer_portal.models import CustomerUser
from core.models import Customer

from .forms import (
    SignupForm,
    OnboardingBusinessForm,
    OnboardingTechnicianForm,
    OnboardingCustomerForm,
    ReplacementForm,
)

from apps.billing.models import Invoice, Payment, TaxRate, BillingConfig

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_owner_tenant(request):
    """Return (tenant, membership) for owner/manager users, or (None, None).
    
    Only returns a membership if the user has owner or manager role.
    Viewers, technicians, and customers get (None, None) — they shouldn't
    access the owner dashboard.
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        membership = (
            TenantMembership.objects
            .filter(user=request.user, is_active=True, role__in=['owner', 'manager'])
            .select_related('tenant')
            .order_by('role')
            .first()
        )
        if membership:
            return membership.tenant, membership
        return None, None
    membership = TenantMembership.objects.filter(
        user=request.user, tenant=tenant, is_active=True,
        role__in=['owner', 'manager']
    ).first()
    if not membership:
        return None, None
    return tenant, membership


# ------------------------------------------------------------------
# 1. Signup
# ------------------------------------------------------------------

def signup_view(request):
    """Public signup page — creates user, tenant, membership, logs in."""
    if request.user.is_authenticated:
        return redirect('owner_dashboard')

    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            try:
                cd = form.cleaned_data

                # Use shared signup service (same logic as API endpoint)
                result = create_tenant_with_owner(
                    business_name=cd['business_name'],
                    email=cd['email'],
                    password=cd['password'],
                    first_name=cd['first_name'],
                    last_name=cd['last_name'],
                )
                user = result['user']
                tenant = result['tenant']

                # Log the user in
                auth_user = authenticate(
                    request, username=user.username, password=cd['password']
                )
                if auth_user:
                    login(request, auth_user)
                    request.session['tenant_id'] = tenant.id

                messages.success(
                    request,
                    f'Welcome to RS Systems, {cd["first_name"]}! '
                    f'Your 30-day free trial has started.',
                )
                return redirect('onboarding')

            except SignupError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Signup error: {e}")
                messages.error(
                    request,
                    'An unexpected error occurred. Please try again.',
                )
    else:
        form = SignupForm()

    return render(request, 'saas/signup.html', {'form': form})


# ------------------------------------------------------------------
# 2. Legal Pages
# ------------------------------------------------------------------

def terms_of_service(request):
    """Terms of Service page."""
    return render(request, 'saas/terms_of_service.html')


def privacy_policy(request):
    """Privacy Policy page."""
    return render(request, 'saas/privacy_policy.html')


# ------------------------------------------------------------------
# 3. Onboarding wizard
# ------------------------------------------------------------------

@login_required
def onboarding_view(request):
    """Multi-step onboarding wizard."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found for your account.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    # Determine current step from GET param or session
    step = request.GET.get('step', request.session.get('onboarding_step', '1'))
    step = str(step)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'skip':
            next_step = str(int(step) + 1)
            request.session['onboarding_step'] = next_step
            return redirect(f'/onboarding/?step={next_step}')

        if step == '1':
            form = OnboardingBusinessForm(request.POST, request.FILES)
            if form.is_valid():
                cd = form.cleaned_data
                if cd.get('business_phone'):
                    tenant.business_phone = cd['business_phone']
                if cd.get('business_email'):
                    tenant.business_email = cd['business_email']
                if cd.get('business_address'):
                    tenant.business_address = cd['business_address']
                if cd.get('logo'):
                    tenant.logo = cd['logo']
                tenant.save()
                messages.success(request, 'Business info saved!')
                request.session['onboarding_step'] = '2'
                return redirect('/onboarding/?step=2')

        elif step == '2':
            # Step 2: Add ANOTHER technician (owner is already set up from signup)
            form = OnboardingTechnicianForm(request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                try:
                    with transaction.atomic():
                        # Create a new user + technician (not yourself — you're already set up)
                        tech_email = cd.get('tech_email', '')
                        tech_first = cd.get('tech_first_name', '')
                        tech_last = cd.get('tech_last_name', '')

                        if tech_email or tech_first:
                            from apps.tenants.services.signup_service import generate_unique_username
                            tech_username = generate_unique_username(tech_email or '', tech_first)
                            if not User.objects.filter(username=tech_username).exists():
                                tech_user = User.objects.create_user(
                                    username=tech_username,
                                    email=tech_email or '',
                                    first_name=tech_first,
                                    last_name=tech_last,
                                    password=User.objects.make_random_password(),
                                )
                                Technician.objects.create(
                                    tenant=tenant,
                                    user=tech_user,
                                    phone_number=cd.get('tech_phone', ''),
                                    is_active=True,
                                )
                                TenantMembership.objects.create(
                                    tenant=tenant, user=tech_user, role='technician',
                                )
                                from django.contrib.auth.models import Group
                                tech_group, _ = Group.objects.get_or_create(name='Technicians')
                                tech_user.groups.add(tech_group)
                                messages.success(request, 'Technician added!')
                            else:
                                messages.info(request, 'A user with that email already exists.')
                        else:
                            messages.info(request, 'No technician info provided.')

                except Exception as e:
                    logger.error(f"Onboarding tech error: {e}")
                    messages.error(request, f'Could not add technician: {e}')

                # Only advance on valid form
                request.session['onboarding_step'] = '3'
                return redirect('/onboarding/?step=3')
            # Invalid form — stay on step 2 (fall through to GET handler)

        elif step == '3':
            form = OnboardingCustomerForm(request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                try:
                    if not Customer.objects.filter(
                        tenant=tenant, name__iexact=cd['customer_name']
                    ).exists():
                        Customer.objects.create(
                            tenant=tenant,
                            name=cd['customer_name'],
                            customer_type=cd['customer_type'],
                            email=cd.get('customer_email') or None,
                            phone=cd.get('customer_phone') or None,
                        )
                        messages.success(request, 'Customer added!')
                    else:
                        messages.info(request, 'Customer already exists.')
                except Exception as e:
                    logger.error(f"Onboarding customer error: {e}")
                    messages.error(request, f'Could not add customer: {e}')

                # Only advance on valid form
                request.session['onboarding_step'] = '4'
                return redirect('/onboarding/?step=4')
            # Invalid form — stay on step 3 (fall through to GET handler)

        elif step == '4':
            # Done — clear onboarding state
            request.session.pop('onboarding_step', None)
            return redirect('owner_dashboard')

    # Step 4 GET = onboarding complete — redirect straight to dashboard
    if step == '4':
        request.session.pop('onboarding_step', None)
        messages.success(request, "Setup complete! Welcome to your dashboard.")
        return redirect('owner_dashboard')

    # Build context for GET
    context = {
        'step': step,
        'tenant': tenant,
    }

    if step == '1':
        context['form'] = OnboardingBusinessForm(initial={
            'business_phone': tenant.business_phone,
            'business_email': tenant.business_email,
            'business_address': tenant.business_address,
        })
    elif step == '2':
        # Owner already has tech profile from signup — step 2 is for adding ANOTHER tech
        context['form'] = OnboardingTechnicianForm(initial={
            'tech_first_name': '',
            'tech_last_name': '',
            'tech_email': '',
            'add_self': False,
        })
    elif step == '3':
        context['form'] = OnboardingCustomerForm()

    return render(request, 'saas/onboarding.html', context)


# ------------------------------------------------------------------
# 4. Owner dashboard
# ------------------------------------------------------------------


def _get_billing_context(tenant):
    """Build billing summary context for the owner dashboard."""
    from apps.billing.models import Invoice, Payment
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from decimal import Decimal

    try:
        # Auto-update overdue status for invoices past due date
        # This catches invoices that became overdue since last check
        today = timezone.now().date()
        Invoice.objects.filter(
            tenant=tenant,
            status__in=['SENT', 'PARTIAL', 'DRAFT'],
            due_date__lt=today,
        ).update(status='OVERDUE')

        # Outstanding invoices
        outstanding = Invoice.objects.filter(
            tenant=tenant,
            status__in=['SENT', 'PARTIAL', 'OVERDUE'],
        ).select_related('customer').order_by('due_date')

        total_outstanding = outstanding.aggregate(
            total=Sum('total') - Sum('amount_paid')
        )
        outstanding_amount = (total_outstanding.get('total') or Decimal('0.00'))

        # Count overdue: either status=OVERDUE or due_date passed and not paid
        from django.utils import timezone
        today = timezone.now().date()
        overdue_count = outstanding.filter(
            models.Q(status='OVERDUE') | 
            models.Q(due_date__lt=today, status__in=['SENT', 'PARTIAL'])
        ).count()

        # Recent payments (last 10)
        recent_payments = Payment.objects.filter(
            invoice__tenant=tenant,
        ).select_related(
            'invoice', 'invoice__customer'
        ).order_by('-payment_date', '-created_at')[:10]

        # Payments this month
        from django.utils import timezone
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        payments_this_month = Payment.objects.filter(
            invoice__tenant=tenant,
            created_at__gte=month_start,
        ).aggregate(total=Sum('amount'))
        collected_this_month = payments_this_month.get('total') or Decimal('0.00')

        # Revenue this month — sum of cost for completed repairs/replacements
        repair_revenue = Repair.objects.filter(
            tenant=tenant,
            queue_status='COMPLETED',
            service_date__gte=month_start,
        ).aggregate(total=Sum('cost'))['total'] or Decimal('0.00')

        replacement_revenue = Replacement.objects.filter(
            tenant=tenant,
            queue_status='COMPLETED',
            service_date__gte=month_start,
        ).aggregate(total=Sum('cost'))['total'] or Decimal('0.00')

        total_revenue = repair_revenue + replacement_revenue

        return {
            'outstanding_invoices': outstanding[:10],
            'outstanding_count': outstanding.count(),
            'outstanding_amount': outstanding_amount,
            'overdue_count': overdue_count,
            'recent_payments': recent_payments,
            'collected_this_month': collected_this_month,
            'total_revenue': total_revenue,
            'repair_revenue': repair_revenue,
            'replacement_revenue': replacement_revenue,
        }
    except Exception:
        return {
            'outstanding_invoices': [],
            'outstanding_count': 0,
            'outstanding_amount': Decimal('0.00'),
            'overdue_count': 0,
            'recent_payments': [],
            'collected_this_month': Decimal('0.00'),
            'total_revenue': Decimal('0.00'),
            'repair_revenue': Decimal('0.00'),
            'replacement_revenue': Decimal('0.00'),
        }


@owner_or_manager_required
def owner_dashboard(request):
    """Owner dashboard with trial banner, usage, quick actions, recent activity."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.info(request, 'No shop found. Please sign up first.')
        return redirect('signup')

    usage_svc = UsageService(tenant)
    usage = usage_svc.get_summary()

    # Recent repairs & replacements
    recent_repairs = (
        Repair.objects.filter(tenant=tenant)
        .select_related('customer', 'technician')
        .order_by('-service_date')[:5]
    )
    recent_replacements = (
        Replacement.objects.filter(tenant=tenant)
        .select_related('customer', 'technician')
        .order_by('-service_date')[:5]
    )

    # Merge and sort, annotate with item_type for template
    all_items = list(recent_repairs) + list(recent_replacements)
    for item in all_items:
        item.item_type = 'Replacement' if isinstance(item, Replacement) else 'Repair'
    recent_activity = sorted(
        all_items,
        key=lambda x: x.service_date,
        reverse=True,
    )[:5]

    # Billing summary
    billing_context = _get_billing_context(tenant)

    context = {
        'tenant': tenant,
        'membership': membership,
        'usage': usage,
        'recent_activity': recent_activity,
        'trial_days_remaining': tenant.trial_days_remaining,
        'is_trial': tenant.plan == 'trial',
        'is_trial_expired': tenant.is_trial_expired,
    }
    context.update(billing_context)
    return render(request, 'saas/owner_dashboard.html', context)


# ------------------------------------------------------------------
# 5. Pricing
# ------------------------------------------------------------------

def pricing_view(request):
    """Public pricing page."""
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('display_order')
    return render(request, 'saas/pricing.html', {'plans': plans})


# ------------------------------------------------------------------
# 6. Billing settings
# ------------------------------------------------------------------

@owner_or_manager_required
def billing_view(request):
    """Billing settings for subscribed owners."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return redirect('signup')
    if not membership or membership.role != 'owner':
        messages.error(request, 'Only the shop owner can manage billing.')
        return redirect('owner_dashboard')

    usage_svc = UsageService(tenant)
    usage = usage_svc.get_summary()
    plans = SubscriptionPlan.objects.filter(is_active=True).exclude(slug='trial').order_by('display_order')

    # Handle actions
    if request.method == 'POST':
        action = request.POST.get('action', '')
        svc = SubscriptionService()

        try:
            if action == 'upgrade':
                plan_slug = request.POST.get('plan')
                if plan_slug:
                    base_url = request.build_absolute_uri('/').rstrip('/')
                    result = svc.create_subscription(tenant, plan_slug, base_url=base_url)
                    # Redirect to Stripe Checkout for payment
                    if result.get('checkout_url'):
                        return redirect(result['checkout_url'])
                    messages.success(request, 'Subscription created!')
            elif action == 'change_plan':
                plan_slug = request.POST.get('plan')
                if plan_slug:
                    try:
                        if tenant.stripe_subscription_id:
                            result = svc.update_subscription(tenant, plan_slug)
                            if result.get('status') == 'pending':
                                messages.info(request, 'Complete payment in Stripe to activate your upgrade.')
                                return_url = request.build_absolute_uri('/owner/billing/')
                                portal_url = svc.create_billing_portal_session(tenant, return_url)
                                return redirect(portal_url)
                            elif result.get('status') == 'scheduled':
                                messages.info(request, result.get('message', 'Plan change scheduled.'))
                            else:
                                messages.success(request, f'Plan updated to {result.get("new_plan")}!')
                        else:
                            raise SubscriptionError("No subscription")
                    except SubscriptionError as e:
                        if 'canceled' in str(e).lower() or 'not completed' in str(e).lower() or 'no subscription' in str(e).lower():
                            # Auto-fallback to create new subscription
                            base_url = request.build_absolute_uri('/').rstrip('/')
                            result = svc.create_subscription(tenant, plan_slug, base_url=base_url)
                            if result.get('checkout_url'):
                                return redirect(result['checkout_url'])
                        else:
                            raise
            elif action == 'cancel':
                svc.cancel_subscription(tenant)
                messages.success(request, 'Subscription will cancel at end of billing period.')
            elif action == 'reactivate':
                svc.reactivate_subscription(tenant)
                messages.success(request, 'Subscription reactivated!')
            elif action == 'billing_portal':
                return_url = request.build_absolute_uri('/owner/billing/')
                portal_url = svc.create_billing_portal_session(tenant, return_url)
                return redirect(portal_url)
        except SubscriptionError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.error(f"Billing error: {e}")
            messages.error(request, 'An error occurred. Please try again.')

        return redirect('billing_settings')

    context = {
        'tenant': tenant,
        'usage': usage,
        'plans': plans,
        'current_plan': tenant.subscription_plan,
        'is_trial': tenant.plan == 'trial',
        'trial_days_remaining': tenant.trial_days_remaining,
    }
    return render(request, 'saas/billing.html', context)


# ------------------------------------------------------------------
# 7. Replacement management
# ------------------------------------------------------------------

@owner_or_manager_required
def replacement_list(request):
    """List all glass replacements for the tenant."""
    from django.core.paginator import Paginator
    
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    # Filter by status if specified
    status_filter = request.GET.get('status', '')
    replacements = Replacement.objects.filter(tenant=tenant).select_related(
        'customer', 'technician__user'
    ).order_by('-service_date', '-created_at')

    if status_filter:
        replacements = replacements.filter(queue_status=status_filter)

    # Pagination
    paginator = Paginator(replacements, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Status choices for filter dropdown
    status_choices = [
        ('', 'All Statuses'),
        ('REQUESTED', 'Customer Requested'),
        ('PENDING', 'Approval Pending'),
        ('APPROVED', 'Approved'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('DENIED', 'Denied'),
    ]

    return render(request, 'saas/replacement_list.html', {
        'page_obj': page_obj,
        'tenant': tenant,
        'status_filter': status_filter,
        'status_choices': status_choices,
    })


@owner_or_manager_required
def replacement_create(request):
    """Create a new glass replacement."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    # Check limits
    usage_svc = UsageService(tenant)
    can_create, limit_msg = usage_svc.can_create_repair()
    if not can_create:
        messages.warning(request, limit_msg)
        return redirect('owner_dashboard')

    if request.method == 'POST':
        form = ReplacementForm(request.POST, request.FILES, tenant=tenant)
        if form.is_valid():
            replacement = form.save(commit=False)
            replacement.tenant = tenant
            replacement.save()

            # Auto-assign technician if none was chosen
            if not replacement.technician_id:
                from apps.tenants.services.assignment_service import auto_assign_replacement
                assigned_tech = auto_assign_replacement(replacement)
                if assigned_tech:
                    messages.info(
                        request,
                        f'Replacement auto-assigned to {assigned_tech.user.get_full_name()}.'
                    )

            messages.success(request, 'Replacement created successfully!')
            return redirect('replacement_detail', pk=replacement.pk)
    else:
        form = ReplacementForm(tenant=tenant)

    return render(request, 'saas/replacement_form.html', {
        'form': form,
        'tenant': tenant,
    })


@owner_or_manager_required
def replacement_detail(request, pk):
    """View a glass replacement."""
    tenant = getattr(request, 'tenant', None)
    replacement = get_object_or_404(Replacement, pk=pk)
    # Strict tenant check — deny if no tenant or tenant mismatch
    if not tenant or replacement.tenant_id != tenant.id:
        messages.error(request, 'Access denied.')
        return redirect('owner_dashboard')

    # Build allowed status transitions for the UI
    status_transitions = []
    current = replacement.queue_status
    if current == 'REQUESTED':
        status_transitions = [('PENDING', 'Move to Pending')]
    elif current == 'PENDING':
        status_transitions = [('APPROVED', 'Approve'), ('DENIED', 'Deny')]
    elif current == 'APPROVED':
        status_transitions = [('IN_PROGRESS', 'Start Work'), ('DENIED', 'Deny')]
    elif current == 'IN_PROGRESS':
        status_transitions = [('COMPLETED', 'Mark Complete')]
    # COMPLETED and DENIED are terminal states

    return render(request, 'saas/replacement_detail.html', {
        'replacement': replacement,
        'tenant': tenant,
        'status_transitions': status_transitions,
    })


@owner_or_manager_required
def replacement_edit(request, pk):
    """Edit an existing glass replacement."""
    tenant = getattr(request, 'tenant', None)
    replacement = get_object_or_404(Replacement, pk=pk)
    
    if not tenant or replacement.tenant_id != tenant.id:
        messages.error(request, 'Access denied.')
        return redirect('owner_dashboard')

    if request.method == 'POST':
        form = ReplacementForm(request.POST, request.FILES, instance=replacement, tenant=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Replacement updated successfully!')
            return redirect('replacement_detail', pk=replacement.pk)
    else:
        form = ReplacementForm(instance=replacement, tenant=tenant)

    return render(request, 'saas/replacement_edit.html', {
        'form': form,
        'replacement': replacement,
        'tenant': tenant,
    })


@require_POST
@owner_or_manager_required
def replacement_update_status(request, pk):
    """Update the status of a glass replacement."""
    tenant = getattr(request, 'tenant', None)
    replacement = get_object_or_404(Replacement, pk=pk)
    
    if not tenant or replacement.tenant_id != tenant.id:
        messages.error(request, 'Access denied.')
        return redirect('owner_dashboard')

    new_status = request.POST.get('status')
    valid_statuses = ['REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'DENIED']
    
    if new_status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('replacement_detail', pk=pk)

    old_status = replacement.queue_status
    replacement.queue_status = new_status
    replacement.save()

    status_display = replacement.get_queue_status_display()
    messages.success(request, f'Status updated to {status_display}.')
    
    return redirect('replacement_detail', pk=pk)


# ------------------------------------------------------------------
# 8. Billing — plan update, cancel, portal redirect
# ------------------------------------------------------------------

@owner_or_manager_required
def billing_update_plan(request):
    """POST /owner/billing/update/ — upgrade or downgrade plan."""
    if request.method != 'POST':
        return redirect('billing_settings')

    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role != 'owner':
        messages.error(request, 'Only the shop owner can change the subscription plan.')
        return redirect('billing_settings')

    new_plan_slug = request.POST.get('plan')
    if not new_plan_slug:
        messages.error(request, 'No plan specified.')
        return redirect('billing_settings')

    svc = SubscriptionService()
    try:
        if tenant.stripe_subscription_id:
            try:
                result = svc.update_subscription(tenant, new_plan_slug)
                if result.get('status') == 'pending':
                    # Upgrade requires payment - redirect to Billing Portal
                    messages.info(request, 'Complete payment in Stripe to activate your upgrade.')
                    return_url = request.build_absolute_uri('/owner/billing/')
                    portal_url = svc.create_billing_portal_session(tenant, return_url)
                    return redirect(portal_url)
                elif result.get('status') == 'scheduled':
                    messages.info(request, result.get('message', 'Plan change scheduled for end of billing period.'))
                else:
                    messages.success(request, f'Plan updated to {result["new_plan"]}!')
                return redirect('billing_settings')
            except SubscriptionError as e:
                # If subscription was canceled/incomplete, auto-fallback to create new
                if 'canceled' in str(e).lower() or 'not completed' in str(e).lower():
                    # Fall through to create_subscription below
                    pass
                else:
                    raise
        
        # Create new subscription (for trial users or after canceled sub)
        base_url = request.build_absolute_uri('/').rstrip('/')
        result = svc.create_subscription(tenant, new_plan_slug, base_url=base_url)
        if result.get('checkout_url'):
            return redirect(result['checkout_url'])
        else:
            messages.success(request, f'Subscribed to {result["plan"]}!')
            return redirect('billing_settings')
    except SubscriptionError as e:
        messages.error(request, str(e))
        return redirect('billing_settings')


@owner_or_manager_required
def billing_cancel(request):
    """POST /owner/billing/cancel/ — cancel subscription at end of period."""
    if request.method != 'POST':
        return redirect('billing_settings')

    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role != 'owner':
        messages.error(request, 'Only the shop owner can cancel the subscription.')
        return redirect('billing_settings')

    svc = SubscriptionService()
    try:
        result = svc.cancel_subscription(tenant)
        messages.warning(request, result['message'])
    except SubscriptionError as e:
        messages.error(request, str(e))

    return redirect('billing_settings')


@owner_or_manager_required
def billing_portal_redirect(request):
    """GET /owner/billing/portal/ — redirect to Stripe Billing Portal."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership:
        messages.error(request, 'Access denied.')
        return redirect('billing_settings')

    svc = SubscriptionService()
    try:
        return_url = request.build_absolute_uri('/owner/billing/')
        portal_url = svc.create_billing_portal_session(tenant, return_url)
        return redirect(portal_url)
    except SubscriptionError as e:
        messages.error(request, str(e))
        return redirect('billing_settings')


# ------------------------------------------------------------------
# 9. Owner Settings
# ------------------------------------------------------------------

@owner_or_manager_required
def owner_settings_view(request):
    """GET/POST /owner/settings/ — business info form + team management."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found. Please complete setup first.')
        return redirect('signup')
    if not membership or membership.role not in ('owner', 'manager'):
        messages.error(request, 'You do not have owner/manager access to this shop.')
        return redirect('owner_dashboard')

    if request.method == 'POST':
        form_type = request.POST.get('form_type', '')

        if form_type == 'assignment_strategy':
            # Handle assignment strategy update
            strategy = request.POST.get('assignment_strategy', '')
            valid_strategies = [c[0] for c in tenant.ASSIGNMENT_STRATEGY_CHOICES]
            if strategy in valid_strategies:
                tenant.assignment_strategy = strategy
                tenant.save(update_fields=['assignment_strategy'])
                messages.success(request, 'Repair assignment strategy updated successfully.')
            else:
                messages.error(request, 'Invalid assignment strategy selected.')
            return redirect('owner_settings')

        if form_type == 'toggle_auto_invoice':
            # Toggle auto-invoice generation at tenant level
            tenant.auto_invoice_enabled = not tenant.auto_invoice_enabled
            tenant.save(update_fields=['auto_invoice_enabled'])
            status = 'enabled' if tenant.auto_invoice_enabled else 'disabled'
            messages.success(request, f'Auto invoice generation {status}.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'billing_location':
            # Update shop location + tax rate breakdown
            try:
                from decimal import Decimal, InvalidOperation
                config = BillingConfig.get_instance()
                config.company_city = request.POST.get('company_city', '').strip()
                config.company_state = request.POST.get('company_state', '').strip().upper()
                config.company_zip = request.POST.get('company_zip', '').strip()

                # Parse component rates
                def _dec(field, default='0'):
                    try:
                        return Decimal(request.POST.get(field, default))
                    except (InvalidOperation, ValueError):
                        return Decimal(default)

                config.state_tax_rate = _dec('state_tax_rate', '6.500')
                config.county_tax_rate = _dec('county_tax_rate', '0')
                config.city_tax_rate = _dec('city_tax_rate', '0')
                config.special_tax_rate = _dec('special_tax_rate', '0')

                # Total auto-calculates from components
                config.default_tax_rate = (
                    config.state_tax_rate + config.county_tax_rate +
                    config.city_tax_rate + config.special_tax_rate
                )

                # Auto-enable tax when rates are set
                if config.default_tax_rate > 0:
                    config.tax_enabled = True

                config.save()
                from django.core.cache import cache
                cache.delete('billing_config_tax')
                messages.success(request, f'Tax settings saved: {config.default_tax_rate}% in {config.company_city}, {config.company_state}')
            except Exception as e:
                logger.error(f"Error updating billing config: {e}")
                messages.error(request, 'Could not update tax settings.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'toggle_overdue_reminders':
            # Toggle overdue reminder emails
            try:
                config = BillingConfig.get_instance()
                config.overdue_reminder_enabled = not config.overdue_reminder_enabled
                config.save(update_fields=['overdue_reminder_enabled'])
                status = 'enabled' if config.overdue_reminder_enabled else 'disabled'
                messages.success(request, f'Overdue reminders {status}.')
            except Exception as e:
                logger.error(f"Error toggling overdue reminders: {e}")
                messages.error(request, 'Could not update reminder settings.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'overdue_reminder_settings':
            # Update overdue reminder configuration
            try:
                config = BillingConfig.get_instance()
                config.overdue_reminder_days = request.POST.get('overdue_reminder_days', '7,14,30').strip()
                config.overdue_reminder_subject = request.POST.get('overdue_reminder_subject', 'Reminder: Invoice #{invoice_number} is overdue').strip()
                config.save(update_fields=['overdue_reminder_days', 'overdue_reminder_subject'])
                messages.success(request, 'Overdue reminder settings saved.')
            except Exception as e:
                logger.error(f"Error updating overdue reminder settings: {e}")
                messages.error(request, 'Could not update reminder settings.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'batch_invoice_settings':
            # Update batch invoicing configuration
            try:
                config = BillingConfig.get_instance()
                config.batch_invoice_frequency = request.POST.get('batch_invoice_frequency', 'disabled')
                config.batch_invoice_day = int(request.POST.get('batch_invoice_day', '1'))
                config.batch_invoice_auto_send = request.POST.get('batch_invoice_auto_send') == '1'
                config.save(update_fields=['batch_invoice_frequency', 'batch_invoice_day', 'batch_invoice_auto_send'])
                
                if config.batch_invoice_frequency != 'disabled':
                    messages.success(request, f'Batch invoicing enabled: {config.batch_invoice_frequency} on day {config.batch_invoice_day}.')
                else:
                    messages.success(request, 'Batch invoicing disabled.')
            except Exception as e:
                logger.error(f"Error updating batch invoice settings: {e}")
                messages.error(request, 'Could not update batch invoice settings.')
            return redirect('/owner/settings/?tab=billing')

        # Default: business info update
        tenant.name = request.POST.get('business_name', tenant.name).strip()
        tenant.business_phone = request.POST.get('business_phone', '').strip()
        tenant.business_email = request.POST.get('business_email', '').strip()
        tenant.business_address = request.POST.get('business_address', '').strip()

        if 'logo' in request.FILES:
            tenant.logo = request.FILES['logo']

        tenant.save()
        messages.success(request, 'Business information updated successfully.')
        return redirect('owner_settings')

    members = TenantMembership.objects.filter(
        tenant=tenant,
        is_active=True,
    ).select_related('user').order_by('role', 'joined_at')

    # Build a dict of user_id → Technician for ability badges
    technicians_by_user = {}
    for tech in Technician.objects.filter(tenant=tenant):
        technicians_by_user[tech.user_id] = tech

    # Annotate members with technician abilities and pending invite status
    for member in members:
        member.technician_record = technicians_by_user.get(member.user_id)
        member.has_unusable_password = not member.user.has_usable_password()

    # Shop join URL for customer portal
    shop_join_url = request.build_absolute_uri(f'/join/{tenant.slug}/')

    # Customers list for owner view
    customers = Customer.objects.filter(tenant=tenant).select_related(
        'primary_technician__user'
    ).order_by('name')
    # Annotate with portal access info
    customer_users = {
        cu.customer_id: cu for cu in CustomerUser.objects.filter(
            customer__tenant=tenant
        ).select_related('user', 'customer')
    }
    for cust in customers:
        cust.portal_user = customer_users.get(cust.id)

    # Tax rates for Billing tab
    tax_rates = TaxRate.objects.filter(
        models.Q(tenant=tenant) | models.Q(tenant__isnull=True)
    ).order_by('state', 'city')
    try:
        billing_config = BillingConfig.get_instance()
        tax_enabled = billing_config.tax_enabled
    except Exception:
        billing_config = None
        tax_enabled = False

    # Active tab from query string
    active_tab = request.GET.get('tab', 'general')

    context = {
        'tenant': tenant,
        'membership': membership,
        'members': members,
        'shop_join_url': shop_join_url,
        'customers': customers,
        'assignment_strategy_choices': tenant.ASSIGNMENT_STRATEGY_CHOICES,
        'tax_rates': tax_rates,
        'tax_enabled': tax_enabled,
        'billing_config': billing_config,
        'active_tab': active_tab,
    }

    return render(request, 'saas/owner_settings.html', context)


@owner_or_manager_required
def invite_member(request):
    """POST /owner/settings/invite/ — invite a new team member with invite token."""
    if request.method != 'POST':
        return redirect('owner_settings')

    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership:
        messages.error(request, 'Access denied.')
        return redirect('signup')

    if membership.role not in ('owner', 'manager'):
        messages.error(request, 'Only owners and managers can invite team members.')
        return redirect('owner_settings')

    email = request.POST.get('email', '').strip().lower()
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    role = request.POST.get('role', 'viewer')

    # Usage limit check for technicians
    if role == 'technician' and tenant:
        from apps.tenants.services.usage_service import UsageService
        can_add, limit_msg = UsageService(tenant).can_add_technician()
        if not can_add:
            messages.warning(request, limit_msg)
            return redirect('owner_settings')

    # Ability checkboxes for technicians/managers
    can_repair = request.POST.get('can_repair') == 'on'
    can_replace = request.POST.get('can_replace') == 'on'

    if not email:
        messages.error(request, 'Email is required.')
        return redirect('owner_settings')

    if role not in ('manager', 'technician', 'viewer'):
        messages.error(request, 'Invalid role selected.')
        return redirect('owner_settings')

    # Check if user already exists
    user = User.objects.filter(email=email).first()
    if not user:
        from apps.tenants.services.signup_service import generate_unique_username
        username = generate_unique_username(email, first_name)

        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save()

    # Check existing membership
    existing = TenantMembership.objects.filter(tenant=tenant, user=user).first()
    if existing:
        if existing.is_active:
            messages.warning(request, f'{email} is already a team member.')
        else:
            existing.is_active = True
            existing.role = role
            existing.save()
            messages.success(request, f'{email} has been re-added to the team.')
        return redirect('owner_settings')

    with transaction.atomic():
        TenantMembership.objects.create(
            tenant=tenant,
            user=user,
            role=role,
        )

        # Create Technician record for technician/manager roles
        if role in ('technician', 'manager'):
            from django.contrib.auth.models import Group
            tech_group, _ = Group.objects.get_or_create(name='Technicians')
            user.groups.add(tech_group)

            if not Technician.objects.filter(user=user).exists():
                Technician.objects.create(
                    tenant=tenant,
                    user=user,
                    is_manager=(role == 'manager'),
                    is_active=True,
                    can_repair=can_repair,
                    can_replace=can_replace,
                )

        # Create InviteToken
        from apps.tenants.models import InviteToken
        invite_token = InviteToken(
            tenant=tenant,
            user=user,
            role=role,
            invited_by=request.user,
        )
        invite_token.save()

        invite_url = request.build_absolute_uri(f"/invite/{invite_token.token}/")

    # Try to send invite email
    email_sent = False
    try:
        from django.core.mail import send_mail
        from django.conf import settings

        inviter_name = request.user.get_full_name() or request.user.email
        subject = f"You're invited to join {tenant.name} on RS Systems"
        body = (
            f"Hi {first_name},\n\n"
            f"{inviter_name} has invited you to join {tenant.name} as a {role}.\n\n"
            f"Click here to set your password and get started:\n"
            f"{invite_url}\n\n"
            f"This link expires in 7 days.\n\n"
            f"— RS Systems"
        )

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        email_sent = True
    except Exception as e:
        logger.warning(f"Failed to send invite email to {email}: {e}")

    if email_sent:
        messages.success(
            request,
            f'{first_name} {last_name} ({email}) has been invited as {role}. '
            f'An invite email has been sent.'
        )
    else:
        messages.success(
            request,
            f'{first_name} {last_name} ({email}) has been invited as {role}. '
            f'Email could not be sent. Share this invite link manually: {invite_url}'
        )

    return redirect('owner_settings')


# ------------------------------------------------------------------
# 10. Shop Join — Customer Self-Signup (Phase 4)
# ------------------------------------------------------------------

def shop_join_view(request, slug):
    """Public page: /join/<slug>/ — customer self-signup for a shop's portal."""
    tenant = get_object_or_404(Tenant, slug=slug, is_active=True)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip() or None
        company_name = request.POST.get('company_name', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        errors = []

        if not first_name or not last_name:
            errors.append('First and last name are required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if password != confirm_password:
            errors.append('Passwords do not match.')

        # Check password strength
        if password:
            temp_user = User(username='temp', email=email, first_name=first_name, last_name=last_name)
            try:
                validate_password(password, user=temp_user)
            except ValidationError as e:
                errors.extend(e.messages)

        # Check email uniqueness
        if email and User.objects.filter(email=email).exists():
            errors.append('An account with this email already exists. Please log in instead.')

        if errors:
            return render(request, 'saas/shop_join.html', {
                'tenant': tenant,
                'errors': errors,
                'form_data': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'phone': phone or '',
                    'company_name': company_name,
                },
            })

        # All good — create everything
        try:
            with transaction.atomic():
                # 1. Create User
                from apps.tenants.services.signup_service import generate_unique_username
                user = User.objects.create_user(
                    username=generate_unique_username(email, first_name),
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )

                # 2. Create Customer
                customer_name = company_name if company_name else f"{first_name} {last_name}"
                customer_type = 'FLEET' if company_name else 'RETAIL'

                # Check uniqueness within this tenant
                if Customer.objects.filter(tenant=tenant, name=customer_name).exists():
                    customer_name = f"{customer_name} ({user.email})"

                customer = Customer.objects.create(
                    tenant=tenant,
                    name=customer_name,
                    customer_type=customer_type,
                    email=email,
                    phone=phone,
                )

                # 3. Create CustomerUser
                CustomerUser.objects.create(
                    user=user,
                    customer=customer,
                    is_primary_contact=True,
                )

                # 4. Create TenantMembership
                TenantMembership.objects.create(
                    tenant=tenant,
                    user=user,
                    role='viewer',
                )

            # 5. Log them in
            auth_user = authenticate(request, username=user.username, password=password)
            if auth_user:
                login(request, auth_user)
                request.session['tenant_id'] = tenant.id

            messages.success(request, f'Welcome to {tenant.name}! Your portal account is ready.')
            return redirect('customer_dashboard')

        except Exception as e:
            logger.error(f"Shop join error for {email} at {tenant.slug}: {e}")
            return render(request, 'saas/shop_join.html', {
                'tenant': tenant,
                'errors': ['An unexpected error occurred. Please try again.'],
                'form_data': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'phone': phone or '',
                    'company_name': company_name,
                },
            })

    return render(request, 'saas/shop_join.html', {'tenant': tenant})


# ------------------------------------------------------------------
# 11. Team Management Endpoints (Phase 6)
# ------------------------------------------------------------------

@owner_or_manager_required
@require_POST
def update_team_member(request, membership_id):
    """POST: Update a team member's role and/or abilities."""
    tenant, my_membership = _get_owner_tenant(request)
    if not tenant or not my_membership:
        messages.error(request, 'Access denied.')
        return redirect('owner_settings')

    target = get_object_or_404(TenantMembership, id=membership_id, tenant=tenant, is_active=True)

    # Can't change own role
    if target.user == request.user:
        messages.error(request, 'You cannot change your own role.')
        return redirect('owner_settings')

    new_role = request.POST.get('role', target.role)
    can_repair = request.POST.get('can_repair') == 'on'
    can_replace = request.POST.get('can_replace') == 'on'

    # Only owners can change roles
    if new_role != target.role and my_membership.role != 'owner':
        messages.error(request, 'Only the shop owner can change member roles.')
        return redirect('owner_settings')

    # Validate role
    if new_role not in ('owner', 'manager', 'technician', 'viewer'):
        messages.error(request, 'Invalid role.')
        return redirect('owner_settings')

    with transaction.atomic():
        old_role = target.role
        target.role = new_role
        target.save()

        # Handle Technician record based on role change
        if new_role in ('technician', 'manager'):
            from django.contrib.auth.models import Group
            tech_group, _ = Group.objects.get_or_create(name='Technicians')
            target.user.groups.add(tech_group)

            tech, created = Technician.objects.get_or_create(
                user=target.user,
                defaults={
                    'tenant': tenant,
                    'is_manager': (new_role == 'manager'),
                    'is_active': True,
                    'can_repair': can_repair,
                    'can_replace': can_replace,
                },
            )
            if not created:
                tech.is_manager = (new_role == 'manager')
                tech.can_repair = can_repair
                tech.can_replace = can_replace
                tech.tenant = tenant
                tech.save()
        elif old_role in ('technician', 'manager') and new_role not in ('technician', 'manager'):
            # Deactivate technician record if moving away from tech/manager
            try:
                tech = Technician.objects.get(user=target.user)
                tech.is_active = False
                tech.save()
            except Technician.DoesNotExist:
                pass

    member_name = target.user.get_full_name() or target.user.email
    messages.success(request, f'Updated {member_name} to {target.get_role_display()}.')
    return redirect('owner_settings')


@owner_or_manager_required
@require_POST
def deactivate_team_member(request, membership_id):
    """POST: Deactivate a team member (soft delete)."""
    tenant, my_membership = _get_owner_tenant(request)
    if not tenant or not my_membership:
        messages.error(request, 'Access denied.')
        return redirect('owner_settings')

    target = get_object_or_404(TenantMembership, id=membership_id, tenant=tenant, is_active=True)

    # Can't deactivate yourself
    if target.user == request.user:
        messages.error(request, 'You cannot deactivate yourself.')
        return redirect('owner_settings')

    # Managers can only deactivate technicians/viewers
    if my_membership.role == 'manager' and target.role in ('owner', 'manager'):
        messages.error(request, 'Managers can only deactivate technicians and viewers.')
        return redirect('owner_settings')

    # Owners can deactivate anyone except themselves (already checked)
    if my_membership.role not in ('owner', 'manager'):
        messages.error(request, 'You do not have permission to deactivate team members.')
        return redirect('owner_settings')

    with transaction.atomic():
        target.is_active = False
        target.save()

        # Also deactivate technician record if exists
        try:
            tech = Technician.objects.get(user=target.user, tenant=tenant)
            tech.is_active = False
            tech.save()
        except Technician.DoesNotExist:
            pass

    member_name = target.user.get_full_name() or target.user.email
    messages.success(request, f'{member_name} has been deactivated from the team.')
    return redirect('owner_settings')


@owner_or_manager_required
@require_POST
def resend_invite(request, membership_id):
    """POST: Resend invite email to a member who hasn't set their password."""
    tenant, my_membership = _get_owner_tenant(request)
    if not tenant or not my_membership:
        messages.error(request, 'Access denied.')
        return redirect('owner_settings')

    if my_membership.role not in ('owner', 'manager'):
        messages.error(request, 'Only owners and managers can resend invites.')
        return redirect('owner_settings')

    target = get_object_or_404(TenantMembership, id=membership_id, tenant=tenant, is_active=True)

    if target.user.has_usable_password():
        messages.info(request, f'{target.user.email} has already set their password.')
        return redirect('owner_settings')

    # Create new InviteToken
    invite_token = InviteToken(
        tenant=tenant,
        user=target.user,
        role=target.role,
        invited_by=request.user,
    )
    invite_token.save()

    invite_url = request.build_absolute_uri(f"/invite/{invite_token.token}/")

    # Send email
    email_sent = False
    try:
        from django.core.mail import send_mail
        from django.conf import settings

        inviter_name = request.user.get_full_name() or request.user.email
        subject = f"Reminder: You're invited to join {tenant.name} on RS Systems"
        body = (
            f"Hi {target.user.first_name},\n\n"
            f"{inviter_name} has re-sent your invitation to join {tenant.name} as a {target.get_role_display()}.\n\n"
            f"Click here to set your password and get started:\n"
            f"{invite_url}\n\n"
            f"This link expires in 7 days.\n\n"
            f"— RS Systems"
        )

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[target.user.email],
            fail_silently=False,
        )
        email_sent = True
    except Exception as e:
        logger.warning(f"Failed to resend invite to {target.user.email}: {e}")

    member_name = target.user.get_full_name() or target.user.email
    if email_sent:
        messages.success(request, f'Invite re-sent to {member_name}.')
    else:
        messages.success(
            request,
            f'New invite created for {member_name}. '
            f'Email could not be sent. Share manually: {invite_url}'
        )
    return redirect('owner_settings')


# ------------------------------------------------------------------
# 12. Owner Invoice Management & Manual Payment Recording
# ------------------------------------------------------------------

@owner_or_manager_required
def owner_invoice_list(request):
    """GET /owner/invoices/ — list all invoices across all customers."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    from django.db.models import Sum, Q, Count
    from django.utils import timezone
    from decimal import Decimal

    # Auto-update overdue status for invoices past due date
    # This catches invoices that became overdue since last check
    Invoice.objects.filter(
        customer__tenant=tenant,
        status__in=['SENT', 'PARTIAL', 'DRAFT'],
        due_date__lt=timezone.now().date(),
    ).update(status='OVERDUE')

    # Base queryset — all invoices for this tenant
    invoices = Invoice.objects.filter(
        customer__tenant=tenant,
    ).select_related('customer').order_by('-invoice_date', '-created_at')

    # --- Filters ---
    status_filter = request.GET.get('status', 'all')
    customer_filter = request.GET.get('customer', '')

    if status_filter == 'paid':
        invoices = invoices.filter(status='PAID')
    elif status_filter == 'unpaid':
        invoices = invoices.filter(status__in=['SENT', 'PARTIAL', 'DRAFT'])
    elif status_filter == 'overdue':
        invoices = invoices.filter(status='OVERDUE')
    elif status_filter == 'partial':
        invoices = invoices.filter(status='PARTIAL')

    if customer_filter:
        try:
            invoices = invoices.filter(customer_id=int(customer_filter))
        except (ValueError, TypeError):
            pass

    # --- Summary cards ---
    all_invoices = Invoice.objects.filter(customer__tenant=tenant)

    outstanding_qs = all_invoices.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE'])
    total_outstanding = outstanding_qs.aggregate(
        total=Sum('total') - Sum('amount_paid')
    )
    outstanding_amount = total_outstanding.get('total') or Decimal('0.00')

    overdue_qs = all_invoices.filter(status='OVERDUE')
    overdue_agg = overdue_qs.aggregate(
        total=Sum('total') - Sum('amount_paid')
    )
    overdue_amount = overdue_agg.get('total') or Decimal('0.00')
    overdue_count = overdue_qs.count()

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    payments_this_month = Payment.objects.filter(
        invoice__customer__tenant=tenant,
        created_at__gte=month_start,
    ).aggregate(total=Sum('amount'))
    payments_month_amount = payments_this_month.get('total') or Decimal('0.00')

    invoices_this_month = all_invoices.filter(
        created_at__gte=month_start,
    ).count()

    # Customer list for filter dropdown
    customers = Customer.objects.filter(tenant=tenant).order_by('name')

    # Uninvoiced completed repairs per customer
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    tracking = InvoiceTrackingService(tenant=tenant)
    uninvoiced_customers = []
    for cust in customers:
        uninvoiced = tracking.get_uninvoiced_repairs(cust)
        count = uninvoiced.count() if hasattr(uninvoiced, 'count') else len(uninvoiced)
        if count > 0:
            # Sum up costs
            total_cost = sum(r.cost or 0 for r in uninvoiced)
            uninvoiced_customers.append({
                'customer': cust,
                'count': count,
                'total': total_cost,
            })

    context = {
        'tenant': tenant,
        'invoices': invoices,
        'customers': customers,
        'status_filter': status_filter,
        'customer_filter': customer_filter,
        'outstanding_amount': outstanding_amount,
        'overdue_amount': overdue_amount,
        'overdue_count': overdue_count,
        'payments_month_amount': payments_month_amount,
        'invoices_this_month': invoices_this_month,
        'uninvoiced_customers': uninvoiced_customers,
    }
    return render(request, 'saas/owner_invoices.html', context)


@owner_or_manager_required
def owner_invoice_detail(request, invoice_id):
    """GET /owner/invoices/<id>/ — invoice detail with payment history."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)
    line_items = invoice.line_items.all().order_by('id')
    payments = invoice.payments.all().order_by('-payment_date', '-created_at')

    # Payment method choices for the form (exclude STRIPE — that's automatic)
    payment_methods = [
        choice for choice in Payment.PAYMENT_METHOD_CHOICES
        if choice[0] != 'STRIPE'
    ]

    # PDF download URL
    pdf_url = None
    if invoice.s3_key:
        pdf_url = f"https://rs-systems-media-20251029.s3.amazonaws.com/{invoice.s3_key}"

    context = {
        'tenant': tenant,
        'invoice': invoice,
        'line_items': line_items,
        'payments': payments,
        'payment_methods': payment_methods,
        'pdf_url': pdf_url,
        'today': timezone.now().date(),
    }
    return render(request, 'saas/owner_invoice_detail.html', context)


@owner_or_manager_required
@require_POST
def owner_record_payment(request, invoice_id):
    """POST /owner/invoices/<id>/record-payment/ — record a manual payment."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)

    # Parse and validate fields
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(request.POST.get('amount', '0'))
    except (InvalidOperation, TypeError):
        messages.error(request, 'Invalid amount. Please enter a valid number.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    payment_method = request.POST.get('payment_method', 'OTHER')
    reference_number = request.POST.get('reference_number', '').strip()
    payment_date_str = request.POST.get('payment_date', '')
    notes = request.POST.get('notes', '').strip()

    # Validate amount
    if amount <= Decimal('0'):
        messages.error(request, 'Payment amount must be greater than zero.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    if amount > invoice.amount_due:
        messages.error(
            request,
            f'Payment amount (${amount}) exceeds the amount due (${invoice.amount_due}).'
        )
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    if invoice.status in ('PAID', 'CANCELLED'):
        messages.error(request, f'Cannot record payment — invoice is {invoice.get_status_display()}.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    # Validate payment method
    valid_methods = [c[0] for c in Payment.PAYMENT_METHOD_CHOICES]
    if payment_method not in valid_methods:
        messages.error(request, 'Invalid payment method.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    # Parse payment date
    from datetime import date
    payment_date = timezone.now().date()
    if payment_date_str:
        try:
            payment_date = date.fromisoformat(payment_date_str)
        except ValueError:
            messages.error(request, 'Invalid payment date.')
            return redirect('owner_invoice_detail', invoice_id=invoice.id)

    # Create the Payment record
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                invoice=invoice,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes,
                recorded_by=request.user,
            )
            # Payment.save() already calls _update_invoice_totals()

        # Send payment confirmation emails (best-effort, don't fail the request)
        try:
            from apps.billing.services.payment_notification_service import PaymentNotificationService
            notification_svc = PaymentNotificationService()
            notification_svc.notify_payment(payment)
        except Exception as e:
            logger.warning(f"Payment notification failed: {e}")

        messages.success(
            request,
            f'Payment of ${amount} recorded successfully via '
            f'{payment.get_payment_method_display()}.'
        )

    except Exception as e:
        logger.error(f"Error recording payment for invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'An error occurred while recording the payment. Please try again.')

    return redirect('owner_invoice_detail', invoice_id=invoice.id)


# ─── Tax Rate Management ─────────────────────────────────────────────
@owner_or_manager_required
def owner_tax_rates(request):
    """GET /owner/tax-rates/ — redirect to settings billing tab."""
    return redirect('/owner/settings/?tab=billing')


@owner_or_manager_required
def owner_add_tax_rate(request):
    """POST /owner/tax-rates/add/ — add a new tax rate."""
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=billing')

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    from decimal import Decimal, InvalidOperation

    city = request.POST.get('city', '').strip()
    county = request.POST.get('county', '').strip()
    state = request.POST.get('state', 'AR').strip().upper()
    zip_code = request.POST.get('zip_code', '').strip()

    if not city:
        messages.error(request, 'City is required.')
        return redirect('/owner/settings/?tab=billing')

    if not state or len(state) != 2:
        messages.error(request, 'Please enter a valid 2-letter state code.')
        return redirect('/owner/settings/?tab=billing')

    try:
        state_rate = Decimal(request.POST.get('state_rate', '0'))
        county_rate = Decimal(request.POST.get('county_rate', '0'))
        city_rate = Decimal(request.POST.get('city_rate', '0'))
        special_rate = Decimal(request.POST.get('special_rate', '0'))
    except (InvalidOperation, ValueError):
        messages.error(request, 'Invalid rate value. Enter numbers only.')
        return redirect('/owner/settings/?tab=billing')

    # Check for duplicates
    if TaxRate.objects.filter(tenant=tenant, city__iexact=city, state__iexact=state).exists():
        messages.error(request, f'A tax rate for {city}, {state} already exists.')
        return redirect('/owner/settings/?tab=billing')

    TaxRate.objects.create(
        tenant=tenant,
        city=city,
        county=county,
        state=state,
        zip_code=zip_code,
        state_rate=state_rate,
        county_rate=county_rate,
        city_rate=city_rate,
        special_rate=special_rate,
    )

    total = state_rate + county_rate + city_rate + special_rate
    messages.success(request, f'Tax rate added: {city}, {state} — {total}%')
    return redirect('/owner/settings/?tab=billing')


@owner_or_manager_required
def owner_edit_tax_rate(request, rate_id):
    """POST /owner/tax-rates/<id>/edit/ — update a tax rate."""
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=billing')

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return redirect('signup')

    rate = get_object_or_404(TaxRate, id=rate_id, tenant=tenant)

    from decimal import Decimal, InvalidOperation

    city = request.POST.get('city', '').strip()
    state = request.POST.get('state', '').strip().upper()

    if city:
        rate.city = city
    if state and len(state) == 2:
        rate.state = state
    rate.county = request.POST.get('county', rate.county).strip()
    rate.zip_code = request.POST.get('zip_code', rate.zip_code).strip()

    try:
        rate.state_rate = Decimal(request.POST.get('state_rate', rate.state_rate))
        rate.county_rate = Decimal(request.POST.get('county_rate', rate.county_rate))
        rate.city_rate = Decimal(request.POST.get('city_rate', rate.city_rate))
        rate.special_rate = Decimal(request.POST.get('special_rate', rate.special_rate))
    except (InvalidOperation, ValueError):
        messages.error(request, 'Invalid rate value.')
        return redirect('/owner/settings/?tab=billing')

    rate.save()  # total auto-calculates
    messages.success(request, f'Tax rate updated: {rate.city}, {rate.state} — {rate.total_rate}%')
    return redirect('/owner/settings/?tab=billing')


@owner_or_manager_required
def owner_delete_tax_rate(request, rate_id):
    """POST /owner/tax-rates/<id>/delete/ — remove a tax rate."""
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=billing')

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return redirect('signup')

    rate = get_object_or_404(TaxRate, id=rate_id, tenant=tenant)
    city_state = f'{rate.city}, {rate.state}'
    rate.delete()
    messages.success(request, f'Tax rate removed: {city_state}')
    return redirect('/owner/settings/?tab=billing')


@owner_or_manager_required
def owner_toggle_tax(request):
    """POST /owner/tax-rates/toggle/ — enable/disable tax globally."""
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=billing')

    try:
        config = BillingConfig.get_instance()
        config.tax_enabled = not config.tax_enabled
        config.save()
        from django.core.cache import cache
        cache.delete('billing_config_tax')
        
        status = 'enabled' if config.tax_enabled else 'disabled'
        messages.success(request, f'Sales tax calculation {status}.')
    except Exception as e:
        logger.error(f"Error toggling tax: {e}")
        messages.error(request, 'Could not update tax setting.')

    return redirect('/owner/settings/?tab=billing')


# ─── Invoice Actions (Send, Email) ───────────────────────────────────
@owner_or_manager_required
@require_POST
def owner_send_invoice(request, invoice_id):
    """POST /owner/invoices/<id>/send/ — finalize draft and send to customer."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)
    
    if invoice.status not in ('DRAFT',):
        messages.error(request, 'Only draft invoices can be sent.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    try:
        # Update status to SENT
        invoice.status = 'SENT'
        invoice.sent_at = timezone.now()
        invoice.save(update_fields=['status', 'sent_at'])
        
        # Try to email the invoice
        email_sent = False
        try:
            from apps.billing.services.invoice_email_service import InvoiceEmailService
            email_service = InvoiceEmailService()
            
            # Get recipient email
            recipient = None
            try:
                prefs = invoice.customer.repair_preferences
                recipient = prefs.billing_email or invoice.customer.email
            except Exception:
                recipient = invoice.customer.email
            
            if recipient:
                # Get repair IDs from line items
                repair_ids = list(invoice.line_items.exclude(repair_id__isnull=True).values_list('repair_id', flat=True))
                
                if repair_ids:
                    success, msg = email_service.send_invoice_email(
                        customer_id=invoice.customer.id,
                        recipient_email=recipient,
                        repair_ids=repair_ids,
                    )
                    email_sent = success
                    if not success:
                        logger.warning(f"Invoice email failed: {msg}")
                else:
                    logger.warning(f"No repair IDs found on invoice {invoice.invoice_number} for email")
        except Exception as e:
            logger.warning(f"Could not email invoice {invoice.invoice_number}: {e}")
        
        if email_sent:
            messages.success(request, f'Invoice {invoice.invoice_number} sent and emailed to customer.')
        else:
            messages.success(request, f'Invoice {invoice.invoice_number} marked as sent. (Email delivery may have failed - check customer email settings)')
            
    except Exception as e:
        logger.error(f"Error sending invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'An error occurred while sending the invoice.')

    return redirect('owner_invoice_detail', invoice_id=invoice.id)


@owner_or_manager_required
@require_POST
def owner_email_invoice(request, invoice_id):
    """POST /owner/invoices/<id>/email/ — (re)send invoice email to customer."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)
    
    if invoice.status == 'DRAFT':
        messages.error(request, 'Cannot email a draft invoice. Send it first.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    try:
        from apps.billing.services.invoice_email_service import InvoiceEmailService
        email_service = InvoiceEmailService()
        
        # Get recipient email (can be overridden from form)
        recipient = request.POST.get('email', '').strip()
        if not recipient:
            try:
                prefs = invoice.customer.repair_preferences
                recipient = prefs.billing_email or invoice.customer.email
            except Exception:
                recipient = invoice.customer.email
        
        if not recipient:
            messages.error(request, 'No email address found for this customer.')
            return redirect('owner_invoice_detail', invoice_id=invoice.id)
        
        repair_ids = list(invoice.line_items.exclude(repair_id__isnull=True).values_list('repair_id', flat=True))
        
        success, msg = email_service.send_invoice_email(
            customer_id=invoice.customer.id,
            recipient_email=recipient,
            repair_ids=repair_ids if repair_ids else None,
        )
        
        if success:
            messages.success(request, f'Invoice emailed to {recipient}.')
        else:
            messages.error(request, f'Failed to email invoice: {msg}')
            
    except Exception as e:
        logger.error(f"Error emailing invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'An error occurred while emailing the invoice.')

    return redirect('owner_invoice_detail', invoice_id=invoice.id)


@owner_or_manager_required
def owner_send_reminder(request, invoice_id):
    """POST /owner/invoices/<id>/reminder/ — send payment reminder to customer."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)
    
    if invoice.status in ['PAID', 'CANCELLED', 'DRAFT']:
        messages.error(request, f'Cannot send reminder for {invoice.get_status_display().lower()} invoice.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    if not invoice.customer.email:
        messages.error(request, 'No email address found for this customer.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)

    try:
        from apps.billing.services.reminder_service import ReminderService
        reminder_service = ReminderService(tenant=tenant)
        
        # Determine reminder type based on invoice status
        if invoice.status == 'OVERDUE' or (invoice.due_date and invoice.due_date < timezone.now().date()):
            reminder_type = 'overdue'
        else:
            reminder_type = 'due_soon'
        
        result = reminder_service.send_reminder(invoice, reminder_type)
        
        if result.get('success'):
            messages.success(request, f'Payment reminder sent to {invoice.customer.email}.')
        else:
            messages.error(request, f'Failed to send reminder: {result.get("error", "Unknown error")}')
            
    except Exception as e:
        logger.error(f"Error sending reminder for invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'An error occurred while sending the reminder.')

    return redirect('owner_invoice_detail', invoice_id=invoice.id)
