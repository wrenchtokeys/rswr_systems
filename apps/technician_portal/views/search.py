"""
Global search across jobs, customers and invoices.

Before this, search existed only inside the job list and the customer list,
each scoped to its own page — so finding "Truck 42" meant first knowing which
page to be on. This is the one box that answers "where is that thing".

Everything here reuses the visibility rules the list pages already enforce:
_visible_jobs() for repairs/replacements, and tenant scoping everywhere else.
Search must never become a side channel that reveals a job the user could not
open from the list.
"""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render

from apps.billing.models import Invoice
from apps.technician_portal.decorators import technician_required, is_tenant_admin
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.technician_portal.views.jobs import _visible_jobs
from common.auth import can_access
from core.models import Customer

# Enough to show the useful hits without turning a one-character typo into a
# full table scan render. The template links to the filtered list pages for more.
PER_SECTION_LIMIT = 8


def _job_matches(model, tenant, technician, user_is_admin, query):
    """Jobs whose unit, customer, vehicle or id looks like the query."""
    predicate = (
        Q(unit_number__icontains=query)
        | Q(customer__name__icontains=query)
        | Q(vehicle_make__icontains=query)
        | Q(vehicle_model__icontains=query)
    )
    # Bare numbers are usually someone pasting a job id.
    if query.isdigit():
        predicate |= Q(id=int(query))

    return (
        _visible_jobs(model, tenant, technician, user_is_admin)
        .filter(predicate)
        .select_related('customer', 'technician__user')
        .order_by('-service_date')[:PER_SECTION_LIMIT]
    )


@technician_required
def global_search(request):
    """Tenant-scoped search over jobs, customers and invoices."""
    tenant = getattr(request, 'tenant', None)
    user_is_admin = is_tenant_admin(request.user, tenant=tenant)
    query = (request.GET.get('q') or '').strip()

    technician = (
        Technician.objects.filter(user=request.user, tenant=tenant).first()
        if tenant else None
    )

    # An empty search isn't an error — just send them somewhere useful.
    if not query:
        return redirect('job_list')

    if not tenant:
        messages.error(request, "No shop context. Please log in again.")
        return redirect('technician_dashboard')

    repairs = _job_matches(Repair, tenant, technician, user_is_admin, query)
    replacements = _job_matches(Replacement, tenant, technician, user_is_admin, query)

    jobs = sorted(
        [(r, 'repair') for r in repairs] + [(r, 'replacement') for r in replacements],
        key=lambda pair: pair[0].service_date,
        reverse=True,
    )[:PER_SECTION_LIMIT]

    # Customers and invoices are shop-level records — gate them on the same
    # permission the nav uses to decide whether to show those sections at all,
    # rather than inventing a third rule here.
    customers = []
    if can_access(request.user, 'customers', tenant):
        customers = list(
            Customer.objects.filter(tenant=tenant)
            .filter(
                Q(name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone__icontains=query)
            )
            .order_by('name')[:PER_SECTION_LIMIT]
        )

    invoices = []
    if can_access(request.user, 'invoices', tenant):
        invoices = list(
            Invoice.objects.filter(tenant=tenant)
            .filter(
                Q(invoice_number__icontains=query)
                | Q(customer__name__icontains=query)
            )
            .select_related('customer')
            .order_by('-invoice_date')[:PER_SECTION_LIMIT]
        )

    total = len(jobs) + len(customers) + len(invoices)

    # One hit, one obvious destination — don't make them tap a results page.
    if total == 1:
        if jobs:
            job, kind = jobs[0]
            return redirect(
                'repair_detail' if kind == 'repair' else 'replacement_detail',
                job.id,
            )
        if customers:
            return redirect('customer_detail', customer_id=customers[0].id)
        return redirect('owner_invoice_detail', invoice_id=invoices[0].id)

    return render(request, 'technician_portal/search_results.html', {
        'query': query,
        'jobs': jobs,
        'customers': customers,
        'invoices': invoices,
        'total': total,
        'per_section_limit': PER_SECTION_LIMIT,
    })
