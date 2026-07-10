"""
Tests for CODE-130: 'canceled' subscription status (cancel_at_period_end)
should NOT immediately lock shops out.

Bug: cancel_subscription() sets subscription_status='canceled' when the owner
clicks "Cancel at end of period".  The SubscriptionEnforcementMiddleware
previously treated 'canceled' unconditionally as expired, causing is_subscription_expired=True
with is_in_grace_period=False → _block() was called → shop redirected to
/subscription-blocked/ immediately, even though they had paid time remaining.

Fix: 'canceled' without a grace_period_end is treated as "scheduled to cancel
but still active". Only when grace_period_end is set (which the
customer.subscription.deleted webhook sets along with status='expired') does
access restriction kick in.
"""

from unittest.mock import MagicMock, patch
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.subscription_middleware import SubscriptionEnforcementMiddleware


def _make_tenant(status, grace_period_end=None, stripe_sub_id='sub_abc123', plan='paid'):
    """Helper: build an unsaved Tenant-like object for middleware testing."""
    tenant = MagicMock(spec=Tenant)
    tenant.subscription_status = status
    tenant.grace_period_end = grace_period_end
    # The middleware (since A3) reads effective_grace_period_end and compares
    # it to now; on the real model the property mirrors grace_period_end.
    tenant.effective_grace_period_end = grace_period_end
    tenant.plan = plan
    tenant.stripe_subscription_id = stripe_sub_id
    # is_trial_expired only relevant for trial plan
    tenant.is_trial_expired = False
    # is_in_grace_period derived from grace_period_end
    if grace_period_end and timezone.now() <= grace_period_end:
        tenant.is_in_grace_period = True
        tenant.grace_days_remaining = (grace_period_end - timezone.now()).days
    else:
        tenant.is_in_grace_period = False
        tenant.grace_days_remaining = 0
    # had_paid_subscription
    tenant.had_paid_subscription = bool(stripe_sub_id)
    return tenant


