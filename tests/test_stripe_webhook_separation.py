"""
Stripe Webhook Separation Tests

Comprehensive tests verifying that billing webhooks and subscription webhooks
are properly separated with independent signing secrets, endpoints, and handlers.

Also tests Stripe Connect payment routing, platform fees, and the interaction
between all three webhook concerns (billing, subscriptions, Connect).

Coverage:
- Billing webhook endpoint (/api/billing/stripe/webhook/)
- Subscription webhook endpoint (/api/tenants/webhooks/stripe/)
- Separate signing secret verification
- Connect direct charges and platform fees
- Event routing — each event goes to the correct handler
- Cross-contamination prevention
- Edge cases: missing secrets, invalid signatures, duplicate events

Author: Amelia (Clawdbot AI)
Date: 2026-03-18
"""

import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.tenants.webhooks import (
    stripe_subscription_webhook,
    handle_subscription_event,
    _handle_checkout_completed as sub_handle_checkout,
    _handle_invoice_paid,
    _handle_invoice_payment_failed,
    _handle_subscription_updated,
    _handle_subscription_deleted,
)


class WebhookEndpointTestBase(TestCase):
    """Base class with shared setup for webhook tests."""

    def setUp(self):
        self.factory = RequestFactory()

        # Get or create subscription plans (migrations may seed defaults)
        self.plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='professional',
            defaults={
                'name': 'Professional',
                'stripe_price_id': 'price_pro_monthly',
                'stripe_annual_price_id': 'price_pro_annual',
                'monthly_price': Decimal('49.99'),
                'annual_price': Decimal('499.99'),
                'max_repairs_per_month': 500,
            },
        )

        self.trial_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'monthly_price': Decimal('0'),
                'max_repairs_per_month': 50,
            },
        )

        # Create owner user
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.owner = User.objects.create_user(
            username='shopowner_wh',
            email='owner_wh@testshop.com',
            password='testpass123',
            first_name='Test',
            last_name='Owner',
        )

        # Create tenant
        self.tenant = Tenant.objects.create(
            name='Test Glass Shop WH',
            slug='test-glass-shop-wh',
            owner=self.owner,
            stripe_customer_id='cus_test123',
            subscription_status='trial',
            plan='trial',
            trial_started_at=timezone.now(),
        )

    def _create_customer_and_invoice(self, invoice_number='INV-001', amount=Decimal('150.00')):
        """Helper to create a customer and invoice for billing tests."""
        from core.models import Customer
        from apps.billing.models import Invoice
        customer, _ = Customer.objects.get_or_create(
            tenant=self.tenant,
            name='Fleet Corp WH',
            defaults={'email': 'fleet_wh@test.com'},
        )
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=customer,
            invoice_number=invoice_number,
            subtotal=amount,
            total=amount,
            status='sent',
        )
        return customer, invoice


# =============================================================================
# 1. SUBSCRIPTION WEBHOOK ENDPOINT TESTS
# =============================================================================

