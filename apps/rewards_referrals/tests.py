from django.test import TestCase
from django.contrib.auth.models import User
from decimal import Decimal
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from .models import (
    ReferralCode, Referral, RewardType, Reward, 
    RewardOption, RewardRedemption
)


class ReferralSystemTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='test company',
            email='test@company.com'
        )
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer
        )

    def test_referral_code_creation(self):
        referral_code = ReferralCode.objects.create(
            code='TEST123',
            customer_user=self.customer_user
        )
        self.assertEqual(str(referral_code), 'TEST123')
        self.assertEqual(referral_code.customer_user, self.customer_user)

    def test_referral_creation(self):
        referral_code = ReferralCode.objects.create(
            code='TEST123',
            customer_user=self.customer_user
        )
        
        # Create another customer for the referral
        new_customer = Customer.objects.create(
            name='new company',
            email='new@company.com'
        )
        new_user = User.objects.create_user(
            username='newuser',
            password='testpass'
        )
        new_customer_user = CustomerUser.objects.create(
            user=new_user,
            customer=new_customer
        )
        
        referral = Referral.objects.create(
            referral_code=referral_code,
            customer_user=new_customer_user
        )
        self.assertEqual(referral.referral_code, referral_code)
        self.assertEqual(referral.customer_user, new_customer_user)
        # New referrals start PENDING — bonuses pay out on first job
        self.assertEqual(referral.status, 'PENDING')
        self.assertIsNone(referral.awarded_at)


class RewardSystemTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='test company',
            email='test@company.com'
        )
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer
        )

    def test_reward_type_string_representation(self):
        # Test percentage discount
        reward_type = RewardType.objects.create(
            name='Repair Discount',
            category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE',
            discount_value=Decimal('25.00')
        )
        self.assertEqual(str(reward_type), 'Repair Discount - 25.00% off')
        
        # Test fixed amount discount
        reward_type_fixed = RewardType.objects.create(
            name='Dollar Off',
            category='REPAIR_DISCOUNT',
            discount_type='FIXED_AMOUNT',
            discount_value=Decimal('10.00')
        )
        self.assertEqual(str(reward_type_fixed), 'Dollar Off - $10.00 off')
        
        # Test free reward
        reward_type_free = RewardType.objects.create(
            name='Free Service',
            category='FREE_SERVICE',
            discount_type='FREE'
        )
        self.assertEqual(str(reward_type_free), 'Free Service - Free')

    def test_reward_creation(self):
        reward = Reward.objects.create(
            customer=self.customer,
            points=100
        )
        self.assertEqual(reward.points, 100)
        self.assertIn(self.customer.name, str(reward))
        self.assertIn('100 points', str(reward))

    def test_reward_option_creation(self):
        reward_type = RewardType.objects.create(
            name='Repair Discount',
            category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE',
            discount_value=Decimal('25.00')
        )
        
        reward_option = RewardOption.objects.create(
            name='25% Off Next Repair',
            description='Get 25% off your next windshield repair',
            points_required=50,
            reward_type=reward_type
        )
        self.assertEqual(str(reward_option), '25% Off Next Repair (50 points)')
        self.assertEqual(reward_option.reward_type, reward_type)

    def test_reward_redemption_workflow(self):
        # Create reward system components
        reward_type = RewardType.objects.create(
            name='Repair Discount',
            category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE',
            discount_value=Decimal('25.00')
        )
        
        reward_option = RewardOption.objects.create(
            name='25% Off Next Repair',
            description='Get 25% off your next windshield repair',
            points_required=50,
            reward_type=reward_type
        )
        
        reward = Reward.objects.create(
            customer=self.customer,
            points=100
        )

        # Create redemption
        redemption = RewardRedemption.objects.create(
            reward=reward,
            reward_option=reward_option,
            status='PENDING'
        )

        self.assertEqual(redemption.status, 'PENDING')
        self.assertEqual(redemption.reward_option, reward_option)
        self.assertIn(self.customer.name, str(redemption))
        self.assertIn('PENDING', str(redemption))