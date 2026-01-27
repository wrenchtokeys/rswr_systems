"""
Clawdbot Signals - Event handlers for automatic actions.

This module contains Django signals that trigger Clawdbot automation:
- Auto-invoice generation on repair completion

Author: Amelia (Clawdbot AI)
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='technician_portal.Repair')
def handle_repair_save(sender, instance, created, **kwargs):
    """
    Handle repair save events - trigger auto-invoice if appropriate.
    
    This signal fires after a Repair is saved. We check if:
    1. The repair just transitioned to COMPLETED status
    2. The customer has auto-invoice preferences enabled
    
    Args:
        sender: The Repair model class
        instance: The Repair instance that was saved
        created: Boolean indicating if this is a new record
        **kwargs: Additional signal arguments
    """
    # Only process if repair is completed
    if instance.queue_status != 'COMPLETED':
        return
    
    # Check if this is a status change to COMPLETED (not just any save of a completed repair)
    # The Repair model tracks original_status - if it was already COMPLETED, skip
    original_status = getattr(instance, 'original_status', None)
    if original_status == 'COMPLETED' and not created:
        # Already was completed, this is just an update (e.g., notes change)
        return
    
    # Don't block the save - run invoice generation async-ish
    # For now, we'll run it synchronously but wrapped in try/except
    try:
        from apps.clawdbot.services.auto_invoice_service import AutoInvoiceService
        
        service = AutoInvoiceService()
        result = service.process_completed_repair(instance)
        
        if result.get('should_generate'):
            invoice_result = result.get('invoice_result', {})
            if invoice_result.get('success'):
                logger.info(
                    f"Auto-invoice generated for repair #{instance.id}: "
                    f"invoice {invoice_result.get('invoice_number')} -> {invoice_result.get('s3_key')}"
                )
            else:
                logger.warning(
                    f"Auto-invoice failed for repair #{instance.id}: "
                    f"{invoice_result.get('error')}"
                )
        else:
            logger.debug(f"Auto-invoice skipped for repair #{instance.id}: {result.get('reason')}")
            
    except Exception as e:
        # Never let invoice generation failure break the repair save
        logger.error(f"Error in auto-invoice signal for repair #{instance.id}: {e}")
