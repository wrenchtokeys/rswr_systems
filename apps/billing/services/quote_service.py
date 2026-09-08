"""
Quote lifecycle — the one place a quote changes state or becomes jobs.

Every entry point here is the thing a view, a public link or a portal page
calls; none of them render anything. They raise ``QuoteError`` with a message
the caller shows as-is.

The important invariant is in ``accept_quote``: **jobs are created through
``save()``** (the house rule quick_job.py spells out), with the quoted price
handed over as ``cost_override`` so progressive pricing cannot re-price the
work between quoting and doing it. ``cost_override`` is pre-discount on the
job models — ``save()`` runs it through ``apply_account_discount`` — so a
customer with an account discount gets the override backed out first
(``_override_for``) and lands on exactly the number they accepted.
"""

import hashlib
import hmac
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.billing.quote_models import Quote, QuoteLineItem

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')


class QuoteError(Exception):
    """A refusal the caller renders."""


# --- public link -------------------------------------------------------------

def public_token(quote_id):
    """Stateless HMAC token for the public quote page (the invoice pay link's
    twin). Its own message prefix, so an invoice token never opens a quote."""
    message = f"view-quote-{quote_id}"
    return hmac.new(
        settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256,
    ).hexdigest()[:32]


def token_matches(quote_id, token):
    return hmac.compare_digest(str(token or ''), public_token(quote_id))


def public_url(quote):
    base = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
    return f"{base}/quote/{quote.id}/{public_token(quote.id)}/"


# --- pricing -----------------------------------------------------------------

def default_repair_price(customer, unit_number, tenant):
    """What the shop would charge for the next repair on this vehicle — the
    number a non-manager's repair line is pinned to. Progressive pricing is
    honoured for fleets, so a quote for repair #3 on a unit prices as #3."""
    from apps.technician_portal.services.pricing_service import get_expected_repair_cost
    price, _count = get_expected_repair_cost(customer, unit_number or '', tenant)
    return price


def recalculate_totals(quote, save=True):
    """Subtotal, frozen tax rate/amount and total from the live lines.

    The rate is looked up when the quote is (re)calculated and stored; the
    customer sees one number and that is the number they accept. Jobs made
    from the quote compute their own tax at creation, as every job does —
    a quote locks the price, not the tax table.
    """
    from apps.billing.services.tax_service import TaxService

    lines = list(quote.line_items.all())
    subtotal = sum((li.amount for li in lines), Decimal('0.00'))
    taxable_base = sum((li.amount for li in lines if li.taxable), Decimal('0.00'))
    tax = TaxService(tenant=quote.tenant).calculate_tax(
        taxable_base, customer=quote.customer, no_tax=quote.no_tax,
    )
    quote.subtotal = subtotal.quantize(CENT)
    quote.tax_rate = Decimal(str(tax.get('rate') or 0))
    quote.tax_amount = Decimal(str(tax.get('amount') or 0)).quantize(CENT)
    quote.total = (quote.subtotal + quote.tax_amount).quantize(CENT)
    if save:
        quote.save(update_fields=['subtotal', 'tax_rate', 'tax_amount', 'total'])
    return quote


def _override_for(quoted_price, customer):
    """The ``cost_override`` that makes ``save()`` land on ``quoted_price``.

    ``Repair.save()`` applies the customer's account discount to the
    override, so a discounted customer needs it backed out. Whole-percent
    discounts round-trip exactly; for anything else we test the neighbours
    so the customer never pays a cent more than they accepted.
    """
    from apps.technician_portal.services.pricing_service import apply_account_discount

    pct = customer.get_effective_discount_percentage() if customer else Decimal('0')
    if not pct or pct <= 0:
        return quoted_price
    base = (Decimal(str(quoted_price)) * Decimal('100') / (Decimal('100') - pct))
    base = base.quantize(CENT, rounding=ROUND_HALF_UP)
    for delta in (Decimal('0.00'), Decimal('-0.01'), Decimal('0.01'), Decimal('-0.02'), Decimal('0.02')):
        candidate = base + delta
        if apply_account_discount(candidate, customer) == quoted_price:
            return candidate
    return base


# --- lifecycle ---------------------------------------------------------------

