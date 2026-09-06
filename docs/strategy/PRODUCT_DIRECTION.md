# RS Systems — Product Direction (September 2026)

**Last updated:** 2026-09-06 (C1 landing credibility built as PR #250; P8 closed earlier the same day)
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
  (tenant 15). No third-party shop has signed up. **The Glass Guy cannot take a payment
  (verified 2026-09-06, read-only, on prod and against Stripe live):** the Express account
  `acct_1U1J241qIkbmw59d` was created 2026-08-06 and the onboarding form was **never
  filled in** — `details_submitted=False`, every requirement still due (address, tax ID,
  representative, bank account, ToS). The shop has 0 invoices. **No code fixes this**; the
  owner resumes onboarding from Settings → Payments. It stays the top item, owned by Drake.
- **The foundation is real and is not the constraint.** All three Stripe legs with webhook
  durability, cron that runs, tenant isolation swept, soft delete, loyalty, warranty, review
  requests, SMS transport (dark until the toll-free number clears), a report-only CSP, zero
  third-party asset hosts, a 16-minute suite with a committed baseline.
- **Nothing brings a stranger to the signup page.** The landing page still shows the
  "500+ Jobs Tracked" trust bar and an HTML mock instead of screenshots.
- **Production runs `969a4035` (deployed 2026-09-06 22:00 UTC)** — everything through
  #248 (P8). Customers' damage photos are no longer world-readable as of 22:04 UTC.
  `ROADMAP.md` keeps that line current.

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

1. ~~**Deploy `main`**~~ — **done 2026-09-06** (prod `61273602`).
2. ~~**Confirm The Glass Guy can take a payment**~~ — **checked 2026-09-06: he cannot.**
   Onboarding was never completed (§Where things stand). Not a session — a form his dad
   fills in. Drake owns the nudge; nothing below waits on it.
3. ~~**P8 — close the world-readable media bucket**~~ — **done 2026-09-06** (#248 deployed
   22:00 UTC, bucket policy narrowed 22:04 UTC; anonymous damage photo → 403). The
   photo-ML arc has no code left.
4. ~~**Landing-page credibility**~~ (`IMPROVEMENT_SESSIONS.md` C1) — **built 2026-09-06,
   PR #250 open.** Trust bar out, founder note under the hero, real captures of the app
   regenerated by `scripts/landing_shots.py`, a switching section. No public demo login
   (Drake's call, separate session).
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
| 2026-09-06 | Step 4 (C1) built as PR #250: the HTML dashboard mock and the "500+ Jobs Tracked" bar are gone, replaced by captures of the real app (one command to re-take) and the founder's note directly under the hero; a switching section added. Next in order is step 5, which waits on the sign-off line — still blank. |
| 2026-09-06 | Step 3 (P8) closed: #248 merged + deployed 22:00 UTC, bucket policy narrowed 22:04 UTC. Next in order is C1 (landing credibility). Sign-off line still blank. |
| 2026-09-06 | Step 3 (P8) built as PR #248 — the application half; the bucket-policy edit is sequenced after its deploy and recorded as an ops step, not a session. Sign-off line still blank. |
| 2026-09-06 | Steps 1–2 of §What happens next closed: `main` deployed (`61273602`, 19:30 UTC) and The Glass Guy's Connect verified on prod + Stripe live — never onboarded, every requirement still due, 0 invoices. Recorded as an owner task, not a session; P8 promoted to the next code session. Sign-off line still blank. |
| 2026-09-02 | Rewritten to one page from the 2026-09-01 direction review. Records the Path A + B-ready-spine decision as a draft awaiting sign-off, scores the June plan, replaces feature-shipping criteria with strangers-paying criteria, and deletes the stale platform-health items (Sentry set 2026-08-09, Tailwind CDN gone since PR #160, suite baseline committed in #244). |
