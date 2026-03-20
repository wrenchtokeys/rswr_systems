"""
Billing Views - Canonical API endpoints for billing operations.

These views are the proper home for billing endpoints.
The clawdbot app proxies to these during the experimental phase.

Security: All endpoints require authentication and tenant scoping.
Author: Amelia (Clawdbot AI)
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.utils import timezone

from common.auth import requires_api

from core.models import Customer


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
# DASHBOARD & REPORTS
# =============================================================================

@requires_api('invoices')
@require_GET
def dashboard(request):
    """Full billing dashboard with metrics, alerts, and trends."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.dashboard_service import DashboardService
    return JsonResponse(DashboardService(tenant).get_full_dashboard())


@requires_api('invoices')
@require_GET
def daily_report(request):
    """Daily business report. ?date=YYYY-MM-DD (default: today)"""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.report_service import ReportService

    date_str = request.GET.get('date')
    if date_str:
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date. Use YYYY-MM-DD'}, status=400)
    else:
        report_date = timezone.now().date()

    return JsonResponse(ReportService(tenant).generate_daily_report(report_date))


@requires_api('invoices')
@require_GET
def weekly_report(request):
    """Weekly business report. ?week_start=YYYY-MM-DD (default: this week)"""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

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

    return JsonResponse(ReportService(tenant).generate_weekly_report(week_start))


# =============================================================================
# INVOICE MANAGEMENT
# =============================================================================

@requires_api('invoices')
@require_GET
def list_invoices(request):
    """
    List invoices with optional filters.
    ?customer_id=1&status=OVERDUE&outstanding=true
    """
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice

    invoices = Invoice.objects.for_tenant(tenant)

    if request.GET.get('customer_id'):
        invoices = invoices.filter(customer_id=request.GET['customer_id'])
    if request.GET.get('status'):
        invoices = invoices.filter(status=request.GET['status'].upper())
    if request.GET.get('outstanding', '').lower() == 'true':
        invoices = invoices.filter(status__in=['SENT', 'PARTIAL', 'OVERDUE'])

    invoices = (
        invoices
        .select_related('customer')
        .annotate(line_item_count=Count('line_items'))
        .order_by('-invoice_date')[:50]
    )

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
            'line_item_count': inv.line_item_count,
        } for inv in invoices],
        'count': len(invoices),
    })


@requires_api('invoices')
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
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    tracking = InvoiceTrackingService(tenant=tenant)

    # Determine which repairs to invoice
    if data.get('repair_ids'):
        from apps.technician_portal.models import Repair
        repairs = list(Repair.objects.filter(
            id__in=data['repair_ids'],
            customer=customer,
            tenant=tenant,
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
        send_email = data.get('auto_email', False)
        invoice = tracking.create_invoice_from_repairs(
            customer=customer,
            repairs=repairs,
            due_days=due_days,
            auto_send=send_email,  # SENT if emailing, DRAFT otherwise
        )
        # Ensure invoice is associated with the tenant
        if not invoice.tenant_id:
            invoice.tenant = tenant
            invoice.save(update_fields=['tenant'])
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(f"Invoice creation failed for customer {customer_id}")
        return JsonResponse({'error': f'Invoice creation failed: {str(e)}'}, status=500)

    # Generate PDF and save to S3
    try:
        from apps.billing.services.invoice_service import InvoiceService
        # Pass tenant so InvoiceService loads correct BillingConfig. (CODE-092)
        invoice_service = InvoiceService(tenant=tenant)
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

    # Generate Stripe payment link (auto when Stripe is configured, skip with no_payment_link=true)
    stripe_result = None
    try:
        if not data.get('no_payment_link', False):
            from apps.billing.services.stripe_service import StripeService
            stripe_svc = StripeService()
            if stripe_svc.is_enabled() and invoice.amount_due > 0:
                # Use connected payment if tenant has Stripe Connect set up
                if invoice.tenant and invoice.tenant.can_accept_payments:
                    from apps.tenants.services.connect_service import ConnectService
                    connect_svc = ConnectService()
                    stripe_result = connect_svc.create_connected_payment_link(invoice)
                # Fall back to platform payment link
                if not stripe_result:
                    stripe_result = stripe_svc.create_payment_link(invoice)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Stripe link failed for {invoice.invoice_number}: {e}")

    # Optionally email — mark SENT only after confirmed delivery (CODE-096)
    if send_email and customer.email:
        from apps.billing.services.invoice_email_service import InvoiceEmailService
        try:
            email_svc = InvoiceEmailService(tenant=tenant)
            success, msg = email_svc.send_invoice_email(
                customer_id=customer_id,
                recipient_email=customer.email,
                repair_ids=repair_ids
            )
            if success:
                import django.utils.timezone as _tz
                invoice.status = 'SENT'
                invoice.sent_at = _tz.now()
                invoice.save(update_fields=['status', 'sent_at'])
            else:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"Invoice {invoice.invoice_number}: auto_email requested but "
                    f"delivery failed — keeping DRAFT. Reason: {msg}"
                )
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"Invoice {invoice.invoice_number}: email exception — keeping DRAFT. "
                f"Error: {_e}"
            )

    try:
        return JsonResponse({
            'success': True,
            'invoice': {
                'id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'total': float(invoice.total),
                'tax_rate': float(invoice.tax_rate),
                'tax_amount': float(invoice.tax_amount),
                'status': invoice.status,
                'due_date': invoice.due_date.isoformat() if invoice.due_date else None,
                'line_items': invoice.line_items.count(),
                's3_key': getattr(invoice, 's3_key', ''),
                'stripe': stripe_result,
            },
        })
    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(f"Response build failed: {traceback.format_exc()}")
        return JsonResponse({'error': f'Invoice created but response failed: {str(e)}'}, status=500)


