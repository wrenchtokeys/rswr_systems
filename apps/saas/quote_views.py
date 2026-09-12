"""
Shop-side quotes (B3) and the public tokened quote page.

Split out of apps/saas/views.py (6,000+ lines) the way technician_portal
splits its views; urls.py imports this module directly.

Access: anyone with 'repairs' access (`technician_required`) can quote — a
tech in the field is who meets the customer. The one thing gated on
`is_manager` is typing a repair price that differs from the shop's own
pricing, the same rule the job form applies to a custom price.
"""

import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.models import BillingConfig
from apps.billing.quote_models import Quote, QuoteLineItem
from apps.billing.services import quote_service
from apps.billing.services.quote_service import QuoteError
from apps.technician_portal.decorators import technician_required
from apps.technician_portal.models import Repair, Replacement, Technician
from core.models import Customer

logger = logging.getLogger(__name__)

STATUS_PILLS = [
    ('open', 'Open'),
    ('accepted', 'Accepted'),
    ('declined', 'Declined'),
    ('expired', 'Expired'),
    ('all', 'All'),
]


def _tenant(request):
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Could not determine your shop. Please log in again.')
    return tenant


def _actor_tech(request, tenant):
    return Technician.objects.filter(user=request.user, tenant=tenant).first()


def _is_manager(request, tenant):
    from common.auth import get_user_role
    role = get_user_role(request.user, tenant=tenant)
    if role in ('superuser', 'owner', 'manager'):
        return True
    tech = _actor_tech(request, tenant)
    return bool(tech and tech.is_manager)


# --- list / detail -----------------------------------------------------------

@technician_required
def quote_list(request):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    Quote.expire_stale(tenant)

    status_filter = request.GET.get('status', 'open')
    if status_filter not in dict(STATUS_PILLS):
        status_filter = 'open'
    customer_filter = request.GET.get('customer', '')

    qs = Quote.objects.filter(tenant=tenant).select_related('customer')
    if status_filter == 'open':
        qs = qs.filter(status__in=Quote.OPEN_STATUSES)
    elif status_filter == 'accepted':
        qs = qs.filter(status='ACCEPTED')
    elif status_filter == 'declined':
        qs = qs.filter(status='DECLINED')
    elif status_filter == 'expired':
        qs = qs.filter(status__in=('EXPIRED', 'SUPERSEDED'))
    if customer_filter.isdigit():
        qs = qs.filter(customer_id=int(customer_filter))

    open_qs = Quote.objects.filter(tenant=tenant, status__in=Quote.OPEN_STATUSES)
    open_stats = open_qs.aggregate(n=Count('id'), total=Sum('total'))
    month_start = timezone.localdate().replace(day=1)
    accepted_month = Quote.objects.filter(
        tenant=tenant, status='ACCEPTED', responded_at__date__gte=month_start,
    ).aggregate(n=Count('id'), total=Sum('total'))
    awaiting = open_qs.filter(status='SENT').count()

    return render(request, 'saas/quote_list.html', {
        'tenant': tenant,
        'quotes': qs[:200],
        'status_pills': STATUS_PILLS,
        'status_filter': status_filter,
        'customer_filter': customer_filter,
        'customers': Customer.objects.filter(tenant=tenant).order_by('name'),
        'open_count': open_stats['n'] or 0,
        'open_total': open_stats['total'] or Decimal('0.00'),
        'awaiting_count': awaiting,
        'accepted_month_count': accepted_month['n'] or 0,
        'accepted_month_total': accepted_month['total'] or Decimal('0.00'),
    })


