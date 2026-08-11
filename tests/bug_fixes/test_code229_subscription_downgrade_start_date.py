"""
CODE-229 Regression Test: Subscription Downgrade Uses Past start_date

Bug: SubscriptionService.update_subscription() — downgrade path — called
stripe.SubscriptionSchedule.modify() with phases[0].start_date set to
subscription.current_period_start, which is always a Unix timestamp in the past.

Stripe rejects any phase start_date that is in the past with:
  InvalidRequestError: start_date must be after the current time

Fix: Use start_date='now' for the first phase in the schedule.

Impact: Every downgrade attempt would throw InvalidRequestError, caught by the
outer except block, and propagated as SubscriptionError to the owner UI —
downgrades were completely broken.
"""
import time
from decimal import Decimal
from unittest.mock import patch, MagicMock, call

from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant, SubscriptionPlan
from apps.tenants.services.subscription_service import SubscriptionService, SubscriptionError


def _make_mock_subscription(status='active', cancel_at_period_end=False):
    """Build a minimal mock Stripe Subscription object.

    Attribute access and __getitem__ must agree. This double previously set
    current_period_end as an attribute while its __getitem__ knew only
    'items' -- a real StripeObject resolves the same field either way, so the
    double silently disagreed with production. It also carries the period on
    the items, which is where Basil (2025-03-31) moved it and where the
    deployed SDK actually reports it.
    """
    now = int(time.time())
    period_start = now - (30 * 24 * 3600)   # 30 days ago (in the past)
    period_end = now + (0 * 24 * 3600 + 1)  # future (1 second from now)

    item = {
        'id': 'si_test',
        'current_period_start': period_start,
        'current_period_end': period_end,
        'price': {'id': 'price_pro_monthly', 'recurring': {'interval': 'month'}},
    }
    data = {
        'id': 'sub_test123',
        'status': status,
        'cancel_at_period_end': cancel_at_period_end,
        'current_period_start': period_start,
        'current_period_end': period_end,
        'items': {'data': [item]},
    }

    sub = MagicMock(**{k: v for k, v in data.items() if k != 'items'})
    sub.__getitem__ = lambda _self, key: data[key]
    sub.__contains__ = lambda _self, key: key in data
    sub.items = MagicMock()
    sub.items.data = [item]
    return sub


