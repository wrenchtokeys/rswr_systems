"""
Stripe API-version compatibility.

Two versions drift independently under this app: the SDK (which decides what
`stripe.api_version` defaults to, and therefore the shape of API *responses*)
and the version pinned on each webhook endpoint in the Stripe Dashboard
(which decides the shape of *inbound* payloads). They are configured in
different places and need not match.

The 2025-03-31 "Basil" release moved three fields this app reads:

    invoice.subscription        -> invoice.parent.subscription_details.subscription
    subscription.current_period_end
                                -> subscription.items.data[].current_period_end
    invoice.lines.data[].price  -> invoice.lines.data[].pricing.price_details.price

Production was verified on 2026-08-10 to be running stripe 15.4.0, whose
default API version is 2026-07-29.dahlia -- past all three. The failure mode
was silent in every case: the webhook handlers returned early (no payment
processed, no dunning email), the plan self-heal never fired, and every
downgrade raised AttributeError.

These tests feed BOTH payload shapes through the same code paths and assert
identical outcomes, so neither a Dashboard version bump nor an SDK upgrade
can quietly disable subscription billing again.
"""

from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.billing.services.stripe_compat import (
    configure_stripe,
    invoice_next_attempt,
    invoice_price_id,
    invoice_subscription_id,
    subscription_interval,
    subscription_item_id,
    subscription_period_end,
)
from apps.tenants.models import SubscriptionPlan, Tenant
from apps.tenants import webhooks


PRICE_ID = 'price_starter_monthly'
SUB_ID = 'sub_test123'
CUSTOMER_ID = 'cus_test123'


class StripeLike:
    """Mimics stripe-python 15.x StripeObject.

    Supports attribute access and __getitem__ but deliberately has NO .get(),
    because 15.x dropped dict inheritance -- calling .get() on a real API
    response raises AttributeError. Webhook payloads are re-parsed to plain
    dicts by the handler, but anything returned from stripe.*.retrieve()
    reaches our code in this form.
    """

    def __init__(self, data):
        self._data = {
            k: (StripeLike(v) if isinstance(v, dict)
                else [StripeLike(i) if isinstance(i, dict) else i for i in v]
                if isinstance(v, list) else v)
            for k, v in data.items()
        }

    def __getitem__(self, key):
        return self._data[key]

    def __getattr__(self, key):
        try:
            return self.__dict__['_data'][key]
        except KeyError:
            raise AttributeError(key)

    def __contains__(self, key):
        return key in self._data


def make_tenant(slug, **kwargs):
    """Tenant.owner is non-null; these tests don't exercise the signup path."""
    owner = get_user_model().objects.create_user(
        username=f'{slug}-owner', email=f'{slug}@test.com', password='pw123!',
    )
    return Tenant.objects.create(slug=slug, owner=owner, **kwargs)


# ----------------------------------------------------------------------
# Payload fixtures -- the same logical event in both shapes
# ----------------------------------------------------------------------

def pre_basil_invoice(**overrides):
    payload = {
        'id': 'in_test123',
        'customer': CUSTOMER_ID,
        'subscription': SUB_ID,
        'billing_reason': 'subscription_cycle',
        'attempt_count': 1,
        'next_payment_attempt': 1767225600,
        'lines': {'data': [{'price': {'id': PRICE_ID}}]},
    }
    payload.update(overrides)
    return payload


def basil_invoice(**overrides):
    """Basil+: no top-level `subscription`, no line `price`."""
    payload = {
        'id': 'in_test123',
        'customer': CUSTOMER_ID,
        'billing_reason': 'subscription_cycle',
        'attempt_count': 1,
        'next_payment_attempt': 1767225600,
        'parent': {
            'type': 'subscription_details',
            'subscription_details': {'subscription': SUB_ID},
        },
        'lines': {
            'data': [{
                'pricing': {
                    'type': 'price_details',
                    'price_details': {'price': PRICE_ID},
                },
                'parent': {
                    'subscription_item_details': {'subscription': SUB_ID},
                },
            }],
        },
    }
    payload.update(overrides)
    return payload


def pre_basil_subscription(**overrides):
    payload = {
        'id': SUB_ID,
        'status': 'active',
        'customer': CUSTOMER_ID,
        'current_period_end': 1767225600,
        'current_period_start': 1764547200,
        'items': {'data': [{
            'id': 'si_test123',
            'price': {'id': PRICE_ID, 'recurring': {'interval': 'month'}},
        }]},
    }
    payload.update(overrides)
    return payload


def basil_subscription(**overrides):
    """Basil+: period moved onto the items."""
    payload = {
        'id': SUB_ID,
        'status': 'active',
        'customer': CUSTOMER_ID,
        'items': {'data': [{
            'id': 'si_test123',
            'current_period_end': 1767225600,
            'current_period_start': 1764547200,
            'price': {'id': PRICE_ID, 'recurring': {'interval': 'month'}},
        }]},
    }
    payload.update(overrides)
    return payload