@requires_api('invoices')
@require_POST
def send_invoice_email(request, invoice_id):
    """
    Send (or resend) an invoice email to the customer.

    POST body (optional):
    {
        "recipient_email": "custom@email.com",   // override recipient
        "cc_emails": ["cc1@example.com", ...]    // additional recipients
    }
    """
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice

    try:
        invoice = Invoice.objects.get(id=invoice_id, tenant=tenant)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)

    # Parse request body for custom recipients
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    # Use custom recipient or fall back to customer email
    recipient_email = data.get('recipient_email') or invoice.customer.email
    cc_emails = data.get('cc_emails', [])

    if not recipient_email:
        return JsonResponse({'error': f'No email address provided and no email on file for {invoice.customer.name}'}, status=400)

    if invoice.status == 'PAID':
        return JsonResponse({'error': f'Invoice {invoice.invoice_number} is already paid'}, status=400)

    try:
        from apps.billing.services.invoice_email_service import InvoiceEmailService
        email_svc = InvoiceEmailService(tenant=tenant)
        repair_ids = list(invoice.line_items.values_list('repair_id', flat=True))
        success, msg = email_svc.send_invoice_email(
            customer_id=invoice.customer_id,
            recipient_email=recipient_email,
            repair_ids=repair_ids if repair_ids else None,
            cc_emails=cc_emails if cc_emails else None,
        )

        if not success:
            import logging
            logging.getLogger(__name__).warning(
                f"Email send returned failure for {invoice.invoice_number}: {msg}"
            )
            return JsonResponse({'error': f'Email failed: {msg}'}, status=500)

        # Update invoice status to SENT if it was DRAFT (only on confirmed delivery)
        if invoice.status == 'DRAFT':
            invoice.status = 'SENT'
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=['status', 'sent_at'])

        all_recipients = [recipient_email] + (cc_emails or [])
        return JsonResponse({'success': True, 'sent_to': ', '.join(all_recipients)})
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(f"Email send failed for {invoice.invoice_number}")
        return JsonResponse({'error': f'Email failed: {str(e)}'}, status=500)


