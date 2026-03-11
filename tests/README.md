# RS Systems Test Suite

Organized testing structure for the RS Systems windshield repair application.

## Directory Structure

```
tests/
 README.md                          # This file
 bug_fixes/                         # Regression tests for specific bug fixes
    test_reward_discount_fix.py   # Tests for reward discount category bug
 integration/                       # Integration and system flow tests
    test_system_flow.py           # Comprehensive end-to-end system tests
 load/                              # Performance and load testing
    load_test_simple.py           # Simple load testing script
 scripts/                           # Test data generation and utilities
     create_test_data.py           # Management command to create test data
```

## Django App Tests (Not in this directory)

Standard Django unit tests are located within each app following Django conventions:

- `core/tests.py` - Tests for Customer model
- `apps/customer_portal/tests.py` - Tests for customer portal models and views
- `apps/rewards_referrals/tests.py` - Tests for rewards system
- `apps/technician_portal/api/tests.py` - Tests for technician API

**Run Django app tests:**
```bash
python manage.py test                          # Run all tests
python manage.py test apps.customer_portal    # Test specific app
python manage.py test core.tests.CustomerModelTest  # Test specific test class
```

## Standalone Test Scripts

### Bug Fixes (`bug_fixes/`)

**Purpose:** Regression tests for specific bugs to ensure they don't reoccur

**test_reward_discount_fix.py**
- **What it tests:** Reward discount calculation logic
- **Why keep it:** Prevents regression of critical billing bug
- **How to run:** `python tests/bug_fixes/test_reward_discount_fix.py`
- **Tests:**
  - MERCHANDISE rewards (donuts, pizza) do NOT reduce repair costs 
  - REPAIR_DISCOUNT (50% off) correctly reduces repair costs 
  - FREE_SERVICE rewards make repairs free 
  - No reward applied shows full cost 

**Recommendation:**  **KEEP** - Valuable regression test for financial logic

### Integration Tests (`integration/`)

**Purpose:** End-to-end system flow testing

**test_system_flow.py**
- **What it tests:** Complete customer  technician  repair workflow
- **Why keep it:** Validates critical business processes
- **How to run:** `python manage.py test_system_flow [--cleanup] [--verbose]`
- **Tests:**
  - Customer repair request flow
  - Technician assignment and visibility
  - Multiple technician scenarios
  - Portal separation (customer vs technician)
  - Repair status progression

**Recommendation:**  **KEEP** - Essential for verifying system integrity after major changes

### Load Tests (`load/`)

**Purpose:** Performance testing and monitoring

**load_test_simple.py**
- **What it tests:** Application response times and concurrent load handling
- **Why keep it:** Quick health checks and performance monitoring
- **How to run:** `python tests/load/load_test_simple.py`
- **Features:**
  - Configurable request count and thread pool
  - Response time statistics (mean, median)
  - Success rate monitoring
  - Targets production URL: https://rssystems.io

**Recommendation:**  **KEEP** - Useful for production health monitoring

### Scripts (`scripts/`)

**Purpose:** Test data generation and setup utilities

**create_test_data.py**
- **What it does:** Creates sample data for testing
- **Why keep it:** Useful for development environment setup
- **How to run:** `python manage.py create_test_data`

**Recommendation:**  **KEEP** - Helpful for dev/staging environments

### Security Note

Previously, there was a `test_database_persistence.py` file with hardcoded production credentials. This file has been **permanently deleted** and was never committed to version control. All sensitive credentials should always use environment variables.

## What to Keep vs Delete

###  KEEP (High Value)

1. **`bug_fixes/test_reward_discount_fix.py`**
   - Prevents critical billing bug regression
   - Comprehensive coverage (17 test cases)
   - Self-contained, no external dependencies

2. **`integration/test_system_flow.py`**
   - Tests complete business workflows
   - Catches integration issues early
   - Can be run as management command

3. **`load/load_test_simple.py`**
   - Quick production health checks
   - Performance baseline tracking
   - Lightweight and easy to run

4. **`scripts/create_test_data.py`**
   - Speeds up development setup
   - Creates realistic test scenarios
   - Useful for demos and staging

5. **Django app tests** (in app directories)
   - Standard Django testing practice
   - Unit tests for models/views/APIs
   - Part of CI/CD pipeline

###  Security & Cleanup

All sensitive test files have been removed. No files with hardcoded credentials exist in this repository.

###  Consider Adding (Future)

1. **API endpoint tests** - More comprehensive REST API testing
2. **UI integration tests** - Selenium/Playwright for critical user flows
3. **Database migration tests** - Validate migration rollback scenarios
4. **Security tests** - Automated security scanning (OWASP checks)
5. **Photo upload tests** - S3 integration and file handling

## Running All Tests

```bash
# Django unit tests
python manage.py test

# Specific bug fix test
python tests/bug_fixes/test_reward_discount_fix.py

# System flow integration test
python manage.py test_system_flow --verbose

# Load test (production)
python tests/load/load_test_simple.py

# Create test data (development)
python manage.py create_test_data
```

## Best Practices

1. **Bug Fix Tests:** Every time you fix a bug, create a regression test
2. **Integration Tests:** Update when adding major features or workflows
3. **Load Tests:** Run before major releases to catch performance issues
4. **Naming:** Use descriptive names: `test_<feature>_<scenario>.py`
5. **Documentation:** Include docstrings explaining what each test validates
6. **Cleanup:** Always clean up test data (use try/finally or Django's TestCase)
7. **Security:** NEVER hardcode credentials - use environment variables

## CI/CD Integration

To add these tests to your CI/CD pipeline:

```yaml
# Example GitHub Actions
- name: Run Django Tests
  run: python manage.py test

- name: Run Bug Fix Tests
  run: python tests/bug_fixes/test_reward_discount_fix.py

- name: Run Integration Tests
  run: python manage.py test_system_flow --cleanup
```

## Maintenance

- **Review quarterly:** Check if tests are still relevant
- **Update after bugs:** Add regression test when fixing bugs
- **Archive carefully:** Move deprecated tests to `deprecated/` before deletion
- **Document changes:** Update this README when adding/removing tests

---

**Last Updated:** November 6, 2025
**Maintained By:** Development Team
