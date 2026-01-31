#!/usr/bin/env python
"""
Comprehensive test script for reward discount bug fix.
Tests that MERCHANDISE rewards (donuts, pizza) do NOT reduce repair costs.
Tests that REPAIR_DISCOUNT and FREE_SERVICE rewards work correctly.
"""

import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rs_systems.settings.development')
django.setup()

from decimal import Decimal
from django.contrib.auth.models import User
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Technician
from apps.rewards_referrals.models import RewardType, RewardOption, RewardRedemption, Reward
from django.utils import timezone


class TestRewardDiscountFix:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_user = None
        self.test_customer_user = None
        self.test_customer = None
        self.test_technician_user = None
        self.test_technician = None
        self.test_reward = None
        self.test_repair = None

    def setup(self):
        """Create test data"""
        print("=" * 70)
        print("SETTING UP TEST DATA")
        print("=" * 70)

        # Create test user
        self.test_user = User.objects.create_user(
            username='test_reward_user',
            email='test@example.com',
            password='testpass123'
        )
        print(f"✓ Created test user: {self.test_user.username}")

        # Create test customer
        self.test_customer = Customer.objects.create(
            name='Test Reward Company',
            email='test@company.com',
            phone='555-0100'
        )
        print(f"✓ Created test customer: {self.test_customer.name}")

        # Link user to customer
        self.test_customer_user = CustomerUser.objects.create(
            user=self.test_user,
            customer=self.test_customer
        )
        print(f"✓ Linked user to customer")

        # Create test technician
        self.test_technician_user = User.objects.create_user(
            username='test_technician',
            email='tech@example.com',
            password='techpass123'
        )
        self.test_technician = Technician.objects.create(
            user=self.test_technician_user,
            phone_number='555-0200'
        )
        print(f"✓ Created test technician: {self.test_technician.user.username}")

        # Create reward balance with enough points for all tests
        self.test_reward = Reward.objects.create(
            customer_user=self.test_customer_user,
            points=10000  # Enough points for all redemptions
        )
        print(f"✓ Created reward balance: {self.test_reward.points} points")

        # Create test repair with $50 cost
        self.test_repair = Repair.objects.create(
            customer=self.test_customer,
            technician=self.test_technician,
            unit_number='TEST-001',
            damage_type='CHIP',
            queue_status='COMPLETED',
            repair_date=timezone.now(),
            cost=Decimal('50.00')
        )
        print(f"✓ Created test repair: ${self.test_repair.cost}")
        print()

    def teardown(self):
        """Clean up test data"""
        print("\n" + "=" * 70)
        print("CLEANING UP TEST DATA")
        print("=" * 70)

        if self.test_repair:
            self.test_repair.delete()
            print("✓ Deleted test repair")

        if self.test_reward:
            self.test_reward.delete()
            print("✓ Deleted reward balance")

        if self.test_technician:
            self.test_technician.delete()
            print("✓ Deleted test technician")

        if self.test_technician_user:
            self.test_technician_user.delete()
            print("✓ Deleted technician user")

        if self.test_customer_user:
            self.test_customer_user.delete()
            print("✓ Deleted customer user link")

        if self.test_customer:
            self.test_customer.delete()
            print("✓ Deleted test customer")

        if self.test_user:
            self.test_user.delete()
            print("✓ Deleted test user")

    def assert_equal(self, actual, expected, test_name):
        """Helper to assert equality and track results"""
        if actual == expected:
            print(f"  ✓ PASS: {test_name}")
            print(f"    Expected: {expected}, Got: {actual}")
            self.passed += 1
            return True
        else:
            print(f"  ✗ FAIL: {test_name}")
            print(f"    Expected: {expected}, Got: {actual}")
            self.failed += 1
            return False

    def test_merchandise_rewards_no_discount(self):
        """Test that MERCHANDISE rewards (donuts, pizza) do NOT reduce repair costs"""
        print("=" * 70)
        print("TEST 1: MERCHANDISE Rewards Should NOT Reduce Repair Cost")
        print("=" * 70)

        # Get the office treats reward type
        office_treats = RewardType.objects.get(category='MERCHANDISE')
        print(f"Reward Type: {office_treats.name}")
        print(f"Category: {office_treats.category}")
        print(f"Discount Type: {office_treats.discount_type}")
        print()

        # Test 1A: Donuts reward
        print("Test 1A: Donuts Reward")
        donut_option = RewardOption.objects.get(name='5 Dozen Donuts for the Office')
        donut_redemption = RewardRedemption.objects.create(
            reward=self.test_reward,
            reward_option=donut_option,
            status='PENDING',
            applied_to_repair=self.test_repair
        )

        result = self.test_repair.get_discounted_cost()
        self.assert_equal(result['final_cost'], Decimal('50.00'), "Donuts reward does not reduce repair cost")
        self.assert_equal(result['discount_applied'], False, "No discount should be applied")
        self.assert_equal(result['savings'], Decimal('0.00'), "No savings from donuts reward")

        # Clean up
        donut_redemption.delete()
        print()

        # Test 1B: Pizza reward
        print("Test 1B: Pizza Reward")
        pizza_option = RewardOption.objects.get(name='5 Large Pizzas for Team')
        pizza_redemption = RewardRedemption.objects.create(
            reward=self.test_reward,
            reward_option=pizza_option,
            status='PENDING',
            applied_to_repair=self.test_repair
        )

        result = self.test_repair.get_discounted_cost()
        self.assert_equal(result['final_cost'], Decimal('50.00'), "Pizza reward does not reduce repair cost")
        self.assert_equal(result['discount_applied'], False, "No discount should be applied")
        self.assert_equal(result['savings'], Decimal('0.00'), "No savings from pizza reward")

        # Clean up
        pizza_redemption.delete()
        print()

    def test_percentage_discount_works(self):
        """Test that REPAIR_DISCOUNT percentage rewards work correctly"""
        print("=" * 70)
        print("TEST 2: REPAIR_DISCOUNT 50% Off Should Work Correctly")
        print("=" * 70)

        discount_option = RewardOption.objects.get(name='50% Off Next Repair')
        discount_redemption = RewardRedemption.objects.create(
            reward=self.test_reward,
            reward_option=discount_option,
            status='PENDING',
            applied_to_repair=self.test_repair
        )

        result = self.test_repair.get_discounted_cost()
        print(f"Reward Type: {discount_option.reward_type.name}")
        print(f"Category: {discount_option.reward_type.category}")
        print(f"Discount Type: {discount_option.reward_type.discount_type}")
        print()

        self.assert_equal(result['final_cost'], Decimal('25.00'), "50% discount reduces $50 to $25")
        self.assert_equal(result['discount_applied'], True, "Discount should be applied")
        self.assert_equal(result['discount_description'], "50% off", "Correct discount description")
        self.assert_equal(result['savings'], Decimal('25.00'), "Savings of $25")

        # Clean up
        discount_redemption.delete()
        print()

    def test_free_service_works(self):
        """Test that FREE_SERVICE rewards work correctly"""
        print("=" * 70)
        print("TEST 3: FREE_SERVICE Reward Should Make Repair Free")
        print("=" * 70)

        free_option = RewardOption.objects.get(name='Free Windshield Repair')
        free_redemption = RewardRedemption.objects.create(
            reward=self.test_reward,
            reward_option=free_option,
            status='PENDING',
            applied_to_repair=self.test_repair
        )

        result = self.test_repair.get_discounted_cost()
        print(f"Reward Type: {free_option.reward_type.name}")
        print(f"Category: {free_option.reward_type.category}")
        print(f"Discount Type: {free_option.reward_type.discount_type}")
        print()

        self.assert_equal(result['final_cost'], Decimal('0.00'), "Free service makes repair $0")
        self.assert_equal(result['discount_applied'], True, "Discount should be applied")
        self.assert_equal(result['discount_description'], "Free repair", "Correct discount description")
        self.assert_equal(result['savings'], Decimal('50.00'), "Savings of $50 (full cost)")

        # Clean up
        free_redemption.delete()
        print()

    def test_no_reward_applied(self):
        """Test that repairs with no rewards show correct cost"""
        print("=" * 70)
        print("TEST 4: No Reward Applied - Should Show Full Cost")
        print("=" * 70)

        result = self.test_repair.get_discounted_cost()

        self.assert_equal(result['final_cost'], Decimal('50.00'), "No discount - full $50 cost")
        self.assert_equal(result['discount_applied'], False, "No discount should be applied")
        self.assert_equal(result['savings'], Decimal('0.00'), "No savings")
        print()

    def run_all_tests(self):
        """Run all tests and display summary"""
        print("\n")
        print("╔" + "=" * 68 + "╗")
        print("║" + " " * 15 + "REWARD DISCOUNT BUG FIX TEST SUITE" + " " * 19 + "║")
        print("╚" + "=" * 68 + "╝")
        print()

        try:
            self.setup()

            self.test_merchandise_rewards_no_discount()
            self.test_percentage_discount_works()
            self.test_free_service_works()
            self.test_no_reward_applied()

        finally:
            self.teardown()

        # Print summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        total = self.passed + self.failed
        print(f"Total Tests: {total}")
        print(f"✓ Passed: {self.passed}")
        print(f"✗ Failed: {self.failed}")

        if self.failed == 0:
            print("\n" + "🎉 " * 10)
            print("ALL TESTS PASSED! Bug fix is working correctly.")
            print("🎉 " * 10)
            return True
        else:
            print("\n⚠️  SOME TESTS FAILED - Review the output above")
            return False


if __name__ == '__main__':
    tester = TestRewardDiscountFix()
    success = tester.run_all_tests()
    exit(0 if success else 1)
