# UX Review & Bug Tracker

Tracks bugs found during admin/code audits. Each entry includes a CODE reference,
status, and description.

## Fixed

### CODE-258: purge_deleted_records corrupts active invoices by deleting their line items
- **Severity:** 🔴 Data integrity / financial corruption
- **Fixed:** 2026-04-01
- **Details:** `purge_deleted_records` deleted ALL InvoiceLineItems referencing
  soft-deleted repairs — including line items on active (non-soft-deleted)
  invoices (SENT, PAID, etc.). This meant a nightly purge could silently
  remove line items from a PAID invoice, breaking the total/subtotal
  relationship and the audit trail. The root cause was the PROTECT FK
  constraint on InvoiceLineItem.repair: the old code worked around it by
  deleting ALL matching line items regardless of the parent invoice's state.
  Fixed by excluding soft-deleted repairs from purging if they are still
  referenced by line items on active invoices. Those repairs will be purged
  in a future run once their parent invoice is also soft-deleted and aged
  past the cutoff. Line items are now only deleted when their parent invoice
  is also being purged or is already soft-deleted.
- **Test:** `tests/bug_fixes/test_code258_purge_active_invoice_protection.py` (6 tests)

### CODE-257: UnitRepairCount lookups missing tenant scoping in pricing services
- **Severity:** 🟡 Data integrity / potential pricing bug
- **Fixed:** 2026-04-01
- **Details:** `batch_pricing_service.calculate_batch_pricing()` and
  `pricing_service.apply_pricing_to_repair()` both queried
  `UnitRepairCount.objects.get(customer=..., unit_number=...)` without `tenant=`
  scoping. The unique constraint on UnitRepairCount is `(tenant, customer, unit_number)`,
  so the unscoped lookup could hit stale NULL-tenant legacy rows or raise
  `MultipleObjectsReturned` if both NULL-tenant and tenant-scoped rows exist for
  the same customer+unit. This would cause wrong `repair_count` to be used for
  progressive pricing calculations — a customer could be charged for the wrong
  pricing tier. The already-fixed `get_or_create` in `get_expected_cost()` (line 190)
  included `tenant=`, but the two `get()` calls at lines 54 and 250 did not.
  Fixed by adding `tenant=` to both lookups with graceful fallback when tenant is None.
- **Test:** `tests/bug_fixes/test_code257_unit_repair_count_tenant_scoping.py` (6 tests)

### CODE-256: ReminderService._render_template() crashes on malformed user templates
- **Severity:** 🟡 Silent data loss / UX bug
- **Fixed:** 2026-04-01
- **Details:** `ReminderService._render_template()` used bare `str.format()` on
  user-editable reminder email templates. If a shop owner included a stray `{`,
  an unknown placeholder like `{foo}`, or a positional `{0}`, the method would
  raise `KeyError`, `IndexError`, or `ValueError`. The caller at line 83 wrapped
  the call in `except Exception: pass`, which meant the crash was silently
  swallowed — the custom template was discarded and the default template used
  instead, with **no log entry and no warning to the shop owner**. This was the
  only remaining `.format()` call on user-editable templates without protection;
  `invoice_email_service.py`, `billing/tasks.py`, and `review_service.py`
  (CODE-244) all had proper try/except or `_safe_format()` wrappers.
  Fixed by adding a try/except that catches KeyError/IndexError/ValueError,
  logs a warning with the tenant ID and template snippet, and returns `''` so
  callers fall back to the default template.
- **Test:** `tests/bug_fixes/test_code256_render_template_safe_format.py` (7 tests)

### CODE-255: Bulk reassign technician action — cross-tenant IDOR
- **Severity:** 🔴 Tenant isolation bug
- **Fixed:** 2026-03-31
- **Details:** Both `RepairAdmin` and `ReplacementAdmin` had a
  `bulk_reassign_technician` action where the POST handler used an unscoped
  `Technician.objects.get(id=technician_id)`. While the dropdown that renders
  the technician options was correctly filtered to same-tenant technicians,
  a staff user could craft a POST request with any `technician_id` from
  another tenant and successfully reassign repairs/replacements to a
  cross-tenant technician — linking Shop B's tech to Shop A's repair data.
  Fixed by scoping the `Technician` lookup to the tenant of the selected
  items. Non-superusers without a tenant context are denied, and an
  unrecognized technician_id now shows an error message instead of crashing
  with `DoesNotExist`.
