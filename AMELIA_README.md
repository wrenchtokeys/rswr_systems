# RS Systems — Development Log & Architecture

*Last Updated: January 29, 2026*  
*Branch: `amelia`*  
*Version: 0.9.0*

---

## The Product

RS Systems is a **multi-tenant SaaS platform for auto glass shops**. A shop owner signs up, gets a free trial, and can manage their entire business: repairs, replacements, customers, technicians, invoicing, and billing.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    RS Systems SaaS                          │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│  Signup  │  Owner   │ Technician│ Customer │   API Layer   │
│  & Onboard│ Dashboard│  Portal  │  Portal  │  (DRF + JSON) │
├──────────┴──────────┴──────────┴──────────┴────────────────┤
│              TenantMiddleware (request.tenant)              │
├────────────────────────────────────────────────────────────┤
│  tenants │  billing │ tech_portal │ customer │  rewards    │
│  (Tenant │ (Invoice │  (Repair,  │ (Portal, │ (Points,    │
│  Members │  Payment │ Replacement│  Approve,│  Referrals) │
│  Plans)  │  Stripe) │ Technician)│  Request)│             │
├────────────────────────────────────────────────────────────┤
│              core (Customer, Vehicle, Notifications)       │
├────────────────────────────────────────────────────────────┤
│                PostgreSQL + S3 (tenant-scoped)             │
└────────────────────────────────────────────────────────────┘
```

### User Types & Portals

| User Type | Portal | URL | Description |
|-----------|--------|-----|-------------|
| Shop Owner | Owner Dashboard | `/owner/` | Billing, usage, settings, team |
| Technician | Tech Portal | `/tech/` | Repairs, replacements, customers |
| Customer | Customer Portal | `/app/` | View repairs, approve, request |
| New User | Signup | `/signup/` | Registration + 30-day trial |

### Service Types

| Service | Model | Pricing | Fields |
|---------|-------|---------|--------|
| Repair | `Repair` (extends `GlassService`) | Progressive ($50→$40→$35→$30→$25 per unit) | damage_type, resin_viscosity, batch support |
| Replacement | `Replacement` (extends `GlassService`) | Parts + Labor + ADAS calibration | glass_position, NAGS #, OEM/aftermarket |

### Customer Types

| Type | Example | Behavior |
|------|---------|----------|
| Fleet | EOS Trucking (50 trucks) | Unit numbers, progressive pricing |
| Retail | John's F-150 | Vehicle (year/make/model/VIN) |
| Walk-in | One-time customer | Minimal info |

---

## App Structure

```
apps/
├── tenants/              # Multi-tenant + SaaS billing
│   ├── models.py         # Tenant, TenantMembership, SubscriptionPlan
│   ├── middleware.py      # TenantMiddleware (request.tenant)
│   ├── mixins.py          # TenantQuerysetMixin, PlanEnforcementMixin
│   ├── managers.py        # TenantManager (.for_tenant())
│   ├── views.py           # Subscription API (DRF)
│   ├── webhooks.py        # Stripe webhook handler
│   ├── owner_views.py     # Owner dashboard (if separate)
│   └── services/
│       ├── signup_service.py       # Shared signup logic
│       ├── subscription_service.py # Stripe lifecycle
│       └── usage_service.py        # Plan limit tracking
│
├── saas/                 # SaaS UI pages
│   ├── views.py          # Signup, onboarding, dashboard, billing, replacement
│   ├── forms.py          # SignupForm, onboarding forms, ReplacementForm
│   └── urls.py           # /signup/, /pricing/, /owner/*, /tech/replacement/*
│
├── billing/              # Invoice + payment system
│   ├── models.py         # Invoice, InvoiceLineItem, Payment
│   ├── views.py          # REST API (auth + tenant-scoped)
│   ├── signals.py        # Auto-invoice on repair/replacement completion
│   └── services/         # PDF gen, email, tracking, Stripe, reminders, reports
│
├── technician_portal/    # Technician-facing features
│   ├── models.py         # GlassService (abstract), Repair, Replacement, Technician
│   ├── views/            # Split into: dashboard, repairs, customers, batch, etc.
│   ├── api/              # DRF serializers, views, URLs
│   ├── forms.py          # RepairForm
│   └── services/         # Pricing, batch pricing
│
├── customer_portal/      # Customer-facing features
│   ├── models.py         # CustomerUser, RepairApproval, Preferences
│   ├── views.py          # Dashboard, repair history, approval workflow
│   └── forms.py          # Customer forms
│
├── rewards_referrals/    # Loyalty & referral program
├── clawdbot/             # Amelia's API namespace
└── security/             # Login attempts, audit, rate limiting
```

---

## Subscription Plans

| Plan | Monthly | Annual | Repairs/mo | Techs | Customers | Storage |
|------|---------|--------|------------|-------|-----------|---------|
| Trial | Free | — | 50 | 2 | 10 | 500 MB |
| Starter | $49 | $470 | 200 | 5 | 50 | 500 MB |
| Pro | $99 | $950 | Unlimited | 15 | Unlimited | 500 MB |
| Enterprise | $249 | $2,390 | Unlimited | Unlimited | Unlimited | 500 MB |

---

## Security Model

| Layer | Implementation |
|-------|---------------|
| Authentication | `@login_required` on all data endpoints |
| Tenant Isolation | Every query filtered by `request.tenant` |
| CSRF | Enabled on all endpoints (exempt only Stripe webhooks) |
| Rate Limiting | 20/min anon, 60/min user, 5/hr signup |
| Owner-only Billing | `_require_owner()` on subscription endpoints |
| Stripe Webhooks | Signature verification via `STRIPE_WEBHOOK_SECRET` |
| Password Policy | Django validators (min length, similarity, common passwords) |
| Login Attempts | Rate-limited (10/hr), logged via security app |

---

## User Flow

### New Shop Owner
```
/signup/ → /onboarding/ (4 steps) → /owner/ (dashboard)
    │           │
    │           ├─ Step 1: Business info
    │           ├─ Step 2: Add technician
    │           ├─ Step 3: Add customer
    │           └─ Step 4: Done!
    │
    └─ Creates: User + Tenant (trial) + TenantMembership (owner)
