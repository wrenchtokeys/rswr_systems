"""
Billing Automation

Business logic for automated billing operations:
- process_overdue_invoices: Daily check for overdue invoices + reminder emails
- process_batch_invoices: Scheduled batch invoice generation for fleet customers
- generate_aging_report: AR aging report

These are plain functions (no Celery). Invoke them:
  - From management commands (cron): process_batch_invoices, process_overdue_invoices
  - On-demand: generate_aging_report

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.tenants.models import Tenant
from apps.technician_portal.models import Repair, Replacement
from apps.customer_portal.models import CustomerRepairPreference
from core.models import Customer

logger = logging.getLogger(__name__)


# =============================================================================
# OVERDUE INVOICE PROCESSING
# =============================================================================

def process_overdue_invoices():
    """
    Daily task to:
    1. Update invoice status from SENT → OVERDUE when past due date
    2. Send reminder emails based on configured schedule
    
    Runs for all tenants with overdue_reminder_enabled=True.
    """
    today = timezone.now().date()
    processed_count = 0
    reminder_count = 0
    
    # Get all tenants (in future, filter by those with billing automation enabled)
    tenants = Tenant.objects.filter(is_active=True)
    
    for tenant in tenants:
        try:
            config = BillingConfig.get_for_tenant(tenant)
        except Exception:
            config = None
        
        # Step 1: Update status to OVERDUE for past-due invoices
        updated = Invoice.objects.filter(
            tenant=tenant,
            status__in=['SENT', 'PARTIAL'],
            due_date__lt=today,
        ).update(status='OVERDUE')
        processed_count += updated
        
        # Step 2: Send reminder emails if enabled
        if config and config.overdue_reminder_enabled:
            reminder_days = _parse_reminder_days(config.overdue_reminder_days)
            
            overdue_invoices = Invoice.objects.filter(
                tenant=tenant,
                status='OVERDUE',
            ).select_related('customer')
            
            for invoice in overdue_invoices:
                days_overdue = (today - invoice.due_date).days
                
                # Check if we should send a reminder today
                if days_overdue in reminder_days:
                    sent = _send_overdue_reminder(invoice, config, days_overdue)
                    if sent:
                        reminder_count += 1
    
    logger.info(
        f"process_overdue_invoices: Updated {processed_count} invoices to OVERDUE, "
        f"sent {reminder_count} reminders"
    )
    return {'updated': processed_count, 'reminders_sent': reminder_count}


def _parse_reminder_days(days_str):
    """Parse comma-separated days string into list of integers."""
    try:
        return [int(d.strip()) for d in days_str.split(',') if d.strip()]
    except (ValueError, AttributeError):
        return [7, 14, 30]  # default


def _send_overdue_reminder(invoice, config, days_overdue):
    """Send overdue reminder email for an invoice."""
    customer = invoice.customer
    if not customer.email:
        logger.warning(f"Cannot send reminder for invoice {invoice.invoice_number}: no customer email")
        return False
    
    # Format subject with template variables
    subject = config.overdue_reminder_subject.format(
        invoice_number=invoice.invoice_number,
        customer_name=customer.name,
        amount_due=f"${invoice.amount_due:.2f}",
        days_overdue=days_overdue,
    )
    
    # Build email body
    body = f"""Dear {customer.name},

This is a friendly reminder that invoice {invoice.invoice_number} is now {days_overdue} days overdue.

Invoice Details:
  Invoice Number: {invoice.invoice_number}
  Invoice Date: {invoice.invoice_date.strftime('%B %d, %Y')}
  Due Date: {invoice.due_date.strftime('%B %d, %Y')}
  Amount Due: ${invoice.amount_due:.2f}

Please submit payment at your earliest convenience.

If you have already sent payment, please disregard this notice.

