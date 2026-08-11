"""
Webhook idempotency, ordering, and retry semantics.

Before StripeWebhookEvent existed, all three of these were broken and none
of them were visible:

- A redelivered event re-ran its handler and re-sent its email.
- A late invoice.payment_failed arriving after invoice.paid flipped a paying
  tenant back to past_due.
- Every exception returned HTTP 200, telling Stripe "handled, don't retry",
  so a transient DB or SES error destroyed the event permanently. The Stripe
  Dashboard showed 100% delivery success the whole time.

That last one is why the endpoint now returns 500 on retryable failures, and
why the event log exists to keep a poison event visible instead of retrying
forever unnoticed.
"""

import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import StripeWebhookEvent
from apps.billing.services import webhook_log
from apps.billing.services.webhook_log import WebhookPermanentError
from apps.tenants import webhooks
from apps.tenants.models import SubscriptionPlan, Tenant


CUSTOMER_ID = 'cus_idem123'
SUB_ID = 'sub_idem123'
PRICE_ID = 'price_starter_idem'

WEBHOOK_URL = '/api/tenants/webhooks/stripe/'


def make_event(event_id, event_type, obj, created=1767225600):
    return {
        'id': event_id,
        'type': event_type,
        'created': created,
        'api_version': '2026-07-29.dahlia',
        'livemode': False,
        'data': {'object': obj},
    }


def paid_invoice():
    return {
        'id': 'in_idem1',
        'customer': CUSTOMER_ID,
        'billing_reason': 'subscription_cycle',
        'parent': {'subscription_details': {'subscription': SUB_ID}},
        'lines': {'data': [{'pricing': {'price_details': {'price': PRICE_ID}}}]},
    }


def failed_invoice():
    return {
        'id': 'in_idem2',
        'customer': CUSTOMER_ID,
        'billing_reason': 'subscription_cycle',
        'attempt_count': 1,
        'next_payment_attempt': 1767312000,
        'parent': {'subscription_details': {'subscription': SUB_ID}},
    }


class WebhookTestBase(TestCase):
    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='starter',
            defaults={'name': 'Starter', 'monthly_price': Decimal('49.00'),
                      'stripe_price_id': PRICE_ID, 'is_active': True},
        )
        owner = get_user_model().objects.create_user(
            username='idem-owner', email='idem@test.com', password='pw123!',
        )
        self.tenant = Tenant.objects.create(
            name='Idem Shop', slug='idem-shop', owner=owner,
            plan='trial', subscription_status='trialing',
            stripe_customer_id=CUSTOMER_ID,
        )

    def reload(self):
        self.tenant.refresh_from_db()
        return self.tenant


class ClaimIdempotencyTests(WebhookTestBase):
    def test_first_claim_processes_second_does_not(self):
        event = make_event('evt_dup1', 'invoice.paid', paid_invoice())

        row, should = webhook_log.claim(event, 'subscription')
        self.assertTrue(should)
        webhook_log.mark_processed(row)

        row2, should2 = webhook_log.claim(event, 'subscription')
        self.assertFalse(should2, "a redelivered event must not be reprocessed")
        self.assertEqual(row2.pk, row.pk)

    def test_failed_event_is_retried(self):
        """Stripe retries a 500; that redelivery must actually run."""
        event = make_event('evt_retry1', 'invoice.paid', paid_invoice())

        row, _ = webhook_log.claim(event, 'subscription')
        webhook_log.mark_failed(row, RuntimeError('db down'))

        row2, should2 = webhook_log.claim(event, 'subscription')
        self.assertTrue(should2, "a previously failed event must be retried")
        self.assertEqual(row2.attempts, 2)

    def test_payload_is_stored_for_replay(self):
        event = make_event('evt_payload1', 'invoice.paid', paid_invoice())
        webhook_log.claim(event, 'subscription')
        row = StripeWebhookEvent.objects.get(event_id='evt_payload1')
        self.assertEqual(row.payload['data']['object']['id'], 'in_idem1')
        self.assertEqual(row.api_version, '2026-07-29.dahlia')
        self.assertFalse(row.livemode)

    def test_missing_event_id_still_processes(self):
        """No id to dedupe on is not a reason to drop the event."""
        row, should = webhook_log.claim({'type': 'invoice.paid'}, 'subscription')
        self.assertIsNone(row)
        self.assertTrue(should)


