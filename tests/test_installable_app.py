"""RS Systems as a home-screen app, and staying signed in to it.

Two halves of one complaint — "I have to find it in the browser and log back in
every time":

  * the manifest + icons that make "Add to Home Screen" install an app, and
  * a "Keep me signed in" session that lasts 90 days from the last VISIT.

See common/sessions.py and rs_systems.views.web_manifest.
"""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.models import Session
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone
from PIL import Image

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from common.sessions import STAMP_KEY

PASSWORD = 'testpass123!'
NINETY_DAYS = 60 * 60 * 24 * 90


def make_owner():
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name='Install Test Glass', email='owner@install.test',
        password=PASSWORD, first_name='Ina', last_name='Owner',
    )
    return result['user'], result['tenant']


class ManifestTests(TestCase):
    def setUp(self):
        self.response = self.client.get('/manifest.webmanifest')
        self.manifest = self.response.json()

    def test_served_as_a_manifest(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertEqual(self.response['Content-Type'], 'application/manifest+json')

    def test_opens_full_screen(self):
        self.assertEqual(self.manifest['display'], 'standalone')

    def test_start_url_is_the_login_router(self):
        """One icon for every role: login_router routes whoever is signed in."""
        self.assertEqual(resolve(self.manifest['start_url']).url_name, 'login')
        self.assertTrue(self.manifest['start_url'].startswith(self.manifest['scope']))

    def test_names_the_platform(self):
        self.assertEqual(self.manifest['name'], 'RS Systems')

    def test_every_icon_exists_at_the_size_it_claims(self):
        self.assertTrue(self.manifest['icons'])
        for icon in self.manifest['icons']:
            relative = icon['src'][len(settings.STATIC_URL):]
            path = finders.find(relative)
            self.assertIsNotNone(path, f'{icon["src"]} is not a static file')
            with Image.open(path) as img:
                self.assertEqual(f'{img.width}x{img.height}', icon['sizes'])

    def test_installable_icon_set(self):
        """Chrome needs a 192 and a 512; Android needs a maskable one or it
        shrinks the icon into a white circle."""
        sizes = {(i['sizes'], i['purpose']) for i in self.manifest['icons']}
        self.assertIn(('192x192', 'any'), sizes)
        self.assertIn(('512x512', 'any'), sizes)
        self.assertIn(('512x512', 'maskable'), sizes)

    def test_fetching_it_starts_no_session(self):
        self.assertNotIn(settings.SESSION_COOKIE_NAME, self.response.cookies)

    def test_apple_touch_icon_is_opaque(self):
        """iOS paints a transparent icon's background black."""
        with Image.open(finders.find('images/app/apple-touch-icon.png')) as img:
            self.assertEqual(img.mode, 'RGB')
            self.assertEqual(img.size, (180, 180))


class InstallMarkupTests(TestCase):
    def test_login_page_is_installable_and_remembers_by_default(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'rel="manifest" href="/manifest.webmanifest"')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, 'name="remember_me" checked')

    def test_staff_shell_carries_the_manifest_and_the_hint(self):
        user, tenant = make_owner()
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()
        response = self.client.get(reverse('owner_dashboard'))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'id="install-hint"')
        self.assertContains(response, 'js/install-hint')

    def test_hint_ships_hidden(self):
        """It is an offer the script makes when the device can take it up —
        a visible card on a desktop Firefox would be a button to nowhere."""
        source = (Path(settings.BASE_DIR) / 'templates/includes/install_hint.html').read_text()
        self.assertIn('<div id="install-hint" class="hidden ', source)

    def test_public_and_customer_shells_do_not_offer_the_platform_app(self):
        """The customer portal is the shop's brand; an RS Systems icon on a
        fleet manager's phone is the platform leaking onto a shop's customer."""
        root = Path(settings.BASE_DIR) / 'templates'
        for name in ('includes/head_assets.html', 'customer_portal/base_customer.html',
                     'saas/base_public.html', 'landing.html'):
            self.assertNotIn('app_install_head', (root / name).read_text(), name)


class StaySignedInTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_owner()

    def _login(self, **extra):
        return self.client.post(reverse('login'), {
            'email': 'owner@install.test', 'password': PASSWORD, **extra,
        })

    def _row(self):
        return Session.objects.get(session_key=self.client.session.session_key)

    def test_ticked_box_lasts_ninety_days(self):
        self.assertEqual(settings.REMEMBER_ME_SESSION_AGE, NINETY_DAYS)
        response = self._login(remember_me='on')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get_expiry_age(), NINETY_DAYS)
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['max-age'], NINETY_DAYS)

    def test_unticked_box_ends_with_the_browser(self):
        """The shared shop computer."""
        response = self._login()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['max-age'], '')

    def test_a_visit_pushes_the_deadline_out(self):
        """The whole point: 90 days from the last visit, not from the login."""
        self._login(remember_me='on')
        # Eighty days later: the row is ten days from expiring.
        session = self.client.session
        session[STAMP_KEY] = (timezone.now().date() - timedelta(days=80)).isoformat()
        session.save()
        nearly_out = timezone.now() + timedelta(days=10)
        Session.objects.filter(session_key=session.session_key).update(expire_date=nearly_out)

        response = self.client.get(reverse('owner_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertGreater(self._row().expire_date, timezone.now() + timedelta(days=89))
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['max-age'], NINETY_DAYS)

    def test_second_visit_the_same_day_writes_nothing(self):
        self._login(remember_me='on')
        self.client.get(reverse('owner_dashboard'))
        response = self.client.get(reverse('owner_dashboard'))
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_browser_length_session_is_left_alone(self):
        self._login()
        self.client.get(reverse('owner_dashboard'))
        self.assertNotIn(STAMP_KEY, self.client.session)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_anonymous_visit_starts_no_session(self):
        self.client.logout()
        response = self.client.get(reverse('login'))
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
