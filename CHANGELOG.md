# Changelog

All notable changes to RS Systems are documented here.

## [Unreleased] — 2026-03-21

### Added
- **Void invoice action** — owners can void invoices from both the bulk action bar (invoice list) and individual invoice detail page. Voiding sets status to CANCELLED. Paid and already-voided invoices are skipped.
- **Delete voided invoices** — the delete action now accepts both DRAFT and CANCELLED (voided) invoices. Active invoices must be voided first before deletion.
- New URL: `POST /owner/invoices/<id>/void/` for single-invoice void

### Changed
- Bulk action bar: "Delete Drafts" renamed to "Delete" with updated confirmation text explaining void-first workflow
- Street address field added to billing location settings (owner Settings → Billing tab)

---

## [2.7] — 2026-03-19 (Tenant Isolation Sweep)

### Fixed (CODE-077 through CODE-093)
- Systematic fix for unscoped `request.user.technician` OneToOneField across entire technician portal
- DRF API ViewSets tenant-scoped
- Clawdbot invoice views tenant-scoped
- Reminder/auto-invoice services tenant-scoped
- Billing API tenant-scoped
- `shop_join_view` blocking existing users (CODE-093)
- `InvoiceService` missing tenant in 3 billing call sites (CODE-092)
- ~70+ regression tests added

---

## [2.6] — 2026-03-18 (Security Hardening Continued)

### Fixed (CODE-049 through CODE-061)
- Race conditions: payment concurrency, TOCTOU
- Financial bugs: Stripe Connect routing, double-billing via unpaid sessions
- IDOR fixes, price override permission escalation
- Replacement-only invoice email skip
- Customer approve/deny status guards
- ~103 new regression tests

---

## [2.5] — 2026-03-15 (Security Hardening Sprint)

### Fixed (CODE-005 through CODE-035)
- 35 bugs fixed: tenant isolation gaps, cross-tenant IDORs, broken permission decorators, N+1 queries

---

## [Stripe Connect] — 2026-03-17

### Added (Stripe Connect Phases 1-3 — Online Invoice Payments)

**Feature: Shop owners can now connect their Stripe account to accept online invoice payments.**

#### Phase 1: Connected Account Onboarding
- **`Tenant` model** — new Stripe Connect fields: `stripe_connect_account_id`, `stripe_onboarding_status` (not_started/pending/in_review/active/restricted/disabled), `stripe_connect_charges_enabled`, `stripe_connect_payouts_enabled`, `stripe_connect_onboarding_complete`, `stripe_connected_at`, `platform_fee_percent`
- **`ConnectService`** (`apps/tenants/services/connect_service.py`) — full service class for Express account creation, onboarding links, status sync, and direct charge sessions
- **Module-level functions**: `create_connect_account`, `create_account_link`, `handle_account_updated_webhook`, `calculate_platform_fee`, `create_direct_charge_session` — spec-aligned API for views and tests
- **Owner portal Connect views**: `connect_setup`, `connect_return`, `connect_refresh`, `connect_dashboard` in `apps/saas/views.py`
- **URLs**: `/owner/payments/setup/`, `/owner/payments/setup/return/`, `/owner/payments/setup/refresh/`, `/owner/payments/dashboard/`
- **Owner Settings template** — new "Payment Processing" tab with Connect status badge, action buttons, and "Customers cannot pay invoices online" warning when not active

#### Phase 2: Payment Routing (Direct Charges)
- **Hard block in `create_direct_charge_session`**: raises `ConnectError` if `stripe_onboarding_status != 'active'` OR `stripe_connect_charges_enabled` is False
- **Direct charges**: checkout sessions created on the connected account via `stripe_account=` param with `application_fee_amount` for platform fee
- **Invoice email gate** (`InvoiceEmailService`): payment links omitted when `tenant.can_accept_payments` is False
- **Customer portal gate**: `can_pay_online` context variable is False when tenant has no active Connect

#### Phase 3: Admin Fee Dashboard
- **`PlatformConfig` model** — singleton global settings (default_fee_percent, competition_pool_enabled, competition_pool_fee_percent); added `get_solo()` alias for `get()`
- **`PlatformFeeRecord` model** — tracks every platform fee collected (tenant, invoice, payment_intent_id, gross_amount, fee_amount, fee_percent, stripe_account_id)
- **Fee recording** in `_handle_payment_succeeded` webhook handler — creates `PlatformFeeRecord` when `application_fee_amount > 0`; deduplication prevents double-recording
- **Admin views**: `/admin/connect-accounts/` (list all tenants with Connect status) and `/admin/platform-config/` (edit global fee settings singleton)
- **Admin templates**: `templates/admin/connect_accounts.html` and `templates/admin/platform_config.html`

