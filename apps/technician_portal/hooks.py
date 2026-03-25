"""
Post-completion hook orchestrator for Repair model.

When a repair transitions to COMPLETED, this module runs all post-completion
hooks in sequence. Each hook is isolated — a failure in one does NOT block the
others or roll back the repair save.

Current hooks (in execution order):
    1. loyalty_hook     — award points via LoyaltyService
    2. warranty_hook    — (placeholder, ready for WarrantyService)
    3. review_request_hook — (placeholder, ready for ReviewRequestService)

How to add a new hook:
    1. Define a function with signature:  def my_hook(repair: Repair) -> None
    2. Append it to COMPLETION_HOOKS in the order it should run.
    3. Write a regression test in tests/test_loyalty_phase1.py or a new test module.

IDEMPOTENCY:
    Each hook must be idempotent — calling it twice on the same repair must
    not create duplicate records or side effects. Guard against re-runs using
    the repair's original_status (set to 'COMPLETED' before the second call)
    or by checking for existing related records.

ATOMICITY:
    Hooks run AFTER super().save() has committed. They must NOT assume they are
    inside the same database transaction as the save. If a hook needs its own
    atomicity, wrap its internals in transaction.atomic().
"""

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Individual hooks
# ---------------------------------------------------------------------------

def loyalty_hook(repair) -> None:
    """
    Award completion points to the primary contact for this repair.

    Delegates to LoyaltyService after loading per-tenant LoyaltyConfig.
    Skips re-awards if the repair was already COMPLETED (idempotency guard
    via repair.original_status).
    """
    try:
        from apps.rewards_referrals.models import LoyaltyConfig
        from apps.rewards_referrals.services import LoyaltyService
        from apps.customer_portal.models import CustomerUser
        from apps.technician_portal.models import Repair

        # Idempotency: only award on first-time COMPLETED transition.
        # original_status is set BEFORE post_completion_hooks() is called (see
        # Repair.save()), so on a re-save of an already-COMPLETED repair it
        # will equal 'COMPLETED' and we skip.
        if hasattr(repair, 'original_status') and repair.original_status == 'COMPLETED':
            return

        # Prefer primary contact; fall back to any contact.
        customer_users = CustomerUser.objects.filter(customer=repair.customer)
        if not customer_users.exists():
            return

        customer_user = (
            customer_users.filter(is_primary_contact=True).first()
            or customer_users.first()
        )

        tenant = repair.customer.tenant
        config = LoyaltyConfig.get_for_tenant(tenant)

        base_points = config.points_per_repair

        LoyaltyService.award_points(
            customer_user=customer_user,
            amount=base_points,
            transaction_type='repair_complete',
            description=f'Repair completed — Unit #{repair.unit_number}',
            tenant=tenant,
            related_repair=repair,
        )

        # Milestone bonus based on lifetime completed repairs for this customer.
        completed_count = Repair.objects.filter(
            customer=repair.customer,
            queue_status='COMPLETED',
        ).count()

        milestone_bonus = 0
        if completed_count == 5:
            milestone_bonus = config.milestone_5_bonus
        elif completed_count == 10:
            milestone_bonus = config.milestone_10_bonus
        elif completed_count >= 25 and completed_count % 25 == 0:
            milestone_bonus = config.milestone_25_bonus

        if milestone_bonus > 0:
            LoyaltyService.award_points(
                customer_user=customer_user,
                amount=milestone_bonus,
                transaction_type='milestone_bonus',
                description=f'Milestone bonus — {completed_count} repairs completed',
                tenant=tenant,
                related_repair=repair,
            )
            logger.info(
                "Loyalty milestone bonus of %s points awarded to %s "
                "(%d repairs completed, repair pk=%s)",
                milestone_bonus,
                customer_user.user.email,
                completed_count,
                repair.pk,
            )

        logger.info(
            "Loyalty: awarded %s base + %s milestone = %s points to %s for repair pk=%s",
            base_points,
            milestone_bonus,
            base_points + milestone_bonus,
            customer_user.user.email,
            repair.pk,
        )

    except Exception as exc:
        logger.error(
            "Post-completion hook 'loyalty_hook' failed for repair pk=%s: %s",
            repair.pk,
            exc,
            exc_info=True,
        )


def warranty_hook(repair) -> None:
    """
    Placeholder: set warranty on repair completion.

    Will delegate to WarrantyService.set_warranty_on_completion(repair)
    once the warranty system is implemented (see docs/proposals/warranty-system.md).
    """
    # TODO (warranty system): uncomment when WarrantyService ships.
    # from apps.warranty.services import WarrantyService
    # WarrantyService.set_warranty_on_completion(repair)
    pass


def review_request_hook(repair) -> None:
    """
    Placeholder: queue a review request email after repair completion.

    Will delegate to ReviewRequestService.on_repair_completed(repair)
    once the review request system is implemented
    (see docs/proposals/review-request-system.md).
    """
    # TODO (review request system): uncomment when ReviewRequestService ships.
    # from apps.reviews.services import ReviewRequestService
    # ReviewRequestService.on_repair_completed(repair)
    pass


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# Ordered list of (name, callable) pairs.  Order matters: loyalty runs first
# so points are in the ledger before warranty or review logic inspect state.
COMPLETION_HOOKS = [
    ('loyalty', loyalty_hook),
    ('warranty', warranty_hook),
    ('review_request', review_request_hook),
]


def post_completion_hooks(repair) -> None:
    """
    Run all post-completion hooks for a repair that just transitioned to COMPLETED.

    Each hook is called in order.  A failure in any hook is caught and logged
    individually; remaining hooks continue executing.  This ensures that a bug
    in (e.g.) the review request hook never prevents loyalty points from being
    awarded, and vice versa.

    Called from Repair.save() immediately after super().save() and
    apply_available_rewards(), before original_status is updated.

    Args:
        repair: The Repair instance that has just been saved with
                queue_status == 'COMPLETED'.
    """
    for name, hook in COMPLETION_HOOKS:
        try:
            hook(repair)
        except Exception as exc:
            # Belt-and-suspenders: each hook already catches internally, but
            # a KeyboardInterrupt or SystemExit could bypass that.  This outer
            # catch ensures the orchestrator never propagates to Repair.save().
            logger.error(
                "Orchestrator: unhandled exception in hook '%s' for repair pk=%s: %s",
                name,
                getattr(repair, 'pk', 'unknown'),
                exc,
                exc_info=True,
            )
