"""
Reward fulfillment and application views for the technician portal.
"""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.technician_portal.models import Technician, Repair
from apps.rewards_referrals.models import RewardRedemption
from apps.rewards_referrals.services import RewardFulfillmentService, RewardService
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from core.models import Customer

import logging

logger = logging.getLogger(__name__)


@technician_required
def reward_fulfillment_detail(request, redemption_id):
    """View details of a reward redemption and mark as fulfilled."""
    tenant = getattr(request, 'tenant', None)
    # Scope to current tenant — unscoped get_object_or_404(Technician, user=request.user)
    # would resolve to whichever Technician row exists for the user, which may belong to
    # a different shop (same pattern as CODE-077 through CODE-082).
    if tenant:
        technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
    else:
        try:
            technician = request.user.technician
        except Technician.DoesNotExist:
            technician = None

    # Scope redemption to the current tenant via the customer chain.
    # RewardRedemption has no direct tenant FK; path is
    # redemption → reward → customer → tenant.
    # An unscoped get_object_or_404 here lets a tech from Shop A read/fulfill
    # redemptions belonging to Shop B just by guessing the integer PK (IDOR).
    if tenant:
        redemption_qs = RewardRedemption.objects.filter(
            reward__customer__tenant=tenant
        )
    else:
        redemption_qs = RewardRedemption.objects.none()
    redemption = get_object_or_404(redemption_qs, id=redemption_id)

    # A technician without a profile (None) should never match the assigned
    # technician slot — even when the redemption is also unassigned (None).
    # Previously, None == None evaluated to True, making any admin/owner
    # without a Technician row appear as "assigned" and then crashing in
    # mark_as_fulfilled() with AttributeError on None.user.  (CODE-176)
    is_assigned_technician = (
        technician is not None
        and redemption.assigned_technician is not None
        and redemption.assigned_technician == technician
    )
    is_admin = is_tenant_admin(request.user, tenant=getattr(request, "tenant", None))
    can_fulfill = is_assigned_technician or is_admin

    # Cancelling (refunding points) is gated like creating a redemption:
    # managers and owners only.
    can_cancel = is_admin or bool(technician and technician.is_manager)

    # Get customer repairs for applying reward. The reward now has a direct
    # customer FK (customer-anchored loyalty), so no CustomerUser hop needed.
    customer_repairs = []
    if redemption.reward:
        try:
            customer = redemption.reward.customer
            # Guard: ensure the customer belongs to the current tenant.
            # The redemption queryset above is already tenant-scoped, so this
            # should always hold, but an explicit check avoids surprises if the
            # chain is unexpectedly broken.
            if tenant and customer.tenant_id != tenant.id:
                customer = None
            if customer:
                repair_qs = Repair.objects.filter(
                    customer=customer,
                    queue_status__in=['APPROVED', 'IN_PROGRESS'],
                    tenant=tenant,
                ) if tenant else Repair.objects.none()
                customer_repairs = repair_qs.select_related('customer', 'technician').order_by('-service_date')
        except Exception:
            pass

    if request.method == 'POST':
        if not can_fulfill:
            messages.error(request, "You don't have permission to fulfill this reward. Only the assigned technician or administrators can fulfill rewards.")
            return redirect('technician_dashboard')

        action = request.POST.get('action')
        if action == 'claim' and not redemption.assigned_technician:
            redemption.assigned_technician = technician
            redemption.save()
            messages.success(request, f'You have claimed the reward: {redemption.reward_option.name}')
            return redirect('reward_fulfillment_detail', redemption_id=redemption.id)

        notes = request.POST.get('notes', '')

        repair_id = request.POST.get('apply_to_repair')
        if repair_id:
            try:
                repair_qs = Repair.objects.all()
                if tenant:
                    repair_qs = repair_qs.filter(tenant=tenant)
                repair = repair_qs.get(id=repair_id)
                redemption.applied_to_repair = repair
            except Repair.DoesNotExist:
                pass

        RewardFulfillmentService.mark_as_fulfilled(redemption, technician, notes)

        messages.success(request, f'Reward {redemption.reward_option.name} has been marked as fulfilled.')
        return redirect('technician_dashboard')

    return render(request, 'technician_portal/reward_fulfillment.html', {
        'redemption': redemption,
        'customer_repairs': customer_repairs,
        'is_assigned_technician': is_assigned_technician,
        'can_fulfill': can_fulfill,
        'can_cancel': can_cancel,
        'current_technician': technician,
        'is_admin': is_admin,
    })


