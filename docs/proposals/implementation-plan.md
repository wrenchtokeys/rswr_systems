# Implementation Plan — Addressing Suggestions

**Author:** Amelia  
**Date:** 2026-03-25  
**Reference:** [`suggestions.md`](./suggestions.md)  
**Purpose:** Concrete plan for implementing each suggestion from the proposals review, organized by when to do it.

---

## Immediate Fixes (Fix Now — Bugs in Proposals)

These are errors in the proposals that need correcting before any implementation begins.

### 1. Review Request: `queue_status_history_contains()` doesn't exist ✅ DONE
**Ref:** [suggestions.md §5](#5-review-request-system-draft) — "method call will raise AttributeError at runtime"

**Fix:** Replace `repair.queue_status_history_contains('DENIED')` with a check against actual data. Two options:
- **Option A (simple):** Check `repair.queue_status == 'DENIED'` — only catches currently-denied repairs, not ones that were denied and later re-requested
- **Option B (better):** Check `TechnicianNotification.objects.filter(repair=repair, message__icontains='DENIED').exists()` — catches any repair that was ever denied (using message content since TechnicianNotification has no notification_type field)

**Completed:** Fixed in `review-request-system.md`. Used Option B with `message__icontains='DENIED'`.
When customer portals deny a repair, a TechnicianNotification is created with "DENIED" in the message.
This check is robust to re-requested repairs that were previously denied.

---

### 2. Warranty: `applies_to` choices don't match Repair damage types ✅ DONE
**Ref:** [suggestions.md §4](#4-warranty-system-draft) — "silently breaks... always fall through to all_repairs default"

**Fix:** Change `WarrantyPolicy.APPLIES_TO_CHOICES` to match `Repair.DAMAGE_TYPE_CHOICES` exactly:
```python
# Was (wrong):  'chip', 'crack', 'star_break', 'bulls_eye', 'combination', 'half_moon', 'replacement'
# Now (correct): 'Chip', 'Crack', 'Star Break', "Bull's Eye", 'Combination Break', 'Half-Moon', 'Other'
```

**Completed:** Fixed in `warranty-system.md`. Choices now match `apps/technician_portal/models.py` lines 443-453
exactly. 'replacement' removed (not in Repair.DAMAGE_TYPE_CHOICES), 'Other' added. max_length bumped to
accommodate 'Combination Break' (16 chars). Added comment warning against future drift.

---

### 3. Reward Redemption UX: Wrong status filter ✅ DONE
**Ref:** [suggestions.md §10](#10-reward-redemption-ux-overhaul-draft) — "FULFILLED implies the redemption is already complete"

**Fix:** Change "Show only FULFILLED, unapplied monetary redemptions" → "Show only APPROVED, unapplied monetary redemptions."

**Completed:** Fixed in `reward-redemption-ux-overhaul.md`. FULFILLED = reward already delivered.
APPROVED = shop approved, not yet applied to a repair. Added inline comment explaining the distinction.

---

### 4. AI Plan Recommendation: Projection math bug ✅ DONE
**Ref:** [suggestions.md §8](#8-ai-plan-recommendation-draft) — "underestimates throughput for shops that ramped up"

**Fix:** Change denominator from `trial_days` to `min(trial_days, 30)`:
```python
sample_days = min(trial_days, 30)
projected_monthly_repairs = (stats['monthly_repairs'] / sample_days) * 30
```

Also fix: Stripe Connect → Enterprise recommendation was too aggressive. Moved to Pro signal.

Also fix: Threshold alignment — Enterprise now requires >15 techs or >500 projected repairs/month.
Pro covers >5 techs, >200 repairs, >50 customers, or Stripe Connect usage. Matches actual plan limits.

**Completed:** All three sub-fixes applied in `ai-plan-recommendation.md` with inline comments
explaining each correction.

---

## Build With Feature (Implement When Building Each Feature)

### 5. Loyalty System — Phases 2-4 improvements
**Ref:** [suggestions.md §3](#3-loyalty-system-overhaul-phase-1-shipped)

| Suggestion | Plan | When |
|-----------|------|------|
| Review bonus fraud — tie to Review Request `status='reviewed'`, not a self-serve button | Wire into ReviewRequestService when both are built | Phase 3 |
| `select_for_update()` on balance reads | ✅ Already implemented in LOYALTY-001 (CODE-165 pattern) | Done |
| `reconcile_balance()` nightly management command | ✅ `reconcile_loyalty_balances` command + `LoyaltyService.reconcile_balance()` — CODE-197 | Done |
| Move liability report from Phase 4 → Phase 2 | ✅ `GET /owner/loyalty/liability/` + `LoyaltyService.get_point_liability_report()` — CODE-197 | Done |
| Default expiry 365 → 730 days (or never) | Drake decided 365 days. Keep as-is unless he changes his mind | N/A |
| Backfill migration note about synthetic data | Add comment to migration noting records are synthetic, not real transactions | Next commit |
| Manual point adjustment endpoint | ✅ `POST /owner/loyalty/customers/<id>/adjust/` + `LoyaltyService.manual_adjustment()` — CODE-197 | Done |
| `expire_loyalty_points` management command | ✅ Expire command with dry-run, tenant filter, balance clamp — CODE-197 | Done |

**Phase 2 delivered (CODE-197, 2026-03-25):**
- `reconcile_loyalty_balances` mgmt command — drift detection + --fix mode + --json
- `expire_loyalty_points` mgmt command — batch expiration per customer, clamps to 0, dry-run
- `LoyaltyService.reconcile_balance()` — read-only diagnostic method
- `LoyaltyService.manual_adjustment()` — signed adjustment with reason + owner audit trail
- `LoyaltyService.get_point_liability_report()` — full outstanding liability breakdown
- `POST /owner/loyalty/customers/<id>/adjust/` — tenant-scoped, cross-tenant 404, JSON response
- `GET /owner/loyalty/liability/` — tenant-scoped JSON liability report
- 59 regression tests passing, all 47 Phase 1 tests still pass

---

### 6. Warranty System improvements ✅ Phase 2 COMPLETE (CODE-207, 2026-03-27)
**Ref:** [suggestions.md §4](#4-warranty-system-draft)

**Phase 1 delivered (Sprint 4, 2026-03-25):**
- WarrantyPolicy model with tenant scoping, `applies_to` choices matching `Repair.DAMAGE_TYPE_CHOICES`
- Warranty fields on Repair (policy FK, expires_at, void tracking, `has_warranty` property)
- WarrantyService (assign/void/check/query methods with `select_for_update()`)
- Orchestrator hook auto-assigns warranty on repair completion
- Data migration seeding default policies for all tenants
- Admin with TenantFilterMixin
- 32 regression tests passing

**Phase 2 delivered (CODE-207, 2026-03-27) — 38 new tests, 70 total:**

| Suggestion | Status |
|-----------|--------|
| Fix `applies_to` choices (see §2 above) | ✅ Done — matches `Repair.DAMAGE_TYPE_CHOICES` |
| Per-customer warranty overrides | ✅ Done — nullable `customer` FK on `WarrantyPolicy`; `assign_warranty()` checks per-customer first; admin + `__str__` updated |
| Soft-deleted original repair → show "Original repair (deleted)" | ✅ Done — template checks `deleted_at` on `warranty_original_repair` |
| Goodwill repair flag | ✅ Done — `is_goodwill_repair` boolean on Repair; excluded from loyalty points; pink badge on list/detail; admin fieldset |
| Warranty badge on repair list view | ✅ Done — ✅ W (emerald) for active, ⌛ W (amber) for expiring <30d; `warranty_expiring_soon` property on Repair |
| Warranty terms on invoice PDF | ✅ Done — `WarrantyPolicy.terms_summary` property; rendered in invoice PDF when available |
| Cache `get_warranty_stats()` or use management command | ✅ Done — 1-hour cache TTL on `get_warranty_stats()`; new `generate_warranty_report` management command (`--json`, `--tenant`, `--period`) |

---

### 7. Review Request System improvements ✅ Phase 1 COMPLETE (CODE-208, 2026-03-27)
**Ref:** [suggestions.md §5](#5-review-request-system-draft)

**Phase 1 delivered — 41 tests passing:**

| Suggestion | Status |
|-----------|--------|
| Fix `queue_status_history_contains` (see §1 above) | ✅ Done — uses `TechnicianNotification` existence check |
| Non-deterministic `CustomerUser.first()` fallback | ✅ Done — `.filter(is_primary_contact=True).first()` only; no fallback; skips if no primary |
| Customer opt-out / CAN-SPAM | ✅ Done — `CustomerUser.review_opt_out` boolean; opt-out link in every email; re-checked at send time |
| Document `'reviewed'` status is a black box until Google API | ✅ Done — code comments + proposal updated |
| `send_review_requests` to cron registry | ✅ Done — production checklist updated (every 15 min) |
| Connect to loyalty system (Phase 3) | ⏳ Pending — wires in when Google Business API integrated |

**Built:**
- `ReviewConfig` (per-tenant, extends `TenantConfig`) — enable toggle, Google review URL, email customization, cooldowns, business hours
- `ReviewRequest` model — lifecycle: pending → sent → clicked → reviewed/skipped/suppressed; UUID tokens for secure public links
- `ReviewRequestService` — 8 eligibility checks; business hours clamping; send pipeline
- `review_request_hook` in `hooks.py` — fires on COMPLETED transitions (replaces placeholder)
- Public endpoints: `/reviews/click/<token>/` and `/reviews/opt-out/<token>/`
- `send_review_requests` management command (`--dry-run` supported)
- Owner settings Reviews tab — enable/disable, Google URL, email template, recent requests table

---

### 8. Website Integration Widget improvements
**Ref:** [suggestions.md §6](#6-website-integration-widget-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Commit to iframe (not shadow DOM) for v1 | Agree — iframe is simpler, CSS-isolated | Phase 1 |
| Add `widget_token` (per-tenant secret, rotatable) | Add `widget_token = UUIDField(default=uuid4)` to tenant or widget config | Phase 1 |
| Don't auto-match customers — create `WebsiteSubmission` always | Agree — manual link/merge safer than auto-match | Phase 1 |
| Split scope: Phase 1 = backend + notifications only, Phase 2 = widget JS | Agree — current Phase 1 is too ambitious | Rescope |
| Add `submission_type` field (`quote_request`, `warranty_claim`, `general_inquiry`) | Agree — enables warranty integration path | Phase 1 |
| Spam score heuristic | Add basic scoring (all-caps, disposable email, speed) before auto-confirm fires | Phase 1 |
| Add `test_widget_submit_cross_tenant_isolation` test | Required | Phase 1 |

---

### 9. Repair Form Efficiency improvements
**Ref:** [suggestions.md §7](#7-repair-form-efficiency-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Drop #6 (auto-fill temperature from weather) | Agree — wrong location model, misleading data | Remove from proposal |
| Move #12 (offline mode) to separate standalone proposal | Agree — too complex for a form efficiency item | Separate proposal |
| Move M4 (live break counter + summary bar) to Phase 1 | Agree — pure CSS/JS, high value, zero risk | Phase 1 |
| Add form analytics endpoint FIRST, before any changes | Agree — need baseline measurements | Phase 0 (before Phase 1) |
| Unit number autocomplete: last 10 recently used, not all units | Agree — better UX and performance | Phase 2 |

---

### 10. AI Plan Recommendation improvements
**Ref:** [suggestions.md §8](#8-ai-plan-recommendation-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Fix projection math (see §4 above) | Use `min(trial_days, 30)` | Before build |
| Fix Stripe Connect → Enterprise (should be Pro signal) | Demote to Pro indicator | Before build |
| Fix threshold alignment to actual plan limits | Match Starter/Pro/Enterprise limits exactly | Before build |
| "How we calculated this" disclosure | Show data points that drove the recommendation | Phase 1 |
| Cache recommendation per tenant per day | Session or lightweight model field with 24h TTL | Phase 1 |

---

### 11. Customer Billing Preferences improvements
**Ref:** [suggestions.md §9](#9-customer-billing-preferences-ux-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Handle empty fields from collapsed `<details>` → treat as "use shop default" | Explicit check in view: empty = don't create preference record | Phase 1 |
| Remove primary tech from UI mockup (already handled by CODE-136) | Clean up proposal | Before build |
| Show actual default value ("Net 30 — shop default") not just "Shop default" | Pre-populate from `BillingConfig.get_for_tenant()` | Phase 1 |
| "Most fleet customers prefer batch billing" tooltip | Add `💡` hint next to invoice preference dropdown | Phase 1 |

---

### 12. Invoice Email Tracking improvements
**Ref:** [suggestions.md §11](#11-invoice-email-tracking-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Hash IP addresses with daily salt (GDPR/CCPA) | Store `hash(ip + daily_salt)` not raw IP. Allows dedup without storing PII. | Phase 1 |
| Label open events as "Possibly opened" (Apple MPP) | UI shows "Opened (estimated)" with tooltip explaining MPP | Phase 1 |
| Separate `EmailMultiAlternatives` migration from this proposal | Do email infra upgrade as standalone task, unblocks this + AI email | Before build |
| Spec Phase 3 auto-reminders fully (max count, notification to shop, recursive clock) | Write full spec: default 2 reminders max, shop notified, 3-day intervals, no recursion | Phase 3 |
| Add `tenant` FK to `InvoiceEmailEvent` indexes | Include in model Meta indexes | Phase 1 |
| Share click tracking infra with review request system | Build `EmailClickTracker` service used by both | Phase 1 |

---

### 13. AI Email Template Assistant improvements
**Ref:** [suggestions.md §12](#12-ai-email-template-assistant-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Verify CODE-114 (customizable email templates) exists | Check `BillingConfig` for template fields — this was built in CODE-119 | Verified |
| Generate placeholder list dynamically from actual registry | Build `get_available_placeholders()` method, feed to LLM prompt | Phase 1 |
| Enforce rate limit: daily cache key per tenant | `cache.get_or_set(f"ai_gen_{tenant.pk}_{date}", 0, 86400)` + increment | Phase 1 |
| "Preview with sample data" button | Render template with example values client-side before save | Phase 1 |
| Share `LLMClient` utility with AI Plan Recommendation | Build shared `ExternalAPIClient` if both features are built | When second AI feature ships |

---

### 14. Competition Pool improvements
**Ref:** [suggestions.md §13](#13-competition-pool-future)

| Suggestion | Plan | When |
|-----------|------|------|
| Legal review for IRS 1099 reporting | **BLOCKER** — must resolve before building. Check if Stripe handles 1099 for connected accounts. | Before build |
| `select_for_update()` on distribution | Add row lock on `CompetitionMonth` during distribution | Phase 1 |
| Public leaderboard opt-in (not default) | Add `show_on_leaderboard` boolean per tenant, default False | Phase 1 |
| Perceptual hash threshold tuning (Hamming distance) | Start with distance < 10, flag for human review, tune from real data | Phase 1 |
| Max payout cap per tenant (20% of pool) | Add `max_payout_percent` to `CompetitionConfig`, default 20% | Phase 1 |

---

## Cross-Cutting (Build as Platform Infrastructure)

**Ref:** [suggestions.md §14](#14-cross-cutting-themes)

### 15. Repair Completion Hook Orchestrator ✅ DONE (CODE-186)
**Problem:** 4+ services all triggering independently on `Repair.save()` COMPLETED transition.

**Implemented:** `apps/technician_portal/hooks.py` — shipped 2026-03-25.

```python
# In Repair.save():
from apps.technician_portal.hooks import post_completion_hooks
post_completion_hooks(self)

# Orchestrator (apps/technician_portal/hooks.py)
COMPLETION_HOOKS = [
    ('loyalty', loyalty_hook),        # awards points via LoyaltyService
    ('warranty', warranty_hook),       # no-op placeholder (WarrantyService pending)
    ('review_request', review_request_hook),  # no-op placeholder (ReviewRequestService pending)
]

def post_completion_hooks(repair):
    for name, hook in COMPLETION_HOOKS:
        try:
            hook(repair)
        except Exception as exc:
            logger.error(f"Orchestrator: unhandled exception in hook '{name}' for repair pk={repair.pk}: {exc}", exc_info=True)
```

**Key properties:**
- Each hook is isolated — failure in one does NOT block others or roll back the save
- Hooks are idempotent — loyalty_hook guards via `original_status`
- `Repair.award_completion_points()` deprecated (logic moved to `loyalty_hook`)
- 7 regression tests in `PostCompletionHooksOrchestratorTests`
- All 83 loyalty tests pass

**To add a new hook:** define `def my_hook(repair) -> None`, append to `COMPLETION_HOOKS`.

---

### 16. TenantConfig Abstract Base Class ✅ DONE
**Problem:** `BillingConfig`, `LoyaltyConfig`, `ReviewConfig`, `WarrantyPolicy` all repeat the same pattern.

**Plan:**
```python
# common/models.py
class TenantConfig(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE)

    @classmethod
    def get_for_tenant(cls, tenant):
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj

    class Meta:
        abstract = True
```

**When:** Next new config model. Retrofit existing ones in a cleanup sprint.

> **Implemented** in `common/models.py`. `LoyaltyConfig` now inherits from `TenantConfig` (`created_at`, `updated_at`, `get_for_tenant()` all inherited). Tested in `tests_loyalty.py` `TenantConfigBaseClassTest` (5 regression tests).

---

### 17. Feature-to-Plan Tier Matrix ✅ DONE
**Problem:** Pricing decisions scattered across proposals with inconsistencies.

**Plan:** Create `docs/PRICING_TIERS.md`:

| Feature | Starter | Professional | Enterprise |
|---------|---------|-------------|------------|
| Repairs & invoicing | ✅ (200/mo limit) | ✅ (unlimited) | ✅ (unlimited) |
| Loyalty points (basic) | ✅ | ✅ | ✅ |
| Loyalty tiers | ❌ | ✅ | ✅ |
| Review requests (auto) | ❌ | ✅ | ✅ |
| Website widget | ✅ (50 submissions/mo) | ✅ (500/mo) | ✅ (unlimited) |
| Warranty tracking | ✅ | ✅ | ✅ |
| Warranty claims workflow | ❌ | ✅ | ✅ |
| AI email templates | ❌ | ✅ | ✅ |
| Invoice email tracking | ❌ | ✅ | ✅ |
| Competition pool | ❌ | ❌ | ✅ |
| Per-customer warranty overrides | ❌ | ❌ | ✅ |
| Google Business API | ❌ | ❌ | ✅ |

**When:** Before any new feature ships to production. Reference from all proposals.

> **Implemented** as `docs/PRICING_TIERS.md`. Reference added to `docs/proposals/README.md` under "Platform Reference Documents".

---

### 18. External API Client Registry
**Problem:** Multiple proposals add LLM/Google API calls with independent implementations.

**Plan:** Build `common/external_api.py` with:
- Consistent timeout handling (default 10s)
- Error logging with cost tracking
- Provider switching (Claude Haiku ↔ Gemini Flash)
- Daily cost accumulator per tenant

**When:** When the second external API feature ships (first one can be standalone).

---

### 19. Management Command Registry ✅ DONE
**Problem:** Cron jobs accumulating without centralized documentation.

**Plan:** Update `docs/deployment/PRODUCTION_CHECKLIST.md` with a management command table.

> **Implemented** in `docs/deployment/PRODUCTION_CHECKLIST.md` (v1.2). Full registry added with four sections:
> - **Scheduled (EB Cron)** — `process_batch_invoices`, `process_overdue_invoices`, `generate_aging_report`, `check_subscription_alerts`
> - **Loyalty commands pending cron** — `expire_loyalty_points` (midnight), `reconcile_loyalty_balances` (3am) — implemented, need adding to `.ebextensions`
> - **On-demand commands** — 10 commands with flags documented
> - **Maintenance-only** — 4 one-time commands
> - **Adding a new command checklist** — 6-step guide for future additions

| Command | Schedule | Purpose |
|---------|----------|---------|
| `check_subscription_alerts` | Daily 9am UTC | Subscription expiry emails |
| `process_batch_invoices` | Daily 6am UTC | Auto-generate batch invoices |
| `process_overdue_invoices` | Daily 8am UTC | Mark overdue, send reminders |
| `expire_loyalty_points` | Daily midnight UTC | Expire points past expiry date |
| `reconcile_loyalty_balances` | Daily 3am UTC | Verify Reward.points matches ledger |
| `generate_aging_report` | Daily 9am UTC | Aging report cache refresh |
| `purge_deleted_records` | Manual / weekly | Hard-purge soft-deleted records older than 30d |

---

## Priority Order

If building all of these, the recommended sequence:

1. **Fix proposal bugs** (§1-4) — 30 minutes, prevents building on broken specs
2. **Tier matrix** (§17) — 1 hour, prevents pricing inconsistencies across features
3. **Warranty system** (§6) — 3-4 days, biggest feature gap for real shops
4. **Review request system** (§7) — 2-3 days, drives Google ranking
5. **Repair completion orchestrator** (§15) — 1 hour, needed before warranty + reviews ship
6. **TenantConfig base class** (§16) — 30 minutes, clean up pattern
7. **Loyalty Phase 2** (§5) — 2-3 days, engagement hooks + liability report
8. **Website widget** (§8) — rescoped Phase 1: 3-4 days
9. **Everything else** — prioritize based on customer feedback

---

*This document turns suggestions into actions. Each item has a clear "when" and "what." Review with Drake before starting any build work.*
