"""
Comprehensive Rewards & Referral System Tests for RS Systems.
Tests the full rewards lifecycle: codes, referrals, points, redemption, fulfillment.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.utils import timezone
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import (
    ReferralCode, Referral, Reward, RewardType, RewardOption, RewardRedemption
)
from apps.rewards_referrals.services import (
    ReferralService, RewardService, RewardFulfillmentService
)


class RewardsTestMixin:
    """Shared setup for rewards tests."""

    def create_base_data(self):
        """Create tenant, technician, and base customer."""
        self.owner_user = User.objects.create_user('rw_owner', 'rwowner@test.com', 'TestPass123!')
        self.tenant = Tenant.objects.create(
            name='Rewards Test Shop', slug='rewards-test-shop',
            subdomain='rewardstestshop', owner=self.owner_user,
            plan='trial', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(user=self.owner_user, tenant=self.tenant, role='owner', is_active=True)

        self.tech_user = User.objects.create_user('rw_tech', 'rwtech@test.com', 'TestPass123!')
        self.tech = Technician.objects.create(user=self.tech_user, tenant=self.tenant, is_active=True)
        TenantMembership.objects.create(user=self.tech_user, tenant=self.tenant, role='technician', is_active=True)
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        self.tech_user.groups.add(tech_group)

        # Customer A (referrer)
        self.customer_a = Customer.objects.create(
            tenant=self.tenant, name='Fleet Alpha', customer_type='FLEET')
        self.user_a = User.objects.create_user('cust_a', 'custa@test.com', 'TestPass123!')
        self.cu_a = CustomerUser.objects.create(user=self.user_a, customer=self.customer_a)

        # Customer B (referred)
        self.customer_b = Customer.objects.create(
            tenant=self.tenant, name='Fleet Beta', customer_type='FLEET')
        self.user_b = User.objects.create_user('cust_b', 'custb@test.com', 'TestPass123!')
        self.cu_b = CustomerUser.objects.create(user=self.user_b, customer=self.customer_b)

    def create_reward_types_and_options(self):
        """Create standard reward types and options for testing."""
        # Repair discount type
        self.rt_repair = RewardType.objects.create(
            name='Repair Discount', category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE', discount_value=Decimal('50.00'),
            is_active=True
        )
        # Free service type
        self.rt_free = RewardType.objects.create(
            name='Free Repair', category='FREE_SERVICE',
            discount_type='FREE', discount_value=Decimal('0'),
            is_active=True
        )
        # Merchandise type (no discount on repairs)
        self.rt_merch = RewardType.objects.create(
            name='Office Treats', category='MERCHANDISE',
            discount_type='NONE', discount_value=Decimal('0'),
            is_active=True
        )

        # Reward options — scoped to tenant so the API view (which filters by
        # request.tenant) returns them correctly.
        self.opt_50off = RewardOption.objects.create(
            name='50% Off Next Repair', description='Half price on your next repair',
            points_required=500, reward_type=self.rt_repair, is_active=True,
            tenant=self.tenant,
        )
        self.opt_free = RewardOption.objects.create(
            name='Free Windshield Repair', description='One free repair',
            points_required=1000, reward_type=self.rt_free, is_active=True,
            tenant=self.tenant,
        )
        self.opt_donuts = RewardOption.objects.create(
            name='Donuts for Office', description='5 dozen donuts',
            points_required=300, reward_type=self.rt_merch, is_active=True,
            tenant=self.tenant,
        )
        self.opt_inactive = RewardOption.objects.create(
            name='Inactive Reward', description='Should not be redeemable',
            points_required=100, reward_type=self.rt_merch, is_active=False,
            tenant=self.tenant,
        )


class ReferralCodeTests(RewardsTestMixin, TestCase):
    """Test referral code generation and validation."""

    def setUp(self):
        self.create_base_data()

    def test_generate_referral_code(self):
        """Should generate a unique code for a customer."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        self.assertIsNotNone(code_obj)
        self.assertEqual(len(code_obj.code), 8)
        self.assertEqual(code_obj.customer_user, self.cu_a)

    def test_generate_code_idempotent(self):
        """Generating code twice should return the same code."""
        code1 = ReferralService.generate_code_for_user(self.cu_a)
        code2 = ReferralService.generate_code_for_user(self.cu_a)
        self.assertEqual(code1.id, code2.id)
        self.assertEqual(code1.code, code2.code)

    def test_validate_valid_code(self):
        """Valid referral code should be found."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        validated = ReferralService.validate_referral_code(code_obj.code)
        self.assertIsNotNone(validated)
        self.assertEqual(validated.id, code_obj.id)

    def test_validate_invalid_code(self):
        """Invalid referral code should return None."""
        result = ReferralService.validate_referral_code('INVALID123')
        self.assertIsNone(result)

    def test_different_users_get_different_codes(self):
        """Each user should get a unique code."""
        code_a = ReferralService.generate_code_for_user(self.cu_a)
        code_b = ReferralService.generate_code_for_user(self.cu_b)
        self.assertNotEqual(code_a.code, code_b.code)


class ReferralProcessingTests(RewardsTestMixin, TestCase):
    """Test referral processing and point awards."""

    def setUp(self):
        self.create_base_data()

    def test_process_referral_awards_points(self):
        """Processing a referral should award 500 to referrer, 100 to referred."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        success = ReferralService.process_referral(code_obj, self.cu_b)
        self.assertTrue(success)

        # Check referrer points
        reward_a = Reward.objects.get(customer_user=self.cu_a)
        self.assertEqual(reward_a.points, 500)

        # Check referred points
        reward_b = Reward.objects.get(customer_user=self.cu_b)
        self.assertEqual(reward_b.points, 100)

    def test_self_referral_blocked(self):
        """Users cannot refer themselves."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        success = ReferralService.process_referral(code_obj, self.cu_a)
        self.assertFalse(success)
        # No reward should be created
        self.assertFalse(Reward.objects.filter(customer_user=self.cu_a).exists())

    def test_duplicate_referral_blocked(self):
        """Same referral should not be processed twice."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        success1 = ReferralService.process_referral(code_obj, self.cu_b)
        success2 = ReferralService.process_referral(code_obj, self.cu_b)
        self.assertTrue(success1)
        self.assertFalse(success2)

        # Points should only be awarded once
        reward_a = Reward.objects.get(customer_user=self.cu_a)
        self.assertEqual(reward_a.points, 500)  # Not 1000

    def test_referral_count(self):
        """Referral count should be accurate."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        # Create a third customer to refer
        customer_c = Customer.objects.create(tenant=self.tenant, name='Fleet Charlie', customer_type='FLEET')
        user_c = User.objects.create_user('cust_c', 'custc@test.com', 'TestPass123!')
        cu_c = CustomerUser.objects.create(user=user_c, customer=customer_c)

        ReferralService.process_referral(code_obj, self.cu_b)
        ReferralService.process_referral(code_obj, cu_c)

        count = ReferralService.get_referral_count(self.cu_a)
        self.assertEqual(count, 2)

    def test_referral_creates_record(self):
        """Processing referral should create a Referral record."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        ReferralService.process_referral(code_obj, self.cu_b)

        referral = Referral.objects.filter(referral_code=code_obj, customer_user=self.cu_b)
        self.assertTrue(referral.exists())

    def test_multiple_referrals_accumulate_points(self):
        """Multiple successful referrals should accumulate points."""
        code_obj = ReferralService.generate_code_for_user(self.cu_a)

        # Create multiple referred users
        for i in range(5):
            cust = Customer.objects.create(tenant=self.tenant, name=f'Fleet {i}', customer_type='FLEET')
            user = User.objects.create_user(f'ref_user_{i}', f'ref{i}@test.com', 'TestPass123!')
            cu = CustomerUser.objects.create(user=user, customer=cust)
            ReferralService.process_referral(code_obj, cu)

        reward_a = Reward.objects.get(customer_user=self.cu_a)
        self.assertEqual(reward_a.points, 2500)  # 500 * 5


