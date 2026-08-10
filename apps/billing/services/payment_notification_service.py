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

            from apps.billing.pay_links import public_invoice_pdf_url, public_pay_url
            context = {
                'payment': payment,
                'invoice': invoice,
                'customer': customer,
                'branding': branding,
                # Tokened /pay/ URL (shop's Connect account); None when the
                # shop can't take online payments — template hides the button.
                'pay_url': public_pay_url(invoice),
                # Tokened PDF link — carries the PAID stamp once paid, so it
                # serves as the customer's downloadable receipt.
                'receipt_pdf_url': public_invoice_pdf_url(invoice),
            }

            # Plain transactional subject — no bracketed prefix, no emoji
            # (spam heuristics; see docs/operations/SES_OPERATIONS.md).
            subject = (
                f"Your receipt from {branding.get('company_name', 'RS Systems')} "
                f"— Invoice {invoice.invoice_number}"
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

        # Owner recipient: BillingConfig.company_email → tenant.business_email
        # → the owner user's own email. Always tenant-scoped — never a global
        # settings fallback, which would leak every shop's payment activity
        # to one address.
        owner_email = None
        tenant = getattr(invoice, 'tenant', None)
        try:
            from apps.billing.models import BillingConfig
            if tenant:
                cfg = BillingConfig.get_for_tenant(tenant)
                owner_email = cfg.company_email
        except Exception:
            pass

        if not owner_email and tenant:
            owner_email = tenant.business_email or ''
            if not owner_email and tenant.owner:
                owner_email = tenant.owner.email or ''

        if not owner_email:
            logger.warning(
                f"No owner email for tenant {getattr(tenant, 'slug', None)} — "
                f"skipping payment notification"
            )
            return False

        try:
            status_text = 'PAID IN FULL' if invoice.status == 'PAID' else f'${invoice.amount_due:.2f} remaining'

            subject = (
                f"Payment: ${payment.amount:.2f} from {customer.name} "
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

    def notify_payment_batch(self, payments):
        """
        One payment covering several invoices for the SAME customer (a fleet
        check applied across open invoices): send ONE combined customer
        receipt and ONE owner notification instead of an email per invoice.

        Args:
            payments: list of Payment instances, all on invoices of one customer

        Returns:
            dict: {customer_sent: bool, owner_sent: bool}
        """
        payments = [p for p in payments if p is not None]
        if not payments:
            return {'customer_sent': False, 'owner_sent': False}
        if len(payments) == 1:
            return self.notify_payment(payments[0])

        for p in payments:
            p.invoice.refresh_from_db()

        first = payments[0]
        customer = first.invoice.customer
        tenant = getattr(first.invoice, 'tenant', None)
        total = sum((p.amount for p in payments), 0)
        method_display = first.get_payment_method_display()
        reference = first.reference_number

        per_invoice_rows = []
        for p in payments:
            inv = p.invoice
            status_note = 'Paid in full' if inv.status == 'PAID' else f'${inv.amount_due:.2f} remaining'
            per_invoice_rows.append(
                (f'Invoice {inv.invoice_number}', f'${p.amount:.2f} — {status_note}')
            )

        result = {'customer_sent': False, 'owner_sent': False}

        # --- Customer receipt ---
        recipient = None
        try:
            recipient = customer.repair_preferences.billing_email
        except Exception:
            pass
        recipient = recipient or customer.email

        from core.email_utils import send_branded_email, shop_sender

        if recipient:
            try:
                detail_rows = [
                    ('Amount Received', f'${total:.2f}'),
                    ('Method', method_display),
                    ('Date', str(first.payment_date)),
                ]
                if reference:
                    detail_rows.append(('Reference', reference))
                detail_rows.append(('', ''))
                detail_rows.extend(per_invoice_rows)

                from_email, _ = shop_sender(shop_name=tenant.name if tenant else None)
                shop_name = tenant.name if tenant else 'RS Systems'
                send_branded_email(
                    subject=f'Your receipt from {shop_name} — ${total:.2f} across {len(payments)} invoices',
                    recipient_list=[recipient],
                    headline=f'Payment Received — ${total:.2f}',
                    body_paragraphs=[
                        f'Thank you! We received your payment of ${total:.2f} '
                        f'and applied it across {len(payments)} invoices as shown below.',
                    ],
                    detail_rows=detail_rows,
                    tenant=tenant,
                    from_email=from_email,
                )
                result['customer_sent'] = True
            except Exception as e:
                logger.error(f"Failed to send combined payment receipt: {e}")

        # --- Owner notification ---
        owner_email = None
        try:
            from apps.billing.models import BillingConfig
            if tenant:
                owner_email = BillingConfig.get_for_tenant(tenant).company_email
        except Exception:
            pass
        if not owner_email and tenant:
            owner_email = tenant.business_email or ''
            if not owner_email and tenant.owner:
                owner_email = tenant.owner.email or ''

        if owner_email:
            try:
                detail_rows = [
                    ('Customer', customer.name),
                    ('Amount', f'${total:.2f}'),
                    ('Method', method_display),
                    ('Date', str(first.payment_date)),
                ]
                if reference:
                    detail_rows.append(('Reference', reference))
                detail_rows.append(('', ''))
                detail_rows.extend(per_invoice_rows)

                send_branded_email(
                    subject=f'Payment: ${total:.2f} from {customer.name} ({len(payments)} invoices)',
                    recipient_list=[owner_email],
                    headline=f'Payment Received — ${total:.2f}',
                    body_paragraphs=[
                        f'{customer.name} paid ${total:.2f}, applied across '
                        f'{len(payments)} invoices.',
                    ],
                    detail_rows=detail_rows,
                    tenant=tenant,
                )
                result['owner_sent'] = True
            except Exception as e:
                logger.error(f"Failed to send combined owner payment notification: {e}")

        return result
