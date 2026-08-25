import base64
import re

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils.http import url_has_allowed_host_and_scheme
from apps.technician_portal.forms import TechnicianRegistrationForm
from django.contrib import messages
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.conf import settings
import logging

logger = logging.getLogger(__name__)
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
import io
import sys

def health_check(request):
    """Health check endpoint for AWS load balancer - bypasses ALLOWED_HOSTS"""
    try:
        # Simple database connectivity test
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        return JsonResponse({
            'status': 'healthy',
            'database': 'connected'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy', 
            'error': str(e)
        }, status=500)

def home(request):
    # Authenticated users go to their portal, visitors see landing page
    if request.user.is_authenticated:
        dest = _route_authenticated_user(request, request.user)
        if dest:
            return dest
        if request.user.is_staff:
            return redirect('/admin/')
        return redirect('owner_dashboard')
    
    # Fetch subscription plans for landing page pricing section
    from apps.tenants.models import SubscriptionPlan
    plans = SubscriptionPlan.objects.filter(
        is_active=True
    ).exclude(
        slug='trial'  # Don't show trial as a pricing option
    ).order_by('display_order')
    
    return render(request, 'landing.html', {'plans': plans})

@never_cache
def customer_login_view(request):
    """Legacy customer login — redirects to unified login."""
    return redirect('login')

@never_cache
def technician_login_view(request):
    """Legacy technician login — redirects to unified login."""
    return redirect('login')

def _route_authenticated_user(request, user):
    """Route an authenticated user to the appropriate portal based on their role.
    Returns a redirect response or None if no valid destination found."""
    from apps.customer_portal.models import CustomerUser
    from apps.technician_portal.models import Technician
    from apps.tenants.models import TenantMembership

    # Check TenantMembership first for role-based routing
    membership = (
        TenantMembership.objects
        .filter(user=user, is_active=True)
        .select_related('tenant')
        .order_by(
            models.Case(
                models.When(role='owner', then=0),
                models.When(role='manager', then=1),
                models.When(role='technician', then=2),
                models.When(role='viewer', then=3),
                default=4,
                output_field=models.IntegerField(),
            )
        )
        .first()
    )

    if membership:
        request.session['tenant_id'] = membership.tenant.id
        if membership.role in ('owner', 'manager'):
            return redirect('owner_dashboard')
        elif membership.role == 'technician':
            return redirect('technician_dashboard')
        elif membership.role == 'viewer':
            # Viewers could be customers (joined via /join/) or read-only staff.
            # Check for CustomerUser first — customers go to customer portal.
            try:
                customer_user = CustomerUser.objects.get(user=user)
                if customer_user.customer.tenant_id:
                    request.session['tenant_id'] = customer_user.customer.tenant_id
                return redirect('customer_dashboard')
            except CustomerUser.DoesNotExist:
                # Read-only staff viewer — send to owner dashboard (read-only)
                return redirect('owner_dashboard')

    # Check if user is a CustomerUser without a TenantMembership
    try:
        customer_user = CustomerUser.objects.get(user=user)
        if customer_user.customer.tenant_id:
            request.session['tenant_id'] = customer_user.customer.tenant_id
        return redirect('customer_dashboard')
    except CustomerUser.DoesNotExist:
        pass

    return None


