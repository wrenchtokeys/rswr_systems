"""
Tests for the Phase 3 support contact form (launch readiness roadmap):

- /help/contact/ renders for owner + technician, redirects anonymous
- Valid POST: SupportMessage saved, admins emailed with Reply-To the sender,
  PRG redirect to the success card echoing the reply address
- Validation: empty message / bad email re-render with the input kept
- Record-first: an email outage still saves the row (emailed_ok=False) and
  still shows the sender success
- Subscription exemption: an expired shop is blocked from the app but can
  still reach and submit the contact form
- Help surfaces link to the form instead of a mailto:
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.support.models import SupportMessage
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'ADMINS': [('Drake', 'drake@test.com')],
    'BASE_URL': 'https://rssystems.io',
}

CONTACT_URL = '/help/contact/'


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
class ContactFormRenderTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user, self.tenant = make_tenant('Render Shop', 'render_owner')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_get_renders_form(self):
        resp = self.client.get(CONTACT_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Talk to a real person')
        # Reply email prefilled from the account
        self.assertContains(resp, 'render_owner@test.com')

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(CONTACT_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp['Location'])

    def test_technician_can_open_form(self):
        tech_user = User.objects.create_user('render_tech', 'tech@test.com', 'testpass123')
        TenantMembership.objects.create(tenant=self.tenant, user=tech_user, role='technician')
        self.client.force_login(tech_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        self.assertEqual(self.client.get(CONTACT_URL).status_code, 200)

    def test_help_surfaces_link_to_form_not_mailto(self):
        for url in ('/help/', '/help/troubleshooting/'):
            resp = self.client.get(url)
            self.assertContains(resp, CONTACT_URL)
            self.assertNotContains(resp, 'mailto:contact@rssystems.io')


@override_settings(**TEST_SETTINGS)
class ContactFormSubmitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user, self.tenant = make_tenant('Submit Shop', 'submit_owner')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post(self, **overrides):
        data = {
            'topic': 'problem',
            'message': 'My invoice email never arrived at the customer.',
            'email': 'submit_owner@test.com',
            'page': 'https://rssystems.io/owner/invoices/',
        }
        data.update(overrides)
        return self.client.post(CONTACT_URL, data)

    def test_valid_post_saves_record_and_emails_admins(self):
        resp = self._post()
        self.assertRedirects(resp, f'{CONTACT_URL}?sent=1')

        record = SupportMessage.objects.get()
        self.assertEqual(record.tenant, self.tenant)
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.name, 'Test Owner')
        self.assertEqual(record.email, 'submit_owner@test.com')
        self.assertEqual(record.topic, 'problem')
        self.assertEqual(record.page, 'https://rssystems.io/owner/invoices/')
        self.assertTrue(record.emailed_ok)
        self.assertEqual(record.status, 'new')

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['drake@test.com'])
        self.assertEqual(sent.reply_to, ['submit_owner@test.com'])
        self.assertIn('Submit Shop', sent.subject)
        self.assertIn('My invoice email never arrived', sent.body)
        self.assertIn(f'/admin/support/supportmessage/{record.pk}/change/', sent.body)

    def test_success_card_echoes_reply_address_once(self):
        resp = self.client.post(CONTACT_URL, {
            'topic': 'question', 'message': 'Where do I set tax?',
            'email': 'submit_owner@test.com',
        }, follow=True)
        self.assertContains(resp, 'your message is in')
        self.assertContains(resp, 'submit_owner@test.com')
        # Refreshing the bookmarked ?sent=1 shows the generic line, not a stale address
        resp = self.client.get(f'{CONTACT_URL}?sent=1')
        self.assertContains(resp, 'the email you gave us')

    def test_empty_message_rerenders_with_error(self):
        resp = self._post(message='   ')
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'message box is empty', status_code=400)
        self.assertEqual(SupportMessage.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_bad_email_rerenders_keeping_message(self):
        resp = self._post(email='not-an-email')
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'double-check it', status_code=400)
        self.assertContains(resp, 'My invoice email never arrived', status_code=400)
        self.assertEqual(SupportMessage.objects.count(), 0)

    def test_blank_email_falls_back_to_account_email(self):
        self._post(email='')
        self.assertEqual(SupportMessage.objects.get().email, 'submit_owner@test.com')

    def test_unknown_topic_degrades_to_question(self):
        self._post(topic='hax')
        self.assertEqual(SupportMessage.objects.get().topic, 'question')

    def test_email_outage_still_saves_record(self):
        with patch('apps.support.views.EmailMessage.send', side_effect=Exception('SES down')):
            resp = self._post()
        self.assertRedirects(resp, f'{CONTACT_URL}?sent=1')
        record = SupportMessage.objects.get()
        self.assertFalse(record.emailed_ok)

    def test_rate_limited_after_ten_posts(self):
        for _ in range(10):
            self._post()
        resp = self._post()
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, 'give us a moment', status_code=429)
        self.assertEqual(SupportMessage.objects.count(), 10)


@override_settings(**TEST_SETTINGS)
class ContactFormExpiredTenantTests(TestCase):
    """The shop whose trial just ended is exactly who needs the form."""

    def setUp(self):
        cache.clear()
        self.user, self.tenant = make_tenant('Expired Shop', 'expired_owner')
        # 30-day trial started 40 days ago, no grace period → hard block
        self.tenant.trial_started_at = timezone.now() - timedelta(days=40)
        self.tenant.save(update_fields=['trial_started_at'])
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_app_is_blocked_but_contact_form_works(self):
        blocked = self.client.get('/owner/dashboard/')
        self.assertEqual(blocked.status_code, 302)
        self.assertIn('/subscription-blocked/', blocked['Location'])

        self.assertEqual(self.client.get(CONTACT_URL).status_code, 200)

        resp = self.client.post(CONTACT_URL, {
            'topic': 'billing',
            'message': 'My trial ended but I still need my invoices.',
            'email': 'expired_owner@test.com',
        })
        self.assertRedirects(resp, f'{CONTACT_URL}?sent=1')
        self.assertEqual(SupportMessage.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
