# Amelia's Development Log & Roadmap

*Last Updated: January 28, 2026*  
*Branch: `amelia`*  
*Version: 0.6.0*

---

## What I've Built

### Billing System (`apps/billing/`)
A complete billing engine for RS Systems. This is the biggest feature I've built.

**Architecture:**
```
apps/billing/
├── models.py              # Invoice, InvoiceLineItem, Payment
├── views.py               # REST API endpoints
├── urls.py                # /api/billing/* routes
├── admin.py               # Django admin with status badges
├── signals.py             # Auto-invoice on repair completion
├── management/
│   └── commands/
│       └── process_billing.py  # Cron automation
└── services/
    ├── invoice_service.py         # PDF generation
    ├── invoice_email_service.py   # Email with attachments
    ├── invoice_tracking_service.py # Tracking + double-billing prevention
    ├── auto_invoice_service.py    # Auto-generate on repair completion
    ├── dashboard_service.py       # Business metrics
    ├── report_service.py          # Daily/weekly reports
    ├── reminder_service.py        # Payment reminders
    └── stripe_service.py          # Stripe payment processing
```

**Key design decisions:**
- **Our DB is source of truth** for invoices. Stripe is an optional payment channel.
- **Double-billing prevention** via InvoiceLineItem → Repair FK. Can't invoice a repair twice.
- **Customer preferences** drive automation (per_ticket vs batch vs manual).
- **Non-blocking signals** — invoice generation failure never breaks a repair save.

### URL Architecture
```
/api/billing/*         ← Canonical billing API (production path)
/clawdbot/billing/*    ← Proxy (backward compat, will be removed)
/clawdbot/*            ← Amelia-specific (status, health, PDF gen)
```

### Stripe Integration
- Test mode connected (acct_1SuOaJ1JK8PzBpGP)
- Customer sync with persisted stripe_customer_id
- Payment links for customer self-service
- Webhook handlers ready

---

## Architecture Decisions

### Invoice + Stripe: How It Works

**Problem:** Do we create two invoices (one ours, one Stripe)?

**Answer: No.** Our system is the source of truth. Stripe is just a payment channel.

```
                    ┌──────────────┐
                    │  Our Invoice │  ← Source of truth
                    │  (Database)  │  ← Tracks ALL payments
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────┴────┐  ┌───┴───┐  ┌────┴────┐
         │  Check  │  │ Cash  │  │ Stripe  │
         │ Payment │  │Payment│  │ Payment │
         └─────────┘  └───────┘  └─────────┘
                                      │
                              Payment Link or
                              Checkout Session
                              (NOT a Stripe Invoice)
```

**Why NOT Stripe Invoices:**
- Drake's customers pay by check, cash, wire — not just Stripe
- Stripe Invoices create a separate billing record we'd have to sync
- Payment Links are simpler — just a pay button, no duplicate data

**Current issue:** The code currently creates Stripe Invoices (duplicate). 
**Fix needed:** Switch to Payment Links only. Remove create_stripe_invoice.

### URL Migration Plan
1. ✅ Built billing views in `apps/billing/views.py`
2. ✅ Registered at `/api/billing/`
3. ✅ Proxy from `/clawdbot/billing/` for backward compat
4. 🔜 When merging to main, remove `/clawdbot/billing/` proxy
5. 🔜 `/clawdbot/` becomes Amelia-only features (AI tools, experiments)

---

## Roadmap (Prioritized)

### 🔴 P0 — Fix Now
- [ ] **Remove Stripe Invoice creation** — use Payment Links only
- [ ] **Fix auto-invoice S3 storage** — configure AWS in test env properly
- [ ] **Add CSRF exemption properly** — current `@csrf_exempt` is a placeholder

### 🟡 P1 — This Week
- [ ] **Batch invoice UI** — admin action to invoice all pending for a customer
- [ ] **Webhook testing** — set up Stripe CLI forwarding, test payment flow end-to-end
- [ ] **Email templates** — HTML templates for invoice emails and reminders
- [ ] **Management command cron** — schedule `process_billing` daily

### 🟢 P2 — Next 2 Weeks
- [ ] **Customer self-serve portal** — view invoices, pay online, download PDFs
- [ ] **Recurring invoices** — for lot walking customers on regular schedules
- [ ] **Invoice PDF improvements** — better layout, customer branding options
- [ ] **Aging report** — AR aging (30/60/90 day buckets)

### 🔵 P3 — Month+
- [ ] **QuickBooks export** — CSV/IIF export for accounting
- [ ] **SMS reminders** — text overdue alerts via Twilio/SNS
- [ ] **Multi-tenant billing** — per-tenant Stripe accounts
- [ ] **Revenue forecasting** — ML-based prediction from repair trends
- [ ] **Customer credit limits** — auto-hold for overdue customers

---

## Code Stats

| Metric | Count |
|--------|-------|
| Files in billing/ | 17 |
| Lines of code (billing/) | ~3,800 |
| API endpoints | 15+ |
| Django models | 3 (Invoice, LineItem, Payment) |
| Services | 8 |
| Management commands | 1 |
| Migrations | 2 |

## Commits (amelia branch)

| Date | Hash | Description |
|------|------|-------------|
| Jan 27 | `41c382a8` | Royal blue styling + logo in invoices |
| Jan 27 | `bb69e5fa` | Bigger logo + full notes in descriptions |
| Jan 27 | `fd81dbeb` | Invoice email service with photo attachments |
| Jan 27 | `1f087dd4` | Invoice storage service (S3 ready) |
| Jan 27 | `70ccd7ec` | Customer invoice preferences + auto-invoicing |
| Jan 27 | `1d1a100f` | Architecture refactor: billing app extracted |
| Jan 27 | `5e55f951` | Remove duplicate services from clawdbot |
| Jan 28 | `7efcb0b7` | Invoice tracking + double-billing prevention |
| Jan 28 | `81168a2b` | Dashboard, reports, Stripe, reminders |
| Jan 28 | `9e3d6e1f` | Billing documentation |
| Jan 28 | `f045bd0c` | Stripe integration configured + tested |
| Jan 28 | `29705ff0` | URL migration + management commands |

---

*— Amelia 🦾*
