# Billing & Payments Roadmap

> Created: Jan 31, 2026  Amelia
> Last updated: February 11, 2026
> Status:  Complete
> Priority: High  core revenue feature

 **For how billing works, see [BILLING_GUIDE.md](docs/BILLING_GUIDE.md)**

## Current State (What Exists)

###  Working
- **Auto-invoice on completion**: Per-ticket invoicing generates PDF, saves to S3, emails to customer
- **Invoice model**: Full Invoice + LineItem + Payment models with status tracking
- **BillingConfig**: Singleton with company address (street/city/state/zip), configurable via Admin > Billing > Billing Configuration
- **Payment terms**: Default COD (Cash on Delivery). Options: COD, Due on Receipt, NET15/30/45/60. Shown on PDF.
- **Stripe integration**: Payment Links auto-generated on invoice creation, Checkout Sessions, webhook handler
- **Stripe keys**: Configured in EB prod (test mode). Webhook at `https://rssystems.io/api/billing/stripe/webhook/`
- **Invoice emails**: Include PDF attachment, repair photos, payment terms, and Stripe pay link
- **Reminder service**: Overdue/upcoming reminders (code exists, not wired to UI)
- **Billing API**: 15+ endpoints at `/api/billing/` (dashboard, CRUD, Stripe, reminders)
- **Customer preferences**: `invoice_preference` (per_ticket/batch/manual), `billing_email`, `auto_email_invoices`
- **Configurable invoice prefix, footer text** via BillingConfig

###  Needs Drake Action
- **Set `STRIPE_WEBHOOK_SECRET` in EB**  grab from Stripe Dashboard (starts with `whsec_`). Without this, webhooks reject all events and payments won't auto-record.
- **Run migration on prod**  `python manage.py migrate billing` (for BillingConfig + payment_terms)
- **Fill in BillingConfig**  Admin > Billing > Billing Configuration (company address)

###  Not Yet Built
- ~~**No payment confirmation emails**~~  Done (Phase 4)
- ~~**No payment status in portals**~~  Done (Phase 5)
- **No reminder UI**  reminder service exists but no portal buttons to trigger them
- ~~**No owner billing dashboard for customer invoices**~~  Done (Phase 5.2)
- ~~**Customer portal has no invoice history/payment view**~~  Done (Phase 5.1)
- **Tech portal has no payment visibility** (deferred)
- ~~No sales tax calculation~~  **Sales tax complete** (Phase 8, v2.2.1)
- **No manual payment UI**  Done  owner can record cash/check/wire/ACH (Phase 5.2)

---

## ~~Phase 1: Payment Terms & Customer Preferences~~  DONE (PR #13)

- [x] BillingConfig singleton: company address, default payment terms, invoice defaults
- [x] Payment terms on Invoice model (COD default, NET15/30/45/60 options)
- [x] Due date auto-calculated from terms (COD=today, NET30=+30 days)
- [x] Payment terms displayed on invoice PDF
- [x] Configurable via Admin > Billing > Billing Configuration
- [ ] Per-customer payment terms override (future  currently uses global default)
- [ ] Customer portal: request payment terms (future)

---

## ~~Phase 2: Stripe Integration (Pay Online)~~  DONE

- [x] Stripe keys configured in EB (test mode)
- [x] Webhook endpoint: `https://rssystems.io/api/billing/stripe/webhook/`
- [x] Payment Links auto-generated on every invoice creation
- [x] Checkout Sessions supported
- [x] Webhook handles checkout.session.completed + payment_intent.succeeded
- [x] Auto-records Payment  updates Invoice status to PAID
- [x] Invoice emails include "Pay Online" link
- [ ] **BLOCKED**: Set `STRIPE_WEBHOOK_SECRET` in EB (Drake)
- [ ] QR code on PDF for scan-to-pay (future)

---

## ~~Phase 3: Check Payment Support~~  DONE (PR #13)

- [x] BillingConfig: structured address fields (street, city, state, zip, phone, email)
- [x] Company address shown on invoice PDF header
- [x] Configurable via Admin dashboard
- [ ] "Make checks payable to..." section on PDF (future polish)

