"""
Job flow helpers — complete a shop-created job and invoice it in one motion.

Backs the quick-create "job already completed" checkbox and the
"Complete & Send Invoice" buttons. Completion always goes through a second
save() (a legal forward jump in ALLOWED_STATUS_TRANSITIONS) rather than
creating records directly as COMPLETED: the completion side effects (unit
counter, pricing, loyalty, warranty, billing signal) only fire on a
transition INTO COMPLETED, and their idempotency guards key off
original_status, which equals queue_status on a fresh instance.
"""

import logging

from apps.technician_portal.models import Repair

logger = logging.getLogger(__name__)


class JobFlowError(Exception):
    """User-facing refusal — .args[0] is the message to show."""


def complete_job(service):
    """Advance a job to COMPLETED with exactly-once completion side effects.

    No-op if already COMPLETED. Refuses PENDING (the customer's preference
    requires an explicit approval step — don't silently bypass it) and
    REQUESTED/DENIED (those need the review flow).
    """
    if service.queue_status == 'COMPLETED':
        return
    if service.queue_status == 'PENDING':
        raise JobFlowError(
            'This customer requires approval before work is marked complete. '
            'The job was saved and is awaiting approval.'
        )
    if service.queue_status not in ('APPROVED', 'IN_PROGRESS'):
        raise JobFlowError(
            f'A {service.get_queue_status_display().lower()} job cannot be '
            f'marked complete from here — review it first.'
        )
    service.queue_status = 'COMPLETED'
    service.save()


def collect_billable_services(service, tenant):
    """The service plus, for multi-break repairs, its COMPLETED batch siblings.

    Returns (services, excluded_count) where excluded_count is how many batch
    siblings were skipped for not being COMPLETED (CODE-226/247 behavior).
    """
    if isinstance(service, Repair) and service.repair_batch_id:
        siblings = list(
            Repair.objects.filter(
                tenant=tenant, repair_batch_id=service.repair_batch_id,
            ).order_by('break_number')
        )
        completed = [r for r in siblings if r.queue_status == 'COMPLETED']
        return completed, len(siblings) - len(completed)
    return [service], 0


def find_active_invoice(services, tenant):
    """Existing non-voided invoice covering any of these services, or None."""
    from apps.billing.models import InvoiceLineItem

    for svc in services:
        field = 'repair' if isinstance(svc, Repair) else 'replacement'
        line_item = InvoiceLineItem.objects.filter(
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID'],
            **{field: svc},
        ).select_related('invoice').first()
        if line_item:
            return line_item.invoice
    return None


def invoice_and_send(service, tenant, submitted_email=None, copy_to_email=None):
    """Find-or-create the invoice for a COMPLETED job and email it.

    Returns (invoice, created, send_result, excluded_count).
    send_result is an InvoiceSendService.SendResult; when the existing invoice
    is already SENT/PAID, reason is 'not_draft' and nothing is re-sent.
    Reuses any invoice the auto-invoice signal may have already created.
    """
    from apps.billing.services.invoice_send_service import InvoiceSendService
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

    services, excluded = collect_billable_services(service, tenant)
    invoice = find_active_invoice(services, tenant)
    created = False
    if invoice is None:
        invoice = InvoiceTrackingService(tenant=tenant).create_invoice_from_services(
            customer=service.customer, services=services,
        )
        created = True

    result = InvoiceSendService.send(invoice, tenant, submitted_email=submitted_email,
                                     copy_to_email=copy_to_email)
    return invoice, created, result, excluded
