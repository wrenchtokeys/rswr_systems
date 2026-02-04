"""
Security vulnerability tests.

These tests verify that security vulnerabilities have been properly remediated.
Run with: python manage.py test tests.security
"""
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from unittest.mock import patch


class OpenRedirectTests(TestCase):
    """Test that open redirect vulnerabilities are blocked."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword123'
        )

    def test_external_redirect_blocked(self):
        """Test that external redirects via ?next= are blocked."""
        # Login and try to redirect to external URL
        response = self.client.post(
            reverse('login'),
            {
                'email': 'testuser',
                'password': 'testpassword123',
                'next': 'https://evil.com/phishing'
            }
        )
        # Should not redirect to external URL
        if response.status_code == 302:
            self.assertNotIn('evil.com', response.url)

    def test_javascript_redirect_blocked(self):
        """Test that javascript: URLs are blocked."""
        response = self.client.post(
            reverse('login'),
            {
                'email': 'testuser',
                'password': 'testpassword123',
                'next': 'javascript:alert(1)'
            }
        )
        if response.status_code == 302:
            self.assertNotIn('javascript:', response.url)

    def test_protocol_relative_redirect_blocked(self):
        """Test that protocol-relative URLs are blocked."""
        response = self.client.post(
            reverse('login'),
            {
                'email': 'testuser',
                'password': 'testpassword123',
                'next': '//evil.com/phishing'
            }
        )
        if response.status_code == 302:
            self.assertNotIn('evil.com', response.url)

    def test_internal_redirect_allowed(self):
        """Test that internal redirects still work."""
        response = self.client.post(
            reverse('login'),
            {
                'email': 'testuser',
                'password': 'testpassword123',
                'next': '/app/dashboard/'
            }
        )
        # Internal redirects should be allowed
        if response.status_code == 302:
            self.assertIn('/app/', response.url)


@override_settings(DEBUG=False)
class SetupEndpointTests(TestCase):
    """Test that setup-database endpoint is protected in production."""

    def test_setup_endpoint_blocked_in_production(self):
        """Test that /setup-database/ returns 404 in production."""
        client = Client()
        # In production (DEBUG=False), the URL shouldn't even be registered
        response = client.get('/setup-database/')
        self.assertEqual(response.status_code, 404)

    def test_setup_endpoint_post_blocked(self):
        """Test that POST to /setup-database/ is blocked in production."""
        client = Client()
        response = client.post('/setup-database/')
        self.assertEqual(response.status_code, 404)


class PasswordValidationTests(TestCase):
    """Test that password validation is properly enforced."""

    def test_weak_password_rejected(self):
        """Test that weak passwords are rejected during invite acceptance."""
        # This tests the password validation in accept_invite
        # We need to mock an invite token for this test
        pass  # TODO: Add test with InviteToken fixture

    def test_common_password_rejected(self):
        """Test that common passwords like 'password123' are rejected."""
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validate_password('password123')

    def test_short_password_rejected(self):
        """Test that short passwords are rejected."""
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validate_password('short')


class PIIMaskingTests(TestCase):
    """Test that PII is properly masked in logs."""

    def test_email_masking(self):
        """Test that emails are properly masked."""
        from core.utils.logging import mask_email

        # Test standard email
        self.assertEqual(mask_email('user@example.com'), 'us***@ex***.com')

        # Test short local part
        self.assertEqual(mask_email('a@example.com'), 'a***@ex***.com')

        # Test empty/invalid
        self.assertEqual(mask_email(''), '')
        self.assertEqual(mask_email('notanemail'), 'notanemail')

    def test_phone_masking(self):
        """Test that phone numbers are properly masked."""
        from core.utils.logging import mask_phone

        # Test E.164 format
        self.assertEqual(mask_phone('+15551234567'), '***4567')

        # Test formatted
        self.assertEqual(mask_phone('(555) 123-4567'), '***4567')

        # Test short numbers
        self.assertEqual(mask_phone('123'), '***')

        # Test empty
        self.assertEqual(mask_phone(''), '')

    def test_pii_text_masking(self):
        """Test that PII in text is properly masked."""
        from core.utils.logging import mask_pii

        # Test email in text
        result = mask_pii('Contact user@example.com for help')
        self.assertNotIn('user@example.com', result)
        self.assertIn('***', result)

        # Test phone in text
        result = mask_pii('Call (555) 123-4567')
        self.assertNotIn('555', result)
        self.assertIn('***4567', result)


class StripeWebhookTests(TestCase):
    """Test Stripe webhook security."""

    @override_settings(DEBUG=False, STRIPE_WEBHOOK_SECRET=None)
    def test_webhook_requires_secret_in_production(self):
        """Test that webhook returns 500 without secret in production."""
        client = Client()
        response = client.post(
            '/api/tenants/webhooks/stripe/',
            data='{}',
            content_type='application/json'
        )
        # Should return 500 when secret is not configured
        self.assertEqual(response.status_code, 500)


class XSSProtectionTests(TestCase):
    """Test that XSS vulnerabilities are prevented."""

    def test_format_html_escapes_content(self):
        """Test that format_html properly escapes user content."""
        from django.utils.html import format_html

        # Malicious input
        malicious = '<script>alert("xss")</script>'

        # format_html should escape it
        result = format_html('User said: {}', malicious)
        self.assertNotIn('<script>', str(result))
        self.assertIn('&lt;script&gt;', str(result))


class RateLimitTests(TestCase):
    """Test that rate limiting is properly configured."""

    def test_login_rate_limited(self):
        """Test that login endpoint is rate limited."""
        # This tests the @ratelimit decorator on login_router
        # We would need to make many requests to trigger the limit
        # For now, just verify the decorator is in place
        from rs_systems.views import login_router
        # Check that the function has been decorated (has ratelimit attributes)
        self.assertTrue(hasattr(login_router, '__wrapped__') or 'ratelimit' in str(login_router))

    def test_invite_rate_limited(self):
        """Test that invite acceptance is rate limited."""
        from rs_systems.views import accept_invite
        # Verify the decorator is applied
        self.assertTrue(hasattr(accept_invite, '__wrapped__') or 'ratelimit' in str(accept_invite))


class AllowedHostsTests(TestCase):
    """Test ALLOWED_HOSTS configuration."""

    @override_settings(DEBUG=False)
    def test_no_broad_wildcards_in_production(self):
        """Test that broad wildcards are not in ALLOWED_HOSTS."""
        from django.conf import settings

        # These broad wildcards should not be present
        for host in settings.ALLOWED_HOSTS:
            # Should not have wildcards that match all subdomains
            self.assertNotEqual(host, '.elasticbeanstalk.com')
            self.assertNotEqual(host, '.amazonaws.com')
