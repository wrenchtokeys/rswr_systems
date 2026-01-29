"""
SaaS UI Views

Template-based views for signup, onboarding, owner dashboard,
pricing, billing settings, and the replacement form.

Author: Amelia (Clawdbot AI)
"""

import logging
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.usage_service import UsageService
from apps.tenants.services.subscription_service import SubscriptionService, SubscriptionError
from apps.technician_portal.models import Repair, Replacement, Technician
from core.models import Customer

from .forms import (
    SignupForm,
    OnboardingBusinessForm,
    OnboardingTechnicianForm,
    OnboardingCustomerForm,
    ReplacementForm,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _generate_unique_slug(business_name):
    base_slug = slugify(business_name)[:50]
    slug = base_slug
    counter = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def _get_owner_tenant(request):
    """Return (tenant, membership) for the current user, or (None, None)."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        # Try to find one
        membership = (
            TenantMembership.objects
            .filter(user=request.user, is_active=True, role='owner')
            .select_related('tenant')
            .first()
        )
        if membership:
            return membership.tenant, membership
        return None, None
    membership = TenantMembership.objects.filter(
        user=request.user, tenant=tenant, is_active=True
    ).first()
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
                with transaction.atomic():
                    cd = form.cleaned_data
                    email = cd['email']
                    username = email[:150]

                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=cd['password'],
                        first_name=cd['first_name'],
                        last_name=cd['last_name'],
                    )

                    slug = _generate_unique_slug(cd['business_name'])
                    trial_plan = SubscriptionPlan.objects.filter(
                        slug='trial', is_active=True
                    ).first()

                    tenant = Tenant.objects.create(
                        name=cd['business_name'],
                        slug=slug,
                        subdomain=slug,
                        owner=user,
                        business_email=email,
                        plan='trial',
                        subscription_plan=trial_plan,
                        subscription_status='trialing',
                        trial_started_at=timezone.now(),
                    )

                    TenantMembership.objects.create(
                        tenant=tenant, user=user, role='owner',
                    )

                # Log the user in
                user = authenticate(
                    request, username=username, password=cd['password']
                )
                if user:
                    login(request, user)
                    # Store tenant in session
                    request.session['tenant_id'] = tenant.id

                messages.success(
                    request,
                    f'Welcome to RS Systems, {cd["first_name"]}! '
                    f'Your 30-day free trial has started.',
                )
                logger.info(f"New signup: {email} — tenant '{tenant.name}'")
                return redirect('onboarding')

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
# 3. Onboarding wizard
# ------------------------------------------------------------------

@login_required
def onboarding_view(request):
    """Multi-step onboarding wizard."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found for your account.')
        return redirect('home')

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
            form = OnboardingTechnicianForm(request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                try:
                    with transaction.atomic():
                        if cd.get('add_self'):
                            # Add current user as technician if not already
                            if not Technician.objects.filter(user=request.user).exists():
                                Technician.objects.create(
                                    tenant=tenant,
                                    user=request.user,
                                    phone_number=cd.get('tech_phone', ''),
                                    is_manager=True,
                                    is_active=True,
                                )
                                # Add to Technicians group
                                from django.contrib.auth.models import Group
                                tech_group, _ = Group.objects.get_or_create(name='Technicians')
                                request.user.groups.add(tech_group)
                        else:
                            # Create a new user + technician
                            tech_email = cd.get('tech_email', '')
                            tech_username = tech_email[:150] if tech_email else f"tech_{cd['tech_first_name'].lower()}_{tenant.slug}"
                            if not User.objects.filter(username=tech_username).exists():
                                tech_user = User.objects.create_user(
                                    username=tech_username,
                                    email=tech_email or '',
                                    first_name=cd['tech_first_name'],
                                    last_name=cd['tech_last_name'],
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
                except Exception as e:
                    logger.error(f"Onboarding tech error: {e}")
                    messages.error(request, f'Could not add technician: {e}')

                request.session['onboarding_step'] = '3'
                return redirect('/onboarding/?step=3')

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

                request.session['onboarding_step'] = '4'
                return redirect('/onboarding/?step=4')

        elif step == '4':
            # Done — clear onboarding state
            request.session.pop('onboarding_step', None)
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
        context['form'] = OnboardingTechnicianForm(initial={
            'tech_first_name': request.user.first_name,
            'tech_last_name': request.user.last_name,
            'tech_email': request.user.email,
            'add_self': True,
        })
    elif step == '3':
        context['form'] = OnboardingCustomerForm()

    return render(request, 'saas/onboarding.html', context)


# ------------------------------------------------------------------
# 4. Owner dashboard
# ------------------------------------------------------------------

@login_required
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

    # Merge and sort
    recent_activity = sorted(
        list(recent_repairs) + list(recent_replacements),
        key=lambda x: x.service_date,
        reverse=True,
    )[:5]

    context = {
        'tenant': tenant,
        'membership': membership,
        'usage': usage,
        'recent_activity': recent_activity,
        'trial_days_remaining': tenant.trial_days_remaining,
        'is_trial': tenant.plan == 'trial',
        'is_trial_expired': tenant.is_trial_expired,
    }
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

@login_required
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
                    svc.create_subscription(tenant, plan_slug)
                    messages.success(request, 'Subscription created! You may need to complete payment.')
            elif action == 'change_plan':
                plan_slug = request.POST.get('plan')
                if plan_slug:
                    svc.update_subscription(tenant, plan_slug)
                    messages.success(request, 'Plan updated!')
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
# 7. Replacement form
# ------------------------------------------------------------------

@login_required
def replacement_create(request):
    """Create a new glass replacement."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        return redirect('home')

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
            messages.success(request, 'Replacement created successfully!')
            return redirect('replacement_detail', pk=replacement.pk)
    else:
        form = ReplacementForm(tenant=tenant)

    return render(request, 'saas/replacement_form.html', {
        'form': form,
        'tenant': tenant,
    })


@login_required
def replacement_detail(request, pk):
    """View a glass replacement."""
    tenant = getattr(request, 'tenant', None)
    replacement = get_object_or_404(Replacement, pk=pk)
    # Check tenant access
    if tenant and replacement.tenant_id and replacement.tenant_id != tenant.id:
        messages.error(request, 'Access denied.')
        return redirect('owner_dashboard')

    return render(request, 'saas/replacement_detail.html', {
        'replacement': replacement,
        'tenant': tenant,
    })


# ------------------------------------------------------------------
# 8. Billing — plan update, cancel, portal redirect
# ------------------------------------------------------------------

@login_required
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
            result = svc.update_subscription(tenant, new_plan_slug)
            messages.success(request, f'Plan updated to {result["new_plan"]}!')
        else:
            result = svc.create_subscription(tenant, new_plan_slug)
            if result.get('client_secret'):
                messages.info(
                    request,
                    'Subscription created. Please complete payment via the billing portal.'
                )
            else:
                messages.success(request, f'Subscribed to {result["plan"]}!')
    except SubscriptionError as e:
        messages.error(request, str(e))

    return redirect('billing_settings')


@login_required
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


@login_required
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

@login_required
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

    context = {
        'tenant': tenant,
        'membership': membership,
        'members': members,
    }

    return render(request, 'saas/owner_settings.html', context)


@login_required
def invite_member(request):
    """POST /owner/settings/invite/ — invite a new team member."""
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

    if not email:
        messages.error(request, 'Email is required.')
        return redirect('owner_settings')

    if role not in ('manager', 'technician', 'viewer'):
        messages.error(request, 'Invalid role selected.')
        return redirect('owner_settings')

    # Check if user already exists
    user = User.objects.filter(email=email).first()
    if not user:
        username = email[:150]
        if User.objects.filter(username=username).exists():
            messages.error(request, 'A user with this email already exists.')
            return redirect('owner_settings')

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

    TenantMembership.objects.create(
        tenant=tenant,
        user=user,
        role=role,
    )

    messages.success(request, f'{first_name} {last_name} ({email}) has been invited as {role}.')
    return redirect('owner_settings')