@never_cache
def login_router(request):
    """Unified login page — authenticates user and routes to appropriate portal."""
    from apps.tenants.models import TenantMembership

    # Already authenticated? Route them (never redirect back to login).
    if request.user.is_authenticated:
        dest = _route_authenticated_user(request, request.user)
        if dest:
            return dest
        # Fallback: staff go to admin, everyone else to owner dashboard
        if request.user.is_staff:
            return redirect('/admin/')
        return redirect('owner_dashboard')

    context = {
        'next': request.GET.get('next', ''),
    }

    if request.method == 'POST':
        # Rate limiting — uses cache backend, wrapped in try/except so a
        # cache misconfiguration never takes down login entirely.
        # increment=True is required: without it the counter never advances
        # and the limit can never trigger.
        try:
            from django_ratelimit.core import is_ratelimited
            limited_by_ip = is_ratelimited(
                request, key='ip', rate='30/h', method='POST',
                group='login_router', increment=True,
            )
            # Per-account limit — blunts password spraying against a single
            # account from many IPs.
            limited_by_account = is_ratelimited(
                request, key='post:email', rate='10/15m', method='POST',
                group='login_router_account', increment=True,
            )
            if limited_by_ip or limited_by_account:
                context['error'] = 'Too many login attempts. Please try again later.'
                return render(request, 'saas/login.html', context)
        except Exception:
            # Cache backend unavailable — log but don't block login
            logger.warning("Rate limiting unavailable (cache backend error)")
            pass

        login_id = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        context['email'] = login_id

        if not login_id or not password:
            context['error'] = 'Please enter your username or email and password.'
            return render(request, 'saas/login.html', context)

        # Find user by email or username. Use filter().first() rather than
        # get() — User.email has no DB-level unique constraint, so duplicate
        # (or mixed-case) emails would make get() raise MultipleObjectsReturned
        # and turn a login attempt into a 500.
        User = get_user_model()
        email_matches = User.objects.filter(email__iexact=login_id).order_by('id')
        if len(email_matches) > 1:
            logger.warning(f"Duplicate email on login: {login_id} matches {len(email_matches)} users")
        user_obj = email_matches.first()
        if user_obj is None:
            user_obj = User.objects.filter(username__iexact=login_id).order_by('id').first()

        if user_obj is None:
            # Log failed attempt
            from apps.security.models import LoginAttempt
            LoginAttempt.log_attempt(request, login_id, False, 'unified', 'User not found')
            context['error'] = 'Invalid email or password.'
            return render(request, 'saas/login.html', context)

        # Check if user has an unusable password (invited but not yet accepted)
        if not user_obj.has_usable_password():
            context['error'] = 'Your account has not been set up yet. Please check your email for an invite link, or contact your shop owner.'
            return render(request, 'saas/login.html', context)

        # Unconfirmed signup — ModelBackend rejects inactive users, so without
        # this check they'd see "Invalid email or password" after entering the
        # correct one. Only reveal the unconfirmed state when the password is
        # right, so this can't be used to enumerate accounts.
        if not user_obj.is_active:
            if user_obj.check_password(password):
                from django.utils.encoding import force_bytes
                from django.utils.http import urlsafe_base64_encode
                uidb64 = urlsafe_base64_encode(force_bytes(user_obj.pk))
                context['error'] = 'Your email address has not been confirmed yet. Please check your inbox for the confirmation link.'
                context['resend_url'] = f'/confirm-email/{uidb64}/resend/'
            else:
                from apps.security.models import LoginAttempt
                LoginAttempt.log_attempt(request, login_id, False, 'unified', 'Invalid credentials')
                context['error'] = 'Invalid email or password.'
            return render(request, 'saas/login.html', context)

        # Authenticate
        user = authenticate(request, username=user_obj.username, password=password)
        if user is None:
            from apps.security.models import LoginAttempt
            LoginAttempt.log_attempt(request, login_id, False, 'unified', 'Invalid credentials')
            context['error'] = 'Invalid email or password.'
            return render(request, 'saas/login.html', context)

        # Log successful login
        from apps.security.models import LoginAttempt
        LoginAttempt.log_attempt(request, login_id, True, 'unified')

        login(request, user)

        # Session lifetime: expires at browser close unless "remember me"
        # was checked (shop computers are often shared).
        if request.POST.get('remember_me'):
            request.session.set_expiry(60 * 60 * 24 * 30)  # 30 days
        else:
            request.session.set_expiry(0)  # browser session

        # Check for ?next= redirect (validate to prevent open redirect attacks)
        next_url = request.POST.get('next', '') or request.GET.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure()
        ):
            return redirect(next_url)

        # Route based on role
        dest = _route_authenticated_user(request, user)
        if dest:
            return dest

        # No membership and not a customer — show error
        logout(request)
        context['error'] = 'No shop account found. Please contact your shop owner or sign up for a new account.'
        context['email'] = login_id
        return render(request, 'saas/login.html', context)

    return render(request, 'saas/login.html', context)

@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


