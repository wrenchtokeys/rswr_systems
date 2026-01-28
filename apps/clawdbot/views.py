"""
Clawdbot Views - Amelia's experimental endpoint

This app provides:
- Status and health checks
- Invoice generation API
- Future: More automation tools

Author: Amelia (Clawdbot AI)
"""

import os
from datetime import datetime, timedelta
from django.http import JsonResponse, HttpResponse, Http404, FileResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
import json

from core.models import Customer
from apps.technician_portal.models import Repair


# Directory for saved invoices
INVOICE_DIR = "/home/ubuntu/invoices"


@require_GET
def status(request):
    """
    Clawdbot status endpoint.
    Returns basic information about Clawdbot's operational status.
    """
    from apps.billing.services.stripe_service import StripeService
    
    stripe_service = StripeService()
    
    return JsonResponse({
        'status': 'online',
        'name': 'Amelia',
        'version': '0.5.0',
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
            's3': True,
            'sendgrid': bool(getattr(settings, 'SENDGRID_API_KEY', None)),
        },
        'endpoints': {
            'status': '/clawdbot/',
            'health': '/clawdbot/health/',
            'dashboard': '/clawdbot/dashboard/',
            'customers': '/clawdbot/customers/',
            'repairs': '/clawdbot/repairs/<customer_id>/',
            'invoices': {
                'preview': '/clawdbot/invoices/preview/<customer_id>/',
                'generate': '/clawdbot/invoices/generate/<customer_id>/',
                'email': '/clawdbot/invoices/email/<customer_id>/',
            },
            'billing': {
                'invoices': '/clawdbot/billing/invoices/',
                'invoice_detail': '/clawdbot/billing/invoices/<id>/',
                'record_payment': '/clawdbot/billing/invoices/<id>/payment/',
                'uninvoiced': '/clawdbot/billing/uninvoiced/<customer_id>/',
                'balance': '/clawdbot/billing/balance/<customer_id>/',
            },
            'reports': {
                'daily': '/clawdbot/reports/daily/',
                'weekly': '/clawdbot/reports/weekly/',
            },
            'stripe': {
                'status': '/clawdbot/stripe/status/',
                'create_invoice': '/clawdbot/stripe/invoice/<id>/',
                'payment_link': '/clawdbot/stripe/payment-link/<id>/',
                'webhook': '/clawdbot/stripe/webhook/',
            },
            'reminders': {
                'summary': '/clawdbot/reminders/summary/',
                'send': '/clawdbot/reminders/send/<invoice_id>/',
                'process_all': '/clawdbot/reminders/process/',
            },
            'preferences': {
                'get': '/clawdbot/preferences/<customer_id>/',
                'update': '/clawdbot/preferences/<customer_id>/update/',
            },
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
    from apps.billing.services.invoice_service import InvoiceService
    
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
        'company': {
            'name': service.COMPANY_NAME,
            'phone': service.COMPANY_PHONE,
            'email': service.COMPANY_EMAIL,
            'address': service.COMPANY_ADDRESS,
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
        - save: If 'true', also save to disk (default: false)
    """
    from apps.billing.services.invoice_service import InvoiceService
    
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
    save_to_disk = request.GET.get('save', 'false').lower() == 'true'
    
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
    
    # Optionally save to disk
    if save_to_disk:
        os.makedirs(INVOICE_DIR, exist_ok=True)
        filename = f"{customer.name.replace(' ', '_')}_{invoice_data.invoice_number}.pdf"
        filepath = os.path.join(INVOICE_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)
    
    # Return PDF
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"invoice_{customer.name.replace(' ', '_')}_{invoice_data.invoice_number}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@require_GET
def list_saved_invoices(request):
    """
    List all saved invoices on disk.
    """
    if not os.path.exists(INVOICE_DIR):
        return JsonResponse({'invoices': [], 'count': 0})
    
    invoices = []
    for filename in os.listdir(INVOICE_DIR):
        if filename.endswith('.pdf'):
            filepath = os.path.join(INVOICE_DIR, filename)
            stat = os.stat(filepath)
            invoices.append({
                'filename': filename,
                'size_bytes': stat.st_size,
                'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                'download_url': f'/clawdbot/invoices/download/{filename}/',
            })
    
    invoices.sort(key=lambda x: x['created'], reverse=True)
    
    return JsonResponse({
        'invoices': invoices,
        'count': len(invoices),
    })


@require_GET
def send_invoice_email(request, customer_id):
    """
    Send invoice email with PDF and photo attachments.
    
    Query params:
        - email: Recipient email (required)
        - days: Number of days to look back (default: 30)
        - photos: Include photos (default: true)
        - repair_ids: Comma-separated repair IDs (optional)
    """
    from apps.billing.services.invoice_email_service import InvoiceEmailService
    
    recipient_email = request.GET.get('email')
    if not recipient_email:
        return JsonResponse({'error': 'email parameter required'}, status=400)
    
    days = int(request.GET.get('days', 30))
    include_photos = request.GET.get('photos', 'true').lower() == 'true'
    
    repair_ids = request.GET.get('repair_ids')
    if repair_ids:
        repair_ids = [int(x.strip()) for x in repair_ids.split(',')]
    
    service = InvoiceEmailService()
    success, message = service.send_invoice_email(
        customer_id=customer_id,
        recipient_email=recipient_email,
        repair_ids=repair_ids,
        days=days,
        include_photos=include_photos
    )
    
    if success:
        return JsonResponse({'success': True, 'message': message})
    else:
        return JsonResponse({'success': False, 'error': message}, status=400)


@require_GET
def download_saved_invoice(request, filename):
    """
    Download a previously saved invoice.
    """
    # Security: prevent directory traversal
    if '..' in filename or '/' in filename:
        return JsonResponse({'error': 'Invalid filename'}, status=400)
    
    filepath = os.path.join(INVOICE_DIR, filename)
    
    if not os.path.exists(filepath):
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    return FileResponse(
        open(filepath, 'rb'),
        content_type='application/pdf',
        as_attachment=True,
        filename=filename
    )


@require_GET
def get_invoice_preferences(request, customer_id):
    """
    Get invoice preferences for a customer.
    
    Returns current invoice settings including:
    - invoice_preference (per_ticket, batch, manual)
    - billing_email
    - auto_email_invoices
    - include_photos_in_invoice
    """
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    # Get or create preferences
    from apps.customer_portal.models import CustomerRepairPreference
    prefs, created = CustomerRepairPreference.objects.get_or_create(
        customer=customer,
        defaults={'invoice_preference': 'batch'}
    )
    
    return JsonResponse({
        'customer': {
            'id': customer.id,
            'name': customer.name,
            'email': customer.email,
        },
        'invoice_settings': {
            'invoice_preference': prefs.invoice_preference,
            'invoice_preference_display': prefs.get_invoice_preference_display(),
            'billing_email': prefs.billing_email,
            'auto_email_invoices': prefs.auto_email_invoices,
            'include_photos_in_invoice': prefs.include_photos_in_invoice,
        },
        'created': created,
    })


@csrf_exempt
@require_POST
def update_invoice_preferences(request, customer_id):
    """
    Update invoice preferences for a customer.
    
    POST body (JSON):
    {
        "invoice_preference": "per_ticket" | "batch" | "manual",
        "billing_email": "billing@example.com" (optional),
        "auto_email_invoices": true | false,
        "include_photos_in_invoice": true | false
    }
    """
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    # Parse JSON body
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    
    # Get or create preferences
    from apps.customer_portal.models import CustomerRepairPreference
    prefs, created = CustomerRepairPreference.objects.get_or_create(
        customer=customer,
        defaults={'invoice_preference': 'batch'}
    )
    
    # Update fields if provided
    valid_preferences = ['per_ticket', 'batch', 'manual']
    
    if 'invoice_preference' in data:
        if data['invoice_preference'] not in valid_preferences:
            return JsonResponse({
                'error': f"Invalid invoice_preference. Must be one of: {valid_preferences}"
            }, status=400)
        prefs.invoice_preference = data['invoice_preference']
    
    if 'billing_email' in data:
        prefs.billing_email = data['billing_email'] or None
    
    if 'auto_email_invoices' in data:
        prefs.auto_email_invoices = bool(data['auto_email_invoices'])
    
    if 'include_photos_in_invoice' in data:
        prefs.include_photos_in_invoice = bool(data['include_photos_in_invoice'])
    
    prefs.save()
    
    return JsonResponse({
        'success': True,
        'customer': {
            'id': customer.id,
            'name': customer.name,
        },
        'invoice_settings': {
            'invoice_preference': prefs.invoice_preference,
            'invoice_preference_display': prefs.get_invoice_preference_display(),
            'billing_email': prefs.billing_email,
            'auto_email_invoices': prefs.auto_email_invoices,
            'include_photos_in_invoice': prefs.include_photos_in_invoice,
        },
    })


# =============================================================================
# INVOICE TRACKING ENDPOINTS
# =============================================================================

@require_GET
def list_invoices(request):
    """
    List all invoices with optional filters.
    
    Query params:
        - customer_id: Filter by customer
        - status: Filter by status (DRAFT, SENT, PAID, PARTIAL, OVERDUE, CANCELLED)
        - outstanding: If 'true', only show unpaid invoices
    """
    from apps.billing.models import Invoice
    
    invoices = Invoice.objects.all()
    
    # Apply filters
    customer_id = request.GET.get('customer_id')
    if customer_id:
        invoices = invoices.filter(customer_id=customer_id)
    
    status_filter = request.GET.get('status')
    if status_filter:
        invoices = invoices.filter(status=status_filter.upper())
    
    outstanding = request.GET.get('outstanding', '').lower() == 'true'
    if outstanding:
        invoices = invoices.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE'])
    
    invoices = invoices.select_related('customer').order_by('-invoice_date')[:50]
    
    invoice_data = []
    for inv in invoices:
        invoice_data.append({
            'id': inv.id,
            'invoice_number': inv.invoice_number,
            'customer': {
                'id': inv.customer.id,
                'name': inv.customer.name,
            },
            'invoice_date': inv.invoice_date.isoformat(),
            'due_date': inv.due_date.isoformat() if inv.due_date else None,
            'total': float(inv.total),
            'amount_paid': float(inv.amount_paid),
            'amount_due': float(inv.amount_due),
            'status': inv.status,
            'line_item_count': inv.line_items.count(),
        })
    
    return JsonResponse({
        'invoices': invoice_data,
        'count': len(invoice_data),
    })


@require_GET
def get_invoice(request, invoice_id):
    """
    Get detailed invoice information including line items and payments.
    """
    from apps.billing.models import Invoice
    
    try:
        invoice = Invoice.objects.select_related('customer').get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    line_items = []
    for item in invoice.line_items.all():
        line_items.append({
            'id': item.id,
            'description': item.description,
            'quantity': item.quantity,
            'unit_price': float(item.unit_price),
            'discount': float(item.discount),
            'amount': float(item.amount),
            'repair_id': item.repair_id,
            'unit_number': item.unit_number,
            'repair_date': item.repair_date.isoformat() if item.repair_date else None,
        })
    
    payments = []
    for payment in invoice.payments.all():
        payments.append({
            'id': payment.id,
            'amount': float(payment.amount),
            'payment_date': payment.payment_date.isoformat(),
            'payment_method': payment.payment_method,
            'payment_method_display': payment.get_payment_method_display(),
            'reference_number': payment.reference_number,
            'notes': payment.notes,
        })
    
    return JsonResponse({
        'invoice': {
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'customer': {
                'id': invoice.customer.id,
                'name': invoice.customer.name,
                'email': invoice.customer.email,
            },
            'invoice_date': invoice.invoice_date.isoformat(),
            'due_date': invoice.due_date.isoformat() if invoice.due_date else None,
            'subtotal': float(invoice.subtotal),
            'discount': float(invoice.discount),
            'total': float(invoice.total),
            'amount_paid': float(invoice.amount_paid),
            'amount_due': float(invoice.amount_due),
            'status': invoice.status,
            'sent_at': invoice.sent_at.isoformat() if invoice.sent_at else None,
            'paid_at': invoice.paid_at.isoformat() if invoice.paid_at else None,
            's3_key': invoice.s3_key,
            'stripe_invoice_id': invoice.stripe_invoice_id,
            'stripe_hosted_url': invoice.stripe_hosted_url,
            'notes': invoice.notes,
        },
        'line_items': line_items,
        'payments': payments,
    })


@require_GET
def get_uninvoiced_repairs(request, customer_id):
    """
    Get repairs that haven't been invoiced yet for a customer.
    These are available to be added to a new invoice.
    """
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    service = InvoiceTrackingService()
    repairs = service.get_uninvoiced_repairs(customer)
    
    repair_data = []
    total_value = 0
    for repair in repairs:
        discounted = repair.get_discounted_cost()
        repair_data.append({
            'id': repair.id,
            'unit_number': repair.unit_number,
            'damage_type': repair.get_damage_type_display() or 'Repair',
            'repair_date': repair.repair_date.isoformat(),
            'original_cost': float(discounted['original_cost']),
            'final_cost': float(discounted['final_cost']),
            'discount_applied': discounted['discount_applied'],
        })
        total_value += float(discounted['final_cost'])
    
    return JsonResponse({
        'customer': {
            'id': customer.id,
            'name': customer.name,
        },
        'uninvoiced_repairs': repair_data,
        'count': len(repair_data),
        'total_value': total_value,
    })


@csrf_exempt
@require_POST
def record_payment(request, invoice_id):
    """
    Record a payment against an invoice.
    
    POST body (JSON):
    {
        "amount": 150.00,
        "payment_method": "CHECK" | "CASH" | "WIRE" | "ACH" | "STRIPE" | "OTHER",
        "reference_number": "Check #1234" (optional),
        "payment_date": "2026-01-28" (optional, defaults to today),
        "notes": "Paid in full" (optional)
    }
    """
    from apps.billing.models import Invoice
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    
    if 'amount' not in data:
        return JsonResponse({'error': 'amount is required'}, status=400)
    
    # Parse payment date if provided
    payment_date = None
    if data.get('payment_date'):
        try:
            payment_date = datetime.strptime(data['payment_date'], '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid payment_date format. Use YYYY-MM-DD'}, status=400)
    
    try:
        service = InvoiceTrackingService()
        payment = service.record_payment(
            invoice=invoice,
            amount=data['amount'],
            payment_method=data.get('payment_method', 'OTHER').upper(),
            reference_number=data.get('reference_number', ''),
            notes=data.get('notes', ''),
            payment_date=payment_date,
        )
        
        # Refresh invoice to get updated status
        invoice.refresh_from_db()
        
        return JsonResponse({
            'success': True,
            'payment': {
                'id': payment.id,
                'amount': float(payment.amount),
                'payment_method': payment.payment_method,
            },
            'invoice': {
                'id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'total': float(invoice.total),
                'amount_paid': float(invoice.amount_paid),
                'amount_due': float(invoice.amount_due),
                'status': invoice.status,
            },
        })
        
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_GET
def get_customer_balance(request, customer_id):
    """
    Get outstanding balance and invoice summary for a customer.
    """
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    service = InvoiceTrackingService()
    balance = service.get_customer_balance(customer)
    
    # Format invoice list
    invoice_summary = []
    for inv in balance['invoices']:
        invoice_summary.append({
            'id': inv.id,
            'invoice_number': inv.invoice_number,
            'invoice_date': inv.invoice_date.isoformat(),
            'due_date': inv.due_date.isoformat() if inv.due_date else None,
            'total': float(inv.total),
            'amount_due': float(inv.amount_due),
            'status': inv.status,
        })
    
    return JsonResponse({
        'customer': {
            'id': customer.id,
            'name': customer.name,
        },
        'balance': {
            'total_outstanding': float(balance['total_outstanding']),
            'invoice_count': balance['invoice_count'],
            'oldest_due': balance['oldest_due'].isoformat() if balance['oldest_due'] else None,
        },
        'outstanding_invoices': invoice_summary,
    })


# =============================================================================
# DASHBOARD & REPORTING
# =============================================================================

@require_GET
def billing_dashboard(request):
    """
    Get full billing dashboard with metrics, alerts, and trends.
    
    Returns comprehensive business intelligence:
    - Revenue (today, week, month, year + growth)
    - Invoice status breakdown
    - Outstanding and overdue amounts
    - Payment metrics by method
    - Customer insights (top outstanding, top revenue)
    - Actionable alerts
    - Trend data for charts
    """
    from apps.billing.services.dashboard_service import DashboardService
    
    service = DashboardService()
    dashboard = service.get_full_dashboard()
    
    return JsonResponse(dashboard)


@require_GET
def daily_report(request):
    """
    Generate a daily business report.
    
    Query params:
        - date: Specific date (YYYY-MM-DD), defaults to today
    """
    from apps.billing.services.report_service import ReportService
    
    date_str = request.GET.get('date')
    if date_str:
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
    else:
        report_date = timezone.now().date()
    
    service = ReportService()
    report = service.generate_daily_report(report_date)
    
    return JsonResponse(report)


@require_GET  
def weekly_report(request):
    """
    Generate a weekly business report.
    
    Query params:
        - week_start: Start date of week (YYYY-MM-DD), defaults to current week
    """
    from apps.billing.services.report_service import ReportService
    
    date_str = request.GET.get('week_start')
    if date_str:
        try:
            week_start = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
    else:
        # Default to start of current week (Monday)
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
    
    service = ReportService()
    report = service.generate_weekly_report(week_start)
    
    return JsonResponse(report)


# =============================================================================
# STRIPE INTEGRATION
# =============================================================================

@require_GET
def stripe_status(request):
    """Check if Stripe integration is configured and enabled."""
    from apps.billing.services.stripe_service import StripeService
    
    service = StripeService()
    
    return JsonResponse({
        'enabled': service.is_enabled(),
        'message': 'Stripe integration ready' if service.is_enabled() else 'Stripe not configured (set STRIPE_SECRET_KEY)',
    })


@csrf_exempt
@require_POST
def create_stripe_invoice(request, invoice_id):
    """
    Create a Stripe invoice from our invoice record.
    
    POST body (JSON):
    {
        "auto_send": true  (optional, defaults to false)
    }
    """
    from apps.billing.models import Invoice
    from apps.billing.services.stripe_service import StripeService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    service = StripeService()
    if not service.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    auto_send = data.get('auto_send', False)
    
    result = service.create_stripe_invoice(invoice, auto_send=auto_send)
    
    if result['success']:
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=400)


@require_GET
def create_payment_link(request, invoice_id):
    """
    Create a Stripe payment link for an invoice.
    Returns a URL that customers can use to pay online.
    """
    from apps.billing.models import Invoice
    from apps.billing.services.stripe_service import StripeService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    if invoice.amount_due <= 0:
        return JsonResponse({'error': 'Invoice already paid'}, status=400)
    
    service = StripeService()
    if not service.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)
    
    result = service.create_payment_link(invoice)
    
    if result['success']:
        return JsonResponse({
            'success': True,
            'payment_link': result['payment_link'],
            'invoice_number': invoice.invoice_number,
            'amount_due': float(invoice.amount_due),
        })
    else:
        return JsonResponse(result, status=400)


@csrf_exempt
def stripe_webhook(request):
    """
    Handle incoming Stripe webhook events.
    Configure this URL in your Stripe dashboard.
    """
    from apps.billing.services.stripe_service import StripeService
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    service = StripeService()
    if not service.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)
    
    payload = request.body
    sig_header = request.headers.get('Stripe-Signature', '')
    
    result = service.handle_webhook(payload, sig_header)
    
    if result['success']:
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=400)


# =============================================================================
# REMINDERS
# =============================================================================

@require_GET
def reminder_summary(request):
    """Get summary of invoices needing payment reminders."""
    from apps.billing.services.reminder_service import ReminderService
    
    service = ReminderService()
    summary = service.get_reminder_summary()
    
    return JsonResponse(summary)


@csrf_exempt
@require_POST
def send_reminder(request, invoice_id):
    """
    Send a payment reminder for a specific invoice.
    
    POST body (JSON):
    {
        "reminder_type": "overdue" | "due_soon" (optional, auto-detected)
    }
    """
    from apps.billing.models import Invoice
    from apps.billing.services.reminder_service import ReminderService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    if invoice.status in ('PAID', 'CANCELLED'):
        return JsonResponse({'error': f'Cannot send reminder for {invoice.status} invoice'}, status=400)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    # Auto-detect reminder type if not specified
    reminder_type = data.get('reminder_type')
    if not reminder_type:
        if invoice.is_overdue:
            reminder_type = 'overdue'
        else:
            reminder_type = 'due_soon'
    
    service = ReminderService()
    result = service.send_reminder(invoice, reminder_type)
    
    if result['success']:
        return JsonResponse({
            'success': True,
            'invoice_number': invoice.invoice_number,
            'reminder_type': result['reminder_type'],
            'sent_to': invoice.customer.email,
        })
    else:
        return JsonResponse(result, status=400)


@csrf_exempt
@require_POST
def process_all_reminders(request):
    """
    Process all pending reminders (due soon + overdue).
    Typically called by cron/scheduled task.
    """
    from apps.billing.services.reminder_service import ReminderService
    
    service = ReminderService()
    
    due_soon_results = service.process_due_soon_reminders()
    overdue_results = service.process_overdue_reminders()
    
    return JsonResponse({
        'success': True,
        'due_soon': due_soon_results,
        'overdue': overdue_results,
        'total_sent': due_soon_results['sent'] + overdue_results['sent'],
    })
