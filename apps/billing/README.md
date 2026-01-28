# Billing App - RS Systems

**Author:** Amelia (Clawdbot AI)  
**Version:** 0.5.0  
**Created:** January 27-28, 2026

## Overview

The billing app provides comprehensive invoice management, payment tracking, and business intelligence for RS Systems. It's designed to prevent double-billing, track payments (both online and manual), and provide actionable insights.

## Architecture

```
apps/billing/
├── models.py                    # Invoice, InvoiceLineItem, Payment
├── admin.py                     # Django admin interfaces
├── signals.py                   # Auto-invoice on repair completion
├── services/
│   ├── invoice_service.py       # PDF generation (from clawdbot)
│   ├── invoice_email_service.py # Email invoices with photos
│   ├── auto_invoice_service.py  # Auto-generate on repair completion
│   ├── invoice_tracking_service.py # Tracking, double-billing prevention
│   ├── dashboard_service.py     # Business metrics and insights
│   ├── report_service.py        # Daily/weekly reports
│   ├── reminder_service.py      # Payment reminders
│   └── stripe_service.py        # Stripe integration
└── migrations/
```

## Models

### Invoice
Tracks invoices with full lifecycle management.

```python
Invoice:
  - invoice_number (unique)
  - customer (FK to Customer)
  - invoice_date, due_date
  - subtotal, discount, total, amount_paid
  - status: DRAFT → SENT → PAID/PARTIAL/OVERDUE/CANCELLED
  - s3_key (PDF storage location)
  - stripe_invoice_id, stripe_hosted_url, stripe_payment_intent_id
  - sent_at, paid_at
  - notes, internal_notes
```

### InvoiceLineItem
Links repairs to invoices - this is how we prevent double-billing.

```python
InvoiceLineItem:
  - invoice (FK)
  - repair (FK to Repair) ← THE KEY RELATIONSHIP
  - description, quantity, unit_price, discount, amount
  - repair_date, unit_number
```

### Payment
Tracks all payments with multiple method support.

```python
Payment:
  - invoice (FK)
  - amount, payment_date
  - payment_method: STRIPE, CHECK, CASH, WIRE, ACH, OTHER
  - reference_number, stripe_payment_id
  - recorded_by (User FK)
```

## Key Features

### Double-Billing Prevention

When creating an invoice, we check if any repairs are already on active invoices:

```python
# In invoice_tracking_service.py
for repair in repairs:
    if repair.invoice_line_items.filter(
        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL', 'PAID']
    ).exists():
        raise ValueError(f"Repair {repair.id} already invoiced")
```

### Auto-Invoice on Completion

When a repair is marked COMPLETED, a Django signal fires:

```python
# In signals.py
@receiver(post_save, sender='technician_portal.Repair')
def handle_repair_completed(sender, instance, **kwargs):
    if instance.queue_status == 'COMPLETED':
        # Check customer preference
        if prefs.invoice_preference == 'per_ticket':
            auto_invoice_service.generate_and_save(instance)
```

### Customer Invoice Preferences

Set per-customer in `CustomerRepairPreference`:

| Preference | Behavior |
|------------|----------|
| `per_ticket` | Auto-generate invoice when each repair completes |
| `batch` | Group repairs, manual invoice generation |
| `manual` | Never auto-generate |

## API Endpoints

All endpoints are under `/clawdbot/`:

### Dashboard & Reports
```
GET /dashboard/                 - Full business dashboard
GET /reports/daily/             - Daily report
GET /reports/daily/?date=2026-01-28
GET /reports/weekly/            - Weekly report
GET /reports/weekly/?week_start=2026-01-20
```

### Invoice Management
```
GET  /billing/invoices/                    - List all invoices
GET  /billing/invoices/?status=OVERDUE     - Filter by status
GET  /billing/invoices/?outstanding=true   - Only unpaid
GET  /billing/invoices/{id}/               - Invoice detail
POST /billing/invoices/{id}/payment/       - Record payment
GET  /billing/uninvoiced/{customer_id}/    - Repairs ready to invoice
GET  /billing/balance/{customer_id}/       - Customer balance
```

### Stripe Integration
```
GET  /stripe/status/                - Check if Stripe configured
POST /stripe/invoice/{id}/          - Create Stripe invoice
GET  /stripe/payment-link/{id}/     - Get payment link URL
POST /stripe/webhook/               - Handle Stripe webhooks
```

### Reminders
```
GET  /reminders/summary/           - Pending reminder counts
POST /reminders/send/{invoice_id}/ - Send reminder for one invoice
POST /reminders/process/           - Process all pending reminders
```

## Configuration

### Environment Variables

```bash
# Required for S3 storage
AWS_STORAGE_BUCKET_NAME=rs-systems-media-20251029

# Required for Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Required for email reminders
SENDGRID_API_KEY=SG....
```

### Stripe Webhook Setup

1. In Stripe Dashboard → Webhooks → Add endpoint
2. URL: `https://yourdomain.com/clawdbot/stripe/webhook/`
3. Events to listen for:
   - `invoice.paid`
   - `invoice.payment_failed`
   - `payment_intent.succeeded`
   - `checkout.session.completed`

## Usage Examples

### Record a manual payment
```bash
curl -X POST http://localhost:8001/clawdbot/billing/invoices/1/payment/ \
  -H "Content-Type: application/json" \
  -d '{"amount": 150, "payment_method": "CHECK", "reference_number": "Check #1234"}'
```

### Get business dashboard
```bash
curl http://localhost:8001/clawdbot/dashboard/
```

### Create Stripe payment link
```bash
curl http://localhost:8001/clawdbot/stripe/payment-link/1/
# Returns: {"payment_link": "https://buy.stripe.com/..."}
```

## Cron Jobs

Add these to your crontab for automated processing:

```cron
# Update overdue invoice statuses daily at midnight
0 0 * * * curl -X POST http://localhost:8001/clawdbot/reminders/process/

# Alternative: Django management command (TODO: create)
# 0 0 * * * cd /path/to/rswr_systems && python manage.py process_reminders
```

## Testing

```bash
# Run with test database
LOCAL_DATABASE_URL="postgresql://..." python manage.py test apps.billing

# Manual testing
python manage.py shell
>>> from apps.billing.services.dashboard_service import DashboardService
>>> service = DashboardService()
>>> dashboard = service.get_full_dashboard()
>>> print(dashboard['revenue'])
```

## Future Enhancements

- [ ] Invoice PDF templates (custom branding)
- [ ] Recurring invoices
- [ ] Credit notes / refunds
- [ ] Multi-currency support
- [ ] QuickBooks integration
- [ ] Automated dunning (escalating reminders)
- [ ] Customer portal for viewing/paying invoices