class RateLimitedPasswordResetView(auth_views.PasswordResetView):
    """
    PasswordResetView with an IP rate limit. Unlimited POSTs here mean
    email-bombing arbitrary users and burning SES quota.
    """

    def post(self, request, *args, **kwargs):
        try:
            from django_ratelimit.core import is_ratelimited
            if is_ratelimited(request, key='ip', rate='5/h', method='POST',
                              group='password_reset', increment=True):
                form = self.get_form()
                form.add_error(None, 'Too many password reset requests. Please try again later.')
                return self.form_invalid(form)
        except Exception:
            # Cache backend unavailable — don't block password resets
            logger.warning("Rate limiting unavailable for password reset (cache backend error)")
        return super().post(request, *args, **kwargs)

@ratelimit(key='ip', rate='20/h', method='POST', block=False)
def accept_invite(request, token):
    """Accept an invite token — set password and join the shop."""
    from apps.tenants.models import InviteToken, TenantMembership
    from apps.technician_portal.models import Technician
    from django.contrib.auth.models import Group
    from django.db import transaction

    try:
        invite = InviteToken.objects.select_related('tenant', 'user').get(token=token)
    except InviteToken.DoesNotExist:
        return render(request, 'saas/invite_accept.html', {'invite_valid': False})

    if not invite.is_valid:
        return render(request, 'saas/invite_accept.html', {'invite_valid': False})

    context = {
        'invite_valid': True,
        'shop_name': invite.tenant.name,
        'role_display': invite.get_role_display(),
    }

    if request.method == 'POST':
        # Check rate limit
        if getattr(request, 'limited', False):
            context['error'] = 'Too many attempts. Please try again later.'
            return render(request, 'saas/invite_accept.html', context)

        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        if password != password_confirm:
            context['error'] = 'Passwords do not match.'
            return render(request, 'saas/invite_accept.html', context)

        # Use Django's password validators instead of simple length check
        try:
            validate_password(password, user=invite.user)
        except ValidationError as e:
            context['error'] = ' '.join(e.messages)
            return render(request, 'saas/invite_accept.html', context)

        with transaction.atomic():
            user = invite.user
            user.set_password(password)
            user.save()

            invite.used_at = timezone.now()
            invite.save()

            # Ensure Technician record exists for technician/manager roles
            if invite.role in ('technician', 'manager'):
                tech_group, _ = Group.objects.get_or_create(name='Technicians')
                user.groups.add(tech_group)

                # Technician.user is a OneToOneField across ALL tenants —
                # never steal (or crash on) another tenant's record (CODE-217).
                from apps.tenants.services.team_service import resolve_ability_flags
                foreign_tech = (
                    Technician.objects.filter(user=user)
                    .exclude(tenant=invite.tenant).first()
                )
                existing_tech = Technician.objects.filter(
                    user=user, tenant=invite.tenant
                ).first()
                if existing_tech:
                    if invite.role == 'manager':
                        existing_tech.is_manager = True
                        existing_tech.save()
                elif foreign_tech:
                    logger.warning(
                        "accept_invite: user %s already has a Technician record "
                        "for tenant %s — cannot create one for tenant %s.",
                        user.id, foreign_tech.tenant_id, invite.tenant_id,
                    )
                else:
                    # Abilities follow the shop's services (a replacement-only
                    # shop must not get a repair-only tech).
                    can_repair, can_replace = resolve_ability_flags(invite.tenant)
                    Technician.objects.create(
                        tenant=invite.tenant,
                        user=user,
                        is_manager=(invite.role == 'manager'),
                        is_active=True,
                        can_repair=can_repair,
                        can_replace=can_replace,
                    )

        # Log the user in
        auth_user = authenticate(request, username=user.username, password=password)
        if auth_user:
            login(request, auth_user)
            request.session['tenant_id'] = invite.tenant.id

        messages.success(request, f'Welcome to {invite.tenant.name}! Your account is ready.')

        # Route to appropriate portal
        dest = _route_authenticated_user(request, auth_user or user)
        if dest:
            return dest
        from common.auth import redirect_to_portal
        return redirect_to_portal(auth_user or user)

    return render(request, 'saas/invite_accept.html', context)


@staff_member_required
def register_technician(request):
    if request.method == 'POST':
        form = TechnicianRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Account created for {user.username}')
            return redirect('admin:index')
    else:
        form = TechnicianRegistrationForm()
    return render(request, 'registration/register_technician.html', {'form': form})

