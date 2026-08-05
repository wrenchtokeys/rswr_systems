# Loyalty Program Improvements

Status tracker for the loyalty/redemption improvement pass started 2026-08-04.
Analysis source: full read-through of `apps/rewards_referrals`,
`apps/technician_portal/hooks.py`, and the owner loyalty dashboard.

## Done (branch `feature/loyalty-redemption-management`)

### 1. Owner UI for reward options
Owners previously could not create/edit/deactivate `RewardOption`s without
Django admin, and `setup_simplified_rewards` deleted **all** options across
**all** tenants.

- `/owner/loyalty/` now has a "Rewards Customers Can Redeem" card:
  add / edit / hide-show / delete, all tenant-scoped, manager/owner-gated.
- Owner-facing "kind" (`percent` / `fixed` / `free` / `merch`) maps to the
  shared `RewardType` table via get_or-create on
  `(category, discount_type, discount_value)` — see `REWARD_KIND_MAP` and
  `_resolve_reward_type` in `apps/saas/views.py`.
- Delete on an option with past redemptions **deactivates** instead
  (`RewardRedemption.reward_option` is CASCADE — a hard delete would erase
  redemption history).
- `setup_simplified_rewards` now requires `--tenant <slug>`, only touches that
  tenant's options, and only deletes with an explicit `--reset`.

### 2. Cancel / refund path for redemptions
Previously a redemption burned points forever; even flipping status to
REJECTED in Django admin did not refund.

- `RewardService.cancel_redemption(redemption_id, tenant, cancelled_by, reason)`
  is the single sanctioned undo: refunds through the ledger with new
  transaction type `redemption_refund` (migration 0020), flips status to
  REJECTED, stamps processed_by/processed_at/notes.
- Guards: PENDING only; loyalty program must be active (award_points refuses
  to move points otherwise); if applied to a job, blocked when the job is
  COMPLETED or invoiced, else the application is cleared.
- Liability report + `get_lifetime_earned` treat refunds correctly (net
  against redeemed, excluded from earned).
- UI: owner dashboard "Open Redemptions" card (cancel & refund button), and a
  manager/owner-gated cancel button on the tech-portal reward fulfillment page
  (`/tech/reward-fulfillment/<id>/`, endpoint `cancel_redemption`).
- Tests: `tests/test_loyalty_management.py` (21 tests).

## Not done — future work

### 3. Silent auto-apply of pending redemptions (surprise factor)
`Repair.apply_available_rewards()` (`apps/technician_portal/models.py`)
consumes the customer's **oldest** pending discount redemption on any repair
completion and auto-fulfills it — a customer saving "50% off" for a big
replacement loses it on a $30 chip repair. Also
`RewardFulfillmentService.assign_technician` auto-assigns the least-loaded
tech to every redemption (including merchandise), which is mostly noise.

Proposal: replace silent auto-apply with a prompt on the completion form
("This customer has a pending 50%-off reward — apply it?"), or an opt-in shop
setting. Drop or simplify auto tech assignment.

### 4. Dead loyalty config / unawarded transaction types
`points_for_review`, `points_for_early_payment`, `tier_bonus`,
`early_pay_bonus`, `review_bonus` exist in `LoyaltyConfig` /
`PointTransaction.TRANSACTION_TYPE_CHOICES` but nothing ever awards them.
Either wire them (review bonus → review-request system; early-pay →
`billing.Payment`) or hide the config fields so owners aren't configuring
no-ops. Note `expiry_warning_days` is also unused (no warning email exists).

### 5. Half-used redemption statuses
`APPROVED` and `SCHEDULED` are in `REDEMPTION_STATUS_CHOICES` but nothing in
the app sets them — real flow is PENDING → FULFILLED (or REJECTED via cancel).
Either collapse the enum or build the approval step it implies.

### 6. Customer-side point ledger visibility
The portal shows redemption history but not the `PointTransaction` ledger
(`LoyaltyService.get_transaction_history` exists, unused by any customer
view). Showing "why my balance changed" (earned on job X / expired /
redeemed / refunded) would preempt disputes, especially with expiry on.

### Smaller notes
- Django admin status flips still bypass the refund path — admin should call
  `RewardService.cancel_redemption` or be documented as accounting-unsafe.
- `RewardType` remains a shared (non-tenant) table; fine as a lookup, but shop
  edits to a shared row would leak across tenants — the owner UI deliberately
  only ever get_or_creates, never edits, RewardType rows.
- Referral leaderboard (`/referral-leaderboard/`) is portal-user based and
  predates customer-anchored loyalty; counts may mislead for multi-user
  companies.
