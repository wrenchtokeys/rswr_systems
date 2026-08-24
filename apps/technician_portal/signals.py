"""
Signal handlers for the technician portal app.

These signals automatically trigger notifications when repair events occur:
- Repair status changes (PENDING, APPROVED, DENIED, IN_PROGRESS, COMPLETED)
- Technician assignments and reassignments
- Batch repair approvals

Signal handlers call NotificationService to create notifications which
then send email/SMS notifications synchronously.
"""

import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from apps.technician_portal.models import Repair, Replacement
from core.services.notification_service import NotificationService
from core.models.notification import Notification

logger = logging.getLogger(__name__)

# Module-level dictionary to track status changes
# Key: repair.id, Value: previous queue_status
_repair_previous_status = {}
# Key: job pk, Value: (previous queue_status, previous technician).
# Separate from _repair_previous_status because handle_repair_status_change
# deletes that entry before the assignment handler runs, and the assignment
# decision needs the old status too (REQUESTED → APPROVED acceptance).
_repair_prev_assignment_state = {}
_replacement_prev_assignment_state = {}
# Old status for the replacement lifecycle handler. Kept apart from the
# assignment tuple above because _handle_assignment_change pops that one.
_replacement_previous_status = {}


@receiver(pre_save, sender=Repair)
def track_repair_changes(sender, instance, **kwargs):
    """
    Track repair status and technician changes before save.

    This runs before the Repair is saved to capture the old values
    for comparison in the post_save signal.

    Args:
        sender: Repair model class
        instance: Repair instance being saved
        **kwargs: Additional signal arguments
    """
    if instance.pk:  # Only for existing repairs (updates)
        try:
            old_repair = Repair.objects.select_related('technician').get(pk=instance.pk)
            _repair_previous_status[instance.pk] = old_repair.queue_status
            _repair_prev_assignment_state[instance.pk] = (
                old_repair.queue_status, old_repair.technician
            )
        except Repair.DoesNotExist:
            pass


@receiver(pre_save, sender=Replacement)
def track_replacement_changes(sender, instance, **kwargs):
    """Track replacement technician/status changes for assignment signals."""
    if instance.pk:
        try:
            old = Replacement.objects.select_related('technician').get(pk=instance.pk)
            _replacement_prev_assignment_state[instance.pk] = (
                old.queue_status, old.technician
            )
            # A SEPARATE record of the old status for the lifecycle handler.
            # It cannot read the tuple above: _handle_assignment_change pops
            # that entry, and its receiver is registered first, so by the time
            # the lifecycle handler runs the status is always gone and no
            # notification would ever fire.
            _replacement_previous_status[instance.pk] = old.queue_status
        except Replacement.DoesNotExist:
            pass


@receiver(post_save, sender=Repair)
def handle_repair_status_change(sender, instance, created, **kwargs):
    """
    Handle repair status changes and trigger appropriate notifications.

    This runs after the Repair is saved and checks if the status has changed
    to trigger the appropriate notification.

    Status Change Events:
    - REQUESTED → PENDING: Notify customer for approval
    - PENDING → APPROVED: Notify technician to proceed
    - PENDING → DENIED: Notify technician of denial
    - APPROVED → IN_PROGRESS: Notify customer work has started
    - IN_PROGRESS → COMPLETED: Notify customer work is done

    Args:
        sender: Repair model class
        instance: Repair instance that was saved
        created: Boolean indicating if this is a new repair
        **kwargs: Additional signal arguments
    """
    # Handle new repair creation
    if created:
        if instance.queue_status == 'PENDING':
            # Technician-created repair needing customer approval
            _notify_customer_approval_needed(instance)
        elif instance.queue_status == 'REQUESTED':
            # Customer-initiated repair request
            _notify_customer_request_received(instance)
            _notify_technician_new_request(instance)
        return

    # Get previous status
    old_status = _repair_previous_status.get(instance.pk)

    if old_status and old_status != instance.queue_status:
        logger.info(
            f"Repair {instance.pk} status changed: "
            f"{old_status} → {instance.queue_status}"
        )

        # Handle status transitions
        if instance.queue_status == 'PENDING' and old_status != 'PENDING':
            # Moved to PENDING state (customer approval needed)
            _notify_customer_approval_needed(instance)

        elif instance.queue_status == 'APPROVED' and old_status == 'PENDING':
            # Approved by customer
            _notify_technician_approved(instance)

        elif instance.queue_status == 'DENIED' and old_status == 'PENDING':
            # Denied by customer
            _notify_technician_denied(instance)

        elif instance.queue_status == 'IN_PROGRESS':
            # Repair work started
            _notify_customer_in_progress(instance)

        elif instance.queue_status == 'COMPLETED':
            # Repair finished
            _notify_customer_completed(instance)
            _notify_owner_repair_completed(instance)

    # Clean up tracking dict to prevent memory leaks
    if instance.pk in _repair_previous_status:
        del _repair_previous_status[instance.pk]


