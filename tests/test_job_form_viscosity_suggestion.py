"""
The temperature -> resin viscosity suggestion on the job form.

It used to live only in `technician_portal/repair_form.html`, driven by
`static/js/repair_form.js`. When the unified job form landed, every "New job"
entry point in the app moved to `technician_portal/job_form.html` — which had
the temperature and viscosity inputs but none of the suggestion wiring. The
API and the per-shop rules behind it kept working the whole time; the only
page that still asked them anything was the edit-an-existing-repair form.

These tests pin the three pieces that have to be present together for a
technician to see anything: the container, the fetch, and a live API that
answers with the shop's own rule.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import ViscosityRecommendation


class JobFormViscositySuggestionTests(TestCase):
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0,
                      'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Viscosity Shop', email='owner@viscosity.test',
            password='testpass123!', first_name='Vic', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        # The suggestion block is gated on the shop actually doing repairs.
        self.tenant.services_offered = 'both'
        self.tenant.save()

        self.rule = ViscosityRecommendation.objects.create(
            tenant=self.tenant, name='Hot Glass', min_temperature=Decimal('105.1'),
            max_temperature=None, recommended_viscosity='Cool Glass First',
            suggestion_text='Cool the windshield first.', badge_color='red',
            display_order=1, is_active=True,
        )

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _job_form(self):
        return self.client.get(reverse('job_create'), {'type': 'repair'})

    def test_job_form_renders_the_suggestion_container(self):
        """Without this div the script has nowhere to write and bails out."""
        html = self._job_form().content.decode()
        self.assertIn('id="viscositySuggestion"', html)

    def test_job_form_calls_the_suggestion_endpoint(self):
        """The container is inert unless something actually fetches a rule."""
        html = self._job_form().content.decode()
        self.assertIn('/tech/api/viscosity-suggestion/', html)

    def test_endpoint_returns_the_shops_own_rule(self):
        response = self.client.get(
            reverse('get_viscosity_suggestion'), {'temperature': '112'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['recommendation'], 'Cool Glass First')
        self.assertEqual(data['suggestion_text'], 'Cool the windshield first.')
        self.assertEqual(data['badge_color'], 'red')

    def test_endpoint_stays_quiet_for_an_uncovered_temperature(self):
        """No matching rule is not an error — the form just shows nothing."""
        data = self.client.get(
            reverse('get_viscosity_suggestion'), {'temperature': '70'}
        ).json()
        self.assertTrue(data['success'])
        self.assertIsNone(data['recommendation'])

    def test_another_shops_rule_is_never_suggested(self):
        """Rules are per-shop; a second tenant's rule must not leak in."""
        other = create_tenant_with_owner(
            business_name='Other Shop', email='owner@other.test',
            password='testpass123!', first_name='Otto', last_name='Owner',
        )['tenant']
        ViscosityRecommendation.objects.create(
            tenant=other, name='Everything', min_temperature=None,
            max_temperature=None, recommended_viscosity='Leaked',
            suggestion_text='Should never be seen.', badge_color='purple',
            display_order=0, is_active=True,
        )

        data = self.client.get(
            reverse('get_viscosity_suggestion'), {'temperature': '70'}
        ).json()
        self.assertIsNone(data['recommendation'])
