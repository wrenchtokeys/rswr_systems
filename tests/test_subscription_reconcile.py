"""
Subscription reconciliation — the safety net for lost subscription webhooks.

The invoice side has had `reconcile_stripe_payments` since the stripe-python
15.x outage; subscriptions had nothing. A webhook that was never delivered,
or was delivered and swallowed by the old blanket `return 200`, left the
tenant permanently wrong with no process that would ever notice: a shop that
paid stuck on plan='trial' until the trial clock locked them out, or a shop
that cancelled months ago still holding full access.

These tests cover the two things that actually matter: that the sweep
repairs drift using the *same* mapping a webhook would have applied, and
that a Stripe outage never gets mistaken for "nothing to do".
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, Tenant
from apps.tenants.services import subscription_reconcile as sr


CUSTOMER_ID = 'cus_rec123'
SUB_ID = 'sub_rec123'
STARTER_PRICE = 'price_starter_rec'
PRO_PRICE = 'price_pro_rec'


def stripe_subscription(status='active', price_id=STARTER_PRICE,
                        sub_id=SUB_ID, cancel_at_period_end=False,
                        interval='month'):
    """Basil-shaped subscription (period lives on the items)."""
    return {
        'id': sub_id,
        'status': status,
        'customer': CUSTOMER_ID,
        'cancel_at_period_end': cancel_at_period_end,
        'items': {'data': [{
            'id': 'si_rec',
            'current_period_end': 1767225600,
            'price': {'id': price_id, 'recurring': {'interval': interval}},
        }]},
    }


@override_settings(STRIPE_SECRET_KEY='sk_test_reconcile')
class ReconcileTestBase(TestCase):
    def setUp(self):
        self.starter, _ = SubscriptionPlan.objects.update_or_create(
            slug='starter',
            defaults={'name': 'Starter', 'monthly_price': Decimal('49.00'),
                      'stripe_price_id': STARTER_PRICE, 'is_active': True},
        )
        self.pro, _ = SubscriptionPlan.objects.update_or_create(
            slug='pro',
            defaults={'name': 'Pro', 'monthly_price': Decimal('99.00'),
                      'stripe_price_id': PRO_PRICE, 'is_active': True},
        )
        owner = get_user_model().objects.create_user(
            username='rec-owner', email='rec@test.com', password='pw123!',
        )
        self.tenant = Tenant.objects.create(
            name='Recon Shop', slug='recon-shop', owner=owner,
            plan='trial', subscription_status='trialing',
            stripe_customer_id=CUSTOMER_ID, stripe_subscription_id=SUB_ID,
        )

    def reload(self):
        self.tenant.refresh_from_db()
        return self.tenant


class ReconcileTenantTests(ReconcileTestBase):
    def test_repairs_a_paying_tenant_stuck_on_trial(self):
        """The headline failure: they paid, the webhook was lost, they're
        still on trial and will be locked out when the clock runs down."""
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            result = sr.reconcile_tenant(self.tenant, apply=True)

        tenant = self.reload()
        self.assertTrue(result['changed'])
        self.assertEqual(result['action'], 'updated')
        self.assertEqual(tenant.plan, 'starter')
        self.assertEqual(tenant.subscription_status, 'active')

    def test_in_sync_tenant_is_left_alone(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(
            plan='starter', subscription_plan=self.starter,
            subscription_status='active',
        )
        self.tenant.refresh_from_db()

        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            result = sr.reconcile_tenant(self.tenant, apply=True)

        self.assertFalse(result['changed'])
        self.assertEqual(result['action'], 'in_sync')

    def test_dry_run_reports_without_writing(self):
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            result = sr.reconcile_tenant(self.tenant, apply=False)

        self.assertEqual(result['action'], 'would_update')
        self.assertTrue(result['changed'])
        self.assertEqual(
            self.reload().plan, 'trial',
            "dry run must not write anything",
        )

    def test_canceled_subscription_expires_tenant(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(
            plan='starter', subscription_plan=self.starter,
            subscription_status='active',
        )
        self.tenant.refresh_from_db()

        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription(status='canceled')):
            sr.reconcile_tenant(self.tenant, apply=True)

        self.assertEqual(self.reload().subscription_status, 'canceled')

    def test_unpaid_expires_with_grace_period(self):
        """Terminal state must still leave read-only access, not a lockout."""
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription(status='unpaid')):
            sr.reconcile_tenant(self.tenant, apply=True)

        tenant = self.reload()
        self.assertEqual(tenant.subscription_status, 'expired')
        self.assertIsNotNone(tenant.grace_period_end)

    def test_incomplete_does_not_grant_the_paid_plan(self):
        """Checkout started but never paid must not upgrade anyone."""
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription(status='incomplete',
                                                    price_id=PRO_PRICE)):
            sr.reconcile_tenant(self.tenant, apply=True)

        tenant = self.reload()
        self.assertEqual(tenant.plan, 'trial', "unpaid tier must not be granted")
        self.assertEqual(tenant.subscription_status, 'trialing')

    def test_stale_subscription_id_falls_back_to_customer_lookup(self):
        """A cancel-then-resubscribe cycle leaves the stored id dead -- and
        that is precisely the tenant most likely to have drifted."""
        import stripe as stripe_mod

        with patch('stripe.Subscription.retrieve',
                   side_effect=stripe_mod.error.InvalidRequestError(
                       'No such subscription', None)), \
             patch('stripe.Subscription.list',
                   return_value={'data': [stripe_subscription(sub_id='sub_new')]}):
            result = sr.reconcile_tenant(self.tenant, apply=True)

        tenant = self.reload()
        self.assertTrue(result['changed'])
        self.assertEqual(tenant.stripe_subscription_id, 'sub_new')
        self.assertEqual(tenant.plan, 'starter')

    def test_no_subscription_in_stripe_is_reported_not_guessed(self):
        with patch('stripe.Subscription.retrieve', return_value=None), \
             patch('stripe.Subscription.list', return_value={'data': []}):
            result = sr.reconcile_tenant(self.tenant, apply=True)

        self.assertEqual(result['action'], 'no_subscription_in_stripe')
        self.assertEqual(self.reload().plan, 'trial')

    def test_stripe_outage_raises_and_changes_nothing(self):
        """An outage must never be mistaken for 'subscription is gone'."""
        import stripe as stripe_mod

        with patch('stripe.Subscription.retrieve',
                   side_effect=stripe_mod.error.APIConnectionError('down')):
            with self.assertRaises(sr.StripeUnavailable):
                sr.reconcile_tenant(self.tenant, apply=True)

        self.assertEqual(self.reload().subscription_status, 'trialing')

    def test_unmappable_price_warns_and_leaves_plan_alone(self):
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription(price_id='price_unknown')), \
             self.assertLogs('apps.tenants.services.subscription_reconcile',
                             level='WARNING') as logs:
            sr.reconcile_tenant(self.tenant, apply=True)

        self.assertTrue(any('matches no SubscriptionPlan' in m for m in logs.output))
        self.assertEqual(self.reload().plan, 'trial')

    def test_reconcile_stamps_the_watermark(self):
        """So a webhook created before this read can't overwrite it later."""
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            sr.reconcile_tenant(self.tenant, apply=True)

        self.assertIsNotNone(self.reload().subscription_synced_at)


