"""
Billing Views - Canonical API endpoints for billing operations.

These views are the proper home for billing endpoints.
The clawdbot app proxies to these during the experimental phase.

Author: Amelia (Clawdbot AI)
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone

from core.models import Customer


# =============================================================================
# DASHBOARD & REPORTS
# =============================================================================

@require_GET
def dashboard(request):
    """Full billing dashboard with metrics, alerts, and trends."""
    from apps.billing.services.dashboard_service import DashboardService
    return JsonResponse(DashboardService().get_full_dashboard())


@require_GET
def daily_report(request):
    """Daily business report. ?date=YYYY-MM-DD (default: today)"""
    from apps.billing.services.report_service import ReportService
    
    date_str = request.GET.get('date')
    if date_str:
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date. Use YYYY-MM-DD'}, status=400)
    else:
        report_date = timezone.now().date()
    
    return JsonResponse(ReportService().generate_daily_report(report_date))


@require_GET
def weekly_report(request):
    """Weekly business report. ?week_start=YYYY-MM-DD (default: this week)"""
    from apps.billing.services.report_service import ReportService
    
    date_str = request.GET.get('week_start')
    if date_str:
        try:
            week_start = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date. Use YYYY-MM-DD'}, status=400)
    else:
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
    
    return JsonResponse(ReportService().generate_weekly_report(week_start))


# =============================================================================
# INVOICE MANAGEMENT
# =============================================================================

@require_GET
def list_invoices(request):
    """
    List invoices with optional filters.
    ?customer_id=1&status=OVERDUE&outstanding=true
    """
    from apps.billing.models import Invoice
    
    invoices = Invoice.objects.all()
    
    if request.GET.get('customer_id'):
        invoices = invoices.filter(customer_id=request.GET['customer_id'])
    if request.GET.get('status'):
        invoices = invoices.filter(status=request.GET['status'].upper())
    if request.GET.get('outstanding', '').lower() == 'true':
        invoices = invoices.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE'])
    
    invoices = invoices.select_related('customer').order_by('-invoice_date')[:50]
    
    return JsonResponse({
        'invoices': [{
            'id': inv.id,
            'invoice_number': inv.invoice_number,
            'customer': {'id': inv.customer.id, 'name': inv.customer.name},
            'invoice_date': inv.invoice_date.isoformat(),
            'due_date': inv.due_date.isoformat() if inv.due_date else None,
            'total': float(inv.total),
            'amount_paid': float(inv.amount_paid),
            'amount_due': float(inv.amount_due),
            'status': inv.status,
            'stripe_hosted_url': inv.stripe_hosted_url or None,
            'line_item_count': inv.line_items.count(),
        } for inv in invoices],
        'count': len(invoices),
    })


@csrf_exempt
@require_POST
def create_invoice(request, customer_id):
    """
    Create a tracked invoice for a customer.
    
    POST body:
    {
        "repair_ids": [1, 2, 3],          // specific repairs (optional)
        "all_uninvoiced": true,             // or invoice everything pending
        "due_days": 30,                     // days until due (default: 30)
        "send_to_stripe": false,            // create in Stripe too
        "auto_email": false                 // email to customer
    }
    """
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    from apps.billing.services.invoice_service import InvoiceService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    tracking = InvoiceTrackingService()
    
    # Determine which repairs to invoice
    if data.get('repair_ids'):
        from apps.technician_portal.models import Repair
        repairs = list(Repair.objects.filter(
            id__in=data['repair_ids'],
            customer=customer,
            queue_status='COMPLETED'
        ))
        if not repairs:
            return JsonResponse({'error': 'No valid completed repairs found'}, status=400)
    elif data.get('all_uninvoiced', False):
        repairs = list(tracking.get_uninvoiced_repairs(customer))
        if not repairs:
            return JsonResponse({'error': 'No uninvoiced repairs for this customer'}, status=400)
    else:
        return JsonResponse({
            'error': 'Provide repair_ids or set all_uninvoiced=true'
        }, status=400)
    
    # Create the tracked invoice
    try:
        due_days = data.get('due_days', 30)
        invoice = tracking.create_invoice_from_repairs(
            customer=customer,
            repairs=repairs,
            due_days=due_days,
            auto_send=True,
        )
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    
    # Generate PDF and save to S3
    try:
        invoice_service = InvoiceService()
        repair_ids = [r.id for r in repairs]
        pdf_bytes, invoice_data = invoice_service.generate_invoice(
            customer_id=customer_id,
            repair_ids=repair_ids
        )
        
        from apps.billing.services.auto_invoice_service import AutoInvoiceService
        auto_service = AutoInvoiceService()
        s3_key = auto_service._save_to_s3(
            pdf_bytes=pdf_bytes,
            customer_id=customer_id,
            invoice_number=invoice.invoice_number
        )
        if s3_key:
            invoice.s3_key = s3_key
            invoice.save()
    except Exception as e:
        # Invoice record created, PDF generation failed - log but don't fail
        import logging
        logging.getLogger(__name__).warning(f"PDF generation failed for {invoice.invoice_number}: {e}")
    
    # Optionally create in Stripe
    stripe_result = None
    if data.get('send_to_stripe', False):
        from apps.billing.services.stripe_service import StripeService
        stripe_svc = StripeService()
        if stripe_svc.is_enabled():
            stripe_result = stripe_svc.create_stripe_invoice(invoice, auto_send=True)
    
    # Optionally email
    if data.get('auto_email', False) and customer.email:
        from apps.billing.services.invoice_email_service import InvoiceEmailService
        try:
            email_svc = InvoiceEmailService()
            email_svc.send_invoice_email(
                customer_id=customer_id,
                recipient_email=customer.email,
                repair_ids=repair_ids
            )
        except Exception:
            pass
    
    return JsonResponse({
        'success': True,
        'invoice': {
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'total': float(invoice.total),
            'status': invoice.status,
            'due_date': invoice.due_date.isoformat() if invoice.due_date else None,
            'line_items': invoice.line_items.count(),
            's3_key': invoice.s3_key,
            'stripe': stripe_result,
        },
    })


@require_GET
def get_invoice(request, invoice_id):
    """Get detailed invoice with line items and payments."""
    from apps.billing.models import Invoice
    
    try:
        invoice = Invoice.objects.select_related('customer').get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
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
            'is_overdue': invoice.is_overdue,
            'sent_at': invoice.sent_at.isoformat() if invoice.sent_at else None,
            'paid_at': invoice.paid_at.isoformat() if invoice.paid_at else None,
            's3_key': invoice.s3_key,
            'stripe_invoice_id': invoice.stripe_invoice_id,
            'stripe_hosted_url': invoice.stripe_hosted_url,
            'notes': invoice.notes,
        },
        'line_items': [{
            'id': item.id,
            'description': item.description,
            'quantity': item.quantity,
            'unit_price': float(item.unit_price),
            'discount': float(item.discount),
            'amount': float(item.amount),
            'repair_id': item.repair_id,
            'unit_number': item.unit_number,
            'repair_date': item.repair_date.isoformat() if item.repair_date else None,
        } for item in invoice.line_items.all()],
        'payments': [{
            'id': p.id,
            'amount': float(p.amount),
            'payment_date': p.payment_date.isoformat(),
            'payment_method': p.payment_method,
            'payment_method_display': p.get_payment_method_display(),
            'reference_number': p.reference_number,
            'notes': p.notes,
        } for p in invoice.payments.all()],
    })


@csrf_exempt
@require_POST
def record_payment(request, invoice_id):
    """
    Record a payment.
    POST: {"amount": 150, "payment_method": "CHECK", "reference_number": "Check #1234"}
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
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    if 'amount' not in data:
        return JsonResponse({'error': 'amount required'}, status=400)
    
    payment_date = None
    if data.get('payment_date'):
        try:
            payment_date = datetime.strptime(data['payment_date'], '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date. Use YYYY-MM-DD'}, status=400)
    
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
        
        invoice.refresh_from_db()
        
        return JsonResponse({
            'success': True,
            'payment': {
                'id': payment.id,
                'amount': float(payment.amount),
                'payment_method': payment.get_payment_method_display(),
            },
            'invoice': {
                'invoice_number': invoice.invoice_number,
                'total': float(invoice.total),
                'amount_paid': float(invoice.amount_paid),
                'amount_due': float(invoice.amount_due),
                'status': invoice.status,
            },
        })
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_POST
def cancel_invoice(request, invoice_id):
    """Cancel an invoice. POST: {"reason": "Duplicate invoice"}"""
    from apps.billing.models import Invoice
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    if invoice.status == 'PAID':
        return JsonResponse({'error': 'Cannot cancel a paid invoice'}, status=400)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    invoice.cancel(reason=data.get('reason', ''))
    
    return JsonResponse({
        'success': True,
        'invoice_number': invoice.invoice_number,
        'status': invoice.status,
    })


