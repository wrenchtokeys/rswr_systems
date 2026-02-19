# RS Systems Testing Guide

## Overview

This guide provides comprehensive testing procedures for the RS Systems windshield repair management platform. It covers automated testing, manual testing workflows, and regression testing to ensure system reliability and functionality.

## Table of Contents

- [Quick Testing Setup](#quick-testing-setup)
- [Automated Testing](#automated-testing)
- [Manual Testing Workflows](#manual-testing-workflows)
- [Test Data Management](#test-data-management)
- [Regression Testing](#regression-testing)
- [Performance Testing](#performance-testing)
- [Security Testing](#security-testing)
- [Testing Environments](#testing-environments)

## Quick Testing Setup

### Prerequisites
- Functioning Django environment (see main README.md)
- Database access (SQLite for development, PostgreSQL for production)
- Valid user accounts or ability to create test data

### Initial Setup
```bash
# Ensure database is set up
python manage.py setup_db
python manage.py setup_groups

# Create test data (recommended for testing)
python manage.py create_test_data --clean
```

## Automated Testing

### Django Unit Tests

The system includes Django's built-in testing framework for component testing:

```bash
# Run all tests
python manage.py test

# Test specific apps
python manage.py test apps.technician_portal
python manage.py test apps.customer_portal
python manage.py test apps.rewards_referrals

# Test with verbose output
python manage.py test --verbosity=2

# Test specific test cases
python manage.py test apps.technician_portal.tests.RepairTestCase
```

### System Flow Testing

A comprehensive automated test validates the complete repair request flow:

```bash
# Run the automated system flow test
python manage.py test_system_flow --verbose

# Run with cleanup of test data
python manage.py test_system_flow --cleanup
```

**What the System Flow Test Covers:**
- Customer repair request creation
- Technician assignment with load balancing
- Multi-technician visibility validation
- Portal separation and authentication
- Complete repair status progression (REQUESTED  COMPLETED)
- Cost calculation verification
- Reward application testing

### Expected Test Results

**Successful Test Output:**
```
=== Testing Repair Request Flow ===
 Customer login successful
 Repair request submitted successfully
 Repair created in database with ID [number]
 Repair assigned to technician: [username]
 Repair should be visible to technician [tech1]
 Repair should be visible to technician [tech2]
 Status updated to APPROVED
 Status updated to IN_PROGRESS
 Status updated to COMPLETED
 Final cost calculated: $50.00

 All tests passed! The repair flow is working correctly.
```

## Manual Testing Workflows

### Complete End-to-End Testing

This workflow tests the entire system from customer request through completion:

#### Step 1: Customer Portal Testing

1. **Login as Customer**
   - URL: `http://localhost:8000/app/login/`
   - Username: `democustomer`
   - Password: `demo123`

2. **Submit Repair Request**
   - Navigate to "Request Repair"
   - Fill out form:
     - Unit Number: `TEST001`
     - Description: `Front windshield crack repair`
     - Damage Type: `Crack`
   - Submit request
   - **Expected Result**: Success message and redirect to dashboard

3. **Verify Request in Dashboard**
   - Check that repair appears in "Recent Repairs"
   - Status should be "Customer Requested"
   - Note the repair ID for tracking

#### Step 2: Technician Portal Testing

1. **Login as Technician**
   - URL: `http://localhost:8000/tech/login/`
   - Username: `tech1`, `tech2`, or `tech3`
   - Password: `demo123`

2. **Verify Repair Visibility**
   - Check dashboard for "Customer Requested Repairs" section
   - **Expected Result**: The repair from Step 1 should be visible
   - **Important**: ALL technicians should see the repair (this validates the fix)

3. **Accept and Progress Repair**
   - Click on the repair to view details
   - Update status to "Approved"
   - **Expected Result**: Customer notification, status change logged
   - Progress through: `Approved`  `In Progress`  `Completed`

4. **Verify Cost Calculation**
   - When marked "Completed", cost should be automatically calculated
   - **Expected Result**: $50.00 for first repair of this unit

#### Step 3: Multi-Technician Testing

1. **Test Load Balancing**
   - Create multiple repair requests as customer
   - Check that repairs are distributed among available technicians
   - **Expected Result**: Repairs assigned to technicians with least current workload

2. **Test Visibility Across Technicians**
   - Login as different technicians
   - **Expected Result**: All REQUESTED repairs visible to all technicians

### Portal Separation Testing

#### Customer Portal Access Control
```bash
# Test customer portal URLs
http://localhost:8000/app/           # Should redirect to login if not authenticated
http://localhost:8000/app/login/     # Customer login page
http://localhost:8000/app/register/  # Customer registration
```

#### Technician Portal Access Control
```bash
# Test technician portal URLs
http://localhost:8000/tech/          # Should redirect to login if not authenticated
http://localhost:8000/tech/login/    # Technician login page
```

#### Cross-Portal Security
1. **Login as Customer**
2. **Attempt to Access Technician Portal**
   - Try: `http://localhost:8000/tech/`
   - **Expected Result**: Redirect or access denied

3. **Login as Technician**
4. **Attempt to Access Customer Portal**
   - Try: `http://localhost:8000/app/`
   - **Expected Result**: Redirect or access denied

## Test Data Management

### Creating Test Data

The system provides a management command for creating consistent test data:

```bash
# Create fresh test data
python manage.py create_test_data --clean

# Create test data without cleaning existing data
python manage.py create_test_data
```

**Test Accounts Created:**
- **Customer**: `democustomer` / `demo123`
- **Technicians**: `tech1`, `tech2`, `tech3` / `demo123`
- **Admin**: `demoadmin` / `demo123`

### Cleaning Test Data

```bash
# Clean only test data (preserves real data)
python manage.py create_test_data --clean
```

### Manual Test Data Setup

If you need to create test data manually:

1. **Create Customer Company**
   ```python
   # In Django shell (python manage.py shell)
   from core.models import Customer
   customer = Customer.objects.create(
       name='test company',
       email='test@company.com',
       phone='555-0123'
   )
   ```

2. **Create Customer User**
   ```python
   from django.contrib.auth.models import User
   from apps.customer_portal.models import CustomerUser
   
   user = User.objects.create_user(
       username='testcustomer',
       email='customer@test.com',
       password='testpass'
   )
   
   CustomerUser.objects.create(
       user=user,
       customer=customer,
       is_primary_contact=True
   )
   ```

## Regression Testing

### Critical Features to Test After Changes

1. **Repair Assignment Logic**
   - Customer creates repair  Assigned to technician with least load
   - Multiple repairs  Distributed evenly among technicians

2. **Repair Visibility**
   - All REQUESTED repairs visible to all technicians
   - Technicians can only modify their assigned repairs (non-admin)
   - Admins can see and modify all repairs

3. **Status Progression**
   - Customer request  Technician approval  Work completion
   - Automatic cost calculation on completion
   - Reward application when applicable

4. **Portal Separation**
   - Customers cannot access technician features
   - Technicians cannot access customer-only features
   - Proper authentication and authorization

### Automated Regression Testing

```bash
# Full regression test suite
python manage.py test --verbosity=2

# Quick smoke test
python manage.py test_system_flow --verbose --cleanup
```

## Performance Testing

### Load Testing Scenarios

1. **Multiple Simultaneous Repair Requests**
   - Create 10+ repair requests simultaneously
   - Verify load balancing works correctly
   - Check response times remain acceptable

2. **Database Query Performance**
   ```python
   # Test repair lookup performance
   from apps.technician_portal.models import Repair
   from django.test.utils import override_settings
   
   # Create 1000+ repairs and test query times
   repairs = Repair.objects.filter(queue_status='REQUESTED')
   # Should complete in <100ms for reasonable data sets
   ```

3. **Dashboard Loading**
   - Time technician dashboard loading with various data volumes
   - Customer dashboard performance with multiple repairs

## Security Testing

### Authentication Testing

1. **Password Security**
   - Test password requirements
   - Verify failed login handling
   - Test session timeout

2. **Authorization Testing**
   - Verify role-based access controls
   - Test that users cannot access unauthorized data
   - Confirm API endpoint security

3. **Data Protection**
   - Test that customer data is isolated
   - Verify technicians cannot see other technicians' assigned repairs
   - Confirm sensitive data is not exposed in API responses

### Security Test Commands

```bash
# Test with different user permissions
python manage.py test apps.security

# Verify API authentication
curl -H "Authorization: Token your-token" http://localhost:8000/api/repairs/
```

## Testing Environments

### Development Environment

**Setup:**
```bash
# Use SQLite database
export ENVIRONMENT=development
python manage.py setup_db
python manage.py create_test_data
```

**Characteristics:**
- SQLite database
- Debug mode enabled
- Test data pre-loaded
- All logging enabled

### Staging Environment

**Setup:**
```bash
# Use production-like database
export ENVIRONMENT=production
export DEBUG=False
export DATABASE_URL=postgresql://...
python manage.py setup_db
```

**Characteristics:**
- PostgreSQL database
- Production settings
- Limited debug information
- Performance monitoring

### Production Testing

**Important:** Never run destructive tests on production!

**Safe Production Tests:**
```bash
# Read-only API tests
curl https://yourdomain.com/api/repairs/ -H "Authorization: Token ..."

# Health check endpoints
curl https://yourdomain.com/health/
```

## Test Automation and CI/CD

### GitHub Actions (Example)

```yaml
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.x
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Setup database
        run: python manage.py setup_db
      - name: Run tests
        run: python manage.py test --verbosity=2
      - name: Run system flow test
        run: python manage.py test_system_flow --cleanup
```

## Troubleshooting Test Issues

### Common Test Failures

1. **"No technicians available"**
   - **Cause**: No technician accounts in database
   - **Solution**: Run `python manage.py create_test_data`

2. **"Repair not visible to technician"**
   - **Cause**: Dashboard not showing REQUESTED repairs correctly
   - **Solution**: Check technician assignment logic in `technician_portal/views.py:88-96`

3. **"Database connection error"**
   - **Cause**: Database not set up or incorrect configuration
   - **Solution**: Run `python manage.py setup_db` and check `CLAUDE.md` for configuration

4. **"Authentication failed"**
   - **Cause**: Test user accounts don't exist or wrong credentials
   - **Solution**: Verify test data creation or check password

### Test Environment Issues

1. **Port conflicts (development server)**
   ```bash
   # Kill processes on port 8000
   lsof -ti:8000 | xargs kill
   # Start server on different port
   python manage.py runserver 8001
   ```

2. **Database migration issues**
   ```bash
   # Reset migrations if needed (development only!)
   python manage.py migrate --fake-initial
   python manage.py migrate
   ```

3. **Static file issues**
   ```bash
   # Collect static files
   python manage.py collectstatic --noinput
   ```

## Test Metrics and Reporting

### Key Performance Indicators

- **Test Coverage**: Aim for >80% code coverage
- **Response Times**: API endpoints <200ms, Page loads <2s
- **Success Rates**: >99% for critical user flows
- **Error Rates**: <1% for all operations

### Test Reporting

```bash
# Generate test coverage report
coverage run --source='.' manage.py test
coverage report
coverage html  # Generates HTML report in htmlcov/
```

---

## Quick Reference

### Test Commands
```bash
# Essential test commands
python manage.py test                    # All unit tests
python manage.py test_system_flow       # End-to-end test
python manage.py create_test_data       # Create test accounts
```

### Test URLs (Development)
```
Customer Portal: http://localhost:8000/app/login/
Technician Portal: http://localhost:8000/tech/login/
Admin: http://localhost:8000/admin/
API Docs: http://localhost:8000/api/schema/swagger-ui/
```

### Test Accounts
```
Customer: democustomer / demo123
Technician: tech1, tech2, tech3 / demo123
Admin: demoadmin / demo123
```

This testing guide ensures comprehensive validation of the RS Systems platform functionality and helps maintain system reliability through systematic testing procedures.