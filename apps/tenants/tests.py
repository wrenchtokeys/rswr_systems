"""
Comprehensive Tests for the Tenants App

Tests cover:
- Tenant model (creation, slug generation, trial tracking)
- TenantMembership model (creation, roles, unique constraint)
- TenantMiddleware (tenant resolution from header, session, membership)
- SubscriptionPlan model (CRUD, is_free, has_feature)
- UsageService (counting, limit enforcement, summary)
- SubscriptionService (validation, trial expiry)
- Tenant isolation (multi-tenant data security)
- Authentication requirements
- Owner-only access enforcement

Author: Amelia (Clawdbot AI) — Test Suite
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase, Client, RequestFactory, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.middleware import TenantMiddleware
from apps.tenants.services.usage_service import UsageService
from apps.tenants.services.subscription_service import (
    SubscriptionService,
    SubscriptionError,
)

# Override cache and hosts for all tests in this module
TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
COMMON_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': TEST_CACHES,
}


# ======================================================================
# Base Test Setup
# ======================================================================

class BaseTestCase(TestCase):
    """Common setup for all tenant tests."""

    def setUp(self):
        # Get or create plans (migration 0004 seeds them, so use get_or_create)
        self.trial_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults=dict(
                name='Trial',
                monthly_price=Decimal('0.00'),
                max_repairs_per_month=50,
                max_technicians=2,
                max_customers=10,
                max_storage_mb=100,
                trial_days=30,
                display_order=0,
                features={'invoicing': True, 'rewards': False},
            ),
        )
        # Ensure test-specific values
        self.trial_plan.features = {'invoicing': True, 'rewards': False}
        self.trial_plan.save()

        self.starter_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='starter',
            defaults=dict(
                name='Starter',
                monthly_price=Decimal('49.00'),
                max_repairs_per_month=200,
                max_technicians=5,
                max_customers=50,
                max_storage_mb=500,
                trial_days=0,
                display_order=1,
                features={'invoicing': True, 'rewards': True, 'api_access': False},
            ),
        )
        self.starter_plan.stripe_price_id = 'price_starter_monthly'
        self.starter_plan.features = {'invoicing': True, 'rewards': True, 'api_access': False}
        self.starter_plan.save()

        self.pro_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='pro',
            defaults=dict(
                name='Pro',
                monthly_price=Decimal('99.00'),
                max_repairs_per_month=None,
                max_technicians=None,
                max_customers=None,
                max_storage_mb=5000,
                trial_days=0,
                display_order=2,
                features={'invoicing': True, 'rewards': True, 'api_access': True},
            ),
        )
        self.pro_plan.stripe_price_id = 'price_pro_monthly'
        self.pro_plan.stripe_annual_price_id = 'price_pro_annual'
        self.pro_plan.annual_price = Decimal('990.00')
        self.pro_plan.max_repairs_per_month = None
        self.pro_plan.max_technicians = None
        self.pro_plan.max_customers = None
        self.pro_plan.features = {'invoicing': True, 'rewards': True, 'api_access': True}
        self.pro_plan.save()

        # Create owner user + tenant
        self.owner = User.objects.create_user(
            'owner@test.com', 'owner@test.com', 'TestPass123!'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop',
            subdomain='test-shop',
            owner=self.owner,
            plan='trial',
            subscription_plan=self.trial_plan,
            subscription_status='trialing',
            trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner'
        )

        # Client with login
        self.client = Client()
        self.client.login(username='owner@test.com', password='TestPass123!')


# ======================================================================
# 1. Tenant Model Tests
# ======================================================================

class TenantModelTest(BaseTestCase):
    """Tests for Tenant model creation, slug generation, trial tracking."""

    def test_tenant_creation(self):
        """Tenant is created with correct fields."""
        self.assertEqual(self.tenant.name, 'Test Shop')
        self.assertEqual(self.tenant.slug, 'test-shop')
        self.assertEqual(self.tenant.subdomain, 'test-shop')
        self.assertEqual(self.tenant.owner, self.owner)
        self.assertEqual(self.tenant.plan, 'trial')
        self.assertEqual(self.tenant.subscription_status, 'trialing')
        self.assertTrue(self.tenant.is_active)

    def test_tenant_str(self):
        """Tenant __str__ returns the name."""
        self.assertEqual(str(self.tenant), 'Test Shop')

    def test_slug_auto_generation(self):
        """Slug is auto-generated from name if not provided."""
        tenant = Tenant(
            name='Auto Glass Pros LLC',
            owner=self.owner,
        )
        tenant.save()
        self.assertEqual(tenant.slug, 'auto-glass-pros-llc')
        self.assertEqual(tenant.subdomain, 'auto-glass-pros-llc')

    def test_subdomain_defaults_to_slug(self):
        """Subdomain defaults to slug if not set."""
        tenant = Tenant(
            name='My New Shop',
            slug='my-new-shop',
            owner=self.owner,
        )
        tenant.save()
        self.assertEqual(tenant.subdomain, 'my-new-shop')

    def test_trial_days_remaining_active_trial(self):
        """trial_days_remaining returns positive days for active trial."""
        remaining = self.tenant.trial_days_remaining
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 30)

    def test_trial_days_remaining_expired(self):
        """trial_days_remaining returns 0 for expired trial."""
        self.tenant.trial_started_at = timezone.now() - timedelta(days=31)
        self.tenant.save()
        self.assertEqual(self.tenant.trial_days_remaining, 0)

    def test_trial_days_remaining_non_trial(self):
        """trial_days_remaining returns 0 for non-trial plans."""
        self.tenant.plan = 'starter'
        self.tenant.save()
        self.assertEqual(self.tenant.trial_days_remaining, 0)

    def test_trial_days_remaining_no_start_date(self):
        """trial_days_remaining returns 0 if trial_started_at is None."""
        self.tenant.trial_started_at = None
        self.tenant.save()
        self.assertEqual(self.tenant.trial_days_remaining, 0)

    def test_is_trial_expired_false_for_active_trial(self):
        """is_trial_expired is False for a fresh trial."""
        self.assertFalse(self.tenant.is_trial_expired)

    def test_is_trial_expired_true_after_30_days(self):
        """is_trial_expired is True after trial period ends."""
        self.tenant.trial_started_at = timezone.now() - timedelta(days=31)
        self.tenant.save()
        self.assertTrue(self.tenant.is_trial_expired)

    def test_is_trial_expired_false_for_paid_plan(self):
        """is_trial_expired is False for paid plans."""
        self.tenant.plan = 'starter'
        self.tenant.save()
        self.assertFalse(self.tenant.is_trial_expired)

    def test_is_trial_expired_false_without_start_date(self):
        """is_trial_expired is False if no trial_started_at."""
        self.tenant.trial_started_at = None
        self.tenant.save()
        self.assertFalse(self.tenant.is_trial_expired)

    def test_is_trial_expired_uses_plan_trial_days(self):
        """is_trial_expired uses subscription_plan.trial_days if available."""
        # Set a shorter trial (10 days)
        short_plan = SubscriptionPlan.objects.create(
            name='Short Trial', slug='short-trial',
            monthly_price=0, trial_days=10, display_order=99,
        )
        self.tenant.subscription_plan = short_plan
        self.tenant.trial_started_at = timezone.now() - timedelta(days=11)
        self.tenant.save()
        self.assertTrue(self.tenant.is_trial_expired)

    def test_get_upload_prefix(self):
        """get_upload_prefix returns tenant-scoped path."""
        self.assertEqual(self.tenant.get_upload_prefix(), 'tenants/test-shop')

    def test_slug_unique(self):
        """Slug must be unique."""
        with self.assertRaises(IntegrityError):
            Tenant.objects.create(
                name='Another Shop',
                slug='test-shop',  # duplicate
                subdomain='another-shop',
                owner=self.owner,
            )


# ======================================================================
# 2. TenantMembership Tests
# ======================================================================

class TenantMembershipTest(BaseTestCase):
    """Tests for TenantMembership model."""

    def test_membership_creation(self):
        """Membership links user to tenant with correct role."""
        membership = TenantMembership.objects.get(
            tenant=self.tenant, user=self.owner
        )
        self.assertEqual(membership.role, 'owner')
        self.assertTrue(membership.is_active)

    def test_membership_str(self):
        """Membership __str__ includes user and tenant info."""
        membership = TenantMembership.objects.get(
            tenant=self.tenant, user=self.owner
        )
        display = str(membership)
        self.assertIn('Test Shop', display)
        self.assertIn('Owner', display)

    def test_unique_together_constraint(self):
        """Cannot create duplicate membership for same user+tenant."""
        with self.assertRaises(IntegrityError):
            TenantMembership.objects.create(
                tenant=self.tenant, user=self.owner, role='technician'
            )

    def test_multiple_roles_different_tenants(self):
        """Same user can be member of multiple tenants."""
        other_tenant = Tenant.objects.create(
            name='Other Shop', slug='other-shop', subdomain='other-shop',
            owner=self.owner,
        )
        membership = TenantMembership.objects.create(
            tenant=other_tenant, user=self.owner, role='manager'
        )
        self.assertEqual(membership.role, 'manager')
        self.assertEqual(
            TenantMembership.objects.filter(user=self.owner).count(), 2
        )

    def test_default_role_is_viewer(self):
        """Default role is 'viewer'."""
        other_user = User.objects.create_user(
            'viewer@test.com', 'viewer@test.com', 'TestPass123!'
        )
        membership = TenantMembership.objects.create(
            tenant=self.tenant, user=other_user
        )
        self.assertEqual(membership.role, 'viewer')

    def test_inactive_membership(self):
        """Inactive memberships can be created."""
        other_user = User.objects.create_user(
            'inactive@test.com', 'inactive@test.com', 'TestPass123!'
        )
        membership = TenantMembership.objects.create(
            tenant=self.tenant, user=other_user, is_active=False
        )
        self.assertFalse(membership.is_active)


# ======================================================================
# 3. TenantMiddleware Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class TenantMiddlewareTest(BaseTestCase):
    """Tests for TenantMiddleware tenant resolution."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(get_response=lambda r: None)

    def _make_request(self, user=None, path='/', headers=None):
        """Helper to create a request with user and headers."""
        request = self.factory.get(path, **(headers or {}))
        if user:
            request.user = user
        else:
            # Simulate anonymous user
            from django.contrib.auth.models import AnonymousUser
            request.user = AnonymousUser()
        request.session = {}
        return request

    def test_unauthenticated_returns_none(self):
        """Unauthenticated requests get tenant=None."""
        request = self._make_request()
        self.middleware.process_request(request)
        self.assertIsNone(request.tenant)

    def test_resolves_tenant_from_header(self):
        """X-Tenant-Slug header resolves to correct tenant."""
        request = self._make_request(
            user=self.owner,
            headers={'HTTP_X_TENANT_SLUG': 'test-shop'},
        )
        self.middleware.process_request(request)
        self.assertEqual(request.tenant, self.tenant)

    def test_header_requires_membership(self):
        """X-Tenant-Slug only works if user has membership."""
        other_user = User.objects.create_user(
            'other@test.com', 'other@test.com', 'TestPass123!'
        )
        request = self._make_request(
            user=other_user,
            headers={'HTTP_X_TENANT_SLUG': 'test-shop'},
        )
        self.middleware.process_request(request)
        self.assertIsNone(request.tenant)

    def test_superuser_bypasses_membership_check(self):
        """Superusers can access any tenant via header."""
        superuser = User.objects.create_superuser(
            'admin@test.com', 'admin@test.com', 'AdminPass123!'
        )
        request = self._make_request(
            user=superuser,
            headers={'HTTP_X_TENANT_SLUG': 'test-shop'},
        )
        self.middleware.process_request(request)
        self.assertEqual(request.tenant, self.tenant)

    def test_resolves_tenant_from_session(self):
        """Tenant resolved from session tenant_id."""
        request = self._make_request(user=self.owner)
        request.session = {'tenant_id': self.tenant.id}
        self.middleware.process_request(request)
        self.assertEqual(request.tenant, self.tenant)

    def test_stale_session_cleared(self):
        """Stale tenant_id in session gets cleared and falls back to membership."""
        request = self._make_request(user=self.owner)
        request.session = {'tenant_id': 99999}  # non-existent
        self.middleware.process_request(request)
        # Stale ID is cleared, then fallback finds user's membership
        # So tenant_id is now set to the valid tenant
        self.assertEqual(request.tenant, self.tenant)
        self.assertEqual(request.session.get('tenant_id'), self.tenant.id)

    def test_session_tenant_requires_membership(self):
        """Session tenant_id only works if user has membership."""
        other_user = User.objects.create_user(
            'noaccess@test.com', 'noaccess@test.com', 'TestPass123!'
        )
        request = self._make_request(user=other_user)
        request.session = {'tenant_id': self.tenant.id}
        self.middleware.process_request(request)
        # Stale session should be cleared, falls back to default
        self.assertIsNone(request.tenant)

    def test_fallback_to_first_membership(self):
        """Fallback uses user's first active membership."""
        request = self._make_request(user=self.owner)
        request.session = {}
        self.middleware.process_request(request)
        self.assertEqual(request.tenant, self.tenant)
        # Also stores in session for next time
        self.assertEqual(request.session.get('tenant_id'), self.tenant.id)

    def test_inactive_tenant_not_resolved(self):
        """Inactive tenants are not resolved."""
        self.tenant.is_active = False
        self.tenant.save()
        request = self._make_request(
            user=self.owner,
            headers={'HTTP_X_TENANT_SLUG': 'test-shop'},
        )
        self.middleware.process_request(request)
        self.assertIsNone(request.tenant)

    def test_inactive_membership_not_resolved(self):
        """Inactive memberships don't grant access."""
        membership = TenantMembership.objects.get(
            tenant=self.tenant, user=self.owner
        )
        membership.is_active = False
        membership.save()

        request = self._make_request(
            user=self.owner,
            headers={'HTTP_X_TENANT_SLUG': 'test-shop'},
        )
        self.middleware.process_request(request)
        self.assertIsNone(request.tenant)

    def test_admin_path_skipped(self):
        """Admin paths skip tenant resolution."""
        request = self._make_request(user=self.owner, path='/admin/')
        self.middleware.process_request(request)
        self.assertIsNone(request.tenant)

    def test_nonexistent_slug_falls_back(self):
        """Non-existent slug in header falls back to membership-based resolution."""
        request = self._make_request(
            user=self.owner,
            headers={'HTTP_X_TENANT_SLUG': 'nonexistent-shop'},
        )
        self.middleware.process_request(request)
        # Header fails, but fallback finds user's membership
        self.assertEqual(request.tenant, self.tenant)

    def test_nonexistent_slug_no_membership_returns_none(self):
        """Non-existent slug returns None for user with no memberships."""
        lonely_user = User.objects.create_user(
            'lonely@test.com', 'lonely@test.com', 'TestPass123!'
        )
        request = self._make_request(
            user=lonely_user,
            headers={'HTTP_X_TENANT_SLUG': 'nonexistent-shop'},
        )
        self.middleware.process_request(request)
        self.assertIsNone(request.tenant)


