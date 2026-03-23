"""
Invoice Tracking Service - Manages invoice lifecycle and prevents double-billing.

This service:
1. Creates Invoice records when PDFs are generated
2. Tracks which repairs are invoiced (prevents double-billing)
3. Manages payment recording
4. Handles invoice status updates

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum

from apps.billing.models import Invoice, InvoiceLineItem, Payment

logger = logging.getLogger(__name__)


class InvoiceTrackingService:
    """
    Handles invoice creation, tracking, and payment processing.
    All operations scoped to a tenant.
    """
    
    DEFAULT_PAYMENT_TERMS_DAYS = 30
    
    def __init__(self, tenant=None):
        self.tenant = tenant
        self._billing_config = None
    
    @property
    def billing_config(self):
        """Lazy-load BillingConfig for this tenant."""
        if self._billing_config is None:
            try:
                from apps.billing.models import BillingConfig
                if self.tenant:
                    self._billing_config = BillingConfig.get_for_tenant(self.tenant)
            except Exception:
                self._billing_config = None
        return self._billing_config
    
    def create_invoice_from_repairs(self, customer, repairs, invoice_number=None, 
                                     due_days=None, s3_key=None, auto_send=False,
                                     payment_terms=None):
        """
        Create a tracked Invoice from a list of repairs.
        
        Args:
            customer: Customer instance
            repairs: List of Repair instances to invoice
            invoice_number: Optional invoice number (auto-generated if not provided)
            due_days: Days until due (default: 30)
            s3_key: S3 key where PDF is stored
            auto_send: Deprecated – ignored. Invoice is always created as DRAFT.
                       Callers must mark SENT only after email delivery is confirmed.
                       (See AGENTS.md gotcha: "Don't mark invoices SENT before
                       confirming email delivery")
            payment_terms: Override payment terms for this invoice (e.g. 'NET30').
                          If None, uses BillingConfig.default_payment_terms.
            
        Returns:
            Invoice instance
        """
        if not repairs:
            raise ValueError("No repairs provided for invoice")
        
        # Check for already-invoiced repairs
        already_invoiced = []
        for repair in repairs:
            if repair.invoice_line_items.filter(
                invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID']
            ).exists():
                already_invoiced.append(repair.id)
        
        if already_invoiced:
            raise ValueError(
                f"Repairs already invoiced: {already_invoiced}. "
                "Cannot bill the same repair twice."
            )
        
        # Generate invoice number if not provided
        if not invoice_number:
            invoice_number = self._generate_invoice_number(customer)
        
        # Get payment terms — caller override takes priority over BillingConfig
        if payment_terms is None:
            payment_terms = 'COD'
            if self.billing_config:
                payment_terms = self.billing_config.default_payment_terms
                # Use config-based due days if caller didn't specify
                if due_days is None:
                    due_days = self.billing_config.due_days_for_terms
        else:
            # Caller specified payment_terms — derive due_days from it if not
            # explicitly provided.  (CODE-153)
            if due_days is None:
                terms_days = {
                    'COD': 0,
                    'DUE_ON_RECEIPT': 0,
                    'NET15': 15,
                    'NET30': 30,
                    'NET45': 45,
                    'NET60': 60,
                }
                due_days = terms_days.get(payment_terms, 0)
        
        due_days = due_days or 0
        due_date = timezone.now().date() + timedelta(days=due_days) if due_days > 0 else timezone.now().date()
        
        with transaction.atomic():
            # Create invoice
            invoice = Invoice.objects.create(
                tenant=self.tenant or customer.tenant,
                invoice_number=invoice_number,
                customer=customer,
                invoice_date=timezone.now().date(),
                due_date=due_date,
                payment_terms=payment_terms,
                status='DRAFT',
                sent_at=None,
                s3_key=s3_key or '',
            )
            
            # Create line items for each repair
            subtotal = Decimal('0.00')
            total_discount = Decimal('0.00')
            
            for repair in repairs:
                discounted = repair.get_discounted_cost()
                
                line_item = InvoiceLineItem.objects.create(
                    invoice=invoice,
                    repair=repair,
                    description=f"Windshield repair - Unit #{repair.unit_number} - {repair.get_damage_type_display() or 'Repair'}",
                    quantity=1,
                    unit_price=discounted['original_cost'],
                    discount=discounted['savings'],
                    amount=discounted['final_cost'],
                    repair_date=repair.repair_date.date() if repair.repair_date else None,
                    unit_number=repair.unit_number,
                )
                
                subtotal += discounted['original_cost']
                total_discount += discounted['savings']
            
            # Update invoice totals
            invoice.subtotal = subtotal
            invoice.discount = total_discount
            invoice.total = subtotal - total_discount  # default before tax

            # Apply sales tax (if enabled)
            try:
                from apps.billing.services.tax_service import TaxService
                tax_svc = TaxService(tenant=invoice.tenant)
                tax_result = tax_svc.apply_tax_to_invoice(invoice)
                logger.info(
                    f"Tax for {invoice.invoice_number}: enabled={tax_result['enabled']}, "
                    f"rate={tax_result['rate']}%, amount=${tax_result['amount']}, "
                    f"exempt={tax_result['exempt']}"
                )
            except Exception as e:
                import traceback
                logger.error(f"TAX CALCULATION FAILED: {e}\n{traceback.format_exc()}")
                # Continue with $0 tax rather than blocking invoice creation

            invoice.save()
            
            logger.info(
                f"Created invoice {invoice_number} for {customer.name}: "
                f"{len(repairs)} repairs, ${invoice.total}"
            )
            
            return invoice
    
    def get_uninvoiced_repairs(self, customer, completed_only=True):
        """
        Get repairs that haven't been invoiced yet.
        
        Args:
            customer: Customer instance
            completed_only: Only return COMPLETED repairs (default: True)
            
        Returns:
            QuerySet of Repair instances
        """
        from apps.technician_portal.models import Repair
        
        # Get repairs for this customer (tenant-scoped)
        repairs = Repair.objects.filter(customer=customer)
        if self.tenant:
            repairs = repairs.filter(tenant=self.tenant)
        
        if completed_only:
            repairs = repairs.filter(queue_status='COMPLETED')
        
        # Exclude repairs marked as "skip invoicing" (legacy paid work)
        repairs = repairs.filter(skip_invoicing=False)
        
        # Exclude repairs that are on active invoices
        # (DRAFT, SENT, PARTIAL, PAID - but not CANCELLED)
        tenant = self.tenant or customer.tenant
        invoiced_repair_ids = InvoiceLineItem.objects.filter(
            repair__isnull=False,
            invoice__tenant=tenant,
            invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID']
        ).values_list('repair_id', flat=True)
        
        repairs = repairs.exclude(id__in=invoiced_repair_ids)
        
        return repairs.order_by('-service_date')
    
    def record_payment(self, invoice, amount, payment_method='OTHER',
                       reference_number='', notes='', recorded_by=None,
                       stripe_payment_id='', payment_date=None):
        """
        Record a payment against an invoice.
        
        Args:
            invoice: Invoice instance
            amount: Payment amount (Decimal)
            payment_method: One of Payment.PAYMENT_METHOD_CHOICES
            reference_number: Check number, transaction ID, etc.
            notes: Optional notes
            recorded_by: User who recorded the payment
            stripe_payment_id: Stripe payment ID if applicable
            payment_date: Date of payment (default: today)
            
        Returns:
            Payment instance
        """
        if invoice.status == 'CANCELLED':
            raise ValueError("Cannot record payment on cancelled invoice")
        
        payment = Payment.objects.create(
            invoice=invoice,
            amount=Decimal(str(amount)),
            payment_date=payment_date or timezone.now().date(),
            payment_method=payment_method,
            reference_number=reference_number,
            notes=notes,
            recorded_by=recorded_by,
            stripe_payment_id=stripe_payment_id,
        )
        
        logger.info(
            f"Payment recorded: ${amount} on invoice {invoice.invoice_number} "
            f"via {payment_method}"
        )
        
        return payment
    
    def get_outstanding_invoices(self, customer=None, include_overdue_only=False):
        """
        Get invoices that haven't been fully paid.
        
        Args:
            customer: Optional customer filter
            include_overdue_only: Only return overdue invoices
            
        Returns:
            QuerySet of Invoice instances
        """
        if self.tenant:
            invoices = Invoice.objects.for_tenant(self.tenant).filter(
                status__in=['SENT', 'PARTIAL', 'OVERDUE']
            )
        else:
            # Safety: scope to customer's tenant if available, else empty
            if customer:
                invoices = Invoice.objects.filter(
                    tenant=customer.tenant,
                    status__in=['SENT', 'PARTIAL', 'OVERDUE']
                )
            else:
                invoices = Invoice.objects.none()
        
        if customer:
            invoices = invoices.filter(customer=customer)
        
        if include_overdue_only:
            invoices = invoices.filter(
                due_date__lt=timezone.now().date()
            )
        
        return invoices.order_by('due_date')
    
    def update_overdue_statuses(self):
        """
        Batch update: Mark invoices as OVERDUE if past due date.
        Run this daily via cron.
        
        Returns:
            int: Number of invoices marked overdue
        """
        today = timezone.now().date()
        
        if not self.tenant:
            logger.warning("update_overdue_statuses called without tenant — skipping")
            return 0
        qs = Invoice.objects.for_tenant(self.tenant)
        updated = qs.filter(
            status__in=['SENT', 'PARTIAL'],
            due_date__lt=today
        ).update(status='OVERDUE')
        
        if updated:
            logger.info(f"Marked {updated} invoices as OVERDUE")
        
        return updated
    
    def get_customer_balance(self, customer):
        """
        Get total outstanding balance for a customer.
        
        Returns:
            dict with total_outstanding, invoice_count, oldest_due
        """
        invoices = self.get_outstanding_invoices(customer=customer)
        
        total = Decimal('0.00')
        oldest_due = None
        
        for inv in invoices:
            total += inv.amount_due
            if inv.due_date:
                if oldest_due is None or inv.due_date < oldest_due:
                    oldest_due = inv.due_date
        
        return {
            'total_outstanding': total,
            'invoice_count': invoices.count(),
            'oldest_due': oldest_due,
            'invoices': list(invoices),
        }
    
    def _generate_invoice_number(self, customer):
        """Generate a unique invoice number using configurable prefix."""
        prefix = 'INV'
        if self.billing_config:
            prefix = self.billing_config.invoice_number_prefix or 'INV'
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        return f"{prefix}-{customer.id}-{timestamp}"