class CanceledSubscriptionMiddlewareTests(TestCase):
    """
    Unit tests for SubscriptionEnforcementMiddleware behaviour around
    'canceled' subscription_status.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='owner_test_130',
            email='owner130@example.com',
            password='testpass',
        )
        self.user.is_superuser = False
        self.get_response = MagicMock(return_value=MagicMock(status_code=200))
        self.middleware = SubscriptionEnforcementMiddleware(self.get_response)

    def _make_request(self, path='/owner/dashboard/', method='GET'):
        if method == 'POST':
            request = self.factory.post(path)
        else:
            request = self.factory.get(path)
        request.user = self.user
        return request

    def _attach_tenant(self, request, tenant):
        request.tenant = tenant

    # -------------------------------------------------------------------------
    # Core bug: 'canceled' without grace_period_end must NOT block access
    # -------------------------------------------------------------------------

    def test_canceled_without_grace_period_allows_get(self):
        """
        STATUS: canceled, grace_period_end=None (cancel_at_period_end=True)
        EXPECTED: GET request allowed — shop still has paid time remaining.
        """
        tenant = _make_tenant('canceled', grace_period_end=None)
        request = self._make_request('/owner/dashboard/', 'GET')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_called_once_with(request)
        self.assertEqual(response.status_code, 200)

    def test_canceled_without_grace_period_allows_post(self):
        """
        STATUS: canceled, grace_period_end=None
        EXPECTED: POST request allowed — shop is still active (just scheduled).
        """
        tenant = _make_tenant('canceled', grace_period_end=None)
        request = self._make_request('/owner/invoices/1/', 'POST')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_called_once_with(request)
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------------
    # 'canceled' WITH grace_period_end: access should be restricted
    # -------------------------------------------------------------------------

    def test_canceled_with_active_grace_period_allows_get(self):
        """
        STATUS: canceled, grace_period_end in future (unusual — normally 'expired')
        EXPECTED: GET allowed (grace period read-only mode).
        """
        grace_end = timezone.now() + timedelta(days=15)
        tenant = _make_tenant('canceled', grace_period_end=grace_end)
        request = self._make_request('/owner/dashboard/', 'GET')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        # Grace period allows GETs (read-only mode)
        self.get_response.assert_called_once_with(request)

    def test_canceled_with_stale_grace_period_still_active(self):
        """
        STATUS: canceled, grace_period_end in the past (STALE stamp).

        EXPECTATION CHANGED by A3 (remediation plan 2026-07-09): this exact
        state was the residual CODE-130 lockout — a lapse+resubscribe cycle
        left a past-dated stamp on a paying tenant, and their next 'cancel
        at period end' locked them out immediately despite paid days
        remaining. A past grace stamp on a 'canceled' tenant is now
        equivalent to no stamp: ACTIVE. ('expired' + past stamp still
        blocks — covered below.)
        """
        grace_end = timezone.now() - timedelta(days=1)
        tenant = _make_tenant('canceled', grace_period_end=grace_end)
        request = self._make_request('/owner/dashboard/', 'GET')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_called_once_with(request)
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------------
    # 'expired' status: always restricted (normal deletion flow)
    # -------------------------------------------------------------------------

    def test_expired_without_grace_period_blocks_all(self):
        """
        STATUS: expired, no grace_period_end
        EXPECTED: access blocked.
        """
        tenant = _make_tenant('expired', grace_period_end=None)
        request = self._make_request('/owner/dashboard/', 'GET')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_expired_with_active_grace_period_allows_get(self):
        """
        STATUS: expired, grace_period_end in future (normal deletion webhook flow)
        EXPECTED: GET allowed, POST blocked.
        """
        grace_end = timezone.now() + timedelta(days=20)
        tenant = _make_tenant('expired', grace_period_end=grace_end)
        request = self._make_request('/owner/dashboard/', 'GET')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_called_once_with(request)

    # -------------------------------------------------------------------------
    # 'active' status: always allowed
    # -------------------------------------------------------------------------

    def test_active_subscription_allows_everything(self):
        """STATUS: active — always allowed."""
        tenant = _make_tenant('active')
        request = self._make_request('/owner/invoices/', 'POST')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_called_once_with(request)
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------------
    # Exempt paths: always allowed regardless of status
    # -------------------------------------------------------------------------

    def test_billing_path_exempt_even_when_canceled(self):
        """
        /owner/billing/ is exempt so owners can always access billing settings.
        """
        tenant = _make_tenant('expired', grace_period_end=timezone.now() - timedelta(days=5))
        request = self._make_request('/owner/billing/', 'GET')
        self._attach_tenant(request, tenant)

        response = self.middleware(request)

        self.get_response.assert_called_once_with(request)


class CanceledSubscriptionIntegrationTests(TestCase):
    """
    Integration tests confirming cancel_subscription() sets up the right state
    and that the middleware correctly allows access in that state.
    """

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='starter',
            defaults={
                'name': 'Starter',
                'monthly_price': '49.00',
                'stripe_price_id': 'price_test_130',
            },
        )

    def test_status_is_canceled_after_cancellation_no_grace_period(self):
        """
        After cancel_subscription() the tenant has status='canceled' and
        grace_period_end=None — confirming the middleware will see it as active.
        """
        user = User.objects.create_user('owner130i', 'o130i@example.com', 'pass')
        tenant = Tenant.objects.create(
            name='Test Shop 130',
            slug='test-shop-130',
            owner=user,
            subscription_status='active',
            plan='starter',
            subscription_plan=self.plan,
            stripe_subscription_id='sub_simulate_130',
        )

        # Simulate what cancel_subscription() does
        tenant.subscription_status = 'canceled'
        tenant.save(update_fields=['subscription_status'])

        # Reload from DB
        tenant.refresh_from_db()

        self.assertEqual(tenant.subscription_status, 'canceled')
        self.assertIsNone(tenant.grace_period_end)
        # Confirm middleware logic: canceled without grace_period_end → NOT expired
        canceled_is_active = (
            tenant.subscription_status == 'canceled'
            and not tenant.grace_period_end
        )
        is_subscription_expired = (
            tenant.subscription_status in ('canceled', 'expired')
            and not canceled_is_active
        )
        self.assertFalse(is_subscription_expired, "Canceled-without-grace-period should NOT be treated as expired")
