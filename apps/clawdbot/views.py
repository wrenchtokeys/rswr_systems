"""
Clawdbot Views - Amelia's experimental endpoint

This app provides:
- Status and health checks
- Invoice generation API
- Future: More automation tools

Author: Amelia (Clawdbot AI)
"""

from datetime import datetime, timedelta
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json

from core.models import Customer
from apps.technician_portal.models import Repair


@require_GET
def status(request):
    """
    Clawdbot status endpoint.
    Returns basic information about Clawdbot's operational status.
    """
    return JsonResponse({
        'status': 'online',
        'name': 'Amelia',
        'version': '0.2.0',
        'capabilities': [
            'invoice_generation',
            'repair_queries',
            'health_checks',
        ],
        'endpoints': {
            'status': '/clawdbot/',
            'health': '/clawdbot/health/',
            'invoices': {
                'preview': '/clawdbot/invoices/preview/<customer_id>/',
                'generate': '/clawdbot/invoices/generate/<customer_id>/',
            },
            'repairs': {
                'list': '/clawdbot/repairs/<customer_id>/',
            }
        }
    })


@require_GET
def health(request):
    """
    Clawdbot health check endpoint.
    Returns actual health status by checking database connectivity.
    """
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
            'service': 'clawdbot',
            'database': 'error',
            'error': str(e),
        }, status=503)


@require_GET
def list_customers(request):
    """
    List all customers with repair counts.
    """
    customers = Customer.objects.all().order_by('name')
    
    customer_data = []
    for customer in customers:
        completed_count = Repair.objects.filter(
            customer=customer,
            queue_status='COMPLETED'
        ).count()
        
        pending_count = Repair.objects.filter(
            customer=customer,
            queue_status__in=['PENDING', 'APPROVED', 'IN_PROGRESS']
        ).count()
        
        customer_data.append({
            'id': customer.id,
            'name': customer.name,
            'email': customer.email,
            'completed_repairs': completed_count,
            'pending_repairs': pending_count,
        })
    
    return JsonResponse({
        'customers': customer_data,
        'total': len(customer_data)
    })


@require_GET
def list_repairs(request, customer_id):
    """
    List completed repairs for a customer that can be invoiced.
    
    Query params:
        - days: Number of days to look back (default: 30)
        - status: Filter by status (default: COMPLETED)
    """
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    days = int(request.GET.get('days', 30))
    status_filter = request.GET.get('status', 'COMPLETED')
    
    start_date = timezone.now() - timedelta(days=days)
    
    repairs = Repair.objects.filter(
        customer=customer,
        queue_status=status_filter,
        repair_date__gte=start_date
    ).select_related('technician', 'technician__user').order_by('-repair_date')
    
    repair_data = []
    for repair in repairs:
        discounted = repair.get_discounted_cost()
        repair_data.append({
            'id': repair.id,
            'unit_number': repair.unit_number,
            'damage_type': repair.get_damage_type_display() or 'Unknown',
            'repair_date': repair.repair_date.isoformat(),
            'technician': repair.technician.user.get_full_name() if repair.technician else None,
            'original_cost': float(discounted['original_cost']),
            'final_cost': float(discounted['final_cost']),
            'discount_applied': discounted['discount_applied'],
            'discount_description': discounted['discount_description'],
            'has_photos': repair.has_photos(),
            'batch_id': str(repair.repair_batch_id) if repair.repair_batch_id else None,
        })
    
    total_cost = sum(r['final_cost'] for r in repair_data)
    
    return JsonResponse({
        'customer': {
            'id': customer.id,
            'name': customer.name,
        },
        'repairs': repair_data,
        'summary': {
            'count': len(repair_data),
            'total_cost': total_cost,
            'date_range': {
                'start': start_date.isoformat(),
                'end': timezone.now().isoformat(),
            }
        }
    })


@require_GET
def invoice_preview(request, customer_id):
    """
    Preview invoice data without generating PDF.
    
    Query params:
        - repair_ids: Comma-separated repair IDs (optional)
        - days: Number of days to look back (default: 30)
    """
    from apps.clawdbot.services.invoice_service import InvoiceService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    # Parse parameters
    repair_ids = request.GET.get('repair_ids')
    if repair_ids:
        repair_ids = [int(x.strip()) for x in repair_ids.split(',')]
    
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)
    
    # Build invoice data
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
        return JsonResponse({
            'error': 'No completed repairs found for invoicing',
            'customer': customer.name,
        }, status=404)
    
    # Convert to JSON-serializable format
    return JsonResponse({
        'preview': True,
        'invoice_number': invoice_data.invoice_number,
        'invoice_date': invoice_data.invoice_date.isoformat(),
        'customer': {
            'name': invoice_data.customer_name,
            'email': invoice_data.customer_email,
            'address': invoice_data.customer_address,
        },
        'line_items': [
            {
                'repair_id': item.repair_id,
                'unit_number': item.unit_number,
                'damage_type': item.damage_type,
                'repair_date': item.repair_date.isoformat(),
                'original_cost': float(item.original_cost),
                'final_cost': float(item.final_cost),
                'discount': item.discount_description,
                'has_photos': item.has_photos,
            }
            for item in invoice_data.line_items
        ],
        'totals': {
            'subtotal': float(invoice_data.subtotal),
            'discount': float(invoice_data.total_discount),
            'total': float(invoice_data.total),
        },
        'item_count': len(invoice_data.line_items),
    })


@require_GET
def generate_invoice(request, customer_id):
    """
    Generate and download a PDF invoice.
    
    Query params:
        - repair_ids: Comma-separated repair IDs (optional)
        - days: Number of days to look back (default: 30)
    """
    from apps.clawdbot.services.invoice_service import InvoiceService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    # Parse parameters
    repair_ids = request.GET.get('repair_ids')
    if repair_ids:
        repair_ids = [int(x.strip()) for x in repair_ids.split(',')]
    
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)
    
    # Generate invoice
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
        return JsonResponse({
            'error': 'No completed repairs found for invoicing',
            'customer': customer.name,
        }, status=404)
    
    # Return PDF
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"invoice_{customer.name.replace(' ', '_')}_{invoice_data.invoice_number}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response
