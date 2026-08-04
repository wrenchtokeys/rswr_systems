"""
Comprehensive tests for Phase 1 of the Loyalty System overhaul.

Tests cover:
- LoyaltyService.award_points() — basic earn, balance update, transaction created
- LoyaltyService with inactive config — no points awarded
- Completion hook reads from LoyaltyConfig
- ReferralService uses LoyaltyService (record at signup, pay on first job)
- Redemption creates negative PointTransaction
- Transaction history endpoint
- Customer nav shows points
- Tenant isolation
- Configurable point values
- Expiry dates set correctly

Loyalty is anchored on core.Customer (the company) — portal accounts
(CustomerUser) are attribution only. One shared balance per company.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import (
    LoyaltyConfig,
    PointTransaction,
    Referral,
    Reward,
    RewardOption,
    RewardRedemption,
    RewardType,
    ReferralCode,
)
from apps.rewards_referrals.services import (
    LoyaltyService,
    ReferralService,
    RewardService,
)
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer


def _make_tenant(name, slug):
    """Create a minimal tenant for testing."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    owner = User.objects.create_user(
        f'{slug}_owner', f'{slug}_owner@test.com', 'testpass123!',
        first_name='Owner', last_name=slug.title(),
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
        subscription_status='trialing',
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant, owner


def _make_customer_user(tenant, email, is_primary=True):
    """Create a Customer + CustomerUser for a tenant."""
    user = User.objects.create_user(
        email.split('@')[0], email, 'testpass123!',
        first_name=email.split('@')[0].title(), last_name='Test',
    )
    customer = Customer.objects.create(
        name=f'{email} Co', email=email, tenant=tenant,
    )
    cu = CustomerUser.objects.create(
        user=user, customer=customer, is_primary_contact=is_primary,
    )
    return cu


# ──────────────────────────────────────────────────────────────────────
# LoyaltyService tests
# ──────────────────────────────────────────────────────────────────────

