# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Development Setup
```bash
# Set up virtual environment and install dependencies
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Initialize database with custom management commands
python manage.py setup_db
python manage.py setup_groups

# Set up simplified rewards system (4 professional options)
python manage.py setup_simplified_rewards

# Create superuser (uses environment variables if available)
python manage.py createsu
```

### Core Development Commands
```bash
# Run development server
python manage.py runserver

# Database operations
python manage.py makemigrations
python manage.py migrate

# Run tests
python manage.py test
python manage.py test apps.technician_portal  # Test specific app

# Collect static files for production
python manage.py collectstatic
```

### Maintenance Commands
```bash
# Audit S3 storage for orphaned repair photos
python manage.py audit_repair_photos              # Dry run - shows orphaned files
python manage.py audit_repair_photos --delete     # Actually delete orphaned files

# Security audit
python manage.py security_audit                   # Run security checks
```

### Notification System Commands
```bash
# Set up notification templates
python manage.py setup_notification_templates     # Create default email/SMS templates

# Test email delivery (AWS SES)
python manage.py test_ses email@example.com       # Send test email

# Test SMS delivery (AWS SNS)
python manage.py test_sns +15551234567            # Send test SMS (optional)
```

## High-Level Architecture

### Modular Django Application Structure
The codebase uses a modular Django architecture with core apps housed in the `apps/` directory:

- **core**: Shared utilities, portal access middleware, and notification system infrastructure
- **technician_portal**: Main repair workflow management with queue-based status tracking
- **customer_portal**: Self-service customer interface with repair tracking and approvals
- **rewards_referrals**: Point-based reward system with referral code generation
- **photo_storage**: Image management for repair documentation
- **queue_management**: Advanced repair workflow orchestration
- **scheduling**: Appointment and maintenance scheduling
- **security**: Authentication, authorization, and security middleware

### Notification System Architecture (Added December 2025)
The system includes a comprehensive notification infrastructure for email and SMS delivery:

**Core Components**:
- **Email Backend**: AWS SES with DKIM/SPF verification and production-ready configuration
- **SMS Backend**: AWS SNS for transactional text messages (optional, $1/month default limit)
- **Task Queue**: Celery with Redis broker for asynchronous notification delivery
- **Monitoring**: CloudWatch metrics and alarms for delivery tracking
- **Templates**: Django-based email templates with HTML/plain text support

**Models** (`core/models/`):
- `NotificationTemplate`: Configurable templates for different notification types
- `Notification`: Individual notification records with delivery status tracking
- `NotificationPreference`: Per-user notification delivery preferences
- `EmailBrandingConfig`: Customizable email branding (logo, colors, footer)

**Services** (`core/services/`):
- `notification_service.py`: High-level notification creation and delivery
- `email_backend.py`: AWS SES integration with rate limiting
- `sms_service.py`: AWS SNS integration for SMS delivery
- `metrics_service.py`: CloudWatch metrics publishing

**Celery Tasks** (`core/tasks.py`):
- Asynchronous notification processing
- Retry logic for failed deliveries
- Rate limiting and batch processing

**Infrastructure**:
- ElastiCache Redis: Task queue and result backend
- Lambda: Inbound email forwarding to Gmail
- S3: Inbound email storage
- CloudWatch: 6 monitoring alarms for delivery health

**Configuration**: See `docs/deployment/NOTIFICATION_NEXT_STEPS.md` for complete setup instructions

### Customer Portal Notifications (Added December 2025)

The notification system extends to the customer portal with company-level notifications:

**Architecture**:
- Notifications sent to **Customer** objects (not CustomerUser) for company-wide visibility
- All CustomerUser accounts for a company see the same notifications (shared notifications)
- Uses same `Notification` model with ContentType polymorphism
- Customer-specific preference model: `CustomerNotificationPreference`

**Customer Portal Components**:
- **Notification Bell**: Header icon with unread badge, always visible (including mobile)
- **AJAX Polling**: Updates every 30 seconds for real-time notification delivery
- **Preferences Page**: `/app/notifications/preferences/` - Manage channels, categories, quiet hours
- **History Page**: `/app/notifications/history/` - Paginated list with filters (25 per page)

