# Feature-to-Plan Tier Matrix

> **Note:** The plan/price table in the root [README.md](../README.md#subscription-plans) is canonical for prices and limits; this doc is what each tier actually gates.

**Last updated:** 2026-09-02 (reduced to what the code enforces — see History)
**Purpose:** The truthful answer to "what do I get on each plan." A proposal that wants a
feature tier-gated adds a row here **and** the enforcement in the same PR; a row without
enforcement is a promise the product does not keep, which is what this file was until
September 2026.

---

## What each plan enforces today

Source of truth: `apps/tenants/management/commands/seed_plans.py` for the numbers,
`apps/tenants/services/usage_service.py` for the checks.

| | Trial (30 days) | Starter $49 | Pro $99 | Enterprise $249 |
|---|---|---|---|---|
| **Jobs per month** | 50 | 200 | Unlimited | Unlimited |
| **Technicians** | 2 | 5 | 15 | Unlimited |
| **Customers** | 10 | 50 | Unlimited | Unlimited |
| **Photo storage** | 100 MB | 500 MB | 2 GB | 10 GB |
| **Custom branding** (logo + brand colour on portal, emails, invoice PDF) | — | — | ✅ | ✅ |

How each is enforced:

- **Jobs per month** — `UsageService.can_create_repairs(n)` at every creation path
  (batches must pass the count, not call the binary check). Counted per calendar month.
- **Technicians / customers** — `can_add_technician()` / `can_add_customer()` at creation;
  `check_against_plan()` pre-flights a downgrade so a shop cannot drop below what it uses.
- **Photo storage** — `calculate_storage_mb()` is **reported** on the plan page and in the
  usage summary; **nothing blocks an upload when the limit is reached.** Treat the number
  as a display until someone decides it should gate.
- **Custom branding** — `Tenant.branding_enabled` → `has_feature('custom_branding',
  plans=('pro', 'enterprise'))`. The uploaded logo and colour are kept on every plan; they
  render only when the plan includes the feature. **This is the only feature flag the
  application reads.**

## Flags in the seed that gate nothing — a decision, not a deletion

`seed_plans.py` also carries `invoicing`, `customer_portal`, `rewards`, `api_access`,
`priority_support` and a `support` label. `Tenant.has_feature`'s docstring is explicit
that none of them is checked anywhere; the pricing page and plan cards *display* them.

| Flag | Seeded | Reality | Decision needed |
|---|---|---|---|
| `invoicing`, `customer_portal` | True on all four plans | Core product; every shop has both | None — display-only is fine, but a DB seeded before these keys existed renders the row as "not included" (`IMPROVEMENT_SESSIONS.md` C2). Verify on prod |
| `rewards` | False on Trial, True elsewhere | **Deliberately not enforced.** Drake's call 2026-08-11: the free trial includes loyalty; hiding it from an evaluating shop costs the sale | None — record stands. Consider seeding it True on Trial so the card stops implying otherwise |
| `api_access` | Enterprise only | There is no public API: the DRF router exists, token auth was removed, only admin session auth remains | **Drake:** delete the row from the seed and the pricing table, or keep it as a stated roadmap item. Do not leave it as a tick |
| `priority_support` | Enterprise only | Nothing in code; the `support` label already says "Priority email support" on Pro and Enterprise | **Drake:** fold into the `support` label and drop the flag |

**What Enterprise buys beyond limits today: nothing.** It is Pro with unlimited technicians
and 10 GB. Either name what it adds (the direction review's candidates: multi-location,
roles beyond owner/manager, an API, priority support with an SLA) or rename the tier until
it does. Until then the plan card must not promise more than the row above.

## Features the previous version of this file gated that do not exist

Listed so nobody re-adds them from memory: Loyalty Tiers (Pro), automated review requests
as Pro-only (they shipped **ungated** on every plan), Website Widget with per-plan
submission caps, Warranty Claims Workflow as Pro-only (warranty shipped ungated), AI Email
Templates, Invoice Email Tracking as Pro-only (shipped ungated, PR #126), Competition Pool,
Per-Customer Warranty Overrides, Google Business API. If any of these is built, gating is a
product decision to make at that time, not a promise to carry in advance.

## How to update this document

1. A feature that should be paid-tier-only gets its `has_feature(...)` check **and** its row
   here in the same PR. `Tenant.has_feature(name, plans=(...))` is the one call to use.
2. A limit change edits `seed_plans.py` **and** the table above; `seed_plans --force` on
   prod is a deliberate step, never a side effect.
3. Downgrades must stay pre-flighted (`check_against_plan`) so no shop loses data it has.

## History

| Date | Change |
|---|---|
| 2026-03-25 | Initial matrix (Amelia) — aspirational, written before most rows existed. |
| 2026-09-02 | Reduced to what the code enforces (jobs, technicians, customers, storage-as-display, custom branding). The unenforced seed flags are listed as decisions for Drake rather than deleted. Named that Enterprise currently buys only limits. |
