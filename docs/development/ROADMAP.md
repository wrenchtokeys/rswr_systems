# RS Systems — Roadmap

*High-level project status and what's next.*
*Last Updated: September 7, 2026 (C1 landing credibility merged, PR #250, awaiting deploy; P8 deployed and the media bucket closed).*

> **Merged, not deployed (keep this line current — a deploy note without an expiry is a
> snapshot):** production runs `969a4035`, deployed **2026-09-06 22:00 UTC** — everything
> merged through #248 (P8) is live, and the media bucket's `repair_photos/*` prefix went
> private at 22:04 UTC the same day. **#250 (C1: landing screenshots + founder note) merged
> 2026-09-07 00:16 UTC as `059fa77a` and is NOT on prod** — the next deploy carries it; docs
> PRs after #248 carry no runtime code. `eb deploy` ships the current branch's HEAD — `git checkout main &&
> git pull` first (or a `deploy-main` branch at `origin/main` when `main` is held by another
> worktree).

> **Scope note.** This file is the long-horizon view. The direction — Path A with a
> B-ready spine — is in `docs/strategy/PRODUCT_DIRECTION.md` (September 2026; awaiting
> Drake's sign-off). The near-term work queues live in `docs/strategy/` and are the ones to
> read before starting a session: `IMPROVEMENT_SESSIONS.md` (now carries a Status line per
> session; B3/B5/B6 are the spine), `FIELD_OPS_SESSIONS.md` (S11–S14 scheduling UX open),
> `PHOTO_ML_SESSIONS.md` (P8 is its last code), `UI_MAGIC_SESSIONS.md` (arc clear; sweeps
> parked), `JOB_QUEUE_SESSIONS.md` (Q5/Q6 parked), `TEST_SUITE_SESSIONS.md`.
> For dated detail on anything below, `CHANGELOG.md` is canonical.

---

## ✅ Completed

### Aug–Sep 2026 — see `CHANGELOG.md` for the full record
Condensed, because these closed out items this file used to list as pending:
- **Technician assignment notifications** (FIELD_OPS N1 #179, N3 #204) — an assigned tech is told, and six lifecycle emails that had never sent now send. Texts (N2) still wait on the toll-free number (v4 submitted 2026-08-31).
- **Scheduling & dispatch, first cut** (FIELD_OPS S1–S5, S7–S10; PRs #188–#214) — `scheduled_for`, day view, dispatch board, working hours, swap, quick-add from the schedule, customer requests carrying when + where.
- **Job queue** (#220/#221) — "Manual" assignment finally means unassigned; the Unassigned queue + manager alerts.
- **UI "magic" S11–S18a** (#209/#210/#223/#229/#233/#235/#240) — skeletons + optimistic rows, auth pages, the `{% icon %}` tag and a Font-Awesome-free chrome, Tailwind source out of `static/`, landing reveal bug, report-only CSP.
- **Photo ML P1–P7** (#211–#243) — tap-to-crop, suggester, backfill queue, break-framed photos on the invoice and portal, before/after exhibit, customer photo download.
- **Email chassis** (#200/#202/#206/#208) — one chassis for every audience, replacement lifecycle emails, receipts, bell + history.
- **Mygrant quotes** (#184/#186/#194) — per-shop encrypted credentials + live glass pricing, dark until the Mygrant IT callback.
- **Test suite** (#244) — 80 min → 16 with `tblib`; committed baseline at `docs/strategy/test_baseline_main.txt`.
- **Billing & subscription hardening** (PRs #166/#171/#172/#173) — EB cron had never executed (four silent bugs), Stripe Basil payload shapes, webhook idempotency + reconcile sweeps, `past_due` read-only at 14 days, platform fee resolution, real plan limits.
- **Payment reliability** (PRs #148/#149) — webhook 500 hotfix, manual-payment guard, reconcile cron, verified payment-complete landing.
- **UI "magic" overhaul S1–S10** (PRs #160/#162/#163/#164/#167/#168/#169) — self-hosted assets, design tokens, brand palette, dashboard/jobs/job-form redesigns, motion, view transitions.
- **SMS** (PRs #156/#158/#159) — AWS End User Messaging transport, invoice texts, review-request texts. TFN registration pending (see `docs/strategy/FIELD_OPS_SESSIONS.md` Appendix A).
- **Launch readiness Phases 1–3** (PRs #143/#144/#146) — funnel/plans, first-run experience, support contact form.
- **Loyalty** (PRs #139/#140/#142) — customer-anchored balances, owner reward management, opt-in auto-apply.
- **Soft delete + 30-day restore** (PR #130), **tax overhaul + fleet/individual** (PRs #127/#128), **tenant branding** (PRs #116/#165).

### v2.10 — Loyalty System + Bug Fix Sprint (March 24, 2026)
- **Loyalty Phase 1** — PointTransaction ledger, LoyaltyConfig (per-tenant configurable), LoyaltyService, points in customer nav, points history page
- **Rewards bug fixes** — 4 bugs fixed from code review (is_active filter, context, routing, unique constraint)
- **Bug fix sprint** — CODE-164 through CODE-175 (tenant isolation in rewards, race conditions, N+1 queries, admin delete_queryset gaps)
- **PR #98** — merged

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

### The Glass Guy cannot take a payment — owner task, not a session
- **Status:** `main` deployed 2026-09-06. Connect checked the same day, read-only, on prod and against Stripe live: Express account created 2026-08-06, **onboarding never completed** (`details_submitted=False`, every requirement still due — address, tax ID, representative, bank account, ToS). 0 invoices on the tenant.
- **Action:** Drake's dad resumes onboarding from Settings → Payments. No code moves this; the queue below does not wait on it.

### ~~P8 — close the world-readable media bucket~~ — DONE 2026-09-06
- **Status:** #248 deployed 22:00 UTC; bucket policy narrowed 22:04 UTC. Anonymous damage photo → 403, shop logo → 200, every app route still serves. The photo-ML arc has no code left.
- **Found on the way (own session, not urgent):** the web process's `SECRET_KEY` differs from the EB-configured value (50 vs 53 chars) — HMAC tokens minted through `run-cron.sh` do not validate on the site. Details in `PHOTO_ML_SESSIONS.md` §P8 Notes.

### Landing page credibility + a front door
- **Status:** the "500+ Jobs Tracked" trust bar reads as "nobody uses this"; the product shot is an HTML mock; nothing on the site captures a lead.
- **Action:** `IMPROVEMENT_SESSIONS.md` C1 (own PR, no decision needed), then the website lead widget (`proposals/website-integration-widget.md`, the one March draft kept as the acquisition item).

### Pre-existing test-suite failures
- **Status:** ~93 red on a clean `main`, baseline committed at `docs/strategy/test_baseline_main.txt`; `scripts/test_guards.sh --full` (PR #245) diffs against it and fails only on regressions.
- **Action:** the honesty half of `docs/strategy/TEST_SUITE_SESSIONS.md`.

### Customer portal test coverage
- **Status:** 30+ views, thin coverage. Anything building on those views is building on sand — and B3 (quotes) will.

*(Resolved: Sentry — `SENTRY_DSN` set and verified in prod 2026-08-09. Tailwind CDN — removed in
PR #160; there are now zero third-party asset hosts and CLAUDE.md forbids reintroducing them.
Technician assignment notifications — N1 #179 and N3 #204, deployed 2026-08-24.)*

---

## 🟡 Next Up

### The spine — quotes, claim tracking, price book
- The three things a medium shop asks for in its first demo that need no NAGS licence and no EDI. One session each, after the fork in `PRODUCT_DIRECTION.md` carries Drake's name.
- **Quote → job** (B3), **Tier 1 insurance claim tracking with short-payment reconciliation** (B5), **shop-owned price book seeded from history** (B6) — all in [`../strategy/IMPROVEMENT_SESSIONS.md`](/docs/strategy/IMPROVEMENT_SESSIONS.md)

### Scheduling UX (second cut)
- *Shipped:* booked time, day view, dispatch board, working hours, swap, quick-add (S1–S10).
- *Remaining:* the move primitive + inline time edit, the ordered day list with drag-to-move, schedule on the dashboard, multi-tech moves.
- → Sessions S11–S14 in [`../strategy/FIELD_OPS_SESSIONS.md`](/docs/strategy/FIELD_OPS_SESSIONS.md)

### Loyalty System Phase 3-4
- Phase 3: Tiers (Pro-only — Bronze/Silver/Gold/Platinum, point multipliers)
- Phase 4: Dashboards (customer loyalty dashboard, owner per-customer view)
- *Phases 1–2 shipped* (ledger, LoyaltyConfig, reconcile + expire commands, liability report, manual adjustment), plus the Aug 2026 customer-anchored rework.
- → [`proposals/loyalty-system-overhaul.md`](/docs/proposals/loyalty-system-overhaul.md), [`proposals/loyalty-program-improvements.md`](/docs/proposals/loyalty-program-improvements.md)

### Review Request System — Google Reviews API
- *Shipped:* `ReviewRequestService`/`ReviewConfig`/`ReviewRequest`, per-tenant settings, fleet gating, and the `send_review_requests` cron (`12_reviews_cron.config`, every 20 min).
- *Remaining:* actual Google Business Profile API integration (currently a link-out).
- → [`proposals/review-request-system.md`](/docs/proposals/review-request-system.md)

### Website Integration Widget
- Embeddable quote form for shop websites
- Auto-creates customers and queues repairs
- Flywheel with review system
- → [`proposals/website-integration-widget.md`](/docs/proposals/website-integration-widget.md)

### Stripe Connect Phase 3 — Dashboard
- *Shipped:* platform fee reporting at `/admin/platform-fees/`.
- *Remaining:* per-shop payout history and balance.

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

### SMS — remaining coverage
- *Shipped* on AWS End User Messaging (not Twilio): invoice texts and review-request texts.
- *Remaining:* repair approval and payment-confirmed texts; tech assignment texts (session N2).
- Blocked in prod until the toll-free number clears registration — see `FIELD_OPS_SESSIONS.md` Appendix A.

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
- **Scheduling / calendar** — *shipped* as FIELD_OPS S1–S10 (booked time, day view, dispatch board); route planning stays backlog (S6)
- **Estimates / quotes** — no quote workflow before a repair (quote → customer approves → converts to repair). **Now spine feature 1** → `IMPROVEMENT_SESSIONS.md` B3

### Infrastructure / code health
- **Test coverage gaps** — customer portal (30+ views, ~16 tests), ConnectService payment routing lightly tested. **~93** pre-existing failures on `main`, baseline committed (`docs/strategy/test_baseline_main.txt`): always compare against it, never count absolutes
- **Missing `db_index` on frequently filtered fields** — `queue_status` on Repair; `status` on Invoice, CustomerInvitation, ReviewRequest, RewardRedemption; `is_active` on Tenant, Technician, etc. Not urgent at current data size; address before scale
- **Admin fieldsets missing `tenant`** (low priority) — Repair, Replacement, Customer, Invoice, TaxRate, UnitRepairCount, DeliveryLog show `tenant` in list views but not fieldsets; admin UX gap only
- **Security admin models not registered** (low priority) — `LoginAttempt`, `SecurityAuditLog`, `customer_portal.ApprovalToken` have no admin registration; likely intentional

### Backlog additions
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
