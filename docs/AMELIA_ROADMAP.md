# RS Systems — Roadmap

*High-level project status and what's next.*
*Last Updated: February 4, 2026*

---

## ✅ Completed

### Unified Permissions & Templates (v2.0.0 — Jan 30, 2026)
Single permission system (`common/auth.py`), one base template (`base_app.html`), fixed signup/onboarding. The foundation everything else is built on.
→ Details: [`PLAN.md`](/PLAN.md)

### Billing & Invoicing (v2.1.0–2.2.0 — Jan 31 – Feb 1, 2026)
Full invoicing lifecycle: auto-invoice on completion, PDF generation, Stripe payments, payment confirmation emails, customer invoice portal, owner invoice dashboard, tech on-site payment collection, manual payment recording.
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) (Phases 1-5 complete)

### Sales Tax (v2.2.1 — Feb 1, 2026)
Tax rate breakdown (state/county/city/special) configured in Settings → Billing & Tax. Tax auto-calculated on every Repair save and at invoice creation. Displayed on repair detail pages (tech + customer portals) and invoices (PDF + portals). Per-customer `tax_exempt` flag supported. Auto-enables when rates are saved.
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md#phase-8-sales-tax-by-zip-code) (Phase 8 complete)

### Invoice UX Improvements (v2.2.2 — Feb 4, 2026)
- **Clickable overdue badge** — Click the "Overdue" summary card to filter to all overdue invoices
- **Overdue count badge** — Shows number of overdue invoices on summary card
- **Send confirmation modal** — "Create & Send" now shows preview before sending:
  - Email subject preview
  - Invoice summary (number, repair count, total)
  - Editable recipient email field
  - Multi-recipient support (comma-separated emails)
  - CC support for additional recipients
- **Dismiss uninvoiced repairs** — For legacy repairs already paid outside the system:
  - "Dismiss" button hides repairs from invoicing without deleting them
  - Adds `skip_invoicing` flag to Repair model
- **Dev email fix** — Console email backend in development (avoids SSL errors)
→ Details: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md#52-owner-portal--invoice-dashboard-)

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

### Retail Customer Enhancements
- **Saved vehicles per customer** — Like units for fleets, but for retail customers who return
- **Vehicle lookup by VIN** — Auto-populate year/make/model from VIN
- **Retail rewards program** — Points/discounts for repeat retail customers
- **Vehicle repair history** — Track all repairs per vehicle (year/make/model)

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
