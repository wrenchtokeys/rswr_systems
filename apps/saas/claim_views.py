"""
Insurance claim tracking (B5), owner side.

Split out of apps/saas/views.py the way quote_views is; urls.py imports this
module directly. Access is `owner_or_manager_required`: chasing an insurer
is a money conversation, and the claims list is a money list.

The one write that is NOT here is recording an insurer payment — that goes
through `views.owner_record_payment` with `from_insurer=1`, so the Stripe
in-flight guard, the row lock and the overpayment check are the same code
for every payment.
"""

import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.claim_models import InsuranceClaim
from apps.billing.models import Invoice, Payment
from apps.billing.services import claim_service
from apps.billing.services.claim_service import ClaimError
from common.decorators import owner_or_manager_required

logger = logging.getLogger(__name__)

STATUS_PILLS = [
    ('open', 'Open'),
    ('short', 'Short-paid'),
    ('waiting', 'Waiting on insurer'),
    ('paid', 'Paid'),
    ('closed', 'Closed'),
    ('all', 'All'),
]

_DEC_RE = re.compile(r'^-?\d+(\.\d{1,2})?$')


def _tenant(request):
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Could not determine your shop. Please log in again.')
    return tenant


def _money(raw, field):
    """'' → None (blank means "not set"); otherwise a non-negative Decimal.
    Raises ClaimError with the field name for anything else."""
    raw = (raw or '').strip().replace(',', '').lstrip('$')
    if raw == '':
        return None
    if not _DEC_RE.match(raw):
        raise ClaimError(f'{field} must be a dollar amount.')
    value = Decimal(raw)
    if value < 0:
        raise ClaimError(f'{field} cannot be negative.')
    return value.quantize(Decimal('0.01'))


def _date(raw, field, default):
    raw = (raw or '').strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ClaimError(f'{field} is not a valid date.')


def _fields_from_post(request, claim=None):
    """The editable claim fields, parsed. Missing keys are left out so an
    edit form that omits a field does not blank it."""
    post = request.POST
    fields = {}
    for name in ('insurer', 'claim_number', 'authorization_number', 'notes'):
        if name in post:
            fields[name] = post.get(name, '').strip()[:100 if name == 'insurer' else 50 if name != 'notes' else 5000]
    if 'deductible' in post:
        fields['deductible'] = _money(post.get('deductible'), 'Deductible')
    if 'billed_amount' in post:
        fields['billed_amount'] = _money(post.get('billed_amount'), 'Billed amount')
    if 'authorized_amount' in post:
        fields['authorized_amount'] = _money(post.get('authorized_amount'), 'Authorized amount')
    if 'submitted_on' in post:
        fields['submitted_on'] = _date(
            post.get('submitted_on'), 'Submitted date',
            claim.submitted_on if claim else timezone.localdate(),
        )
    return fields


# --- list / detail -----------------------------------------------------------

@owner_or_manager_required
def claim_list(request):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')

    status_filter = request.GET.get('status', 'open')
    if status_filter not in dict(STATUS_PILLS):
        status_filter = 'open'

    qs = InsuranceClaim.objects.filter(tenant=tenant).select_related('invoice', 'invoice__customer')
    if status_filter == 'open':
        qs = qs.filter(status__in=InsuranceClaim.OPEN_STATUSES)
    elif status_filter == 'short':
        qs = qs.filter(status='SHORT')
    elif status_filter == 'waiting':
        qs = qs.filter(status__in=('SUBMITTED', 'AUTHORIZED'))
    elif status_filter == 'paid':
        qs = qs.filter(status='PAID')
    elif status_filter == 'closed':
        qs = qs.filter(status='CLOSED')

    rollup = claim_service.rollup(tenant)
    month_start = timezone.localdate().replace(day=1)
    received_month = Payment.objects.filter(
        claim__tenant=tenant, payment_date__gte=month_start,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    return render(request, 'saas/claim_list.html', {
        'tenant': tenant,
        'claims': qs[:300],
        'status_pills': STATUS_PILLS,
        'status_filter': status_filter,
        'short': rollup['short'],
        'waiting': rollup['waiting'],
        'received_month': received_month,
    })


@owner_or_manager_required
def claim_detail(request, claim_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    claim = get_object_or_404(
        InsuranceClaim.objects.select_related('invoice', 'invoice__customer', 'closed_by'),
        id=claim_id, tenant=tenant,
    )
    invoice = claim.invoice
    payment_methods = [c for c in Payment.PAYMENT_METHOD_CHOICES if c[0] != 'STRIPE']
    suggested = min(claim.short_amount, invoice.amount_due) if claim.is_open else Decimal('0.00')
    return render(request, 'saas/claim_detail.html', {
        'tenant': tenant,
        'claim': claim,
        'invoice': invoice,
        'insurer_payments': claim.payments.select_related('recorded_by').order_by('-payment_date', '-created_at'),
        'other_payments': invoice.payments.filter(claim__isnull=True).order_by('-payment_date', '-created_at'),
        'payment_methods': payment_methods,
        'can_record_payment': claim.is_open and invoice.status not in ('PAID', 'CANCELLED') and invoice.amount_due > 0,
        'suggested_amount': max(suggested, Decimal('0.00')),
        'today': timezone.localdate(),
    })


# --- writes ------------------------------------------------------------------

@owner_or_manager_required
@require_POST
def claim_create(request, invoice_id):
    """Track a claim on an invoice. Prefilled from the job by the template;
    the POST may carry the header fields or nothing at all."""
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    invoice = get_object_or_404(Invoice, id=invoice_id, customer__tenant=tenant)
    try:
        fields = _fields_from_post(request)
        claim = claim_service.create_claim(invoice, request=request, **fields)
    except ClaimError as e:
        messages.error(request, str(e))
        return redirect('owner_invoice_detail', invoice_id=invoice.id)
    messages.success(request, f'Tracking the insurance claim on {invoice.invoice_number}.')
    return redirect('claim_detail', claim_id=claim.id)


@owner_or_manager_required
@require_POST
def claim_edit(request, claim_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    claim = get_object_or_404(InsuranceClaim.objects.select_related('invoice'), id=claim_id, tenant=tenant)
    try:
        fields = _fields_from_post(request, claim)
        claim_service.update_claim(claim, request=request, **fields)
    except ClaimError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Claim updated.')
    return redirect('claim_detail', claim_id=claim.id)


@owner_or_manager_required
@require_POST
def claim_close(request, claim_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    claim = get_object_or_404(InsuranceClaim.objects.select_related('invoice'), id=claim_id, tenant=tenant)
    try:
        claim_service.close_claim(claim, request=request, reason=request.POST.get('reason', ''))
    except ClaimError as e:
        messages.error(request, str(e))
    else:
        if claim.written_off_amount > 0:
            messages.success(request, f'Claim closed. ${claim.written_off_amount} written off.')
        else:
            messages.success(request, 'Claim closed.')
    return redirect('claim_detail', claim_id=claim.id)


@owner_or_manager_required
@require_POST
def claim_reopen(request, claim_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    claim = get_object_or_404(InsuranceClaim.objects.select_related('invoice'), id=claim_id, tenant=tenant)
    try:
        claim_service.reopen_claim(claim, request=request)
    except ClaimError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Claim reopened.')
    return redirect('claim_detail', claim_id=claim.id)
