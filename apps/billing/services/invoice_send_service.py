"""
InvoiceSendService — the one way to finalize a DRAFT invoice and email it.

Extracted from owner_send_invoice so job-level "Save & Send Invoice" /
"Complete & Send Invoice" actions share the exact pipeline: recipient
resolution → optional inline email capture → PDF/email delivery → mark SENT
only on confirmed delivery (CODE-112: a failed send leaves the invoice DRAFT).
"""

import logging
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    sent: bool
    reason: str  # 'sent' | 'not_draft' | 'invalid_email' | 'duplicate_email' | 'no_email' | 'delivery_failed' | 'error'
    recipient: str = ''
    message: str = ''


class InvoiceSendService:

    @staticmethod
    def send(invoice, tenant, submitted_email=None):
        """Attempt to send a DRAFT invoice; returns a SendResult.

        submitted_email, when the customer has no address on file, is
        validated, checked for cross-customer duplicates, and saved onto the
        customer before sending (inline email capture).
        """
        from core.models import Customer

        if invoice.status not in ('DRAFT',):
            return SendResult(False, 'not_draft',
                              message='Only draft invoices can be sent.')

        try:
            # Resolve recipient email
            recipient = None
            try:
                prefs = invoice.customer.repair_preferences
                recipient = prefs.billing_email or invoice.customer.email
            except Exception:
                recipient = invoice.customer.email

            submitted_email = (submitted_email or '').strip()
            if submitted_email and not recipient:
                try:
                    validate_email(submitted_email)
                except ValidationError:
                    return SendResult(
                        False, 'invalid_email',
                        message=f'"{submitted_email}" is not a valid email address.',
                    )
                duplicate = Customer.objects.filter(
                    tenant=tenant, email__iexact=submitted_email
                ).exclude(pk=invoice.customer.pk).exists()
                if duplicate:
                    return SendResult(
                        False, 'duplicate_email',
                        message='Another customer already uses that email address. '
                                'Please use a different one.',
                    )
                try:
                    # Savepoint so a duplicate slipping past the check above
                    # (race) doesn't poison the surrounding transaction.
                    with transaction.atomic():
                        invoice.customer.email = submitted_email
                        invoice.customer.save(update_fields=['email'])
                except IntegrityError:
                    return SendResult(
                        False, 'duplicate_email',
                        message='Another customer already uses that email address. '
                                'Please use a different one.',
                    )
                recipient = submitted_email

            # CODE-112: Block send entirely if no email on file
            if not recipient:
                return SendResult(
                    False, 'no_email',
                    message=f'Cannot send invoice — no email address on file for '
                            f'{invoice.customer.name}. '
                            f"Add an email in the customer's settings first.",
                )

            # Attempt email delivery
            email_sent = False
            try:
                from apps.billing.services.invoice_email_service import InvoiceEmailService
                email_service = InvoiceEmailService(tenant=tenant)

                # A4: pass the Invoice record so the PDF renders from the
                # invoice's OWN line items and stored totals.
                success, msg = email_service.send_invoice_email(
                    customer_id=invoice.customer.id,
                    recipient_email=recipient,
                    invoice=invoice,
                )
                email_sent = success
                if not success:
                    logger.warning(f"Invoice email failed for {invoice.invoice_number}: {msg}")
            except Exception as e:
                logger.warning(f"Could not email invoice {invoice.invoice_number}: {e}")

            # CODE-112: Only mark SENT if email actually delivered.
            if email_sent:
                invoice.status = 'SENT'
                invoice.sent_at = timezone.now()
                invoice.save(update_fields=['status', 'sent_at'])
                return SendResult(
                    True, 'sent', recipient=recipient,
                    message=f'Invoice {invoice.invoice_number} sent to {recipient}.',
                )
            return SendResult(
                False, 'delivery_failed', recipient=recipient,
                message=f'Invoice {invoice.invoice_number} could NOT be sent — email '
                        f'delivery to {recipient} failed. The invoice remains as a '
                        f'draft. Please check the email address and try again.',
            )

        except Exception as e:
            logger.error(f"Error sending invoice {invoice.invoice_number}: {e}")
            return SendResult(False, 'error',
                              message='An error occurred while sending the invoice.')
