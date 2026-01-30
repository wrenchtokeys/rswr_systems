"""
Billing Signals - Event handlers for automatic invoice generation.

This module contains Django signals that trigger billing automation:
- Auto-invoice generation on repair/replacement completion

Author: Amelia (Clawdbot AI)
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _handle_service_completed(instance, created, service_type='repair'):
    """
    Shared handler for repair/replacement completion — trigger auto-invoice if preferences allow.
    """
    # Only process if service is completed
    if instance.queue_status != 'COMPLETED':
        return
    
    # Check if this is a status change to COMPLETED (not just any save of a completed record)
    original_status = getattr(instance, 'original_status', None)
    if original_status == 'COMPLETED' and not created:
        return
    
    try:
        from apps.billing.services.auto_invoice_service import AutoInvoiceService
        
        service = AutoInvoiceService()
        result = service.process_completed_repair(instance)
        
        if result.get('should_generate'):
            invoice_result = result.get('invoice_result', {})
            if invoice_result.get('success'):
                logger.info(
                    f"[billing] Auto-invoice generated for {service_type} #{instance.id}: "
                    f"invoice {invoice_result.get('invoice_number')} -> {invoice_result.get('s3_key')}"
                )
            else:
                logger.warning(
                    f"[billing] Auto-invoice failed for {service_type} #{instance.id}: "
                    f"{invoice_result.get('error')}"
                )
        else:
            logger.debug(f"[billing] Auto-invoice skipped for {service_type} #{instance.id}: {result.get('reason')}")
            
    except Exception as e:
        logger.error(f"[billing] Error in auto-invoice signal for {service_type} #{instance.id}: {e}")


@receiver(post_save, sender='technician_portal.Repair')
def handle_repair_completed(sender, instance, created, **kwargs):
    """Handle repair completion - trigger auto-invoice if customer preferences allow."""
    _handle_service_completed(instance, created, 'repair')


@receiver(post_save, sender='technician_portal.Replacement')
def handle_replacement_completed(sender, instance, created, **kwargs):
    """Handle replacement completion - trigger auto-invoice if customer preferences allow."""
    _handle_service_completed(instance, created, 'replacement')
