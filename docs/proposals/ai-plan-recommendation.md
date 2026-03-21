# Proposal: AI-Powered Plan Recommendation

**Author:** Amelia  
**Date:** 2026-03-21  
**Status:** Draft — awaiting Drake's review

---

## Problem

New shop owners signing up for RS Systems don't always know which plan fits their business. We already see this — the "Not sure yet" option exists because people hesitate. Even those who pick a plan at signup may not be choosing optimally for their actual usage patterns.

Once a shop has been using the trial for 2-3 weeks, we have real data about their business: number of techs, customers, repairs, invoices, whether they use features like rewards or Stripe Connect. That data can drive a personalized recommendation that's more useful than a static pricing page.

## Solution

Add an AI-powered plan recommendation engine that analyzes a tenant's actual usage during trial and suggests the best-fit plan.

### Data Points for Recommendation

| Signal | What It Tells Us |
|--------|-----------------|
| Number of technicians added | Team size → Solo vs Starter vs Pro |
| Number of customers | Account volume → capacity needs |
| Repairs completed per week | Throughput → will they hit limits? |
| Invoices generated | Whether they use billing features |
| Stripe Connect set up | Payment sophistication |
| Rewards/referrals used | Feature engagement |
| Storage used (photos) | Media-heavy shops need more |
| Number of active users | Multi-user = higher tier |

### Recommendation Logic (Rule-Based First, ML Later)

**Phase 1 — Rule-based (no external dependencies):**

```python
def recommend_plan(tenant):
    """Analyze tenant usage and recommend a plan."""
    stats = {
        'techs': tenant.technicians.count(),
        'customers': tenant.customers.count(),
        'monthly_repairs': tenant.repairs.filter(
            completed_at__gte=now() - timedelta(days=30)
        ).count(),
        'uses_invoicing': tenant.invoices.exists(),
        'uses_rewards': tenant.reward_entries.exists(),
        'uses_connect': tenant.can_accept_payments,
        'storage_mb': tenant.get_storage_used_mb(),
    }
    
    # Project monthly usage from trial activity
    trial_days = (now() - tenant.trial_started_at).days or 1
    projected_monthly_repairs = (stats['monthly_repairs'] / trial_days) * 30
    
    if (stats['techs'] > 5 or projected_monthly_repairs > 200 
            or stats['uses_connect'] or stats['customers'] > 50):
        return 'enterprise', "Your shop's volume and team size need Enterprise-level capacity."
    
    if (stats['techs'] > 2 or projected_monthly_repairs > 50
            or stats['uses_invoicing'] or stats['uses_rewards']):
        return 'pro', "You're using advanced features and growing fast — Pro gives you room."
    
    if stats['techs'] >= 1 or projected_monthly_repairs > 10:
        return 'starter', "Perfect for a shop your size — all the essentials, no extras you don't need."
    
    return 'starter', "Start here — you can always upgrade as your shop grows."
```

**Phase 2 — Enhanced with LLM (future):**
- Feed usage stats to an LLM for natural language explanation
- "Based on your 47 repairs this month with 3 techs, Pro gives you unlimited repairs and team seats"
- Personalized to the shop's actual workflow, not generic marketing copy

### Where It Shows Up

1. **Billing page** — "Recommended for you" badge with explanation below plan card
2. **Day 20 nudge email** — for "not sure" signups, include the AI recommendation
3. **Trial expiry emails** — include recommendation in the "time to upgrade" emails
4. **Owner dashboard** — subtle banner: "Based on your usage, we think [Plan] is your best fit"

### API Endpoint

```
GET /api/tenants/plan-recommendation/
Response: {
    "recommended_plan": "pro",
    "reason": "You're using advanced features and growing fast...",
    "usage_summary": { ... },
    "confidence": "high"  // high/medium/low based on data volume
}
```

Confidence levels:
- **High:** 14+ days of activity, 10+ repairs
- **Medium:** 7-13 days, 3-9 repairs
- **Low:** <7 days or <3 repairs (too early to tell — show all plans equally)

## Scope

### Phase 1 (rule-based, can ship in a day)
- `PlanRecommendationService` in `apps/tenants/services.py`
- Recommendation logic based on usage stats (no external API calls)
- Display on billing page as "Recommended" badge
- Include in nudge email
- API endpoint for future frontend use

### Phase 2 (LLM-enhanced, future)
- Natural language explanations via API (Anthropic/OpenAI)
- A/B test rule-based vs LLM explanations for conversion
- Feedback loop: track if users follow recommendations

## Risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| Bad recommendation hurts trust | Medium | Show confidence level; don't recommend on low data |
| Over-engineering for current scale | Low | Phase 1 is ~100 lines of code, no dependencies |
| Privacy concern (analyzing usage) | Low | Standard SaaS analytics; no PII in recommendation |
| Recommendation feels pushy | Medium | Subtle UI; "suggestion" language, not hard sell |

## Cost

- Phase 1: Zero. Pure Python logic, no external APIs.
- Phase 2: ~$0.01 per recommendation (one LLM call per billing page view, cached per session).

## Decision Needed

Drake: approve Phase 1 (rule-based) to ship alongside the nudge email work? Phase 2 can wait until we have enough tenants to validate whether recommendations improve conversion.
