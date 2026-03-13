# RS Systems — Roadmap

*High-level project status and what's next.*
*Last Updated: March 12, 2026*

---

## ✅ Completed

### v2.0 — Unified Permissions & Templates (Jan 30, 2026)
Single permission system (`common/auth.py`), one base template (`base_app.html`), fixed signup/onboarding.

### v2.1–2.2 — Billing & Invoicing (Jan 31 – Feb 4, 2026)
Full invoicing lifecycle: auto-invoice, PDF generation, Stripe payments, payment confirmation emails, customer/owner/tech invoice portals, manual payment recording, sales tax system (state/county/city/special rates), invoice UX improvements.

### v2.2.1 — SaaS Subscription Billing (Feb 10-11, 2026)
Stripe Checkout Sessions, usage enforcement (repairs/techs/customers limits), trial/expired/past-due banners, subscription webhooks, billing portal link. Security fix: plan only upgrades after payment confirmed.

### v2.3 — Subscription Expiry UX (March 11, 2026)
Role-aware `/subscription-blocked/` page, 30-day read-only grace period, banners for all roles, email alerts at 6 lifecycle stages, `check_subscription_alerts` management command. 31 tests.
→ Details: [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md)

### v2.4 — Admin Console Overhaul (March 11-12, 2026)
Custom metrics dashboard, TenantFilterMixin (tenant-aware filtering), subscription management actions, CSV exports, bulk invoice generation, audit log viewer (Django LogEntry), global admin search (`/admin/search/`). Performance: select_related, autocomplete_fields, list_per_page. 41 admin tests.

### Bug Fixes (March 9-12, 2026)
BUG-001 (create_repair 500), BUG-004 (custom error pages), viscosity settings 500 for owners, UX-001 through UX-011 (navbar, tables, portal preview, trial badge, onboarding, customer details, role badges, billing settings).

### Infrastructure (March 11-12, 2026)
Domain migration to rssystems.io, SendGrid domain auth, ImprovMX inbound email forwarding (contact@rssystems.io), email docs in README, OpenClaw upgrade to 2026.3.11.

### Earlier Releases
- **Manager Settings** (Nov 2025) — viscosity rules, team overview, `@manager_required`
- **Notifications** (Oct 2025) — SendGrid email + SMS, repair lifecycle notifications
- **Rewards & Referrals** (Jul 2025) — referral codes, points, redemption

---

## 🔜 Next Up

### Billing Phase 6: Automation & Polish
- Batch invoicing for `batch` preference customers
- Overdue auto-processing (daily check + reminder emails)
- Aging reports (current/30/60/90+ days)
- Statement of account per customer
- Reminder UI in owner portal ("Send Reminder" button on overdue invoices)
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md)

### Subscription Lifecycle Emails
- Payment failed / retry coming / canceled / plan changed emails
- Post-trial win-back emails (7d and 30d after expiry)
- Data export option for departing users

### Production Hardening
- Switch Stripe from test to live keys
- Monitor real user signups and onboarding flow
- Performance profiling under real load

---

## 📋 Backlog

### Near-term
- Tech portal: payment badge on repair list (invoiced/paid indicator)
- QR code on PDF invoices for scan-to-pay
- Per-customer payment terms override
- Mobile-responsive repair logging (techs are in trucks)

### Medium-term
- Customer self-service repair requests
- Owner reporting/analytics dashboard
- Customer portal refresh (unified styling)
- PWA / offline mode for techs
- Lot walking scheduler

### Long-term
- AI/ML damage assessment from photos
- QuickBooks integration
- Multi-location support
- Smart technician assignment (workload + distance)

---

## 🐦 X / Social

**Active accounts:**
- **@wrenchtokeys** (Drake) — ~1,009 followers, building in public
- **@Amelia_claw** (Amelia) — AI dev account, 3 posts/day + engagement

Strategy: [`~/clawd/x_strategy.md`]

---

## Related Docs
- [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) — Detailed billing phases
- [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md) — Trial/expiry/grace period
- [`CHANGELOG.md`](CHANGELOG.md) — Version history