**Default Notification Categories** (enabled by default):
- **Pending Approvals**: Repairs awaiting customer approval (critical workflow)
- **Repair Completions**: Repairs marked as completed
- **New Repair Requests**: New repair requests submitted
- In Progress Updates: Repairs started by technicians (optional)
- Repair Status Changes: Other status updates (optional)
- Rewards & Referrals: Reward activity (optional)
- System Announcements: Important system messages (optional)

**Customer-Specific Features**:
- **Batch Mode**: Daily digest option for pending approvals (reduces email volume)
- **Quiet Hours**: Pause non-urgent notifications during specified time periods
- **Company-Wide Visibility**: Multiple users per company see identical notification feed
- **Caching**: 2-minute cache for unread counts reduces database load from polling

**URLs**:
```
/app/notifications/preferences/    Notification settings (form-based)
/app/notifications/history/         Full notification history with pagination
/app/notifications/<id>/mark-read/  AJAX mark single as read
/app/notifications/mark-all-read/   AJAX bulk mark all as read
/app/notifications/unread-count/    AJAX polling endpoint (30s interval)
```

**Implementation Files**:
- **Views**: `/apps/customer_portal/views.py` (lines 1673-1932)
- **Forms**: `/apps/customer_portal/forms.py` - `CustomerNotificationPreferenceForm`
- **URLs**: `/apps/customer_portal/urls.py` - 5 notification routes
- **Templates**:
  - `/templates/customer_portal/includes/notification_bell.html` - Bell component
  - `/templates/customer_portal/notification_preferences.html` - Settings page
  - `/templates/customer_portal/notification_history.html` - History page
- **Signals**: `/core/signals.py` - Auto-creates preferences for new customers
- **Migration**: `/core/migrations/0007_setup_customer_notification_defaults.py`

**Auto-Setup**:
- New customers automatically get `CustomerNotificationPreference` via post_save signal
- Data migration created preferences for all existing customers
- Default channels: email=True, sms=False (opt-in), in_app=True

### Portal Separation Architecture
The application uses a clear portal separation strategy for better user experience:

- **Marketing Landing Page** (`/`): Professional homepage showcasing services and directing users to appropriate portals
- **Customer Portal** (`/app/`): Fleet managers and company administrators portal
- **Technician Portal** (`/tech/`): Authorized repair technicians portal
- **Legacy Support** (`/accounts/login/`, `/login/`): Portal selection for existing links

### Portal URLs and Access
```
/  Marketing landing page (public)
/app/  Customer dashboard (redirects to login if unauthenticated)
/app/login/  Customer-specific login page
/app/register/  Customer registration
/tech/  Technician dashboard (redirects to login if unauthenticated)
/tech/login/  Technician-specific login page
/tech/settings/  Manager settings dashboard (managers and staff only)
/tech/settings/viscosity/  Viscosity rules management
/tech/settings/team/  Team overview dashboard
/accounts/login/  Portal selection page (legacy support)
/login/  Portal selection page (legacy support)
```

### Authentication & Access Control
- **Portal-Specific Login**: Separate login flows with distinct branding and validation
- **Access Middleware**: `common.portal_middleware.PortalAccessMiddleware` enforces permissions
- **Role-Based Routing**: Automatic redirection to appropriate portal after login
- **Cross-Portal Prevention**: Authenticated users cannot access unauthorized portals
- **Legacy URL Support**: Old login URLs redirect to portal selection page

### Group Permissions & Security
The system uses Django's built-in group-based permission system to control access levels:

**Technicians Group** (created by `setup_groups` command):
- **Repair Management**: View, add, change repairs (no delete to preserve data integrity)
- **Customer Data**: View-only access to customer information for repair context
- **Repair History**: View unit repair counts for pricing calculations
- **Notifications**: View and update technician notifications (mark as read)
- **Profile Management**: View and change their own technician profile

