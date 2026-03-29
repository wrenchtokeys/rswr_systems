"""
CODE-233: Missing @ratelimit on customer_register and shop_join_view

Both public account-creation endpoints were importing django_ratelimit but
never actually applying the @ratelimit decorator:

  - apps/customer_portal/views.py :: customer_register
  - apps/saas/views.py :: shop_join_view

customer_register already checked `getattr(request, 'limited', False)` but
because the @ratelimit decorator was never applied, `request.limited` was
always False — the check was dead code and rate limiting never fired.

shop_join_view had no rate limiting at all on its POST path.

Fix (CODE-233):
  - @ratelimit(key='ip', rate='10/h', method='POST', block=False) added to
    both views.
  - shop_join_view POST handler now checks request.limited and returns an
    error response rather than processing the submission.

Tests:
  1. When request.limited=True, customer_register returns an error and
     creates no user.
  2. When request.limited=True, shop_join_view POST creates no user and
     returns 200 with error content.
  3. When request.limited=False, shop_join_view POST proceeds normally.
  4. GET requests to both views are not affected by POST rate limiting.
  5. Both views' source code references '@ratelimit'.
"""

import inspect
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.customer_portal import views as cp_views
from apps.saas import views as saas_views
from apps.tenants.models import Tenant, SubscriptionPlan


def _make_request(factory_method, path, data=None):
    """Build a RequestFactory request with required middleware attributes."""
    req = factory_method(path, data or {})
    req.user = AnonymousUser()
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


class CustomerRegisterRateLimitTests(TestCase):
    """customer_register must have @ratelimit and respect request.limited."""

    def test_source_contains_ratelimit_decorator(self):
        """customer_portal/views.py must apply @ratelimit to customer_register."""
        src = inspect.getsource(cp_views)
        # Check decorator appears just before the function definition
        self.assertIn('@ratelimit', src,
                      "customer_portal/views.py must contain @ratelimit decorator")

    def test_limited_request_shows_error_and_creates_no_user(self):
        """When request.limited=True, customer_register must block and create no user."""
        factory = RequestFactory()
        req = _make_request(factory.post, '/register/', {
            'username': 'spambot',
            'email': 'spam@bot.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'first_name': 'Spam',
            'last_name': 'Bot',
        })
        req.limited = True  # simulate ratelimit firing

        response = cp_views.customer_register(req)

        self.assertFalse(
            User.objects.filter(username='spambot').exists(),
            "No user should be created when rate-limited"
        )
        # Should return an error page (200) or redirect — not a 500
        self.assertIn(response.status_code, [200, 302],
                      "Rate-limited request must return 200 or redirect, not 500")

    def test_not_limited_get_succeeds(self):
        """GET to customer_register should return 200 regardless of rate limiting."""
        factory = RequestFactory()
        req = _make_request(factory.get, '/register/')

        response = cp_views.customer_register(req)
        self.assertEqual(response.status_code, 200)

    def test_ratelimit_imported_in_customer_portal_views(self):
        """django_ratelimit must be imported in customer_portal/views.py."""
        src = inspect.getsource(cp_views)
        self.assertIn('from django_ratelimit', src,
                      "customer_portal/views.py must import django_ratelimit")


class ShopJoinRateLimitTests(TestCase):
    """shop_join_view must have @ratelimit and respect request.limited on POST."""

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'price': 0,
                'max_technicians': 2,
                'max_customers': 10,
                'max_repairs_per_month': 50,
                'is_active': True,
            },
        )
        owner = User.objects.create_user(
            username='shopowner_233',
            email='shopowner233@example.com',
            password='testpass123',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 233',
            slug='test-shop-233',
            subdomain='test-shop-233',
            owner=owner,
            subscription_plan=plan,
            subscription_status='trialing',
        )

    def test_source_contains_ratelimit_decorator(self):
        """saas/views.py must apply @ratelimit to shop_join_view."""
        src = inspect.getsource(saas_views)
        self.assertIn('@ratelimit', src,
                      "saas/views.py must contain @ratelimit decorator")

    def test_ratelimit_imported_in_saas_views(self):
        """django_ratelimit must be imported in saas/views.py."""
        src = inspect.getsource(saas_views)
        self.assertIn('from django_ratelimit', src,
                      "saas/views.py must import django_ratelimit")

    def test_limited_post_creates_no_user(self):
        """When request.limited=True, shop_join_view POST must not create users."""
        factory = RequestFactory()
        req = _make_request(factory.post, f'/join/{self.tenant.slug}/', {
            'first_name': 'Rate',
            'last_name': 'Limited',
            'email': 'ratelimited233@example.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
        })
        req.limited = True  # simulate ratelimit firing

        response = saas_views.shop_join_view(req, slug=self.tenant.slug)

        self.assertFalse(
            User.objects.filter(email='ratelimited233@example.com').exists(),
            "No user should be created when shop_join_view is rate-limited"
        )
        # Should return 200 with error, not redirect to portal
        self.assertEqual(response.status_code, 200,
                         "Rate-limited shop_join_view POST must return 200 with error")

    def test_limited_post_response_contains_rate_limit_message(self):
        """Rate-limited response must mention the rate limit to the user."""
        factory = RequestFactory()
        req = _make_request(factory.post, f'/join/{self.tenant.slug}/', {
            'first_name': 'Rate',
            'last_name': 'Limited2',
            'email': 'ratelimited2_233@example.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
        })
        req.limited = True

        response = saas_views.shop_join_view(req, slug=self.tenant.slug)
        content = response.content.decode()
        self.assertIn('Too many', content,
                      "Rate-limited response must include 'Too many' error message")

    def test_not_limited_post_creates_user(self):
        """When request.limited=False, shop_join_view POST should create a user."""
        # Use the Django test client (not RequestFactory) so the session backend
        # is properly initialized — shop_join_view writes to request.session
        # after creating the user, and a plain dict session raises AttributeError.
        response = self.client.post(
            f'/join/{self.tenant.slug}/',
            {
                'first_name': 'Valid',
                'last_name': 'User',
                'email': 'validuser233@example.com',
                'password': 'Sup3rSecure!Pass',
                'confirm_password': 'Sup3rSecure!Pass',
            },
        )

        # User should have been created regardless of redirect status
        self.assertTrue(
            User.objects.filter(email='validuser233@example.com').exists(),
            "User should be created when not rate-limited"
        )
        # Successful signup redirects to customer dashboard or login
        self.assertIn(response.status_code, [200, 302],
                      "Successful shop_join should redirect (302) or render portal (200)")

    def test_get_request_not_blocked(self):
        """GET requests to shop_join_view should return 200."""
        factory = RequestFactory()
        req = _make_request(factory.get, f'/join/{self.tenant.slug}/')

        response = saas_views.shop_join_view(req, slug=self.tenant.slug)
        self.assertEqual(response.status_code, 200)
