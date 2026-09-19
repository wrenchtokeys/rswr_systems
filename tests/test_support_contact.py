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
- Public /contact/ (HELP_CENTER_SESSIONS H2): anonymous GET/POST, source='public',
  honeypot, Turnstile, per-IP rate limit, landing page links to it
- Acknowledgement email to the sender (H5) and the sender's own message list
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
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
PUBLIC_URL = '/contact/'


def _admin_mail():
    """The admin notification — the outbox also holds the sender's acknowledgement."""
    return [m for m in mail.outbox if m.to == ['drake@test.com']]


def _ack_mail():
    return [m for m in mail.outbox if m.to != ['drake@test.com']]


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
        # Regression: a multi-line {# #} in base_app.html isn't a comment to
        # Django — it rendered as visible text at the bottom of every page.
        self.assertNotContains(resp, '?v= busts')

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
        self.assertEqual(record.source, 'app')
        self.assertEqual(record.role, 'owner')

        self.assertEqual(len(_admin_mail()), 1)
        sent = _admin_mail()[0]
        self.assertEqual(sent.to, ['drake@test.com'])
        self.assertEqual(sent.reply_to, ['submit_owner@test.com'])
        self.assertIn('Submit Shop', sent.subject)
        self.assertIn('Role: owner', sent.body)
        self.assertIn('My invoice email never arrived', sent.body)
        self.assertIn(f'/admin/support/supportmessage/{record.pk}/change/', sent.body)

    def test_sender_gets_an_acknowledgement(self):
        self._post()
        record = SupportMessage.objects.get()
        self.assertTrue(record.acknowledged)
        acks = _ack_mail()
        self.assertEqual(len(acks), 1)
        ack = acks[0]
        self.assertEqual(ack.to, ['submit_owner@test.com'])
        self.assertEqual(ack.subject, 'We got your message')
        self.assertNotIn('[', ack.subject)
        self.assertIn('My invoice email never arrived', ack.body)
        # RS Systems talking, not the shop.
        self.assertNotIn('Submit Shop via', ack.from_email)

    def test_acknowledgement_failure_is_swallowed(self):
        with patch('apps.support.services.send_branded_email', side_effect=Exception('SES down')):
            resp = self._post()
        self.assertRedirects(resp, f'{CONTACT_URL}?sent=1')
        record = SupportMessage.objects.get()
        self.assertTrue(record.emailed_ok)
        self.assertFalse(record.acknowledged)

    def test_own_messages_listed_under_the_form(self):
        self._post(message='First question about tax.')
        other_user = User.objects.create_user('other_owner', 'other@test.com', 'testpass123')
        SupportMessage.objects.create(user=other_user, email='other@test.com', message='Not yours to see.')
        resp = self.client.get(CONTACT_URL)
        self.assertContains(resp, 'Your messages')
        self.assertContains(resp, 'First question about tax.')
        self.assertContains(resp, 'Received')
        self.assertNotContains(resp, 'Not yours to see.')
        SupportMessage.objects.filter(user=self.user).update(status='replied')
        self.assertContains(self.client.get(CONTACT_URL), 'Answered by email')

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
        with patch('apps.support.services.EmailMessage.send', side_effect=Exception('SES down')):
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
        # 30-day trial started 60 days ago: past the trial AND past the
        # TRIAL_GRACE_DAYS read-only window → hard block.
        self.tenant.trial_started_at = timezone.now() - timedelta(days=60)
        self.tenant.save(update_fields=['trial_started_at'])
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_app_is_blocked_but_contact_form_works(self):
        blocked = self.client.get(reverse('owner_dashboard'))
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
        self.assertEqual(len(_admin_mail()), 1)


