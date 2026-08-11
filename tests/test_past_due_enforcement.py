"""
past_due enforcement, trial grace, and the notification layer.

Three behaviours land here, each replacing something that quietly cost
money or customers:

1. **past_due had no teeth.** The middleware showed a banner and fell
   straight through to the response. A shop whose card died kept full write
   access for the entire Stripe retry window and indefinitely after it --
   logging jobs, sending invoices, never paying. It now escalates to
   read-only at PAST_DUE_GRACE_DAYS (14).

2. **Expired trials got no grace at all.** grace_period_end was only ever
   written by the subscription.deleted webhook, so a shop that never
   subscribed hit a hard wall the second the trial clock ran out.

3. **Alert dedup keys were never cleared.** A tenant who lapsed,
   resubscribed, and lapsed again received NO lifecycle emails the second
   time -- the first lapse's keys permanently suppressed them.
"""

import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services import subscription_notify
from apps.tenants.subscription_middleware import SubscriptionEnforcementMiddleware


def make_tenant(slug='pd-shop', status='past_due', past_due_days=None,
                plan='starter'):
    owner = User.objects.create_user(
        username=f'{slug}-owner', email=f'{slug}@test.com', password='pw123!',
        first_name='Pat',
    )
    plan_obj, _ = SubscriptionPlan.objects.update_or_create(
        slug='starter',
        defaults={'name': 'Starter', 'monthly_price': Decimal('49.00'),
                  'is_active': True},
    )
    tenant = Tenant.objects.create(
        name='Past Due Shop', slug=slug, owner=owner, plan=plan,
        subscription_plan=plan_obj, subscription_status=status,
        stripe_customer_id=f'cus_{slug}', stripe_subscription_id=f'sub_{slug}',
        trial_started_at=timezone.now(),
    )
    if past_due_days is not None:
        tenant.past_due_since = timezone.now() - timezone.timedelta(days=past_due_days)
        tenant.save(update_fields=['past_due_since'])
    TenantMembership.objects.create(
        tenant=tenant, user=owner, role='owner', is_active=True,
    )
    return tenant, owner