**Security Boundaries**:
- **No User Management**: Technicians cannot create, modify, or delete user accounts
- **No Administrative Access**: Cannot access Django admin user management functions
- **No Data Deletion**: Cannot delete critical models (repairs, customers) to preserve audit trail
- **Portal Isolation**: Technician permissions only apply to technician portal functions

### Key Business Logic Patterns

**Repair Workflow**: Central `Repair` model with status-based progression (REQUESTED  PENDING  APPROVED  IN_PROGRESS  COMPLETED). Cost calculation is automatic based on unit repair frequency using `UnitRepairCount` tracking. **Sales tax** (`tax_rate`, `tax_amount`) is calculated automatically on every save using `TaxService` and the rates configured in `BillingConfig`. The `total_with_tax` property returns cost + tax. Tax is also independently calculated at invoice creation time via `TaxService.apply_tax_to_invoice()`.

**Multi-Break Batch Repairs** (New as of 11/8/2025): System supports creating multiple repairs for the same unit in one session. Each break is a separate `Repair` record linked via `repair_batch_id` (UUID). Progressive pricing: Break 1 priced as repair #N+1, Break 2 as #N+2, etc. Fully integrated with custom pricing tiers and volume discounts. All repairs in batch created atomically via `@transaction.atomic`. Customer portal supports batch approval (all-or-nothing). Access at `/tech/repairs/create-multi-break/`. See test suite at `tests/bug_fixes/test_multi_break_repair.py` for comprehensive examples.

**Photo Documentation**: Repair model supports photo uploads with `damage_photo_before`, `damage_photo_after`, and `additional_photos` fields. Photos are stored in AWS S3 (production) or local media directory (development) with automatic validation for file types and sizes. HEIC photos automatically converted to JPEG.

**Reward Integration**: Simplified professional reward system with 4 options: 50% repair discount (2,000 pts), free repair (3,500 pts), office donuts (1,500 pts), and team pizza (2,500 pts). Each referral earns 500 points. Automatic reward application to completed repairs via `apply_available_rewards()` method. The system supports percentage discounts, fixed amounts, and free services through `RewardType` and `RewardRedemption` models.

**Customer Linking**: `CustomerUser` model bridges Django's built-in User model to the business `Customer` entity, allowing multiple users per company account.

**Manager Settings Portal** (Added November 2025): Centralized configuration interface for managers within the technician portal. Accessible at `/tech/settings/` for users with `is_manager=True` or staff status. Features card-based UI with modal editing for viscosity rules management and team overview dashboard. Uses `@manager_required` decorator for permission control. AJAX API endpoints provide real-time updates without page refresh. Future phases planned for pricing configuration and audit logging. See `docs/development/MANAGER_SETTINGS_ROADMAP.md` for detailed feature roadmap.

### Multi-Break Batch Repair Architecture

**Database Schema** (`apps/technician_portal/models.py:236-250`):
- `repair_batch_id`: UUIDField linking repairs created in same session (nullable, indexed)
- `break_number`: PositiveIntegerField for break sequence (1, 2, 3...)
- `total_breaks_in_batch`: PositiveIntegerField for total count in batch

**Pricing Service** (`apps/technician_portal/services/batch_pricing_service.py`):
- `calculate_batch_pricing(customer, unit_number, breaks_count)`: Returns progressive pricing breakdown
- `calculate_batch_total(pricing_breakdown)`: Computes batch summary with total cost
- `get_batch_pricing_preview(customer_id, unit_number, breaks_count)`: AJAX endpoint data
- Fully integrates with `pricing_service.calculate_repair_cost()` for custom pricing support

**Views** (`apps/technician_portal/views.py:445-633`):
- `create_multi_break_repair()`: Main batch creation view with transaction safety
- `get_batch_pricing_json()`: AJAX endpoint for live pricing preview
- URL: `/tech/repairs/create-multi-break/` and `/tech/api/batch-pricing/`

**Frontend** (`templates/technician_portal/multi_break_repair_form.html` + `static/js/multi_break.js`):
- Modal-based break entry (mobile-optimized with camera capture)
- Live pricing preview via AJAX
- LocalStorage autosave prevents data loss
- Photo previews and validation