def _pick_technician(tenant, actor_user, service_type, customer):
    """(technician, needs_assignment) for a job the quote is about to create.

    With an actor (the shop recording an acceptance) this is exactly quick
    job creation's rule. Without one (a customer clicking the link) it is the
    shop's assignment strategy, then any capable active tech flagged as
    nobody's pick — the same order, minus the actor.
    """
    from apps.technician_portal.services.quick_job import resolve_technician
    from apps.tenants.services.assignment_service import select_technician
    from apps.technician_portal.models import Technician

    if actor_user is not None:
        return resolve_technician(tenant, actor_user, service_type, customer=customer)

    pick = select_technician(tenant, customer=customer, service_type=service_type)
    if pick:
        return pick, False
    qs = Technician.objects.filter(tenant=tenant, is_active=True)
    ability = qs.filter(can_replace=True) if service_type == 'replacement' else qs.filter(can_repair=True)
    return (ability.first() or qs.first()), True


def _build_job(quote, line, technician, needs_assignment, actor_user):
    from apps.technician_portal.models import Repair, Replacement

    customer = quote.customer
    fleet_unit = '' if customer.is_individual else (line.unit_number or quote.unit_number)
    common = dict(
        tenant=quote.tenant,
        customer=customer,
        technician=technician,
        quote=quote,
        unit_number=fleet_unit,
        vehicle_year=quote.vehicle_year,
        vehicle_make=quote.vehicle_make,
        vehicle_model=quote.vehicle_model,
        description=line.description,
        cost_override=_override_for(line.unit_price, customer),
        override_reason=f"Quoted price — quote {quote.quote_number}",
        # The acceptance IS the approval. Set explicitly so
        # resolve_initial_shop_status is never consulted.
        queue_status='APPROVED',
        no_tax=quote.no_tax or not line.taxable,
        internal_notes=f"Created from quote {quote.quote_number}.",
    )
    if line.service_type == 'REPAIR':
        job = Repair(damage_type=line.damage_type or '', **common)
    else:
        job = Replacement(glass_position=line.glass_position or '', **common)
    job.needs_assignment = needs_assignment
    if actor_user is not None:
        job._assignment_actor_user_id = actor_user.id
    return job


@transaction.atomic
def accept_quote(quote, *, via, actor_user=None, actor_name=''):
    """Accept the quote and create its jobs. Returns the created jobs.

    `via` is one of Quote.ACCEPTED_VIA_CHOICES. Locks the quote row so two
    clicks on the emailed link cannot create the jobs twice.
    """
    from apps.tenants.services.usage_service import UsageService
    from apps.technician_portal.models import JobCharge

    quote = Quote.objects.select_for_update().select_related('customer', 'tenant').get(pk=quote.pk)
    if quote.status not in Quote.OPEN_STATUSES:
        raise QuoteError('This quote has already been answered.')
    if quote.is_expired or quote.valid_until < timezone.localdate():
        raise QuoteError(
            f"This quote expired on {quote.valid_until:%B %-d, %Y}. "
            "Ask the shop for an updated one."
        )

    lines = list(quote.line_items.all())
    job_lines = [li for li in lines if li.creates_jobs]
    if not job_lines:
        raise QuoteError('This quote has no repair or replacement on it to schedule.')
    job_count = sum(li.quantity for li in job_lines)

    allowed, limit_msg = UsageService(quote.tenant).can_create_repairs(job_count)
    if not allowed:
        raise QuoteError(limit_msg or 'The shop has reached its plan limit for this month.')

    created = []
    for line in job_lines:
        service_type = 'replacement' if line.service_type == 'REPLACEMENT' else 'repair'
        technician, needs_assignment = _pick_technician(
            quote.tenant, actor_user, service_type, quote.customer,
        )
        if technician is None:
            raise QuoteError('The shop has no active technician to schedule this with yet.')
        for _ in range(line.quantity):
            job = _build_job(quote, line, technician, needs_assignment, actor_user)
            job.save()
            if needs_assignment:
                from apps.technician_portal.services.assignments import notify_needs_assignment
                try:
                    notify_needs_assignment(job)
                except Exception:  # pragma: no cover — notification must not block acceptance
                    logger.exception('needs-assignment notification failed for quote %s', quote.pk)
            created.append(job)

    # "Other" lines (trip charge, disposal) ride on the first job as extra
    # charges — exactly what the job form does with them, so invoicing picks
    # them up as free-form lines.
    first = created[0]
    field = 'replacement' if first.__class__.__name__ == 'Replacement' else 'repair'
    for line in lines:
        if line.creates_jobs:
            continue
        JobCharge.objects.create(
            tenant=quote.tenant,
            description=line.description,
            amount=line.amount,
            taxable=line.taxable and not quote.no_tax,
            **{field: first},
        )

    now = timezone.now()
    quote.status = 'ACCEPTED'
    quote.responded_at = now
    quote.accepted_via = via
    quote.responded_by_name = (actor_name or '')[:100]
    quote.save(update_fields=['status', 'responded_at', 'accepted_via', 'responded_by_name', 'updated_at'])

    _notify_shop_of_response(quote, created)
    return created


