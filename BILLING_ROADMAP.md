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
- **No sales tax calculation** — invoices have no tax (Phase 8)
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

### 5.3 Technician Portal — Payment Badge
- [ ] On repair detail: show invoice status badge if invoiced
- [ ] On repair list: optional column showing if repair has been invoiced/paid

### 5.4 Reminder System
- [ ] Owner can click "Send Reminder" on any overdue invoice
- [ ] Auto-reminders: configurable schedule (7 days, 14 days, 30 days overdue)
- [ ] Reminder count tracked per invoice

**Note**: 5.3 and 5.4 deferred to Phase 6 (polish)

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

## Phase 8: Sales Tax by Zip Code

**Goal**: Automatically calculate and apply correct sales tax per invoice based on service location.

### Why it's complex
- Arkansas state rate: 6.5%
- Cities/counties add local taxes on top (combined can reach 11.625%)
- Rate varies by zip code — some zips span multiple jurisdictions
- Rates change periodically

### Key constraint: tax must be on the invoice, not at checkout
If tax is only added at Stripe checkout, customers paying by check/cash would skip tax.
Tax MUST be calculated at invoice creation time and shown on the PDF.
Stripe checkout charges the tax-inclusive total — no additional tax added at payment.

### Options (pick one for rate lookup)
1. **Stripe Tax Calculations API** — Use Stripe's tax calculation endpoint at invoice creation to get the rate, store it on our invoice. Checkout charges the pre-calculated total. ~$0.50/txn.
2. **Tax API** (TaxJar, Avalara, etc.) — Dedicated tax calculation at invoice creation. Monthly fee.
3. **Local tax table** — Maintain a zip→rate lookup table ourselves. Free but we own the maintenance. Arkansas Dept of Finance publishes rate files.

### Tasks (regardless of approach)
- [ ] Add `tax_rate`, `tax_amount` fields to Invoice model
- [ ] Add `tax_enabled` toggle to BillingConfig (global on/off — **default: off**)
- [ ] Add `tax_exempt` flag on Customer model (per-customer override)
- [ ] Calculate tax at invoice creation time (not at checkout)
- [ ] Invoice PDF shows: subtotal + tax + total (or just subtotal = total if no tax)
- [ ] Email templates show tax breakdown (hide tax line when zero)
- [ ] Stripe checkout charges the tax-inclusive `total` (no additional tax)
- [ ] Check/cash payments are for the same tax-inclusive total
- [ ] Determine service location per repair (customer address? job site zip?)
- [ ] Tax reporting: monthly/quarterly totals for filing

### No-tax mode
- BillingConfig.tax_enabled = False → invoices skip tax entirely (subtotal = total)
- Customer.tax_exempt = True → that customer always gets $0 tax regardless of global setting
- This lets Drake run without tax initially and flip it on when ready
- Tax-exempt useful for government accounts, resellers, or fleets with exemption certs

**Estimated effort**: ~8-12 hours depending on approach
**Priority**: P1 — legal compliance (but can launch with tax_enabled=False initially)

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

**Still needed:**
- [ ] Create Stripe Products + Prices in Stripe Dashboard
- [ ] Copy `stripe_price_id` / `stripe_annual_price_id` into SubscriptionPlan records
- [ ] Wire up subscription checkout flow (owner upgrades/downgrades plan)
- [ ] Handle subscription webhooks (invoice.paid, customer.subscription.updated/deleted)
- [ ] Dunning — handle failed subscription payments gracefully
- [ ] Usage enforcement — block actions when plan limits hit (repairs, techs, storage)
- [ ] Trial expiration → prompt to upgrade
- [ ] Billing portal link (Stripe Customer Portal for managing payment method/invoices)