**Form Validation** (`apps/technician_portal/forms.py:272-292`):
- Modified duplicate validation allows batches (same `repair_batch_id`)
- Blocks separate pending repairs for same unit (standard behavior)

**Testing** (`tests/bug_fixes/test_multi_break_repair.py`):
- 20 comprehensive tests covering progressive pricing, custom pricing, batch creation, transaction safety, duplicate validation
- All tests passing as of 11/8/2025

### Configuration Management
Settings use a `rs_systems/settings/` package with a shared base to prevent drift:
- **Shared base**: `rs_systems/settings/base.py`  canonical INSTALLED_APPS, MIDDLEWARE, TEMPLATES, etc.
- **Development**: `rs_systems/settings/development.py` (imports from base, used by `manage.py`)
- **Production**: `rs_systems/settings/production.py` (imports from base, used by wsgi/Procfile/EB)
- Adding a new app or middleware only requires editing `base.py`  both environments inherit it
- **Database Flexibility**: Supports PostgreSQL (production) and SQLite (development) via `dj_database_url`

**IMPORTANT  Rules for settings changes:**
1. **New apps**: Add to `INSTALLED_APPS` in `base.py`, never in development.py or production.py individually
2. **New middleware**: Add to `MIDDLEWARE` in `base.py` for the same reason
3. **New context processors**: Add to `TEMPLATES` in `base.py`
4. **Environment-specific overrides only** go in development.py or production.py (e.g., DEBUG, database config, caching backend, security hardening)
5. **Never create a separate settings file** for a new environment  add it as a new file under `rs_systems/settings/` that imports from `base.py`
6. The old `settings_aws.py` and top-level `settings.py` no longer exist  do not recreate them

### API & Documentation
- **REST Framework**: Full API with token authentication
- **Interactive Docs**: Available at `/api/schema/swagger-ui/`
- **Auto-generated Schema**: Uses `drf_spectacular` for OpenAPI documentation

## Important Development Patterns

### Manager Settings Architecture
- **Portal Separation**: Manager settings accessible only to managers (`is_manager=True`) and staff users
- **URL Pattern**: `/tech/settings/` namespace for all manager configuration endpoints
- **Permission Decorator**: `@manager_required` decorator in `apps/technician_portal/decorators.py` for view-level access control
- **UI Pattern**: Card-based interface with modal editing for modern, responsive UX
- **AJAX API**: RESTful endpoints for real-time CRUD operations without page refresh
- **Navigation Integration**: Manager Settings link appears in user dropdown menu for authorized users
- **File Organization**:
  - Views: `apps/technician_portal/views.py` (manager settings section)
  - Templates: `templates/technician_portal/settings/` directory
  - JavaScript: `static/js/manager_settings.js` (modal and AJAX handling)
  - CSS: `static/css/components/manager-settings.css` (card-based design system)
- **Future Phases**: See `docs/development/MANAGER_SETTINGS_ROADMAP.md` for planned pricing configuration and audit features

### Viscosity Rules Management (Added November 2025)
Temperature-based resin viscosity recommendations with auto-priority system:

**Auto-Priority System**:
- New rules automatically assigned priority: `(max existing priority + 10)`
- No manual priority input required - maximizes usability
- Visual priority badges:  1st, ˆ 2nd,  3rd, "4th", "5th"...
- Rules evaluated in priority order (lowest display_order first)
- When multiple rules match temperature, first matching rule wins

**Key Features**:
- CRUD operations via AJAX modals (`/tech/settings/viscosity/`)
- Temperature range validation (client + server side)
- Active/inactive toggle for rules
- Professional card-based UI with status indicators

**Implementation Details**:
- Model: `ViscosityRecommendation` (`apps/technician_portal/models.py:704-841`)
- Auto-priority logic: `apps/technician_portal/views.py:2110-2115`
- Priority display: `apps/technician_portal/views.py:2063-2071` (ordinal suffix helper)
- API Endpoints: GET/POST `/tech/settings/api/viscosity/`