class WebhookAndReconcileAgreeTests(ReconcileTestBase):
    """One mapping, two callers -- they must not drift apart."""

    def test_same_subscription_yields_same_state_either_way(self):
        from apps.tenants import webhooks

        subscription = stripe_subscription(status='active', price_id=PRO_PRICE)

        # Path 1: the webhook.
        event = {'id': 'evt_1', 'type': 'customer.subscription.updated',
                 'created': 1767225600, 'data': {'object': subscription}}
        webhooks._handle_subscription_updated(subscription, event=event)
        via_webhook = {
            'plan': self.reload().plan,
            'status': self.tenant.subscription_status,
        }

        # Reset, then Path 2: the reconciler.
        Tenant.objects.filter(pk=self.tenant.pk).update(
            plan='trial', subscription_plan=None,
            subscription_status='trialing', subscription_synced_at=None,
        )
        self.tenant.refresh_from_db()
        with patch('stripe.Subscription.retrieve', return_value=subscription):
            sr.reconcile_tenant(self.tenant, apply=True)
        via_reconcile = {
            'plan': self.reload().plan,
            'status': self.tenant.subscription_status,
        }

        self.assertEqual(via_webhook, via_reconcile)
        self.assertEqual(via_reconcile['plan'], 'pro')


class ReconcileAllTests(ReconcileTestBase):
    def test_sweep_counts_and_isolates_failures(self):
        """One tenant erroring must not abort the sweep."""
        import stripe as stripe_mod

        owner2 = get_user_model().objects.create_user(
            username='rec-owner2', email='rec2@test.com', password='pw123!',
        )
        Tenant.objects.create(
            name='Second Shop', slug='second-shop', owner=owner2,
            plan='trial', subscription_status='trialing',
            stripe_customer_id='cus_other', stripe_subscription_id='sub_other',
        )

        def retrieve(sub_id, *a, **kw):
            if sub_id == 'sub_other':
                raise stripe_mod.error.APIConnectionError('down')
            return stripe_subscription()

        with patch('stripe.Subscription.retrieve', side_effect=retrieve):
            summary = sr.reconcile_all(apply=True)

        self.assertEqual(summary['errors'], 1)
        self.assertEqual(summary['updated'], 1)
        self.assertEqual(self.reload().plan, 'starter')

    def test_sweep_skips_tenants_with_no_stripe_customer(self):
        owner3 = get_user_model().objects.create_user(
            username='rec-owner3', email='rec3@test.com', password='pw123!',
        )
        Tenant.objects.create(
            name='No Stripe', slug='no-stripe', owner=owner3,
            plan='trial', subscription_status='trialing',
            stripe_customer_id='',
        )

        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            summary = sr.reconcile_all(apply=True)

        self.assertEqual(summary['checked'], 1)

    def test_tenant_filter(self):
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            summary = sr.reconcile_all(apply=True, tenant_slug='recon-shop')
        self.assertEqual(summary['checked'], 1)


class ReconcileCommandTests(ReconcileTestBase):
    def test_command_dry_run_writes_nothing(self):
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            call_command('reconcile_subscriptions', '--dry-run', stdout=out)

        self.assertIn('dry run', out.getvalue())
        self.assertEqual(self.reload().plan, 'trial')

    def test_command_applies_and_warns_on_repair(self):
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        with patch('stripe.Subscription.retrieve',
                   return_value=stripe_subscription()):
            call_command('reconcile_subscriptions', stdout=out)

        output = out.getvalue()
        self.assertIn('check Stripe webhook health', output)
        self.assertEqual(self.reload().plan, 'starter')
