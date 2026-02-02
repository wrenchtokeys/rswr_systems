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

## [2.2.1] - February 1, 2026

### Fixed — Tax Calculation on Repair Tickets & Invoices
- **Tax on repair tickets**: Added `tax_rate`, `tax_amount` fields to Repair model. Tax is now calculated automatically from `BillingConfig` rates every time a repair is saved. `total_with_tax` property shows cost + tax.
- **Tax display**: Repair detail pages in both technician and customer portals now show tax breakdown and total with tax.
- **Invoice creation fix**: Moved `InvoiceService` (reportlab) import into the PDF generation block so invoice record creation and tax calculation no longer fail if reportlab is unavailable.
- **Auto-enable tax on rate save**: Saving non-zero tax rates in Owner Settings now automatically sets `tax_enabled = True`.

---

## [2.2.0] - February 1, 2026

### 🧾 INVOICE PORTALS & PAYMENT MANAGEMENT

Full invoice visibility and payment handling across all three portals.

#### Added — Customer Portal
- **Invoice List** (`/app/invoices/`): Customers see all their invoices with status badges (Paid ✅, Overdue 🔴, Sent 📤, Partial ⚠️, Cancelled)
- **Invoice Detail** (`/app/invoices/<id>/`): Line items, totals, payment history, PDF download
- **Pay Now**: One-click Stripe checkout from invoice detail page
- **"Invoices" nav link** added to customer portal navigation

#### Added — Owner Portal
- **Invoice Dashboard** (`/owner/invoices/`): Summary cards (outstanding, overdue, payments this month) + full invoice table with filters
- **Manual Payment Recording**: Form on invoice detail — record cash, check, wire, ACH, credit card payments with reference number, date, notes
- **Auto-status updates**: Recording payment automatically updates invoice status + sends confirmation emails
- **PDF view + payment actions** on every invoice row

#### Added — Technician Portal
- **Collect Payment On-Site** (`/tech/repairs/<id>/collect-payment/`): Techs can record cash/check payments from repair detail page for completed+invoiced repairs
- Payment auto-linked to invoice, confirmation emails sent

#### Added — Stripe Landing Pages
- `/payment-complete` — Branded thank-you page after successful Stripe payment
- `/payment-cancelled` — Return page for cancelled Stripe checkouts

#### Technical Details
- Customer views: `apps/customer_portal/views.py` (`customer_invoices`, `customer_invoice_detail`, `customer_invoice_pay`)
- Owner views: `apps/saas/views.py` (`owner_invoice_list`, `owner_invoice_detail`)
- Tech view: `apps/technician_portal/views/repairs.py` (`tech_collect_payment`)
- Templates: `customer_portal/invoices/`, `saas/owner_invoices.html`, `saas/owner_invoice_detail.html`

---

## [2.1.0] - January 31, 2026

### 💰 BILLING & INVOICING SYSTEM

Complete billing infrastructure: auto-invoicing, Stripe payments, payment confirmation emails.

#### Added
- **BillingConfig** singleton: Company address (street/city/state/zip), default payment terms, invoice prefix/footer — configurable via Admin > Billing
- **Payment Terms**: COD (default), Due on Receipt, NET15/30/45/60. Due date auto-calculated. Displayed on PDF invoices.
- **Stripe Integration**: Payment Links auto-generated on invoice creation. Checkout Sessions. Webhook handler at `/api/billing/stripe/webhook/`
- **Auto-Invoice on Completion**: Django signal fires on repair COMPLETED → generates PDF → saves to S3 → emails customer (for `per_ticket` preference customers)
- **Payment Confirmation Emails**: Branded HTML receipt to customer (amount, method, date, remaining balance with "Pay Remaining" link for partials). Plain text notification to owner.
- **Payment Status in Portals**: Owner dashboard and repair detail pages show invoice/payment status
- **15+ Billing API Endpoints** at `/api/billing/` — dashboard, CRUD, Stripe, reminders, customer preferences

