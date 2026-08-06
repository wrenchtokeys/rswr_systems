"""
SaaS UI Views

Template-based views for signup, onboarding, owner dashboard,
pricing, billing settings, replacement form, shop join (customer
self-signup), and team management endpoints.

Author: Amelia (Clawdbot AI)
"""

import logging
import os
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
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from common.decorators import owner_or_manager_required, owner_required
from apps.technician_portal.decorators import technician_required
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.tenants.models import InviteToken, OnboardingState, SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.usage_service import UsageService
from apps.tenants.services.subscription_service import SubscriptionService, SubscriptionError
from apps.tenants.services.signup_service import create_tenant_with_owner, SignupError
from apps.technician_portal.models import Repair, Replacement, Technician, WarrantyPolicy
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
        # Use explicit priority ordering so 'owner' always beats 'manager' —
        # alphabetical order_by('role') puts 'manager' first (m < o), which
        # would return a manager membership at Shop B rather than an owner
        # membership at Shop A for users who belong to multiple shops.
        # Mirrors the annotation pattern in common/auth._get_membership. (CODE-129)
        from django.db.models import Case, When, IntegerField, Value
        membership = (
            TenantMembership.objects
            .filter(user=request.user, is_active=True, role__in=['owner', 'manager'])
            .select_related('tenant')
            .annotate(
                role_priority=Case(
                    When(role='owner', then=Value(0)),
                    When(role='manager', then=Value(1)),
                    default=Value(99),
                    output_field=IntegerField(),
                )
            )
            .order_by('role_priority')
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

    Used for shop-join (customer portal) signups where the user IS immediately
    logged in, and email verification is for notification preferences only.

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

        from core.email_utils import send_branded_email
        send_branded_email(
            subject='Verify your email address — RS Systems',
            recipient_list=[user.email],
            headline='Verify Your Email',
            body_paragraphs=[
                'Welcome to RS Systems!',
                'Please verify your email address by clicking the button below. This link will expire in 24 hours.',
                "If you didn't create an account, you can safely ignore this email.",
            ],
            button_text='✅ Verify Email',
            button_url=verification_url,
            fail_silently=True,
        )
        logger.info(f"Verification email sent to {user.email}")
    except Exception as e:
        # Log but don't fail - verification email is non-critical
        logger.warning(f"Failed to send verification email to {user.email}: {e}")


def _send_confirmation_email(request, user, tenant):
    """
    Send email confirmation link to a new shop owner whose account is inactive.

    Unlike _send_verification_email, this email is required — the user CANNOT
    log in until they click the link. Uses Django's built-in token generator
    (same one as password reset) for secure one-time tokens.

    Returns True if the email was handed to the backend, False on failure.
    A failure never breaks signup — the check-email page surfaces it and
    offers the resend link instead of leaving the user stranded.
    """
    try:
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        confirm_url = request.build_absolute_uri(
            reverse('owner_confirm_email', kwargs={'uidb64': uid, 'token': token})
        )

        from core.email_utils import send_branded_email
        sent = send_branded_email(
            subject='Confirm your email address — RS Systems',
            recipient_list=[user.email],
            headline='Confirm Your Email',
            body_paragraphs=[
                f'Hi {user.first_name or user.email},',
                'Thanks for signing up for RS Systems!',
                'To activate your account and start your 30-day free trial, please confirm your email address by clicking the button below.',
                "This link expires in 24 hours. If you didn't create an account, you can safely ignore this email.",
            ],
            button_text='Activate My Account',
            button_url=confirm_url,
            fail_silently=False,
        )
        logger.info(f"Confirmation email sent to {user.email} (account inactive, tenant={tenant.slug if tenant else '?'})")
        return bool(sent)
    except Exception as e:
        logger.warning(f"Failed to send confirmation email to {user.email}: {e}")
        return False


# ------------------------------------------------------------------
# 1. Signup
# ------------------------------------------------------------------

def _verify_turnstile(request) -> bool:
    """
    Verify Cloudflare Turnstile CAPTCHA token server-side.

    Returns True if verification passes OR if Turnstile is not configured
    (TURNSTILE_SECRET_KEY not set — so dev/test works without keys).
    Returns False only when keys are configured but verification fails.
    """
    import os
    import urllib.request
    import urllib.parse
    import json

    secret_key = os.environ.get('TURNSTILE_SECRET_KEY', '')
    if not secret_key:
        # Not configured — skip validation (dev/CI mode)
        return True

    token = request.POST.get('cf-turnstile-response', '')
    if not token:
        return False

    try:
        data = urllib.parse.urlencode({
            'secret': secret_key,
            'response': token,
            'remoteip': request.META.get('REMOTE_ADDR', ''),
        }).encode()
        req = urllib.request.Request(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data=data,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
        return result.get('success', False)
    except Exception as e:
        logger.warning(f"Turnstile verification error: {e}")
        # Fail open on network errors to avoid blocking legitimate signups
        return True


@ratelimit(key='ip', rate='5/h', method='POST', block=True)
def signup_view(request):
    """
    Public signup page — creates user, tenant, membership.

    The user account is created with is_active=False. A confirmation email
    is sent. The user is NOT logged in until they click the link.

    Rate-limited to 5 POST requests per IP per hour. Turnstile CAPTCHA is
    the primary defence but is disabled in dev/CI (no secret key), so the
    rate limit is the safety net against automated account-creation spam.
    """
    if request.user.is_authenticated:
        return redirect('owner_dashboard')

    turnstile_site_key = os.environ.get('TURNSTILE_SITE_KEY', '')

    if request.method == 'POST':
        # Turnstile CAPTCHA check (skipped if env var not set)
        if not _verify_turnstile(request):
            messages.error(request, 'CAPTCHA verification failed. Please try again.')
            form = SignupForm(request.POST)
            return render(request, 'saas/signup.html', {'form': form, 'turnstile_site_key': turnstile_site_key})

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
                    phone=cd.get('phone', ''),
                    services_offered=cd.get('services_offered', 'both'),
                )
                user = result['user']
                tenant = result['tenant']

                # Save intended plan if selected (clean_plan already validated)
                if cd.get('plan'):
                    tenant.intended_plan = cd['plan']
                    tenant.save(update_fields=['intended_plan'])

                # Set account inactive until email is confirmed
                user.is_active = False
                user.save(update_fields=['is_active'])

                # Send confirmation email; a failure is surfaced on the
                # check-email page (resend link) instead of silently lost.
                email_sent = _send_confirmation_email(request, user, tenant)

                # Notify site admins of new signup
                try:
                    from django.core.mail import mail_admins
                    mail_admins(
                        subject=f"New signup: {cd['first_name']} {cd['last_name']} ({tenant.name})",
                        message=(
                            f"New user signed up for RS Systems:\n\n"
                            f"Name: {cd['first_name']} {cd['last_name']}\n"
                            f"Email: {cd['email']}\n"
                            f"Shop: {tenant.name}\n"
                            f"Plan: {tenant.subscription_plan}\n"
                            f"Pending email confirmation."
                        ),
                    )
                except Exception:
                    pass  # Non-fatal — don't block signup

                # Don't log in yet — Post/Redirect/Get to the "check your
                # email" page so a refresh never re-submits the form.
                request.session['signup_pending'] = {
                    'email': cd['email'],
                    'first_name': cd['first_name'],
                    'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
                    'email_send_failed': not email_sent,
                }
                return redirect('signup_check_email')

            except SignupError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Signup error: {e}")
                messages.error(
                    request,
                    'An unexpected error occurred. Please try again.',
                )
    else:
        initial = {}
        plan_param = request.GET.get('plan', '')
        if plan_param and SubscriptionPlan.objects.filter(
            slug=plan_param, is_active=True
        ).exclude(slug='trial').exists():
            initial['plan'] = plan_param
        form = SignupForm(initial=initial)

    return render(request, 'saas/signup.html', {'form': form, 'turnstile_site_key': turnstile_site_key})


def signup_check_email(request):
    """
    GET /signup/check-email/ — refresh-safe landing after signup.

    Reads (without popping) the session state stashed by signup_view so the
    page survives refreshes. Direct visits with no pending signup go back to
    the signup form.
    """
    pending = request.session.get('signup_pending')
    if not pending:
        return redirect('signup')
    return render(request, 'saas/email_confirmation_sent.html', {
        'email': pending.get('email'),
        'first_name': pending.get('first_name'),
        'uidb64': pending.get('uidb64'),
        'email_send_failed': pending.get('email_send_failed', False),
    })


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

def _mark_wizard_complete(state):
    """Mark the onboarding wizard finished (idempotent)."""
    state.wizard_step = 4
    if state.wizard_completed_at is None:
        state.wizard_completed_at = timezone.now()
    state.save(update_fields=['wizard_step', 'wizard_completed_at', 'updated_at'])


@login_required
def onboarding_view(request):
    """Multi-step onboarding wizard."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found for your account.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    # Wizard progress lives on OnboardingState (not the session) so an owner
    # who bails at step 2 can resume from any device/login. (Phase 2, launch
    # readiness roadmap.)
    state = OnboardingState.get_for_tenant(tenant)

    def _persist_step(n):
        state.wizard_step = n
        state.save(update_fields=['wizard_step', 'updated_at'])

    # Determine current step: explicit GET param wins, else resume where the
    # wizard left off. wizard_step=0 means never started → step 1.
    default_step = str(state.wizard_step) if 1 <= state.wizard_step <= 4 else '1'
    step = str(request.GET.get('step', default_step))
    if step not in ('1', '2', '3', '4'):
        step = '1'

    # Record that the wizard has been started (0 → 1) so the dashboard can
    # offer a "finish setting up" resume link if the owner bails.
    if state.wizard_step < 1:
        _persist_step(1)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'skip':
            next_step = str(int(step) + 1)
            _persist_step(int(next_step))
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
                _persist_step(2)
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
                                # Guard: Technician.user is a OneToOneField — if this user
                                # already has a Technician record at a *different* tenant
                                # (e.g. they previously signed up for another shop), we
                                # cannot create a second one.  Attempting to do so raises
                                # IntegrityError (duplicate key).  Inform the user instead
                                # of crashing.  (CODE-217)
                                foreign_tech = Technician.objects.filter(user=request.user).exclude(tenant=tenant).first()
                                if foreign_tech:
                                    messages.warning(
                                        request,
                                        'Your account is already linked to a technician profile at another shop. '
                                        'You can still manage this shop as an owner — add a separate technician '
                                        'account from Settings → Team if needed.'
                                    )
                                else:
                                    from apps.tenants.services.team_service import resolve_ability_flags
                                    self_can_repair, self_can_replace = resolve_ability_flags(
                                        tenant,
                                        cd.get('tech_can_repair', True),
                                        cd.get('tech_can_replace', True),
                                    )
                                    Technician.objects.create(
                                        tenant=tenant,
                                        user=request.user,
                                        phone_number=cd.get('tech_phone', '') or tenant.business_phone,
                                        is_active=True,
                                        can_repair=self_can_repair,
                                        can_replace=self_can_replace,
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

                            if tech_email:
                                from apps.tenants.services.usage_service import UsageService
                                can_add, limit_msg = UsageService(tenant).can_add_technician()
                                if not can_add:
                                    messages.warning(request, limit_msg)
                                elif User.objects.filter(email__iexact=tech_email).exists():
                                    messages.info(request, 'A user with that email already exists. You can add them to your team from Settings → Team.')
                                else:
                                    from apps.tenants.services.team_service import (
                                        add_team_member, TeamServiceError,
                                    )
                                    tech_display = f"{tech_first} {tech_last}".strip() or tech_email
                                    try:
                                        result = add_team_member(
                                            tenant,
                                            request.user,
                                            email=tech_email,
                                            first_name=tech_first,
                                            last_name=tech_last,
                                            role='technician',
                                            phone=cd.get('tech_phone', ''),
                                            can_repair=cd.get('tech_can_repair', True),
                                            can_replace=cd.get('tech_can_replace', True),
                                            base_url=request.build_absolute_uri('/'),
                                        )
                                        if result['email_sent']:
                                            messages.success(
                                                request,
                                                f'{tech_display} has been added to your team. '
                                                f'We emailed them a link to set their password and log in.'
                                            )
                                        else:
                                            messages.success(
                                                request,
                                                f'{tech_display} has been added to your team. '
                                                f"The invite email could not be sent — share this link with them: {result['invite_url']}"
                                            )
                                    except TeamServiceError as e:
                                        messages.error(request, str(e))
                            else:
                                messages.info(request, 'No technician info provided — you can add team members later in Settings → Team.')

                except Exception as e:
                    logger.error(f"Onboarding tech error: {e}")
                    messages.error(request, f'Could not add technician: {e}')

                # Only advance on valid form
                _persist_step(3)
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
                _persist_step(4)
                return redirect('/onboarding/?step=4')
            # Invalid form — stay on step 3 (fall through to GET handler)

        elif step == '4':
            # Done
            _mark_wizard_complete(state)
            return redirect('owner_dashboard')

    # Step 4 GET = onboarding complete — redirect straight to dashboard
    if step == '4':
        _mark_wizard_complete(state)
        messages.success(request, "Setup complete! Welcome to your dashboard.")
        return redirect('owner_dashboard')

    # Build context for GET
    context = {
        'step': step,
        'tenant': tenant,
    }

    # An invalid POST falls through to here — keep the bound form so its
    # validation errors actually show (e.g. "add their email" on step 2).
    bound_form = None
    if request.method == 'POST':
        try:
            bound_form = form
        except NameError:
            pass

    if step == '1':
        context['form'] = bound_form or OnboardingBusinessForm(initial={
            'business_phone': tenant.business_phone,
            'business_email': tenant.business_email,
            'business_address': tenant.business_address,
        })
    elif step == '2':
        # Owner already has tech profile from signup — step 2 is for adding ANOTHER tech
        context['form'] = bound_form or OnboardingTechnicianForm(initial={
            'tech_first_name': '',
            'tech_last_name': '',
            'tech_email': '',
            'add_self': False,
        })
    elif step == '3':
        context['form'] = bound_form or OnboardingCustomerForm()

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

    # Setup checklist — one shared item list drives this card and the
    # settings-page card (Phase 2, launch readiness roadmap). The old
    # setup_steps context is kept (empty) for template/test compatibility.
    setup_steps = []
    setup_completion = _setup_completion(tenant)
    checklist_items = _setup_checklist_items(tenant, setup_completion)

    # First-run state: wizard resume link, persisted dismissals, tours.
    onboarding_state = OnboardingState.get_for_tenant(tenant)
    wizard_resume_step = None
    if not onboarding_state.wizard_completed and 1 <= onboarding_state.wizard_step <= 3:
        wizard_resume_step = onboarding_state.wizard_step

    # Tax setup banner: shown until the owner explicitly answers the
    # sales-tax question (billing_config.tax_configured).
    try:
        billing_config = BillingConfig.get_for_tenant(tenant)
    except Exception:
        billing_config = None

    # Resolve intended plan name for trial banner
    intended_plan_name = ''
    if tenant.intended_plan:
        try:
            intended_plan_name = SubscriptionPlan.objects.get(slug=tenant.intended_plan).name
        except SubscriptionPlan.DoesNotExist:
            pass

    context = {
        'tenant': tenant,
        'membership': membership,
        'usage': usage,
        'recent_activity': recent_activity,
        'trial_days_remaining': tenant.trial_days_remaining,
        'is_trial': tenant.plan == 'trial' and not tenant.is_platform_owner,
        'is_trial_expired': tenant.is_trial_expired,
        'setup_steps': setup_steps,
        'setup_completion': setup_completion,
        'checklist_items': checklist_items,
        'checklist_dismissed': onboarding_state.checklist_dismissed_at is not None,
        'trial_banner_dismissed': onboarding_state.trial_banner_dismissed_at is not None,
        'wizard_resume_step': wizard_resume_step,
        # ?tour=1 forces a replay (help pages link it); otherwise only on
        # first visit.
        'tour_slug': (
            'owner-dashboard'
            if (request.GET.get('tour') == '1'
                or not onboarding_state.has_completed_tour('owner-dashboard'))
            else ''
        ),
        'intended_plan': tenant.intended_plan,
        'intended_plan_name': intended_plan_name,
        'billing_config': billing_config,
    }
    context.update(billing_context)
    return render(request, 'saas/owner_dashboard.html', context)


# ------------------------------------------------------------------
# 4b. First-run state endpoints (Phase 2, launch readiness roadmap)
# ------------------------------------------------------------------

# Tours that exist in static/js/tours.js. Slugs not listed here 404 —
# adding a tour means adding it in both places.
TOUR_SLUGS = ('owner-dashboard', 'job-form')


@owner_or_manager_required
@require_POST
def dismiss_checklist(request):
    """POST /owner/checklist/dismiss/ — permanently hide the dashboard setup checklist."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No shop found.'}, status=403)
    state = OnboardingState.get_for_tenant(tenant)
    state.checklist_dismissed_at = timezone.now()
    state.save(update_fields=['checklist_dismissed_at', 'updated_at'])
    return JsonResponse({'success': True})


@owner_or_manager_required
@require_POST
def dismiss_trial_banner(request):
    """POST /owner/trial-banner/dismiss/ — hide the informational trial banner.

    Urgent states (trial expired / ≤7 days left) re-surface it regardless —
    see the template condition in owner_dashboard.html.
    """
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No shop found.'}, status=403)
    state = OnboardingState.get_for_tenant(tenant)
    state.trial_banner_dismissed_at = timezone.now()
    state.save(update_fields=['trial_banner_dismissed_at', 'updated_at'])
    return JsonResponse({'success': True})


@owner_or_manager_required
@require_POST
def complete_tour(request, slug):
    """POST /owner/tours/<slug>/complete/ — mark a tour done (skip = done, never re-nag)."""
    if slug not in TOUR_SLUGS:
        raise Http404('Unknown tour')
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No shop found.'}, status=403)
    state = OnboardingState.get_for_tenant(tenant)
    state.mark_tour_completed(slug)
    return JsonResponse({'success': True})


# ------------------------------------------------------------------
# 5. Pricing
# ------------------------------------------------------------------

def pricing_view(request):
    """Public pricing page. Trial isn't a card — every plan starts as a trial."""
    plans = SubscriptionPlan.objects.filter(is_active=True).exclude(slug='trial').order_by('display_order')
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
                plan_slug = request.POST.get('plan') or tenant.intended_plan
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

    # Single source of truth for the displayed plan: tenant.plan (the slug the
    # middleware enforces) wins over a stale subscription_plan FK. The two can
    # drift (e.g. migration 0016 set plan='pro' without touching the FK).
    current_plan = tenant.subscription_plan
    if tenant.plan and (not current_plan or current_plan.slug != tenant.plan):
        current_plan = SubscriptionPlan.objects.filter(slug=tenant.plan).first() or current_plan

    context = {
        'tenant': tenant,
        'usage': usage,
        'plans': plans,
        'current_plan': current_plan,
        'current_plan_slug': current_plan.slug if current_plan else tenant.plan,
        'is_trial': tenant.plan == 'trial' and not tenant.is_platform_owner,
        'is_platform_owner': tenant.is_platform_owner,
        'trial_days_remaining': tenant.trial_days_remaining,
        'intended_plan': tenant.intended_plan if tenant.intended_plan and tenant.intended_plan != tenant.plan else '',
    }
    return render(request, 'saas/billing.html', context)


# ------------------------------------------------------------------
# 7. Replacement management
# ------------------------------------------------------------------

@technician_required
def replacement_list(request):
    """Legacy /tech/replacements/ — redirects to the unified job list."""
    params = request.GET.copy()
    if not params.get('status'):
        params.pop('status', None)  # old list used status='' for "all"
    params['type'] = 'replacement'
    return redirect(f"{reverse('job_list')}?{params.urlencode()}")


def _replacement_technician_access(request, tenant, replacement=None,
                                   require_can_replace=False):
    """Access check for technician-facing replacement views.

    Tenant admins (owner/manager/staff) and working managers always pass.
    Otherwise the user needs a tenant-scoped Technician profile; when a
    replacement is given it must be assigned to them, and require_can_replace
    additionally demands the can_replace ability.
    """
    from apps.technician_portal.decorators import is_tenant_admin
    if is_tenant_admin(request.user, tenant=tenant):
        return True
    technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
    if technician is None:
        return False
    if technician.is_manager:
        return True
    if require_can_replace and not technician.can_replace:
        return False
    if replacement is not None and replacement.technician_id != technician.id:
        return False
    return True


@technician_required
def replacement_create(request):
    """Create a new glass replacement."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    # New replacements only for shops that offer them (existing ones stay
    # viewable via replacement_list/detail for history).
    if not tenant.offers_replacements:
        messages.info(request, 'Your shop is set to repairs only. You can change this under Settings → What does your shop do?')
        return redirect('owner_dashboard')

    if not _replacement_technician_access(request, tenant, require_can_replace=True):
        messages.warning(request, "Your technician profile isn't set up for replacements. Ask a manager to enable it under Team settings.")
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    # Check limits
    usage_svc = UsageService(tenant)
    can_create, limit_msg = usage_svc.can_create_repair()
    if not can_create:
        messages.warning(request, limit_msg)
        return redirect('owner_dashboard')

    from apps.technician_portal.views.jobs import _parse_extra_charges, _save_extra_charges
    from apps.technician_portal.models import FeePreset

    charges = []
    if request.method == 'POST':
        form = ReplacementForm(request.POST, request.FILES, tenant=tenant)
        charges, charge_error = _parse_extra_charges(request)
        if form.is_valid() and charge_error:
            form.add_error(None, charge_error)
        if form.is_valid():
            replacement = form.save(commit=False)
            replacement.tenant = tenant
            replacement.save()

            if charges:
                _save_extra_charges(
                    replacement, charges, tenant, taxable=not replacement.no_tax,
                )

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
        # ?customer=<id>&unit=<n> prefill — same params the New Repair
        # buttons on customer/unit detail pages use.
        initial = {}
        if request.GET.get('customer'):
            initial['customer'] = request.GET.get('customer')
        if request.GET.get('unit'):
            initial['unit_number'] = request.GET.get('unit')
        form = ReplacementForm(tenant=tenant, initial=initial)

    return render(request, 'saas/replacement_form.html', {
        'form': form,
        'tenant': tenant,
        'charge_rows': charges,
        'fee_presets': FeePreset.objects.filter(tenant=tenant, is_active=True),
    })


@technician_required
def replacement_detail(request, pk):
    """View a glass replacement."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

    if not _replacement_technician_access(request, tenant, replacement=replacement):
        messages.warning(request, "You don't have access to this replacement.")
        return redirect('job_list')

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

    # Invoiced state — drives the "Create Invoice" button on completed jobs
    from apps.billing.models import InvoiceLineItem
    invoice_line_item = InvoiceLineItem.objects.filter(
        replacement=replacement,
        invoice__tenant=tenant,
        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
    ).select_related('invoice').first()

    from apps.billing.services.invoice_send_service import InvoiceSendService
    from apps.technician_portal.decorators import is_tenant_admin
    return render(request, 'saas/replacement_detail.html', {
        'replacement': replacement,
        'tenant': tenant,
        'is_admin': is_tenant_admin(request.user, tenant=tenant),
        'status_transitions': status_transitions,
        'is_invoiced': invoice_line_item is not None,
        'existing_invoice': invoice_line_item.invoice if invoice_line_item else None,
        'invoice_recipient_email': InvoiceSendService.resolve_recipient(replacement.customer)
                                   if replacement.customer else '',
    })


@technician_required
def replacement_edit(request, pk):
    """Edit an existing glass replacement."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

    if not _replacement_technician_access(request, tenant, replacement=replacement,
                                          require_can_replace=True):
        messages.warning(request, "You don't have access to edit this replacement.")
        return redirect('job_list')

    # Extra charges are editable until the job lands on a live invoice;
    # after that they're managed on the invoice (Add Line Item).
    from apps.billing.services.invoice_sync import live_invoice_number_for_service
    from apps.technician_portal.views.jobs import _parse_extra_charges, _save_extra_charges
    from apps.technician_portal.models import FeePreset
    charges_locked_invoice = live_invoice_number_for_service(replacement)

    if request.method == 'POST':
        form = ReplacementForm(request.POST, request.FILES, instance=replacement, tenant=tenant)
        charges, charge_error = _parse_extra_charges(request)
        if not charges_locked_invoice and charge_error and form.is_valid():
            form.add_error(None, charge_error)
        if form.is_valid():
            form.save()
            if not charges_locked_invoice:
                _save_extra_charges(
                    replacement, charges, tenant, taxable=not replacement.no_tax,
                )
            messages.success(request, 'Replacement updated successfully!')
            return redirect('replacement_detail', pk=replacement.pk)
    else:
        form = ReplacementForm(instance=replacement, tenant=tenant)

    if request.method == 'POST' and not charges_locked_invoice:
        charge_rows = [
            (d.strip(), a.strip())
            for d, a in zip(request.POST.getlist('charge_desc'),
                            request.POST.getlist('charge_amount'))
            if d.strip() or a.strip()
        ]
    else:
        charge_rows = [(c.description, c.amount) for c in replacement.extra_charges.all()]

    return render(request, 'saas/replacement_edit.html', {
        'form': form,
        'replacement': replacement,
        'tenant': tenant,
        'charges_locked_invoice': charges_locked_invoice,
        'charge_rows': charge_rows,
        'fee_presets': FeePreset.objects.filter(tenant=tenant, is_active=True),
    })


@require_POST
@technician_required
def replacement_update_status(request, pk):
    """Update the status of a glass replacement."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

    if not _replacement_technician_access(request, tenant, replacement=replacement,
                                          require_can_replace=True):
        messages.warning(request, "You don't have access to update this replacement.")
        return redirect('job_list')

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


@require_POST
@technician_required
def replacement_delete(request, pk):
    """Soft-delete a replacement. Owner/manager only.

    Mirrors delete_repair: the replacement and any invoices containing it are
    soft-deleted together (payments stay intact), restorable from Recently
    Deleted for 30 days, then purged by purge_deleted_records.
    """
    from apps.technician_portal.decorators import is_tenant_admin
    from apps.billing.models import Invoice

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

    if not is_tenant_admin(request.user, tenant=tenant):
        messages.error(request, "Only owners and managers can delete replacements.")
        return redirect('replacement_detail', pk=pk)

    with transaction.atomic():
        now = timezone.now()
        replacement.deleted_at = now
        replacement.save(update_fields=['deleted_at'])
        Invoice.objects.filter(
            line_items__replacement=replacement
        ).distinct().update(deleted_at=now)

    messages.success(
        request,
        f"Replacement #{pk} has been deleted. "
        "You can restore it from Recently Deleted for 30 days."
    )
    return redirect('job_list')


@require_POST
@technician_required
def replacement_complete_and_invoice(request, pk):
    """One click: complete the replacement (if needed), invoice it, and email
    the invoice. Mirrors repair_complete_and_invoice."""
    from common.auth import can_access
    from apps.technician_portal.services.job_flow import (
        JobFlowError, complete_job, invoice_and_send,
    )
    from apps.technician_portal.views.jobs import _copy_to_email, notify_invoice_outcome

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No shop context. Please log in.')
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)
    replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

    if not can_access(request.user, 'invoices', tenant):
        messages.warning(request, "You don't have access to invoicing.")
        return redirect('replacement_detail', pk=pk)

    if not _replacement_technician_access(request, tenant, replacement=replacement,
                                          require_can_replace=True):
        messages.warning(request, "You don't have access to this replacement.")
        return redirect('job_list')

    try:
        complete_job(replacement)
    except JobFlowError as e:
        messages.warning(request, str(e))
        return redirect('replacement_detail', pk=pk)

    try:
        invoice, created, result, excluded = invoice_and_send(
            replacement, tenant, copy_to_email=_copy_to_email(request))
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('replacement_detail', pk=pk)
    notify_invoice_outcome(request, invoice, created, result, excluded)
    return redirect('owner_invoice_detail', invoice_id=invoice.id)


