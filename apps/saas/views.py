"""
SaaS UI Views

Template-based views for signup, onboarding, owner dashboard,
pricing, billing settings, replacement form, shop join (customer
self-signup), and team management endpoints.

Author: Amelia (Clawdbot AI)
"""

import logging
import secrets
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
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


def _send_verification_email(request, user):
    """
    Send email verification link to a user after signup.
    
    Uses Django's token generator for secure verification links.
    Fails silently to never block the signup flow.
    """
    try:
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        
        # Check if user is a CustomerUser or shop owner
        try:
            from apps.customer_portal.models import CustomerUser
            CustomerUser.objects.get(user=user)
            # Customer - use customer verification URL
            verification_url = request.build_absolute_uri(
                reverse('customer_confirm_email_verification', kwargs={'uidb64': uid, 'token': token})
            )
        except CustomerUser.DoesNotExist:
            # Shop owner — use the dedicated owner verification endpoint
            verification_url = request.build_absolute_uri(
                reverse('owner_confirm_email_verification', kwargs={'uidb64': uid, 'token': token})
            )
        
        send_mail(
            subject='Verify your email address - RS Systems',
            message=f'''Welcome to RS Systems!

Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create an account, you can safely ignore this email.

— The RS Systems Team
''',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,  # Never block signup on email failure
        )
        logger.info(f"Verification email sent to {user.email}")
    except Exception as e:
        # Log but don't fail - verification email is non-critical
        logger.warning(f"Failed to send verification email to {user.email}: {e}")


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

                # Send verification email (fails silently)
                _send_verification_email(request, user)

                messages.success(
                    request,
                    f'Welcome to RS Systems, {cd["first_name"]}! '
                    f'Your 30-day free trial has started. Check your email to verify your address.',
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
            # Step 2: Add technician — either yourself or someone else
            form = OnboardingTechnicianForm(request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                try:
                    with transaction.atomic():
                        add_self = cd.get('add_self', False)

                        if add_self:
                            # Add the owner as a technician (use their existing user)
                            if not Technician.objects.filter(user=request.user, tenant=tenant).exists():
                                Technician.objects.create(
                                    tenant=tenant,
                                    user=request.user,
                                    phone_number=cd.get('tech_phone', '') or tenant.business_phone,
                                    is_active=True,
                                )
                                from django.contrib.auth.models import Group
                                tech_group, _ = Group.objects.get_or_create(name='Technicians')
                                request.user.groups.add(tech_group)
                                messages.success(request, 'You have been added as a technician!')
                            else:
                                messages.info(request, 'You are already set up as a technician.')
                        else:
                            # Add a different person as technician
                            tech_email = cd.get('tech_email', '')
                            tech_first = cd.get('tech_first_name', '')
                            tech_last = cd.get('tech_last_name', '')

                            if tech_email or tech_first:
                                from apps.tenants.services.signup_service import generate_unique_username
                                # Check email uniqueness BEFORE generating username.
                                # generate_unique_username() always returns a unique username, so the
                                # old guard `if not User.objects.filter(username=...).exists()` was
                                # always True — dead code that never caught duplicate emails.
                                # Fix: check email first (the actual duplicate risk).
                                if tech_email and User.objects.filter(email__iexact=tech_email).exists():
                                    messages.info(request, 'A user with that email already exists. You can add them to your team from Settings → Team.')
                                else:
                                    tech_username = generate_unique_username(tech_email or '', tech_first)
                                    tech_user = User.objects.create_user(
                                        username=tech_username,
                                        email=tech_email or '',
                                        first_name=tech_first,
                                        last_name=tech_last,
                                        password=secrets.token_urlsafe(16),
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
                                    tech_display = f"{tech_first} {tech_last}".strip() or tech_email or 'Technician'
                                    if tech_email:
                                        messages.success(
                                            request,
                                            f'{tech_display} has been added to your team. '
                                            f'Go to Settings → Team to send them an invite so they can log in.'
                                        )
                                    else:
                                        messages.success(
                                            request,
                                            f'{tech_display} has been added to your team. '
                                            f'Add their email in Settings → Team to send a login invite.'
                                        )
                            else:
                                messages.info(request, 'No technician info provided — you can add team members later in Settings → Team.')

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
            status__in=['SENT', 'PARTIAL'],
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
        logger.exception("Failed to load billing dashboard stats for tenant")
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

    # Setup checklist for new users
    from apps.billing.models import TaxRate

    setup_steps = []
    has_tax_rates = TaxRate.objects.filter(tenant=tenant, is_active=True).exists()
    has_customers = Customer.objects.filter(tenant=tenant).exists()
    has_technicians = Technician.objects.filter(tenant=tenant, is_active=True).exists()
    has_business_info = bool(tenant.business_phone and tenant.business_email)

    if not has_business_info:
        setup_steps.append({
            'label': 'Add your business info',
            'desc': 'Phone number and email for invoices',
            'url': '/owner/settings/?tab=general',
            'icon': 'fas fa-building',
        })
    # NOTE: Pricing step intentionally removed. _setup_completion() treats pricing
    # as always configured (sensible defaults exist), and checking for default values
    # is ambiguous — a shop owner may legitimately charge $50 per repair.
    # The "Finish setting up your shop" banner was persisting even after full setup
    # because pricing_is_default was True even for correctly configured shops. (CODE-110)
    if not has_tax_rates:
        setup_steps.append({
            'label': 'Configure sales tax',
            'desc': 'Tax is disabled until you add a tax rate for your area',
            'url': '/owner/settings/?tab=billing',
            'icon': 'fas fa-receipt',
        })
    if not has_customers:
        setup_steps.append({
            'label': 'Add your first customer',
            'desc': 'Fleet accounts, retail, or walk-in',
            'url': '/tech/customers/create/',
            'icon': 'fas fa-users',
        })
    if not has_technicians:
        setup_steps.append({
            'label': 'Add a technician',
            'desc': 'Add yourself or invite a team member',
            'url': '/owner/settings/?tab=team',
            'icon': 'fas fa-hard-hat',
        })

    setup_completion = _setup_completion(tenant)

    context = {
        'tenant': tenant,
        'membership': membership,
        'usage': usage,
        'recent_activity': recent_activity,
        'trial_days_remaining': tenant.trial_days_remaining,
        'is_trial': tenant.plan == 'trial',
        'is_trial_expired': tenant.is_trial_expired,
        'setup_steps': setup_steps,
        'setup_completion': setup_completion,
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
    ).order_by('-service_date', '-id')

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
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

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
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

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
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

    new_status = request.POST.get('status')

    # Valid forward transitions only — no backward re-opening of closed replacements.
    # COMPLETED replacements may already have invoice line items; re-opening them would
    # cause the replacement to be invoiced again (double-billing).  DENIED replacements
    # should require deliberate manual intervention, not an accidental status POST.
    # (CODE-064: mirrors the CODE-061 guard applied to customer-portal repair views.)
    ALLOWED_TRANSITIONS = {
        'REQUESTED':   {'PENDING', 'APPROVED', 'DENIED'},
        'PENDING':     {'APPROVED', 'DENIED'},
        'APPROVED':    {'IN_PROGRESS', 'DENIED'},
        'IN_PROGRESS': {'COMPLETED', 'DENIED'},
        # COMPLETED and DENIED are terminal — no transitions allowed
        'COMPLETED':   set(),
        'DENIED':      set(),
    }

    old_status = replacement.queue_status
    allowed = ALLOWED_TRANSITIONS.get(old_status, set())

    if new_status not in allowed:
        if old_status in ('COMPLETED', 'DENIED'):
            messages.error(
                request,
                f'This replacement is {replacement.get_queue_status_display()} and cannot be changed. '
                f'Contact support if a correction is needed.'
            )
        else:
            messages.error(request, f'Invalid status transition from {old_status} to {new_status}.')
        return redirect('replacement_detail', pk=pk)

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
# 9. Stripe Connect (Receive Invoice Payments)
# ------------------------------------------------------------------

@owner_or_manager_required
def connect_setup(request):
    """POST /owner/payments/setup/ — start Stripe Connect onboarding."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role != 'owner':
        messages.error(request, 'Only the shop owner can set up payment processing.')
        return redirect('owner_dashboard')

    if request.method != 'POST':
        # GET — show the setup page with current status
        return render(request, 'saas/connect_setup.html', {
            'tenant': tenant,
            'membership': membership,
        })

    from apps.tenants.services.connect_service import ConnectService, ConnectError
    svc = ConnectService()

    if not svc.is_enabled():
        messages.error(request, 'Payment processing is not available at this time.')
        return redirect('billing_settings')

    try:
        return_url = request.build_absolute_uri('/owner/payments/setup/return/')
        refresh_url = request.build_absolute_uri('/owner/payments/setup/refresh/')
        onboarding_url = svc.create_connect_account(tenant, return_url, refresh_url)
        return redirect(onboarding_url)
    except ConnectError as e:
        messages.error(request, f'Failed to start payment setup: {e}')
        return redirect('billing_settings')


@owner_or_manager_required
def connect_return(request):
    """GET /owner/payments/setup/return/ — user returned from Stripe onboarding."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return redirect('owner_dashboard')

    from apps.tenants.services.connect_service import ConnectService, ConnectError
    svc = ConnectService()

    try:
        status = svc.sync_account_status(tenant)
        if status.get('charges_enabled'):
            messages.success(
                request,
                '✅ Payment processing is set up! Your customers can now pay invoices '
                'online and funds will go directly to your bank account.'
            )
        elif status.get('details_submitted'):
            messages.info(
                request,
                'Your information has been submitted. Stripe is reviewing your account — '
                'this usually takes 1-2 business days. We\'ll notify you when it\'s ready.'
            )
        else:
            messages.warning(
                request,
                'It looks like you didn\'t complete all the setup steps. '
                'Click "Set Up Payments" to continue where you left off.'
            )
    except ConnectError as e:
        messages.error(request, f'Error checking account status: {e}')

    return redirect('billing_settings')


@owner_or_manager_required
def connect_refresh(request):
    """GET /owner/payments/setup/refresh/ — onboarding link expired, create new one."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role != 'owner':
        return redirect('billing_settings')

    from apps.tenants.services.connect_service import ConnectService, ConnectError
    svc = ConnectService()

    try:
        return_url = request.build_absolute_uri('/owner/payments/setup/return/')
        refresh_url = request.build_absolute_uri('/owner/payments/setup/refresh/')
        onboarding_url = svc.create_connect_account(tenant, return_url, refresh_url)
        return redirect(onboarding_url)
    except ConnectError as e:
        messages.error(request, f'Failed to restart payment setup: {e}')
        return redirect('billing_settings')


@owner_or_manager_required
def connect_dashboard(request):
    """GET /owner/payments/dashboard/ — redirect to Stripe Express Dashboard."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return redirect('owner_dashboard')

    from apps.tenants.services.connect_service import ConnectService, ConnectError
    svc = ConnectService()

    try:
        dashboard_url = svc.create_login_link(tenant)
        return redirect(dashboard_url)
    except ConnectError as e:
        messages.error(request, f'Unable to access payment dashboard: {e}')
        return redirect('billing_settings')


# ------------------------------------------------------------------
# 10. Owner Settings
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

        if form_type == 'toggle_progressive_pricing':
            # Toggle progressive pricing at tenant level
            tenant.use_progressive_pricing = not tenant.use_progressive_pricing
            tenant.save(update_fields=['use_progressive_pricing'])
            if tenant.use_progressive_pricing:
                messages.success(request, 'Progressive pricing enabled. Repair prices decrease with each subsequent repair on a unit.')
            else:
                messages.success(request, 'Progressive pricing disabled. Every repair uses first-repair pricing.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'update_pricing_tiers':
            # Update pricing tier values
            from decimal import Decimal, InvalidOperation
            try:
                def _parse_price(field, default):
                    try:
                        val = request.POST.get(field, '')
                        return Decimal(val) if val else default
                    except (InvalidOperation, ValueError):
                        return default

                tenant.repair_price_1 = _parse_price('repair_price_1', Decimal('50.00'))
                tenant.repair_price_2 = _parse_price('repair_price_2', Decimal('40.00'))
                tenant.repair_price_3 = _parse_price('repair_price_3', Decimal('35.00'))
                tenant.repair_price_4 = _parse_price('repair_price_4', Decimal('30.00'))
                tenant.repair_price_5_plus = _parse_price('repair_price_5_plus', Decimal('25.00'))
                tenant.save(update_fields=[
                    'repair_price_1', 'repair_price_2', 'repair_price_3',
                    'repair_price_4', 'repair_price_5_plus'
                ])
                messages.success(request, 'Pricing tiers updated successfully.')
            except Exception as e:
                logger.error(f"Error updating pricing tiers: {e}")
                messages.error(request, 'Could not update pricing tiers.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'billing_location':
            # Update shop location + tax rate breakdown
            try:
                from decimal import Decimal, InvalidOperation
                from apps.billing.models import TaxRate as _TaxRate
                config = BillingConfig.get_for_tenant(tenant)
                config.company_address = request.POST.get('company_address', '').strip()
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
                cache.delete(f'billing_config_tax_{tenant.pk}')

                # CODE-103: sync TaxRate records so TaxService.is_tax_enabled() works.
                # TaxService checks TaxRate.objects.filter(tenant=tenant, is_active=True)
                # NOT BillingConfig.tax_enabled — so we MUST create/update a TaxRate row
                # or tax will never actually be applied to invoices even when the rate is set.
                if config.default_tax_rate > 0 and config.company_city and config.company_state:
                    # Reactivate a previously deactivated rate or create a new one.
                    existing = _TaxRate.objects.filter(
                        tenant=tenant,
                        city__iexact=config.company_city,
                        state__iexact=config.company_state,
                    ).first()
                    if existing:
                        existing.state_rate = config.state_tax_rate
                        existing.county_rate = config.county_tax_rate
                        existing.city_rate = config.city_tax_rate
                        existing.special_rate = config.special_tax_rate
                        existing.is_active = True
                        existing.save()
                    else:
                        _TaxRate.objects.create(
                            tenant=tenant,
                            city=config.company_city,
                            state=config.company_state,
                            state_rate=config.state_tax_rate,
                            county_rate=config.county_tax_rate,
                            city_rate=config.city_tax_rate,
                            special_rate=config.special_tax_rate,
                            is_active=True,
                        )
                elif config.default_tax_rate <= 0:
                    # No rate → deactivate all TaxRate rows for this tenant
                    _TaxRate.objects.filter(tenant=tenant).update(is_active=False)

                messages.success(request, f'Tax settings saved: {config.default_tax_rate}% in {config.company_city}, {config.company_state}')
            except Exception as e:
                logger.error(f"Error updating billing config: {e}")
                messages.error(request, 'Could not update tax settings.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'toggle_overdue_reminders':
            # Toggle overdue reminder emails
            try:
                config = BillingConfig.get_for_tenant(tenant)
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
                config = BillingConfig.get_for_tenant(tenant)
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
                config = BillingConfig.get_for_tenant(tenant)
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

        if form_type == 'email_templates':
            try:
                config = BillingConfig.get_for_tenant(tenant)
                config.invoice_email_template = request.POST.get('invoice_email_template', '').strip()
                config.reminder_email_template = request.POST.get('reminder_email_template', '').strip()
                config.save(update_fields=['invoice_email_template', 'reminder_email_template'])
                messages.success(request, 'Email templates saved.')
            except Exception as e:
                logger.error(f"Error saving email templates: {e}")
                messages.error(request, 'Could not save email templates.')
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

    # Tax rates were removed from owner_settings.html (billing tab now uses BillingConfig
    # component rates directly).  This query was fetching 349+ shared AR reference rows
    # on every settings page load for no reason — CODE-101.
    try:
        billing_config = BillingConfig.get_for_tenant(tenant)
        tax_enabled = billing_config.tax_enabled
    except Exception:
        billing_config = None
        tax_enabled = False

    # Active tab from query string
    active_tab = request.GET.get('tab', 'general')

    # UX-006: flag whether any customer has a primary tech set
    any_customer_has_primary_tech = Customer.objects.filter(
        tenant=tenant, primary_technician__isnull=False
    ).exists()

    # Overdue reminder day choices (checkboxes) and active selections
    reminder_day_choices = [
        ('3', '3 days'), ('7', '1 week'), ('14', '2 weeks'),
        ('21', '3 weeks'), ('30', '1 month'), ('45', '45 days'),
        ('60', '2 months'), ('90', '3 months'),
    ]
    active_reminder_days = []
    if billing_config and billing_config.overdue_reminder_days:
        active_reminder_days = [
            d.strip() for d in billing_config.overdue_reminder_days.split(',') if d.strip()
        ]

    # Batch invoicing: month day choices for dropdown
    batch_month_days = [{'value': d, 'label': f'{d}{"st" if d == 1 else "nd" if d == 2 else "rd" if d == 3 else "th"} of the month'} for d in range(1, 29)]

    context = {
        'tenant': tenant,
        'membership': membership,
        'members': members,
        'shop_join_url': shop_join_url,
        'customers': customers,
        'assignment_strategy_choices': tenant.ASSIGNMENT_STRATEGY_CHOICES,
        'tax_enabled': tax_enabled,
        'billing_config': billing_config,
        'active_tab': active_tab,
        'any_customer_has_primary_tech': any_customer_has_primary_tech,
        'reminder_day_choices': reminder_day_choices,
        'active_reminder_days': active_reminder_days,
        'batch_month_days': batch_month_days,
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

    # Usage limit check for technicians AND managers (both consume Technician seats)
    if role in ('technician', 'manager') and tenant:
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

    # Prevent inviting yourself (owner)
    if email == request.user.email.lower():
        messages.warning(request, "That's your own email. To add yourself as a technician, go to Team settings and use the 'Add myself' option.")
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
            return redirect('owner_settings')
        else:
            # Re-activate the membership with the new role
            existing.is_active = True
            existing.role = role
            existing.save()

            # Re-activate / update Technician record if they need tech portal access.
            # Without this, the re-added member's Technician.is_active stays False and
            # they cannot log in to the technician portal.  Also sync is_manager and
            # can_repair/can_replace to reflect the new role + ability checkboxes.
            with transaction.atomic():
                if role in ('technician', 'manager'):
                    from django.contrib.auth.models import Group
                    tech_group, _ = Group.objects.get_or_create(name='Technicians')
                    user.groups.add(tech_group)

                    # Update or create the Technician record for this tenant
                    Technician.objects.update_or_create(
                        user=user,
                        tenant=tenant,
                        defaults={
                            'is_active': True,
                            'is_manager': (role == 'manager'),
                            'can_repair': can_repair,
                            'can_replace': can_replace,
                        },
                    )
                else:
                    # Non-tech role: deactivate any lingering Technician record
                    try:
                        tech = Technician.objects.get(user=user, tenant=tenant)
                        tech.is_active = False
                        tech.save(update_fields=['is_active'])
                    except Technician.DoesNotExist:
                        pass

                # Create a fresh InviteToken so they get a password-reset link.
                # (Their old token may have expired or been consumed.)
                from apps.tenants.models import InviteToken
                invite_token = InviteToken(
                    tenant=tenant,
                    user=user,
                    role=role,
                    invited_by=request.user,
                )
                invite_token.save()

            invite_url = request.build_absolute_uri(f"/invite/{invite_token.token}/")

            # Try to send a fresh invite email so they can regain access
            email_sent = False
            try:
                from django.core.mail import send_mail
                from django.conf import settings

                inviter_name = request.user.get_full_name() or request.user.email
                subject = f"You've been re-added to {tenant.name} on RS Systems"
                body = (
                    f"Hi {user.first_name or user.email},\n\n"
                    f"{inviter_name} has re-added you to {tenant.name} as a {role}.\n\n"
                    f"Use this link to set your password and get back in:\n"
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
                logger.warning(f"Failed to send re-invite email to {email}: {e}")

            if email_sent:
                messages.success(request, f'{email} has been re-added to the team. A fresh invite email has been sent.')
            else:
                messages.success(
                    request,
                    f'{email} has been re-added to the team. '
                    f'Email could not be sent. Share this link manually: {invite_url}'
                )
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

            if not Technician.objects.filter(user=user, tenant=tenant).exists():
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
    from apps.customer_portal.models import CustomerUser as CustomerUserModel
    tenant = get_object_or_404(Tenant, slug=slug, is_active=True)

    # If the user is already authenticated, check if they already have a
    # customer record at this tenant.  If so, redirect them to the portal.
    # If not, create one automatically so they don't get stuck with a
    # "please log in" error that leads nowhere.  (CODE-093)
    if request.user.is_authenticated:
        existing_cu = CustomerUserModel.objects.filter(
            user=request.user, customer__tenant=tenant
        ).first()
        if existing_cu:
            request.session['tenant_id'] = tenant.id
            messages.info(request, f"You already have access to {tenant.name}.")
            return redirect('customer_dashboard')

        # Check if user already has a CustomerUser at a DIFFERENT shop.
        # CustomerUser.user is a OneToOneField — only one CustomerUser record
        # per Django User globally. Creating a second one would crash with
        # IntegrityError. (CODE-113)
        any_cu = CustomerUserModel.objects.filter(user=request.user).select_related('customer__tenant').first()
        if any_cu:
            other_shop = any_cu.customer.tenant.name if any_cu.customer and any_cu.customer.tenant else 'another shop'
            messages.warning(
                request,
                f"Your account is already linked to {other_shop}. "
                f"Customer portal accounts are tied to a single shop. "
                f"To access {tenant.name}'s portal, please ask the shop admin "
                f"to invite you using a different email address."
            )
            return redirect('customer_dashboard')

        # Authenticated user, no customer record at any shop — create one automatically
        with transaction.atomic():
            customer_name = (
                request.user.get_full_name() or request.user.email
            )
            # Avoid duplicate customer names within this tenant
            if Customer.objects.filter(tenant=tenant, name=customer_name).exists():
                customer_name = f"{customer_name} ({request.user.email})"
            customer = Customer.objects.create(
                tenant=tenant,
                name=customer_name,
                customer_type='RETAIL',
                email=request.user.email,
            )
            CustomerUserModel.objects.create(
                user=request.user,
                customer=customer,
                is_primary_contact=True,
            )
            TenantMembership.objects.get_or_create(
                tenant=tenant,
                user=request.user,
                defaults={'role': 'viewer'},
            )
        request.session['tenant_id'] = tenant.id
        messages.success(request, f"Welcome to {tenant.name}! Your portal account is ready.")
        return redirect('customer_dashboard')

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

        # Check email uniqueness.  Note: if the user finds this error, they
        # should log in at /login/?next=/join/<slug>/ — after login the view
        # will detect their existing account and create a CustomerUser record
        # automatically (see the is_authenticated branch at the top of this view).
        if email and User.objects.filter(email=email).exists():
            errors.append(
                'An account with this email already exists. '
                'Please log in to access this portal.'
            )

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

            # 6. Send verification email (fails silently)
            _send_verification_email(request, user)

            messages.success(request, f'Welcome to {tenant.name}! Your portal account is ready. Check your email to verify your address.')
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

            # IMPORTANT: Technician.user is a OneToOneField — a user can only have
            # one Technician record across ALL tenants.  We must scope the lookup
            # to THIS tenant to avoid:
            #   (a) silently rewriting another tenant's Technician.tenant to ours, or
            #   (b) updating another tenant's is_manager/can_repair flags.
            # If the user already has a Technician record for a *different* tenant,
            # we leave it untouched and log a warning; the admin should resolve the
            # cross-tenant membership manually.
            try:
                tech = Technician.objects.get(user=target.user, tenant=tenant)
                # Existing record for this tenant — update in place
                tech.is_manager = (new_role == 'manager')
                tech.can_repair = can_repair
                tech.can_replace = can_replace
                tech.is_active = True
                tech.save()
            except Technician.DoesNotExist:
                # No record for this tenant yet.  Check if user has a record for
                # another tenant (cross-tenant shared user edge case).
                foreign_tech = Technician.objects.filter(user=target.user).exclude(tenant=tenant).first()
                if foreign_tech:
                    # User is already a Technician at a different shop.
                    # Do NOT steal that record — log and skip creation so we don't
                    # corrupt the other tenant's data.
                    logger.warning(
                        "update_team_member: user %s already has a Technician record "
                        "for tenant %s (id=%s). Skipping Technician creation for tenant %s.",
                        target.user_id,
                        foreign_tech.tenant_id,
                        foreign_tech.id,
                        tenant.id,
                    )
                else:
                    Technician.objects.create(
                        user=target.user,
                        tenant=tenant,
                        is_manager=(new_role == 'manager'),
                        is_active=True,
                        can_repair=can_repair,
                        can_replace=can_replace,
                    )
        elif old_role in ('technician', 'manager') and new_role not in ('technician', 'manager'):
            # Deactivate technician record if moving away from tech/manager.
            # Scope to THIS tenant so we don't touch another shop's record.
            try:
                tech = Technician.objects.get(user=target.user, tenant=tenant)
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
        status__in=['SENT', 'PARTIAL'],
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

    # Uninvoiced completed repairs per customer — computed in bulk to avoid N+1.
    # Strategy:
    #   1. Fetch all invoiced repair IDs for this tenant in one query.
    #   2. Fetch all uninvoiced completed repairs for this tenant in one query.
    #   3. Group in Python by customer_id.
    from django.db.models import Sum as _Sum
    from apps.billing.models import InvoiceLineItem as _ILI

    _invoiced_repair_ids = set(
        _ILI.objects.filter(
            repair__isnull=False,
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID'],
        ).values_list('repair_id', flat=True)
    )

    # All uninvoiced completed repairs for this tenant, excluding skip_invoicing
    _uninvoiced_qs = (
        Repair.objects.filter(
            tenant=tenant,
            queue_status='COMPLETED',
            skip_invoicing=False,
        )
        .exclude(id__in=_invoiced_repair_ids)
        .values('customer_id', 'cost')
    )

    # Group by customer_id
    _by_customer: dict = {}
    for row in _uninvoiced_qs:
        cid = row['customer_id']
        cost = row['cost'] or 0
        if cid not in _by_customer:
            _by_customer[cid] = {'count': 0, 'total': 0}
        _by_customer[cid]['count'] += 1
        _by_customer[cid]['total'] += cost

    uninvoiced_customers = []
    for cust in customers:
        info = _by_customer.get(cust.id)
        if info and info['count'] > 0:
            uninvoiced_customers.append({
                'customer': cust,
                'count': info['count'],
                'total': info['total'],
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

    # PDF download URL — use model method so bucket name is read from settings,
    # not hardcoded.  Works correctly in dev/prod/staging.
    pdf_url = invoice.get_pdf_url()

    # Resolve recipient email for send confirmation preview (CODE-112)
    recipient_email = None
    try:
        prefs = invoice.customer.repair_preferences
        recipient_email = prefs.billing_email or invoice.customer.email
    except Exception:
        recipient_email = invoice.customer.email

    # Render saved reminder template if one exists (CODE-113)
    rendered_reminder_default = ''
    try:
        config = BillingConfig.get_for_tenant(tenant)
        if config.reminder_email_template:
            from apps.billing.services.reminder_service import ReminderService
            svc = ReminderService(tenant=tenant)
            rendered_reminder_default = svc._render_template(config.reminder_email_template, invoice)
    except Exception:
        pass

    context = {
        'tenant': tenant,
        'invoice': invoice,
        'line_items': line_items,
        'payments': payments,
        'payment_methods': payment_methods,
        'pdf_url': pdf_url,
        'recipient_email': recipient_email,
        'rendered_reminder_default': rendered_reminder_default,
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
    # NOTE: The amount_due check must happen INSIDE the transaction with a row-level
    # lock (select_for_update) to prevent a TOCTOU race where two concurrent payment
    # submissions both read the same stale amount_due and both pass validation,
    # resulting in overpayment. (CODE-056)
    try:
        with transaction.atomic():
            # Re-read the invoice under an exclusive row lock so our amount_due
            # check reflects any concurrent payment that may have just committed.
            invoice_locked = Invoice.objects.select_for_update().get(pk=invoice.id)

            # Re-check status inside the lock (it could have changed concurrently)
            if invoice_locked.status in ('PAID', 'CANCELLED'):
                raise ValueError(
                    f'Cannot record payment — invoice is {invoice_locked.get_status_display()}.'
                )

            # Validate amount against the fresh, locked amount_due
            if amount > invoice_locked.amount_due:
                raise ValueError(
                    f'Payment amount (${amount}) exceeds the remaining balance '
                    f'(${invoice_locked.amount_due}).'
                )

            payment = Payment.objects.create(
                invoice=invoice_locked,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes,
                recorded_by=request.user,
            )
            # Payment.save() already calls _update_invoice_totals() with its own lock

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

    except ValueError as e:
        # Validation error raised inside the transaction (race condition guard,
        # overpayment check, status check).  Surface the specific message to the user.
        messages.error(request, str(e))
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
    """POST /owner/tax-rates/toggle/ — enable/disable tax for this tenant."""
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=billing')

    tenant, _membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('/owner/settings/?tab=billing')

    try:
        from django.core.cache import cache
        from apps.billing.models import TaxRate

        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = not config.tax_enabled
        config.save()
        cache.delete(f'billing_config_tax_{tenant.pk}')

        # CODE-099: Sync TaxRate.is_active with the new tax_enabled state.
        # TaxService.is_tax_enabled() for tenant-aware paths checks
        # TaxRate.objects.filter(tenant=tenant, is_active=True).exists() —
        # it does NOT read BillingConfig.tax_enabled.  Without this sync,
        # toggling tax off via this button leaves active TaxRate records so
        # tax still gets charged on every invoice.  Toggling back on would
        # then show no rates active (all still deactivated from the first
        # disable), so it also needs to reactivate existing rates.
        if not config.tax_enabled:
            TaxRate.objects.filter(tenant=tenant).update(is_active=False)
        else:
            # Re-enable all rates for this tenant when tax is turned back on.
            # The owner can fine-tune individual rates on the tax rates page.
            TaxRate.objects.filter(tenant=tenant).update(is_active=True)

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
        # Resolve recipient email
        recipient = None
        try:
            prefs = invoice.customer.repair_preferences
            recipient = prefs.billing_email or invoice.customer.email
        except Exception:
            recipient = invoice.customer.email

        # CODE-112: Block send entirely if no email on file
        if not recipient:
            messages.error(
                request,
                f'Cannot send invoice — no email address on file for {invoice.customer.name}. '
                f'Add an email in the customer\'s settings first.'
            )
            return redirect('owner_invoice_detail', invoice_id=invoice.id)

        # Attempt email delivery
        email_sent = False
        try:
            from apps.billing.services.invoice_email_service import InvoiceEmailService
            email_service = InvoiceEmailService(tenant=tenant)

            repair_ids = list(invoice.line_items.exclude(repair_id__isnull=True).values_list('repair_id', flat=True))

            success, msg = email_service.send_invoice_email(
                customer_id=invoice.customer.id,
                recipient_email=recipient,
                repair_ids=repair_ids if repair_ids else None,
            )
            email_sent = success
            if not success:
                logger.warning(f"Invoice email failed for {invoice.invoice_number}: {msg}")
        except Exception as e:
            logger.warning(f"Could not email invoice {invoice.invoice_number}: {e}")

        # CODE-112: Only mark SENT if email actually delivered.
        # If email fails, leave as DRAFT so the owner knows it didn't go out.
        if email_sent:
            invoice.status = 'SENT'
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=['status', 'sent_at'])
            messages.success(request, f'Invoice {invoice.invoice_number} sent to {recipient}.')
        else:
            messages.error(
                request,
                f'Invoice {invoice.invoice_number} could NOT be sent — email delivery to {recipient} failed. '
                f'The invoice remains as a draft. Please check the email address and try again.'
            )

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
        email_service = InvoiceEmailService(tenant=tenant)
        
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

    # CODE-113: Accept optional custom message from editable textarea
    custom_message = request.POST.get('custom_message', '').strip()

    try:
        from apps.billing.services.reminder_service import ReminderService
        reminder_service = ReminderService(tenant=tenant)
        
        # Determine reminder type based on invoice status
        if invoice.status == 'OVERDUE' or (invoice.due_date and invoice.due_date < timezone.now().date()):
            reminder_type = 'overdue'
        else:
            reminder_type = 'due_soon'
        
        result = reminder_service.send_reminder(
            invoice, reminder_type,
            custom_body=custom_message if custom_message else None,
        )
        
        if result.get('success'):
            messages.success(request, f'Payment reminder sent to {invoice.customer.email}.')
        else:
            messages.error(request, f'Failed to send reminder: {result.get("error", "Unknown error")}')
            
    except Exception as e:
        logger.error(f"Error sending reminder for invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'An error occurred while sending the reminder.')

    return redirect('owner_invoice_detail', invoice_id=invoice.id)


# ---------------------------------------------------------------------------
# Subscription Blocked View (role-aware)
# ---------------------------------------------------------------------------

@login_required
def subscription_blocked_view(request):
    """
    /subscription-blocked/

    Role-aware page shown when a tenant's subscription has expired and the
    grace period has ended. Content varies by user role:
    - Owners/Managers: upgrade prompt with link to billing
    - Technicians: contact owner message
    - Customers: contact shop message
    """
    from common.auth import get_user_role
    from apps.tenants.models import TenantMembership

    tenant = getattr(request, 'tenant', None)
    user_role = get_user_role(request.user, tenant)

    context = {
        'tenant': tenant,
        'user_role': user_role,
    }

    if tenant:
        if user_role in ('owner', 'manager'):
            # Show owner name/email and billing link
            context['owner'] = tenant.owner
        elif user_role == 'technician':
            # Show owner contact info
            context['owner'] = tenant.owner
        else:
            # Customer — show shop contact info
            context['shop_name'] = tenant.name
            context['shop_phone'] = tenant.business_phone
            context['shop_email'] = tenant.business_email

    return render(request, 'saas/subscription_blocked.html', context)


# ------------------------------------------------------------------
# 13. Billing Phase 6 — Aging Report, Statement of Account
# ------------------------------------------------------------------

@owner_or_manager_required
def owner_aging_report_json(request):
    """GET /owner/billing/aging/ — AR aging data as JSON."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        from django.http import JsonResponse
        return JsonResponse({'error': 'No tenant'}, status=403)

    from apps.billing.tasks import generate_aging_report
    from django.http import JsonResponse

    reports = generate_aging_report(tenant_id=tenant.id)
    data = reports.get(tenant.slug, {
        'buckets': {k: {'count': 0, 'total': 0.0} for k in ['current', '1_30', '31_60', '61_90', '90_plus']},
        'grand_total': 0.0,
        'generated_at': '',
    })
    return JsonResponse(data)


@owner_or_manager_required
def owner_aging_report_csv(request):
    """GET /owner/billing/aging/export/ — CSV download of AR aging data."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    import csv
    from django.http import HttpResponse
    from django.utils import timezone
    from apps.billing.models import Invoice

    today = timezone.now().date()
    outstanding = Invoice.objects.filter(
        customer__tenant=tenant,
        status__in=['SENT', 'PARTIAL', 'OVERDUE'],
    ).select_related('customer').order_by('due_date')

    from decimal import Decimal

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{tenant.name.replace(" ", "_")}_AR_Aging_{today}.csv"'
    writer = csv.writer(response)

    # Header with report info
    writer.writerow([f'AR Aging Report — {tenant.name}'])
    writer.writerow([f'Generated: {today.strftime("%B %d, %Y")}'])
    writer.writerow([])

    # Column headers
    writer.writerow([
        'Customer', 'Invoice #', 'Invoice Date', 'Due Date',
        'Total', 'Paid', 'Amount Due', 'Status',
        'Days Overdue', 'Aging Bucket', 'Customer Email', 'Customer Phone',
    ])

    bucket_label = {
        'current': 'Current',
        '1_30': '1-30 Days',
        '31_60': '31-60 Days',
        '61_90': '61-90 Days',
        '90_plus': '90+ Days',
    }

    # Track bucket totals
    bucket_totals = {k: Decimal('0.00') for k in bucket_label}
    grand_total = Decimal('0.00')

    for inv in outstanding:
        days_old = (today - inv.due_date).days if inv.due_date else 0
        if days_old <= 0:
            bucket = 'current'
        elif days_old <= 30:
            bucket = '1_30'
        elif days_old <= 60:
            bucket = '31_60'
        elif days_old <= 90:
            bucket = '61_90'
        else:
            bucket = '90_plus'

        amount_due = inv.amount_due
        bucket_totals[bucket] += amount_due
        grand_total += amount_due

        writer.writerow([
            inv.customer.name,
            inv.invoice_number,
            inv.invoice_date.strftime('%m/%d/%Y'),
            inv.due_date.strftime('%m/%d/%Y') if inv.due_date else '',
            f'{float(inv.total):.2f}',
            f'{float(inv.amount_paid):.2f}',
            f'{float(amount_due):.2f}',
            inv.get_status_display(),
            max(0, days_old),
            bucket_label[bucket],
            inv.customer.email or '',
            inv.customer.phone or '',
        ])

    # Summary section
    writer.writerow([])
    writer.writerow(['SUMMARY'])
    for key, label in bucket_label.items():
        writer.writerow([label, '', '', '', '', '', f'{float(bucket_totals[key]):.2f}'])
    writer.writerow([])
    writer.writerow(['Total Outstanding', '', '', '', '', '', f'{float(grand_total):.2f}'])

    return response


@owner_or_manager_required
def owner_customer_statement(request, customer_id):
    """GET /owner/customers/<id>/statement/ — Statement of Account for a customer."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    from django.shortcuts import get_object_or_404
    from decimal import Decimal

    customer = get_object_or_404(Customer, id=customer_id, tenant=tenant)

    # All invoices for this customer, oldest first
    invoices = Invoice.objects.filter(
        customer=customer,
    ).prefetch_related('payments').order_by('invoice_date', 'created_at')

    # All payments for this customer, chronological
    payments = Payment.objects.filter(
        invoice__customer=customer,
    ).select_related('invoice').order_by('payment_date', 'created_at')

    # Build a unified timeline for running balance
    events = []
    for inv in invoices:
        events.append({
            'type': 'invoice',
            'date': inv.invoice_date,
            'description': f'Invoice {inv.invoice_number}',
            'debit': inv.total,
            'credit': Decimal('0.00'),
            'invoice': inv,
            'payment': None,
        })
    for pmt in payments:
        events.append({
            'type': 'payment',
            'date': pmt.payment_date,
            'description': f'Payment — {pmt.get_payment_method_display()}' + (f' #{pmt.reference_number}' if pmt.reference_number else ''),
            'debit': Decimal('0.00'),
            'credit': pmt.amount,
            'invoice': pmt.invoice,
            'payment': pmt,
        })

    events.sort(key=lambda e: (e['date'], e['type']))  # invoices before payments same day

    running_balance = Decimal('0.00')
    for ev in events:
        running_balance += ev['debit'] - ev['credit']
        ev['running_balance'] = running_balance

    # Summary stats
    total_invoiced = sum(inv.total for inv in invoices)
    total_paid = sum(pmt.amount for pmt in payments)
    balance_due = total_invoiced - total_paid

    context = {
        'tenant': tenant,
        'customer': customer,
        'events': events,
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'balance_due': balance_due,
        'statement_date': timezone.now().date(),
    }
    return render(request, 'saas/customer_statement.html', context)


# ------------------------------------------------------------------
# 14. Owner Setup — Unified "Configure Your Shop" Page
# ------------------------------------------------------------------

DEFAULT_VISCOSITY_RULES = [
    {
        'name': 'Cold Glass',
        'min_temperature': None,
        'max_temperature': 59.9,
        'recommended_viscosity': 'Low',
        'suggestion_text': (
            'Use low viscosity resin. Allow extra cure time in cold conditions. '
            'Consider warming the glass with a heat gun before injection for best results.'
        ),
        'badge_color': 'blue',
        'display_order': 1,
    },
    {
        'name': 'Cool Glass',
        'min_temperature': 60.0,
        'max_temperature': 74.9,
        'recommended_viscosity': 'Low-Medium',
        'suggestion_text': (
            'Low to medium viscosity resin. Standard injection pressure. '
            'Good conditions for most repairs.'
        ),
        'badge_color': 'green',
        'display_order': 2,
    },
    {
        'name': 'Ideal Conditions',
        'min_temperature': 75.0,
        'max_temperature': 95.0,
        'recommended_viscosity': 'Medium',
        'suggestion_text': (
            'Medium viscosity resin. Ideal repair conditions \u2014 standard cure time and best penetration.'
        ),
        'badge_color': 'green',
        'display_order': 3,
    },
    {
        'name': 'Warm Glass',
        'min_temperature': 95.1,
        'max_temperature': 105.0,
        'recommended_viscosity': 'High',
        'suggestion_text': (
            'Use high viscosity resin. Work quickly \u2014 resin cures faster in heat. '
            'Shade the repair area if possible.'
        ),
        'badge_color': 'orange',
        'display_order': 4,
    },
    {
        'name': 'Hot Glass \u2014 Cool First',
        'min_temperature': 105.1,
        'max_temperature': None,
        'recommended_viscosity': 'Cool Glass First',
        'suggestion_text': (
            'Glass is too hot for optimal repair. Cool the windshield first \u2014 park in shade, '
            'run A/C, or use cooling spray. Once below 105\u00b0F, use high viscosity resin.'
        ),
        'badge_color': 'red',
        'display_order': 5,
    },
]


def _setup_completion(tenant):
    """Return completion info for each of the 6 setup sections."""
    from apps.billing.models import TaxRate, BillingConfig
    from apps.technician_portal.models import ViscosityRecommendation
    from decimal import Decimal

    try:
        billing_config = BillingConfig.get_for_tenant(tenant)
    except Exception:
        billing_config = None

    has_business_info = bool(tenant.business_phone and tenant.business_email)
    has_tax = TaxRate.objects.filter(tenant=tenant, is_active=True).exists()
    has_viscosity = ViscosityRecommendation.objects.filter(tenant=tenant, is_active=True).exists()
    has_billing = bool(billing_config and billing_config.default_payment_terms)

    return {
        'business_info': has_business_info,
        'pricing': True,  # always has defaults
        'tax': has_tax,
        'billing': has_billing,
        'viscosity': has_viscosity,
        'assignment': True,  # always has default
        'critical_complete': has_business_info and has_billing,
        'all_complete': has_business_info and has_tax and has_billing and has_viscosity,
        'configured_count': sum([
            has_business_info, True, has_tax, has_billing, has_viscosity, True
        ]),
    }


@owner_or_manager_required
def owner_setup_view(request):
    """GET /owner/setup/ — unified shop configuration accordion page."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found. Please complete signup first.')
        return redirect('signup')
    if not membership or membership.role not in ('owner', 'manager'):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Access denied.')

    from apps.billing.models import TaxRate, BillingConfig
    from apps.technician_portal.models import ViscosityRecommendation

    try:
        billing_config = BillingConfig.get_for_tenant(tenant)
    except Exception:
        billing_config = None

    tax_rates = TaxRate.objects.filter(tenant=tenant, is_active=True).order_by('state', 'city')
    viscosity_rules = ViscosityRecommendation.objects.filter(tenant=tenant, is_active=True).order_by('display_order')

    completion = _setup_completion(tenant)

    # Overdue reminder day choices (checkboxes) and active selections
    reminder_day_choices = [
        ('3', '3 days'), ('7', '1 week'), ('14', '2 weeks'),
        ('21', '3 weeks'), ('30', '1 month'), ('45', '45 days'),
        ('60', '2 months'), ('90', '3 months'),
    ]
    active_reminder_days = []
    if billing_config and billing_config.overdue_reminder_days:
        active_reminder_days = [
            d.strip() for d in billing_config.overdue_reminder_days.split(',') if d.strip()
        ]

    context = {
        'tenant': tenant,
        'membership': membership,
        'billing_config': billing_config,
        'tax_rates': tax_rates,
        'viscosity_rules': viscosity_rules,
        'completion': completion,
        'assignment_strategy_choices': tenant.ASSIGNMENT_STRATEGY_CHOICES,
        'reminder_day_choices': reminder_day_choices,
        'active_reminder_days': active_reminder_days,
    }
    return render(request, 'saas/owner_setup.html', context)


@owner_or_manager_required
@require_POST
def owner_setup_save_business(request):
    """POST /owner/setup/save/business/ — AJAX save business info."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role not in ('owner', 'manager'):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        tenant.name = request.POST.get('business_name', tenant.name).strip() or tenant.name
        tenant.business_phone = request.POST.get('business_phone', '').strip()
        tenant.business_email = request.POST.get('business_email', '').strip()
        tenant.business_address = request.POST.get('business_address', '').strip()
        logo_url = request.POST.get('logo_url', '').strip()
        if logo_url:
            # Store logo URL in a note field if no logo_url field exists
            pass
        tenant.save(update_fields=['name', 'business_phone', 'business_email', 'business_address'])
        return JsonResponse({'success': True, 'message': 'Business info saved!'})
    except Exception as e:
        logger.error(f"Setup save business error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@owner_or_manager_required
@require_POST
def owner_setup_save_pricing(request):
    """POST /owner/setup/save/pricing/ — AJAX save pricing structure."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role not in ('owner', 'manager'):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        from decimal import Decimal, InvalidOperation

        def _parse(field, default):
            try:
                val = request.POST.get(field, '').strip()
                return Decimal(val) if val else default
            except (InvalidOperation, ValueError):
                return default

        pricing_model = request.POST.get('pricing_model', 'progressive')
        tenant.use_progressive_pricing = (pricing_model == 'progressive')
        tenant.repair_price_1 = _parse('repair_price_1', Decimal('50.00'))
        tenant.repair_price_2 = _parse('repair_price_2', Decimal('40.00'))
        tenant.repair_price_3 = _parse('repair_price_3', Decimal('35.00'))
        tenant.repair_price_4 = _parse('repair_price_4', Decimal('30.00'))
        tenant.repair_price_5_plus = _parse('repair_price_5_plus', Decimal('25.00'))
        tenant.save(update_fields=[
            'use_progressive_pricing',
            'repair_price_1', 'repair_price_2', 'repair_price_3',
            'repair_price_4', 'repair_price_5_plus',
        ])
        return JsonResponse({'success': True, 'message': 'Pricing saved!'})
    except Exception as e:
        logger.error(f"Setup save pricing error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@owner_or_manager_required
@require_POST
def owner_setup_save_tax(request):
    """POST /owner/setup/save/tax/ — AJAX save tax rates."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role not in ('owner', 'manager'):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        from decimal import Decimal, InvalidOperation
        from apps.billing.models import TaxRate, BillingConfig

        tax_enabled = request.POST.get('tax_enabled') == '1'

        def _dec(field, default='0'):
            try:
                return Decimal(request.POST.get(field, default) or default)
            except (InvalidOperation, ValueError):
                return Decimal(default)

        state_rate = _dec('state_rate')
        county_rate = _dec('county_rate')
        city_rate = _dec('city_rate')
        special_rate = _dec('special_rate')
        total = state_rate + county_rate + city_rate + special_rate

        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', 'AR').strip().upper()

        # Update tenant's BillingConfig tax enabled flag
        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = tax_enabled
        if tax_enabled and total > 0:
            config.state_tax_rate = state_rate
            config.county_tax_rate = county_rate
            config.city_tax_rate = city_rate
            config.special_tax_rate = special_rate
            config.default_tax_rate = total
            config.save()
        else:
            config.save(update_fields=['tax_enabled'])

        # Deactivate all TaxRates when tax is disabled.
        # TaxService.calculate_tax() determines "tax enabled" by checking
        # TaxRate.objects.filter(tenant=tenant, is_active=True).exists() — it
        # does NOT consult BillingConfig.tax_enabled for tenant-aware paths.
        # Without this, disabling tax via setup leaves active TaxRate records
        # so tax keeps being charged on every invoice even when the owner
        # toggled it off. (CODE-099)
        if not tax_enabled:
            TaxRate.objects.filter(tenant=tenant).update(is_active=False)

        # Create or update tenant TaxRate if enabled and we have location
        if tax_enabled and total > 0 and city and state:
            # Include is_active=False rows in the lookup: if the owner is
            # re-enabling a previously deactivated rate we reactivate it
            # rather than creating a duplicate entry.
            existing = TaxRate.objects.filter(tenant=tenant, city__iexact=city, state__iexact=state).first()
            if existing:
                existing.state_rate = state_rate
                existing.county_rate = county_rate
                existing.city_rate = city_rate
                existing.special_rate = special_rate
                existing.is_active = True  # re-activate if it was deactivated
                existing.save()
            else:
                TaxRate.objects.create(
                    tenant=tenant,
                    city=city,
                    state=state,
                    state_rate=state_rate,
                    county_rate=county_rate,
                    city_rate=city_rate,
                    special_rate=special_rate,
                    is_active=True,
                )

        return JsonResponse({'success': True, 'message': 'Tax settings saved!'})
    except Exception as e:
        logger.error(f"Setup save tax error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@owner_or_manager_required
@require_POST
def owner_setup_save_billing(request):
    """POST /owner/setup/save/billing/ — AJAX save billing & invoicing config."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role not in ('owner', 'manager'):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        from apps.billing.models import BillingConfig

        config = BillingConfig.get_for_tenant(tenant)
        config.default_payment_terms = request.POST.get('default_payment_terms', 'COD')
        config.overdue_reminder_enabled = request.POST.get('overdue_reminder_enabled') == '1'
        config.overdue_reminder_days = request.POST.get('overdue_reminder_days', '7,14,30').strip()
        config.batch_invoice_frequency = request.POST.get('batch_invoice_frequency', 'disabled')
        try:
            config.batch_invoice_day = int(request.POST.get('batch_invoice_day', '1'))
        except (ValueError, TypeError):
            config.batch_invoice_day = 1
        config.save(update_fields=[
            'default_payment_terms', 'overdue_reminder_enabled', 'overdue_reminder_days',
            'batch_invoice_frequency', 'batch_invoice_day',
        ])

        # Auto-email invoices is on the Tenant model
        auto_email = request.POST.get('auto_email_invoices') == '1'
        tenant.auto_invoice_enabled = auto_email
        tenant.save(update_fields=['auto_invoice_enabled'])

        return JsonResponse({'success': True, 'message': 'Billing settings saved!'})
    except Exception as e:
        logger.error(f"Setup save billing error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@owner_or_manager_required
@require_POST
def owner_setup_save_viscosity(request):
    """POST /owner/setup/save/viscosity/ — AJAX toggle viscosity and auto-populate defaults."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role not in ('owner', 'manager'):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        from apps.technician_portal.models import ViscosityRecommendation
        from decimal import Decimal

        enable = request.POST.get('enable_viscosity') == '1'

        if enable:
            # Auto-populate defaults if none exist
            if not ViscosityRecommendation.objects.filter(tenant=tenant).exists():
                for rule_data in DEFAULT_VISCOSITY_RULES:
                    min_temp = Decimal(str(rule_data['min_temperature'])) if rule_data['min_temperature'] is not None else None
                    max_temp = Decimal(str(rule_data['max_temperature'])) if rule_data['max_temperature'] is not None else None
                    ViscosityRecommendation.objects.create(
                        tenant=tenant,
                        name=rule_data['name'],
                        min_temperature=min_temp,
                        max_temperature=max_temp,
                        recommended_viscosity=rule_data['recommended_viscosity'],
                        suggestion_text=rule_data['suggestion_text'],
                        badge_color=rule_data['badge_color'],
                        display_order=rule_data['display_order'],
                        is_active=True,
                    )
            else:
                # Re-activate existing rules
                ViscosityRecommendation.objects.filter(tenant=tenant).update(is_active=True)
            message = 'Viscosity recommendations enabled with default rules!'
        else:
            # Deactivate all rules for this tenant
            ViscosityRecommendation.objects.filter(tenant=tenant).update(is_active=False)
            message = 'Viscosity recommendations disabled.'

        return JsonResponse({'success': True, 'message': message, 'enabled': enable})
    except Exception as e:
        logger.error(f"Setup save viscosity error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def owner_confirm_email_verification(request, uidb64, token):
    """
    GET /owner/verify-email/<uidb64>/<token>/

    Process email verification token for a shop owner.  No login required —
    the link is sent immediately after signup, before the session is fully
    established on all devices.  The token itself authenticates the action.

    Unlike customer/technician verification there is no email_verified flag
    to persist for owners (email verification doesn't gate any owner feature).
    The view just validates the token and shows a success (or error) message,
    then redirects to the owner dashboard (or signup page if not logged in).
    """
    from django.utils.http import urlsafe_base64_decode

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        messages.success(request, "Email verified successfully! Welcome to RS Systems.")
    else:
        messages.error(request, "Invalid or expired verification link.")

    if request.user.is_authenticated:
        return redirect('owner_dashboard')
    return redirect('signup')


@owner_or_manager_required
@require_POST
def owner_setup_save_assignment(request):
    """POST /owner/setup/save/assignment/ — AJAX save repair assignment strategy."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership or membership.role not in ('owner', 'manager'):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        strategy = request.POST.get('assignment_strategy', 'primary_first')
        valid = [c[0] for c in tenant.ASSIGNMENT_STRATEGY_CHOICES]
        if strategy not in valid:
            return JsonResponse({'success': False, 'error': 'Invalid strategy.'}, status=400)
        tenant.assignment_strategy = strategy
        tenant.save(update_fields=['assignment_strategy'])
        return JsonResponse({'success': True, 'message': 'Assignment strategy saved!'})
    except Exception as e:
        logger.error(f"Setup save assignment error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =====================================================================
# Invoice Bulk Actions & PDF Download (CODE-112)
# =====================================================================

@owner_or_manager_required
@require_POST
def owner_invoice_bulk_action(request):
    """POST /owner/invoices/bulk/ — bulk mark-paid or delete invoices."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No shop found.'}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    action = data.get('action')
    invoice_ids = data.get('invoice_ids', [])

    if not invoice_ids:
        return JsonResponse({'success': False, 'error': 'No invoices selected.'}, status=400)

    # Always scope to tenant
    invoices = Invoice.objects.filter(id__in=invoice_ids, customer__tenant=tenant)

    if action == 'mark_paid':
        updated = 0
        for inv in invoices.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE', 'DRAFT']):
            inv.amount_paid = inv.total
            inv.status = 'PAID'
            inv.save(update_fields=['amount_paid', 'status'])
            updated += 1
        return JsonResponse({
            'success': True,
            'message': f'{updated} invoice(s) marked as paid.',
        })

    elif action == 'delete':
        # Only allow deleting DRAFT invoices
        drafts = invoices.filter(status='DRAFT')
        deleted_count = drafts.count()
        skipped = invoices.exclude(status='DRAFT').count()
        drafts.delete()
        msg = f'{deleted_count} draft invoice(s) deleted.'
        if skipped:
            msg += f' {skipped} non-draft invoice(s) were skipped.'
        return JsonResponse({'success': True, 'message': msg})

    else:
        return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)


@owner_or_manager_required
def owner_invoice_pdf(request, invoice_id):
    """GET /owner/invoices/<id>/pdf/ — generate and download invoice PDF on demand."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)

    try:
        from apps.billing.services.invoice_service import InvoiceService

        service = InvoiceService(tenant=tenant)
        repair_ids = list(
            invoice.line_items
            .exclude(repair_id__isnull=True)
            .values_list('repair_id', flat=True)
        )

        pdf_bytes, invoice_data = service.generate_invoice(
            customer_id=invoice.customer.id,
            repair_ids=repair_ids if repair_ids else None,
        )

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response

    except Exception as e:
        logger.error(f"PDF generation failed for invoice {invoice.invoice_number}: {e}")
        messages.error(request, f'Could not generate PDF: {e}')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)
