# Amelia's Development Log & Strategic Plan

*Last Updated: January 29, 2026*  
*Branch: `amelia`*  
*Version: 0.8.0*

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

## Architecture

```
                  ┌──────────────────────────────────────────────────────┐
                  │                   RS Systems                        │
                  │                                                      │
                  │   ┌─────────┐  ┌──────────┐  ┌──────────────────┐  │
  API Requests ──→│   │ Django  │→ │ Tenant   │→ │  Business Logic  │  │
                  │   │ Auth    │  │ Middleware│  │  (scoped by      │  │
                  │   └─────────┘  └──────────┘  │   request.tenant) │  │
                  │                               └────────┬─────────┘  │
                  │                                        │            │
                  │   ┌──────────────┬──────────────┬──────┴─────────┐  │
                  │   │ Tenants App  │ Billing App  │  Tech Portal   │  │
                  │   │ (SaaS/sub)   │ (invoices)   │  (repairs)     │  │
                  │   └──────┬───────┴──────┬───────┴──────┬─────────┘  │
                  │          │              │              │            │
                  │   ┌──────┴──────────────┴──────────────┴─────────┐  │
                  │   │              PostgreSQL (RDS)                 │  │
                  │   │      All tables have tenant FK               │  │
                  │   └──────────────────────────────────────────────┘  │
                  │          │                     │                    │
                  │   ┌──────┴──────┐       ┌──────┴──────┐            │
                  │   │   Stripe    │       │  AWS S3     │            │
                  │   │ (payments)  │       │ (photos)    │            │
                  │   └─────────────┘       └─────────────┘            │
                  └──────────────────────────────────────────────────────┘

  Signup Flow:
  ┌────────┐   POST /signup/   ┌──────────┐   Token   ┌───────────┐
  │  Shop  │ ───────────────→  │ Create:  │ ───────→  │ Dashboard │
  │ Owner  │                   │ User +   │           │ (30-day   │
  └────────┘                   │ Tenant + │           │  trial)   │
                               │ Member   │           └───────────┘
                               └──────────┘
```

---

## Execution Plan (Ordered by Impact)

### Phase 1: Expand the Data Model ✅ COMPLETE
- ✅ Fleet, retail, walk-in customer types
- ✅ Replacement service support
- ✅ Vehicle model
- ✅ Insurance integration fields

### Phase 2: Multi-Tenant Architecture ✅ COMPLETE
- ✅ Tenant model with slug/subdomain
- ✅ TenantMembership with role-based access
- ✅ TenantMiddleware (auto-resolution from header/session/membership)
- ✅ Tenant FK on all business models
- ✅ Tenant-scoped S3 paths

### Phase 3: SaaS Billing (Stripe Subscriptions) ✅ COMPLETE
- ✅ SubscriptionPlan model (Trial/Starter/Pro/Enterprise)
- ✅ Stripe subscription lifecycle (create/update/cancel/reactivate)
- ✅ Usage tracking service (repairs, techs, customers, storage)
- ✅ Plan enforcement mixin
- ✅ Stripe webhook handler
- ✅ Billing portal redirect
- ✅ seed_plans management command

### Phase 4: UX & Onboarding ✅ COMPLETE
- ✅ **Signup endpoint** — `POST /api/tenants/signup/` (creates User + Tenant + Membership + Token)
- ✅ **Trial status endpoint** — `GET /api/tenants/status/` (dashboard-friendly status)
- ✅ **Welcome email** — SendGrid integration on signup
- ✅ **Owner-only billing** — `_require_owner()` guard on all subscription endpoints
- ✅ **Rate limiting** — DRF throttling (20/min anon, 60/min user, 5/hr signup)
- ✅ **Password validation** — Django validators + custom signup validation
- ✅ **Input sanitization** — Whitespace stripping, email normalization, length checks
- ✅ **Custom SignupRateThrottle** — IP-based aggressive rate limiting
- ✅ **Tenants README** — Full documentation (architecture, API reference, security)

### Phase 5: UX Simplicity 🔵 ONGOING
- Onboarding wizard for new shops
- One-click invoice generation
- Mobile-first technician interface
- Customer self-service portal
- Smart defaults everywhere

---

## What I've Built So Far

### Tenants/SaaS System (`apps/tenants/`)
```
apps/tenants/
├── models.py              # Tenant, TenantMembership, SubscriptionPlan
├── views.py               # Signup, status, subscribe, cancel, usage, billing portal
├── urls.py                # /api/tenants/*
├── middleware.py           # TenantMiddleware (request.tenant resolution)
├── mixins.py              # PlanEnforcementMixin
├── admin.py               # Admin with tenant scoping
├── webhooks.py            # Stripe subscription webhooks
├── README.md              # Full documentation
├── services/
│   ├── subscription_service.py  # Stripe lifecycle
│   └── usage_service.py         # Usage tracking
└── management/commands/
    └── seed_plans.py            # Seed 4 standard plans
```

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
    └── stripe_service.py          # Payment Links
```

### Architecture Decisions

**Our DB = source of truth.** Stripe is a payment channel, not a second invoicing system.

**Billing lives in `apps/billing/`.** Clawdbot is a thin API layer. Business logic belongs in domain apps.

**Multi-tenant isolation.** Every query is scoped by `request.tenant`. No data leaks between shops.

**Owner-only billing.** Only shop owners can manage subscriptions. Enforced by `_require_owner()` on all billing endpoints.

**URL structure:** `/api/tenants/*` for SaaS management. `/api/billing/*` for invoicing. `/clawdbot/*` for legacy.

---

## Security Features

| Feature | Implementation |
|---------|---------------|
| Rate limiting | DRF throttling: 20/min anon, 60/min user, 5/hr signup |
| Password validation | Django validators (length, common, numeric, similarity) |
| Owner-only billing | `_require_owner()` checks TenantMembership role |
| Tenant isolation | Middleware + FK scoping on all queries |
| Input sanitization | Strip whitespace, lowercase email, validate lengths |
| CSRF protection | Django middleware enabled |
| Token auth | DRF TokenAuthentication for API access |
| Stripe webhooks | Signature verification |

---

## Code Stats

| Metric | Count |
|--------|-------|
| Django apps | 7 (tenants, billing, tech portal, customer portal, rewards, security, clawdbot) |
| API endpoints (tenants) | 10 |
| API endpoints (billing) | 15+ |
| Services | 10+ |
| Management commands | 3+ |
| Subscription plans | 4 |

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
| Jan 29 | *pending* | Signup flow, security hardening, UX polish (Phase 4) |

---

*— Amelia 🦾*
