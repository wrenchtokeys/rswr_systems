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
    today = timezone.localdate()
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

                # C3: tier-based instead of exact-day-match. The old
                # `days_overdue in reminder_days` had two failure modes:
                # running the command twice in a day double-emailed the
                # customer, and a cron miss on the exact day an invoice hit
                # a tier meant that tier was NEVER sent. Now: send when the
                # invoice has crossed a tier that hasn't been sent yet
                # (tracked in last_reminder_days_overdue), at most one
                # reminder (the highest crossed tier) per run.
                last_sent_tier = (
                    invoice.last_reminder_days_overdue
                    if invoice.last_reminder_days_overdue is not None else -1
                )
                eligible_tiers = [
                    t for t in reminder_days
                    if days_overdue >= t and t > last_sent_tier
                ]
                if eligible_tiers:
                    tier = max(eligible_tiers)
                    try:
                        sent = _send_overdue_reminder(invoice, config, days_overdue)
                        if sent:
                            invoice.last_reminder_days_overdue = tier
                            invoice.save(update_fields=['last_reminder_days_overdue'])
                            reminder_count += 1
                    except Exception as inv_exc:
                        # Log and continue — one broken invoice/template must not
                        # prevent reminders for the rest of the tenant's invoices.
                        logger.error(
                            f"_send_overdue_reminder failed for invoice "
                            f"{invoice.invoice_number} (id={invoice.id}): {inv_exc}"
                        )
    
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

    # Prefer billing_email from CustomerRepairPreference when set — fleet customers
    # often have a dedicated AP email that is different from their general contact
    # email.  All manual invoice-send paths already do this; the automated reminder
    # task must be consistent.  (CODE-127)
    recipient_email = None
    try:
        prefs = customer.repair_preferences
        recipient_email = prefs.billing_email or customer.email
    except Exception:
        recipient_email = customer.email

    if not recipient_email:
        logger.warning(f"Cannot send reminder for invoice {invoice.invoice_number}: no customer email")
        return False
    
    # Format subject with all documented template variables.
    # Use a safe mapping so that unknown placeholders in a custom subject
    # template produce an empty string rather than a KeyError that would
    # abort the entire reminder loop.  (CODE-117)
    _company_name = config.company_name or (invoice.tenant.name if invoice.tenant else '')
    _due_date_str = invoice.due_date.strftime('%m/%d/%Y') if invoice.due_date else ''
    try:
        subject = config.overdue_reminder_subject.format(
            invoice_number=invoice.invoice_number,
            customer_name=customer.name,
            amount_due=f"${invoice.amount_due:.2f}",
            total=f"${invoice.total:.2f}",
            days_overdue=days_overdue,
            due_date=_due_date_str,
            company_name=_company_name,
        )
    except (KeyError, ValueError):
        # Malformed template — fall back to the system default subject so we
        # still send the reminder rather than silently dropping it.
        logger.warning(
            f"Malformed overdue_reminder_subject template for tenant "
            f"{invoice.tenant_id}: {config.overdue_reminder_subject!r}. "
            f"Using default subject."
        )
        subject = f"Reminder: Invoice #{invoice.invoice_number} is overdue"
    
    # Generate public payment link
    # NOTE: pay_url must be initialised to None BEFORE the try block.
    # If the import or generate_payment_token call raises, pay_url would
    # otherwise be undefined and the send_branded_email call below would
    # raise NameError, silently aborting the reminder. (CODE-179)
    pay_url = None
    pay_link_text = ''
    try:
        from apps.billing.pay_links import public_pay_url
        # Pay link only when the shop can actually take online payments
        # (active Stripe Connect) — otherwise the button dead-ends.
        pay_url = public_pay_url(invoice)
        if pay_url:
            pay_link_text = f"\nPay online: {pay_url}\n"
    except Exception:
        pass

    _company_name = config.company_name or (invoice.tenant.name if invoice.tenant else '')
    _company_phone = config.company_phone or (invoice.tenant.business_phone if invoice.tenant else '')

    # Build email body
    body = f"""Dear {customer.name},

This is a friendly reminder that invoice {invoice.invoice_number} is now {days_overdue} days overdue.

Invoice Details:
  Invoice Number: {invoice.invoice_number}
  Invoice Date: {invoice.invoice_date.strftime('%B %d, %Y')}
  Due Date: {invoice.due_date.strftime('%B %d, %Y')}
  Amount Due: ${invoice.amount_due:.2f}
{pay_link_text}
Please submit payment at your earliest convenience.

If you have already sent payment, please disregard this notice.

Thank you,
{_company_name}
{_company_phone}
"""
    
    try:
        from core.email_utils import send_branded_email
        send_branded_email(
            subject=subject,
            recipient_list=[recipient_email],
            headline=f'Payment Reminder — Invoice {invoice.invoice_number}',
            body_paragraphs=[
                f"Dear {customer.name},",
                f"This is a friendly reminder that invoice {invoice.invoice_number} is now {days_overdue} days overdue.",
                "If you have already sent payment, please disregard this notice.",
            ],
            detail_rows=[
                ('Invoice #', invoice.invoice_number),
                ('Invoice Date', invoice.invoice_date.strftime('%B %d, %Y')),
                ('Due Date', invoice.due_date.strftime('%B %d, %Y')),
                ('Amount Due', f'${invoice.amount_due:.2f}'),
            ],
            button_text='Pay Now' if pay_url else None,
            button_url=pay_url if pay_url else None,
            tenant=invoice.tenant,
            plain_text=body,
            headers={
                'X-SES-MESSAGE-TAGS': f'rs_invoice_id={invoice.id}',
                'List-Unsubscribe': f'<mailto:{settings.DEFAULT_FROM_EMAIL}?subject=unsubscribe>',
            },
        )
        
        # Log that we sent a reminder
        invoice.internal_notes = (invoice.internal_notes or '') + f"\n[{timezone.now().strftime('%Y-%m-%d')}] Reminder sent ({days_overdue} days overdue)"
        invoice.save(update_fields=['internal_notes'])
        
        logger.info(f"Sent overdue reminder for invoice {invoice.invoice_number} to {recipient_email}")
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
    today = timezone.localdate()
    invoices_created = 0
    
    tenants = Tenant.objects.filter(is_active=True)
    
    for tenant in tenants:
        try:
            config = BillingConfig.get_for_tenant(tenant)
        except Exception:
            continue
        
        if config.batch_invoice_frequency == 'disabled':
            continue
        
        is_shop_day = _should_run_batch_today(config, today)
        
        # Find all batch-preference customers for this tenant (CODE-203 scoping).
        batch_prefs = CustomerRepairPreference.objects.filter(
            invoice_preference='batch',
            customer__tenant=tenant,
        )
        
        # Per-customer batch_invoice_day overrides only apply to monthly frequency.
        # Weekly/biweekly use weekday (0-6) which is a different domain than
        # batch_invoice_day (day-of-month 1-28), so overrides are meaningless.
        #
        # Monthly: customers WITH override → invoice when THEIR day matches today.
        #          customers WITHOUT override → invoice on shop's batch day.
        # Weekly/biweekly: all batch customers invoiced on shop day. (CODE-225)
        if config.batch_invoice_frequency == 'monthly':
            override_customer_ids = batch_prefs.filter(
                batch_invoice_day__isnull=False,
                batch_invoice_day=today.day,
            ).values_list('customer_id', flat=True)
            
            default_customer_ids = batch_prefs.filter(
                batch_invoice_day__isnull=True,
            ).values_list('customer_id', flat=True) if is_shop_day else []
            
            from itertools import chain
            eligible_ids = set(chain(override_customer_ids, default_customer_ids))
        else:
            # Weekly/biweekly — all batch customers on shop day, ignore overrides
            if not is_shop_day:
                continue
            eligible_ids = set(batch_prefs.values_list('customer_id', flat=True))
        
        if not eligible_ids:
            continue
        
        batch_customers = Customer.objects.filter(
            tenant=tenant,
            id__in=eligible_ids,
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
        # Run every other week, anchored to a fixed epoch Monday. ISO week
        # parity (isocalendar()[1] % 2) breaks across 53-week years: week 53
        # is odd and week 1 of the next year is also odd, producing either
        # two consecutive runs or a three-week gap at the boundary. (D4)
        from datetime import date as _date
        _BIWEEKLY_EPOCH = _date(2024, 1, 1)  # a Monday
        weeks_since_epoch = (today - _BIWEEKLY_EPOCH).days // 7
        return today.weekday() == config.batch_invoice_day and weeks_since_epoch % 2 == 0
    
    elif config.batch_invoice_frequency == 'monthly':
        return today.day == config.batch_invoice_day
    
    return False


def _create_batch_invoice(tenant, customer, config):
    """
    Create a batch invoice for a customer's uninvoiced repairs.
    
    Returns the created Invoice or None if no uninvoiced repairs.
    """
    # Get uninvoiced repairs for this customer.
    # NOTE: The repair exclusion subquery MUST scope to invoice__tenant=tenant.
    # Without it, a repair from Tenant A with the same integer PK as a repair
    # from Tenant B could be incorrectly excluded, AND the subquery forces a
    # full-table scan of all InvoiceLineItems across all tenants. (CODE-036)
    invoiced_repair_ids = InvoiceLineItem.objects.filter(
        repair__isnull=False,
        invoice__tenant=tenant,
        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
    ).values_list('repair_id', flat=True)
    uninvoiced_repairs = Repair.objects.filter(
        tenant=tenant,
        customer=customer,
        queue_status='COMPLETED',
        skip_invoicing=False,
    ).exclude(id__in=invoiced_repair_ids)
    
    # Get uninvoiced replacements too
    invoiced_replacement_ids = InvoiceLineItem.objects.filter(
        replacement__isnull=False,
        invoice__tenant=tenant,
        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE'], invoice__deleted_at__isnull=True,
    ).values_list('replacement_id', flat=True)
    uninvoiced_replacements = Replacement.objects.filter(
        tenant=tenant,
        customer=customer,
        queue_status='COMPLETED',
        skip_invoicing=False,
    ).exclude(id__in=invoiced_replacement_ids)
    
    repairs_list = list(uninvoiced_repairs)
    replacements_list = list(uninvoiced_replacements)
    
    if not repairs_list and not replacements_list:
        return None
    
    try:
        with transaction.atomic():
            # Calculate totals
            subtotal = Decimal('0.00')

            # Resolve effective payment terms: customer-specific override wins
            # over the shop-level BillingConfig default.  The
            # CustomerRepairPreference.payment_terms field was added in
            # migration 0013 but the batch invoice task was never updated to
            # read it, so customer-specific terms were silently ignored and all
            # batch invoices used the shop default.  (CODE-219)
            effective_payment_terms = config.default_payment_terms
            try:
                customer_prefs = customer.repair_preferences
                if customer_prefs.payment_terms:
                    effective_payment_terms = customer_prefs.payment_terms
            except Exception:
                pass  # No preferences set — use shop default

            # Create invoice
            invoice_number = _generate_invoice_number(tenant, config)
            due_date = _calculate_due_date(config, payment_terms_override=effective_payment_terms)
            
            # Always create as DRAFT — status is promoted to SENT only AFTER
            # email delivery is confirmed (see CODE-095 / AGENTS.md gotcha).
            # Setting 'SENT' here and then failing the email would leave the
            # invoice permanently SENT with the customer never having received it.
            invoice = Invoice.objects.create(
                tenant=tenant,
                customer=customer,
                invoice_number=invoice_number,
                invoice_date=timezone.localdate(),
                due_date=due_date,
                payment_terms=effective_payment_terms,
                status='DRAFT',
                notes=f'Batch invoice for {len(repairs_list)} repairs and {len(replacements_list)} replacements',
            )
            
            # Add repair line items
            # CODE-122: Use get_discounted_cost() so reward-based discounts
            # (REPAIR_DISCOUNT, FREE_SERVICE redemptions) are reflected in the
            # line item amount and the invoice discount/subtotal totals.
            # Previously repair.cost was used directly, causing customers with
            # earned rewards to be overbilled on all batch invoices.
            total_discount = Decimal('0.00')
            taxable_base = Decimal('0.00')
            for repair in repairs_list:
                discounted = repair.get_discounted_cost()
                original = discounted['original_cost'] or Decimal('0.00')
                final_amt = discounted['final_cost'] or Decimal('0.00')
                savings = discounted['savings'] or Decimal('0.00')

                pricing_info = repair.get_progressive_pricing_info()
                if pricing_info['is_discounted']:
                    prog_savings = pricing_info['base_rate'] - pricing_info['actual_cost']
                    unit_price = pricing_info['base_rate']
                    total_disc = prog_savings + savings
                    amount = unit_price - total_disc
                else:
                    unit_price = original
                    total_disc = savings
                    amount = final_amt

                subtotal += unit_price
                total_discount += total_disc
                if not repair.no_tax:
                    taxable_base += amount

                description = repair.get_invoice_description()
                if pricing_info['is_discounted']:
                    description += " [multi-break rate]"

                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    repair=repair,
                    description=description,
                    quantity=1,
                    unit_price=unit_price,
                    discount=total_disc,
                    amount=amount,
                    repair_date=repair.service_date,
                    unit_number=repair.get_vehicle_identifier(),
                    taxable=not repair.no_tax,
                )

                from apps.billing.services.invoice_sync import create_charge_lines
                for charge_line in create_charge_lines(invoice, repair):
                    subtotal += charge_line.unit_price
                    if charge_line.taxable:
                        taxable_base += charge_line.amount

            # Add replacement line items
            for replacement in replacements_list:
                amount = replacement.cost or Decimal('0.00')
                subtotal += amount
                if not replacement.no_tax:
                    taxable_base += amount

                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    replacement=replacement,
                    description=replacement.get_invoice_description(),
                    quantity=1,
                    unit_price=amount,
                    amount=amount,
                    repair_date=replacement.service_date,
                    unit_number=replacement.get_vehicle_identifier(),
                    taxable=not replacement.no_tax,
                )

                from apps.billing.services.invoice_sync import create_charge_lines
                for charge_line in create_charge_lines(invoice, replacement):
                    subtotal += charge_line.unit_price
                    if charge_line.taxable:
                        taxable_base += charge_line.amount

            # Calculate tax via TaxService (single source of truth for whether
            # tax applies + per-tenant rate with component breakdown, CODE-104).
            #
            # CODE-122: Tax is calculated on the discounted net so customers are
            # not charged tax on reward savings they have already earned. Jobs
            # flagged no_tax (cash deals) are excluded from the taxable base but
            # still count toward the invoice total.
            from apps.billing.services.tax_service import TaxService
            tax_svc = TaxService(tenant=tenant)
            discounted_subtotal = subtotal - total_discount
            tax_result = tax_svc.calculate_tax(subtotal=taxable_base, customer=customer)
            invoice.subtotal = subtotal
            invoice.discount = total_discount
            invoice.tax_rate = tax_result['rate']
            invoice.state_tax_rate = tax_result['state_rate']
            invoice.county_tax_rate = tax_result['county_rate']
            invoice.city_tax_rate = tax_result['city_rate']
            invoice.special_tax_rate = tax_result['special_rate']
            invoice.tax_amount = tax_result['amount']
            invoice.total = discounted_subtotal + tax_result['amount']
            invoice.save()
            
            # Send if auto_send is enabled — only mark SENT after email confirmed.
            # (CODE-095: same pattern as CODE-094 for AutoInvoiceService.
            # Do NOT stamp sent_at or set status='SENT' before the email attempt.)
            if config.batch_invoice_auto_send:
                email_sent = _send_batch_invoice_email(invoice, config)
                if email_sent:
                    from apps.billing.services.invoice_send_service import InvoiceSendService
                    invoice.record_email_sent(InvoiceSendService.resolve_recipient(invoice.customer))
                else:
                    # Email failed — leave as DRAFT so the shop owner can see it
                    # and retry manually. Log at WARNING level for visibility.
                    logger.warning(
                        f"Batch invoice {invoice.invoice_number} for {customer.name} "
                        f"created as DRAFT — auto-send email delivery failed. "
                        f"Owner must send manually."
                    )
            
            logger.info(f"Created batch invoice {invoice.invoice_number} for {customer.name} - ${invoice.total}")
            return invoice
            
    except Exception as e:
        logger.error(f"Failed to create batch invoice for {customer.name}: {e}")
        return None


