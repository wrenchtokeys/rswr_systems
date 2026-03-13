# RS Systems Troubleshooting Guide

## Table of Contents

- [Common Issues](#common-issues)
- [Repair Flow Issues](#repair-flow-issues)
- [Authentication Problems](#authentication-problems)
- [Database Issues](#database-issues)
- [Performance Problems](#performance-problems)
- [Deployment Issues](#deployment-issues)
- [Development Environment](#development-environment)
- [API Issues](#api-issues)
- [Frontend Problems](#frontend-problems)
- [Logging and Debugging](#logging-and-debugging)

## Common Issues

### Issue: Repairs Not Visible to Technicians

**Symptoms:**
- Customer creates repair request successfully
- Technician dashboard shows no new repairs
- Repair exists in database but not displayed

**Root Cause:**
This was a known issue that has been fixed. Previously, technicians could only see repairs specifically assigned to them.

**Solution:**
 **Fixed in recent update**: All technicians now see all REQUESTED repairs in their dashboard.

**Verification:**
```bash
# Run the system test to verify the fix
python manage.py test_system_flow --verbose
```

**If Still Experiencing Issues:**
1. Check that you're using the latest code
2. Verify technician has proper permissions:
```python
# In Django shell
from django.contrib.auth.models import User
from apps.technician_portal.models import Technician

user = User.objects.get(username='your_technician')
print(f"Has technician profile: {hasattr(user, 'technician')}")
print(f"In Technicians group: {user.groups.filter(name='Technicians').exists()}")
```

### Issue: "No technicians available" Error

**Symptoms:**
- Customer tries to submit repair request
- Error message: "No technicians available. Please try again later."

**Root Cause:**
No technician accounts exist in the system.

**Solution:**
```bash
# Create test technicians
python manage.py create_test_data

# Or create manually in Django admin
python manage.py createsuperuser
# Go to /admin/ and create Technician records
```

**Prevention:**
Always ensure at least one technician exists before testing repair requests.

### Issue: Load Balancing Not Working

**Symptoms:**
- All repairs assigned to same technician
- Uneven distribution of workload

**Root Cause:**
Database query not properly counting active repairs.

**Verification:**
```python
# Check active repair counts in Django shell
from apps.technician_portal.models import Technician
from django.db.models import Count, Q

technicians = Technician.objects.annotate(
    active_repairs=Count('repair', filter=Q(
        repair__queue_status__in=['REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS']
    ))
).order_by('active_repairs', 'id')

for tech in technicians:
    print(f"{tech.user.username}: {tech.active_repairs} active repairs")
```

**Solution:**
Ensure the load balancing logic is correctly implemented in `apps/customer_portal/views.py:500-514`.

## Repair Flow Issues

### Issue: Repair Status Not Updating

**Symptoms:**
- Technician clicks to update repair status
- No change occurs or error message displayed
- Status remains in previous state

**Debugging Steps:**

1. **Check Permissions:**
```python
# Verify technician can modify this repair
repair = Repair.objects.get(id=repair_id)
user = User.objects.get(username='technician_username')

print(f"Repair assigned to: {repair.technician.user.username}")
print(f"Current user: {user.username}")
print(f"User is staff: {user.is_staff}")
print(f"Can modify: {user.is_staff or repair.technician.user == user}")
```

2. **Check URL Pattern:**
```bash
# Verify URL is correct
python manage.py show_urls | grep update_queue_status
```

3. **Check Form Data:**
- Ensure CSRF token is included
- Verify status value is valid
- Check HTTP method is POST

**Common Solutions:**
- Ensure user is logged in as correct technician
- Verify repair is assigned to current technician (non-admin users)
- Check that new status is in QUEUE_CHOICES

### Issue: Cost Not Calculated After Completion

**Symptoms:**
- Repair marked as COMPLETED
- Cost remains $0.00
- No error messages

**Root Cause:**
Cost calculation logic not triggering properly.

**Verification:**
```python
# Check repair save logic
repair = Repair.objects.get(id=repair_id)
print(f"Status: {repair.queue_status}")
print(f"Cost: {repair.cost}")
print(f"Customer: {repair.customer}")

# Check UnitRepairCount
from apps.technician_portal.models import UnitRepairCount
count = UnitRepairCount.objects.filter(
    customer=repair.customer, 
    unit_number=repair.unit_number
).first()
print(f"Unit repair count: {count.repair_count if count else 'None'}")
```

**Solution:**
1. Ensure repair has a customer assigned
2. Verify UnitRepairCount records exist
3. Check that save() method is being called properly

### Issue: Reward Not Auto-Applied

**Symptoms:**
- Customer has pending reward redemptions
- Repair completed but no discount applied
- Reward remains in PENDING status

**Debugging:**
```python
# Check reward application logic
from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import RewardRedemption

customer_users = CustomerUser.objects.filter(customer=repair.customer)
print(f"Customer users found: {customer_users.count()}")

pending_redemptions = RewardRedemption.objects.filter(
    reward__customer_user__in=customer_users,
    status='PENDING',
    applied_to_repair__isnull=True
)
print(f"Pending redemptions: {pending_redemptions.count()}")
```

**Solution:**
Ensure the `apply_available_rewards()` method is called in the repair save logic.

## Authentication Problems

### Issue: Login Redirect Loop

**Symptoms:**
- User enters correct credentials
- Redirected back to login page repeatedly
- No error message displayed

**Common Causes:**
1. **Session Configuration Issue:**
```python
# Check settings.py
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 1209600  # 2 weeks
```

2. **Middleware Order:**
```python
# Ensure correct middleware order in settings.py
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # ... other middleware
    'common.portal_middleware.PortalAccessMiddleware',  # Should be last
]
```

3. **Portal Access Middleware:**
Check if user has proper portal access in the portal middleware.

### Issue: "Account does not have technician access"

**Symptoms:**
- User can login but cannot access technician portal
- Error message about technician access

**Solution:**
```python
# Add user to Technicians group
from django.contrib.auth.models import User, Group
from apps.technician_portal.models import Technician

user = User.objects.get(username='username')
tech_group = Group.objects.get(name='Technicians')
user.groups.add(tech_group)

# Create Technician profile if needed
Technician.objects.get_or_create(
    user=user,
    defaults={'expertise': 'General Repair'}
)
```

### Issue: Customer Profile Not Found

**Symptoms:**
- User logs in successfully
- Redirected to profile creation repeatedly
- Cannot access customer portal features

**Solution:**
```python
# Create CustomerUser profile
from apps.customer_portal.models import CustomerUser
from core.models import Customer

user = User.objects.get(username='username')
customer = Customer.objects.get(name='customer_name')

CustomerUser.objects.get_or_create(
    user=user,
    defaults={
        'customer': customer,
        'is_primary_contact': True
    }
)
```

## Database Issues

### Issue: Migration Errors

**Symptoms:**
- `python manage.py migrate` fails
- Dependency conflicts
- Missing migration files

**Common Solutions:**

1. **Reset Migrations (Development Only):**
```bash
# WARNING: This deletes all data!
rm -rf */migrations/
python manage.py makemigrations
python manage.py migrate
```

2. **Fake Initial Migration:**
```bash
python manage.py migrate --fake-initial
```

3. **Resolve Dependencies:**
```bash
# Check migration status
python manage.py showmigrations

# Apply specific migration
python manage.py migrate app_name migration_name
```

### Issue: Database Connection Errors

**Symptoms:**
- "connection to server closed unexpectedly"
- "database does not exist"
- "authentication failed"

**PostgreSQL Issues:**
```bash
# Check PostgreSQL status
pg_ctl status

# Start PostgreSQL
pg_ctl start

# Create database
createdb rs_systems_dev
```

**Database URL Issues:**
```bash
# Check environment variables
echo $DATABASE_URL

# Test connection
python manage.py dbshell
```

### Issue: Data Corruption or Inconsistency

**Symptoms:**
- Unexpected data relationships
- Missing related objects
- Integrity constraint violations

**Recovery Steps:**
```bash
# Create backup first
python manage.py dumpdata > backup.json

# Rebuild UnitRepairCount data
python manage.py shell
>>> from apps.customer_portal.views import rebuild_unit_repair_counts
>>> from core.models import Customer
>>> for customer in Customer.objects.all():
...     rebuild_unit_repair_counts(customer)
```

## Performance Problems

### Issue: Slow Dashboard Loading

**Symptoms:**
- Dashboard takes >5 seconds to load
- High database query count
- Browser becomes unresponsive

**Debugging:**
```python
# Enable query logging in settings.py (development only)
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.db.backends': {
            'level': 'DEBUG',
            'handlers': ['console'],
        }
    }
}
```

**Optimization Solutions:**
```python
# Use select_related for foreign keys
repairs = Repair.objects.select_related(
    'technician__user', 'customer'
).filter(queue_status='REQUESTED')

# Use prefetch_related for reverse relationships
customers = Customer.objects.prefetch_related(
    'repair_set__technician__user'
).all()

# Add database indexes
class Repair(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=['queue_status']),
            models.Index(fields=['customer', 'unit_number']),
        ]
```

### Issue: High Memory Usage

**Symptoms:**
- Server runs out of memory
- Slow response times
- Process killed by system

**Solutions:**
```python
# Use pagination for large datasets
from django.core.paginator import Paginator

repairs = Repair.objects.all()
paginator = Paginator(repairs, 25)  # 25 per page

# Use iterator for bulk operations
for repair in Repair.objects.iterator(chunk_size=100):
    # Process repair
    pass

# Use bulk operations
Repair.objects.bulk_create(repair_list)
Repair.objects.bulk_update(repair_list, ['status'])
```

## Deployment Issues

### Issue: Static Files Not Loading

**Symptoms:**
- Website loads but no CSS/JavaScript
- 404 errors for static assets
- Plain HTML layout

**Solutions:**
```bash
# Collect static files
python manage.py collectstatic --noinput

# Check static file settings
python manage.py shell
>>> from django.conf import settings
>>> print(settings.STATIC_URL)
>>> print(settings.STATIC_ROOT)
>>> print(settings.STATICFILES_DIRS)
```

**WhiteNoise Configuration:**
```python
# settings.py
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Add this
    # ... other middleware
]

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

### Issue: Environment Variables Not Working

**Symptoms:**
- Settings using default values
- DEBUG=True in production
- Database connection errors

**Solutions:**
```bash
# Check environment variables
env | grep -E "(SECRET_KEY|DEBUG|DATABASE_URL)"

# Railway deployment
railway variables set SECRET_KEY=your-secret-key

# AWS deployment
# Set in Elastic Beanstalk configuration
```

### Issue: SSL/HTTPS Problems

**Symptoms:**
- Mixed content warnings
- SSL certificate errors
- Infinite redirect loops

**Solutions:**
```python
# settings_aws.py
if os.environ.get('USE_HTTPS') == 'true':
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
```

## Development Environment

### Issue: Virtual Environment Problems

**Symptoms:**
- Command not found errors
- Wrong Python version
- Package installation failures

**Solutions:**
```bash
# Recreate virtual environment
deactivate
rm -rf venv
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Issue: Port Already in Use

**Symptoms:**
- "Error: That port is already in use"
- Cannot start development server

**Solutions:**
```bash
# Find and kill process using port
lsof -ti:8000 | xargs kill

# Use different port
python manage.py runserver 8001

# Windows alternative
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Issue: Import Errors

**Symptoms:**
- ModuleNotFoundError
- ImportError: cannot import name
- Circular import errors

**Solutions:**
```bash
# Check Python path
python manage.py shell
>>> import sys
>>> print(sys.path)

# Verify app is in INSTALLED_APPS
python manage.py shell
>>> from django.conf import settings
>>> print(settings.INSTALLED_APPS)

# Fix circular imports
# Move imports inside functions or use late imports
```

## API Issues

### Issue: API Returns 403 Forbidden

**Symptoms:**
- API requests return 403 status
- "Authentication credentials were not provided"
- CSRF token errors

**Solutions:**
```python
# For API clients, use token authentication
from rest_framework.authtoken.models import Token
token = Token.objects.create(user=user)

# Include in requests
headers = {'Authorization': f'Token {token.key}'}
response = requests.get(url, headers=headers)
```

```javascript
// For AJAX requests, include CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');
fetch(url, {
    method: 'POST',
    headers: {
        'X-CSRFToken': csrftoken,
        'Content-Type': 'application/json',
    },
    body: JSON.stringify(data)
});
```

### Issue: API Returns Wrong Data

**Symptoms:**
- API returns data user shouldn't see
- Missing expected data
- Incorrect permissions applied

**Debugging:**
```python
# Check view permissions
class RepairViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        print(f"User: {user}, Staff: {user.is_staff}")
        queryset = super().get_queryset()
        print(f"Queryset count: {queryset.count()}")
        return queryset
```

## Frontend Problems

### Issue: JavaScript Errors

**Symptoms:**
- Features not working
- Console errors
- Visualizations not loading

**Common Issues:**
1. **D3.js Not Loading:**
```html
<!-- Check script tag in template -->
<script src="{% static 'js/d3.v7.min.js' %}"></script>
<script>
console.log('D3 version:', d3.version);  // Should print version
</script>
```

2. **API Endpoint Issues:**
```javascript
// Check API response
fetch('/app/api/repair-cost-data/')
    .then(response => {
        console.log('Status:', response.status);
        return response.json();
    })
    .then(data => {
        console.log('Data:', data);
    })
    .catch(error => {
        console.error('Error:', error);
    });
```

### Issue: CSS Not Applied

**Symptoms:**
- Styling not working
- Layout broken
- Responsive design issues

**Solutions:**
```bash
# Check static files
python manage.py findstatic css/style.css

# Force browser refresh
# Ctrl+F5 or Cmd+Shift+R

# Check CSS file for syntax errors
# Use browser dev tools
```

## Logging and Debugging

### Enable Debug Mode

```python
# settings.py (development only)
DEBUG = True
ALLOWED_HOSTS = ['*']

# Add debug toolbar
INSTALLED_APPS += ['debug_toolbar']
MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

INTERNAL_IPS = ['127.0.0.1']
```

### Comprehensive Logging Setup

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'debug.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'apps': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'django.db.backends': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
```

### Debug Specific Issues

```python
# Add debug logging to views
import logging
logger = logging.getLogger(__name__)

def problematic_view(request):
    logger.debug(f"User: {request.user}")
    logger.debug(f"Method: {request.method}")
    logger.debug(f"POST data: {request.POST}")
    
    # Your view logic here
    
    logger.debug(f"Response data: {response_data}")
    return response
```

### Common Debug Commands

```bash
# Django shell for debugging
python manage.py shell

# Check URLs
python manage.py show_urls

# Validate models
python manage.py check

# SQL for specific query
python manage.py shell
>>> from django.db import connection
>>> print(connection.queries)

# Check migrations
python manage.py showmigrations

# Test specific functionality
python manage.py test apps.technician_portal.tests.test_views.TestSpecificFunction -v 2
```

## Getting Help

### When to Seek Additional Support

1. **Security Vulnerabilities**: Report immediately
2. **Data Loss**: Stop operations and backup immediately
3. **Production Outages**: Follow incident response procedures
4. **Persistent Performance Issues**: Consider professional optimization

### Information to Provide

When reporting issues, include:
- Error messages (full stack trace)
- Steps to reproduce
- Environment details (development/production)
- Browser/client information
- Relevant log entries
- Screenshots if applicable

### Resources

- **Django Documentation**: https://docs.djangoproject.com/
- **Django REST Framework**: https://www.django-rest-framework.org/
- **Project Documentation**: See `/docs` directory
- **Code Comments**: Inline documentation throughout codebase
- **Contact**: contact@rssystems.io

---

This troubleshooting guide covers the most common issues encountered with the RS Systems platform. For issues not covered here, check the logs, enable debug mode, and use Django's debugging tools to investigate further.