### Model Relationships
- Use `get_or_create()` pattern for `UnitRepairCount` tracking in repair saves
- `RewardRedemption` can be linked to repairs via `applied_to_repair` foreign key
- Technician notifications are automatically created for pending redemptions

### Testing Strategy
- Test files follow Django conventions: `apps/[app_name]/api/tests.py`
- Use Django's built-in TestCase for database-backed tests
- Management commands in `core/management/commands/` for setup automation

### Database Migrations
- Custom migration files handle complex business logic setup
- Use `setup_db.py` and `setup_groups.py` for initial environment configuration
- All apps have migration directories under `apps/[app_name]/migrations/`

### Static File Management
- Static files in `static/` directory with component-based CSS organization
- Uses WhiteNoise for production static file serving
- JavaScript includes D3.js for customer portal data visualizations

## Environment Configuration

### Required Environment Variables
```bash
SECRET_KEY=your-secret-key
DEBUG=True/False
ENVIRONMENT=development/production
ALLOWED_HOSTS=localhost,yourdomain.com
```

### Database Configuration
```bash
# For AWS production deployment
USE_AWS_DB=true
AWS_DATABASE_URL=postgresql://username:password@your-rds-endpoint:5432/rs_systems

# For local development  
USE_AWS_DB=false
LOCAL_DATABASE_URL=sqlite:///db.sqlite3
```

### Quick Database Switching

The `.env` file contains both database configurations. Simply change `USE_AWS_DB` to switch:

**Option 1: Edit .env file directly**
```bash
# In .env file, change:
USE_AWS_DB=false  # for local SQLite
USE_AWS_DB=true   # for AWS PostgreSQL
```

**Option 2: Use environment variable override (temporary)**
```bash
# Use local database (default)
python manage.py setup_groups  # Uses local SQLite

# Switch to AWS database for one command
USE_AWS_DB=true python manage.py setup_groups  # Uses AWS PostgreSQL

# Or export for session
export USE_AWS_DB=true
python manage.py setup_groups  # Uses AWS PostgreSQL
python manage.py migrate       # Still uses AWS PostgreSQL

# Back to local
export USE_AWS_DB=false
python manage.py runserver  # Back to local SQLite
```

**Option 3: Create shell aliases (add to ~/.zshrc or ~/.bashrc)**
```bash
# Add these to your shell configuration
alias rs-local='export USE_AWS_DB=false && echo " Switched to LOCAL database"'
alias rs-aws='export USE_AWS_DB=true && echo "  Switched to AWS database"'

# Then use:
rs-local
python manage.py runserver

rs-aws
python manage.py setup_groups
```

### Security Settings
```bash
USE_HTTPS=true  # Enables security headers for production
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
```

### Media Storage Configuration
```bash
# AWS S3 Configuration (Production)
USE_S3=true
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=us-east-1

# Local Development (Default)
USE_S3=false  # Photos stored in media/ directory
```

### Notification System Configuration (Updated December 2025)
```bash
# SendGrid (Email) - Primary email provider
# Get API key from: https://app.sendgrid.com/settings/api_keys
SENDGRID_API_KEY=SG.your-api-key-here
DEFAULT_FROM_EMAIL=notifications@yourdomain.com
DEFAULT_FROM_NAME=Your Company Notifications
EMAIL_RATE_LIMIT=100  # Emails per second (SendGrid allows high rates)

# AWS SNS (SMS) - Optional, disabled by default
# Future: Consider Twilio for SMS (see docs/strategy/SAAS_NOTIFICATION_STRATEGY.md)
SMS_ENABLED=false  # Set to true to enable SMS
AWS_SNS_REGION=us-east-1
SMS_SENDER_ID=YourCompany
SMS_MAX_PRICE_USD=0.50

# Celery (Task Queue)
CELERY_BROKER_URL=redis://your-redis-endpoint:6379/0
CELERY_RESULT_BACKEND=redis://your-redis-endpoint:6379/0
CELERY_CONCURRENCY=4

# CloudWatch Monitoring - Optional
AWS_CLOUDWATCH_ENABLED=false  # Set to true to enable metrics
```