class OrderingGuardTests(WebhookTestBase):
    def test_late_payment_failed_does_not_undo_paid(self):
        """The bug this guard exists for.

        Stripe does not guarantee order. A retried payment_failed created
        BEFORE the paid event must not mark a paying shop past_due.
        """
        paid = make_event('evt_paid', 'invoice.paid', paid_invoice(), created=2000)
        late_fail = make_event(
            'evt_fail', 'invoice.payment_failed', failed_invoice(), created=1000,
        )

        webhooks._handle_invoice_paid(paid['data']['object'], event=paid)
        self.assertEqual(self.reload().subscription_status, 'active')

        with patch.object(webhooks, '_notify_owners_and_managers') as notify:
            webhooks._handle_invoice_payment_failed(
                late_fail['data']['object'], event=late_fail,
            )

        self.assertEqual(
            self.reload().subscription_status, 'active',
            "a stale payment_failed must not override a newer invoice.paid",
        )
        notify.assert_not_called()

    def test_newer_payment_failed_still_applies(self):
        """The guard must not swallow legitimately newer events."""
        paid = make_event('evt_paid2', 'invoice.paid', paid_invoice(), created=1000)
        later_fail = make_event(
            'evt_fail2', 'invoice.payment_failed', failed_invoice(), created=2000,
        )

        webhooks._handle_invoice_paid(paid['data']['object'], event=paid)
        with patch.object(webhooks, '_notify_owners_and_managers'):
            webhooks._handle_invoice_payment_failed(
                later_fail['data']['object'], event=later_fail,
            )
        self.assertEqual(self.reload().subscription_status, 'past_due')

    def test_same_second_events_both_apply(self):
        """Stripe's `created` has 1s resolution; ties must not be dropped."""
        paid = make_event('evt_a', 'invoice.paid', paid_invoice(), created=1500)
        same = make_event('evt_b', 'invoice.payment_failed', failed_invoice(),
                          created=1500)

        webhooks._handle_invoice_paid(paid['data']['object'], event=paid)
        with patch.object(webhooks, '_notify_owners_and_managers'):
            webhooks._handle_invoice_payment_failed(
                same['data']['object'], event=same,
            )
        self.assertEqual(self.reload().subscription_status, 'past_due')

    def test_watermark_advances(self):
        paid = make_event('evt_w', 'invoice.paid', paid_invoice(), created=1767225600)
        webhooks._handle_invoice_paid(paid['data']['object'], event=paid)
        self.assertIsNotNone(self.reload().subscription_synced_at)

    def test_events_without_created_always_apply(self):
        """Hand-built/legacy payloads must not be silently discarded."""
        self.tenant.subscription_synced_at = timezone.now()
        self.tenant.save(update_fields=['subscription_synced_at'])
        webhooks._handle_invoice_paid(paid_invoice(), event=None)
        self.assertEqual(self.reload().subscription_status, 'active')