@requires_api('invoices')
@require_POST
def send_invoice_email_batch(request):
    """Send invoice emails for multiple invoices at once."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    try:
        data = json.loads(request.body)
        invoice_ids = data.get('invoice_ids', [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not invoice_ids:
        return JsonResponse({'error': 'No invoice IDs provided'}, status=400)

    from apps.billing.models import Invoice
    from apps.billing.services.invoice_email_service import InvoiceEmailService
    email_svc = InvoiceEmailService(tenant=tenant)

    # Fetch all requested invoices in one query (with customer & line items prefetched)
    # to avoid N individual .get() calls + lazy FK traversals inside the loop.
    invoice_map = {
        inv.id: inv
        for inv in Invoice.objects.filter(
            id__in=invoice_ids, tenant=tenant
        ).select_related('customer').prefetch_related('line_items')
    }

    results = []
    for inv_id in invoice_ids:
        invoice = invoice_map.get(inv_id)
        if invoice is None:
            results.append({'id': inv_id, 'success': False, 'error': 'Not found'})
            continue
        try:
            if invoice.status == 'PAID':
                results.append({'id': inv_id, 'success': False, 'error': 'Already paid'})
                continue
            if not invoice.customer.email:
                results.append({'id': inv_id, 'success': False, 'error': 'No email'})
                continue
            repair_ids = [item.repair_id for item in invoice.line_items.all()]
            sent_ok, sent_msg = email_svc.send_invoice_email(
                customer_id=invoice.customer_id,
                recipient_email=invoice.customer.email,
                repair_ids=repair_ids if repair_ids else None,
            )
            if sent_ok:
                results.append({'id': inv_id, 'success': True, 'sent_to': invoice.customer.email})
            else:
                results.append({'id': inv_id, 'success': False, 'error': sent_msg})
        except Exception as e:
            results.append({'id': inv_id, 'success': False, 'error': str(e)})

    sent = sum(1 for r in results if r['success'])
    failed = len(results) - sent
    return JsonResponse({'success': True, 'sent': sent, 'failed': failed, 'results': results})


@requires_api('invoices')
@require_GET
def get_invoice(request, invoice_id):
    """Get detailed invoice with line items and payments."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice

    try:
        invoice = Invoice.objects.for_tenant(tenant).select_related('customer').get(id=invoice_id)
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
            'service_date': item.repair_date.isoformat() if item.repair_date else None,
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


@requires_api('invoices')
@require_POST
def record_payment(request, invoice_id):
    """
    Record a payment.
    POST: {"amount": 150, "payment_method": "CHECK", "reference_number": "Check #1234"}
    """
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

    try:
        invoice = Invoice.objects.for_tenant(tenant).get(id=invoice_id)
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
        service = InvoiceTrackingService(tenant=tenant)
        payment = service.record_payment(
            invoice=invoice,
            amount=data['amount'],
            payment_method=data.get('payment_method', 'OTHER').upper(),
            reference_number=data.get('reference_number', ''),
            notes=data.get('notes', ''),
            payment_date=payment_date,
        )

        invoice.refresh_from_db()

        # Send payment confirmation emails (non-blocking)
        notif_result = {'customer_sent': False, 'owner_sent': False}
        if not data.get('skip_notifications', False):
            try:
                from apps.billing.services.payment_notification_service import PaymentNotificationService
                notif_result = PaymentNotificationService().notify_payment(payment)
            except Exception:
                pass

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
            'notifications': notif_result,
        })
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)


@requires_api('invoices')
@require_POST
def cancel_invoice(request, invoice_id):
    """Cancel an invoice. POST: {"reason": "Duplicate invoice"}"""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice

    try:
        invoice = Invoice.objects.for_tenant(tenant).get(id=invoice_id)
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

