# Tenant Isolation Security Audit

**Date:** March 4, 2026  
**Auditor:** Amelia (AI Assistant)  
**Branch:** `autonomous-work`  
**Scope:** All Python files in RS Systems, excluding migrations, venv, __pycache__

## Summary

Comprehensive sweep of every `.objects.` database query across the entire codebase to verify tenant isolation in this multi-tenant SaaS application.

**Result:** 8 new issues found and fixed (BUG-029 through BUG-036). All previous 28 bugs remain fixed.

## Methodology

1. `grep -rn "\.objects\." --include="*.py"` across entire project (excluding migrations/venv)
2. Manual review of every file with database queries
3. Verification that tenant-owned models are always filtered by tenant in user-facing code

## Apps/Files Reviewed

### apps/technician_portal/
| File | Queries Found | Status |
|------|--------------|--------|
| api/views.py | 4 ViewSets | **FIXED (BUG-029)** — Added TenantScopedViewSetMixin |
| views/dashboard.py | ~25 queries | **FIXED (BUG-030, BUG-031)** — Scoped admin stats and redemptions |
| views/repairs.py | ~15 queries | ✅ PASS — All use `.all()` + `tenant` filter pattern |
| views/customers.py | ~12 queries | ✅ PASS — All use `.all()` + `tenant` filter pattern |
| views/batch.py | ~6 queries | ✅ PASS — All tenant-scoped |
| views/rewards.py | ~4 queries | ✅ PASS — All tenant-scoped |
| views/notifications.py | ~3 queries | ✅ PASS — Scoped to technician |
| views/settings.py | 1 query | ✅ PASS — ViscosityRecommendation is global config |
| forms.py | ~4 queries | ✅ PASS — Tenant-scoped with superuser fallback |
| admin.py | ~3 queries | ✅ PASS — Django admin (superuser-only) |

### apps/billing/
| File | Queries Found | Status |
|------|--------------|--------|
| services/invoice_service.py | ~4 queries | ✅ PASS — Fixed in Round 2 |
| services/invoice_email_service.py | ~3 queries | ✅ PASS — Fixed in Round 2 |
| services/invoice_tracking_service.py | ~5 queries | ✅ PASS — Fixed in Round 2 |
| services/dashboard_service.py | ~3 queries | ✅ PASS — Fixed in Round 2 |
| admin.py | ~3 queries | ✅ PASS — Django admin (superuser-only) |
| management/commands/tax_debug.py | ~8 queries | ⚠️ NOTED — Diagnostic command, superuser-only |

### apps/customer_portal/
| File | Queries Found | Status |
|------|--------------|--------|
| views.py | ~25 queries | **FIXED (BUG-035, BUG-036)** — Changed `.all()` fallbacks to `.none()` |
| services/invitation_service.py | ~3 queries | ✅ PASS — Uses token-based lookup |

### apps/rewards_referrals/
| File | Queries Found | Status |
|------|--------------|--------|
| services.py | ~20 queries | **FIXED (BUG-032, BUG-033)** — Scoped technician assignment and pending redemptions |
| views.py | ~12 queries | **FIXED (BUG-034)** — Scoped leaderboard |
| admin.py | ~3 queries | ✅ PASS — Django admin (superuser-only) |

### apps/saas/
| File | Queries Found | Status |
|------|--------------|--------|
| views.py | ~50 queries | ✅ PASS — All properly tenant-scoped |
| forms.py | ~3 queries | ✅ PASS — Tenant-scoped |

### apps/tenants/
| File | Queries Found | Status |
|------|--------------|--------|
| services/*.py | ~15 queries | ✅ PASS — All properly scoped |
| middleware.py | ~4 queries | ✅ PASS — Tenant resolution logic |
| webhooks.py | ~8 queries | ✅ PASS — Stripe webhook, uses internal IDs |
| views.py | ~8 queries | ✅ PASS — All scoped |

### core/
| File | Queries Found | Status |
|------|--------------|--------|
| services/notification_service.py | ~5 queries | ✅ PASS — Uses recipient types |
| services/email_service.py | ~3 queries | ✅ PASS — Uses notification IDs |
| services/sms_service.py | ~3 queries | ✅ PASS — Uses notification IDs |
| tasks.py | ~8 queries | ✅ PASS — Notification delivery, scoped by recipient |
| admin.py | ~3 queries | ✅ PASS — Django admin (superuser-only) |

### apps/clawdbot/
| File | Queries Found | Status |
|------|--------------|--------|
| views.py | ~5 queries | ✅ PASS — All use `tenant=tenant` |

### apps/security/
| File | Queries Found | Status |
|------|--------------|--------|
| management/commands/security_audit.py | ~8 queries | ✅ PASS — User-level (not tenant-scoped model) |

## Query Count Summary

- **Total `.objects.` queries reviewed:** ~250+
- **Issues found:** 8 (BUG-029 through BUG-036)
- **Issues fixed:** 8
- **Tests added:** 8 (in `tests/test_tenant_isolation_round3.py`)
- **All tests passing:** ✅

## Models That MUST Be Tenant-Scoped

| Model | Has `tenant` FK | Verified |
|-------|----------------|----------|
| Customer | ✅ | ✅ |
| Repair | ✅ (via GlassService) | ✅ |
| Replacement | ✅ (via GlassService) | ✅ |
| Technician | ✅ | ✅ |
| Invoice | ✅ | ✅ |
| InvoiceLineItem | via Invoice FK | ✅ |
| Payment | via Invoice FK | ✅ |
| TaxRate | ✅ | ✅ |
| BillingConfig | ✅ | ✅ (singleton per tenant) |
| CustomerRepairPreference | via Customer FK | ✅ |

## Models Without Tenant FK (By Design)

| Model | Reason |
|-------|--------|
| ReferralCode | Linked via `customer_user__customer__tenant` |
| Referral | Linked via referral_code chain |
| Reward | Linked via `customer_user__customer__tenant` |
| RewardOption | Global catalog (like SubscriptionPlan) |
| RewardRedemption | Linked via `reward__customer_user__customer__tenant` |
| RepairApproval | Linked via `repair__tenant` |
| ViscosityRecommendation | Global reference data |
| Notification | Uses GenericForeignKey to recipient |
| NotificationTemplate | Global templates |

## Remaining Risks & Recommendations

1. **Django Admin actions** (`rs_systems/admin.py`): `make_customer` uses `Customer.objects.first()` without tenant context. This is superuser-only but could accidentally assign to wrong tenant. **Recommendation:** Add tenant selection to admin action.

2. **Management commands** (`check_notifications`, `tax_debug`, `audit_repair_photos`): Query all tenants. This is expected for diagnostic tools but should be noted. **Recommendation:** Add `--tenant` flag to commands.

3. **Rewards models lack direct tenant FK**: All scoping goes through relationship chains (`reward__customer_user__customer__tenant`). This works but is fragile. **Recommendation:** Consider adding `tenant` FK to RewardRedemption for simpler queries.

4. **ViscosityRecommendation is global**: All tenants share the same rules. **Recommendation:** Add tenant FK if tenants should have custom rules.

5. **Raw SQL**: No raw SQL queries found (`raw()`, `extra()`, `RawSQL`, `connection.cursor()`). ✅
