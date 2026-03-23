# Proposal: Reward Redemption UX Overhaul

**Author:** Amelia  
**Date:** 2026-03-22  
**Status:** Draft — awaiting Drake's review

---

## Problem

The rewards system has three UX gaps:

1. **Customers can't apply monetary rewards to repairs.** They redeem points in the rewards page, but a technician has to manually link the reward to a specific repair. No self-serve.

2. **Physical rewards (pizza, donuts) have no scheduling.** Customer redeems "Pizza Party" but there's no way to say "deliver it next Friday at noon." The tech just sees an unfulfilled redemption with no timing info.

3. **All reward types use the same redemption flow.** A free repair and a pizza party shouldn't have the same UX — one is a discount, the other is a delivery.

## Solution

Split the redemption flow by reward category:

### Flow A: Monetary Rewards (REPAIR_DISCOUNT, FREE_SERVICE)

**Customer submits a repair request:**
```
┌─ Request Repair ──────────────────────────┐
│ Unit Number: [________]                   │
│ Damage Type: [Star Break ▾]              │
│ Description: [________________]           │
│ Photo: [Upload]                           │
│                                           │
│ 🎁 You have 1 available reward:          │
│ ┌───────────────────────────────────────┐ │
│ │ ☐ 25% Off Next Repair (redeemed 3/15)│ │
│ │   Saves ~$12.50 on a standard repair │ │
│ └───────────────────────────────────────┘ │
│                                           │
│ [Submit Repair Request]                   │
└───────────────────────────────────────────┘
```

- Show only FULFILLED, unapplied monetary redemptions
- Customer checks the box to apply
- Repair is created with `applied_rewards` already linked
- Tech sees "Customer applied: 25% off" on repair detail
- Invoice auto-calculates the discount via `get_discounted_cost()`

**Alternative: apply at any time before invoicing**
- Customer can also apply from their repair detail page (before completion)
- "Apply a Reward" button shows available monetary redemptions

### Flow B: Physical Rewards (MERCHANDISE, OTHER)

**Customer redeems in rewards page:**
```
┌─ Redeem: Pizza Party 🍕 ─────────────────┐
│                                           │
│ You're redeeming: Pizza Party             │
│ Cost: 5,000 points                        │
│ Your balance: 7,500 points                │
│                                           │
│ Preferred Date: [March 28, 2026]          │
│ Preferred Time: [12:00 PM ▾]             │
│ Notes: [Pepperoni please, 10 people]      │
│                                           │
│ [Redeem & Schedule]                       │
└───────────────────────────────────────────┘
```

- Date/time picker appears ONLY for non-monetary rewards
- Notes field for special requests
- Tech/manager dashboard shows scheduled fulfillments
- Status flow: PENDING → SCHEDULED → FULFILLED

### Model Changes

```python
# RewardRedemption — add 3 fields
class RewardRedemption(models.Model):
    # ... existing fields ...
    
    # New: scheduling for physical rewards
    preferred_date = models.DateField(
        null=True, blank=True,
        help_text="Customer's preferred delivery/fulfillment date"
    )
    preferred_time = models.TimeField(
        null=True, blank=True,
        help_text="Customer's preferred time"
    )
    customer_notes = models.TextField(
        blank=True,
        help_text="Special requests from customer"
    )
```

### View Changes

1. **`request_repair()`** — add available monetary rewards to context, process selected reward on POST
2. **`redeem_reward()`** — split flow: monetary = instant redeem (no scheduling), physical = show date/time picker
3. **`customer_repair_detail()`** — add "Apply Reward" button for unapplied monetary rewards
4. **Tech `reward_fulfillment_detail()`** — show scheduled date/time for physical rewards

### Template Changes

1. `request_repair.html` — optional reward selection section
2. `referrals/rewards.html` — different redeem modal for monetary vs physical
3. `repair_detail.html` (customer) — "Apply Reward" option
4. `reward_fulfillment_detail.html` (tech) — show scheduling info

## Scope

- 1 migration (3 new fields on RewardRedemption)
- ~4 view changes
- ~4 template changes
- No new models, no new apps

## Risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| Customer applies reward then repair is denied | Low | Reward stays on the redemption, can be re-applied to another repair |
| Double-discount (reward + price override) | Low | `get_discounted_cost()` already handles this — only first discount applies |
| Physical reward scheduled but never fulfilled | Medium | Add reminder notification for techs when fulfillment date approaches |
| Migration on live data | Low | All 3 fields are nullable — zero risk to existing records |

## Decision Needed

Drake: approve the split flow approach? The key question is whether customers should apply monetary rewards at repair request time (simpler but requires them to think ahead) or at any point before invoicing (more flexible but more complex UI).
