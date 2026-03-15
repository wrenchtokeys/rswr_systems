# Service classes:
# - ReferralService (code generation, tracking)
# - RewardService (point calculation, redemption)
# - RewardFulfillmentService (assignment and fulfillment of rewards)

from django.utils import timezone
from .models import ReferralCode, Referral, Reward, RewardOption, RewardRedemption
from core.models import Customer
from apps.customer_portal.models import CustomerUser
import random
import string
from django.db.models import Sum
from django.db import transaction

class ReferralService:
    """
    Service class for managing referral-related operations.
    
    This class provides methods for generating and validating referral codes,
    processing referrals, and retrieving referral statistics.
    """
    
    # Constants for point awards
    REFERRER_POINTS = 500  # Points awarded to the person who referred someone
    REFERRED_POINTS = 100  # Points awarded to the person who was referred
    
    @staticmethod
    def generate_referral_code(customer_user):
        """
        Generate a random 6-character referral code for a given customer.
        
        Args:
            customer_user (CustomerUser): The customer to generate a code for
            
        Returns:
            str: The generated referral code
        """
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        ReferralCode.objects.create(code=code, customer_user=customer_user)
        return code
    
    @staticmethod
    def track_referral(referral_code, customer_user):
        """
        Create a record of a successful referral.
        
        Args:
            referral_code (ReferralCode): The referral code that was used
            customer_user (CustomerUser): The customer who used the referral code
            
        Returns:
            Referral: The created referral object
        """
        referral = Referral.objects.create(referral_code=referral_code, customer_user=customer_user)
        return referral
    
    @staticmethod
    def validate_referral_code(code):
        """
        Validate a referral code and return the ReferralCode object if valid.
        
        Args:
            code (str): The referral code to validate
            
        Returns:
            ReferralCode: The referral code object if valid, None otherwise
        """
        try:
            return ReferralCode.objects.get(code=code)
        except ReferralCode.DoesNotExist:
            return None
    
    @staticmethod
    @transaction.atomic
    def process_referral(referral_code_obj, customer_user):
        """
        Process a referral when a new user signs up with a referral code.
        
        This method:
        1. Verifies the referral is valid (not self-referral, not duplicate)
        2. Creates a referral record
        3. Awards points to both the referrer (500) and the referred user (100)
        
        Args:
            referral_code_obj (ReferralCode): The referral code object
            customer_user (CustomerUser): The customer who used the code
            
        Returns:
            bool: True if the referral was processed successfully, False otherwise
        """
        # Ensure users can't refer themselves
        if referral_code_obj.customer_user == customer_user:
            return False
        
        # Check if this referral already exists
        if Referral.objects.filter(referral_code=referral_code_obj, customer_user=customer_user).exists():
            return False
        
        # Create the referral
        Referral.objects.create(
            referral_code=referral_code_obj,
            customer_user=customer_user
        )
        
        # Give points to the referrer
        referrer = referral_code_obj.customer_user
        reward, created = Reward.objects.get_or_create(customer_user=referrer)
        reward.points += ReferralService.REFERRER_POINTS
        reward.save()
        
        # Also give points to the referred user as a welcome bonus
        referred_reward, created = Reward.objects.get_or_create(customer_user=customer_user)
        referred_reward.points += ReferralService.REFERRED_POINTS
        referred_reward.save()
        
        return True
    
    @staticmethod
    def get_referral_count(customer_user):
        """
        Get the number of successful referrals for a user.
        
        Args:
            customer_user (CustomerUser): The customer to check referrals for
            
        Returns:
            int: The number of successful referrals
        """
        try:
            referral_code = ReferralCode.objects.get(customer_user=customer_user)
            return Referral.objects.filter(referral_code=referral_code).count()
        except ReferralCode.DoesNotExist:
            return 0
    
    @staticmethod
    def generate_code_for_user(customer_user, length=8):
        """
        Generate a new referral code for a user, or return their existing one.
        
        Args:
            customer_user (CustomerUser): The customer to generate a code for
            length (int): The length of the referral code to generate
            
        Returns:
            ReferralCode: The customer's referral code object (new or existing)
        """
        # Check if user already has a code
        existing = ReferralCode.objects.filter(customer_user=customer_user).first()
        if existing:
            return existing
        
        # Generate a new code
        characters = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choice(characters) for _ in range(length))
            if not ReferralCode.objects.filter(code=code).exists():
                return ReferralCode.objects.create(
                    code=code,
                    customer_user=customer_user
                )

