# Changelog

All notable changes to RS Systems are documented here.

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