### Tests
- **`tests/test_stripe_connect.py`** — 31 new tests covering:
  - Fee calculation: tenant override > global default > 0 fallback
  - `create_direct_charge_session` hard block for non-active Connect
  - `handle_account_updated_webhook`: status transitions (active, restricted, in_review, pending)
  - First activation sets `stripe_connected_at`; re-activation doesn't overwrite it
  - Invoice email: `can_accept_payments` gate
  - Customer portal: `can_pay_online` context var logic
  - `PlatformConfig` singleton behavior and `get_solo()` alias
  - `PlatformFeeRecord` creation, deduplication, and zero-fee bypass

---

## [Unreleased] — 2026-03-17

### Added (Soft-Delete for Repairs & Invoices)

**Feature: Repairs and invoices can now be soft-deleted instead of permanently removed.**

- **`Repair.deleted_at`** — new nullable `DateTimeField`; when set, the repair is excluded from all default querysets
- **`Invoice.deleted_at`** — same pattern on Invoice model
- **`RepairSoftDeleteManager` / `InvoiceSoftDeleteManager`** — default managers auto-filter `deleted_at__isnull=True`; use `Repair.all_objects` / `Invoice.all_objects` for unfiltered access
- **`delete_repair` view** (`POST /tech/repairs/<id>/delete/`) — owner/manager only; blocks if any payment exists on a linked invoice; soft-deletes repair + cascades to linked invoices
- **`restore_repair` view** (`POST /tech/repairs/<id>/restore/`) — owner/manager only; restores repair + its linked invoices; blocked after 30 days
- **`archived_repairs` view** (`GET /tech/repairs/archived/`) — shows all soft-deleted repairs and invoices within the 30-day window with one-click restore
- **Delete button** on `repair_detail.html` — visible to owners/managers only; triggers a confirmation modal before POSTing
- **`purge_deleted_records` management command** — hard-deletes records older than `--days` (default 30); dry-run by default, use `--apply` to execute; handles PROTECT constraint by deleting `InvoiceLineItem` rows first
- **Migrations**: `billing.0017_invoice_deleted_at`, `technician_portal.0034_repair_deleted_at`
- **Docs**: `docs/SOFT_DELETE.md` — full reference for the feature

### Technical
- Cascade on delete: invoices with line items pointing to the deleted repair are soft-deleted in the same atomic transaction
- Restore cascade: restoring a repair also restores `deleted_at__isnull=False` invoices linked to it
- All existing querysets automatically exclude deleted records via the new default manager (no call-site changes needed)

## [Unreleased] — 2026-03-14 (2)

### Fixed (CODE-006 — Admin classes missing TenantFilterMixin / tenant visibility)
- **TechnicianAdmin** — added `tenant` to `list_display` and `list_filter`
- **UnitRepairCountAdmin** — added `TenantFilterMixin`; tenant now visible in list_display/list_filter
- **ViscosityRecommendationAdmin** — added `TenantFilterMixin`; tenant visible in list_display/list_filter
- **TaxRateAdmin** (billing app) — added `TenantFilterMixin`; tenant visible in list_display/list_filter
- **DeliveryLogAdmin** (core) — added `TenantFilterMixin` (model already had tenant FK; was missing from admin)
- **customer_portal admins** — new `CustomerTenantFilterMixin` (filters via `customer__tenant`) applied to CustomerUserAdmin, CustomerPreferenceAdmin, RepairApprovalAdmin (`repair__customer`), CustomerPricingAdmin, CustomerRepairPreferenceAdmin, CustomerInvitationAdmin; `get_tenant_display` shown in all list views
- **rewards_referrals admins** — `RewardOptionAdmin` uses `TenantFilterMixin`; `RewardAdmin`, `ReferralCodeAdmin` use new `CustomerUserTenantFilterMixin`; `ReferralAdmin` and `RewardRedemptionAdmin` have custom `get_queryset` scoping; all show tenant in list view
- **BillingConfig data fix** — new management command `fix_billing_config_names` corrects company_name = tenant.name for all rows where migration incorrectly defaulted to "Rockstar Windshield Repair" (`python manage.py fix_billing_config_names --apply`)
- All 98 existing admin/billing/owner-setup tests pass

## [Unreleased] — 2026-03-14

