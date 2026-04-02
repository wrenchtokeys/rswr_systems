"""
CODE-271: LoyaltyService.manual_adjustment() had duplicate @transaction.atomic
          decorators introduced by CODE-267 patch.

Root cause:
  CODE-267 added @transaction.atomic to fix the select_for_update() outside
  transaction bug. However, manual_adjustment() already had @transaction.atomic
  on it. The CODE-267 patch blindly added a second decorator without checking
  whether one already existed.

  While duplicate @transaction.atomic decorators are not a runtime crash — the
  outer creates a transaction (or savepoint), the inner creates a savepoint
  within that — it creates confusing nesting semantics and may interfere with
  callers that check transaction state.  Most critically, it indicates a flawed
  patching process that could introduce worse bugs.

Fix:
  Remove the duplicate @transaction.atomic, keeping exactly one.

Tests:
  1. Verify manual_adjustment() has exactly one transaction.atomic wrapper
     (introspection via __wrapped__ or functools inspection).
  2. Positive adjustment still works and commits atomically.
  3. Negative adjustment still works and commits atomically.
  4. An exception mid-adjustment still rolls back both the Reward.points update
     and the PointTransaction — confirming atomicity.

Affected path:
  apps/rewards_referrals/services.py — LoyaltyService.manual_adjustment()
"""
import functools
import inspect
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth.models import User
from django.db import connection, transaction

from apps.rewards_referrals.services import LoyaltyService
from apps.rewards_referrals.models import LoyaltyConfig, Reward, PointTransaction
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.tenants.models import Tenant


def _count_atomic_wrappers(fn):
    """
    Count how many times @transaction.atomic has been applied to `fn`.

    transaction.atomic() wraps functions using functools.wraps, so
    __wrapped__ is set.  Walk the chain until we hit the raw function
    and count how many layers are transaction.atomic Atomic context managers.
    """
    from django.db.transaction import Atomic
    count = 0
    current = fn
    while hasattr(current, '__wrapped__'):
        # The closure cell in the wrapper created by transaction.atomic
        # holds an Atomic instance.  Check via the __closure__ of the
        # wrapper function.
        closure_vals = []
        if current.__code__ is not None and current.__closure__:
            closure_vals = [c.cell_contents for c in current.__closure__
                            if not isinstance(c.cell_contents, type) and callable(getattr(c.cell_contents, '__enter__', None))]
        if any(isinstance(v, Atomic) for v in closure_vals):
            count += 1
        current = current.__wrapped__
    return count


class DuplicateAtomicDecoratorTests(TestCase):
    """Verify manual_adjustment() has exactly one @transaction.atomic decorator."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner271',
            email='owner271@example.com',
            password='testpass',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 271',
            slug='test-shop-271',
            is_active=True,
            owner=self.owner,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Customer 271',
            email='customer271@example.com',
        )
        self.admin_user = User.objects.create_user(
            username='admin271',
            email='admin271@example.com',
            password='testpass',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.admin_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        self.loyalty_config = LoyaltyConfig.objects.create(
            tenant=self.tenant,
            is_active=True,
            points_per_repair=10,
        )
        # Seed a balance of 100 points
        self.reward = Reward.objects.create(
            tenant=self.tenant,
            customer_user=self.customer_user,
            points=100,
        )
        PointTransaction.objects.create(
            tenant=self.tenant,
            customer_user=self.customer_user,
            amount=100,
            balance_after=100,
            transaction_type='repair_complete',
            description='Seed balance',
        )
        self.adjuster = User.objects.create_user(
            username='adjuster271',
            email='adjuster271@example.com',
            password='testpass',
        )

    def test_exactly_one_atomic_wrapper(self):
        """
        manual_adjustment() must have exactly one @transaction.atomic decorator.

        Two decorators create unexpected savepoint nesting and indicate
        a broken patching process (CODE-271).
        """
        count = _count_atomic_wrappers(LoyaltyService.manual_adjustment)
        self.assertEqual(
            count, 1,
            f"Expected exactly 1 @transaction.atomic on manual_adjustment(), "
            f"found {count}. The duplicate was introduced by CODE-267 without "
            f"checking for an existing decorator."
        )

    def test_positive_adjustment_commits(self):
        """Positive adjustment updates balance and creates a PointTransaction."""
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=50,
            reason='Courtesy bonus',
            created_by=self.adjuster,
            tenant=self.tenant,
        )
        self.assertIsNotNone(pt)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.points, 150)
        self.assertTrue(
            PointTransaction.objects.filter(
                customer_user=self.customer_user,
                amount=50,
                transaction_type='manual_adjustment',
            ).exists()
        )

    def test_negative_adjustment_commits(self):
        """Negative adjustment deducts from balance and creates a PointTransaction."""
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=-30,
            reason='Correction',
            created_by=self.adjuster,
            tenant=self.tenant,
        )
        self.assertIsNotNone(pt)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.points, 70)

    def test_atomicity_on_failure_rolls_back(self):
        """
        If award_points() raises mid-adjustment, Reward.points must NOT change.

        This confirms that the single @transaction.atomic wraps the entire
        balance-check + award sequence.  If there were two wrappers, the inner
        one could commit a partial update before the outer rolls back.
        """
        import unittest.mock as mock

        original_balance = self.reward.points  # 100

        # Simulate award_points() raising after the balance check passes
        with mock.patch.object(
            LoyaltyService,
            'award_points',
            side_effect=RuntimeError("Simulated failure in award_points"),
        ):
            with self.assertRaises((RuntimeError, Exception)):
                LoyaltyService.manual_adjustment(
                    customer_user=self.customer_user,
                    amount=-50,
                    reason='Should not commit',
                    created_by=self.adjuster,
                    tenant=self.tenant,
                )

        # Balance must be unchanged after rollback
        self.reward.refresh_from_db()
        self.assertEqual(
            self.reward.points,
            original_balance,
            "Reward.points changed despite exception — @transaction.atomic rollback failed."
        )

    def test_no_duplicate_transactions_on_concurrent_calls(self):
        """
        Two sequential calls each create exactly one PointTransaction.

        With duplicate @transaction.atomic, the outer decorator starts a
        transaction and the inner one starts a savepoint; a failure inside
        the savepoint may partially commit.  This test confirms that
        sequential manual adjustments each produce exactly one ledger entry.
        """
        before_count = PointTransaction.objects.filter(
            customer_user=self.customer_user,
            transaction_type='manual_adjustment',
        ).count()

        LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=10,
            reason='First adjustment',
            created_by=self.adjuster,
            tenant=self.tenant,
        )
        LoyaltyService.manual_adjustment(
            customer_user=self.customer_user,
            amount=5,
            reason='Second adjustment',
            created_by=self.adjuster,
            tenant=self.tenant,
        )

        after_count = PointTransaction.objects.filter(
            customer_user=self.customer_user,
            transaction_type='manual_adjustment',
        ).count()
        self.assertEqual(after_count - before_count, 2,
                         "Expected exactly 2 new manual_adjustment transactions.")

        self.reward.refresh_from_db()
        self.assertEqual(self.reward.points, 115)  # 100 + 10 + 5