@transaction.atomic
def decline_quote(quote, *, via, reason='', actor_name=''):
    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    if quote.status not in Quote.OPEN_STATUSES:
        raise QuoteError('This quote has already been answered.')
    quote.status = 'DECLINED'
    quote.responded_at = timezone.now()
    quote.accepted_via = via
    quote.responded_by_name = (actor_name or '')[:100]
    quote.decline_reason = (reason or '')[:2000]
    quote.save(update_fields=[
        'status', 'responded_at', 'accepted_via', 'responded_by_name', 'decline_reason', 'updated_at',
    ])
    _notify_shop_of_response(quote, [])
    return quote


def _notify_shop_of_response(quote, jobs):
    """Tell the shop in-app. Best effort; never fails the response."""
    from apps.technician_portal.models import Technician, TechnicianNotification

    try:
        if quote.accepted_via == 'shop':
            return  # they just did it themselves
        vehicle = quote.get_vehicle_label()
        where = f" on {vehicle}" if vehicle else ''
        if quote.status == 'ACCEPTED':
            message = (f"{quote.customer.name} accepted quote {quote.quote_number}{where} — "
                       f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} created (${quote.total:,.2f}).")
        else:
            message = f"{quote.customer.name} declined quote {quote.quote_number}{where}."
            if quote.decline_reason:
                message += f" Reason: {quote.decline_reason[:200]}"
        recipients = set()
        for job in jobs:
            recipients.add(job.technician_id)
        for tech in Technician.objects.filter(tenant=quote.tenant, is_active=True, is_manager=True):
            recipients.add(tech.id)
        if quote.created_by_id:
            actor_tech = Technician.objects.filter(tenant=quote.tenant, user_id=quote.created_by_id).first()
            if actor_tech:
                recipients.add(actor_tech.id)
        first_repair = next((j for j in jobs if j.__class__.__name__ == 'Repair'), None)
        for tech_id in recipients:
            TechnicianNotification.objects.create(
                technician_id=tech_id, message=message, read=False,
                repair=first_repair,
            )
    except Exception:  # pragma: no cover
        logger.exception('quote response notification failed for quote %s', quote.pk)


@transaction.atomic
def revise_quote(quote, actor_user=None):
    """Clone into a fresh DRAFT that supersedes this one.

    Repair lines are re-priced on today's numbers only when the shop edits
    them; the clone starts from the old prices so a one-line tweak is a
    one-line tweak. The clone gets a new number and a new validity window.
    """
    from apps.billing.models import BillingConfig

    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    if not quote.can_be_revised:
        raise QuoteError('Only a sent, declined or expired quote can be revised.')
    config = BillingConfig.get_for_tenant(quote.tenant)
    today = timezone.localdate()
    clone = Quote.objects.create(
        tenant=quote.tenant,
        quote_number=BillingConfig.allocate_quote_number(quote.tenant),
        customer=quote.customer,
        created_by=actor_user if (actor_user is not None and actor_user.is_authenticated) else quote.created_by,
        status='DRAFT',
        quote_date=today,
        valid_until=today + timedelta(days=config.quote_valid_days or 30),
        unit_number=quote.unit_number,
        vehicle_year=quote.vehicle_year,
        vehicle_make=quote.vehicle_make,
        vehicle_model=quote.vehicle_model,
        no_tax=quote.no_tax,
        notes=quote.notes,
        internal_notes=quote.internal_notes,
        supersedes=quote,
    )
    for li in quote.line_items.all():
        QuoteLineItem.objects.create(
            quote=clone, service_type=li.service_type, description=li.description,
            unit_number=li.unit_number, damage_type=li.damage_type,
            glass_position=li.glass_position, quantity=li.quantity,
            unit_price=li.unit_price, amount=li.amount, taxable=li.taxable,
            sort_order=li.sort_order,
        )
    recalculate_totals(clone)
    if quote.status != 'DECLINED':
        quote.status = 'SUPERSEDED'
    else:
        # A declined quote keeps its answer; the chain still shows the revision.
        pass
    quote.save(update_fields=['status', 'updated_at'])
    return clone


