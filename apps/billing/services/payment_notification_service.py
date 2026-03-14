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
            context = {
                'payment': payment,
                'invoice': invoice,
                'customer': customer,
                'branding': self.branding,
            }

            subject = (
                f"[{self.branding.get('company_name', 'RS Systems')}] "
                f"Payment Received — Invoice {invoice.invoice_number}"
            )

            html_body = render_to_string(
                'emails/notifications/payment_received.html', context
            )
            text_body = render_to_string(
                'emails/notifications/payment_received.txt', context
            )

            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
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
            status_text = 'PAID IN FULL' if invoice.status == 'PAID' else f'${invoice.amount_due} remaining'

            subject = (
                f"💰 Payment: ${payment.amount} from {customer.name} "
                f"({status_text})"
            )

            body = (
                f"Payment received!\n\n"
                f"Customer:       {customer.name}\n"
                f"Invoice:        {invoice.invoice_number}\n"
                f"Amount:         ${payment.amount}\n"
                f"Method:         {payment.get_payment_method_display()}\n"
                f"Date:           {payment.payment_date}\n"
                f"{'Reference:      ' + payment.reference_number + chr(10) if payment.reference_number else ''}"
                f"\n"
                f"Invoice Total:  ${invoice.total}\n"
                f"Total Paid:     ${invoice.amount_paid}\n"
                f"Balance:        ${invoice.amount_due}\n"
                f"Status:         {invoice.get_status_display()}\n"
            )

            email = EmailMultiAlternatives(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[owner_email],
            )
            email.send()

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
        result = {
            'customer_sent': False,
            'owner_sent': False,
        }

        result['customer_sent'] = self.send_customer_receipt(payment)
        result['owner_sent'] = self.send_owner_notification(payment)

        return result
