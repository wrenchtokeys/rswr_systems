"""
Tests for the Phase 2 first-run experience (launch readiness roadmap):

- OnboardingState lazy-create + wizard persistence across sessions
- Dashboard "resume wizard" link
- Persisted checklist / trial-banner dismissals (tenant-scoped)
- Tour completion endpoint (JSON write, bad slug 404)
- /help/ pages: 200 for owner + technician, redirect anonymous
- Dashboard and Settings render the SAME checklist items
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings

from apps.tenants.models import OnboardingState, SubscriptionPlan, Tenant, TenantMembership
from apps.technician_portal.models import Technician

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        owner_username, f'{owner_username}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_SETTINGS)
class OnboardingStateModelTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_tenant('State Shop', 'state_owner')

    def test_get_for_tenant_lazy_creates(self):
        self.assertEqual(OnboardingState.objects.count(), 0)
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertEqual(state.wizard_step, 0)
        self.assertIsNone(state.wizard_completed_at)
        self.assertEqual(state.tours_completed, {})
        # Second call returns the same row
        again = OnboardingState.get_for_tenant(self.tenant)
        self.assertEqual(state.pk, again.pk)
        self.assertEqual(OnboardingState.objects.count(), 1)

    def test_tour_helpers(self):
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertFalse(state.has_completed_tour('owner-dashboard'))
        state.mark_tour_completed('owner-dashboard')
        state.refresh_from_db()
        self.assertTrue(state.has_completed_tour('owner-dashboard'))
        self.assertIn('owner-dashboard', state.tours_completed)


@override_settings(**TEST_SETTINGS)
class WizardPersistenceTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_tenant('Wizard Shop', 'wizard_owner')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _relogin(self):
        """Fresh client = new session; wizard state must NOT live in the session."""
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_visiting_wizard_marks_started(self):
        self.client.get('/onboarding/')
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertEqual(state.wizard_step, 1)

    def test_skip_advances_and_survives_relogin(self):
        r = self.client.post('/onboarding/?step=1', {'action': 'skip'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('step=2', r.url)
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertEqual(state.wizard_step, 2)

        self._relogin()
        r = self.client.get('/onboarding/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['step'], '2')

    def test_finishing_sets_completed_at(self):
        self.client.post('/onboarding/?step=1', {'action': 'skip'})
        self.client.post('/onboarding/?step=2', {'action': 'skip'})
        self.client.post('/onboarding/?step=3', {'action': 'skip'})
        # Step 4 GET redirects to dashboard and marks complete
        r = self.client.get('/onboarding/?step=4')
        self.assertEqual(r.status_code, 302)
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertIsNotNone(state.wizard_completed_at)
        self.assertTrue(state.wizard_completed)

    def test_dashboard_offers_resume_when_abandoned(self):
        self.client.post('/onboarding/?step=1', {'action': 'skip'})  # now at step 2
        r = self.client.get('/owner/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['wizard_resume_step'], 2)
        self.assertContains(r, 'step 2 of 4')

    def test_dashboard_no_resume_when_completed(self):
        state = OnboardingState.get_for_tenant(self.tenant)
        from django.utils import timezone
        state.wizard_step = 4
        state.wizard_completed_at = timezone.now()
        state.save()
        r = self.client.get('/owner/')
        self.assertIsNone(r.context['wizard_resume_step'])

    def test_dashboard_no_resume_when_never_started(self):
        """Existing shops (lazy-created state, step 0) must not get the banner."""
        r = self.client.get('/owner/')
        self.assertIsNone(r.context['wizard_resume_step'])


@override_settings(**TEST_SETTINGS)
class DismissEndpointTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_tenant('Dismiss Shop', 'dismiss_owner')
        self.other_user, self.other_tenant = make_tenant('Other Shop', 'other_owner')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_dismiss_checklist_persists(self):
        r = self.client.post('/owner/checklist/dismiss/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertIsNotNone(state.checklist_dismissed_at)
        # Dashboard no longer renders the checklist card
        r = self.client.get('/owner/')
        self.assertTrue(r.context['checklist_dismissed'])
        self.assertNotContains(r, 'id="setupChecklist"')

    def test_dismiss_trial_banner_persists(self):
        r = self.client.post('/owner/trial-banner/dismiss/')
        self.assertEqual(r.status_code, 200)
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertIsNotNone(state.trial_banner_dismissed_at)
        r = self.client.get('/owner/')
        self.assertTrue(r.context['trial_banner_dismissed'])

    def test_dismissals_are_tenant_scoped(self):
        self.client.post('/owner/checklist/dismiss/')
        self.client.post('/owner/trial-banner/dismiss/')
        other_state = OnboardingState.get_for_tenant(self.other_tenant)
        self.assertIsNone(other_state.checklist_dismissed_at)
        self.assertIsNone(other_state.trial_banner_dismissed_at)

    def test_get_not_allowed(self):
        r = self.client.get('/owner/checklist/dismiss/')
        self.assertEqual(r.status_code, 405)

    def test_anonymous_cannot_dismiss(self):
        anon = Client()
        r = anon.post('/owner/checklist/dismiss/')
        self.assertNotEqual(r.status_code, 200)
        self.assertIsNone(
            OnboardingState.objects.filter(tenant=self.tenant).first()
        )


@override_settings(**TEST_SETTINGS)
class TourEndpointTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_tenant('Tour Shop', 'tour_owner')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_complete_tour_writes_json(self):
        r = self.client.post('/owner/tours/owner-dashboard/complete/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        state = OnboardingState.get_for_tenant(self.tenant)
        self.assertTrue(state.has_completed_tour('owner-dashboard'))

    def test_unknown_slug_404s(self):
        r = self.client.post('/owner/tours/not-a-tour/complete/')
        self.assertEqual(r.status_code, 404)

    def test_dashboard_stops_offering_completed_tour(self):
        r = self.client.get('/owner/')
        self.assertEqual(r.context['tour_slug'], 'owner-dashboard')
        self.assertContains(r, 'data-tour="owner-dashboard"')

        self.client.post('/owner/tours/owner-dashboard/complete/')
        r = self.client.get('/owner/')
        self.assertEqual(r.context['tour_slug'], '')
        self.assertNotContains(r, 'data-tour="owner-dashboard"')

    def test_tour_replay_via_query_param(self):
        """?tour=1 (linked from the help pages) forces a replay even after completion."""
        self.client.post('/owner/tours/owner-dashboard/complete/')
        r = self.client.get('/owner/?tour=1')
        self.assertEqual(r.context['tour_slug'], 'owner-dashboard')
        self.assertContains(r, 'data-tour="owner-dashboard"')


@override_settings(**TEST_SETTINGS)
class HelpPagesTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant('Help Shop', 'help_owner')
        # A technician (non-owner) user
        self.tech_user = User.objects.create_user(
            'help_tech', 'help_tech@test.com', 'testpass123', first_name='Tech',
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.tech_user, role='technician',
        )
        Technician.objects.create(
            tenant=self.tenant, user=self.tech_user, is_active=True,
        )

    def _login(self, user):
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        return client

    def test_help_home_and_topics_200_for_owner(self):
        from apps.support.views import HELP_TOPICS, HELP_SECTIONS
        client = self._login(self.owner)
        r = client.get('/help/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Create your first job')
        # Every registered topic renders (registry-driven, so new guides are
        # covered automatically) and carries its video slot.
        for slug in HELP_TOPICS:
            r = client.get(f'/help/{slug}/')
            self.assertEqual(r.status_code, 200, f'/help/{slug}/ failed')
            self.assertContains(r, 'Video coming soon')
        # Every topic's section exists in the section list
        section_keys = {key for key, _ in HELP_SECTIONS}
        for slug, topic in HELP_TOPICS.items():
            self.assertIn(topic['section'], section_keys, f'{slug} has unknown section')

    def test_help_pages_200_for_technician(self):
        client = self._login(self.tech_user)
        r = client.get('/help/')
        self.assertEqual(r.status_code, 200)
        r = client.get('/help/first-job/')
        self.assertEqual(r.status_code, 200)

    def test_help_redirects_anonymous(self):
        anon = Client()
        r = anon.get('/help/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url)

    def test_unknown_topic_404s(self):
        client = self._login(self.owner)
        r = client.get('/help/not-a-real-page/')
        self.assertEqual(r.status_code, 404)


@override_settings(**TEST_SETTINGS)
class ChecklistConsistencyTests(TestCase):
    """Dashboard and Settings must render the same checklist items."""

    def setUp(self):
        self.user, self.tenant = make_tenant('Consistent Shop', 'consistent_owner')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_dashboard_and_settings_agree(self):
        dash = self.client.get('/owner/')
        settings_page = self.client.get('/owner/settings/')
        self.assertEqual(dash.status_code, 200)
        self.assertEqual(settings_page.status_code, 200)
        self.assertEqual(
            dash.context['checklist_items'],
            settings_page.context['checklist_items'],
        )
        # Counts agree with the item list
        completion = dash.context['setup_completion']
        self.assertEqual(
            completion['total_count'], len(dash.context['checklist_items']),
        )

    def test_customer_item_completes(self):
        from core.models import Customer
        dash = self.client.get('/owner/')
        item = next(i for i in dash.context['checklist_items']
                    if i['label'] == 'Your First Customer')
        self.assertEqual(item['status'], 'todo')

        Customer.objects.create(tenant=self.tenant, name='First Fleet')
        dash = self.client.get('/owner/')
        item = next(i for i in dash.context['checklist_items']
                    if i['label'] == 'Your First Customer')
        self.assertEqual(item['status'], 'done')