**Production Setup**:
- For initial setup: See `docs/deployment/NOTIFICATION_NEXT_STEPS.md`
- Requires ElastiCache Redis cluster (production) or local Redis (development)
- SendGrid domain authentication required (DKIM/SPF via DNS records)
- SMS spend limit defaults to $1/month (~150 messages)

## Portal Separation Testing & Troubleshooting

### Testing Portal Functionality
```bash
# Test all portals are accessible
curl -I http://localhost:8000/                    # Should return 200 (landing page)
curl -I http://localhost:8000/app/                # Should return 302 (redirect to login)
curl -I http://localhost:8000/app/login/          # Should return 200 (customer login)
curl -I http://localhost:8000/tech/login/         # Should return 200 (technician login)
curl -I http://localhost:8000/login/              # Should return 200 (portal selection)

# Verify URL routing
python manage.py shell -c "
from django.urls import reverse
print('Customer dashboard:', reverse('customer_dashboard'))
print('Technician dashboard:', reverse('technician_dashboard'))
"

# Run all tests
python manage.py test --verbosity=2
```

### Troubleshooting Resources

For detailed troubleshooting, see the appropriate documentation:
- **Deployment Issues**: `docs/deployment/AWS_DEPLOYMENT.md#troubleshooting`
- **Security Incidents**: `docs/security/INCIDENT_RESPONSE.md`
- **Test Failures**: `docs/development/TESTING.md#debugging-failed-tests`
- **Admin Issues**: `docs/user-guides/ADMIN_GUIDE.md#troubleshooting`
- **User Portal Issues**: See respective user guides in `docs/user-guides/`

### Documentation Structure

**Professional SaaS Documentation** (as of December 2025):
```
/docs/
 README.md                           # Documentation index
 deployment/
    AWS_DEPLOYMENT.md              # Complete AWS deployment guide
    PRODUCTION_CHECKLIST.md        # Pre/post deployment verification
    NOTIFICATION_NEXT_STEPS.md     # Notification system deployment guide
 security/
    SECURITY_OVERVIEW.md           # Security features and roadmap
    INCIDENT_RESPONSE.md           # Emergency response procedures
 development/
    UI_DESIGN_GUIDE.md             # UI/UX design system and components
    WORKFLOW_IMPLEMENTATION.md     # Sprint tracking and phases
    TIMEZONE_HANDLING.md           # Multi-timezone support and datetime patterns
    CHANGELOG.md                   # Version history
    TESTING.md                     # Testing procedures
    notifications/                 # Notification system documentation
        README.md                  # Overview and architecture
        NOTIFICATION_README.md     # Technical implementation details
        NOTIFICATION_CONFIGURATION_GUIDE.md  # Configuration reference
        SIMPLE_TESTING_GUIDE.md    # Testing procedures
        ADMIN_DASHBOARD_GUIDE.md   # Admin interface guide
 operations/
    NOTIFICATION_OPERATIONS.md     # Daily operations guide
    NOTIFICATION_TROUBLESHOOTING.md # Common issues and solutions
 user-guides/
     ADMIN_GUIDE.md                 # Administrator interface guide
     TECHNICIAN_GUIDE.md            # Technician portal guide
     CUSTOMER_GUIDE.md              # Customer portal guide
```

**Quick Access**:
- All documentation: `/docs/README.md`
- UI/UX design system: `docs/development/UI_DESIGN_GUIDE.md`
- Timezone handling: `docs/development/TIMEZONE_HANDLING.md`
- Current implementation: `docs/development/WORKFLOW_IMPLEMENTATION.md`
- Version history: `docs/development/CHANGELOG.md`
- Notification deployment: `docs/deployment/NOTIFICATION_NEXT_STEPS.md`
- Notification operations: `docs/operations/NOTIFICATION_OPERATIONS.md`

## Settings Refactor (January 2026)