def _generate_invoice_number(tenant, config):
    """Sequential per-tenant invoice number: "{prefix}-{counter}".

    Delegates to BillingConfig.allocate_invoice_number, which locks the config
    row (concurrency-safe — replaces the count-based scheme from CODE-036) and
    advances the shop's next_invoice_number counter.
    """
    from apps.billing.models import BillingConfig
    return BillingConfig.allocate_invoice_number(tenant)


def _calculate_due_date(config, payment_terms_override=None):
    """Calculate due date based on payment terms.

    Args:
        config: BillingConfig instance for the tenant (used as fallback).
        payment_terms_override: If provided, this term code takes priority over
            ``config.default_payment_terms``.  Allows customer-specific terms
            to affect the due date (CODE-219).
    """
    today = timezone.localdate()
    
    terms_days = {
        'COD': 0,
        'DUE_ON_RECEIPT': 0,
        'NET15': 15,
        'NET30': 30,
        'NET45': 45,
        'NET60': 60,
    }

    effective_terms = payment_terms_override or config.default_payment_terms
    days = terms_days.get(effective_terms, config.default_due_days)
    return today + timedelta(days=days)


def _send_batch_invoice_email(invoice, config):
    """Send the batch invoice email through the one invoice-email path.

    This used to be a separate invoice email: send_branded_email with four
    detail rows, no line items, and a default body that said "Please find
    attached your invoice" while attaching nothing. InvoiceEmailService
    sends the same receipt-shaped email as every other invoice path — line
    items grouped per vehicle, amount-first, the shop's CODE-119 template
    reaching both halves — and attaches the PDF it promises.

    Recipient resolution stays here (CODE-139): billing_email over
    customer.email, so a fleet AP-only account with no customer.email
    still gets its invoice. `config` is unused now but kept in the
    signature — the service resolves the same BillingConfig itself.

    Returns:
        bool: True if email was sent successfully, False otherwise.
    """
    customer = invoice.customer

    recipient_email = None
    try:
        prefs = customer.repair_preferences
        recipient_email = prefs.billing_email or customer.email
    except Exception:
        recipient_email = customer.email

    if not recipient_email:
        logger.warning(
            f"Cannot auto-send batch invoice {invoice.invoice_number}: "
            f"customer {customer.name!r} has no email address."
        )
        return False

    from apps.billing.services.invoice_email_service import InvoiceEmailService
    try:
        service = InvoiceEmailService(tenant=invoice.tenant)
        success, message = service.send_invoice_email(
            customer_id=customer.id,
            recipient_email=recipient_email,
            invoice=invoice,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
        )
    except Exception as e:
        logger.error(
            f"Failed to send batch invoice email for {invoice.invoice_number}: {e}"
        )
        return False

    if not success:
        logger.warning(
            f"Batch invoice email for {invoice.invoice_number} not sent: {message}"
        )
    return success


# =============================================================================
# AGING REPORT
# =============================================================================

def generate_aging_report(tenant_id=None):
    """
    Generate accounts receivable aging report.
    
    Returns dict with aging buckets: current, 30, 60, 90+ days.
    Can be called for a specific tenant or all tenants.
    """
    today = timezone.localdate()
    
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
