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

### 🟡 Decide (Drake) — the four March drafts
*Unreviewed since March 2026. The 2026-09-01 direction review recommends keeping ONE as the
acquisition item and archiving the other three under `docs/archive/proposals/`. They stay here
until Drake confirms; nothing moves on the strength of this table. If any is kept, re-verify it
against the current code before building — the app has changed a great deal since March.*

| Proposal | Recommendation | Notes |
|----------|--------|-------|
| [Website Integration Widget](website-integration-widget.md) | **Keep** — the acquisition item | Embeddable quote form for shop websites. The only proposal that brings a stranger to the signup page; sequenced after landing credibility (`IMPROVEMENT_SESSIONS.md` C1) |
| [Repair Form Efficiency](repair-form-efficiency.md) | **Archive** | 12 ideas for repair form, 7 for replacement, 5 for multi-break. Overtaken by the unified job form, UI S6/S7 and the job-form parity pass (#187) |
| [AI Plan Recommendation](ai-plan-recommendation.md) | **Archive** | Rule-based plan suggestions during trial. No acquisition/adoption case; plan flags barely gate anything (`PRICING_TIERS.md`) |
| [AI Email Template Assistant](ai-email-template-assistant.md) | **Archive** | AI-generated email templates per shop. The email chassis (#200/#208) made the templates house-styled and fixed; per-shop generation cuts against `SES_OPERATIONS.md` |

### 📋 Future
| Proposal | Status | Notes |
|----------|--------|-------|
| [Competition Pool](competition-pool.md) | Documented | Gamification between techs. Build after loyalty system |

## Where the live work queues are
This directory is for **proposals** — ideas awaiting a yes/no. Work that has been approved and
sequenced lives in `docs/strategy/`, and those are the files to read before starting a session:

*Refreshed 2026-09-02 from the strategy docs.*

| Doc | What's open |
|---|---|
| [`PRODUCT_DIRECTION.md`](../strategy/PRODUCT_DIRECTION.md) | **The direction** — Path A with a B-ready spine, drafted, awaiting Drake's sign-off; the ordered "what happens next" list |
| [`IMPROVEMENT_SESSIONS.md`](../strategy/IMPROVEMENT_SESSIONS.md) | Status line on every session (2026-09-02). **Next:** C1 landing credibility, then the spine — B3 quotes, B5 claim tracking, B6 price book. A5/B1 done; A2/C2 verify on prod; D1/D2 memos wait on interviews |
| [`PHOTO_ML_SESSIONS.md`](../strategy/PHOTO_ML_SESSIONS.md) | **P8 — close the world-readable media bucket** (its last code; after #243 deploys). P5/P4b parked, held by Drake |
| [`FIELD_OPS_SESSIONS.md`](../strategy/FIELD_OPS_SESSIONS.md) | S11–S14 scheduling UX (sequenced after the spine). N2 texts wait on the toll-free number (v4 reviewing). P1 Mygrant waits on their IT callback. Two N3 copy decisions wait on Drake |
| [`UI_MAGIC_SESSIONS.md`](../strategy/UI_MAGIC_SESSIONS.md) | Arc clear through S18a. S14/S15 fold into C1; the S13 sweep, S16 remainder and S18b are **parked pending users** |
| [`JOB_QUEUE_SESSIONS.md`](../strategy/JOB_QUEUE_SESSIONS.md) | Q1–Q4 shipped and deployed; Q5/Q6 parked |
| [`TEST_SUITE_SESSIONS.md`](../strategy/TEST_SUITE_SESSIONS.md) | 16-minute suite with a committed baseline; the "honesty half" (make the 93 red tests green or gone) is open. T7 guard script = PR #245 |
| [`BILLING_RELIABILITY_PLAN.md`](../strategy/BILLING_RELIABILITY_PLAN.md) | "Still to do" — `set_stripe_prices --verify` after billing deploys, text-to-pay, in-person card |

## How This Works
I add proposals here when I spot opportunities during autonomous work. Drake reviews and approves/rejects via PR comments or chat. Nothing gets built until approved.
