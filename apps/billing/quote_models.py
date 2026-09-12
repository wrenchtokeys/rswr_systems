"""
Quotes — a priced estimate the customer accepts before any job exists.

IMPROVEMENT_SESSIONS B3, the first spine feature of PRODUCT_DIRECTION
(September 2026). The product used to be job → invoice only; fleet
procurement and every insurance-adjacent workflow need a priced estimate
first, and until now the shop wrote it somewhere else.

Design decisions, recorded here because the session doc asked for them:

* **A separate model, not a pre-REQUESTED job status.** A quote can be
  declined, revised or expire without polluting job history, job counts,
  progressive-pricing counters or revenue. Jobs are created only when the
  quote is accepted (``services/quote_service.accept_quote``).
* **Accepting a quote creates the jobs**, with the quoted price locked via
  ``cost_override`` — the one field the job models already treat as "a
  human set this price", so progressive pricing cannot re-price a job
  between quoting and doing the work. The jobs come in as ``APPROVED``:
  the acceptance *is* the customer's approval.
* **Quotes expire.** ``valid_until`` defaults to ``BillingConfig.quote_valid_days``
  (30). A SENT quote past that date reads as EXPIRED and cannot be accepted;
  the shop revises it instead, which re-prices on today's numbers.
* **Revision is a supersede chain.** "Revise" clones a quote into a new
  DRAFT that points at the old one through ``supersedes``; the old one is
  marked SUPERSEDED and stays visible.
* **Numbering** mirrors invoices: ``BillingConfig.allocate_quote_number()``
  is row-locked and skips taken numbers. Never hand-format a quote number.
* **No soft delete.** Only a DRAFT can be deleted, and a draft nobody sent
  has nothing to restore. Everything else stays on record.

The line items deliberately carry no FK to the jobs they became; the jobs
point back (``GlassService.quote``), so "what did this quote turn into" is
``quote.repairs`` / ``quote.replacements`` and a deleted job never leaves a
dangling line.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.tenants.managers import TenantManager
from rs_systems.model_mixins import AutoUpdateTimestampMixin


class Quote(AutoUpdateTimestampMixin, models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SENT', 'Sent'),
        ('ACCEPTED', 'Accepted'),
        ('DECLINED', 'Declined'),
        ('EXPIRED', 'Expired'),
        ('SUPERSEDED', 'Revised'),
    ]
    # Statuses a customer can still act on (before the expiry check).
    OPEN_STATUSES = ('DRAFT', 'SENT')

    ACCEPTED_VIA_CHOICES = [
        ('link', 'Emailed link'),
        ('portal', 'Customer portal'),
        ('shop', 'Recorded by the shop'),
    ]

    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='quotes',
    )
    quote_number = models.CharField(max_length=50, db_index=True)
    customer = models.ForeignKey(
        'core.Customer', on_delete=models.PROTECT, related_name='quotes',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True,
    )
    quote_date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(
        help_text='Last day the customer can accept at these prices.',
    )

    # The vehicle the quote is for. Fleets name a unit, individuals a car —
    # the same two-column split the job models use (CLAUDE.md: individuals
    # vs fleets, never mixed). A line may name its own unit for a fleet
    # quote spanning several vehicles.
    unit_number = models.CharField(max_length=50, blank=True)
    vehicle_year = models.PositiveIntegerField(null=True, blank=True)
    vehicle_make = models.CharField(max_length=50, blank=True)
    vehicle_model = models.CharField(max_length=50, blank=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal('0.000'))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # "Charge sales tax" unchecked — carried onto every job the quote creates.
    no_tax = models.BooleanField(default=False)

    notes = models.TextField(blank=True, help_text='Shown to the customer.')
    internal_notes = models.TextField(blank=True, help_text='Shop only.')

    # Delivery
    sent_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    sent_to_email = models.EmailField(blank=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)

    # Response
    responded_at = models.DateTimeField(null=True, blank=True)
    accepted_via = models.CharField(max_length=20, choices=ACCEPTED_VIA_CHOICES, blank=True)
    responded_by_name = models.CharField(max_length=100, blank=True)
    decline_reason = models.TextField(blank=True)

    supersedes = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revisions',
        help_text='The quote this one replaced.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-quote_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'quote_number'],
                name='unique_quote_number_per_tenant',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'status'], name='quote_tenant_status_idx'),
            models.Index(fields=['customer', 'status'], name='quote_customer_status_idx'),
        ]

    def __str__(self):
        return f"Quote {self.quote_number}"

    # --- state -------------------------------------------------------------

    @property
    def is_expired(self):
        """A SENT quote past its last valid day, whether or not the sweep has
        stamped it yet. Drafts don't expire — nobody has been promised a
        price — but they can't be sent with a past date either."""
        if self.status == 'EXPIRED':
            return True
        return self.status == 'SENT' and self.valid_until < timezone.localdate()

    @property
    def effective_status(self):
        return 'EXPIRED' if self.is_expired else self.status

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES and not self.is_expired

    @property
    def can_be_edited(self):
        return self.status in self.OPEN_STATUSES

    @property
    def can_be_revised(self):
        return self.status in ('SENT', 'DECLINED', 'EXPIRED')

    @classmethod
    def expire_stale(cls, tenant):
        """Stamp EXPIRED on every SENT quote past its date. Cheap enough to
        run on each list/detail load; there is no cron for this on purpose."""
        return cls.objects.filter(
            tenant=tenant, status='SENT', valid_until__lt=timezone.localdate(),
        ).update(status='EXPIRED')

    # --- vehicle -----------------------------------------------------------

    @property
    def vehicle_column_label(self):
        return self.customer.vehicle_column_label

    @property
    def vehicle_description(self):
        parts = [str(self.vehicle_year) if self.vehicle_year else '',
                 self.vehicle_make, self.vehicle_model]
        return ' '.join(p for p in parts if p).strip()

    def get_vehicle_identifier(self):
        """Bare identifier for a column whose header says what it is —
        unit for a fleet, year/make/model for an individual. '' when nothing
        is on record (print nothing, never a bare noun)."""
        if self.customer.is_individual:
            return self.vehicle_description
        return self.unit_number or ''

    def get_vehicle_label(self):
        ident = self.get_vehicle_identifier()
        if not ident:
            return ''
        if self.customer.is_individual:
            return ident
        return f"Unit #{ident}"

    # --- jobs --------------------------------------------------------------

    @property
    def jobs(self):
        """The repairs and replacements this quote became, newest last."""
        jobs = list(self.repairs.all()) + list(self.replacements.all())
        jobs.sort(key=lambda j: (j.service_date, j.id))
        return jobs

    @property
    def job_count(self):
        return self.repairs.count() + self.replacements.count()

    @property
    def expected_job_count(self):
        return sum(li.quantity for li in self.line_items.all() if li.creates_jobs)


class QuoteLineItem(models.Model):
    SERVICE_TYPE_CHOICES = [
        ('REPAIR', 'Repair'),
        ('REPLACEMENT', 'Replacement'),
        ('OTHER', 'Other charge'),
    ]

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='line_items')
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPE_CHOICES, default='REPAIR')
    description = models.CharField(max_length=500)
    # Fleet quote spanning units: a line may name its own unit; blank means
    # the quote's. Ignored for individuals.
    unit_number = models.CharField(max_length=50, blank=True)
    damage_type = models.CharField(max_length=100, blank=True)
    glass_position = models.CharField(max_length=30, blank=True)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    taxable = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.description} - ${self.amount}"

    @property
    def creates_jobs(self):
        return self.service_type in ('REPAIR', 'REPLACEMENT')

    def effective_unit_number(self):
        return self.unit_number or self.quote.unit_number

    def save(self, *args, **kwargs):
        # `is None`, not falsy — a deliberate $0.00 line (goodwill) stays $0.
        if self.amount is None:
            self.amount = self.unit_price * self.quantity
        super().save(*args, **kwargs)