class RewardRedemptionTests(RewardsTestMixin, TestCase):
    """Test reward redemption flow."""

    def setUp(self):
        self.create_base_data()
        self.create_reward_types_and_options()
        # Give customer A 1000 points
        self.reward_a = Reward.objects.create(customer_user=self.cu_a, points=1000)

    def test_redeem_with_sufficient_points(self):
        """Redemption should succeed with enough points."""
        success, result = RewardService.redeem_reward(self.cu_a, self.opt_50off.id)
        self.assertTrue(success)
        self.assertIsInstance(result, RewardRedemption)
        self.assertEqual(result.status, 'PENDING')

        # Points should be deducted
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 500)  # 1000 - 500

    def test_redeem_with_insufficient_points(self):
        """Redemption should fail with not enough points."""
        self.reward_a.points = 100
        self.reward_a.save()

        success, message = RewardService.redeem_reward(self.cu_a, self.opt_50off.id)
        self.assertFalse(success)
        self.assertIn('Not enough points', message)

        # Points should not change
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 100)

    def test_redeem_inactive_option(self):
        """Cannot redeem an inactive reward option."""
        self.reward_a.points = 10000
        self.reward_a.save()

        success, message = RewardService.redeem_reward(self.cu_a, self.opt_inactive.id)
        self.assertFalse(success)
        self.assertIn('not currently available', message)

    def test_redeem_invalid_option(self):
        """Cannot redeem a non-existent reward option."""
        success, message = RewardService.redeem_reward(self.cu_a, 99999)
        self.assertFalse(success)
        self.assertIn('Invalid', message)

    def test_redeem_exact_points(self):
        """Redemption should work when points exactly match cost."""
        self.reward_a.points = 300
        self.reward_a.save()

        success, result = RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        self.assertTrue(success)

        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 0)

    def test_multiple_redemptions_deplete_points(self):
        """Multiple redemptions should correctly deplete points."""
        # Start with 1000 points
        # Redeem donuts (300) -> 700
        success1, _ = RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        self.assertTrue(success1)
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 700)

        # Redeem 50% off (500) -> 200
        success2, _ = RewardService.redeem_reward(self.cu_a, self.opt_50off.id)
        self.assertTrue(success2)
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 200)

        # Try free repair (1000) -> should fail
        success3, msg = RewardService.redeem_reward(self.cu_a, self.opt_free.id)
        self.assertFalse(success3)
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 200)  # Unchanged

    def test_redemption_history(self):
        """Redemption history should track all redemptions."""
        RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        RewardService.redeem_reward(self.cu_a, self.opt_50off.id)

        history = RewardService.get_redemption_history(self.cu_a)
        self.assertEqual(history.count(), 2)

    def test_available_vs_unavailable_rewards(self):
        """Should correctly split rewards by affordability."""
        self.reward_a.points = 400
        self.reward_a.save()

        result = RewardService.get_available_rewards(self.cu_a)
        available_names = [o.name for o in result['available']]
        unavailable_names = [o.name for o in result['unavailable']]

        self.assertIn('Donuts for Office', available_names)  # 300 pts
        self.assertIn('50% Off Next Repair', unavailable_names)  # 500 pts
        self.assertIn('Free Windshield Repair', unavailable_names)  # 1000 pts

    def test_reward_balance_service(self):
        """RewardService.get_reward_balance should return correct balance."""
        balance = RewardService.get_reward_balance(self.cu_a)
        self.assertEqual(balance, 1000)

    def test_reward_balance_no_reward(self):
        """Balance should be 0 for user with no reward record."""
        balance = RewardService.get_reward_balance(self.cu_b)
        self.assertEqual(balance, 0)