- **Test:** `tests/bug_fixes/test_code255_bulk_reassign_tenant_scoping.py` (5 tests)

### CODE-254: AutoUpdateTimestampMixin for all 18 models with auto_now updated_at
- **Severity:** 🟡 Data integrity / audit trail bug (systemic)
- **Fixed:** 2026-03-31
- **Details:** Django's `auto_now=True` on DateTimeField is NOT auto-included
  when `save()` is called with `update_fields=[...]`. CODE-253 fixed this for
  Tenant only. This commit creates a reusable `AutoUpdateTimestampMixin` in
  `rs_systems/model_mixins.py` and applies it to all 18 affected models:
  Tenant, BillingConfig, Invoice, PlatformConfig, WarrantyPolicy,
  ViscosityRecommendation, ReviewConfig, LoyaltyConfig, CustomerRepairPreference,
  CustomerPricing, ReferralCode, Reward, RewardOption, Vehicle,
  NotificationTemplate, EmailBrandingConfig, TechnicianNotificationPreference,
  CustomerNotificationPreference.
  Applied via abstract bases where possible (TenantConfig → ReviewConfig +
  LoyaltyConfig; BaseNotificationPreference → both preference models).
  Tenant's inline fix replaced with the mixin.
- **Test:** `tests/bug_fixes/test_code254_auto_update_timestamp_mixin.py` (40 tests)

### CODE-253: Tenant.save(update_fields=...) not bumping updated_at
- **Severity:** 🟡 Data integrity / audit trail bug
- **Fixed:** 2026-03-31
- **Details:** Django's `auto_now=True` on DateTimeField is NOT automatically
  included when `save()` is called with `update_fields=[...]`. Every code path
  that uses `update_fields` for efficiency — webhook handlers (6 call sites),
  subscription service (8 call sites), Connect service (4 call sites), admin
  actions (3 call sites), and more — silently leaves `updated_at` stale. The
  timestamp lies about when the Tenant record was last modified. This affects
  30+ call sites across the codebase.
  Fixed by overriding `Tenant.save()` to auto-inject `'updated_at'` into
  `update_fields` when the caller specifies `update_fields` without it.
  Creates a new list to avoid mutating the caller's original list.
- **Test:** `tests/bug_fixes/test_code253_tenant_updated_at.py` (7 tests)
- **Note:** The same bug exists on all other models with `auto_now=True` on
  `updated_at` (BillingConfig, Invoice, Reward, LoyaltyConfig, etc. — 18
  models total). A common `AutoUpdateTimestampMixin` should be created to fix
  them all. Tracked below for future runs.

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

### CODE-235: NotificationAdmin FK dropdown cross-tenant data leak
- **Severity:** 🔴 Tenant isolation bug
- **Fixed:** 2026-03-30
- **Details:** `NotificationAdmin` had custom `get_queryset()` for tenant scoping
  but no `formfield_for_foreignkey` override. Non-superuser staff could see ALL
  customers and repairs from ALL tenants in the `customer` and `repair` FK dropdowns
  when editing a notification — exposing customer names and repair details cross-tenant.
  Fixed by adding `formfield_for_foreignkey()` that scopes `customer` and `repair`
  FKs to the current user's tenant(s). `template` and `recipient_type` FKs are left
  unrestricted (no tenant context).
- **Test:** `tests/bug_fixes/test_code235_notification_fk_tenant_scoping.py` (5 tests)

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

### CODE-253b: auto_now updated_at bug on non-Tenant models — ✅ FIXED (CODE-254)

### ApprovalToken not registered in admin
- `customer_portal.ApprovalToken` — no admin registration
- Might be fine if it's a transient/token model, but could be useful for debugging