class MiddlewareHarness(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.passed = []

    def _run(self, request):
        self.passed = []

        def get_response(req):
            self.passed.append('passed_through')
            from django.http import HttpResponse
            return HttpResponse('ok')

        mw = SubscriptionEnforcementMiddleware(get_response)
        return mw(request)

    def _request(self, tenant, user, method='GET', path='/tech/jobs/'):
        request = getattr(self.factory, method.lower())(path)
        request.user = user
        request.tenant = tenant
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return request


@override_settings(PAST_DUE_GRACE_DAYS=14)
class PastDueLadderTests(MiddlewareHarness):
    def test_day_three_keeps_full_access_with_a_warning(self):
        tenant, owner = make_tenant(past_due_days=3)
        request = self._request(tenant, owner, method='POST')
        self._run(request)
        self.assertEqual(
            self.passed, ['passed_through'],
            "an innocently expired card must not lose write access on day 3",
        )
        self.assertTrue(getattr(request, 'subscription_past_due', False))
        self.assertEqual(request.past_due_days_until_read_only, 11)

    def test_day_fifteen_blocks_writes(self):
        tenant, owner = make_tenant(past_due_days=15)
        request = self._request(tenant, owner, method='POST')
        response = self._run(request)
        self.assertEqual(self.passed, [])
        self.assertEqual(response.status_code, 302)

    def test_day_fifteen_still_allows_reads(self):
        """Read-only means read-only, not locked out."""
        tenant, owner = make_tenant(past_due_days=15)
        request = self._request(tenant, owner, method='GET')
        self._run(request)
        self.assertEqual(self.passed, ['passed_through'])
        self.assertEqual(request.subscription_readonly_reason, 'past_due')

    def test_api_write_gets_402_not_a_redirect(self):
        tenant, owner = make_tenant(past_due_days=20)
        request = self._request(tenant, owner, method='POST', path='/api/jobs/')
        response = self._run(request)
        self.assertEqual(response.status_code, 402)
        # Calling the middleware directly yields a raw JsonResponse, which
        # has no .json() helper -- that belongs to the test client.
        self.assertEqual(json.loads(response.content)['reason'], 'past_due')

    def test_billing_page_stays_reachable_when_read_only(self):
        """The fix must always be one click away."""
        tenant, owner = make_tenant(past_due_days=30)
        request = self._request(
            tenant, owner, method='POST', path='/owner/billing/',
        )
        self._run(request)
        self.assertEqual(self.passed, ['passed_through'])

    def test_past_due_without_a_stamp_never_restricts(self):
        """Legacy rows have no past_due_since; don't lock them out."""
        tenant, owner = make_tenant(past_due_days=None)
        request = self._request(tenant, owner, method='POST')
        self._run(request)
        self.assertEqual(self.passed, ['passed_through'])

    def test_platform_owner_is_exempt(self):
        tenant, owner = make_tenant(past_due_days=60)
        tenant.is_platform_owner = True
        tenant.save(update_fields=['is_platform_owner'])
        request = self._request(tenant, owner, method='POST')
        self._run(request)
        self.assertEqual(self.passed, ['passed_through'])

    @override_settings(PAST_DUE_GRACE_DAYS=7)
    def test_threshold_is_configurable(self):
        tenant, owner = make_tenant(past_due_days=8)
        request = self._request(tenant, owner, method='POST')
        response = self._run(request)
        self.assertEqual(self.passed, [])
        self.assertEqual(response.status_code, 302)


class PastDueModelTests(TestCase):
    @override_settings(PAST_DUE_GRACE_DAYS=14)
    def test_days_past_due_and_countdown(self):
        tenant, _ = make_tenant(past_due_days=5)
        self.assertEqual(tenant.days_past_due, 5)
        self.assertEqual(tenant.past_due_days_until_read_only, 9)
        self.assertFalse(tenant.past_due_is_read_only)

    def test_active_tenant_is_never_past_due(self):
        tenant, _ = make_tenant(status='active', past_due_days=30)
        self.assertFalse(tenant.past_due_is_read_only)
        self.assertIsNone(tenant.past_due_days_until_read_only)


class ReactivationClearsEverythingTests(TestCase):
    def test_mark_subscription_active_resets_alert_keys(self):
        """The bug: a second lapse sent no emails at all.

        subscription_alerts_sent was never cleared on reactivation, so the
        dedup keys from the first lapse permanently suppressed the trial and
        grace sequences the next time round.
        """
        tenant, _ = make_tenant(past_due_days=10)
        tenant.subscription_alerts_sent = {'trial_expiry_7_days': 'x'}
        tenant.grace_period_end = timezone.now() + timezone.timedelta(days=5)
        tenant.save()

        fields = tenant.mark_subscription_active(status='active')
        tenant.save(update_fields=fields)
        tenant.refresh_from_db()

        self.assertEqual(tenant.subscription_alerts_sent, {})
        self.assertIsNone(tenant.grace_period_end)
        self.assertIsNone(tenant.past_due_since)
        self.assertEqual(tenant.subscription_status, 'active')

    def test_invoice_paid_clears_past_due_since(self):
        from apps.tenants import webhooks

        tenant, _ = make_tenant(past_due_days=10)
        invoice = {
            'id': 'in_rec', 'customer': tenant.stripe_customer_id,
            'billing_reason': 'subscription_cycle',
            'parent': {'subscription_details': {
                'subscription': tenant.stripe_subscription_id}},
        }
        with patch.object(webhooks, '_notify_owners_and_managers'):
            webhooks._handle_invoice_paid(invoice, event=None)

        tenant.refresh_from_db()
        self.assertIsNone(tenant.past_due_since)
        self.assertEqual(tenant.subscription_status, 'active')

    def test_first_failure_stamps_but_retries_do_not_reset_it(self):
        """Stripe retries the same invoice; the countdown must not restart."""
        from apps.tenants import webhooks

        tenant, _ = make_tenant(status='active')
        invoice = {
            'id': 'in_f', 'customer': tenant.stripe_customer_id,
            'billing_reason': 'subscription_cycle', 'attempt_count': 1,
            'parent': {'subscription_details': {
                'subscription': tenant.stripe_subscription_id}},
        }
        with patch.object(webhooks, '_notify_owners_and_managers'):
            webhooks._handle_invoice_payment_failed(invoice, event=None)
        tenant.refresh_from_db()
        first_stamp = tenant.past_due_since
        self.assertIsNotNone(first_stamp)

        # Backdate, then deliver a retry of the same lapse.
        tenant.past_due_since = timezone.now() - timezone.timedelta(days=10)
        tenant.save(update_fields=['past_due_since'])
        with patch.object(webhooks, '_notify_owners_and_managers'):
            webhooks._handle_invoice_payment_failed(
                dict(invoice, attempt_count=2), event=None,
            )
        tenant.refresh_from_db()
        self.assertEqual(
            tenant.days_past_due, 10,
            "a retry must not restart the read-only countdown",
        )


class NotificationTests(TestCase):
    def test_payment_failed_uses_stripe_retry_date(self):
        tenant, _ = make_tenant()
        msg = subscription_notify.build_message(
            tenant, 'payment_failed',
            {'attempt_count': 2, 'next_payment_attempt': 1767225600},
        )
        body = ' '.join(msg['paragraphs'])
        self.assertIn('January 1, 2026', body)
        self.assertNotIn('of 4', body)

    def test_payment_failed_final_attempt_copy(self):
        tenant, _ = make_tenant()
        msg = subscription_notify.build_message(
            tenant, 'payment_failed',
            {'attempt_count': 4, 'next_payment_attempt': None},
        )
        self.assertIn('final automatic attempt', ' '.join(msg['paragraphs']))

    def test_every_event_has_in_app_copy(self):
        """Email-only was the old bug; each message must carry both."""
        tenant, _ = make_tenant()
        for event_type in (
            'payment_failed', 'payment_recovered', 'payment_action_required',
            'renewal_upcoming', 'past_due_reminder', 'past_due_readonly',
            'subscription_ended',
        ):
            with self.subTest(event=event_type):
                msg = subscription_notify.build_message(tenant, event_type, {})
                self.assertTrue(msg.get('in_app'), f"{event_type} has no in-app text")
                self.assertTrue(msg.get('subject'))
                self.assertTrue(msg.get('paragraphs'))

    def test_in_app_notification_created_for_managers(self):
        from apps.technician_portal.models import Technician, TechnicianNotification

        tenant, owner = make_tenant()
        Technician.objects.create(
            user=owner, tenant=tenant, is_active=True, is_manager=True,
        )
        count = subscription_notify.create_in_app_notification(
            tenant, 'Your payment failed',
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician__tenant=tenant).count(), 1,
        )

    def test_notify_sends_both_channels(self):
        tenant, _ = make_tenant()
        with patch.object(subscription_notify, 'create_in_app_notification') as in_app, \
             patch('core.email_utils.send_branded_email') as email:
            subscription_notify.notify_owners_and_managers(
                tenant, 'payment_failed', {'attempt_count': 1},
            )
        in_app.assert_called_once()
        email.assert_called_once()

    def test_notify_never_raises(self):
        """A mail failure must not roll back the state change that caused it."""
        tenant, _ = make_tenant()
        with patch('core.email_utils.send_branded_email',
                   side_effect=RuntimeError('SES down')):
            subscription_notify.notify_owners_and_managers(
                tenant, 'payment_failed', {},
            )


