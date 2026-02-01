# RS Systems — Roadmap

*High-level project status and what's next.*
*Last Updated: February 1, 2026*

---

## ✅ Completed

### Unified Permissions & Templates (v2.0.0 — Jan 30, 2026)
Single permission system (`common/auth.py`), one base template (`base_app.html`), fixed signup/onboarding. The foundation everything else is built on.
→ Details: [`PLAN.md`](/PLAN.md)

### Billing & Invoicing (v2.1.0–2.2.0 — Jan 31 – Feb 1, 2026)
Full invoicing lifecycle: auto-invoice on completion, PDF generation, Stripe payments, payment confirmation emails, customer invoice portal, owner invoice dashboard, tech on-site payment collection, manual payment recording.
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) (Phases 1-5 complete)

### SaaS Multi-Tenant Architecture
Tenants app with `Tenant`, `TenantMembership`, `SubscriptionPlan` models. Signup flow, onboarding wizard, owner portal with billing page. Subscription plans defined (Trial/Starter/Pro/Enterprise) but not yet wired to Stripe checkout.

### Manager Settings (v1.7.0 — Nov 2025)
Viscosity rules management, team overview dashboard, `@manager_required` decorator.

### Notifications (v1.4.0+ — Oct 2025)
Email + SMS notification system with SendGrid. Repair status changes, assignment alerts, approval requests.

### Rewards & Referrals (v1.0.0 — Jul 2025)
Referral codes, point-based rewards, flexible redemption options.

---

## 🔜 Next Up

### Sales Tax (Billing Phase 8)
Add `tax_rate`, `tax_amount` to invoices. Tax calculated at invoice creation (not Stripe checkout) so check/cash customers pay the same total. Arkansas has state + local rates varying by zip code.
- Ships with `tax_enabled=False` by default — flip on when ready
- Per-customer `tax_exempt` flag for government/exempt accounts
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md#phase-8-sales-tax-by-zip-code) (~8-12 hours)

### Billing Automation (Phase 6)
- Batch invoicing for `batch` preference customers
- Overdue auto-processing (daily status check + reminder emails)
- Aging reports (current/30/60/90+ days)
- Statement of account per customer
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md#phase-6-polish--automation) (~12 hours)

### SaaS Subscription Billing (Phase 7)
Wire up Stripe Products/Prices for subscription plans, checkout flow, subscription webhooks, usage enforcement, trial expiration.
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md#phase-7-saas-subscription-billing-glass-shops)

### Deploy v2.x to AWS
PLAN.md Step 6 — push the unified permissions/template/billing stack to production. Run migrations, verify Stripe webhook secret is set, fill in BillingConfig.

---

## 📋 Backlog

### Near-term
- Tech portal: payment badge on repair list (invoiced/paid indicator)
- Reminder system UI (owner clicks "Send Reminder" on overdue invoices)
- QR code on PDF invoices for scan-to-pay
- Per-customer payment terms override

### Medium-term
- Mobile optimization / PWA (offline mode, camera, GPS)
- Lot walking scheduler (backend scheduling from customer preferences)
- Owner-native customer/repair pages (instead of wrapping tech portal)
- Customer portal refresh (unified styling with `base_app.html`)

### Long-term
- AI/ML damage assessment from customer photos
- QuickBooks integration (maybe — Stripe may handle everything)
- Advanced analytics dashboard
- Smart technician assignment (workload + distance)

---

## 🐦 X/Twitter Strategy
**Handle**: @wrenchtokeys
**Status**: Research phase

Content pillars: tradesman who codes, building in public, industry disruption, educational content. Strategy documented but not yet executing.

---

## 🤖 Clawdbot Endpoint
**Status**: Active — used for development

- Status: `/clawdbot/`
- Customers: `/clawdbot/customers/`
- Repairs: `/clawdbot/repairs/<customer_id>/`
- Invoice preview/generation endpoints

---

## 🔗 Related Docs
- [`PLAN.md`](/PLAN.md) — Unified permissions/template plan (complete)
- [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) — Detailed billing roadmap (Phases 1-5 done)
- [`docs/development/CHANGELOG.md`](docs/development/CHANGELOG.md) — Version history
- [`docs/development/FUTURE_FEATURES.md`](docs/development/FUTURE_FEATURES.md) — Feature backlog
- [`apps/billing/README.md`](apps/billing/README.md) — Billing app technical docs