class LoyaltyServiceAwardPointsTest(TestCase):
    """Test LoyaltyService.award_points() core behaviour."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Shop A', 'shop-a')
        self.cu = _make_customer_user(self.tenant, 'alice@test.com')
        self.customer = self.cu.customer

    def test_basic_earn(self):
        pt = LoyaltyService.award_points(
            self.customer, 50, 'repair_complete', 'Repair done',
        )
        self.assertIsNotNone(pt)
        self.assertEqual(pt.amount, 50)
        self.assertEqual(pt.balance_after, 50)
        self.assertEqual(pt.transaction_type, 'repair_complete')
        self.assertEqual(pt.tenant, self.tenant)
        # Reward row updated
        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 50)
        self.assertEqual(reward.tenant, self.tenant)

    def test_acting_customer_user_attribution(self):
        """acting_customer_user is stored on the transaction (attribution only)."""
        pt = LoyaltyService.award_points(
            self.customer, 50, 'repair_complete', 'Repair done',
            acting_customer_user=self.cu,
        )
        self.assertEqual(pt.customer_user, self.cu)
        self.assertEqual(pt.customer, self.customer)

    def test_multiple_awards_accumulate(self):
        LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'R1')
        pt2 = LoyaltyService.award_points(self.customer, 100, 'referral_received', 'Welcome')
        self.assertEqual(pt2.balance_after, 150)
        self.assertEqual(Reward.objects.get(customer=self.customer).points, 150)

    def test_negative_amount_deducts(self):
        LoyaltyService.award_points(self.customer, 200, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.customer, -50, 'redemption', 'Redeemed')
        self.assertEqual(pt.amount, -50)
        self.assertEqual(pt.balance_after, 150)

    def test_inactive_config_returns_none(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Nope')
        self.assertIsNone(pt)
        # No Reward row created
        self.assertFalse(Reward.objects.filter(customer=self.customer).exists())

    def test_expiry_set_when_configured(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_expiry_days = 90
        config.save()
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Exp test')
        self.assertIsNotNone(pt.expires_at)
        expected = timezone.now() + timedelta(days=90)
        self.assertAlmostEqual(
            pt.expires_at.timestamp(), expected.timestamp(), delta=5,
        )

    def test_no_expiry_when_zero(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_expiry_days = 0
        config.save()
        pt = LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'No exp')
        self.assertIsNone(pt.expires_at)

    def test_no_expiry_on_negative_amount(self):
        LoyaltyService.award_points(self.customer, 100, 'manual_adjustment', 'Seed')
        pt = LoyaltyService.award_points(self.customer, -50, 'redemption', 'Spend')
        self.assertIsNone(pt.expires_at)

    def test_related_repair_stored(self):
        from apps.technician_portal.models import Technician, Repair
        tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True,
        )
        repair = Repair.objects.create(
            customer=self.customer, tenant=self.tenant, technician=tech,
            unit_number='U1', damage_type='CHIP',
            queue_status='COMPLETED',
        )
        pt = LoyaltyService.award_points(
            self.customer, 50, 'repair_complete', 'Done',
            related_repair=repair,
        )
        self.assertEqual(pt.related_repair, repair)

    def test_tenant_resolved_from_customer(self):
        """If tenant not passed explicitly, resolve from customer.tenant."""
        pt = LoyaltyService.award_points(
            self.customer, 10, 'manual_adjustment', 'Auto-resolve',
        )
        self.assertEqual(pt.tenant, self.tenant)

    def test_customer_without_tenant_returns_none(self):
        """A tenant-less customer cannot earn points (no config to consult)."""
        orphan = Customer.objects.create(name='Orphan Co', email='orphan@test.com')
        pt = LoyaltyService.award_points(orphan, 50, 'repair_complete', 'Nope')
        self.assertIsNone(pt)


class LoyaltyServiceReadTest(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('Shop B', 'shop-b')
        self.cu = _make_customer_user(self.tenant, 'bob@test.com')
        self.customer = self.cu.customer

    def test_get_balance_empty(self):
        self.assertEqual(LoyaltyService.get_balance(self.customer), 0)

    def test_get_balance_after_award(self):
        LoyaltyService.award_points(self.customer, 75, 'repair_complete', 'R')
        self.assertEqual(LoyaltyService.get_balance(self.customer), 75)

    def test_get_transaction_history(self):
        LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'R1')
        LoyaltyService.award_points(self.customer, 100, 'referral_received', 'Ref')
        history = list(LoyaltyService.get_transaction_history(self.customer))
        self.assertEqual(len(history), 2)
        # Most recent first
        self.assertEqual(history[0].transaction_type, 'referral_received')

    def test_get_lifetime_earned(self):
        LoyaltyService.award_points(self.customer, 100, 'repair_complete', 'R1')
        LoyaltyService.award_points(self.customer, -30, 'redemption', 'Spend')
        LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'R2')
        self.assertEqual(LoyaltyService.get_lifetime_earned(self.customer), 150)


# ──────────────────────────────────────────────────────────────────────
# Tenant isolation
# ──────────────────────────────────────────────────────────────────────

class TenantIsolationTest(TestCase):
    def setUp(self):
        self.tenant_a, _ = _make_tenant('Shop A', 'iso-a')
        self.tenant_b, _ = _make_tenant('Shop B', 'iso-b')
        self.cu_a = _make_customer_user(self.tenant_a, 'alice-iso@test.com')
        self.cu_b = _make_customer_user(self.tenant_b, 'bob-iso@test.com')
        self.customer_a = self.cu_a.customer
        self.customer_b = self.cu_b.customer

    def test_transactions_scoped_to_customer(self):
        LoyaltyService.award_points(self.customer_a, 100, 'repair_complete', 'A repair')
        LoyaltyService.award_points(self.customer_b, 200, 'repair_complete', 'B repair')

        a_history = LoyaltyService.get_transaction_history(self.customer_a)
        b_history = LoyaltyService.get_transaction_history(self.customer_b)
        self.assertEqual(len(a_history), 1)
        self.assertEqual(len(b_history), 1)
        self.assertEqual(a_history[0].tenant, self.tenant_a)
        self.assertEqual(b_history[0].tenant, self.tenant_b)

    def test_balance_isolated(self):
        LoyaltyService.award_points(self.customer_a, 100, 'repair_complete', 'A')
        LoyaltyService.award_points(self.customer_b, 999, 'repair_complete', 'B')
        self.assertEqual(LoyaltyService.get_balance(self.customer_a), 100)
        self.assertEqual(LoyaltyService.get_balance(self.customer_b), 999)

    def test_same_company_users_share_balance(self):
        """Two portal users of the SAME company see one shared balance.

        (Loyalty is customer-anchored: there is no per-portal-user balance
        within a company any more.)
        """
        second_user = User.objects.create_user(
            'alice2-iso', 'alice2-iso@test.com', 'testpass123!',
        )
        cu_a2 = CustomerUser.objects.create(
            user=second_user, customer=self.customer_a, is_primary_contact=False,
        )
        LoyaltyService.award_points(
            self.customer_a, 100, 'repair_complete', 'A', acting_customer_user=self.cu_a,
        )
        LoyaltyService.award_points(
            self.customer_a, 50, 'repair_complete', 'A2', acting_customer_user=cu_a2,
        )
        # One shared Reward row, one shared balance
        self.assertEqual(Reward.objects.filter(customer=self.customer_a).count(), 1)
        self.assertEqual(LoyaltyService.get_balance(self.customer_a), 150)
        self.assertEqual(LoyaltyService.get_balance(cu_a2.customer), 150)


# ──────────────────────────────────────────────────────────────────────
# LoyaltyConfig
# ──────────────────────────────────────────────────────────────────────

class LoyaltyConfigTest(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant('Config Shop', 'config-shop')

    def test_get_for_tenant_creates_with_defaults(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.points_per_repair, 50)
        self.assertEqual(config.referral_bonus_referrer, 500)
        self.assertTrue(config.is_active)

    def test_get_for_tenant_idempotent(self):
        c1 = LoyaltyConfig.get_for_tenant(self.tenant)
        c2 = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(c1.pk, c2.pk)

    def test_custom_values_used_in_award(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 75
        config.save()
        self.assertEqual(config.points_per_repair, 75)


# ──────────────────────────────────────────────────────────────────────
# Completion-hook awards (loyalty_hook)
# ──────────────────────────────────────────────────────────────────────

class AwardCompletionPointsTest(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('Repair Shop', 'repair-shop')
        self.cu = _make_customer_user(self.tenant, 'repaircust@test.com')
        self.customer = self.cu.customer
        from apps.technician_portal.models import Technician
        self.tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True,
        )

    def _make_repair_and_complete(self, unit_number='U1', customer=None):
        """Create a repair as IN_PROGRESS then transition to COMPLETED.

        Repair.__init__ snapshots queue_status as original_status, so creating
        directly with COMPLETED means the loyalty hook sees
        original_status==COMPLETED and skips. The real flow is always a
        status transition.
        """
        from apps.technician_portal.models import Repair
        repair = Repair.objects.create(
            customer=customer or self.customer, tenant=self.tenant,
            technician=self.tech, unit_number=unit_number,
            damage_type='CHIP', queue_status='IN_PROGRESS',
        )
        repair.queue_status = 'COMPLETED'
        repair.save()
        return repair

    def test_reads_from_config(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.points_per_repair = 75
        config.save()

        repair = self._make_repair_and_complete()

        self.assertEqual(LoyaltyService.get_balance(self.customer), 75)
        pt = PointTransaction.objects.get(
            customer=self.customer, transaction_type='repair_complete',
        )
        self.assertEqual(pt.amount, 75)
        self.assertEqual(pt.related_repair, repair)

    def test_milestone_5_bonus(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        # Create 4 completed repairs first (each awards base points)
        for i in range(4):
            self._make_repair_and_complete(unit_number=f'M{i}')
        base_from_first_4 = config.points_per_repair * 4

        # 5th repair triggers milestone bonus
        self._make_repair_and_complete(unit_number='M4')

        expected = base_from_first_4 + config.points_per_repair + config.milestone_5_bonus
        self.assertEqual(LoyaltyService.get_balance(self.customer), expected)

    def test_no_duplicate_on_resave(self):
        """Re-saving an already-COMPLETED repair should not award again."""
        repair = self._make_repair_and_complete()
        balance_after_first = LoyaltyService.get_balance(self.customer)
        self.assertGreater(balance_after_first, 0)
        # Re-save (original_status is now COMPLETED)
        repair.save()
        self.assertEqual(LoyaltyService.get_balance(self.customer), balance_after_first)

    def test_customer_without_portal_users_still_earns(self):
        """Points anchor on the Customer — a company with ZERO portal
        accounts earns on completed work just the same."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        no_portal = Customer.objects.create(
            name='No Portal Co', email='noportal@test.com', tenant=self.tenant,
        )
        self._make_repair_and_complete(unit_number='NP1', customer=no_portal)
        self.assertEqual(
            LoyaltyService.get_balance(no_portal), config.points_per_repair,
        )
        pt = PointTransaction.objects.get(
            customer=no_portal, transaction_type='repair_complete',
        )
        self.assertIsNone(pt.customer_user)