# --- delivery ----------------------------------------------------------------

def resolve_recipient(quote):
    """Where the quote email goes: the invoice pipeline's answer for this
    customer (billing email, else main email), '' when nothing is on file."""
    from apps.billing.services.invoice_send_service import InvoiceSendService
    return InvoiceSendService.resolve_recipient(quote.customer) or ''


def email_kwargs(quote, to_email):
    """The send_branded_email kwargs for a quote — split out so
    `manage.py preview_emails` renders exactly what a real send produces."""
    shop = quote.tenant.name
    total = f"${quote.total:,.2f}"
    rows = []
    vehicle = quote.get_vehicle_label()
    if vehicle:
        rows.append(('Vehicle', vehicle))
    for li in quote.line_items.all():
        label = li.description
        if li.quantity > 1:
            label = f"{li.description} × {li.quantity}"
        rows.append((label, f"${li.amount:,.2f}"))
    if quote.tax_amount > 0:
        rows.append(('Subtotal', f"${quote.subtotal:,.2f}"))
        rows.append(('Tax', f"${quote.tax_amount:,.2f}"))
    rows.append(('Total', total, 'strong money'))
    rows.append(('Good through', quote.valid_until.strftime('%B %-d, %Y')))
    paragraphs = []
    if quote.notes.strip():
        paragraphs.append(quote.notes.strip())
    url = public_url(quote)
    return dict(
        subject=f"Your quote from {shop} — {total}",
        headline=f"Quote {quote.quote_number}: {total}",
        lede=(f"{shop} has priced the work below. Review it and accept online — "
              f"nothing is scheduled until you do."),
        body_paragraphs=paragraphs,
        detail_rows=rows,
        button_text='Review and accept',
        button_url=url,
        note=(f"This quote is good through {quote.valid_until:%B %-d, %Y}. "
              f"If the link above does not work, copy this address into your browser: {url}"),
        preheader=f"Quote {quote.quote_number} for {total}, good through {quote.valid_until:%b %-d}.",
        tenant=quote.tenant,
        recipient_list=[to_email],
    )


def send_quote(quote, *, to_email=None, actor_user=None):
    """Email the quote and move it to SENT. Returns the address it went to."""
    from core.email_utils import send_branded_email

    if quote.status not in Quote.OPEN_STATUSES:
        raise QuoteError('This quote has already been answered and cannot be re-sent.')
    if not quote.line_items.exists():
        raise QuoteError('Add at least one line before sending.')
    if quote.valid_until < timezone.localdate():
        raise QuoteError('The "good through" date is in the past — extend it before sending.')
    to_email = (to_email or resolve_recipient(quote)).strip()
    if not to_email:
        raise QuoteError(
            f"{quote.customer.name} has no email on file. Add one on the customer page, "
            "or enter one here."
        )

    recalculate_totals(quote)
    sent = send_branded_email(**email_kwargs(quote, to_email))
    if not sent:
        raise QuoteError('The email could not be sent. Try again in a moment.')

    now = timezone.now()
    if quote.sent_at is None:
        quote.sent_at = now
    quote.last_sent_at = now
    quote.sent_to_email = to_email
    quote.status = 'SENT'
    quote.save(update_fields=['sent_at', 'last_sent_at', 'sent_to_email', 'status', 'updated_at'])
    return to_email


def record_view(quote):
    """Customer opened the link. Mail scanners hit links seconds after
    delivery; the invoice page's grace window applies here too."""
    grace = int(getattr(settings, 'INVOICE_VIEW_GRACE_SECONDS', 300) or 0)
    if quote.last_sent_at and (timezone.now() - quote.last_sent_at).total_seconds() < grace:
        return
    now = timezone.now()
    updates = {'view_count': quote.view_count + 1}
    if quote.first_viewed_at is None:
        updates['first_viewed_at'] = now
    Quote.objects.filter(pk=quote.pk).update(**updates)
