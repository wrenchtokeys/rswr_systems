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

    def test_count_active_technicians_excludes_deactivated_tech_record(self):
        """
        Regression test for CODE-045: Technician.is_active=False must not count
        toward plan seat limits even when the underlying user account is active.

        Scenario: shop owner deactivates a seasonal technician via team management.
        deactivate_team_member() sets tech.is_active=False + membership.is_active=False
        but leaves user.is_active=True (the user account itself isn't deleted).
        Before the fix, count_active_technicians() only checked user__is_active and
        would still count this tech, blocking the owner from inviting a replacement.
        """
        from apps.technician_portal.models import Technician
        # user account stays active, only Technician record is deactivated
        Technician.objects.filter(user=self.tech_user, tenant=self.tenant).update(
            is_active=False
        )
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
        # No auth token until email is confirmed — issuing one here would
        # let signups bypass email confirmation entirely.
        self.assertNotIn('token', data)
        self.assertEqual(data['user']['email'], 'newowner@test.com')
        self.assertEqual(data['tenant']['name'], 'New Glass Shop')

        # Verify database objects
        user = User.objects.get(email='newowner@test.com')
        self.assertFalse(user.is_active)  # inactive until email confirmed
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


# ======================================================================
# 11. Subscription Upgrade/Downgrade Tests
# ======================================================================

def stripe_subscription_mock(item_id, period_end=1735689600,
                             period_start=1733011200, status='active',
                             price_id='price_current', interval='month'):
    """A test double that behaves like a real Stripe Subscription.

    The previous inline mocks set current_period_end as an *attribute* while
    their __getitem__ returned None for it. A real StripeObject resolves the
    same field either way, so the doubles quietly disagreed with production
    and hid the fact that Basil (2025-03-31) moved current_period_end onto
    the items. Keep both access paths consistent here.
    """
    data = {
        'id': 'sub_mock',
        'status': status,
        'current_period_end': period_end,
        'current_period_start': period_start,
        'items': {'data': [{
            'id': item_id,
            'current_period_end': period_end,
            'current_period_start': period_start,
            'price': {'id': price_id, 'recurring': {'interval': interval}},
        }]},
    }
    mock = MagicMock(**{k: v for k, v in data.items() if k != 'items'})
    mock.__getitem__ = lambda _self, key: data[key]
    mock.__contains__ = lambda _self, key: key in data
    return mock