Thank you,
{config.company_name}
{config.company_phone}
"""
    
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[customer.email],
            fail_silently=False,
        )
        
        # Log that we sent a reminder
        invoice.internal_notes = (invoice.internal_notes or '') + f"\n[{timezone.now().strftime('%Y-%m-%d')}] Reminder sent ({days_overdue} days overdue)"
        invoice.save(update_fields=['internal_notes'])
        
        logger.info(f"Sent overdue reminder for invoice {invoice.invoice_number} to {customer.email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send reminder for invoice {invoice.invoice_number}: {e}")
        return False


# =============================================================================
# BATCH INVOICING
# =============================================================================

def process_batch_invoices():
    """
    Scheduled task to generate batch invoices for fleet customers.
    
    Runs based on BillingConfig.batch_invoice_frequency:
    - weekly: runs on configured day of week
    - biweekly: runs every other week
    - monthly: runs on configured day of month
    
    Only processes customers with invoice_preference='batch'.
    """
    today = timezone.now().date()
    invoices_created = 0
    
    tenants = Tenant.objects.filter(is_active=True)
    
    for tenant in tenants:
        try:
            config = BillingConfig.get_for_tenant(tenant)
        except Exception:
            continue
        
        if config.batch_invoice_frequency == 'disabled':
            continue
        
        # Check if today is the right day to run
        if not _should_run_batch_today(config, today):
            continue
        
        # Find customers with batch preference
        batch_customers = Customer.objects.filter(
            tenant=tenant,
        ).filter(
            id__in=CustomerRepairPreference.objects.filter(
                invoice_preference='batch'
            ).values_list('customer_id', flat=True)
        )
        
        for customer in batch_customers:
            invoice = _create_batch_invoice(tenant, customer, config)
            if invoice:
                invoices_created += 1
    
    logger.info(f"process_batch_invoices: Created {invoices_created} batch invoices")
    return {'invoices_created': invoices_created}


def _should_run_batch_today(config, today):
    """Check if batch invoicing should run today based on config."""
    if config.batch_invoice_frequency == 'weekly':
        return today.weekday() == config.batch_invoice_day
    
    elif config.batch_invoice_frequency == 'biweekly':
        # Run every other week (even week numbers)
        week_num = today.isocalendar()[1]
        return today.weekday() == config.batch_invoice_day and week_num % 2 == 0
    
    elif config.batch_invoice_frequency == 'monthly':
        return today.day == config.batch_invoice_day
    
    return False


def _create_batch_invoice(tenant, customer, config):
    """
    Create a batch invoice for a customer's uninvoiced repairs.
    
    Returns the created Invoice or None if no uninvoiced repairs.
    """
    # Get uninvoiced repairs for this customer
    uninvoiced_repairs = Repair.objects.filter(
        tenant=tenant,
        customer=customer,
        queue_status='COMPLETED',
        skip_invoicing=False,
    ).exclude(
        id__in=InvoiceLineItem.objects.filter(
            repair__isnull=False
        ).values_list('repair_id', flat=True)
    )
    
    # Get uninvoiced replacements too
    invoiced_replacement_ids = InvoiceLineItem.objects.filter(
        replacement__isnull=False,
        invoice__tenant=tenant,
        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID'],
    ).values_list('replacement_id', flat=True)
    uninvoiced_replacements = Replacement.objects.filter(
        tenant=tenant,
        customer=customer,
        queue_status='COMPLETED',
    ).exclude(id__in=invoiced_replacement_ids)
    
    repairs_list = list(uninvoiced_repairs)
    replacements_list = list(uninvoiced_replacements)
    
    if not repairs_list and not replacements_list:
        return None
    
    try:
        with transaction.atomic():
            # Calculate totals
            subtotal = Decimal('0.00')
            
            # Create invoice
            invoice_number = _generate_invoice_number(tenant, config)
            due_date = _calculate_due_date(config)
            
            invoice = Invoice.objects.create(
                tenant=tenant,
                customer=customer,
                invoice_number=invoice_number,
                invoice_date=timezone.now().date(),
                due_date=due_date,
                payment_terms=config.default_payment_terms,
                status='DRAFT' if not config.batch_invoice_auto_send else 'SENT',
                notes=f'Batch invoice for {len(repairs_list)} repairs and {len(replacements_list)} replacements',
            )
            
            # Add repair line items
            for repair in repairs_list:
                amount = repair.cost or Decimal('0.00')
                subtotal += amount
                
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    repair=repair,
                    description=f"Windshield Repair - {repair.damage_type} - Unit {repair.unit_number or 'N/A'}",
                    quantity=1,
                    unit_price=amount,
                    amount=amount,
                    repair_date=repair.service_date,
                    unit_number=repair.unit_number or '',
                )
            
            # Add replacement line items
            for replacement in replacements_list:
                amount = replacement.cost or Decimal('0.00')
                subtotal += amount
                
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    replacement=replacement,
                    description=f"Windshield Replacement - Unit {replacement.unit_number or 'N/A'}",
                    quantity=1,
                    unit_price=amount,
                    amount=amount,
                    repair_date=replacement.service_date,
                    unit_number=replacement.unit_number or '',
                )
            
            # Calculate tax if enabled
            tax_amount = Decimal('0.00')
            if config.tax_enabled and not customer.tax_exempt:
                tax_amount = (subtotal * config.default_tax_rate / 100).quantize(Decimal('0.01'))
            
            # Update invoice totals
            invoice.subtotal = subtotal
            invoice.tax_rate = config.default_tax_rate if config.tax_enabled else Decimal('0.00')
            invoice.tax_amount = tax_amount
            invoice.total = subtotal + tax_amount
            invoice.save()
            
            # Send if auto_send is enabled
            if config.batch_invoice_auto_send:
                invoice.sent_at = timezone.now()
                invoice.save(update_fields=['sent_at'])
                _send_batch_invoice_email(invoice, config)
            
            logger.info(f"Created batch invoice {invoice.invoice_number} for {customer.name} - ${invoice.total}")
            return invoice
            
    except Exception as e:
        logger.error(f"Failed to create batch invoice for {customer.name}: {e}")
        return None


def _generate_invoice_number(tenant, config):
    """Generate a unique invoice number."""
    prefix = config.invoice_number_prefix or 'INV'
    date_str = timezone.now().strftime('%Y%m%d')
    
    # Count existing invoices today for this tenant
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    count = Invoice.objects.filter(
        tenant=tenant,
        created_at__gte=today_start,
    ).count() + 1
    
    return f"{prefix}-{tenant.id}-{date_str}-{count:03d}"


def _calculate_due_date(config):
    """Calculate due date based on payment terms."""
    today = timezone.now().date()
    
    terms_days = {
        'COD': 0,
        'DUE_ON_RECEIPT': 0,
        'NET15': 15,
        'NET30': 30,
        'NET45': 45,
        'NET60': 60,
    }
    
    days = terms_days.get(config.default_payment_terms, config.default_due_days)
    return today + timedelta(days=days)


def _send_batch_invoice_email(invoice, config):
    """Send batch invoice email to customer."""
    customer = invoice.customer
    if not customer.email:
        return
    
    subject = f"Invoice {invoice.invoice_number} from {config.company_name}"
    body = f"""Dear {customer.name},

