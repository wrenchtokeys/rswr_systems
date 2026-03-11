# Changelog - RS Systems

All notable changes to the RS Systems windshield repair management platform.

## Format
- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes

---

## [2.3.1] - March 3, 2026

### Security
- **CRITICAL: Cross-tenant customer data leak** — RepairForm showed ALL customers from ALL shops. Now tenant-filtered. (BUG-001)
- **CRITICAL: Cross-tenant tax leak** — TaxService read from global BillingConfig singleton. Now reads from tenant-scoped TaxRate entries. New tenants default to zero tax. (BUG-003)
- **CRITICAL: No subscription enforcement** — Users could use app indefinitely after trial expired. New `SubscriptionEnforcementMiddleware` blocks expired/canceled tenants. (BUG-002)
- **Missing CSRF token** on primary technician change form — caused 403 on save. (BUG-007)
- **Technician queryset unfiltered** — RepairForm technician dropdown now tenant-scoped. (BUG-001)
- **Technician lookup on primary tech update** — now filtered by tenant to prevent cross-tenant assignment.

### Fixed
- **Signup crash on Django 5.x** — `User.objects.make_random_password()` removed in Django 5. Replaced with `secrets.token_urlsafe()`. (BUG-004)
- **"Add myself as technician" required name fields** — Now uses owner's existing user when `add_self` is checked. (BUG-005)
- **Skip buttons on onboarding broken** — Browser HTML5 validation blocked submit. Added `formnovalidate`. (BUG-006)
- **Real customer names in placeholder text** — Changed "EOS Trucking, Penske" to generic examples. (BUG-014)

### Added
- **Subscription lifecycle documentation** — `docs/development/SUBSCRIPTION_LIFECYCLE.md` with data retention policy, trial email alert plan, and soft landing page spec.
- **Automated test suite** — 109 tests covering billing models, auth/permissions, tenant isolation, core models, URL routing, and bug fix regressions.
- **Data retention policy** — All tenant data preserved indefinitely after trial/subscription expiration.

---

## [2.3.0] - February 19, 2026

### Added - Progressive Pricing & Replacements
- **Configurable progressive pricing tiers** - shop owners can set custom prices for repairs 1-5+ per unit
- **Progressive pricing toggle** - enable/disable per tenant in owner settings
- **Per-customer progressive pricing flag** - override tenant default for specific customers
- **Viscosity rules configuration** - moved to General tab in owner settings with dedicated link
- **Customer portal replacement views** - customers can view, approve, and deny replacements
- **Replacement list view** - with filtering and pagination for technicians
- **Replacement edit view** - technicians can update replacement details and status
- **Tax fields on Replacement model** - full tax support for glass replacements
- **Terms of Service page** - `/terms/` with legal content
- **Privacy Policy page** - `/privacy/` with legal content
- **Email verification on signup** - sends verification email after owner and customer registration

### Fixed
- **Multi-break batch tenant isolation** - convert_to_batch now correctly copies tenant to new repairs
- **UnitRepairCount tenant lookup** - includes tenant in get_or_create to prevent cross-tenant issues
- **Pricing preview** - respects progressive pricing settings from tenant
- **Repair count reset** - resets unit repair count when replacement is completed
- **Owner dashboard recent activity** - fixed template bugs in activity display
- **Registration form data preservation** - form data preserved on validation errors
- **Stale branding** - updated all references to RS Systems

### Changed
- **Documentation cleanup** - removed all emojis from documentation files

---

## [2.2.3] - February 4, 2026

### Added  Send Reminder Button
- **Send Reminder** button on invoice detail page now functional
- **Polished modal** with invoice summary, email preview, and confirmation
  - Shows customer, amount due, due date, status
  - Email subject and body preview
  - Lists what's included (PDF, payment link, invoice details)
  - Warning if no email on file
  - Escape key or click outside to close
- **PDF invoice attached** to reminder emails
- **Company info from BillingConfig** (no more hardcoded placeholders)
- Subject format: `[RS Systems] Overdue Notice: Invoice X - Customer`
- "Do not reply" footer added
- Reminder logged in invoice internal_notes
- URL: `POST /owner/invoices/<id>/reminder/`

