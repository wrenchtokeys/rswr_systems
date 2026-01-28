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
    
    def __init__(self):
        self.from_email = getattr(
            settings, 'INVOICE_FROM_EMAIL', 
            'billing@rockstarwindshield.repair'
        )
    
    def send_reminder(self, invoice, reminder_type='overdue'):
        """
        Send a payment reminder for an invoice.
        
        Args:
            invoice: Invoice model instance
            reminder_type: 'overdue', 'due_soon', 'payment_received'
            
        Returns:
            dict: Send result
        """
        if not invoice.customer.email:
            return {'success': False, 'error': 'Customer has no email address'}
        
        # Build email content
        subject, body = self._build_reminder_email(invoice, reminder_type)
        
        # Send via SendGrid or Django's email backend
        try:
            success = self._send_email(
                to_email=invoice.customer.email,
                subject=subject,
                body=body,
                invoice=invoice
            )
            
            if success:
                # Log the reminder
                invoice.internal_notes += f"\n[Reminder] {reminder_type} sent at {timezone.now()}"
                invoice.save()
                
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
            
            invoices = Invoice.objects.filter(
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
            
            invoices = Invoice.objects.filter(
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
        if not invoice.customer.email:
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
        
        body += """

If you have any questions, please don't hesitate to contact us.

Best regards,
Rockstar Windshield Repair
"""
        
        try:
            success = self._send_email(
                to_email=invoice.customer.email,
                subject=subject,
                body=body,
                invoice=invoice
            )
            return {'success': success}
        except Exception as e:
            logger.error(f"Error sending payment confirmation: {e}")
            return {'success': False, 'error': str(e)}
    
    def _build_reminder_email(self, invoice, reminder_type):
        """Build reminder email subject and body."""
        
        if reminder_type.startswith('due_soon'):
            days = reminder_type.split('_')[-1]
            subject = f"Payment Reminder - Invoice {invoice.invoice_number} Due Soon"
            urgency = "friendly"
        elif reminder_type.startswith('overdue'):
            days = reminder_type.split('_')[-1]
            subject = f"Overdue Notice - Invoice {invoice.invoice_number}"
            urgency = "urgent" if '30d' in reminder_type else "firm"
        else:
            subject = f"Payment Reminder - Invoice {invoice.invoice_number}"
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
        
        closing = """
Thank you for your business.

Best regards,
Rockstar Windshield Repair
Phone: (555) 123-4567
Email: billing@rockstarwindshield.repair
"""
        
        body = f"{greeting}\n{intro}\n{details}\n{payment_info}\n{closing}"
        
        return subject, body
    
    def _send_email(self, to_email, subject, body, invoice=None):
        """
        Send email via SendGrid or Django's email backend.
        
        Returns:
            bool: True if sent successfully
        """
        # Try SendGrid first
        sendgrid_key = getattr(settings, 'SENDGRID_API_KEY', None)
        
        if sendgrid_key:
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail
                
                message = Mail(
                    from_email=self.from_email,
                    to_emails=to_email,
                    subject=subject,
                    plain_text_content=body
                )
                
                sg = SendGridAPIClient(sendgrid_key)
                response = sg.send(message)
                
                return response.status_code in [200, 201, 202]
                
            except Exception as e:
                logger.error(f"SendGrid error: {e}")
                # Fall through to Django email
        
        # Fallback to Django's email backend
        try:
            from django.core.mail import send_mail
            
            send_mail(
                subject=subject,
                message=body,
                from_email=self.from_email,
                recipient_list=[to_email],
                fail_silently=False,
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
        due_soon = Invoice.objects.filter(
            status__in=['SENT', 'PARTIAL'],
            due_date__gte=today,
            due_date__lte=today + timedelta(days=7)
        ).count()
        
        # Overdue
        overdue = Invoice.objects.filter(status='OVERDUE').count()
        
        # Severely overdue (30+ days)
        severely_overdue = Invoice.objects.filter(
            status='OVERDUE',
            due_date__lte=today - timedelta(days=30)
        ).count()
        
        return {
            'due_soon': due_soon,
            'overdue': overdue,
            'severely_overdue': severely_overdue,
            'total_needing_attention': due_soon + overdue,
        }
