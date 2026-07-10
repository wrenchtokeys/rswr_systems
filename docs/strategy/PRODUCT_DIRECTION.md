# RS Systems — Product Direction (Mid-2026)

**Document Purpose:** Where the platform stands as of June 2026 and the recommended direction for the next 90 days.

**Last Updated:** June 12, 2026
**Status:** Proposed — pending Drake's review
**Supersedes nothing** — complements `docs/development/ROADMAP.md` (roadmap + feature backlog; absorbed the former `docs/TODO.md`) and `BILLING_ROADMAP.md` (billing phases, now largely complete).

---

## Executive Summary

RS Systems is no longer an MVP. As of v2.10+ the platform is a production-ready, multi-tenant SaaS with complete billing (Stripe invoicing, SaaS subscriptions, Connect payouts), tenant isolation hardened across ~265 tracked CODE-XXX fixes, soft-delete with restore, warranty claims, loyalty points through Phase 2, and a 331-test suite with per-bug regression coverage.

The last three months were dominated by **stabilization**: tenant-isolation sweeps, mobile UX fixes, batch invoicing correctness, and data-integrity hardening. That work has paid off — the codebase is clean, there are almost no TODOs in code, and velocity is high.

**The recommended pivot: shift from hardening to growth.** The platform is solid enough to support customer acquisition, but three things stand between here and growth:

1. **Nothing brings new shops in** — no lead-capture widget, no review engine, no trial-conversion nudges.
2. **Two operational gaps block adoption at some shops** — no scheduling/calendar and no estimates/quotes workflow.
3. **Production observability is one env var away** — Sentry is wired but not enabled; there is no CI.

The 90-day plan below sequences these as: **growth quick wins → operational gaps → engagement depth**, with platform health items threaded throughout as small, parallel tasks.

---

## Where We Are

### Shipped and stable (do not revisit)

| Area | Status |
|------|--------|
| Multi-tenant isolation | Complete; middleware-enforced, regression-swept (v2.7) |
| Billing & invoicing | Complete; batch invoices, aging, overdue automation, sales tax |
| Stripe (all three legs) | Invoice payments live, SaaS subscriptions live, Connect live |
| Subscription enforcement | Trial/grace/blocked flows, plan limits, dunning (v2.3–2.5) |
| Repair workflow | Queue statuses, multi-break batches, progressive pricing, auto-assignment |
| Customer portal | Approvals, requests, invitations, payments, warranty claims |
| Loyalty | Phases 1–2 shipped (points, redemption, reconciliation, liability report) |
| Warranty | Phase 1 shipped (policies, claims, invoice terms) |
| Soft delete | Repairs & invoices, 30-day restore, purge protection (CODE-258) |
| Security | Throttling, audit logging, IDOR sweeps, CAPTCHA, email normalization |
| SEO foundation | Meta/OG tags, structured data, sitemap (CODE-261) |

### Known gaps (the raw material for this plan)

- **Acquisition/retention features designed but unbuilt:** review request system, website widget, trial-expiry email campaign — all have written proposals in `docs/proposals/`.
- **Operational features missing entirely:** scheduling/calendar, estimates/quotes, customer communication log — flagged in `docs/development/ROADMAP.md` ("Absorbed from TODO.md" section), no proposals yet.
- **Engagement features mid-flight:** loyalty Phases 3–4 (tiers, dashboards), warranty Phase 2, Stripe Connect Phase 3 dashboard.
- **Platform health debt:** Sentry needs only `SENTRY_DSN` set in EB; Tailwind still loads from CDN in production; no CI pipeline; 8 pre-existing test failures; customer portal has ~16 tests covering 30+ views.
- **Stale docs:** `BILLING_ROADMAP.md` still lists Phase 7 webhook work and the `STRIPE_WEBHOOK_SECRET` blocker as open, but both shipped in February–March. Needs a status pass.

---

## Strategic Read

Development since March has been almost entirely inward-facing (correctness, isolation, polish). That was the right call — you can't grow on a leaky foundation — but the foundation is now solid and the marginal return on more hardening is low.

The product's constraint has moved from **"is it safe to put shops on this?"** (yes) to **"how do shops find it, convert, and stick?"** Every dollar of engineering should now answer one of:

1. **Acquisition** — does it bring a shop to the signup page?
2. **Conversion** — does it turn a trial into a paying tenant?
3. **Adoption** — does it remove a reason a shop says "this doesn't fit how we work"?
4. **Retention** — does it make a paying shop stickier?

Scheduling and quotes are *adoption* features: their absence is the kind of thing that loses a sale in the first demo. The review system and website widget are *acquisition* features — and notably, they also help RS Systems' own tenants grow their businesses, which is the strongest retention story a B2B SaaS can tell.

---

## The 90-Day Plan

### Phase A — Growth quick wins (weeks 1–4)

All three are designed, small, and compound with each other.