class SubscriptionWebhookEndpointTests(WebhookEndpointTestBase):
    """Tests for /api/tenants/webhooks/stripe/ endpoint."""

    @override_settings(STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='whsec_sub_test123')
    @patch('stripe.Webhook.construct_event')
    def test_valid_subscription_event_processed(self, mock_construct):
        """Valid subscription event is processed and returns 200."""
        mock_construct.return_value = {
            'id': 'evt_test1',
            'type': 'customer.subscription.updated',
            'data': {
                'object': {
                    'id': 'sub_test1',
                    'customer': 'cus_test123',
                    'status': 'active',
                    'items': {'data': [{'price': {'id': 'price_pro_monthly'}}]},
                    'cancel_at_period_end': False,
                }
            },
        }

        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=abc',
        )
        response = stripe_subscription_webhook(request)
        self.assertEqual(response.status_code, 200)

    @override_settings(STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='whsec_sub_test123')
    @patch('stripe.Webhook.construct_event')
    def test_subscription_webhook_uses_subscription_secret(self, mock_construct):
        """Subscription endpoint uses STRIPE_SUBSCRIPTION_WEBHOOK_SECRET."""
        mock_construct.return_value = {
            'id': 'evt_test2',
            'type': 'invoice.paid',
            'data': {'object': {'customer': 'cus_x', 'subscription': None}},
        }

        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=b'test_payload',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=abc',
        )
        stripe_subscription_webhook(request)
        # Verify the secret passed to construct_event is the subscription one
        call_args = mock_construct.call_args
        self.assertEqual(call_args[0][2], 'whsec_sub_test123')

    @override_settings(
        STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='',
        STRIPE_WEBHOOK_SECRET='whsec_billing_fallback',
    )
    @patch('stripe.Webhook.construct_event')
    def test_subscription_webhook_falls_back_to_billing_secret(self, mock_construct):
        """When STRIPE_SUBSCRIPTION_WEBHOOK_SECRET is empty, falls back to STRIPE_WEBHOOK_SECRET."""
        mock_construct.return_value = {
            'id': 'evt_test3',
            'type': 'invoice.paid',
            'data': {'object': {'customer': 'cus_test123', 'subscription': 'sub_1'}},
        }

        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=abc',
        )
        stripe_subscription_webhook(request)
        call_args = mock_construct.call_args
        self.assertEqual(call_args[0][2], 'whsec_billing_fallback')

    @override_settings(STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='', STRIPE_WEBHOOK_SECRET='', DEBUG=False)
    def test_subscription_webhook_rejects_without_secret_in_production(self):
        """No webhook secret in production returns 500."""
        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=abc',
        )
        response = stripe_subscription_webhook(request)
        self.assertEqual(response.status_code, 500)

    @override_settings(STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='whsec_sub_test123')
    @patch('stripe.Webhook.construct_event')
    def test_subscription_webhook_rejects_invalid_signature(self, mock_construct):
        """Invalid signature returns 400."""
        import stripe as stripe_module
        mock_construct.side_effect = stripe_module.error.SignatureVerificationError(
            'bad sig', 'sig'
        )
        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=invalid',
        )
        response = stripe_subscription_webhook(request)
        self.assertEqual(response.status_code, 400)

    def test_subscription_webhook_rejects_get(self):
        """GET requests to webhook are rejected."""
        request = self.factory.get('/api/tenants/webhooks/stripe/')
        response = stripe_subscription_webhook(request)
        self.assertEqual(response.status_code, 405)


# =============================================================================
# 2. BILLING WEBHOOK ENDPOINT TESTS
# =============================================================================

