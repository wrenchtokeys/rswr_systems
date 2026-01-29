"""
Customer management views for the technician portal.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Q, Count
from django.views.decorators.http import require_POST

from apps.technician_portal.models import Technician, Repair, UnitRepairCount
from core.models import Customer
from apps.technician_portal.forms import CustomerForm
from apps.technician_portal.decorators import technician_required, admin_required

import logging

logger = logging.getLogger(__name__)


@admin_required
def create_customer(request):
    """Create a new customer (admin only)."""
    tenant = getattr(request, 'tenant', None)

    if request.method == 'POST':
        form = CustomerForm(request.POST, tenant=tenant)
        if form.is_valid():
            customer = form.save(commit=False)
            if tenant:
                customer.tenant = tenant
            customer.save()
            messages.success(request, f"Customer '{customer.name}' has been created successfully.")
            return redirect('technician_dashboard')
    else:
        form = CustomerForm(tenant=tenant)
    return render(request, 'technician_portal/customer_form.html', {'form': form})


@technician_required
def customer_list(request):
    """List all customers accessible to the current technician."""
    tenant = getattr(request, 'tenant', None)

    if request.user.is_staff:
        customers = Customer.objects.all()
        if tenant:
            customers = customers.filter(tenant=tenant)
        customers = customers.order_by('name')
    else:
        if hasattr(request.user, 'technician'):
            technician = request.user.technician
            repair_qs = Repair.objects.filter(technician=technician)
            if tenant:
                repair_qs = repair_qs.filter(tenant=tenant)
            customer_ids = repair_qs.values_list('customer_id', flat=True).distinct()
            customers = Customer.objects.filter(id__in=customer_ids)
            if tenant:
                customers = customers.filter(tenant=tenant)
            customers = customers.order_by('name')
        else:
            customers = Customer.objects.none()

    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # Annotate with active repair counts in a single query (avoids N+1)
    customers = customers.annotate(
        active_repairs_count=Count(
            'repair',
            filter=~Q(repair__queue_status='COMPLETED')
        )
    )

    return render(request, 'technician_portal/customer_list.html', {
        'customers': customers,
        'search_query': search_query,
        'is_admin': request.user.is_staff
    })


@technician_required
def customer_details(request, customer_id):
    """View customer details with unit listing for current technician."""
    tenant = getattr(request, 'tenant', None)
    technician = get_object_or_404(Technician, user=request.user)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    customer = get_object_or_404(qs, id=customer_id)

    repairs = Repair.objects.filter(
        technician=technician,
        customer=customer
    ).exclude(queue_status__in=['REQUESTED', 'PENDING'])
    if tenant:
        repairs = repairs.filter(tenant=tenant)

    unit_search = request.GET.get('unit_search', '')
    if unit_search:
        repairs = repairs.filter(unit_number__icontains=unit_search)

    units = repairs.values_list('unit_number', flat=True).distinct()

    # Determine if user can edit primary technician (admin, owner, or manager)
    can_edit_customer = request.user.is_staff or technician.is_manager

    # Provide available technicians for the primary tech dropdown
    available_technicians = Technician.objects.filter(is_active=True)
    if tenant:
        available_technicians = available_technicians.filter(tenant=tenant)
    available_technicians = available_technicians.order_by('user__first_name')

    return render(request, 'technician_portal/customer_details.html', {
        'customer': customer,
        'units': units,
        'unit_search': unit_search,
        'can_edit_customer': can_edit_customer,
        'available_technicians': available_technicians,
    })


@technician_required
def unit_details(request, customer_id, unit_number):
    """View all repairs for a specific unit."""
    tenant = getattr(request, 'tenant', None)
    technician = get_object_or_404(Technician, user=request.user)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    customer = get_object_or_404(qs, id=customer_id)

    repairs = Repair.objects.filter(
        technician=technician,
        customer=customer,
        unit_number=unit_number
    ).exclude(
        queue_status__in=['REQUESTED', 'PENDING']
    ).select_related('customer', 'technician__user')
    if tenant:
        repairs = repairs.filter(tenant=tenant)

    return render(request, 'technician_portal/unit_details.html', {
        'customer': customer,
        'unit_number': unit_number,
        'repairs': repairs,
    })


@technician_required
def mark_unit_replaced(request, customer_id, unit_number):
    """Mark a unit's windshield as replaced, resetting repair count."""
    tenant = getattr(request, 'tenant', None)
    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    customer = get_object_or_404(qs, id=customer_id)
    unit_repair_count = get_object_or_404(UnitRepairCount, customer=customer, unit_number=unit_number)
    unit_repair_count.repair_count = 0
    unit_repair_count.save()
    messages.success(request, f"Unit #{unit_number} for {customer.name} has been marked as replaced. Repair count reset to 0.")
    return redirect('customer_detail', customer_id=customer_id)


@technician_required
@require_POST
def update_primary_technician(request, customer_id):
    """Update the primary technician for a customer (manager/admin only)."""
    tenant = getattr(request, 'tenant', None)

    if not request.user.is_staff:
        if not hasattr(request.user, 'technician') or not request.user.technician.is_manager:
            messages.error(request, "Only managers or admins can change a customer's primary technician.")
            return redirect('customer_detail', customer_id=customer_id)

    qs = Customer.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    customer = get_object_or_404(qs, id=customer_id)

    tech_id = request.POST.get('primary_technician')
    if tech_id:
        tech = get_object_or_404(Technician, id=tech_id, is_active=True)
        customer.primary_technician = tech
        customer.save(update_fields=['primary_technician'])
        messages.success(request, f"Primary technician set to {tech.user.get_full_name()}.")
    else:
        customer.primary_technician = None
        customer.save(update_fields=['primary_technician'])
        messages.success(request, "Primary technician cleared.")

    return redirect('customer_detail', customer_id=customer_id)