@technician_required
def quote_detail(request, quote_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    Quote.expire_stale(tenant)
    quote = get_object_or_404(
        Quote.objects.select_related('customer', 'supersedes'), id=quote_id, tenant=tenant,
    )
    return render(request, 'saas/quote_detail.html', {
        'tenant': tenant,
        'quote': quote,
        'line_items': quote.line_items.all(),
        'jobs': quote.jobs,
        'revisions': quote.revisions.all(),
        'recipient_email': quote.sent_to_email or quote_service.resolve_recipient(quote),
        'public_url': quote_service.public_url(quote),
        'can_manage_price': _is_manager(request, tenant),
    })


# --- create / edit -----------------------------------------------------------

_DEC_RE = re.compile(r'^-?\d+(\.\d{1,2})?$')


def _parse_money(raw):
    raw = (raw or '').strip().replace('$', '').replace(',', '')
    if raw == '':
        return None
    if not _DEC_RE.match(raw):
        raise ValueError(raw)
    return Decimal(raw).quantize(Decimal('0.01'))


def _parse_lines(request):
    """The line rows from the POST arrays. Rows with neither a description
    nor a price are ignored (an empty spare row). Returns (lines, errors)."""
    types = request.POST.getlist('line_type')
    descs = request.POST.getlist('line_desc')
    units = request.POST.getlist('line_unit')
    qtys = request.POST.getlist('line_qty')
    prices = request.POST.getlist('line_price')
    damages = request.POST.getlist('line_damage')
    glass = request.POST.getlist('line_glass')
    n = max(len(types), len(descs), len(prices))

    def at(lst, i, default=''):
        return lst[i] if i < len(lst) else default

    lines, errors = [], []
    for i in range(n):
        desc = at(descs, i).strip()
        price_raw = at(prices, i).strip()
        if not desc and not price_raw:
            continue
        service_type = at(types, i, 'REPAIR').strip().upper()
        if service_type not in dict(QuoteLineItem.SERVICE_TYPE_CHOICES):
            service_type = 'REPAIR'
        if not desc:
            errors.append(f'Line {i + 1} needs a description.')
        try:
            qty = int(at(qtys, i, '1') or 1)
        except ValueError:
            qty = 0
        if qty < 1:
            errors.append(f'Line {i + 1}: quantity must be at least 1.')
            qty = 1
        try:
            price = _parse_money(price_raw)
        except (ValueError, InvalidOperation):
            errors.append(f'Line {i + 1}: "{price_raw}" is not a price.')
            price = None
        if price is not None and price < 0:
            errors.append(f'Line {i + 1}: a price cannot be negative.')
        lines.append({
            'service_type': service_type,
            'description': desc[:500],
            'unit_number': at(units, i).strip()[:50],
            'quantity': qty,
            'unit_price': price,  # None = "use the shop's price" (repair only)
            'damage_type': at(damages, i).strip()[:100],
            'glass_position': at(glass, i).strip()[:30],
            'sort_order': i,
        })
    return lines, errors


def _quote_form(request, tenant, quote=None):
    """Create and edit share one form. GET renders; POST validates, saves,
    and redirects to the detail page."""
    config = BillingConfig.get_for_tenant(tenant)
    today = timezone.localdate()
    customers = Customer.objects.filter(tenant=tenant).order_by('name')
    is_manager = _is_manager(request, tenant)
    shop_tax_enabled = bool(config.tax_enabled)

    if quote is not None and not quote.can_be_edited:
        messages.warning(request, f'Quote {quote.quote_number} has been answered and can no longer be edited. Revise it instead.')
        return redirect('quote_detail', quote_id=quote.id)

    if request.method == 'POST':
        errors = []
        customer = None
        cid = request.POST.get('customer', '')
        if cid.isdigit():
            customer = customers.filter(id=int(cid)).first()
        if customer is None:
            errors.append('Pick a customer.')

        valid_until_raw = request.POST.get('valid_until', '').strip()
        try:
            valid_until = timezone.datetime.strptime(valid_until_raw, '%Y-%m-%d').date()
        except ValueError:
            valid_until = None
            errors.append('Enter the "good through" date.')
        if valid_until and valid_until < today:
            errors.append('The "good through" date cannot be in the past.')

        year_raw = request.POST.get('vehicle_year', '').strip()
        vehicle_year = None
        if year_raw:
            if year_raw.isdigit() and 1900 <= int(year_raw) <= today.year + 2:
                vehicle_year = int(year_raw)
            else:
                errors.append('Vehicle year does not look right.')

        lines, line_errors = _parse_lines(request)
        errors.extend(line_errors)
        if not lines:
            errors.append('Add at least one line.')
        elif not any(li['service_type'] in ('REPAIR', 'REPLACEMENT') for li in lines):
            errors.append('A quote needs at least one repair or replacement line — "Other" lines ride along with the work.')

        header_unit = request.POST.get('unit_number', '').strip()[:50]

        # Repair pricing: blank means "the shop's price for this vehicle";
        # a typed price that differs from it is a custom price, which is a
        # manager's call (the job form's rule).
        if customer is not None:
            for li in lines:
                if li['service_type'] == 'REPAIR':
                    unit_key = (li['unit_number'] or header_unit) if not customer.is_individual else ''
                    expected = quote_service.default_repair_price(customer, unit_key, tenant)
                    if li['unit_price'] is None:
                        li['unit_price'] = expected
                    elif li['unit_price'] != expected and not is_manager:
                        errors.append(
                            f'Line {li["sort_order"] + 1}: the shop price for this repair is ${expected:,.2f}. '
                            'Only a manager can quote a different price — leave it blank to use the shop price.'
                        )
                elif li['unit_price'] is None:
                    errors.append(f'Line {li["sort_order"] + 1} needs a price.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'saas/quote_form.html', _form_context(
                tenant, quote, customers, config, today, is_manager, shop_tax_enabled,
                posted=request.POST, posted_lines=lines,
            ))

        from django.db import transaction
        with transaction.atomic():
            creating = quote is None
            if creating:
                quote = Quote(
                    tenant=tenant,
                    quote_number=BillingConfig.allocate_quote_number(tenant),
                    created_by=request.user,
                    status='DRAFT',
                )
            quote.customer = customer
            quote.valid_until = valid_until
            quote.unit_number = '' if customer.is_individual else header_unit
            quote.vehicle_year = vehicle_year
            quote.vehicle_make = request.POST.get('vehicle_make', '').strip()[:50]
            quote.vehicle_model = request.POST.get('vehicle_model', '').strip()[:50]
            quote.no_tax = shop_tax_enabled and request.POST.get('charge_tax') != '1'
            quote.notes = request.POST.get('notes', '').strip()
            quote.internal_notes = request.POST.get('internal_notes', '').strip()
            quote.save()
            quote.line_items.all().delete()
            for li in lines:
                QuoteLineItem.objects.create(
                    quote=quote,
                    service_type=li['service_type'],
                    description=li['description'],
                    unit_number='' if customer.is_individual else li['unit_number'],
                    quantity=li['quantity'],
                    unit_price=li['unit_price'],
                    amount=li['unit_price'] * li['quantity'],
                    taxable=True,
                    damage_type=li['damage_type'] if li['service_type'] == 'REPAIR' else '',
                    glass_position=li['glass_position'] if li['service_type'] == 'REPLACEMENT' else '',
                    sort_order=li['sort_order'],
                )
            quote_service.recalculate_totals(quote)

        if request.POST.get('then') == 'send':
            try:
                to = quote_service.send_quote(quote, actor_user=request.user)
                messages.success(request, f'Quote {quote.quote_number} sent to {to}.')
            except QuoteError as e:
                messages.warning(request, f'Saved, but not sent: {e}')
        else:
            messages.success(request, f'Quote {quote.quote_number} {"created" if creating else "updated"}.')
        return redirect('quote_detail', quote_id=quote.id)

    return render(request, 'saas/quote_form.html', _form_context(
        tenant, quote, customers, config, today, is_manager, shop_tax_enabled,
        preselect_customer=request.GET.get('customer', ''),
    ))