def _handle_assignment_change(instance, created, prev_state_dict):
    """Shared Repair/Replacement assignment handler.

    Delegates the actual decision + delivery to
    services.assignments.notify_assignment_from_signal, which fixes the two
    holes the old handler had: assigning a previously-UNASSIGNED job now
    notifies (old code required an old technician), and crossing
    REQUESTED → APPROVED notifies the tech who was provisionally assigned
    while the job was still a request.
    """
    prev_status, prev_technician = prev_state_dict.pop(
        instance.pk, (None, None)
    )

    # Paths that go through services.assignments.assign_job notify explicitly
    # and exactly once — the signal is the fallback for everything else
    # (form edits, auto-assign, future code).
    if getattr(instance, '_assignment_notifications_handled', False):
        return

    from apps.technician_portal.services.assignments import (
        notify_assignment_from_signal,
    )
    notify_assignment_from_signal(
        instance,
        old_technician=prev_technician,
        old_status=prev_status,
        created=created,
        actor_user_id=getattr(instance, '_assignment_actor_user_id', None),
    )


@receiver(post_save, sender=Repair)
def handle_technician_assignment(sender, instance, created, **kwargs):
    """Notify on repair assignment/reassignment (see _handle_assignment_change)."""
    _handle_assignment_change(instance, created, _repair_prev_assignment_state)


@receiver(post_save, sender=Replacement)
def handle_replacement_assignment(sender, instance, created, **kwargs):
    """Notify on replacement assignment/reassignment — replacements previously
    had no assignment signals at all."""
    _handle_assignment_change(instance, created, _replacement_prev_assignment_state)


@receiver(post_save, sender=Replacement)
def handle_replacement_status_change(sender, instance, created, **kwargs):
    """Replacement lifecycle notifications, mirroring the repair ones.

    Replacements had no lifecycle templates at all until now, so a customer
    booking the shop's most expensive job heard less than one booking a $40
    chip repair. The transitions match handle_repair_status_change, with one
    difference that matters: a customer-created replacement enters as
    REQUESTED with no price on it (the shop sources the glass and quotes it),
    so the customer gets "we have your request", not "it is booked".

    Status events:
    - created REQUESTED  -> customer confirmation + shop "needs pricing"
    - -> PENDING         -> customer approval needed (the shop has priced it)
    - PENDING -> APPROVED-> technician: order the glass
    - PENDING -> DENIED  -> technician: do not order
    - -> IN_PROGRESS     -> customer: work started
    - -> COMPLETED       -> customer: done
    """
    old_status = _replacement_previous_status.pop(instance.pk, None)

    if created:
        if instance.queue_status == 'REQUESTED':
            _notify_customer_replacement_received(instance)
            _notify_shop_replacement_needs_pricing(instance)
        elif instance.queue_status == 'PENDING':
            _notify_customer_replacement_approval_needed(instance)
        return

    if not old_status or old_status == instance.queue_status:
        return

    logger.info(
        f"Replacement {instance.pk} status changed: "
        f"{old_status} → {instance.queue_status}"
    )

    if instance.queue_status == 'PENDING':
        _notify_customer_replacement_approval_needed(instance)
    elif instance.queue_status == 'APPROVED' and old_status == 'PENDING':
        _notify_technician_replacement_approved(instance)
    elif instance.queue_status == 'DENIED' and old_status == 'PENDING':
        _notify_technician_replacement_denied(instance)
    elif instance.queue_status == 'IN_PROGRESS':
        _notify_customer_replacement_in_progress(instance)
    elif instance.queue_status == 'COMPLETED':
        _notify_customer_replacement_completed(instance)


# ---- Replacement notification senders --------------------------------------
#
# Notification.repair is a Repair-only FK, so these cannot pass the job as
# `repair=` the way the repair senders do. They call job_display_context()
# directly instead — the same helper create_notification uses — so both job
# types put the same derived values in front of the templates.