---

## [2.2.2] - February 4, 2026

### Added  Invoice UX Improvements

#### Clickable Overdue Badge
- **Overdue summary card** on `/owner/invoices/` is now clickable  filters to show only overdue invoices
- **Count badge** shows number of overdue invoices when > 0
- **Visual highlight** (ring) when overdue filter is active

#### Send Confirmation Modal
- **"Create & Send"** now opens a confirmation modal instead of sending immediately
- Modal shows:
  - Email subject preview
  - Invoice summary (number, repair count, total amount)
  - Editable recipient email field
  - Support for multiple recipients (comma-separated)
- Backend `send_invoice_email` endpoint now accepts custom `recipient_email` and `cc_emails` parameters
- Invoice status auto-updates DRAFT  SENT when email is sent

#### Dismiss Uninvoiced Repairs
- **"Dismiss" button** on uninvoiced work section  for legacy repairs already paid outside the system
- Marks repairs with `skip_invoicing=True` flag  hides from invoicing without deleting
- API endpoint: `POST /api/billing/customers/<id>/uninvoiced/dismiss/`
- Accepts `{"all": true}` to dismiss all, or `{"repair_ids": [1,2,3]}` for specific repairs

#### Dev Email Fix
- Development settings now use **console email backend** by default
- Emails print to terminal instead of sending (avoids SSL certificate errors)
- Set `USE_REAL_EMAIL=True` in `.env` to send actual emails locally

#### Technical Details
- Templates: `saas/owner_invoices.html` (modal + clickable badge + dismiss button)
- Views: `apps/saas/views.py` (added `overdue_count` to context)
- API: `apps/billing/views.py` (`send_invoice_email` updated, `dismiss_uninvoiced_repairs` added)
- Model: `apps/technician_portal/models.py` (added `skip_invoicing` field to Repair)
- Settings: `rs_systems/settings/development.py` (console email backend)

---

## [2.2.1] - February 1, 2026

### Fixed  Tax Calculation on Repair Tickets & Invoices
- **Tax on repair tickets**: Added `tax_rate`, `tax_amount` fields to Repair model. Tax is now calculated automatically from `BillingConfig` rates every time a repair is saved. `total_with_tax` property shows cost + tax.
- **Tax display**: Repair detail pages in both technician and customer portals now show tax breakdown and total with tax.
- **Invoice creation fix**: Moved `InvoiceService` (reportlab) import into the PDF generation block so invoice record creation and tax calculation no longer fail if reportlab is unavailable.
- **Auto-enable tax on rate save**: Saving non-zero tax rates in Owner Settings now automatically sets `tax_enabled = True`.

---

## [2.2.0] - February 1, 2026

###  INVOICE PORTALS & PAYMENT MANAGEMENT

Full invoice visibility and payment handling across all three portals.

#### Added  Customer Portal
- **Invoice List** (`/app/invoices/`): Customers see all their invoices with status badges (Paid , Overdue , Sent , Partial , Cancelled)
- **Invoice Detail** (`/app/invoices/<id>/`): Line items, totals, payment history, PDF download
- **Pay Now**: One-click Stripe checkout from invoice detail page
- **"Invoices" nav link** added to customer portal navigation

#### Added  Owner Portal
- **Invoice Dashboard** (`/owner/invoices/`): Summary cards (outstanding, overdue, payments this month) + full invoice table with filters
- **Manual Payment Recording**: Form on invoice detail  record cash, check, wire, ACH, credit card payments with reference number, date, notes
- **Auto-status updates**: Recording payment automatically updates invoice status + sends confirmation emails
- **PDF view + payment actions** on every invoice row

#### Added  Technician Portal
- **Collect Payment On-Site** (`/tech/repairs/<id>/collect-payment/`): Techs can record cash/check payments from repair detail page for completed+invoiced repairs
- Payment auto-linked to invoice, confirmation emails sent

#### Added  Stripe Landing Pages
- `/payment-complete`  Branded thank-you page after successful Stripe payment
- `/payment-cancelled`  Return page for cancelled Stripe checkouts

