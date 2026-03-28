"""
CODE-216 Regression: handle_batch_repair_request() stripped available_rewards on error.

Mirrors the same bug fixed for handle_single_repair_request() in CODE-211.
When handle_batch_repair_request() hit a validation error (no units_data,
empty units list, no technicians available, or JSON parse error), it called
render() with NO context dict, so the template received available_rewards=None.
The reward selection UI disappeared on form re-render.

Root cause: handle_batch_repair_request(request, customer) wasn't receiving
customer_user, so it couldn't call _get_available_monetary_rewards(). The
caller (request_repair) had customer_user but only passed customer to the
batch handler.

Fix (CODE-216):
1. Added customer_user=None parameter to handle_batch_repair_request().
2. Updated call site in request_repair() to pass customer_user.
3. Pre-computed _rewards_ctx at the top of the handler.
4. All 5 render() error paths now include _rewards_ctx.

Tests verify:
  1. Missing units_data: render() called with available_rewards in context.
  2. Empty units list: render() called with available_rewards in context.
  3. No technician available: render() called with available_rewards in context.
  4. JSON decode error: render() called with available_rewards in context.
  5. General exception: render() called with available_rewards in context.
  6. Customer_user=None: available_rewards defaults to [] safely.
  7. customer_user provided: _get_available_monetary_rewards is called.
  8. Call site passes customer_user: request_repair() passes customer_user to handler.
"""

import json
from urllib.parse import urlencode
from unittest.mock import patch, MagicMock, call
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse

from apps.customer_portal.views import handle_batch_repair_request
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.tenants.models import Tenant, SubscriptionPlan

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'STORAGES': {
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
    'STRIPE_SECRET_KEY': 'sk_test_dummy',
    'STRIPE_PUBLISHABLE_KEY': 'pk_test_dummy',
}


def _make_url_encoded_post(factory, path, data):
    """
    Build a POST request using application/x-www-form-urlencoded content type.

    Django's RequestFactory uses multipart/form-data for dict payloads by default.
    handle_batch_repair_request() checks `'multipart/form-data' in request.content_type`
    to detect AJAX requests — if that fires, it returns JSON instead of rendering the
    template.  URL-encoding avoids that false-positive.
    """
    encoded = urlencode(data)
    req = factory.post(path, encoded, content_type='application/x-www-form-urlencoded')
    req.session = SessionStore()
    req.session.create()
    req._messages = FallbackStorage(req)
    return req