def _replacement_context(replacement, action_url, **extra):
    """Flat, JSON-serializable context for a replacement notification."""
    from core.services.notification_service import job_display_context

    context = job_display_context(replacement)
    context.update({
        'replacement_id': replacement.pk,
        'unit_number': replacement.unit_number,
        'customer_name': replacement.customer.name if replacement.customer else '',
        'action_url': action_url,
    })
    technician = getattr(replacement, 'technician', None)
    if technician and getattr(technician, 'user', None):
        context['technician_name'] = (
            technician.user.get_full_name() or technician.user.username
        )
    context.update(extra)
    return context


def _notify_customer_replacement(replacement, template_name, action_url, **extra):
    """Send a replacement notification to the customer. Never raises."""
    if not replacement.customer:
        return
    try:
        NotificationService.create_notification(
            recipient=replacement.customer,
            template_name=template_name,
            context=_replacement_context(replacement, action_url, **extra),
            customer=replacement.customer,
        )
    except Exception:
        logger.warning(
            f"Failed to send {template_name} for replacement {replacement.pk}",
            exc_info=True,
        )


def _notify_technician_replacement(replacement, template_name, action_url, **extra):
    """Send a replacement notification to the assigned technician."""
    technician = getattr(replacement, 'technician', None)
    if not technician:
        return
    try:
        NotificationService.create_notification(
            recipient=technician,
            template_name=template_name,
            context=_replacement_context(replacement, action_url, **extra),
            customer=replacement.customer,
        )
    except Exception:
        logger.warning(
            f"Failed to send {template_name} for replacement {replacement.pk}",
            exc_info=True,
        )


def _notify_customer_replacement_received(replacement):
    _notify_customer_replacement(
        replacement, 'replacement_request_received',
        f'/app/replacements/{replacement.pk}/',
        customer_notes=getattr(replacement, 'customer_notes', '') or '',
    )


def _notify_shop_replacement_needs_pricing(replacement):
    _notify_technician_replacement(
        replacement, 'replacement_request_submitted',
        f'/tech/replacements/{replacement.pk}/',
        customer_notes=getattr(replacement, 'customer_notes', '') or '',
    )


def _notify_customer_replacement_approval_needed(replacement):
    _notify_customer_replacement(
        replacement, 'replacement_pending_approval',
        f'/app/replacements/{replacement.pk}/',
    )


def _notify_technician_replacement_approved(replacement):
    _notify_technician_replacement(
        replacement, 'replacement_approved',
        f'/tech/replacements/{replacement.pk}/',
    )


def _notify_technician_replacement_denied(replacement):
    _notify_technician_replacement(
        replacement, 'replacement_denied',
        f'/tech/replacements/{replacement.pk}/',
    )


def _notify_customer_replacement_in_progress(replacement):
    _notify_customer_replacement(
        replacement, 'replacement_in_progress',
        f'/app/replacements/{replacement.pk}/',
    )


def _notify_customer_replacement_completed(replacement):
    _notify_customer_replacement(
        replacement, 'replacement_completed',
        f'/app/replacements/{replacement.pk}/',
    )


# ============================================================================
# NOTIFICATION HELPER FUNCTIONS
# ============================================================================