class RewardService:
    """
    Service class for managing reward-related operations.
    
    This class provides methods for calculating reward points,
    processing reward redemptions, and retrieving reward histories.
    """
    
    @staticmethod
    def calculate_points(customer_user):
        """
        Calculate points based on customer's activity.
        
        Args:
            customer_user (CustomerUser): The customer to calculate points for
            
        Returns:
            int: The calculated points
        """
        # Calculate points based on customer's activity
        points = 0
        
        # Example: 1 point per completed task
        # points = Referral.objects.filter(customer_user=customer_user).count()
        return points
    
    @staticmethod
    def redeem_reward(reward):
        """
        Process reward redemption.
        
        Args:
            reward (Reward): The reward to redeem
            
        Returns:
            Reward: The updated reward object
        """
        # Process reward redemption
        reward.redeemed = True
        reward.save()
        return reward

    @staticmethod
    def get_reward_options(active_only=True, tenant=None):
        """
        Get available reward options, scoped to tenant.

        Args:
            active_only (bool): Whether to return only active reward options
            tenant: Tenant instance to filter by

        Returns:
            QuerySet: Reward options
        """
        qs = RewardOption.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        if active_only:
            qs = qs.filter(is_active=True)
        return qs
    
    @staticmethod
    def get_reward_redemptions(customer_user):
        """
        Get all reward redemptions for a customer.
        
        Args:
            customer_user (CustomerUser): The customer to get redemptions for
            
        Returns:
            QuerySet: The customer's redemptions
        """
        return RewardRedemption.objects.filter(reward__customer_user=customer_user).order_by('-created_at')
    
    @staticmethod
    def get_reward_balance(customer_user):
        """
        Get the current reward balance for a user.
        
        Args:
            customer_user (CustomerUser): The customer to get balance for
            
        Returns:
            int: The customer's current point balance
        """
        reward = Reward.objects.filter(customer_user=customer_user).first()
        return reward.points if reward else 0
    
    @staticmethod
    def get_reward_history(customer_user):
        """
        Get reward history for a customer.
        
        Args:
            customer_user (CustomerUser): The customer to get history for
            
        Returns:
            QuerySet: The customer's reward history
        """
        return Reward.objects.filter(customer_user=customer_user).order_by('-created_at')
    
    @staticmethod
    @transaction.atomic
    def redeem_reward(customer_user, reward_option_id):
        """
        Redeem a reward for a user.
        
        This method:
        1. Verifies the user has enough points for the chosen reward
        2. Creates a redemption record
        3. Deducts points from the user's balance
        
        Args:
            customer_user (CustomerUser): The customer redeeming the reward
            reward_option_id (int): The ID of the reward option to redeem
            
        Returns:
            tuple: (bool success, str message or RewardRedemption object)
        """
        try:
            # Scope the lookup to the customer's tenant to prevent IDOR
            # (a customer from Shop A must not be able to redeem Shop B's options)
            tenant = customer_user.customer.tenant
            reward_option = RewardOption.objects.get(id=reward_option_id, tenant=tenant)
            
            # Check if reward option is active
            if not reward_option.is_active:
                return False, "This reward option is not currently available."
                
            reward, created = Reward.objects.get_or_create(customer_user=customer_user)
            
            # Check if user has enough points
            if reward.points < reward_option.points_required:
                return False, f"Not enough points. You need {reward_option.points_required}, but have {reward.points}."
            
            # Create redemption record
            redemption = RewardRedemption.objects.create(
                reward=reward,
                reward_option=reward_option,
                status='PENDING'
            )
            
            # Deduct points
            reward.points -= reward_option.points_required
            reward.save()
            
            return True, redemption
            
        except RewardOption.DoesNotExist:
            return False, "Invalid reward option"
    
    @staticmethod
    def get_available_rewards(customer_user):
        """
        Get list of rewards the user can redeem based on their balance.
        
        Separates rewards into 'available' and 'unavailable' categories
        based on whether the user has enough points to redeem them.
        
        Args:
            customer_user (CustomerUser): The customer to get rewards for
            
        Returns:
            dict: Dictionary with 'available' and 'unavailable' reward lists
        """
        points = RewardService.get_reward_balance(customer_user)
        
        # Scope to the customer's tenant to prevent cross-tenant data leaks
        tenant = customer_user.customer.tenant
        all_rewards = RewardOption.objects.filter(is_active=True, tenant=tenant).order_by('points_required')
        
        result = {
            'available': [],
            'unavailable': []
        }
        
        for option in all_rewards:
            if option.points_required <= points:
                result['available'].append(option)
            else:
                result['unavailable'].append(option)
        
        return result
    
    @staticmethod
    def get_redemption_history(customer_user, limit=None):
        """
        Get reward redemption history for a user.
        
        Args:
            customer_user (CustomerUser): The customer to get history for
            limit (int, optional): Maximum number of records to return
            
        Returns:
            QuerySet: The customer's redemption history
        """
        redemptions = RewardRedemption.objects.filter(
            reward__customer_user=customer_user
        ).order_by('-created_at')
        
        if limit:
            redemptions = redemptions[:limit]
            
        return redemptions