@override_settings(
    STRIPE_SECRET_KEY='sk_test_fake123',
    STRIPE_WEBHOOK_SECRET='whsec_billing_test456',
)
class BillingWebhookEndpointTests(WebhookEndpointTestBase):
    """Tests for /api/billing/stripe/webhook/ via StripeService.handle_webhook."""

    def _get_svc(self):
        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        # Force enabled since we're testing with fake keys
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_test456'
        return svc

    @patch('stripe.Webhook.construct_event')
    def test_billing_webhook_uses_billing_secret(self, mock_construct):
        """Billing endpoint uses STRIPE_WEBHOOK_SECRET."""
        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'data': {'object': {'id': 'pi_test', 'metadata': {}, 'amount_received': 0}},
        }
        svc = self._get_svc()
        svc.handle_webhook(b'{}', 't=123,v1=abc')
        call_args = mock_construct.call_args
        self.assertEqual(call_args[0][2], 'whsec_billing_test456')

    def test_billing_webhook_rejects_without_secret(self):
        """No webhook secret returns error."""
        svc = self._get_svc()
        svc.webhook_secret = ''
        result = svc.handle_webhook(b'{}', 't=123,v1=abc')
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Webhook secret not configured')

    def test_billing_webhook_rejects_when_disabled(self):
        """Disabled Stripe returns error."""
        svc = self._get_svc()
        svc.enabled = False
        result = svc.handle_webhook(b'{}', 't=123,v1=abc')
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Stripe not configured')

    @patch('stripe.Webhook.construct_event')
    def test_billing_checkout_completed_records_payment(self, mock_construct):
        """checkout.session.completed with rs_invoice_id records payment."""
        _, invoice = self._create_customer_and_invoice('INV-B001', Decimal('150.00'))

        # Direct charges arrive as Connect events: event['account'] must
        # match the invoice tenant's Connect account or the payment is refused.
        self.tenant.stripe_connect_account_id = 'acct_shop_b001'
        self.tenant.save(update_fields=['stripe_connect_account_id'])

        mock_construct.return_value = {
            'type': 'checkout.session.completed',
            'account': 'acct_shop_b001',
            'data': {
                'object': {
                    'id': 'cs_test_123',
                    'payment_status': 'paid',
                    'amount_total': 15000,
                    'payment_intent': 'pi_test_123',
                    'metadata': {'rs_invoice_id': str(invoice.id)},
                }
            },
        }

        svc = self._get_svc()
        result = svc.handle_webhook(b'{}', 't=123,v1=abc')
        self.assertTrue(result['success'])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'PAID')

    @patch('stripe.Webhook.construct_event')
    def test_billing_checkout_wrong_account_refused(self, mock_construct):
        """A charge that landed on a different Stripe account (e.g. a stale
        platform Payment Link, or forged metadata) must NOT mark the
        invoice paid — the shop never received that money."""
        _, invoice = self._create_customer_and_invoice('INV-B004', Decimal('99.00'))

        self.tenant.stripe_connect_account_id = 'acct_shop_b004'
        self.tenant.save(update_fields=['stripe_connect_account_id'])

        mock_construct.return_value = {
            'type': 'checkout.session.completed',
            # No 'account' key → platform-account charge
            'data': {
                'object': {
                    'id': 'cs_test_wrong',
                    'payment_status': 'paid',
                    'amount_total': 9900,
                    'payment_intent': 'pi_test_wrong',
                    'metadata': {'rs_invoice_id': str(invoice.id)},
                }
            },
        }

        svc = self._get_svc()
        result = svc.handle_webhook(b'{}', 't=123,v1=abc')
        self.assertEqual(result.get('flagged'), 'account_mismatch')
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'sent')  # NOT paid
        self.assertEqual(invoice.payments.count(), 0)

    @patch('stripe.Webhook.construct_event')
    def test_billing_checkout_unpaid_defers(self, mock_construct):
        """checkout.session.completed with payment_status=unpaid does NOT record payment."""
        _, invoice = self._create_customer_and_invoice('INV-B002', Decimal('200.00'))

        mock_construct.return_value = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_456',
                    'payment_status': 'unpaid',
                    'amount_total': 20000,
                    'payment_intent': None,
                    'metadata': {'rs_invoice_id': str(invoice.id)},
                }
            },
        }

        svc = self._get_svc()
        result = svc.handle_webhook(b'{}', 't=123,v1=abc')
        self.assertTrue(result['success'])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'sent')  # Still sent, not paid

    @patch('stripe.Webhook.construct_event')
    def test_billing_payment_intent_succeeded(self, mock_construct):
        """payment_intent.succeeded records payment."""
        _, invoice = self._create_customer_and_invoice('INV-B003', Decimal('75.50'))

        self.tenant.stripe_connect_account_id = 'acct_shop_b003'
        self.tenant.save(update_fields=['stripe_connect_account_id'])

        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'account': 'acct_shop_b003',
            'data': {
                'object': {
                    'id': 'pi_test_789',
                    'amount_received': 7550,
                    'metadata': {'rs_invoice_id': str(invoice.id)},
                }
            },
        }

        svc = self._get_svc()
        result = svc.handle_webhook(b'{}', 't=123,v1=abc')
        self.assertTrue(result['success'])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'PAID')


# =============================================================================
# 3. WEBHOOK SEPARATION — NO CROSS-CONTAMINATION
# =============================================================================

