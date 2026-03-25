# Proposal Suggestions & Analysis

**Author:** Amelia (self-review)
**Date:** 2026-03-24
**Purpose:** Honest assessment of every proposal in this directory — what works, what doesn't, what could be better, and how each fits into the RS Systems platform as a whole.

---

## How to Read This Document

Each section covers one proposal with four angles:

- **What I like** — the strong parts, worth preserving
- **What I'd reconsider** — real concerns, not nitpicks
- **How to improve it** — concrete suggestions
- **Integration notes** — how it connects to the rest of the system

Shipped proposals are reviewed for historical completeness. Draft proposals get the most critical attention.

---

## Table of Contents

1. [Stripe Connect Multi-Tenant Payments](#1-stripe-connect-multi-tenant-payments-shipped)
2. [Stripe Connect Implementation Plan](#2-stripe-connect-implementation-plan-shipped)
3. [Loyalty System Overhaul](#3-loyalty-system-overhaul-phase-1-shipped)
4. [Warranty System](#4-warranty-system-draft)
5. [Review Request System](#5-review-request-system-draft)
6. [Website Integration Widget](#6-website-integration-widget-draft)
7. [Repair Form Efficiency](#7-repair-form-efficiency-draft)
8. [AI Plan Recommendation](#8-ai-plan-recommendation-draft)
9. [Customer Billing Preferences UX](#9-customer-billing-preferences-ux-draft)
10. [Reward Redemption UX Overhaul](#10-reward-redemption-ux-overhaul-draft)
11. [Invoice Email Tracking](#11-invoice-email-tracking-draft)
12. [AI Email Template Assistant](#12-ai-email-template-assistant-draft)
13. [Competition Pool](#13-competition-pool-future)
14. [Cross-Cutting Themes](#14-cross-cutting-themes)

---

## 1. Stripe Connect Multi-Tenant Payments (Shipped)

**Status:** ✅ SHIPPED — superseded by the implementation plan below.

### What I Like

The problem statement is concise and exactly right: all customer invoice payments flowing to Drake's account is a blocker for scaling to other shops. The comparison of three account types (Standard / Express / Custom) with a clear recommendation for Express was useful for a quick decision. The fee structure table covering four options gave Drake a concrete set of choices rather than an abstract "you should decide."

### What I'd Reconsider

The `transfer_data.destination` approach described here (destination transfer) was later replaced with the direct charges approach in the implementation plan. Destination transfers and direct charges have materially different liability and refund mechanics. The final implementation was the right call — this doc's approach would have been harder to refund without `reverse_transfer`. For future reference: always prefer direct charges + application fee over destination transfers when the platform controls the customer relationship.

### How It Could Be Improved

Even though shipped and superseded, this doc should add a one-line note pointing to the implementation plan and explaining *why* direct charges were chosen over destination transfers. Future Amelia reading this history might otherwise wonder why the approach changed.

### Integration Notes

N/A — superseded. The implementation plan is the canonical reference.

---

## 2. Stripe Connect Implementation Plan (Shipped)

**Status:** ✅ SHIPPED — Phases 1-2 live.

### What I Like

The "No KYC = No Online Payments" section is the best part of this document. Having a clear, named principle with four explicit enforcement points prevents the half-baked state where the UI hides a button but the backend still accepts the request. The belt-and-suspenders approach (webhook keeps state fresh, API call is the gate at checkout session creation) is exactly right for payment infrastructure where a silent failure is unacceptable.

The edge case coverage is excellent: account disconnection, restricted accounts mid-invoice, refund handling with `reverse_transfer=True`, race conditions at checkout session creation. Each one explains *why* the solution works, not just what it does.

The fee calculation using integer cents to avoid floating-point issues is a detail that reflects real payment engineering experience. Many implementations get this wrong.

### What I'd Reconsider

The `PlatformConfig` singleton model is heavier than it needs to be. It holds two fields (`default_fee_percent` and `competition_pool_fee_percent`) that are currently both 0%. A Django admin-configurable `SiteConfig` singleton or even a `django-constance`-style approach would be lighter. As the platform grows and more global settings accumulate, a proper settings framework is better than adding fields to a singleton model.

One gap: what happens when the Stripe API call itself fails during checkout session creation? The proposal says "API call is the gate" but doesn't specify the fallback behavior. If `stripe.Account.retrieve()` returns a 503, should we show an error page or degrade to "payment unavailable"? Degrading gracefully (showing "contact shop for payment options") is better than a crash.

### How It Could Be Improved

Add explicit handling for the "Stripe API timeout" case in Phase 2's implementation points. The current code path assumes `stripe_account_id` is reliably current from webhooks, which is usually true but not guaranteed. A 5-minute cache on the Connect status check with `stripe.Account.retrieve()` as a refresh fallback would make this bulletproof.

Phase 3's fee dashboard should include a running total of platform fees YTD — useful for understanding the business's payment revenue vs subscription revenue split.

### Integration Notes

The `PlatformConfig.competition_pool_enabled` field referenced here creates a direct dependency on the Competition Pool proposal. Since Competition Pool is firmly in "future" status, this field should either be removed from the shipped code or explicitly gated behind a feature flag so it doesn't confuse future developers.

---

## 3. Loyalty System Overhaul (Phase 1 Shipped)

**Status:** 🚧 Phase 1 SHIPPED — Phases 2-4 pending.

### What I Like

This is the most architecturally ambitious proposal in the set, and it's well-founded. The immutable ledger approach for `PointTransaction` is the right call — it mirrors how every financial system treats money, and loyalty points are effectively a micro-currency. The cached balance on `Reward.points` for fast reads while the ledger provides the audit trail is a classic CQRS-lite pattern and is appropriate here.

The competitive landscape table showing that no glass shop SaaS has tiers, configurable points, or a customer dashboard is compelling. If this is accurate, it's a genuine differentiator.

Using lifetime points for tier calculation (not current balance) so that spending points doesn't demote you is exactly right. Penalizing customers for using rewards would undermine the whole program.

The phased implementation (Foundation → Engagement → Tiers → Dashboard) is sensible. Phases are genuinely separable, and Phase 1 is backwards-compatible with existing behavior.

### What I'd Reconsider

**Backfill migration quality.** The proposal says Phase 1 includes "a migration that creates PointTransaction records from existing Reward.points balances." But there's no way to know *how* those points were earned — the transaction type would have to be a generic `'historical'` entry. The backfill creates an audit trail that looks authoritative but is actually synthetic. This is worth noting clearly so future analysis doesn't treat backfilled records as equivalent to real transaction data.

**Review bonus fraud risk.** Phase 2 includes "Leave a review → 100 points." The proposal lists this as a "new endpoint" but doesn't specify how the system verifies that a review was actually left. If it's just a "claim your points" button after submitting a review request, it's trivially gameable — customers could click it without leaving a review. This needs to be either:
- Tied to the Review Request system marking a request as `'reviewed'`, or
- A one-time manual process (owner awards points after seeing the review), or
- Verified via Google Business API (Phase 3 of the review proposal)

The current design leaves a $100 point exploitable loophole for every customer.

**Race condition on balance update.** The `@transaction.atomic` decorator on `LoyaltyService.award_points()` is necessary but may not be sufficient under high concurrency. The balance update reads `Reward.points`, adds `amount`, and saves. If two transactions run simultaneously (e.g., batch processing completing multiple repairs at once for the same customer), both could read the same starting balance and both write conflicting values. The fix is `Reward.objects.select_for_update().get(customer_user=...)` inside the atomic block to acquire a row-level lock before reading the balance.

### How It Could Be Improved

Add a `reconcile_balance()` method to `LoyaltyService` that recomputes `Reward.points` from the sum of all `PointTransaction.amount` for a customer and flags discrepancies. This would be a nightly management command that catches any drift from bugs or direct database edits. Essential for a financial-grade feature.

The `LoyaltyConfig.points_expiry_days = 365` default means all points expire annually. For fleet customers who earn slowly (one repair per truck per quarter), 365 days is tight. Consider defaulting to 730 days (2 years) or making it `Never` by default, letting shops opt into expiration rather than having to remember to set it to 0.

Phase 4's "point liability report" should move to Phase 2. Shops need to understand their outstanding liability before they can have an informed conversation with customers about the program.

### Integration Notes

The repair completion hook in `Repair.save()` now triggers:
1. Loyalty points (Phase 1, exists)
2. Review request (Phase 1 of that proposal)
3. Warranty calculation (Phase 1 of that proposal)
4. Tax calculation (existing, via `TaxService`)

That's four service calls on a single `Repair.save()`. If any one throws an exception, it should not roll back the save. These hooks need to be wrapped in `try/except` with error logging, not hard failures. Consider a post-save signal pattern or an explicit `post_completion_hooks(repair)` orchestrator method that catches and logs each hook independently.

---

## 4. Warranty System (Draft)

### What I Like

The problem statement is concrete and operational: shop owners don't have a quick way to confirm warranty status when a customer calls back. The "look unprofessional" framing is exactly the right way to think about this — it's not just a data problem, it's a trust problem.

The `WarrantyPolicy` model with `applies_to` per-damage-type and a fallback to `all_repairs` is elegant. It mirrors how shops actually think about warranties (chips get lifetime, cracks get 1 year) while giving shops an escape hatch if they want a simpler blanket policy.

The `create_warranty_claim()` method with `cost_override=Decimal('0.00')` and `override_reason` is the right way to integrate with progressive pricing — it bypasses the pricing calculation cleanly without hacking the pricing service.

The integration notes are the strongest part of this proposal. The explicit callouts that warranty claims should NOT award loyalty points and should NOT trigger review requests show that these systems have been thought about together, not in isolation.

### What I'd Reconsider

**Damage type coupling.** The `applies_to` choices in `WarrantyPolicy` hardcode a list of damage types: `chip`, `crack`, `star_break`, `bulls_eye`, `combination`, `half_moon`, `replacement`, `all_repairs`. If the existing `Repair` model uses different identifiers for damage types (e.g., `CHIP`, `CRACK`, `STAR_BREAK` in uppercase), this silently breaks — the `WarrantyService.set_warranty_on_completion()` lookup on `applies_to=repair.damage_type` would always fall through to the `all_repairs` default without anyone noticing. Before implementing this, verify the exact values of `Repair.DAMAGE_TYPE_CHOICES` in the existing model and match them precisely.

**Per-customer warranty overrides in Phase 3.** This is buried in "future" but it's a real need for fleet customers. A fleet manager with 200 trucks should be able to negotiate a 2-year warranty for their account. Moving this to Phase 2 is worth considering, since it's the same data model work (adding a `ForeignKey(Customer)` nullable field to `WarrantyPolicy`) and the user story is compelling.

**Soft-delete interaction.** RS Systems has a 30-day restore window for soft-deleted repairs. What happens when the original repair in a warranty claim gets soft-deleted? The `warranty_original_repair = ForeignKey('self', on_delete=models.SET_NULL)` handles the FK, but the warranty claim detail view will show "Original repair: —" with no explanation. This should show "Original repair (deleted)" instead of just a blank.

**Out-of-warranty goodwill claims.** The proposal handles the in-warranty case well but the out-of-warranty case just says "shop can offer a goodwill discount." This should be a first-class concept — a "Goodwill Repair" flag that creates a repair with a discount note but not a full warranty claim. Shops frequently want to honor repairs slightly outside warranty as a customer retention gesture without creating a false warranty record.

### How It Could Be Improved

Add a **warranty status badge to the repair list view** (technician portal), not just the detail view. Techs often scan the list to find a specific truck. Showing ✅ W (warranty) or ⌛ W (expiring in 30 days) at a glance saves a click.

The **warranty certificate PDF** mentioned in Phase 3 should surface in Phase 1 as a minimum — even just adding "WARRANTY: [terms]" to the existing invoice PDF. Customers expect written proof of warranty. This is a one-line addition to the invoice template.

The `WarrantyService.get_warranty_stats()` method should be extracted to a management command or scheduled analytics call, not run on-demand in the dashboard view. For shops with thousands of repairs, this query could be slow if called on every dashboard load.

### Integration Notes

The website widget proposal explicitly mentions "customers could submit warranty requests through website widget." This creates a new inbound warranty path: anonymous person submits "my repair failed" through the shop's website → `WebsiteSubmission` created → shop reviews → creates warranty claim. This flow is worth designing explicitly — the `WebsiteSubmission` model needs a `submission_type` field that includes `warranty_claim` as an option.

---

## 5. Review Request System (Draft)

### What I Like

This is one of the strongest proposals in the set. The smart throttling rules differentiated by customer type (one-time retail / repeat individual / fleet) show a real understanding of how glass shop customer relationships work. Sending a review request to a fleet manager after every truck repair would get the entire domain blocked — the 180-day fleet cooldown is exactly right.

The timing logic — 2-hour delay, business hours only, timezone-aware — is the kind of thoughtful detail that separates a good email automation from an annoying one. A review request at 2am is worse than no request at all.

The review request status flow (`pending → sent → clicked → reviewed / skipped / suppressed`) is clean and covers every state. The `suppressed` status for negative experiences (DENIED repair, dispute) is smart — you should never ask a frustrated customer for a public review.

The flywheel narrative connecting website widget → repair completion → review request → better Google ranking → more widget submissions is genuinely compelling and shows that these features are designed as a system, not isolated features.

### What I'd Reconsider

**`queue_status_history_contains('DENIED')` doesn't exist.** The `ReviewRequestService.on_repair_completed()` method on line 165 calls `repair.queue_status_history_contains('DENIED')`. The `Repair` model has a `queue_status` CharField, not a status history field. Unless a separate audit log or status history table exists that I'm not aware of, this method call will raise `AttributeError` at runtime. The intent is correct — don't ask customers who had a repair denied — but the implementation needs to use whatever mechanism actually tracks status history (audit log, a `RepairStatusHistory` model, or simply checking if any `TechnicianNotification` with type `repair_denied` exists for this repair's customer).

**Review request sent to `customer_user.user.email` — but what if there's no portal account?** The logic correctly returns `None` if no `CustomerUser` exists. But fleet customers with many trucks often have *multiple* contacts. Should the review request go to the primary contact only, or to all contacts? The service says "For fleets: primary contact only" but the fallback is `CustomerUser.objects.filter(customer=customer).first()` — which is non-deterministic ordering. This should be `.filter(is_primary_contact=True)` with no fallback, or a deterministic fallback (oldest account, or the one who approved the repair).

**Confirmed reviews are a black box.** The `'reviewed'` status is mentioned but there's no automatic path to reach it — it requires either the Google Business API integration (Phase 3) or a manual admin action. This means the "already reviewed" check (`ReviewRequest.objects.filter(status='reviewed')`) will almost never return `True` in practice (since no one is manually marking reviews). The throttling rules will fall back to the cooldown check instead, which means repeat review requests will go out until the Google API is integrated. This is probably fine, but it should be documented so the behavior isn't surprising.

### How It Could Be Improved

Add a `customer_opted_out = BooleanField` field to the `ReviewConfig` model or a separate customer-level preference. Right now there's no way for a customer to opt out of review requests. Every email should have an unsubscribe link, and that unsubscribe should set a `suppressed` status on future requests for that customer. This is also a CAN-SPAM compliance requirement.

The `ReviewConfig.email_subject` default is "How was your experience with {shop_name}?" — this is fine but shops who use the AI Email Template Assistant (another proposal) should be able to run that same AI generation on review request emails. Cross-referencing these proposals: the AI assistant should cover review request templates, not just invoice templates.

**Extend tracking to the loyalty system.** If the loyalty proposal awards 100 points for leaving a review, the review request system should be the authoritative source of truth on whether a review was left. When the Google Business API is integrated in Phase 3, a confirmed review (`status='reviewed'`) should trigger `LoyaltyService.award_points()`. This closes the loop between the two systems.

### Integration Notes

The `send_review_requests` management command should be added to `cron.yaml` alongside `process_batch_invoices` and `check_subscription_alerts`. The click tracking redirect endpoint (`/r/<request_id>/<repair_id>/`) needs to be added to `rs_systems/urls.py` at the root level, not under `/billing/` or `/app/`, since it's a public URL that needs to work without authentication.

---

## 6. Website Integration Widget (Draft)

### What I Like

The "dogfooding plan" is the best part of this proposal. Testing Phase 1 exclusively on Rockstar Windshield Repair's own website before releasing it to other shops is the right instinct — it forces real-world validation before the feature becomes someone else's problem. Too many SaaS features ship to customers before the team has used them daily.

The business case is strong: website integration creates high switching costs. Once a shop's lead pipeline flows through RS Systems, migrating away means rebuilding that integration elsewhere. The "Powered by RS Systems" footer link as a distribution play is clever — low-friction advertising on every shop's website.

The "zero double entry" promise is the right headline feature. Manual re-entry of website leads is a real daily pain for small shop owners.

### What I'd Reconsider

**iframe vs shadow DOM — commit to one.** The proposal says "renders an iframe or shadow DOM form." These are fundamentally different architectures. An iframe is much simpler to build and provides CSS isolation automatically, but has two problems: auto-sizing height requires cross-origin `postMessage` communication, and some website builders block iframes. Shadow DOM integrates better visually but leaks shop-specific CSS in unpredictable ways. For a v1, iframe is the right choice — simpler, more isolated, known quantity. Pick iframe explicitly.

**Tenant slug in the script tag is public.** `data-tenant="rockstar-wr"` is visible to anyone who views the source of any page the widget is on. That's fine for identifying the tenant, but the submit endpoint `POST /api/widget/submit/` must validate that the submitted data actually comes from a reasonable source (not just that the slug exists). Rate limiting per IP is necessary but not sufficient — a targeted attacker could flood a specific shop with fake leads using residential proxies. Consider adding a `widget_token` (per-tenant, rotatable GUID) that must match on submission. This is different from the tenant slug — it's a secret that only the shop's website has. Add "Regenerate Widget Token" to the settings UI.

**Customer auto-match by email/phone is risky.** The proposal mentions matching incoming submissions to existing customers by phone/email. This could silently merge a new lead with an unrelated existing account if someone happens to share an email address (common in fleet scenarios — dispatcher@company.com might be used by multiple contacts). The safer default is: create a new `WebsiteSubmission` always, then let the owner manually link or merge to an existing customer. Auto-match should be a Phase 2 decision after seeing real data.

### How It Could Be Improved

The `WebsiteSubmission.status` choices (`new / contacted / quoted / scheduled / won / lost`) are a mini-CRM pipeline. This is a significant scope expansion beyond "quote form." The "Lead Queue" dashboard tab, response time tracking, and conversion metrics in Phase 1 are ambitious for a one-week estimate. I'd suggest splitting:
- **Phase 1 (1 week):** Submit endpoint, `WebsiteSubmission` model, owner notification, customer confirmation, simple "New Leads" list in dashboard (no pipeline stages yet)
- **Phase 2 (1 week):** Widget JS, branding, setup instructions
- **Phase 3 (1-2 weeks):** Pipeline stages, conversion metrics, response time SLAs

The current Phase 1 attempts too much simultaneously.

Add a **spam score field** to `WebsiteSubmission`. Run basic heuristics on every submission (all-caps name, disposable email domain, phone number format, submission speed). Flag high-scoring submissions so the owner can review before the customer auto-confirm email fires. Nobody wants to auto-email spam.

### Integration Notes

The warranty system proposal explicitly mentions website widget as a channel for warranty requests. The `WebsiteSubmission` model should have a `submission_type` field: `quote_request`, `warranty_claim`, `general_inquiry`. This lets the system route different types appropriately and sets up the warranty integration path.

The website widget creates customers and repairs through an external API without authentication. All the same tenant isolation rules apply — the widget backend must never let a submission for Tenant A create records in Tenant B's data. This might seem obvious but deserves an explicit test: `test_widget_submit_cross_tenant_isolation`.

---

## 7. Repair Form Efficiency (Draft)

### What I Like

The scope of this proposal is appropriately ambitious — the repair form is the most-used interface in the entire system, so even small friction reductions compound quickly. The 12+7+5 ideas are well-structured with honest effort and risk estimates for each.

The phase ordering is excellent. Phase 1 (Save & New, Smart Defaults, Reorder Fields, Collapsible Sections) can be done in 1-2 days and would noticeably reduce friction for every tech, every day. These should be the highest-priority items in the set.

The success metrics section at the end is the best part of any efficiency-focused proposal. "Time to log a repair under 30 seconds for quick mode, under 60 seconds for full" gives a concrete benchmark for evaluating whether the changes worked. Form analytics (#X1) would let us measure against this target.

### What I'd Reconsider

**#6 Auto-fill Temperature from weather — wrong location model.** The proposal suggests using shop address or geolocation to prefetch ambient temperature. But windshield techs are *mobile* — they drive to fleet yards, parking lots, and customer sites that may be 30+ miles from the shop. The shop's address is almost certainly the wrong location to use. Browser geolocation is the right source, but it adds a permission prompt on a mobile device that some techs will deny. The proposal correctly notes that windshield temperature in direct sun can be 20-40°F above ambient, making auto-fill misleading anyway. I'd drop this feature or move it firmly to Phase 4. The cost-benefit doesn't justify the implementation complexity.

**#12 Offline Mode — underestimated complexity.** The proposal correctly flags this as "high complexity" and "v3.0," but it may be underselling the scope. A service worker + IndexedDB offline queue for a form that creates customers, assigns repairs, uploads photos, and calculates progressive pricing across tenant boundaries is not a standard offline-first implementation. The real solution here might be a native mobile app (React Native or Flutter) rather than a PWA, since native apps have better offline storage primitives. This should be a separate, standalone proposal rather than idea #12 in a form efficiency doc.

**M4 Live Break Counter + Summary Bar is too valuable to leave in Phase 2.** A sticky bar showing "4 breaks · $180 total · [Submit All]" is pure CSS/JS, zero risk, and directly addresses the problem of techs not knowing the running total as they add breaks. This should be in Phase 1.

### How It Could Be Improved

**Add a "last modified by" indicator to the repair detail view.** This isn't a form proposal per se, but it's related: when the repair form is improved for speed, more edits will happen more quickly. It becomes important to know whether a status change was made by the tech, the manager, or the system. A simple "last modified by [name] at [time]" line on the detail view provides this without a full audit log.

**#8 Unit Number Autocomplete should fetch recently used units, not all units.** For fleet customers with 500 trucks, showing all 500 in an autocomplete is overwhelming and slow. The suggestion should be limited to: (a) the last 10 units repaired for this customer, plus (b) fuzzy match on what's typed. This makes the autocomplete faster and more relevant.

**Consider a progressive enhancement strategy.** Rather than reworking the entire form layout at once, the Reorder Fields (#7) and Collapsible Sections (#3) changes can be done with Tailwind CSS classes and Alpine.js (if that's in the stack) or minimal vanilla JS. If these changes are done in a way that's reversible via a feature flag or settings toggle, we can A/B test them against the current layout to verify the improvement before committing.

### Integration Notes

Form analytics (#X1) should be the first cross-cutting change made before any other form changes. Without baseline measurements, we can't prove whether Phase 1 or Phase 2 improvements actually reduced form completion time. The analytics endpoint can be a simple `POST /api/analytics/form-event/` that logs `{form_type, event, duration_ms}` — lightweight and non-blocking.

The multi-break form's M4 (sticky summary bar) would naturally show progressive pricing: "Break 1: $50, Break 2: $40, Break 3: $35." This makes the pricing visible to techs, which could surface confusion or questions from fleet customers about why prices drop. The tech should be prepared to explain progressive pricing. Consider adding a small "?" tooltip explaining the pricing model.

---

## 8. AI Plan Recommendation (Draft)

### What I Like

The rule-based first approach is exactly right. Building a recommendation engine that runs without any external API dependencies means Phase 1 can ship the same day it's written, costs zero, and has no infrastructure failure modes. The confidence levels (high/medium/low based on data volume) prevent the system from making authoritative-sounding recommendations when it has too little data to be meaningful.

The four placement points (billing page badge, day 20 nudge email, trial expiry email, owner dashboard banner) cover the right moments in the conversion funnel. A nudge at day 20 catches people before they're in the "ignore it until it expires" mindset.

### What I'd Reconsider

**Projection math has a latent bug.** The recommendation logic:
```python
trial_days = (now() - tenant.trial_started_at).days or 1
projected_monthly_repairs = (stats['monthly_repairs'] / trial_days) * 30
```

`stats['monthly_repairs']` is filtered to `completed_at__gte=now() - timedelta(days=30)`. If a shop is on day 45 of their trial, `trial_days=45` but `monthly_repairs` only reflects the last 30 days. The projection would be `(last_30_days_repairs / 45) * 30`, which underestimates throughput for shops that ramped up after their first two weeks. The correct formula should use `min(trial_days, 30)` as the denominator:

```python
sample_days = min(trial_days, 30)
projected_monthly_repairs = (stats['monthly_repairs'] / sample_days) * 30
```

**Stripe Connect → Enterprise recommendation is too aggressive.** The current logic: if `stats['uses_connect']`, recommend Enterprise. But Stripe Connect is available to all shops. A shop with 2 techs and 20 repairs/month who set up Stripe Connect would be pushed to Enterprise ($249/month) when they clearly only need Starter ($49/month). Remove this signal or move it to Pro (which makes more sense — shops actively processing online payments are doing meaningful volume).

**The Enterprise and Pro thresholds don't match the actual plan limits.** From the README: Starter = 200 repairs/month, 5 techs, 50 customers. Pro = unlimited repairs, 15 techs. The current logic recommends Enterprise for shops with `stats['customers'] > 50`, but that's the Starter limit — hitting it means they need Pro, not Enterprise. The thresholds need to match the actual plan limits precisely, or recommendations will be off.

### How It Could Be Improved

Add a "how we calculated this" disclosure to the recommendation. Something like:
> "Based on 3 technicians, 34 repairs in the last 30 days, and active invoicing — we think Pro is your best fit."

This turns the recommendation from a black box into a transparent explanation. Shops that feel misclassified can understand why and either agree or disagree. It also prevents the "feels like a sales pitch" reaction.

Cache the recommendation per tenant per day. If the billing page is loaded 10 times by the same owner, there's no reason to recalculate usage stats 10 times. Store the recommendation + reason in the session or a lightweight model field with a 24-hour TTL.

### Integration Notes

The recommendation API endpoint `GET /api/tenants/plan-recommendation/` should be consistent with the existing DRF setup in `apps/tenants/`. The `usage_summary` response field gives a natural audit log of what data drove the recommendation — this is also useful for a future support conversation ("we recommended Pro because you had 180 repairs in your trial month").

---

## 9. Customer Billing Preferences UX (Draft)

### What I Like

This proposal is tightly scoped and directly solves a real friction point. The six-step problem (create → save → navigate → open settings → configure billing → optionally set pricing) is accurately described — I've noticed the same pattern. Making it 1-2 steps is the right goal.

Zero new models, zero migrations, collapsed by default: this is exactly the kind of proposal that should get approved quickly because the cost of being wrong is near-zero. If shops don't use the expanded section, it collapses and disappears. If they do use it, they save 5 minutes of setup per new customer.

The scope estimate (~80 lines total) is realistic. This is a disciplined proposal — it knows what it is and what it isn't.

### What I'd Reconsider

**The collapsed state and form submission interaction needs explicit testing.** In HTML, `<details>` / `<summary>` elements don't prevent their children from submitting when the form is posted — inputs inside a closed `<details>` still get submitted. This is correct behavior (fields should submit with defaults even when collapsed), but it means the view must handle the case where all billing fields are submitted empty. The view logic should treat empty `invoice_preference` as "use shop default" not "error" and should not create a `CustomerRepairPreference` record if nothing was explicitly set. This is a small but important nuance.

**Primary tech is already done via CODE-136 — remove it from the UI mockup.** The proposal lists "Primary tech: [Select... ▾]" in the collapsible section but notes it's already handled separately. Including it in the mockup and then saying "already done" creates confusion during implementation — which existing control handles this? Move it to a separate "What's already handled" section to avoid double-implementing.

### How It Could Be Improved

Consider pre-populating the "Payment terms" field with the shop's current default as the selected option, not just showing "Shop default" as a placeholder. "Shop default" is ambiguous — is the shop default Net 30 or COD? Showing the actual value (e.g., "Net 30 — shop default") makes the option concrete without requiring the owner to remember their own settings.

Add a small "💡 Most fleet customers prefer batch billing" tooltip or hint next to the Invoice preference field. This isn't prescriptive, but it gives new shop owners guidance based on common practice. The difference between batch billing and per-ticket affects cash flow timing and the fleet manager's workload — a hint helps owners who don't know which to pick.

### Integration Notes

This proposal's implementation in `create_customer()` view needs to run the same validation as the existing customer settings page. The `CustomerRepairPreference` and `CustomerPricing` models must be created with `tenant=request.tenant` — don't let the form skip this. The best approach is to extract a `CustomerPreferenceForm` that's used both on the creation form and the settings page, ensuring validation is consistent.

---

## 10. Reward Redemption UX Overhaul (Draft)

### What I Like

Splitting the redemption flow by reward type is the right architectural decision. Applying a 25% repair discount and scheduling a pizza party are fundamentally different actions — treating them the same creates a confusing flow for one of the two cases. The three-field migration (preferred_date, preferred_time, customer_notes) is clean, nullable, and zero-risk on existing data.

The "Alternative: apply at any time before invoicing" path (customer can apply a reward from their repair detail page, not just at request time) is worth including — it's more flexible and gives customers who forget at request time a second chance.

### What I'd Reconsider

**"FULFILLED, unapplied monetary redemptions" — I think this is the wrong status filter.** The proposal says to show "FULFILLED, unapplied monetary redemptions" on the repair request form. But `FULFILLED` in the redemption flow means the reward has already been delivered/applied. The intended filter should be `APPROVED` redemptions (approved by the shop but not yet applied to a specific repair). FULFILLED implies the redemption is already complete. Please clarify the intended status at this stage — the current wording would show already-used rewards as available to apply again.

**What happens to an applied reward if the repair is denied?** The proposal acknowledges this ("Reward stays on the redemption, can be re-applied") but doesn't specify the *user experience* of this scenario. The customer selected a reward when submitting, the tech denied the repair, and now the customer has an applied-but-useless reward sitting on a denied repair. The system needs to either:
- Auto-unapply the reward when a repair is denied, showing the customer "Your 25% off reward has been restored and can be used on your next repair"
- Or require a manual step (owner unapplies it)

Auto-unapply is the right answer. The view that handles repair denial should call a service method to restore the applied reward.

### How It Could Be Improved

The physical reward scheduling flow (Flow B) should include a **confirmation step from the shop's side**. Right now the customer schedules a date, but there's no mechanism for the shop to confirm or propose an alternative date. A simple status flow:
- Customer: `PENDING` → selects date → `SCHEDULED`
- Shop: can accept (`CONFIRMED`) or propose new date (`COUNTER_PROPOSED`)
- Customer: accepts counter → `CONFIRMED`

This prevents "the customer scheduled a pizza party on a day the shop is closed" situations. Even a simple "shop confirms" step without counter-proposal would prevent chaos.

### Integration Notes

The reward redemption UX overhaul and the loyalty system overhaul both touch redemption flows and should be built in the same sprint. Specifically: if a customer has an `APPROVED` monetary redemption (loyalty proposal) and applies it to a repair request (this proposal), the redemption status transition needs to be consistent between the two systems. The loyalty proposal's `LoyaltyService` and the redemption UX's view changes need to agree on what status transitions are valid.

---

## 11. Invoice Email Tracking (Draft)

### What I Like

The problem statement is pitch-perfect: "knowing that Penske opened your $4,200 invoice 3 times but hasn't paid is a completely different conversation." This is the right way to frame a feature — in terms of what the user can DO with the information, not what the system records.

The security design is solid: UUID4 token (not invoice ID), pixel endpoint with `Cache-Control: no-store` to prevent deduplication, click redirect validating against an allowlist, rate limit per token. These details prevent the obvious attack vectors.

The invoice activity timeline mockup is exactly what QuickBooks and FreshBooks show. The baseline feature request is "parity with what already exists elsewhere" — a low bar to clear.

### What I'd Reconsider

**IP address and user agent are PII under some regulations.** The `InvoiceEmailEvent` model stores `ip_address` (GenericIPAddressField) and `user_agent` (TextField). Under GDPR, if RS Systems has any EU customers, IP addresses are personal data. Under CCPA, they're personal information. The proposal should include a data retention policy for these fields: either don't store them at all (just log the event without IP/UA), or anonymize them (e.g., mask the last octet of the IP: `192.168.1.X`), or add a configurable retention period after which they're cleared. The most conservative approach (and the one requiring least legal review) is to hash the IP with a daily salt — this allows deduplication within a day without storing raw addresses.

**The blocking dependency on SendGrid is a real problem.** The proposal notes "SendGrid credits are currently exhausted — this feature ships whenever we have a working email provider." This is a significant asterisk. The core infrastructure change (switch from `EmailMessage` to `EmailMultiAlternatives`) should be done as a separate task that unblocks both this proposal and the AI Email Template Assistant. Once the email provider is sorted, both proposals are ready to go.

**Apple Mail Privacy Protection (MPP) false opens.** The proposal mentions this in the risk table, but it's worth being more explicit. Since iOS 15 (2021), Apple Mail pre-fetches pixels for all emails on Apple devices, marking them as "opened" even if the recipient never looked at the email. Given that many fleet dispatchers use iPhones, the open rate for this user base could be 100% false positives. The `user_agent` field is supposed to help filter known prefetch agents, but MPP uses Apple's servers (not the user's device), making filtering unreliable. The UI should explicitly label open events as "Possibly opened" and treat click events as the reliable signal.

### How It Could Be Improved

Phase 3's "auto-reminder triggers" based on email open status is the highest-value feature in this proposal and should be scoped more explicitly. "If not opened after 3 days, auto-send reminder" needs careful design:
- Should the shop be notified that a reminder was auto-sent (yes)?
- Should the reminder email also have tracking (yes, reuse the same infrastructure)?
- What's the max number of auto-reminders before stopping (configurable, suggest default of 2)?
- Does an auto-reminder reset the clock for the next auto-reminder?

This is a complete feature in itself. Add it as Phase 3 with a clear spec rather than a one-line bullet.

Add the `InvoiceEmailEvent.tenant` FK to the model's `indexes` in `Meta`. Tenant-scoped analytics queries ("how many invoices were opened this month for this tenant") will be slow without it, and this is a high-cardinality table that will grow quickly.

### Integration Notes

The click tracking redirect endpoint (`/billing/track/<uuid:token>/click/`) and the review request click tracking (`/r/<request_id>/<repair_id>/`) both solve the same problem — recording when a user clicks an outbound link from an email. These should share infrastructure. Consider a general-purpose `EmailClickTracker` service that both billing tracking and review request tracking use, rather than building two separate click-tracking systems.

---

## 12. AI Email Template Assistant (Draft)

### What I Like

The cost estimate is refreshingly specific and honest: ~$0.001 per generation, ~$3/month for 100 generations/day across all tenants. Many AI feature proposals handwave cost — this one does the math. At that price, this is essentially free, and the ROI from even one fewer awkward collection email per shop per month is dramatically positive.

The free vs. paid tier split (free tier = defaults only, paid tiers = AI generation) is a clean feature gate that doesn't feel arbitrary. It's the kind of feature that makes someone say "I should upgrade."

Phase 1's "fixed prompt template, no style input" is correctly scoped as the MVP. Get the generation working before adding the style controls.

### What I'd Reconsider

**`CODE-114 (customizable email templates)` — is this built?** The proposal says it "depends on CODE-114" but doesn't state whether that ticket exists or is complete. If shops can't customize email templates yet, this entire proposal has no UX surface to attach to. Check the current state of email template customization in `BillingConfig` before committing to this.

**The placeholder list in the LLM prompt doesn't match the actual system.** The example prompt lists `{customer_name}`, `{invoice_number}`, `{total}`, `{amount_due}`, `{due_date}`, `{days_overdue}`, `{company_name}`. These need to match exactly what `InvoiceEmailService` actually substitutes. If the real code uses `{{total}}` (double braces, Django template style) instead of `{total}` (f-string style), the AI will generate templates with the wrong syntax. The LLM prompt should be dynamically generated from the actual available placeholder registry, not hardcoded.

**Rate limiting mechanism is unspecified.** The proposal says "max 10 generations per tenant per day" but doesn't say how to enforce this. Using Django cache with a daily key (`f"ai_gen_{tenant.pk}_{today.isoformat()}"`) is the simplest approach. Using a database counter in `BillingConfig` is more auditable. Pick one and spec it, or the implementation will take shortcuts.

### How It Could Be Improved

Add a "Preview with sample data" button that takes the generated template and renders it with example values (customer_name = "EOS Trucking", invoice_number = "INV-1-20260320", etc.) before the owner saves. This is the most important UX feature for adoption — owners who can't picture what the email actually looks like won't use the feature. The preview rendering can be done client-side with simple string replacement.

Phase 3's "learn from edits" idea (stop suggesting phrases the owner consistently removes) is interesting but requires tracking edit diffs, which adds significant complexity. A simpler version: track which generated templates the owner uses as-is vs. significantly edits. High edit rates suggest the prompt needs tuning. Low edit rates suggest it's working. This telemetry can inform prompt improvement without building a full learning system.

Connect Phase 3 to the invoice email tracking proposal. If email tracking shows that invoices with custom templates have higher payment rates than default templates, that's a compelling data point for conversion. "Shops using AI-generated templates get paid 3 days faster" would sell itself.

### Integration Notes

This proposal and the AI Plan Recommendation share the same external API integration pattern (LLM call, response parsing, caching). If both are built, they should share an `LLMClient` utility class that handles API selection (Claude Haiku vs Gemini Flash), timeout handling, error logging, and daily cost tracking. Building two independent integrations would create maintenance fragmentation.

---

## 13. Competition Pool (Future)

### What I Like

The anti-cheat system is the most thoughtful section in any proposal in this directory. Layered defense (photo requirements → statistical anomaly detection → VIN validation → customer confirmation → manual review) with escalating punishment shows real adversarial thinking. The "repair logged at 2am, photo at 2:01am, next repair at 2:02am" anomaly pattern is the kind of detail that makes fraud systems actually work.

The three distribution model options (Top N split / Pro-rata / Tiered bonus) with a recommendation for real cash (Option A — Stripe Transfer) over credits shows good judgment about what actually motivates people.

The data model sketch is clean: `CompetitionMonth` tracks the pool lifecycle, `CompetitionEntry` tracks per-tenant participation, and `RepairFlag` enables the manual review queue. The status flow on `CompetitionMonth` (`accumulating → frozen → reviewing → distributed`) is correct.

### What I'd Reconsider

**Tax reporting obligations are missing and this is not optional.** If RS Systems distributes cash to shops via Stripe Transfer, and any shop receives more than $600 in a calendar year, US law requires filing IRS Form 1099-MISC. This is a legal and operational requirement, not an edge case. Before building this feature, legal review is needed to understand:
- Which entity is responsible for 1099 filing (RS Systems, the platform)?
- How to collect TINs (Taxpayer Identification Numbers) from shops receiving payouts?
- How to handle payouts to non-US shops?

This could add significant compliance overhead. It may be sufficient to add "Stripe handles 1099 for connected accounts" to the proposal, but that needs to be verified — Stripe handles 1099-K (card payment processing) but not necessarily 1099-MISC (prize/award payments).

**Double-payout race condition on distribution.** The `CompetitionMonth.status` field protects against double distribution, but the transition from `reviewing → distributed` and the Stripe Transfer creation need to be in a single database transaction with `select_for_update()`. If two admin users click "distribute" at the same millisecond (unlikely but possible), both could read `status='reviewing'` before either writes `status='distributed'`. The fix:

```python
with transaction.atomic():
    month = CompetitionMonth.objects.select_for_update().get(pk=month_id)
    if month.status != 'reviewing':
        raise ValueError("Already distributed or invalid state")
    # ... create transfers ...
    month.status = 'distributed'
    month.save()
```

This is critical for a feature that moves real money.

**Public leaderboard is a security concern.** The "Future Enhancements" section includes a public leaderboard showing top shops by repair count. A sophisticated competitor (or insurance fraud investigator) could use this to identify which shops have abnormally high repair volumes. I'd recommend making the leaderboard opt-in (shops choose whether to appear publicly) and only showing relative rankings, not absolute counts.

### How It Could Be Improved

The perceptual hashing approach for photo deduplication (`imagehash` library or similar) is the right tool, but hash collisions are possible. Two different photos with similar composition (same truck, same repair location, similar lighting) could generate similar hashes. The system should use a threshold (not exact match) and flag near-duplicates for human review rather than auto-rejecting. The Hamming distance threshold that defines "too similar" will need to be tuned empirically.

The minimum threshold of "10 verified repairs to qualify" is reasonable but the proposal should also include a maximum payout per tenant per month (e.g., 20% of total pool). Without a cap, a single dominant shop could win 90% of the pool every month, making the competition pointless for everyone else and undermining the motivational value for smaller shops.

### Integration Notes

Competition Pool is explicitly blocked on Stripe Connect Phases 1-3 being complete. Both are now live. The remaining dependency is the `PlatformConfig.competition_pool_fee_percent` field (referenced in the Stripe Connect implementation plan) which needs to be settable from the admin before the pool accumulates any money. Verify this field exists and is editable in the current admin panel before planning Competition Pool development.

---

## 14. Cross-Cutting Themes

Having reviewed all 13 proposals together, several patterns emerge that are worth addressing at the platform level.

### The Repair Completion Hook Needs an Orchestrator

Four separate proposals (Loyalty Points, Warranty, Review Requests, and future hooks) all trigger on `Repair.save()` when status transitions to `COMPLETED`. The current approach of each service independently hooking into `save()` will create a tangled, hard-to-debug execution order. A clean solution:

```python
def post_completion_hooks(repair):
    """Single orchestration point for all post-completion logic.
    Each hook is isolated — failure in one doesn't block others."""
    hooks = [
        LoyaltyService.award_completion_points,
        WarrantyService.set_warranty_on_completion,
        ReviewRequestService.on_repair_completed,
    ]
    for hook in hooks:
        try:
            hook(repair)
        except Exception as e:
            logger.error(f"Post-completion hook {hook.__name__} failed: {e}", exc_info=True)
```

This should be called from one place in `Repair.save()` (or a post-save signal) and each hook should be idempotent (calling it twice doesn't create duplicate records).

### Per-Tenant Config Objects Are Proliferating

We now have (or will have): `BillingConfig`, `LoyaltyConfig`, `ReviewConfig`, `WarrantyPolicy` — all per-tenant, all with `get_for_tenant(tenant)` class methods. This pattern is good but should be documented explicitly so future proposals follow the same convention. Consider a base class:

```python
class TenantConfig(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE)

    @classmethod
    def get_for_tenant(cls, tenant):
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj

    class Meta:
        abstract = True
```

Every new per-tenant config model should inherit from `TenantConfig`.

### External API Dependencies Need a Central Registry

Three proposals add external API dependencies: AI Email Templates (LLM API), Review Request (Google Places API), and AI Plan Recommendation (optional LLM). Each proposal independently defines how to call these APIs. A central `ExternalAPIClient` registry would:
- Provide consistent timeout handling (current: each proposal defines its own)
- Log all external API calls for cost monitoring
- Enable easy switching between providers (e.g., Claude Haiku → Gemini Flash)
- Make API failures visible in a single place

### The Pricing Angle Is Inconsistently Applied

Multiple proposals include a "Pricing Angle" section suggesting which plan gets which features. But the tiers aren't always consistent:
- Loyalty: Starter gets basic points, Pro gets tiers
- Review Requests: Starter gets manual review link, Professional gets automation
- Website Widget: Starter gets 50 submissions/month, Pro gets 500
- Warranty: Starter gets tracking, Pro gets claims workflow

This is fine as long as these decisions are made deliberately and consistently. Before any of these ship, there should be a single "Feature-to-Plan mapping" document that all proposals reference. Otherwise, each feature launch requires re-deciding the same pricing question.

### Management Commands and Cron Jobs Need Documentation

The platform already has: `process_batch_invoices`, `process_overdue_invoices`, `generate_aging_report`, `check_subscription_alerts`. Pending proposals would add: `send_review_requests`, `expire_loyalty_points`. These all need to be in `cron.yaml` and documented in `docs/deployment/PRODUCTION_CHECKLIST.md`. A shared "management command registry" would prevent each proposal from treating this as a post-launch detail.

---

*This document reflects my honest read of every proposal as of 2026-03-24. It's meant to improve the work, not gatekeep it. Every proposal here is a net positive — the critiques are about making good ideas great.*