@technician_required
@require_POST
def cancel_redemption(request, redemption_id):
    """
    Cancel a PENDING redemption and refund the points to the customer's
    balance. Manager/owner only — same gate as spending the points.
    """
    tenant = getattr(request, 'tenant', None)

    is_admin = is_tenant_admin(request.user, tenant=tenant)
    technician = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    if not (is_admin or (technician and technician.is_manager)):
        messages.error(request, "Only managers and owners can cancel a redemption.")
        return redirect('technician_dashboard')

    if tenant is None:
        messages.error(request, "No shop context.")
        return redirect('technician_dashboard')

    success, message = RewardService.cancel_redemption(
        redemption_id,
        tenant,
        cancelled_by=request.user,
        reason=request.POST.get('reason', ''),
    )
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)

    # Send the user back to the customer page when we can, else the dashboard.
    redemption = RewardRedemption.objects.filter(
        pk=redemption_id, reward__customer__tenant=tenant,
    ).select_related('reward__customer').first()
    if redemption is not None:
        return redirect('customer_detail', customer_id=redemption.reward.customer_id)
    return redirect('technician_dashboard')


@technician_required
def apply_reward_to_repair(request, repair_id):
    """Apply a reward redemption to a specific repair."""
    tenant = getattr(request, 'tenant', None)
    if is_tenant_admin(request.user, tenant=getattr(request, "tenant", None)):
        qs = Repair.objects.all()
        if tenant:
            qs = qs.filter(tenant=tenant)

        else:
            qs = qs.none()
        repair = get_object_or_404(qs, id=repair_id)
    else:
        # Scope to current tenant; unscoped request.user.technician may resolve
        # to a Technician from a different shop (same pattern as CODE-077/082).
        scoped_tech = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
        if scoped_tech is None:
            messages.error(request, "You don't have a technician profile.")
            return redirect('technician_dashboard')
        qs = Repair.objects.filter(technician=scoped_tech)
        if tenant:
            qs = qs.filter(tenant=tenant)
        else:
            qs = qs.none()
        repair = get_object_or_404(qs, id=repair_id)

    # Manager/owner check — creating a NEW redemption (spending the customer's
    # points) is gated like a price override; applying an existing redemption
    # stays open to any tech.
    acting_is_admin = is_tenant_admin(request.user, tenant=tenant)
    acting_tech_row = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    can_create_redemption = acting_is_admin or bool(acting_tech_row and acting_tech_row.is_manager)

    if request.method == 'POST':
        option_id = request.POST.get('option_id')
        redemption_id = request.POST.get('redemption_id')
        auto_fulfill = request.POST.get('auto_fulfill') == 'on'

        # One-step "redeem & apply": spend points on a reward option and put
        # it straight on this repair. Atomic — a failed apply rolls back the
        # point deduction.
        if option_id:
            if not can_create_redemption:
                messages.error(request, "Only managers and owners can redeem a customer's points.")
                return redirect('repair_detail', repair_id=repair.id)

            class _ApplyFailed(Exception):
                pass

            try:
                with transaction.atomic():
                    success, result = RewardService.redeem_reward(
                        repair.customer, option_id, created_by=request.user,
                    )
                    if not success:
                        messages.error(request, result)
                        return redirect('apply_reward_to_repair', repair_id=repair.id)
                    result.notes = (
                        f"Redeemed in-shop by {request.user.get_full_name() or request.user.username}"
                    )
                    result.save(update_fields=['notes'])
                    applied, message = repair.apply_reward(
                        result,
                        technician=acting_tech_row,
                        auto_fulfill=auto_fulfill,
                    )
                    if not applied:
                        # Abort the atomic block so the redemption AND the
                        # point deduction roll back together.
                        raise _ApplyFailed(message)
            except _ApplyFailed as exc:
                messages.error(request, str(exc))
                return redirect('apply_reward_to_repair', repair_id=repair.id)

            messages.success(request, f"Redeemed {result.reward_option.name} and applied it to this repair.")
            return redirect('repair_detail', repair_id=repair.id)

        if not redemption_id:
            messages.error(request, "No reward selected")
            return redirect('repair_detail', repair_id=repair.id)

        # Scope to tenant; prevents applying a redemption from Shop B to a Shop A repair.
        if tenant:
            redemption_qs = RewardRedemption.objects.filter(
                reward__customer__tenant=tenant
            )
        else:
            redemption_qs = RewardRedemption.objects.none()
        redemption = get_object_or_404(redemption_qs, id=redemption_id)

        if redemption.reward.customer_id != repair.customer_id:
            messages.error(request, "This reward belongs to a different customer and cannot be applied to this repair.")
            return redirect('repair_detail', repair_id=repair.id)

        # Resolve current-tenant technician for assignment — never unscoped.
        acting_tech = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
        success, message = repair.apply_reward(
            redemption,
            technician=acting_tech,
            auto_fulfill=auto_fulfill
        )

        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)

        return redirect('repair_detail', repair_id=repair.id)

    # GET request
    available_redemptions = RewardRedemption.objects.filter(
        reward__customer=repair.customer,
        status='PENDING',
        applied_to_repair__isnull=True
    ).select_related('reward_option', 'reward_option__reward_type')

    # Options the customer's balance can afford right now (managers can
    # redeem & apply in one step). Only discount-type rewards make sense on
    # a repair — merchandise is fulfilled separately.
    from apps.rewards_referrals.services import LoyaltyService
    balance = LoyaltyService.get_balance(repair.customer)
    affordable_options = [
        opt for opt in RewardService.get_available_rewards(repair.customer)['available']
        if opt.reward_type and opt.reward_type.category in ('REPAIR_DISCOUNT', 'FREE_SERVICE')
    ]

    return render(request, 'technician_portal/apply_reward.html', {
        'repair': repair,
        'available_redemptions': available_redemptions,
        'affordable_options': affordable_options,
        'points_balance': balance,
        'can_create_redemption': can_create_redemption,
    })