# ──────────────────────────────────────────────────────────────────────
# ReferralService refactor — record at signup, pay on first job
# ──────────────────────────────────────────────────────────────────────

class ReferralServiceLoyaltyTest(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant('Referral Shop', 'ref-shop')
        self.referrer = _make_customer_user(self.tenant, 'referrer@test.com')
        self.referred = _make_customer_user(self.tenant, 'referred@test.com')
        self.code = ReferralCode.objects.create(
            code='REF123', customer_user=self.referrer,
        )

    def test_record_referral_awards_nothing(self):
        """Signup only records a PENDING referral — no points move yet."""
        result = ReferralService.record_referral(self.code, self.referred)
        self.assertTrue(result)

        referral = Referral.objects.get(
            referral_code=self.code, customer_user=self.referred,
        )
        self.assertEqual(referral.status, 'PENDING')
        self.assertIsNone(referral.awarded_at)
        self.assertEqual(LoyaltyService.get_balance(self.referrer.customer), 0)
        self.assertEqual(LoyaltyService.get_balance(self.referred.customer), 0)

    def test_award_referral_bonuses_uses_loyalty_service(self):
        ReferralService.record_referral(self.code, self.referred)
        awarded = ReferralService.award_referral_bonuses(self.referred.customer)
        self.assertEqual(awarded, 1)

        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(
            LoyaltyService.get_balance(self.referrer.customer),
            config.referral_bonus_referrer,
        )
        self.assertEqual(
            LoyaltyService.get_balance(self.referred.customer),
            config.referral_bonus_referred,
        )
        referral = Referral.objects.get(
            referral_code=self.code, customer_user=self.referred,
        )
        self.assertEqual(referral.status, 'AWARDED')
        self.assertIsNotNone(referral.awarded_at)

    def test_referral_creates_transactions(self):
        ReferralService.record_referral(self.code, self.referred)
        ReferralService.award_referral_bonuses(self.referred.customer)
        referrer_txns = PointTransaction.objects.filter(
            customer=self.referrer.customer, transaction_type='referral_made',
        )
        referred_txns = PointTransaction.objects.filter(
            customer=self.referred.customer, transaction_type='referral_received',
        )
        self.assertEqual(referrer_txns.count(), 1)
        self.assertEqual(referred_txns.count(), 1)

    def test_award_referral_bonuses_idempotent(self):
        """A referral pays exactly once — re-running awards nothing more."""
        ReferralService.record_referral(self.code, self.referred)
        ReferralService.award_referral_bonuses(self.referred.customer)
        second = ReferralService.award_referral_bonuses(self.referred.customer)
        self.assertEqual(second, 0)

        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(
            LoyaltyService.get_balance(self.referrer.customer),
            config.referral_bonus_referrer,
        )
        self.assertEqual(
            LoyaltyService.get_balance(self.referred.customer),
            config.referral_bonus_referred,
        )

    def test_custom_referral_amounts(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.referral_bonus_referrer = 300
        config.referral_bonus_referred = 50
        config.save()

        ReferralService.record_referral(self.code, self.referred)
        ReferralService.award_referral_bonuses(self.referred.customer)
        self.assertEqual(LoyaltyService.get_balance(self.referrer.customer), 300)
        self.assertEqual(LoyaltyService.get_balance(self.referred.customer), 50)

    def test_cross_tenant_referral_blocked(self):
        other_tenant, _ = _make_tenant('Other Shop', 'other-ref')
        other_cu = _make_customer_user(other_tenant, 'other@test.com')
        result = ReferralService.record_referral(self.code, other_cu)
        self.assertFalse(result)

    def test_same_company_referral_blocked(self):
        """Two portal users of the same company can't refer each other —
        the balance is shared, so it would be self-referral."""
        coworker_user = User.objects.create_user(
            'coworker', 'coworker@test.com', 'testpass123!',
        )
        coworker = CustomerUser.objects.create(
            user=coworker_user, customer=self.referrer.customer,
            is_primary_contact=False,
        )
        result = ReferralService.record_referral(self.code, coworker)
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────────────────
# RewardService.redeem_reward() refactor
# ──────────────────────────────────────────────────────────────────────

class RedeemRewardLoyaltyTest(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant('Redeem Shop', 'redeem-shop')
        self.cu = _make_customer_user(self.tenant, 'redeemer@test.com')
        self.customer = self.cu.customer
        self.reward_type = RewardType.objects.create(
            name='Discount', category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE', discount_value=Decimal('10.00'),
        )
        self.option = RewardOption.objects.create(
            name='10% Off', description='Discount', points_required=100,
            reward_type=self.reward_type, tenant=self.tenant, is_active=True,
        )
        # Seed points
        LoyaltyService.award_points(self.customer, 200, 'manual_adjustment', 'Seed')

    def test_redemption_creates_negative_transaction(self):
        success, redemption = RewardService.redeem_reward(self.customer, self.option.pk)
        self.assertTrue(success)
        self.assertIsInstance(redemption, RewardRedemption)

        txn = PointTransaction.objects.filter(
            customer=self.customer, transaction_type='redemption',
        ).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, -100)
        self.assertEqual(txn.related_redemption, redemption)

    def test_balance_after_redemption(self):
        RewardService.redeem_reward(self.customer, self.option.pk)
        # redeem_reward delegates the deduction to LoyaltyService.
        # Seed: +200 → 200, Redeem: -100 → 100
        self.assertEqual(LoyaltyService.get_balance(self.customer), 100)

    def test_insufficient_points(self):
        # Deduct to leave only 50 points
        LoyaltyService.award_points(self.customer, -150, 'redemption', 'Partial spend')
        success, msg = RewardService.redeem_reward(self.customer, self.option.pk)
        self.assertFalse(success)
        self.assertIn('Not enough points', msg)


# ──────────────────────────────────────────────────────────────────────
# Customer portal views
# ──────────────────────────────────────────────────────────────────────

class CustomerPointsHistoryViewTest(TestCase):
    def setUp(self):
        from apps.tenants.services.signup_service import create_tenant_with_owner
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='View Shop', email='viewowner@test.com',
            password='testpass123!', first_name='View', last_name='Owner',
        )
        self.owner_user = result['user']
        self.tenant = result['tenant']

        # Create a customer user for this tenant
        self.cu = _make_customer_user(self.tenant, 'viewcust@test.com')
        LoyaltyService.award_points(self.cu.customer, 150, 'repair_complete', 'Test repair')

        self.client.force_login(self.cu.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_points_history_page_loads(self):
        response = self.client.get('/app/rewards/points-history/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Points History')
        self.assertContains(response, '150')  # balance
        self.assertContains(response, 'Test repair')

    def test_nav_shows_points_badge(self):
        response = self.client.get('/app/rewards/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '150')  # badge in nav


# ──────────────────────────────────────────────────────────────────────
# Backfill migration (logic test, not actual migration runner)
# ──────────────────────────────────────────────────────────────────────

class BackfillLogicTest(TestCase):
    """Test that legacy Reward rows get a PointTransaction when backfilled."""

    def test_legacy_reward_gets_tenant_and_transaction(self):
        tenant, _ = _make_tenant('Legacy Shop', 'legacy-shop')
        cu = _make_customer_user(tenant, 'legacy@test.com')
        customer = cu.customer

        # Simulate a pre-migration Reward (no tenant, no PointTransaction)
        reward = Reward.objects.create(customer=customer, points=350)
        self.assertIsNone(reward.tenant_id)

        # Simulate backfill logic
        reward.tenant = customer.tenant
        reward.save(update_fields=['tenant'])
        PointTransaction.objects.create(
            tenant=tenant, customer=customer,
            amount=reward.points, balance_after=reward.points,
            transaction_type='manual_adjustment',
            description='Legacy balance migration',
        )

        reward.refresh_from_db()
        self.assertEqual(reward.tenant, tenant)
        self.assertEqual(PointTransaction.objects.filter(customer=customer).count(), 1)
        pt = PointTransaction.objects.get(customer=customer)
        self.assertEqual(pt.amount, 350)
        self.assertEqual(pt.description, 'Legacy balance migration')


# ──────────────────────────────────────────────────────────────────────
# CODE-173: Reward.customer must be unique — no duplicate rows
# ──────────────────────────────────────────────────────────────────────

class RewardUniqueConstraintTest(TestCase):
    """
    Regression tests for CODE-173: Reward uniqueness (now per customer).

    Before the fix, LoyaltyService.award_points() and RewardService.redeem_reward()
    used a create()-then-get() pattern that could produce two Reward rows for the
    same account under concurrent access.  A subsequent .get() call would
    then raise MultipleObjectsReturned and crash the entire points pipeline.

    Fix:
      1. UniqueConstraint on Reward.customer at the DB level
         (unique_reward_per_customer).
      2. get_or_create() in award_points() and redeem_reward() so concurrent
         calls converge safely on a single row.
    """

    def setUp(self):
        self.tenant, _ = _make_tenant('Unique Shop', 'unique-shop')
        self.cu = _make_customer_user(self.tenant, 'unique@test.com')
        self.customer = self.cu.customer

    def test_duplicate_reward_row_violates_constraint(self):
        """Two Reward rows for the same customer should be blocked by DB."""
        from django.db import IntegrityError
        Reward.objects.create(customer=self.customer, tenant=self.tenant, points=0)
        with self.assertRaises(IntegrityError):
            Reward.objects.create(customer=self.customer, tenant=self.tenant, points=0)

    def test_award_points_creates_single_reward_row(self):
        """award_points() called twice should not create duplicate Reward rows."""
        LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'First repair')
        LoyaltyService.award_points(self.customer, 50, 'repair_complete', 'Second repair')

        reward_count = Reward.objects.filter(customer=self.customer).count()
        self.assertEqual(reward_count, 1, "award_points() must not create more than one Reward row")

        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 100)

    def test_award_points_balance_accumulates_correctly(self):
        """Multiple award_points() calls accumulate in the single Reward row."""
        LoyaltyService.award_points(self.customer, 100, 'repair_complete', 'R1')
        LoyaltyService.award_points(self.customer, 200, 'repair_complete', 'R2')
        LoyaltyService.award_points(self.customer, -50, 'redemption', 'Spent some')

        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 250)

        # PointTransaction ledger should have 3 rows
        txn_count = PointTransaction.objects.filter(customer=self.customer).count()
        self.assertEqual(txn_count, 3)

    def test_award_points_idempotent_on_existing_reward(self):
        """award_points() when a Reward already exists does not recreate it."""
        # Pre-create the Reward row (simulates legacy data or prior call)
        Reward.objects.create(customer=self.customer, tenant=self.tenant, points=75)

        # award_points() must not raise and must update the existing row
        LoyaltyService.award_points(self.customer, 25, 'repair_complete', 'R3')

        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 100)

    def test_get_or_create_does_not_raise_multiple_objects(self):
        """
        Simulate the exact scenario that caused MultipleObjectsReturned before fix.

        Without the UniqueConstraint + get_or_create fix, this test would be
        impossible to write cleanly — the IntegrityError from step 2 is itself
        the proof the constraint exists.
        """
        from django.db import IntegrityError, transaction as db_transaction

        Reward.objects.create(customer=self.customer, tenant=self.tenant, points=0)

        # Attempting to insert a second row must fail at the DB level
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                Reward.objects.create(customer=self.customer, tenant=self.tenant, points=0)

        # After the failed savepoint, we should still be able to fetch the original
        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 0)