def _form_context(tenant, quote, customers, config, today, is_manager, shop_tax_enabled,
                  posted=None, posted_lines=None, preselect_customer=''):
    default_valid = today + timedelta(days=config.quote_valid_days or 30)
    if posted is not None:
        header = {
            'customer_id': posted.get('customer', ''),
            'valid_until': posted.get('valid_until', ''),
            'unit_number': posted.get('unit_number', ''),
            'vehicle_year': posted.get('vehicle_year', ''),
            'vehicle_make': posted.get('vehicle_make', ''),
            'vehicle_model': posted.get('vehicle_model', ''),
            'charge_tax': posted.get('charge_tax') == '1',
            'notes': posted.get('notes', ''),
            'internal_notes': posted.get('internal_notes', ''),
        }
        lines = posted_lines or []
    elif quote is not None:
        header = {
            'customer_id': str(quote.customer_id),
            'valid_until': quote.valid_until.isoformat(),
            'unit_number': quote.unit_number,
            'vehicle_year': quote.vehicle_year or '',
            'vehicle_make': quote.vehicle_make,
            'vehicle_model': quote.vehicle_model,
            'charge_tax': not quote.no_tax,
            'notes': quote.notes,
            'internal_notes': quote.internal_notes,
        }
        lines = [{
            'service_type': li.service_type, 'description': li.description,
            'unit_number': li.unit_number, 'quantity': li.quantity,
            'unit_price': li.unit_price, 'damage_type': li.damage_type,
            'glass_position': li.glass_position,
        } for li in quote.line_items.all()]
    else:
        header = {
            'customer_id': preselect_customer if str(preselect_customer).isdigit() else '',
            'valid_until': default_valid.isoformat(),
            'unit_number': '', 'vehicle_year': '', 'vehicle_make': '', 'vehicle_model': '',
            'charge_tax': True, 'notes': '', 'internal_notes': '',
        }
        lines = []
    # One JSON blob of customer types so the form can flip the vehicle
    # fields between "Unit #" and year/make/model without a round trip.
    individual_ids = list(customers.filter(customer_type__in=Customer.INDIVIDUAL_TYPES).values_list('id', flat=True))
    return {
        'tenant': tenant,
        'quote': quote,
        'customers': customers,
        'individual_ids': individual_ids,
        'header': header,
        'lines': lines,
        'is_manager': is_manager,
        'shop_tax_enabled': shop_tax_enabled,
        'offers_repairs': tenant.offers_repairs,
        'offers_replacements': tenant.offers_replacements,
        'damage_types': [c for c in Repair.DAMAGE_TYPE_CHOICES if c[0]],
        'glass_positions': Replacement.GLASS_POSITION_CHOICES,
        'valid_days': config.quote_valid_days or 30,
        'today': today,
    }