@requires_api('invoices')
@require_GET
def get_uninvoiced_repairs(request, customer_id):
    """Get repairs that haven't been invoiced yet."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    repairs = InvoiceTrackingService(tenant=tenant).get_uninvoiced_repairs(customer)

    total = 0
    repair_data = []
    for r in repairs:
        disc = r.get_discounted_cost()
        repair_data.append({
            'id': r.id,
            'unit_number': r.unit_number,
            'damage_type': r.get_damage_type_display() or 'Repair',
            'service_date': r.repair_date.isoformat(),
            'cost': float(disc['final_cost']),
        })
        total += float(disc['final_cost'])

    return JsonResponse({
        'customer': {'id': customer.id, 'name': customer.name},
        'uninvoiced_repairs': repair_data,
        'count': len(repair_data),
        'total_value': total,
    })


@requires_api('invoices')
@require_POST
def dismiss_uninvoiced_repairs(request, customer_id):
    """
    Dismiss (skip invoicing) for repairs that were already paid outside the system.
    
    POST body:
    {
        "repair_ids": [1, 2, 3],    // specific repairs to dismiss
        "all": true                  // or dismiss all uninvoiced for this customer
    }
    """
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.technician_portal.models import Repair

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Get uninvoiced repairs for this customer
    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
    uninvoiced = InvoiceTrackingService(tenant=tenant).get_uninvoiced_repairs(customer)
    uninvoiced_ids = list(uninvoiced.values_list('id', flat=True))

    if data.get('all'):
        # Dismiss all uninvoiced repairs for this customer
        repair_ids = uninvoiced_ids
    elif data.get('repair_ids'):
        # Dismiss specific repairs (must be in uninvoiced list)
        repair_ids = [rid for rid in data['repair_ids'] if rid in uninvoiced_ids]
    else:
        return JsonResponse({'error': 'Provide repair_ids or set all=true'}, status=400)

    if not repair_ids:
        return JsonResponse({'error': 'No valid repairs to dismiss'}, status=400)

    # Mark repairs as skip_invoicing
    updated = Repair.objects.filter(id__in=repair_ids, customer=customer).update(skip_invoicing=True)

    return JsonResponse({
        'success': True,
        'dismissed_count': updated,
        'message': f'Dismissed {updated} repair(s) from invoicing',
    })


@requires_api('invoices')
@require_GET
def get_customer_balance(request, customer_id):
    """Get outstanding balance for a customer."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    balance = InvoiceTrackingService(tenant=tenant).get_customer_balance(customer)

    return JsonResponse({
        'customer': {'id': customer.id, 'name': customer.name, 'email': customer.email},
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


@requires_api('invoices')
@require_GET
def get_invoice_preferences(request, customer_id):
    """Get invoice preferences for a customer."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
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


@requires_api('invoices')
@require_POST
def update_invoice_preferences(request, customer_id):
    """Update invoice preferences for a customer."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    try:
        customer = Customer.objects.get(id=customer_id, tenant=tenant)
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

@requires_api('invoices')
@require_GET
def stripe_status(request):
    """Check Stripe integration status."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.stripe_service import StripeService
    svc = StripeService()
    return JsonResponse({
        'enabled': svc.is_enabled(),
        'test_mode': getattr(settings, 'STRIPE_TEST_MODE', True),
    })


@requires_api('invoices')
@require_POST
def create_checkout_session(request, invoice_id):
    """
    Create a Stripe Checkout Session for an invoice.
    Customer gets redirected to Stripe's hosted payment page.

    No duplicate invoice is created in Stripe — just a payment session.
    """
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice
    from apps.billing.services.stripe_service import StripeService

    try:
        invoice = Invoice.objects.for_tenant(tenant).get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)

    if invoice.amount_due <= 0:
        return JsonResponse({'error': 'Invoice already paid'}, status=400)

    svc = StripeService()
    if not svc.is_enabled():
        return JsonResponse({'error': 'Stripe not configured'}, status=503)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    result = svc.create_checkout_session(
        invoice,
        success_url=data.get('success_url'),
        cancel_url=data.get('cancel_url'),
    )
    return JsonResponse(result, status=200 if result['success'] else 400)


@requires_api('invoices')
@require_GET
def create_payment_link(request, invoice_id):
    """Get a Stripe payment link for an invoice."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice
    from apps.billing.services.stripe_service import StripeService

    try:
        invoice = Invoice.objects.for_tenant(tenant).get(id=invoice_id)
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
    """
    Handle Stripe webhook events.

    NOTE: This endpoint intentionally has NO login_required and keeps
    @csrf_exempt because Stripe sends webhook POST requests with
    signature verification (not session auth).
    """
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

@requires_api('invoices')
@require_GET
def reminder_summary(request):
    """Get count of invoices needing reminders."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.reminder_service import ReminderService
    return JsonResponse(ReminderService(tenant).get_reminder_summary())


@requires_api('invoices')
@require_POST
def send_reminder(request, invoice_id):
    """Send payment reminder for an invoice."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.models import Invoice
    from apps.billing.services.reminder_service import ReminderService

    try:
        invoice = Invoice.objects.for_tenant(tenant).get(id=invoice_id)
    except Invoice.DoesNotExist:
        return JsonResponse({'error': 'Invoice not found'}, status=404)

    if invoice.status in ('PAID', 'CANCELLED'):
        return JsonResponse({'error': f'Cannot remind for {invoice.status} invoice'}, status=400)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    reminder_type = data.get('reminder_type', 'overdue' if invoice.is_overdue else 'due_soon')
    result = ReminderService(tenant).send_reminder(invoice, reminder_type)

    if result['success']:
        return JsonResponse({'success': True, 'sent_to': invoice.customer.email})
    return JsonResponse(result, status=400)


@requires_api('invoices')
@require_POST
def process_all_reminders(request):
    """Process all pending reminders. For cron/scheduled tasks."""
    tenant, err = _get_tenant_or_403(request)
    if err:
        return err

    from apps.billing.services.reminder_service import ReminderService

    svc = ReminderService(tenant)
    due_soon = svc.process_due_soon_reminders()
    overdue = svc.process_overdue_reminders()

    return JsonResponse({
        'due_soon': due_soon,
        'overdue': overdue,
        'total_sent': due_soon['sent'] + overdue['sent'],
    })