class SubscriptionDowngradeStartDateTest(TestCase):
    """Verify that the downgrade schedule uses start_date='now', not a past timestamp."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.owner = User.objects.create_user(
            username='downgrade_owner',
            email='downgrade@test.com',
            password='testpass123',
        )

        self.higher_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='pro',
            defaults={
                'name': 'Pro',
                'stripe_price_id': 'price_pro_monthly',
                'monthly_price': Decimal('99.00'),
                'max_repairs_per_month': 1000,
            },
        )

        self.lower_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='starter',
            defaults={
                'name': 'Starter',
                'stripe_price_id': 'price_starter_monthly',
                'monthly_price': Decimal('29.00'),
                'max_repairs_per_month': 100,
            },
        )

        self.tenant = Tenant.objects.create(
            name='Downgrade Test Shop',
            slug='downgrade-test-shop',
            owner=self.owner,
            stripe_customer_id='cus_downgrade123',
            stripe_subscription_id='sub_test123',
            subscription_status='active',
            plan='pro',
            subscription_plan=self.higher_plan,
            trial_started_at=timezone.now(),
        )

    @patch('apps.tenants.services.subscription_service.stripe.SubscriptionSchedule')
    @patch('apps.tenants.services.subscription_service.stripe.Subscription')
    def test_downgrade_uses_start_date_now(self, mock_sub_cls, mock_schedule_cls):
        """Downgrade path must pass start_date='now', not current_period_start."""
        mock_sub = _make_mock_subscription()
        mock_sub_cls.retrieve.return_value = mock_sub

        mock_schedule = MagicMock()
        mock_schedule.id = 'sub_sched_test'
        mock_schedule_cls.create.return_value = mock_schedule
        mock_schedule_cls.modify.return_value = mock_schedule

        svc = SubscriptionService()
        result = svc.update_subscription(self.tenant, 'starter')

        # Result should be 'scheduled' (downgrade, not upgrade)
        self.assertEqual(result['status'], 'scheduled')
        self.assertEqual(result['new_plan'], 'Starter')

        # Verify SubscriptionSchedule.create was called with from_subscription.
        # Assert the argument rather than the exact call -- an idempotency_key
        # rides along so a double-submit cannot create two schedules.
        mock_schedule_cls.create.assert_called_once()
        self.assertEqual(
            mock_schedule_cls.create.call_args.kwargs['from_subscription'],
            'sub_test123',
        )

        # Extract the phases passed to modify
        modify_call_kwargs = mock_schedule_cls.modify.call_args[1]
        phases = modify_call_kwargs['phases']

        self.assertEqual(len(phases), 2, "Expected exactly 2 phases")

        first_phase = phases[0]
        second_phase = phases[1]

        # ---- THE BUG CHECK ----
        # First phase start_date must be 'now', not a past Unix timestamp
        self.assertEqual(
            first_phase['start_date'],
            'now',
            f"First phase start_date should be 'now', got {first_phase['start_date']!r}. "
            f"A past Unix timestamp causes Stripe to reject the request with InvalidRequestError."
        )

        # First phase end_date should be the period end (future timestamp)
        self.assertIsNotNone(first_phase.get('end_date'))
        self.assertGreater(
            first_phase['end_date'],
            int(time.time()),
            "First phase end_date should be in the future"
        )

        # Second phase should start at the period end
        self.assertEqual(
            second_phase['start_date'],
            first_phase['end_date'],
            "Second phase should start when first phase ends"
        )

        # Second phase should use the lower plan's price
        self.assertEqual(
            second_phase['items'][0]['price'],
            'price_starter_monthly'
        )

    @patch('apps.tenants.services.subscription_service.stripe.SubscriptionSchedule')
    @patch('apps.tenants.services.subscription_service.stripe.Subscription')
    def test_downgrade_does_not_use_current_period_start(self, mock_sub_cls, mock_schedule_cls):
        """Verify past timestamp is never used as start_date in downgrade phases."""
        mock_sub = _make_mock_subscription()
        past_timestamp = mock_sub.current_period_start  # This is in the past

        mock_sub_cls.retrieve.return_value = mock_sub

        mock_schedule = MagicMock()
        mock_schedule.id = 'sub_sched_test2'
        mock_schedule_cls.create.return_value = mock_schedule
        mock_schedule_cls.modify.return_value = mock_schedule

        svc = SubscriptionService()
        svc.update_subscription(self.tenant, 'starter')

        modify_call_kwargs = mock_schedule_cls.modify.call_args[1]
        phases = modify_call_kwargs['phases']

        for i, phase in enumerate(phases):
            self.assertNotEqual(
                phase.get('start_date'),
                past_timestamp,
                f"Phase {i} start_date should never be the past current_period_start timestamp. "
                f"Stripe will reject it with InvalidRequestError."
            )

    @patch('apps.tenants.services.subscription_service.stripe.SubscriptionSchedule')
    @patch('apps.tenants.services.subscription_service.stripe.Subscription')
    def test_upgrade_does_not_use_schedule(self, mock_sub_cls, mock_schedule_cls):
        """Upgrade path should use Subscription.modify directly, not SubscriptionSchedule."""
        # Lower plan tenant upgrading to higher plan
        self.tenant.subscription_plan = self.lower_plan
        self.tenant.plan = 'starter'
        self.tenant.save(update_fields=['subscription_plan', 'plan'])

        mock_sub = _make_mock_subscription()
        mock_sub_cls.retrieve.return_value = mock_sub
        mock_sub_cls.modify.return_value = mock_sub

        svc = SubscriptionService()
        result = svc.update_subscription(self.tenant, 'pro')

        self.assertEqual(result['status'], 'pending')

        # SubscriptionSchedule should NOT be called for upgrades
        mock_schedule_cls.create.assert_not_called()
        mock_schedule_cls.modify.assert_not_called()

    @patch('apps.tenants.services.subscription_service.stripe.SubscriptionSchedule')
    @patch('apps.tenants.services.subscription_service.stripe.Subscription')
    def test_downgrade_schedule_end_behavior_is_release(self, mock_sub_cls, mock_schedule_cls):
        """end_behavior must be 'release' so the subscription continues normally after downgrade."""
        mock_sub = _make_mock_subscription()
        mock_sub_cls.retrieve.return_value = mock_sub

        mock_schedule = MagicMock()
        mock_schedule.id = 'sub_sched_end_behavior'
        mock_schedule_cls.create.return_value = mock_schedule
        mock_schedule_cls.modify.return_value = mock_schedule

        svc = SubscriptionService()
        svc.update_subscription(self.tenant, 'starter')

        modify_call_kwargs = mock_schedule_cls.modify.call_args[1]
        self.assertEqual(
            modify_call_kwargs.get('end_behavior'),
            'release',
            "end_behavior must be 'release' to convert schedule back to regular subscription"
        )
