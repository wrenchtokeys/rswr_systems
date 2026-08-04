# Proposal: Loyalty System Overhaul

**Author:** Amelia  
**Date:** 2026-03-24  
**Status:** ✅ Phase 1 SHIPPED (LOYALTY-001, March 24 2026) — ✅ Phase 2 SHIPPED (CODE-197, March 25 2026) — Phases 3-4 pending

> **Addendum (August 2026) — Customer-anchored loyalty.** The ledger no longer
> anchors on portal accounts. `Reward` and `PointTransaction` are keyed on
> `core.Customer` (one shared balance per company); `PointTransaction.customer_user`
> survives only as nullable "acting portal user" attribution. Consequences:
> customers with **no portal login** (walk-ins, most retail) earn points; all
> portal users of a company share one balance; the shop can see the balance and
> redeem on the customer's behalf from the customer page and Apply Reward page
> (creating a redemption is manager/owner-gated); invoice + review emails carry a
> factual balance line (LoyaltyConfig.show_balance_in_emails). Referrals moved to
> deferred payout: recorded PENDING at signup on `/join/<slug>/?ref=CODE`, paid
> when the referred customer's first job completes (`referral_payout_hook`).
> Migrations 0016–0019; per-user balances were SUM-merged per company in 0017.

---

## Executive Summary

RS Systems has the bones of a loyalty program (points, referrals, redemptions) but customers can't see their points, shops can't configure the rules, and there's no audit trail. This proposal turns it into a **real competitive advantage** — a configurable, tier-based loyalty engine that makes fleet managers stay and shop owners look professional.

The key insight: **glass repair is a repeat business**. Fleets come back every week. Loyalty programs turn "we need a repair" into "we're going to *our* shop." That's the difference between a customer and a relationship.

---

## What Exists Today

### Referral System ✅ (functional)
- Unique referral codes per customer (8-char alphanumeric)
- Referrer gets **500 points**, referred gets **100 points**
- Cross-tenant protection, self-referral prevention, duplicate prevention
- Referral tracking, stats, leaderboard views

### Points System ⚠️ (partially functional)
- **50 points** per completed repair (hardcoded)
- **Milestone bonuses:** 250 at 5th repair, 500 at 10th, 1000 every 25th
- Points balance tracked per customer
- Points auto-awarded on repair completion
- `calculate_points()` is a stub that returns 0 — dead code

### Redemption System ⚠️ (built but underused)
- RewardOption: shops define what points can buy (name, cost, discount type/value)
- RewardType: categories (repair discount, replacement discount, free service, merchandise, gift card)
- Discount types: percentage, fixed amount, free
- Redemption flow: customer requests → pending → approved → fulfilled/rejected
- Auto-applies repair discounts on completion
- Connects to invoicing (discounts show on invoice PDF)

---

## Problems

### For Customers
1. **Points are invisible.** No UI showing balance, no "you earned 50 points!" moment. Points exist in the database but customers never see them.
2. **No earning context.** Did I get points for that repair? How many? Nobody knows without checking the admin.
3. **No status or recognition.** A fleet that's sent 200 repairs gets treated identically to a first-timer. No tier, no perks, no "valued customer" signal.
4. **No reason to engage.** Only repairs and referrals earn points. No hooks for reviews, early payment, or engagement.

### For Shop Owners
5. **No configuration.** Point values are hardcoded. A shop doing $400 repairs and a shop doing $40 chip repairs both award 50 points. That makes no sense — the economics are completely different.
6. **No program visibility.** No dashboard showing total points issued, redeemed, or outstanding liability.
7. **No manual controls.** Can't award bonus points for a great customer, can't adjust for a mistake.
8. **No expiration.** Points accumulate forever. For accounting, that's an ever-growing liability with no way to clean it up.

