# UX Review & Bug Tracker

Tracks bugs found during admin/code audits. Each entry includes a CODE reference,
status, and description.

## Fixed

### CODE-232b: ViscosityRecommendation & RewardOption admin missing tenant in fieldsets
- **Severity:** 🟡 Data integrity / admin UX bug
- **Fixed:** 2026-03-30
- **Details:** Both `ViscosityRecommendationAdmin` and `RewardOptionAdmin` had `tenant`
  in `list_display` and `list_filter` but NOT in `fieldsets`. This meant superusers
  creating new records via admin would save them with `tenant=NULL` (model fields are
  nullable), making them invisible to non-superuser staff and logically orphaned from
  any shop. Editing existing records also had no way to see/change the tenant assignment.
  Fixed by adding `tenant` to the first fieldset group in both admin classes.
- **Test:** `tests/bug_fixes/test_code232_admin_tenant_in_fieldsets.py` (4 tests)
- **Note:** Several other TenantFilterMixin admins (Repair, Replacement, Customer,
  Invoice, TaxRate, UnitRepairCount) also lack `tenant` in fieldsets but those models
  are primarily created via SaaS views (not admin) and have tenant auto-set logic or
  are less commonly created manually. Tracked below for future cleanup.

### CODE-233: FK dropdown leak in rewards/referrals admin (cross-tenant data leak)
- **Severity:** 🔴 Tenant isolation bug
- **Fixed:** 2026-03-30
- **Details:** `CustomerUserTenantFilterMixin` (used by `RewardAdmin`, `ReferralCodeAdmin`)
  and `ReferralAdmin` had no `formfield_for_foreignkey` override. Non-superuser staff
  could see ALL FK dropdown entries from ALL tenants when editing rewards, referral codes,
  or referrals — exposing customer names, emails, and referral codes cross-tenant.
  Fixed by adding `formfield_for_foreignkey` to `CustomerUserTenantFilterMixin` (handles
  both direct-tenant and customer→tenant FK paths) and an explicit override in
  `ReferralAdmin` for its `referral_code` and `customer_user` fields.
- **Test:** `tests/bug_fixes/test_code233_rewards_fk_tenant_scoping.py` (6 tests)

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

### CODE-234: RewardRedemptionAdmin FK dropdown cross-tenant data leak
- **Severity:** 🔴 Tenant isolation bug
- **Fixed:** 2026-03-30
- **Details:** `RewardRedemptionAdmin` used `autocomplete_fields` for `reward_option`,
  `assigned_technician`, `applied_to_repair`, and `raw_id_fields` for `reward`, but
  had no `formfield_for_foreignkey` override. While the autocomplete search results
  are scoped by the target admin's `get_queryset()`, the form's `ModelChoiceField`
  validation is NOT — it defaults to the full, unscoped queryset. A non-superuser
  staff user could bypass the autocomplete UI and POST an arbitrary cross-tenant FK
  id (e.g. a technician or repair from another shop); Django would validate it
  against the unrestricted queryset and silently accept it. This allows:
    - Assigning a Shop B technician to a Shop A reward redemption
    - Linking a Shop B repair to a Shop A redemption
    - Selecting a Shop B reward option for a Shop A redemption
  Fixed by adding `formfield_for_foreignkey()` that scopes `reward_option`,
  `assigned_technician`, `applied_to_repair`, and `reward` FKs to the current
  user's tenant(s). `processed_by` (User FK, no tenant) is left unrestricted.
- **Test:** `tests/bug_fixes/test_code234_redemption_fk_tenant_scoping.py` (5 tests)

## Open / Noted (for future runs)

### Other TenantFilterMixin admins missing tenant in fieldsets (low priority)
- Repair, Replacement, Customer, Invoice, TaxRate, UnitRepairCount, DeliveryLog
- These models are primarily created via SaaS views, not admin, and mostly
  have auto-set logic or are rarely created manually.
- Adding tenant to fieldsets would improve admin UX for superusers but is not
  a data integrity risk since these creation paths are uncommon.

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
