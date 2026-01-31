# Billing & Payments Roadmap

> Created: Jan 31, 2026 — Amelia
> Status: Planning
> Priority: High — core revenue feature

## Current State (What Exists)

### ✅ Working
- **Auto-invoice on completion**: Per-ticket invoicing generates PDF, saves to S3, emails to customer
- **Invoice model**: Full Invoice + LineItem + Payment models with status tracking
- **Stripe service**: Payment Links / Checkout Sessions (code exists, needs Stripe keys configured)
- **Reminder service**: Overdue/upcoming reminders (code exists, not wired to UI)
- **Billing API**: 15+ endpoints at `/api/billing/` (dashboard, CRUD, Stripe, reminders)
- **Customer preferences**: `invoice_preference` (per_ticket/batch/manual), `billing_email`, `auto_email_invoices`
- **Owner billing page**: `/owner/billing/` — subscription management (SaaS billing, NOT customer billing)
- **Customer account settings**: Billing tab with invoice preference radio buttons

### ❌ Missing / Not Working
- **No payment terms** — customers can't request/have net 30, net 60, etc.
- **No Stripe keys configured** — `STRIPE_SECRET_KEY` not set in production
- **No pay-online link in invoice emails** — emails have PDF but no "Pay Now" button
- **No check payment address on invoices** — PDF doesn't include company mailing address
- **No payment status in portals** — no one can see if an invoice is paid/unpaid
- **No reminder UI** — reminder service exists but no portal buttons to trigger them
- **No owner billing dashboard for customer invoices** — owner billing page is for SaaS subscription only
- **Customer portal has no invoice history/payment view**
- **Tech portal has no payment visibility**

---

## Phase 1: Payment Terms & Customer Preferences (Owner Dashboard)
**Goal**: Owner can set payment terms per customer. Customers can request terms.

### 1.1 Model Changes
```python
# CustomerRepairPreference — add fields:
payment_terms = models.CharField(
    max_length=20,
    choices=[
        ('due_on_receipt', 'Due on Receipt'),
        ('net_15', 'Net 15'),
        ('net_30', 'Net 30'),
        ('net_45', 'Net 45'),
        ('net_60', 'Net 60'),
    ],
    default='due_on_receipt'
)
payment_terms_approved = models.BooleanField(default=False)
payment_terms_requested = models.CharField(max_length=20, blank=True)  # What customer asked for
```

### 1.2 Owner Dashboard — Customer Billing Management
- New page: `/owner/customers/<id>/billing/` or section in customer detail
- Shows: current payment terms, outstanding balance, invoice history
- Actions: approve/change payment terms, send reminder, view invoices
- Table view: all customers with balance due, sorted by amount/age

### 1.3 Customer Portal — Request Terms
- In account settings billing tab, add "Request Payment Terms" dropdown
- When customer selects net terms, it creates a pending request
- Owner gets notification of the request
- Owner approves → terms take effect on next invoice

### 1.4 Auto-set Due Dates
- When invoice is generated, `due_date` calculated from `payment_terms`
- `due_on_receipt` = invoice date
- `net_30` = invoice date + 30 days, etc.

**Estimated effort**: ~8 hours

---

## Phase 2: Stripe Integration (Pay Online)
**Goal**: Customers can pay invoices online via Stripe link in email.

### 2.1 Stripe Setup
- Configure `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` in EB env
- Create Stripe account (or verify existing) at dashboard.stripe.com
- Set webhook URL: `https://rockstarwindshield.repair/api/billing/stripe/webhook/`

### 2.2 Pay Now Button in Invoice Email
- Invoice email template gets "Pay Online" button
- Links to Stripe Checkout Session (generated per invoice)
- Flow: Customer clicks → Stripe hosted page → pays → webhook fires → Payment recorded → Invoice status updated

### 2.3 Stripe Webhook Handler
- `stripe_webhook` view already exists in billing/views.py
- Handles `checkout.session.completed` event
- Creates Payment record, updates Invoice status
- Sends payment confirmation email

### 2.4 Payment Link in Invoice PDF
- QR code or short URL on the PDF itself
- Customer can scan to pay even from a printed invoice

**Estimated effort**: ~10 hours
**Prerequisite**: Stripe account with API keys

---

## Phase 3: Check Payment Support
**Goal**: Invoices include mailing address for check payments.