Please find attached your invoice for recent services.

Invoice Number: {invoice.invoice_number}
Invoice Date: {invoice.invoice_date.strftime('%B %d, %Y')}
Due Date: {invoice.due_date.strftime('%B %d, %Y')}
Total Amount: ${invoice.total:.2f}

Thank you for your business!

{config.company_name}
{config.company_phone}
{config.company_email}
"""
    
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[customer.email],
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"Failed to send batch invoice email for {invoice.invoice_number}: {e}")


# =============================================================================
# AGING REPORT
# =============================================================================

def generate_aging_report(tenant_id=None):
    """
    Generate accounts receivable aging report.
    
    Returns dict with aging buckets: current, 30, 60, 90+ days.
    Can be called for a specific tenant or all tenants.
    """
    today = timezone.now().date()
    
    if tenant_id:
        tenants = Tenant.objects.filter(id=tenant_id, is_active=True)
    else:
        tenants = Tenant.objects.filter(is_active=True)
    
    reports = {}
    
    for tenant in tenants:
        outstanding = Invoice.objects.filter(
            tenant=tenant,
            status__in=['SENT', 'PARTIAL', 'OVERDUE'],
        ).select_related('customer')
        
        buckets = {
            'current': {'count': 0, 'total': Decimal('0.00'), 'invoices': []},
            '1_30': {'count': 0, 'total': Decimal('0.00'), 'invoices': []},
            '31_60': {'count': 0, 'total': Decimal('0.00'), 'invoices': []},
            '61_90': {'count': 0, 'total': Decimal('0.00'), 'invoices': []},
            '90_plus': {'count': 0, 'total': Decimal('0.00'), 'invoices': []},
        }
        
        for inv in outstanding:
            amount_due = inv.amount_due
            days_old = (today - inv.due_date).days if inv.due_date else 0
            
            if days_old <= 0:
                bucket = 'current'
            elif days_old <= 30:
                bucket = '1_30'
            elif days_old <= 60:
                bucket = '31_60'
            elif days_old <= 90:
                bucket = '61_90'
            else:
                bucket = '90_plus'
            
            buckets[bucket]['count'] += 1
            buckets[bucket]['total'] += amount_due
            buckets[bucket]['invoices'].append({
                'invoice_number': inv.invoice_number,
                'customer': inv.customer.name,
                'amount_due': float(amount_due),
                'days_old': days_old,
            })
        
        # Calculate grand total
        grand_total = sum(b['total'] for b in buckets.values())
        
        reports[tenant.slug] = {
            'tenant_name': tenant.name,
            'buckets': {k: {'count': v['count'], 'total': float(v['total'])} for k, v in buckets.items()},
            'grand_total': float(grand_total),
            'generated_at': timezone.now().isoformat(),
        }
    
    logger.info(f"Generated aging reports for {len(reports)} tenants")
    return reports
