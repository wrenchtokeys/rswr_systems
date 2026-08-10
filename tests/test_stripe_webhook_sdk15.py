"""
Regression tests for the stripe-python v15 webhook outage.

stripe-python 15.x removed dict inheritance from StripeObject: a real
`stripe.Event` no longer supports `.get(...)`, so `event.get('account')`
raised AttributeError and EVERY delivery to /api/billing/stripe/webhook/
returned HTTP 500. Customer payments succeeded on Stripe but invoices
stayed UNPAID and no receipts were sent (first hit in production
2026-08-05; a real $137.19 customer payment was lost to it 2026-08-08).

The dedicated subscription endpoint had the mirror-image failure mode:
handlers call `session.get(...)`, the exception was swallowed, and the
endpoint returned 200 — a silent no-op.

The fix re-parses the signature-verified raw payload into plain dicts, so
handlers no longer depend on the SDK's object model. These tests feed the
webhook a construct_event return value shaped like a v15 Event (supports
__getitem__ but NOT .get) and assert end-to-end processing still works.
"""

import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone


class V15StyleEvent:
    """Mimics stripe-python 15.x Event: subscriptable, but no dict methods."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __getattr__(self, key):
        # Mirrors stripe._stripe_object.StripeObject.__getattr__: attribute
        # access falls through to the payload, and 'get' is not a payload key.
        try:
            return self._data[key]
        except KeyError as err:
            raise AttributeError(*err.args) from err


class StripeSdk15WebhookTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        from django.contrib.auth import get_user_model
        from apps.tenants.models import Tenant, SubscriptionPlan

        User = get_user_model()
        self.owner = User.objects.create_user(
            username='sdk15owner', email='sdk15@test.com', password='x',
        )
        self.tenant = Tenant.objects.create(
            name='SDK15 Shop',
            slug='sdk15-shop',
            owner=self.owner,
            stripe_customer_id='cus_sdk15',
            stripe_connect_account_id='acct_sdk15',
            subscription_status='trial',
            plan='trial',
            trial_started_at=timezone.now(),
        )
        self.plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='professional',
            defaults={
                'name': 'Professional',
                'stripe_price_id': 'price_sdk15_monthly',
                'monthly_price': Decimal('49.00'),
                'max_repairs_per_month': 500,
            },
        )

        from core.models import Customer
        from apps.billing.models import Invoice
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='SDK15 Fleet', email='fleet@sdk15.test',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-SDK15-1',
            subtotal=Decimal('137.19'),
            total=Decimal('137.19'),
            status='SENT',
        )

    def _billing_svc(self):
        from apps.billing.services.stripe_service import StripeService
        svc = StripeService()
        svc.enabled = True
        svc.webhook_secret = 'whsec_test'
        return svc

    @patch('stripe.Webhook.construct_event')
    def test_payment_intent_succeeded_with_v15_event_marks_invoice_paid(
            self, mock_construct):
        event_dict = {
            'id': 'evt_sdk15_pi',
            'type': 'payment_intent.succeeded',
            'account': 'acct_sdk15',
            'data': {
                'object': {
                    'id': 'pi_sdk15',
                    'amount_received': 13719,
                    'metadata': {'rs_invoice_id': str(self.invoice.id)},
                }
            },
        }
        payload = json.dumps(event_dict).encode()
        mock_construct.return_value = V15StyleEvent(event_dict)

        result = self._billing_svc().handle_webhook(payload, 't=1,v1=sig')

        self.assertTrue(result['success'])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(self.invoice.amount_paid, Decimal('137.19'))
        self.assertEqual(
            self.invoice.payments.filter(stripe_payment_id='pi_sdk15').count(), 1,
        )

    @patch('stripe.Webhook.construct_event')
    def test_checkout_completed_with_v15_event_marks_invoice_paid(
            self, mock_construct):
        event_dict = {
            'id': 'evt_sdk15_cs',
            'type': 'checkout.session.completed',
            'account': 'acct_sdk15',
            'data': {
                'object': {
                    'id': 'cs_sdk15',
                    'mode': 'payment',
                    'payment_status': 'paid',
                    'amount_total': 13719,
                    'payment_intent': 'pi_sdk15_cs',
                    'metadata': {'rs_invoice_id': str(self.invoice.id)},
                }
            },
        }
        payload = json.dumps(event_dict).encode()
        mock_construct.return_value = V15StyleEvent(event_dict)

        result = self._billing_svc().handle_webhook(payload, 't=1,v1=sig')

        self.assertTrue(result['success'])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

    @override_settings(STRIPE_SUBSCRIPTION_WEBHOOK_SECRET='whsec_sub_test')
    @patch('stripe.Webhook.construct_event')
    def test_subscription_webhook_with_v15_event_activates_tenant(
            self, mock_construct):
        from apps.tenants.webhooks import stripe_subscription_webhook

        event_dict = {
            'id': 'evt_sdk15_sub',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_sdk15_sub',
                    'mode': 'subscription',
                    'customer': 'cus_sdk15',
                    'subscription': 'sub_sdk15',
                    'payment_status': 'paid',
                    'metadata': {
                        'tenant_id': str(self.tenant.id),
                        'plan_slug': 'professional',
                    },
                }
            },
        }
        payload = json.dumps(event_dict).encode()
        mock_construct.return_value = V15StyleEvent(event_dict)

        request = self.factory.post(
            '/api/tenants/webhooks/stripe/',
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=1,v1=sig',
        )
        response = stripe_subscription_webhook(request)

        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertEqual(self.tenant.stripe_subscription_id, 'sub_sdk15')
        self.assertEqual(self.tenant.plan, 'professional')
