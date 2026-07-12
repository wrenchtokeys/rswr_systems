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

### 🚧 Partially Shipped
| Proposal | Status | Notes |
|----------|--------|-------|
| [Loyalty System Overhaul](loyalty-system-overhaul.md) | Phases 1-2 shipped | Phase 1: ledger, LoyaltyConfig, LoyaltyService. Phase 2: reconcile command, expire command, liability report, manual adjustment. Phases 3-4 (tiers, dashboards) pending |
| [Warranty System](warranty-system.md) | Phase 1 shipped | Policies, claim workflow, repair badges, invoice terms, completion hook. Phase 2 (per-customer overrides, goodwill flag, stats cache) pending |
| [Review Request System](review-request-system.md) | Phase 1 shipped (CODE-208) | `ReviewRequestService`, `ReviewConfig`, `ReviewRequest` models. Phase 2/3 (actual Google Reviews API) pending |
| [Reward Redemption UX](reward-redemption-ux-overhaul.md) | Phase 1 shipped (CODE-210) | `preferred_date`/`preferred_time` on physical rewards, auto-restore points on denial |
| [Manager Settings Roadmap](MANAGER_SETTINGS_ROADMAP.md) | Phase 1 shipped (Nov 2025) | Manager settings dashboard live; later phases pending |

### 🟡 Awaiting Review
| Proposal | Status | Notes |
|----------|--------|-------|
| [Website Integration Widget](website-integration-widget.md) | Draft | Embeddable quote form for shop websites |
| [Repair Form Efficiency](repair-form-efficiency.md) | Draft | 12 ideas for repair form, 7 for replacement, 5 for multi-break |
| [AI Plan Recommendation](ai-plan-recommendation.md) | Draft | Rule-based plan suggestions during trial |
| [Invoice Email Tracking](invoice-email-tracking.md) | Draft | Open/click tracking on invoice emails |
| [AI Email Template Assistant](ai-email-template-assistant.md) | Draft | AI-generated email templates per shop |

### 📋 Future
| Proposal | Status | Notes |
|----------|--------|-------|
| [Competition Pool](competition-pool.md) | Documented | Gamification between techs. Build after loyalty system |

## How This Works
I add proposals here when I spot opportunities during autonomous work. Drake reviews and approves/rejects via PR comments or chat. Nothing gets built until approved.