#### Technical Details
- Invoice + InvoiceLineItem + Payment models with double-billing prevention
- Services: `invoice_service.py` (PDF), `auto_invoice_service.py`, `stripe_service.py`, `invoice_email_service.py`, `reminder_service.py`, `dashboard_service.py`, `report_service.py`
- Stripe webhook handles `checkout.session.completed` + `payment_intent.succeeded` → auto-records Payment → updates Invoice status
- Full billing roadmap: [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md)

---

## [2.0.0] - January 30, 2026

### 🏗️ UNIFIED PERMISSIONS, TEMPLATES & ONBOARDING

Major architectural overhaul: one permission system, one base template, fixed signup flow. Built in a single session — 28 tests passing.

#### Added
- **Unified Permission System** (`common/auth.py`):
  - `can_access(user, area, tenant)` — single function replacing 182 scattered permission checks across 7 mechanisms
  - `@requires('area')` decorator for all views
  - Context processor providing `user_can_repair`, `user_can_invoice`, etc. to all templates
  - Areas: repairs, customers, invoices, reports, team, settings
- **`base_app.html`** — One base template for all shop staff (owner, manager, tech). Modern Tailwind, sticky nav, adapts to user capabilities. Replaces the old `base.html` / `base_owner.html` split.
- **Settings Package**: Refactored `settings.py` into `rs_systems/settings/base.py`, `development.py`, `production.py`

#### Changed
- **Signup & Onboarding**: `create_tenant_with_owner()` now auto-creates Technician profile + adds to Technicians group. Onboarding cut to 2 steps (business info → dashboard). No more silent failures.
- **All redirects**: `redirect('home')` for authenticated users replaced with `redirect_to_portal(user)` — customers go to `/app/`, staff go to `/tech/dashboard/`
- **Owner Navigation**: Changed from `Dashboard | Billing | Settings | [Tech Portal]` to `Dashboard | Repairs | Customers | Invoices | Settings` — linking to existing pages
- **~25 tech portal templates** updated from `{% extends "base.html" %}` to `{% extends "base_app.html" %}`

#### Fixed
- Onboarding wizard silently advancing on form failures, leaving users without Technician profiles
- Owners landing on `base.html` pages with wrong nav after clicking dashboard actions
- Authenticated users being redirected to landing page instead of their portal

#### Details
- Full plan and rationale: [`PLAN.md`](/PLAN.md)
- Steps 1-5 completed in one day. Step 6 (deploy to AWS) pending.

---

## [1.7.0] - November 18, 2025

### 🎛️ MANAGER SETTINGS PORTAL

#### Added
- **Manager Settings Dashboard** (`/tech/settings/`): Card-based navigation hub for managers
- **Viscosity Rules Management** (`/tech/settings/viscosity/`): CRUD interface with auto-priority system (🥇🥈🥉 badges), modal editing, toggle switches, AJAX operations
- **Team Overview** (`/tech/settings/team/`): Performance dashboard — per-technician stats, completion rates, recent repairs
- **`@manager_required` decorator** for view-level access control

#### Changed
- Viscosity rules UX: removed confusing manual priority input, replaced with automatic ordering + visual badges
- `ViscosityRecommendation` model: added public `get_temp_range_display()` for template access

#### Fixed
- Template syntax error from calling private `_get_temp_range_display` method

---

## [1.6.3] - November 3, 2025

### 🗄️ STORAGE & DATA MANAGEMENT

#### Added
- **Automatic Photo Deletion**: `django-cleanup` package deletes S3 files when repairs are removed
- **Storage Audit Command**: `python manage.py audit_repair_photos` — finds orphaned files, calculates storage costs, optional `--delete`

#### Changed
- `TechnicianNotification` cascade behavior: SET_NULL → CASCADE (notifications deleted with repair)

#### Fixed
- Orphaned photos remaining in S3 after repair deletion (14+ files, ~16 MB in production)

#### Security
- Deleted repair photos now actually removed from S3 (GDPR compliance improvement)

---

## [1.6.2] - October 30, 2025

### 🔒 BACKUP & DATA PROTECTION

