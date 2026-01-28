# Amelia's Development Log & Strategic Plan

*Last Updated: January 28, 2026*  
*Branch: `amelia`*  
*Version: 0.7.0*

---

## The Product Vision

RS Systems serves auto glass shops. The software needs to be:
- **Dead simple** — shop owners don't have time for complex software
- **Extremely powerful** — handles fleet accounts, retail walk-ins, repairs AND replacements
- **Multi-tenant** — every glass shop gets their own account
- **Self-sustaining** — shops pay via Stripe subscription

### Customer Types We Must Support

| Type | Example | Current Support | Priority |
|------|---------|----------------|----------|
| Fleet accounts | EOS Trucking (50 trucks) | ✅ Built | — |
| Retail / Individual | John's F-150 | ❌ Not built | 🔴 HIGH |
| One-time walk-ins | Random person | ❌ Not built | 🔴 HIGH |

### Service Types We Must Support

| Service | Example | Current Support | Priority |
|---------|---------|----------------|----------|
| Windshield repair | Chip/crack fill | ✅ Built | — |
| Windshield replacement | Full glass swap | ❌ Not built | 🔴 HIGH |
| Side/back glass | Door window replacement | ❌ Not built | 🟡 MEDIUM |
| ADAS calibration | Post-replacement sensor cal | ❌ Not built | 🟡 MEDIUM |

---

## Execution Plan (Ordered by Impact)

### Phase 1: Expand the Data Model 🔴 NOW
**Why first:** Everything builds on top of the right data model. If we add multi-tenant later, it wraps around these models. Get them right now.

**1a. Support retail/individual customers**
- Add `customer_type` field: FLEET, RETAIL, WALK_IN
- Fleet = existing behavior (account with multiple units)
- Retail = individual person with one vehicle (name, phone, vehicle info)
- Walk-in = one-time job, minimal info needed
- Vehicle model: year, make, model, VIN (optional)

**1b. Support replacement services**
- Add `service_type` field: REPAIR, REPLACEMENT
- Replacement has different fields: glass type, OEM vs aftermarket, NAGS number
- Different pricing model (flat rate + parts, not progressive per-unit)
- Different workflow (may need parts ordering, scheduling)
- Insurance integration fields (claim number, deductible, authorization)

**1c. Clean up existing code**
- Split massive view files into services
- Remove deprecated pricing method
- Fix N+1 queries

### Phase 2: Multi-Tenant Architecture 🟡 NEXT
**Why second:** Can't serve other shops without isolation.

- Tenant model (shop name, subdomain, settings)
- Tenant FK on Customer, Repair, Invoice
- Middleware that auto-filters by tenant
- Tenant-scoped admin
- Separate S3 paths per tenant

### Phase 3: SaaS Billing (Stripe Subscriptions) 🟢 THEN
**Why third:** Need multi-tenant before we can bill tenants.

- Subscription plans: Free trial → Starter → Pro → Enterprise
- Stripe Subscription API integration
- Usage tracking (repairs/month, storage, etc.)
- Billing portal for shop owners
- Plan limits enforcement

### Phase 4: UX Simplicity 🔵 ONGOING
**Why ongoing:** This isn't a phase — it's a principle. Every feature must be dead simple.

- Onboarding wizard for new shops
- One-click invoice generation
- Mobile-first technician interface
- Customer self-service portal
- Smart defaults everywhere (don't make users configure what they don't need to)

---

## What I've Built So Far

### Billing System (`apps/billing/`)
```
apps/billing/
├── models.py              # Invoice, InvoiceLineItem, Payment
├── views.py               # REST API (15+ endpoints)
├── urls.py                # /api/billing/*
├── admin.py               # Admin with status badges
├── signals.py             # Auto-invoice on repair completion
├── management/commands/
│   └── process_billing.py # Cron automation
└── services/
    ├── invoice_service.py         # PDF generation
    ├── invoice_email_service.py   # Email with attachments
    ├── invoice_tracking_service.py # Tracking + double-billing prevention
    ├── auto_invoice_service.py    # Auto-generate on completion
    ├── dashboard_service.py       # Business metrics
    ├── report_service.py          # Daily/weekly reports
    ├── reminder_service.py        # Payment reminders
    └── stripe_service.py          # Payment Links (not duplicate invoices)
```

### Architecture Decisions

**Our DB = source of truth.** Stripe is a payment channel, not a second invoicing system.

**Billing lives in `apps/billing/`.** Clawdbot is a thin API layer. Business logic belongs in domain apps.

**URL structure:** `/api/billing/*` is canonical. `/clawdbot/billing/*` proxies for backward compat.

---

## Code Stats

| Metric | Count |
|--------|-------|
| Files in billing/ | 17 |
| Lines of code | ~3,800 |
| API endpoints | 15+ |
| Services | 8 |
| Management commands | 1 |

## Commit History (amelia branch)

| Date | Hash | Description |
|------|------|-------------|
| Jan 27 | `41c382a8` | Royal blue styling + logo in invoices |
| Jan 27 | `bb69e5fa` | Bigger logo + full notes |
| Jan 27 | `fd81dbeb` | Invoice email service |
| Jan 27 | `1f087dd4` | Invoice storage service |
| Jan 27 | `70ccd7ec` | Customer invoice preferences |
| Jan 27 | `1d1a100f` | Architecture refactor: billing app |
| Jan 27 | `5e55f951` | Cleanup duplicate services |
| Jan 28 | `7efcb0b7` | Invoice tracking + payments |
| Jan 28 | `81168a2b` | Dashboard, reports, Stripe, reminders |
| Jan 28 | `9e3d6e1f` | Billing documentation |
| Jan 28 | `f045bd0c` | Stripe integration configured |
| Jan 28 | `29705ff0` | URL migration + management commands |
| Jan 28 | `b96eb815` | Fix Stripe architecture |

---

*— Amelia 🦾*
