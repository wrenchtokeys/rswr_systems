"""
Signal handlers for the technician portal app.

These signals automatically trigger notifications when repair events occur:
- Repair status changes (PENDING, APPROVED, DENIED, IN_PROGRESS, COMPLETED)
- Technician assignments and reassignments
- Batch repair approvals

Signal handlers call NotificationService to create notifications which
then queue email/SMS delivery tasks via Celery.
"""

import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from apps.technician_portal.models import Repair
from core.services.notification_service import NotificationService
from core.models.notification import Notification

logger = logging.getLogger(__name__)

# Module-level dictionary to track status changes
# Key: repair.id, Value: previous queue_status
_repair_previous_status = {}
_repair_previous_technician = {}


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
            old_repair = Repair.objects.get(pk=instance.pk)
            _repair_previous_status[instance.pk] = old_repair.queue_status
            _repair_previous_technician[instance.pk] = old_repair.technician
        except Repair.DoesNotExist:
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

    # Clean up tracking dict to prevent memory leaks
    if instance.pk in _repair_previous_status:
        del _repair_previous_status[instance.pk]


@receiver(post_save, sender=Repair)
def handle_technician_assignment(sender, instance, created, **kwargs):
    """
    Handle technician assignments and reassignments.

    Triggers notifications when:
    - New repair is assigned to a technician
    - Repair is reassigned to a different technician

    Args:
        sender: Repair model class
        instance: Repair instance that was saved
        created: Boolean indicating if this is a new repair
        **kwargs: Additional signal arguments
    """
    # New assignment
    if created and instance.technician:
        _notify_technician_assigned(instance)
        return

    # Check for reassignment
    if not created and instance.pk:
        old_technician = _repair_previous_technician.get(instance.pk)

        if old_technician and old_technician != instance.technician:
            logger.info(
                f"Repair {instance.pk} reassigned: "
                f"{old_technician} → {instance.technician}"
            )

            # Notify old technician about reassignment
            _notify_technician_reassigned(instance, old_technician)

            # Notify new technician about assignment
            _notify_technician_assigned(instance)

        # Clean up tracking dict
        if instance.pk in _repair_previous_technician:
            del _repair_previous_technician[instance.pk]


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


def _notify_technician_assigned(repair):
    """
    Notify technician of new repair assignment.

    Priority: HIGH (SMS + in-app)
    Triggered when: New repair created or repair reassigned
    """
    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name if repair.customer else 'Unknown',
        'status': repair.get_queue_status_display(),
        'technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'action_url': f'/tech/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=repair.technician,
        template_name='repair_assigned',
        context=context,
        repair=repair,
        customer=repair.customer
    )


def _notify_technician_reassigned(repair, old_technician):
    """
    Notify old technician that repair was reassigned.

    Priority: MEDIUM (Email + in-app)
    Triggered when: Technician changed on existing repair
    """
    context = {
        'repair_id': repair.pk,
        'unit_number': repair.unit_number,
        'new_technician_name': repair.technician.user.get_full_name() or repair.technician.user.username,
        'customer_name': repair.customer.name if repair.customer else 'Unknown',
        'action_url': f'/tech/repairs/{repair.pk}/',
    }

    NotificationService.create_notification(
        recipient=old_technician,
        template_name='repair_reassigned_away',
        context=context,
        repair=repair,
        customer=repair.customer
    )


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

        if recipient:
            # Invalidate unread count cache
            # Cache key format: notif_unread_count:tech:{technician_id}
            if hasattr(recipient, 'id'):
                cache_key = f'notif_unread_count:tech:{recipient.id}'
                cache.delete(cache_key)

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
