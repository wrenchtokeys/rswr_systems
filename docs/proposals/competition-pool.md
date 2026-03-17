# Proposal: Competition Pool

**Status:** DOCUMENTED — Future build (after Stripe Connect Phases 1-3)
**Date:** 2026-03-17
**Requested by:** Drake

## Concept

Platform fees collected from invoice payments + a configurable % of subscription payments accumulate in a monthly pool. At month-end, the pool is distributed to shops based on verified repair count — rewarding the most active, legitimate shops.

## Revenue Sources → Pool

| Source | Configurable? | Default |
|--------|--------------|---------|
| Platform fee on invoice payments (% of each charge) | Yes, via admin | 0% |
| % of subscription payments | Yes, via admin | 0% |

Both feed into the same monthly pool. Admin controls each independently.

## Distribution Rules

### Ranking: Verified Repairs / Month
- Only COMPLETED repairs with photographic evidence count
- Repairs must have: at least 1 before photo, 1 after photo, VIN or unit number
- Repairs flagged as suspicious don't count (see anti-cheat below)

### Payout Structure (configurable via admin)
Option A — Top N split:
- 1st place: 40% of pool
- 2nd place: 30%
- 3rd place: 20%
- 4th-5th: 5% each

Option B — Pro-rata:
- Pool split proportionally by verified repair count
- Shop with 50 repairs out of 200 total = 25% of pool

Option C — Tiered bonus:
- Hit 50 verified repairs: flat $X bonus
- Hit 100: bigger bonus
- Unlimited tiers, admin-configurable

Drake decides which model. All configurable from admin dashboard.

### Minimum Thresholds
- Shop must have ≥10 verified repairs to qualify (configurable)
- Shop must have active subscription (no free tier or expired)
- Shop must have active Stripe Connect (to receive payout)

## Anti-Cheat / Verification System

This is the hard part. Shops are incentivized to inflate repair counts. Here's a layered defense:

### Layer 1: Photo Requirements
- Before/after photos required to count as "verified"
- Photos must have EXIF data with timestamp (or upload timestamp within X hours of repair date)
- Same photo can't be reused across repairs (perceptual hash comparison)

### Layer 2: Statistical Anomaly Detection
- Flag shops with sudden spikes in repair count (e.g., 3x their usual monthly volume)
- Flag shops where repair timestamps cluster suspiciously (20 repairs in 1 hour)
- Flag shops where all repairs have identical cost / same vehicle info
- Flag shops where repair-to-photo time ratio is unrealistic (repair logged at 2am, photo at 2:01am, next repair at 2:02am)

### Layer 3: VIN / Unit Validation
- If VIN provided: validate format, check for duplicates across short timeframe
- Same VIN repaired 5 times in a month = suspicious
- Unit numbers from fleet customers cross-referenced with customer records

### Layer 4: Customer Confirmation (optional, future)
- Customer portal shows their repairs — they can flag "I didn't have this repair done"
- Fleet managers see all repairs for their fleet — unusual ones stand out
- This is passive detection, not a gate

### Layer 5: Manual Review (admin)
- Admin dashboard: flagged repairs with reason
- Admin can: verify, reject, or suspend shop from competition
- Three-strike system: 3 rejected repairs in a month = disqualified for that month

### Punishment for Bad Actors
- **Strike 1:** Warning + flagged repairs removed from count
- **Strike 2:** Disqualified from current month's pool
- **Strike 3:** Suspended from competition for 3 months
- **Egregious fraud:** Permanent ban from competition + possible account termination

All actions logged with admin who took them + timestamp (audit trail).

## Admin Dashboard Controls

```
Competition Pool Settings:
  [x] Competition pool enabled
  Default platform fee: [2.0] %
  Subscription pool contribution: [5.0] %
  
Distribution:
  Model: [Pro-rata / Top N / Tiered] dropdown
  Minimum repairs to qualify: [10]
  Payout day: [1st of month]
  
Anti-Cheat:
  [x] Require before/after photos
  [x] Require VIN or unit number  
  Photo reuse detection: [Enabled]
  Anomaly spike threshold: [3.0x] monthly average
  Min time between repairs: [15] minutes
  
Manual Review Queue:
  [View flagged repairs →]
  
History:
  [View past pool distributions →]
```

## Payout Mechanics

### How does money get to winners?
Option A: Stripe Transfer
- Use `stripe.Transfer.create(destination=shop_account_id, amount=pool_share)`
- Money moves from platform account to connected accounts
- Clean, automated, auditable

Option B: Subscription Credit
- Instead of cash, apply credit to next month's subscription
- Simpler (no transfer mechanics) but less exciting

Recommend Option A — real money is more motivating than credits.

### Monthly Cycle
1. Month ends → freeze repair counts
2. Run verification (auto-flag anomalies)
3. Admin reviews flagged items (grace period: 3 business days)
4. Calculate distribution
5. Execute Stripe transfers
6. Email each shop their ranking + payout
7. Update leaderboard

## Data Model (Sketch)

```python
class CompetitionMonth(models.Model):
    month = DateField()  # First of month
    pool_amount = DecimalField()  # Total pool for this month
    fee_contribution = DecimalField()  # From platform fees
    subscription_contribution = DecimalField()  # From subscription %
    status = CharField()  # accumulating, frozen, reviewing, distributed
    distributed_at = DateTimeField(null=True)

class CompetitionEntry(models.Model):
    competition = ForeignKey(CompetitionMonth)
    tenant = ForeignKey(Tenant)
    verified_repairs = IntegerField()
    flagged_repairs = IntegerField()
    rank = IntegerField(null=True)
    payout_amount = DecimalField(null=True)
    payout_transfer_id = CharField(blank=True)  # Stripe transfer ID
    status = CharField()  # qualified, disqualified, paid

class RepairFlag(models.Model):
    repair = ForeignKey(Repair)
    reason = CharField()  # duplicate_photo, timestamp_anomaly, vin_reuse, volume_spike
    auto_flagged = BooleanField(default=True)
    reviewed_by = ForeignKey(User, null=True)
    resolution = CharField()  # pending, verified, rejected
    resolved_at = DateTimeField(null=True)
```

## Future Enhancements
- Public leaderboard (opt-in) for marketing
- Monthly email blast: "Top 10 shops on RS Systems this month"
- Badge system in customer portal: "Gold Verified Shop — 100+ repairs"
- API for shops to display their ranking on their own website

## Dependencies
- Stripe Connect Phases 1-3 must be complete first
- Photo upload system already exists (repair photos)
- EXIF parsing: may need a library (Pillow can read EXIF)
- Perceptual hashing: imagehash library or similar

## Timeline Estimate
- Core pool mechanics + admin dashboard: ~5-7 days
- Anti-cheat Layer 1-2 (photos + anomaly detection): ~3-4 days
- Anti-cheat Layer 3 (VIN validation): ~2 days
- Stripe transfer payouts: ~2-3 days
- Testing: ~3-4 days
- **Total: ~15-20 days**
