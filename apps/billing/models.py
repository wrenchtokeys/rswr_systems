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

import logging
from django.db import models, transaction
from django.utils import timezone
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.tenants.managers import TenantManager
from rs_systems.model_mixins import AutoUpdateTimestampMixin

logger = logging.getLogger(__name__)


# =============================================================================
# BILLING CONFIGURATION (Per-Tenant)
# =============================================================================

class BillingConfig(AutoUpdateTimestampMixin, models.Model):
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

    # === EMAIL TEMPLATES (editable defaults) ===
    invoice_email_template = models.TextField(
        blank=True,
        default='',
        help_text='Default email body when sending an invoice. '
                  'Use {customer_name}, {invoice_number}, {total}, {invoice_date}, {company_name} as placeholders. '
                  'Leave blank to use the system default.',
    )
    reminder_email_template = models.TextField(
        blank=True,
        default='',
        help_text='Default email body for payment reminders. '
                  'Use {customer_name}, {invoice_number}, {total}, {amount_due}, {due_date}, {days_overdue}, {company_name} as placeholders. '
                  'Leave blank to use the system default.',
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

class InvoiceSoftDeleteManager(TenantManager):
    """
    Default manager for Invoice — automatically excludes soft-deleted records.
    Use Invoice.all_objects for unfiltered access (including deleted).
    """
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Invoice(AutoUpdateTimestampMixin, models.Model):
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

    # Soft-delete — set to a timestamp to mark as deleted (not visible in default queryset)
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When set, this invoice is soft-deleted and excluded from normal querysets"
    )

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

    # Soft-delete manager (default — excludes deleted records)
    objects = InvoiceSoftDeleteManager()
    # Unfiltered manager — use when you need deleted records too
    all_objects = TenantManager()
    
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

    # ------------------------------------------------------------------
    # S3 cleanup on delete (CODE-152)
    # ------------------------------------------------------------------
    def delete(self, *args, **kwargs):
        """Delete the invoice and its S3 PDF object (if any).

        Voided (CANCELLED) invoices keep their PDF for audit trail — the S3
        object is only removed when the record is actually deleted (DRAFT or
        already-voided invoices).
        """
        self._delete_s3_object()
        super().delete(*args, **kwargs)

    def _delete_s3_object(self):
        """Remove the S3 object for this invoice's PDF, if one exists."""
        if not self.s3_key:
            return
        try:
            from django.conf import settings
            bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
            if not bucket:
                return
            import boto3
            from botocore.exceptions import ClientError
            s3_client = boto3.client('s3')
            s3_client.delete_object(Bucket=bucket, Key=self.s3_key)
            logger.info(f"Deleted S3 object: s3://{bucket}/{self.s3_key}")
        except Exception as e:
            # Log but don't block deletion — orphaned S3 objects are
            # preferable to a stuck invoice that can't be deleted.
            logger.warning(f"Failed to delete S3 object {self.s3_key}: {e}")

    @property
    def amount_due(self):
        """Amount still owed on this invoice."""
        return self.total - self.amount_paid

    @property
    def state_tax_amount(self):
        """Calculated state tax amount from rate × subtotal."""
        if not self.state_tax_rate or not self.subtotal:
            return Decimal('0.00')
        return (self.subtotal * self.state_tax_rate / Decimal('100')).quantize(Decimal('0.01'))

    @property
    def county_tax_amount(self):
        """Calculated county tax amount from rate × subtotal."""
        if not self.county_tax_rate or not self.subtotal:
            return Decimal('0.00')
        return (self.subtotal * self.county_tax_rate / Decimal('100')).quantize(Decimal('0.01'))

    @property
    def city_tax_amount(self):
        """Calculated city tax amount from rate × subtotal."""
        if not self.city_tax_rate or not self.subtotal:
            return Decimal('0.00')
        return (self.subtotal * self.city_tax_rate / Decimal('100')).quantize(Decimal('0.01'))

    @property
    def special_tax_amount(self):
        """Calculated special district tax amount from rate × subtotal."""
        if not self.special_tax_rate or not self.subtotal:
            return Decimal('0.00')
        return (self.subtotal * self.special_tax_rate / Decimal('100')).quantize(Decimal('0.01'))

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

    def get_pdf_url(self):
        """
        Return the raw (UNSIGNED) S3 object URL for the invoice PDF, or None.

        SECURITY (B1): do NOT put this URL in templates or hand it to users.
        The bucket is private on the invoices/ prefix, so this URL 403s for
        anyone; and if the bucket were ever public, the keys are predictable
        (invoices/<customer_id>/<year>/<number>.pdf) — an enumerable
        cross-tenant leak. Serve PDFs through the ownership-checked views
        (owner_invoice_pdf / customer_invoice_pdf), which mint short-TTL
        presigned URLs. Kept only for internal/diagnostic use.

        Reads the bucket/domain from Django settings so this works correctly in
        every environment (dev, staging, prod) and survives bucket renames.

        Priority order:
        1. AWS_S3_CUSTOM_DOMAIN setting  (e.g. 'mybucket.s3.amazonaws.com')
        2. AWS_STORAGE_BUCKET_NAME       (constructs domain from bucket name)
        3. Falls back to None if neither is configured (local/dev without S3)
        """
        if not self.s3_key:
            return None

        from django.conf import settings

        # Try AWS_S3_CUSTOM_DOMAIN first (set by production.py when USE_S3=True)
        custom_domain = getattr(settings, 'AWS_S3_CUSTOM_DOMAIN', None)
        if custom_domain:
            return f"https://{custom_domain}/{self.s3_key}"

        # Fallback: construct from bucket name
        bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
        if bucket:
            region = getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1')
            return f"https://{bucket}.s3.{region}.amazonaws.com/{self.s3_key}"

        return None


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
        # Auto-calculate amount only when it has not been explicitly set (None).
        #
        # BUG (CODE-151): The old guard was `if not self.amount:` which is True for
        # both None AND Decimal('0.00').  This caused line items with a deliberately
        # computed amount of $0.00 — e.g. FREE_SERVICE reward redemptions where
        # get_discounted_cost() returns final_cost=Decimal(0) — to have their amount
        # overridden to (unit_price × quantity - discount) on every save().
        # For a free repair (discount=0, unit_price=50) that means $0 becomes $50,
        # effectively silently dropping the customer's reward discount from invoices.
        #
        # Fix: use `is None` so only genuinely unset amounts are auto-computed.
        # Callers that explicitly pass amount=Decimal('0.00') (e.g. FREE rewards,
        # fully-discounted line items) now retain that value.
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
        constraints = [
            # C2: Stripe delivers checkout.session.completed and
            # payment_intent.succeeded concurrently (and retries on
            # timeout) with the same pi_... id. The application-level
            # .exists() precheck is a check-then-create race; this partial
            # unique index is the only thing that actually prevents a
            # double-credited payment. Empty string = manual payment,
            # exempt.
            models.UniqueConstraint(
                fields=['stripe_payment_id'],
                condition=~models.Q(stripe_payment_id=''),
                name='unique_stripe_payment_id_when_set',
            ),
        ]

    def __str__(self):
        return f"${self.amount} on {self.invoice.invoice_number} via {self.get_payment_method_display()}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update invoice payment total and status
        self._update_invoice_totals()

    def delete(self, *args, **kwargs):
        # Capture invoice_id before deletion so we can reconcile after.
        # Payment.invoice FK uses on_delete=PROTECT so the invoice row
        # will still exist after this payment is removed.
        invoice_id = self.invoice_id
        super().delete(*args, **kwargs)
        # Recompute invoice totals now that this payment is gone.
        # Uses the same SELECT FOR UPDATE pattern as _update_invoice_totals to
        # be safe under concurrent operations.
        # (CODE-118: without this, deleting a payment left invoice.amount_paid
        # stale — a PAID invoice would remain PAID even with $0 payments.)
        with transaction.atomic():
            try:
                invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
            except Invoice.DoesNotExist:
                return
            total_paid = invoice.payments.aggregate(
                total=models.Sum('amount')
            )['total'] or Decimal('0.00')
            invoice.amount_paid = total_paid
            # Recompute status — must handle PAID demotion here since
            # update_status() never demotes an already-PAID invoice back to
            # SENT/PARTIAL (it was designed for forward-only transitions).
            if invoice.status != 'CANCELLED':
                if total_paid >= invoice.total:
                    invoice.status = 'PAID'
                    if not invoice.paid_at:
                        invoice.paid_at = timezone.now()
                elif total_paid > 0:
                    invoice.status = 'PARTIAL'
                    invoice.paid_at = None
                else:
                    # No money received — revert to SENT or OVERDUE.
                    # Check due_date directly (not invoice.is_overdue which
                    # short-circuits on PAID/CANCELLED status).
                    invoice.paid_at = None
                    is_past_due = (
                        invoice.due_date is not None
                        and timezone.now().date() > invoice.due_date
                    )
                    if is_past_due:
                        invoice.status = 'OVERDUE'
                    elif invoice.status in ('PAID', 'PARTIAL'):
                        # Revert to SENT — no money received any more
                        invoice.status = 'SENT'
                    # DRAFT stays DRAFT, OVERDUE stays OVERDUE if already set
            invoice.save()

    def _update_invoice_totals(self):
        """
        Update the invoice's amount_paid and status.

        Uses SELECT FOR UPDATE to prevent a race condition where two concurrent
        payments both read the same stale aggregate and one overwrites the
        other's work, leaving amount_paid under-counted.

        Example: customer pays via Stripe webhook AND a technician records a
        cash payment at the same moment. Without the lock both transactions
        would read the same SUM and the final write would lose one payment.
        """
        with transaction.atomic():
            # Lock the invoice row for the duration of the read-aggregate-write
            # sequence so concurrent payments serialise here instead of racing.
            invoice = Invoice.objects.select_for_update().get(pk=self.invoice_id)
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