#### Technical Details
- Customer views: `apps/customer_portal/views.py` (`customer_invoices`, `customer_invoice_detail`, `customer_invoice_pay`)
- Owner views: `apps/saas/views.py` (`owner_invoice_list`, `owner_invoice_detail`)
- Tech view: `apps/technician_portal/views/repairs.py` (`tech_collect_payment`)
- Templates: `customer_portal/invoices/`, `saas/owner_invoices.html`, `saas/owner_invoice_detail.html`

---

## [2.1.0] - January 31, 2026

###  BILLING & INVOICING SYSTEM

Complete billing infrastructure: auto-invoicing, Stripe payments, payment confirmation emails.

#### Added
- **BillingConfig** singleton: Company address (street/city/state/zip), default payment terms, invoice prefix/footer  configurable via Admin > Billing
- **Payment Terms**: COD (default), Due on Receipt, NET15/30/45/60. Due date auto-calculated. Displayed on PDF invoices.
- **Stripe Integration**: Payment Links auto-generated on invoice creation. Checkout Sessions. Webhook handler at `/api/billing/stripe/webhook/`
- **Auto-Invoice on Completion**: Django signal fires on repair COMPLETED  generates PDF  saves to S3  emails customer (for `per_ticket` preference customers)
- **Payment Confirmation Emails**: Branded HTML receipt to customer (amount, method, date, remaining balance with "Pay Remaining" link for partials). Plain text notification to owner.
- **Payment Status in Portals**: Owner dashboard and repair detail pages show invoice/payment status
- **15+ Billing API Endpoints** at `/api/billing/`  dashboard, CRUD, Stripe, reminders, customer preferences

#### Technical Details
- Invoice + InvoiceLineItem + Payment models with double-billing prevention
- Services: `invoice_service.py` (PDF), `auto_invoice_service.py`, `stripe_service.py`, `invoice_email_service.py`, `reminder_service.py`, `dashboard_service.py`, `report_service.py`
- Stripe webhook handles `checkout.session.completed` + `payment_intent.succeeded`  auto-records Payment  updates Invoice status
- Full billing roadmap: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md)

---

## [2.0.0] - January 30, 2026

###  UNIFIED PERMISSIONS, TEMPLATES & ONBOARDING

Major architectural overhaul: one permission system, one base template, fixed signup flow. Built in a single session  28 tests passing.

#### Added
- **Unified Permission System** (`common/auth.py`):
  - `can_access(user, area, tenant)`  single function replacing 182 scattered permission checks across 7 mechanisms
  - `@requires('area')` decorator for all views
  - Context processor providing `user_can_repair`, `user_can_invoice`, etc. to all templates
  - Areas: repairs, customers, invoices, reports, team, settings
- **`base_app.html`**  One base template for all shop staff (owner, manager, tech). Modern Tailwind, sticky nav, adapts to user capabilities. Replaces the old `base.html` / `base_owner.html` split.
- **Settings Package**: Refactored `settings.py` into `rs_systems/settings/base.py`, `development.py`, `production.py`

#### Changed
- **Signup & Onboarding**: `create_tenant_with_owner()` now auto-creates Technician profile + adds to Technicians group. Onboarding cut to 2 steps (business info  dashboard). No more silent failures.
- **All redirects**: `redirect('home')` for authenticated users replaced with `redirect_to_portal(user)`  customers go to `/app/`, staff go to `/tech/dashboard/`
- **Owner Navigation**: Changed from `Dashboard | Billing | Settings | [Tech Portal]` to `Dashboard | Repairs | Customers | Invoices | Settings`  linking to existing pages
- **~25 tech portal templates** updated from `{% extends "base.html" %}` to `{% extends "base_app.html" %}`

#### Fixed
- Onboarding wizard silently advancing on form failures, leaving users without Technician profiles
- Owners landing on `base.html` pages with wrong nav after clicking dashboard actions
- Authenticated users being redirected to landing page instead of their portal

