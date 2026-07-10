# RS Systems — Roadmap

*High-level project status and what's next.*
*Last Updated: July 10, 2026 (absorbed TODO.md; core sections last revised March 25, 2026)*

---

## ✅ Completed

### v2.10 — Loyalty System + Bug Fix Sprint (March 24, 2026)
- **Loyalty Phase 1** — PointTransaction ledger, LoyaltyConfig (per-tenant configurable), LoyaltyService, points in customer nav, points history page
- **Rewards bug fixes** — 4 bugs fixed from code review (is_active filter, context, routing, unique constraint)
- **Bug fix sprint** — CODE-164 through CODE-175 (tenant isolation in rewards, race conditions, N+1 queries, admin delete_queryset gaps)
- **PR #98** — open, pending merge

### v2.9 — Mobile UX + FAB + Stripe Connect Live (March 23, 2026)
- **Stripe Connect approved and live** — charges_enabled, payouts_enabled, real payments flowing
- **Mobile UI fixes** — batch buttons responsive, 44px min tap targets, wider forms
- **Windshield damage diagram** — restored on repair, multi-break, and customer request forms
- **FAB quick action button** — on all 19 portal pages with staggered animation
- **Platform owner flag** — permanent pro plan for Rockstar, no subscription needed
- **Public payment links** — HMAC-token URLs for customer payment without login
- **Branded HTML emails** — all 11+ email types converted from plain text
- **PRs #79-96 merged and deployed**

### v2.8 — Bug Fix Sprint (March 21-22, 2026)
- CODE-113 through CODE-124 — 12 bugs fixed (shop_join IntegrityError, Decimal falsy bypass, bulk invoice mark_paid, overdue reminder format, custom email template, PDF invoice numbers, admin tax bypass, batch reward discounts, void ProtectedError, PaymentAdmin delete)
- Signup CAPTCHA fix + plan selection UX
- Plan pre-selection, Stripe checkout default, "Not sure yet" option, day 20 nudge email

### v2.7 — Tenant Isolation Sweep (March 18-20, 2026)
- CODE-077 through CODE-104 — Full OneToOneField tenant isolation sweep across technician portal, DRF API, clawdbot views, reminder/auto-invoice services, billing API
- ~70+ regression tests. PR #61 merged, deployed to production.

### v2.6 — Security Hardening (March 16-17, 2026)
- CODE-049 through CODE-061 — Race conditions, financial bugs, IDOR fixes, customer portal guards
- ~103 new regression tests. PR #60 merged.

### v2.5 — Production Hardening & Live Billing (March 15-16, 2026)
- Live Stripe keys, cache fix, login resilience, invoice payment flow
- Phone validation, multi-break fix, duplicate repair check
- 8 PRs merged, 8 deploys, zero downtime

### v2.4 — Admin Console Overhaul (March 11-12, 2026)
Custom metrics dashboard, TenantFilterMixin, subscription management, CSV exports, bulk invoicing, audit log, global admin search.

### v2.3 — Subscription Expiry UX (March 11, 2026)
Role-aware blocked page, grace period, email alerts, management command. → [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md)

### v2.0–2.2 — Foundation (Jan-Feb 2026)
Unified permissions, billing/invoicing lifecycle, SaaS subscription billing, Stripe Checkout.

---

## 🔴 High Priority (Do Now)

### Sentry Error Tracking
- **Status:** Integration wired in code, just needs `SENTRY_DSN` env var in EB
- **Action:** Create free Sentry project → set DSN → deploy
- **Impact:** Catches every 500 instantly with full traceback

### Tailwind CDN → Production Build
- **Status:** Loading from `cdn.tailwindcss.com` in production (console warning)
- **Action:** Bundle Tailwind via PostCSS or CLI, serve from static files
- **Impact:** Faster page loads, no external dependency

---

## 🟡 Next Up

### Loyalty System Phase 2-4
- Phase 2: Engagement hooks (early payment bonus, review bonus, manual adjustments, expiry cron)
- Phase 3: Tiers (Pro-only — Bronze/Silver/Gold/Platinum, point multipliers)
- Phase 4: Dashboards (customer loyalty dashboard, owner per-customer view, liability report)
- → [`proposals/loyalty-system-overhaul.md`](/docs/proposals/loyalty-system-overhaul.md)

