"""
Reminder Service - Sends payment reminders for outstanding invoices.

Provides:
- Overdue invoice reminders
- Upcoming due date reminders
- Payment confirmation emails
- Batch reminder processing

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


class ReminderService:
    """
    Handles sending payment reminders and notifications.
    """
    
    # Reminder schedule (days before/after due date)
    REMINDER_SCHEDULE = {
        'before_due': [7, 3, 1],      # Days before due date
        'after_due': [1, 7, 14, 30],  # Days after due date
    }
    
    def __init__(self, tenant=None):
        self.tenant = tenant
        # Use noreply email - replies won't be received
        self.from_email = getattr(
            settings, 'REMINDER_FROM_EMAIL',
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@rssystems.io')
        )
    
    def _filter(self, qs):
        """Apply tenant filter to any queryset."""
        if self.tenant:
            return qs.filter(tenant=self.tenant)
        return qs.none()
    
    def send_reminder(self, invoice, reminder_type='overdue', custom_body=None):
        """
        Send a payment reminder for an invoice with PDF attached.
        
        Args:
            invoice: Invoice model instance
            reminder_type: 'overdue', 'due_soon', 'payment_received'
            custom_body: Optional custom message body (overrides default template)
            
        Returns:
            dict: Send result
        """
        # Prefer billing_email from CustomerRepairPreference when set — fleet customers
        # often have a dedicated AP email that differs from their general contact email.
        # Consistent with the manual invoice send flow in saas/views.py. (CODE-127)
        _recipient_email = None
        try:
            _prefs = invoice.customer.repair_preferences
            _recipient_email = _prefs.billing_email or invoice.customer.email
        except Exception:
            _recipient_email = invoice.customer.email

        if not _recipient_email:
            return {'success': False, 'error': 'Customer has no email address'}
        
        # Build email content — use custom body if provided (CODE-113)
        subject, body = self._build_reminder_email(invoice, reminder_type)
        if custom_body:
            body = custom_body
        elif self.tenant:
            # Check for saved template in BillingConfig
            try:
                from apps.billing.models import BillingConfig
                config = BillingConfig.get_for_tenant(self.tenant)
                if config.reminder_email_template:
                    body = self._render_template(config.reminder_email_template, invoice)
            except Exception:
                pass  # Fall back to default
        
        # Generate PDF attachment
        pdf_bytes = None
        try:
            from apps.billing.services.invoice_service import InvoiceService
            # Pass tenant so InvoiceService loads the correct BillingConfig (company name,
            # address, payment terms).  Without tenant, InvoiceService() skips
            # BillingConfig and generates PDFs with blank company info — same root
            # cause as CODE-090 (clawdbot views).  (CODE-092)
            invoice_tenant = getattr(invoice, 'tenant', None) or getattr(
                getattr(invoice, 'customer', None), 'tenant', None
            )
            invoice_service = InvoiceService(tenant=invoice_tenant)
            repair_ids = list(invoice.line_items.exclude(repair_id__isnull=True).values_list('repair_id', flat=True))
            pdf_bytes, _ = invoice_service.generate_invoice(
                customer_id=invoice.customer_id,
                repair_ids=repair_ids if repair_ids else None,
            )
        except Exception as e:
            logger.warning(f"Could not generate PDF for reminder: {e}")
            # Continue without PDF - still send the reminder
        
        # Send via SendGrid or Django's email backend
        try:
            success = self._send_email(
                to_email=_recipient_email,
                subject=subject,
                body=body,
                invoice=invoice,
                pdf_attachment=pdf_bytes
            )
            
            if success:
                # Log the reminder — only update internal_notes so we never
                # overwrite status/totals/paid_at with a stale in-memory value.
                # PDF generation + SMTP can take a few seconds; a full save()
                # could clobber a payment that arrived during that window.
                # Matches the pattern used in tasks._send_overdue_reminder().
                # (CODE-171)
                invoice.internal_notes = (invoice.internal_notes or '') + f"\n[Reminder] {reminder_type} sent at {timezone.now()}"
                invoice.save(update_fields=['internal_notes'])

                logger.info(f"Sent {reminder_type} reminder for invoice {invoice.invoice_number}")
                return {'success': True, 'reminder_type': reminder_type}
            else:
                return {'success': False, 'error': 'Email send failed'}
                
        except Exception as e:
            logger.error(f"Error sending reminder: {e}")
            return {'success': False, 'error': str(e)}
    
    def process_due_soon_reminders(self):
        """
        Send reminders for invoices due soon.
        Run this daily via cron.
        
        Returns:
            dict: Processing results
        """
        from apps.billing.models import Invoice
        
        today = timezone.now().date()
        results = {'sent': 0, 'skipped': 0, 'errors': 0}
        
        for days_before in self.REMINDER_SCHEDULE['before_due']:
            target_due_date = today + timedelta(days=days_before)
            
            invoices = self._filter(Invoice.objects).filter(
                status__in=['SENT', 'PARTIAL'],
                due_date=target_due_date
            )
            
            for invoice in invoices:
                # Check if we already sent this reminder
                reminder_key = f"[Reminder] due_soon_{days_before}d"
                if reminder_key in invoice.internal_notes:
                    results['skipped'] += 1
                    continue
                
                result = self.send_reminder(invoice, f'due_soon_{days_before}d')
                if result['success']:
                    results['sent'] += 1
                else:
                    results['errors'] += 1
        
        logger.info(f"Due soon reminders: {results}")
        return results
    
    def process_overdue_reminders(self):
        """
        Send reminders for overdue invoices.
        Run this daily via cron.
        
        Returns:
            dict: Processing results
        """
        from apps.billing.models import Invoice
        
        today = timezone.now().date()
        results = {'sent': 0, 'skipped': 0, 'errors': 0}
        
        for days_after in self.REMINDER_SCHEDULE['after_due']:
            target_due_date = today - timedelta(days=days_after)
            
            invoices = self._filter(Invoice.objects).filter(
                status__in=['SENT', 'PARTIAL', 'OVERDUE'],
                due_date=target_due_date
            )
            
            for invoice in invoices:
                # Check if we already sent this reminder
                reminder_key = f"[Reminder] overdue_{days_after}d"
                if reminder_key in invoice.internal_notes:
                    results['skipped'] += 1
                    continue
                
                result = self.send_reminder(invoice, f'overdue_{days_after}d')
                if result['success']:
                    results['sent'] += 1
                else:
                    results['errors'] += 1
        
        logger.info(f"Overdue reminders: {results}")
        return results
    
    def send_payment_confirmation(self, invoice, payment):
        """
        Send payment confirmation email.
        
        Args:
            invoice: Invoice model instance
            payment: Payment model instance
            
        Returns:
            dict: Send result
        """
        # Prefer billing_email from CustomerRepairPreference when set — same logic
        # as send_reminder() above.  (CODE-127)
        _pc_recipient = None
        try:
            _pc_prefs = invoice.customer.repair_preferences
            _pc_recipient = _pc_prefs.billing_email or invoice.customer.email
        except Exception:
            _pc_recipient = invoice.customer.email

        if not _pc_recipient:
            return {'success': False, 'error': 'Customer has no email address'}
        
        subject = f"Payment Received - Invoice {invoice.invoice_number}"
        
        body = f"""