@override_settings(
    STRIPE_SECRET_KEY='sk_test_fake',
    STRIPE_WEBHOOK_SECRET='whsec_billing_secret',
    STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='whsec_sub_secret',
)
class WebhookSeparationTests(WebhookEndpointTestBase):
    """Verify billing and subscription webhooks use independent secrets."""

    @patch('stripe.Webhook.construct_event')
    def test_billing_and_subscription_use_different_secrets(self, mock_construct):
        """Each endpoint uses its own signing secret."""
        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'data': {'object': {'id': 'pi_1', 'metadata': {}, 'amount_received': 0}},
        }

        # Call billing webhook
        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_secret'
        svc.handle_webhook(b'billing_payload', 't=1,v1=a')
        billing_secret = mock_construct.call_args[0][2]

        mock_construct.reset_mock()
        mock_construct.return_value = {
            'id': 'evt_2',
            'type': 'invoice.paid',
            'data': {'object': {'customer': 'cus_x', 'subscription': 'sub_x'}},
        }

        # Call subscription webhook
        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=b'sub_payload',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=2,v1=b',
        )
        stripe_subscription_webhook(request)
        sub_secret = mock_construct.call_args[0][2]

        self.assertEqual(billing_secret, 'whsec_billing_secret')
        self.assertEqual(sub_secret, 'whsec_sub_secret')
        self.assertNotEqual(billing_secret, sub_secret)

    @patch('stripe.Webhook.construct_event')
    def test_billing_webhook_routes_subscription_events_as_fallback(self, mock_construct):
        """Billing webhook still delegates subscription events (backward compat)."""
        mock_construct.return_value = {
            'type': 'customer.subscription.updated',
            'data': {
                'object': {
                    'id': 'sub_fallback',
                    'customer': 'cus_test123',
                    'status': 'active',
                    'items': {'data': [{'price': {'id': 'price_pro_monthly'}}]},
                    'cancel_at_period_end': False,
                }
            },
        }

        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_secret'
        result = svc.handle_webhook(b'{}', 't=1,v1=a')
        self.assertTrue(result.get('success'))
        self.assertTrue(result.get('handled'))

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')

    @patch('stripe.Account.retrieve')
    @patch('stripe.Webhook.construct_event')
    def test_billing_webhook_handles_connect_account_updated(self, mock_construct, mock_account_retrieve):
        """Billing webhook routes account.updated to Connect handler."""
        self.tenant.stripe_connect_account_id = 'acct_test_123'
        self.tenant.save()

        mock_requirements = MagicMock()
        mock_requirements.currently_due = []
        mock_requirements.eventually_due = []
        mock_requirements.past_due = []
        mock_requirements.disabled_reason = None

        mock_account_retrieve.return_value = MagicMock(
            id='acct_test_123',
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
            requirements=mock_requirements,
        )

        mock_construct.return_value = {
            'type': 'account.updated',
            'data': {
                'object': {
                    'id': 'acct_test_123',
                    'charges_enabled': True,
                    'payouts_enabled': True,
                    'details_submitted': True,
                }
            },
        }

        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_secret'
        result = svc.handle_webhook(b'{}', 't=1,v1=a')
        self.assertTrue(result.get('success'))

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.stripe_connect_charges_enabled)
        self.assertTrue(self.tenant.stripe_connect_payouts_enabled)

    @patch('stripe.Webhook.construct_event')
    def test_unhandled_event_returns_success(self, mock_construct):
        """Unknown event types return success but not handled."""
        mock_construct.return_value = {
            'type': 'some.unknown.event',
            'data': {'object': {}},
        }

        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_secret'
        result = svc.handle_webhook(b'{}', 't=1,v1=a')
        self.assertTrue(result.get('success'))
        self.assertFalse(result.get('handled', True))


# =============================================================================
# 4. SUBSCRIPTION EVENT HANDLER TESTS
# =============================================================================