@override_settings(STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='', DEBUG=True)
class EndpointRetrySemanticsTests(WebhookTestBase):
    """The endpoint's HTTP status is the retry contract with Stripe."""

    def _post(self, event):
        return self.client.post(
            WEBHOOK_URL, data=json.dumps(event),
            content_type='application/json',
        )

    def test_success_returns_200_and_marks_processed(self):
        resp = self._post(make_event('evt_ok', 'invoice.paid', paid_invoice()))
        self.assertEqual(resp.status_code, 200)
        row = StripeWebhookEvent.objects.get(event_id='evt_ok')
        self.assertEqual(row.status, 'processed')
        self.assertEqual(self.reload().subscription_status, 'active')

    def test_duplicate_delivery_does_not_rerun_handler(self):
        event = make_event('evt_once', 'invoice.paid', paid_invoice())
        self._post(event)

        with patch.object(webhooks, '_handle_invoice_paid') as handler:
            resp = self._post(event)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('duplicate'))
        handler.assert_not_called()

    def test_retryable_error_returns_500_and_marks_failed(self):
        """A transient failure must make Stripe retry, not discard."""
        event = make_event('evt_boom', 'invoice.paid', paid_invoice())

        with patch.object(webhooks, '_handle_invoice_paid',
                          side_effect=RuntimeError('database is down')):
            resp = self._post(event)

        self.assertEqual(
            resp.status_code, 500,
            "returning 200 on a transient error destroys the event permanently",
        )
        row = StripeWebhookEvent.objects.get(event_id='evt_boom')
        self.assertEqual(row.status, 'failed')
        self.assertIn('database is down', row.last_error)

    def test_permanent_error_returns_200_and_marks_ignored(self):
        """An unknown customer will never resolve; retrying is pointless."""
        orphan = dict(paid_invoice(), customer='cus_nobody')
        resp = self._post(make_event('evt_orphan', 'invoice.paid', orphan))

        self.assertEqual(resp.status_code, 200)
        row = StripeWebhookEvent.objects.get(event_id='evt_orphan')
        self.assertEqual(row.status, 'ignored')

    def test_unhandled_event_type_is_ignored_not_failed(self):
        resp = self._post(make_event('evt_unk', 'customer.discount.created', {}))
        self.assertEqual(resp.status_code, 200)
        row = StripeWebhookEvent.objects.get(event_id='evt_unk')
        self.assertEqual(row.status, 'ignored')

    def test_failed_event_reprocesses_on_stripe_retry(self):
        """End-to-end: 500, then Stripe redelivers, then it succeeds."""
        event = make_event('evt_recover', 'invoice.paid', paid_invoice())

        with patch.object(webhooks, '_handle_invoice_paid',
                          side_effect=RuntimeError('transient')):
            self.assertEqual(self._post(event).status_code, 500)

        self.assertEqual(self._post(event).status_code, 200)
        row = StripeWebhookEvent.objects.get(event_id='evt_recover')
        self.assertEqual(row.status, 'processed')
        self.assertEqual(row.attempts, 2)
        self.assertEqual(self.reload().subscription_status, 'active')


class NewEventTypeTests(WebhookTestBase):
    def test_uncollectible_expires_with_grace(self):
        event = make_event(
            'evt_unc', 'invoice.marked_uncollectible',
            {'id': 'in_unc', 'customer': CUSTOMER_ID},
        )
        with patch.object(webhooks, '_notify_owners_and_managers'):
            webhooks._handle_invoice_uncollectible(
                event['data']['object'], event=event,
            )
        tenant = self.reload()
        self.assertEqual(tenant.subscription_status, 'expired')
        self.assertIsNotNone(
            tenant.grace_period_end,
            "a write-off must still leave read-only access, not a hard lockout",
        )

    def test_dispute_alerts_the_platform_not_the_tenant(self):
        dispute = {'charge': 'ch_1', 'amount': 4900, 'reason': 'fraudulent',
                   'status': 'needs_response'}
        with patch.object(webhooks, '_notify_owners_and_managers') as tenant_notify, \
             patch('core.email_utils.send_branded_email') as send:
            webhooks._handle_dispute_created(dispute, event=None)

        tenant_notify.assert_not_called()
        self.assertTrue(send.called, "the platform must be told about a dispute")

    def test_dispute_does_not_change_tenant_state(self):
        before = self.reload().subscription_status
        with patch('core.email_utils.send_branded_email'):
            webhooks._handle_dispute_created(
                {'charge': 'ch_2', 'amount': 100, 'reason': 'duplicate'},
                event=None,
            )
        self.assertEqual(self.reload().subscription_status, before)

    def test_upcoming_invoice_notifies(self):
        with patch.object(webhooks, '_notify_owners_and_managers') as notify:
            webhooks._handle_invoice_upcoming(
                {'id': 'in_up', 'customer': CUSTOMER_ID, 'amount_due': 4900,
                 'next_payment_attempt': 1767312000},
                event=None,
            )
        notify.assert_called_once()
        self.assertEqual(notify.call_args[0][1], 'renewal_upcoming')

    def test_action_required_notifies(self):
        with patch.object(webhooks, '_notify_owners_and_managers') as notify:
            webhooks._handle_invoice_action_required(
                {'id': 'in_3ds', 'customer': CUSTOMER_ID,
                 'hosted_invoice_url': 'https://stripe/x'},
                event=None,
            )
        notify.assert_called_once()
        self.assertEqual(notify.call_args[0][1], 'payment_action_required')

    def test_unknown_customer_is_permanent_not_retryable(self):
        with self.assertRaises(WebhookPermanentError):
            webhooks._handle_invoice_upcoming(
                {'id': 'in_x', 'customer': 'cus_nobody'}, event=None,
            )
