# Testing Guide - RS Systems

Comprehensive testing procedures for the RS Systems windshield repair management platform.

**Last Updated**: March 2026

## Table of Contents
- [Quick Start](#quick-start)
- [Test Suite Structure](#test-suite-structure)
- [Automated Testing](#automated-testing)
- [Manual Testing Procedures](#manual-testing-procedures)
- [Feature Testing](#feature-testing)
- [Security Testing](#security-testing)
- [Performance Testing](#performance-testing)
- [Testing Best Practices](#testing-best-practices)

---

## Quick Start

```bash
# Set up test environment
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development

# Full suite (~331 tests, ~7 min)
python manage.py test tests/ -v 1

# Fast smoke tests (use during dev)
python manage.py test tests.test_primary_contact tests.test_e2e_today -v 2

# Specific test file
python manage.py test tests.test_admin
python manage.py test tests.test_subscription_expiry
python manage.py test tests.test_billing_phase6
```

### Quick System Verification
```bash
# Run Django system checks
python manage.py check --deploy
```

---

## Test Suite Structure

All canonical tests live in `tests/` (top-level). Some app-level `tests.py` exist but the main suite is here.

```
tests/
├── README.md
├── helpers.py                          # Shared test utilities
├── test_e2e_today.py                   # Core E2E workflow tests
├── test_primary_contact.py             # Primary contact notification tests
├── test_admin.py                       # Admin console (41 tests) — v2.4
├── test_subscription_expiry.py         # Subscription expiry UX (31 tests) — v2.3
├── test_billing_phase6.py              # Billing Phase 6 features (32 tests)
├── test_owner_setup.py                 # Configure Your Shop (/owner/setup/) tests
├── test_ux004_005_fixes.py             # UX fix regression tests
├── test_auth_permissions.py
├── test_billing_models.py
├── test_bug_fixes_march.py
├── test_models_core.py
├── test_step3_signup.py
├── test_step5_nav.py
├── test_tenant_isolation.py
├── test_tenant_isolation_round3.py
├── test_tenant_isolation_round4.py
├── test_url_routing.py
├── bug_fixes/                          # Regression tests for specific bugs
│   ├── test_billing_settings_ux.py
│   ├── test_code001_exception_logging.py
│   ├── test_code003_invoice_created_at_index.py
│   ├── test_code004_n_plus_one_batch_views.py
│   ├── test_custom_error_pages.py
│   ├── test_multi_break_repair.py
│   ├── test_navbar_duplicate.py
│   ├── test_reward_discount_fix.py
│   ├── test_ux003_portal_preview.py
│   ├── test_ux006_assignment_context.py
│   ├── test_ux007_customer_phone.py
│   ├── test_ux009_team_role_badges.py
│   └── test_ux_template_fixes.py
├── comprehensive/                      # Longer integration flows
├── integration/
└── security/
```

### Key Test Files by Feature

| File | Tests | Feature |
|------|-------|---------|
| `test_admin.py` | 41 | Admin console: dashboard, tenant filter, CSV export, global search, audit log |
| `test_subscription_expiry.py` | 31 | Grace period, blocked page, email alerts, middleware |
| `test_billing_phase6.py` | 32 | Aging widget, statement of account, remind from list, EB cron |
| `test_owner_setup.py` | — | Configure Your Shop page, viscosity auto-populate |
| `test_ux004_005_fixes.py` | — | UX fix regression tests |

---

## Automated Testing

### Test Setup Pattern

Always use `force_login` (not `client.login`) and set `tenant_id` in session:

```python
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants.models import SubscriptionPlan

class MyTestCase(TestCase):
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        result = create_tenant_with_owner(
            business_name='Test Shop', email='owner@test.com',
            password='testpass123!', first_name='Test', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
```

### Test Categories

#### 1. Model Tests
```python
# Test model creation and fields
def test_customer_pricing_model(self):
    pricing = CustomerPricing.objects.create(
        customer=customer,
        use_custom_pricing=True,
        repair_1_price=Decimal('45.00')
    )
    self.assertTrue(pricing.use_custom_pricing)
    self.assertEqual(pricing.repair_1_price, Decimal('45.00'))
```

#### 2. Business Logic Tests
```python
# Test pricing calculations
def test_pricing_calculation(self):
    cost = calculate_repair_cost(customer, 1)
    self.assertEqual(cost, Decimal('45.00'))  # Custom pricing
```

#### 3. Permission Tests
```python
# Test manager permissions
def test_manager_override_permission(self):
    can_override = can_manager_override_price(technician, Decimal('100.00'))
    self.assertTrue(can_override)  # Within $150 limit
```

#### 4. Integration Tests
```python
# Test repair creation with pricing
def test_repair_uses_pricing_service(self):
    repair = Repair.objects.create(customer=customer, unit_number='UNIT001')
    self.assertEqual(repair.cost, Decimal('45.00'))  # Applied custom pricing
```

---

## Manual Testing Procedures

### Customer Portal Testing

#### Test 1: Customer Registration
```
Steps:
1. Navigate to https://[domain]/app/register/
2. Fill out registration form:
   - Company name: Test Company
   - Contact name: Test User
   - Email: test@example.com
   - Phone: 555-0123
   - Address: 123 Test St
   - Password: TestPass123
3. Submit form

Expected:
 Success message displayed
 User logged in automatically
 Dashboard loads
 Welcome points awarded (if configured)
```

#### Test 2: Repair Request Submission
```
Steps:
1. Login: https://[domain]/app/login/
2. Navigate to "Submit Repair Request"
3. Fill form:
   - Unit number: TEST001
   - Damage type: CHIP
   - Description: "Test damage"
   - (Optional) Upload photo
4. Submit

Expected:
 Request created successfully
 Status shows "REQUESTED"
 Appears on dashboard
 Photo uploaded (if provided)
```

#### Test 3: Repair Approval (PENDING Repairs)
```
Steps:
1. Login as customer with PENDING repair
2. Check dashboard for yellow alert banner
3. Review repair details:
   - Unit number
   - Damage type
   - Technician name
   - Cost estimate
   - Technician notes
4. Click "Approve" or "Deny"

Expected:
 Yellow alert banner visible
 All repair details shown
 Approve button works
 Deny shows confirmation dialog
 Status updates correctly
 Alert disappears after action
```

### Technician Portal Testing

#### Test 4: Technician Login
```
Steps:
1. Navigate to https://[domain]/tech/login/
2. Enter credentials:
   - Username: [tech_username]
   - Password: [password]
3. Submit

Expected:
 Login successful
 Dashboard loads
 Shows repair queues
 Shows notifications
```

#### Test 5: Manager Assignment (REQUESTED Repairs)
```
Prerequisites:
- User is a manager
- REQUESTED repair exists

Steps:
1. Login as manager
2. View "Customer Requested Repairs" section
3. Click on REQUESTED repair
4. Click "Assign to Technician"
5. Select technician from dropdown
6. Submit assignment

Expected:
 Only shows technicians managed by this manager
 Assignment succeeds
 Repair status  APPROVED
 Assigned technician receives notification
 Notification includes repair link
```

#### Test 6: Field Repair Creation (with Approval Required)
```
Prerequisites:
- Customer has "Require Approval" preference

Steps:
1. Login as technician
2. Create new repair:
   - Customer: [Customer requiring approval]
   - Unit: UNIT002
   - Damage type: CHIP
   - Notes: "Found during inspection"
   - Try setting status to COMPLETED
3. Submit

Expected:
 Repair created
 Status forced to PENDING (NOT COMPLETED)
 Warning message: "Customer requires approval"
 Repair visible to customer
 NOT visible to technician after creation
```

#### Test 7: Manager Pricing Override
```
Prerequisites:
- User is manager with override permission
- Manager has approval limit (e.g., $150)

Steps:
1. Login as manager
2. Create/edit repair
3. Scroll to "Manager Pricing Override" section
4. Enter override price: $100
5. Enter reason: "Customer complaint resolution"
6. Submit

Test Cases:
a) Within limit ($100, limit $150):  Should succeed
b) Exceeds limit ($200, limit $150):  Should fail with error
c) No reason provided:  Should fail with validation error

Expected:
 Override section visible to managers only
 Validation enforces approval limit
 Reason required
 Override price applied to repair
```

### Admin Interface Testing

#### Test 8: Customer Pricing Configuration
```
Steps:
1. Login to admin: https://[domain]/admin/
2. Navigate to Customer Portal  Customer Pricing
3. Click "Add customer pricing"
4. Configure:
   - Customer: ABC Logistics
   - Use custom pricing: 
   - Repair 1 price: 45.00
   - Repair 2 price: 35.00
   - Volume discount threshold: 10
   - Volume discount percentage: 15.00
   - Notes: "VIP customer - 10% discount + 15% volume bonus"
5. Save

Expected:
 Pricing saves successfully
 Appears in pricing list
 All fields retained
 Created by auto-populated
```

#### Test 9: Customer Repair Preferences
```
Steps:
1. Admin  Customer Portal  Customer Repair Preferences
2. Add preference:
   - Customer: [Select customer]
   - Approval mode: REQUIRE_APPROVAL
3. Save

Test customer repair creation:
- Should force PENDING status
- Should show on customer dashboard
- Should require approval

Test approval modes:
a) AUTO_APPROVE: All repairs auto-approved
b) REQUIRE_APPROVAL: All require approval
c) UNIT_THRESHOLD (3): First 3 units auto-approved, rest require approval
```

---

## Feature Testing

### Sprint 1: Core Pricing & Roles (September 2025)

####  Feature 1.1: Customer Pricing Tiers
**Test Status**: PASSED (automated + manual)

```bash
# Automated test
python test_sprint1.py  # Tests 1-2

# Manual verification
python manage.py shell -c "
from core.models import Customer
from apps.technician_portal.services.pricing_service import calculate_repair_cost
customer = Customer.objects.get(name='ABC Logistics')
print(f'1st repair: \${calculate_repair_cost(customer, 1)}')
print(f'2nd repair: \${calculate_repair_cost(customer, 2)}')
print(f'5th+ repair: \${calculate_repair_cost(customer, 5)}')
"
```

####  Feature 1.2: Volume Discounts
**Test Status**: PASSED

```python
# Test volume discount calculation
from apps.customer_portal.pricing_models import CustomerPricing

pricing = CustomerPricing.objects.get(customer=customer)
# Assume customer has 12 total repairs, threshold is 10
cost_without_discount = Decimal('35.00')
cost_with_discount = pricing.apply_volume_discount(cost_without_discount)
# Expected: $29.75 (15% discount)
```

####  Feature 1.3: Manager Override
**Test Status**: PASSED

```
Manual Test:
1. Login as manager with $150 limit
2. Create repair, override to $140 
3. Try override to $160  (exceeds limit)
4. Override to $140 without reason  (validation fails)
```

### October 2025: Critical Security & Workflow

####  Feature 2.1: Approval Bypass Prevention
**Test Status**: PASSED

```
Security Test:
1. Customer has "Require Approval" preference
2. Technician creates repair
3. Technician tries to set status to COMPLETED
4. Expected: Forced to PENDING
5. Actual:  Forced to PENDING with warning message

Result: SECURITY FIX VERIFIED 
```

####  Feature 2.2: Manager Assignment
**Test Status**: PASSED

```
Workflow Test:
1. Customer submits repair request (status: REQUESTED)
2. Manager sees repair in dashboard
3. Non-manager does NOT see repair 
4. Manager assigns to Tech A
5. Status changes to APPROVED 
6. Tech A receives notification with link 
7. Tech B cannot see assignment (not their repair) 

Result: ALL CHECKS PASSED 
```

####  Feature 2.3: Customer Approval Dashboard
**Test Status**: PASSED

```
UX Test:
1. Tech creates field repair (PENDING)
2. Customer logs in
3. Yellow alert banner visible 
4. Shows: unit, damage, tech, cost, notes 
5. Approve button works 
6. Deny with confirmation works 
7. Alert disappears after action 

Result: UX VERIFIED 
```

####  Feature 2.4: Repair Visibility Controls
**Test Status**: PASSED

```
Access Control Test:
1. REQUESTED repair:
   - Manager can view 
   - Non-manager cannot view 
   - Non-manager gets error message 

2. PENDING repair:
   - Customer can view 
   - ALL technicians cannot view 
   - Direct URL access blocked 
   - Shows "pending approval" message 

Result: ACCESS CONTROL VERIFIED 
```

---

## Security Testing

### Authentication Tests

#### Test S1: Rate Limiting
```
Steps:
1. Attempt login with wrong password 10 times
2. Attempt 11th login

Expected:
 First 10 attempts: "Invalid credentials"
 11th attempt: "Rate limit exceeded"
 Blocked for 1 hour
```

#### Test S2: Bot Protection
```
Test Cases:
a) Username "ygzwnplsgv":  Rejected (suspicious pattern)
b) Username "a1b2c3d4e5":  Rejected (hex pattern)
c) Username "testuser123":  Accepted (normal pattern)

Expected:
 Suspicious usernames blocked
 Error message: "Username appears suspicious"
```

#### Test S3: Honeypot Protection
```
Steps:
1. Registration form has hidden "website" field
2. Bot fills hidden field
3. Submit form

Expected:
 Registration rejected silently
 No error message shown (don't alert bot)
```

### Authorization Tests

#### Test S4: Portal Access Control
```
Test Cases:
1. Customer tries to access /tech/:  Forbidden
2. Technician tries to access /app/:  Forbidden
3. Customer accesses /app/:  Allowed
4. Technician accesses /tech/:  Allowed

Expected:
 Portal boundaries enforced
 Redirect to appropriate login
```

#### Test S5: Manager Permission Checks
```
Test Cases:
1. Non-manager tries to view override section:  Hidden
2. Manager without override permission:  Hidden
3. Manager with override permission:  Visible
4. Non-manager tries direct POST to override:  Validation fails

Expected:
 UI hides based on permissions
 Server-side validation enforces permissions
```

### Security Audit Tests

```bash
# Run security audit
python manage.py security_audit

# Check for suspicious users
python manage.py security_audit --check-user testuser

# Clean up bot accounts
python manage.py security_audit --delete-suspicious

Expected:
 Identifies suspicious patterns
 Lists potential bot accounts
 Cleanup works correctly
```

---

## Performance Testing

### Database Query Performance

```python
# Check for N+1 queries
from django.test.utils import override_settings
from django.db import connection
from django.test import TestCase

with override_settings(DEBUG=True):
    connection.queries_log.clear()
    # Perform action
    repairs = Repair.objects.all()[:10]
    for repair in repairs:
        customer_name = repair.customer.name

    # Check query count
    query_count = len(connection.queries)
    print(f"Queries executed: {query_count}")
    # Should be ~2 (1 for repairs, 1 for customers with select_related)
```

### Page Load Testing

```bash
# Test page load times
curl -w "@curl-format.txt" -o /dev/null -s https://[domain]/app/

# curl-format.txt:
# time_namelookup:  %{time_namelookup}\n
# time_connect:  %{time_connect}\n
# time_starttransfer:  %{time_starttransfer}\n
# time_total:  %{time_total}\n

# Expected:
# < 1s for static pages
# < 3s for dashboard pages with data
```

### Load Testing (Production)

```bash
# Use Apache Bench for basic load testing
ab -n 1000 -c 10 https://[domain]/

# -n 1000: Total requests
# -c 10: Concurrent requests

# Expected:
# Requests per second: >50
# Time per request: <200ms average
# Failed requests: 0
```

---

## Testing Best Practices

### Before Deployment

**Pre-Deployment Checklist:**
- [ ] All tests passing (`python manage.py test`)
- [ ] Django system check clean (`python manage.py check --deploy`)
- [ ] Security audit clean (`python manage.py security_audit`)
- [ ] Manual testing of new features complete
- [ ] Regression testing of existing features
- [ ] Performance testing acceptable
- [ ] Database migrations tested on development database

### Test Data Management

**Creating Test Data:**
```bash
# Create fresh test data
python manage.py create_test_data --clean

# Creates:
# - 3 customers (abc logistics, city delivery, eos trucking)
# - 3 technicians (tech1, tech2, tech3)
# - Various repairs in different statuses
# - Sample pricing configurations
```

**Cleaning Test Data:**
```python
# Remove test data (use carefully!)
from django.contrib.auth.models import User

# Remove test users
User.objects.filter(username__startswith='test').delete()

# Remove test customers
Customer.objects.filter(name__icontains='test').delete()
```

### Continuous Integration

**GitHub Actions Example:**
```yaml
name: Django Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run tests
        run: |
          python manage.py test
          python manage.py check --deploy
```

---

## Test Coverage

### Current Coverage (Estimated)

- **Models**: ~80% covered
- **Views**: ~70% covered
- **Business Logic**: ~90% covered
- **Templates**: Manual testing only
- **API**: ~85% covered

### Generating Coverage Report

```bash
# Install coverage
pip install coverage

# Run tests with coverage
coverage run --source='.' manage.py test

# Generate report
coverage report

# HTML report
coverage html
# Open htmlcov/index.html
```

---

## Debugging Failed Tests

### Common Issues

**Issue 1: Database Integrity Errors**
```python
# Clear test database
python manage.py flush --no-input

# Or use fresh migrations
python manage.py migrate --run-syncdb
```

**Issue 2: Import Errors**
```python
# Check Python path
import sys
print(sys.path)

# Ensure project root is in path
```

**Issue 3: Permissions Errors**
```python
# Ensure test user has correct permissions
from django.contrib.auth.models import Group, Permission

# Add user to group
tech_group = Group.objects.get(name='Technicians')
user.groups.add(tech_group)
```

### Verbose Test Output

```bash
# Run with maximum verbosity
python manage.py test --verbosity=3

# Keep test database
python manage.py test --keepdb

# Run specific test
python manage.py test apps.technician_portal.tests.TestRepairModel.test_pricing
```

---

## Resources

### Testing Documentation
- [Django Testing](https://docs.djangoproject.com/en/stable/topics/testing/)
- [Django REST Framework Testing](https://www.django-rest-framework.org/api-guide/testing/)
- [Coverage.py](https://coverage.readthedocs.io/)

### Internal Docs
- [Changelog](/docs/development/CHANGELOG.md)
- [Deployment Checklist](/docs/deployment/PRODUCTION_CHECKLIST.md)
- [Security Testing](/docs/security/SECURITY_OVERVIEW.md)

---

**Last Updated**: October 21, 2025
**Test Suite Version**: 1.4.0
**Test Coverage Target**: 85%
**Status**: All Tests Passing 
