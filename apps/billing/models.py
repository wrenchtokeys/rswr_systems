"""
Billing Models - Invoice and Payment tracking

Tracks:
- Invoices generated for customers
- Which repairs are on each invoice (prevents double-billing)
- Payment status and history
- Stripe integration IDs
- Billing configuration (company address, payment terms)
- Sales tax rates and per-invoice tax calculation

Author: Amelia (Clawdbot AI)
"""

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.tenants.managers import TenantManager


# =============================================================================
# BILLING CONFIGURATION (Per-Tenant)
# =============================================================================

class BillingConfig(models.Model):
    """
    Per-tenant billing configuration — controls company info on invoices,
    default payment terms, and other billing defaults for each shop.

    Each Tenant has exactly one BillingConfig (OneToOne). Use
    BillingConfig.get_for_tenant(tenant) to fetch or create it.

    Editable via Admin Dashboard → Billing → Billing Configuration.
    """

    PAYMENT_TERMS_CHOICES = [
        ('COD', 'Cash on Delivery (COD)'),
        ('DUE_ON_RECEIPT', 'Due on Receipt'),
        ('NET15', 'Net 15'),
        ('NET30', 'Net 30'),
        ('NET45', 'Net 45'),
        ('NET60', 'Net 60'),
    ]

    # Multi-tenant: each shop gets its own config
    tenant = models.OneToOneField(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='billing_config',
    )

    # === COMPANY INFO (shown on invoices) ===
    company_name = models.CharField(
        max_length=200,
        default='',
        blank=True,
        help_text='Company name displayed on invoices (defaults to shop name if blank)',
    )
    company_address = models.CharField(
        max_length=200,
        blank=True,
        help_text='Street address (e.g., 123 Main St)',
    )
    company_city = models.CharField(
        max_length=100,
        blank=True,
        help_text='City',
    )
    company_state = models.CharField(
        max_length=50,
        blank=True,
        help_text='State (e.g., TX)',
    )
    company_zip = models.CharField(
        max_length=20,
        blank=True,
        help_text='ZIP / Postal code',
    )
    company_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text='Phone number shown on invoices',
    )
    company_email = models.EmailField(
        blank=True,
        help_text='Email shown on invoices',
    )
    company_website = models.URLField(
        blank=True,
        help_text='Website URL shown on invoices',
    )

    # === DEFAULT PAYMENT TERMS ===
    default_payment_terms = models.CharField(
        max_length=20,
        choices=PAYMENT_TERMS_CHOICES,
        default='COD',
        help_text='Default payment terms for new invoices',
    )
    default_due_days = models.PositiveIntegerField(
        default=0,
        help_text='Default days until invoice is due (0 = due on receipt/COD). '
                  'Overridden by payment terms if set (e.g., NET30 = 30 days).',
    )

    # === INVOICE DEFAULTS ===
    invoice_footer_note = models.TextField(
        blank=True,
        default='Thank you for your business!',
        help_text='Footer text printed at the bottom of every invoice',
    )
    invoice_number_prefix = models.CharField(
        max_length=20,
        default='INV',
        help_text='Prefix for auto-generated invoice numbers (e.g., INV → INV-1-20260131...)',
    )

    # === SALES TAX ===
    tax_enabled = models.BooleanField(
        default=False,
        help_text='Enable sales tax calculation on invoices. When disabled, all invoices have zero tax.',
    )
    default_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text='Combined tax rate (auto-calculated from components). Percentage, e.g. 9.500 = 9.5%.',
    )
    state_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('6.500'),
        help_text='State sales tax rate (percentage)',
    )
    county_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text='County sales tax rate (percentage)',
    )
    city_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text='City sales tax rate (percentage)',
    )
    special_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text='Special district tax rate (percentage)',
    )

    # === AUTOMATION: OVERDUE REMINDERS ===
    overdue_reminder_enabled = models.BooleanField(
        default=False,
        help_text='Enable automatic reminder emails for overdue invoices',
    )
    overdue_reminder_days = models.CharField(
        max_length=50,
        default='7,14,30',
        help_text='Days after due date to send reminders (comma-separated, e.g., "7,14,30")',
    )
    overdue_reminder_subject = models.CharField(
        max_length=200,
        default='Reminder: Invoice #{invoice_number} is overdue',
        help_text='Email subject template. Use {invoice_number}, {customer_name}, {amount_due}, {days_overdue}',
    )
    
    # === AUTOMATION: BATCH INVOICING ===
    BATCH_FREQUENCY_CHOICES = [
        ('disabled', 'Disabled'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly'),
    ]
    batch_invoice_frequency = models.CharField(
        max_length=20,
        choices=BATCH_FREQUENCY_CHOICES,
        default='disabled',
        help_text='How often to auto-generate batch invoices for fleet customers',
    )
    batch_invoice_day = models.PositiveSmallIntegerField(
        default=1,
        help_text='Day to run batch invoicing. For weekly: 0=Mon, 6=Sun. For monthly: 1-28.',
    )
    batch_invoice_auto_send = models.BooleanField(
        default=False,
        help_text='Automatically send batch invoices via email (otherwise creates as DRAFT)',
    )

    # === METADATA ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Billing Configuration'
        verbose_name_plural = 'Billing Configurations'

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant_id else 'No Tenant'
        return f'Billing Configuration — {tenant_name}'

    def save(self, *args, **kwargs):
        # OneToOneField on tenant handles uniqueness — no manual enforcement needed
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Billing configuration cannot be deleted.')

    @classmethod
    def get_for_tenant(cls, tenant):
        """
        Get (or create with defaults) the BillingConfig for this tenant.

        On creation, auto-populates company_name from tenant.name so new shops
        don't inherit any hardcoded placeholder value.

        Args:
            tenant: Tenant instance

        Returns:
            BillingConfig instance for the given tenant
        """
        instance, created = cls.objects.get_or_create(tenant=tenant)
        if created and not instance.company_name:
            instance.company_name = tenant.name
            instance.save(update_fields=['company_name'])
        return instance

    @classmethod
    def get_instance(cls):
        """
        DEPRECATED — do not use in new code.
        Use BillingConfig.get_for_tenant(tenant) instead.
        Raises RuntimeError to surface incorrect usage quickly.
        """
        raise RuntimeError(
            "BillingConfig.get_instance() is deprecated. "
            "BillingConfig is now per-tenant. "
            "Use BillingConfig.get_for_tenant(tenant) instead."
        )

    @property
    def full_address(self):
        """Return formatted multi-line company address."""
        lines = []
        if self.company_address:
            lines.append(self.company_address)
        city_state_zip = ''
        if self.company_city:
            city_state_zip = self.company_city
        if self.company_state:
            city_state_zip += f', {self.company_state}' if city_state_zip else self.company_state
        if self.company_zip:
            city_state_zip += f' {self.company_zip}' if city_state_zip else self.company_zip
        if city_state_zip:
            lines.append(city_state_zip)
        return '\n'.join(lines)

    @property
    def due_days_for_terms(self):
        """Return the number of due days implied by payment terms."""
        terms_days = {
            'COD': 0,
            'DUE_ON_RECEIPT': 0,
            'NET15': 15,
            'NET30': 30,
            'NET45': 45,
            'NET60': 60,
        }
        return terms_days.get(self.default_payment_terms, self.default_due_days)


# =============================================================================
# INVOICE
# =============================================================================

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
    
    # Payment terms
    payment_terms = models.CharField(
        max_length=20,
        choices=BillingConfig.PAYMENT_TERMS_CHOICES,
        default='COD',
        help_text='Payment terms for this invoice',
    )
    
    # Amounts
    subtotal = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="Combined tax rate applied (percentage, e.g., 9.500 = 9.5%)"
    )
    state_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="State portion of tax rate"
    )
    county_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="County portion of tax rate"
    )
    city_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="City portion of tax rate"
    )
    special_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=3, default=Decimal('0.000'),
        help_text="Special district portion of tax rate"
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Calculated tax amount"
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
    
    # Description / Notes
    description = models.TextField(
        blank=True,
        help_text="Customer-facing description or summary for this invoice"
    )
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
            models.Index(fields=['created_at'], name='billing_invoice_created_at_idx'),
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
    Links repairs/replacements to invoices to prevent double-billing.
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
    
    # Link to replacement (if applicable)
    replacement = models.ForeignKey(
        'technician_portal.Replacement',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='invoice_line_items',
        help_text="The replacement this line item is for. PROTECT prevents deleting invoiced replacements."
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
        # Auto-calculate amount only when it has never been set.
        # Using `is None` instead of `not self.amount` so that an explicitly
        # set amount of $0.00 is preserved and not recalculated on re-save.
        if self.amount is None:
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


# =============================================================================
# TAX RATES
# =============================================================================

class TaxRate(models.Model):
    """
    Sales tax rates by location. Shop owners add rates for areas they serve.
    Lookup by city+state when calculating invoice tax.
    
    Total rate auto-calculates from component rates on save.
    """
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='tax_rates',
        null=True,
        blank=True,
    )
    
    city = models.CharField(max_length=100, db_index=True)
    county = models.CharField(max_length=100, blank=True, db_index=True)
    state = models.CharField(max_length=2, default='AR', db_index=True)
    zip_code = models.CharField(max_length=10, blank=True, db_index=True)

    # Rates stored as percentages (e.g., 9.500 means 9.5%)
    state_rate = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal('6.500'))
    county_rate = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal('0.000'))
    city_rate = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal('0.000'))
    special_rate = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal('0.000'))
    total_rate = models.DecimalField(
        max_digits=5, decimal_places=3, db_index=True,
        default=Decimal('0.000'),
        help_text="Auto-calculated: state + county + city + special"
    )

    effective_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    # Tenant-aware manager
    objects = TenantManager()

    class Meta:
        ordering = ['state', 'city']
        indexes = [
            models.Index(fields=['city', 'state']),
            models.Index(fields=['zip_code']),
        ]

    def __str__(self):
        return f"{self.city}, {self.state} — {self.total_rate}%"

    def save(self, *args, **kwargs):
        # Auto-calculate total from components
        self.total_rate = (
            self.state_rate + self.county_rate + 
            self.city_rate + self.special_rate
        )
        # Normalize city name for consistent lookups
        if self.city:
            self.city = self.city.strip()
        if self.state:
            self.state = self.state.strip().upper()
        super().save(*args, **kwargs)
