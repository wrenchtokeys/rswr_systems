"""
CODE-224: accept_invite view lacked @ratelimit decorator.

Bug: The accept_invite view used getattr(request, 'limited', False) to check
rate limiting, but had no @ratelimit decorator or middleware to actually set
request.limited. The check was dead code — request.limited was never True.
Meanwhile, the security test suite (test_vulnerabilities.py) explicitly
verified that accept_invite has a @ratelimit decorator (via __wrapped__
attribute check), and was failing.

Fix: Added @ratelimit(key='ip', rate='20/h', method='POST', block=False) to
accept_invite, making the existing request.limited guard functional and fixing
the failing security test.

The invite token is a UUID (cryptographically unpredictable), so brute force
was not a practical exploit — but rate limiting is still correct defense-in-
depth and aligns the implementation with the test contract.
"""

from django.test import TestCase


class AcceptInviteRateLimitDecoratorTest(TestCase):
    """Verify @ratelimit is applied to accept_invite."""

    def test_accept_invite_has_ratelimit_decorator(self):
        """accept_invite must have @ratelimit so request.limited is functional."""
        from rs_systems.views import accept_invite
        # @ratelimit wraps the function and sets __wrapped__
        self.assertTrue(
            hasattr(accept_invite, '__wrapped__'),
            "accept_invite must be decorated with @ratelimit. "
            "Without it, the getattr(request, 'limited', False) guard is dead code."
        )

    def test_get_request_renders_invite_form(self):
        """GET /invite/<token>/ should render the invite form (not crash)."""
        import uuid
        from django.test import Client
        client = Client()
        # Non-existent token: expect a rendered invalid-invite page (not 500)
        response = client.get(f'/invite/{uuid.uuid4()}/')
        self.assertIn(response.status_code, [200, 302])