### 3.1 Company Address in Tenant Model
```python
# Tenant — add fields (or TenantBillingConfig):
billing_address_line1 = models.CharField(max_length=200, blank=True)
billing_address_line2 = models.CharField(max_length=200, blank=True)
billing_city = models.CharField(max_length=100, blank=True)
billing_state = models.CharField(max_length=50, blank=True)
billing_zip = models.CharField(max_length=20, blank=True)
billing_phone = models.CharField(max_length=20, blank=True)
```

### 3.2 Owner Settings — Company Billing Info
- In owner settings, section for company billing address
- Required before invoicing is enabled
- Shows on all invoices and emails

### 3.3 Invoice PDF Update
- Add company address block ("Make checks payable to...")
- Include company logo, phone, email
- Professional invoice layout with remittance section

### 3.4 Invoice Email Template
- Footer with: "Pay online at [link] or mail check to [address]"
- Clear payment instructions

**Estimated effort**: ~6 hours

---

## Phase 4: Payment Status in Portals
**Goal**: All three portals show invoice/payment status.

### 4.1 Owner Portal — Invoice Dashboard
- New page: `/owner/invoices/` (or tab on existing dashboard)
- Table: all invoices with status badges (Paid ✅, Overdue 🔴, Sent 📤, Partial ⚠️)
- Filters: by customer, status, date range
- Actions: view PDF, record manual payment, send reminder, cancel
- Summary cards: total outstanding, overdue amount, payments this month

### 4.2 Customer Portal — My Invoices
- New page: `/app/invoices/` (or tab in account settings)
- List of all invoices for this customer
- Status, amount, due date, pay button (Stripe)
- Download PDF link
- Payment history

### 4.3 Technician Portal — Payment Badge
- On repair detail: show invoice status badge if invoiced
- On repair list: optional column showing if repair has been invoiced/paid
- Helps techs know if customer is in good standing

### 4.4 Reminder System
- Owner can click "Send Reminder" on any overdue invoice
- Auto-reminders: configurable schedule (7 days, 14 days, 30 days overdue)
- Reminder count tracked per invoice
- Customer sees "Payment Reminder" in notification bell

**Estimated effort**: ~15 hours

---

## Phase 5: Polish & Automation
**Goal**: Production-ready billing that runs itself.

### 5.1 Batch Invoicing
- For customers with `batch` preference: generate weekly/monthly consolidated invoices
- Management command or celery task: `process_batch_invoices`
- Groups uninvoiced repairs by customer, generates one invoice per customer

### 5.2 Overdue Auto-Processing
- Celery beat task: daily check for overdue invoices
- Auto-update status from SENT → OVERDUE when past due date
- Trigger reminder emails per schedule

### 5.3 Aging Report
- Owner dashboard: accounts receivable aging (current, 30, 60, 90+ days)
- Export to CSV
- Key metric for business health

### 5.4 Statement of Account
- Per-customer statement showing all invoices and payments
- Monthly or on-demand generation
- Email to customer

**Estimated effort**: ~12 hours

---

## Implementation Order

| Priority | Phase | Description | Hours | Dependencies |
|----------|-------|-------------|-------|--------------|
| 🔴 P0 | 1 | Payment terms & customer prefs | 8 | None |
| 🔴 P0 | 3 | Check address on invoices | 6 | None |
| 🟡 P1 | 4 | Payment status in portals | 15 | Phase 1 |
| 🟡 P1 | 2 | Stripe integration | 10 | Stripe account |
| 🟢 P2 | 5 | Automation & reports | 12 | Phases 1-4 |

**Total estimated**: ~51 hours

### Quick Wins (can do first)
1. Add company address to invoice PDF + email (Phase 3) — ~2 hrs
2. Payment terms model fields + due date calculation (Phase 1.1, 1.4) — ~2 hrs
3. Owner invoice list page (Phase 4.1) — ~4 hrs

---

## Questions for Drake
1. **Stripe account**: Do you have one? Test or live keys?
2. **Company address**: What address goes on invoices for check payments?
3. **Default terms**: Should new customers default to "Due on Receipt" or something else?
4. **Reminder frequency**: How aggressive? (e.g., 7 days, then weekly?)
5. **Batch invoicing**: For fleet customers, weekly or monthly consolidation?