Dear {invoice.customer.name},

Thank you for your payment!

Payment Details:
- Invoice: {invoice.invoice_number}
- Amount Received: ${payment.amount:,.2f}
- Payment Method: {payment.get_payment_method_display()}
- Date: {payment.payment_date.strftime('%B %d, %Y')}

Invoice Status: {invoice.get_status_display()}
"""
        
        if invoice.status == 'PAID':
            body += "\nThis invoice has been paid in full. Thank you for your business!"
        else:
            body += f"\nRemaining Balance: ${invoice.amount_due:,.2f}"

        # Look up company name from per-tenant BillingConfig
        _company_name = ""
        _tenant = self.tenant or getattr(invoice, 'tenant', None)
        if _tenant:
            try:
                from apps.billing.models import BillingConfig
                _config = BillingConfig.get_for_tenant(_tenant)
                if _config:
                    _company_name = _config.company_name or _tenant.name or ""
            except Exception:
                pass
            if not _company_name:
                _company_name = _tenant.name

        body += f"""

If you have any questions, please don't hesitate to contact us.

Best regards,
{_company_name}
"""
        
        try:
            success = self._send_email(
                to_email=_pc_recipient,
                subject=subject,
                body=body,
                invoice=invoice
            )
            return {'success': success}
        except Exception as e:
            logger.error(f"Error sending payment confirmation: {e}")
            return {'success': False, 'error': str(e)}
    
    def _render_template(self, template_str, invoice):
        """Render a user-defined email template with invoice placeholders."""
        from django.utils import timezone
        today = timezone.now().date()
        days_overdue = max(0, (today - invoice.due_date).days) if invoice.due_date else 0

        company_name = ''
        if self.tenant:
            try:
                from apps.billing.models import BillingConfig
                config = BillingConfig.get_for_tenant(self.tenant)
                company_name = config.company_name or self.tenant.name
            except Exception:
                company_name = self.tenant.name

        try:
            return template_str.format(
                customer_name=invoice.customer.name,
                invoice_number=invoice.invoice_number,
                total=f'${invoice.total:,.2f}',
                amount_due=f'${invoice.amount_due:,.2f}',
                due_date=invoice.due_date.strftime('%B %d, %Y') if invoice.due_date else 'N/A',
                days_overdue=days_overdue,
                company_name=company_name,
            )
        except (KeyError, IndexError, ValueError) as exc:
            # User-editable template contains unknown placeholders or malformed
            # braces (e.g. a stray "{").  Log a warning so the shop owner's
            # custom template failure is visible in logs rather than silently
            # swallowed, and return empty string so callers fall back to the
            # default template.  Same pattern as invoice_email_service.py and
            # billing/tasks.py.  (CODE-256)
            logger.warning(
                "Malformed reminder_email_template for tenant %s: %r — %s",
                self.tenant.pk if self.tenant else '?',
                template_str[:200],
                exc,
            )
            return ''

    def _build_reminder_email(self, invoice, reminder_type):
        """Build reminder email subject and body."""
        
        customer_name = invoice.customer.name
        
        if reminder_type.startswith('due_soon'):
            days = reminder_type.split('_')[-1]
            subject = f"[RS Systems] Payment Reminder: Invoice {invoice.invoice_number} - {customer_name}"
            urgency = "friendly"
        elif reminder_type.startswith('overdue'):
            days = reminder_type.split('_')[-1]
            subject = f"[RS Systems] Overdue Notice: Invoice {invoice.invoice_number} - {customer_name}"
            urgency = "urgent" if '30d' in reminder_type else "firm"
        else:
            subject = f"[RS Systems] Payment Reminder: Invoice {invoice.invoice_number} - {customer_name}"
            urgency = "friendly"
        
        # Build body
        greeting = f"Dear {invoice.customer.name},"
        
        if urgency == "friendly":
            intro = f"""
