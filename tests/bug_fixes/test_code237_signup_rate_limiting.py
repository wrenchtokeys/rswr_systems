"""
CODE-237 — Rate limiting on signup and resend-confirmation endpoints + URL routing fix.

Bugs found:
1. resend_confirmation_email was a public GET endpoint with no rate limiting.
   Since uidb64 is just base64(user_pk) — sequential integers — an attacker could
   enumerate all PKs and trigger unlimited confirmation emails, exhausting the
   SendGrid quota (50k/month) and email-bombing inactive users.

2. signup_view POST was also unprotected (Turnstile is disabled in dev/CI).

3. URL ROUTING BUG: The resend URL pattern came AFTER the confirm-email token
   pattern in urls.py. Since <str:token> matched "resend", the resend endpoint
   was completely unreachable — clicking "Send a New Confirmation Email" on the
   expired-link page actually hit the confirm view with token="resend", which
   always showed the invalid-token page. New owners with expired links had NO
   way to get a new confirmation email.

Fix:
- Added @ratelimit decorators to both endpoints
- Swapped URL pattern order so resend comes before the token pattern
"""

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.tenants.models import Tenant, TenantMembership


LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCMEM_CACHE)
class ResendConfirmationBasicTest(TestCase):
    """Verify resend_confirmation_email basic functionality (URL routing fix)."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='inactive_owner',
            email='inactive@example.com',
            password='TestPass123!',
            is_active=False,
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop', slug='test-shop', owner=self.user,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner',
        )
        self.uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.url = reverse('resend_confirmation_email', kwargs={'uidb64': self.uidb64})

    def tearDown(self):
        cache.clear()

    def test_resend_returns_200_for_inactive_user(self):
        """Basic functionality: resend works for inactive users."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'inactive@example.com')

    def test_resend_rejects_active_user(self):
        """Active users can't trigger resend."""
        self.user.is_active = True
        self.user.save()
        resp = self.client.get(self.url, follow=True)
        self.assertRedirects(resp, reverse('signup'))

    def test_resend_rejects_invalid_uidb64(self):
        """Invalid uidb64 redirects to signup."""
        url = reverse('resend_confirmation_email', kwargs={'uidb64': 'INVALID'})
        resp = self.client.get(url, follow=True)
        self.assertRedirects(resp, reverse('signup'))

    def test_resend_rejects_nonexistent_user(self):
        """Non-existent user PK redirects to signup."""
        fake_uid = urlsafe_base64_encode(force_bytes(99999))
        url = reverse('resend_confirmation_email', kwargs={'uidb64': fake_uid})
        resp = self.client.get(url, follow=True)
        self.assertRedirects(resp, reverse('signup'))

    def test_url_routing_resend_not_captured_by_token_pattern(self):
        """Regression: resend URL must not be captured by confirm-email/<uidb64>/<token>/.

        Before CODE-237, the token pattern came first and matched 'resend' as a token,
        so the resend endpoint was completely unreachable.
        """
        url = reverse('resend_confirmation_email', kwargs={'uidb64': self.uidb64})
        self.assertIn('/resend/', url)
        resp = self.client.get(url)
        # Should reach the actual resend view (200 with confirmation page),
        # NOT the confirm view (which would show the invalid-token page)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.user.email)
        # Should NOT contain "Link Expired or Invalid" — that's the confirm view's error page
        self.assertNotContains(resp, 'Link Expired or Invalid')


@override_settings(CACHES=LOCMEM_CACHE, RATELIMIT_ENABLE=True)
class ResendConfirmationRateLimitTest(TestCase):
    """Verify resend_confirmation_email is rate-limited."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='inactive_owner_rl',
            email='inactive_rl@example.com',
            password='TestPass123!',
            is_active=False,
        )
        self.tenant = Tenant.objects.create(
            name='RL Shop', slug='rl-shop', owner=self.user,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner',
        )
        self.uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.url = reverse('resend_confirmation_email', kwargs={'uidb64': self.uidb64})

    def tearDown(self):
        cache.clear()

    def test_resend_is_rate_limited_after_3_requests(self):
        """After 3 resend requests from same IP, the 4th should be blocked (403)."""
        for i in range(3):
            resp = self.client.get(self.url)
            self.assertEqual(resp.status_code, 200, f"Request {i+1} should succeed")

        # 4th request should be rate-limited
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403, "4th request should be rate-limited")


@override_settings(CACHES=LOCMEM_CACHE, RATELIMIT_ENABLE=True)
class SignupRateLimitTest(TestCase):
    """Verify signup_view POST is rate-limited."""

    def setUp(self):
        cache.clear()
        self.url = reverse('signup')

    def tearDown(self):
        cache.clear()

    def test_signup_post_is_rate_limited_after_5_requests(self):
        """After 5 signup POST requests from same IP, the 6th should be blocked."""
        for i in range(5):
            resp = self.client.post(self.url, {
                'business_name': f'Shop {i}',
                'email': f'user{i}@example.com',
                'first_name': 'Test',
                'last_name': 'User',
                'password': 'TestPass123!',
                'password_confirm': 'TestPass123!',
            })
            # May succeed or show form errors — but should not be 403
            self.assertNotEqual(resp.status_code, 403, f"Request {i+1} should not be rate-limited")

        # 6th should be blocked
        resp = self.client.post(self.url, {
            'business_name': 'Shop 6',
            'email': 'user6@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'TestPass123!',
            'password_confirm': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, 403, "6th POST request should be rate-limited")

    def test_signup_get_is_not_rate_limited(self):
        """GET requests to signup should never be rate-limited (only POST is decorated)."""
        for _ in range(10):
            resp = self.client.get(self.url)
            self.assertEqual(resp.status_code, 200)

    def test_signup_authenticated_user_redirected(self):
        """Already-logged-in users skip signup entirely."""
        user = User.objects.create_user(username='existing', password='pass123')
        self.client.login(username='existing', password='pass123')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)


@override_settings(CACHES=LOCMEM_CACHE, RATELIMIT_ENABLE=True)
class EnumerationResistanceTest(TestCase):
    """Verify sequential PK enumeration can't mass-trigger emails."""

    def setUp(self):
        cache.clear()
        self.users = []
        for i in range(5):
            user = User.objects.create_user(
                username=f'enum_user_{i}',
                email=f'enum{i}@example.com',
                password='TestPass123!',
                is_active=False,
            )
            tenant = Tenant.objects.create(
                name=f'Enum Shop {i}', slug=f'enum-shop-{i}', owner=user,
            )
            TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
            self.users.append(user)

    def tearDown(self):
        cache.clear()

    def test_enumerating_pks_hits_rate_limit(self):
        """Cycling through different uidb64 values still uses same IP, so rate limit applies."""
        responses = []
        for user in self.users:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            url = reverse('resend_confirmation_email', kwargs={'uidb64': uidb64})
            resp = self.client.get(url)
            responses.append(resp.status_code)

        # First 3 should succeed (200), rest should be rate-limited (403)
        successes = [r for r in responses if r == 200]
        blocked = [r for r in responses if r == 403]
        self.assertLessEqual(len(successes), 3, "At most 3 resends should succeed per hour per IP")
        self.assertGreaterEqual(len(blocked), 2, "At least 2 should be rate-limited")