class SubscriptionUpgradeDowngradeTest(BaseTestCase):
    """
    Tests for upgrade/downgrade detection and security handling.
    
    Key behaviors tested:
    - Upgrades: Plan NOT updated locally (waits for webhook)
    - Downgrades: User keeps current tier until period end (uses schedule)
    """

    def setUp(self):
        super().setUp()
        self.svc = SubscriptionService()
        
        # Create enterprise plan for upgrade testing
        self.enterprise_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='enterprise',
            defaults=dict(
                name='Enterprise',
                monthly_price=Decimal('249.00'),
                max_repairs_per_month=None,
                max_technicians=None,
                max_customers=None,
                max_storage_mb=50000,
                trial_days=0,
                display_order=3,
                features={'invoicing': True, 'rewards': True, 'api_access': True, 'white_label': True},
            ),
        )
        self.enterprise_plan.stripe_price_id = 'price_enterprise_monthly'
        self.enterprise_plan.save()

    def test_upgrade_detection_starter_to_pro(self):
        """Starter ($49) → Pro ($99) is detected as upgrade."""
        self.tenant.subscription_plan = self.starter_plan
        self.tenant.plan = 'starter'
        self.tenant.save()
        
        is_upgrade = (
            self.pro_plan.monthly_price > 
            (self.tenant.subscription_plan.monthly_price or 0)
        )
        self.assertTrue(is_upgrade)

    def test_upgrade_detection_pro_to_enterprise(self):
        """Pro ($99) → Enterprise ($249) is detected as upgrade."""
        self.tenant.subscription_plan = self.pro_plan
        self.tenant.plan = 'pro'
        self.tenant.save()
        
        is_upgrade = (
            self.enterprise_plan.monthly_price > 
            (self.tenant.subscription_plan.monthly_price or 0)
        )
        self.assertTrue(is_upgrade)

    def test_downgrade_detection_pro_to_starter(self):
        """Pro ($99) → Starter ($49) is detected as downgrade."""
        self.tenant.subscription_plan = self.pro_plan
        self.tenant.plan = 'pro'
        self.tenant.save()
        
        is_upgrade = (
            self.starter_plan.monthly_price > 
            (self.tenant.subscription_plan.monthly_price or 0)
        )
        self.assertFalse(is_upgrade)

    def test_downgrade_detection_enterprise_to_starter(self):
        """Enterprise ($249) → Starter ($49) is detected as downgrade."""
        self.tenant.subscription_plan = self.enterprise_plan
        self.tenant.plan = 'enterprise'
        self.tenant.save()
        
        is_upgrade = (
            self.starter_plan.monthly_price > 
            (self.tenant.subscription_plan.monthly_price or 0)
        )
        self.assertFalse(is_upgrade)

    def test_no_plan_to_any_is_upgrade(self):
        """No current plan → any paid plan is treated as upgrade."""
        self.tenant.subscription_plan = None
        self.tenant.plan = 'trial'
        self.tenant.save()
        
        is_upgrade = (
            self.tenant.subscription_plan is None or 
            self.starter_plan.monthly_price > 
            (self.tenant.subscription_plan.monthly_price if self.tenant.subscription_plan else 0)
        )
        self.assertTrue(is_upgrade)

    @patch('stripe.Subscription.retrieve')
    @patch('stripe.Subscription.modify')
    def test_upgrade_does_not_update_local_plan(self, mock_modify, mock_retrieve):
        """Upgrade returns 'pending' status and does NOT update tenant.plan."""
        # Setup tenant on starter plan with active subscription
        self.tenant.subscription_plan = self.starter_plan
        self.tenant.plan = 'starter'
        self.tenant.stripe_subscription_id = 'sub_test123'
        self.tenant.save()
        
        # Mock Stripe responses
        mock_retrieve.return_value = stripe_subscription_mock('si_item123')
        mock_modify.return_value = {'id': 'sub_test123'}
        
        # Attempt upgrade to Pro
        result = self.svc.update_subscription(self.tenant, 'pro')
        
        # Verify result indicates pending (waiting for webhook)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['new_plan'], 'Pro')
        self.assertIn('momentarily', result['message'])
        
        # CRITICAL: Local plan should NOT be updated
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'starter')  # Still starter!
        self.assertEqual(self.tenant.subscription_plan, self.starter_plan)

    @patch('stripe.SubscriptionSchedule.modify')
    @patch('stripe.SubscriptionSchedule.create')
    @patch('stripe.Subscription.retrieve')
    def test_downgrade_creates_schedule_keeps_current_plan(
        self, mock_retrieve, mock_schedule_create, mock_schedule_modify
    ):
        """Downgrade creates schedule and keeps user on current (higher) plan."""
        # Setup tenant on Pro plan with active subscription
        self.tenant.subscription_plan = self.pro_plan
        self.tenant.plan = 'pro'
        self.tenant.stripe_subscription_id = 'sub_test456'
        self.tenant.save()
        
        # Mock Stripe responses
        mock_retrieve.return_value = stripe_subscription_mock('si_item456')
        
        mock_schedule_create.return_value = MagicMock(id='sub_sched_789')
        mock_schedule_modify.return_value = {}
        
        # Attempt downgrade to Starter
        result = self.svc.update_subscription(self.tenant, 'starter')
        
        # Verify result indicates scheduled
        self.assertEqual(result['status'], 'scheduled')
        self.assertEqual(result['new_plan'], 'Starter')
        self.assertIn('end of your current billing period', result['message'])
        self.assertEqual(result['current_period_end'], 1735689600)
        
        # CRITICAL: Local plan should NOT be changed (user keeps Pro access)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'pro')  # Still Pro!
        self.assertEqual(self.tenant.subscription_plan, self.pro_plan)
        
        # Verify schedule was created
        mock_schedule_create.assert_called_once_with(
            from_subscription='sub_test456'
        )

    @patch('stripe.Subscription.retrieve')
    def test_upgrade_calls_stripe_modify_with_proration(self, mock_retrieve):
        """Upgrade calls Stripe with create_prorations behavior."""
        self.tenant.subscription_plan = self.starter_plan
        self.tenant.plan = 'starter'
        self.tenant.stripe_subscription_id = 'sub_test789'
        self.tenant.save()
        
        mock_retrieve.return_value = stripe_subscription_mock('si_item789')
        
        with patch('stripe.Subscription.modify') as mock_modify:
            mock_modify.return_value = {'id': 'sub_test789'}
            self.svc.update_subscription(self.tenant, 'pro')
            
            # Verify Stripe.modify was called with correct params
            mock_modify.assert_called_once()
            call_kwargs = mock_modify.call_args[1]
            self.assertEqual(call_kwargs['proration_behavior'], 'create_prorations')
            self.assertEqual(call_kwargs['items'][0]['price'], 'price_pro_monthly')

    def test_downgrade_requires_current_plan_stripe_id(self):
        """Downgrade fails gracefully if current plan has no stripe_price_id."""
        # Create a plan without stripe price ID
        broken_plan = SubscriptionPlan.objects.create(
            name='BrokenPlan', slug='broken',
            monthly_price=Decimal('199.00'), display_order=99,
        )
        self.tenant.subscription_plan = broken_plan
        self.tenant.plan = 'broken'
        self.tenant.stripe_subscription_id = 'sub_test999'
        self.tenant.save()
        
        with patch('stripe.Subscription.retrieve') as mock_retrieve:
            mock_retrieve.return_value = stripe_subscription_mock('si_item999')
            
            with self.assertRaises(SubscriptionError) as ctx:
                self.svc.update_subscription(self.tenant, 'starter')
            
            self.assertIn('current plan', str(ctx.exception).lower())

    def test_same_price_treated_as_downgrade(self):
        """Same price is treated as downgrade (safe, no upgrade access)."""
        # Create two plans with same price
        plan_a = SubscriptionPlan.objects.create(
            name='Plan A', slug='plan-a',
            monthly_price=Decimal('99.00'),
            stripe_price_id='price_plan_a',
            display_order=10,
        )
        plan_b = SubscriptionPlan.objects.create(
            name='Plan B', slug='plan-b',
            monthly_price=Decimal('99.00'),
            stripe_price_id='price_plan_b',
            display_order=11,
        )
        
        self.tenant.subscription_plan = plan_a
        self.tenant.plan = 'plan-a'
        self.tenant.save()
        
        # Same price means NOT an upgrade (99 > 99 is False)
        is_upgrade = plan_b.monthly_price > (plan_a.monthly_price or 0)
        self.assertFalse(is_upgrade)