1. **Trial expiration email campaign** (~1 week)
   Alerts at 7d/3d/1d before expiry, day-of, and win-back at 7d/30d after. The `check_subscription_alerts` command and EB cron infrastructure already exist — this extends a proven pattern. Directly attacks trial churn, which is the cheapest revenue available.

2. **Review request system** (~1–2 weeks)
   Smart Google-review requests after repair completion, throttled by customer type. Proposal: `docs/proposals/review-request-system.md`. Helps every tenant's own marketing — high perceived value, strong retention story.

3. **Website integration widget** (~2–3 weeks)
   Embeddable quote-request form for shop websites that auto-creates customers and repair requests. Proposal: `docs/proposals/website-integration-widget.md`. This is the platform's first lead-generation feature and a differentiator in sales conversations.

**Parallel platform-health tasks (each < 1 day, do alongside Phase A):**
- Set `SENTRY_DSN` in EB — observability before shipping new surface area.
- Replace Tailwind CDN with a production build step.
- Fix the 8 pre-existing test failures so the suite is green before new work lands on it.
- Update `BILLING_ROADMAP.md` statuses (Phase 7 complete, webhook secret resolved).

### Phase B — Close the adoption gaps (weeks 4–10)

These need proposals written first (none exist yet). Write the proposal, get sign-off, then build.

4. **Estimates / quotes workflow** (~2–3 weeks)
   Quote → customer approval → convert to repair. The approval machinery already exists in the customer portal; this is a new `Quote` model plus a conversion path, not a new subsystem. Recommended **before** scheduling because it reuses more existing infrastructure and unblocks shops whose insurance/fleet workflows require formal estimates.

5. **Scheduling / calendar — minimum viable version** (~3–4 weeks)
   Start with a daily/weekly calendar of assigned repairs per technician — *not* route optimization or time-slot booking (those go to Later). The auto-assignment system already knows who is doing what; the first version is largely a view over existing data plus a scheduled date/time field.

6. **Customer communication log** (~1–2 weeks, can interleave)
   A simple per-customer timeline of calls/texts/notes. Small CRUD feature, high day-to-day value for owners, and a natural foundation for the proposed invoice email tracking later.

**Parallel test-debt task:** before or during Phase B, add integration tests for the untested customer portal views (payment flow, invoice detail, repair approval). New quote/approval work will build directly on these views — test them first.

### Phase C — Engagement depth (weeks 10–13)

7. **Loyalty Phase 3: tiers** (~1.5–2 weeks) — Bronze/Silver/Gold/Platinum multipliers, Pro-plan-only. This is also a plan-upgrade incentive, which makes it a monetization feature, not just engagement.
8. **Loyalty Phase 4: dashboards** (~1.5–2 weeks) — customer-facing balance/history, owner analytics with point liability.
9. **Stripe Connect Phase 3 dashboard** (~1 week) — payout history, balance, fee reporting. Backend exists; this is UI.

### Later / deliberately deferred

- **Warranty Phase 2** (per-customer overrides, goodwill flag) — Phase 1 covers the common case; revisit when a tenant asks.
- **Repair form efficiency, reward redemption UX, customer billing preferences** — good incremental UX work; batch a polish sprint after Phase C.
- **AI plan recommendation, AI email assistant, competition pool, invoice email tracking** — interesting, but none answer acquisition/conversion/adoption as directly as the items above.
- **Route optimization / time-slot booking** — wait until the basic calendar proves demand.
- **CI/CD pipeline** — valuable, but with one developer and a disciplined test culture it's lower leverage than shipping; slot it when a second contributor appears or after Phase B.
- **Clawdbot** — still an experimental proxy over canonical billing endpoints. Decide by end of Phase B: either document its transition plan or remove it to avoid double-maintenance.

---

## Risks & Watch Items

| Risk | Mitigation |
|------|------------|
| Customer portal test gap (~16 tests / 30+ views) meets new quote/approval features | Test existing views before Phase B builds on them |
| Trial expiry hard-block with no data export could anger churned trials | Pair the email campaign with at least a CSV export on the blocked page |
| Widget opens a public, unauthenticated write path | Proposal must cover rate limiting, CAPTCHA (already used at signup), and tenant-scoped tokens; run `security_audit` before launch |
| Scheduling scope creep (routes, slots, drag-and-drop) | Ship the read-mostly calendar first; expand only on tenant pull |
| Stale roadmap docs mislead future planning sessions | Fold the doc-status pass into Phase A |

---

## Success Criteria (how we'll know this worked)

By mid-September 2026:

- Trial → paid conversion measurably improved (baseline it now from existing tenant data before the email campaign ships).
- At least one tenant embedding the website widget and receiving leads through it.
- Review requests sending in production with tenant opt-in.
- A shop can run its day from the calendar view and send a quote without leaving the platform.
- Sentry receiving production errors; test suite green.

---

## Document History

| Date | Change |
|------|--------|
| 2026-06-12 | Initial version — post-stabilization direction for Q3 2026 |
