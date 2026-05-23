"""
CODE-211 Regression: handle_single_repair_request() stripped available_rewards on error.

When handle_single_repair_request() hit a validation error (missing unit number,
bad photo, or no technicians available) it called render() with NO context dict,
so the template received available_rewards=None.  Any reward selection UI the
customer had been looking at disappeared on form re-render.  Customers who had
pre-selected a reward would land back on a blank form with their selection gone.

Root cause: The helper was called from request_repair() which fetched rewards
before the POST branch.  But handle_single_repair_request() rendered its own
error responses without forwarding those rewards.  Added in CODE-210.

Fix (CODE-211): Pre-compute _rewards_ctx at the top of handle_single_repair_request()
and include it in every render() error path:

    _rewards_ctx = {
        'available_rewards': _get_available_monetary_rewards(customer_user) if customer_user else [],
    }

Tests verify:
  1. Missing unit_number error: available_rewards present in response context.
  2. No-technician error: available_rewards present in response context.
  3. Invalid photo: available_rewards present in response context.
  4. Success path (redirect): no context check needed (normal redirect).
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore

from apps.customer_portal.views import handle_single_repair_request
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


def _make_post_request(factory, path, data, files=None):
    """Build a POST request with messages middleware attached."""
    if files:
        req = factory.post(path, dict(**data, **files))
    else:
        req = factory.post(path, data)
    # Attach session + message storage (required by messages framework)
    req.session = SessionStore()
    req.session.create()
    messages = FallbackStorage(req)
    req._messages = messages
    return req


@override_settings(**TEST_OVERRIDES)
class TestCode211RepairRequestRewardsContext(TestCase):
    """Reward context is preserved on all error paths in handle_single_repair_request."""

    def setUp(self):
        self.factory = RequestFactory()
        plan, _ = SubscriptionPlan.objects.get_or_create(
            name='Starter',
            defaults={'stripe_price_id': 'price_test', 'monthly_price': 49, 'max_customers': 50},
        )
        # Tenant.owner is required — create the owner user first via a placeholder
        # then update the tenant after (avoids circular dependency in setUp).
        placeholder_owner = User.objects.create_user('tenantowner211', 'to211@example.com', 'pass')
        self.tenant = Tenant.objects.create(
            name='Repair Co',
            slug='repair-co',
            subscription_plan=plan,
            owner=placeholder_owner,
        )
        self.owner = User.objects.create_user('owner211', 'owner211@example.com', 'pass')
        self.user = User.objects.create_user('custuser211', 'cu211@example.com', 'pass')
        self.customer = Customer.objects.create(
            name='Fleet Co',
            tenant=self.tenant,
            email='fleet@fleet.co',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer,
            is_primary_contact=True,
        )

    def _fake_rewards(self):
        """Return a MagicMock that looks like a queryset with one item."""
        reward = MagicMock()
        reward.id = 99
        reward.reward_option.name = 'Free Repair'
        qs = MagicMock()
        qs.__iter__ = lambda s: iter([reward])
        qs.__bool__ = lambda s: True
        return qs

    def test_missing_unit_number_preserves_rewards_via_render_context(self):
        """Error: missing unit_number — render() was called with _rewards_ctx."""
        req = _make_post_request(self.factory, '/repair/request/', {
            'unit_number': '',
        })
        req.tenant = self.tenant

        fake_rewards = self._fake_rewards()
        render_calls = []

        def fake_render(request, template, context=None, *args, **kwargs):
            render_calls.append(context or {})
            from django.http import HttpResponse
            return HttpResponse('ok')

        with patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=fake_rewards), \
             patch('apps.customer_portal.views.render', side_effect=fake_render):
            handle_single_repair_request(req, self.customer, self.customer_user)

        self.assertEqual(len(render_calls), 1, "Expected exactly one render() call on validation error")
        ctx = render_calls[0]
        self.assertIn('available_rewards', ctx, "available_rewards must be in render context on error")
        self.assertEqual(ctx['available_rewards'], fake_rewards)

    def test_no_technician_error_preserves_rewards(self):
        """Error: no available technician — render() called with available_rewards."""
        req = _make_post_request(self.factory, '/repair/request/', {
            'unit_number': 'UNIT-999',
        })
        req.tenant = self.tenant

        fake_rewards = self._fake_rewards()
        render_calls = []

        def fake_render(request, template, context=None, *args, **kwargs):
            render_calls.append(context or {})
            from django.http import HttpResponse
            return HttpResponse('ok')

        with patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=fake_rewards), \
             patch('apps.customer_portal.views.get_available_technician', return_value=None), \
             patch('apps.customer_portal.views.render', side_effect=fake_render):
            handle_single_repair_request(req, self.customer, self.customer_user)

        self.assertEqual(len(render_calls), 1)
        ctx = render_calls[0]
        self.assertIn('available_rewards', ctx)
        self.assertEqual(ctx['available_rewards'], fake_rewards)

    def test_invalid_photo_preserves_rewards(self):
        """Error: invalid photo type — render() called with available_rewards."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad_photo = SimpleUploadedFile('bad.txt', b'not an image', content_type='text/plain')

        req = _make_post_request(
            self.factory,
            '/repair/request/',
            {'unit_number': 'UNIT-001'},
            files={'damage_photo_before': bad_photo},
        )
        req.tenant = self.tenant

        fake_rewards = self._fake_rewards()
        render_calls = []

        def fake_render(request, template, context=None, *args, **kwargs):
            render_calls.append(context or {})
            from django.http import HttpResponse
            return HttpResponse('ok')

        with patch('apps.customer_portal.views._get_available_monetary_rewards', return_value=fake_rewards), \
             patch('apps.customer_portal.views.validate_repair_photo', return_value=(False, 'Bad file type')), \
             patch('apps.customer_portal.views.render', side_effect=fake_render):
            handle_single_repair_request(req, self.customer, self.customer_user)

        self.assertEqual(len(render_calls), 1)
        ctx = render_calls[0]
        self.assertIn('available_rewards', ctx)
        self.assertEqual(ctx['available_rewards'], fake_rewards)

    def test_no_customer_user_gets_empty_rewards(self):
        """When customer_user is None, available_rewards defaults to empty list (no crash)."""
        req = _make_post_request(self.factory, '/repair/request/', {
            'unit_number': '',  # trigger the first error path
        })
        req.tenant = self.tenant

        render_calls = []

        def fake_render(request, template, context=None, *args, **kwargs):
            render_calls.append(context or {})
            from django.http import HttpResponse
            return HttpResponse('ok')

        with patch('apps.customer_portal.views.render', side_effect=fake_render):
            # Pass customer_user=None — simulates edge case where profile was
            # retrieved via customer but customer_user is unavailable.
            handle_single_repair_request(req, self.customer, customer_user=None)

        self.assertEqual(len(render_calls), 1)
        ctx = render_calls[0]
        self.assertIn('available_rewards', ctx)
        # Should be an empty list, not None or a missing key
        self.assertEqual(ctx['available_rewards'], [])
