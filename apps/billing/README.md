# Billing App - RS Systems

**Author:** Amelia (Clawdbot AI)
**Version:** 2.4.0
**Last Updated:** March 12, 2026

## Overview

The billing app provides invoice management, payment tracking, and business intelligence for RS Systems. Designed to prevent double-billing, track payments (online and manual), and provide actionable insights.

### Architecture Decision

**Our database is the single source of truth for invoices.**

Stripe is a payment channel — NOT a second invoicing system. We use Stripe Payment Links and Checkout Sessions. We do NOT create Stripe Invoices.

```
Our Invoice (DB) ← Source of truth for ALL billing
    │
    ├── Check payment    → manually recorded (owner or tech)
    ├── Cash payment     → manually recorded (owner or tech)
    ├── Wire/ACH payment → manually recorded (owner)
    └── Stripe payment   → Payment Link → webhook → auto-recorded
```

## Models

### Invoice
Full lifecycle: DRAFT → SENT → PAID/PARTIAL/OVERDUE/CANCELLED

Key fields: `invoice_number`, `customer`, `due_date`, `subtotal`, `discount`, `total`, `amount_paid`, `status`, `s3_key` (PDF), `stripe_hosted_url`, `payment_terms`

### InvoiceLineItem
Links repairs to invoices — prevents double-billing. Each repair can only appear on one active invoice.

### Payment
Supports: STRIPE, CHECK, CASH, WIRE, ACH, OTHER. Tracks `reference_number`, `recorded_by`, `stripe_payment_id`.

### BillingConfig (Per-Tenant)
Company address, default payment terms, invoice prefix/footer, automation settings. **Each tenant has their own BillingConfig** via a OneToOne relationship with `Tenant`. Managed via Admin > Billing > Billing Configuration.

Use `BillingConfig.get_for_tenant(tenant)` — creates with defaults if the tenant doesn't have one yet. `get_instance()` raises `RuntimeError` to surface legacy callers.

Previously a singleton (CODE-002 — fixed 2026-03-14).

## Services

| Service | Purpose |
|---------|---------|
| `invoice_service.py` | PDF generation with ReportLab |
| `auto_invoice_service.py` | Auto-generate on repair completion (signal-driven) |
| `stripe_service.py` | Payment Links, Checkout Sessions, webhook handling |
| `invoice_email_service.py` | Email invoices with PDF + repair photos |
| `invoice_tracking_service.py` | Double-billing prevention, status tracking |
| `dashboard_service.py` | Business metrics and insights |
| `report_service.py` | Daily/weekly reports |
| `reminder_service.py` | Payment reminders (owner-triggered via UI + auto via cron) |

## Management Commands (Billing)

| Command | Schedule | Purpose |
|---------|----------|---------|
| `python manage.py process_batch_invoices` | 6 AM UTC via EB cron | Auto-generate batch invoices |
| `python manage.py process_overdue_invoices` | 8 AM UTC via EB cron | Mark overdue, send reminders |
| `python manage.py generate_aging_report` | 9 AM UTC via EB cron | Refresh aging data |

## Endpoints

### Billing API (`/api/billing/`)

**Dashboard & Reports:**
- `GET /dashboard/` — Full business dashboard
- `GET /reports/daily/` — Daily report (`?date=2026-01-28`)
- `GET /reports/weekly/` — Weekly report (`?week_start=2026-01-20`)

**Invoice CRUD:**
- `GET /invoices/` — List all (`?status=OVERDUE`, `?outstanding=true`)
- `POST /invoices/create/<customer_id>/` — Create invoice
- `GET /invoices/<id>/` — Invoice detail
- `POST /invoices/<id>/payment/` — Record payment
- `POST /invoices/<id>/cancel/` — Cancel invoice

**Customer Data:**
- `GET /customers/<id>/uninvoiced/` — Repairs ready to invoice
- `GET /customers/<id>/balance/` — Customer balance
- `GET /customers/<id>/preferences/` — Invoice preferences
- `POST /customers/<id>/preferences/update/` — Update preferences

**Stripe:**
- `GET /stripe/status/` — Check Stripe configuration
- `POST /stripe/checkout/<id>/` — Create Checkout Session
- `GET /stripe/payment-link/<id>/` — Get Payment Link URL
- `POST /stripe/webhook/` — Handle Stripe webhooks

**Reminders:**
- `GET /reminders/summary/` — Pending reminder counts
- `POST /reminders/send/<id>/` — Send reminder for one invoice
- `POST /reminders/process/` — Process all pending reminders

### Portal Endpoints (not in this app but use billing data)

**Customer Portal (`/app/`):**
- `GET /app/invoices/` — Customer invoice list
- `GET /app/invoices/<id>/` — Invoice detail with payment history
- `POST /app/invoices/<id>/pay/` — Initiate Stripe checkout

**Owner Portal (`/owner/`):**
- `GET /owner/invoices/` — Invoice dashboard with summary cards
- `GET /owner/invoices/<id>/` — Detail + manual payment form

**Technician Portal (`/tech/`):**
- `POST /tech/repairs/<id>/collect-payment/` — Record on-site payment

**Stripe Landing Pages (root URLs):**
- `/payment-complete` — Success page after Stripe payment
- `/payment-cancelled` — Cancellation return page

## Key Features

### Auto-Invoice on Completion
Signal in `signals.py` fires when repair status → COMPLETED. For `per_ticket` preference customers, generates PDF, saves to S3, emails customer with Stripe pay link.

### Double-Billing Prevention
`invoice_tracking_service.py` checks if any repair is already on an active invoice before creating a new one.

### Payment Confirmation Emails
On any payment (Stripe webhook or manual recording):
- Customer: branded HTML receipt with amount, method, remaining balance
- Owner: plain text notification with amount + customer + status
- Partial payments include "Pay Remaining Balance" button with Stripe link

### Customer Preferences
Per-customer in `CustomerRepairPreference`:
- `per_ticket` — Auto-generate invoice per completed repair
- `batch` — Group repairs, manual generation (Phase 6: auto batch)
- `manual` — Never auto-generate

## Configuration

```bash
# Required for S3 (PDF storage)
AWS_STORAGE_BUCKET_NAME=rs-systems-media-20251029

# Required for Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Required for emails
SENDGRID_API_KEY=SG....
```

### Stripe Webhook Setup
1. Stripe Dashboard → Webhooks → Add endpoint
2. URL: `https://rssystems.io/api/billing/stripe/webhook/`
3. Events: `checkout.session.completed`, `payment_intent.succeeded`

## Phase 6 Features (Complete as of Mar 12, 2026)

### AR Aging Report Widget
- Widget on `/owner/invoices/` showing Current / 1-30 / 31-60 / 61-90 / 90+ day buckets
- Color-coded green → dark red
- AJAX-loaded from `/owner/billing/aging/` JSON endpoint
- Export CSV at `/owner/billing/aging/export/`

### Statement of Account
- Per-customer statement at `/owner/customers/<id>/statement/`
- Shows all invoices + payments with running balance
- Print-friendly layout

### Send Reminder from Invoice List
- "Remind" button on each overdue/sent row in the invoice list
- AJAX toast on success

### EB Cron Scheduling
- `.ebextensions/11_billing_cron.config` — cron.d entries for billing commands

## All Phases Complete
See [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) for full history.