---

## ~~Phase 4: Payment Confirmation Emails~~  DONE (PR #16)

- [x] Customer receipt email (branded HTML + plain text)
- [x] Shows: amount, method, date, invoice summary, remaining balance
- [x] "Pay Remaining Balance" button for partial payments with Stripe link
- [x] Owner notification email (plain text, subject shows amount + customer + status)
- [x] Wired into Stripe webhook (auto on online payment)
- [x] Wired into manual payment API (auto on record_payment)
- [x] Non-fatal  notification failures don't break payment recording
- [ ] Stripe refund handling (charge.refunded webhook  future)

---

## Phase 5: Invoice Portals & Payment Management  DONE (PR #16)
**Goal**: Customers can view/pay invoices. Owners can manage payments.

### 5.1 Customer Portal  My Invoices 
- [x] Invoice list page: `/app/invoices/`
- [x] Click invoice  detail view (receipt): line items, subtotal, discount, total, payment history
- [x] Status badges (Paid , Overdue , Sent , Partial , Cancelled)
- [x] "Pay Now" button  Stripe checkout (creates session, redirects)
- [x] Download PDF link (S3)
- [x] Payment history per invoice
- [x] "Invoices" nav link added to customer portal

### 5.2 Owner Portal  Invoice Dashboard 
- [x] Invoice list page: `/owner/invoices/` with summary cards
- [x] Table: all invoices with status badges, filters by customer + status
- [x] **Record Manual Payment form** (cash, check, wire, ACH, credit card, other)
- [x] Form fields: amount (defaults to balance), method, reference #, date, notes
- [x] Auto-updates invoice status + sends confirmation emails
- [x] Actions: view PDF, record payment
- [x] Summary cards: total outstanding, overdue amount, payments this month, invoices this month
- [x] Owner dashboard linked to invoice list
- [x] **Clickable overdue badge**  Click overdue card to filter all overdue invoices (Feb 4, 2026)
- [x] **Overdue count badge**  Shows number of overdue invoices on the summary card
- [x] **Send confirmation modal**  "Create & Send" shows preview before sending (Feb 4, 2026):
  - Subject preview
  - Invoice summary (number, repair count, total)
  - Editable recipient email
  - Multi-recipient support (comma-separated)
  - CC support for additional recipients
- [x] **Dismiss uninvoiced repairs**  "Dismiss" button for legacy repairs already paid outside system (Feb 4, 2026):
  - Marks repairs with `skip_invoicing=True`
  - Hides them from uninvoiced section without deleting
  - API: `POST /api/billing/customers/<id>/uninvoiced/dismiss/`

### 5.3 Technician Portal  Payment Badge
- [ ] On repair detail: show invoice status badge if invoiced
- [ ] On repair list: optional column showing if repair has been invoiced/paid

### 5.4 Reminder System  (Feb 4, 2026)
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
- **From**: Uses `DEFAULT_FROM_EMAIL` env var (default: `notifications@rssystems.io`)
- **Replies**: Not supported  emails include "do not reply" notice
- **Future**: Consider Google Workspace or SendGrid Inbound Parse for reply handling

---

## Phase 6 UI: Dashboard Surfaces & Automation  DONE (Mar 12, 2026)
**Goal**: Surface billing data in the owner portal UI. Built by Amelia.

### 6 UI.1 Aging Report Widget 
- [x] AR aging widget on owner invoice list (`/owner/invoices/`)
- [x] Buckets: Current, 1-30, 31-60, 61-90, 90+ days — color-coded green→dark red
- [x] AJAX-loaded from `/owner/billing/aging/` JSON endpoint
- [x] Export CSV button at `/owner/billing/aging/export/`

### 6 UI.2 Statement of Account 
- [x] Per-customer statement at `/owner/customers/<id>/statement/`
- [x] Shows all invoices + payments with running balance
- [x] Print-friendly layout, no nav clutter
- [x] Print button (CSS @media print)