This is a friendly reminder that invoice {invoice.invoice_number} is due on {invoice.due_date.strftime('%B %d, %Y')}.
"""
        elif urgency == "firm":
            intro = f"""
This is a reminder that invoice {invoice.invoice_number} was due on {invoice.due_date.strftime('%B %d, %Y')} and remains unpaid.
"""
        else:  # urgent
            intro = f"""
IMPORTANT: Invoice {invoice.invoice_number} is now significantly overdue. The original due date was {invoice.due_date.strftime('%B %d, %Y')}.

Please arrange payment immediately to avoid any service interruptions.
"""
        
        details = f"""
Invoice Details:
- Invoice Number: {invoice.invoice_number}
- Invoice Date: {invoice.invoice_date.strftime('%B %d, %Y')}
- Due Date: {invoice.due_date.strftime('%B %d, %Y')}
- Total Amount: ${invoice.total:,.2f}
- Amount Paid: ${invoice.amount_paid:,.2f}
- Amount Due: ${invoice.amount_due:,.2f}
"""
        
        # Add payment link if available
        payment_info = ""
        if invoice.stripe_hosted_url:
            payment_info = f"""
Pay Online: {invoice.stripe_hosted_url}

Or contact us to arrange alternative payment methods.
"""
        else:
            payment_info = """