# =============================================================================
# CUSTOMER BILLING
# =============================================================================

@require_GET
def get_uninvoiced_repairs(request, customer_id):
    """Get repairs that haven't been invoiced yet."""
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    repairs = InvoiceTrackingService().get_uninvoiced_repairs(customer)
    
    total = 0
    repair_data = []
    for r in repairs:
        disc = r.get_discounted_cost()
        repair_data.append({
            'id': r.id,
            'unit_number': r.unit_number,
            'damage_type': r.get_damage_type_display() or 'Repair',
            'repair_date': r.repair_date.isoformat(),
            'cost': float(disc['final_cost']),
        })
        total += float(disc['final_cost'])
    
    return JsonResponse({
        'customer': {'id': customer.id, 'name': customer.name},
        'uninvoiced_repairs': repair_data,
        'count': len(repair_data),
        'total_value': total,
    })


@require_GET
def get_customer_balance(request, customer_id):
    """Get outstanding balance for a customer."""
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    balance = InvoiceTrackingService().get_customer_balance(customer)
    
    return JsonResponse({
        'customer': {'id': customer.id, 'name': customer.name},
        'balance': {
            'total_outstanding': float(balance['total_outstanding']),
            'invoice_count': balance['invoice_count'],
            'oldest_due': balance['oldest_due'].isoformat() if balance['oldest_due'] else None,
        },
        'outstanding_invoices': [{
            'id': inv.id,
            'invoice_number': inv.invoice_number,
            'total': float(inv.total),
            'amount_due': float(inv.amount_due),
            'due_date': inv.due_date.isoformat() if inv.due_date else None,
            'status': inv.status,
        } for inv in balance['invoices']],
    })