### For the Platform (RS Systems SaaS)
9. **No transaction log.** Just a single integer (`Reward.points`). If something goes wrong, there's no audit trail. No way to debug, no way to show customers "here's how you earned those points."
10. **Not a differentiator yet.** The feature exists in code but doesn't work well enough for anyone to use it. It's not a selling point on the pricing page.

---

## Proposed System

### Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │          LoyaltyConfig               │
                    │  (per-tenant point rules & settings)  │
                    └──────────┬──────────────────────────┘
                               │
    ┌──────────────┬───────────┼───────────┬──────────────┐
    │              │           │           │              │
    ▼              ▼           ▼           ▼              ▼
 Repair        Referral    Payment     Review         Manual
 Complete      Processed   Received    Submitted      Adjustment
    │              │           │           │              │
    └──────────────┴───────────┴───────────┴──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  PointTransaction    │
                    │  (immutable ledger)  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Reward.points       │
                    │  (cached balance)    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        Tier Calculation   Redemption     Notifications
        (lifetime pts)     (spend pts)    (earn/tier/expiry)
```

### 1. Point Transaction Ledger

Every point change becomes an immutable record. `Reward.points` stays as a cached balance for fast reads.

```python
class PointTransaction(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    customer_user = models.ForeignKey('customer_portal.CustomerUser', on_delete=models.CASCADE)
    
    amount = models.IntegerField()  # +50, -500, etc.
    balance_after = models.IntegerField()  # running balance
    
    TRANSACTION_TYPES = [
        ('repair_complete', 'Repair Completed'),
        ('referral_made', 'Referral Made'),
        ('referral_received', 'Referral Received'),
        ('milestone_bonus', 'Milestone Bonus'),
        ('early_pay_bonus', 'Early Payment Bonus'),
        ('review_bonus', 'Review Bonus'),
        ('tier_bonus', 'Tier Bonus'),
        ('manual_adjustment', 'Manual Adjustment'),
        ('redemption', 'Reward Redeemed'),
        ('expiration', 'Points Expired'),
    ]
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255)
    
    # Optional links to the thing that triggered it
    related_repair = models.ForeignKey('technician_portal.Repair', null=True, blank=True, on_delete=models.SET_NULL)
    related_redemption = models.ForeignKey('rewards_referrals.RewardRedemption', null=True, blank=True, on_delete=models.SET_NULL)
    related_payment = models.ForeignKey('billing.Payment', null=True, blank=True, on_delete=models.SET_NULL)
    
    # For expiration
    expires_at = models.DateTimeField(null=True, blank=True)
    expired = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer_user', '-created_at']),
            models.Index(fields=['tenant', 'transaction_type']),
            models.Index(fields=['expires_at'], condition=Q(expired=False, expires_at__isnull=False)),
        ]
```

**Central service method** — all point changes go through one function:

```python
class LoyaltyService:
    @staticmethod
    @transaction.atomic
    def award_points(customer_user, amount, transaction_type, description,
                     tenant=None, related_repair=None, related_payment=None,
                     related_redemption=None, created_by=None):
        """Single entry point for all point changes. Handles balance update,
        tier multiplier, transaction logging, and notifications."""
        
        # 1. Load LoyaltyConfig for this tenant
        # 2. Apply tier multiplier if applicable
        # 3. Lock and update Reward.points
        # 4. Create PointTransaction record
        # 5. Check for tier upgrade
        # 6. Send notification (async/non-blocking)
        # 7. Return the transaction
