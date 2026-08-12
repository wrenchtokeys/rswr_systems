# Proposals

## Platform Reference Documents

| Document | Purpose |
|----------|---------|
| [Pricing Tiers](../PRICING_TIERS.md) | Feature-to-plan tier matrix — **check before every proposal** |

---

Feature proposals and workflow improvements suggested by Amelia.

Each proposal includes:
- **Problem** — what's broken or missing
- **Solution** — what I'd build
- **Scope** — files changed, estimated complexity
- **Risk** — what could go wrong

## Status Key
- 🟡 **Draft** — waiting for Drake's review
- ✅ **Shipped** — built and merged
- 🚧 **Partial** — some phases shipped, more pending
- 📋 **Documented** — future build, not yet prioritized
- ❌ **Rejected** — not doing this (with reason)

## Current Proposals

### ✅ Shipped
| Proposal | Status | Notes |
|----------|--------|-------|
| [Stripe Connect Implementation](../archive/stripe-connect-implementation-plan.md) | ✅ Shipped, archived | Phases 1-2 live, Connect approved March 2026. Canonical Connect reference — see `docs/development/CHANGELOG.md` 2026-03-17 entry |
| [Stripe Connect Multi-Tenant](../archive/proposals/stripe-connect-multi-tenant-payments.md) | ✅ Shipped, archived | Earlier destination-transfer design, superseded by the implementation plan above (direct charges instead); moved to archive |
| [Customer Billing Preferences](../archive/proposals/customer-billing-preferences-ux.md) | ✅ Shipped, archived | CODE-209: `_save_billing_preferences()`, `CustomerRepairPreference`; moved to archive |
| [Invoice Email Tracking](invoice-email-tracking.md) | ✅ Shipped | PR #126 (2026-07-27), verified live in prod. Open-tracking pixel + `DeliveryLog`; `core/email_utils.py`, `rs_systems/views.py`, `tests/test_invoice_view_tracking.py` |
| [Launch Readiness Roadmap](launch-readiness-roadmap.md) | ✅ Shipped | All 3 phases merged + deployed (PRs #143/#144/#146). Retained as design charter + decisions log |

### 🚧 Partially Shipped
| Proposal | Status | Notes |
|----------|--------|-------|
| [Loyalty System Overhaul](loyalty-system-overhaul.md) | Phases 1-2 shipped | Phase 1: ledger, LoyaltyConfig, LoyaltyService. Phase 2: reconcile command, expire command, liability report, manual adjustment. Since reworked customer-anchored (PR #139) + owner reward management (PRs #140/#142). Phases 3-4 (tiers, dashboards) pending — remaining gaps tracked in [loyalty-program-improvements.md](loyalty-program-improvements.md) |
| [Warranty System](warranty-system.md) | Phase 2 shipped (CODE-207) | Doc body still says "Phase 2 COMPLETE"; simplified further in PR #117 (`applies_to` = repairs/replacements, warranty fields on `GlassService`, replacements auto-warranty) |
| [Review Request System](review-request-system.md) | Phase 1 shipped + productionized | `ReviewRequestService`, `ReviewConfig`, `ReviewRequest`; plus fleet gating and the `send_review_requests` cron (`12_reviews_cron.config`, every 20 min, CODE-230 concurrency-safe). Phase 2/3 (actual Google Reviews API) pending |
| [Reward Redemption UX](reward-redemption-ux-overhaul.md) | Phase 1 shipped (CODE-210) | `preferred_date`/`preferred_time` on physical rewards, auto-restore points on denial |
| [Manager Settings Roadmap](MANAGER_SETTINGS_ROADMAP.md) | Phase 1 shipped (Nov 2025) | Manager settings dashboard live; later phases pending |

### 🟡 Awaiting Review
*All four have sat unreviewed since March 2026. Treat them as a cold backlog, not as pending work —
the live queues are in `docs/strategy/`. If any is still wanted, re-verify it against the current
code before building; the app has changed a great deal since they were written.*

| Proposal | Status | Notes |
|----------|--------|-------|
| [Website Integration Widget](website-integration-widget.md) | Draft (Mar 2026) | Embeddable quote form for shop websites |
| [Repair Form Efficiency](repair-form-efficiency.md) | Draft (Mar 2026) | 12 ideas for repair form, 7 for replacement, 5 for multi-break. **Partly overtaken** by the unified job form and UI sessions S6/S7 |
| [AI Plan Recommendation](ai-plan-recommendation.md) | Draft (Mar 2026) | Rule-based plan suggestions during trial |
| [AI Email Template Assistant](ai-email-template-assistant.md) | Draft (Mar 2026) | AI-generated email templates per shop |

### 📋 Future
| Proposal | Status | Notes |
|----------|--------|-------|
| [Competition Pool](competition-pool.md) | Documented | Gamification between techs. Build after loyalty system |

## Where the live work queues are
This directory is for **proposals** — ideas awaiting a yes/no. Work that has been approved and
sequenced lives in `docs/strategy/`, and those are the files to read before starting a session:

| Doc | What's open |
|---|---|
| [`UI_MAGIC_SESSIONS.md`](../strategy/UI_MAGIC_SESSIONS.md) | S11–S17 TODO (S1–S10 shipped) |
| [`FIELD_OPS_SESSIONS.md`](../strategy/FIELD_OPS_SESSIONS.md) | N1–N3 + S1–S5 TODO — tech notifications, scheduling, dispatch |
| [`IMPROVEMENT_SESSIONS.md`](../strategy/IMPROVEMENT_SESSIONS.md) | Whole doc pending Drake's Path A/B decision (§1) |
| [`BILLING_RELIABILITY_PLAN.md`](../strategy/BILLING_RELIABILITY_PLAN.md) | "Still to do" — text-to-pay, in-person card |

## How This Works
I add proposals here when I spot opportunities during autonomous work. Drake reviews and approves/rejects via PR comments or chat. Nothing gets built until approved.