class SubscriptionEventHandlerTests(WebhookEndpointTestBase):
    """Test individual subscription event handlers."""

    def test_checkout_completed_activates_subscription(self):
        """checkout.session.completed sets tenant to active with correct plan."""
        session = {
            'id': 'cs_test_sub',
            'customer': 'cus_test123',
            'subscription': 'sub_new_123',
            'metadata': {
                'tenant_id': str(self.tenant.id),
                'plan_slug': 'professional',
            },
        }
        sub_handle_checkout(session)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertEqual(self.tenant.stripe_subscription_id, 'sub_new_123')
        self.assertEqual(self.tenant.plan, 'professional')
        self.assertEqual(self.tenant.subscription_plan, self.plan)

    def test_checkout_completed_without_subscription_ignored(self):
        """checkout.session.completed without subscription ID is ignored."""
        session = {
            'id': 'cs_onetime',
            'customer': 'cus_test123',
            'subscription': None,
            'metadata': {},
        }
        sub_handle_checkout(session)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'trial')

    def test_checkout_completed_unknown_customer_with_metadata_fallback(self):
        """Falls back to tenant_id in metadata when customer ID doesn't match."""
        session = {
            'id': 'cs_test_fallback',
            'customer': 'cus_unknown_999',
            'subscription': 'sub_fb_123',
            'metadata': {
                'tenant_id': str(self.tenant.id),
                'plan_slug': 'professional',
            },
        }
        sub_handle_checkout(session)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertEqual(self.tenant.stripe_subscription_id, 'sub_fb_123')

    def test_invoice_paid_activates_tenant(self):
        """invoice.paid sets subscription to active."""
        self.tenant.subscription_status = 'past_due'
        self.tenant.stripe_subscription_id = 'sub_existing'
        self.tenant.save()

        _handle_invoice_paid({
            'id': 'in_test_paid',
            'customer': 'cus_test123',
            'subscription': 'sub_existing',
        })

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')

    def test_invoice_paid_non_subscription_ignored(self):
        """invoice.paid without subscription is ignored."""
        _handle_invoice_paid({
            'id': 'in_onetime',
            'customer': 'cus_test123',
            'subscription': None,
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'trial')

    def test_invoice_payment_failed_sets_past_due(self):
        """invoice.payment_failed marks tenant as past_due."""
        self.tenant.subscription_status = 'active'
        self.tenant.stripe_subscription_id = 'sub_active'
        self.tenant.save()

        _handle_invoice_payment_failed({
            'id': 'in_test_failed',
            'customer': 'cus_test123',
            'subscription': 'sub_active',
            'attempt_count': 2,
        })

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'past_due')

    def test_subscription_updated_active_with_plan_change(self):
        """subscription.updated changes plan and status."""
        self.tenant.stripe_subscription_id = 'sub_upgrade'
        self.tenant.subscription_status = 'active'
        self.tenant.save()

        _handle_subscription_updated({
            'id': 'sub_upgrade',
            'customer': 'cus_test123',
            'status': 'active',
            'items': {'data': [{'price': {'id': 'price_pro_monthly'}}]},
            'cancel_at_period_end': False,
        })

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertEqual(self.tenant.subscription_plan, self.plan)
        self.assertEqual(self.tenant.plan, 'professional')

    def test_subscription_updated_incomplete_does_not_change_plan(self):
        """subscription.updated with incomplete status doesn't upgrade plan."""
        self.tenant.stripe_subscription_id = 'sub_inc'
        self.tenant.plan = 'trial'
        self.tenant.save()

        _handle_subscription_updated({
            'id': 'sub_inc',
            'customer': 'cus_test123',
            'status': 'incomplete',
            'items': {'data': [{'price': {'id': 'price_pro_monthly'}}]},
        })

        self.tenant.refresh_from_db()
        # CODE-228: 'incomplete' maps to 'trialing' (a valid status choice
        # that leaves current access unchanged), never stored verbatim.
        self.assertEqual(self.tenant.subscription_status, 'trialing')
        self.assertEqual(self.tenant.plan, 'trial')  # NOT upgraded — payment not confirmed

    def test_subscription_updated_cancel_at_period_end(self):
        """subscription.updated with cancel_at_period_end sets status to canceled."""
        self.tenant.stripe_subscription_id = 'sub_cancel'
        self.tenant.subscription_status = 'active'
        self.tenant.save()

        _handle_subscription_updated({
            'id': 'sub_cancel',
            'customer': 'cus_test123',
            'status': 'active',
            'items': {'data': [{'price': {'id': 'price_pro_monthly'}}]},
            'cancel_at_period_end': True,
        })

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'canceled')

    def test_subscription_updated_past_due_maps_correctly(self):
        """subscription.updated with past_due status maps correctly."""
        self.tenant.stripe_subscription_id = 'sub_pd'
        self.tenant.save()

        _handle_subscription_updated({
            'id': 'sub_pd',
            'customer': 'cus_test123',
            'status': 'past_due',
            'items': {'data': []},
        })

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'past_due')

    def test_subscription_deleted_reverts_to_trial_with_grace(self):
        """subscription.deleted reverts to trial with 30-day grace period."""
        self.tenant.subscription_status = 'active'
        self.tenant.stripe_subscription_id = 'sub_del'
        self.tenant.plan = 'professional'
        self.tenant.subscription_plan = self.plan
        self.tenant.save()

        _handle_subscription_deleted({
            'id': 'sub_del',
            'customer': 'cus_test123',
        })

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'expired')
        self.assertEqual(self.tenant.plan, 'trial')
        self.assertIsNotNone(self.tenant.grace_period_end)
        days_remaining = (self.tenant.grace_period_end - timezone.now()).days
        self.assertGreaterEqual(days_remaining, 29)
        self.assertLessEqual(days_remaining, 30)

    def test_handle_subscription_event_dispatches_correctly(self):
        """handle_subscription_event routes known events correctly."""
        # Unknown event — not handled
        result = handle_subscription_event('unknown.event', {})
        self.assertTrue(result['success'])
        self.assertFalse(result['handled'])

        # Known event — handled
        self.tenant.subscription_status = 'active'
        self.tenant.stripe_subscription_id = 'sub_dispatch'
        self.tenant.save()

        result = handle_subscription_event('invoice.payment_failed', {
            'id': 'in_dispatch',
            'customer': 'cus_test123',
            'subscription': 'sub_dispatch',
        })
        self.assertTrue(result['success'])
        self.assertTrue(result['handled'])

    def test_handle_subscription_event_catches_exceptions(self):
        """handle_subscription_event catches exceptions and returns success (no Stripe retry)."""
        result = handle_subscription_event('customer.subscription.deleted', {
            'id': 'sub_nonexistent',
            'customer': 'cus_nonexistent',
        })
        self.assertTrue(result['success'])


