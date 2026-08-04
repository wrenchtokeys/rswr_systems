"""
Tests for Loyalty System Phase 1 — LOYALTY-001
PointTransaction ledger, LoyaltyConfig, LoyaltyService, the customer-anchored
completion-hook awards and ReferralService.
Includes regression tests for CODE-186: post_completion_hooks orchestrator.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import (
    LoyaltyConfig, PointTransaction, Reward, RewardOption, RewardRedemption,
    RewardType, ReferralCode, Referral,
)
from apps.rewards_referrals.services import LoyaltyService, ReferralService, RewardService
from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import Tenant
from core.models import Customer


def _make_tenant(name='Test Shop', slug=None):
    """Create a minimal tenant with required owner."""
    slug = slug or name.lower().replace(' ', '-')
    owner = User.objects.create_user(
        username=f'owner-{slug}',
        email=f'owner-{slug}@test.com',
        password='testpass123',
    )
    return Tenant.objects.create(name=name, slug=slug, owner=owner)


def _make_customer_user(tenant, email='test@example.com', is_primary=True):
    """Create User → Customer → CustomerUser chain."""
    user = User.objects.create_user(
        username=email.split('@')[0],
        email=email,
        password='testpass123',
    )
    customer = Customer.objects.create(
        name=f'Customer for {email}',
        tenant=tenant,
    )
    cu = CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=is_primary,
    )
    return cu


# ---------------------------------------------------------------------------
# LoyaltyConfig
# ---------------------------------------------------------------------------
class LoyaltyConfigTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()

    def test_get_for_tenant_creates_defaults(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.points_per_repair, 50)
        self.assertEqual(config.referral_bonus_referrer, 500)
        self.assertEqual(config.referral_bonus_referred, 100)
        self.assertEqual(config.milestone_5_bonus, 250)
        self.assertEqual(config.points_expiry_days, 365)
        self.assertEqual(config.program_name, 'Rewards')
        self.assertTrue(config.is_active)

    def test_get_for_tenant_returns_same(self):
        c1 = LoyaltyConfig.get_for_tenant(self.tenant)
        c2 = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(c1.pk, c2.pk)

    def test_custom_values(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 100
        config.program_name = 'Rockstar Rewards'
        config.save()
        refreshed = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(refreshed.points_per_repair, 100)
        self.assertEqual(refreshed.program_name, 'Rockstar Rewards')


# ---------------------------------------------------------------------------
# LoyaltyService.award_points
# ---------------------------------------------------------------------------
class LoyaltyServiceAwardTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        self.customer = self.cu.customer

    def test_basic_award(self):
        pt = LoyaltyService.award_points(
            self.customer, 50, 'repair_complete', 'Test repair',
        )
        self.assertIsNotNone(pt)
        self.assertEqual(pt.amount, 50)
        self.assertEqual(pt.balance_after, 50)
        self.assertEqual(pt.transaction_type, 'repair_complete')
        self.assertEqual(pt.tenant, self.tenant)

    def test_balance_accumulates(self):
        LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'R1')
        LoyaltyService.award_points(self.customer, 100, 'referral_made', 'Ref')
        self.assertEqual(LoyaltyService.get_balance(self.customer), 150)

    def test_negative_deduction(self):
        LoyaltyService.award_points(self.customer, 500, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.customer, -200, 'redemption', 'Redeem')
        self.assertEqual(pt.balance_after, 300)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 300)

    def test_inactive_config_returns_none(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Nope')
        self.assertIsNone(pt)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 0)

    def test_expiry_set_when_configured(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_expiry_days = 365
        config.save()
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Test')
        self.assertIsNotNone(pt.expires_at)
        # Should be ~365 days from now
        delta = pt.expires_at - timezone.now()
        self.assertAlmostEqual(delta.days, 365, delta=1)

    def test_no_expiry_when_zero(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_expiry_days = 0
        config.save()
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Test')
        self.assertIsNone(pt.expires_at)

    def test_no_expiry_on_deductions(self):
        LoyaltyService.award_points(self.customer, 500, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.customer, -100, 'redemption', 'Redeem')
        self.assertIsNone(pt.expires_at)

    def test_tenant_auto_resolved(self):
        """Tenant is resolved from the customer if not passed."""
        pt = LoyaltyService.award_points(
            self.customer, 50, 'repair_complete', 'Auto tenant',
        )
        self.assertEqual(pt.tenant, self.tenant)

    def test_created_by_recorded(self):
        admin = User.objects.create_user('admin', password='x')
        pt = LoyaltyService.award_points(
            self.customer, 100, 'manual_adjustment', 'Bonus', created_by=admin,
        )
        self.assertEqual(pt.created_by, admin)


# ---------------------------------------------------------------------------
# LoyaltyService read methods
# ---------------------------------------------------------------------------
class LoyaltyServiceReadTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        self.customer = self.cu.customer

    def test_get_balance_zero_for_new_user(self):
        self.assertEqual(LoyaltyService.get_balance(self.customer), 0)

    def test_get_transaction_history(self):
        for i in range(5):
            LoyaltyService.award_points(self.customer, 10, 'repair_complete', f'R{i}')
        history = LoyaltyService.get_transaction_history(self.customer, limit=3)
        self.assertEqual(len(history), 3)
        # Most recent first
        self.assertEqual(history[0].description, 'R4')

    def test_get_lifetime_earned(self):
        LoyaltyService.award_points(self.customer, 100, 'repair_complete', 'Earn')
        LoyaltyService.award_points(self.customer, 200, 'referral_made', 'Ref')
        LoyaltyService.award_points(self.customer, -50, 'redemption', 'Spend')
        self.assertEqual(LoyaltyService.get_lifetime_earned(self.customer), 300)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
class LoyaltyTenantIsolationTests(TestCase):
    def setUp(self):
        self.tenant_a = _make_tenant('Shop A', 'shop-a')
        self.tenant_b = _make_tenant('Shop B', 'shop-b')
        self.cu_a = _make_customer_user(self.tenant_a, 'a@test.com')
        self.cu_b = _make_customer_user(self.tenant_b, 'b@test.com')
        self.customer_a = self.cu_a.customer
        self.customer_b = self.cu_b.customer

    def test_points_isolated(self):
        LoyaltyService.award_points(self.customer_a, 100, 'repair_complete', 'A repair')
        LoyaltyService.award_points(self.customer_b, 200, 'repair_complete', 'B repair')
        self.assertEqual(LoyaltyService.get_balance(self.customer_a), 100)
        self.assertEqual(LoyaltyService.get_balance(self.customer_b), 200)

    def test_transaction_history_isolated(self):
        LoyaltyService.award_points(self.customer_a, 100, 'repair_complete', 'A')
        LoyaltyService.award_points(self.customer_b, 200, 'repair_complete', 'B')
        history_a = LoyaltyService.get_transaction_history(self.customer_a)
        self.assertEqual(len(history_a), 1)
        self.assertEqual(history_a[0].tenant, self.tenant_a)

    def test_config_isolated(self):
        config_a = LoyaltyConfig.get_for_tenant(self.tenant_a)
        config_a.points_per_repair = 75
        config_a.save()
        config_b = LoyaltyConfig.get_for_tenant(self.tenant_b)
        self.assertEqual(config_b.points_per_repair, 50)  # default


# ---------------------------------------------------------------------------
# Completion-hook point awards (loyalty_hook via Repair.save)
# ---------------------------------------------------------------------------
class AwardCompletionPointsTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        self.customer = self.cu.customer
        self.tech_user = User.objects.create_user('tech1', password='x')
        self.tech = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant,
        )

    def _make_repair(self, status='REQUESTED'):
        return Repair.objects.create(
            customer=self.cu.customer,
            technician=self.tech,
            tenant=self.tenant,
            unit_number='TEST-001',
            queue_status=status,
        )

    def test_completion_awards_config_points(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 75
        config.save()

        repair = self._make_repair('REQUESTED')
        repair.queue_status = 'COMPLETED'
        repair.save()

        self.assertEqual(LoyaltyService.get_balance(self.customer), 75)
        pt = PointTransaction.objects.filter(
            customer=self.customer, transaction_type='repair_complete',
        ).first()
        self.assertIsNotNone(pt)
        self.assertEqual(pt.amount, 75)
        self.assertEqual(pt.related_repair, repair)

    def test_completion_milestone_5(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        # Create 4 already-completed repairs
        for i in range(4):
            Repair.objects.create(
                customer=self.cu.customer, technician=self.tech,
                tenant=self.tenant, unit_number=f'U-{i}',
                queue_status='COMPLETED',
            )
        # 5th repair triggers milestone
        repair = self._make_repair('REQUESTED')
        repair.queue_status = 'COMPLETED'
        repair.save()

        expected = config.points_per_repair + config.milestone_5_bonus
        self.assertEqual(LoyaltyService.get_balance(self.customer), expected)

        milestone_tx = PointTransaction.objects.filter(
            customer=self.customer, transaction_type='milestone_bonus',
        ).first()
        self.assertIsNotNone(milestone_tx)
        self.assertEqual(milestone_tx.amount, config.milestone_5_bonus)

    def test_no_double_award_on_resave(self):
        repair = self._make_repair('REQUESTED')
        repair.queue_status = 'COMPLETED'
        repair.save()
        balance_after_first = LoyaltyService.get_balance(self.customer)

        # Resave as COMPLETED
        repair.save()
        self.assertEqual(LoyaltyService.get_balance(self.customer), balance_after_first)


# ---------------------------------------------------------------------------
# ReferralService uses LoyaltyService
# ---------------------------------------------------------------------------
class ReferralServiceLoyaltyTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.referrer = _make_customer_user(self.tenant, 'referrer@test.com')
        self.referred = _make_customer_user(self.tenant, 'referred@test.com')
        # Generate referral code
        self.code = ReferralCode.objects.create(
            code='REF123', customer_user=self.referrer,
        )

    def test_referral_awards_config_points(self):
        """record_referral moves no points; award_referral_bonuses pays config amounts."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.referral_bonus_referrer = 600
        config.referral_bonus_referred = 150
        config.save()

        result = ReferralService.record_referral(self.code, self.referred)
        self.assertTrue(result)
        # No points move at signup — the referral is PENDING until first job.
        self.assertEqual(LoyaltyService.get_balance(self.referrer.customer), 0)
        self.assertEqual(LoyaltyService.get_balance(self.referred.customer), 0)

        awarded = ReferralService.award_referral_bonuses(self.referred.customer)
        self.assertEqual(awarded, 1)
        self.assertEqual(LoyaltyService.get_balance(self.referrer.customer), 600)
        self.assertEqual(LoyaltyService.get_balance(self.referred.customer), 150)

    def test_referral_creates_transactions(self):
        ReferralService.record_referral(self.code, self.referred)
        ReferralService.award_referral_bonuses(self.referred.customer)

        referrer_tx = PointTransaction.objects.filter(
            customer=self.referrer.customer, transaction_type='referral_made',
        )
        self.assertEqual(referrer_tx.count(), 1)

        referred_tx = PointTransaction.objects.filter(
            customer=self.referred.customer, transaction_type='referral_received',
        )
        self.assertEqual(referred_tx.count(), 1)


