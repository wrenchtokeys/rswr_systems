"""
Regression tests for A3 (Remediation Plan 2026-07-09):
Stale grace_period_end locked out paying tenants (CODE-130 regression).

Root cause:
    _handle_subscription_deleted sets grace_period_end = now + 30d, but NO
    reactivation path ever cleared it. After a lapse + resubscribe cycle the
    tenant carries a grace_period_end pointing at a date in the past. Months
    later the owner clicks "Cancel at period end" (status -> 'canceled',
    paid days remaining). The middleware's
        canceled_is_active = status == 'canceled' and not tenant.grace_period_end
    saw the stale timestamp, treated the cancellation as "access ended", and
    because the timestamp was long past, is_in_grace_period was False too:
    immediate full lockout of a paying customer.

Fix (two parts, both required):
    1. Every path that moves a tenant to active/trialing clears
       grace_period_end (checkout webhook, invoice.paid webhook,
       subscription.updated webhook, reactivate_subscription service,
       admin bulk activate).
    2. The middleware decides canceled_is_active from whether a grace period
       is CURRENT (grace_period_end in the future), not from raw truthiness.
       A past grace stamp on a 'canceled' tenant is equivalent to no grace.
       A genuinely 'expired' tenant with a past grace stamp stays BLOCKED.

State table encoded by the middleware after the fix:
    canceled + no grace stamp        -> ACTIVE (scheduled cancel, paid days remain)
    canceled + past grace stamp      -> ACTIVE (stale stamp; same as no stamp)
    canceled + future grace stamp    -> read-only grace
    expired  + future grace stamp    -> read-only grace
    expired  + past grace stamp      -> BLOCKED
    expired  + no grace stamp        -> BLOCKED
"""

from django.test import TestCase, Client
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan, Tenant
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants import webhooks


def _paid_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='starter',
        defaults={'name': 'Starter', 'monthly_price': 49, 'is_active': True},
    )
    return plan


class GracePeriodReactivationTests(TestCase):
    """A3: reactivation must clear grace_period_end; stale stamps must not lock out."""

    def setUp(self):
        self.client = Client()
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        self.plan = _paid_plan()
        result = create_tenant_with_owner(
            business_name='A3 Test Shop',
            email='owner_a3@test.com',
            password='testpass123!',
            first_name='AthreeOwner',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']

        # Simulate a paid subscription
        self.tenant.plan = self.plan.slug
        self.tenant.subscription_plan = self.plan
        self.tenant.subscription_status = 'active'
        self.tenant.stripe_customer_id = 'cus_a3test'
        self.tenant.stripe_subscription_id = 'sub_a3test'
        self.tenant.save()

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _get_dashboard(self):
        """Hit a non-exempt authenticated page through the middleware."""
        return self.client.get('/owner/')

    def test_a_deletion_webhook_sets_grace(self):
        webhooks._handle_subscription_deleted({
            'id': 'sub_a3test', 'customer': 'cus_a3test',
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'expired')
        self.assertIsNotNone(self.tenant.grace_period_end)

    def test_b_checkout_completed_clears_grace(self):
        # Lapse first
        webhooks._handle_subscription_deleted({
            'id': 'sub_a3test', 'customer': 'cus_a3test',
        })
        self.tenant.refresh_from_db()
        self.assertIsNotNone(self.tenant.grace_period_end)

        # Resubscribe via checkout
        webhooks._handle_checkout_completed({
            'customer': 'cus_a3test',
            'subscription': 'sub_a3new',
            'metadata': {'plan_slug': self.plan.slug},
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertIsNone(
            self.tenant.grace_period_end,
            "Reactivation must clear grace_period_end — a stale stamp is a "
            "time bomb that fires on the owner's next cancellation",
        )

    def test_c_invoice_paid_clears_grace(self):
        self.tenant.grace_period_end = timezone.now() - timezone.timedelta(days=90)
        self.tenant.save(update_fields=['grace_period_end'])

        webhooks._handle_invoice_paid({
            'customer': 'cus_a3test',
            'subscription': 'sub_a3test',
            'id': 'in_a3test',
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertIsNone(self.tenant.grace_period_end)

    def test_d_subscription_updated_active_clears_grace(self):
        self.tenant.grace_period_end = timezone.now() - timezone.timedelta(days=90)
        self.tenant.save(update_fields=['grace_period_end'])

        webhooks._handle_subscription_updated({
            'id': 'sub_a3test',
            'customer': 'cus_a3test',
            'status': 'active',
            'items': {'data': []},
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertIsNone(self.tenant.grace_period_end)

    def test_e_canceled_with_stale_grace_still_has_access(self):
        """The lockout scenario: stale past stamp + owner clicks cancel."""
        # Stale stamp from an old lapse (data that exists in prod today)
        self.tenant.grace_period_end = timezone.now() - timezone.timedelta(days=90)
        # Owner cancels at period end — paid days remain
        self.tenant.subscription_status = 'canceled'
        self.tenant.save(update_fields=['grace_period_end', 'subscription_status'])

        response = self._get_dashboard()
        self.assertEqual(
            response.status_code, 200,
            "A 'canceled' tenant with only a STALE grace stamp has paid days "
            "remaining and must keep full access (CODE-130 semantics)",
        )

    def test_f_canceled_without_grace_has_access(self):
        """Baseline CODE-130 behavior must keep working."""
        self.tenant.subscription_status = 'canceled'
        self.tenant.grace_period_end = None
        self.tenant.save(update_fields=['subscription_status', 'grace_period_end'])

        response = self._get_dashboard()
        self.assertEqual(response.status_code, 200)

    def test_g_canceled_with_current_grace_is_readonly(self):
        """A future grace stamp means the subscription actually ended: read-only."""
        self.tenant.subscription_status = 'canceled'
        self.tenant.grace_period_end = timezone.now() + timezone.timedelta(days=10)
        self.tenant.save(update_fields=['subscription_status', 'grace_period_end'])

        # GET allowed (grace, read-only)
        response = self._get_dashboard()
        self.assertEqual(response.status_code, 200)
        # Write blocked
        response = self.client.post('/owner/customers/add/', data={'name': 'X'})
        self.assertIn(response.status_code, (302, 402))

    def test_h_expired_with_past_grace_is_blocked(self):
        """An 'expired' tenant whose grace has lapsed must stay blocked."""
        self.tenant.subscription_status = 'expired'
        self.tenant.grace_period_end = timezone.now() - timezone.timedelta(days=5)
        self.tenant.save(update_fields=['subscription_status', 'grace_period_end'])

        response = self._get_dashboard()
        self.assertEqual(response.status_code, 302)
        self.assertIn('/subscription-blocked/', response['Location'])

    def test_i_expired_with_current_grace_is_readonly(self):
        self.tenant.subscription_status = 'expired'
        self.tenant.grace_period_end = timezone.now() + timezone.timedelta(days=10)
        self.tenant.save(update_fields=['subscription_status', 'grace_period_end'])

        response = self._get_dashboard()
        self.assertEqual(response.status_code, 200)