class RewardFulfillmentService:
    """
    Service class for fulfilling reward redemptions.
    
    This class provides methods for assigning technicians to fulfill
    reward redemptions and tracking the fulfillment process.
    """
    
    @staticmethod
    def assign_technician(redemption):
        """
        Assign the most appropriate technician to fulfill a reward.
        
        This method uses a simple workload-based algorithm to assign
        the technician with the least active repairs.
        
        Args:
            redemption (RewardRedemption): The redemption to assign
            
        Returns:
            Technician: The assigned technician, or None if no technicians are available
        """
        from django.db.models import Count, Q
        from apps.technician_portal.models import Technician, Repair

        # Get active technicians scoped to the redemption's tenant
        try:
            tenant = redemption.reward.customer_user.customer.tenant
        except AttributeError:
            tenant = None
        technicians_qs = Technician.objects.all()
        if tenant:
            technicians_qs = technicians_qs.filter(tenant=tenant)

        if not technicians_qs.exists():
            return None

        # Single annotated query: get each technician's active-repair count in one shot.
        # Previously this was an N+1 loop (one COUNT per technician row).
        assigned_technician = (
            technicians_qs
            .annotate(
                active_repair_count=Count(
                    'repair',
                    filter=~Q(repair__queue_status__in=['COMPLETED', 'DENIED'])
                )
            )
            .order_by('active_repair_count', 'id')  # stable tie-break by PK
            .first()
        )

        if assigned_technician is None:
            return None
        
        # Assign to redemption
        redemption.assigned_technician = assigned_technician
        redemption.save()
        
        # Send notification
        RewardFulfillmentService.notify_technician(redemption, assigned_technician)
        
        return assigned_technician
    
    @staticmethod
    def notify_technician(redemption, technician):
        """
        Send notification to technician about new reward fulfillment.
        
        Creates a notification record in the database that will be displayed
        to the technician in their portal.
        
        Args:
            redemption (RewardRedemption): The redemption to notify about
            technician (Technician): The technician to notify
        """
        # For now, we'll implement a simple notification in the DB
        # In a real system, this might send an email, SMS, or push notification
        from django.utils import timezone
        from apps.technician_portal.models import TechnicianNotification
        
        TechnicianNotification.objects.create(
            technician=technician,
            message=f"New reward redemption to fulfill: {redemption.reward_option.name} for {redemption.reward.customer_user.user.email}",
            redemption=redemption,
            created_at=timezone.now()
        )
        
    @staticmethod
    @transaction.atomic
    def mark_as_fulfilled(redemption, technician, notes=None):
        """
        Mark a redemption as fulfilled by a technician.
        
        Args:
            redemption (RewardRedemption): The redemption to mark as fulfilled
            technician (Technician): The technician who fulfilled the redemption
            notes (str, optional): Additional notes about the fulfillment
            
        Returns:
            RewardRedemption: The updated redemption object
        """
        from django.utils import timezone
        
        redemption.status = 'FULFILLED'
        redemption.processed_by = technician.user
        redemption.processed_at = timezone.now()
        redemption.fulfilled_at = timezone.now()
        
        if notes:
            redemption.notes = notes
            
        redemption.save()
        
        # Notify the customer (implementation will vary based on system requirements)
        # This could send an email, SMS, or update the customer dashboard
        
        return redemption
        
    @staticmethod
    def get_pending_redemptions(tenant=None):
        """
        Get all pending redemptions that need to be fulfilled.
        
        Args:
            tenant: Optional tenant to scope results
            
        Returns:
            QuerySet: All pending redemptions
        """
        qs = RewardRedemption.objects.filter(status='PENDING')
        if tenant:
            qs = qs.filter(reward__customer_user__customer__tenant=tenant)
        return qs.order_by('created_at')
        
    @staticmethod
    def get_technician_redemptions(technician):
        """
        Get all redemptions assigned to a specific technician.
        
        Args:
            technician (Technician): The technician
            
        Returns:
            QuerySet: Redemptions assigned to the technician
        """
        return RewardRedemption.objects.filter(
            assigned_technician=technician
        ).exclude(
            status='FULFILLED'
        ).order_by('created_at')
    