# ---------------------------------------------------------------------------
# Redemption creates negative PointTransaction
# ---------------------------------------------------------------------------
class RedemptionLoyaltyTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        self.customer = self.cu.customer
        # Seed points
        LoyaltyService.award_points(self.customer, 500, 'manual_adjustment', 'Seed')
        # Create reward option
        self.reward_type = RewardType.objects.create(
            name='Repair Discount', category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE', discount_value=10,
        )
        self.option = RewardOption.objects.create(
            tenant=self.tenant, name='10% off',
            description='10% off next repair',
            points_required=200, reward_type=self.reward_type,
        )

    def test_redemption_deducts_and_logs(self):
        success, redemption = RewardService.redeem_reward(self.customer, self.option.pk)
        self.assertTrue(success)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 300)

        tx = PointTransaction.objects.filter(
            customer=self.customer, transaction_type='redemption',
        ).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, -200)
        self.assertEqual(tx.balance_after, 300)
        self.assertEqual(tx.related_redemption, redemption)

    def test_insufficient_points_rejected(self):
        expensive = RewardOption.objects.create(
            tenant=self.tenant, name='Free repair',
            description='Free repair', points_required=1000,
            reward_type=self.reward_type,
        )
        success, msg = RewardService.redeem_reward(self.customer, expensive.pk)
        self.assertFalse(success)
        self.assertIn('Not enough points', msg)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)


