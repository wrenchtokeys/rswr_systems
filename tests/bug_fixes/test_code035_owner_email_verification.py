"""
CODE-035 Regression: Broken shop-owner email verification link.

Before fix:
  _send_verification_email() in saas/views.py sent shop owners a link to
  `customer_confirm_email_verification` — a customer-portal-only view that
  does `CustomerUser.objects.get(user=user)`.  For shop owners (who are never
  CustomerUsers) this always raised CustomerUser.DoesNotExist, producing:

      "Customer profile not found."

  ... and redirecting the owner to the customer portal login page.

After fix:
  The CustomerUser.DoesNotExist branch now builds a URL to the new
  `owner_confirm_email_verification` view (in saas/views.py), which:
    - Validates the token
    - Shows a success message on a valid token
    - Shows an error message on an invalid/expired token
    - Redirects to owner_dashboard when authenticated, signup otherwise

Tests verify:
  1. Valid token → 302 redirect to owner_dashboard + success message
  2. Invalid token → 302 redirect + error message (no 500)
  3. Tampered UID → 302 redirect + error message (no 500)
  4. Unauthenticated user with valid token → 302 to signup (not customer login)
  5. _send_verification_email() for a non-CustomerUser sends URL containing
     'verify-email' (owner endpoint) not 'customer/verify-email'
  6. _send_verification_email() for a CustomerUser still sends the customer URL
"""

from django.test import TestCase, Client, RequestFactory, override_settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from unittest.mock import patch, MagicMock
import uuid

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def _make_owner(suffix=''):
    """Create a shop owner user + tenant."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name='Test Plan',
        defaults={'stripe_price_id': 'price_test', 'monthly_price': '0.00',
                  'annual_price': '0.00', 'max_technicians': 5,
                  'max_repairs_per_month': 100}
    )
    user = User.objects.create_user(
        username=f'owner_{suffix}_{uuid.uuid4().hex[:6]}',
        email=f'owner{suffix}@example.com',
        password='testpass123',
    )
    tenant = Tenant.objects.create(
        name=f'Test Shop {suffix}',
        slug=f'test-shop-{suffix}-{uuid.uuid4().hex[:6]}',
        plan=plan,
        owner=user,
        is_active=True,
    )
    TenantMembership.objects.create(
        user=user, tenant=tenant, role='owner', is_active=True
    )
    return user, tenant


def _make_link(user):
    """Build a valid verification UID+token pair."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return uid, token


@override_settings(**TEST_OVERRIDES)
class OwnerEmailVerificationViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = _make_owner('a')

    def _url(self, uidb64, token):
        return reverse('owner_confirm_email_verification',
                       kwargs={'uidb64': uidb64, 'token': token})

    # ------------------------------------------------------------------
    # 1. Valid token, authenticated owner → success + redirect to dashboard
    # ------------------------------------------------------------------
    def test_valid_token_authenticated_redirects_to_dashboard(self):
        self.client.force_login(self.user)
        # Generate token AFTER login so last_login is already updated
        uid, token = _make_link(self.user)
        resp = self.client.get(self._url(uid, token))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('owner_dashboard'), resp['Location'])
        # Check for success flash message
        messages = list(resp.wsgi_request._messages)
        self.assertTrue(
            any('verified' in str(m).lower() for m in messages),
            f"Expected success message, got: {messages}"
        )

    # ------------------------------------------------------------------
    # 2. Invalid token → error message, no 500
    # ------------------------------------------------------------------
    def test_invalid_token_shows_error(self):
        uid, _ = _make_link(self.user)
        bad_token = 'invalid-token-xyz'
        self.client.force_login(self.user)
        resp = self.client.get(self._url(uid, bad_token))
        self.assertEqual(resp.status_code, 302)
        messages = list(resp.wsgi_request._messages)
        self.assertTrue(
            any('invalid' in str(m).lower() or 'expired' in str(m).lower() for m in messages),
            f"Expected error message, got: {messages}"
        )

    # ------------------------------------------------------------------
    # 3. Tampered UID → error message, no 500
    # ------------------------------------------------------------------
    def test_tampered_uid_shows_error(self):
        _, token = _make_link(self.user)
        bad_uid = 'aW52YWxpZA'  # base64 for "invalid"
        self.client.force_login(self.user)
        resp = self.client.get(self._url(bad_uid, token))
        self.assertEqual(resp.status_code, 302)
        messages = list(resp.wsgi_request._messages)
        self.assertTrue(
            any('invalid' in str(m).lower() or 'expired' in str(m).lower() for m in messages),
            f"Expected error message, got: {messages}"
        )

    # ------------------------------------------------------------------
    # 4. Unauthenticated user with valid token → redirect to signup (NOT customer login)
    # ------------------------------------------------------------------
    def test_valid_token_unauthenticated_redirects_to_signup(self):
        uid, token = _make_link(self.user)
        # Do NOT log in
        resp = self.client.get(self._url(uid, token))
        self.assertEqual(resp.status_code, 302)
        location = resp['Location']
        self.assertIn(reverse('signup'), location)
        # Crucially: must NOT redirect to customer login
        self.assertNotIn('customer', location)

    # ------------------------------------------------------------------
    # 5. _send_verification_email sends owner URL for non-CustomerUser
    # ------------------------------------------------------------------
    def test_send_verification_email_uses_owner_url_for_shop_owner(self):
        from apps.saas.views import _send_verification_email
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/')
        request.META['SERVER_NAME'] = 'testserver'
        request.META['SERVER_PORT'] = '80'

        sent_urls = []

        def fake_send_mail(subject, message, from_email, recipient_list, fail_silently=False):
            sent_urls.append(message)

        with patch('apps.saas.views.send_mail', side_effect=fake_send_mail):
            _send_verification_email(request, self.user)

        self.assertEqual(len(sent_urls), 1, "Expected exactly one email sent")
        body = sent_urls[0]
        # Should contain the owner verification path, not the customer one
        self.assertIn('verify-email', body)
        self.assertNotIn('customer/verify-email', body)

    # ------------------------------------------------------------------
    # 6. _send_verification_email still sends customer URL for CustomerUser
    # ------------------------------------------------------------------
    def test_send_verification_email_uses_customer_url_for_customer_user(self):
        from apps.saas.views import _send_verification_email
        from apps.customer_portal.models import CustomerUser
        from core.models import Customer
        from django.test import RequestFactory

        # Create a CustomerUser
        customer_owner_user = User.objects.create_user(
            username=f'cu_{uuid.uuid4().hex[:6]}',
            email='cu@example.com',
            password='testpass123',
        )
        customer = Customer.objects.create(
            name='Test Customer',
            tenant=self.tenant,
        )
        CustomerUser.objects.create(
            user=customer_owner_user,
            customer=customer,
            is_primary_contact=True,
        )

        factory = RequestFactory()
        request = factory.get('/')
        request.META['SERVER_NAME'] = 'testserver'
        request.META['SERVER_PORT'] = '80'

        sent_urls = []

        def fake_send_mail(subject, message, from_email, recipient_list, fail_silently=False):
            sent_urls.append(message)

        with patch('apps.saas.views.send_mail', side_effect=fake_send_mail):
            _send_verification_email(request, customer_owner_user)

        self.assertEqual(len(sent_urls), 1)
        body = sent_urls[0]
        # Customer verification URL lives under /app/verify-email/...
        self.assertIn('/app/verify-email/', body)