### What happened
After the amelia branch merge, `settings_aws.py` (production) was missing 4 apps (`clawdbot`, `billing`, `tenants`, `saas`), 2 middleware (`TenantMiddleware`, `PortalAccessMiddleware`), the `portal_access` context processor, and throttle rates that had been added to `settings.py` (dev). This caused the production deploy to crash. The root cause was maintaining two independent settings files that could drift apart.

### What was done
Refactored into a `rs_systems/settings/` package:

| File | Role |
|------|------|
| `settings/__init__.py` | Empty  makes it a Python package |
| `settings/base.py` | **Single source of truth** for INSTALLED_APPS, MIDDLEWARE, TEMPLATES, REST_FRAMEWORK, email, SMS, Stripe, Celery shared config |
| `settings/development.py` | `from .base import *` + dev overrides: DEBUG=True, SECRET_KEY fallback, SQLite fallback, Redis-with-memory-fallback, TIME_ZONE America/Chicago, dotenv loading |
| `settings/production.py` | `from .base import *` + prod overrides: SECRET_KEY required, DEBUG=False, PostgreSQL required, S3 STORAGES, hardened security, Redis-only, Sentry, CloudWatch, TIME_ZONE UTC |

### Files deleted
- `rs_systems/settings.py`  replaced by `settings/` package
- `rs_systems/settings_aws.py`  replaced by `settings/production.py`

### References updated
All files that pointed to `settings_aws` or bare `rs_systems.settings` were updated:
- `wsgi.py`, `asgi.py`  `rs_systems.settings.production`
- `Procfile`, `.ebextensions/01_wsgi.config`  `rs_systems.settings.production`
- `celery.py`  defaults to `rs_systems.settings.development` (production overrides via Procfile/EB)
- `manage.py`  `rs_systems.settings.development`
- `deployment/celery-worker.service`, `celery-beat.service`  `rs_systems.settings.production`
- Test files and scripts  `rs_systems.settings.development`

### Why this matters
Adding a new Django app or middleware now requires exactly one edit to `base.py`. Both development and production inherit it. The class of bug that crashed the deploy is structurally impossible with this layout.

## Deployment to AWS Elastic Beanstalk

### How to deploy
```bash
eb deploy        # from /Users/drakeduncan/projects/rs_systems_branch2
eb events | head -20   # check for success
curl -I https://rssystems.io/health/   # should return 200
```

### Critical: EB environment variables override config files
The EB console/`eb setenv` environment variables **take precedence** over `option_settings` in `.ebextensions/*.config` files. If a deploy fails, check `eb printenv` to verify `DJANGO_SETTINGS_MODULE` is set correctly.

**Current required EB environment variable:**
```
DJANGO_SETTINGS_MODULE=rs_systems.settings.production
```

If this is wrong (e.g., still pointing to an old deleted module), fix it with:
```bash
eb setenv DJANGO_SETTINGS_MODULE=rs_systems.settings.production
```

### Deploy workflow
EB deploys from the **local `main` branch**. If you're working on a feature branch:
1. Commit and push your feature branch
2. Merge into `main` (via GitHub PR or `git merge`)
3. `git checkout main && git pull origin main` to ensure local main is up to date
4. Run `eb deploy` from the project root (deploys whatever is on the local `main` branch)
5. Check `eb events | head -20` for success
6. Verify with `curl -I https://rssystems.io/health/` (expect 200)

**Important:** `eb deploy` packages the **local working directory**, not what's on GitHub. Always pull latest `main` before deploying. Never deploy from a feature branch.

**Never change `DJANGO_SETTINGS_MODULE`** in the EB console  it must stay as `rs_systems.settings.production`.

### Common deploy failure causes
- **Missing EB env var**: `eb printenv` shows wrong `DJANGO_SETTINGS_MODULE`  fix with `eb setenv`
- **New app/middleware not in base.py**: Add to `rs_systems/settings/base.py`, not individual env files
- **Missing Python package**: Add to `requirements.txt` before deploying
- **collectstatic fails**: Usually a settings import error  check that production.py loads cleanly