# Proposal: Loyalty System Overhaul

**Author:** Amelia  
**Date:** 2026-03-24  
**Status:** Draft — awaiting Drake's review

---

## What Exists Today

### Referral System (functional)
- Customer gets a unique referral code (8-char alphanumeric)
- When someone signs up with that code: referrer gets **500 points**, referred gets **100 points**
- Cross-tenant protection (can't use Shop A's code at Shop B)
- Self-referral prevention, duplicate prevention
- Referral tracking, stats, leaderboard views

### Points System (partially functional)
- **50 points** per completed repair
- **Milestone bonuses:** 250 at 5th repair, 500 at 10th, 1000 every 25th
- Points balance tracked per customer
- Points auto-awarded on repair completion

### Redemption System (built but limited)
- RewardOption model: shop defines what points can buy (name, points cost, discount type/value)
- RewardType model: categories (repair discount, replacement discount, free service, merchandise, gift card)
- Discount types: percentage, fixed amount, free, none
- Redemption flow: customer requests → pending → approved/fulfilled/rejected
- Auto-applies repair discounts when repair is completed
- Technician assignment for fulfillment
- Connects to invoicing (discounts show on invoice)

### What's Missing / Broken

1. **No way for customers to see their points** — the views exist but there's no customer-facing UI that makes this obvious. Points are invisible unless someone navigates to the right URL.

2. **No earning visibility** — customers don't know they earned 50 points when their repair was completed. No email, no notification, no celebration moment.

3. **Earning is one-dimensional** — only referrals and repair completions earn points. No engagement hooks.

4. **No tiers** — a customer with 100 repairs is treated the same as one with 1. No status, no perks, no recognition.

5. **Shop owners can't configure the point values** — 50 points/repair and 500/referral are hardcoded. Different shops have different margins and want different incentives.

6. **No expiration** — points never expire. For SaaS this means an ever-growing liability on the shop's books.

7. **RewardService.calculate_points() is a stub** — literally returns 0, never called anywhere.

8. **No transaction log** — if points are wrong, there's no audit trail of why. Just a running balance.

---

## Proposed Loyalty System

### 1. Point Transaction Ledger

Replace the single `Reward.points` integer with a transaction log. Every point change gets a record.

```
PointTransaction
  - customer_user (FK)
  - tenant (FK)
  - amount (+50, -500, etc.)
  - balance_after (running balance)
  - type (repair_complete, referral_made, referral_received, redemption, 
          milestone_bonus, manual_adjustment, expiration, tier_bonus,
          review_bonus, early_pay_bonus)
  - description ("Completed repair #R-1234", "Referred John D.", "Redeemed 10% off")
  - related_repair (FK, nullable)
  - related_redemption (FK, nullable)
  - created_at
  - expires_at (nullable — for expiration support)
```

**Why:** Audit trail, debugging, customer-facing history ("here's exactly how you earned and spent every point"), and enables expiration.

### 2. Configurable Point Rules (per tenant)

New model: `LoyaltyConfig` (per-tenant, like BillingConfig)

```
LoyaltyConfig
  - tenant (OneToOne)
  - points_per_repair (default: 50)
  - referral_bonus_referrer (default: 500)
  - referral_bonus_referred (default: 100)
  - milestone_5_bonus (default: 250)
  - milestone_10_bonus (default: 500)
  - milestone_25_bonus (default: 1000)
  - points_for_review (default: 100)
  - points_for_early_payment (default: 25)
  - points_expiry_days (default: 365, 0 = never)
  - tier_enabled (default: false)
  - is_active (default: true)
```

Shop owners configure this from their settings. Different shops can have wildly different point economies.

### 3. Loyalty Tiers

Optional tier system (shop owners opt in):

```
LoyaltyTier
  - tenant (FK)
  - name ("Bronze", "Silver", "Gold", "Platinum" — or custom names)
  - min_lifetime_points (threshold to reach this tier)
  - point_multiplier (1.0, 1.25, 1.5, 2.0 — earn faster at higher tiers)
  - perks_description (free text — "Priority scheduling, 5% off all repairs")
  - badge_color (hex)
  - sort_order
```

