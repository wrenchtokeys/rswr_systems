"""/help/contact/ has to work for someone who hasn't signed up.

It is the only non-mailto contact path on the landing page -- "Have a customer
list in a spreadsheet, or questions about your setup? Send it through the
contact form" -- and it was `@login_required`, so it 302'd a visitor to
/login/?next=/help/contact/. The page is written for a shop owner who is
interested but has no account, which is precisely who could not use it.

The help GUIDES stay gated; only `contact` opened.
"""

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings

from apps.support.models import SupportMessage
from tests.test_e2e_today import make_tenant

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'ADMINS': [('Drake', 'drake@rssystems.test')],
    'RATELIMIT_ENABLE': False,
}


@override_settings(**TEST_SETTINGS)
class AnonymousContactTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_a_visitor_can_open_the_form(self):
        resp = self.client.get('/help/contact/')
        self.assertEqual(resp.status_code, 200, 'the landing page contact link still 302s')
        self.assertFalse(resp.context['known'])

    def test_the_landing_page_link_actually_lands(self):
        """The exact hop the landing page asks a visitor to make."""
        landing = self.client.get('/')
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, '/help/contact/')
        self.assertEqual(self.client.get('/help/contact/').status_code, 200)

    def test_the_visitor_is_asked_who_they_are(self):
        resp = self.client.get('/help/contact/')
        self.assertContains(resp, 'What shop are you with?')
        self.assertContains(resp, 'name="shop_name"')
        self.assertContains(resp, 'Your name')

    def test_a_visitor_message_is_recorded_and_emailed(self):
        resp = self.client.post('/help/contact/', {
            'topic': 'question',
            'message': 'Do you import a customer list from a spreadsheet?',
            'email': 'owner@someglass.test',
            'name': 'Sam Owner',
            'shop_name': 'Some Glass Co',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('sent=1', resp['Location'])

        record = SupportMessage.objects.get()
        self.assertIsNone(record.tenant)
        self.assertIsNone(record.user)
        self.assertEqual(record.name, 'Sam Owner')
        self.assertEqual(record.shop_name, 'Some Glass Co')
        self.assertEqual(record.email, 'owner@someglass.test')
        self.assertTrue(record.emailed_ok)

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.reply_to, ['owner@someglass.test'])
        self.assertIn('Some Glass Co', sent.subject)
        self.assertIn('Some Glass Co', sent.body)
        self.assertIn('visitor', sent.body)

    def test_the_record_survives_a_dead_mailer(self):
        """Record-first: an SES outage must not lose a lead."""
        with override_settings(EMAIL_BACKEND='tests.test_public_contact.ExplodingBackend'):
            resp = self.client.post('/help/contact/', {
                'topic': 'problem', 'message': 'Nothing loads.',
                'email': 'sam@someglass.test', 'shop_name': 'Some Glass Co',
            })
        self.assertEqual(resp.status_code, 302)
        record = SupportMessage.objects.get()
        self.assertFalse(record.emailed_ok, 'a failed send must be flaggable in the admin')
        self.assertEqual(record.message, 'Nothing loads.')

    def test_an_empty_message_is_refused_without_losing_what_was_typed(self):
        resp = self.client.post('/help/contact/', {
            'topic': 'idea', 'message': '   ', 'email': 'sam@someglass.test',
            'shop_name': 'Some Glass Co',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'message box is empty', status_code=400)
        self.assertContains(resp, 'Some Glass Co', status_code=400)
        self.assertEqual(SupportMessage.objects.count(), 0)

    def test_a_bad_email_is_refused(self):
        resp = self.client.post('/help/contact/', {
            'topic': 'question', 'message': 'hello', 'email': 'not-an-email',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(SupportMessage.objects.count(), 0)

    def test_the_honeypot_swallows_a_bot_without_telling_it(self):
        resp = self.client.post('/help/contact/', {
            'topic': 'question', 'message': 'buy my links',
            'email': 'bot@spam.test', 'website': 'http://spam.test',
        })
        # Looks exactly like success from the outside; nothing is stored.
        self.assertEqual(resp.status_code, 302)
        self.assertIn('sent=1', resp['Location'])
        self.assertEqual(SupportMessage.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_the_visitor_gets_the_public_shell_not_the_app_chrome(self):
        resp = self.client.get('/help/contact/')
        self.assertEqual(resp.context['base_template'], 'saas/base_public.html')
        # base_app.html's nav would be meaningless without a tenant.
        self.assertNotContains(resp, 'All guides')

    def test_the_guides_themselves_are_still_gated(self):
        """Opening contact must not open the help centre with it."""
        for url in ('/help/', '/help/sales-tax/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, f'{url} is now public')
            self.assertIn('login', resp['Location'])


@override_settings(**TEST_SETTINGS)
class LoggedInContactTests(TestCase):
    """The existing behaviour, unchanged."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Contact Shop', 'contact_owner')
        self.owner.email = 'owner@contactshop.test'
        self.owner.save(update_fields=['email'])
        self.client = Client()
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_a_signed_in_owner_is_not_asked_what_shop_they_are_with(self):
        resp = self.client.get('/help/contact/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['known'])
        self.assertNotContains(resp, 'What shop are you with?')
        self.assertEqual(resp.context['base_template'], 'base_app.html')

    def test_their_message_still_carries_tenant_and_user(self):
        resp = self.client.post('/help/contact/', {
            'topic': 'billing', 'message': 'Question about my plan.',
            'email': 'owner@contactshop.test',
        })
        self.assertEqual(resp.status_code, 302)
        record = SupportMessage.objects.get()
        self.assertEqual(record.tenant, self.tenant)
        self.assertEqual(record.user, self.owner)
        self.assertEqual(record.shop_name, '', 'the tenant is the answer for a known sender')
        self.assertIn('Contact Shop', mail.outbox[0].subject)

    def test_a_typed_shop_name_is_ignored_for_a_known_sender(self):
        """The tenant is authoritative; a spoofed field must not override it."""
        self.client.post('/help/contact/', {
            'topic': 'question', 'message': 'hi',
            'email': 'owner@contactshop.test', 'shop_name': 'Someone Else Glass',
        })
        record = SupportMessage.objects.get()
        self.assertEqual(record.shop_name, '')
        self.assertEqual(record.tenant, self.tenant)


class ExplodingBackend:
    """Email backend that always fails, for the record-first test."""

    def __init__(self, *a, **kw):
        pass

    def send_messages(self, messages):
        raise RuntimeError('SES is down')
