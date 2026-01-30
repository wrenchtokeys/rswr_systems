"""
Billing Models - Invoice and Payment tracking

Tracks:
- Invoices generated for customers
- Which repairs are on each invoice (prevents double-billing)
- Payment status and history
- Stripe integration IDs

Author: Amelia (Clawdbot AI)
"""

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
from apps.tenants.managers import TenantManager


class Invoice(models.Model):
    """
    Tracks invoices sent to customers.
    
    Workflow:
    1. DRAFT - Invoice created but not sent
    2. SENT - Invoice delivered to customer
    3. PAID - Fully paid
    4. PARTIAL - Partially paid
    5. OVERDUE - Past due date, not fully paid
    6. CANCELLED - Invoice voided
    """
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SENT', 'Sent'),
        ('PAID', 'Paid'),
        ('PARTIAL', 'Partially Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='invoices',
        null=True,  # Nullable during migration transition
        blank=True,
    )
    
    # Core fields
    invoice_number = models.CharField(max_length=50, db_index=True)
    customer = models.ForeignKey(
        'core.Customer',
        on_delete=models.PROTECT,  # Don't delete customers with invoices
        related_name='invoices'
    )
    
    # Dates
    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    
    # Amounts
    subtotal = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    total = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    
    # Status
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True
    )
    
    # Storage
    s3_key = models.CharField(
        max_length=500, blank=True,
        help_text="S3 key where PDF is stored"
    )
    
    # Stripe integration
    stripe_invoice_id = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Stripe Invoice ID if synced"
    )
    stripe_payment_intent_id = models.CharField(
        max_length=100, blank=True,
        help_text="Stripe PaymentIntent ID"
    )
    stripe_hosted_url = models.URLField(
        blank=True,
        help_text="Stripe hosted invoice URL for customer"
    )
    
    # Timestamps
    sent_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Notes
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(
        blank=True,
        help_text="Internal notes (not shown to customer)"
    )
    
    # Tenant-aware manager
    objects = TenantManager()
    
    class Meta:
        ordering = ['-invoice_date', '-created_at']
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'invoice_number'],
                name='unique_invoice_number_per_tenant',
            ),
        ]
    
    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name} - ${self.total}"
    
    @property
    def amount_due(self):
        """Amount still owed on this invoice."""
        return self.total - self.amount_paid
    
    @property
    def is_overdue(self):
        """Check if invoice is past due."""
        if self.status in ('PAID', 'CANCELLED'):
            return False
        if self.due_date and timezone.now().date() > self.due_date:
            return True
        return False
    
    def update_status(self):
        """Update status based on payments and due date."""
        if self.status == 'CANCELLED':
            return
        
        if self.amount_paid >= self.total:
            self.status = 'PAID'
            if not self.paid_at:
                self.paid_at = timezone.now()
        elif self.amount_paid > 0:
            self.status = 'PARTIAL'
        elif self.is_overdue:
            self.status = 'OVERDUE'
        # Don't change DRAFT or SENT status automatically
    
    def mark_sent(self):
        """Mark invoice as sent to customer."""
        if self.status == 'DRAFT':
            self.status = 'SENT'
            self.sent_at = timezone.now()
            self.save()
    
    def cancel(self, reason=None):
        """Cancel this invoice."""
        self.status = 'CANCELLED'
        if reason:
            self.internal_notes += f"\n[Cancelled] {reason}"
        self.save()


class InvoiceLineItem(models.Model):
    """
    Individual line items on an invoice.
    Links repairs to invoices to prevent double-billing.
    """
    
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='line_items'
    )
    
    # Link to repair (if applicable)
    repair = models.ForeignKey(
        'technician_portal.Repair',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='invoice_line_items',
        help_text="The repair this line item is for. PROTECT prevents deleting invoiced repairs."
    )
    
    # Line item details
    description = models.CharField(max_length=500)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Metadata
    repair_date = models.DateField(null=True, blank=True)
    unit_number = models.CharField(max_length=50, blank=True)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.description} - ${self.amount}"
    
    def save(self, *args, **kwargs):
        # Auto-calculate amount if not set
        if not self.amount:
            self.amount = (self.unit_price * self.quantity) - self.discount
        super().save(*args, **kwargs)


class Payment(models.Model):
    """
    Tracks payments received for invoices.
    Supports multiple payment methods including Stripe and manual entry.
    """
    
    PAYMENT_METHOD_CHOICES = [
        ('STRIPE', 'Stripe (Online)'),
        ('CHECK', 'Check'),
        ('CASH', 'Cash'),
        ('WIRE', 'Wire Transfer'),
        ('ACH', 'ACH Transfer'),
        ('CREDIT_CARD', 'Credit Card (Manual)'),
        ('OTHER', 'Other'),
    ]
    
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    
    # Payment details
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default='OTHER'
    )
    
    # Reference info
    reference_number = models.CharField(
        max_length=100, blank=True,
        help_text="Check number, transaction ID, etc."
    )
    stripe_payment_id = models.CharField(
        max_length=100, blank=True,
        help_text="Stripe Payment ID if paid via Stripe"
    )
    stripe_charge_id = models.CharField(
        max_length=100, blank=True,
        help_text="Stripe Charge ID"
    )
    
    # Metadata
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="User who recorded this payment"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-payment_date', '-created_at']
    
    def __str__(self):
        return f"${self.amount} on {self.invoice.invoice_number} via {self.get_payment_method_display()}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update invoice payment total and status
        self._update_invoice_totals()
    
    def _update_invoice_totals(self):
        """Update the invoice's amount_paid and status."""
        invoice = self.invoice
        total_paid = invoice.payments.aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0.00')
        
        invoice.amount_paid = total_paid
        invoice.update_status()
        invoice.save()