Tier is calculated from **lifetime points earned** (not current balance — spending doesn't demote you). Fleet managers love this — it rewards volume.

### 4. More Ways to Earn

Beyond repairs and referrals:

| Action | Points | Notes |
|--------|--------|-------|
| Repair completed | Configurable (default 50) | Already exists |
| Referral (referrer) | Configurable (default 500) | Already exists |
| Referral (referred) | Configurable (default 100) | Already exists |
| Leave a review | 100 | One-time per customer, after first completed repair |
| Pay invoice early | 25 | Paid before due date |
| Milestone bonuses | 250/500/1000 | At 5th, 10th, every 25th repair |
| Tier multiplier | 1.25x–2x | Higher tiers earn more per action |
| Manual bonus | Variable | Shop owner awards bonus points (appreciation, apology, promo) |

### 5. Customer-Facing Loyalty Dashboard

Visible in the customer portal:

- **Points balance** (prominent, always visible in nav/header)
- **Tier status** with progress bar to next tier
- **Points history** (transaction log — "Mar 24: +50 for repair R-1234")
- **Available rewards** (what they can redeem now vs. what they need more points for)
- **Referral code** with easy share button
- **Leaderboard** (optional — top referrers)

### 6. Notification Hooks

Points should feel like a reward, not a database update:

- **Email on point earn:** "You just earned 50 points for your repair! Your balance is now 450."
- **Email on tier upgrade:** "Congratulations! You've reached Gold tier. Here's what that means..."
- **Email on expiration warning:** "You have 200 points expiring in 30 days. Redeem them now!"
- **In-app notification** for all the above

### 7. Owner/Manager Loyalty Dashboard

For the shop owner:

- **Program overview:** total points issued, total redeemed, total outstanding (liability)
- **Top customers** by points/tier
- **Redemption queue** (pending rewards to fulfill)
- **Manual point adjustment** (with reason required — audit trail)
- **Program configuration** (point values, tiers, expiration)

---

## Implementation Plan

### Phase 1: Foundation (3-4 days)
- `PointTransaction` model + migration
- `LoyaltyConfig` model (per-tenant) + migration
- Refactor `award_completion_points()` and `process_referral()` to write transactions
- Backfill existing `Reward.points` into transaction ledger
- Keep `Reward.points` as cached balance (updated on each transaction)
- Customer points history view
- Points balance visible in customer portal nav

### Phase 2: Engagement Hooks (2-3 days)
- Early payment bonus (hook into Payment.save())
- Review bonus (new model or flag on customer)
- Manual point adjustment (owner dashboard)
- Point earn notification emails (branded HTML, using `send_branded_email`)
- Expiration system (management command, configurable per tenant)

### Phase 3: Tiers (2-3 days)
- `LoyaltyTier` model
- Tier calculation from lifetime points
- Tier-based point multiplier
- Tier badge in customer portal
- Tier upgrade notification email
- Owner can define custom tier names and thresholds

### Phase 4: Owner Dashboard (1-2 days)
- Loyalty program overview widget
- Program configuration page
- Manual adjustment tool
- Redemption queue improvements
- Point liability report

---

## Scope & Risk

| Aspect | Assessment |
|--------|-----------|
| **Effort** | Phase 1: 3-4 days. Full system: ~2 weeks. |
| **Risk** | Low-medium. Touches existing reward models but backwards compatible. |
| **Migration** | Backfill transaction ledger from existing `Reward.points`. Non-destructive. |
| **Breaking changes** | None. Existing points, referrals, and redemptions continue working. New features layer on top. |
| **Dependencies** | None. Uses existing email infrastructure. |

## Why This Matters for RS Systems

Loyalty programs are a **retention moat** for the SaaS:

1. **Shops that set up loyalty programs have stickier customers** — customers come back for points, not just because they need a repair
2. **Fleet managers love it** — "we've earned Gold tier with this shop" is a reason to not switch
3. **Differentiator** — no other glass shop SaaS has a configurable loyalty system. Most are just invoice-and-forget.
4. **Revenue impact** — shops with loyalty programs have higher repeat rates. Higher repeat rates = higher MRR for RS Systems.

## Decision Needed
1. Approve Phase 1 (foundation + transaction ledger)?
2. Should tiers be included in the base plan or a Pro/Enterprise feature?
3. Point expiration: default to 365 days, or never-expire as default?
