# Service classes:
# - LoyaltyService (THE single entry point for all point changes)
# - ReferralService (code generation, tracking)
# - RewardService (point calculation, redemption)
# - RewardFulfillmentService (assignment and fulfillment of rewards)

import logging
import random
import string
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    LoyaltyConfig,
    PointTransaction,
    Referral,
    ReferralCode,
    Reward,
    RewardOption,
    RewardRedemption,
)
from apps.customer_portal.models import CustomerUser
from core.models import Customer

logger = logging.getLogger(__name__)


class LoyaltyService:
    """Single entry point for all point balance changes."""

    @staticmethod
    @transaction.atomic
    def award_points(customer_user, amount, transaction_type, description,
                     tenant=None, related_repair=None, related_payment=None,
                     related_redemption=None, created_by=None):
        """
        Award (or deduct) points and create an immutable PointTransaction.

        Returns the PointTransaction, or None if the loyalty program is inactive.
        """
        # Resolve tenant
        if tenant is None:
            tenant = customer_user.customer.tenant

        config = LoyaltyConfig.get_for_tenant(tenant)
        if not config.is_active:
            return None

        # Lock the Reward row (CODE-165 / CODE-173 pattern).
        # Use get_or_create() so concurrent calls don't race between a failed
        # .get() and a subsequent .create() — which could produce two Reward rows
        # for the same customer_user and cause MultipleObjectsReturned on the
        # next call.  The unique_reward_per_customer_user DB constraint enforces
        # this at the database level as a second line of defence.
        reward, _created = Reward.objects.get_or_create(
            customer_user=customer_user,
            defaults={'tenant': tenant, 'points': 0},
        )
        # Re-fetch with select_for_update so the row is locked for the
        # balance increment below (prevents concurrent double-spend).
        reward = Reward.objects.select_for_update().get(pk=reward.pk)

        # Ensure tenant is set on legacy Reward rows
        if reward.tenant_id is None:
            reward.tenant = tenant

        reward.points += amount
        reward.save()

        # Compute expiry
        expires_at = None
        if amount > 0 and config.points_expiry_days > 0:
            expires_at = timezone.now() + timedelta(days=config.points_expiry_days)

        pt = PointTransaction.objects.create(
            tenant=tenant,
            customer_user=customer_user,
            amount=amount,
            balance_after=reward.points,
            transaction_type=transaction_type,
            description=description,
            related_repair=related_repair,
            related_redemption=related_redemption,
            related_payment=related_payment,
            expires_at=expires_at,
            created_by=created_by,
        )
        return pt

    @staticmethod
    def get_balance(customer_user):
        """Return cached balance from Reward row."""
        reward = Reward.objects.filter(customer_user=customer_user).first()
        return reward.points if reward else 0

    @staticmethod
    def get_transaction_history(customer_user, limit=20):
        """Return recent PointTransactions."""
        qs = PointTransaction.objects.filter(
            customer_user=customer_user,
        ).order_by('-created_at')
        if limit:
            qs = qs[:limit]
        return qs

    @staticmethod
    def get_lifetime_earned(customer_user):
        """Sum of all positive PointTransactions (for tier calculation)."""
        result = PointTransaction.objects.filter(
            customer_user=customer_user,
            amount__gt=0,
        ).aggregate(total=Sum('amount'))
        return result['total'] or 0


