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

def loyalty_hook(service) -> None:
    """
    Award completion points to the customer (company) for this job.

    Accepts either a Repair or a Replacement. Delegates to LoyaltyService
    after loading per-tenant LoyaltyConfig. Points anchor on the Customer
    record, so customers WITHOUT portal accounts earn too. Skips re-awards
    if the job was already COMPLETED (idempotency guard via original_status).
    """
    try:
        from apps.rewards_referrals.models import LoyaltyConfig
        from apps.rewards_referrals.services import LoyaltyService
        from apps.technician_portal.models import Repair, Replacement

        is_repair = isinstance(service, Repair)

        # Idempotency: only award on first-time COMPLETED transition.
        # original_status is set BEFORE the hooks are called (see the save()
        # methods), so on a re-save of an already-COMPLETED job it will equal
        # 'COMPLETED' and we skip.
        if hasattr(service, 'original_status') and service.original_status == 'COMPLETED':
            return

        # Goodwill repairs are courtesy work — no loyalty points awarded.
        if getattr(service, 'is_goodwill_repair', False):
            return

        customer = service.customer
        tenant = customer.tenant
        if tenant is None:
            return
        config = LoyaltyConfig.get_for_tenant(tenant)

        base_points = config.points_per_repair
        related = {'related_repair': service} if is_repair else {'related_replacement': service}

        LoyaltyService.award_points(
            customer=customer,
            amount=base_points,
            transaction_type='repair_complete' if is_repair else 'replacement_complete',
            description=(
                f"{'Repair' if is_repair else 'Replacement'} completed — "
                f"Unit #{service.unit_number}"
            ),
            tenant=tenant,
            **related,
        )

        # Milestone bonus based on lifetime completed jobs (repairs +
        # replacements) for this customer.
        completed_count = Repair.objects.filter(
            customer=service.customer,
            queue_status='COMPLETED',
        ).count() + Replacement.objects.filter(
            customer=service.customer,
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
                customer=customer,
                amount=milestone_bonus,
                transaction_type='milestone_bonus',
                description=f'Milestone bonus — {completed_count} jobs completed',
                tenant=tenant,
                **related,
            )
            logger.info(
                "Loyalty milestone bonus of %s points awarded to %s "
                "(%d jobs completed, job pk=%s)",
                milestone_bonus,
                customer.name,
                completed_count,
                service.pk,
            )

        logger.info(
            "Loyalty: awarded %s base + %s milestone = %s points to %s for job pk=%s",
            base_points,
            milestone_bonus,
            base_points + milestone_bonus,
            customer.name,
            service.pk,
        )

    except Exception as exc:
        logger.error(
            "Post-completion hook 'loyalty_hook' failed for job pk=%s: %s",
            service.pk,
            exc,
            exc_info=True,
        )


def referral_payout_hook(service) -> None:
    """
    Pay out pending referral bonuses when the referred customer's first
    job completes.

    Referrals are recorded as PENDING at signup (no points move) and pay
    out here — a referral only counts once it becomes real work.

    Idempotency: award_referral_bonuses flips each Referral to AWARDED
    under a row lock, so re-runs are no-ops; the original_status guard
    skips re-saves of already-COMPLETED jobs entirely.
    """
    try:
        from apps.rewards_referrals.services import ReferralService

        if hasattr(service, 'original_status') and service.original_status == 'COMPLETED':
            return

        # Goodwill work doesn't trigger payouts either — a referral pays
        # when the customer's first REAL job completes.
        if getattr(service, 'is_goodwill_repair', False):
            return

        awarded = ReferralService.award_referral_bonuses(service.customer)
        if awarded:
            logger.info(
                "Referral payout: %d referral(s) awarded for customer %s (job pk=%s)",
                awarded,
                service.customer.name,
                service.pk,
            )

    except Exception as exc:
        logger.error(
            "Post-completion hook 'referral_payout_hook' failed for job pk=%s: %s",
            service.pk,
            exc,
            exc_info=True,
        )


def warranty_hook(repair) -> None:
    """
    Assign warranty to a repair that just transitioned to COMPLETED.

    Delegates to WarrantyService.assign_warranty(repair). If no active
    warranty policy exists for the tenant, the hook is a silent no-op
    (the shop hasn't configured warranties yet).

    Idempotency: skips if the repair already has a warranty assigned
    or if original_status was already COMPLETED (re-save).
    """
    try:
        from apps.technician_portal.warranty_service import WarrantyService

        # Idempotency: skip re-saves of already-COMPLETED repairs
        if hasattr(repair, 'original_status') and repair.original_status == 'COMPLETED':
            return

        # Skip if warranty already assigned (e.g. manual assignment)
        if repair.warranty_policy_id:
            return

        WarrantyService.assign_warranty(repair)

    except ValueError:
        # No policy found for this tenant — that's fine, warranty is optional.
        pass
    except Exception as exc:
        logger.error(
            "Post-completion hook 'warranty_hook' failed for repair pk=%s: %s",
            repair.pk,
            exc,
            exc_info=True,
        )


def review_request_hook(repair) -> None:
    """
    Queue a review request email after repair completion.

    Delegates to ReviewRequestService which evaluates eligibility
    (cooldowns, opt-outs, negative experience, etc.) and either
    schedules a pending request or records a skip/suppression.
    """
    try:
        from apps.technician_portal.review_service import ReviewRequestService

        # Idempotency: skip re-saves of already-COMPLETED repairs
        if hasattr(repair, 'original_status') and repair.original_status == 'COMPLETED':
            return

        ReviewRequestService.schedule_review_request(repair)

    except Exception as exc:
        logger.error(
            "Post-completion hook 'review_request_hook' failed for repair pk=%s: %s",
            repair.pk,
            exc,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# Ordered list of (name, callable) pairs.  Order matters: loyalty runs first
# so points are in the ledger before warranty or review logic inspect state.
COMPLETION_HOOKS = [
    ('loyalty', loyalty_hook),
    ('referral_payout', referral_payout_hook),
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