```

### 2. Configurable Point Rules

```python
class LoyaltyConfig(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE)
    
    # Earning rules
    points_per_repair = models.PositiveIntegerField(default=50)
    referral_bonus_referrer = models.PositiveIntegerField(default=500)
    referral_bonus_referred = models.PositiveIntegerField(default=100)
    milestone_5_bonus = models.PositiveIntegerField(default=250)
    milestone_10_bonus = models.PositiveIntegerField(default=500)
    milestone_25_bonus = models.PositiveIntegerField(default=1000)
    points_for_review = models.PositiveIntegerField(default=100)
    points_for_early_payment = models.PositiveIntegerField(default=25)
    
    # Program settings
    points_expiry_days = models.PositiveIntegerField(default=365,
        help_text="Days before points expire. 0 = never expire.")
    expiry_warning_days = models.PositiveIntegerField(default=30,
        help_text="Send warning email this many days before expiration.")
    tiers_enabled = models.BooleanField(default=False)
    program_name = models.CharField(max_length=100, default="Rewards",
        help_text="What to call the program ('Rewards', 'Loyalty Points', etc.)")
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    @classmethod
    def get_for_tenant(cls, tenant):
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj
```

Accessible from **Owner Portal → Settings → Loyalty Program**. Simple form, no code changes needed per shop.

### 3. Loyalty Tiers

```python
class LoyaltyTier(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='loyalty_tiers')
    
    name = models.CharField(max_length=50)  # "Bronze", "Silver", "Gold", "Platinum"
    min_lifetime_points = models.PositiveIntegerField()
    point_multiplier = models.DecimalField(max_digits=3, decimal_places=2, default=1.00,
        help_text="Point earning multiplier. 1.5 = earn 50% more points.")
    perks_description = models.TextField(blank=True,
        help_text="What this tier gets. Shown to customers.")
    badge_color = models.CharField(max_length=7, default="#2563eb")
    sort_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['sort_order', 'min_lifetime_points']
        unique_together = ['tenant', 'name']
