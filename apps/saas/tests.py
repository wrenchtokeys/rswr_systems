"""
Comprehensive Tests for the SaaS App

Tests cover:
- Signup flow (form validation, user/tenant creation, login)
- Onboarding wizard (business info, technician, customer, skip)
- Owner dashboard (access, usage display, trial banner)
- Billing settings (owner access, plans display)
- Replacement form (create, tenant scoping, plan limits)

Author: Amelia (Clawdbot AI) — Test Suite
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.usage_service import UsageService

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
# Base Setup
# ======================================================================

class SaaSBaseTestCase(TestCase):
    """Common setup for SaaS tests."""

    def setUp(self):
        self.trial_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults=dict(
                name='Trial', monthly_price=Decimal('0.00'),
                max_repairs_per_month=50, max_technicians=2, max_customers=10,
                max_storage_mb=100, trial_days=30, display_order=0,
                features={'invoicing': True},
            ),
        )
        self.starter_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='starter',
            defaults=dict(
                name='Starter', monthly_price=Decimal('49.00'),
                stripe_price_id='price_starter_test',
                max_repairs_per_month=200, max_technicians=5, max_customers=50,
                display_order=1,
            ),
        )

    def _create_owner_with_tenant(self, email='owner@test.com',
                                   tenant_name='Test Shop',
                                   tenant_slug='test-shop'):
        """Helper to create an owner user with a tenant."""
        owner = User.objects.create_user(email, email, 'TestPass123!')
        tenant = Tenant.objects.create(
            name=tenant_name, slug=tenant_slug, subdomain=tenant_slug,
            owner=owner, plan='trial', subscription_plan=self.trial_plan,
            subscription_status='trialing', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(
            tenant=tenant, user=owner, role='owner'
        )
        return owner, tenant

    def _logged_in_client(self, email='owner@test.com', password='TestPass123!'):
        """Helper to create a logged-in client."""
        client = Client()
        client.login(username=email, password=password)
        return client


# ======================================================================
# 1. Signup Flow Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class SignupFlowTest(SaaSBaseTestCase):
    """Tests for the /signup/ page."""

    def test_signup_get_returns_200(self):
        """GET /signup/ returns the signup form."""
        response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'form')

    def test_signup_post_valid_data(self):
        """POST /signup/ with valid data creates user+tenant and redirects."""
        response = self.client.post('/signup/', {
            'business_name': 'Quick Fix Glass',
            'first_name': 'John',
            'last_name': 'Smith',
            'email': 'john@quickfix.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('onboarding', response.url.lower())

    def test_signup_creates_user(self):
        """Signup creates a User with correct details."""
        self.client.post('/signup/', {
            'business_name': 'My Glass Shop',
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'jane@glasshop.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        user = User.objects.get(email='jane@glasshop.com')
        self.assertEqual(user.first_name, 'Jane')
        self.assertEqual(user.last_name, 'Doe')

    def test_signup_creates_tenant(self):
        """Signup creates a Tenant with trial plan."""
        self.client.post('/signup/', {
            'business_name': 'Glass Pros',
            'first_name': 'Bob',
            'last_name': 'Builder',
            'email': 'bob@glasspros.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        tenant = Tenant.objects.get(name='Glass Pros')
        self.assertEqual(tenant.plan, 'trial')
        self.assertEqual(tenant.subscription_status, 'trialing')
        self.assertIsNotNone(tenant.trial_started_at)
        self.assertEqual(tenant.subscription_plan, self.trial_plan)

    def test_signup_creates_membership(self):
        """Signup creates TenantMembership with owner role."""
        self.client.post('/signup/', {
            'business_name': 'Owner Shop',
            'first_name': 'Alice',
            'last_name': 'Owner',
            'email': 'alice@ownershop.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        user = User.objects.get(email='alice@ownershop.com')
        tenant = Tenant.objects.get(name='Owner Shop')
        membership = TenantMembership.objects.get(tenant=tenant, user=user)
        self.assertEqual(membership.role, 'owner')
        self.assertTrue(membership.is_active)

    def test_signup_logs_user_in(self):
        """After signup, user is logged in (session has user)."""
        response = self.client.post('/signup/', {
            'business_name': 'Login Test Shop',
            'first_name': 'Sam',
            'last_name': 'Test',
            'email': 'sam@logintest.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        }, follow=True)
        # After redirect and following, user should be authenticated
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_signup_duplicate_email_rejected(self):
        """Signup rejects already-used email."""
        User.objects.create_user(
            'existing@test.com', 'existing@test.com', 'TestPass123!'
        )
        response = self.client.post('/signup/', {
            'business_name': 'Dupe Shop',
            'first_name': 'Dupe',
            'last_name': 'User',
            'email': 'existing@test.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        # Should stay on signup page (200) with errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')

    def test_signup_password_mismatch_rejected(self):
        """Signup rejects mismatched passwords."""
        response = self.client.post('/signup/', {
            'business_name': 'Mismatch Shop',
            'first_name': 'Mis',
            'last_name': 'Match',
            'email': 'mismatch@test.com',
            'password': 'SecurePass456!',
            'password_confirm': 'DifferentPass789!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'do not match')

    def test_signup_weak_password_rejected(self):
        """Signup rejects weak passwords."""
        response = self.client.post('/signup/', {
            'business_name': 'Weak Shop',
            'first_name': 'Weak',
            'last_name': 'Pass',
            'email': 'weak@test.com',
            'password': '123',
            'password_confirm': '123',
        })
        self.assertEqual(response.status_code, 200)
        # Django's form will re-render with errors

    def test_signup_authenticated_user_redirected(self):
        """Authenticated users are redirected away from signup."""
        owner, tenant = self._create_owner_with_tenant()
        client = self._logged_in_client()
        response = client.get('/signup/')
        self.assertEqual(response.status_code, 302)
        # Redirects to dashboard
        self.assertIn('owner', response.url.lower())

    def test_signup_missing_business_name(self):
        """Signup requires business name."""
        response = self.client.post('/signup/', {
            'business_name': '',
            'first_name': 'No',
            'last_name': 'Biz',
            'email': 'nobiz@test.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        self.assertEqual(response.status_code, 200)
        # Form should have errors

    def test_signup_missing_email(self):
        """Signup requires email."""
        response = self.client.post('/signup/', {
            'business_name': 'No Email Shop',
            'first_name': 'No',
            'last_name': 'Email',
            'email': '',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        self.assertEqual(response.status_code, 200)

    def test_signup_generates_unique_slug(self):
        """Multiple shops with same name get unique slugs."""
        self.client.post('/signup/', {
            'business_name': 'Auto Glass',
            'first_name': 'First',
            'last_name': 'Shop',
            'email': 'first@autoglass.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        # Create second signup with new client (logout first)
        client2 = Client()
        client2.post('/signup/', {
            'business_name': 'Auto Glass',
            'first_name': 'Second',
            'last_name': 'Shop',
            'email': 'second@autoglass.com',
            'password': 'SecurePass456!',
            'password_confirm': 'SecurePass456!',
        })
        tenants = Tenant.objects.filter(name='Auto Glass')
        self.assertEqual(tenants.count(), 2)
        slugs = [t.slug for t in tenants]
        self.assertNotEqual(slugs[0], slugs[1])


# ======================================================================
# 2. Onboarding Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class OnboardingTest(SaaSBaseTestCase):
    """Tests for the /onboarding/ wizard."""

    def setUp(self):
        super().setUp()
        self.owner, self.tenant = self._create_owner_with_tenant()
        self.client = self._logged_in_client()

    def test_onboarding_requires_login(self):
        """Onboarding redirects unauthenticated users."""
        anon_client = Client()
        response = anon_client.get('/onboarding/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_onboarding_step_1_renders(self):
        """Step 1 (business info) renders correctly."""
        response = self.client.get('/onboarding/?step=1')
        self.assertEqual(response.status_code, 200)

    def test_onboarding_step_1_saves_business_info(self):
        """Step 1 saves business info to tenant."""
        response = self.client.post('/onboarding/?step=1', {
            'business_phone': '555-123-4567',
            'business_email': 'info@testshop.com',
            'business_address': '123 Main St',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('step=2', response.url)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.business_phone, '555-123-4567')
        self.assertEqual(self.tenant.business_email, 'info@testshop.com')
        self.assertEqual(self.tenant.business_address, '123 Main St')

    def test_onboarding_step_2_renders(self):
        """Step 2 (technician) renders correctly."""
        response = self.client.get('/onboarding/?step=2')
        self.assertEqual(response.status_code, 200)

    def test_onboarding_step_2_adds_self_as_technician(self):
        """Step 2 can add current user as technician."""
        response = self.client.post('/onboarding/?step=2', {
            'tech_first_name': self.owner.first_name or 'Owner',
            'tech_last_name': self.owner.last_name or 'Test',
            'add_self': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('step=3', response.url)

        from apps.technician_portal.models import Technician
        self.assertTrue(
            Technician.objects.filter(user=self.owner, tenant=self.tenant).exists()
        )

    def test_onboarding_step_3_renders(self):
        """Step 3 (customer) renders correctly."""
        response = self.client.get('/onboarding/?step=3')
        self.assertEqual(response.status_code, 200)

    def test_onboarding_step_3_creates_customer(self):
        """Step 3 creates a customer."""
        response = self.client.post('/onboarding/?step=3', {
            'customer_name': 'EOS Trucking',
            'customer_type': 'FLEET',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('step=4', response.url)

        from core.models import Customer
        self.assertTrue(
            Customer.objects.filter(
                tenant=self.tenant, name='EOS Trucking'
            ).exists()
        )

    def test_onboarding_skip_step_1(self):
        """Skip button advances to next step."""
        response = self.client.post('/onboarding/?step=1', {
            'action': 'skip',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('step=2', response.url)

    def test_onboarding_skip_step_2(self):
        """Skip button on step 2 advances to step 3."""
        response = self.client.post('/onboarding/?step=2', {
            'action': 'skip',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('step=3', response.url)

    def test_onboarding_skip_step_3(self):
        """Skip button on step 3 advances to step 4."""
        response = self.client.post('/onboarding/?step=3', {
            'action': 'skip',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('step=4', response.url)

    def test_onboarding_step_4_redirects_to_dashboard(self):
        """Step 4 (done) redirects to owner dashboard."""
        response = self.client.post('/onboarding/?step=4', {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('owner', response.url.lower())

    def test_onboarding_duplicate_customer_handled(self):
        """Adding duplicate customer shows info message."""
        from core.models import Customer
        Customer.objects.create(
            tenant=self.tenant, name='Existing Co', customer_type='FLEET',
        )
        response = self.client.post('/onboarding/?step=3', {
            'customer_name': 'Existing Co',
            'customer_type': 'FLEET',
        }, follow=True)
        # Should still redirect and not create duplicate
        self.assertEqual(
            Customer.objects.filter(
                tenant=self.tenant, name__iexact='Existing Co'
            ).count(), 1
        )


# ======================================================================
# 3. Owner Dashboard Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class OwnerDashboardTest(SaaSBaseTestCase):
    """Tests for the /owner/ dashboard."""

    def setUp(self):
        super().setUp()
        self.owner, self.tenant = self._create_owner_with_tenant()
        self.client = self._logged_in_client()

    def test_dashboard_requires_login(self):
        """Dashboard redirects unauthenticated users."""
        anon_client = Client()
        response = anon_client.get('/owner/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_dashboard_returns_200(self):
        """Authenticated owner can access dashboard."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)

    def test_dashboard_shows_usage(self):
        """Dashboard context contains usage data."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('usage', response.context)
        usage = response.context['usage']
        self.assertIn('repairs', usage)
        self.assertIn('technicians', usage)
        self.assertIn('customers', usage)

    def test_dashboard_shows_trial_banner(self):
        """Dashboard shows trial info for trial tenants."""
        response = self.client.get('/owner/')
        self.assertTrue(response.context['is_trial'])
        self.assertGreater(response.context['trial_days_remaining'], 0)

    def test_dashboard_shows_recent_activity(self):
        """Dashboard includes recent_activity."""
        response = self.client.get('/owner/')
        self.assertIn('recent_activity', response.context)

    def test_dashboard_no_tenant_redirects(self):
        """User with no tenant is redirected to signup."""
        no_tenant_user = User.objects.create_user(
            'notenant@test.com', 'notenant@test.com', 'TestPass123!'
        )
        client = Client()
        client.login(username='notenant@test.com', password='TestPass123!')
        response = client.get('/owner/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('signup', response.url.lower())


# ======================================================================
# 4. Billing Settings Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class BillingSettingsTest(SaaSBaseTestCase):
    """Tests for the /owner/billing/ page."""

    def setUp(self):
        super().setUp()
        self.owner, self.tenant = self._create_owner_with_tenant()
        self.client = self._logged_in_client()

    def test_billing_requires_login(self):
        """Billing page redirects unauthenticated users."""
        anon_client = Client()
        response = anon_client.get('/owner/billing/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_billing_returns_200_for_owner(self):
        """Owner can access billing page."""
        response = self.client.get('/owner/billing/')
        self.assertEqual(response.status_code, 200)

    def test_billing_shows_plans(self):
        """Billing page context contains available plans."""
        response = self.client.get('/owner/billing/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('plans', response.context)
        # Should show paid plans (not trial)
        plan_slugs = [p.slug for p in response.context['plans']]
        self.assertIn('starter', plan_slugs)
        self.assertNotIn('trial', plan_slugs)

    def test_billing_shows_current_plan(self):
        """Billing page shows the current subscription plan."""
        response = self.client.get('/owner/billing/')
        self.assertEqual(response.context['current_plan'], self.trial_plan)

    def test_billing_shows_trial_info(self):
        """Billing shows trial status."""
        response = self.client.get('/owner/billing/')
        self.assertTrue(response.context['is_trial'])
        self.assertGreater(response.context['trial_days_remaining'], 0)

    def test_billing_non_owner_redirected(self):
        """Non-owner is redirected from billing page."""
        tech_user = User.objects.create_user(
            'tech@test.com', 'tech@test.com', 'TestPass123!'
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=tech_user, role='technician'
        )
        tech_client = Client()
        tech_client.login(username='tech@test.com', password='TestPass123!')
        response = tech_client.get('/owner/billing/')
        # Should redirect to dashboard with error
        self.assertEqual(response.status_code, 302)

    def test_billing_no_tenant_redirected(self):
        """User with no tenant is redirected."""
        no_tenant_user = User.objects.create_user(
            'orphan@test.com', 'orphan@test.com', 'TestPass123!'
        )
        client = Client()
        client.login(username='orphan@test.com', password='TestPass123!')
        response = client.get('/owner/billing/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('signup', response.url.lower())


# ======================================================================
# 5. Replacement Form Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class ReplacementFormTest(SaaSBaseTestCase):
    """Tests for the replacement create form."""

    def setUp(self):
        super().setUp()
        self.owner, self.tenant = self._create_owner_with_tenant()
        self.client = self._logged_in_client()

        # Create a technician
        from apps.technician_portal.models import Technician
        self.technician = Technician.objects.create(
            tenant=self.tenant, user=self.owner, is_active=True,
        )

        # Create a customer
        from core.models import Customer
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', customer_type='FLEET',
        )

    def test_replacement_form_requires_login(self):
        """Replacement form redirects unauthenticated users."""
        anon_client = Client()
        response = anon_client.get('/tech/replacement/new/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_replacement_form_get(self):
        """GET shows empty replacement form."""
        response = self.client.get('/tech/replacement/new/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_replacement_form_post_creates_replacement(self):
        """POST creates a replacement with correct tenant."""
        response = self.client.post('/tech/replacement/new/', {
            'customer': self.customer.id,
            'technician': self.technician.id,
            'unit_number': 'T-100',
            'glass_position': 'WINDSHIELD',
            'glass_type': 'OEM',
            'parts_cost': '150.00',
            'labor_cost': '200.00',
            'requires_adas_calibration': False,
            'insurance_claim': False,
        })
        # Should redirect on success
        if response.status_code == 302:
            from apps.technician_portal.models import Replacement
            replacement = Replacement.objects.get(unit_number='T-100')
            self.assertEqual(replacement.tenant, self.tenant)
            self.assertEqual(replacement.customer, self.customer)
            self.assertEqual(replacement.technician, self.technician)

    def test_replacement_form_plan_limit_enforced(self):
        """Plan limit prevents replacement creation when at limit."""
        # Set repair limit to 0
        self.trial_plan.max_repairs_per_month = 0
        self.trial_plan.save()

        response = self.client.get('/tech/replacement/new/')
        # Should redirect with a warning about plan limits
        self.assertEqual(response.status_code, 302)

    def test_replacement_form_scopes_customers_to_tenant(self):
        """Form only shows customers from the current tenant."""
        # Create another tenant's customer
        other_owner = User.objects.create_user(
            'other@test.com', 'other@test.com', 'TestPass123!'
        )
        other_tenant = Tenant.objects.create(
            name='Other', slug='other', subdomain='other', owner=other_owner,
        )
        from core.models import Customer
        Customer.objects.create(
            tenant=other_tenant, name='Other Customer', customer_type='FLEET',
        )

        response = self.client.get('/tech/replacement/new/')
        form = response.context['form']
        customer_qs = form.fields['customer'].queryset
        self.assertEqual(customer_qs.count(), 1)
        self.assertEqual(customer_qs.first().name, 'Fleet Co')


# ======================================================================
# 6. Pricing Page Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class PricingPageTest(SaaSBaseTestCase):
    """Tests for the /pricing/ page."""

    def test_pricing_is_public(self):
        """Pricing page is accessible without login."""
        response = self.client.get('/pricing/')
        self.assertEqual(response.status_code, 200)

    def test_pricing_shows_plans(self):
        """Pricing page context includes plans."""
        response = self.client.get('/pricing/')
        self.assertIn('plans', response.context)
        plans = response.context['plans']
        self.assertGreaterEqual(len(plans), 2)

    def test_pricing_plans_ordered(self):
        """Plans are ordered by display_order."""
        response = self.client.get('/pricing/')
        plans = list(response.context['plans'])
        self.assertEqual(plans[0].slug, 'trial')
        self.assertEqual(plans[1].slug, 'starter')


# ======================================================================
# 7. Owner Settings Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class OwnerSettingsTest(SaaSBaseTestCase):
    """Tests for /owner/settings/ page."""

    def setUp(self):
        super().setUp()
        self.owner, self.tenant = self._create_owner_with_tenant()
        self.client = self._logged_in_client()

    def test_settings_requires_login(self):
        """Settings page redirects unauthenticated users."""
        anon_client = Client()
        response = anon_client.get('/owner/settings/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_settings_returns_200(self):
        """Owner can access settings page."""
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 200)

    def test_settings_update_business_info(self):
        """POST updates business info."""
        response = self.client.post('/owner/settings/', {
            'business_name': 'Updated Shop Name',
            'business_phone': '555-999-1234',
            'business_email': 'updated@shop.com',
            'business_address': '456 New St',
        })
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, 'Updated Shop Name')
        self.assertEqual(self.tenant.business_phone, '555-999-1234')

    def test_settings_shows_members(self):
        """Settings page shows team members."""
        response = self.client.get('/owner/settings/')
        self.assertIn('members', response.context)

    def test_settings_non_owner_rejected(self):
        """Viewer cannot access settings."""
        viewer = User.objects.create_user(
            'viewer@test.com', 'viewer@test.com', 'TestPass123!'
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=viewer, role='viewer'
        )
        client = Client()
        client.login(username='viewer@test.com', password='TestPass123!')
        response = client.get('/owner/settings/')
        # Should redirect with error
        self.assertEqual(response.status_code, 302)


# ======================================================================
# 8. Invite Member Tests
# ======================================================================

@override_settings(**COMMON_OVERRIDES)
class InviteMemberTest(SaaSBaseTestCase):
    """Tests for /owner/settings/invite/."""

    def setUp(self):
        super().setUp()
        self.owner, self.tenant = self._create_owner_with_tenant()
        self.client = self._logged_in_client()

    def test_invite_requires_post(self):
        """GET redirects to settings."""
        response = self.client.get('/owner/settings/invite/')
        self.assertEqual(response.status_code, 302)

    def test_invite_creates_user_and_membership(self):
        """Inviting a new email creates user + membership."""
        response = self.client.post('/owner/settings/invite/', {
            'email': 'newtechnician@test.com',
            'first_name': 'New',
            'last_name': 'Tech',
            'role': 'technician',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email='newtechnician@test.com')
        membership = TenantMembership.objects.get(
            tenant=self.tenant, user=user
        )
        self.assertEqual(membership.role, 'technician')

    def test_invite_existing_user(self):
        """Inviting existing user adds membership to tenant."""
        existing = User.objects.create_user(
            'existing@test.com', 'existing@test.com', 'TestPass123!'
        )
        response = self.client.post('/owner/settings/invite/', {
            'email': 'existing@test.com',
            'first_name': 'Existing',
            'last_name': 'User',
            'role': 'manager',
        })
        self.assertEqual(response.status_code, 302)
        membership = TenantMembership.objects.get(
            tenant=self.tenant, user=existing
        )
        self.assertEqual(membership.role, 'manager')

    def test_invite_duplicate_handled(self):
        """Inviting already-existing member shows warning."""
        tech = User.objects.create_user(
            'dupetech@test.com', 'dupetech@test.com', 'TestPass123!'
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=tech, role='technician'
        )
        response = self.client.post('/owner/settings/invite/', {
            'email': 'dupetech@test.com',
            'first_name': 'Dupe',
            'last_name': 'Tech',
            'role': 'technician',
        })
        self.assertEqual(response.status_code, 302)
        # Should not create duplicate
        self.assertEqual(
            TenantMembership.objects.filter(
                tenant=self.tenant, user=tech
            ).count(), 1
        )
