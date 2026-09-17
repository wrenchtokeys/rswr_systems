"""
A2P consent surface guards (2026-09-17).

RS Systems' toll-free registration was denied four times. Version 1's reason was
"Unclear Opt-in Language" against a checkbox whose entire label read "SMS
Notifications"; version 3's was "Pre-selected Opt-in" against a box that has
never carried `checked`.

These tests pin the staff opt-in surface — the screen that gets screenshotted for
the registration — so neither denial can come back by a template edit. See
docs/operations/SMS_REGISTRATION.md.
"""

import re

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.technician_portal.models import Technician
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models.notification_preferences import TechnicianNotificationPreference


class SmsConsentSurfaceTests(TestCase):
    """The consent block must carry every element a carrier looks for."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0,
                      'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Test Shop', email='owner@test.com',
            password='testpass123!', first_name='Test', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user)
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _page(self):
        response = self.client.get(reverse('notification_preferences'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_consent_states_who_is_texting_and_about_what(self):
        """Registrant brand and message types, at the point of consent."""
        html = self._page()
        self.assertIn('RS Systems', html)
        self.assertIn('repair requests', html)

    def test_consent_states_frequency(self):
        """v1 was denied for omitting message frequency."""
        html = self._page()
        self.assertIn('Message frequency varies', html)

    def test_consent_states_rates_and_stop_help(self):
        """Msg & data rates + STOP/HELP must sit beside the box, not only on /sms/."""
        html = self._page()
        self.assertIn('data rates may apply', html)
        self.assertIn('Reply STOP to opt out', html)
        self.assertIn('HELP for help', html)

    def test_consent_links_program_terms_privacy_and_terms(self):
        html = self._page()
        self.assertIn('/sms/', html)
        self.assertIn(reverse('privacy_policy'), html)
        self.assertIn(reverse('terms_of_service'), html)

    def test_consent_says_it_is_not_a_condition_of_service(self):
        html = self._page()
        self.assertIn('not a condition', html.lower())

    def test_checkbox_is_never_pre_selected(self):
        """Version 3's denial. The box must render unchecked for a new user.

        Asserted against the rendered HTML rather than the model, because the
        thing that was denied was a screenshot of rendered HTML.
        """
        html = self._page()
        match = re.search(
            r'<input[^>]*name="receive_sms_notifications"[^>]*>', html
        )
        self.assertIsNotNone(match, "SMS consent checkbox is missing from the page")
        self.assertNotIn('checked', match.group(0))


class SmsConsentRecordTests(TestCase):
    """Turning the switch on through the form writes the evidence."""

    def setUp(self):
        self.user = User.objects.create_user(username='tech', email='t@test.com')
        self.technician = Technician.objects.create(
            user=self.user, phone_number='+15012827129'
        )
        self.prefs = TechnicianNotificationPreference.objects.create(
            technician=self.technician
        )

    def test_opting_in_through_the_form_stamps_consent(self):
        from apps.technician_portal.forms import TechnicianNotificationPreferenceForm

        form = TechnicianNotificationPreferenceForm(
            data={
                'receive_email_notifications': 'on',
                'receive_sms_notifications': 'on',
                'receive_in_app_notifications': 'on',
            },
            instance=self.prefs,
        )
        self.assertTrue(form.is_valid(), form.errors)
        prefs = form.save()
        self.assertIsNotNone(prefs.sms_consent_at)
        self.assertEqual(prefs.sms_consent_source, 'SELF_SERVICE')

    def test_saving_again_does_not_move_the_timestamp(self):
        """The original moment is the evidence; a later save must not overwrite it."""
        from apps.technician_portal.forms import TechnicianNotificationPreferenceForm

        self.prefs.receive_sms_notifications = True
        self.prefs.sms_consent_at = timezone.now() - timezone.timedelta(days=30)
        self.prefs.sms_consent_source = 'SELF_SERVICE'
        self.prefs.save()
        original = self.prefs.sms_consent_at

        form = TechnicianNotificationPreferenceForm(
            data={
                'receive_email_notifications': 'on',
                'receive_sms_notifications': 'on',
                'receive_in_app_notifications': 'on',
            },
            instance=self.prefs,
        )
        self.assertTrue(form.is_valid(), form.errors)
        prefs = form.save()
        self.assertEqual(prefs.sms_consent_at, original)