```

**Tier logic:**
- Calculated from **lifetime points earned** (sum of all positive PointTransactions)
- Spending points doesn't demote you — once you hit Gold, you stay Gold
- Tier multiplier applies to future earnings (Gold at 1.5x means 50 pts/repair becomes 75)
- Default tiers created when shop enables the feature:

| Tier | Lifetime Points | Multiplier | Rough Meaning |
|------|----------------|------------|---------------|
| Bronze | 0 | 1.0x | Everyone starts here |
| Silver | 500 | 1.25x | ~10 repairs or 1 referral |
| Gold | 2,000 | 1.5x | Loyal repeat customer |
| Platinum | 5,000 | 2.0x | Fleet-level loyalty |

Shop owners can rename these, change thresholds, or add custom tiers.

**Why fleet managers care:** A fleet sending 50 trucks/year earns ~2,500 points just from repairs. They hit Gold tier, earning 1.5x, which accelerates them toward Platinum. It's a flywheel — the more they use you, the faster they earn, the more reason to stay.

### 4. Earning Actions

| Action | Default Points | Hook Location | Notes |
|--------|---------------|---------------|-------|
| Repair completed | 50 | `Repair.save()` (exists) | Configurable via LoyaltyConfig |
| Referral (referrer) | 500 | `ReferralService.process_referral()` (exists) | Configurable |
| Referral (referred) | 100 | `ReferralService.process_referral()` (exists) | Welcome bonus |
| Milestone: 5th repair | 250 | `award_completion_points()` (exists) | Configurable |
| Milestone: 10th repair | 500 | `award_completion_points()` (exists) | Configurable |
| Milestone: every 25th | 1,000 | `award_completion_points()` (exists) | Configurable |
| Pay invoice early | 25 | `Payment.save()` — **new hook** | Before due date |
| Leave a review | 100 | New endpoint — **new feature** | One-time per customer |
| Manual bonus | Variable | Owner dashboard — **new feature** | Requires reason (audit) |
| Tier multiplier | Varies | `LoyaltyService.award_points()` — **new** | Applied automatically |

### 5. Customer Experience

#### Points Balance (always visible)
Add to the customer portal nav bar: `⭐ 450 pts` or `Gold · 450 pts`

Clicking opens the loyalty dashboard:

**Loyalty Dashboard (customer portal)**
```
┌─────────────────────────────────────────────────┐
│  ⭐ Gold Tier                    450 points      │
│  ████████████████░░░░░  2,000 / 5,000 to Plat   │
│                                                  │
│  Perks: 1.5x point earnings, priority scheduling │
├─────────────────────────────────────────────────┤
│  Recent Activity                                 │
│  Mar 24  +75  Repair R-1234 completed  (1.5x)   │
│  Mar 20  +25  Invoice paid early                 │
│  Mar 18  +75  Repair R-1230 completed  (1.5x)   │
│  Mar 10  -500 Redeemed: 10% off next repair     │
│  Mar 05  +750 Referral: John D. signed up (1.5x)│
├─────────────────────────────────────────────────┤
│  Available Rewards                               │
│  ✅ 10% off next repair (200 pts)               │
│  ✅ Free chip repair (400 pts)                  │
│  🔒 Free full repair (800 pts) — need 350 more  │
├─────────────────────────────────────────────────┤
│  Your Referral Code: GOLD4XK2                    │
│  [Copy] [Share]                                  │
│  3 successful referrals · 1,500 pts earned       │
└─────────────────────────────────────────────────┘
```

#### Notification Emails

**Point Earned:**
> Subject: You earned 75 points! ⭐
>
> Your repair on Unit #4482 is complete. You earned **75 points** (Gold tier: 1.5x bonus!). Your balance is now **450 points**.
>
> [View My Rewards →]

**Tier Upgrade:**
> Subject: You've reached Gold tier! 🏆
>
> Congratulations! You've earned over 2,000 lifetime points with [Shop Name] and are now a **Gold** member.
>
> **Your perks:** 1.5x point earnings on every repair, priority scheduling
>
> [View My Rewards →]

**Expiration Warning:**
> Subject: 200 points expiring in 30 days
>
> You have **200 points** that will expire on April 24, 2026. Redeem them before they're gone!
>
> [Browse Rewards →]

### 6. Owner Dashboard

**Settings → Loyalty Program**
- Toggle program on/off
- Set point values for each action
- Configure expiration (days, 0 = never)
- Enable/disable tiers
- Customize tier names and thresholds

**Dashboard → Loyalty Widget**
- Total points issued (lifetime)
- Total points redeemed
- Total points outstanding (liability)
- Active customers with points
- Recent redemptions needing fulfillment

**Customers → [Customer] → Loyalty Tab**
- Current balance, tier, lifetime earned
- Transaction history
- Manual adjustment button (with required reason)

---

## Implementation Plan

### Phase 1: Foundation (3-4 days)
**Goal:** Transaction ledger + configurable rules. Everything backwards-compatible.

- [ ] `PointTransaction` model + migration
- [ ] `LoyaltyConfig` model (per-tenant) + migration  
- [ ] `LoyaltyService.award_points()` — central point management
- [ ] Refactor `award_completion_points()` to use LoyaltyService + read from LoyaltyConfig
- [ ] Refactor `ReferralService.process_referral()` to use LoyaltyService + read from LoyaltyConfig
- [ ] Backfill: migration that creates PointTransaction records from existing `Reward.points` balances
- [ ] Customer points history API endpoint
- [ ] Points balance in customer portal nav
- [ ] Tests for all point flows (earn, spend, balance, backfill)

### Phase 2: Engagement Hooks (2-3 days)
**Goal:** More ways to earn + notifications.

- [ ] Early payment bonus: hook into `Payment.save()`, check if `payment_date <= invoice.due_date`
- [ ] Review bonus: simple endpoint, one-time flag per customer (Phase 3: wire to Review Request `status='reviewed'`)
- [x] Manual point adjustment: `POST /owner/loyalty/customers/<id>/adjust/` with required `reason` — CODE-197
- [ ] Point earn notification email (branded HTML via `send_branded_email`)
- [x] Expiration management command (`expire_loyalty_points`) — CODE-197
- [ ] Expiration warning email (X days before) — requires email infra
- [ ] Owner settings page for LoyaltyConfig
- [x] `reconcile_loyalty_balances` nightly management command — CODE-197
- [x] `GET /owner/loyalty/liability/` point liability report — CODE-197

### Phase 3: Tiers (2-3 days)
**Goal:** Status and recognition for loyal customers.

- [ ] `LoyaltyTier` model + migration
- [ ] Default tier seeding (Bronze/Silver/Gold/Platinum) on enable
- [ ] Tier calculation: sum of positive PointTransactions
- [ ] Point multiplier applied in `LoyaltyService.award_points()`
- [ ] Tier badge in customer portal (nav + dashboard)
- [ ] Tier progress bar (points toward next tier)
- [ ] Tier upgrade notification email
- [ ] Owner tier configuration page (custom names, thresholds, multipliers)

### Phase 4: Dashboards & Polish (1-2 days)
**Goal:** Visibility for owners and customers.

- [ ] Customer loyalty dashboard (balance, history, rewards, referral code)
- [ ] Owner loyalty widget on main dashboard
- [ ] Owner per-customer loyalty view (balance, history, manual adjust)
- [ ] Point liability report
- [ ] Redemption queue improvements

---

## Technical Notes

### Backwards Compatibility
- Existing `Reward.points` field stays — used as cached balance for fast reads
- `Reward.points` is updated atomically inside `LoyaltyService.award_points()`
- All existing referral/redemption flows continue working
- New `PointTransaction` records are additive — no existing data is modified
- Shops that don't configure `LoyaltyConfig` get sensible defaults (same as current hardcoded values)

### Performance
- `PointTransaction` is append-only, indexed on `(customer_user, -created_at)` for fast history
- Tier calculation can be cached on `Reward` model (updated on each transaction)
- GSI on `(tenant, transaction_type)` for owner analytics queries
- Balance reads stay O(1) via `Reward.points` cache

### Multi-Tenant Safety
- All queries scoped to tenant (same pattern as billing, repairs, etc.)
- `LoyaltyConfig` is per-tenant — shops can't see or affect each other's programs
- `LoyaltyTier` is per-tenant — custom tiers per shop
- Manual adjustments require `created_by` user — full audit trail

---

## Competitive Landscape

| Feature | RS Systems (proposed) | Glassbot | ClearPro | Generic CRM |
|---------|----------------------|----------|----------|-------------|
| Points per repair | ✅ Configurable | ❌ | ❌ | ❌ |
| Referral program | ✅ Built-in | ❌ | ❌ | Plugin |
| Tiers | ✅ Custom per shop | ❌ | ❌ | ❌ |
| Invoice integration | ✅ Auto-discount | ❌ | ❌ | ❌ |
| Customer dashboard | ✅ | ❌ | ❌ | ❌ |
| Multi-tenant | ✅ Each shop configures own | N/A | N/A | N/A |

No glass shop SaaS has this. The closest is generic CRM plugins that don't understand repairs, invoices, or fleet dynamics.

---

## Scope & Risk

| Aspect | Assessment |
|--------|-----------|
| **Total effort** | ~2 weeks across all phases |
| **Phase 1 effort** | 3-4 days |
| **Risk** | Low. Additive — no existing behavior changes. |
| **Migration risk** | Low. Backfill is read-only on existing data, creates new records. |
| **Breaking changes** | None. Existing points, referrals, redemptions continue working. |
| **Dependencies** | None. Uses existing email + notification infrastructure. |

## Pricing Angle

| Plan | Loyalty Features |
|------|-----------------|
| **Starter** | Basic points + referrals (current behavior, configurable values) |
| **Professional** | + Tiers, early payment bonus, review bonus, expiration |
| **Enterprise** | + Custom tier names, advanced analytics, API access |

## Decision Needed
1. Approve Phase 1 (foundation + transaction ledger)?
2. Tiers: base plan or Pro feature?
3. Point expiration: default 365 days or never?
4. Program branding: let shops name it ("Rockstar Rewards", "Fleet Points")?
