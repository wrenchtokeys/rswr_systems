"""
Reward fulfillment and application views for the technician portal.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import RewardRedemption
from apps.rewards_referrals.services import RewardFulfillmentService
from core.models import Customer
from apps.technician_portal.decorators import technician_required, is_tenant_admin

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
    # redemption → reward → customer_user → customer → tenant.
    # An unscoped get_object_or_404 here lets a tech from Shop A read/fulfill
    # redemptions belonging to Shop B just by guessing the integer PK (IDOR).
    if tenant:
        redemption_qs = RewardRedemption.objects.filter(
            reward__customer_user__customer__tenant=tenant
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

    # Get customer repairs for applying reward
    customer_repairs = []
    if redemption.reward and redemption.reward.customer_user and redemption.reward.customer_user.user:
        customer_email = redemption.reward.customer_user.user.email
        try:
            customer_qs = Customer.objects.all()
            if tenant:
                customer_qs = customer_qs.filter(tenant=tenant)

            else:
                customer_qs = customer_qs.none()
            customer = customer_qs.get(email=customer_email)
            repair_qs = Repair.objects.filter(
                customer=customer,
                queue_status__in=['APPROVED', 'IN_PROGRESS']
            )
            if tenant:
                repair_qs = repair_qs.filter(tenant=tenant)

            else:
                repair_qs = repair_qs.none()
            customer_repairs = repair_qs.select_related('customer', 'technician').order_by('-service_date')
        except Customer.DoesNotExist:
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
        'current_technician': technician,
        'is_admin': is_admin,
    })


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

    if request.method == 'POST':
        redemption_id = request.POST.get('redemption_id')
        auto_fulfill = request.POST.get('auto_fulfill') == 'on'

        if not redemption_id:
            messages.error(request, "No reward selected")
            return redirect('repair_detail', repair_id=repair.id)

        # Scope to tenant; prevents applying a redemption from Shop B to a Shop A repair.
        if tenant:
            redemption_qs = RewardRedemption.objects.filter(
                reward__customer_user__customer__tenant=tenant
            )
        else:
            redemption_qs = RewardRedemption.objects.none()
        redemption = get_object_or_404(redemption_qs, id=redemption_id)

        customer_users = CustomerUser.objects.filter(customer=repair.customer)
        reward_customer_user = redemption.reward.customer_user

        if not customer_users.filter(id=reward_customer_user.id).exists():
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
    customer_users = CustomerUser.objects.filter(customer=repair.customer)

    available_redemptions = RewardRedemption.objects.filter(
        reward__customer_user__in=customer_users,
        status='PENDING',
        applied_to_repair__isnull=True
    ).select_related('reward_option', 'reward_option__reward_type')

    return render(request, 'technician_portal/apply_reward.html', {
        'repair': repair,
        'available_redemptions': available_redemptions,
    })