class ApiVersionPinTests(SimpleTestCase):
    """The pin must exist and actually reach the stripe module."""

    def test_setting_is_defined_and_non_empty(self):
        self.assertTrue(
            getattr(settings, 'STRIPE_API_VERSION', ''),
            "STRIPE_API_VERSION must be pinned; leaving it unset makes the "
            "payload shape a function of whichever SDK the last build resolved."
        )

    def test_configure_stripe_applies_the_pin(self):
        import stripe
        original = stripe.api_version
        try:
            stripe.api_version = 'bogus'
            with self.settings(STRIPE_SECRET_KEY='sk_test_x'):
                configure_stripe()
            self.assertEqual(stripe.api_version, settings.STRIPE_API_VERSION)
        finally:
            stripe.api_version = original


class CompatAccessorTests(SimpleTestCase):
    """Each accessor returns the same value from either shape."""

    def test_invoice_subscription_id(self):
        self.assertEqual(invoice_subscription_id(pre_basil_invoice()), SUB_ID)
        self.assertEqual(invoice_subscription_id(basil_invoice()), SUB_ID)

    def test_invoice_subscription_id_expanded_object(self):
        """Expandable fields may arrive as the full object, not an id."""
        expanded = pre_basil_invoice(subscription={'id': SUB_ID, 'object': 'subscription'})
        self.assertEqual(invoice_subscription_id(expanded), SUB_ID)

    def test_invoice_subscription_id_absent_for_one_off(self):
        one_off = {'id': 'in_x', 'customer': CUSTOMER_ID, 'billing_reason': 'manual'}
        self.assertIsNone(invoice_subscription_id(one_off))

    def test_invoice_price_id(self):
        self.assertEqual(invoice_price_id(pre_basil_invoice()), PRICE_ID)
        self.assertEqual(invoice_price_id(basil_invoice()), PRICE_ID)

    def test_invoice_price_id_missing_lines(self):
        self.assertEqual(invoice_price_id({'id': 'in_x'}), '')

    def test_subscription_period_end(self):
        self.assertEqual(subscription_period_end(pre_basil_subscription()), 1767225600)
        self.assertEqual(subscription_period_end(basil_subscription()), 1767225600)

    def test_subscription_period_end_takes_latest_item(self):
        """A phase must not end before any item's paid-through date."""
        sub = basil_subscription(items={'data': [
            {'id': 'si_1', 'current_period_end': 1767225600},
            {'id': 'si_2', 'current_period_end': 1769904000},
        ]})
        self.assertEqual(subscription_period_end(sub), 1769904000)

    def test_subscription_period_end_unknown_shape_returns_none(self):
        """Unknown shape must degrade to None, not raise."""
        self.assertIsNone(subscription_period_end({'id': SUB_ID}))

    def test_subscription_item_id(self):
        self.assertEqual(subscription_item_id(pre_basil_subscription()), 'si_test123')
        self.assertEqual(subscription_item_id(basil_subscription()), 'si_test123')

    def test_subscription_interval(self):
        self.assertEqual(subscription_interval(pre_basil_subscription()), 'month')
        annual = basil_subscription(items={'data': [{
            'id': 'si_a',
            'price': {'id': 'price_annual', 'recurring': {'interval': 'year'}},
        }]})
        self.assertEqual(subscription_interval(annual), 'year')

    def test_invoice_next_attempt(self):
        self.assertEqual(invoice_next_attempt(basil_invoice()), 1767225600)
        self.assertIsNone(invoice_next_attempt(basil_invoice(next_payment_attempt=None)))

    def test_accessors_tolerate_stripe_objects_without_get(self):
        """stripe-python 15.x StripeObject has __getitem__ but no .get()."""
        obj = StripeLike(basil_subscription())
        self.assertFalse(hasattr(obj, 'get'), "fixture must mimic 15.x")
        self.assertEqual(subscription_period_end(obj), 1767225600)
        self.assertEqual(subscription_item_id(obj), 'si_test123')
        self.assertEqual(subscription_interval(obj), 'month')

        inv = StripeLike(basil_invoice())
        self.assertEqual(invoice_subscription_id(inv), SUB_ID)
        self.assertEqual(invoice_price_id(inv), PRICE_ID)