class BillingPortalDeepLinkTests(TestCase):
    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_flow_is_passed_through(self):
        from apps.tenants.services.subscription_service import SubscriptionService

        tenant, _ = make_tenant()
        with patch('stripe.billing_portal.Session.create') as create:
            create.return_value = type('S', (), {'url': 'https://portal'})()
            SubscriptionService().create_billing_portal_session(
                tenant, 'https://back', flow='payment_method_update',
            )
        self.assertEqual(
            create.call_args.kwargs['flow_data']['type'],
            'payment_method_update',
        )

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_falls_back_when_portal_config_rejects_the_flow(self):
        """A misconfigured Dashboard must not 500 an owner trying to pay."""
        import stripe as stripe_mod
        from apps.tenants.services.subscription_service import SubscriptionService

        tenant, _ = make_tenant()
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if 'flow_data' in kwargs:
                raise stripe_mod.error.InvalidRequestError('no config', None)
            return type('S', (), {'url': 'https://portal'})()

        with patch('stripe.billing_portal.Session.create', side_effect=create):
            url = SubscriptionService().create_billing_portal_session(
                tenant, 'https://back', flow='payment_method_update',
            )

        self.assertEqual(url, 'https://portal')
        self.assertEqual(len(calls), 2)
        self.assertNotIn('flow_data', calls[1])