### 6 UI.3 Send Reminder from Invoice List 
- [x] "Remind" button on each overdue/sent invoice row in the list
- [x] AJAX call with toast notification on success
- [x] Uses existing `owner_send_reminder` view

### 6 UI.4 EB Cron Scheduling 
- [x] `.ebextensions/11_billing_cron.config` — cron.d file for billing commands
- [x] process_batch_invoices at 6 AM UTC daily
- [x] process_overdue_invoices at 8 AM UTC daily
- [x] generate_aging_report at 9 AM UTC daily

---

## Phase 6: Polish & Automation  DONE (Feb 11, 2026)
**Goal**: Production-ready billing that runs itself.

### 6.1 Batch Invoicing 
- [x] Management command: `python manage.py process_batch_invoices` (scheduled via EB cron at 6 AM UTC)
- [x] Configurable frequency: weekly, bi-weekly, monthly, or disabled
- [x] Configurable day: day of week (0-6) or day of month (1-28)
- [x] Auto-send option: creates as DRAFT or sends immediately
- [x] Groups uninvoiced repairs + replacements by customer
- [x] Only processes customers with `invoice_preference='batch'`

### 6.2 Overdue Auto-Processing 
- [x] Management command: `python manage.py process_overdue_invoices` (scheduled via EB cron at 8 AM UTC)
- [x] Auto-update status from SENT/PARTIAL → OVERDUE when past due date
- [x] Configurable reminder schedule (e.g., "7,14,30" days after due)
- [x] Customizable email subject template with variables
- [x] Reminders logged in invoice internal_notes
- [x] Enable/disable toggle in BillingConfig

### 6.3 Aging Report 
- [x] Management command: `python manage.py generate_aging_report` (scheduled via EB cron at 9 AM UTC)
- [x] Buckets: current, 1-30, 31-60, 61-90, 90+ days
- [x] Returns count + total per bucket, plus invoice details
- [x] Can run for single tenant or all tenants
- [x] UI dashboard widget — `/owner/invoices/` (Phase 6 UI)
- [x] Export to CSV — `/owner/billing/aging/export/` (Phase 6 UI)

### 6.4 Statement of Account
- [x] Per-customer statement — `/owner/customers/<id>/statement/` (Phase 6 UI)
- [ ] Monthly email generation (future)

### Configuration (BillingConfig)
All automation settings are configurable in Settings  Billing:

| Setting | Description | Default |
|---------|-------------|---------|
| `overdue_reminder_enabled` | Enable automatic reminder emails | Off |
| `overdue_reminder_days` | Days to send reminders (comma-separated) | "7,14,30" |
| `overdue_reminder_subject` | Email subject template | "Reminder: Invoice #{invoice_number} is overdue" |
| `batch_invoice_frequency` | disabled / weekly / biweekly / monthly | disabled |
| `batch_invoice_day` | Day to run (0-6 for weekly, 1-28 for monthly) | 1 |
| `batch_invoice_auto_send` | Send immediately or create as DRAFT | Off |

**Migration**: `0010_add_automation_config`

---

## Implementation Order

| Priority | Phase | Description | Status | Hours |
|----------|-------|-------------|--------|-------|
|  | 1 | Payment terms & BillingConfig | DONE |  |
|  | 2 | Stripe integration | DONE |  |
|  | 3 | Company address on invoices | DONE |  |
|  | 4 | Payment confirmation emails | DONE |  |
|  | 5 | Invoice portals & payment management | DONE |  |
|  | 6 | Automation & reports | DONE (Feb 11, 2026) |  |
|  | 7 | SaaS subscription billing | DONE (Feb 11, 2026) |  |
|  | 8 | Sales tax by zip code | DONE (Feb 1, 2026) |  |

**All phases complete!** 

### Resolved Questions
- **Stripe account**:  Test keys configured in EB
- **Default terms**: COD (Cash on Delivery) per Drake
- **Company address**: Configurable via BillingConfig admin (Drake to fill in)