@require_GET
def get_invoice_preferences(request, customer_id):
    """Get invoice preferences for a customer."""
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    from apps.customer_portal.models import CustomerRepairPreference
    prefs, created = CustomerRepairPreference.objects.get_or_create(
        customer=customer, defaults={'invoice_preference': 'batch'}
    )
    
    return JsonResponse({
        'customer': {'id': customer.id, 'name': customer.name},
        'invoice_settings': {
            'invoice_preference': prefs.invoice_preference,
            'invoice_preference_display': prefs.get_invoice_preference_display(),
            'billing_email': prefs.billing_email,
            'auto_email_invoices': prefs.auto_email_invoices,
            'include_photos_in_invoice': prefs.include_photos_in_invoice,
        },
    })


@csrf_exempt
@require_POST
def update_invoice_preferences(request, customer_id):
    """Update invoice preferences for a customer."""
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    from apps.customer_portal.models import CustomerRepairPreference
    prefs, _ = CustomerRepairPreference.objects.get_or_create(
        customer=customer, defaults={'invoice_preference': 'batch'}
    )
    
    valid = ['per_ticket', 'batch', 'manual']
    if 'invoice_preference' in data:
        if data['invoice_preference'] not in valid:
            return JsonResponse({'error': f'Must be one of: {valid}'}, status=400)
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
        'invoice_settings': {
            'invoice_preference': prefs.invoice_preference,
            'billing_email': prefs.billing_email,
            'auto_email_invoices': prefs.auto_email_invoices,
            'include_photos_in_invoice': prefs.include_photos_in_invoice,
        },
    })