```

### Returning User (Login)
```
/login/ → login_router checks role:
    ├─ Owner/Manager → /owner/
    ├─ Customer → /app/
    └─ Technician → /tech/
```

### Subscription Lifecycle
```
Trial (30 days) → Subscribe (Stripe) → Active → Cancel → Expired
                                         ↑                  │
                                         └── Reactivate ────┘
```

---

## API Endpoints

### Tenant/Subscription (`/api/tenants/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/plans/` | Public | List subscription plans |
| POST | `/signup/` | Public | Register new shop |
| GET | `/status/` | Auth | Tenant status + usage |
| POST | `/subscribe/` | Owner | Start Stripe subscription |
| POST | `/subscription/update/` | Owner | Change plan |
| POST | `/subscription/cancel/` | Owner | Cancel at period end |
| POST | `/subscription/reactivate/` | Owner | Un-cancel |
| GET | `/usage/` | Auth | Usage vs plan limits |
| GET | `/billing-portal/` | Owner | Stripe portal redirect |
| POST | `/webhooks/stripe/` | Stripe | Webhook handler |

### Billing (`/api/billing/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/dashboard/` | Auth+Tenant | Billing metrics |
| GET | `/invoices/` | Auth+Tenant | List invoices |
| POST | `/invoices/create/<id>/` | Auth+Tenant | Create invoice |
| POST | `/invoices/<id>/payment/` | Auth+Tenant | Record payment |
| POST | `/invoices/<id>/cancel/` | Auth+Tenant | Cancel invoice |

### UI Pages
| URL | Access | Description |
|-----|--------|-------------|
| `/signup/` | Public | Registration |
| `/pricing/` | Public | Plan comparison |
| `/onboarding/` | Auth | Setup wizard |
| `/owner/` | Auth (owner) | Dashboard |
| `/owner/billing/` | Auth (owner) | Billing settings |
| `/owner/settings/` | Auth (owner) | Business info + team |
| `/tech/` | Auth (tech) | Technician dashboard |
| `/tech/replacement/new/` | Auth (tech) | New replacement form |
| `/app/` | Auth (customer) | Customer dashboard |

---

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
| Jan 28 | `d576f4b1` | Expand data model (retail, replacements, vehicles) |
| Jan 28 | `bdbf89bb` | **Split Repair/Replacement into separate models** |
| Jan 28 | `301a329e` | Phase 1c codebase cleanup |
| Jan 28 | `a47ebd39` | **Phase 2: Multi-tenant architecture** |
| Jan 28 | `fedbf71e` | **Phase 3: SaaS billing + Stripe subscriptions** |
| Jan 28 | `5268a3a9` | Phase 4: Signup, security, UX polish |
| Jan 28 | `851ef52d` | Complete SaaS UI (signup, onboarding, dashboard) |
| Jan 28 | `56777536` | Enhanced owner settings + invite modal |
| Jan 29 | `1f7bd7f2` | **Security: Auth + tenant scoping on ALL APIs** |
| Jan 29 | TBD | Audit fixes: field rename compat, login routing, docs |

---

## Development Phases — ALL COMPLETE

### ✅ Phase 1: Data Model Expansion
- 1a: Retail/walk-in customer types
- 1b: Replacement services (separate model)
- 1c: Code cleanup (views split, N+1 fixed, deprecated code removed)

### ✅ Phase 2: Multi-Tenant Architecture
- Tenant model with owner, business info, Stripe IDs
- TenantMembership (owner/manager/technician/viewer roles)
- Tenant FK on all business models
- TenantMiddleware + TenantManager
- Data migration for existing records

### ✅ Phase 3: SaaS Billing
- SubscriptionPlan model (4 tiers)
- Stripe subscription lifecycle (create/update/cancel/reactivate)
- Usage tracking and plan enforcement
- Webhook handler with signature verification
- Billing portal integration

### ✅ Phase 4: UX & Security
- Full signup flow (UI + API)
- 4-step onboarding wizard
- Owner dashboard with usage meters
- Billing settings with plan comparison
- Pricing page
- Replacement form (separate from repair)
- Auth + tenant scoping on ALL endpoints
- Rate limiting, CSRF enforcement
- Login routing by role

---

*— Amelia 🦾*