# ---------------------------------------------------------------------------
# Configurable point values
# ---------------------------------------------------------------------------
class ConfigurablePointValuesTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        self.customer = self.cu.customer

    def test_zero_points_per_repair(self):
        """Shop can set 0 points per repair (loyalty disabled for repairs)."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 0
        config.save()

        tech_user = User.objects.create_user('tech', password='x')
        tech = Technician.objects.create(user=tech_user, tenant=self.tenant)
        repair = Repair.objects.create(
            customer=self.cu.customer, technician=tech,
            tenant=self.tenant, unit_number='U-1',
            queue_status='REQUESTED',
        )
        repair.queue_status = 'COMPLETED'
        repair.save()

        # Should still get 0 from repair but no crash
        # (base_points=0 is valid — uses is not None check not truthiness)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 0)


# ---------------------------------------------------------------------------
# PointTransaction model
# ---------------------------------------------------------------------------
class PointTransactionModelTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        self.customer = self.cu.customer

    def test_str_positive(self):
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Test')
        self.assertIn('+50', str(pt))

    def test_str_negative(self):
        LoyaltyService.award_points(self.customer, 500, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.customer, -100, 'redemption', 'Spend')
        self.assertIn('-100', str(pt))

    def test_ordering_newest_first(self):
        pt1 = LoyaltyService.award_points(self.customer, 10, 'repair_complete', 'First')
        pt2 = LoyaltyService.award_points(self.customer, 20, 'repair_complete', 'Second')
        txs = list(PointTransaction.objects.filter(customer=self.customer))
        self.assertEqual(txs[0].pk, pt2.pk)


# ---------------------------------------------------------------------------
# CODE-186: post_completion_hooks orchestrator regression tests
# ---------------------------------------------------------------------------

class PostCompletionHooksOrchestratorTests(TestCase):
    """
    Regression tests for apps/technician_portal/hooks.py — the post-completion
    hook orchestrator introduced in CODE-186.

    These tests verify:
    1. The orchestrator runs and awards loyalty points (integration).
    2. A failing hook does NOT roll back the repair save.
    3. A failing hook does NOT block subsequent hooks.
    4. Placeholder hooks (warranty, review_request) run without error.
    5. post_completion_hooks() is called from Repair.save() on COMPLETED.
    """

    def setUp(self):
        self.tenant = _make_tenant('Orchestrator Shop', 'orch-shop')
        self.cu = _make_customer_user(self.tenant, 'orch@example.com')
        self.customer = self.cu.customer
        tech_user = User.objects.create_user('orch_tech', password='x')
        self.tech = Technician.objects.create(user=tech_user, tenant=self.tenant)
        LoyaltyConfig.get_for_tenant(self.tenant)  # ensure config exists

    def _make_repair(self, status='REQUESTED'):
        return Repair.objects.create(
            customer=self.cu.customer,
            technician=self.tech,
            tenant=self.tenant,
            unit_number='ORCH-001',
            queue_status=status,
        )

    # ------------------------------------------------------------------
    # 1. Orchestrator integration: loyalty points awarded via hooks.py
    # ------------------------------------------------------------------
    def test_orchestrator_awards_loyalty_points(self):
        """Completing a repair via save() triggers loyalty_hook and awards points."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 60
        config.save()

        repair = self._make_repair('REQUESTED')
        repair.queue_status = 'COMPLETED'
        repair.save()

        balance = LoyaltyService.get_balance(self.customer)
        self.assertEqual(balance, 60)

        tx = PointTransaction.objects.filter(
            customer=self.customer, transaction_type='repair_complete'
        ).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, 60)

    # ------------------------------------------------------------------
    # 2. Failing hook does NOT roll back the repair save
    # ------------------------------------------------------------------
    def test_failing_hook_does_not_roll_back_repair_save(self):
        """If a hook raises an exception, the repair save must still commit."""
        from apps.technician_portal import hooks

        original_hooks = hooks.COMPLETION_HOOKS[:]
        try:
            def exploding_hook(repair):
                raise RuntimeError("Simulated hook failure")

            hooks.COMPLETION_HOOKS = [('explode', exploding_hook)]

            repair = self._make_repair('REQUESTED')
            repair.queue_status = 'COMPLETED'
            repair.save()  # must NOT raise

            # Repair is saved despite the hook failing
            repair.refresh_from_db()
            self.assertEqual(repair.queue_status, 'COMPLETED')
        finally:
            hooks.COMPLETION_HOOKS = original_hooks

    # ------------------------------------------------------------------
    # 3. Failing hook does NOT block subsequent hooks
    # ------------------------------------------------------------------
    def test_failing_hook_does_not_block_subsequent_hooks(self):
        """A hook failure is isolated; the next hook in the list still runs."""
        from apps.technician_portal import hooks

        execution_order = []

        def first_hook(repair):
            execution_order.append('first')
            raise RuntimeError("First hook failed")

        def second_hook(repair):
            execution_order.append('second')

        original_hooks = hooks.COMPLETION_HOOKS[:]
        try:
            hooks.COMPLETION_HOOKS = [
                ('first', first_hook),
                ('second', second_hook),
            ]
            repair = self._make_repair('REQUESTED')
            repair.queue_status = 'COMPLETED'
            repair.save()

            self.assertIn('first', execution_order)
            self.assertIn('second', execution_order)
            self.assertEqual(execution_order.index('first'), 0)
            self.assertEqual(execution_order.index('second'), 1)
        finally:
            hooks.COMPLETION_HOOKS = original_hooks

    # ------------------------------------------------------------------
    # 4. Placeholder hooks (warranty, review_request) run without error
    # ------------------------------------------------------------------
    def test_placeholder_hooks_do_not_raise(self):
        """warranty_hook and review_request_hook are no-ops that must not raise."""
        from apps.technician_portal.hooks import warranty_hook, review_request_hook

        repair = self._make_repair('COMPLETED')
        # Force original_status so idempotency guard doesn't skip the loyalty hook
        repair.original_status = 'IN_PROGRESS'

        # These should silently do nothing
        try:
            warranty_hook(repair)
            review_request_hook(repair)
        except Exception as exc:
            self.fail(f"Placeholder hook raised unexpectedly: {exc}")

    # ------------------------------------------------------------------
    # 5. post_completion_hooks() called from Repair.save() on COMPLETED
    # ------------------------------------------------------------------
    def test_post_completion_hooks_called_on_completed_save(self):
        """Verify Repair.save() calls post_completion_hooks when COMPLETED."""
        from apps.technician_portal import hooks

        called_with = []

        def spy_hook(repair):
            called_with.append(repair.pk)

        original_hooks = hooks.COMPLETION_HOOKS[:]
        try:
            hooks.COMPLETION_HOOKS = [('spy', spy_hook)]

            repair = self._make_repair('REQUESTED')
            repair.queue_status = 'COMPLETED'
            repair.save()

            self.assertEqual(len(called_with), 1)
            self.assertEqual(called_with[0], repair.pk)
        finally:
            hooks.COMPLETION_HOOKS = original_hooks

    # ------------------------------------------------------------------
    # 6. post_completion_hooks() NOT called for non-COMPLETED saves
    # ------------------------------------------------------------------
    def test_post_completion_hooks_not_called_on_non_completed_save(self):
        """Hooks must NOT run when repair transitions to APPROVED or IN_PROGRESS."""
        from apps.technician_portal import hooks

        called_with = []

        def spy_hook(repair):
            called_with.append(repair.queue_status)

        original_hooks = hooks.COMPLETION_HOOKS[:]
        try:
            hooks.COMPLETION_HOOKS = [('spy', spy_hook)]

            repair = self._make_repair('REQUESTED')
            repair.queue_status = 'APPROVED'
            repair.save()

            repair.queue_status = 'IN_PROGRESS'
            repair.save()

            self.assertEqual(called_with, [],
                             "Hooks fired on non-COMPLETED status transition")
        finally:
            hooks.COMPLETION_HOOKS = original_hooks

    # ------------------------------------------------------------------
    # 7. Idempotency: hooks not called twice on re-save of COMPLETED repair
    # ------------------------------------------------------------------
    def test_hooks_not_called_on_resave_of_completed_repair(self):
        """Re-saving an already-COMPLETED repair must not run hooks again."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 50
        config.save()

        repair = self._make_repair('REQUESTED')
        repair.queue_status = 'COMPLETED'
        repair.save()

        balance_after_first = LoyaltyService.get_balance(self.customer)
        self.assertEqual(balance_after_first, 50)

        # Re-save without changing status
        repair.save()

        balance_after_resave = LoyaltyService.get_balance(self.customer)
        self.assertEqual(balance_after_resave, 50,
                         "Double award detected on re-save of already-COMPLETED repair")
