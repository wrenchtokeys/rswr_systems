"""
Clawdbot Views - Amelia's API orchestration layer.

This is the experimental namespace (/clawdbot/).
Billing endpoints live canonically at /api/billing/ and are
proxied here for backward compatibility.

Non-billing endpoints (status, health, customer/repair queries)
remain here as they're clawdbot-specific.

Security: Data endpoints require authentication and tenant scoping.
         Status/health endpoints remain public for monitoring.
Author: Amelia (Clawdbot AI)
"""

import os
from datetime import datetime, timedelta
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.utils import timezone
import json

from core.models import Customer
from apps.technician_portal.models import Repair, Replacement


# =============================================================================
# HELPERS
# =============================================================================

def _get_tenant_or_403(request):
    """
    Extract tenant from request. Returns (tenant, None) on success
    or (None, JsonResponse) on failure.
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return None, JsonResponse(
            {'error': 'No tenant context. Ensure you are logged in and belong to an organization.'},
            status=403,
        )
    return tenant, None


# =============================================================================
# CLAWDBOT-SPECIFIC ENDPOINTS (status, health — public for monitoring)
# =============================================================================

@require_GET
def status(request):
    """Clawdbot status endpoint. Public — no sensitive data."""
    from apps.billing.services.stripe_service import StripeService
    stripe_service = StripeService()

    return JsonResponse({
        'status': 'online',
        'name': 'Amelia',
        'version': '0.9.0',
        'capabilities': [
            'invoice_generation',
            'auto_invoice_on_completion',
            'invoice_tracking',
            'double_billing_prevention',
            'payment_recording',
            'customer_invoice_preferences',
            'billing_dashboard',
            'business_reports',
            'stripe_integration' if stripe_service.is_enabled() else 'stripe_ready',
            'payment_reminders',
            's3_invoice_storage',
        ],
        'integrations': {
            'stripe': stripe_service.is_enabled(),
            'stripe_test_mode': getattr(settings, 'STRIPE_TEST_MODE', True),
            's3': True,
            'sendgrid': bool(getattr(settings, 'SENDGRID_API_KEY', None)),
        },
        'api': {
            'billing': '/api/billing/',
            'clawdbot': '/clawdbot/',
        },
        'note': 'Billing endpoints available at /api/billing/ (canonical) and /clawdbot/ (experimental)',
    })


@require_GET
def health(request):
    """Health check endpoint. Public — no sensitive data."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({
            'healthy': True,
            'service': 'clawdbot',
            'database': 'connected',
            'timestamp': timezone.now().isoformat(),
        })
    except Exception as e:
        return JsonResponse({
            'healthy': False,
            'error': str(e),
        }, status=503)


# =============================================================================
# DATA ENDPOINTS (require auth + tenant scoping)
# =============================================================================

@login_required
@require_GET
def list_customers(request):
    """List all customers with repair counts (annotated to avoid N+1)."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from django.db.models import Count, Q

    customers = Customer.objects.filter(tenant=tenant).annotate(
        completed_repairs=Count(
            'repair', filter=Q(repair__queue_status='COMPLETED')
        ),
        pending_repairs=Count(
            'repair', filter=Q(repair__queue_status__in=['PENDING', 'APPROVED', 'IN_PROGRESS'])
        ),
    ).order_by('name')

    return JsonResponse({
        'customers': [{
            'id': c.id,
            'name': c.name,
            'email': c.email,
            'completed_repairs': c.completed_repairs,
            'pending_repairs': c.pending_repairs,
        } for c in customers],
        'total': customers.count(),
    })


@login_required
@require_GET
def list_repairs(request, customer_id):
    """List completed repairs for a customer."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)

    repairs = Repair.objects.filter(
        customer=customer,
        tenant=tenant,
        queue_status='COMPLETED',
        service_date__gte=start_date
    ).select_related('technician', 'technician__user').order_by('-service_date')

    repair_data = []
    for r in repairs:
        disc = r.get_discounted_cost()
        repair_data.append({
            'id': r.id,
            'unit_number': r.unit_number,
            'damage_type': r.get_damage_type_display() or 'Unknown',
            'service_date': r.repair_date.isoformat(),
            'cost': float(disc['final_cost']),
            'has_photos': r.has_photos(),
        })

    return JsonResponse({
        'customer': {'id': customer.id, 'name': customer.name},
        'repairs': repair_data,
        'count': len(repair_data),
    })


# =============================================================================
# INVOICE GENERATION (original clawdbot features - PDF generation)
# =============================================================================

@login_required
@require_GET
def invoice_preview(request, customer_id):
    """Preview invoice data without generating PDF."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.invoice_service import InvoiceService

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    repair_ids = request.GET.get('repair_ids')
    if repair_ids:
        repair_ids = [int(x.strip()) for x in repair_ids.split(',')]

    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)

    service = InvoiceService()
    try:
        invoice_data = service.build_invoice_data(
            customer_id=customer_id,
            repair_ids=repair_ids,
            start_date=start_date if not repair_ids else None
        )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not invoice_data.line_items:
        return JsonResponse({'error': 'No completed repairs found'}, status=404)

    return JsonResponse({
        'preview': True,
        'invoice_number': invoice_data.invoice_number,
        'customer': {'name': invoice_data.customer_name},
        'line_items': [{
            'unit_number': item.unit_number,
            'damage_type': item.damage_type,
            'service_date': item.repair_date.isoformat(),
            'final_cost': float(item.final_cost),
        } for item in invoice_data.line_items],
        'totals': {
            'subtotal': float(invoice_data.subtotal),
            'discount': float(invoice_data.total_discount),
            'total': float(invoice_data.total),
        },
    })


@login_required
@require_GET
def generate_invoice(request, customer_id):
    """Generate and download a PDF invoice."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.invoice_service import InvoiceService

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    repair_ids = request.GET.get('repair_ids')
    if repair_ids:
        repair_ids = [int(x.strip()) for x in repair_ids.split(',')]

    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)

    service = InvoiceService()
    try:
        pdf_bytes, invoice_data = service.generate_invoice(
            customer_id=customer_id,
            repair_ids=repair_ids,
            start_date=start_date if not repair_ids else None
        )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not invoice_data.line_items:
        return JsonResponse({'error': 'No completed repairs found'}, status=404)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"invoice_{customer.name.replace(' ', '_')}_{invoice_data.invoice_number}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