class RewardFulfillmentTests(RewardsTestMixin, TestCase):
    """Test reward fulfillment workflow."""

    def setUp(self):
        self.create_base_data()
        self.create_reward_types_and_options()
        self.reward_a = Reward.objects.create(customer_user=self.cu_a, points=1000)

    def test_assign_technician(self):
        """Should assign a technician to fulfill a redemption."""
        _, redemption = RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        assigned = RewardFulfillmentService.assign_technician(redemption)

        self.assertIsNotNone(assigned)
        redemption.refresh_from_db()
        self.assertEqual(redemption.assigned_technician, self.tech)

    def test_mark_as_fulfilled(self):
        """Should mark redemption as fulfilled."""
        _, redemption = RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        redemption.assigned_technician = self.tech
        redemption.save()

        result = RewardFulfillmentService.mark_as_fulfilled(redemption, self.tech, notes='Delivered donuts')
        self.assertEqual(result.status, 'FULFILLED')
        self.assertIsNotNone(result.fulfilled_at)
        self.assertEqual(result.notes, 'Delivered donuts')

    def test_pending_redemptions_list(self):
        """Should list all pending redemptions."""
        RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        RewardService.redeem_reward(self.cu_a, self.opt_50off.id)

        pending = RewardFulfillmentService.get_pending_redemptions()
        self.assertEqual(pending.count(), 2)

    def test_fulfilled_not_in_pending(self):
        """Fulfilled redemptions should not appear in pending list."""
        _, redemption = RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        RewardFulfillmentService.mark_as_fulfilled(redemption, self.tech)

        pending = RewardFulfillmentService.get_pending_redemptions()
        self.assertEqual(pending.count(), 0)