# ------------------------------------------------------------------
# 8. Billing — plan update, cancel, portal redirect
# ------------------------------------------------------------------

@owner_required
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


@owner_required
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


@owner_required
def update_payment_method(request):
    """GET /owner/update-payment-method/ — redirect to Stripe Billing Portal for card update."""
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


@owner_required
def billing_portal_redirect(request):
    """GET /owner/billing/portal/ — redirect to Stripe Billing Portal."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership:
        messages.error(request, 'Access denied.')
        return redirect('billing_settings')

    if tenant.is_platform_owner:
        messages.info(request, 'Platform owner accounts have a permanent plan — no billing portal needed.')
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

@owner_required
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


@owner_required
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


@owner_required
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


@owner_required
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
                messages.success(request, 'Job assignment strategy updated successfully.')
            else:
                messages.error(request, 'Invalid assignment strategy selected.')
            return redirect('owner_settings')

        if form_type == 'services_offered':
            new_services = request.POST.get('services_offered', '')
            valid_services = [c[0] for c in tenant.SERVICES_CHOICES]
            if new_services not in valid_services:
                messages.error(request, 'Invalid selection.')
                return redirect('owner_settings')
            if new_services == tenant.services_offered:
                return redirect('owner_settings')

            old_services = tenant.services_offered
            tenant.services_offered = new_services
            tenant.save(update_fields=['services_offered'])

            # Keep technician abilities in sync so work stays assignable.
            active_techs = Technician.objects.filter(tenant=tenant, is_active=True)
            notes = []
            if new_services in ('repair', 'replacement'):
                # Single-service shop: everyone does the one service.
                updated = active_techs.update(
                    can_repair=tenant.offers_repairs,
                    can_replace=tenant.offers_replacements,
                )
                if updated:
                    service_word = 'repairs' if new_services == 'repair' else 'replacements'
                    notes.append(f'All your technicians are now set to do {service_word}.')
            else:
                # Now offering both: make sure each service has someone who
                # can do it, otherwise customer requests dead-end.
                if not active_techs.filter(can_repair=True).exists():
                    active_techs.update(can_repair=True)
                    notes.append('All your technicians can now be assigned repairs — adjust individuals under Team.')
                if not active_techs.filter(can_replace=True).exists():
                    active_techs.update(can_replace=True)
                    notes.append('All your technicians can now be assigned replacements — adjust individuals under Team.')

            label = dict(tenant.SERVICES_CHOICES)[new_services]
            msg = f'Got it — your shop now does: {label.lower()}.'
            if notes:
                msg += ' ' + ' '.join(notes)
            messages.success(request, msg)
            logger.info(
                "services_offered changed for tenant %s: %s -> %s",
                tenant.id, old_services, new_services,
            )
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

                # Fall back to the tenant's current value, not the factory
                # defaults — the flat-price form posts only repair_price_1,
                # and a partial POST must never reset the other tiers.
                tenant.repair_price_1 = _parse_price('repair_price_1', tenant.repair_price_1)
                tenant.repair_price_2 = _parse_price('repair_price_2', tenant.repair_price_2)
                tenant.repair_price_3 = _parse_price('repair_price_3', tenant.repair_price_3)
                tenant.repair_price_4 = _parse_price('repair_price_4', tenant.repair_price_4)
                tenant.repair_price_5_plus = _parse_price('repair_price_5_plus', tenant.repair_price_5_plus)
                tenant.save(update_fields=[
                    'repair_price_1', 'repair_price_2', 'repair_price_3',
                    'repair_price_4', 'repair_price_5_plus'
                ])
                messages.success(request, 'Repair pricing updated.')
            except Exception as e:
                logger.error(f"Error updating pricing tiers: {e}")
                messages.error(request, 'Could not update pricing tiers.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'add_fee_preset':
            # Saved fees (trip charge etc.) — one-tap chips on the job form
            from decimal import Decimal, InvalidOperation
            from apps.technician_portal.models import FeePreset
            label = request.POST.get('label', '').strip()
            try:
                amount = Decimal(request.POST.get('amount', ''))
            except (InvalidOperation, TypeError):
                amount = None
            if not label or amount is None or amount <= 0:
                messages.error(request, 'A saved fee needs a name and an amount above zero.')
            else:
                FeePreset.objects.create(tenant=tenant, label=label[:100], amount=amount)
                messages.success(request, f'Saved fee "{label}" added.')
            return redirect('/owner/settings/?tab=billing#saved-fees')

        if form_type == 'delete_fee_preset':
            from apps.technician_portal.models import FeePreset
            try:
                preset = FeePreset.objects.get(
                    tenant=tenant, id=int(request.POST.get('preset_id', '')))
                preset.delete()
                messages.success(request, f'Saved fee "{preset.label}" removed.')
            except (FeePreset.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Saved fee not found.')
            return redirect('/owner/settings/?tab=billing#saved-fees')

        if form_type == 'billing_location':
            # Update shop address ONLY. Tax setup is its own explicit form
            # (form_type='tax_settings') — saving your address must never
            # silently enable tax or touch rates.
            try:
                config = BillingConfig.get_for_tenant(tenant)
                config.company_address = request.POST.get('company_address', '').strip()
                config.company_city = request.POST.get('company_city', '').strip()
                config.company_state = request.POST.get('company_state', '').strip().upper()
                config.company_zip = request.POST.get('company_zip', '').strip()
                config.save()
                messages.success(request, 'Shop address saved.')
            except Exception as e:
                logger.error(f"Error updating shop address: {e}")
                messages.error(request, 'Could not save the shop address.')
            return redirect('/owner/settings/?tab=billing')

        if form_type == 'tax_settings':
            # The ONLY place tax gets configured. Explicit yes/no answer +
            # a single combined rate (advanced: component breakdown).
            try:
                from decimal import Decimal, InvalidOperation
                from apps.billing.models import TaxRate as _TaxRate
                config = BillingConfig.get_for_tenant(tenant)
                charges_tax = request.POST.get('charges_tax', '').strip().lower()
                if charges_tax not in ('yes', 'no'):
                    messages.error(request, 'Choose "Yes, we charge sales tax" or "No, we don\'t".')
                    return redirect('/owner/settings/?tab=billing')

                if charges_tax == 'no':
                    config.tax_enabled = False
                    config.tax_configured = True
                    config.save()
                    messages.success(request, "Got it — this shop doesn't charge sales tax. Invoices will have no tax.")
                    return redirect('/owner/settings/?tab=billing')

                def _dec(field):
                    raw = (request.POST.get(field, '') or '').strip()
                    if raw == '':
                        return Decimal('0')
                    return Decimal(raw)

                try:
                    # Advanced breakdown wins when any component is filled in;
                    # otherwise the single combined field goes in the state slot.
                    components = {
                        'state_tax_rate': _dec('state_tax_rate'),
                        'county_tax_rate': _dec('county_tax_rate'),
                        'city_tax_rate': _dec('city_tax_rate'),
                        'special_tax_rate': _dec('special_tax_rate'),
                    }
                    if not any(components.values()):
                        components['state_tax_rate'] = _dec('tax_rate_percent')
                except (InvalidOperation, ValueError):
                    messages.error(request, 'Enter your sales tax rate as a percent, like 8.25')
                    return redirect('/owner/settings/?tab=billing')

                total_rate = sum(components.values())
                if total_rate <= 0 or total_rate > 30:
                    messages.error(request, 'Enter your sales tax rate as a percent between 0 and 30, like 8.25')
                    return redirect('/owner/settings/?tab=billing')

                config.state_tax_rate = components['state_tax_rate']
                config.county_tax_rate = components['county_tax_rate']
                config.city_tax_rate = components['city_tax_rate']
                config.special_tax_rate = components['special_tax_rate']
                config.default_tax_rate = total_rate
                config.tax_enabled = True
                config.tax_configured = True
                config.save()

                # Keep the tenant's single TaxRate row in sync so the
                # location-based rate cascade keeps working. Rates only —
                # this row no longer controls whether tax applies.
                row = _TaxRate.objects.filter(tenant=tenant).order_by('-effective_date', '-id').first()
                if row is None:
                    row = _TaxRate(tenant=tenant)
                row.city = config.company_city or ''
                row.state = config.company_state or ''
                row.state_rate = config.state_tax_rate
                row.county_rate = config.county_tax_rate
                row.city_rate = config.city_tax_rate
                row.special_rate = config.special_tax_rate
                row.is_active = True
                row.save()

                messages.success(request, f'Sales tax set to {total_rate}%. Invoices will include it from now on.')
            except Exception as e:
                logger.error(f"Error updating tax settings: {e}")
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

                # Validate frequency against canonical choices — an unrecognised
                # value would be silently saved and then cause batch invoicing to
                # never run (the task's _should_run_batch_today() returns False for
                # any unknown frequency).  (CODE-201)
                raw_freq = request.POST.get('batch_invoice_frequency', 'disabled')
                valid_frequencies = {code for code, _ in BillingConfig.BATCH_FREQUENCY_CHOICES}
                if raw_freq not in valid_frequencies:
                    messages.error(
                        request,
                        f'Invalid batch invoice frequency: {raw_freq!r}. '
                        f'Must be one of: {", ".join(sorted(valid_frequencies))}.'
                    )
                    return redirect('/owner/settings/?tab=billing')

                raw_day = request.POST.get('batch_invoice_day', '1')
                try:
                    batch_day = int(raw_day)
                except (ValueError, TypeError):
                    messages.error(request, 'Batch invoice day must be a number.')
                    return redirect('/owner/settings/?tab=billing')

                # Validate day range based on frequency:
                #   weekly/biweekly → 0-6 (Monday=0, Sunday=6)
                #   monthly         → 1-28
                #   disabled        → day is irrelevant, accept any valid int
                if raw_freq in ('weekly', 'biweekly') and not (0 <= batch_day <= 6):
                    messages.error(
                        request,
                        f'Batch invoice day must be 0–6 for weekly/bi-weekly scheduling '
                        f'(0=Monday … 6=Sunday). Got: {batch_day}.'
                    )
                    return redirect('/owner/settings/?tab=billing')
                if raw_freq == 'monthly' and not (1 <= batch_day <= 28):
                    messages.error(
                        request,
                        f'Batch invoice day must be 1–28 for monthly scheduling. Got: {batch_day}.'
                    )
                    return redirect('/owner/settings/?tab=billing')

                config.batch_invoice_frequency = raw_freq
                config.batch_invoice_day = batch_day
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

        if form_type == 'invoice_numbering':
            try:
                config = BillingConfig.get_for_tenant(tenant)
                prefix = request.POST.get('invoice_number_prefix', '').strip() or 'INV'
                if len(prefix) > 20:
                    messages.error(request, 'Invoice prefix must be 20 characters or fewer.')
                    return redirect('/owner/settings/?tab=billing')
                try:
                    next_number = int(request.POST.get('next_invoice_number', ''))
                except (ValueError, TypeError):
                    messages.error(request, 'Next invoice number must be a whole number.')
                    return redirect('/owner/settings/?tab=billing')
                if next_number < 1:
                    messages.error(request, 'Next invoice number must be at least 1.')
                    return redirect('/owner/settings/?tab=billing')
                config.invoice_number_prefix = prefix
                config.next_invoice_number = next_number
                config.save(update_fields=['invoice_number_prefix', 'next_invoice_number'])
                messages.success(request, f'Invoice numbering saved. Your next invoice will be {prefix}-{next_number}.')
            except Exception as e:
                logger.error(f"Error saving invoice numbering: {e}")
                messages.error(request, 'Could not save invoice numbering.')
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

        if form_type == 'review_settings':
            try:
                from apps.technician_portal.review_models import ReviewConfig
                review_config = ReviewConfig.get_for_tenant(tenant)
                review_config.is_enabled = request.POST.get('review_enabled') == 'on'
                review_config.send_to_fleet = request.POST.get('review_send_to_fleet') == 'on'
                review_config.google_review_url = request.POST.get('google_review_url', '').strip()
                review_config.email_subject = (
                    request.POST.get('email_subject', '').strip()
                    or "How was your experience with {shop_name}?"
                )
                review_config.email_body_template = request.POST.get('email_body_template', '').strip()
                review_config.save(update_fields=[
                    'is_enabled', 'send_to_fleet', 'google_review_url',
                    'email_subject', 'email_body_template',
                ])
                messages.success(request, 'Review settings saved.')
            except Exception as e:
                logger.error(f"Error saving review settings: {e}")
                messages.error(request, 'Could not save review settings.')
            return redirect('/owner/settings/?tab=reviews')

        if form_type == 'branding':
            import re
            if request.POST.get('reset_brand'):
                tenant.brand_color = ''
                tenant.save(update_fields=['brand_color'])
                messages.success(request, 'Brand color reset to the default blue.')
            else:
                brand_color = request.POST.get('brand_color', '').strip()
                if re.fullmatch(r'#[0-9a-fA-F]{6}', brand_color):
                    tenant.brand_color = brand_color
                    tenant.save(update_fields=['brand_color'])
                    messages.success(request, 'Brand color saved. It now shows on your invoices, emails, and customer portal.')
                else:
                    messages.error(request, 'Please pick a valid color.')
            return redirect('owner_settings')

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

    # Batch invoicing: month day choices for dropdown.
    # Use proper ordinal logic: 11/12/13 are always "th" (not "st"/"nd"/"rd"),
    # then cycle by last digit.  The inline ternary chain previously used
    # `d == 1`, `d == 2`, `d == 3` which produced "11st", "12nd", "21th", etc.
    # (CODE-148)
    def _ordinal_suffix(n):
        if 10 <= n % 100 <= 20:
            return 'th'
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

    batch_month_days = [{'value': d, 'label': f'{d}{_ordinal_suffix(d)} of the month'} for d in range(1, 29)]

    # Batch invoicing only touches customers whose invoice preference is
    # 'batch' — surface a warning when the schedule is on but nobody qualifies.
    from apps.customer_portal.models import CustomerRepairPreference
    has_batch_customers = CustomerRepairPreference.objects.filter(
        customer__tenant=tenant, invoice_preference='batch',
    ).exists()

    # Next batch run date, computed with the nightly task's own scheduling
    # logic so the preview can never drift from what the cron actually does.
    # The job fires at 06:00 UTC; past that, today's run already happened.
    batch_next_run = None
    if billing_config and billing_config.batch_invoice_frequency != 'disabled':
        from datetime import timedelta
        from apps.billing.tasks import _should_run_batch_today
        now = timezone.now()
        start = now.date() + timedelta(days=1) if now.hour >= 6 else now.date()
        for offset in range(70):
            candidate = start + timedelta(days=offset)
            if _should_run_batch_today(billing_config, candidate):
                batch_next_run = candidate
                break

    # Reminders toggled on with no day marks selected will never email anyone
    reminders_misconfigured = bool(
        billing_config
        and billing_config.overdue_reminder_enabled
        and not active_reminder_days
    )

    # Review request settings + recent requests
    from apps.technician_portal.review_models import ReviewConfig, ReviewRequest
    review_config = ReviewConfig.get_for_tenant(tenant)
    recent_review_requests = (
        ReviewRequest.objects
        .filter(tenant=tenant)
        .select_related('customer', 'repair')
        .order_by('-created_at')[:10]
    )

    # Warranty policies for the Warranty tab — the two tenant-wide policies
    warranty_policies = (
        WarrantyPolicy.objects
        .filter(tenant=tenant, customer__isnull=True, is_active=True)
        .order_by('applies_to', 'name')
    )

    completion = _setup_completion(tenant)

    # Whether the logged-in owner/manager is themselves an active technician
    # for THIS tenant — drives the "Add myself as a technician" callout.
    # Cross-tenant records don't count, but block creating a second one
    # (Technician.user is a OneToOneField, CODE-217).
    my_tech = Technician.objects.filter(user=request.user, tenant=tenant).first()
    my_foreign_tech = (
        None if my_tech
        else Technician.objects.filter(user=request.user).exclude(tenant=tenant).first()
    )
    i_am_technician = bool(my_tech and my_tech.is_active)
    can_add_self_as_tech = not i_am_technician and not my_foreign_tech

    # Saved fees for the Billing tab (one-tap extra charges on the job form)
    from apps.technician_portal.models import FeePreset
    fee_presets = FeePreset.objects.filter(tenant=tenant).order_by('display_order', 'id')

    context = {
        'tenant': tenant,
        'membership': membership,
        'members': members,
        'i_am_technician': i_am_technician,
        'can_add_self_as_tech': can_add_self_as_tech,
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
        'has_batch_customers': has_batch_customers,
        'batch_next_run': batch_next_run,
        'reminders_misconfigured': reminders_misconfigured,
        'review_config': review_config,
        'recent_review_requests': recent_review_requests,
        'warranty_policies': warranty_policies,
        'warranty_applies_to_choices': WarrantyPolicy.APPLIES_TO_CHOICES,
        'warranty_duration_type_choices': WarrantyPolicy.WARRANTY_DURATION_CHOICES,
        'completion': completion,
        'checklist_items': _setup_checklist_items(tenant, completion),
        'fee_presets': fee_presets,
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

    # Ability checkboxes for technicians/managers. Single-service shops
    # ignore the checkboxes — everyone does what the shop does.
    from apps.tenants.services.team_service import resolve_ability_flags
    can_repair, can_replace = resolve_ability_flags(
        tenant,
        request.POST.get('can_repair') == 'on',
        request.POST.get('can_replace') == 'on',
    )

    if not email:
        messages.error(request, 'Email is required.')
        return redirect('owner_settings')

    # Prevent inviting yourself (owner)
    if email == request.user.email.lower():
        messages.warning(request, "That's your own email. Use the 'Add myself as a technician' button on the Team tab instead.")
        return redirect('/owner/settings/?tab=team')

    if role not in ('manager', 'technician', 'viewer'):
        messages.error(request, 'Invalid role selected.')
        return redirect('owner_settings')

    # Privilege escalation guard: managers cannot invite other managers.
    # Only shop owners can grant manager-level access.  Without this check,
    # a manager can run the invite flow with role=manager (the role validation
    # above allows it) and create a peer manager without the owner's knowledge.
    # (CODE-206)
    if membership.role == 'manager' and role == 'manager':
        messages.error(request, 'Only the shop owner can invite managers.')
        return redirect('owner_settings')

    # Check existing membership (reactivation branch stays inline; the
    # fresh-member path below goes through team_service.add_team_member).
    user = User.objects.filter(email=email).first()
    existing = TenantMembership.objects.filter(tenant=tenant, user=user).first() if user else None
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
                from core.email_utils import send_branded_email
                send_branded_email(
                    subject=subject,
                    recipient_list=[email],
                    headline=f"Welcome Back to {tenant.name}!",
                    body_paragraphs=[
                        f"Hi {user.first_name or user.email},",
                        f"{inviter_name} has re-added you to {tenant.name} as a {role}.",
                        "Click the button below to set your password and get back in. This link expires in 7 days.",
                    ],
                    button_text='🔑 Set Password & Log In',
                    button_url=invite_url,
                    tenant=tenant,
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

    from apps.tenants.services.team_service import add_team_member, TeamServiceError
    try:
        result = add_team_member(
            tenant,
            request.user,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            can_repair=can_repair,
            can_replace=can_replace,
            base_url=request.build_absolute_uri('/'),
        )
    except TeamServiceError as e:
        messages.error(request, str(e))
        return redirect('owner_settings')

    if result['email_sent']:
        messages.success(
            request,
            f'{first_name} {last_name} ({email}) has been invited as {role}. '
            f'An invite email has been sent.'
        )
    else:
        messages.success(
            request,
            f'{first_name} {last_name} ({email}) has been invited as {role}. '
            f"Email could not be sent. Share this invite link manually: {result['invite_url']}"
        )

    return redirect('owner_settings')


# ------------------------------------------------------------------
# 10. Shop Join — Customer Self-Signup (Phase 4)
# ------------------------------------------------------------------

def _record_signup_referral(tenant, customer_user, raw_code):
    """
    Validate + record a referral code entered at signup. Returns True if a
    PENDING referral was recorded (bonuses pay on first completed job).
    Never raises — signup must succeed even if the code is bad.
    """
    if not raw_code or not str(raw_code).strip():
        return False
    try:
        from apps.rewards_referrals.services import ReferralService
        code_obj = ReferralService.validate_referral_code(str(raw_code).strip().upper())
        if code_obj is None:
            return False
        # Cross-tenant codes are rejected inside record_referral too, but
        # check here so we can tell the difference for messaging.
        if code_obj.customer_user.customer.tenant_id != tenant.id:
            return False
        return ReferralService.record_referral(code_obj, customer_user)
    except Exception:
        logger.warning('Failed to record signup referral', exc_info=True)
        return False


def _notify_shop_new_signup(tenant, customer, user, referral_recorded=False):
    """
    Best-effort owner notification when a customer self-signs up via
    /join/<slug>/. In-app notification to manager technicians + email to the
    shop owner. Never raises — signup must succeed even if delivery fails.
    """
    signup_kind = 'fleet account' if customer.customer_type == 'FLEET' else 'individual account'
    referral_note = ' (used a referral code)' if referral_recorded else ''

    try:
        from apps.technician_portal.models import Technician, TechnicianNotification
        for tech in Technician.objects.filter(tenant=tenant, is_active=True, is_manager=True):
            TechnicianNotification.objects.create(
                technician=tech,
                message=f"New portal signup: {customer.name} ({signup_kind}){referral_note}",
                read=False,
            )
    except Exception:
        logger.warning('Failed to create signup TechnicianNotification', exc_info=True)

    try:
        recipient = getattr(getattr(tenant, 'owner', None), 'email', '') or (tenant.business_email or '')
        if not recipient:
            return
        from core.email_utils import send_branded_email
        detail_rows = [
            ('Customer', customer.name),
            ('Type', 'Fleet' if customer.customer_type == 'FLEET' else 'Individual'),
            ('Contact', user.get_full_name() or user.email),
            ('Email', user.email),
        ]
        if referral_recorded:
            detail_rows.append(('Referral', 'Signed up with a referral code — bonus pays after their first completed job'))
        send_branded_email(
            subject=f"New customer signup — {customer.name}",
            recipient_list=[recipient],
            headline="New Portal Signup",
            body_paragraphs=[
                f"{customer.name} just created a portal account at your shop{referral_note}.",
                "They can now request services from the customer portal. Requests will appear in your queue for pricing and approval as usual.",
            ],
            detail_rows=detail_rows,
            tenant=tenant,
            fail_silently=True,
        )
    except Exception:
        logger.warning('Failed to send signup notification email', exc_info=True)


@ratelimit(key='ip', rate='10/h', method='POST', block=False)
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
            new_cu = CustomerUserModel.objects.create(
                user=request.user,
                customer=customer,
                is_primary_contact=True,
            )
            TenantMembership.objects.get_or_create(
                tenant=tenant,
                user=request.user,
                defaults={'role': 'viewer'},
            )
        referral_recorded = _record_signup_referral(tenant, new_cu, request.GET.get('ref'))
        _notify_shop_new_signup(tenant, customer, request.user, referral_recorded)
        request.session['tenant_id'] = tenant.id
        messages.success(request, f"Welcome to {tenant.name}! Your portal account is ready.")
        return redirect('customer_dashboard')

    turnstile_site_key = os.environ.get('TURNSTILE_SITE_KEY', '')

    if request.method == 'POST':
        # Enforce IP-based rate limit (set by @ratelimit decorator)
        if getattr(request, 'limited', False):
            return render(request, 'saas/shop_join.html', {
                'tenant': tenant,
                'errors': ['Too many registration attempts. Please try again later.'],
                'form_data': {},
                'turnstile_site_key': turnstile_site_key,
            })

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip() or None
        company_name = request.POST.get('company_name', '').strip()
        referral_code_input = request.POST.get('referral_code', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        errors = []

        # Same CAPTCHA gate as owner signup (no-op when keys unconfigured)
        if not _verify_turnstile(request):
            errors.append('CAPTCHA verification failed. Please try again.')

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
        if email and User.objects.filter(email__iexact=email).exists():
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
                    'referral_code': referral_code_input,
                },
                'turnstile_site_key': turnstile_site_key,
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
                customer_user_rec = CustomerUser.objects.create(
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

            # Referral (PENDING — pays after first completed job) + owner heads-up
            referral_recorded = _record_signup_referral(tenant, customer_user_rec, referral_code_input)
            _notify_shop_new_signup(tenant, customer, user, referral_recorded)
            if referral_code_input and not referral_recorded:
                messages.warning(request, "That referral code wasn't valid for this shop, so no referral was recorded — your account was still created.")
            elif referral_recorded:
                messages.info(request, "Referral recorded! You and your referrer will receive bonus points after your first completed service.")

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
            logger.error(f"Shop join error for {email} at {tenant.slug}: {e}", exc_info=True)
            return render(request, 'saas/shop_join.html', {
                'tenant': tenant,
                'errors': ['An unexpected error occurred. Please try again.'],
                'form_data': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'phone': phone or '',
                    'company_name': company_name,
                    'referral_code': referral_code_input,
                },
                'turnstile_site_key': turnstile_site_key,
            })

    return render(request, 'saas/shop_join.html', {
        'tenant': tenant,
        'turnstile_site_key': turnstile_site_key,
        'prefill_referral_code': (request.GET.get('ref') or '').strip().upper(),
    })


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

    new_role = request.POST.get('role', target.role)

    # You can edit your own abilities (e.g. the owner turning on "Does
    # replacements" for themselves) but never your own role.
    if target.user == request.user and new_role != target.role:
        messages.error(request, 'You cannot change your own role.')
        return redirect('owner_settings')

    # Single-service shops ignore the checkboxes — everyone does what the
    # shop does.
    from apps.tenants.services.team_service import resolve_ability_flags
    can_repair, can_replace = resolve_ability_flags(
        tenant,
        request.POST.get('can_repair') == 'on',
        request.POST.get('can_replace') == 'on',
    )

    # Only owners can change roles
    if new_role != target.role and my_membership.role != 'owner':
        messages.error(request, 'Only the shop owner can change member roles.')
        return redirect('owner_settings')

    # Managers can only update technicians — not other managers or owners.
    # Without this check, a manager can POST with role=manager (matching the
    # target's current role so the role-change guard above doesn't fire) and
    # silently modify a peer manager's can_repair/can_replace abilities.
    # Only the shop owner should be able to edit manager or owner records.
    # Editing yourself is exempt — the role-change guard above already fired.
    # (CODE-212)
    if (
        my_membership.role == 'manager'
        and target.role in ('manager', 'owner')
        and target.user != request.user
    ):
        messages.error(request, 'Managers can only update technician team members.')
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
                    # Promotion to a tech role consumes a Technician seat —
                    # enforce the same plan limit as the invite path.
                    from apps.tenants.services.usage_service import UsageService
                    can_add, limit_msg = UsageService(tenant).can_add_technician()
                    if not can_add:
                        messages.warning(request, limit_msg)
                        transaction.set_rollback(True)
                        return redirect('owner_settings')
                    Technician.objects.create(
                        user=target.user,
                        tenant=tenant,
                        is_manager=(new_role == 'manager'),
                        is_active=True,
                        can_repair=can_repair,
                        can_replace=can_replace,
                    )
        elif new_role == 'owner':
            # Owners are usually working technicians too (signup creates the
            # record) — keep their ability flags editable, e.g. the owner
            # turning on "Does replacements" for themselves.
            tech = Technician.objects.filter(user=target.user, tenant=tenant).first()
            if tech:
                tech.can_repair = can_repair
                tech.can_replace = can_replace
                tech.save(update_fields=['can_repair', 'can_replace'])
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
def team_add_self(request):
    """POST /owner/team/add-self/ — make the logged-in owner/manager a working technician.

    Owners of older shops (created before signup auto-added the owner as a
    technician) or anyone whose technician record was deactivated need a way
    to become assignable again. Abilities follow what the shop does.
    """
    tenant, membership = _get_owner_tenant(request)
    if not tenant or not membership:
        messages.error(request, 'Access denied.')
        return redirect('owner_settings')

    from apps.tenants.services.team_service import resolve_ability_flags
    can_repair, can_replace = resolve_ability_flags(tenant)

    tech = Technician.objects.filter(user=request.user, tenant=tenant).first()
    if tech and tech.is_active:
        messages.info(request, 'You are already set up as a technician.')
        return redirect('/owner/settings/?tab=team')

    # Same seat limit as inviting a technician
    from apps.tenants.services.usage_service import UsageService
    can_add, limit_msg = UsageService(tenant).can_add_technician()
    if not can_add:
        messages.warning(request, limit_msg)
        return redirect('/owner/settings/?tab=team')

    if tech:
        # Reactivate the existing record
        tech.is_active = True
        tech.can_repair = can_repair
        tech.can_replace = can_replace
        tech.save(update_fields=['is_active', 'can_repair', 'can_replace'])
    else:
        # Technician.user is a OneToOneField across ALL tenants (CODE-217)
        foreign_tech = Technician.objects.filter(user=request.user).exclude(tenant=tenant).first()
        if foreign_tech:
            messages.warning(
                request,
                'Your account is already linked to a technician profile at another shop, '
                'so it cannot be added here. Invite yourself with a different email instead.'
            )
            return redirect('/owner/settings/?tab=team')
        Technician.objects.create(
            tenant=tenant,
            user=request.user,
            is_manager=(membership.role in ('owner', 'manager')),
            is_active=True,
            can_repair=can_repair,
            can_replace=can_replace,
            phone_number=tenant.business_phone or '',
        )

    from django.contrib.auth.models import Group
    tech_group, _ = Group.objects.get_or_create(name='Technicians')
    request.user.groups.add(tech_group)

    messages.success(request, 'You can now be assigned jobs like any other technician.')
    return redirect('/owner/settings/?tab=team')


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

        from core.email_utils import send_branded_email
        send_branded_email(
            subject=subject,
            recipient_list=[target.user.email],
            headline=f"Reminder: Join {tenant.name}",
            body_paragraphs=[
                f"Hi {target.user.first_name},",
                f"{inviter_name} has re-sent your invitation to join {tenant.name} as a {target.get_role_display()}.",
                "Click the button below to set your password and get started. This link expires in 7 days.",
            ],
            button_text='🚀 Accept Invitation',
            button_url=invite_url,
            tenant=tenant,
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
        # Overdue invoices are the most unpaid of all — excluding them here
        # hid exactly the invoices most worth chasing.
        invoices = invoices.filter(status__in=['SENT', 'PARTIAL', 'DRAFT', 'OVERDUE'])
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

    # AR aging, server-rendered (replaces the old client-side fetch of the
    # JSON endpoint, which showed a spinner on every page load). Only buckets
    # with money in them are passed — the template hides the rest.
    from apps.billing.tasks import generate_aging_report
    _aging = generate_aging_report(tenant_id=tenant.id).get(tenant.slug) or {}
    _aging_data = _aging.get('buckets') or {}
    aging_total = _aging.get('grand_total') or 0
    _bucket_defs = [
        # (key, plain-language label, segment color)
        # Severity ramp: neutral gray for not-yet-due, then light amber to
        # dark red as invoices get older. Hex (not Tailwind classes) so the
        # CSS purge can't drop them.
        ('current', 'Not yet due', '#9ca3af'),
        ('1_30', '1–30 days late', '#fde68a'),
        ('31_60', '31–60 days late', '#f59e0b'),
        ('61_90', '61–90 days late', '#dc2626'),
        ('90_plus', 'Over 90 days late', '#7f1d1d'),
    ]
    aging_buckets = []
    for key, label, color in _bucket_defs:
        b = _aging_data.get(key) or {}
        total = b.get('total') or 0
        if total <= 0:
            continue
        aging_buckets.append({
            'key': key,
            'label': label,
            'color': color,
            'count': b.get('count') or 0,
            'total': total,
            'pct': round(total / aging_total * 100, 1) if aging_total else 0,
        })

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
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
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

    # Same bulk strategy for uninvoiced completed replacements
    _invoiced_replacement_ids = set(
        _ILI.objects.filter(
            replacement__isnull=False,
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
        ).values_list('replacement_id', flat=True)
    )

    _uninvoiced_replacement_qs = (
        Replacement.objects.filter(
            tenant=tenant,
            queue_status='COMPLETED',
            skip_invoicing=False,
        )
        .exclude(id__in=_invoiced_replacement_ids)
        .values('customer_id', 'cost')
    )

    # Group by customer_id (repairs + replacements combined)
    _by_customer: dict = {}
    for row in list(_uninvoiced_qs) + list(_uninvoiced_replacement_qs):
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

    # Default payment terms for invoice creation modal (CODE-153)
    from apps.billing.models import BillingConfig
    try:
        billing_config = BillingConfig.get_for_tenant(tenant)
        default_payment_terms = billing_config.default_payment_terms
    except Exception:
        default_payment_terms = 'COD'
    terms_display = dict(BillingConfig.PAYMENT_TERMS_CHOICES).get(
        default_payment_terms, default_payment_terms
    )

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
        'aging_buckets': aging_buckets,
        'aging_total': aging_total,
        'status_pills': [
            ('all', 'All'),
            ('unpaid', 'Unpaid'),
            ('overdue', 'Overdue'),
            ('partial', 'Partially paid'),
            ('paid', 'Paid'),
        ],
        'uninvoiced_customers': uninvoiced_customers,
        'default_payment_terms': default_payment_terms,
        'default_payment_terms_display': terms_display,
        # For the quick "Record payment" and bulk mark-paid modals
        'payment_methods': [
            choice for choice in Payment.PAYMENT_METHOD_CHOICES
            if choice[0] != 'STRIPE'
        ],
        'today': timezone.now().date(),
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

    # PDF download URL — always the tenant-scoped Django view, never a raw
    # S3 object URL. Invoice keys are predictable and the bucket is private
    # on invoices/*; the view mints a short-TTL presigned URL after the
    # ownership check. (B1)
    pdf_url = reverse('owner_invoice_pdf', args=[invoice.id]) if invoice.s3_key else None

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
        'payment_terms_choices': BillingConfig.PAYMENT_TERMS_CHOICES,
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

    # Where to land afterwards — the invoice detail page by default, or a
    # same-site path passed by the caller (the invoice list's quick-payment
    # modal stays on the list).
    next_url = request.POST.get('next', '')
    if not (next_url.startswith('/') and not next_url.startswith('//')):
        next_url = ''

    def _done():
        return redirect(next_url) if next_url else redirect(
            'owner_invoice_detail', invoice_id=invoice.id
        )

    # Parse and validate fields
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(request.POST.get('amount', '0'))
    except (InvalidOperation, TypeError):
        messages.error(request, 'Invalid amount. Please enter a valid number.')
        return _done()

    payment_method = request.POST.get('payment_method', 'OTHER')
    reference_number = request.POST.get('reference_number', '').strip()
    payment_date_str = request.POST.get('payment_date', '')
    notes = request.POST.get('notes', '').strip()

    # Validate amount
    if amount <= Decimal('0'):
        messages.error(request, 'Payment amount must be greater than zero.')
        return _done()

    if invoice.status in ('PAID', 'CANCELLED'):
        messages.error(request, f'Cannot record payment — invoice is {invoice.get_status_display()}.')
        return _done()

    # Validate payment method
    valid_methods = [c[0] for c in Payment.PAYMENT_METHOD_CHOICES]
    if payment_method not in valid_methods:
        messages.error(request, 'Invalid payment method.')
        return _done()

    # Parse payment date
    from datetime import date
    payment_date = timezone.now().date()
    if payment_date_str:
        try:
            payment_date = date.fromisoformat(payment_date_str)
        except ValueError:
            messages.error(request, 'Invalid payment date.')
            return _done()

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

    return _done()


@owner_or_manager_required
def owner_receive_payment(request):
    """
    GET/POST /owner/payments/receive/ — receive one customer payment and
    apply it across their open invoices (the fleet-check workflow: Penske
    cuts one check that covers four invoices).
    """
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    from decimal import Decimal, InvalidOperation
    from datetime import date
    from django.db.models import Sum, Count

    OPEN_STATUSES = ['SENT', 'PARTIAL', 'OVERDUE', 'DRAFT']

    open_invoices_qs = Invoice.objects.filter(
        customer__tenant=tenant,
        status__in=OPEN_STATUSES,
        deleted_at__isnull=True,
    )

    # Customer picker: everyone with an open balance
    customer_rows = list(
        open_invoices_qs.values('customer_id', 'customer__name')
        .annotate(open_count=Count('id'), outstanding=Sum('total') - Sum('amount_paid'))
        .order_by('customer__name')
    )

    selected_customer = None
    raw_customer = request.POST.get('customer_id') or request.GET.get('customer') or ''
    if raw_customer:
        try:
            selected_customer = Customer.objects.get(tenant=tenant, id=int(raw_customer))
        except (Customer.DoesNotExist, ValueError, TypeError):
            messages.error(request, 'Customer not found.')
            return redirect('owner_receive_payment')

    open_invoices = []
    if selected_customer:
        open_invoices = [
            inv for inv in open_invoices_qs.filter(customer=selected_customer)
            .order_by('due_date', 'invoice_date', 'id')
            if inv.amount_due > 0
        ]

    if request.method == 'POST' and selected_customer:
        def _fail(msg):
            messages.error(request, msg)
            return redirect(f"{reverse('owner_receive_payment')}?customer={selected_customer.id}")

        payment_method = request.POST.get('payment_method', 'OTHER')
        valid_methods = [c[0] for c in Payment.PAYMENT_METHOD_CHOICES]
        if payment_method not in valid_methods:
            return _fail('Invalid payment method.')

        reference_number = request.POST.get('reference_number', '').strip()
        notes = request.POST.get('notes', '').strip()

        payment_date = timezone.now().date()
        if request.POST.get('payment_date'):
            try:
                payment_date = date.fromisoformat(request.POST['payment_date'])
            except ValueError:
                return _fail('Invalid payment date.')

        # Per-invoice allocations
        allocations = {}
        for inv in open_invoices:
            raw = (request.POST.get(f'alloc_{inv.id}') or '').strip()
            if not raw:
                continue
            try:
                val = Decimal(raw)
            except InvalidOperation:
                return _fail(f'Invalid amount for invoice {inv.invoice_number}.')
            if val < 0:
                return _fail(f'Amount for invoice {inv.invoice_number} can\'t be negative.')
            if val > 0:
                allocations[inv.id] = val.quantize(Decimal('0.01'))

        if not allocations:
            return _fail('Apply the payment to at least one invoice.')

        total_alloc = sum(allocations.values(), Decimal('0.00'))

        # The typed payment amount must match what's applied — a mismatch
        # means money would silently vanish or appear.
        try:
            amount = Decimal(request.POST.get('amount', '0')).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            return _fail('Invalid payment amount.')
        if amount != total_alloc:
            return _fail(
                f'Payment amount (${amount}) doesn\'t match the total applied '
                f'to invoices (${total_alloc}). Adjust the amounts so they match.'
            )

        invoice_by_id = {inv.id: inv for inv in open_invoices}
        try:
            with transaction.atomic():
                # Lock in id order (consistent order avoids deadlocks) and
                # re-validate against fresh balances — same TOCTOU guard as
                # owner_record_payment (CODE-056).
                locked = list(
                    Invoice.objects.select_for_update()
                    .filter(id__in=allocations.keys(), customer=selected_customer,
                            deleted_at__isnull=True)
                    .order_by('id')
                )
                if len(locked) != len(allocations):
                    raise ValueError('One of the selected invoices no longer exists.')

                payments = []
                for inv in locked:
                    alloc = allocations[inv.id]
                    if inv.status in ('PAID', 'CANCELLED'):
                        raise ValueError(
                            f'Invoice {inv.invoice_number} is already '
                            f'{inv.get_status_display().lower()}.'
                        )
                    if alloc > inv.amount_due:
                        raise ValueError(
                            f'${alloc} exceeds the remaining balance '
                            f'(${inv.amount_due}) on invoice {inv.invoice_number}.'
                        )
                    payments.append(Payment.objects.create(
                        invoice=inv,
                        amount=alloc,
                        payment_date=payment_date,
                        payment_method=payment_method,
                        reference_number=reference_number,
                        notes=notes,
                        recorded_by=request.user,
                    ))

            # One combined receipt + owner notification (best-effort)
            try:
                from apps.billing.services.payment_notification_service import PaymentNotificationService
                PaymentNotificationService().notify_payment_batch(payments)
            except Exception as e:
                logger.warning(f"Batch payment notification failed: {e}")

            messages.success(
                request,
                f'Payment of ${total_alloc} from {selected_customer.name} recorded '
                f'across {len(payments)} invoice{"s" if len(payments) != 1 else ""}.'
            )
            return redirect(f"{reverse('owner_invoice_list')}?customer={selected_customer.id}")

        except ValueError as e:
            return _fail(str(e))
        except Exception as e:
            logger.error(f"Error receiving payment for customer {selected_customer.id}: {e}")
            return _fail('An error occurred while recording the payment. Please try again.')

    payment_methods = [
        choice for choice in Payment.PAYMENT_METHOD_CHOICES
        if choice[0] != 'STRIPE'
    ]

    context = {
        'tenant': tenant,
        'customer_rows': customer_rows,
        'selected_customer': selected_customer,
        'open_invoices': open_invoices,
        'payment_methods': payment_methods,
        'today': timezone.now().date(),
    }
    return render(request, 'saas/owner_receive_payment.html', context)


# ─── Tax Rate Management ─────────────────────────────────────────────
@owner_or_manager_required
def owner_toggle_tax(request):
    """POST /owner/tax-rates/toggle/ — enable/disable tax for this tenant.

    BillingConfig.tax_enabled is the single source of truth; TaxRate rows
    only hold rates, so there is nothing to sync anymore. Answering the
    toggle counts as configuring tax (dismisses the setup banner).
    """
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=billing')

    tenant, _membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('/owner/settings/?tab=billing')

    try:
        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = not config.tax_enabled
        config.tax_configured = True
        config.save()  # BillingConfig.save() invalidates the TaxService cache

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

    # The whole pipeline (recipient resolution, inline email capture,
    # delivery, mark-SENT-only-on-success) lives in InvoiceSendService so the
    # job-level quick-invoice actions share it.
    from apps.billing.services.invoice_send_service import InvoiceSendService
    copy_to = request.user.email if (
        request.POST.get('send_me_copy') and request.user.email) else None
    result = InvoiceSendService.send(
        invoice, tenant, submitted_email=request.POST.get('email', ''),
        copy_to_email=copy_to,
    )
    if result.sent:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)
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

    if invoice.status == 'CANCELLED':
        messages.error(request, 'Cannot email a cancelled (voided) invoice.')
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
        
        copy_to = request.user.email if (
            request.POST.get('send_me_copy') and request.user.email) else None
        # Pass the Invoice record (A4): the PDF renders from the invoice's
        # own line items and stored totals. The old repair-lookback call here
        # couldn't re-send replacement-only invoices at all ("no completed
        # repairs found") and is exactly what invoice= exists to replace.
        success, msg = email_service.send_invoice_email(
            customer_id=invoice.customer.id,
            recipient_email=recipient,
            invoice=invoice,
            bcc_emails=[copy_to] if copy_to else None,
        )

        if success:
            invoice.record_email_sent(recipient)
            messages.success(request, f'Invoice emailed to {recipient}.')
        else:
            messages.error(request, f'Failed to email invoice: {msg}')
            
    except Exception as e:
        logger.error(f"Error emailing invoice {invoice.invoice_number}: {e}")
        messages.error(request, 'An error occurred while emailing the invoice.')

    return redirect('owner_invoice_detail', invoice_id=invoice.id)


@owner_or_manager_required
@require_POST
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

    # Resolve the actual recipient — prefer CustomerRepairPreference.billing_email
    # over customer.email so fleet customers with a dedicated AP address receive the
    # reminder at the right inbox.  (CODE-128: guard was checking customer.email only,
    # which blocked reminders for customers whose *only* email is billing_email.)
    _reminder_recipient = None
    try:
        _reminder_prefs = invoice.customer.repair_preferences
        _reminder_recipient = _reminder_prefs.billing_email or invoice.customer.email
    except Exception:
        _reminder_recipient = invoice.customer.email

    if not _reminder_recipient:
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
            # Show the actual recipient address so the owner knows where it went
            messages.success(request, f'Payment reminder sent to {_reminder_recipient}.')
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

    def _csv_safe(value):
        """
        Neutralise CSV formula injection.

        Spreadsheet applications (Excel, LibreOffice, Google Sheets) treat a
        cell value as a formula when it starts with '=', '+', '-', or '@'.
        An attacker with control over user-supplied data (e.g. a customer name
        like '=HYPERLINK(...)') could embed a payload that executes when an
        accountant opens the exported file.

        Fix: prefix any cell whose string representation starts with a formula
        trigger character with a single-quote (').  The single-quote is the
        standard spreadsheet escape; it forces the cell to be treated as text.
        Numeric/date/None values are left untouched — only strings are checked.
        (CODE-214)
        """
        if not isinstance(value, str):
            return value
        if value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
            return "'" + value
        return value

    # Sanitise the tenant name used in the filename and header row.
    # A shop name containing a double-quote would break the Content-Disposition
    # header; strip/replace potentially dangerous characters.
    safe_tenant_name = tenant.name.replace('"', '').replace('\n', '').replace('\r', '').replace(' ', '_')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{safe_tenant_name}_AR_Aging_{today}.csv"'
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
            _csv_safe(inv.customer.name),
            _csv_safe(inv.invoice_number),
            inv.invoice_date.strftime('%m/%d/%Y'),
            inv.due_date.strftime('%m/%d/%Y') if inv.due_date else '',
            f'{float(inv.total):.2f}',
            f'{float(inv.amount_paid):.2f}',
            f'{float(amount_due):.2f}',
            inv.get_status_display(),
            max(0, days_old),
            bucket_label[bucket],
            _csv_safe(inv.customer.email or ''),
            _csv_safe(inv.customer.phone or ''),
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

    # All invoices for this customer, oldest first.
    # CODE-264: Add tenant filter for defense-in-depth tenant isolation (same
    # pattern as CODE-255/262 applied to other invoice queries).
    invoices = Invoice.objects.filter(
        customer=customer,
        tenant=tenant,
    ).prefetch_related('payments').order_by('invoice_date', 'created_at')

    # All payments for this customer, chronological.
    # CODE-264: Add tenant filter via invoice__tenant for defense-in-depth.
    # Also exclude payments for soft-deleted invoices: Payment's FK join
    # bypasses InvoiceSoftDeleteManager, so without the deleted_at guard a
    # soft-deleted invoice's payments appear as credits while the matching
    # debit (the invoice itself) is excluded — creating an imbalanced
    # running balance and overstating how much the customer has paid.
    payments = Payment.objects.filter(
        invoice__customer=customer,
        invoice__tenant=tenant,
        invoice__deleted_at__isnull=True,
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
    """Return completion info for each of the setup sections."""
    from apps.billing.models import TaxRate, BillingConfig
    from apps.technician_portal.models import ViscosityRecommendation, Technician
    from apps.tenants.models import InviteToken
    from django.utils import timezone as tz

    try:
        billing_config = BillingConfig.get_for_tenant(tenant)
    except Exception:
        billing_config = None

    has_business_info = bool(tenant.business_phone and tenant.business_email)
    has_customers = Customer.objects.filter(tenant=tenant).exists()
    # "Set up" means the owner explicitly answered the sales-tax question —
    # charging nothing is a perfectly valid answer.
    has_tax = bool(billing_config and billing_config.tax_configured)
    # Resin rules only matter for shops that do repairs.
    has_viscosity = (
        not tenant.offers_repairs
        or ViscosityRecommendation.objects.filter(tenant=tenant, is_active=True).exists()
    )
    has_billing = bool(billing_config and billing_config.default_payment_terms)
    # Team is "set up" once anyone beyond the owner exists or has a pending invite.
    has_team = (
        Technician.objects.filter(tenant=tenant, is_active=True).count() > 1
        or InviteToken.objects.filter(
            tenant=tenant, used_at__isnull=True, expires_at__gt=tz.now()
        ).exists()
    )

    # Items shown in the checklist card; resin rules hidden for shops
    # that don't do repairs.
    items = [has_business_info, has_customers, True, has_tax, has_billing, True, has_team]
    if tenant.offers_repairs:
        items.append(has_viscosity)

    # Defaults genuinely work, so pricing/billing/assignment always count as
    # "complete" — but the checklist should say "Using standard defaults"
    # rather than the false "Configured" when the owner never touched them.
    from decimal import Decimal
    pricing_defaulted = bool(
        tenant.offers_repairs
        and tenant.use_progressive_pricing
        and (
            tenant.repair_price_1, tenant.repair_price_2, tenant.repair_price_3,
            tenant.repair_price_4, tenant.repair_price_5_plus,
        ) == (
            Decimal('50.00'), Decimal('40.00'), Decimal('35.00'),
            Decimal('30.00'), Decimal('25.00'),
        )
    )
    billing_defaulted = not billing_config or billing_config.default_payment_terms == 'COD'
    assignment_defaulted = tenant.assignment_strategy == 'primary_first'

    return {
        'business_info': has_business_info,
        'customers': has_customers,
        'pricing': True,  # always has defaults
        'pricing_defaulted': pricing_defaulted,
        'tax': has_tax,
        'billing': has_billing,
        'billing_defaulted': billing_defaulted,
        'viscosity': has_viscosity,
        'assignment': True,  # always has default
        'assignment_defaulted': assignment_defaulted,
        'team': has_team,
        # has_billing was always True (default_payment_terms defaults 'COD'),
        # so business info is the only genuinely critical item.
        'critical_complete': has_business_info,
        'all_complete': all(items),
        'configured_count': sum(items),
        'total_count': len(items),
    }


def _setup_checklist_items(tenant, completion):
    """
    The ONE itemized setup checklist, rendered on both the owner dashboard
    and the settings page (components/setup_checklist_items.html) so the two
    surfaces can never disagree.

    Each item: label, url, status ('done' | 'defaulted' | 'todo'), todo_label.
    """
    settings_url = reverse('owner_settings')

    def item(label, url, status, todo_label='Not set up'):
        return {'label': label, 'url': url, 'status': status, 'todo_label': todo_label}

    items = [
        item('Business Info', f'{settings_url}?tab=general',
             'done' if completion['business_info'] else 'todo'),
        item('Your First Customer', reverse('create_customer'),
             'done' if completion['customers'] else 'todo',
             'Add one to get started'),
        item('Your Team', f'{settings_url}?tab=team&invite=1',
             'done' if completion['team'] else 'todo',
             'Just you so far'),
        item('Job Prices', f'{settings_url}?tab=billing',
             'defaulted' if completion['pricing_defaulted'] else 'done'),
        item('Sales Tax', f'{settings_url}?tab=billing',
             'done' if completion['tax'] else 'todo'),
        item('Invoicing', f'{settings_url}?tab=billing',
             'defaulted' if completion['billing_defaulted'] else 'done'),
    ]
    if tenant.offers_repairs:
        items.append(item('Repair Resin Rules', reverse('manage_viscosity_rules'),
                          'done' if completion['viscosity'] else 'todo'))
    items.append(item('Job Assignment', f'{settings_url}?tab=general',
                      'defaulted' if completion['assignment_defaulted'] else 'done'))
    return items


@owner_or_manager_required
def owner_setup_view(request):
    """GET /owner/setup/ — retired "Configure Your Shop" accordion.

    The setup sections merged into /owner/settings/ (checklist card + tabs),
    so this URL now just redirects there. The /owner/setup/save/* endpoints
    below stay: they are the save layer for the settings-page viscosity
    toggle and are kept for API/test compatibility.
    """
    return redirect('owner_settings')


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
        state = request.POST.get('state', '').strip().upper()

        # BillingConfig.tax_enabled is the single source of truth; saving
        # here counts as answering the tax question (tax_configured).
        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = tax_enabled
        config.tax_configured = True
        if tax_enabled and total > 0:
            config.state_tax_rate = state_rate
            config.county_tax_rate = county_rate
            config.city_tax_rate = city_rate
            config.special_tax_rate = special_rate
            config.default_tax_rate = total
        config.save()

        # Keep the tenant's single TaxRate row in sync (rates only — the row
        # no longer controls whether tax applies).
        if tax_enabled and total > 0:
            row = TaxRate.objects.filter(tenant=tenant).order_by('-effective_date', '-id').first()
            if row is None:
                row = TaxRate(tenant=tenant)
            row.state_rate = state_rate
            row.county_rate = county_rate
            row.city_rate = city_rate
            row.special_rate = special_rate
            row.is_active = True
            if city:
                row.city = city
            if state:
                row.state = state
            row.save()

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

        # Validate default_payment_terms against canonical choices.
        # An unrecognised value is silently saved to the DB and causes invoice
        # creation to use Django's CharField default instead of the intended
        # terms, producing incorrect due dates.  Mirror the validation applied
        # in owner_settings_view.  (CODE-202)
        raw_terms = request.POST.get('default_payment_terms', 'COD')
        valid_terms = {code for code, _ in BillingConfig.PAYMENT_TERMS_CHOICES}
        if raw_terms not in valid_terms:
            return JsonResponse(
                {'success': False, 'error': f'Invalid payment terms: {raw_terms!r}. '
                                            f'Must be one of: {", ".join(sorted(valid_terms))}.'},
                status=400,
            )

        # Validate batch_invoice_frequency — an unrecognised value is silently
        # saved and causes _should_run_batch_today() to return False forever,
        # so no batch invoices ever run.  The same validation lives in
        # owner_settings_view (CODE-201) but was missing here in the setup
        # wizard endpoint.  (CODE-202)
        raw_freq = request.POST.get('batch_invoice_frequency', 'disabled')
        valid_frequencies = {code for code, _ in BillingConfig.BATCH_FREQUENCY_CHOICES}
        if raw_freq not in valid_frequencies:
            return JsonResponse(
                {'success': False, 'error': f'Invalid batch invoice frequency: {raw_freq!r}. '
                                            f'Must be one of: {", ".join(sorted(valid_frequencies))}.'},
                status=400,
            )

        # Validate batch_invoice_day range based on frequency.
        try:
            batch_day = int(request.POST.get('batch_invoice_day', '1'))
        except (ValueError, TypeError):
            return JsonResponse(
                {'success': False, 'error': 'Batch invoice day must be a number.'},
                status=400,
            )
        if raw_freq in ('weekly', 'biweekly') and not (0 <= batch_day <= 6):
            return JsonResponse(
                {'success': False, 'error': f'Batch invoice day must be 0–6 for weekly/bi-weekly '
                                            f'scheduling (0=Monday … 6=Sunday). Got: {batch_day}.'},
                status=400,
            )
        if raw_freq == 'monthly' and not (1 <= batch_day <= 28):
            return JsonResponse(
                {'success': False, 'error': f'Batch invoice day must be 1–28 for monthly scheduling. '
                                            f'Got: {batch_day}.'},
                status=400,
            )

        config.default_payment_terms = raw_terms
        config.overdue_reminder_enabled = request.POST.get('overdue_reminder_enabled') == '1'
        config.overdue_reminder_days = request.POST.get('overdue_reminder_days', '7,14,30').strip()
        config.batch_invoice_frequency = raw_freq
        config.batch_invoice_day = batch_day
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


def owner_confirm_email(request, uidb64, token):
    """
    GET /confirm-email/<uidb64>/<token>/

    Activate a shop owner account that was created with is_active=False.

    This is the link from the confirmation email sent at signup.  On success:
      - Sets user.is_active = True
      - Logs the user in
      - Redirects to onboarding

    On failure (bad/expired token): shows an error and a link to resend.
    """
    from django.utils.http import urlsafe_base64_decode

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        # Activate the account
        first_activation = not user.is_active
        if first_activation:
            user.is_active = True
            user.save(update_fields=['is_active'])

        # Log the user in (bypass password check — token is the credential here)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        # Find their tenant to set the session
        from apps.tenants.models import TenantMembership
        membership = TenantMembership.objects.filter(
            user=user, role='owner'
        ).select_related('tenant').first()
        if membership:
            request.session['tenant_id'] = membership.tenant.id

        # Welcome email goes out on activation (not at signup — the account
        # isn't usable until now)
        if first_activation and membership:
            try:
                from apps.tenants.views import _send_welcome_email
                plan = membership.tenant.subscription_plan
                _send_welcome_email(user, membership.tenant,
                                    plan.trial_days if plan else 30)
            except Exception as e:
                logger.warning(f"Welcome email failed for {user.email}: {e}")

        messages.success(request, "🎉 You're in! Your free trial has started — let's set up your shop.")
        return redirect('onboarding')

    # Token invalid. If the account is already active, the most common cause
    # is clicking the link a second time (login on first use rotates
    # last_login, which invalidates the token). Don't show a scary error —
    # the account is fine, they just need to log in.
    if user is not None and user.is_active:
        messages.info(request, 'Your email is already confirmed — just log in.')
        return redirect('login')

    return render(request, 'saas/email_confirmation_invalid.html', {
        'uidb64': uidb64,
    })


def owner_confirm_email_verification(request, uidb64, token):
    """
    GET /owner/verify-email/<uidb64>/<token>/

    Process email verification token for a shop owner who is already active.
    This endpoint is used when the owner clicks the verification link from
    the old-style _send_verification_email() helper (e.g. shop_join flow).

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


@ratelimit(key='ip', rate='3/h', method='GET', block=True)
def resend_confirmation_email(request, uidb64):
    """
    GET /confirm-email/<uidb64>/resend/

    Resend the account confirmation email for an inactive account.
    The user must not yet be active (prevents abuse by active users).

    Rate-limited to 3 requests per IP per hour to prevent:
    - Email bombing inactive users
    - SES quota exhaustion (uidb64 is trivially enumerable)
    """
    from django.utils.http import urlsafe_base64_decode

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or user.is_active:
        messages.error(request, 'Invalid request or account already active.')
        return redirect('signup')

    # Find tenant for the email helper
    from apps.tenants.models import TenantMembership
    membership = TenantMembership.objects.filter(user=user).select_related('tenant').first()
    tenant = membership.tenant if membership else None

    email_sent = _send_confirmation_email(request, user, tenant)

    return render(request, 'saas/email_confirmation_sent.html', {
        'email': user.email,
        'first_name': user.first_name,
        'uidb64': uidb64,
        'email_send_failed': not email_sent,
        'resent': True,
    })


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
        # CODE-115: Create a Payment record for each invoice so payment history
        # is complete and paid_at is correctly set via Payment.save() →
        # _update_invoice_totals() → invoice.update_status().
        # Previously this action wrote amount_paid/status directly with no
        # Payment row and no paid_at stamp — payment history tab was empty and
        # the paid_at field was always NULL for bulk-paid invoices.
        from datetime import date as _date
        from django.utils import timezone as _tz

        payment_method = data.get('payment_method') or 'OTHER'
        valid_methods = [c[0] for c in Payment.PAYMENT_METHOD_CHOICES]
        if payment_method not in valid_methods:
            return JsonResponse({'success': False, 'error': 'Invalid payment method.'}, status=400)
        reference_number = (data.get('reference_number') or '').strip()
        payment_date = _tz.now().date()
        if data.get('payment_date'):
            try:
                payment_date = _date.fromisoformat(data['payment_date'])
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid payment date.'}, status=400)

        updated = 0
        payments_by_customer = {}
        payable = invoices.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE', 'DRAFT'])
        for inv in payable.select_related('customer'):
            remaining = inv.amount_due
            if remaining <= 0:
                continue
            try:
                with transaction.atomic():
                    payment = Payment.objects.create(
                        invoice=inv,
                        amount=remaining,
                        payment_method=payment_method,
                        reference_number=reference_number,
                        notes='Marked as paid by shop owner',
                        recorded_by=request.user,
                        payment_date=payment_date,
                    )
                    # Payment.save() → _update_invoice_totals() sets paid_at
                    # and status='PAID' via invoice.update_status(). No manual
                    # status/amount_paid overwrite needed.
            except Exception as e:
                logger.warning(f"Bulk mark_paid: could not create payment for invoice {inv.id}: {e}")
            else:
                updated += 1
                payments_by_customer.setdefault(inv.customer_id, []).append(payment)

        # Receipts: one combined email per customer (the single-invoice
        # Record Payment path sends these too — bulk used to silently skip
        # them, so paying by check got a receipt but bulk mark-paid didn't).
        try:
            from apps.billing.services.payment_notification_service import PaymentNotificationService
            svc = PaymentNotificationService()
            for customer_payments in payments_by_customer.values():
                svc.notify_payment_batch(customer_payments)
        except Exception as e:
            logger.warning(f"Bulk mark_paid: receipt notification failed: {e}")

        return JsonResponse({
            'success': True,
            'message': f'{updated} invoice(s) marked as paid.',
        })

    elif action == 'void':
        # Void invoices that aren't already PAID, CANCELLED, or PARTIAL.
        # (CODE-123) PARTIAL invoices have recorded payments — voiding them
        # silently orphans those Payment records and prevents future deletion
        # (Payment.invoice uses on_delete=PROTECT).  Owners must remove
        # payments first, which demotes the invoice to SENT/OVERDUE, and then
        # they can void it.
        voidable = invoices.exclude(status__in=['PAID', 'PARTIAL', 'CANCELLED'])
        voided_count = voidable.count()
        skipped_paid = invoices.filter(status__in=['PAID', 'CANCELLED']).count()
        skipped_partial = invoices.filter(status='PARTIAL').count()
        voidable.update(status='CANCELLED')
        msg = f'{voided_count} invoice(s) voided.'
        if skipped_paid:
            msg += f' {skipped_paid} paid/already-voided invoice(s) were skipped.'
        if skipped_partial:
            msg += (
                f' {skipped_partial} partially-paid invoice(s) were skipped — '
                'remove the payments first, then void.'
            )
        return JsonResponse({'success': True, 'message': msg})

    elif action == 'delete':
        # Soft-delete any selected invoice, regardless of status.  Payments
        # and line items stay intact so a restore brings everything back;
        # purge_deleted_records hard-deletes (payments included) after 30
        # days.  The jobs on the invoice become re-invoicable immediately —
        # uninvoiced queries ignore line items on soft-deleted invoices.
        deleted_count = invoices.update(deleted_at=timezone.now())

        return JsonResponse({
            'success': True,
            'message': (
                f'{deleted_count} invoice(s) deleted. '
                'You can restore them from Recently Deleted for 30 days.'
            ),
        })

    else:
        return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)


@owner_or_manager_required
def owner_invoice_pdf(request, invoice_id):
    """
    GET /owner/invoices/<id>/pdf/ — serve the invoice PDF, tenant-scoped.

    This view is the ONLY sanctioned way to hand out an invoice PDF (B1):
    the ownership check above the presigned-URL mint is what keeps one
    tenant's invoices unreachable from another tenant's session. Never
    expose raw S3 object URLs in templates — the bucket keys are
    predictable (invoices/<customer_id>/<year>/<number>.pdf) and the
    bucket must stay private on the invoices/ prefix.

    Behavior:
    - archived copy exists (s3_key) and ?fresh is not set: redirect to a
      short-TTL presigned URL for the exact bytes emailed to the customer
    - otherwise: render the stored Invoice record on demand (A4 path —
      the invoice's OWN line items, never a repair lookback)
    """
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)

    force_fresh = 'fresh' in request.GET
    if invoice.s3_key and not force_fresh:
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
        service = InvoiceService(tenant=tenant)
        pdf_bytes, _ = service.generate_invoice_from_record(invoice)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response

    except Exception as e:
        logger.error(f"PDF generation failed for invoice {invoice.invoice_number}: {e}")
        messages.error(request, f'Could not generate PDF: {e}')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)


@owner_or_manager_required
@require_POST
def owner_invoice_void(request, invoice_id):
    """POST /owner/invoices/<id>/void/ — void a single invoice."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No shop found.'}, status=403)

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)

    if invoice.status == 'PAID':
        return JsonResponse({'success': False, 'error': 'Cannot void a paid invoice.'}, status=400)
    if invoice.status == 'CANCELLED':
        return JsonResponse({'success': False, 'error': 'Invoice is already voided.'}, status=400)

    # (CODE-123) Block voiding partially-paid invoices.  A PARTIAL invoice has
    # real money recorded against it; voiding without removing those payments
    # leaves orphaned Payment records that prevent the invoice from ever being
    # deleted and misrepresent the shop's financials.  The owner must delete or
    # reverse the payments first, at which point the invoice reverts to
    # SENT/OVERDUE and can then be voided normally.
    if invoice.status == 'PARTIAL':
        payment_count = invoice.payments.count()
        return JsonResponse(
            {
                'success': False,
                'error': (
                    f'Cannot void a partially-paid invoice. '
                    f'{payment_count} payment(s) are recorded against it. '
                    'Please remove or reverse the payment(s) first, '
                    'then void the invoice.'
                ),
            },
            status=400,
        )

    invoice.status = 'CANCELLED'
    invoice.save(update_fields=['status'])
    return JsonResponse({'success': True, 'message': f'Invoice {invoice.invoice_number} voided.'})


@owner_or_manager_required
def owner_invoice_delete(request, invoice_id):
    """POST /owner/invoices/<id>/delete/ — soft-delete a single invoice.

    Works on any status.  Payments and line items stay intact so the invoice
    can be restored from Recently Deleted for 30 days, after which
    purge_deleted_records hard-deletes it (payments included, S3 PDF cleaned
    up).  Its jobs become re-invoicable immediately.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No shop found.'}, status=403)

    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)

    invoice.deleted_at = timezone.now()
    invoice.save(update_fields=['deleted_at'])

    return JsonResponse({
        'success': True,
        'message': (
            f'Invoice {invoice.invoice_number} deleted. '
            'You can restore it from Recently Deleted for 30 days.'
        ),
    })


@owner_or_manager_required
def owner_generate_invoice_from_repair(request, repair_id):
    """
    POST /owner/invoices/generate-from-repair/<repair_id>/
    
    One-click invoice generation from the repair detail page.
    Creates a draft invoice for the repair, then redirects to the invoice
    detail page where the owner can review, edit, and send.
    """
    if request.method != 'POST':
        messages.error(request, 'Invalid request.')
        return redirect('technician_dashboard')

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('technician_dashboard')

    from apps.technician_portal.models import Repair
    repair = get_object_or_404(Repair, id=repair_id, tenant=tenant)

    # Validate: must be completed
    if repair.queue_status != 'COMPLETED':
        messages.error(request, 'Only completed repairs can be invoiced.')
        return redirect('repair_detail', repair_id=repair.id)

    # Multi-break batch: include ALL sibling repairs from the same batch.
    # A multi-break job (e.g. 3 chips on one windshield) creates separate Repair
    # records sharing the same repair_batch_id. Invoicing only the clicked repair
    # would miss the other breaks and undercharge. (CODE-226)
    if repair.repair_batch_id:
        all_batch_repairs = list(
            Repair.objects.filter(
                tenant=tenant,
                repair_batch_id=repair.repair_batch_id,
            ).order_by('break_number')
        )
        batch_repairs = [r for r in all_batch_repairs if r.queue_status == 'COMPLETED']
        # CODE-247: Warn if some siblings are not yet completed
        excluded_count = len(all_batch_repairs) - len(batch_repairs)
        if excluded_count > 0:
            messages.warning(
                request,
                f'{excluded_count} of {len(all_batch_repairs)} batch repairs are not yet completed '
                f'and were excluded from this invoice.'
            )
    else:
        batch_repairs = [repair]

    # Validate: not already invoiced (check all repairs in the batch)
    from apps.billing.models import InvoiceLineItem
    already_invoiced_repair = None
    for r in batch_repairs:
        if InvoiceLineItem.objects.filter(
            repair=r,
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
        ).exists():
            already_invoiced_repair = r
            break

    if already_invoiced_repair:
        line_item = InvoiceLineItem.objects.filter(
            repair=already_invoiced_repair,
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
        ).select_related('invoice').first()
        existing_invoice = line_item.invoice

        # CODE-249: If the existing invoice is a DRAFT and this is a batch,
        # check if any batch siblings are missing from the invoice. This happens
        # when the invoice was created before the batch fix (CODE-226) — only 1
        # repair was included. Auto-add missing siblings to the draft invoice.
        if existing_invoice.status == 'DRAFT' and repair.repair_batch_id:
            invoiced_repair_ids = set(
                InvoiceLineItem.objects.filter(invoice=existing_invoice)
                .values_list('repair_id', flat=True)
            )
            missing_repairs = [r for r in batch_repairs if r.id not in invoiced_repair_ids]

            if missing_repairs:
                from decimal import Decimal as D
                for mr in missing_repairs:
                    discounted = mr.get_discounted_cost()
                    pricing_info = mr.get_progressive_pricing_info()
                    
                    if pricing_info['is_discounted']:
                        prog_savings = pricing_info['base_rate'] - pricing_info['actual_cost']
                        unit_price = pricing_info['base_rate']
                        total_disc = prog_savings + discounted['savings']
                        amount = unit_price - total_disc
                    else:
                        unit_price = discounted['original_cost']
                        total_disc = discounted['savings']
                        amount = discounted['final_cost']
                    
                    description = mr.get_invoice_description()
                    if pricing_info['is_discounted']:
                        description += " [multi-break rate]"
                    
                    InvoiceLineItem.objects.create(
                        invoice=existing_invoice,
                        repair=mr,
                        description=description,
                        quantity=1,
                        unit_price=unit_price,
                        discount=total_disc,
                        amount=amount,
                        repair_date=mr.repair_date.date() if mr.repair_date else None,
                        unit_number=mr.unit_number,
                        taxable=not mr.no_tax and not mr.customer.tax_exempt,
                    )

                    from apps.billing.services.invoice_sync import create_charge_lines
                    create_charge_lines(existing_invoice, mr)

                # Recalculate invoice totals
                all_line_items = InvoiceLineItem.objects.filter(invoice=existing_invoice)
                existing_invoice.subtotal = sum(li.unit_price for li in all_line_items)
                existing_invoice.discount = sum(li.discount for li in all_line_items)
                existing_invoice.total = existing_invoice.subtotal - existing_invoice.discount

                # Re-apply tax — on the taxable lines only
                try:
                    from apps.billing.services.tax_service import TaxService
                    tax_svc = TaxService(tenant=existing_invoice.tenant)
                    taxable_base = sum(
                        (li.amount for li in all_line_items if li.taxable), D('0.00'))
                    tax_svc.apply_tax_to_invoice(existing_invoice, taxable_base=taxable_base)
                except Exception:
                    pass

                existing_invoice.save()
                messages.success(
                    request,
                    f'Added {len(missing_repairs)} missing batch repair(s) to existing invoice '
                    f'{existing_invoice.invoice_number}. Review below.'
                )
                return redirect('owner_invoice_detail', invoice_id=existing_invoice.id)

        # If invoice is not DRAFT but batch has missing siblings, warn the user
        if existing_invoice.status != 'DRAFT' and repair.repair_batch_id:
            invoiced_repair_ids = set(
                InvoiceLineItem.objects.filter(invoice=existing_invoice)
                .values_list('repair_id', flat=True)
            )
            missing_count = sum(1 for r in batch_repairs if r.id not in invoiced_repair_ids)
            if missing_count > 0:
                messages.warning(
                    request,
                    f'This invoice is missing {missing_count} batch repair(s) but cannot be '
                    f'auto-updated because it\'s already {existing_invoice.get_status_display()}. '
                    f'Void this invoice and regenerate to include all batch repairs.'
                )

        messages.info(request, 'This repair (or part of its batch) has already been invoiced.')
        return redirect('owner_invoice_detail', invoice_id=existing_invoice.id)

    # Generate the invoice — accept optional payment_terms override (CODE-153)
    req_payment_terms = request.POST.get('payment_terms') or None
    if req_payment_terms:
        from apps.billing.models import BillingConfig
        valid_terms = {code for code, _label in BillingConfig.PAYMENT_TERMS_CHOICES}
        if req_payment_terms not in valid_terms:
            req_payment_terms = None  # fall back to default

    try:
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        tracking_svc = InvoiceTrackingService(tenant=tenant)
        invoice = tracking_svc.create_invoice_from_repairs(
            customer=repair.customer,
            repairs=batch_repairs,
            payment_terms=req_payment_terms,
        )
        repair_count = len(batch_repairs)
        if repair_count > 1:
            messages.success(request, f'Invoice {invoice.invoice_number} created for {repair_count} repairs (multi-break batch). Review and send below.')
        else:
            messages.success(request, f'Invoice {invoice.invoice_number} created as draft. Review and send below.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('repair_detail', repair_id=repair.id)
    except Exception as e:
        logger.error(f"Error generating invoice from repair {repair_id}: {e}", exc_info=True)
        messages.error(request, 'Could not generate invoice. Please try again.')
        return redirect('repair_detail', repair_id=repair.id)


@owner_or_manager_required
def owner_generate_invoice_from_replacement(request, replacement_id):
    """
    POST /owner/invoices/generate-from-replacement/<replacement_id>/

    One-click invoice generation from the replacement detail page.
    Creates a draft invoice for the replacement, then redirects to the invoice
    detail page where the owner can review, edit, and send.
    """
    if request.method != 'POST':
        messages.error(request, 'Invalid request.')
        return redirect('technician_dashboard')

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('technician_dashboard')

    replacement = get_object_or_404(Replacement, id=replacement_id, tenant=tenant)

    # Validate: must be completed
    if replacement.queue_status != 'COMPLETED':
        messages.error(request, 'Only completed replacements can be invoiced.')
        return redirect('replacement_detail', pk=replacement.id)

    # Validate: not already invoiced
    from apps.billing.models import InvoiceLineItem
    line_item = InvoiceLineItem.objects.filter(
        replacement=replacement,
        invoice__tenant=tenant,
        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
    ).select_related('invoice').first()
    if line_item:
        messages.info(request, 'This replacement has already been invoiced.')
        return redirect('owner_invoice_detail', invoice_id=line_item.invoice.id)

    # Generate the invoice — accept optional payment_terms override (CODE-153)
    req_payment_terms = request.POST.get('payment_terms') or None
    if req_payment_terms:
        from apps.billing.models import BillingConfig
        valid_terms = {code for code, _label in BillingConfig.PAYMENT_TERMS_CHOICES}
        if req_payment_terms not in valid_terms:
            req_payment_terms = None  # fall back to default

    try:
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        tracking_svc = InvoiceTrackingService(tenant=tenant)
        invoice = tracking_svc.create_invoice_from_services(
            customer=replacement.customer,
            services=[replacement],
            payment_terms=req_payment_terms,
        )
        messages.success(request, f'Invoice {invoice.invoice_number} created as draft. Review and send below.')
        return redirect('owner_invoice_detail', invoice_id=invoice.id)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('replacement_detail', pk=replacement.id)
    except Exception as e:
        logger.error(f"Error generating invoice from replacement {replacement_id}: {e}", exc_info=True)
        messages.error(request, 'Could not generate invoice. Please try again.')
        return redirect('replacement_detail', pk=replacement.id)


# ──────────────────────────────────────────────────────────────────────────────
# Loyalty Phase 2: Manual Point Adjustment + Point Liability Report
# (CODE-197)
# ──────────────────────────────────────────────────────────────────────────────

@owner_or_manager_required
@require_POST
def owner_loyalty_adjust_points(request, customer_id):
    """
    POST /owner/loyalty/customers/<customer_id>/adjust/

    Manually award or deduct loyalty points for a specific customer
    (company). Restricted to owners and managers of the same tenant.

    Form fields:
        amount  (int, non-zero — positive = award, negative = deduct)
        reason  (str, required — stored in PointTransaction.description)

    Returns JSON:
        { "success": true, "new_balance": 450, "transaction_id": 99 }
      or
        { "success": false, "error": "..." }
    """
    from apps.rewards_referrals.services import LoyaltyService
    from core.models import Customer

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Unauthorized.'}, status=403)

    # Unscoped get_object_or_404 is forbidden — always include tenant= scoping.
    # Default manager: soft-deleted customers are not adjustable.
    try:
        customer = Customer.objects.get(pk=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Customer not found.'}, status=404)

    # Parse and validate inputs
    try:
        raw_amount = request.POST.get('amount', '')
        amount = int(raw_amount)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Amount must be a non-zero integer.'}, status=400)

    reason = request.POST.get('reason', '').strip()

    try:
        pt = LoyaltyService.manual_adjustment(
            customer=customer,
            amount=amount,
            reason=reason,
            created_by=request.user,
            tenant=tenant,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        logger.error('owner_loyalty_adjust_points: unexpected error for customer=%s: %s', customer_id, exc, exc_info=True)
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred.'}, status=500)

    return JsonResponse({
        'success': True,
        'new_balance': pt.balance_after,
        'transaction_id': pt.pk,
        'amount': pt.amount,
        'description': pt.description,
    })


@owner_or_manager_required
def owner_loyalty_liability_report(request):
    """
    GET /owner/loyalty/liability/

    JSON endpoint returning the point liability report for the authenticated
    owner's tenant. Restricted to owners and managers.

    Response:
        {
            "tenant_name": "Rockstar Windshield Repair",
            "total_outstanding_points": 1200,
            "total_issued_lifetime": 5400,
            "total_redeemed_lifetime": 3800,
            "total_expired_lifetime": 200,
            "total_manually_adjusted": 100,
            "active_customer_count": 7,
            "customers": [
                {
                    "customer_id": 3,
                    "email": "fleet@eos.com",
                    "customer_name": "EOS Trucking",
                    "current_balance": 450,
                    "lifetime_earned": 1200,
                    "lifetime_redeemed": 700,
                    "lifetime_expired": 50,
                },
                ...
            ]
        }
    """
    from apps.rewards_referrals.services import LoyaltyService

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    report = LoyaltyService.get_point_liability_report(tenant)
    report['tenant_name'] = tenant.name

    return JsonResponse(report)


# ──────────────────────────────────────────────────────────────────────────────
# Loyalty Dashboard — Owner HTML Page
# ──────────────────────────────────────────────────────────────────────────────

@owner_or_manager_required
def owner_loyalty_dashboard(request):
    """
    GET  /owner/loyalty/          — render the loyalty dashboard
    POST /owner/loyalty/config/   — handled separately (see owner_loyalty_save_config)
    """
    from apps.rewards_referrals.services import LoyaltyService
    from apps.rewards_referrals.models import (
        LoyaltyConfig, PointTransaction, RewardOption, RewardRedemption,
    )
    from django.db.models import Sum, Q
    from django.utils import timezone

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return redirect('owner_dashboard')

    # Liability report (customer list + totals)
    report = LoyaltyService.get_point_liability_report(tenant)

    # Points awarded this month
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    points_this_month = (
        PointTransaction.objects
        .filter(tenant=tenant, created_at__gte=month_start, amount__gt=0)
        .aggregate(total=Sum('amount'))['total'] or 0
    )

    config = LoyaltyConfig.get_for_tenant(tenant)

    # Reward catalog (all options, including hidden — owners manage them here)
    reward_options = (
        RewardOption.objects
        .filter(tenant=tenant)
        .select_related('reward_type')
        .order_by('points_required')
    )

    # Open redemptions awaiting fulfillment — cancellable while PENDING
    pending_redemptions = (
        RewardRedemption.objects
        .filter(reward__customer__tenant=tenant, status='PENDING')
        .select_related(
            'reward__customer', 'reward_option',
            'applied_to_repair', 'applied_to_replacement',
        )
        .order_by('-created_at')[:50]
    )

    ctx = {
        'tenant': tenant,
        'report': report,
        'points_this_month': points_this_month,
        'config': config,
        'reward_options': reward_options,
        'pending_redemptions': pending_redemptions,
    }
    return render(request, 'saas/owner_loyalty.html', ctx)


@owner_or_manager_required
@require_POST
def owner_loyalty_save_config(request):
    """
    POST /owner/loyalty/config/
    Save LoyaltyConfig fields: is_active, points_per_repair,
    points_expiry_days, show_balance_in_emails.
    """
    from apps.rewards_referrals.models import LoyaltyConfig

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Unauthorized.'}, status=403)

    config = LoyaltyConfig.get_for_tenant(tenant)

    errors = []

    # Toggles
    config.is_active = request.POST.get('is_active') == 'true'
    if 'show_balance_in_emails' in request.POST:
        config.show_balance_in_emails = request.POST.get('show_balance_in_emails') == 'true'
    if 'auto_apply_rewards' in request.POST:
        config.auto_apply_rewards = request.POST.get('auto_apply_rewards') == 'true'

    # points_per_repair
    try:
        ppr = int(request.POST.get('points_per_repair', config.points_per_repair))
        if ppr < 0:
            raise ValueError
        config.points_per_repair = ppr
    except (ValueError, TypeError):
        errors.append('Points per repair must be a non-negative integer.')

    # points_expiry_days
    try:
        ped = int(request.POST.get('points_expiry_days', config.points_expiry_days))
        if ped < 0:
            raise ValueError
        config.points_expiry_days = ped
    except (ValueError, TypeError):
        errors.append('Points expiry days must be a non-negative integer (0 = never).')

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    config.save()
    return JsonResponse({
        'success': True,
        'is_active': config.is_active,
        'points_per_repair': config.points_per_repair,
        'points_expiry_days': config.points_expiry_days,
        'show_balance_in_emails': config.show_balance_in_emails,
        'auto_apply_rewards': config.auto_apply_rewards,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Reward Option CRUD + Redemption Cancel (owner/manager only)
# ──────────────────────────────────────────────────────────────────────────────

# Owner-facing "kind" choices → (RewardType.category, RewardType.discount_type).
# Kept deliberately simple: the four shapes a shop reward actually takes.
REWARD_KIND_MAP = {
    'percent': ('REPAIR_DISCOUNT', 'PERCENTAGE'),
    'fixed': ('REPAIR_DISCOUNT', 'FIXED_AMOUNT'),
    'free': ('FREE_SERVICE', 'FREE'),
    'merch': ('MERCHANDISE', 'NONE'),
}


def _resolve_reward_type(kind, value):
    """
    Map an owner-facing reward kind + value to a RewardType row.

    RewardType is a shared (non-tenant) lookup table, so identical shapes are
    reused across shops via get_or_create on (category, discount_type, value).
    Returns (RewardType, None) or (None, error message).
    """
    from decimal import Decimal, InvalidOperation
    from apps.rewards_referrals.models import RewardType

    if kind not in REWARD_KIND_MAP:
        return None, 'Invalid reward type.'
    category, discount_type = REWARD_KIND_MAP[kind]

    if kind in ('percent', 'fixed'):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None, 'Discount value must be a number.'
        if kind == 'percent' and not (0 < value <= 100):
            return None, 'Percentage discount must be between 1 and 100.'
        if kind == 'fixed' and value <= 0:
            return None, 'Dollar discount must be greater than zero.'
    else:
        value = 0

    if kind == 'percent':
        name = f'{value.normalize()}% Off Service'
        description = f'{value.normalize()}% discount applied to a job'
    elif kind == 'fixed':
        name = f'${value.normalize()} Off Service'
        description = f'${value.normalize()} discount applied to a job'
    elif kind == 'free':
        name = 'Free Service'
        description = 'One job free of charge'
    else:
        name = 'Merchandise / Other'
        description = 'Fulfilled by the shop outside of job pricing'

    reward_type, _created = RewardType.objects.get_or_create(
        category=category,
        discount_type=discount_type,
        discount_value=value,
        defaults={'name': name, 'description': description, 'is_active': True},
    )
    return reward_type, None


def _parse_reward_option_form(request):
    """Validate the shared create/edit form. Returns (data dict, errors list)."""
    errors = []
    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    kind = request.POST.get('kind', '')

    if not name:
        errors.append('Name is required.')

    try:
        points_required = int(request.POST.get('points_required', ''))
        if points_required <= 0:
            raise ValueError
    except (ValueError, TypeError):
        points_required = None
        errors.append('Point cost must be a positive whole number.')

    reward_type = None
    if not errors:
        reward_type, type_error = _resolve_reward_type(
            kind, request.POST.get('discount_value', '0'),
        )
        if type_error:
            errors.append(type_error)

    return {
        'name': name,
        'description': description,
        'points_required': points_required,
        'reward_type': reward_type,
        'is_active': request.POST.get('is_active', 'on') == 'on',
    }, errors


@owner_or_manager_required
@require_POST
def owner_reward_option_create(request):
    """POST /owner/loyalty/options/create/ — add a reward option."""
    from apps.rewards_referrals.models import RewardOption

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    data, errors = _parse_reward_option_form(request)
    if errors:
        messages.error(request, ' '.join(errors))
        return redirect('owner_loyalty_dashboard')

    RewardOption.objects.create(
        tenant=tenant,
        name=data['name'],
        description=data['description'] or data['name'],
        points_required=data['points_required'],
        reward_type=data['reward_type'],
        is_active=data['is_active'],
    )
    messages.success(request, f'Reward "{data["name"]}" added.')
    return redirect('owner_loyalty_dashboard')


@owner_or_manager_required
@require_POST
def owner_reward_option_edit(request, option_id):
    """POST /owner/loyalty/options/<id>/edit/ — update a reward option."""
    from apps.rewards_referrals.models import RewardOption

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    option = get_object_or_404(RewardOption, pk=option_id, tenant=tenant)

    data, errors = _parse_reward_option_form(request)
    if errors:
        messages.error(request, ' '.join(errors))
        return redirect('owner_loyalty_dashboard')

    option.name = data['name']
    option.description = data['description'] or data['name']
    option.points_required = data['points_required']
    option.reward_type = data['reward_type']
    option.is_active = data['is_active']
    option.save()
    messages.success(request, f'Reward "{option.name}" updated.')
    return redirect('owner_loyalty_dashboard')


@owner_or_manager_required
@require_POST
def owner_reward_option_toggle(request, option_id):
    """POST /owner/loyalty/options/<id>/toggle/ — flip is_active."""
    from apps.rewards_referrals.models import RewardOption

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    option = get_object_or_404(RewardOption, pk=option_id, tenant=tenant)
    option.is_active = not option.is_active
    option.save(update_fields=['is_active', 'updated_at'])
    state = 'active' if option.is_active else 'hidden from customers'
    messages.success(request, f'Reward "{option.name}" is now {state}.')
    return redirect('owner_loyalty_dashboard')


@owner_or_manager_required
@require_POST
def owner_reward_option_delete(request, option_id):
    """
    POST /owner/loyalty/options/<id>/delete/ — remove a reward option.

    RewardRedemption.reward_option is CASCADE, so deleting an option that has
    ever been redeemed would erase redemption history. Those options are
    deactivated instead; hard delete is reserved for never-used options.
    """
    from apps.rewards_referrals.models import RewardOption, RewardRedemption

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    option = get_object_or_404(RewardOption, pk=option_id, tenant=tenant)

    if RewardRedemption.objects.filter(reward_option=option).exists():
        option.is_active = False
        option.save(update_fields=['is_active', 'updated_at'])
        messages.info(
            request,
            f'"{option.name}" has past redemptions, so it was hidden instead of '
            'deleted (deleting it would erase that history).',
        )
    else:
        name = option.name
        option.delete()
        messages.success(request, f'Reward "{name}" deleted.')
    return redirect('owner_loyalty_dashboard')


@owner_or_manager_required
@require_POST
def owner_loyalty_cancel_redemption(request, redemption_id):
    """
    POST /owner/loyalty/redemptions/<id>/cancel/ — cancel a pending
    redemption and refund the points (the only sanctioned undo path).
    """
    from apps.rewards_referrals.services import RewardService

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    success, message = RewardService.cancel_redemption(
        redemption_id,
        tenant,
        cancelled_by=request.user,
        reason=request.POST.get('reason', ''),
    )
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect('owner_loyalty_dashboard')


# ─────────────────────────────────────────────
# Warranty Policy CRUD (owner/manager only)
# ─────────────────────────────────────────────

@owner_or_manager_required
def owner_warranty_create(request):
    """POST /owner/settings/warranty/create/ — create a new warranty policy."""
    if request.method != 'POST':
        return redirect('/owner/settings/?tab=warranty')

    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    name = request.POST.get('name', '').strip()
    applies_to = request.POST.get('applies_to', 'repairs')
    duration_type = request.POST.get('duration_type', 'custom_days')
    coverage_description = request.POST.get('coverage_description', '').strip()
    is_active = request.POST.get('is_active') == 'on'
    is_default = request.POST.get('is_default') == 'on'
    covers_labor = request.POST.get('covers_labor') == 'on'
    covers_materials = request.POST.get('covers_materials') == 'on'

    try:
        duration_days = int(request.POST.get('duration_days', 365))
    except (ValueError, TypeError):
        duration_days = 365

    # Validate applies_to
    valid_applies = [c[0] for c in WarrantyPolicy.APPLIES_TO_CHOICES]
    if applies_to not in valid_applies:
        messages.error(request, 'Invalid "Applies To" value.')
        return redirect('/owner/settings/?tab=warranty')

    # Validate duration_type
    valid_duration_types = [c[0] for c in WarrantyPolicy.WARRANTY_DURATION_CHOICES]
    if duration_type not in valid_duration_types:
        messages.error(request, 'Invalid "Duration Type" value.')
        return redirect('/owner/settings/?tab=warranty')

    if not name:
        messages.error(request, 'Policy name is required.')
        return redirect('/owner/settings/?tab=warranty')

    try:
        WarrantyPolicy.objects.create(
            tenant=tenant,
            name=name,
            applies_to=applies_to,
            duration_type=duration_type,
            duration_days=duration_days,
            coverage_description=coverage_description,
            is_active=is_active,
            is_default=is_default,
            covers_labor=covers_labor,
            covers_materials=covers_materials,
        )
        messages.success(request, f'Warranty policy "{name}" created.')
    except Exception as e:
        logger.error(f"Error creating warranty policy: {e}")
        messages.error(request, f'Could not create policy: {e}')

    return redirect('/owner/settings/?tab=warranty')


@owner_or_manager_required
def owner_warranty_edit(request, policy_id):
    """POST /owner/settings/warranty/<id>/edit/ — update an existing warranty policy."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    policy = get_object_or_404(WarrantyPolicy, pk=policy_id, tenant=tenant)

    if request.method != 'POST':
        return redirect('/owner/settings/?tab=warranty')

    name = request.POST.get('name', '').strip()
    applies_to = request.POST.get('applies_to', policy.applies_to)
    duration_type = request.POST.get('duration_type', policy.duration_type)
    coverage_description = request.POST.get('coverage_description', '').strip()
    is_active = request.POST.get('is_active') == 'on'
    is_default = request.POST.get('is_default') == 'on'
    covers_labor = request.POST.get('covers_labor') == 'on'
    covers_materials = request.POST.get('covers_materials') == 'on'

    try:
        duration_days = int(request.POST.get('duration_days', policy.duration_days))
    except (ValueError, TypeError):
        duration_days = policy.duration_days

    valid_applies = [c[0] for c in WarrantyPolicy.APPLIES_TO_CHOICES]
    if applies_to not in valid_applies:
        messages.error(request, 'Invalid "Applies To" value.')
        return redirect('/owner/settings/?tab=warranty')

    # Validate duration_type
    valid_duration_types = [c[0] for c in WarrantyPolicy.WARRANTY_DURATION_CHOICES]
    if duration_type not in valid_duration_types:
        messages.error(request, 'Invalid "Duration Type" value.')
        return redirect('/owner/settings/?tab=warranty')

    if not name:
        messages.error(request, 'Policy name is required.')
        return redirect('/owner/settings/?tab=warranty')

    try:
        policy.name = name
        policy.applies_to = applies_to
        policy.duration_type = duration_type
        policy.duration_days = duration_days
        policy.coverage_description = coverage_description
        policy.is_active = is_active
        policy.is_default = is_default
        policy.covers_labor = covers_labor
        policy.covers_materials = covers_materials
        policy.save()
        messages.success(request, f'Warranty policy "{name}" updated.')
    except Exception as e:
        logger.error(f"Error updating warranty policy {policy_id}: {e}")
        messages.error(request, f'Could not update policy: {e}')

    return redirect('/owner/settings/?tab=warranty')


@owner_or_manager_required
def owner_warranty_toggle(request, policy_id):
    """POST /owner/settings/warranty/<id>/toggle/ — soft toggle is_active."""
    tenant, membership = _get_owner_tenant(request)
    if not tenant:
        messages.error(request, 'No shop found.')
        return redirect('signup')

    policy = get_object_or_404(WarrantyPolicy, pk=policy_id, tenant=tenant)

    if request.method != 'POST':
        return redirect('/owner/settings/?tab=warranty')

    policy.is_active = not policy.is_active
    policy.save(update_fields=['is_active'])
    status = 'activated' if policy.is_active else 'deactivated'
    messages.success(request, f'Policy "{policy.name}" {status}.')
    return redirect('/owner/settings/?tab=warranty')