@staff_member_required
def setup_database(request):
    """
    Setup database with migrations and create superuser.

    SECURITY: Only available in DEBUG mode and requires staff authentication.
    This endpoint should never be exposed in production.
    """
    # Block in production - this endpoint should only be used in development
    if not settings.DEBUG:
        logger.warning(
            f"setup_database accessed in production by {request.user.username} "
            f"from {request.META.get('REMOTE_ADDR', 'unknown')}"
        )
        return HttpResponseNotFound("Not Found")

    if request.method != 'POST':
        return HttpResponse("""
        <html>
        <body>
            <h1>Database Setup (Development Only)</h1>
            <p>Click the button below to set up the database:</p>
            <form method="post">
                {% csrf_token %}
                <button type="submit">Setup Database</button>
            </form>
        </body>
        </html>
        """)

    # Capture output
    output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = output

    try:
        # Run migrations
        call_command('migrate', verbosity=1, interactive=False)
        print("Migrations completed successfully")

        # Create superuser if it doesn't exist - use environment variables only
        import os
        User = get_user_model()
        admin_username = os.environ.get('DJANGO_ADMIN_USERNAME', 'admin')
        admin_email = os.environ.get('DJANGO_ADMIN_EMAIL', 'admin@example.com')
        admin_password = os.environ.get('DJANGO_ADMIN_PASSWORD')

        if admin_password:
            if not User.objects.filter(username=admin_username).exists():
                User.objects.create_superuser(
                    username=admin_username,
                    email=admin_email,
                    password=admin_password
                )
                print(f"Superuser '{admin_username}' created successfully")
            else:
                print(f"Superuser '{admin_username}' already exists")
        else:
            print("DJANGO_ADMIN_PASSWORD not set - skipping superuser creation")

        # Collect static files
        call_command('collectstatic', verbosity=1, interactive=False)
        print("Static files collected successfully")

        print("Database setup completed!")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        sys.stdout = old_stdout

    result = output.getvalue()

    return HttpResponse(f"""
    <html>
    <body>
        <h1>Database Setup Results</h1>
        <pre>{result}</pre>
        <p><a href="/">Return to Home</a></p>
        <p><a href="/admin/">Go to Admin</a></p>
    </body>
    </html>
    """)


def generate_payment_token(invoice_id):
    """Generate an HMAC token for public invoice payment links."""
    import hmac, hashlib
    secret = settings.SECRET_KEY
    message = f"pay-invoice-{invoice_id}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]


def public_pay_invoice(request, invoice_id, token):
    """
    Public payment page — no login required.
    Token is HMAC-derived from invoice ID + SECRET_KEY, so URLs are unforgeable.

    GET renders a confirm page; only the POST from that page creates the
    Stripe Checkout session. Mail security gateways GET every link in an
    email while scanning it — creating a Checkout session on GET meant every
    scanned invoice email spawned a real Stripe session.
    """
    invoice = _resolve_public_invoice(invoice_id, token, request=request)
    if invoice is None:
        return render(request, '404.html', status=404)

    if invoice.status == 'PAID' or invoice.amount_due <= 0:
        return render(
            request, 'billing/payment_complete.html',
            _payment_complete_context(invoice, 'paid'),
        )

    tenant = invoice.tenant

    if not (tenant and tenant.can_accept_payments):
        # No Connect account: never fall back to a platform-account charge —
        # the money would settle in the platform's Stripe balance, not the
        # shop's. Show the contact-the-shop page instead.
        context = {
            'invoice': invoice,
            'error_msg': "Online payments are not yet available for this shop. Please contact them directly to arrange payment.",
            'company_name': tenant.name if tenant else 'RS Systems',
            'company_phone': tenant.business_phone if tenant else '',
        }
        return render(request, 'billing/public_pay_unavailable.html', context)

    if request.method == 'POST':
        # Human clicked "Continue to secure payment" — create the session.
        checkout_url = None
        error_msg = None
        try:
            from apps.tenants.services.connect_service import ConnectService
            connect_svc = ConnectService()
            base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
            result = connect_svc.create_connected_checkout_session(
                invoice,
                success_url=f"{base_url}/payment-complete?session={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}/pay/{invoice_id}/{token}/",
            )
            if result.get('checkout_url'):
                checkout_url = result['checkout_url']
        except Exception as e:
            logger.warning(f"Could not create checkout for public pay page: {e}")
            error_msg = "Online payments are temporarily unavailable. Please contact the shop directly."

        if checkout_url:
            return redirect(checkout_url)
        context = {
            'invoice': invoice,
            'error_msg': error_msg or "Online payments are temporarily unavailable. Please contact the shop directly.",
            'company_name': tenant.name if tenant else 'RS Systems',
            'company_phone': tenant.business_phone if tenant else '',
        }
        return render(request, 'billing/public_pay_unavailable.html', context)

    # GET: confirm page (no Stripe side effects).
    context = {
        'invoice': invoice,
        'company_name': tenant.name if tenant else 'RS Systems',
        'company_phone': tenant.business_phone if tenant else '',
        'view_url': f"/invoice/{invoice.id}/{token}/",
    }
    return render(request, 'billing/public_pay_confirm.html', context)


