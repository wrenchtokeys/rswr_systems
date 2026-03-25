# Implementation Plan — Addressing Suggestions

**Author:** Amelia  
**Date:** 2026-03-25  
**Reference:** [`suggestions.md`](./suggestions.md)  
**Purpose:** Concrete plan for implementing each suggestion from the proposals review, organized by when to do it.

---

## Immediate Fixes (Fix Now — Bugs in Proposals)

These are errors in the proposals that need correcting before any implementation begins.

### 1. Review Request: `queue_status_history_contains()` doesn't exist
**Ref:** [suggestions.md §5](#5-review-request-system-draft) — "method call will raise AttributeError at runtime"

**Fix:** Replace `repair.queue_status_history_contains('DENIED')` with a check against actual data. Two options:
- **Option A (simple):** Check `repair.queue_status == 'DENIED'` — only catches currently-denied repairs, not ones that were denied and later re-requested
- **Option B (better):** Check `TechnicianNotification.objects.filter(repair=repair, notification_type='repair_denied').exists()` — catches any repair that was ever denied

**Plan:** Fix in `review-request-system.md` before building. Use Option B.

---

### 2. Warranty: `applies_to` choices don't match Repair damage types
**Ref:** [suggestions.md §4](#4-warranty-system-draft) — "silently breaks... always fall through to all_repairs default"

**Fix:** Change `WarrantyPolicy.APPLIES_TO_CHOICES` to match `Repair.DAMAGE_TYPE_CHOICES` exactly:
```python
# Current (wrong):  'chip', 'crack', 'star_break', 'bulls_eye'
# Correct (match):  'Chip', 'Crack', 'Star Break', "Bull's Eye"
```

**Plan:** Fix in `warranty-system.md` before building. Pull choices directly from `Repair.DAMAGE_TYPE_CHOICES` to prevent future drift.

---

### 3. Reward Redemption UX: Wrong status filter
**Ref:** [suggestions.md §10](#10-reward-redemption-ux-overhaul-draft) — "FULFILLED implies the redemption is already complete"

**Fix:** Change "Show only FULFILLED, unapplied monetary redemptions" → "Show only APPROVED, unapplied monetary redemptions."

**Plan:** Fix in `reward-redemption-ux-overhaul.md`.

---

### 4. AI Plan Recommendation: Projection math bug
**Ref:** [suggestions.md §8](#8-ai-plan-recommendation-draft) — "underestimates throughput for shops that ramped up"

**Fix:** Change denominator from `trial_days` to `min(trial_days, 30)`:
```python
sample_days = min(trial_days, 30)
projected_monthly_repairs = (stats['monthly_repairs'] / sample_days) * 30
```

Also fix: Stripe Connect → Enterprise recommendation is too aggressive. Move to Pro signal, not Enterprise.

Also fix: Enterprise threshold uses 50 customers (Starter limit), not Pro limit. Align thresholds to actual plan limits.

**Plan:** Fix all three issues in `ai-plan-recommendation.md`.

---

## Build With Feature (Implement When Building Each Feature)

### 5. Loyalty System — Phases 2-4 improvements
**Ref:** [suggestions.md §3](#3-loyalty-system-overhaul-phase-1-shipped)

| Suggestion | Plan | When |
|-----------|------|------|
| Review bonus fraud — tie to Review Request `status='reviewed'`, not a self-serve button | Wire into ReviewRequestService when both are built | Phase 2 |
| `select_for_update()` on balance reads | ✅ Already implemented in LOYALTY-001 (CODE-165 pattern) | Done |
| `reconcile_balance()` nightly management command | Add `reconcile_loyalty_balances` command, run daily via cron | Phase 2 |
| Move liability report from Phase 4 → Phase 2 | Agree — shops need to see outstanding points before scaling the program | Phase 2 |
| Default expiry 365 → 730 days (or never) | Drake decided 365 days. Keep as-is unless he changes his mind | N/A |
| Backfill migration note about synthetic data | Add comment to migration noting records are synthetic, not real transactions | Next commit |

---

### 6. Warranty System improvements
**Ref:** [suggestions.md §4](#4-warranty-system-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Fix `applies_to` choices (see §2 above) | Pull from `Repair.DAMAGE_TYPE_CHOICES` | Before build |
| Per-customer warranty overrides → Phase 2 not Phase 3 | Agree — add nullable `customer` FK to `WarrantyPolicy` in Phase 1 migration, build UI in Phase 2 | Phase 1 migration, Phase 2 UI |
| Soft-deleted original repair → show "Original repair (deleted)" | Add check for `warranty_original_repair` existence in template | Phase 1 |
| Goodwill repair flag (out-of-warranty courtesy repairs) | Add `is_goodwill_repair` boolean to Repair, separate from warranty claim | Phase 1 |
| Warranty badge on repair list view (not just detail) | Add ✅W / ⌛W / ❌W badge to repair list table | Phase 1 |
| Warranty terms on invoice PDF → Phase 1 minimum | Add one line to invoice template: "WARRANTY: [terms from policy]" | Phase 1 |
| Cache `get_warranty_stats()` or use management command | Use management command + cached results, not on-demand in dashboard view | Phase 2 |

---

### 7. Review Request System improvements
**Ref:** [suggestions.md §5](#5-review-request-system-draft)

| Suggestion | Plan | When |
|-----------|------|------|
| Fix `queue_status_history_contains` (see §1 above) | Use notification existence check | Before build |
| Non-deterministic `CustomerUser.first()` fallback | Change to `.filter(is_primary_contact=True)` with no fallback. If no primary, skip. | Phase 1 |
| Customer opt-out / unsubscribe | Add `review_opt_out` boolean on CustomerUser. Unsubscribe link in every review email. CAN-SPAM compliance. | Phase 1 |
| Document that `'reviewed'` status is a black box until Google API | Add note to proposal and code comments | Phase 1 |
| Connect to loyalty system — confirmed review triggers points | When review `status='reviewed'` (via Google API Phase 3), call `LoyaltyService.award_points()` | Phase 3 |
| Add `send_review_requests` to cron.yaml | Add alongside existing management commands | Phase 1 |

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

### 15. Repair Completion Hook Orchestrator
**Problem:** 4+ services all triggering independently on `Repair.save()` COMPLETED transition.

**Plan:**
```python
# In Repair.save() or post_save signal:
post_completion_hooks(self)

# Orchestrator (new file: apps/technician_portal/hooks.py)
def post_completion_hooks(repair):
    hooks = [
        ('loyalty', LoyaltyService.award_completion_points),
        ('warranty', WarrantyService.set_warranty_on_completion),
        ('reviews', ReviewRequestService.on_repair_completed),
    ]
    for name, hook in hooks:
        try:
            hook(repair)
        except Exception as e:
            logger.error(f"Post-completion hook '{name}' failed for repair {repair.pk}: {e}", exc_info=True)
```

**When:** Build when the second hook (warranty or reviews) ships. Currently only loyalty is hooked in — one hook doesn't need an orchestrator.

---

### 16. TenantConfig Abstract Base Class
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

---

### 17. Feature-to-Plan Tier Matrix
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

### 19. Management Command Registry
**Problem:** Cron jobs accumulating without centralized documentation.

**Plan:** Update `docs/deployment/PRODUCTION_CHECKLIST.md` with a management command table:

| Command | Schedule | Purpose |
|---------|----------|---------|
| `check_subscription_alerts` | Daily 8am | Subscription expiry emails |
| `process_batch_invoices` | Daily | Auto-generate batch invoices |
| `process_overdue_invoices` | Daily | Mark overdue, send reminders |
| `send_review_requests` | Every 30min | Send queued review request emails |
| `expire_loyalty_points` | Daily midnight | Expire points past expiry date |
| `reconcile_loyalty_balances` | Daily 3am | Verify Reward.points matches ledger |
| `generate_aging_report` | Weekly Monday | Aging report cache refresh |

**When:** Next deployment doc update. Add each new command as features ship.

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
