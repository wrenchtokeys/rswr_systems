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
| [Stripe Connect Implementation](stripe-connect-implementation-plan.md) | ✅ Shipped | Phases 1-2 live, Connect approved March 2026 |
| [Stripe Connect Multi-Tenant](stripe-connect-multi-tenant-payments.md) | ✅ Shipped | Superseded by implementation plan above |

### 🚧 Partially Shipped
| Proposal | Status | Notes |
|----------|--------|-------|
| [Loyalty System Overhaul](loyalty-system-overhaul.md) | Phases 1-2 shipped | Phase 1: ledger, LoyaltyConfig, LoyaltyService. Phase 2: reconcile command, expire command, liability report, manual adjustment. Phases 3-4 (tiers, dashboards) pending |
| [Warranty System](warranty-system.md) | Phase 1 shipped | Policies, claim workflow, repair badges, invoice terms, completion hook. Phase 2 (per-customer overrides, goodwill flag, stats cache) pending |

### 🟡 Awaiting Review
| Proposal | Status | Notes |
|----------|--------|-------|
| [Review Request System](review-request-system.md) | Draft | Smart Google review requests after repair completion. Ties into website widget flywheel |
| [Website Integration Widget](website-integration-widget.md) | Draft | Embeddable quote form for shop websites |
| [Repair Form Efficiency](repair-form-efficiency.md) | Draft | 12 ideas for repair form, 7 for replacement, 5 for multi-break |
| [AI Plan Recommendation](ai-plan-recommendation.md) | Draft | Rule-based plan suggestions during trial |
| [Customer Billing Preferences](customer-billing-preferences-ux.md) | Draft | Payment terms/prefs on customer create form |
| [Reward Redemption UX](reward-redemption-ux-overhaul.md) | Draft | Modal for redemptions (partially addressed by LOYALTY-003 confirm modal) |
| [Invoice Email Tracking](invoice-email-tracking.md) | Draft | Open/click tracking on invoice emails |
| [AI Email Template Assistant](ai-email-template-assistant.md) | Draft | AI-generated email templates per shop |

### 📋 Future
| Proposal | Status | Notes |
|----------|--------|-------|
| [Competition Pool](competition-pool.md) | Documented | Gamification between techs. Build after loyalty system |

## How This Works
I add proposals here when I spot opportunities during autonomous work. Drake reviews and approves/rejects via PR comments or chat. Nothing gets built until approved.