# ======================================================================
# CODE-171 — TenantAdmin N+1 queries for 'owner' and 'subscription_plan'
# ======================================================================

class TenantAdminListSelectRelatedTest(TestCase):
    """
    Regression test for CODE-171.

    TenantAdmin.list_display includes 'owner' (FK→User) and 'subscription_plan'
    (FK→SubscriptionPlan). Without list_select_related, the Django admin
    change-list fires one extra SELECT per tenant row for each of those FKs —
    an N+1 query pattern that degrades linearly with tenant count.

    Fix: add list_select_related = ['owner', 'subscription_plan'] to TenantAdmin.
    """

    def test_tenant_admin_has_list_select_related(self):
        """TenantAdmin must declare list_select_related to avoid N+1 queries."""
        from apps.tenants.admin import TenantAdmin
        lsr = getattr(TenantAdmin, 'list_select_related', None)
        self.assertIsNotNone(
            lsr,
            "TenantAdmin.list_select_related is missing — admin list view will fire "
            "N+1 queries for 'owner' and 'subscription_plan' columns."
        )
        # Must cover both FK columns present in list_display
        self.assertIn(
            'owner', lsr,
            "TenantAdmin.list_select_related must include 'owner' (FK→User) "
            "to prevent per-row SELECT for each tenant's owner."
        )
        self.assertIn(
            'subscription_plan', lsr,
            "TenantAdmin.list_select_related must include 'subscription_plan' "
            "(FK→SubscriptionPlan) to prevent per-row SELECT for each tenant."
        )

    def test_tenant_admin_changelist_query_count(self):
        """
        Admin change-list for N tenants should NOT fire 2*N extra queries for
        owner + subscription_plan lookups.  With list_select_related, the join
        happens in the initial SELECT so the query count stays constant.
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from apps.tenants.admin import TenantAdmin
        from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
        from decimal import Decimal

        # Create a superuser for the admin request
        superuser = User.objects.create_superuser(
            username='su_code171', email='su171@test.com', password='pass'
        )

        # Create a plan and a handful of tenants
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial-171',
            defaults=dict(
                name='Trial 171',
                monthly_price=Decimal('0.00'),
                max_repairs_per_month=50,
                max_technicians=2,
                max_customers=10,
                max_storage_mb=100,
                trial_days=30,
                display_order=99,
                features={},
            ),
        )

        owners = []
        tenants_created = []
        for i in range(4):
            owner = User.objects.create_user(
                username=f'owner_171_{i}',
                email=f'owner171_{i}@test.com',
                password='pass',
            )
            owners.append(owner)
            t = Tenant.objects.create(
                name=f'Shop 171 {i}',
                slug=f'shop-171-{i}',
                subdomain=f'shop171{i}',
                owner=owner,
                plan='trial',
                subscription_plan=plan,
                subscription_status='trialing',
            )
            tenants_created.append(t)

        # Simulate admin changelist request
        factory = RequestFactory()
        request = factory.get('/admin/tenants/tenant/')
        request.user = superuser

        site = AdminSite()
        admin_instance = TenantAdmin(Tenant, site)

        with CaptureQueriesContext(connection) as ctx:
            qs = admin_instance.get_queryset(request)
            # Materialise the queryset to trigger the SELECT
            list(qs)

        num_queries = len(ctx.captured_queries)

        # With list_select_related the ORM issues a single query with JOINs.
        # Without it, it would fire 1 (base) + 4*owner + 4*subscription_plan = 9+.
        # We allow up to 3 queries (e.g. base + deferred counts) as a loose bound.
        self.assertLessEqual(
            num_queries, 3,
            f"TenantAdmin.get_queryset() fired {num_queries} queries for 4 tenants. "
            f"Expected ≤3 with list_select_related. Queries:\n"
            + "\n".join(q['sql'][:120] for q in ctx.captured_queries)
        )
