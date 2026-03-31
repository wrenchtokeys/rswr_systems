from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
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
        try:
            from django_ratelimit.core import is_ratelimited
            if is_ratelimited(request, key='ip', rate='30/h', method='POST',
                              group='login_router'):
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

        # Find user by email or username
        User = get_user_model()
        login_id_lower = login_id.lower()
        try:
            user_obj = User.objects.get(email=login_id_lower)
        except User.DoesNotExist:
            try:
                # Try username (case-insensitive)
                user_obj = User.objects.get(username__iexact=login_id)
            except User.DoesNotExist:
                user_obj = None

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

                if not Technician.objects.filter(user=user, tenant=invite.tenant).exists():
                    Technician.objects.create(
                        tenant=invite.tenant,
                        user=user,
                        is_manager=(invite.role == 'manager'),
                        is_active=True,
                        can_repair=True,
                        can_replace=False,
                    )
                else:
                    tech = Technician.objects.get(user=user, tenant=invite.tenant)
                    if invite.role == 'manager':
                        tech.is_manager = True
                        tech.save()

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
    """
    import hmac as hmac_mod
    expected = generate_payment_token(invoice_id)
    if not hmac_mod.compare_digest(token, expected):
        return render(request, '404.html', status=404)

    from apps.billing.models import Invoice
    try:
        invoice = Invoice.objects.select_related('customer', 'tenant').get(id=invoice_id)
    except Invoice.DoesNotExist:
        return render(request, '404.html', status=404)

    if invoice.status == 'PAID':
        return render(request, 'billing/payment_complete.html')

    if invoice.amount_due <= 0:
        return render(request, 'billing/payment_complete.html')

    # Try to create a Stripe Checkout session
    checkout_url = None
    error_msg = None
    tenant = invoice.tenant

    if tenant and tenant.can_accept_payments:
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
    else:
        # Try platform Stripe (non-Connect)
        try:
            from apps.billing.services.stripe_service import StripeService
            svc = StripeService()
            if svc.is_enabled():
                base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
                result = svc.create_checkout_session(
                    invoice,
                    success_url=f"{base_url}/payment-complete?session={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{base_url}/pay/{invoice_id}/{token}/",
                )
                if result.get('checkout_url'):
                    checkout_url = result['checkout_url']
        except Exception as e:
            logger.warning(f"Could not create platform checkout: {e}")
            error_msg = "Online payments are temporarily unavailable. Please contact the shop directly."

    # If we got a checkout URL, redirect immediately
    if checkout_url:
        return redirect(checkout_url)

    # Otherwise show an info page
    context = {
        'invoice': invoice,
        'error_msg': error_msg or "Online payments are not yet available for this shop. Please contact them directly to arrange payment.",
        'company_name': tenant.name if tenant else 'RS Systems',
        'company_phone': tenant.business_phone if tenant else '',
    }
    return render(request, 'billing/public_pay_unavailable.html', context)


def payment_complete(request):
    """Landing page after successful Stripe checkout."""
    session_id = request.GET.get('session')
    if session_id:
        logger.info(f"Payment complete landing — Stripe session: {session_id}")
    return render(request, 'billing/payment_complete.html')


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
        ('https://rssystems.io/login/', '0.5', 'monthly'),
        ('https://rssystems.io/register/', '0.8', 'monthly'),
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
