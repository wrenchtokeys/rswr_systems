"""
Insurance claim tracking, Tier 1 (no EDI).

IMPROVEMENT_SESSIONS B5, the second spine feature of PRODUCT_DIRECTION
(September 2026). Insurance money arrives late and short; the daily pain is
"they paid $312 on a $380 claim" and not knowing, across every open job,
what is still outstanding. That pain is independent of how the claim was
submitted, so this tracks the claim and reconciles it against money
received — no clearinghouse, no insurer formats.

Design decisions, recorded here because the session doc asked for them:

* **The claim hangs off the invoice, not the job.** Reconciliation is
  against money received, and money is received against an invoice. The
  job still carries the insurer / claim number / deductible the technician
  typed on the job form; those are copied onto the claim when the invoice
  is created (``services/claim_service.ensure_claim_for_invoice``) and are
  editable there. One claim per invoice.

* **Money is derived, never typed twice.** Expected = the authorized
  amount if the insurer has named one, else the billed amount if the shop
  pinned one, else the invoice total minus the deductible (which follows
  the invoice when lines are edited). Received = the sum of the payments
  recorded *as insurer payments* against the invoice (``Payment.claim``);
  the customer's deductible is an ordinary payment and never counts.
  Short = expected minus received.

* **Status is a function of the money, except CLOSED.** ``reconcile``
  recomputes it after every payment, payment deletion, invoice-total
  change and claim edit: nothing received → SUBMITTED (or AUTHORIZED once
  the insurer named a figure); some received → SHORT; everything → PAID.
  CLOSED is the one human act — the shop stops chasing, and the short
  amount at that moment is snapshotted as ``written_off_amount`` so the
  aging card stops counting it. Reopening derives the status again.

* **Owner and manager only.** Chasing an insurer is a money conversation;
  technicians see the insurance fields on the job and nothing else. The
  customer portal does not show claim status in this cut (session doc
  recommendation).

* **Every mutation is audit-logged** through ``apps.security`` (claim data
  is sensitive; the session doc says extend that log, never bypass it).
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.managers import TenantManager
from rs_systems.model_mixins import AutoUpdateTimestampMixin

ZERO = Decimal('0.00')


class InsuranceClaim(AutoUpdateTimestampMixin, models.Model):
    STATUS_CHOICES = [
        ('SUBMITTED', 'Submitted'),
        ('AUTHORIZED', 'Authorized'),
        ('SHORT', 'Short-paid'),
        ('PAID', 'Paid in full'),
        ('CLOSED', 'Closed'),
    ]
    # Still waiting on money from the insurer.
    OPEN_STATUSES = ('SUBMITTED', 'AUTHORIZED', 'SHORT')

    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='insurance_claims',
    )
    invoice = models.OneToOneField(
        'billing.Invoice', on_delete=models.CASCADE, related_name='claim',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    insurer = models.CharField(max_length=100, blank=True, help_text='Insurance company')
    claim_number = models.CharField(max_length=50, blank=True, db_index=True)
    authorization_number = models.CharField(max_length=50, blank=True)
    deductible = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="The customer's share. Paid to the shop by the customer, never by the insurer.",
    )

    # What the shop asked the insurer for. Blank = follow the invoice
    # (total minus deductible) so a line edit re-prices the claim too.
    billed_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Blank means the invoice total minus the deductible.',
    )
    # What the insurer said it will pay. Blank until they answer.
    authorized_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    # Cache of the insurer payments linked to this claim; recomputed by
    # claim_service.reconcile (same pattern as Invoice.amount_paid).
    received_amount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='SUBMITTED', db_index=True,
    )
    submitted_on = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True, help_text='Shop only — who you spoke to, what they said.')

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    close_reason = models.TextField(blank=True)
    # The short amount at the moment the claim was closed — the money the
    # shop decided to stop chasing. Zero unless CLOSED.
    written_off_amount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-submitted_on', '-id']
        indexes = [
            models.Index(fields=['tenant', 'status'], name='claim_tenant_status_idx'),
        ]

    def __str__(self):
        label = self.claim_number or f'claim on {self.invoice.invoice_number}'
        return f'Insurance {label}'

    # --- money -------------------------------------------------------------

    @property
    def deductible_amount(self):
        return self.deductible if self.deductible is not None else ZERO

    @property
    def invoice_billed_amount(self):
        """What the invoice says the insurer's share is: total minus deductible."""
        return max(self.invoice.total - self.deductible_amount, ZERO)

    @property
    def effective_billed_amount(self):
        return self.billed_amount if self.billed_amount is not None else self.invoice_billed_amount

    @property
    def expected_amount(self):
        """What the shop is waiting on from the insurer."""
        if self.authorized_amount is not None:
            return self.authorized_amount
        return self.effective_billed_amount

    @property
    def short_amount(self):
        """Money the insurer still owes (open) or the shop wrote off (closed)."""
        if self.status == 'CLOSED':
            return self.written_off_amount
        if self.status == 'PAID':
            return ZERO
        return max(self.expected_amount - self.received_amount, ZERO)

    @property
    def outstanding_amount(self):
        """The part of the short that is actually still owed to the shop.
        If the customer covered the difference the invoice is paid and the
        claim, though short, is not money the shop is waiting on. This is
        what the aging card counts."""
        if not self.is_open:
            return ZERO
        return max(min(self.short_amount, self.invoice.amount_due), ZERO)

    @property
    def authorized_short_of_billed(self):
        """The cut the insurer made when authorizing, if any."""
        if self.authorized_amount is None:
            return ZERO
        return max(self.effective_billed_amount - self.authorized_amount, ZERO)

    # --- state -------------------------------------------------------------

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_closed(self):
        return self.status == 'CLOSED'

    @property
    def is_waiting(self):
        """Open, and nothing has come in yet."""
        return self.status in ('SUBMITTED', 'AUTHORIZED')

    def derived_status(self):
        """The status the money says this claim is in. CLOSED is not derived —
        it is the shop's decision — so callers check that first."""
        expected = self.expected_amount
        received = self.received_amount
        if expected > ZERO and received >= expected:
            return 'PAID'
        if received > ZERO:
            return 'SHORT'
        if self.authorized_amount is not None:
            return 'AUTHORIZED'
        return 'SUBMITTED'
