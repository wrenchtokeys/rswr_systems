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
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import connection
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

@ratelimit(key='ip', rate='10/h', method='POST')
def customer_login_view(request):
    """Login view specifically for customers"""
    if request.user.is_authenticated:
        return redirect('customer_dashboard')

    # Check if rate limited
    if getattr(request, 'limited', False):
        messages.error(request, "Too many login attempts. Please try again in an hour.")
        return render(request, 'customer_login.html', {'form': AuthenticationForm(), 'portal_type': 'customer'})

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        username = request.POST.get('username', '')

        if form.is_valid():
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                # Verify user is a customer
                from apps.customer_portal.models import CustomerUser
                try:
                    customer_user = CustomerUser.objects.get(user=user)
                    # Log successful login
                    from apps.security.models import LoginAttempt
                    LoginAttempt.log_attempt(request, username, True, 'customer')
                    login(request, user)
                    next_url = request.GET.get('next', 'customer_dashboard')
                    return redirect(next_url)
                except CustomerUser.DoesNotExist:
                    # Log failed attempt - wrong portal
                    from apps.security.models import LoginAttempt
                    LoginAttempt.log_attempt(request, username, False, 'customer', 'Not a customer account')
                    messages.error(request, "This account is not authorized for customer access.")
            else:
                # Log failed attempt - bad credentials
                from apps.security.models import LoginAttempt
                LoginAttempt.log_attempt(request, username, False, 'customer', 'Invalid credentials')
        else:
            # Log failed attempt - form validation failed
            if username:
                from apps.security.models import LoginAttempt
                LoginAttempt.log_attempt(request, username, False, 'customer', 'Form validation failed')
    else:
        form = AuthenticationForm()

    return render(request, 'customer_login.html', {'form': form, 'portal_type': 'customer'})

@ratelimit(key='ip', rate='10/h', method='POST')
def technician_login_view(request):
    """Login view specifically for technicians"""
    if request.user.is_authenticated:
        from apps.technician_portal.models import Technician
        try:
            technician = Technician.objects.get(user=request.user)
            return redirect('technician_dashboard')
        except Technician.DoesNotExist:
            pass

    # Check if rate limited
    if getattr(request, 'limited', False):
        messages.error(request, "Too many login attempts. Please try again in an hour.")
        return render(request, 'technician_login.html', {'form': AuthenticationForm(), 'portal_type': 'technician'})

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                # Verify user is a technician
                from apps.technician_portal.models import Technician
                try:
                    technician = Technician.objects.get(user=user)
                    login(request, user)
                    next_url = request.GET.get('next', 'technician_dashboard')
                    return redirect(next_url)
                except Technician.DoesNotExist:
                    messages.error(request, "This account is not authorized for technician access.")
    else:
        form = AuthenticationForm()

    return render(request, 'technician_login.html', {'form': form, 'portal_type': 'technician'})

def login_router(request):
    """Legacy login URL that redirects to appropriate portal based on user role."""
    # Check if user is already authenticated
    if request.user.is_authenticated:
        from apps.customer_portal.models import CustomerUser
        from apps.technician_portal.models import Technician
        from apps.tenants.models import TenantMembership

        # Check if user is a tenant owner/manager → owner dashboard
        owner_membership = TenantMembership.objects.filter(
            user=request.user, is_active=True, role__in=['owner', 'manager']
        ).first()
        if owner_membership:
            return redirect('owner_dashboard')

        # Check if user is a customer → customer dashboard
        try:
            customer_user = CustomerUser.objects.get(user=request.user)
            return redirect('customer_dashboard')
        except CustomerUser.DoesNotExist:
            pass

        # Check if user is a technician → technician dashboard
        try:
            technician = Technician.objects.get(user=request.user)
            return redirect('technician_dashboard')
        except Technician.DoesNotExist:
            pass

        # Fallback: if they have any tenant membership, send to owner dashboard
        any_membership = TenantMembership.objects.filter(
            user=request.user, is_active=True
        ).first()
        if any_membership:
            return redirect('owner_dashboard')

    # For unauthenticated users, show portal selection
    return render(request, 'login_router.html')

@require_POST
def logout_view(request):
    logout(request)
    return redirect('home')

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
