# Changelog

All notable changes to RS Systems are documented here.

## [Unreleased] — 2026-07-06 (Production 500 on repair form — staticfiles manifest race)

### Fixed
- **CODE-266 (root cause)** — `/tech/repairs/create/` returned 500 in production: gunicorn started **before** the postdeploy hook ran `collectstatic`, so workers on freshly-booted instances (autoscaling scale-up, immutable updates) loaded an empty staticfiles manifest and cached it for the life of the process. Every `{% static %}` render then raised `ValueError: Missing staticfiles manifest entry`. Collectstatic moved to `.platform/hooks/predeploy/01_collectstatic.sh` (runs against `/var/app/staging` before the app flips and the web service starts, on deploys *and* scale-up self-startup). Removed the now-redundant `leader_only` container command (`.ebextensions/06_static_files.config`) and the postdeploy collectstatic. Same failure signature hit `admin/css/base.css` on the previous instance July 2–4.
- **CODE-266 (resilience)** — Static storage switched to `rs_systems.storage.ForgivingManifestStaticFilesStorage` (`manifest_strict = False`): a missing manifest entry now falls back to hashing the file on disk instead of turning the whole page into a 500.
- **CODE-266 (error handler)** — `create_repair()`'s render-failure fallback crashed with `NameError: name 'settings' is not defined` (`settings.DEBUG` check without the import), replacing the intended diagnostic page with a raw 500. Import added.
- **CODE-267** — `InvoiceEmailService` called `logger.warning()` but the module never defined `logger`. The `NameError` was swallowed by an outer `except Exception: pass`, silently dropping the Stripe payment link from invoice emails whenever payment-token generation failed. Module logger added. (Found via pyflakes undefined-name audit; the audit found no other real instances.)

## [Unreleased] — 2026-03-26 (Sprint 7 — Cleanup & Registry)

### Added
- **Management Command Registry** — `docs/deployment/PRODUCTION_CHECKLIST.md` now contains a full registry of all management commands (scheduled EB cron, on-demand, and maintenance-only). Includes per-command flags, log file paths, and a 6-step checklist for adding new commands. (§19 of implementation-plan.md)

### Fixed
- **CODE-199** — `reconcile_loyalty_balances` command crashed with `TransactionManagementError` due to `select_for_update()` called outside an atomic block in the read path. Silent failure masked as "0 drifts found" on every run. Fixed by using plain `.get()` in read path; `--fix` mode still uses proper locked atomic block.
- **CODE-198** — Missing `db_index` on `Tenant.stripe_customer_id`, `stripe_subscription_id`, and `stripe_connect_account_id`. Every Stripe webhook triggered a full table scan. Three indexes added via migration `0017`.
- **CODE-197 / Loyalty Phase 2** — Four Phase 2 items shipped: `reconcile_loyalty_balances` command, `expire_loyalty_points` command, point liability report (`GET /owner/loyalty/liability/`), manual point adjustment (`POST /owner/loyalty/customers/<id>/adjust/`). 59 new tests.
- **CODE-196** — Missing `select_related('warranty_policy')` in `repair_detail()` view; extra DB query per page load for every warranted repair.
- **CODE-195 / Sprint 5 — Warranty UI** — Owner warranty policy settings, repair warranty badges, warranty claim modal, invoice PDF warranty terms. 12 new tests.
- **CODE-190** — `account_settings()` used bare `len(password) < 8` instead of `validate_password()`. Third and final instance of this pattern (CODE-188 fixed the other two).
- **CODE-190 / DashboardService** — `_filter()` applied `filter(tenant=...)` to Payment querysets which have no direct `tenant` FK (path is Payment → Invoice → Tenant). `FieldError` → 500 on billing dashboard.
- **CODE-189** — `WarrantyService.get_all_warranty_repairs()` used `models.Q(...)` without importing `models`. Runtime `NameError` on any call.
- **CODE-188** — `customer_register()` and `accept_customer_invitation()` used bare length check instead of Django's `validate_password()`. Weak/common passwords accepted.
- **CODE-187** — `unit_details()` fell into `else` branch doing `Repair.objects.filter(technician=None)` instead of `.none()` when no Technician record existed.
- **CODE-186 — Repair Completion Hook Orchestrator** — `Repair.save()` now calls a hook orchestrator (`technician_portal/hooks.py`) instead of award_completion_points directly. Loyalty, warranty, and review hooks all isolated; one failure can't block others.
- **CODE-185** — `ReferralCode.customer_user` field changed from `ForeignKey(unique=True)` to `OneToOneField` (fixes Django W342 warning; no schema change, constraint was already enforced).
- **CODE-184 (Decimal falsy)** — Three templates used `{% if value %}` on optional Decimal fields. `Decimal('0.00')` is falsy; managers with zero approval limits and $0.00-override repairs were invisible. Fixed to `{% if value is not None %}`.
- **CODE-184 (TenantConfig)** — `TenantConfig` abstract base class added to `common/models.py`. `LoyaltyConfig` refactored to inherit from it, removing duplicated `created_at`, `updated_at`, `get_for_tenant()`.
- **CODE-183** — CANCELLED invoice email guard missing in 3 send paths: single-send API, batch API, and owner portal resend.
- **CODE-182** — `send_invoice_email_batch()` batch success path never updated `invoice.status` or `invoice.sent_at`. All batch-sent invoices stayed as DRAFT indefinitely.
- **CODE-181 (email fallbacks)** — Three exception-fallback paths in `InvoiceEmailService` hardcoded `https://rssystems.io` instead of using `settings.BASE_URL`.
- **CODE-181 (convert_to_batch)** — `cost_override` not persisted on new Repair rows in `convert_to_batch()`, silently wiping manager price overrides on repair completion.
- **CODE-180** — `reward_fulfillment_detail()` used wrong email field for Customer lookup. `customer_repairs` always empty; "Apply to Repair" dropdown never appeared.

### Technical
- `WarrantyPolicy` model, migrations, admin, service, and hook — full warranty system Phase 1
- `PointTransaction` ledger, `LoyaltyConfig`, `LoyaltyService` — full loyalty Phase 2
- `db_index=True` on three Stripe ID fields — migration `0017_add_stripe_id_indexes`
- `docs/PRICING_TIERS.md` — feature-to-plan tier matrix (§17 of implementation-plan.md)
- `docs/proposals/suggestions.md` and `implementation-plan.md` — full proposals audit and action plan
- All proposal bugs §1–4 corrected in source proposal docs

---

## [Unreleased] — 2026-03-21

### Added
- **"Not sure yet" plan option at signup** — users who don't know which plan they want can skip the decision and explore during trial
- **Intended plan pre-selection on billing page** — if a user chose a plan at signup, it's highlighted with a "Recommended for you" badge and pulsing border on the billing/upgrade page
- **Stripe Checkout plan default** — the Upgrade button falls back to the user's intended plan from signup, reducing friction at checkout
- **Day 20 nudge email for undecided signups** — tenants who chose "Not sure yet" get a friendly email when 10 days remain on trial, linking to the pricing page
- **Void invoice action** — owners can void invoices from both the bulk action bar (invoice list) and individual invoice detail page. Voiding sets status to CANCELLED. Paid and already-voided invoices are skipped.
- **Delete voided invoices** — the delete action now accepts both DRAFT and CANCELLED (voided) invoices. Active invoices must be voided first before deletion.
- New URL: `POST /owner/invoices/<id>/void/` for single-invoice void
- Proposal: AI-powered plan recommendation based on shop usage data (`docs/proposals/ai-plan-recommendation.md`)

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