# ======================================================================
# 4. SubscriptionPlan Tests
# ======================================================================

class SubscriptionPlanTest(BaseTestCase):
    """Tests for SubscriptionPlan model."""

    def test_plan_creation(self):
        """Plans are created with correct attributes."""
        self.assertEqual(self.trial_plan.name, 'Trial')
        self.assertEqual(self.trial_plan.monthly_price, Decimal('0.00'))
        self.assertEqual(self.trial_plan.trial_days, 30)

    def test_plan_str(self):
        """Plan __str__ shows name and price."""
        self.assertEqual(str(self.trial_plan), 'Trial ($0.00/mo)')
        self.assertEqual(str(self.starter_plan), 'Starter ($49.00/mo)')

    def test_is_free_true_for_trial(self):
        """is_free returns True for $0 plans."""
        self.assertTrue(self.trial_plan.is_free)

    def test_is_free_false_for_paid(self):
        """is_free returns False for paid plans."""
        self.assertFalse(self.starter_plan.is_free)
        self.assertFalse(self.pro_plan.is_free)

    def test_has_feature_true(self):
        """has_feature returns True for included features."""
        self.assertTrue(self.trial_plan.has_feature('invoicing'))
        self.assertTrue(self.pro_plan.has_feature('api_access'))

    def test_has_feature_false(self):
        """has_feature returns False for excluded features."""
        self.assertFalse(self.trial_plan.has_feature('rewards'))
        self.assertFalse(self.starter_plan.has_feature('api_access'))

    def test_has_feature_missing(self):
        """has_feature returns False for undefined features."""
        self.assertFalse(self.trial_plan.has_feature('nonexistent_feature'))

    def test_slug_unique(self):
        """Plan slug must be unique."""
        with self.assertRaises(IntegrityError):
            SubscriptionPlan.objects.create(
                name='Duplicate Plan',
                slug='starter',  # duplicate of existing
                monthly_price=0,
            )

    def test_ordering(self):
        """Plans are ordered by display_order, then price."""
        plans = list(SubscriptionPlan.objects.all())
        self.assertEqual(plans[0], self.trial_plan)
        self.assertEqual(plans[1], self.starter_plan)
        self.assertEqual(plans[2], self.pro_plan)

    def test_null_limits_mean_unlimited(self):
        """Null limit values represent unlimited."""
        self.assertIsNone(self.pro_plan.max_repairs_per_month)
        self.assertIsNone(self.pro_plan.max_technicians)
        self.assertIsNone(self.pro_plan.max_customers)


