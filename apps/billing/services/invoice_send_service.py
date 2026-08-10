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
    def resolve_recipient(customer):
        """Where an invoice email for this customer goes: the dedicated
        billing email when set, else the customer's main email ('' if none).
        Single source of truth — the send pipeline and the confirmation
        dialogs must show/use the same address."""
        if customer is None:
            return ''
        try:
            prefs = customer.repair_preferences
            return prefs.billing_email or customer.email or ''
        except Exception:
            return customer.email or ''

    @staticmethod
    def resolve_recipient_phone(customer):
        """E.164 mobile number an invoice text for this customer would go to,
        or '' when there is no usable phone on file. Single source of truth —
        the send pipeline and the confirmation dialogs must show/use the
        same number."""
        from core.services.sms_service import SMSService
        if customer is None:
            return ''
        return SMSService.normalize_phone(customer.phone) or ''

    @staticmethod
    def sms_ready(tenant):
        """Tenant-level gate for invoice texting: platform SMS configured
        (toll-free number live) + the shop's Text Invoices toggle on."""
        from core.services.sms_service import SMSService
        from apps.billing.models import BillingConfig
        if not SMSService.is_enabled():
            return False
        try:
            return BillingConfig.get_for_tenant(tenant).sms_invoicing_enabled
        except Exception:
            return False

    @staticmethod
    def sms_available(invoice, tenant):
        """Whether the 'Text the invoice' option should be offered for this
        invoice: tenant gate + a usable phone on the customer."""
        return (
            InvoiceSendService.sms_ready(tenant)
            and bool(InvoiceSendService.resolve_recipient_phone(invoice.customer))
        )

    @staticmethod
    def send_sms(invoice, tenant):
        """Text the customer a link to the public invoice page.

        Returns (ok: bool, message: str). Only called after the invoice is
        SENT (or for resends) — a text never promotes a DRAFT, and a failed
        text never blocks the email pipeline. Records SMS consent on the
        customer (the acting shop user attests via the send dialog).
        """
        from core.services.sms_service import SMSService

        phone = InvoiceSendService.resolve_recipient_phone(invoice.customer)
        if not phone:
            return False, 'No usable mobile number on file for this customer.'
        if not InvoiceSendService.sms_ready(tenant):
            return False, 'Text messaging is not enabled for this shop.'

        invoice.customer.record_sms_consent()
        body = InvoiceSendService._build_sms_body(invoice, tenant, phone)
        ok, _log = SMSService.send_notification_sms(
            notification_id=None, recipient_phone=phone, message=body,
            tenant=tenant,
        )
        if ok:
            invoice.record_sms_sent(phone)
            return True, f'Invoice link texted to {phone}.'
        return False, f'Could not text the invoice to {phone} — see the invoice email instead.'

    @staticmethod
    def _build_sms_body(invoice, tenant, phone):
        """One-segment invoice text. The public link must never be truncated,
        so the shop name is what gives way when space runs out. Opt-out
        wording rides on the customer's first text only (toll-free
        verification expects it once, not on every message)."""
        from django.conf import settings
        from apps.billing.pay_links import public_pay_url
        from core.models.notification_delivery_log import NotificationDeliveryLog
        from core.services.sms_service import SMSService

        link = public_pay_url(invoice)
        verb = 'View & pay' if link else 'View'
        if not link:
            from rs_systems.views import generate_payment_token
            base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
            link = f"{base_url}/invoice/{invoice.id}/{generate_payment_token(invoice.id)}/"

        stop = ''
        first_text = not NotificationDeliveryLog.objects.filter(
            channel='sms', recipient_phone=phone, tenant=tenant,
        ).exists()
        if first_text:
            stop = ' Reply STOP to opt out.'

        tail = f": Invoice {invoice.invoice_number} for ${invoice.total} — {verb.lower()}: {link}{stop}"
        shop = (tenant.name or 'Your auto glass shop').strip()
        room = SMSService.MAX_SMS_LENGTH - len(tail)
        if len(shop) > room:
            shop = shop[:max(room, 0)].rstrip()
        return f"{shop}{tail}"

    @staticmethod
    def send(invoice, tenant, submitted_email=None, copy_to_email=None):
        """Attempt to send a DRAFT invoice; returns a SendResult.

        submitted_email, when the customer has no address on file, is
        validated, checked for cross-customer duplicates, and saved onto the
        customer before sending (inline email capture).

        copy_to_email, when set, receives a BCC copy of the invoice email
        ("Send me a copy" — the acting shop user's address).
        """
        from core.models import Customer

        if invoice.status not in ('DRAFT',):
            return SendResult(False, 'not_draft',
                              message='Only draft invoices can be sent.')

        try:
            # Resolve recipient email
            recipient = InvoiceSendService.resolve_recipient(invoice.customer)

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
                    bcc_emails=[copy_to_email] if copy_to_email else None,
                )
                email_sent = success
                if not success:
                    logger.warning(f"Invoice email failed for {invoice.invoice_number}: {msg}")
            except Exception as e:
                logger.warning(f"Could not email invoice {invoice.invoice_number}: {e}")

            # CODE-112: Only mark SENT if email actually delivered.
            if email_sent:
                invoice.record_email_sent(recipient)
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
