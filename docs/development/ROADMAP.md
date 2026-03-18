# RS Systems — Roadmap

*High-level project status and what's next.*
*Last Updated: March 16, 2026*

---

## ✅ Completed

### v2.5 — Production Hardening & Live Billing (March 15-16, 2026)
- **Live Stripe keys** — switched from test to live mode in production
- **Cache fix** — RedisCache → DatabaseCache fallback (no Redis on EB)
- **Login resilience** — ratelimit + DRF throttling gracefully degrade on cache failure
- **Stripe subscription checkout** — creates live Checkout Sessions, redirects to Stripe
- **Invoice payment flow** — end-to-end: repair → invoice → Stripe payment link → webhook → payment recorded
- **Stripe Connect (Phase 1+2)** — multi-tenant payment routing deployed (awaiting Connect activation)
- **Phone validation UX** — accepts all common formats, normalizes to E.164
- **Multi-break fix** — admin/owner users can now create multi-break batches (was crashing)
- **Duplicate repair check** — no longer blocks editing existing batch repairs
- **Notification CSRF fix** — mark-all-read works with httpOnly CSRF cookies
- **Notification escaping** — fixed `&amp;` double-escaping in customer names
- **Admin forgot password** — enabled built-in Django admin password reset link
- **AWS IAM** — `amelia-deploy` user for autonomous deploys, log access, monitoring
- **GitHub autonomy** — branch protection, PAT for PR merge, full CI/CD loop
- **Scaling guide** — `docs/SCALING.md` — component thresholds, upgrade paths, cost estimates
- **Stripe Connect proposal** — `docs/proposals/stripe-connect-multi-tenant-payments.md`
- **8 PRs merged, 8 deploys, zero downtime** in one day

### v2.4 — Admin Console Overhaul (March 11-12, 2026)
Custom metrics dashboard, TenantFilterMixin (tenant-aware filtering), subscription management actions, CSV exports, bulk invoice generation, audit log viewer (Django LogEntry), global admin search (`/admin/search/`). Performance: select_related, autocomplete_fields, list_per_page. 41 admin tests.

### v2.3 — Subscription Expiry UX (March 11, 2026)
Role-aware `/subscription-blocked/` page, 30-day read-only grace period, banners for all roles, email alerts at 6 lifecycle stages, `check_subscription_alerts` management command. 31 tests.
→ Details: [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md)

### v2.2.1 — SaaS Subscription Billing (Feb 10-11, 2026)
Stripe Checkout Sessions, usage enforcement (repairs/techs/customers limits), trial/expired/past-due banners, subscription webhooks, billing portal link.

### v2.1–2.2 — Billing & Invoicing (Jan 31 – Feb 4, 2026)
Full invoicing lifecycle: auto-invoice, PDF generation, Stripe payments, payment confirmation emails, customer/owner/tech invoice portals, manual payment recording, sales tax system.

### v2.0 — Unified Permissions & Templates (Jan 30, 2026)
Single permission system (`common/auth.py`), one base template (`base_app.html`), fixed signup/onboarding.

### Earlier Releases
- **Manager Settings** (Nov 2025) — viscosity rules, team overview, `@manager_required`
- **Notifications** (Oct 2025) — SendGrid email + SMS, repair lifecycle notifications
- **Rewards & Referrals** (Jul 2025) — referral codes, points, redemption

---

## 🔴 Blocking Revenue (Do Now)

### Stripe Connect Activation
- **Status:** Code deployed, needs Drake to enable Connect in Stripe Dashboard
- **Action:** Go to https://dashboard.stripe.com/connect → sign up
- **Impact:** Without this, other shops can't receive customer invoice payments
- **Proposal:** `docs/proposals/stripe-connect-multi-tenant-payments.md`

### SendGrid Credits Exhausted
- **Status:** All emails blocked — invoices, password resets, invitations
- **Action:** Upgrade SendGrid plan or wait for credit reset
- **Impact:** Can't onboard new users (no invitation/verification emails)

### Sentry Error Tracking
- **Status:** Integration wired in code, just needs `SENTRY_DSN` env var in EB
- **Action:** Create free Sentry project → set DSN → deploy
- **Impact:** Catches every 500 instantly with full traceback (would have saved hours on the login crash)

---

## 🟡 First Customer Readiness

### Mobile UX Bug Sweep
- **Status:** Active bugs found on mobile (notification CSRF, form silent failures)
- **Action:** Systematic test of every page on mobile, fix responsiveness
- **Priority:** Shop owners and techs use phones in the field

### Admin Password Reset
- **Status:** Admin account missing email, can't use password reset
- **Action:** Set email on admin user via `changepassword` management command

### Tailwind CDN → Production Build
- **Status:** Loading from `cdn.tailwindcss.com` in production (shows console warning)
- **Action:** Bundle Tailwind via PostCSS or Tailwind CLI, serve from static files
- **Impact:** Faster page loads, no external dependency

### CI/CD Pipeline
- **Status:** No automated tests on PR. Amelia runs tests locally before merge.
- **Action:** GitHub Actions workflow: run test suite on every PR to `main`
- **Impact:** Catches regressions before deploy

---

## 🟢 Growth Features

### Customer Portal Improvements
- Fleet managers need: view repairs, approve work, pay invoices, see history
- Quick-approve/deny from email links (partially built)
- Customer team management (invite fleet manager colleagues)

### Owner Reporting & Analytics
- Monthly revenue trends, repair volume charts
- Technician performance (repairs/day, completion rate)
- Customer profitability analysis
- Export to CSV/PDF

### SMS Notifications
- Fleet managers don't check email — text them
- Repair approval requests, invoice ready, payment confirmed
- AWS SNS integration exists, needs UI + templates

### QuickBooks Integration
- Export invoices to QuickBooks Online
- Sync customer records
- Revenue tracking for accountant handoff

### QR Code on PDF Invoices
- Scan-to-pay from printed invoices
- Generates QR linking to Stripe payment page

---

## 🔵 Scale Prep

### Redis + Celery (When Needed)
- **Trigger:** > 50 concurrent users or email sending slows requests
- **Action:** Add ElastiCache Redis, re-enable Celery for async tasks
- **Details:** `docs/SCALING.md`

### Auto-Scaling
- **Trigger:** > 100 req/sec sustained
- **Action:** EB capacity → Load balanced, min=1 max=3

### CDN for Media
- **Trigger:** > 1000 photos/day served
- **Action:** CloudFront distribution for S3 media bucket

---

## 📋 Backlog

### Near-term
- Per-customer payment terms override
- Tech portal: payment badge on repair list (invoiced/paid indicator)
- Customer self-service repair requests via portal
- PWA / offline mode for techs

### Medium-term
- Lot walking scheduler
- Multi-location support per tenant
- Smart technician assignment (workload + distance)
- Customer portal refresh (unified styling)

### Long-term
- AI/ML damage assessment from photos
- White-label branding per shop
- API for third-party integrations
- Mobile native app (React Native)

---

## 🐦 X / Social

**Active accounts:**
- **@wrenchtokeys** (Drake) — ~1,009 followers, building in public
- **@Amelia_claw** (Amelia) — AI dev account, iterating on voice + engagement

Analytics: `~/clawd/x_analytics.md`
Strategy: `~/clawd/x_strategy.md`

---

## Related Docs
- [`SCALING.md`](/docs/SCALING.md) — Infrastructure scaling guide
- [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) — Detailed billing phases
- [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md) — Trial/expiry/grace period
- [`CHANGELOG.md`](CHANGELOG.md) — Version history
- [`proposals/`](/docs/proposals/) — Feature proposals awaiting approval