#### Details
- Full plan and rationale: [Unified permissions plan (archived)
- Steps 1-5 completed in one day. Step 6 (deploy to AWS) pending.

---

## [1.7.0] - November 18, 2025

###  MANAGER SETTINGS PORTAL

#### Added
- **Manager Settings Dashboard** (`/tech/settings/`): Card-based navigation hub for managers
- **Viscosity Rules Management** (`/tech/settings/viscosity/`): CRUD interface with auto-priority system (� badges), modal editing, toggle switches, AJAX operations
- **Team Overview** (`/tech/settings/team/`): Performance dashboard  per-technician stats, completion rates, recent repairs
- **`@manager_required` decorator** for view-level access control

#### Changed
- Viscosity rules UX: removed confusing manual priority input, replaced with automatic ordering + visual badges
- `ViscosityRecommendation` model: added public `get_temp_range_display()` for template access

#### Fixed
- Template syntax error from calling private `_get_temp_range_display` method

---

## [1.6.3] - November 3, 2025

###  STORAGE & DATA MANAGEMENT

#### Added
- **Automatic Photo Deletion**: `django-cleanup` package deletes S3 files when repairs are removed
- **Storage Audit Command**: `python manage.py audit_repair_photos`  finds orphaned files, calculates storage costs, optional `--delete`

#### Changed
- `TechnicianNotification` cascade behavior: SET_NULL  CASCADE (notifications deleted with repair)

#### Fixed
- Orphaned photos remaining in S3 after repair deletion (14+ files, ~16 MB in production)

#### Security
- Deleted repair photos now actually removed from S3 (GDPR compliance improvement)

---

## [1.6.2] - October 30, 2025

###  BACKUP & DATA PROTECTION

#### Changed
- **RDS backup retention**: 7  30 days with point-in-time recovery
- **S3 versioning enabled**: Deleted/replaced photos recoverable for 30 days
- **Lifecycle policies**: Auto-cleanup of old versions, expired markers, incomplete uploads

#### Removed
- Custom SQLite backup system (was silently failing since August  production uses PostgreSQL)
- Empty `rs-systems-backups-20250823` S3 bucket

---

## [1.6.1] - October 29, 2025

###  ADMIN ENHANCEMENTS

#### Added
- **Lot Walking Admin Configuration**: Checkbox widgets for day selection, time picker, frequency dropdown in CustomerRepairPreference admin
- **Enhanced admin list**: `lot_walking_enabled` and `lot_walking_frequency` columns + filters

---

## [1.6.0] - October 29, 2025

###  IMAGE UPLOAD ENHANCEMENTS

#### Added
- **HEIC/HEIF Support**: Native iPhone photo format with auto-conversion to JPEG (95% quality)
- **10MB Upload Limit**: Increased from 2.5MB (Django + Nginx configured)
- **Image Conversion Utility** (`common/utils.py`): Shared HEICJPEG converter

#### Fixed
- Upload failures for 2.5-5MB files (Django default limit)
- AWS 413 errors (Nginx 1MB default)
- HEIC images not displaying in browser

---

## [1.5.0] - October 25, 2025

###  MAJOR UI/UX REDESIGN

#### Changed
- **Customer Account Settings**: Complete redesign  card-based layout, tooltip system, tab navigation, Tailwind CSS

#### Added
- **Lot Walking Configuration UI**: Customer-facing settings for frequency, preferred days/time
- **UI Design Guide** (`docs/development/UI_DESIGN_GUIDE.md`)

---

## [1.4.0] - October 21, 2025

###  CRITICAL SECURITY FIXES & WORKFLOW

#### Security
- **CRITICAL**: Fixed approval bypass  technicians could set status to COMPLETED to skip customer approval
- **HIGH**: Fixed IntegrityError when technicians updated their own repairs

#### Added
- Manager assignment system for REQUESTED repairs
- Customer approval dashboard with yellow alert banner
- Customer repair preferences (AUTO_APPROVE, REQUIRE_APPROVAL, UNIT_THRESHOLD)
- Notification enhancement: repair ForeignKey + "View Repair" button
- Repair visibility controls (REQUESTED=managers only, PENDING=hidden from techs)

---

## [1.3.0] - September 28, 2025

###  SPRINT 1: Core Pricing & Roles

#### Added
- Custom pricing system (CustomerPricing model + PricingService)
- Manager role system (is_manager, approval_limit, managed_technicians M2M)
- Performance tracking fields (repairs_completed, average_repair_time, customer_rating)
- Manager override UI with audit trail

---

## [1.2.0] - August 23, 2025

### Added
- Automated backup system (daily S3 backups, 30-day retention)
- Security audit command

---

## [1.1.0] - August 2025

### Added
- Photo upload system (S3 integration, before/after photos)
- Security: rate limiting, bot protection, honeypot fields, security headers

---

## [1.0.0] - July 2025

### Added
- Customer Portal (repair requests, status tracking, approval workflow, D3.js analytics)
- Technician Portal (queue workflow, smart pricing, photo documentation, rewards)
- Rewards & Referrals System (referral codes, points, flexible redemption)
- Admin interface, authentication, RESTful API with Swagger docs
- Infrastructure: PostgreSQL, WhiteNoise, AWS Elastic Beanstalk, Gunicorn

---

## Version History Summary

| Version | Date | Focus | Status |
|---------|------|-------|--------|
| 2.2.0 | Feb 1, 2026 | Invoice Portals & Payments |  Complete |
| 2.1.0 | Jan 31, 2026 | Billing & Invoicing System |  Complete |
| 2.0.0 | Jan 30, 2026 | Unified Permissions & Templates |  Complete |
| 1.7.0 | Nov 18, 2025 | Manager Settings Portal |  Complete |
| 1.6.3 | Nov 3, 2025 | Storage & Data Management |  Complete |
| 1.6.2 | Oct 30, 2025 | Backup & Data Protection |  Complete |
| 1.6.1 | Oct 29, 2025 | Admin Lot Walking Config |  Complete |
| 1.6.0 | Oct 29, 2025 | Image Upload (HEIC) |  Complete |
| 1.5.0 | Oct 25, 2025 | UI/UX Redesign |  Complete |
| 1.4.0 | Oct 21, 2025 | Security Fixes & Workflow |  Deployed |
| 1.3.0 | Sep 28, 2025 | Pricing & Roles |  Complete |
| 1.2.0 | Aug 23, 2025 | Backup & Security |  Complete |
| 1.1.0 | Aug 2025 | Photos & Security |  Complete |
| 1.0.0 | Jul 2025 | Initial Release |  Complete |

---

**Latest Version**: 2.2.0
**Last Updated**: February 1, 2026
**Status**: Production Ready 

## [2.3.0] - February 10, 2026

### Added  Phase 7: SaaS Subscription Billing Polish

#### Usage Enforcement
- **Repair creation limit**  blocks creating repairs when monthly limit reached
- **Customer creation limit**  blocks adding customers when at plan limit
- **Technician invite limit**  blocks inviting technicians when at seat limit
- All limits show friendly message with upgrade CTA

#### Subscription Status Banners
- **Trial expiring soon** (7 days)  amber banner with upgrade CTA
- **Trial expired**  red banner prompting upgrade
- **Past due**  red banner prompting payment method update
- **Canceled**  gray banner with reactivate option
- Banners display for owners/managers across all pages

#### Already Built (discovered during Phase 7)
- Usage meters on owner dashboard (repairs/technicians/customers with progress bars)
- Full subscription API (subscribe, update, cancel, reactivate, billing portal)
- Stripe webhook handlers for subscription lifecycle
- SubscriptionPlan model with limits and Stripe price IDs
- UsageService for tracking usage vs limits

### What's Needed to Go Live
1. Create Stripe Products/Prices in Stripe Dashboard (Drake action)
2. Copy `stripe_price_id` values into SubscriptionPlan records
3. Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` env vars in production

## [2.3.1] - February 11, 2026

### Security
- **CRITICAL: Plan upgrade now requires payment**  Fixed security hole where clicking "Upgrade" granted paid plan features before payment completed. Plan now only upgrades via `checkout.session.completed` webhook after Stripe confirms payment.

### Fixed
- **Stripe API breaking change**  Switched from direct subscription creation to Stripe Checkout Sessions (Stripe removed `payment_intent` from Invoice objects in March 2025)
- **Added checkout.session.completed webhook handler**  Captures subscription ID and upgrades plan after successful payment

### Changed
- `create_subscription` now returns `checkout_url` for redirect instead of `client_secret`
- Plan/subscription_plan fields only updated in webhook handlers, never before payment
