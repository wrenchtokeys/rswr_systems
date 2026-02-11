# Billing & Payments Roadmap

> Created: Jan 31, 2026 — Amelia
> Last updated: Jan 31, 2026
> Status: In Progress
> Priority: High — core revenue feature

## Current State (What Exists)

### ✅ Working
- **Auto-invoice on completion**: Per-ticket invoicing generates PDF, saves to S3, emails to customer
- **Invoice model**: Full Invoice + LineItem + Payment models with status tracking
- **BillingConfig**: Singleton with company address (street/city/state/zip), configurable via Admin > Billing > Billing Configuration
- **Payment terms**: Default COD (Cash on Delivery). Options: COD, Due on Receipt, NET15/30/45/60. Shown on PDF.
- **Stripe integration**: Payment Links auto-generated on invoice creation, Checkout Sessions, webhook handler
- **Stripe keys**: Configured in EB prod (test mode). Webhook at `https://rockstarwindshield.repair/api/billing/stripe/webhook/`
- **Invoice emails**: Include PDF attachment, repair photos, payment terms, and Stripe pay link
- **Reminder service**: Overdue/upcoming reminders (code exists, not wired to UI)
- **Billing API**: 15+ endpoints at `/api/billing/` (dashboard, CRUD, Stripe, reminders)
- **Customer preferences**: `invoice_preference` (per_ticket/batch/manual), `billing_email`, `auto_email_invoices`
- **Configurable invoice prefix, footer text** via BillingConfig

### ⏳ Needs Drake Action
- **Set `STRIPE_WEBHOOK_SECRET` in EB** — grab from Stripe Dashboard (starts with `whsec_`). Without this, webhooks reject all events and payments won't auto-record.
- **Run migration on prod** — `python manage.py migrate billing` (for BillingConfig + payment_terms)
- **Fill in BillingConfig** — Admin > Billing > Billing Configuration (company address)

### ❌ Not Yet Built
- ~~**No payment confirmation emails**~~ ✅ Done (Phase 4)
- ~~**No payment status in portals**~~ ✅ Done (Phase 5)
- **No reminder UI** — reminder service exists but no portal buttons to trigger them
- ~~**No owner billing dashboard for customer invoices**~~ ✅ Done (Phase 5.2)
- ~~**Customer portal has no invoice history/payment view**~~ ✅ Done (Phase 5.1)
- **Tech portal has no payment visibility** (deferred)
- ~~No sales tax calculation~~ — **Sales tax complete** (Phase 8, v2.2.1)
- **No manual payment UI** ✅ Done — owner can record cash/check/wire/ACH (Phase 5.2)

---

## ~~Phase 1: Payment Terms & Customer Preferences~~ ✅ DONE (PR #13)

- [x] BillingConfig singleton: company address, default payment terms, invoice defaults
- [x] Payment terms on Invoice model (COD default, NET15/30/45/60 options)
- [x] Due date auto-calculated from terms (COD=today, NET30=+30 days)
- [x] Payment terms displayed on invoice PDF
- [x] Configurable via Admin > Billing > Billing Configuration
- [ ] Per-customer payment terms override (future — currently uses global default)
- [ ] Customer portal: request payment terms (future)

---

## ~~Phase 2: Stripe Integration (Pay Online)~~ ✅ DONE

- [x] Stripe keys configured in EB (test mode)
- [x] Webhook endpoint: `https://rockstarwindshield.repair/api/billing/stripe/webhook/`
- [x] Payment Links auto-generated on every invoice creation
- [x] Checkout Sessions supported
- [x] Webhook handles checkout.session.completed + payment_intent.succeeded
- [x] Auto-records Payment → updates Invoice status to PAID
- [x] Invoice emails include "Pay Online" link
- [ ] **BLOCKED**: Set `STRIPE_WEBHOOK_SECRET` in EB (Drake)
- [ ] QR code on PDF for scan-to-pay (future)

---

## ~~Phase 3: Check Payment Support~~ ✅ DONE (PR #13)

- [x] BillingConfig: structured address fields (street, city, state, zip, phone, email)
- [x] Company address shown on invoice PDF header
- [x] Configurable via Admin dashboard
- [ ] "Make checks payable to..." section on PDF (future polish)

---

## ~~Phase 4: Payment Confirmation Emails~~ ✅ DONE (PR #16)