class WebhookShapeToleranceTests(TestCase):
    """Both payload shapes must drive identical tenant state."""

    def setUp(self):
        # Plans are seeded by migration, so update rather than create.
        self.plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='starter',
            defaults={'name': 'Starter', 'monthly_price': Decimal('49.00'),
                      'stripe_price_id': PRICE_ID, 'is_active': True},
        )
        self.tenant = make_tenant(
            'shape-shop', name='Shape Shop',
            plan='trial', subscription_status='trialing',
            stripe_customer_id=CUSTOMER_ID,
        )

    def _reload(self):
        self.tenant.refresh_from_db()
        return self.tenant

    def test_invoice_paid_activates_under_both_shapes(self):
        for name, invoice in (('pre-basil', pre_basil_invoice()),
                              ('basil', basil_invoice())):
            with self.subTest(shape=name):
                Tenant.objects.filter(pk=self.tenant.pk).update(
                    subscription_status='trialing', plan='trial',
                    stripe_subscription_id='',
                )
                webhooks._handle_invoice_paid(invoice)
                tenant = self._reload()
                self.assertEqual(tenant.subscription_status, 'active')
                self.assertEqual(tenant.stripe_subscription_id, SUB_ID)

    def test_plan_self_heal_fires_under_both_shapes(self):
        """A lost checkout webhook must still be recovered from invoice.paid."""
        for name, invoice in (('pre-basil', pre_basil_invoice()),
                              ('basil', basil_invoice())):
            with self.subTest(shape=name):
                Tenant.objects.filter(pk=self.tenant.pk).update(
                    plan='trial', subscription_plan=None,
                    subscription_status='trialing',
                )
                webhooks._handle_invoice_paid(invoice)
                tenant = self._reload()
                self.assertEqual(
                    tenant.plan, 'starter',
                    f"{name}: plan was not self-healed from the invoice price",
                )
                self.assertEqual(tenant.subscription_plan_id, self.plan.id)

    def test_payment_failed_sets_past_due_under_both_shapes(self):
        for name, invoice in (('pre-basil', pre_basil_invoice()),
                              ('basil', basil_invoice())):
            with self.subTest(shape=name):
                Tenant.objects.filter(pk=self.tenant.pk).update(
                    subscription_status='active',
                )
                with patch.object(webhooks, '_notify_owners_and_managers'):
                    webhooks._handle_invoice_payment_failed(invoice)
                self.assertEqual(self._reload().subscription_status, 'past_due')

    def test_one_off_invoice_is_still_ignored(self):
        """The early return must survive -- just not fire on a shape change."""
        one_off = {'id': 'in_oneoff', 'customer': CUSTOMER_ID,
                   'billing_reason': 'manual'}
        Tenant.objects.filter(pk=self.tenant.pk).update(
            subscription_status='trialing')
        webhooks._handle_invoice_paid(one_off)
        self.assertEqual(self._reload().subscription_status, 'trialing')


class DowngradePeriodEndTests(TestCase):
    """The downgrade path read a field Basil deleted."""

    def setUp(self):
        self.starter, _ = SubscriptionPlan.objects.update_or_create(
            slug='starter',
            defaults={'name': 'Starter', 'monthly_price': Decimal('49.00'),
                      'stripe_price_id': PRICE_ID, 'is_active': True},
        )
        self.pro, _ = SubscriptionPlan.objects.update_or_create(
            slug='pro',
            defaults={'name': 'Pro', 'monthly_price': Decimal('99.00'),
                      'stripe_price_id': 'price_pro_monthly', 'is_active': True},
        )
        self.tenant = make_tenant(
            'down-shop', name='Down Shop', plan='pro',
            subscription_status='active', subscription_plan=self.pro,
            stripe_customer_id=CUSTOMER_ID, stripe_subscription_id=SUB_ID,
        )

    def test_downgrade_schedules_against_basil_subscription(self):
        from apps.tenants.services.subscription_service import SubscriptionService

        with patch('stripe.Subscription.retrieve',
                   return_value=StripeLike(basil_subscription())), \
             patch('stripe.SubscriptionSchedule.create',
                   return_value=type('S', (), {'id': 'sub_sched_1'})()), \
             patch('stripe.SubscriptionSchedule.modify') as mock_modify:
            result = SubscriptionService().update_subscription(self.tenant, 'starter')

        self.assertEqual(result['status'], 'scheduled')
        phases = mock_modify.call_args.kwargs['phases']
        self.assertEqual(phases[0]['end_date'], 1767225600)
        self.assertEqual(phases[1]['start_date'], 1767225600)
        self.assertEqual(phases[1]['items'][0]['price'], PRICE_ID)

    def test_downgrade_fails_loudly_when_period_end_is_unknown(self):
        """An unrecognised shape must raise a clear error, not AttributeError."""
        from apps.tenants.services.subscription_service import (
            SubscriptionError, SubscriptionService,
        )

        shapeless = StripeLike({'id': SUB_ID, 'status': 'active',
                                'items': {'data': [{'id': 'si_x'}]}})
        with patch('stripe.Subscription.retrieve', return_value=shapeless), \
             patch('stripe.SubscriptionSchedule.create',
                   return_value=type('S', (), {'id': 'sub_sched_1'})()):
            with self.assertRaises(SubscriptionError):
                SubscriptionService().update_subscription(self.tenant, 'starter')

    def test_upgrade_resolves_item_id_from_either_shape(self):
        from apps.tenants.services.subscription_service import SubscriptionService

        for name, sub in (('pre-basil', StripeLike(pre_basil_subscription())),
                          ('basil', StripeLike(basil_subscription()))):
            with self.subTest(shape=name):
                Tenant.objects.filter(pk=self.tenant.pk).update(
                    subscription_plan=self.starter, plan='starter')
                self.tenant.refresh_from_db()
                with patch('stripe.Subscription.retrieve', return_value=sub), \
                     patch('stripe.Subscription.modify') as mock_modify:
                    SubscriptionService().update_subscription(self.tenant, 'pro')
                items = mock_modify.call_args.kwargs['items']
                self.assertEqual(items[0]['id'], 'si_test123')