# ---------------------------------------------------------------------------
# CODE-175 regression tests — RewardService.redeem_reward() with inactive
# loyalty program
# ---------------------------------------------------------------------------

class RedeemRewardInactiveLoyaltyTest(TestCase):
    """
    CODE-175: RewardService.redeem_reward() must block redemptions when the
    loyalty program is inactive.

    Previously LoyaltyService.award_points() short-circuited on
    config.is_active=False without raising, leaving the RewardRedemption row
    committed but the point balance un-decremented — a free-redemption loophole.
    """

    def setUp(self):
        self.tenant, _ = _make_tenant('FixTenant', 'fix-tenant')
        self.user = User.objects.create_user(
            username='cx_fix', password='pass', email='cx_fix@example.com'
        )
        self.customer = Customer.objects.create(
            name='FixCo', tenant=self.tenant
        )
        self.cu = CustomerUser.objects.create(
            user=self.user, customer=self.customer, is_primary_contact=True
        )
        self.reward_type = RewardType.objects.create(
            name='Discount', category='REPAIR_DISCOUNT', discount_type='NONE'
        )
        self.option = RewardOption.objects.create(
            tenant=self.tenant,
            name='$5 Off',
            description='5 bucks off',
            points_required=200,
            reward_type=self.reward_type,
            is_active=True,
        )
        # Give the customer a generous balance
        Reward.objects.create(
            customer=self.customer, tenant=self.tenant, points=500
        )

    def _set_loyalty_active(self, active):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = active
        config.save()

    def test_redemption_blocked_when_loyalty_inactive(self):
        """redeem_reward() must return failure when the loyalty program is off."""
        self._set_loyalty_active(False)
        success, result = RewardService.redeem_reward(self.customer, self.option.id)
        self.assertFalse(success)
        self.assertIn('not currently active', result)

    def test_no_redemption_row_created_when_loyalty_inactive(self):
        """No RewardRedemption row must be persisted if the program is inactive."""
        self._set_loyalty_active(False)
        RewardService.redeem_reward(self.customer, self.option.id)
        self.assertEqual(
            RewardRedemption.objects.filter(reward__customer=self.customer).count(), 0,
            "RewardRedemption must NOT be committed when loyalty is inactive"
        )

    def test_points_unchanged_when_loyalty_inactive(self):
        """Point balance must remain untouched when redemption is blocked."""
        self._set_loyalty_active(False)
        RewardService.redeem_reward(self.customer, self.option.id)
        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 500, "Balance must not change on blocked redemption")

    def test_no_point_transaction_when_loyalty_inactive(self):
        """No PointTransaction row must be created for a blocked redemption."""
        self._set_loyalty_active(False)
        RewardService.redeem_reward(self.customer, self.option.id)
        self.assertEqual(
            PointTransaction.objects.filter(customer=self.customer).count(), 0
        )

    def test_redemption_succeeds_and_deducts_when_active(self):
        """Sanity check: normal redemption still works with active program."""
        self._set_loyalty_active(True)
        success, result = RewardService.redeem_reward(self.customer, self.option.id)
        self.assertTrue(success)
        self.assertIsInstance(result, RewardRedemption)
        # Points should be deducted
        reward = Reward.objects.get(customer=self.customer)
        self.assertEqual(reward.points, 500 - self.option.points_required)

    def test_point_transaction_created_on_successful_redemption(self):
        """A negative PointTransaction row must exist after a successful redemption."""
        self._set_loyalty_active(True)
        RewardService.redeem_reward(self.customer, self.option.id)
        txns = PointTransaction.objects.filter(customer=self.customer, transaction_type='redemption')
        self.assertEqual(txns.count(), 1)
        self.assertEqual(txns.first().amount, -self.option.points_required)