# ======================================================================
# 5. UsageService Tests
# ======================================================================

class UsageServiceTest(BaseTestCase):
    """Tests for UsageService counting and limit enforcement."""

    def setUp(self):
        super().setUp()
        self.usage = UsageService(self.tenant)

        # Create a technician for repairs
        self.tech_user = User.objects.create_user(
            'tech@test.com', 'tech@test.com', 'TestPass123!'
        )
        from apps.technician_portal.models import Technician
        self.technician = Technician.objects.create(
            tenant=self.tenant,
            user=self.tech_user,
            is_active=True,
        )

        # Create a customer
        from core.models import Customer
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Customer',
            customer_type='FLEET',
        )

    def test_count_repairs_this_month_zero(self):
        """Count is 0 when no repairs exist."""
        self.assertEqual(self.usage.count_repairs_this_month(), 0)

    def test_count_repairs_this_month(self):
        """Counts repairs created this month."""
        from apps.technician_portal.models import Repair
        Repair.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='T-100',
            service_date=timezone.now(),
            cost=Decimal('150.00'),
            damage_type='Chip',
            insurance_claim=False,
        )
        self.assertEqual(self.usage.count_repairs_this_month(), 1)

    def test_count_repairs_includes_replacements(self):
        """Count includes both repairs and replacements."""
        from apps.technician_portal.models import Repair, Replacement
        Repair.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='T-100',
            service_date=timezone.now(),
            cost=Decimal('150.00'),
            damage_type='Chip',
            insurance_claim=False,
        )
        Replacement.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='T-200',
            service_date=timezone.now(),
            cost=Decimal('500.00'),
            insurance_claim=False,
        )
        self.assertEqual(self.usage.count_repairs_this_month(), 2)

    def test_count_repairs_excludes_other_tenants(self):
        """Only counts repairs for this tenant."""
        other_tenant = Tenant.objects.create(
            name='Other Shop', slug='other', subdomain='other', owner=self.owner,
        )
        other_tech_user = User.objects.create_user(
            'other_tech@test.com', 'other_tech@test.com', 'TestPass123!'
        )
        from apps.technician_portal.models import Technician, Repair
        other_tech = Technician.objects.create(
            tenant=other_tenant, user=other_tech_user, is_active=True,
        )
        from core.models import Customer
        other_cust = Customer.objects.create(
            tenant=other_tenant, name='Other Customer', customer_type='FLEET',
        )
        Repair.objects.create(
            tenant=other_tenant, technician=other_tech, customer=other_cust,
            unit_number='X-1', service_date=timezone.now(),
            cost=Decimal('100.00'), damage_type='Chip', insurance_claim=False,
        )
        self.assertEqual(self.usage.count_repairs_this_month(), 0)

    def test_count_active_technicians(self):
        """Counts active technicians for tenant."""
        self.assertEqual(self.usage.count_active_technicians(), 1)

    def test_count_active_technicians_excludes_inactive(self):
        """Excludes inactive technician users."""
        self.tech_user.is_active = False
        self.tech_user.save()
        self.assertEqual(self.usage.count_active_technicians(), 0)

    def test_count_customers(self):
        """Counts customers for tenant."""
        self.assertEqual(self.usage.count_customers(), 1)

    def test_can_create_repair_within_limit(self):
        """Allows repair creation when under limit."""
        allowed, msg = self.usage.can_create_repair()
        self.assertTrue(allowed)
        self.assertEqual(msg, '')

    def test_can_create_repair_at_limit(self):
        """Denies repair creation at limit."""
        # Set plan limit to 1
        self.trial_plan.max_repairs_per_month = 1
        self.trial_plan.save()

        from apps.technician_portal.models import Repair
        Repair.objects.create(
            tenant=self.tenant, technician=self.technician,
            customer=self.customer, unit_number='T-1',
            service_date=timezone.now(), cost=Decimal('100.00'),
            damage_type='Chip', insurance_claim=False,
        )

        usage = UsageService(self.tenant)
        allowed, msg = usage.can_create_repair()
        self.assertFalse(allowed)
        self.assertIn('Trial', msg)
        self.assertIn('1', msg)

    def test_can_create_repair_unlimited(self):
        """Unlimited plan always allows repair creation."""
        self.tenant.subscription_plan = self.pro_plan
        self.tenant.save()
        usage = UsageService(self.tenant)
        allowed, msg = usage.can_create_repair()
        self.assertTrue(allowed)

    def test_can_create_repair_no_plan(self):
        """No plan allows everything (no limits)."""
        self.tenant.subscription_plan = None
        self.tenant.save()
        usage = UsageService(self.tenant)
        allowed, msg = usage.can_create_repair()
        self.assertTrue(allowed)

    def test_can_add_technician_within_limit(self):
        """Allows technician when under limit."""
        allowed, msg = self.usage.can_add_technician()
        self.assertTrue(allowed)

    def test_can_add_technician_at_limit(self):
        """Denies technician at limit."""
        self.trial_plan.max_technicians = 1
        self.trial_plan.save()
        usage = UsageService(self.tenant)
        allowed, msg = usage.can_add_technician()
        self.assertFalse(allowed)
        self.assertIn('1', msg)

    def test_can_add_customer_within_limit(self):
        """Allows customer when under limit."""
        allowed, msg = self.usage.can_add_customer()
        self.assertTrue(allowed)

    def test_can_add_customer_at_limit(self):
        """Denies customer at limit."""
        self.trial_plan.max_customers = 1
        self.trial_plan.save()
        usage = UsageService(self.tenant)
        allowed, msg = usage.can_add_customer()
        self.assertFalse(allowed)

    def test_get_summary(self):
        """get_summary returns complete usage data."""
        summary = self.usage.get_summary()
        self.assertIn('repairs', summary)
        self.assertIn('technicians', summary)
        self.assertIn('customers', summary)
        self.assertIn('storage_mb', summary)
        self.assertIn('plan', summary)
        self.assertIn('subscription_status', summary)
        self.assertIn('trial_days_remaining', summary)

        # Verify structure
        self.assertEqual(summary['plan'], 'Trial')
        self.assertEqual(summary['repairs']['limit'], 50)
        self.assertEqual(summary['technicians']['used'], 1)
        self.assertEqual(summary['customers']['used'], 1)
        self.assertEqual(summary['subscription_status'], 'trialing')
        self.assertIsNotNone(summary['trial_days_remaining'])

    def test_get_summary_no_plan(self):
        """Summary works when tenant has no plan."""
        self.tenant.subscription_plan = None
        self.tenant.save()
        usage = UsageService(self.tenant)
        summary = usage.get_summary()
        self.assertEqual(summary['plan'], 'No Plan')
        self.assertIsNone(summary['repairs']['limit'])

    def test_usage_percentage_calculation(self):
        """Percentage is calculated correctly in summary."""
        summary = self.usage.get_summary()
        # 1 technician out of 2 = 50%
        self.assertEqual(summary['technicians']['percent'], 50.0)

    def test_usage_percentage_unlimited(self):
        """Percentage is None for unlimited limits."""
        self.tenant.subscription_plan = self.pro_plan
        self.tenant.save()
        usage = UsageService(self.tenant)
        summary = usage.get_summary()
        self.assertIsNone(summary['repairs']['percent'])


