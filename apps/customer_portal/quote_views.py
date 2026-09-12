"""
Customer-portal quotes (B3): the logged-in customer's quotes, and accepting
or declining one in the portal. The same service the public link uses, so
the two doors lead to the same room.
"""

import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.billing.quote_models import Quote
from apps.billing.services import quote_service
from apps.billing.services.quote_service import QuoteError
from apps.customer_portal.views import _get_customer_user_for_tenant, customer_required

logger = logging.getLogger(__name__)


def _customer(request):
    customer_user = _get_customer_user_for_tenant(request)
    return customer_user, customer_user.customer


@customer_required
def customer_quotes(request):
    customer_user, customer = _customer(request)
    Quote.expire_stale(customer.tenant)
    quotes = list(
        Quote.objects.filter(customer=customer, tenant=customer.tenant)
        .exclude(status='DRAFT')
        .order_by('-quote_date', '-id')
    )
    open_quotes = [q for q in quotes if q.status == 'SENT']
    return render(request, 'customer_portal/quotes.html', {
        'quotes': quotes,
        'open_quotes': open_quotes,
        'open_count': len(open_quotes),
        'customer': customer,
    })


@customer_required
def customer_quote_detail(request, quote_id):
    customer_user, customer = _customer(request)
    Quote.expire_stale(customer.tenant)
    quote = get_object_or_404(
        Quote.objects.exclude(status='DRAFT'),
        id=quote_id, customer=customer, tenant=customer.tenant,
    )
    if quote.status == 'SENT' and quote.first_viewed_at is None:
        quote_service.record_view(quote)
    return render(request, 'customer_portal/quote_detail.html', {
        'quote': quote,
        'line_items': quote.line_items.all(),
        'jobs': quote.jobs if quote.status == 'ACCEPTED' else [],
        'customer': customer,
        'can_respond': quote.status == 'SENT' and not quote.is_expired,
    })


@customer_required
@require_POST
def customer_quote_respond(request, quote_id):
    customer_user, customer = _customer(request)
    quote = get_object_or_404(
        Quote.objects.exclude(status='DRAFT'),
        id=quote_id, customer=customer, tenant=customer.tenant,
    )
    action = request.POST.get('action', '')
    name = request.user.get_full_name() or request.user.get_username()
    try:
        if action == 'accept':
            jobs = quote_service.accept_quote(quote, via='portal', actor_name=name)
            messages.success(
                request,
                f'Quote {quote.quote_number} accepted. {len(jobs)} job'
                f'{"s are" if len(jobs) != 1 else " is"} on the shop\'s schedule.',
            )
        elif action == 'decline':
            quote_service.decline_quote(
                quote, via='portal', reason=request.POST.get('reason', ''), actor_name=name,
            )
            messages.success(request, f'Quote {quote.quote_number} declined. The shop has been told.')
        else:
            messages.error(request, 'Choose accept or decline.')
    except QuoteError as e:
        messages.error(request, str(e))
    return redirect('customer_quote_detail', quote_id=quote.id)
