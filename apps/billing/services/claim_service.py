"""
Insurance claim lifecycle (B5). Every state change goes through here.

See apps/billing/claim_models.py for the design. The shape mirrors
quote_service: small functions, each one a verb the UI calls, each one
audit-logged through apps.security.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.billing.claim_models import ZERO, InsuranceClaim
from apps.security.audit import log_event

logger = logging.getLogger(__name__)


class ClaimError(Exception):
    """A state change the claim will not allow. The message is safe to show."""


# --- reconciliation ------------------------------------------------------

def reconcile(claim, save=True):
    """Recompute received_amount and, unless CLOSED, the status. Called after
    every payment, payment deletion, invoice-total change and claim edit.

    Idempotent and cheap: one aggregate. Returns the claim.
    """
    received = claim.payments.aggregate(total=Sum('amount'))['total'] or ZERO
    claim.received_amount = received
    if claim.status != 'CLOSED':
        claim.status = claim.derived_status()
    if save:
        claim.save(update_fields=['received_amount', 'status', 'updated_at'])
    return claim


def reconcile_by_id(claim_id):
    claim = InsuranceClaim.objects.select_related('invoice').filter(id=claim_id).first()
    if claim is not None:
        reconcile(claim)
    return claim


def reconcile_invoice_claim(invoice):
    """The invoice's claim, reconciled — or None when the invoice has none.
    Safe to call from any invoice-total path."""
    claim = InsuranceClaim.objects.filter(invoice_id=invoice.id).first()
    if claim is None:
        return None
    claim.invoice = invoice
    return reconcile(claim)


# --- creation ------------------------------------------------------------

def _jobs_on(invoice):
    jobs = []
    for line in invoice.line_items.select_related('repair', 'replacement'):
        job = line.repair or line.replacement
        if job is not None and job not in jobs:
            jobs.append(job)
    return jobs


def prefill_from_jobs(jobs):
    """What the job form already captured, for a claim on these jobs. The
    first insurance-flagged job wins; a mixed invoice is the owner's to fix
    on the claim page. Returns {} when no job is flagged."""
    flagged = [j for j in jobs if getattr(j, 'insurance_claim', False)]
    if not flagged:
        return {}
    src = flagged[0]
    return {
        'insurer': (src.insurance_company or '').strip(),
        'claim_number': (src.claim_number or '').strip(),
        'authorization_number': (src.authorization_number or '').strip(),
        'deductible': src.deductible,
    }


def prefill_for_invoice(invoice):
    return prefill_from_jobs(_jobs_on(invoice))


def create_claim(invoice, *, request=None, user=None, **fields):
    """Track a claim on this invoice. One per invoice; a second call raises."""
    if InsuranceClaim.objects.filter(invoice=invoice).exists():
        raise ClaimError('This invoice already has an insurance claim.')
    if invoice.status == 'CANCELLED':
        raise ClaimError('A cancelled invoice cannot carry an insurance claim.')
    user = user or (request.user if request is not None and request.user.is_authenticated else None)
    claim = InsuranceClaim(
        tenant=invoice.tenant or invoice.customer.tenant,
        invoice=invoice,
        created_by=user,
        insurer=fields.get('insurer', ''),
        claim_number=fields.get('claim_number', ''),
        authorization_number=fields.get('authorization_number', ''),
        deductible=fields.get('deductible'),
        billed_amount=fields.get('billed_amount'),
        authorized_amount=fields.get('authorized_amount'),
        submitted_on=fields.get('submitted_on') or invoice.invoice_date or timezone.localdate(),
        notes=fields.get('notes', ''),
    )
    claim.status = claim.derived_status()
    claim.save()
    # Money already on the invoice may include insurer payments recorded
    # before the claim existed; nothing links them yet, so received is 0.
    log_event(
        request, 'claim_created',
        f'Insurance claim tracked on invoice {invoice.invoice_number}',
        tenant=claim.tenant, claim_id=claim.id, invoice_id=invoice.id,
        source='auto' if request is None else 'owner',
    )
    return claim


def ensure_claim_for_invoice(invoice, services=None):
    """Create the claim for an invoice built from a job flagged "Insurance
    claim", copying what the technician typed. Returns the claim, or None
    when no job on the invoice is flagged. Called from invoice creation."""
    existing = InsuranceClaim.objects.filter(invoice=invoice).first()
    if existing is not None:
        return existing
    jobs = list(services) if services is not None else _jobs_on(invoice)
    prefill = prefill_from_jobs(jobs)
    if not prefill:
        return None
    return create_claim(invoice, **prefill)


# --- edits ---------------------------------------------------------------

EDITABLE = ('insurer', 'claim_number', 'authorization_number', 'deductible',
            'billed_amount', 'authorized_amount', 'submitted_on', 'notes')


def update_claim(claim, *, request=None, **fields):
    """Edit the header and money fields; status follows the money."""
    if claim.status == 'CLOSED':
        raise ClaimError('Reopen the claim before editing it.')
    changed = []
    for name in EDITABLE:
        if name not in fields:
            continue
        value = fields[name]
        if getattr(claim, name) != value:
            setattr(claim, name, value)
            changed.append(name)
    if changed:
        claim.save()
        reconcile(claim)
        log_event(
            request, 'claim_updated',
            f'Insurance claim on invoice {claim.invoice.invoice_number} edited',
            tenant=claim.tenant, claim_id=claim.id, invoice_id=claim.invoice_id,
            fields=changed,
        )
    return claim


def close_claim(claim, *, request=None, user=None, reason=''):
    """Stop chasing. The short amount right now is what the shop wrote off."""
    if claim.status == 'CLOSED':
        raise ClaimError('This claim is already closed.')
    user = user or (request.user if request is not None and request.user.is_authenticated else None)
    with transaction.atomic():
        reconcile(claim, save=False)
        claim.written_off_amount = max(claim.expected_amount - claim.received_amount, ZERO)
        claim.status = 'CLOSED'
        claim.closed_at = timezone.now()
        claim.closed_by = user
        claim.close_reason = (reason or '').strip()
        claim.save()
    log_event(
        request, 'claim_closed',
        f'Insurance claim on invoice {claim.invoice.invoice_number} closed; '
        f'${claim.written_off_amount} written off',
        tenant=claim.tenant, claim_id=claim.id, invoice_id=claim.invoice_id,
        written_off=str(claim.written_off_amount),
    )
    return claim


def reopen_claim(claim, *, request=None):
    if claim.status != 'CLOSED':
        raise ClaimError('Only a closed claim can be reopened.')
    claim.status = 'SUBMITTED'  # placeholder; reconcile derives the real one
    claim.written_off_amount = ZERO
    claim.closed_at = None
    claim.closed_by = None
    claim.close_reason = ''
    claim.save()
    reconcile(claim)
    log_event(
        request, 'claim_reopened',
        f'Insurance claim on invoice {claim.invoice.invoice_number} reopened',
        tenant=claim.tenant, claim_id=claim.id, invoice_id=claim.invoice_id,
    )
    return claim


def log_insurer_payment(claim, payment, request=None):
    log_event(
        request, 'claim_payment',
        f'Insurer payment of ${payment.amount} recorded on invoice '
        f'{claim.invoice.invoice_number}',
        tenant=claim.tenant, claim_id=claim.id, invoice_id=claim.invoice_id,
        payment_id=payment.id, amount=str(payment.amount),
    )


# --- rollups (the aging card, the claims list) ---------------------------

def rollup(tenant):
    """Open-claim money for a tenant, split the way the owner asks about it:
    short-paid (something came in, not enough) and waiting (nothing yet).
    Computed in Python: expected depends on the invoice, and open claims
    are a small set."""
    short = {'count': 0, 'total': ZERO}
    waiting = {'count': 0, 'total': ZERO}
    qs = InsuranceClaim.objects.filter(
        tenant=tenant, status__in=InsuranceClaim.OPEN_STATUSES,
    ).select_related('invoice')
    for claim in qs:
        owed = claim.outstanding_amount
        if owed <= ZERO:
            continue  # the customer covered it; the invoice is not owed
        bucket = short if claim.status == 'SHORT' else waiting
        bucket['count'] += 1
        bucket['total'] += owed
    return {'short': short, 'waiting': waiting}