@technician_required
@require_POST
def redeem_for_customer(request, customer_id):
    """
    In-shop redemption from the customer page: a manager/owner spends the
    customer's points on a reward option (e.g. merchandise, or a discount
    to be applied to a job later). Point-of-sale path for customers without
    portal accounts.
    """
    tenant = getattr(request, 'tenant', None)
    qs = Customer.objects.filter(tenant=tenant) if tenant else Customer.objects.none()
    customer = get_object_or_404(qs, id=customer_id)

    is_admin = is_tenant_admin(request.user, tenant=tenant)
    technician = Technician.objects.filter(user=request.user, tenant=tenant).first() if tenant else None
    if not (is_admin or (technician and technician.is_manager)):
        messages.error(request, "Only managers and owners can redeem a customer's points.")
        return redirect('customer_detail', customer_id=customer.id)

    option_id = request.POST.get('option_id')
    if not option_id:
        messages.error(request, "No reward selected.")
        return redirect('customer_detail', customer_id=customer.id)

    success, result = RewardService.redeem_reward(
        customer, option_id, created_by=request.user,
    )
    if success:
        result.notes = f"Redeemed in-shop by {request.user.get_full_name() or request.user.username}"
        result.save(update_fields=['notes'])
        messages.success(
            request,
            f"Redeemed {result.reward_option.name} for {customer.name}. "
            "Discount rewards will be applied to their next repair automatically, "
            "or apply one from a repair's Apply Reward page."
        )
    else:
        messages.error(request, result)
    return redirect('customer_detail', customer_id=customer.id)