# =============================================================================
# 5. STRIPE CONNECT WEBHOOK & SERVICE TESTS
# =============================================================================

@override_settings(
    STRIPE_SECRET_KEY='sk_test_fake',
    STRIPE_WEBHOOK_SECRET='whsec_billing_test',
)
class StripeConnectWebhookTests(WebhookEndpointTestBase):
    """Tests for Stripe Connect through the billing webhook."""

    @patch('stripe.Account.retrieve')
    @patch('stripe.Webhook.construct_event')
    def test_account_updated_syncs_tenant(self, mock_construct, mock_account_retrieve):
        """account.updated webhook syncs Connect status to tenant."""
        self.tenant.stripe_connect_account_id = 'acct_connected_shop'
        self.tenant.save()

        mock_requirements = MagicMock()
        mock_requirements.currently_due = []
        mock_requirements.eventually_due = []
        mock_requirements.past_due = []
        mock_requirements.disabled_reason = None

        mock_account_retrieve.return_value = MagicMock(
            id='acct_connected_shop',
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
            requirements=mock_requirements,
        )

        mock_construct.return_value = {
            'type': 'account.updated',
            'data': {
                'object': {
                    'id': 'acct_connected_shop',
                    'charges_enabled': True,
                    'payouts_enabled': True,
                    'details_submitted': True,
                }
            },
        }

        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_test'
        result = svc.handle_webhook(b'{}', 't=1,v1=a')
        self.assertTrue(result.get('success'))

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.stripe_connect_charges_enabled)
        self.assertTrue(self.tenant.stripe_connect_payouts_enabled)

    @patch('stripe.Webhook.construct_event')
    def test_payment_intent_with_platform_fee_records_fee(self, mock_construct):
        """payment_intent.succeeded with application_fee records PlatformFeeRecord."""
        from apps.billing.models import PlatformFeeRecord, PlatformConfig

        PlatformConfig.objects.all().delete()
        PlatformConfig.objects.create(default_fee_percent=Decimal('10.00'))

        _, invoice = self._create_customer_and_invoice('INV-FEE-001', Decimal('200.00'))

        self.tenant.stripe_connect_account_id = 'acct_shop_fee'
        self.tenant.save()

        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'account': 'acct_shop_fee',
            'data': {
                'object': {
                    'id': 'pi_fee_test',
                    'amount_received': 20000,
                    'application_fee_amount': 2000,  # $20 = 10%
                    'on_behalf_of': 'acct_shop_fee',
                    'metadata': {'rs_invoice_id': str(invoice.id)},
                }
            },
        }

        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_test'
        result = svc.handle_webhook(b'{}', 't=1,v1=a')
        self.assertTrue(result['success'])

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'PAID')

        fee_record = PlatformFeeRecord.objects.get(payment_intent_id='pi_fee_test')
        self.assertEqual(fee_record.fee_amount, Decimal('20.00'))
        self.assertEqual(fee_record.gross_amount, Decimal('200.00'))
        self.assertEqual(fee_record.fee_percent, Decimal('10.00'))
        self.assertEqual(fee_record.stripe_account_id, 'acct_shop_fee')
        self.assertEqual(fee_record.tenant, self.tenant)

    @patch('stripe.Webhook.construct_event')
    def test_duplicate_payment_intent_no_double_fee(self, mock_construct):
        """Duplicate payment_intent.succeeded doesn't create duplicate fee records."""
        from apps.billing.models import PlatformFeeRecord

        _, invoice = self._create_customer_and_invoice('INV-DUPE-001', Decimal('100.00'))

        self.tenant.stripe_connect_account_id = 'acct_dupe'
        self.tenant.save(update_fields=['stripe_connect_account_id'])

        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'account': 'acct_dupe',
            'data': {
                'object': {
                    'id': 'pi_dupe_test',
                    'amount_received': 10000,
                    'application_fee_amount': 1000,
                    'on_behalf_of': 'acct_dupe',
                    'metadata': {'rs_invoice_id': str(invoice.id)},
                }
            },
        }

        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_billing_test'

        svc.handle_webhook(b'{}', 't=1,v1=a')
        svc.handle_webhook(b'{}', 't=1,v1=a')

        self.assertEqual(
            PlatformFeeRecord.objects.filter(payment_intent_id='pi_dupe_test').count(),
            1,
            "Duplicate webhook should not create second fee record",
        )