### Review Request System
- Smart Google review requests after repair completion
- Throttled per customer type (retail/fleet/already reviewed)
- Google Business integration
- → [`proposals/review-request-system.md`](/docs/proposals/review-request-system.md)

### Website Integration Widget
- Embeddable quote form for shop websites
- Auto-creates customers and queues repairs
- Flywheel with review system
- → [`proposals/website-integration-widget.md`](/docs/proposals/website-integration-widget.md)

### Stripe Connect Phase 3 — Dashboard
- Payout history, balance, admin fee reporting
- Connect is live, dashboard is the remaining piece

---

## 🟢 Growth Features

### Customer Portal Improvements
- Fleet manager: view repairs, approve, pay, history
- Quick-approve/deny from email links
- Customer team management

### Owner Reporting & Analytics
- Monthly revenue trends, repair volume charts
- Technician performance
- Customer profitability analysis

### SMS Notifications (Twilio)
- Fleet managers don't check email — text them
- Repair approval, invoice ready, payment confirmed

### CI/CD Pipeline
- GitHub Actions: run test suite on every PR to `main`

---

## 🔵 Scale Prep

### Redis + Celery (When Needed)
- **Trigger:** > 50 concurrent users or email sending slows requests
- **Details:** `docs/SCALING.md`

### Auto-Scaling
- **Trigger:** > 100 req/sec sustained
- EB capacity → Load balanced, min=1 max=3

---

## 📋 Backlog

- Repair form efficiency improvements → [`proposals/repair-form-efficiency.md`](/docs/proposals/repair-form-efficiency.md)
- AI plan recommendation → [`proposals/ai-plan-recommendation.md`](/docs/proposals/ai-plan-recommendation.md)
- Competition pool (gamification) → [`proposals/competition-pool.md`](/docs/proposals/competition-pool.md)
- QuickBooks integration
- QR code on PDF invoices (scan-to-pay)
- Multi-location support per tenant
- PWA / offline mode for techs
- Mobile native app

---

## Absorbed from TODO.md (2026-07-10)

Items folded in from the deleted `docs/TODO.md` that weren't already tracked here or in
`docs/proposals/README.md`.

### Missing operational features (proposals needed)
- **Customer communication log** — no record of calls/texts/conversations per customer; shops track this in their heads
- **Scheduling / calendar** — repairs have a date but no calendar view, time slots, or route planning; minimum viable: daily view of who's going where
- **Estimates / quotes** — no quote workflow before a repair (quote → customer approves → converts to repair)

### Infrastructure / code health
- **Test coverage gaps** — customer portal (30+ views, ~16 tests), ConnectService payment routing lightly tested, 8 pre-existing failures in test_step5_nav / test_step3_signup / test_rewards / test_user_flow
- **Missing `db_index` on frequently filtered fields** — `queue_status` on Repair; `status` on Invoice, CustomerInvitation, ReviewRequest, RewardRedemption; `is_active` on Tenant, Technician, etc. Not urgent at current data size; address before scale
- **Admin fieldsets missing `tenant`** (low priority) — Repair, Replacement, Customer, Invoice, TaxRate, UnitRepairCount, DeliveryLog show `tenant` in list views but not fieldsets; admin UX gap only
- **Security admin models not registered** (low priority) — `LoginAttempt`, `SecurityAuditLog`, `customer_portal.ApprovalToken` have no admin registration; likely intentional

### Backlog additions
- White-label branding (custom colors/logo per shop beyond name)
- Public API for third-party integrations
- AI damage assessment from photos
- Lot-walking scheduler (route optimization for parking-lot jobs)
- Vehicle history across time by VIN
- Parts inventory (resin, blades, seals — probably overkill for most shops)

---

## Related Docs
- [`SCALING.md`](/docs/SCALING.md) — Infrastructure scaling guide
- [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md) — Trial/expiry/grace period
- [`CHANGELOG.md`](CHANGELOG.md) — Version history
- [`proposals/`](/docs/proposals/) — Feature proposals
