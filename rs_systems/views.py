from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from apps.technician_portal.forms import TechnicianRegistrationForm
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
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
    # The root page is now a marketing landing page
    # No automatic redirects for authenticated users
    return render(request, 'landing.html')

def customer_login_view(request):
    """Legacy customer login — redirects to unified login."""
    return redirect('login')

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


@ratelimit(key='ip', rate='30/h', method='POST')
def login_router(request):
    """Unified login page — authenticates user and routes to appropriate portal."""
    from apps.tenants.models import TenantMembership

    # Already authenticated? Route them.
    if request.user.is_authenticated:
        dest = _route_authenticated_user(request, request.user)
        if dest:
            return dest
        # Fallback for authenticated users with no clear destination
        from common.auth import redirect_to_portal
        return redirect_to_portal(request.user)

    context = {
        'next': request.GET.get('next', ''),
    }

    if request.method == 'POST':
        # Check rate limit
        if getattr(request, 'limited', False):
            context['error'] = 'Too many login attempts. Please try again later.'
            return render(request, 'saas/login.html', context)

        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        context['email'] = email

        if not email or not password:
            context['error'] = 'Please enter both email and password.'
            return render(request, 'saas/login.html', context)

        # Find user by email (username is email in our system)
        User = get_user_model()
        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            try:
                user_obj = User.objects.get(username=email)
            except User.DoesNotExist:
                user_obj = None

        if user_obj is None:
            # Log failed attempt
            from apps.security.models import LoginAttempt
            LoginAttempt.log_attempt(request, email, False, 'unified', 'User not found')
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
            LoginAttempt.log_attempt(request, email, False, 'unified', 'Invalid credentials')
            context['error'] = 'Invalid email or password.'
            return render(request, 'saas/login.html', context)

        # Log successful login
        from apps.security.models import LoginAttempt
        LoginAttempt.log_attempt(request, email, True, 'unified')

        login(request, user)

        # Check for ?next= redirect
        next_url = request.POST.get('next', '') or request.GET.get('next', '')
        if next_url:
            return redirect(next_url)

        # Route based on role
        dest = _route_authenticated_user(request, user)
        if dest:
            return dest

        # No membership and not a customer — show error
        logout(request)
        context['error'] = 'No shop account found. Please contact your shop owner or sign up for a new account.'
        context['email'] = email
        return render(request, 'saas/login.html', context)

    return render(request, 'saas/login.html', context)

@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')

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
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        if len(password) < 8:
            context['error'] = 'Password must be at least 8 characters long.'
            return render(request, 'saas/invite_accept.html', context)

        if password != password_confirm:
            context['error'] = 'Passwords do not match.'
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

                if not Technician.objects.filter(user=user).exists():
                    Technician.objects.create(
                        tenant=invite.tenant,
                        user=user,
                        is_manager=(invite.role == 'manager'),
                        is_active=True,
                        can_repair=True,
                        can_replace=False,
                    )
                else:
                    tech = Technician.objects.get(user=user)
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

@csrf_exempt
def setup_database(request):
    """Setup database with migrations and create superuser"""
    if request.method != 'POST':
        return HttpResponse("""
        <html>
        <body>
            <h1>Database Setup</h1>
            <p>Click the button below to set up the database:</p>
            <form method="post">
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
        
        # Create superuser if it doesn't exist
        User = get_user_model()
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='admin123'
            )
            print("Superuser 'admin' created successfully")
        else:
            print("Superuser 'admin' already exists")
        
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
        <p><a href="/admin/">Go to Admin</a> (username: admin, password: admin123)</p>
    </body>
    </html>
    """)


def payment_complete(request):
    """Landing page after successful Stripe checkout."""
    session_id = request.GET.get('session')
    if session_id:
        logger.info(f"Payment complete landing — Stripe session: {session_id}")
    return render(request, 'billing/payment_complete.html')


def payment_cancelled(request):
    """Landing page when customer cancels Stripe checkout."""
    return render(request, 'billing/payment_cancelled.html')