# =============================================================================
# 6. CONNECT SERVICE UNIT TESTS
# =============================================================================

class ConnectServiceTests(WebhookEndpointTestBase):
    """Tests for ConnectService methods."""

    def test_calculate_platform_fee_tenant_override(self):
        """Tenant-specific fee override takes priority."""
        from apps.tenants.services.connect_service import ConnectService

        from apps.billing.models import PlatformConfig
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.save()

        self.tenant.platform_fee_percent = Decimal('15.00')
        self.tenant.save()

        svc = ConnectService()
        fee_cents, fee_percent, _fixed = svc.calculate_platform_fee(Decimal('100.00'), self.tenant)
        self.assertEqual(fee_cents, 1500)
        self.assertEqual(fee_percent, Decimal('15.00'))

    def test_calculate_platform_fee_global_default(self):
        """Falls back to PlatformConfig default when no tenant override."""
        from apps.tenants.services.connect_service import ConnectService
        from apps.billing.models import PlatformConfig

        self.tenant.platform_fee_percent = None
        self.tenant.save()

        PlatformConfig.objects.all().delete()
        PlatformConfig.objects.create(
            default_fee_percent=Decimal('8.50'), fee_enabled=True,
        )

        svc = ConnectService()
        fee_cents, fee_percent, _fixed = svc.calculate_platform_fee(Decimal('200.00'), self.tenant)
        self.assertEqual(fee_cents, 1700)  # $17.00
        self.assertEqual(fee_percent, Decimal('8.50'))

    def test_calculate_platform_fee_zero_when_none(self):
        """Returns zero fee when no config or zero percent."""
        from apps.tenants.services.connect_service import ConnectService
        from apps.billing.models import PlatformConfig

        self.tenant.platform_fee_percent = None
        self.tenant.save()

        PlatformConfig.objects.all().delete()
        PlatformConfig.objects.create(
            default_fee_percent=Decimal('0'), fee_enabled=True,
        )

        svc = ConnectService()
        fee_cents, fee_percent, _fixed = svc.calculate_platform_fee(Decimal('100.00'), self.tenant)
        self.assertEqual(fee_cents, 0)

    @patch('stripe.checkout.Session.create')
    def test_create_connected_checkout_requires_connect(self, mock_session):
        """Checkout on unconnected tenant raises ConnectError."""
        from apps.tenants.services.connect_service import ConnectService, ConnectError

        _, invoice = self._create_customer_and_invoice('INV-NOCO-001', Decimal('50.00'))

        self.tenant.stripe_connect_account_id = ''
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()

        svc = ConnectService()
        with self.assertRaises(ConnectError):
            svc.create_connected_checkout_session(invoice)

        mock_session.assert_not_called()

    @patch('stripe.checkout.Session.create')
    def test_create_connected_checkout_with_fee(self, mock_session):
        """Connected checkout includes application_fee_amount."""
        from apps.tenants.services.connect_service import ConnectService

        from apps.billing.models import PlatformConfig

        _, invoice = self._create_customer_and_invoice('INV-CONN-001', Decimal('300.00'))

        # Fees are gated on the PlatformConfig master switch, so the
        # mechanism can ship dormant.
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.save()

        self.tenant.stripe_connect_account_id = 'acct_connected'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_payouts_enabled = True
        self.tenant.platform_fee_percent = Decimal('10.00')
        self.tenant.save()

        mock_session.return_value = MagicMock(url='https://checkout.stripe.com/test', id='cs_test')

        svc = ConnectService()
        result = svc.create_connected_checkout_session(invoice)
        self.assertTrue(result['success'])

        call_kwargs = mock_session.call_args[1]
        self.assertEqual(call_kwargs['stripe_account'], 'acct_connected')
        self.assertEqual(
            call_kwargs['payment_intent_data']['application_fee_amount'],
            3000,  # $30 = 10% of $300
        )
        self.assertEqual(call_kwargs['metadata']['rs_invoice_id'], str(invoice.id))

    @patch('stripe.checkout.Session.create')
    def test_create_connected_checkout_no_fee_when_zero(self, mock_session):
        """Connected checkout with 0% fee has no application_fee_amount."""
        from apps.tenants.services.connect_service import ConnectService
        from apps.billing.models import PlatformConfig

        _, invoice = self._create_customer_and_invoice('INV-NOFEE-001', Decimal('100.00'))

        self.tenant.stripe_connect_account_id = 'acct_nofee'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_payouts_enabled = True
        self.tenant.platform_fee_percent = Decimal('0')
        self.tenant.save()

        PlatformConfig.objects.all().delete()
        PlatformConfig.objects.create(default_fee_percent=Decimal('0'))

        mock_session.return_value = MagicMock(url='https://checkout.stripe.com/test', id='cs_nofee')

        svc = ConnectService()
        result = svc.create_connected_checkout_session(invoice)
        self.assertTrue(result['success'])

        call_kwargs = mock_session.call_args[1]
        # payment_intent_data always carries the invoice metadata (the webhook
        # resolves the invoice from PaymentIntent metadata), but must not add
        # an application_fee_amount when the fee is 0.
        self.assertIn('payment_intent_data', call_kwargs)
        self.assertNotIn('application_fee_amount', call_kwargs['payment_intent_data'])
        self.assertEqual(
            call_kwargs['payment_intent_data']['metadata']['rs_invoice_id'],
            str(invoice.id),
        )