# Mail security gateways (Microsoft Defender Safe Links, Proofpoint,
# Mimecast, Barracuda...) fetch every link in an email while scanning it.
# Their fetches must not count as the customer viewing the invoice — that
# phantom "viewed" signal is worse than no signal.
_SCANNER_UA_RE = re.compile(
    r'bot|crawl|spider|preview|scan|monitor|fetch|probe|validator|checker'
    r'|python|curl|wget|libwww|okhttp|headless|phantom|slurp'
    r'|proofpoint|mimecast|barracuda|defender|safelinks|urldefense',
    re.IGNORECASE,
)


def _is_scanner_request(request):
    """Heuristic: does this request look like a mail-gateway scanner?"""
    if request is None:
        return False
    if request.method not in ('GET',):
        return True
    ua = request.META.get('HTTP_USER_AGENT', '')
    if not ua:
        return True
    return bool(_SCANNER_UA_RE.search(ua))


def _resolve_public_invoice(invoice_id, token, request=None, record_view=True):
    """Token-check + fetch for public invoice pages; None if either fails.

    A successful resolve counts as the customer viewing the invoice ONLY
    when it looks like a human click: scanner user-agents are ignored, and
    so is anything within INVOICE_VIEW_GRACE_SECONDS of the send — security
    gateways detonate emailed links seconds after delivery.
    """
    import hmac as hmac_mod
    expected = generate_payment_token(invoice_id)
    if not hmac_mod.compare_digest(token, expected):
        return None
    from apps.billing.models import Invoice
    try:
        invoice = Invoice.objects.select_related('customer', 'tenant').get(id=invoice_id)
    except Invoice.DoesNotExist:
        return None
    try:
        if record_view and not _is_scanner_request(request):
            grace = getattr(settings, 'INVOICE_VIEW_GRACE_SECONDS', 300)
            recently_sent = (
                invoice.last_sent_at is not None
                and (timezone.now() - invoice.last_sent_at).total_seconds() < grace
            )
            if not recently_sent:
                invoice.mark_viewed()
    except Exception as e:
        logger.warning(f"Could not record invoice view for {invoice_id}: {e}")
    return invoice