def _notify_customer_approval_needed(repair):
    """
    Notify customer that a repair needs approval.

    Priority: HIGH (SMS + in-app)
    Triggered when: Repair status → PENDING
    """
    if not repair.customer:
        logger.warning(f"Repair {repair.pk} has no customer linked")
        return

    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'estimated_cost': float(repair.cost),
        'customer_name': repair.customer.name,
        'damage_type': repair.get_damage_type_display() or 'Unknown',
        'action_url': f'/app/repairs/{repair.pk}/',
    }

    # Generate one-click approval tokens for email links
    from apps.customer_portal.models import CustomerUser, ApprovalToken
    try:
        customer_user = CustomerUser.objects.filter(customer=repair.customer).first()
        if customer_user:
            tokens = ApprovalToken.create_pair(repair=repair, customer_user=customer_user)
            context['quick_approve_token'] = str(tokens['approve_token'].token)
            context['quick_deny_token'] = str(tokens['deny_token'].token)
    except Exception as e:
        logger.warning(f"Could not generate approval tokens for repair {repair.pk}: {e}")

    NotificationService.create_notification(
        recipient=repair.customer,
        template_name='repair_pending_approval',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_technician_approved(repair):
    """
    Notify technician that repair has been approved.

    Priority: URGENT (SMS + Email + in-app)
    Triggered when: PENDING → APPROVED
    """
    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name if repair.customer else 'Unknown',
        'estimated_cost': float(repair.cost),
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'action_url': f'/tech/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.technician,
        template_name='repair_approved',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_technician_denied(repair):
    """
    Notify technician that repair has been denied.

    Priority: URGENT (SMS + Email + in-app)
    Triggered when: PENDING → DENIED
    """
    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name if repair.customer else 'Unknown',
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'denial_reason': getattr(repair, 'denial_reason', ''),  # Optional field
        'action_url': f'/tech/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.technician,
        template_name='repair_denied',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_customer_in_progress(repair):
    """
    Notify customer that repair work has started.

    Priority: MEDIUM (Email + in-app)
    Triggered when: status → IN_PROGRESS
    """
    if not repair.customer:
        return

    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'customer_name': repair.customer.name,
        'action_url': f'/app/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.customer,
        template_name='repair_in_progress',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_customer_completed(repair):
    """
    Notify customer that repair has been completed.

    Priority: HIGH (SMS + in-app)
    Triggered when: status → COMPLETED
    """
    if not repair.customer:
        return

    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'final_cost': float(repair.cost),
        'customer_name': repair.customer.name,
        'action_url': f'/app/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.customer,
        template_name='repair_completed',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_owner_repair_completed(repair):
    """
    Notify the tenant owner/manager when a repair is completed.

    This ensures the person who assigned the repair (or the shop owner)
    knows the work is done without having to check manually.

    Priority: NORMAL (in-app + email)
    Triggered when: status → COMPLETED
    """
    if not repair.tenant:
        return

    # Don't notify if the tech IS the owner (they already know)
    owner = repair.tenant.owner
    if repair.technician and repair.technician.user_id == owner.id:
        return

    tech_name = 'Unknown'
    if repair.technician:
        tech_name = repair.technician.user.get_full_name() or repair.technician.user.username

    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name if repair.customer else 'Unknown',
        'technician_name': tech_name,
        'final_cost': float(repair.cost) if repair.cost else 0,
        'action_url': f'/tech/repairs/{repair.pk}/',
    }

    # Notify the owner
    try:
        NotificationService.create_notification(
            recipient=owner,
            template_name='repair_completed',
            context=context,
            repair=repair,
            customer=repair.customer,
        )
    except Exception as e:
        logger.warning(f"Could not notify owner of repair completion: {e}")

    # Also notify managers (who may have assigned the repair)
    try:
        from apps.tenants.models import TenantMembership
        manager_memberships = TenantMembership.objects.filter(
            tenant=repair.tenant, role='manager', is_active=True,
        ).exclude(user=owner).select_related('user')

        for membership in manager_memberships:
            # Don't notify the tech who completed it
            if repair.technician and membership.user_id == repair.technician.user_id:
                continue
            try:
                NotificationService.create_notification(
                    recipient=membership.user,
                    template_name='repair_completed',
                    context=context,
                    repair=repair,
                    customer=repair.customer,
                )
            except Exception as e:
                logger.warning(f"Could not notify manager {membership.user_id} of repair completion: {e}")
    except Exception as e:
        logger.warning(f"Could not notify managers of repair completion: {e}")


def _notify_customer_request_received(repair):
    """
    Notify customer that their repair request has been received.

    Priority: MEDIUM (Email + in-app)
    Triggered when: Customer submits repair via customer portal (REQUESTED status)
    """
    if not repair.customer:
        logger.warning(f"Repair {repair.pk} has no customer linked")
        return

    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name,
        'damage_type': repair.get_damage_type_display() or 'Unknown',
        # What they asked for (S4), echoed back in the email they already
        # get. Deliberately NOT a new customer-facing message: a batch
        # request already fans this template out once per row, so a second
        # stream would multiply by the same factor.
        'preferred_time': repair.get_time_preference(),
        'action_url': f'/app/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.customer,
        template_name='repair_request_received',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_technician_new_request(repair):
    """
    Notify technician/manager that a new repair request was submitted.

    Priority: HIGH (Email + SMS + in-app)
    Triggered when: Customer submits repair via customer portal (REQUESTED status)
    """
    if not repair.technician:
        logger.warning(f"Repair {repair.pk} has no technician assigned")
        return

    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name if repair.customer else 'Unknown',
        'damage_type': repair.get_damage_type_display() or 'Unknown',
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'action_url': f'/tech/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.technician,
        template_name='repair_request_submitted',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def notify_batch_approved(repairs):
    """
    Notify technician that a batch of repairs was approved.

    This is called manually from the batch approval view (not a signal).

    Priority: URGENT (SMS + Email + in-app)

    Args:
        repairs: QuerySet or list of Repair objects in the batch
    """
    if not repairs:
        return

    # All repairs in batch should have same technician
    first_repair = repairs[0]
    technician = first_repair.technician
    batch_id = first_repair.repair_batch_id

    if not batch_id:
        logger.warning("Repairs do not have a batch_id")
        return

    # Calculate batch totals
    repair_count = len(repairs)
    total_cost = sum(float(r.cost) for r in repairs)

    context = {
        'batch_id': str(batch_id),
        'unit_number': first_repair.unit_number,
        'repair_count': repair_count,
        'total_cost': total_cost,
        'customer_name': first_repair.customer.name if first_repair.customer else 'Unknown',
        'technician_name': technician.user.get_full_name() or technician.user.username,
        'action_url': f'/tech/repairs/?batch={batch_id}',
    }

    NotificationService.create_notification(
        recipient=technician,
        template_name='batch_approved',
        context=context,
        repair_batch_id=batch_id,
        customer=first_repair.customer
    )


