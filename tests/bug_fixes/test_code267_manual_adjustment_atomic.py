"""
CODE-267: LoyaltyService.manual_adjustment() calls select_for_update() outside
          a transaction, causing TransactionManagementError when deducting points.

Root cause:
  LoyaltyService.manual_adjustment() had a balance check that called
  Reward.objects.select_for_update().get(pk=...) to lock the row before
  checking if a deduction would go below zero.  PostgreSQL requires
  select_for_update() to be called inside a transaction.atomic() block;
  without it, Django raises TransactionManagementError immediately.

Fix:
  Decorate manual_adjustment() with @transaction.atomic so the lock is always
  inside a transaction.  The nested @transaction.atomic on award_points() becomes
  a savepoint, which is safe.

Affected path:
  apps/rewards_referrals/services.py — LoyaltyService.manual_adjustment()
"""
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth.models import User
from django.db import transaction

from apps.rewards_referrals.services import LoyaltyService
from apps.rewards_referrals.models import LoyaltyConfig, Reward, PointTransaction
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.tenants.models import Tenant


class ManualAdjustmentAtomicTests(TestCase):
    """manual_adjustment() works correctly for both positive and negative amounts."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner267',
            email='owner267@example.com',
            password='testpass',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-267',
            is_active=True,
            owner=self.owner,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Customer 267',
            email='cust267@example.com',
        )
        self.customer_user = CustomerUser.objects.create(
            user=User.objects.create_user(
                username='custuser267',
                email='custuser267@example.com',
                password='pass',
            ),
            customer=self.customer,
            is_primary_contact=True,
        )
        # Ensure loyalty program is active
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = True
        config.save()

        # Seed the customer with 100 points
        LoyaltyService.award_points(
            customer_user=self.customer_user,
            amount=100,
            transaction_type='purchase',
            description='Initial seed',
            tenant=self.tenant,
        )

    def test_positive_adjustment_works(self):
        """Award points via manual_adjustment — should not raise."""
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=50,
            reason='Goodwill credit',
            created_by=self.owner,
            tenant=self.tenant,
        )
        self.assertIsNotNone(pt)
        self.assertEqual(pt.amount, 50)
        self.assertEqual(pt.balance_after, 150)

    def test_negative_adjustment_no_transaction_management_error(self):
        """
        Deducting points must NOT raise TransactionManagementError.

        Before CODE-267 fix, calling select_for_update() outside atomic() would
        raise TransactionManagementError on PostgreSQL.
        """
        # This should not raise TransactionManagementError or any DB error
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=-30,
            reason='Correction',
            created_by=self.owner,
            tenant=self.tenant,
        )
        self.assertIsNotNone(pt)
        self.assertEqual(pt.amount, -30)
        self.assertEqual(pt.balance_after, 70)

    def test_negative_adjustment_zero_balance_allowed(self):
        """Deducting the exact balance (result = 0) is allowed."""
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=-100,
            reason='Full correction',
            created_by=self.owner,
            tenant=self.tenant,
        )
        self.assertIsNotNone(pt)
        self.assertEqual(pt.balance_after, 0)

    def test_negative_adjustment_below_zero_raises(self):
        """Deducting more than balance raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            LoyaltyService.manual_adjustment(
                customer_user=self.customer_user,
                amount=-200,
                reason='Over-deduction',
                created_by=self.owner,
                tenant=self.tenant,
            )
        self.assertIn('below zero', str(ctx.exception))

    def test_zero_amount_raises(self):
        """Amount of zero raises ValueError."""
        with self.assertRaises(ValueError):
            LoyaltyService.manual_adjustment(
                customer_user=self.customer_user,
                amount=0,
                reason='Zero adjustment',
                created_by=self.owner,
                tenant=self.tenant,
            )

    def test_blank_reason_raises(self):
        """Blank reason raises ValueError."""
        with self.assertRaises(ValueError):
            LoyaltyService.manual_adjustment(
                customer_user=self.customer_user,
                amount=10,
                reason='',
                created_by=self.owner,
                tenant=self.tenant,
            )

    def test_inactive_loyalty_raises(self):
        """Adjustment while loyalty program inactive raises ValueError."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()

        with self.assertRaises(ValueError) as ctx:
            LoyaltyService.manual_adjustment(
                customer_user=self.customer_user,
                amount=10,
                reason='test',
                created_by=self.owner,
                tenant=self.tenant,
            )
        self.assertIn('inactive', str(ctx.exception))

    def test_transaction_logged_in_ledger(self):
        """Adjustment creates a PointTransaction with correct type."""
        LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=25,
            reason='Goodwill',
            created_by=self.owner,
            tenant=self.tenant,
        )
        pt = PointTransaction.objects.filter(
            customer_user=self.customer_user,
            transaction_type='manual_adjustment',
        ).last()
        self.assertIsNotNone(pt)
        self.assertIn('Goodwill', pt.description)
        self.assertEqual(pt.created_by, self.owner)