### Fixed (CODE-002 — Multi-tenant BillingConfig)
- **BillingConfig is now per-tenant** (`OneToOneField(Tenant)`) — removed the `singleton_id` global singleton
- Added `BillingConfig.get_for_tenant(tenant)` — creates with defaults if missing for that tenant
- `BillingConfig.get_instance()` now raises `RuntimeError` to surface any remaining legacy callers
- Updated all 14 call sites across 7 files: `apps/saas/views.py` (10), `invoice_service.py`, `invoice_tracking_service.py`, `payment_notification_service.py`, `reminder_service.py`, `tax_service.py`
- `tax_debug` management command now iterates all tenants (or accepts `--tenant <id|slug>`)
- Admin: `BillingConfigAdmin` uses `TenantFilterMixin` — non-superusers only see their tenant's config
- Migrations: `0013_billingconfig_tenant_fk` (data migration assigns existing config to first tenant) + `0014_alter_billingconfig_options`
- Tests: updated 11 existing tests + added 3 new tests (two-tenant isolation, deprecated get_instance, idempotent get_for_tenant)

## [Unreleased] — 2026-03-13

### Documentation
- **ADMIN_GUIDE.md** — Updated for v2.4 admin overhaul: added Admin Dashboard section (metrics, subscription overview, activity feed), Tenant Filtering section (TenantFilterMixin behavior for superusers vs non-superusers), Subscription Management section (extend trial 7/30d, activate, deactivate actions), CSV Exports section (repairs, invoices, customers), Bulk Invoice Generation section (CustomerAdmin action), Audit Log section (Django LogEntry viewer, color-coded badges), Global Search section (/admin/search/). Updated all navigation arrows to use → format. Bumped to v2.4.
- **CUSTOMER_GUIDE.md** — Added "When the Shop's Subscription Expires" section explaining what customers see (blocked screen with shop contact info) and what to do. Updated support contact email to contact@rssystems.io. Bumped to v2.4.
- **TECHNICIAN_GUIDE.md** — Added viscosity recommendation note with default temperature rules table. Clarified that settings pages are accessible to owners AND managers (not just `is_manager=True` technicians). Bumped to v2.4.
- **VISCOSITY_CONFIGURATION_GUIDE.md** — Major rewrite. Primary access path is now /owner/setup/ (Configure Your Shop) with auto-populate defaults on first enable. Documented all 5 default rules with temperature ranges and suggestion text. Clarified that owners and managers can access settings (fixed @technician_required bug note). Manual editing still available at /tech/settings/viscosity/. Bumped to v2.4.
- **USER_FLOWS.md** — Added 4 new flows: Configure Your Shop (setup accordion, viscosity auto-populate), Subscription Expiry (trial warning → grace → blocked, per-role screens), Statement of Account (/owner/customers/<id>/statement/), and AR Aging Report (/owner/billing/ widget + CSV export).
- **MULTI_BREAK_QUICK_START.md** — Updated windshield temperature field to mention viscosity auto-suggestions. Corrected optimal temperature range to 60–95°F (ideal: 75–95°F) per actual ViscosityRecommendation defaults.

### Added
- **"Configure Your Shop" unified setup page** (`/owner/setup/`)
  - 6-section accordion UI covering Business Info, Pricing, Tax, Billing, Viscosity, Assignment
  - Per-section AJAX save (no page reload), individual Save buttons
  - Completion status badges (✓ Complete / ⚠ Not configured / ○ Optional)
  - ⓘ info tooltips on each section explaining WHY the setting matters
  - Viscosity auto-populate: enabling creates 5 standard temperature rules scoped to the tenant
  - Mobile responsive layout with Tailwind CSS
  - Toast notifications on save success/error
  - Auto-opens first incomplete section on page load
- **Owner dashboard setup progress card** — shows "X of 6 configured" with progress bar; links to `/owner/setup/`; disappears when critical sections (Business Info + Billing) are done
- **"Configure Your Shop" link** on the existing `/owner/settings/` page
- **26 tests** in `tests/test_owner_setup.py` covering access control, each save endpoint, viscosity auto-populate, and tenant isolation

### Technical
- Added `_setup_completion(tenant)` helper to `apps/saas/views.py` (computes completion across all 6 sections)
- Added 7 new URL patterns in `apps/saas/urls.py` under `/owner/setup/`
- Dashboard view now passes `setup_completion` context to template
- `DEFAULT_VISCOSITY_RULES` constant defined in `views.py` for auto-populate