# ============================================================================
# CACHE INVALIDATION SIGNALS (Phase 6 - Production Optimization)
# ============================================================================

from django.core.cache import cache
from core.models.notification_preferences import TechnicianNotificationPreference


@receiver(post_save, sender=Notification)
def invalidate_notification_cache(sender, instance, created, **kwargs):
    """
    Invalidate cached notification data when a notification is created or updated.

    Cache invalidation targets:
    - Unread count cache for the recipient
    - Recent notifications cache for notification bell

    This ensures the notification bell updates in real-time without
    requiring manual cache clearing.

    Args:
        sender: Notification model class
        instance: Notification instance that was saved
        created: Boolean indicating if this is a new notification
        **kwargs: Additional signal arguments
    """
    try:
        # Get recipient from notification
        recipient = instance.recipient

        if recipient and hasattr(recipient, 'id'):
            # Invalidate unread count cache.
            #
            # CODE-087 added a tenant suffix to the cache key in get_unread_count()
            # so that cross-tenant users see the correct shop's notification count.
            # Cache key format (post-CODE-087): notif_unread_count:tech:{id}:{tenant_pk}
            #
            # The original signal only deleted the old (non-tenant-scoped) key
            # `notif_unread_count:tech:{id}`, which is never set by the view anymore.
            # That made the cache invalidation a no-op: new notifications would not
            # appear in the bell until the 120-second TTL expired.
            #
            # Fix: when the recipient is a Technician (the only model that uses the
            # tenant-scoped key), delete the correct key.  Also delete the legacy key
            # to handle any entries left from before CODE-087.
            from apps.technician_portal.models import Technician as _Technician
            if isinstance(recipient, _Technician) and recipient.tenant_id:
                # Tenant-scoped key (used by get_unread_count after CODE-087)
                tenant_scoped_key = f'notif_unread_count:tech:{recipient.id}:{recipient.tenant_id}'
                cache.delete(tenant_scoped_key)
                logger.debug(
                    f"Invalidated tenant-scoped notification cache for Technician {recipient.id} "
                    f"(tenant {recipient.tenant_id})"
                )
            else:
                # Fallback: non-technician recipients or technicians without a tenant
                # use the legacy key format.
                legacy_key = f'notif_unread_count:tech:{recipient.id}'
                cache.delete(legacy_key)
                logger.debug(
                    f"Invalidated notification cache for {recipient._meta.model_name} {recipient.id}"
                )

    except Exception as e:
        # Cache invalidation errors should not break notification creation
        logger.warning(f"Error invalidating notification cache: {e}")


@receiver(post_save, sender=TechnicianNotificationPreference)
def invalidate_preference_cache(sender, instance, **kwargs):
    """
    Invalidate cached preferences when a technician updates their notification settings.

    This ensures that preference changes take effect immediately without
    requiring users to log out/in.

    Args:
        sender: TechnicianNotificationPreference model class
        instance: Preference instance that was saved
        **kwargs: Additional signal arguments
    """
    try:
        technician_id = instance.technician.id

        # Invalidate preference cache
        # Cache key format: notif_prefs:tech:{technician_id}
        cache_key = f'notif_prefs:tech:{technician_id}'
        cache.delete(cache_key)

        logger.debug(
            f"Invalidated preference cache for technician {technician_id}"
        )

    except Exception as e:
        logger.warning(f"Error invalidating preference cache: {e}")
