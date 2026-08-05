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
    def award_points(customer, amount, transaction_type, description,
                     tenant=None, acting_customer_user=None,
                     related_repair=None, related_replacement=None,
                     related_payment=None, related_redemption=None, created_by=None):
        """
        Award (or deduct) points for a customer (company) and create an
        immutable PointTransaction.

        ``customer`` is a core.Customer — points do not require a portal
        account. ``acting_customer_user`` optionally records which portal
        user triggered the change (attribution only).

        Returns the PointTransaction, or None if the loyalty program is
        inactive or the customer has no tenant.
        """
        # Resolve tenant. Customer.tenant is nullable — never look up config
        # for a tenant-less customer.
        if tenant is None:
            tenant = customer.tenant
        if tenant is None:
            logger.warning(
                'award_points skipped: customer pk=%s has no tenant', customer.pk,
            )
            return None

        config = LoyaltyConfig.get_for_tenant(tenant)
        if not config.is_active:
            return None

        # Lock the Reward row (CODE-165 / CODE-173 pattern).
        # Use get_or_create() so concurrent calls don't race between a failed
        # .get() and a subsequent .create() — which could produce two Reward rows
        # for the same customer and cause MultipleObjectsReturned on the
        # next call.  The unique_reward_per_customer DB constraint enforces
        # this at the database level as a second line of defence.
        reward, _created = Reward.objects.get_or_create(
            customer=customer,
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
            customer=customer,
            customer_user=acting_customer_user,
            amount=amount,
            balance_after=reward.points,
            transaction_type=transaction_type,
            description=description,
            related_repair=related_repair,
            related_replacement=related_replacement,
            related_redemption=related_redemption,
            related_payment=related_payment,
            expires_at=expires_at,
            created_by=created_by,
        )
        return pt

    @staticmethod
    def get_balance(customer):
        """Return cached balance from the customer's Reward row."""
        reward = Reward.objects.filter(customer=customer).first()
        return reward.points if reward else 0

    @staticmethod
    def get_transaction_history(customer, limit=20):
        """Return recent PointTransactions for a customer."""
        qs = PointTransaction.objects.filter(
            customer=customer,
        ).order_by('-created_at')
        if limit:
            qs = qs[:limit]
        return qs

    @staticmethod
    def get_lifetime_earned(customer):
        """Sum of all positive PointTransactions (for tier calculation).

        Redemption refunds are excluded — refunded points were already
        counted when originally earned.
        """
        result = PointTransaction.objects.filter(
            customer=customer,
            amount__gt=0,
        ).exclude(
            transaction_type='redemption_refund',
        ).aggregate(total=Sum('amount'))
        return result['total'] or 0

    @staticmethod
    def get_email_balance_line(customer):
        """
        One-line factual balance string for transactional emails, or None.

        The single gate both invoice and review emails use: program active,
        shop's show_balance_in_emails toggle on, and a positive balance.
        Returns None on any failure — emails must never break on loyalty.
        """
        try:
            tenant = customer.tenant
            if tenant is None:
                return None
            config = LoyaltyConfig.get_for_tenant(tenant)
            if not (config.is_active and config.show_balance_in_emails):
                return None
            balance = LoyaltyService.get_balance(customer)
            if balance <= 0:
                return None
            # One factual sentence with a claim hint. Deliberately no links:
            # most earning customers have no portal login, and links push
            # invoice email toward a promotional classification (SES rules).
            return (
                f"{config.program_name} balance: {balance:,} points — "
                "ask us about redeeming them on your next service."
            )
        except Exception:
            logger.debug('get_email_balance_line skipped', exc_info=True)
            return None

    @staticmethod
    def reconcile_balance(customer):
        """
        Recompute Reward.points from the PointTransaction ledger and flag drift.

        Returns a dict:
            {
                'ledger_sum': int,
                'cached_balance': int,
                'drift': int,          # ledger_sum - cached_balance
                'in_sync': bool,
            }

        Does NOT mutate any data — read-only diagnostic method.
        Use the reconcile_loyalty_balances management command (with --fix) to
        correct drift automatically, or update Reward.points manually.
        """
        ledger_sum = (
            PointTransaction.objects
            .filter(customer=customer)
            .aggregate(total=Sum('amount'))
        )['total'] or 0

        reward = Reward.objects.filter(customer=customer).first()
        cached_balance = reward.points if reward else 0

        drift = ledger_sum - cached_balance
        return {
            'ledger_sum': ledger_sum,
            'cached_balance': cached_balance,
            'drift': drift,
            'in_sync': drift == 0,
        }

    @staticmethod
    @transaction.atomic
    def manual_adjustment(customer, amount, reason, created_by, tenant=None):
        """
        Apply a manual point adjustment by an owner or manager.

        ``amount`` may be positive (award) or negative (deduct).
        ``reason`` is required for audit purposes and stored in description.
        ``created_by`` must be the Django User making the adjustment.

        Returns the created PointTransaction, or raises ValueError on bad input.
        Raises ValueError if:
          - amount is zero
          - reason is blank
          - a deduction would take the balance below zero
          - the loyalty program is inactive

        This method does NOT bypass LoyaltyService.award_points() — it uses it
        as the single write path so every adjustment appears in the ledger with
        the correct balance_after and tenant FK.
        """
        if amount == 0:
            raise ValueError('Adjustment amount cannot be zero.')
        if not reason or not str(reason).strip():
            raise ValueError('A reason is required for manual point adjustments (audit trail).')

        if tenant is None:
            tenant = customer.tenant
        if tenant is None:
            raise ValueError('Cannot adjust points for a customer with no tenant.')

        config = LoyaltyConfig.get_for_tenant(tenant)
        if not config.is_active:
            raise ValueError('Cannot make adjustments while the loyalty program is inactive.')

        if amount < 0:
            # Guard: deductions must not take the balance below zero.
            # Lock first to get the current balance under the atomic block.
            reward, _ = Reward.objects.get_or_create(
                customer=customer,
                defaults={'tenant': tenant, 'points': 0},
            )
            reward = Reward.objects.select_for_update().get(pk=reward.pk)
            if reward.points + amount < 0:
                raise ValueError(
                    f'Deduction of {abs(amount)} would take balance below zero '
                    f'(current balance: {reward.points}).'
                )

        description = f'Manual adjustment: {str(reason).strip()}'
        pt = LoyaltyService.award_points(
            customer=customer,
            amount=amount,
            transaction_type='manual_adjustment',
            description=description,
            tenant=tenant,
            created_by=created_by,
        )
        return pt

    @staticmethod
    def get_point_liability_report(tenant):
        """
        Return a point liability summary for a tenant.

        Liability = total outstanding (un-redeemed, un-expired) points across
        all customers. This is the maximum points exposure the shop has.

        Returns a dict:
            {
                'total_outstanding_points': int,
                'total_issued_lifetime': int,
                'total_redeemed_lifetime': int,
                'total_expired_lifetime': int,
                'total_manually_adjusted': int,
                'active_customer_count': int,
                'customers': [
                    {
                        'customer_id': int,
                        'customer_name': str,
                        'email': str,          # Customer.email (may be '')
                        'current_balance': int,
                        'lifetime_earned': int,
                        'lifetime_redeemed': int,
                        'lifetime_expired': int,
                    },
                    ...
                ],
            }
        """
        from django.db.models import Sum, Q, Count, Case, When, IntegerField, Value

        # Aggregate PointTransaction by transaction_type for this tenant
        stats = (
            PointTransaction.objects
            .filter(tenant=tenant)
            .aggregate(
                issued=Sum(
                    Case(
                        When(amount__gt=0, transaction_type__in=[
                            'repair_complete', 'referral_made', 'referral_received',
                            'milestone_bonus', 'early_pay_bonus', 'review_bonus',
                            'tier_bonus',
                        ], then='amount'),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                manual_positive=Sum(
                    Case(
                        When(amount__gt=0, transaction_type='manual_adjustment', then='amount'),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                manual_negative=Sum(
                    Case(
                        When(amount__lt=0, transaction_type='manual_adjustment', then='amount'),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                # Refunds (positive) net against redemptions (negative) so a
                # cancelled redemption doesn't inflate lifetime-redeemed.
                redeemed=Sum(
                    Case(
                        When(transaction_type__in=['redemption', 'redemption_refund'], then='amount'),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                expired=Sum(
                    Case(
                        When(transaction_type='expiration', then='amount'),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
            )
        )

        total_issued = (stats['issued'] or 0) + (stats['manual_positive'] or 0)
        total_redeemed = abs(stats['redeemed'] or 0)
        total_expired = abs(stats['expired'] or 0)
        total_manual_deducted = abs(stats['manual_negative'] or 0)

        # Total outstanding = current sum of all Reward.points for this tenant
        total_outstanding = (
            Reward.objects
            .filter(
                tenant=tenant,
                points__gt=0,
            )
            .aggregate(total=Sum('points'))
        )['total'] or 0

        # Per-customer breakdown — only customers with any activity.
        # Build stats in a SINGLE annotated query (CODE-200 fix: was N+1).
        per_customer_stats = {
            row['customer_id']: row
            for row in (
                PointTransaction.objects
                .filter(tenant=tenant)
                .values('customer_id')
                .annotate(
                    # Refunds are excluded from earned (already counted when
                    # first earned) and net against redeemed.
                    c_issued=Sum(
                        Case(
                            When(
                                Q(amount__gt=0) & ~Q(transaction_type='redemption_refund'),
                                then='amount',
                            ),
                            default=Value(0),
                            output_field=IntegerField(),
                        )
                    ),
                    c_redeemed=Sum(
                        Case(
                            When(transaction_type__in=['redemption', 'redemption_refund'], then='amount'),
                            default=Value(0),
                            output_field=IntegerField(),
                        )
                    ),
                    c_expired=Sum(
                        Case(
                            When(transaction_type='expiration', then='amount'),
                            default=Value(0),
                            output_field=IntegerField(),
                        )
                    ),
                )
            )
        }

        customer_data = []
        rewards = (
            Reward.objects
            .filter(tenant=tenant)
            .select_related('customer')
            .order_by('-points')
        )

        for reward in rewards:
            customer = reward.customer
            c_stats = per_customer_stats.get(customer.pk, {})
            customer_data.append({
                'customer_id': customer.pk,
                'customer_name': customer.name,
                'email': customer.email or '',
                'current_balance': reward.points,
                'lifetime_earned': c_stats.get('c_issued') or 0,
                'lifetime_redeemed': abs(c_stats.get('c_redeemed') or 0),
                'lifetime_expired': abs(c_stats.get('c_expired') or 0),
            })

        active_count = sum(1 for c in customer_data if c['current_balance'] > 0)

        return {
            'total_outstanding_points': total_outstanding,
            'total_issued_lifetime': total_issued,
            'total_redeemed_lifetime': total_redeemed,
            'total_expired_lifetime': total_expired,
            'total_manually_adjusted': (stats['manual_positive'] or 0) + (stats['manual_negative'] or 0),
            'active_customer_count': active_count,
            'customers': customer_data,
        }


class ReferralService:
    """
    Service class for managing referral-related operations.

    This class provides methods for generating and validating referral codes,
    processing referrals, and retrieving referral statistics.
    """

    # Legacy class-level constants kept for backwards compat, but
    # award_referral_bonuses() now reads from LoyaltyConfig.
    REFERRER_POINTS = 500
    REFERRED_POINTS = 100

    @staticmethod
    def validate_referral_code(code):
        """Validate a referral code and return the ReferralCode object if valid."""
        try:
            return ReferralCode.objects.get(code=code)
        except ReferralCode.DoesNotExist:
            return None

    @staticmethod
    @transaction.atomic
    def record_referral(referral_code_obj, customer_user):
        """
        Record a referral at signup time — NO points move here.

        Creates a PENDING Referral; bonuses pay out via
        award_referral_bonuses() when the referred customer's first job
        completes. Deferring the payout means fake signups earn nothing.

        Returns True if the referral was recorded, False if rejected
        (self-referral, cross-tenant, or duplicate).
        """
        # Ensure users can't refer themselves — neither their own portal
        # account nor another portal account of the same company.
        if referral_code_obj.customer_user == customer_user:
            return False
        if referral_code_obj.customer_user.customer_id == customer_user.customer_id:
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

        Referral.objects.create(
            referral_code=referral_code_obj,
            customer_user=customer_user,
            status='PENDING',
        )
        return True

    @staticmethod
    @transaction.atomic
    def award_referral_bonuses(customer):
        """
        Pay out PENDING referrals for a customer's portal users.

        Called by the completion hook when one of the customer's jobs
        completes. Idempotent: each Referral pays exactly once (status flag,
        row-locked). Referrer earns per referral; the referred customer's
        welcome bonus pays at most once per customer.

        Returns the number of referrals awarded.
        """
        pending = list(
            Referral.objects.select_for_update()
            .filter(customer_user__customer=customer, status='PENDING')
            .select_related('referral_code__customer_user__customer', 'customer_user')
        )
        if not pending:
            return 0

        tenant = customer.tenant
        if tenant is None:
            return 0
        config = LoyaltyConfig.get_for_tenant(tenant)

        awarded = 0
        for referral in pending:
            referrer_cu = referral.referral_code.customer_user
            LoyaltyService.award_points(
                customer=referrer_cu.customer,
                amount=config.referral_bonus_referrer,
                transaction_type='referral_made',
                description=f'Referral bonus — {customer.name} completed their first job',
                tenant=tenant,
                acting_customer_user=referrer_cu,
            )

            # Welcome bonus — AT MOST ONCE per referred customer. Without
            # this check a company could collect the bonus for codes from
            # several different referrers (the duplicate guard in
            # record_referral is per (code, user) pair, not per customer).
            # The referrer-side award above stays per referral — a referrer
            # legitimately earns for each company they bring in. (B4)
            already_received = PointTransaction.objects.filter(
                customer=customer,
                transaction_type='referral_received',
            ).exists()
            if not already_received:
                LoyaltyService.award_points(
                    customer=customer,
                    amount=config.referral_bonus_referred,
                    transaction_type='referral_received',
                    description='Welcome bonus — joined with a referral code',
                    tenant=tenant,
                    acting_customer_user=referral.customer_user,
                )

            referral.status = 'AWARDED'
            referral.awarded_at = timezone.now()
            referral.save(update_fields=['status', 'awarded_at'])
            awarded += 1

        return awarded

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
    def get_reward_options(active_only=True, tenant=None):
        """Get available reward options, scoped to tenant."""
        qs = RewardOption.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)
        if active_only:
            qs = qs.filter(is_active=True)
        return qs

    @staticmethod
    def get_reward_redemptions(customer):
        """Get all reward redemptions for a customer."""
        return RewardRedemption.objects.filter(reward__customer=customer).order_by('-created_at')

    @staticmethod
    def get_reward_balance(customer):
        """Get the current reward balance for a customer."""
        return LoyaltyService.get_balance(customer)

    @staticmethod
    def get_reward_history(customer):
        """Get reward history for a customer."""
        return Reward.objects.filter(customer=customer).order_by('-created_at')

    @staticmethod
    @transaction.atomic
    def redeem_reward(customer, reward_option_id, acting_customer_user=None, created_by=None):
        """
        Redeem a reward against a customer's balance via LoyaltyService.

        ``acting_customer_user`` records the portal user who redeemed (portal
        flow); ``created_by`` records the staff Django user (in-shop flow).

        Returns:
            tuple: (bool success, str message or RewardRedemption object)
        """
        try:
            tenant = customer.tenant
            if tenant is None:
                return False, "This customer is not linked to a shop."
            reward_option = RewardOption.objects.get(id=reward_option_id, tenant=tenant)

            if not reward_option.is_active:
                return False, "This reward option is not currently available."

            # Guard: if the loyalty program is inactive, redemptions are blocked.
            # LoyaltyService.award_points() returns None (no deduction) when
            # config.is_active is False — creating a free-redemption loophole
            # where the RewardRedemption row would be committed but the point
            # balance never decremented (CODE-175).
            config = LoyaltyConfig.get_for_tenant(tenant)
            if not config.is_active:
                return False, "The loyalty program is not currently active."

            # Lock the Reward row (CODE-165 / CODE-173 pattern).
            # Use get_or_create() to avoid the race that produces duplicate rows.
            reward, _created = Reward.objects.get_or_create(
                customer=customer,
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

            # Deduct via LoyaltyService (updates Reward.points + creates PointTransaction).
            # We have already verified config.is_active above, so award_points() will
            # not short-circuit.  Use the already-fetched config to avoid a second
            # get_or_create inside award_points().
            pt = LoyaltyService.award_points(
                customer=customer,
                amount=-reward_option.points_required,
                transaction_type='redemption',
                description=f'Redeemed: {reward_option.name}',
                tenant=tenant,
                acting_customer_user=acting_customer_user,
                related_redemption=redemption,
                created_by=created_by,
            )

            # Defensive check: if award_points() still returned None for any
            # reason, roll back by raising an exception (the @transaction.atomic
            # wrapper will abort the redemption and the RewardRedemption row).
            if pt is None:
                raise RuntimeError("award_points() returned None during redemption — aborting to protect point balance.")

            return True, redemption

        except RewardOption.DoesNotExist:
            return False, "Invalid reward option"

    @staticmethod
    @transaction.atomic
    def cancel_redemption(redemption_id, tenant, cancelled_by=None, reason=''):
        """
        Cancel a PENDING redemption and refund its points.

        This is the ONLY sanctioned way to undo a redemption — it restores the
        points through the ledger (transaction_type='redemption_refund') so
        the liability report stays honest. Flipping status to REJECTED in the
        Django admin does NOT refund.

        Rules:
          - Only PENDING redemptions can be cancelled (FULFILLED means the
            reward was delivered; REJECTED is already terminal).
          - If the redemption is applied to a job, the job must not be
            COMPLETED or invoiced (the discount may already be on paper);
            otherwise the application is cleared as part of the cancel.
          - The loyalty program must be active — award_points() refuses to
            move points while it is off, and a cancel that doesn't refund
            would silently burn the customer's balance.

        ``cancelled_by`` is the Django User performing the cancel (stored in
        processed_by and on the refund transaction). ``reason`` is optional
        free text appended to the redemption notes.

        Returns:
            tuple: (bool success, str message)
        """
        redemption = (
            RewardRedemption.objects
            .select_for_update()
            .select_related('reward__customer', 'reward_option')
            .filter(pk=redemption_id, reward__customer__tenant=tenant)
            .first()
        )
        if redemption is None:
            return False, "Redemption not found."

        if redemption.status != 'PENDING':
            return False, (
                f"Only pending redemptions can be cancelled "
                f"(this one is {redemption.get_status_display().lower()})."
            )

        config = LoyaltyConfig.get_for_tenant(tenant)
        if not config.is_active:
            return False, (
                "The loyalty program is turned off. Re-enable it before "
                "cancelling so the points can be refunded."
            )

        # If applied to a job, only cancel while the discount can't have
        # reached an invoice yet.
        applied_job = redemption.applied_to_repair or redemption.applied_to_replacement
        if applied_job is not None:
            if applied_job.queue_status == 'COMPLETED':
                return False, (
                    "This reward is applied to a completed job and can no "
                    "longer be cancelled."
                )
            if applied_job.invoice_line_items.filter(
                invoice__deleted_at__isnull=True,
            ).exclude(invoice__status='CANCELLED').exists():
                return False, (
                    "This reward is applied to a job that has been invoiced "
                    "and can no longer be cancelled."
                )
            redemption.applied_to_repair = None
            redemption.applied_to_replacement = None

        customer = redemption.reward.customer
        pt = LoyaltyService.award_points(
            customer=customer,
            amount=redemption.reward_option.points_required,
            transaction_type='redemption_refund',
            description=f'Refund: cancelled redemption of {redemption.reward_option.name}',
            tenant=tenant,
            related_redemption=redemption,
            created_by=cancelled_by,
        )
        if pt is None:
            # Should be unreachable (is_active checked above) — abort rather
            # than reject without refunding.
            raise RuntimeError(
                "award_points() returned None during redemption cancel — "
                "aborting to protect point balance."
            )

        redemption.status = 'REJECTED'
        redemption.processed_by = cancelled_by
        redemption.processed_at = timezone.now()
        cancel_note = 'Cancelled and points refunded'
        if cancelled_by is not None:
            cancel_note += f' by {cancelled_by.get_full_name() or cancelled_by.username}'
        if reason and str(reason).strip():
            cancel_note += f' — {str(reason).strip()}'
        redemption.notes = f"{redemption.notes}\n{cancel_note}" if redemption.notes else cancel_note
        redemption.save()

        return True, (
            f"Cancelled {redemption.reward_option.name} and refunded "
            f"{redemption.reward_option.points_required} points to {customer.name}."
        )

    @staticmethod
    def get_available_rewards(customer):
        """Get list of rewards the customer can redeem based on their balance."""
        points = RewardService.get_reward_balance(customer)

        tenant = customer.tenant
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
    def get_redemption_history(customer, limit=None):
        """Get reward redemption history for a customer."""
        redemptions = RewardRedemption.objects.filter(
            reward__customer=customer
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
            tenant = redemption.reward.customer.tenant
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
            message=f"New reward redemption to fulfill: {redemption.reward_option.name} for {redemption.reward.customer.name}",
            redemption=redemption,
            created_at=timezone.now()
        )

    @staticmethod
    @transaction.atomic
    def mark_as_fulfilled(redemption, technician, notes=None):
        """Mark a redemption as fulfilled by a technician.

        ``technician`` may be a Technician instance or None.  When None (e.g.
        an owner/manager fulfills via the admin without a Technician row),
        ``processed_by`` is left as-is rather than crashing with AttributeError
        on ``None.user``.  (CODE-176)
        """
        redemption.status = 'FULFILLED'
        # Only set processed_by if a Technician instance was provided.
        # Owners and managers who reach this view without a Technician record
        # pass technician=None; accessing .user on None raises AttributeError.
        if technician is not None:
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
            qs = qs.filter(reward__customer__tenant=tenant)
        return qs.order_by('created_at')

    @staticmethod
    def get_technician_redemptions(technician):
        """Get all redemptions assigned to a specific technician."""
        return RewardRedemption.objects.filter(
            assigned_technician=technician
        ).exclude(
            status='FULFILLED'
        ).order_by('created_at')
