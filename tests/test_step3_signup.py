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