def public_view_invoice(request, invoice_id, token):
    """
    Public invoice VIEW page — no login required.

    This is where "View Invoice Online" in invoice emails lands: a summary of
    the invoice with a PDF download and (when payable) a Pay button. The
    email's "Pay Invoice" button goes straight to /pay/ (Stripe Checkout)
    instead — the two links used to be the same URL.
    """
    invoice = _resolve_public_invoice(invoice_id, token, request=request)
    if invoice is None:
        return render(request, '404.html', status=404)

    tenant = invoice.tenant
    can_pay = (
        invoice.status not in ('PAID', 'CANCELLED')
        and invoice.amount_due > 0
        # No Pay button unless the shop can actually take online payments
        # (active Stripe Connect) — the /pay/ page would dead-end otherwise.
        and bool(tenant and tenant.can_accept_payments)
    )

    # Repair photos live here, not as email attachments — multi-MB photo
    # payloads get invoice emails quarantined at corporate mail gateways.
    photos = []
    try:
        repair_items = invoice.line_items.exclude(repair_id__isnull=True).select_related('repair')
        for item in repair_items:
            repair = item.repair
            if not repair:
                continue
            for field, label in (
                (repair.damage_photo_before, 'Before'),
                (repair.damage_photo_after, 'After'),
                (repair.customer_submitted_photo, 'Customer submitted'),
            ):
                if field:
                    try:
                        photos.append({
                            'unit': repair.unit_number,
                            'label': label,
                            'url': field.url,
                        })
                    except Exception:
                        continue
    except Exception as e:
        logger.warning(f"Could not load photos for public invoice {invoice_id}: {e}")

    # First-party SMS opt-in (toll-free registration requires consent from
    # the customer's own screen, not shop attestation). Offered to every
    # customer, with a number field when the shop has no usable mobile on
    # file — most invoices are emailed and `Customer.phone` is optional, so
    # gating the card on a stored phone hid it from the majority of the
    # people whose consent the carrier wants. Deliberately NOT gated on
    # SMSService.is_enabled(), so consent can be collected (and the surface
    # screenshotted for carrier review) while the number awaits approval.
    from core.services.sms_service import SMSService
    customer = invoice.customer
    sms_phone = SMSService.normalize_phone(customer.phone) if customer else ''

    context = {
        'invoice': invoice,
        'line_items': invoice.line_items.all(),
        'company_name': tenant.name if tenant else 'RS Systems',
        'company_phone': tenant.business_phone if tenant else '',
        'company_email': tenant.business_email if tenant else '',
        'can_pay': can_pay,
        'pay_url': f"/pay/{invoice.id}/{token}/",
        'pdf_url': f"/invoice/{invoice.id}/{token}/pdf/",
        'photos': photos,
        'sms_optin_offered': customer is not None,
        'sms_optin_phone_last4': sms_phone[-4:] if sms_phone else '',
        'sms_opted_in': bool(customer and customer.sms_opt_in),
        'sms_optin_url': f"/invoice/{invoice.id}/{token}/sms-opt-in/",
        'sms_optin_state': request.GET.get('sms', ''),
    }
    return render(request, 'billing/public_invoice_view.html', context)


@require_POST
def public_invoice_sms_opt_in(request, invoice_id, token):
    """First-party SMS consent from the public invoice page (same token).

    Records CUSTOMER-source consent on the invoice's customer — the
    carrier-compliant opt-in surface for toll-free registration v2."""
    from core.services.sms_service import SMSService

    invoice = _resolve_public_invoice(invoice_id, token, request=request, record_view=False)
    if invoice is None:
        return render(request, '404.html', status=404)

    view_url = f"/invoice/{invoice.id}/{token}/"
    customer = invoice.customer
    if customer is None:
        return redirect(view_url)

    on_file = SMSService.normalize_phone(customer.phone)
    # No usable mobile on file: the customer supplies one here. Their own
    # entry is the strongest form of first-party consent, and it is only
    # ever written when the shop has nothing usable — a public token must
    # not overwrite a number the shop already has.
    submitted = SMSService.normalize_phone(request.POST.get('sms_phone', ''))
    if not on_file and not submitted:
        return redirect(f"{view_url}?sms=badphone#sms-updates")
    if request.POST.get('sms_agree') != '1':
        return redirect(f"{view_url}?sms=missing#sms-updates")

    if not on_file:
        customer.phone = submitted
        customer.save(update_fields=['phone'])
        logger.info(
            f"Customer {customer.id} supplied a mobile number via public "
            f"invoice {invoice.id} while opting in to texts"
        )
    customer.record_sms_consent(source=customer.SMS_CONSENT_CUSTOMER)
    logger.info(
        f"First-party SMS opt-in recorded for customer {customer.id} "
        f"via public invoice {invoice.id}"
    )
    return redirect(f"{view_url}?sms=thanks#sms-updates")


def public_invoice_pdf(request, invoice_id, token):
    """Inline PDF of the invoice for the public view page (same token)."""
    invoice = _resolve_public_invoice(invoice_id, token, request=request)
    if invoice is None:
        return render(request, '404.html', status=404)

    from apps.billing.services.invoice_service import InvoiceService
    try:
        pdf_bytes, _ = InvoiceService(tenant=invoice.tenant).generate_invoice_from_record(invoice)
    except Exception as e:
        logger.error(f"Public invoice PDF render failed for {invoice_id}: {e}")
        return render(request, '404.html', status=404)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Invoice_{invoice.invoice_number}.pdf"'
    return response


