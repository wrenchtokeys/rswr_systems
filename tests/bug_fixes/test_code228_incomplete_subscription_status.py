"""
Regression tests for CODE-228: _handle_subscription_updated stores invalid
'incomplete' value in Tenant.subscription_status, which is not in the model's
choices list.

Bug: status_map in _handle_subscription_updated had:
    'incomplete': 'incomplete'
When Stripe fires customer.subscription.updated with status='incomplete'
(payment started but not confirmed), the webhook handler stored 'incomplete'
in subscription_status. This value is not in Tenant.SUBSCRIPTION_STATUS
choices (trialing/active/past_due/canceled/expired), violating data integrity.

Fix: Map 'incomplete' to 'trialing' (access unchanged, payment not confirmed).
The 'active' status arrives via invoice.paid when payment clears.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock

from apps.tenants.models import Tenant, SubscriptionPlan


class IncompleteSubscriptionStatusTest(TestCase):
    """Verify that incomplete Stripe subscription status doesn't store invalid value."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_test', email='owner@test.com', password='testpass',
        )
        # Get the trial plan that migration creates
        self.trial_plan = SubscriptionPlan.objects.filter(slug='trial').first()

        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop',
            owner=self.owner,
            stripe_subscription_id='sub_test123',
            stripe_customer_id='cus_test123',
            subscription_status='trialing',
        )

    def _make_stripe_subscription_event(self, status, cancel_at_period_end=False):
        """Return a mock Stripe subscription object."""
        return {
            'id': 'sub_test123',
            'customer': 'cus_test123',
            'status': status,
            'cancel_at_period_end': cancel_at_period_end,
            'items': {
                'data': [],  # No plan change in these tests
            },
        }

    def test_incomplete_status_maps_to_trialing_not_stored_as_invalid(self):
        """
        When Stripe sends status='incomplete', subscription_status must be set
        to 'trialing' (a valid choice), NOT 'incomplete' (invalid).
        """
        from apps.tenants.webhooks import _handle_subscription_updated

        subscription = self._make_stripe_subscription_event('incomplete')
        _handle_subscription_updated(subscription)

        self.tenant.refresh_from_db()
        valid_choices = {'trialing', 'active', 'past_due', 'canceled', 'expired'}

        self.assertIn(
            self.tenant.subscription_status, valid_choices,
            f"subscription_status '{self.tenant.subscription_status}' is not a valid choice",
        )
        self.assertEqual(
            self.tenant.subscription_status, 'trialing',
            "Incomplete Stripe subscription should map to 'trialing' status",
        )

    def test_incomplete_expired_maps_to_expired(self):
        """incomplete_expired should map to 'expired' (a valid choice)."""
        from apps.tenants.webhooks import _handle_subscription_updated

        subscription = self._make_stripe_subscription_event('incomplete_expired')
        _handle_subscription_updated(subscription)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'expired')

    def test_active_status_stays_active(self):
        """Active subscription status must remain 'active'."""
        from apps.tenants.webhooks import _handle_subscription_updated

        subscription = self._make_stripe_subscription_event('active')
        _handle_subscription_updated(subscription)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')

    def test_past_due_stays_past_due(self):
        """past_due Stripe status must map to 'past_due'."""
        from apps.tenants.webhooks import _handle_subscription_updated

        subscription = self._make_stripe_subscription_event('past_due')
        _handle_subscription_updated(subscription)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'past_due')

    def test_all_resulting_statuses_are_valid_choices(self):
        """
        For every Stripe status we handle, the resulting subscription_status
        must be one of the valid Tenant model choices.
        """
        from apps.tenants.webhooks import _handle_subscription_updated

        valid_choices = {'trialing', 'active', 'past_due', 'canceled', 'expired'}

        stripe_statuses = [
            'active', 'past_due', 'canceled', 'trialing',
            'incomplete', 'incomplete_expired', 'unpaid',
        ]

        for stripe_status in stripe_statuses:
            # Reset to trialing before each test
            self.tenant.subscription_status = 'trialing'
            self.tenant.save(update_fields=['subscription_status'])

            subscription = self._make_stripe_subscription_event(stripe_status)
            _handle_subscription_updated(subscription)

            self.tenant.refresh_from_db()
            self.assertIn(
                self.tenant.subscription_status, valid_choices,
                f"Stripe status='{stripe_status}' produced invalid "
                f"subscription_status='{self.tenant.subscription_status}'",
            )

    def test_incomplete_does_not_grant_active_access(self):
        """
        A tenant with an incomplete Stripe subscription should stay on 'trialing'
        status — not 'active'. This prevents unpaid access.
        """
        from apps.tenants.webhooks import _handle_subscription_updated

        self.tenant.subscription_status = 'trialing'
        self.tenant.save(update_fields=['subscription_status'])

        subscription = self._make_stripe_subscription_event('incomplete')
        _handle_subscription_updated(subscription)

        self.tenant.refresh_from_db()
        self.assertNotEqual(
            self.tenant.subscription_status, 'active',
            "Incomplete (unpaid) subscription must NOT grant active status",
        )