- [x] Customer receipt email (branded HTML + plain text)
- [x] Shows: amount, method, date, invoice summary, remaining balance
- [x] "Pay Remaining Balance" button for partial payments with Stripe link
- [x] Owner notification email (plain text, subject shows amount + customer + status)
- [x] Wired into Stripe webhook (auto on online payment)
- [x] Wired into manual payment API (auto on record_payment)
- [x] Non-fatal — notification failures don't break payment recording
- [ ] Stripe refund handling (charge.refunded webhook → future)

---

## Phase 5: Invoice Portals & Payment Management ✅ DONE (PR #16)
**Goal**: Customers can view/pay invoices. Owners can manage payments.

### 5.1 Customer Portal — My Invoices ✅
- [x] Invoice list page: `/app/invoices/`
- [x] Click invoice → detail view (receipt): line items, subtotal, discount, total, payment history
- [x] Status badges (Paid ✅, Overdue 🔴, Sent 📤, Partial ⚠️, Cancelled)
- [x] "Pay Now" button → Stripe checkout (creates session, redirects)
- [x] Download PDF link (S3)
- [x] Payment history per invoice
- [x] "Invoices" nav link added to customer portal

### 5.2 Owner Portal — Invoice Dashboard ✅
- [x] Invoice list page: `/owner/invoices/` with summary cards
- [x] Table: all invoices with status badges, filters by customer + status
- [x] **Record Manual Payment form** (cash, check, wire, ACH, credit card, other)
- [x] Form fields: amount (defaults to balance), method, reference #, date, notes
- [x] Auto-updates invoice status + sends confirmation emails
- [x] Actions: view PDF, record payment
- [x] Summary cards: total outstanding, overdue amount, payments this month, invoices this month
- [x] Owner dashboard linked to invoice list
- [x] **Clickable overdue badge** — Click overdue card to filter all overdue invoices (Feb 4, 2026)
- [x] **Overdue count badge** — Shows number of overdue invoices on the summary card
- [x] **Send confirmation modal** — "Create & Send" shows preview before sending (Feb 4, 2026):
  - Subject preview
  - Invoice summary (number, repair count, total)
  - Editable recipient email
  - Multi-recipient support (comma-separated)
  - CC support for additional recipients
- [x] **Dismiss uninvoiced repairs** — "Dismiss" button for legacy repairs already paid outside system (Feb 4, 2026):
  - Marks repairs with `skip_invoicing=True`
  - Hides them from uninvoiced section without deleting
  - API: `POST /api/billing/customers/<id>/uninvoiced/dismiss/`

### 5.3 Technician Portal — Payment Badge
- [ ] On repair detail: show invoice status badge if invoiced
- [ ] On repair list: optional column showing if repair has been invoiced/paid

### 5.4 Reminder System ✅ (Feb 4, 2026)
- [x] Owner can click "Send Reminder" on any overdue/outstanding invoice
- [x] Reminder button on invoice detail page (`/owner/invoices/<id>/`)
- [x] Sends appropriate email (overdue vs due_soon) based on invoice status
- [x] **PDF invoice attached** to reminder emails
- [x] Subject format: `[RS Systems] Overdue Notice: Invoice X - Customer`
- [x] "Do not reply" footer (no inbound email configured)
- [x] Reminder logged in invoice internal_notes
- [ ] Auto-reminders: configurable schedule (7 days, 14 days, 30 days overdue)
- [ ] Reminder count tracked per invoice

**Note**: 5.3 deferred. Auto-reminders for Phase 6.

### Email Configuration
- **From**: Uses `DEFAULT_FROM_EMAIL` env var (default: `notifications@rockstarwindshield.repair`)
- **Replies**: Not supported — emails include "do not reply" notice
- **Future**: Consider Google Workspace or SendGrid Inbound Parse for reply handling

---

## Phase 6: Polish & Automation
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

| Priority | Phase | Description | Status | Hours |
|----------|-------|-------------|--------|-------|
| ✅ | 1 | Payment terms & BillingConfig | DONE | — |
| ✅ | 2 | Stripe integration | DONE (needs webhook secret) | — |
| ✅ | 3 | Company address on invoices | DONE | — |
| ✅ | 4 | Payment confirmation emails | DONE | — |
| ✅ | 5 | Invoice portals & payment management | DONE (5.1 + 5.2) | — |
| 🟢 P2 | 6 | Automation & reports | — | ~12 |
| 🔴 P1 | 7 | SaaS subscription billing | — | TBD |
| 🟡 P1 | 8 | Sales tax by zip code | — | ~8-12 |