# 1x1 transparent GIF, the classic email open-tracking pixel.
_TRACKING_PIXEL = base64.b64decode(
    'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
)


def public_invoice_open_pixel(request, invoice_id, token):
    """Legacy email open-tracking pixel endpoint.

    New invoice emails no longer embed the pixel — mail security gateways
    (Microsoft Defender etc.) prefetch it while scanning, producing phantom
    "viewed" counts, and a remote 1x1 image is itself a spam-filter signal.
    The endpoint stays alive so already-sent emails don't render a broken
    image, but it never records a view: delivery is tracked via SES events,
    views via genuine invoice-page opens.
    """
    response = HttpResponse(_TRACKING_PIXEL, content_type='image/gif')
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def payment_complete(request):
    """Landing page after successful Stripe checkout.

    This page is a recovery path, not just a thank-you: when the customer
    lands here we verify the checkout session with Stripe and record the
    payment immediately if the webhook hasn't already — so the invoice
    flips to PAID even if webhook delivery is broken. The page then shows
    the SHOP's identity and the invoice's real status, never an unverified
    platform-branded "payment received" claim.
    """
    session_id = request.GET.get('session', '')
    invoice, state = None, 'unknown'
    if session_id:
        logger.info(f"Payment complete landing — Stripe session: {session_id}")
        try:
            from apps.billing.services.stripe_reconcile import resolve_session
            invoice, state = resolve_session(session_id)
        except Exception:
            logger.warning(
                f"payment_complete could not resolve session {session_id}",
                exc_info=True,
            )

    return render(
        request, 'billing/payment_complete.html',
        _payment_complete_context(invoice, state),
    )


def _payment_complete_context(invoice, state):
    tenant = getattr(invoice, 'tenant', None)
    receipt_pdf_url = None
    if invoice is not None:
        from apps.billing.pay_links import public_invoice_pdf_url
        receipt_pdf_url = public_invoice_pdf_url(invoice)
    return {
        'invoice': invoice,
        'state': state,  # 'paid' | 'processing' | 'unknown'
        'company_name': tenant.name if tenant else 'RS Systems',
        'company_phone': (tenant.business_phone or '') if tenant else '',
        'company_email': (tenant.business_email or '') if tenant else 'contact@rssystems.io',
        'receipt_pdf_url': receipt_pdf_url,
    }


def payment_cancelled(request):
    """Landing page when customer cancels Stripe checkout."""
    return render(request, 'billing/payment_cancelled.html')



def robots_txt(request):
    """robots.txt for search engine crawlers."""
    content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/
Disallow: /clawdbot/
Disallow: /setup-database/
Disallow: /portal/
Disallow: /owner/
Disallow: /customer/

Sitemap: https://rssystems.io/sitemap.xml
"""
    return HttpResponse(content.strip(), content_type='text/plain')


def sitemap_xml(request):
    """Basic XML sitemap for search engines."""
    urls = [
        ('https://rssystems.io/', '1.0', 'weekly'),
        ('https://rssystems.io/pricing/', '0.8', 'monthly'),
        ('https://rssystems.io/signup/', '0.8', 'monthly'),
        ('https://rssystems.io/login/', '0.5', 'monthly'),
        ('https://rssystems.io/sms/', '0.3', 'monthly'),
    ]
    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, priority, freq in urls:
        xml_lines.append(f'  <url>')
        xml_lines.append(f'    <loc>{loc}</loc>')
        xml_lines.append(f'    <changefreq>{freq}</changefreq>')
        xml_lines.append(f'    <priority>{priority}</priority>')
        xml_lines.append(f'  </url>')
    xml_lines.append('</urlset>')
    return HttpResponse('\n'.join(xml_lines), content_type='application/xml')


def custom_404(request, exception=None):
    """Custom 404 handler — branded page instead of bare Django 404 (BUG-004)."""
    return render(request, '404.html', status=404)


def custom_500(request):
    """Custom 500 handler — branded page instead of bare Django 500 (BUG-004)."""
    return render(request, '500.html', status=500)