@override_settings(**TEST_SETTINGS)
class PublicContactTests(TestCase):
    """A prospect on the landing page can write in without an account (H2)."""

    def setUp(self):
        cache.clear()

    def _post(self, **overrides):
        data = {
            'name': 'Pat Prospect',
            'email': 'pat@example.com',
            'topic': 'question',
            'message': 'I have 40 trucks in a spreadsheet. Can you import them?',
        }
        data.update(overrides)
        return self.client.post(PUBLIC_URL, data)

    def test_anonymous_get_renders(self):
        resp = self.client.get(PUBLIC_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Talk to a real person')
        self.assertContains(resp, 'name="name"')
        self.assertContains(resp, 'name="website"')  # honeypot

    def test_anonymous_post_saves_public_record_and_emails(self):
        resp = self._post()
        self.assertRedirects(resp, f'{PUBLIC_URL}?sent=1')
        record = SupportMessage.objects.get()
        self.assertEqual(record.source, 'public')
        self.assertIsNone(record.tenant)
        self.assertIsNone(record.user)
        self.assertEqual(record.name, 'Pat Prospect')
        self.assertEqual(record.email, 'pat@example.com')
        self.assertTrue(record.emailed_ok)
        self.assertTrue(record.acknowledged)
        admin = _admin_mail()[0]
        self.assertEqual(admin.reply_to, ['pat@example.com'])
        self.assertIn('Pat Prospect', admin.subject)
        self.assertIn('public form', admin.body)
        self.assertEqual(_ack_mail()[0].to, ['pat@example.com'])

    def test_success_card_after_redirect(self):
        resp = self._post()
        resp = self.client.get(resp['Location'])
        self.assertContains(resp, 'your message is in')
        self.assertContains(resp, 'pat@example.com')

    def test_name_required_on_public_form(self):
        resp = self._post(name='')
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'your name', status_code=400)
        self.assertEqual(SupportMessage.objects.count(), 0)

    def test_honeypot_filled_saves_nothing_and_looks_like_success(self):
        resp = self._post(website='http://spam.example')
        self.assertRedirects(resp, f'{PUBLIC_URL}?sent=1')
        self.assertEqual(SupportMessage.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_turnstile_failure_rejected(self):
        with patch('apps.saas.views._verify_turnstile', return_value=False):
            resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "confirm you", status_code=400)
        self.assertEqual(SupportMessage.objects.count(), 0)

    def test_ip_rate_limited_after_five_posts(self):
        for _ in range(5):
            self._post()
        resp = self._post()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(SupportMessage.objects.count(), 5)

    def test_signed_in_user_on_public_form_keeps_their_shop(self):
        user, tenant = make_tenant('Public Shop', 'public_owner')
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()
        resp = self.client.get(PUBLIC_URL)
        self.assertNotContains(resp, 'name="shop_name"')  # the tenant answers that
        self._post(email='public_owner@test.com', shop_name='Somebody Else Glass')
        record = SupportMessage.objects.get()
        self.assertEqual(record.source, 'public')
        self.assertEqual(record.tenant, tenant)
        self.assertEqual(record.user, user)
        self.assertEqual(record.role, 'owner')
        self.assertEqual(record.shop_name, '')  # typed, discarded: the tenant is the truth
        self.assertIn('Shop: Public Shop', _admin_mail()[0].body)

    def test_visitor_shop_name_is_recorded_and_marked_unverified(self):
        resp = self.client.get(PUBLIC_URL)
        self.assertContains(resp, 'name="shop_name"')
        self._post(shop_name='  Pat\'s Auto Glass  ')
        record = SupportMessage.objects.get()
        self.assertEqual(record.shop_name, "Pat's Auto Glass")
        self.assertIsNone(record.tenant)
        body = _admin_mail()[0].body
        self.assertIn("Shop: Pat's Auto Glass (visitor, public form)", body)

    def test_visitor_shop_name_is_optional(self):
        self._post(shop_name='')
        record = SupportMessage.objects.get()
        self.assertEqual(record.shop_name, '')
        self.assertIn('Shop: (no shop — public form)', _admin_mail()[0].body)

    def test_public_pages_link_to_the_public_form(self):
        # The landing page used to send prospects to /help/contact/ — a login wall.
        for url in ('/', '/sms/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, f'href="{PUBLIC_URL}"')
            self.assertNotContains(resp, '/help/contact/')
            self.assertNotContains(resp, 'mailto:contact@rssystems.io')


@override_settings(**TEST_SETTINGS)
class SweepSupportMessagesTests(TestCase):
    """The sweep is what turns emailed_ok=False from a silent row into a sent email (H5)."""

    def setUp(self):
        cache.clear()
        old = timezone.now() - timedelta(minutes=30)
        self.failed = SupportMessage.objects.create(
            name='Old Failed', email='old@test.com', message='This one never reached Drake.',
            emailed_ok=False, acknowledged=False,
        )
        SupportMessage.objects.filter(pk=self.failed.pk).update(created_at=old)
        self.fine = SupportMessage.objects.create(
            name='Old Fine', email='fine@test.com', message='This one was fine.',
            emailed_ok=True, acknowledged=True,
        )
        SupportMessage.objects.filter(pk=self.fine.pk).update(created_at=old)
        # Fresh and failed: could still be mid-request — must be left alone.
        self.fresh = SupportMessage.objects.create(
            name='Fresh', email='fresh@test.com', message='Just arrived.',
            emailed_ok=False, acknowledged=False,
        )

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('sweep_support_messages', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_and_sends_nothing(self):
        out = self._run('--dry-run')
        self.assertIn('1 message(s) never reached the admins', out)
        self.assertIn('1 sender(s) never got an acknowledgement', out)
        self.assertIn(f'#{self.failed.pk}', out)
        self.assertNotIn(f'#{self.fresh.pk}', out)
        self.assertEqual(len(mail.outbox), 0)
        self.failed.refresh_from_db()
        self.assertFalse(self.failed.emailed_ok)

    def test_real_run_resends_and_stamps_only_stale_rows(self):
        out = self._run()
        self.assertIn('Re-sent 1 admin notification(s) and 1 acknowledgement(s)', out)
        self.failed.refresh_from_db()
        self.assertTrue(self.failed.emailed_ok)
        self.assertTrue(self.failed.acknowledged)
        self.fresh.refresh_from_db()
        self.assertFalse(self.fresh.emailed_ok)
        admin = _admin_mail()
        self.assertEqual(len(admin), 1)
        self.assertEqual(admin[0].reply_to, ['old@test.com'])
        self.assertIn('never reached Drake', admin[0].body)
        acks = _ack_mail()
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0].to, ['old@test.com'])
        # Idempotent: a second run has nothing to do.
        self._run()
        self.assertEqual(len(mail.outbox), 2)