# =============================================================================
# STRIPE
# =============================================================================

@require_GET
def stripe_status(request):
    """Check Stripe integration status."""
    from apps.billing.services.stripe_service import StripeService
    svc = StripeService()
    return JsonResponse({
        'enabled': svc.is_enabled(),
        'test_mode': getattr(settings, 'STRIPE_TEST_MODE', True),
    })


@csrf_exempt
@require_POST
def create_stripe_invoice(request, invoice_id):
    """Create Stripe invoice from our invoice. POST: {"auto_send": true}"""
    from apps.billing.models import Invoice
    from apps.billing.services.stripe_service import StripeService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    svc = StripeService()
    if not svc.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    result = svc.create_stripe_invoice(invoice, auto_send=data.get('auto_send', True))
    return JsonResponse(result, status=200 if result['success'] else 400)


@require_GET
def create_payment_link(request, invoice_id):
    """Get a Stripe payment link for an invoice."""
    from apps.billing.models import Invoice
    from apps.billing.services.stripe_service import StripeService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    if invoice.amount_due <= 0:
        return JsonResponse({'error': 'Invoice already paid'}, status=400)
    
    svc = StripeService()
    if not svc.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)
    
    result = svc.create_payment_link(invoice)
    if result['success']:
        return JsonResponse({
            'payment_link': result['payment_link'],
            'invoice_number': invoice.invoice_number,
            'amount_due': float(invoice.amount_due),
        })
    return JsonResponse(result, status=400)


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events."""
    from apps.billing.services.stripe_service import StripeService
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    svc = StripeService()
    if not svc.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)
    
    result = svc.handle_webhook(
        request.body, request.headers.get('Stripe-Signature', '')
    )
    return JsonResponse(result, status=200 if result['success'] else 400)


# =============================================================================
# REMINDERS
# =============================================================================

@require_GET
def reminder_summary(request):
    """Get count of invoices needing reminders."""
    from apps.billing.services.reminder_service import ReminderService
    return JsonResponse(ReminderService().get_reminder_summary())


@csrf_exempt
@require_POST
def send_reminder(request, invoice_id):
    """Send payment reminder for an invoice."""
    from apps.billing.models import Invoice
    from apps.billing.services.reminder_service import ReminderService
    
    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)
    
    if invoice.status in ('PAID', 'CANCELLED'):
        return JsonResponse({'error': f'Cannot remind for {invoice.status} invoice'}, status=400)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    reminder_type = data.get('reminder_type', 'overdue' if invoice.is_overdue else 'due_soon')
    result = ReminderService().send_reminder(invoice, reminder_type)
    
    if result['success']:
        return JsonResponse({'success': True, 'sent_to': invoice.customer.email})
    return JsonResponse(result, status=400)


@csrf_exempt
@require_POST
def process_all_reminders(request):
    """Process all pending reminders. For cron/scheduled tasks."""
    from apps.billing.services.reminder_service import ReminderService
    
    svc = ReminderService()
    due_soon = svc.process_due_soon_reminders()
    overdue = svc.process_overdue_reminders()
    
    return JsonResponse({
        'due_soon': due_soon,
        'overdue': overdue,
        'total_sent': due_soon['sent'] + overdue['sent'],
    })