@technician_required
def quote_create(request):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    return _quote_form(request, tenant)


@technician_required
def quote_edit(request, quote_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    quote = get_object_or_404(Quote, id=quote_id, tenant=tenant)
    return _quote_form(request, tenant, quote)


# --- actions -----------------------------------------------------------------

@technician_required
@require_POST
def quote_send(request, quote_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    quote = get_object_or_404(Quote, id=quote_id, tenant=tenant)
    to_email = request.POST.get('to_email', '').strip()
    try:
        to = quote_service.send_quote(quote, to_email=to_email or None, actor_user=request.user)
        messages.success(request, f'Quote {quote.quote_number} sent to {to}.')
    except QuoteError as e:
        messages.error(request, str(e))
    return redirect('quote_detail', quote_id=quote.id)


@technician_required
@require_POST
def quote_mark_accepted(request, quote_id):
    """The customer said yes in person or on the phone — record it and
    create the jobs, exactly as the link would have."""
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    quote = get_object_or_404(Quote, id=quote_id, tenant=tenant)
    try:
        jobs = quote_service.accept_quote(
            quote, via='shop', actor_user=request.user,
            actor_name=request.user.get_full_name() or request.user.get_username(),
        )
        messages.success(
            request,
            f'Quote {quote.quote_number} accepted — {len(jobs)} job{"s" if len(jobs) != 1 else ""} created.',
        )
    except QuoteError as e:
        messages.error(request, str(e))
    return redirect('quote_detail', quote_id=quote.id)


@technician_required
@require_POST
def quote_mark_declined(request, quote_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    quote = get_object_or_404(Quote, id=quote_id, tenant=tenant)
    try:
        quote_service.decline_quote(
            quote, via='shop', reason=request.POST.get('reason', ''),
            actor_name=request.user.get_full_name() or request.user.get_username(),
        )
        messages.success(request, f'Quote {quote.quote_number} marked declined.')
    except QuoteError as e:
        messages.error(request, str(e))
    return redirect('quote_detail', quote_id=quote.id)


@technician_required
@require_POST
def quote_revise(request, quote_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    quote = get_object_or_404(Quote, id=quote_id, tenant=tenant)
    try:
        clone = quote_service.revise_quote(quote, actor_user=request.user)
    except QuoteError as e:
        messages.error(request, str(e))
        return redirect('quote_detail', quote_id=quote.id)
    messages.success(request, f'Revision {clone.quote_number} created from {quote.quote_number}. Edit it, then send.')
    return redirect('quote_edit', quote_id=clone.id)


@technician_required
@require_POST
def quote_delete(request, quote_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('login')
    quote = get_object_or_404(Quote, id=quote_id, tenant=tenant)
    if quote.status != 'DRAFT':
        messages.error(request, 'Only a draft can be deleted. A sent quote stays on record — decline or revise it.')
        return redirect('quote_detail', quote_id=quote.id)
    number = quote.quote_number
    quote.delete()
    messages.success(request, f'Draft {number} deleted.')
    return redirect('quote_list')


# --- public tokened page -----------------------------------------------------

def _resolve_public_quote(quote_id, token):
    if not quote_service.token_matches(quote_id, token):
        return None
    try:
        return Quote.objects.select_related('customer', 'tenant').get(id=quote_id)
    except Quote.DoesNotExist:
        return None


def _public_context(quote, state='', error=''):
    tenant = quote.tenant
    return {
        'quote': quote,
        'line_items': quote.line_items.all(),
        'company_name': tenant.name,
        'company_phone': getattr(tenant, 'business_phone', '') or '',
        'company_email': getattr(tenant, 'business_email', '') or '',
        'status': quote.effective_status,
        'state': state,
        'error': error,
        'respond_url': f"/quote/{quote.id}/{quote_service.public_token(quote.id)}/respond/",
        'jobs': quote.jobs if quote.status == 'ACCEPTED' else [],
    }


def public_quote_view(request, quote_id, token):
    """Read-only on GET, always. Mail gateways fetch every link they scan
    (the invoice pay page learned this the hard way), so accepting is a
    POST from this page, never a click on a link."""
    quote = _resolve_public_quote(quote_id, token)
    if quote is None:
        return render(request, '404.html', status=404)
    if quote.status == 'SENT' and quote.is_expired:
        Quote.objects.filter(pk=quote.pk, status='SENT').update(status='EXPIRED')
        quote.status = 'EXPIRED'
    try:
        from rs_systems.views import _is_scanner_request
        if not _is_scanner_request(request):
            quote_service.record_view(quote)
    except Exception:  # pragma: no cover
        pass
    return render(request, 'billing/public_quote_view.html', _public_context(quote))


@require_POST
def public_quote_respond(request, quote_id, token):
    quote = _resolve_public_quote(quote_id, token)
    if quote is None:
        return render(request, '404.html', status=404)
    action = request.POST.get('action', '')
    name = request.POST.get('name', '').strip()
    if action not in ('accept', 'decline'):
        return render(request, 'billing/public_quote_view.html',
                      _public_context(quote, error='Choose accept or decline.'), status=400)
    if not name:
        return render(request, 'billing/public_quote_view.html',
                      _public_context(quote, error='Please type your name so the shop knows who answered.'), status=400)
    try:
        if action == 'accept':
            quote_service.accept_quote(quote, via='link', actor_name=name)
            state = 'accepted'
        else:
            quote_service.decline_quote(quote, via='link', reason=request.POST.get('reason', ''), actor_name=name)
            state = 'declined'
    except QuoteError as e:
        quote.refresh_from_db()
        return render(request, 'billing/public_quote_view.html',
                      _public_context(quote, error=str(e)), status=409)
    quote.refresh_from_db()
    return render(request, 'billing/public_quote_view.html', _public_context(quote, state=state))
