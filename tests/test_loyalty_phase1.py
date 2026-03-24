"""
Tests for Loyalty System Phase 1 — LOYALTY-001
PointTransaction ledger, LoyaltyConfig, LoyaltyService, refactored
award_completion_points and ReferralService.
"""
from datetime import timedelta
from decimal import Decimal

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

    def test_basic_award(self):
        pt = LoyaltyService.award_points(
            self.cu, 50, 'repair_complete', 'Test repair',
        )
        self.assertIsNotNone(pt)
        self.assertEqual(pt.amount, 50)
        self.assertEqual(pt.balance_after, 50)
        self.assertEqual(pt.transaction_type, 'repair_complete')
        self.assertEqual(pt.tenant, self.tenant)

    def test_balance_accumulates(self):
        LoyaltyService.award_points(self.cu, 50, 'repair_complete', 'R1')
        LoyaltyService.award_points(self.cu, 100, 'referral_made', 'Ref')
        self.assertEqual(LoyaltyService.get_balance(self.cu), 150)

    def test_negative_deduction(self):
        LoyaltyService.award_points(self.cu, 500, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.cu, -200, 'redemption', 'Redeem')
        self.assertEqual(pt.balance_after, 300)
        self.assertEqual(LoyaltyService.get_balance(self.cu), 300)

    def test_inactive_config_returns_none(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()
        pt = LoyaltyService.award_points(self.cu, 50, 'repair_complete', 'Nope')
        self.assertIsNone(pt)
        self.assertEqual(LoyaltyService.get_balance(self.cu), 0)

    def test_expiry_set_when_configured(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_expiry_days = 365
        config.save()
        pt = LoyaltyService.award_points(self.cu, 50, 'repair_complete', 'Test')
        self.assertIsNotNone(pt.expires_at)
        # Should be ~365 days from now
        delta = pt.expires_at - timezone.now()
        self.assertAlmostEqual(delta.days, 365, delta=1)

    def test_no_expiry_when_zero(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_expiry_days = 0
        config.save()
        pt = LoyaltyService.award_points(self.cu, 50, 'repair_complete', 'Test')
        self.assertIsNone(pt.expires_at)

    def test_no_expiry_on_deductions(self):
        LoyaltyService.award_points(self.cu, 500, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.cu, -100, 'redemption', 'Redeem')
        self.assertIsNone(pt.expires_at)

    def test_tenant_auto_resolved(self):
        """Tenant is resolved from customer_user if not passed."""
        pt = LoyaltyService.award_points(
            self.cu, 50, 'repair_complete', 'Auto tenant',
        )
        self.assertEqual(pt.tenant, self.tenant)

    def test_created_by_recorded(self):
        admin = User.objects.create_user('admin', password='x')
        pt = LoyaltyService.award_points(
            self.cu, 100, 'manual_adjustment', 'Bonus', created_by=admin,
        )
        self.assertEqual(pt.created_by, admin)


# ---------------------------------------------------------------------------
# LoyaltyService read methods
# ---------------------------------------------------------------------------
class LoyaltyServiceReadTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)

    def test_get_balance_zero_for_new_user(self):
        self.assertEqual(LoyaltyService.get_balance(self.cu), 0)

    def test_get_transaction_history(self):
        for i in range(5):
            LoyaltyService.award_points(self.cu, 10, 'repair_complete', f'R{i}')
        history = LoyaltyService.get_transaction_history(self.cu, limit=3)
        self.assertEqual(len(history), 3)
        # Most recent first
        self.assertEqual(history[0].description, 'R4')

    def test_get_lifetime_earned(self):
        LoyaltyService.award_points(self.cu, 100, 'repair_complete', 'Earn')
        LoyaltyService.award_points(self.cu, 200, 'referral_made', 'Ref')
        LoyaltyService.award_points(self.cu, -50, 'redemption', 'Spend')
        self.assertEqual(LoyaltyService.get_lifetime_earned(self.cu), 300)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
class LoyaltyTenantIsolationTests(TestCase):
    def setUp(self):
        self.tenant_a = _make_tenant('Shop A', 'shop-a')
        self.tenant_b = _make_tenant('Shop B', 'shop-b')
        self.cu_a = _make_customer_user(self.tenant_a, 'a@test.com')
        self.cu_b = _make_customer_user(self.tenant_b, 'b@test.com')

    def test_points_isolated(self):
        LoyaltyService.award_points(self.cu_a, 100, 'repair_complete', 'A repair')
        LoyaltyService.award_points(self.cu_b, 200, 'repair_complete', 'B repair')
        self.assertEqual(LoyaltyService.get_balance(self.cu_a), 100)
        self.assertEqual(LoyaltyService.get_balance(self.cu_b), 200)

    def test_transaction_history_isolated(self):
        LoyaltyService.award_points(self.cu_a, 100, 'repair_complete', 'A')
        LoyaltyService.award_points(self.cu_b, 200, 'repair_complete', 'B')
        history_a = LoyaltyService.get_transaction_history(self.cu_a)
        self.assertEqual(len(history_a), 1)
        self.assertEqual(history_a[0].tenant, self.tenant_a)

    def test_config_isolated(self):
        config_a = LoyaltyConfig.get_for_tenant(self.tenant_a)
        config_a.points_per_repair = 75
        config_a.save()
        config_b = LoyaltyConfig.get_for_tenant(self.tenant_b)
        self.assertEqual(config_b.points_per_repair, 50)  # default


# ---------------------------------------------------------------------------
# award_completion_points refactor
# ---------------------------------------------------------------------------
class AwardCompletionPointsTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
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

        self.assertEqual(LoyaltyService.get_balance(self.cu), 75)
        pt = PointTransaction.objects.filter(
            customer_user=self.cu, transaction_type='repair_complete',
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
        self.assertEqual(LoyaltyService.get_balance(self.cu), expected)

        milestone_tx = PointTransaction.objects.filter(
            customer_user=self.cu, transaction_type='milestone_bonus',
        ).first()
        self.assertIsNotNone(milestone_tx)
        self.assertEqual(milestone_tx.amount, config.milestone_5_bonus)

    def test_no_double_award_on_resave(self):
        repair = self._make_repair('REQUESTED')
        repair.queue_status = 'COMPLETED'
        repair.save()
        balance_after_first = LoyaltyService.get_balance(self.cu)

        # Resave as COMPLETED
        repair.save()
        self.assertEqual(LoyaltyService.get_balance(self.cu), balance_after_first)


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
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.referral_bonus_referrer = 600
        config.referral_bonus_referred = 150
        config.save()

        result = ReferralService.process_referral(self.code, self.referred)
        self.assertTrue(result)
        self.assertEqual(LoyaltyService.get_balance(self.referrer), 600)
        self.assertEqual(LoyaltyService.get_balance(self.referred), 150)

    def test_referral_creates_transactions(self):
        ReferralService.process_referral(self.code, self.referred)

        referrer_tx = PointTransaction.objects.filter(
            customer_user=self.referrer, transaction_type='referral_made',
        )
        self.assertEqual(referrer_tx.count(), 1)

        referred_tx = PointTransaction.objects.filter(
            customer_user=self.referred, transaction_type='referral_received',
        )
        self.assertEqual(referred_tx.count(), 1)


# ---------------------------------------------------------------------------
# Redemption creates negative PointTransaction
# ---------------------------------------------------------------------------
class RedemptionLoyaltyTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)
        # Seed points
        LoyaltyService.award_points(self.cu, 500, 'manual_adjustment', 'Seed')
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
        success, redemption = RewardService.redeem_reward(self.cu, self.option.pk)
        self.assertTrue(success)
        self.assertEqual(LoyaltyService.get_balance(self.cu), 300)

        tx = PointTransaction.objects.filter(
            customer_user=self.cu, transaction_type='redemption',
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
        success, msg = RewardService.redeem_reward(self.cu, expensive.pk)
        self.assertFalse(success)
        self.assertIn('Not enough points', msg)
        self.assertEqual(LoyaltyService.get_balance(self.cu), 500)


# ---------------------------------------------------------------------------
# Configurable point values
# ---------------------------------------------------------------------------
class ConfigurablePointValuesTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)

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
        self.assertEqual(LoyaltyService.get_balance(self.cu), 0)


# ---------------------------------------------------------------------------
# PointTransaction model
# ---------------------------------------------------------------------------
class PointTransactionModelTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()
        self.cu = _make_customer_user(self.tenant)

    def test_str_positive(self):
        pt = LoyaltyService.award_points(self.cu, 50, 'repair_complete', 'Test')
        self.assertIn('+50', str(pt))

    def test_str_negative(self):
        LoyaltyService.award_points(self.cu, 500, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.cu, -100, 'redemption', 'Spend')
        self.assertIn('-100', str(pt))

    def test_ordering_newest_first(self):
        pt1 = LoyaltyService.award_points(self.cu, 10, 'repair_complete', 'First')
        pt2 = LoyaltyService.award_points(self.cu, 20, 'repair_complete', 'Second')
        txs = list(PointTransaction.objects.filter(customer_user=self.cu))
        self.assertEqual(txs[0].pk, pt2.pk)