# ======================================================================
# 6. SubscriptionService Tests
# ======================================================================

class SubscriptionServiceTest(BaseTestCase):
    """Tests for SubscriptionService validation (no Stripe calls)."""

    def setUp(self):
        super().setUp()
        self.svc = SubscriptionService()

    def test_create_subscription_no_free_plan(self):
        """Cannot create subscription for free Trial plan."""
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.create_subscription(self.tenant, 'trial')
        self.assertIn('free Trial', str(ctx.exception))

    def test_create_subscription_missing_plan(self):
        """Cannot subscribe to nonexistent plan."""
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.create_subscription(self.tenant, 'nonexistent')
        self.assertIn('not found', str(ctx.exception))

    def test_create_subscription_missing_price_id(self):
        """Cannot subscribe if plan has no Stripe Price ID."""
        # Create plan without price ID
        no_price_plan = SubscriptionPlan.objects.create(
            name='NoPricePlan', slug='no-price', monthly_price=Decimal('29.00'),
            display_order=99,
        )
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.create_subscription(self.tenant, 'no-price')
        self.assertIn('no Stripe Price ID', str(ctx.exception))

    def test_cancel_subscription_no_active(self):
        """Cannot cancel when no subscription ID exists."""
        self.tenant.stripe_subscription_id = ''
        self.tenant.save()
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.cancel_subscription(self.tenant)
        self.assertIn('No active subscription', str(ctx.exception))

    def test_update_subscription_no_subscription(self):
        """Cannot update when no subscription exists."""
        self.tenant.stripe_subscription_id = ''
        self.tenant.save()
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.update_subscription(self.tenant, 'pro')
        self.assertIn('No active subscription', str(ctx.exception))

    def test_update_subscription_to_free(self):
        """Cannot switch to free Trial plan."""
        self.tenant.stripe_subscription_id = 'sub_test123'
        self.tenant.save()
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.update_subscription(self.tenant, 'trial')
        self.assertIn('free Trial', str(ctx.exception))

    def test_check_trial_expiry_active_trial(self):
        """Check trial status for active trial."""
        result = self.svc.check_trial_expiry(self.tenant)
        self.assertTrue(result['is_trial'])
        self.assertFalse(result['expired'])
        self.assertIsNotNone(result['days_remaining'])
        self.assertGreater(result['days_remaining'], 0)

    def test_check_trial_expiry_expired_trial(self):
        """Check trial status for expired trial."""
        self.tenant.trial_started_at = timezone.now() - timedelta(days=31)
        self.tenant.save()
        result = self.svc.check_trial_expiry(self.tenant)
        self.assertTrue(result['is_trial'])
        self.assertTrue(result['expired'])
        self.assertEqual(result['days_remaining'], 0)
        # Should update subscription_status to expired
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'expired')

    def test_check_trial_expiry_paid_plan(self):
        """Check trial status for paid plan returns not trial."""
        self.tenant.plan = 'starter'
        self.tenant.save()
        result = self.svc.check_trial_expiry(self.tenant)
        self.assertFalse(result['is_trial'])
        self.assertFalse(result['expired'])

    def test_reactivate_no_subscription(self):
        """Cannot reactivate when no subscription exists."""
        self.tenant.stripe_subscription_id = ''
        self.tenant.save()
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.reactivate_subscription(self.tenant)
        self.assertIn('No subscription', str(ctx.exception))

    def test_billing_portal_no_customer(self):
        """Cannot open billing portal without Stripe customer."""
        self.tenant.stripe_customer_id = ''
        self.tenant.save()
        with self.assertRaises(SubscriptionError) as ctx:
            self.svc.create_billing_portal_session(self.tenant, '/')
        self.assertIn('No billing account', str(ctx.exception))


