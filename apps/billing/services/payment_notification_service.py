"""
Payment Notification Service — sends confirmation emails when payments are received.

Sends to:
1. Customer — payment receipt with invoice summary
2. Owner — notification that payment came in

Triggered by:
- Stripe webhook (automatic online payment)
- Manual payment recording (check, cash, COD)

Author: Amelia (Clawdbot AI)
"""

import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


class PaymentNotificationService:
    """
    Sends payment confirmation emails to customers and owner.
    """

    def __init__(self):
        self._branding = None

    @property
    def branding(self):
        """Lazy-load email branding config."""
        if self._branding is None:
            try:
                from core.models.email_branding import EmailBrandingConfig
                self._branding = EmailBrandingConfig.get_instance().to_template_context()
            except Exception:
                self._branding = {
                    'company_name': 'RS Systems',
                    'primary_color': '#2C5282',
                    'secondary_color': '#4299E1',
                    'success_color': '#38A169',
                    'danger_color': '#E53E3E',
                    'text_color': '#2D3748',
                    'background_color': '#F7FAFC',
                    'heading_font': 'Arial, Helvetica, sans-serif',
                    'body_font': 'Arial, Helvetica, sans-serif',
                    'button_border_radius': 4,
                    'support_email': '',
                    'support_phone': '',
                }
        return self._branding

    def send_customer_receipt(self, payment):
        """
        Send payment confirmation email to the customer.

        Args:
            payment: Payment model instance

        Returns:
            bool: True if sent successfully
        """
        invoice = payment.invoice
        customer = invoice.customer

        # Find recipient email
        recipient = None
        try:
            prefs = customer.repair_preferences
            recipient = prefs.billing_email
        except Exception:
            pass
        recipient = recipient or customer.email

        if not recipient:
            logger.warning(
                f"No email for customer {customer.id} — skipping payment receipt"
            )
            return False

        try:
            # Brand the receipt as the invoice's tenant (the shop), not the
            # platform singleton — customers of every shop receive these.
            branding = self.branding
            tenant = getattr(invoice, 'tenant', None)
            if tenant:
                try:
                    from core.models.email_branding import EmailBrandingConfig
                    branding = EmailBrandingConfig.get_tenant_context(tenant)
                except Exception:
                    pass

            context = {
                'payment': payment,
                'invoice': invoice,
                'customer': customer,
                'branding': branding,
            }

            subject = (
                f"[{branding.get('company_name', 'RS Systems')}] "
                f"Payment Received — Invoice {invoice.invoice_number}"
            )

            html_body = render_to_string(
                'emails/notifications/payment_received.html', context
            )
            text_body = render_to_string(
                'emails/notifications/payment_received.txt', context
            )

            from core.email_utils import shop_sender
            from_email, reply_to = shop_sender(
                shop_name=tenant.name if tenant else None,
                reply_to_email=branding.get('support_email', ''),
            )
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email,
                to=[recipient],
                reply_to=reply_to,
            )
            email.attach_alternative(html_body, 'text/html')
            email.send()

            logger.info(
                f"Payment receipt sent to {recipient} for "
                f"${payment.amount} on {invoice.invoice_number}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send payment receipt: {e}")
            return False

    def send_owner_notification(self, payment):
        """
        Send payment notification to the business owner.

        Args:
            payment: Payment model instance

        Returns:
            bool: True if sent successfully
        """
        invoice = payment.invoice
        customer = invoice.customer

        # Get owner email from BillingConfig (per-tenant) or fallback
        owner_email = None
        try:
            from apps.billing.models import BillingConfig
            tenant = getattr(invoice, 'tenant', None)
            if tenant:
                cfg = BillingConfig.get_for_tenant(tenant)
                owner_email = cfg.company_email
        except Exception:
            pass

        if not owner_email:
            owner_email = getattr(settings, 'DEFAULT_OWNER_EMAIL', None)

        if not owner_email:
            logger.debug("No owner email configured — skipping owner notification")
            return False

        try:
            status_text = 'PAID IN FULL' if invoice.status == 'PAID' else f'${invoice.amount_due:.2f} remaining'

            subject = (
                f"💰 Payment: ${payment.amount:.2f} from {customer.name} "
                f"({status_text})"
            )

            tenant = getattr(invoice, 'tenant', None)

            detail_rows = [
                ('Customer', customer.name),
                ('Invoice', invoice.invoice_number),
                ('Amount', f'${payment.amount:.2f}'),
                ('Method', payment.get_payment_method_display()),
                ('Date', str(payment.payment_date)),
            ]
            if payment.reference_number:
                detail_rows.append(('Reference', payment.reference_number))
            detail_rows.extend([
                ('', ''),  # spacer
                ('Invoice Total', f'${invoice.total:.2f}'),
                ('Total Paid', f'${invoice.amount_paid:.2f}'),
                ('Balance', f'${invoice.amount_due:.2f}'),
                ('Status', invoice.get_status_display()),
            ])

            from core.email_utils import send_branded_email
            send_branded_email(
                subject=subject,
                recipient_list=[owner_email],
                headline=f'Payment Received — ${payment.amount:.2f}',
                body_paragraphs=[
                    f'{customer.name} just paid ${payment.amount:.2f} on invoice {invoice.invoice_number}.',
                ],
                detail_rows=detail_rows,
                tenant=tenant,
            )

            logger.info(
                f"Owner notified of ${payment.amount} payment from {customer.name}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send owner payment notification: {e}")
            return False

    def notify_payment(self, payment):
        """
        Main entry point — send both customer receipt and owner notification.

        Args:
            payment: Payment model instance

        Returns:
            dict: {customer_sent: bool, owner_sent: bool}
        """
        # Refresh the invoice from DB to get post-payment totals.
        # Payment.save() calls _update_invoice_totals() which updates
        # amount_paid/status in the DB, but the in-memory invoice object
        # on `payment.invoice` may still hold stale pre-payment values.
        payment.invoice.refresh_from_db()

        result = {
            'customer_sent': False,
            'owner_sent': False,
        }

        result['customer_sent'] = self.send_customer_receipt(payment)
        result['owner_sent'] = self.send_owner_notification(payment)

        return result