class RewardViewTests(RewardsTestMixin, TestCase):
    """Test rewards views via HTTP."""

    def setUp(self):
        self.client = Client()
        self.create_base_data()
        self.create_reward_types_and_options()
        self.reward_a = Reward.objects.create(customer_user=self.cu_a, points=1000)
        self.code_a = ReferralService.generate_code_for_user(self.cu_a)

    def test_reward_balance_api(self):
        """Should return current balance as JSON."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.get('/referrals/reward-balance/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['points'], 1000)

    def test_referral_code_api(self):
        """Should return user's referral code."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.get('/referrals/referral-code/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['code'], self.code_a.code)

    def test_referral_stats_api(self):
        """Should return referral stats."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.get('/referrals/referral-stats/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total_referrals'], 0)
        self.assertEqual(data['points'], 1000)

    def test_referral_tracking_post(self):
        """Should process a referral via POST."""
        self.client.login(username='cust_b', password='TestPass123!')
        resp = self.client.post('/referrals/referral-tracking/', {'code': self.code_a.code})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

        # Verify points awarded
        reward_a = Reward.objects.get(customer_user=self.cu_a)
        self.assertEqual(reward_a.points, 1500)  # 1000 + 500

    def test_referral_tracking_invalid_code(self):
        """Should reject invalid referral code."""
        self.client.login(username='cust_b', password='TestPass123!')
        resp = self.client.post('/referrals/referral-tracking/', {'code': 'BADCODE'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_referral_tracking_self_referral(self):
        """Should reject self-referral via view."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.post('/referrals/referral-tracking/', {'code': self.code_a.code})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_rewards_dashboard_loads(self):
        """Rewards dashboard should load."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.get('/referrals/referral-rewards/')
        self.assertEqual(resp.status_code, 200)

    def test_redeem_reward_view(self):
        """Should redeem a reward via POST."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.post('/referrals/redeem-reward/', {'option_id': self.opt_donuts.id})
        # Should redirect after redemption
        self.assertEqual(resp.status_code, 302)

        # Verify points deducted
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 700)

    def test_redeem_insufficient_points_view(self):
        """Should show error when insufficient points."""
        self.reward_a.points = 10
        self.reward_a.save()

        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.post('/referrals/redeem-reward/', {'option_id': self.opt_donuts.id}, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Points should not change
        self.reward_a.refresh_from_db()
        self.assertEqual(self.reward_a.points, 10)

    def test_unauthenticated_reward_access(self):
        """Unauthenticated users should be redirected."""
        urls = [
            '/referrals/reward-balance/',
            '/referrals/referral-code/',
            '/referrals/referral-rewards/',
            '/referrals/redeem-reward/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, [302, 405],
                          f"{url} should redirect unauthenticated user")

    def test_generate_referral_code_view(self):
        """Should generate a referral code for user without one."""
        self.client.login(username='cust_b', password='TestPass123!')
        # GET should show page
        resp = self.client.get('/referrals/generate-referral-code/')
        self.assertEqual(resp.status_code, 200)

        # POST should generate code
        resp = self.client.post('/referrals/generate-referral-code/')
        self.assertIn(resp.status_code, [200, 302])

        # Verify code was created
        self.assertTrue(ReferralCode.objects.filter(customer_user=self.cu_b).exists())

    def test_reward_options_api(self):
        """Should return reward options as JSON for AJAX requests."""
        self.client.login(username='cust_a', password='TestPass123!')
        resp = self.client.get('/referrals/reward-options/',
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        # Should only include active options
        option_names = [o['name'] for o in data['options']]
        self.assertIn('Donuts for Office', option_names)
        self.assertNotIn('Inactive Reward', option_names)


class EndToEndRewardsFlowTest(RewardsTestMixin, TestCase):
    """Full end-to-end test of the rewards system."""

    def setUp(self):
        self.client = Client()
        self.create_base_data()
        self.create_reward_types_and_options()

    def test_full_referral_to_redemption_flow(self):
        """
        Complete flow:
        1. Customer A generates referral code
        2. Customer B uses referral code
        3. Customer A gets 500 points, Customer B gets 100 points
        4. Customer A redeems donuts (300 pts)
        5. Technician fulfills the reward
        6. Customer A has 200 points remaining
        """
        # Step 1: Customer A generates referral code
        code_obj = ReferralService.generate_code_for_user(self.cu_a)
        self.assertIsNotNone(code_obj)

        # Step 2: Customer B uses the code
        success = ReferralService.process_referral(code_obj, self.cu_b)
        self.assertTrue(success)

        # Step 3: Verify points
        reward_a = Reward.objects.get(customer_user=self.cu_a)
        reward_b = Reward.objects.get(customer_user=self.cu_b)
        self.assertEqual(reward_a.points, 500)
        self.assertEqual(reward_b.points, 100)

        # Step 4: Customer A redeems donuts (300 pts)
        success, redemption = RewardService.redeem_reward(self.cu_a, self.opt_donuts.id)
        self.assertTrue(success)
        self.assertEqual(redemption.status, 'PENDING')

        reward_a.refresh_from_db()
        self.assertEqual(reward_a.points, 200)

        # Step 5: Technician fulfills
        assigned = RewardFulfillmentService.assign_technician(redemption)
        self.assertIsNotNone(assigned)

        fulfilled = RewardFulfillmentService.mark_as_fulfilled(
            redemption, self.tech, notes='Delivered to office')
        self.assertEqual(fulfilled.status, 'FULFILLED')

        # Step 6: Verify final state
        reward_a.refresh_from_db()
        self.assertEqual(reward_a.points, 200)

        # Verify referral count
        self.assertEqual(ReferralService.get_referral_count(self.cu_a), 1)

        # Verify redemption history
        history = RewardService.get_redemption_history(self.cu_a)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().status, 'FULFILLED')
