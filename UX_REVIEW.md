# UX Review & Bug Tracker

Tracks bugs found during admin/code audits. Each entry includes a CODE reference,
status, and description.

## Fixed

### CODE-231: AuditLogAdmin missing tenant scoping (cross-tenant data leak)
- **Severity:** 🔴 Tenant isolation bug
- **Fixed:** 2026-03-29
- **Details:** `AuditLogAdmin` (Django's `LogEntry` admin) had no `get_queryset()`
  override — non-superuser staff could see ALL audit log entries across all tenants.
  Since `LogEntry.object_repr` contains customer names, invoice numbers, and repair
  details, a Shop A admin could read Shop B's sensitive business data simply by
  visiting the audit log page. Fixed by scoping to log entries made by users who
  share at least one active `TenantMembership` with the requesting user.
- **Test:** `tests/bug_fixes/test_code231_auditlog_tenant_scoping.py` (6 tests)

### CODE-230: Replacement.save() missing tenant filter on UnitRepairCount reset
- **Severity:** 🔴 Tenant isolation bug
- **Fixed:** 2026-03-29
- **Details:** When a Replacement was completed, the code that resets the unit's
  repair count (new windshield = fresh repair pricing) queried UnitRepairCount
  without `tenant=self.tenant`. This could reset the wrong tenant's repair count
  if two tenants had customers with the same unit number. The Repair model's
  save() already included tenant= in its UnitRepairCount lookup — this was a
  copy-paste omission when Replacement was added.
- **Test:** `tests/bug_fixes/test_code230_replacement_unit_count_tenant.py`

## Open / Noted (for future runs)

### Missing db_index on frequently filtered fields
- `queue_status` on Repair (via GlassService) — filtered in many views and admin
- `status` on Invoice, CustomerInvitation, ReviewRequest, RewardRedemption
- `is_active` on Tenant, Technician, ViscosityRecommendation, TaxRate, etc.
- **Impact:** Performance — queries scan more rows than needed on larger datasets.
  Not urgent now (small data) but should be addressed before scale.

### Security admin models not registered
- `LoginAttempt` and `SecurityAuditLog` have no admin registration
- Low priority — they're audit/security models and may intentionally be unregistered

### ApprovalToken not registered in admin
- `customer_portal.ApprovalToken` — no admin registration
- Might be fine if it's a transient/token model, but could be useful for debugging
