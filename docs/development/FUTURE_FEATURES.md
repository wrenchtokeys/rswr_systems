# Future Features — RS Systems

**Last Updated**: March 3, 2026
**Purpose**: Track what's planned vs. what's done

---

##  Recently Completed (Oct 2025  Feb 2026)

### Billing & Payments (Jan 2026)
-  Invoice automation  PDF generation, auto-invoice on repair completion
-  Stripe integration  Payment Links, Checkout Sessions, webhooks
-  Customer portal invoice pages (list, detail, Pay Now)
-  Owner invoice dashboard with manual payment recording
-  Tech on-site payment collection from repair detail
-  Payment confirmation emails (customer receipt + owner notification)
-  BillingConfig (company address, payment terms, invoice defaults)

### Architecture (Jan 2026)
- ✅ Unified permission system (`common/auth.py`, `@requires()` decorator)
- ✅ One base template (`base_app.html`) for all shop staff
- ✅ Signup/onboarding fix (auto-Technician profile, simplified wizard)
- ✅ Settings refactor (base/development/production package)

### SaaS Multi-Tenant (Jan 2026)
- ✅ Tenants app (Tenant, TenantMembership, SubscriptionPlan models)
- ✅ Signup flow + onboarding wizard
- ✅ Owner portal with billing page

### Security & Tenant Isolation (March 2026)
- ✅ Cross-tenant data leak fix — RepairForm customer/technician dropdowns now tenant-filtered
- ✅ Tax service tenant isolation — TaxService reads from tenant-scoped TaxRate, not global BillingConfig
- ✅ Subscription enforcement middleware — blocks expired trials and canceled subscriptions
- ✅ CSRF fix on primary technician form
- ✅ Django 5.x compatibility fix (make_random_password removed)
- ✅ 109 automated tests covering billing, auth, tenant isolation, models, URL routing

### Manager Settings (Nov 2025)
-  Viscosity rules management (CRUD, auto-priority, AJAX)
-  Team overview dashboard (per-tech stats, completion rates)

### Notifications (Oct 2025)
-  Email + SMS notification system (SendGrid)
-  Repair status change notifications
-  Assignment and approval alerts

### Rewards & Referrals
-  Referral codes, point-based rewards, flexible redemption

### Customer Settings (Oct 2025)
-  Account settings redesign (Tailwind, card-based, tabbed)
-  Lot walking preference UI (frequency, days, time)
-  Repair preferences (auto-approve, require approval, threshold)

---

##  Planned  Near-term

### Sales Tax by Zip Code (Billing Phase 8)
Auto-calculate Arkansas state + local tax at invoice creation. `tax_enabled` toggle (default off), per-customer `tax_exempt` flag. ~8-12 hours.
 See [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md#phase-8-sales-tax-by-zip-code)

### Batch Invoicing Automation (Phase 6)
Weekly/monthly consolidated invoices for `batch` preference customers. Management command: `process_batch_invoices`. ~12 hours.

### Reminder System UI
Owner clicks "Send Reminder" on overdue invoices. Auto-reminder schedule (7/14/30 days). Reminder count tracked per invoice.

### Tech Portal Payment Badge
Show invoice status badge on repair list and repair detail for invoiced repairs.

### Aging Reports
Accounts receivable aging: current, 30, 60, 90+ days. CSV export. Key business health metric.

### Statement of Account
Per-customer statement showing all invoices and payments. Monthly or on-demand, emailable.

### QR Code on Invoice PDF
Scan-to-pay: QR code linking to Stripe checkout, printed on PDF invoices.

---

##  Planned  Medium-term

### Mobile Optimization / PWA
- Offline mode with service workers
- Touch-friendly repair logging for techs in the field
- Camera capture enhancements
- GPS location tracking
- Push notifications

### Lot Walking Scheduler (Backend)
The customer preference UI exists  scheduling backend doesn't. Needs:
- `LotWalkSchedule` + `LotWalkRoute` models
- Schedule generation from customer preferences
- Technician calendar view
- Route optimization
- `generate_lot_walk_schedules` management command

### Owner-Native Pages
Dedicated owner pages at `/customers/` and `/repairs/` extending `base_app.html` natively instead of wrapping tech portal views.

### Subscription Lifecycle & Trial Emails
Trial enforcement middleware is live, but needs:
- Email alerts before/after trial expiry (7d, 3d, 1d, expired, win-back)
- Soft landing page showing data stats + upgrade CTA (instead of hard redirect to /pricing/)
- Data export option for departing users
- **Data retention: keep all data indefinitely** (decided March 2026)
- See [`SUBSCRIPTION_LIFECYCLE.md`](SUBSCRIPTION_LIFECYCLE.md) for full plan

### SaaS Subscription Billing (Phase 7)
Wire SubscriptionPlan to Stripe Products/Prices. Checkout flow, subscription webhooks, usage enforcement. See [Billing Roadmap Phase 7](/BILLING_ROADMAP.md#phase-7-saas-subscription-billing-glass-shops).

---

## � Planned  Long-term

- **AI/ML Damage Assessment**: "Can this be repaired?" classifier from customer photos
- **QuickBooks Integration**: Export invoices to QBO (may not be needed if Stripe handles everything)
- **Advanced Analytics**: Revenue analysis, repair trends, technician performance
- **Smart Technician Assignment**: Auto-assign based on workload, distance, skills
- **Voice Notes + Digital Signatures**: For field technicians
- **Webhook System**: Third-party integrations

---

##  Related
- [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md)  Detailed billing phases
- [`docs/development/CHANGELOG.md`](CHANGELOG.md)  Version history
- [`docs/AMELIA_ROADMAP.md`](../AMELIA_ROADMAP.md)  High-level roadmap

## Custom Contact Email on Payment Pages
**Priority**: P1 (needs real email before production)
**Status**: Waiting on Drake to set up appropriate email

The payment-complete and payment-cancelled pages currently show `info@rssystems.io` which is a send-only/no-reply address. Need to replace with a real reply-to email customers can actually reach.

**Files to update:**
- `templates/billing/payment_complete.html`
- `templates/billing/payment_cancelled.html`
- Possibly `templates/emails/` notification templates if they reference this address

**Action needed:** Drake sets up an email (e.g. `support@rssystems.io`), then update all templates.
