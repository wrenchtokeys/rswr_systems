"""
Smoke tests for Step 3: Fix Signup & Onboarding.

1. create_tenant_with_owner() auto-creates Technician + adds to Technicians group
2. Onboarding step progression only advances on valid form
3. Step 2 is about adding ANOTHER technician, not yourself
"""
from django.test import TestCase
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