**Remaining estimated**: ~31 hours

### Resolved Questions
- **Stripe account**: ✅ Test keys configured in EB
- **Default terms**: COD (Cash on Delivery) per Drake
- **Company address**: Configurable via BillingConfig admin (Drake to fill in)

### Open Questions
- **Reminder frequency**: How aggressive? (e.g., 7 days, then weekly?)
- **Batch invoicing**: For fleet customers, weekly or monthly consolidation?
- **Per-customer payment terms**: Need override per customer, or global default enough for now?

---

## Phase 8: Sales Tax ✅ COMPLETE (Feb 1, 2026)

**Goal**: Automatically calculate and apply correct sales tax on repairs and invoices.

### What was built
- **BillingConfig rate fields**: `state_tax_rate`, `county_tax_rate`, `city_tax_rate`, `special_tax_rate` with auto-calculated `default_tax_rate` (total). Shop owners enter their rates in Settings → Billing & Tax.
- **Tax on repairs**: `tax_rate` and `tax_amount` fields on Repair model. Tax auto-calculated on every `save()` via `TaxService`. `total_with_tax` property returns cost + tax. Displayed on tech and customer repair detail pages.
- **Tax on invoices**: `tax_rate`, `state_tax_rate`, `county_tax_rate`, `city_tax_rate`, `special_tax_rate`, `tax_amount` fields on Invoice model. Tax calculated at invoice creation time via `TaxService.apply_tax_to_invoice()`. PDF shows full breakdown.
- **Per-customer exemption**: `Customer.tax_exempt` flag → $0 tax regardless of global setting.
- **Auto-enable**: Saving non-zero rates auto-sets `tax_enabled = True`.
- **No-tax mode**: `BillingConfig.tax_enabled = False` → everything stays $0.

### Design decisions
- **No tax table / API** — shop owner enters their local rates directly. Simple, no maintenance, no external deps.
- **Tax on the invoice, not at checkout** — check/cash customers pay the same tax-inclusive total as Stripe customers.
- **Tax calculated at creation time** — rate is frozen on the invoice/repair record so historical records stay accurate even if rates change later.

### Completed tasks
- [x] Add tax rate breakdown fields to BillingConfig
- [x] Add `tax_rate`, `tax_amount` fields to Invoice model (with breakdown)
- [x] Add `tax_rate`, `tax_amount` fields to Repair model
- [x] Add `tax_enabled` toggle to BillingConfig (global on/off)
- [x] Add `tax_exempt` flag on Customer model
- [x] Tax auto-calculated on Repair.save()
- [x] Tax applied at invoice creation via InvoiceTrackingService
- [x] Invoice PDF shows tax breakdown (state/county/city/special)
- [x] Email templates show tax breakdown
- [x] Settings UI: 4 rate fields with live-updating total
- [x] Tech portal repair detail shows tax
- [x] Customer portal repair detail shows tax

---

## Phase 7: SaaS Subscription Billing (Glass Shops)

Separate from customer billing — this is charging glass shops to use RS Systems.

**Already built:**
- SubscriptionPlan model (Trial/Starter $49/Pro $99/Enterprise $249)
- Plan limits (repairs/month, technicians, customers, storage)
- Feature flags per plan
- SubscriptionService + signup flow
- Owner billing page at `/owner/billing/`
- Tenant webhook handler

**Still needed (Drake action):**
- [ ] Create Stripe Products + Prices in Stripe Dashboard
- [ ] Copy `stripe_price_id` / `stripe_annual_price_id` into SubscriptionPlan records

**Completed (Feb 10, 2026):**
- [x] Wire up subscription checkout flow (owner upgrades/downgrades plan)
- [x] Handle subscription webhooks (invoice.paid, customer.subscription.updated/deleted)
- [x] Dunning — handle failed subscription payments gracefully (past_due banner + email)
- [x] Usage enforcement — block actions when plan limits hit (repairs, techs, customers)
- [x] Trial expiration → prompt to upgrade (expired + expiring banners)
- [x] Billing portal link (Stripe Customer Portal for managing payment method/invoices)