class ReferralService:
    """
    Service class for managing referral-related operations.

    This class provides methods for generating and validating referral codes,
    processing referrals, and retrieving referral statistics.
    """

    # Legacy class-level constants kept for backwards compat, but
    # process_referral() now reads from LoyaltyConfig.
    REFERRER_POINTS = 500
    REFERRED_POINTS = 100

    @staticmethod
    def generate_referral_code(customer_user):
        """Generate a random 6-character referral code for a given customer."""
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        ReferralCode.objects.create(code=code, customer_user=customer_user)
        return code

    @staticmethod
    def track_referral(referral_code, customer_user):
        """Create a record of a successful referral."""
        referral = Referral.objects.create(referral_code=referral_code, customer_user=customer_user)
        return referral

    @staticmethod
    def validate_referral_code(code):
        """Validate a referral code and return the ReferralCode object if valid."""
        try:
            return ReferralCode.objects.get(code=code)
        except ReferralCode.DoesNotExist:
            return None

    @staticmethod
    @transaction.atomic
    def process_referral(referral_code_obj, customer_user):
        """
        Process a referral when a new user signs up with a referral code.

        Reads point values from LoyaltyConfig and delegates to LoyaltyService.
        """
        # Ensure users can't refer themselves
        if referral_code_obj.customer_user == customer_user:
            return False

        # Ensure both parties belong to the same tenant (CODE-072)
        try:
            code_tenant = referral_code_obj.customer_user.customer.tenant
            user_tenant = customer_user.customer.tenant
            if code_tenant.pk != user_tenant.pk:
                return False
        except AttributeError:
            return False

        # Check if this referral already exists
        if Referral.objects.filter(referral_code=referral_code_obj, customer_user=customer_user).exists():
            return False

        # Create the referral
        Referral.objects.create(
            referral_code=referral_code_obj,
            customer_user=customer_user
        )

        tenant = customer_user.customer.tenant
        config = LoyaltyConfig.get_for_tenant(tenant)

        # Award points to the referrer
        referrer = referral_code_obj.customer_user
        LoyaltyService.award_points(
            customer_user=referrer,
            amount=config.referral_bonus_referrer,
            transaction_type='referral_made',
            description=f'Referral bonus — referred {customer_user.user.email}',
            tenant=tenant,
        )

        # Award points to the referred user
        LoyaltyService.award_points(
            customer_user=customer_user,
            amount=config.referral_bonus_referred,
            transaction_type='referral_received',
            description='Welcome bonus — signed up with referral code',
            tenant=tenant,
        )

        return True

    @staticmethod
    def get_referral_count(customer_user):
        """Get the number of successful referrals for a user."""
        try:
            referral_code = ReferralCode.objects.get(customer_user=customer_user)
            return Referral.objects.filter(referral_code=referral_code).count()
        except ReferralCode.DoesNotExist:
            return 0

    @staticmethod
    def generate_code_for_user(customer_user, length=8):
        """Generate a new referral code for a user, or return their existing one."""
        existing = ReferralCode.objects.filter(customer_user=customer_user).first()
        if existing:
            return existing

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
        """Calculate points based on customer's activity."""
        points = 0
        return points

    @staticmethod
    def get_reward_options(active_only=True, tenant=None):
        """Get available reward options, scoped to tenant."""
        qs = RewardOption.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        if active_only:
            qs = qs.filter(is_active=True)
        return qs

    @staticmethod
    def get_reward_redemptions(customer_user):
        """Get all reward redemptions for a customer."""
        return RewardRedemption.objects.filter(reward__customer_user=customer_user).order_by('-created_at')

    @staticmethod
    def get_reward_balance(customer_user):
        """Get the current reward balance for a user."""
        return LoyaltyService.get_balance(customer_user)

    @staticmethod
    def get_reward_history(customer_user):
        """Get reward history for a customer."""
        return Reward.objects.filter(customer_user=customer_user).order_by('-created_at')

    @staticmethod
    @transaction.atomic
    def redeem_reward(customer_user, reward_option_id):
        """
        Redeem a reward for a user via LoyaltyService.

        Returns:
            tuple: (bool success, str message or RewardRedemption object)
        """
        try:
            tenant = customer_user.customer.tenant
            reward_option = RewardOption.objects.get(id=reward_option_id, tenant=tenant)

            if not reward_option.is_active:
                return False, "This reward option is not currently available."

            # Lock the Reward row (CODE-165 / CODE-173 pattern).
            # Use get_or_create() to avoid the race that produces duplicate rows.
            reward, _created = Reward.objects.get_or_create(
                customer_user=customer_user,
                defaults={'tenant': tenant, 'points': 0},
            )
            reward = Reward.objects.select_for_update().get(pk=reward.pk)

            if reward.points < reward_option.points_required:
                return False, f"Not enough points. You need {reward_option.points_required}, but have {reward.points}."

            # Create redemption record
            redemption = RewardRedemption.objects.create(
                reward=reward,
                reward_option=reward_option,
                status='PENDING'
            )

            # Deduct via LoyaltyService (updates Reward.points + creates PointTransaction)
            LoyaltyService.award_points(
                customer_user=customer_user,
                amount=-reward_option.points_required,
                transaction_type='redemption',
                description=f'Redeemed: {reward_option.name}',
                tenant=tenant,
                related_redemption=redemption,
            )

            return True, redemption

        except RewardOption.DoesNotExist:
            return False, "Invalid reward option"

    @staticmethod
    def get_available_rewards(customer_user):
        """Get list of rewards the user can redeem based on their balance."""
        points = RewardService.get_reward_balance(customer_user)

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
        """Get reward redemption history for a user."""
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
        """Assign the most appropriate technician to fulfill a reward."""
        from django.db.models import Count, Q
        from apps.technician_portal.models import Technician, Repair

        try:
            tenant = redemption.reward.customer_user.customer.tenant
        except AttributeError:
            tenant = None
        technicians_qs = Technician.objects.all()
        if tenant:
            technicians_qs = technicians_qs.filter(tenant=tenant)

        if not technicians_qs.exists():
            return None

        assigned_technician = (
            technicians_qs
            .annotate(
                active_repair_count=Count(
                    'repair',
                    filter=~Q(repair__queue_status__in=['COMPLETED', 'DENIED'])
                )
            )
            .order_by('active_repair_count', 'id')
            .first()
        )

        if assigned_technician is None:
            return None

        redemption.assigned_technician = assigned_technician
        redemption.save()

        RewardFulfillmentService.notify_technician(redemption, assigned_technician)

        return assigned_technician

    @staticmethod
    def notify_technician(redemption, technician):
        """Send notification to technician about new reward fulfillment."""
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
        """Mark a redemption as fulfilled by a technician."""
        redemption.status = 'FULFILLED'
        redemption.processed_by = technician.user
        redemption.processed_at = timezone.now()
        redemption.fulfilled_at = timezone.now()

        if notes:
            redemption.notes = notes

        redemption.save()

        return redemption

    @staticmethod
    def get_pending_redemptions(tenant=None):
        """Get all pending redemptions that need to be fulfilled."""
        qs = RewardRedemption.objects.filter(status='PENDING')
        if tenant:
            qs = qs.filter(reward__customer_user__customer__tenant=tenant)
        return qs.order_by('created_at')

    @staticmethod
    def get_technician_redemptions(technician):
        """Get all redemptions assigned to a specific technician."""
        return RewardRedemption.objects.filter(
            assigned_technician=technician
        ).exclude(
            status='FULFILLED'
        ).order_by('created_at')