Please contact us to arrange payment or if you have any questions.
"""
        
        # Get company info from BillingConfig (per-tenant)
        company_name = ""
        company_phone = ""
        company_website = ""
        _reminder_tenant = self.tenant or getattr(invoice, 'tenant', None)
        if _reminder_tenant:
            try:
                from apps.billing.models import BillingConfig
                config = BillingConfig.get_for_tenant(_reminder_tenant)
                if config:
                    company_name = config.company_name or _reminder_tenant.name or ""
                    company_phone = config.company_phone or _reminder_tenant.business_phone or ""
                    company_website = config.company_website or ""
            except Exception:
                pass
            if not company_name:
                company_name = _reminder_tenant.name
        
        # Build closing with actual company info
        closing_lines = [
            "",
            "Thank you for your business.",
            "",
            "Best regards,",
            company_name,
        ]
        if company_phone:
            closing_lines.append(f"Phone: {company_phone}")
        if company_website:
            closing_lines.append(company_website)
        closing_lines.extend([
            "",
            "---",
            "This is an automated message. Please do not reply to this email.",
        ])
        
        closing = "\n".join(closing_lines)
        
        body = f"{greeting}\n{intro}\n{details}\n{payment_info}\n{closing}"
        
        return subject, body
    
    def _send_email(self, to_email, subject, body, invoice=None, pdf_attachment=None):
        """
        Send email via SendGrid or Django's email backend.
        
        Args:
            to_email: Recipient email
            subject: Email subject
            body: Plain text body
            invoice: Invoice object (for PDF filename)
            pdf_attachment: PDF bytes to attach
            
        Returns:
            bool: True if sent successfully
        """
        # Try SendGrid first
        sendgrid_key = getattr(settings, 'SENDGRID_API_KEY', None)
        
        if sendgrid_key:
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
                import base64
                
                message = Mail(
                    from_email=self.from_email,
                    to_emails=to_email,
                    subject=subject,
                    plain_text_content=body
                )
                
                # Attach PDF if provided
                if pdf_attachment and invoice:
                    encoded_pdf = base64.b64encode(pdf_attachment).decode()
                    attachment = Attachment(
                        FileContent(encoded_pdf),
                        FileName(f"Invoice_{invoice.invoice_number}.pdf"),
                        FileType('application/pdf'),
                        Disposition('attachment')
                    )
                    message.attachment = attachment
                
                sg = SendGridAPIClient(sendgrid_key)
                response = sg.send(message)
                
                return response.status_code in [200, 201, 202]
                
            except Exception as e:
                logger.error(f"SendGrid error: {e}")
                # Fall through to Django email
        
        # Fallback to Django's email backend (branded HTML)
        try:
            from core.email_utils import send_branded_email

            attachments = []
            if pdf_attachment and invoice:
                attachments.append(
                    (f"Invoice_{invoice.invoice_number}.pdf", pdf_attachment, 'application/pdf')
                )

            tenant = getattr(invoice, 'tenant', None) if invoice else None
            send_branded_email(
                subject=subject,
                recipient_list=[to_email],
                headline=subject,
                body_paragraphs=[body],
                tenant=tenant,
                attachments=attachments,
                from_email=self.from_email,
            )
            return True
            
        except Exception as e:
            logger.error(f"Django email error: {e}")
            return False
    
    def get_reminder_summary(self):
        """
        Get summary of pending reminders.
        
        Returns:
            dict: Summary of invoices needing reminders
        """
        from apps.billing.models import Invoice
        
        today = timezone.now().date()
        
        # Due soon (next 7 days)
        due_soon = self._filter(Invoice.objects).filter(
            status__in=['SENT', 'PARTIAL'],
            due_date__gte=today,
            due_date__lte=today + timedelta(days=7)
        ).count()
        
        # Overdue
        overdue = self._filter(Invoice.objects).filter(status='OVERDUE').count()
        
        # Severely overdue (30+ days)
        severely_overdue = self._filter(Invoice.objects).filter(
            status='OVERDUE',
            due_date__lte=today - timedelta(days=30)
        ).count()
        
        return {
            'due_soon': due_soon,
            'overdue': overdue,
            'severely_overdue': severely_overdue,
            'total_needing_attention': due_soon + overdue,
        }