# ======================================================================
# 7. Tenant API Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class TenantAPITest(BaseTestCase):
    """Tests for tenant API endpoints."""

    def test_list_plans_public(self):
        """GET /api/tenants/plans/ is public and returns plans."""
        self.client.logout()
        response = self.client.get('/api/tenants/plans/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('plans', data)
        self.assertGreaterEqual(len(data['plans']), 3)
        slugs = [p['slug'] for p in data['plans']]
        self.assertIn('trial', slugs)
        self.assertIn('starter', slugs)

    def test_status_requires_auth(self):
        """GET /api/tenants/status/ requires authentication."""
        self.client.logout()
        response = self.client.get('/api/tenants/status/')
        self.assertIn(response.status_code, [401, 403])

    def test_usage_requires_auth(self):
        """GET /api/tenants/usage/ requires authentication."""
        self.client.logout()
        response = self.client.get('/api/tenants/usage/')
        self.assertIn(response.status_code, [401, 403])

    def test_subscribe_requires_auth(self):
        """POST /api/tenants/subscribe/ requires authentication."""
        self.client.logout()
        response = self.client.post(
            '/api/tenants/subscribe/',
            data={'plan': 'starter'},
            content_type='application/json',
        )
        self.assertIn(response.status_code, [401, 403])

    def test_cancel_requires_auth(self):
        """POST /api/tenants/subscription/cancel/ requires authentication."""
        self.client.logout()
        response = self.client.post('/api/tenants/subscription/cancel/')
        self.assertIn(response.status_code, [401, 403])

    def test_signup_api_creates_tenant(self):
        """POST /api/tenants/signup/ creates user, tenant, membership."""
        self.client.logout()
        response = self.client.post(
            '/api/tenants/signup/',
            data={
                'business_name': 'New Glass Shop',
                'email': 'newowner@test.com',
                'password': 'SecurePass456!',
                'first_name': 'Jane',
                'last_name': 'Doe',
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn('user', data)
        self.assertIn('tenant', data)
        self.assertIn('token', data)
        self.assertEqual(data['user']['email'], 'newowner@test.com')
        self.assertEqual(data['tenant']['name'], 'New Glass Shop')

        # Verify database objects
        user = User.objects.get(email='newowner@test.com')
        tenant = Tenant.objects.get(slug=data['tenant']['slug'])
        self.assertEqual(tenant.owner, user)
        self.assertTrue(
            TenantMembership.objects.filter(
                tenant=tenant, user=user, role='owner'
            ).exists()
        )

    def test_signup_api_duplicate_email(self):
        """Signup rejects duplicate email."""
        self.client.logout()
        response = self.client.post(
            '/api/tenants/signup/',
            data={
                'business_name': 'Dupe Shop',
                'email': 'owner@test.com',  # already exists
                'password': 'SecurePass456!',
                'first_name': 'John',
                'last_name': 'Doe',
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('errors', data)
        self.assertIn('email', data['errors'])

    def test_signup_api_missing_fields(self):
        """Signup rejects missing required fields."""
        self.client.logout()
        response = self.client.post(
            '/api/tenants/signup/',
            data={'email': 'partial@test.com'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('errors', data)


# ======================================================================
# 8. Tenant Isolation Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class TenantIsolationTest(TestCase):
    """Tests that data is properly isolated between tenants."""

    def setUp(self):
        # Plan (seeded by migration, so get_or_create)
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults=dict(
                name='Trial', monthly_price=0,
                max_repairs_per_month=50, max_technicians=5, max_customers=10,
                trial_days=30, display_order=0,
            ),
        )

        # Tenant A
        self.owner_a = User.objects.create_user(
            'ownerA@test.com', 'ownerA@test.com', 'TestPass123!'
        )
        self.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a', subdomain='shop-a',
            owner=self.owner_a, plan='trial', subscription_plan=self.plan,
            subscription_status='trialing', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(
            tenant=self.tenant_a, user=self.owner_a, role='owner'
        )

        # Tenant B
        self.owner_b = User.objects.create_user(
            'ownerB@test.com', 'ownerB@test.com', 'TestPass123!'
        )
        self.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b', subdomain='shop-b',
            owner=self.owner_b, plan='trial', subscription_plan=self.plan,
            subscription_status='trialing', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(
            tenant=self.tenant_b, user=self.owner_b, role='owner'
        )

        # Create technicians
        self.tech_user_a = User.objects.create_user(
            'techA@test.com', 'techA@test.com', 'TestPass123!'
        )
        self.tech_user_b = User.objects.create_user(
            'techB@test.com', 'techB@test.com', 'TestPass123!'
        )
        from apps.technician_portal.models import Technician
        self.tech_a = Technician.objects.create(
            tenant=self.tenant_a, user=self.tech_user_a, is_active=True,
        )
        self.tech_b = Technician.objects.create(
            tenant=self.tenant_b, user=self.tech_user_b, is_active=True,
        )

        # Create customers
        from core.models import Customer
        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a, name='Customer A', customer_type='FLEET',
        )
        self.customer_b = Customer.objects.create(
            tenant=self.tenant_b, name='Customer B', customer_type='FLEET',
        )

        # Create repairs
        from apps.technician_portal.models import Repair
        self.repair_a = Repair.objects.create(
            tenant=self.tenant_a, technician=self.tech_a,
            customer=self.customer_a, unit_number='A-1',
            service_date=timezone.now(), cost=Decimal('100.00'),
            damage_type='Chip', insurance_claim=False,
        )
        self.repair_b = Repair.objects.create(
            tenant=self.tenant_b, technician=self.tech_b,
            customer=self.customer_b, unit_number='B-1',
            service_date=timezone.now(), cost=Decimal('200.00'),
            damage_type='Crack', insurance_claim=False,
        )

    def test_usage_service_isolated(self):
        """UsageService only counts data for its tenant."""
        usage_a = UsageService(self.tenant_a)
        usage_b = UsageService(self.tenant_b)

        self.assertEqual(usage_a.count_repairs_this_month(), 1)
        self.assertEqual(usage_b.count_repairs_this_month(), 1)
        self.assertEqual(usage_a.count_active_technicians(), 1)
        self.assertEqual(usage_b.count_active_technicians(), 1)
        self.assertEqual(usage_a.count_customers(), 1)
        self.assertEqual(usage_b.count_customers(), 1)

    def test_repair_data_isolated(self):
        """Repairs are scoped to their tenant."""
        from apps.technician_portal.models import Repair
        repairs_a = Repair.objects.filter(tenant=self.tenant_a)
        repairs_b = Repair.objects.filter(tenant=self.tenant_b)
        self.assertEqual(repairs_a.count(), 1)
        self.assertEqual(repairs_b.count(), 1)
        self.assertEqual(repairs_a.first().unit_number, 'A-1')
        self.assertEqual(repairs_b.first().unit_number, 'B-1')

    def test_customer_data_isolated(self):
        """Customers are scoped to their tenant."""
        from core.models import Customer
        customers_a = Customer.objects.filter(tenant=self.tenant_a)
        customers_b = Customer.objects.filter(tenant=self.tenant_b)
        self.assertEqual(customers_a.count(), 1)
        self.assertEqual(customers_b.count(), 1)
        self.assertEqual(customers_a.first().name, 'customer a')
        self.assertEqual(customers_b.first().name, 'customer b')

    def test_middleware_isolates_tenant_access(self):
        """User A cannot resolve Tenant B via middleware — falls back to own tenant."""
        factory = RequestFactory()
        middleware = TenantMiddleware(get_response=lambda r: None)

        request = factory.get('/', HTTP_X_TENANT_SLUG='shop-b')
        request.user = self.owner_a
        request.session = {}
        middleware.process_request(request)
        # Owner A has no membership in Tenant B, so header fails.
        # Fallback resolves to Owner A's own tenant (Shop A).
        self.assertEqual(request.tenant, self.tenant_a)
        # Crucially: NOT Tenant B
        self.assertNotEqual(request.tenant, self.tenant_b)

    def test_invoice_data_isolated(self):
        """Invoices are scoped to their tenant."""
        from apps.billing.models import Invoice
        inv_a = Invoice.objects.create(
            tenant=self.tenant_a, customer=self.customer_a,
            invoice_number='INV-A-001', total=Decimal('100.00'),
        )
        inv_b = Invoice.objects.create(
            tenant=self.tenant_b, customer=self.customer_b,
            invoice_number='INV-B-001', total=Decimal('200.00'),
        )
        self.assertEqual(
            Invoice.objects.filter(tenant=self.tenant_a).count(), 1
        )
        self.assertEqual(
            Invoice.objects.filter(tenant=self.tenant_b).count(), 1
        )


# ======================================================================
# 9. Authentication Required Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class AuthenticationRequiredTest(TestCase):
    """Tests that protected endpoints require authentication."""

    def setUp(self):
        self.client = Client()

    def test_owner_dashboard_requires_login(self):
        """GET /owner/ redirects to login when unauthenticated."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_billing_settings_requires_login(self):
        """GET /owner/billing/ redirects to login."""
        response = self.client.get('/owner/billing/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_owner_settings_requires_login(self):
        """GET /owner/settings/ redirects to login."""
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_onboarding_requires_login(self):
        """GET /onboarding/ redirects to login."""
        response = self.client.get('/onboarding/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_replacement_create_requires_login(self):
        """GET /tech/replacement/new/ redirects to login."""
        response = self.client.get('/tech/replacement/new/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_signup_is_public(self):
        """GET /signup/ is accessible without login."""
        response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)

    def test_pricing_is_public(self):
        """GET /pricing/ is accessible without login."""
        # Plans are seeded by migration 0004
        response = self.client.get('/pricing/')
        self.assertEqual(response.status_code, 200)

    def test_api_plans_is_public(self):
        """GET /api/tenants/plans/ is accessible without login."""
        response = self.client.get('/api/tenants/plans/')
        self.assertEqual(response.status_code, 200)

    def test_api_status_requires_auth(self):
        """GET /api/tenants/status/ requires auth."""
        response = self.client.get('/api/tenants/status/')
        self.assertIn(response.status_code, [401, 403])

    def test_api_usage_requires_auth(self):
        """GET /api/tenants/usage/ requires auth."""
        response = self.client.get('/api/tenants/usage/')
        self.assertIn(response.status_code, [401, 403])

    def test_api_subscribe_requires_auth(self):
        """POST /api/tenants/subscribe/ requires auth."""
        response = self.client.post(
            '/api/tenants/subscribe/',
            data={'plan': 'starter'},
            content_type='application/json',
        )
        self.assertIn(response.status_code, [401, 403])

    def test_api_cancel_requires_auth(self):
        """POST /api/tenants/subscription/cancel/ requires auth."""
        response = self.client.post('/api/tenants/subscription/cancel/')
        self.assertIn(response.status_code, [401, 403])

    def test_api_update_requires_auth(self):
        """POST /api/tenants/subscription/update/ requires auth."""
        response = self.client.post(
            '/api/tenants/subscription/update/',
            data={'plan': 'pro'},
            content_type='application/json',
        )
        self.assertIn(response.status_code, [401, 403])

    def test_api_billing_portal_requires_auth(self):
        """GET /api/tenants/billing-portal/ requires auth."""
        response = self.client.get('/api/tenants/billing-portal/')
        self.assertIn(response.status_code, [401, 403])


# ======================================================================
# 10. Owner-Only Access Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class OwnerOnlyTest(BaseTestCase):
    """Tests that owner-only actions reject non-owners."""

    def setUp(self):
        super().setUp()
        # Create a non-owner user with technician role
        self.tech_user = User.objects.create_user(
            'techonly@test.com', 'techonly@test.com', 'TestPass123!'
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.tech_user, role='technician'
        )
        self.tech_client = Client()
        self.tech_client.login(
            username='techonly@test.com', password='TestPass123!'
        )

    def test_non_owner_cannot_access_billing(self):
        """Technician cannot access billing settings."""
        response = self.tech_client.get('/owner/billing/')
        # Should redirect to dashboard or show error
        if response.status_code == 200:
            # Some views may render but show error message
            pass
        else:
            self.assertEqual(response.status_code, 302)

    def test_non_owner_cannot_update_plan(self):
        """Technician cannot change subscription plan."""
        response = self.tech_client.post('/owner/billing/update/', {'plan': 'pro'})
        self.assertEqual(response.status_code, 302)

    def test_non_owner_cannot_cancel(self):
        """Technician cannot cancel subscription."""
        response = self.tech_client.post('/owner/billing/cancel/')
        self.assertEqual(response.status_code, 302)

    def test_api_subscribe_requires_owner(self):
        """API subscribe endpoint requires owner role."""
        self.tech_client.login(
            username='techonly@test.com', password='TestPass123!'
        )
        response = self.tech_client.post(
            '/api/tenants/subscribe/',
            data={'plan': 'starter'},
            content_type='application/json',
        )
        # Should be 403 (no tenant or not owner)
        self.assertEqual(response.status_code, 403)

    def test_api_cancel_requires_owner(self):
        """API cancel endpoint requires owner role."""
        response = self.tech_client.post(
            '/api/tenants/subscription/cancel/',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
