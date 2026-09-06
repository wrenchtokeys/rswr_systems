# RS Systems — Product Direction (September 2026)

**Last updated:** 2026-09-02 (rewritten to one page from the 2026-09-01 direction review)
**Status:** Path A with a B-ready spine — **drafted, awaiting Drake's sign-off.** Until he
writes his name and a date under §The decision, treat it as the working assumption every
session plans against, not as a decision.
**Companions:** `IMPROVEMENT_SESSIONS.md` (the session backlog; its §1 is the fork this page
decides), `docs/development/ROADMAP.md` (long-horizon list), `docs/development/CHANGELOG.md`
(what actually shipped, dated). The June 2026 version of this document is summarised in
§The June plan, scored; nothing else from it survives.

---

## The decision

**Path A now, with a B-ready spine.** RS Systems is built for the 1–5 technician shop that
runs on sticky notes, texts and Excel, and competes against paper. It does **not** pursue
insurance/TPA EDI, NAGS licensing, multi-location or a public API in the next two quarters.
What it does build are the three things a medium shop asks about in its first demo that
need no licence and no clearinghouse — and each is the foundation Path B would stand on if
the interviews say to go there:

| # | Spine feature | Session | Why it is load-bearing |
|---|---|---|---|
| 1 | **A quote that converts to a job** | `IMPROVEMENT_SESSIONS.md` B3 | The product is job → invoice only. Fleet procurement and every insurance-adjacent workflow need a priced estimate first; today the shop writes it somewhere else and RS Systems is the second system |
| 2 | **Tier 1 insurance claim tracking** (no EDI): claim, status, expected vs received, short-payment reconciliation | `IMPROVEMENT_SESSIONS.md` B5 (promoted out of D1) | Insurance money arrives late and short. Knowing what is outstanding is where the daily pain is, and it is independent of how the claim was submitted |
| 3 | **A shop-owned price book** seeded from history | `IMPROVEMENT_SESSIONS.md` B6 (promoted out of D2) | The cheaper 80% of NAGS: vehicle/glass → this shop's price, no licence. Progressive repair pricing already proves the pattern |

Path B — becoming the system of record for shops doing insurance/TPA volume — is **not
rejected**; it is not decidable yet. Its gate is business development (can a shop this size
get credentialed, what does an aggregator cost), not code. The five insurance-shop interviews
`IMPROVEMENT_SESSIONS.md` asked for on 2026-08-07 are still the thing that decides it, and
nobody has held one.

*Sign-off:* ______ (Drake) · date ______. If you want this written differently, change this
section; every other doc points here rather than restating it.

## Where things stand (2026-09-02)

- **Users are two shops, both family**: Rockstar Windshield Repair and The Glass Guy
  (tenant 15). No third-party shop has signed up. The Glass Guy's Stripe Connect was still
  pending in mid-August; **if that is still true, the one real customer cannot take a
  payment, and confirming it outranks everything on this page.**
- **The foundation is real and is not the constraint.** All three Stripe legs with webhook
  durability, cron that runs, tenant isolation swept, soft delete, loyalty, warranty, review
  requests, SMS transport (dark until the toll-free number clears), a report-only CSP, zero
  third-party asset hosts, a 16-minute suite with a committed baseline.
- **Nothing brings a stranger to the signup page.** The landing page still shows the
  "500+ Jobs Tracked" trust bar and an HTML mock instead of screenshots.
- **Production runs `966a31da` (deployed 2026-08-31 23:46 UTC).** Seven PRs merged since
  (#238–#244) are on `main` and not deployed; `ROADMAP.md` keeps that line current.

## The June plan, scored

The June 2026 version of this document said "shift from hardening to growth" and set
criteria for mid-September. Here is how it went, so the misses are on record.

| June plan item | Status (2026-09-01) | What exists |
|---|---|---|
| Trial expiry email campaign | Partial | Lifecycle alerts (`check_subscription_alerts`); no post-expiry win-back sequence |
| Review request system | **Shipped** | Cron every 20 min, fleet gating, Google link-out |
| Website lead widget | Not started | Proposal from March, unreviewed |
| Quotes / estimates | Not started | No model; the flow is job → invoice only |
| Scheduling calendar | Partial | `scheduled_for`, day view, dispatch board, working hours; the S9–S14 UX arc is open |
| Customer communication log | Not started | Nothing |
| Sentry, self-hosted assets, green suite | **Done** | All three closed in August (the "8 pre-existing failures" figure was wrong twice over; the real number is ~93 with a committed baseline) |

What shipped instead, in rough order of effort: the UI overhaul (S1–S18a), field ops
(N1–N3, S1–S10), the photo-ML arc (P1–P7), billing hardening, the CSP, the test suite.
All good work; almost none of it is adoption or acquisition. That is the drift this page
corrects.

## What happens next, in order

1. **Deploy `main`** (Drake). `git checkout main && git pull` first — `eb deploy` ships the
   current branch's HEAD.
2. **Confirm The Glass Guy can take a payment** (read-only Connect check on prod). If not,
   that is the next session.
3. **P8 — close the world-readable media bucket** (`PHOTO_ML_SESSIONS.md`). A security fix,
   not a feature; ships right after P7 is on prod.
4. **Landing-page credibility** (`IMPROVEMENT_SESSIONS.md` C1): trust bar out, founder
   story up, real screenshots. Needs no decision.
5. **The three spine features, one session each**, after §The decision carries a name.
6. **Go-to-market, which no code moves**: three shops that are not family on the product,
   and the five insurance-shop interviews.

**Parked, on purpose** — no user is waiting on them, and a fresh session must not pick
them up by default: the Font Awesome → `{% icon %}` sweep (1,217 call sites), enforcing the
CSP (S18b), and the repairable-or-not classifier (P5/P4b — negative class at zero, accruing
at zero; held open by Drake, ask before touching).

## Success criteria

Not features shipped. These are the only numbers that say the direction is working:

- **A shop that is not family pays.** One paying stranger by the end of Q4 2026.
- **Three non-family shops are on the product** (trial or paid) and one of them has sent a
  quote and turned it into a job.
- **Five insurance-shop interviews held and written up**, with the Path B question
  answered on evidence: can we get credentialed, at what cost, and does it change their
  buying decision.
- **The Glass Guy has taken a card payment through RS Systems.**

## Document history

| Date | Change |
|---|---|
| 2026-06-12 | Initial version — post-stabilization direction for Q3 2026 (90-day plan: growth quick wins → adoption gaps → engagement depth). |
| 2026-09-02 | Rewritten to one page from the 2026-09-01 direction review. Records the Path A + B-ready-spine decision as a draft awaiting sign-off, scores the June plan, replaces feature-shipping criteria with strangers-paying criteria, and deletes the stale platform-health items (Sentry set 2026-08-09, Tailwind CDN gone since PR #160, suite baseline committed in #244). |