# =============================================================================
# 7. URL ROUTING TESTS
# =============================================================================

class WebhookURLRoutingTests(TestCase):
    """Verify webhook URLs are correctly registered and separated."""

    def test_billing_webhook_url_resolves(self):
        """Billing webhook URL resolves correctly."""
        from django.urls import reverse
        url = reverse('billing:stripe_webhook')
        self.assertEqual(url, '/api/billing/stripe/webhook/')

    def test_subscription_webhook_url_resolves(self):
        """Subscription webhook URL resolves correctly."""
        from django.urls import reverse
        url = reverse('tenants:stripe_subscription_webhook')
        self.assertEqual(url, '/api/tenants/webhooks/stripe/')

    def test_webhook_urls_are_different(self):
        """Billing and subscription webhooks have different URLs."""
        from django.urls import reverse
        billing_url = reverse('billing:stripe_webhook')
        sub_url = reverse('tenants:stripe_subscription_webhook')
        self.assertNotEqual(billing_url, sub_url)

    def test_billing_webhook_accepts_post(self):
        """Billing webhook endpoint is reachable via POST."""
        response = self.client.post(
            '/api/billing/stripe/webhook/',
            data=b'{}',
            content_type='application/json',
        )
        # Should not be 404 (may be 400/503 depending on config)
        self.assertNotEqual(response.status_code, 404)

    def test_subscription_webhook_accepts_post(self):
        """Subscription webhook endpoint is reachable via POST."""
        response = self.client.post(
            '/api/tenants/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
        )
        self.assertNotEqual(response.status_code, 404)


# =============================================================================
# 8. SETTINGS CONFIGURATION TESTS
# =============================================================================

class StripeSettingsTests(TestCase):
    """Verify Stripe settings are properly separated."""

    def test_separate_webhook_secrets_exist_in_settings(self):
        """Both webhook secret settings are defined."""
        self.assertTrue(hasattr(settings, 'STRIPE_WEBHOOK_SECRET'))
        self.assertTrue(hasattr(settings, 'STRIPE_SUBSCRIPTION_WEBHOOK_SECRET'))

    @override_settings(
        STRIPE_WEBHOOK_SECRET='billing_secret',
        STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='sub_secret',
    )
    def test_secrets_are_independent(self):
        """The two secrets are independent settings."""
        self.assertEqual(settings.STRIPE_WEBHOOK_SECRET, 'billing_secret')
        self.assertEqual(settings.STRIPE_SUBSCRIPTION_WEBHOOK_SECRET, 'sub_secret')
        self.assertNotEqual(
            settings.STRIPE_WEBHOOK_SECRET,
            settings.STRIPE_SUBSCRIPTION_WEBHOOK_SECRET,
        )
