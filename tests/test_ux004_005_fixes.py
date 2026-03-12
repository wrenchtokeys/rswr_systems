"""
Regression tests for UX-004 and UX-005:

UX-004: Free Trial badge should use blue outline styling (not amber/orange)
        to match the blue nav design system.

UX-005: Onboarding step 2 tech creation should show clear, actionable
        success messages including tech name and next steps.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner


class TrialBadgeColorTests(TestCase):
    """UX-004: Trial plan badge should use blue outline, not amber/orange."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Free Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )

    def setUp(self):
        result = create_tenant_with_owner(
            business_name='Trial Badge Shop', email='trialbadge@test.com',
            password='testpass123!', first_name='Trial', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_trial_badge_has_blue_outline_classes(self):
        """Trial plan badge should use blue outline (border-blue-300, text-blue-600, bg-white)."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Blue outline pill classes should be present
        self.assertIn('border-blue-300', content)
        self.assertIn('text-blue-600', content)
        self.assertIn('bg-white', content)

    def test_trial_badge_does_not_use_amber_classes(self):
        """Trial plan badge should NOT use amber/orange classes (UX-004 fix)."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The nav badge section should not have amber-100/amber-800 for trial
        # We check the plan badge specifically — amber colors should be gone from nav badge
        self.assertNotIn('bg-amber-100 text-amber-800', content)

    def test_trial_badge_shows_on_settings_page(self):
        """Trial badge should be visible with blue styling on settings page."""
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('border-blue-300', content)

    def test_base_app_template_has_blue_trial_class_not_amber(self):
        """The base_app.html template source should have blue classes, not amber, for trial plan."""
        with open('templates/base_app.html', 'r') as f:
            template_src = f.read()
        # The trial plan conditional should use blue outline classes
        self.assertIn('border-blue-300', template_src)
        self.assertIn('text-blue-600', template_src)
        # The amber class should not appear in the plan badge conditional
        # (amber can appear elsewhere but not in the trial badge block)
        trial_idx = template_src.find("tenant.plan == 'trial'")
        # Get the surrounding context (next 100 chars)
        badge_block = template_src[trial_idx:trial_idx+100]
        self.assertNotIn('bg-amber-100', badge_block)

    def test_trial_badge_shows_plan_display_text(self):
        """Trial badge should still show the plan name text."""
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The plan display name should be shown (Free Trial or Trial)
        self.assertIn('Trial', content)


class OnboardingTechConfirmationTests(TestCase):
    """UX-005: Onboarding step 2 tech creation shows clear, actionable messages."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Free Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )

    def setUp(self):
        result = create_tenant_with_owner(
            business_name='Onboarding Test Shop', email='onboardtest@test.com',
            password='testpass123!', first_name='Onboard', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session['onboarding_step'] = '2'
        session.save()

    def test_add_self_shows_clear_confirmation(self):
        """Adding yourself as a tech should show a clear success message."""
        response = self.client.post('/onboarding/?step=2', {
            'add_self': True,
            'tech_phone': '',
            'tech_first_name': '',
            'tech_last_name': '',
            'tech_email': '',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in response.context['messages']]
        # Should confirm the user was added
        added_messages = [m for m in messages_list if 'technician' in m.lower()]
        self.assertTrue(
            len(added_messages) > 0,
            f"Expected a technician confirmation message, got: {messages_list}"
        )

    def test_add_other_tech_with_email_shows_next_steps(self):
        """Adding another person should show their name and point to Settings → Team for invite."""
        response = self.client.post('/onboarding/?step=2', {
            'add_self': False,
            'tech_first_name': 'Alex',
            'tech_last_name': 'Smith',
            'tech_email': 'alex.smith.onboard@test.com',
            'tech_phone': '555-0101',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in response.context['messages']]
        # Should mention the tech's name or email
        name_mentioned = any('Alex' in m or 'alex.smith' in m for m in messages_list)
        self.assertTrue(name_mentioned, f"Tech name not in messages: {messages_list}")
        # Should point to Settings → Team
        settings_mentioned = any('Settings' in m for m in messages_list)
        self.assertTrue(settings_mentioned, f"Settings guidance not in messages: {messages_list}")

    def test_add_other_tech_without_email_mentions_invite(self):
        """Adding a tech without email should still prompt user to add email for invite."""
        response = self.client.post('/onboarding/?step=2', {
            'add_self': False,
            'tech_first_name': 'Jordan',
            'tech_last_name': 'Lee',
            'tech_email': '',
            'tech_phone': '555-0202',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in response.context['messages']]
        # Should encourage adding email for invite
        invite_guidance = any(
            'email' in m.lower() or 'invite' in m.lower() or 'settings' in m.lower()
            for m in messages_list
        )
        self.assertTrue(invite_guidance, f"No invite guidance in messages: {messages_list}")

    def test_no_tech_info_shows_helpful_message(self):
        """Submitting step 2 with no tech info should show a helpful message with next steps."""
        response = self.client.post('/onboarding/?step=2', {
            'add_self': False,
            'tech_first_name': '',
            'tech_last_name': '',
            'tech_email': '',
            'tech_phone': '',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        messages_list = [str(m) for m in response.context['messages']]
        # Should mention Settings → Team as fallback
        helpful = any('Settings' in m or 'later' in m for m in messages_list)
        self.assertTrue(helpful, f"No helpful guidance in messages: {messages_list}")

    def test_add_other_tech_advances_to_step_3(self):
        """Successfully adding another tech should advance onboarding to step 3."""
        response = self.client.post('/onboarding/?step=2', {
            'add_self': False,
            'tech_first_name': 'Sam',
            'tech_last_name': 'Parker',
            'tech_email': 'sam.parker.onboard@test.com',
            'tech_phone': '',
        }, follow=False)
        # Should redirect to step 3
        self.assertRedirects(response, '/onboarding/?step=3', fetch_redirect_response=False)