# =============================================================================
# PLATFORM CONFIG (Singleton)
# =============================================================================

class PlatformConfig(AutoUpdateTimestampMixin, models.Model):
    """
    Singleton — global platform settings for Stripe Connect fee routing.

    Use PlatformConfig.get() to fetch (creates with defaults if missing).
    """
    default_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Default platform fee % on invoice payments (e.g. 2.50 = 2.5%)"
    )
    competition_pool_enabled = models.BooleanField(
        default=False,
        help_text="Whether the competition pool feature is active"
    )
    competition_pool_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="% of subscription payments routed to competition pool"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform Configuration'
        verbose_name_plural = 'Platform Configuration'

    def __str__(self):
        return f'Platform Config (fee: {self.default_fee_percent}%)'

    def save(self, *args, **kwargs):
        # Enforce singleton: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Platform configuration cannot be deleted.')

    @classmethod
    def get(cls):
        """Get (or create with defaults) the singleton PlatformConfig."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def get_solo(cls):
        """Alias for get() — singleton accessor."""
        return cls.get()


# =============================================================================
# PLATFORM FEE RECORDS
# =============================================================================

class PlatformFeeRecord(models.Model):
    """
    Tracks every platform fee collected on invoice payments.

    Created when a connected charge succeeds. Used for reporting,
    audit trail, and future competition pool calculations.
    """
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='platform_fee_records',
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='platform_fee_records',
    )
    payment_intent_id = models.CharField(
        max_length=255, db_index=True,
        help_text="Stripe PaymentIntent ID (pi_...)"
    )
    gross_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Total payment amount in dollars"
    )
    fee_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Platform fee collected in dollars"
    )
    fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text="Fee rate at time of charge (percentage)"
    )
    stripe_account_id = models.CharField(
        max_length=50,
        help_text="Shop's connected account ID (acct_...)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Fee Record'
        verbose_name_plural = 'Platform Fee Records'
        indexes = [
            models.Index(fields=['tenant', 'created_at']),
        ]

    def __str__(self):
        return (
            f"Fee ${self.fee_amount} ({self.fee_percent}%) on "
            f"{self.invoice.invoice_number} → {self.stripe_account_id}"
        )
