# RS Systems Developer Guide

## Table of Contents

- [System Architecture](#system-architecture)
- [Development Environment Setup](#development-environment-setup)
- [Code Organization](#code-organization)
- [Data Models and Business Logic](#data-models-and-business-logic)
- [API Development](#api-development)
- [Frontend Development](#frontend-development)
- [Testing and Quality Assurance](#testing-and-quality-assurance)
- [Deployment and DevOps](#deployment-and-devops)
- [Contributing Guidelines](#contributing-guidelines)

## System Architecture

### High-Level Overview

RS Systems is built using a modular Django architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                    Web Interface Layer                      │
├──────────────────┬──────────────────┬─────────────────────┤
│  Customer Portal │ Technician Portal│    Admin Portal     │
│   (/app/)        │    (/tech/)      │     (/admin/)       │
└──────────────────┴──────────────────┴─────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                     Business Logic Layer                    │
├──────────────────┬──────────────────┬─────────────────────┤
│  Repair Workflow │  Reward System   │ Customer Management │
│   Queue Mgmt     │  Referral Logic  │  Technician Mgmt    │
└──────────────────┴──────────────────┴─────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                        Data Layer                           │
├──────────────────┬──────────────────┬─────────────────────┤
│   PostgreSQL     │    File Storage  │    Session Store    │
│  (Production)    │   (AWS S3/Local) │     (Database)      │
└──────────────────┴──────────────────┴─────────────────────┘
```

### Core Applications

#### 1. Technician Portal (`apps/technician_portal/`)

**Purpose**: Manage repair workflows, customer interactions, and technical documentation.

**Key Components**:
- `models.py`: Repair, Technician, UnitRepairCount, TechnicianNotification
- `views.py`: Dashboard, repair management, customer interaction
- `forms.py`: Repair creation/editing, technician profile management
- `api/`: REST API endpoints for repair operations

**Recent Improvements**:
- Load-balanced technician assignment
- Enhanced repair visibility (all REQUESTED repairs visible to all technicians)
- Improved dashboard performance with query optimization

#### 2. Customer Portal (`apps/customer_portal/`)

**Purpose**: Self-service repair requests, status tracking, and rewards management.

**Key Components**:
- `models.py`: CustomerUser, RepairApproval, CustomerPreference
- `views.py`: Repair requests, approval workflows, account management
- `api/`: Data endpoints for visualizations

**Recent Improvements**:
- Intelligent technician assignment using workload balancing
- Enhanced repair request flow with better error handling

#### 3. Rewards & Referrals (`apps/rewards_referrals/`)

**Purpose**: Point-based reward system with referral tracking.

**Key Components**:
- `models.py`: Reward, RewardType, ReferralCode, RewardRedemption
- `services.py`: Business logic for point calculation and redemption
- `api/`: Reward management endpoints

### Database Schema

#### Core Entity Relationships

```mermaid
erDiagram
    Customer ||--o{ CustomerUser : has
    Customer ||--o{ Repair : receives
    Technician ||--o{ Repair : performs
    User ||--|| CustomerUser : extends
    User ||--|| Technician : extends
    Repair ||--o| RepairApproval : requires
    CustomerUser ||--o{ ReferralCode : owns
    CustomerUser ||--o{ Reward : earns
    Reward ||--o{ RewardRedemption : creates
    RewardRedemption ||--o| Repair : applies_to
```

#### Key Business Rules

1. **Repair Assignment**: Uses load balancing to distribute work evenly
2. **Cost Calculation**: Based on unit repair frequency (decreasing cost model)
3. **Reward Application**: Automatic application to completed repairs
4. **Status Workflow**: REQUESTED → PENDING → APPROVED → IN_PROGRESS → COMPLETED

## Development Environment Setup

### Prerequisites

- Python 3.8+
- Node.js (for frontend asset management)
- PostgreSQL (for production-like development)
- Git
- Virtual environment tools

### Detailed Setup Process

#### 1. Repository Setup

```bash
# Clone repository
git clone <repository-url>
cd rs_systems_branch2

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

#### 2. Environment Configuration

Create `.env` file in project root:

```bash
# Core Settings
SECRET_KEY=your-development-secret-key-here
DEBUG=True
ENVIRONMENT=development

# Database (SQLite for development)
LOCAL_DATABASE_URL=sqlite:///db.sqlite3

# For PostgreSQL development (optional)
# DATABASE_URL=postgresql://user:password@localhost:5432/rs_systems_dev

# Admin Account
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@localhost
ADMIN_PASSWORD=secure-dev-password

# Security (development)
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
USE_HTTPS=False
```

#### 3. Database Initialization

```bash
# Set up database with migrations and initial data
python manage.py setup_db

# Create user groups and permissions
python manage.py setup_groups

# Create test data for development
python manage.py create_test_data
```

#### 4. Static Assets

```bash
# Collect static files
python manage.py collectstatic --noinput

# For development server (optional)
python manage.py runserver
```

### Development Tools

#### Recommended IDE Extensions

**VSCode**:
- Python
- Django
- Python Docstring Generator
- GitLens
- REST Client

**PyCharm**:
- Django support (built-in)
- Database tools
- HTTP Client

#### Code Quality Tools

```bash
# Install development dependencies
pip install black flake8 isort django-extensions

# Code formatting
black .

# Import sorting
isort .

# Linting
flake8 .
```

## Code Organization

### Directory Structure

```
rs_systems_branch2/
├── apps/                          # Application modules
│   ├── customer_portal/          # Customer interface
│   ├── technician_portal/        # Technician interface
│   ├── rewards_referrals/        # Reward system
│   ├── photo_storage/            # File management
│   ├── queue_management/         # Workflow management
│   ├── scheduling/               # Appointment system
│   └── security/                 # Security utilities
├── core/                         # Shared utilities
│   ├── models.py                 # Customer model
│   └── management/commands/      # CLI utilities
├── rs_systems/                   # Django project settings
│   ├── settings/                 # Settings package
│   │   ├── base.py               # Shared settings (INSTALLED_APPS, MIDDLEWARE, etc.)
│   │   ├── development.py        # Dev settings (DEBUG=True, SQLite fallback)
│   │   └── production.py         # Production settings (PostgreSQL, S3, security)
│   └── urls.py                   # URL routing
├── static/                       # Static assets
│   ├── css/                      # Stylesheets
│   ├── js/                       # JavaScript
│   └── images/                   # Images
├── templates/                    # HTML templates
│   ├── base.html                 # Base template
│   ├── customer_portal/          # Customer templates
│   └── technician_portal/        # Technician templates
└── docs/                         # Documentation
```

### Coding Standards

#### Python Code Style

```python
# Follow PEP 8 with these specific guidelines:

# Class naming (PascalCase)
class RepairWorkflow:
    pass

# Function naming (snake_case)
def calculate_repair_cost(repair_count):
    pass

# Constants (UPPER_SNAKE_CASE)
REPAIR_STATUS_CHOICES = [
    ('REQUESTED', 'Customer Requested'),
    ('PENDING', 'Approval Pending'),
    # ...
]

# Docstrings (Google style)
def process_repair_request(customer, unit_number, description):
    """Process a new repair request from a customer.
    
    Args:
        customer (Customer): The customer requesting repair
        unit_number (str): Vehicle/unit identifier
        description (str): Repair description
        
    Returns:
        Repair: Created repair instance
        
    Raises:
        ValidationError: If input data is invalid
    """
    pass
```

#### Django Patterns

```python
# Model design
class Repair(models.Model):
    # Use descriptive field names
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True)
    
    # Include metadata
    class Meta:
        ordering = ['-repair_date']
        indexes = [
            models.Index(fields=['queue_status']),
            models.Index(fields=['customer', 'unit_number']),
        ]
    
    # Business logic in model methods
    def calculate_cost(self, repair_count):
        """Calculate cost based on repair frequency."""
        return self.calculate_cost(repair_count)

# View design
@technician_required
def repair_detail(request, repair_id):
    """Display detailed repair information."""
    repair = get_object_or_404(Repair, id=repair_id)
    
    # Check permissions
    if not request.user.is_staff and repair.technician.user != request.user:
        return HttpResponseForbidden()
    
    return render(request, 'technician_portal/repair_detail.html', {
        'repair': repair,
    })
```

### API Development Standards

#### REST API Design

```python
# Use ViewSets for consistent API design
class RepairViewSet(viewsets.ModelViewSet):
    """API endpoints for repair management."""
    
    serializer_class = RepairSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter repairs based on user permissions."""
        user = self.request.user
        if user.is_staff:
            return Repair.objects.all()
        elif hasattr(user, 'technician'):
            return Repair.objects.filter(technician=user.technician)
        else:
            return Repair.objects.none()

# Serializer design
class RepairSerializer(serializers.ModelSerializer):
    """Serializer for Repair model with business logic."""
    
    discounted_cost = serializers.SerializerMethodField()
    
    class Meta:
        model = Repair
        fields = ['id', 'unit_number', 'description', 'cost', 'discounted_cost']
        read_only_fields = ['cost']
    
    def get_discounted_cost(self, obj):
        """Calculate final cost with discounts applied."""
        return obj.get_discounted_cost()
```

## Data Models and Business Logic

### Repair Workflow Implementation

#### Load-Balanced Assignment Algorithm

```python
# Location: apps/customer_portal/views.py:500-514
def assign_technician_with_load_balancing():
    """Assign repair to technician with least active workload."""
    
    technicians = Technician.objects.annotate(
        active_repairs=Count(
            'repair', 
            filter=Q(repair__queue_status__in=[
                'REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS'
            ])
        )
    ).order_by('active_repairs', 'id')
    
    return technicians.first()  # Technician with least load
```

#### Cost Calculation Logic

```python
# Location: apps/technician_portal/models.py:142-153
@staticmethod
def calculate_cost(repair_count):
    """Calculate repair cost based on frequency."""
    cost_schedule = {
        1: 50,   # First repair
        2: 40,   # Second repair  
        3: 35,   # Third repair
        4: 30,   # Fourth repair
    }
    return cost_schedule.get(repair_count, 25)  # 5+ repairs
```

#### Reward Auto-Application

```python
# Location: apps/technician_portal/models.py:95-140
def apply_available_rewards(self):
    """Automatically apply pending rewards to completed repairs."""
    
    if self.queue_status != 'COMPLETED':
        return
    
    # Find pending redemptions for this customer
    customer_users = CustomerUser.objects.filter(customer=self.customer)
    pending_redemptions = RewardRedemption.objects.filter(
        reward__customer_user__in=customer_users,
        status='PENDING',
        applied_to_repair__isnull=True
    ).order_by('created_at')
    
    # Apply oldest pending redemption
    if pending_redemptions.exists():
        redemption = pending_redemptions.first()
        redemption.applied_to_repair = self
        redemption.save()
```

### Database Optimization

#### Index Strategy

```python
# Ensure efficient queries with proper indexing
class Repair(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=['queue_status']),          # Status filtering
            models.Index(fields=['customer', 'unit_number']), # Customer lookups
            models.Index(fields=['technician']),             # Assignment queries
            models.Index(fields=['repair_date']),            # Chronological sorting
        ]
```

#### Query Optimization Examples

```python
# Efficient repair loading with related data
repairs = Repair.objects.select_related(
    'technician__user', 
    'customer'
).prefetch_related(
    'applied_rewards__reward_option'
).filter(queue_status='REQUESTED')

# Efficient dashboard data loading
customer_stats = Repair.objects.filter(
    customer=customer
).aggregate(
    total_completed=Count('id', filter=Q(queue_status='COMPLETED')),
    total_cost=Sum('cost', filter=Q(queue_status='COMPLETED')),
    active_repairs=Count('id', filter=~Q(queue_status__in=['COMPLETED', 'DENIED']))
)
```

## API Development

### Authentication and Permissions

#### Token Authentication Setup

```python
# rs_systems/settings/base.py
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

# Create tokens for users
from rest_framework.authtoken.models import Token
token = Token.objects.create(user=user)
```

#### Custom Permissions

```python
from rest_framework.permissions import BasePermission

class IsTechnicianOrReadOnly(BasePermission):
    """Allow technicians to modify, others read-only."""
    
    def has_permission(self, request, view):
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return request.user.is_authenticated
        return hasattr(request.user, 'technician')

class IsRepairOwnerOrAdmin(BasePermission):
    """Allow repair owners or admins to access."""
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        return obj.technician.user == request.user
```

### API Documentation

The system uses `drf-spectacular` for automatic API documentation:

```python
# rs_systems/settings/base.py
SPECTACULAR_SETTINGS = {
    'TITLE': 'RS Systems API',
    'DESCRIPTION': 'Windshield Repair Management API',
    'VERSION': '1.0.0',
    'SCHEMA_PATH_PREFIX': '/api/',
}

# Access documentation at:
# /api/schema/swagger-ui/  - Interactive Swagger UI
# /api/schema/redoc/       - ReDoc documentation
# /api/schema/             - OpenAPI schema JSON
```

### API Endpoints Reference

#### Repair Management API

```python
# GET /api/repairs/
# List repairs (filtered by user permissions)

# POST /api/repairs/
# Create new repair (technicians only)

# GET /api/repairs/{id}/
# Retrieve specific repair

# PUT /api/repairs/{id}/
# Update repair (owner or admin only)

# PATCH /api/repairs/{id}/status/
# Update repair status
```

#### Customer Management API

```python
# GET /api/customers/
# List customers (filtered by technician assignments)

# GET /api/customers/{id}/repairs/
# List repairs for specific customer
```

#### Rewards API

```python
# GET /api/rewards/
# List user's rewards

# POST /api/rewards/redeem/
# Redeem reward points

# GET /api/referrals/code/
# Get user's referral code
```

## Frontend Development

### Template Organization

#### Base Template Structure

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Meta tags and CSS -->
    {% load static %}
    <link href="{% static 'css/bootstrap.min.css' %}" rel="stylesheet">
    <link href="{% static 'css/custom.css' %}" rel="stylesheet">
</head>
<body>
    <!-- Navigation -->
    {% include 'components/navbar.html' %}
    
    <!-- Content -->
    <main>
        {% block content %}{% endblock %}
    </main>
    
    <!-- Scripts -->
    <script src="{% static 'js/bootstrap.bundle.min.js' %}"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

#### Portal-Specific Templates

```html
<!-- templates/technician_portal/dashboard.html -->
{% extends 'base.html' %}
{% load static %}

{% block title %}Technician Dashboard{% endblock %}

{% block content %}
<div class="container">
    <!-- Dashboard widgets -->
    <div class="row">
        <div class="col-md-6">
            {% include 'technician_portal/components/repair_queue.html' %}
        </div>
        <div class="col-md-6">
            {% include 'technician_portal/components/notifications.html' %}
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{% static 'js/technician_dashboard.js' %}"></script>
{% endblock %}
```

### JavaScript and Data Visualization

#### D3.js Integration

```javascript
// static/js/customer_dashboard.js
class RepairTrendsChart {
    constructor(containerId) {
        this.container = d3.select(`#${containerId}`);
        this.margin = {top: 20, right: 30, bottom: 40, left: 50};
        this.width = 600 - this.margin.left - this.margin.right;
        this.height = 400 - this.margin.top - this.margin.bottom;
    }
    
    async loadData() {
        const response = await fetch('/app/api/repair-cost-data/');
        this.data = await response.json();
        this.render();
    }
    
    render() {
        // D3.js chart rendering logic
        const svg = this.container.append('svg')
            .attr('width', this.width + this.margin.left + this.margin.right)
            .attr('height', this.height + this.margin.top + this.margin.bottom);
        
        // Chart implementation...
    }
}

// Initialize charts on page load
document.addEventListener('DOMContentLoaded', function() {
    const trendsChart = new RepairTrendsChart('repair-trends');
    trendsChart.loadData();
});
```

### CSS Architecture

#### Component-Based Styling

```css
/* static/css/components/repair-card.css */
.repair-card {
    background: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1rem;
    transition: box-shadow 0.2s ease;
}

.repair-card:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.repair-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
}

.repair-card__status {
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
}

.repair-card__status--requested {
    background-color: #fef3c7;
    color: #92400e;
}

.repair-card__status--approved {
    background-color: #d1fae5;
    color: #065f46;
}
```

## Testing and Quality Assurance

### Unit Testing Patterns

#### Model Testing

```python
# apps/technician_portal/tests/test_models.py
from django.test import TestCase
from apps.technician_portal.models import Repair, Technician
from core.models import Customer

class RepairModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='test customer')
        self.technician = Technician.objects.create(
            user=User.objects.create_user('tech', 'tech@test.com', 'pass')
        )
    
    def test_cost_calculation(self):
        """Test repair cost calculation based on frequency."""
        # Test first repair
        self.assertEqual(Repair.calculate_cost(1), 50)
        
        # Test fifth repair (uses default)
        self.assertEqual(Repair.calculate_cost(5), 25)
    
    def test_repair_completion_updates_cost(self):
        """Test that completing repair calculates cost."""
        repair = Repair.objects.create(
            technician=self.technician,
            customer=self.customer,
            unit_number='TEST001',
            description='Test repair'
        )
        
        repair.queue_status = 'COMPLETED'
        repair.save()
        
        self.assertEqual(repair.cost, 50)  # First repair for this unit
```

#### View Testing

```python
# apps/technician_portal/tests/test_views.py
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

class TechnicianDashboardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('tech', 'tech@test.com', 'pass')
        self.technician = Technician.objects.create(user=self.user)
    
    def test_dashboard_requires_login(self):
        """Test that dashboard requires authentication."""
        response = self.client.get(reverse('technician_dashboard'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_dashboard_shows_requested_repairs(self):
        """Test that dashboard displays REQUESTED repairs."""
        self.client.login(username='tech', password='pass')
        
        # Create a REQUESTED repair
        repair = Repair.objects.create(
            technician=self.technician,
            customer=self.customer,
            queue_status='REQUESTED'
        )
        
        response = self.client.get(reverse('technician_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, repair.unit_number)
```

### Integration Testing

```python
# tests/test_integration.py
from django.test import TestCase, TransactionTestCase
from django.db import transaction

class RepairWorkflowIntegrationTest(TransactionTestCase):
    """Test complete repair workflow from request to completion."""
    
    def test_customer_request_to_completion_flow(self):
        """Test entire repair flow."""
        # 1. Customer creates request
        customer_response = self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'FLOW001',
            'description': 'Test crack',
            'damage_type': 'Crack'
        })
        
        # 2. Verify repair created
        repair = Repair.objects.get(unit_number='FLOW001')
        self.assertEqual(repair.queue_status, 'REQUESTED')
        
        # 3. Technician processes repair
        tech_client = Client()
        tech_client.login(username='tech1', password='demo123')
        
        # 4. Progress through statuses
        for status in ['APPROVED', 'IN_PROGRESS', 'COMPLETED']:
            response = tech_client.post(
                reverse('update_queue_status', args=[repair.id]),
                {'status': status}
            )
            repair.refresh_from_db()
            self.assertEqual(repair.queue_status, status)
        
        # 5. Verify final state
        self.assertGreater(repair.cost, 0)
```

### Performance Testing

```python
# tests/test_performance.py
import time
from django.test import TestCase
from django.test.utils import override_settings

class PerformanceTest(TestCase):
    def test_repair_list_performance(self):
        """Test that repair list loads within acceptable time."""
        # Create large dataset
        repairs = [
            Repair(technician=self.technician, customer=self.customer, 
                  unit_number=f'UNIT{i}', description=f'Repair {i}')
            for i in range(1000)
        ]
        Repair.objects.bulk_create(repairs)
        
        # Test query performance
        start_time = time.time()
        response = self.client.get(reverse('repair_list'))
        end_time = time.time()
        
        self.assertEqual(response.status_code, 200)
        self.assertLess(end_time - start_time, 1.0)  # Should load in <1 second
```

## Deployment and DevOps

### Environment Configuration

#### Production Settings

```python
# rs_systems/settings/production.py
from .base import *

DEBUG = False
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'rssystems.io').split(',')

# Database (PostgreSQL required)
DATABASES = {
    'default': dj_database_url.config(default=os.environ.get('DATABASE_URL'))
}

# Static files
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Email (SendGrid)
EMAIL_BACKEND = 'sendgrid_backend.SendgridBackend'
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'notifications@rssystems.io')

# Security
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

#### Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.9

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Collect static files
RUN python manage.py collectstatic --noinput

# Run migrations and start server
CMD ["sh", "-c", "python manage.py migrate && gunicorn rs_systems.wsgi:application --bind 0.0.0.0:8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEBUG=False
      - DATABASE_URL=postgresql://user:password@db:5432/rs_systems
    depends_on:
      - db
  
  db:
    image: postgres:13
    environment:
      - POSTGRES_DB=rs_systems
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Deployment Automation

#### GitHub Actions CI/CD

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          python manage.py test
          python manage.py test_system_flow --cleanup
      
      - name: Check migrations
        run: |
          python manage.py makemigrations --check --dry-run

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v2
      
      - name: Deploy to Railway
        uses: railway-deploy@v1
        with:
          token: ${{ secrets.RAILWAY_TOKEN }}
          service: rs-systems-production
```

### Monitoring and Logging

#### Production Logging

```python
# rs_systems/settings/production.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/app/logs/django.log',
            'maxBytes': 15728640,  # 15MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
```

#### Health Check Endpoints

```python
# core/views.py
from django.http import JsonResponse
from django.db import connection

def health_check(request):
    """Basic health check endpoint."""
    try:
        # Test database connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        return JsonResponse({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=503)
```

## Contributing Guidelines

### Git Workflow

#### Branch Naming Convention

```bash
# Feature branches
feature/repair-assignment-optimization
feature/customer-portal-redesign

# Bug fixes
bugfix/repair-cost-calculation
bugfix/authentication-redirect

# Hotfixes
hotfix/security-vulnerability
hotfix/critical-data-loss
```

#### Commit Message Format

```
type(scope): short description

Longer explanation if needed

Fixes #123
```

**Types**: feat, fix, docs, style, refactor, test, chore

**Example**:
```
feat(technician): implement load-balanced repair assignment

- Replace simple first() selection with workload-based assignment
- Add active repair count annotation to technician queries
- Improve distribution of repairs among available technicians

Fixes #45
```

### Code Review Process

#### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed
- [ ] Performance impact assessed

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No debugging code left
```

#### Review Checklist

1. **Functionality**: Does the code work as intended?
2. **Tests**: Are there adequate tests covering the changes?
3. **Performance**: Are there any performance implications?
4. **Security**: Are there any security concerns?
5. **Documentation**: Is documentation updated appropriately?

### Development Best Practices

#### Security Considerations

```python
# Always validate user input
def update_repair_status(request, repair_id):
    repair = get_object_or_404(Repair, id=repair_id)
    
    # Check permissions
    if not request.user.is_staff and repair.technician.user != request.user:
        raise PermissionDenied()
    
    # Validate status transition
    new_status = request.POST.get('status')
    if new_status not in dict(Repair.QUEUE_CHOICES):
        raise ValidationError('Invalid status')

# Use Django's built-in protections
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required

@login_required
@csrf_protect
def secure_view(request):
    pass
```

#### Performance Guidelines

```python
# Use select_related for foreign keys
repairs = Repair.objects.select_related(
    'technician__user', 'customer'
).filter(queue_status='PENDING')

# Use prefetch_related for reverse foreign keys
customers = Customer.objects.prefetch_related(
    'repair_set'
).all()

# Avoid N+1 queries
# Bad:
for repair in repairs:
    print(repair.technician.user.username)  # Queries DB each time

# Good:
repairs = repairs.select_related('technician__user')
for repair in repairs:
    print(repair.technician.user.username)  # Data already loaded
```

#### Error Handling

```python
import logging

logger = logging.getLogger(__name__)

def create_repair(request):
    try:
        # Business logic
        repair = Repair.objects.create(...)
        logger.info(f'Repair {repair.id} created successfully')
        return repair
    except ValidationError as e:
        logger.warning(f'Validation error creating repair: {e}')
        raise
    except Exception as e:
        logger.error(f'Unexpected error creating repair: {e}', exc_info=True)
        raise
```

---

This developer guide provides comprehensive information for working with the RS Systems codebase. For specific implementation details, refer to the code comments and docstrings throughout the project.