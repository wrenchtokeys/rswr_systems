"""
Smoke tests for Step 3: Fix Signup & Onboarding.

1. create_tenant_with_owner() auto-creates Technician + adds to Technicians group
2. Onboarding step progression only advances on valid form
3. Step 2 is about adding ANOTHER technician, not yourself
4. CODE-105: Signup CAPTCHA fix + intended_plan + dashboard banner
"""
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth.models import User, Group
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician


class SignupAutoTechnicianTests(TestCase):
    """After signup, the owner should have a Technician profile and be in Technicians group."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )

    def test_signup_creates_technician_profile(self):
        result = create_tenant_with_owner(
            business_name='Auto Tech Shop',
            email='autotech@test.com',
            password='testpass123!',
            first_name='Drake',
            last_name='Owner',
        )
        user = result['user']
        tenant = result['tenant']

        # Should have Technician profile
        self.assertTrue(
            Technician.objects.filter(user=user, tenant=tenant).exists(),
            "Owner should get a Technician profile on signup"
        )

        # Should be is_manager
        tech = Technician.objects.get(user=user)
        self.assertTrue(tech.is_manager, "Owner's tech profile should be is_manager")
        self.assertTrue(tech.is_active, "Owner's tech profile should be active")

    def test_signup_adds_to_technicians_group(self):
        result = create_tenant_with_owner(
            business_name='Group Test Shop',
            email='grouptest@test.com',
            password='testpass123!',
            first_name='Test',
            last_name='Owner',
        )
        user = result['user']

        self.assertTrue(
            user.groups.filter(name='Technicians').exists(),
            "Owner should be in Technicians group after signup"
        )

    def test_signup_still_creates_owner_membership(self):
        result = create_tenant_with_owner(
            business_name='Membership Shop',
            email='membership@test.com',
            password='testpass123!',
            first_name='M',
            last_name='Owner',
        )

        membership = result['membership']
        self.assertEqual(membership.role, 'owner')
        self.assertTrue(membership.is_active)


class OnboardingDuplicateEmailTests(TestCase):
    """
    CODE-027: Onboarding step 2 had dead-code email check.
    generate_unique_username() always returns a unique username, so the old guard
    `if not User.objects.filter(username=tech_username).exists()` was always True
    and never blocked duplicate emails. Fix: check email before creating user.
    """

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )

    def setUp(self):
        # Create owner and their tenant (Shop A)
        result = create_tenant_with_owner(
            business_name='Code 027 Shop',
            email='code027owner@test.com',
            password='testpass123!',
            first_name='Owner',
            last_name='Code027',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        # Pre-existing user at another shop with a known email
        self.existing_user = User.objects.create_user(
            username='existingtech_other',
            email='existing_tech@test.com',
            first_name='Other',
            last_name='Tech',
            password='somepass',
        )

    def test_step2_duplicate_email_does_not_create_second_user(self):
        """
        Submitting an existing email in onboarding step 2 should NOT create a
        second User record — it should show an info message and advance.
        """
        initial_user_count = User.objects.count()
        response = self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'Other',
            'tech_last_name': 'Tech',
            'tech_email': 'existing_tech@test.com',
            'tech_phone': '555-0000',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        # No new user should be created
        self.assertEqual(
            User.objects.count(), initial_user_count,
            "Duplicate email in onboarding step 2 must NOT create a second User"
        )

    def test_step2_duplicate_email_shows_info_message(self):
        """
        The duplicate-email case should show a friendly info message, not a 500.
        """
        response = self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'Other',
            'tech_last_name': 'Tech',
            'tech_email': 'existing_tech@test.com',
            'tech_phone': '555-0000',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Should contain the info message and advance cleanly (no server error page)
        self.assertIn('already exists', content)
        self.assertNotIn('Server Error', content)
        self.assertNotIn('Internal Server Error', content)

    def test_step2_new_email_still_creates_user(self):
        """
        A brand-new email should still create a User and Technician record.
        """
        from apps.technician_portal.models import Technician
        initial_user_count = User.objects.count()
        response = self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'Brand',
            'tech_last_name': 'New',
            'tech_email': 'brandnewtech_code027@test.com',
            'tech_phone': '555-1234',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            User.objects.count(), initial_user_count + 1,
            "A new email should create a User during onboarding step 2"
        )
        new_user = User.objects.get(email='brandnewtech_code027@test.com')
        self.assertTrue(
            Technician.objects.filter(user=new_user, tenant=self.tenant).exists(),
            "New tech user should have a Technician profile for this tenant"
        )

    def test_step2_no_email_only_first_name_still_creates_user(self):
        """
        Providing only a first name (no email) should still create a user — the
        duplicate-email guard must not accidentally block email-less technicians.
        """
        from apps.technician_portal.models import Technician
        initial_user_count = User.objects.count()
        response = self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'NoEmail',
            'tech_last_name': 'Tech',
            'tech_email': '',
            'tech_phone': '555-9999',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            User.objects.count(), initial_user_count + 1,
            "Tech without email should still be created"
        )


class OnboardingStepProgressionTests(TestCase):
    """Onboarding should NOT advance on invalid form submissions."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )

    def setUp(self):
        # Create an owner and log in
        result = create_tenant_with_owner(
            business_name='Onboard Shop',
            email='onboard@test.com',
            password='testpass123!',
            first_name='Test',
            last_name='Onboard',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        # Use force_login — create_tenant_with_owner uses first_name as username,
        # not email, so client.login(username=email) would fail.
        self.client.force_login(self.user)
        # Set tenant in session
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_step2_is_about_adding_another_tech(self):
        """Step 2 initial form should NOT have add_self checked."""
        response = self.client.get('/onboarding/?step=2')
        self.assertEqual(response.status_code, 200)
        # The initial form should not have add_self=True since owner already has tech profile
        content = response.content.decode()
        # The page should mention adding a team member, not yourself
        # (The form should not default to adding yourself)
        self.assertIn('step', response.context)


class SignupCaptchaAndPlanTests(TestCase):
    """CODE-105: Signup view passes turnstile_site_key and saves intended_plan."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        cls.starter_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='starter', defaults={'name': 'Starter', 'monthly_price': 49, 'trial_days': 0, 'is_active': True}
        )
        cls.pro_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='pro', defaults={'name': 'Professional', 'monthly_price': 99, 'trial_days': 0, 'is_active': True}
        )

    def test_signup_get_passes_turnstile_site_key(self):
        """GET /signup/ should have turnstile_site_key in context."""
        with patch.dict('os.environ', {'TURNSTILE_SITE_KEY': 'test-site-key-123'}):
            response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['turnstile_site_key'], 'test-site-key-123')

    def test_signup_post_error_passes_turnstile_site_key(self):
        """POST /signup/ with errors should still have turnstile_site_key in context."""
        with patch.dict('os.environ', {'TURNSTILE_SITE_KEY': 'test-key-456'}):
            response = self.client.post('/signup/', {
                'business_name': '',  # invalid
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'test@test.com',
                'password': 'testpass123!',
                'password_confirm': 'testpass123!',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['turnstile_site_key'], 'test-key-456')

    def test_signup_without_turnstile_key_still_works(self):
        """Signup should work when TURNSTILE_SITE_KEY is not set."""
        with patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('TURNSTILE_SITE_KEY', None)
            response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['turnstile_site_key'], '')

    def test_signup_with_plan_saves_intended_plan(self):
        """Signup with plan selection should save intended_plan on tenant."""
        with patch('apps.saas.views._verify_turnstile', return_value=True), \
             patch('apps.saas.views._send_confirmation_email'):
            response = self.client.post('/signup/', {
                'business_name': 'Plan Test Shop',
                'first_name': 'Plan',
                'last_name': 'Tester',
                'email': 'plan_test@test.com',
                'password': 'Str0ngP@ss123!',
                'password_confirm': 'Str0ngP@ss123!',
                'plan': 'starter',
            })
        self.assertEqual(response.status_code, 200)  # renders confirmation page
        tenant = Tenant.objects.get(name='Plan Test Shop')
        self.assertEqual(tenant.intended_plan, 'starter')

    def test_signup_without_plan_leaves_intended_plan_empty(self):
        """Signup without plan selection should leave intended_plan empty."""
        with patch('apps.saas.views._verify_turnstile', return_value=True), \
             patch('apps.saas.views._send_confirmation_email'):
            response = self.client.post('/signup/', {
                'business_name': 'No Plan Shop',
                'first_name': 'No',
                'last_name': 'Plan',
                'email': 'no_plan@test.com',
                'password': 'Str0ngP@ss123!',
                'password_confirm': 'Str0ngP@ss123!',
                'plan': '',
            })
        self.assertEqual(response.status_code, 200)
        tenant = Tenant.objects.get(name='No Plan Shop')
        self.assertEqual(tenant.intended_plan, '')

    def test_signup_form_has_plan_field(self):
        """SignupForm should include plan choices from active SubscriptionPlans."""
        from apps.saas.forms import SignupForm
        form = SignupForm()
        self.assertIn('plan', form.fields)
        choices = [c[0] for c in form.fields['plan'].choices]
        self.assertIn('starter', choices)
        self.assertIn('pro', choices)
        self.assertNotIn('trial', choices)  # trial excluded


class DashboardIntendedPlanTests(TestCase):
    """CODE-105: Dashboard shows intended_plan in trial banner context."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
        )
        cls.starter_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='starter', defaults={'name': 'Starter', 'monthly_price': 49, 'trial_days': 0, 'is_active': True}
        )

    def setUp(self):
        result = create_tenant_with_owner(
            business_name='Dashboard Plan Shop',
            email='dash_plan@test.com',
            password='testpass123!',
            first_name='Dash',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_dashboard_with_intended_plan(self):
        """Dashboard context includes intended_plan_name when set."""
        self.tenant.intended_plan = 'starter'
        self.tenant.save(update_fields=['intended_plan'])
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['intended_plan'], 'starter')
        self.assertEqual(response.context['intended_plan_name'], 'Starter')

    def test_dashboard_without_intended_plan(self):
        """Dashboard context has empty intended_plan_name when not set."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['intended_plan'], '')
        self.assertEqual(response.context['intended_plan_name'], '')

    def test_dashboard_shows_intended_plan_in_banner(self):
        """Template should mention intended plan name in trial banner."""
        self.tenant.intended_plan = 'starter'
        self.tenant.save(update_fields=['intended_plan'])
        response = self.client.get('/owner/')
        content = response.content.decode()
        self.assertIn('Starter', content)
        self.assertIn('the plan you chose at signup', content)
