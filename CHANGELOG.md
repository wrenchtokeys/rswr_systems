
## [Unreleased] - 2026-03-04

### Fixed (Round 3 Systematic Tenant Isolation Sweep — BUG-029 through BUG-036)
- **BUG-029:** REST API ViewSets (Technician, Customer, Repair, Replacement) now tenant-scoped via TenantScopedViewSetMixin
- **BUG-030:** Dashboard admin stats (technician count, pending redemptions) now tenant-scoped
- **BUG-031:** Dashboard pending RewardRedemption lists now tenant-scoped for all user types
- **BUG-032:** RewardFulfillmentService.assign_technician() now only assigns same-tenant technicians
- **BUG-033:** RewardFulfillmentService.get_pending_redemptions() now accepts optional tenant parameter
- **BUG-034:** Referral leaderboard now scoped to current tenant
- **BUG-035:** Customer portal profile creation dropdown no longer falls back to all customers (uses .none())
- **BUG-036:** Customer portal profile creation POST error paths no longer fall back to all customers

### Added
- `TenantScopedViewSetMixin` for DRF ViewSets (`apps/technician_portal/api/views.py`)
- Tenant isolation tests for Round 3 fixes (`tests/test_tenant_isolation_round3.py`)
- Security audit document (`docs/security/TENANT_ISOLATION_AUDIT.md`)

### Fixed (Round 2 Code Audit — BUG-020 through BUG-027)
- **BUG-020:** Fixed NameError crash in send_invoice_email/send_invoice_email_batch views (Invoice model not imported)
- **BUG-021:** InvoiceTrackingService.get_outstanding_invoices() now tenant-scoped (was leaking cross-tenant data)
- **BUG-022:** InvoiceTrackingService.update_overdue_statuses() no longer mutates ALL tenants' invoices
- **BUG-023:** InvoiceTrackingService.get_uninvoiced_repairs() now scopes InvoiceLineItem query by tenant
- **BUG-024:** StripeService._record_stripe_payment() — added audit logging of tenant context
- **BUG-025:** InvoiceService.build_invoice_data() now filters Customer by tenant
- **BUG-026:** DashboardService alerts now filters batch customer prefs by tenant (returns empty without tenant)
- **BUG-027:** InvoiceEmailService now accepts tenant param and scopes all payment link queries; all callers updated