@override_settings(**TEST_OVERRIDES)
class BatchRepairRewardsContextTest(TestCase):
    """CODE-216: handle_batch_repair_request() passes available_rewards on every error path."""

    @classmethod
    def setUpTestData(cls):
        SubscriptionPlan.objects.get_or_create(
            slug='test',
            defaults=dict(name='Test', monthly_price=0, annual_price=0,
                          max_repairs_per_month=100, max_technicians=5, max_customers=50),
        )
        cls.owner_user = User.objects.create_user('code216_owner', password='pw')
        cls.tenant = Tenant.objects.create(
            name='Test Shop 216', slug='test-shop-216', plan='test',
            owner=cls.owner_user,
        )
        cls.user = User.objects.create_user('code216_cust', password='pw')
        cls.customer = Customer.objects.create(
            name='Fleet Co 216', tenant=cls.tenant, email='fleet216@example.com'
        )
        cls.customer_user = CustomerUser.objects.create(
            user=cls.user, customer=cls.customer, is_primary_contact=True
        )
        cls.factory = RequestFactory()

    def _make_request(self, data):
        req = _make_url_encoded_post(self.factory, '/app/request-repair/', data)
        req.tenant = self.tenant
        req.user = self.user
        return req

    # ------------------------------------------------------------------
    # Helper: run the handler, intercept the render() call, inspect ctx
    # ------------------------------------------------------------------

    def _call_with_render_intercepted(self, request, customer, customer_user):
        """
        Patch django.shortcuts.render inside the views module to capture the
        context passed on error-path render() calls.

        Returns (render_context, render_was_called) tuple.
        """
        captured = {}

        def fake_render(req, template, context=None, **kw):
            captured['context'] = context or {}
            return HttpResponse(b'', status=200)

        with patch('apps.customer_portal.views.render', side_effect=fake_render):
            handle_batch_repair_request(request, customer, customer_user)

        return captured.get('context', None)

    # ------------------------------------------------------------------
    # Error-path tests
    # ------------------------------------------------------------------

    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    def test_missing_units_data_preserves_rewards(self, mock_rewards):
        """No units_data in POST → render() receives available_rewards key."""
        req = self._make_request({'batch_submission': 'true'})
        ctx = self._call_with_render_intercepted(req, self.customer, self.customer_user)
        self.assertIsNotNone(ctx, "render() should have been called")
        self.assertIn('available_rewards', ctx)

    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    def test_empty_units_list_preserves_rewards(self, mock_rewards):
        """Empty units_data JSON → render() receives available_rewards key."""
        req = self._make_request({
            'batch_submission': 'true',
            'units_data': json.dumps([]),
        })
        ctx = self._call_with_render_intercepted(req, self.customer, self.customer_user)
        self.assertIsNotNone(ctx, "render() should have been called")
        self.assertIn('available_rewards', ctx)

    @patch('apps.customer_portal.views.get_available_technician', return_value=None)
    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    def test_no_technician_preserves_rewards(self, mock_rewards, mock_tech):
        """No available technician → render() receives available_rewards key."""
        req = self._make_request({
            'batch_submission': 'true',
            'units_data': json.dumps([{'unitNumber': 'T-1', 'damageType': 'CHIP'}]),
        })
        ctx = self._call_with_render_intercepted(req, self.customer, self.customer_user)
        self.assertIsNotNone(ctx, "render() should have been called")
        self.assertIn('available_rewards', ctx)

    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    def test_invalid_json_preserves_rewards(self, mock_rewards):
        """Invalid JSON in units_data → render() receives available_rewards key."""
        req = self._make_request({
            'batch_submission': 'true',
            'units_data': 'not-valid-json{',
        })
        ctx = self._call_with_render_intercepted(req, self.customer, self.customer_user)
        self.assertIsNotNone(ctx, "render() should have been called")
        self.assertIn('available_rewards', ctx)

    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    @patch('apps.customer_portal.views.get_available_technician')
    def test_general_exception_preserves_rewards(self, mock_tech, mock_rewards):
        """Unexpected exception → render() receives available_rewards key."""
        mock_tech.side_effect = RuntimeError("unexpected boom")
        req = self._make_request({
            'batch_submission': 'true',
            'units_data': json.dumps([{'unitNumber': 'T-1', 'damageType': 'CHIP'}]),
        })
        ctx = self._call_with_render_intercepted(req, self.customer, self.customer_user)
        self.assertIsNotNone(ctx, "render() should have been called")
        self.assertIn('available_rewards', ctx)

    # ------------------------------------------------------------------
    # Null-safety and call-site tests
    # ------------------------------------------------------------------

    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    def test_customer_user_none_defaults_to_empty_rewards(self, mock_rewards):
        """customer_user=None → available_rewards defaults to [] without error."""
        req = self._make_request({'batch_submission': 'true'})
        ctx = self._call_with_render_intercepted(req, self.customer, customer_user=None)
        self.assertIsNotNone(ctx, "render() should have been called")
        self.assertIn('available_rewards', ctx)
        self.assertEqual(ctx['available_rewards'], [])
        # _get_available_monetary_rewards must NOT be called when customer_user is None
        mock_rewards.assert_not_called()

    @patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=[])
    def test_rewards_fn_called_with_customer_user(self, mock_rewards):
        """customer_user provided → _get_available_monetary_rewards called with it."""
        req = self._make_request({'batch_submission': 'true'})
        self._call_with_render_intercepted(req, self.customer, self.customer_user)
        mock_rewards.assert_called_once_with(self.customer_user)

    @patch('apps.customer_portal.views.handle_batch_repair_request')
    @patch('apps.customer_portal.views._get_customer_user_for_tenant')
    def test_call_site_passes_customer_user(self, mock_get_cu, mock_batch_handler):
        """
        request_repair() call site passes customer_user to handle_batch_repair_request().

        This is the call-site fix: before CODE-216, request_repair() called
        handle_batch_repair_request(request, customer) without customer_user.
        After the fix, it calls handle_batch_repair_request(request, customer, customer_user).
        """
        from apps.customer_portal.views import request_repair

        # Set up fake customer_user
        mock_batch_handler.return_value = HttpResponse(b'ok')
        fake_cu = MagicMock()
        fake_cu.customer = self.customer
        mock_get_cu.return_value = fake_cu

        req = self._make_request({'batch_submission': 'true'})
        req.method = 'POST'

        request_repair(req)

        # Verify customer_user was passed as the third argument
        self.assertTrue(mock_batch_handler.called, "handle_batch_repair_request should be called")
        args, kwargs = mock_batch_handler.call_args
        # call: handle_batch_repair_request(request, customer, customer_user)
        self.assertEqual(len(args), 3, "Should be called with 3 positional args: request, customer, customer_user")
        self.assertEqual(args[2], fake_cu, "Third arg should be customer_user")
