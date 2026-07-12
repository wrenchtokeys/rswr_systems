# Feature-to-Plan Tier Matrix

> **Note:** The plan/price table in the root [README.md](../README.md#subscription-plans) is canonical for prices and limits; this doc is the detailed feature-to-tier matrix.

**Last updated:** 2026-03-25
**Author:** Amelia
**Purpose:** Single source of truth for which features are available on each subscription plan. All proposals MUST reference this document before features ship to ensure consistent tier gating.

---

## Plan Overview

| | Starter | Professional | Enterprise |
|---|---------|-------------|------------|
| **Monthly Price** | Low | Mid | High |
| **Repair Limit** | 200/mo | Unlimited | Unlimited |
| **Technician Limit** | 5 | 15 | Unlimited |
| **Customer Limit** | 50 | Unlimited | Unlimited |

---

## Feature Matrix

| Feature | Starter | Professional | Enterprise | Notes |
|---------|---------|-------------|------------|-------|
| **Repairs & Invoicing** | ✅ (200/mo limit) | ✅ (unlimited) | ✅ (unlimited) | Core platform feature |
| **Progressive Pricing** | ✅ | ✅ | ✅ | Per-unit cost tiers |
| **Multi-Break Batch Repairs** | ✅ | ✅ | ✅ | Core workflow |
| **Loyalty Points (basic)** | ✅ | ✅ | ✅ | Earn/redeem points, basic program |
| **Loyalty Tiers** | ❌ | ✅ | ✅ | Bronze/Silver/Gold tier progression |
| **Review Requests (auto)** | ❌ | ✅ | ✅ | Automated post-repair review requests |
| **Website Widget** | ✅ (50 submissions/mo) | ✅ (500 submissions/mo) | ✅ (unlimited) | Embeddable quote form |
| **Warranty Tracking** | ✅ | ✅ | ✅ | Basic warranty records on repairs |
| **Warranty Claims Workflow** | ❌ | ✅ | ✅ | Full claims process, zero-charge warranty repairs |
| **AI Email Templates** | ❌ | ✅ | ✅ | LLM-generated email templates per shop |
| **Invoice Email Tracking** | ❌ | ✅ | ✅ | Open/click tracking on invoice emails |
| **Competition Pool** | ❌ | ❌ | ✅ | Gamification between technicians |
| **Per-Customer Warranty Overrides** | ❌ | ❌ | ✅ | Custom warranty terms per fleet customer |
| **Google Business API** | ❌ | ❌ | ✅ | Direct Google Business Profile integration |

---

## Pricing Logic

### Why features are gated where they are

**Starter — get shops running fast.** Every shop needs repairs, invoicing, basic loyalty, warranty tracking, and a simple web presence. Starter includes the essentials so new shops see value immediately. Volume limits (200 repairs/mo, 5 techs, 50 customers, 50 widget submissions/mo) keep the tier sized for small operations.

**Professional — automation and engagement.** Shops that outgrow Starter need automation: review requests fire automatically, loyalty tiers drive repeat business, warranty claims reduce manual work, AI templates save time composing emails, and email tracking closes the feedback loop on invoices. The widget scales to 500 submissions/mo. Tech and customer limits expand to support growing teams.

**Enterprise — competitive edge and full control.** Large or multi-location shops get everything unlimited plus features that require deeper integration or create competitive differentiation: competition pools for tech gamification, per-customer warranty overrides for fleet contract flexibility, and direct Google Business API access for reputation management at scale.

### Guiding principles

1. **Core workflows are never gated.** Repairs, invoicing, and basic loyalty are available on every plan.
2. **Automation is the Professional upgrade hook.** If a feature replaces manual work with automated workflows, it belongs in Professional.
3. **Enterprise is for scale and customization.** Features that only matter at high volume or require deep per-customer configuration are Enterprise.
4. **Widget and volume limits scale with plan.** Per-submission and per-entity limits increase naturally across tiers.

---

## Enforcement

Feature gating is enforced by `SubscriptionEnforcementMiddleware` in `apps/tenants/subscription_middleware.py`. Each gated feature should check the tenant's plan before rendering UI or processing requests.

Plan limits (repairs/mo, techs, customers, widget submissions) are checked at the point of creation — not retroactively. If a shop downgrades, existing data is preserved but new creation is blocked once limits are exceeded.

---

## How to Update This Document

When adding a new feature to the platform:

1. **Before writing the proposal:** Check this matrix to see where similar features land tier-wise.
2. **In the proposal:** Include a "Pricing Tier" section that references this document and states which plan(s) get the feature.
3. **Before shipping:** Update this matrix with the new feature row. Get the tier decision reviewed.
4. **After shipping:** Verify the enforcement code matches this document.

When changing tier assignments:

1. Update the feature row in the matrix above.
2. Update the enforcement code to match.
3. Note the change date and reason in a commit message.
4. Consider migration impact — shops on lower tiers may lose access to features they were using.