#### Changed
- **RDS backup retention**: 7 → 30 days with point-in-time recovery
- **S3 versioning enabled**: Deleted/replaced photos recoverable for 30 days
- **Lifecycle policies**: Auto-cleanup of old versions, expired markers, incomplete uploads

#### Removed
- Custom SQLite backup system (was silently failing since August — production uses PostgreSQL)
- Empty `rs-systems-backups-20250823` S3 bucket

---

## [1.6.1] - October 29, 2025

### 🔧 ADMIN ENHANCEMENTS

#### Added
- **Lot Walking Admin Configuration**: Checkbox widgets for day selection, time picker, frequency dropdown in CustomerRepairPreference admin
- **Enhanced admin list**: `lot_walking_enabled` and `lot_walking_frequency` columns + filters

---

## [1.6.0] - October 29, 2025

### 📸 IMAGE UPLOAD ENHANCEMENTS

#### Added
- **HEIC/HEIF Support**: Native iPhone photo format with auto-conversion to JPEG (95% quality)
- **10MB Upload Limit**: Increased from 2.5MB (Django + Nginx configured)
- **Image Conversion Utility** (`common/utils.py`): Shared HEIC→JPEG converter

#### Fixed
- Upload failures for 2.5-5MB files (Django default limit)
- AWS 413 errors (Nginx 1MB default)
- HEIC images not displaying in browser

---

## [1.5.0] - October 25, 2025

### 🎨 MAJOR UI/UX REDESIGN

#### Changed
- **Customer Account Settings**: Complete redesign — card-based layout, tooltip system, tab navigation, Tailwind CSS

#### Added
- **Lot Walking Configuration UI**: Customer-facing settings for frequency, preferred days/time
- **UI Design Guide** (`docs/development/UI_DESIGN_GUIDE.md`)

---

## [1.4.0] - October 21, 2025

### 🚨 CRITICAL SECURITY FIXES & WORKFLOW

#### Security
- **CRITICAL**: Fixed approval bypass — technicians could set status to COMPLETED to skip customer approval
- **HIGH**: Fixed IntegrityError when technicians updated their own repairs

#### Added
- Manager assignment system for REQUESTED repairs
- Customer approval dashboard with yellow alert banner
- Customer repair preferences (AUTO_APPROVE, REQUIRE_APPROVAL, UNIT_THRESHOLD)
- Notification enhancement: repair ForeignKey + "View Repair" button
- Repair visibility controls (REQUESTED=managers only, PENDING=hidden from techs)

---

## [1.3.0] - September 28, 2025

### 🎯 SPRINT 1: Core Pricing & Roles

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
| 2.2.0 | Feb 1, 2026 | Invoice Portals & Payments | ✅ Complete |
| 2.1.0 | Jan 31, 2026 | Billing & Invoicing System | ✅ Complete |
| 2.0.0 | Jan 30, 2026 | Unified Permissions & Templates | ✅ Complete |
| 1.7.0 | Nov 18, 2025 | Manager Settings Portal | ✅ Complete |
| 1.6.3 | Nov 3, 2025 | Storage & Data Management | ✅ Complete |
| 1.6.2 | Oct 30, 2025 | Backup & Data Protection | ✅ Complete |
| 1.6.1 | Oct 29, 2025 | Admin Lot Walking Config | ✅ Complete |
| 1.6.0 | Oct 29, 2025 | Image Upload (HEIC) | ✅ Complete |
| 1.5.0 | Oct 25, 2025 | UI/UX Redesign | ✅ Complete |
| 1.4.0 | Oct 21, 2025 | Security Fixes & Workflow | ✅ Deployed |
| 1.3.0 | Sep 28, 2025 | Pricing & Roles | ✅ Complete |
| 1.2.0 | Aug 23, 2025 | Backup & Security | ✅ Complete |
| 1.1.0 | Aug 2025 | Photos & Security | ✅ Complete |
| 1.0.0 | Jul 2025 | Initial Release | ✅ Complete |

---

**Latest Version**: 2.2.0
**Last Updated**: February 1, 2026
**Status**: Production Ready ✅