### Resolved Questions
- **Reminder frequency**: Configurable via `overdue_reminder_days` (default: 7, 14, 30 days)
- **Batch invoicing**: Configurable frequency (weekly/biweekly/monthly) + day
- **Per-customer payment terms**: Global default for now (per-customer override in backlog)

---

## Phase 8: Sales Tax  COMPLETE (Feb 1, 2026)

**Goal**: Automatically calculate and apply correct sales tax on repairs and invoices.

### What was built
- **BillingConfig rate fields**: `state_tax_rate`, `county_tax_rate`, `city_tax_rate`, `special_tax_rate` with auto-calculated `default_tax_rate` (total). Shop owners enter their rates in Settings  Billing & Tax.
- **Tax on repairs**: `tax_rate` and `tax_amount` fields on Repair model. Tax auto-calculated on every `save()` via `TaxService`. `total_with_tax` property returns cost + tax. Displayed on tech and customer repair detail pages.
- **Tax on invoices**: `tax_rate`, `state_tax_rate`, `county_tax_rate`, `city_tax_rate`, `special_tax_rate`, `tax_amount` fields on Invoice model. Tax calculated at invoice creation time via `TaxService.apply_tax_to_invoice()`. PDF shows full breakdown.
- **Per-customer exemption**: `Customer.tax_exempt` flag  $0 tax regardless of global setting.
- **Auto-enable**: Saving non-zero rates auto-sets `tax_enabled = True`.
- **No-tax mode**: `BillingConfig.tax_enabled = False`  everything stays $0.

### Design decisions
- **No tax table / API** — shop owner enters their local rates directly. Simple, no maintenance, no external deps.
- **Tax on the invoice, not at checkout** — check/cash customers pay the same tax-inclusive total as Stripe customers.
- **Tax calculated at creation time** — rate is frozen on the invoice/repair record so historical records stay accurate even if rates change later.
- **Tenant-scoped tax rates (March 2026 fix)** — TaxService now reads from tenant-specific `TaxRate` entries, not the global `BillingConfig` singleton. New tenants with no `TaxRate` entries default to zero tax. This prevents cross-tenant tax leakage in multi-tenant SaaS.

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

Separate from customer billing  this is charging glass shops to use RS Systems.

**Already built:**
- SubscriptionPlan model (Trial/Starter $49/Pro $99/Enterprise $249)
- Plan limits (repairs/month, technicians, customers, storage)
- Feature flags per plan
- SubscriptionService + signup flow
- Owner billing page at `/owner/billing/`
- Tenant webhook handler

**Still needed (Drake action):**
- [x] Create Stripe Products + Prices in Stripe Dashboard  Done Feb 11
- [x] Copy `stripe_price_id` into SubscriptionPlan records  Done Feb 11
- [ ] Add `checkout.session.completed` event to Stripe webhook

**Completed (Feb 10-11, 2026):**
- [x] Wire up subscription checkout flow via Stripe Checkout Sessions
- [x] Handle subscription webhooks (checkout.session.completed, invoice.paid/failed, subscription.updated/deleted)
- [x] Dunning  handle failed subscription payments gracefully (past_due banner + email)
- [x] Usage enforcement  block actions when plan limits hit (repairs, techs, customers)
- [x] Trial expiration  prompt to upgrade (expired + expiring banners)
- [x] Billing portal link (Stripe Customer Portal for managing payment method/invoices)
- [x] **Security fix**: Plan only upgrades AFTER payment confirmed (not before checkout)

**Added March 2026:**
- [x] Subscription enforcement middleware — blocks access on expired trial/canceled/expired subscription
- [ ] Trial expiration email alerts (7d, 3d, 1d before + day-of + win-back at 7d and 30d after)
- [ ] Soft landing page for expired trials (show data stats, upgrade CTA, export option)
- **Data retention policy**: Keep all tenant data indefinitely after expiration. No automated cleanup.
- See [`docs/development/SUBSCRIPTION_LIFECYCLE.md`](docs/development/SUBSCRIPTION_LIFECYCLE.md) for full lifecycle plan