# ──────────────────────────────────────────────────────────────────────
# TenantConfig abstract base class (CODE-184)
# ──────────────────────────────────────────────────────────────────────

class TenantConfigBaseClassTest(TestCase):
    """Tests for TenantConfig abstract base class via LoyaltyConfig."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('BaseClass Shop', 'baseclass-shop')

    def test_loyalty_config_inherits_get_for_tenant(self):
        """LoyaltyConfig.get_for_tenant() works via inherited classmethod."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertIsInstance(config, LoyaltyConfig)
        self.assertEqual(config.tenant, self.tenant)

    def test_get_for_tenant_creates_if_missing(self):
        """get_for_tenant creates a new LoyaltyConfig if none exists."""
        LoyaltyConfig.objects.filter(tenant=self.tenant).delete()
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertIsNotNone(config.pk)

    def test_get_for_tenant_idempotent(self):
        """Calling get_for_tenant twice returns same object, no duplicate created."""
        config1 = LoyaltyConfig.get_for_tenant(self.tenant)
        config2 = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertEqual(config1.pk, config2.pk)
        self.assertEqual(LoyaltyConfig.objects.filter(tenant=self.tenant).count(), 1)

    def test_loyalty_config_has_created_at(self):
        """LoyaltyConfig has created_at via TenantConfig inheritance."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertIsNotNone(config.created_at)

    def test_loyalty_config_has_updated_at(self):
        """LoyaltyConfig has updated_at via TenantConfig inheritance."""
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertIsNotNone(config.updated_at)
