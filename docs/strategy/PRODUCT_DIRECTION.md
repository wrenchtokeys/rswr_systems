# RS Systems — Product Direction (September 2026)

**Last updated:** 2026-09-18 (the 2026-09-17/18 readiness audit split step 6: **stranger-shop readiness** — three open PRs plus session **C3 · Findability** — comes before the selling, which is now step 7. The spine is on prod as of `8da23bbe`; the five insurance interviews stay dropped as a gate, and Path B waits for a paying customer to ask.)
**Status:** Path A with a B-ready spine — **decided. Signed off by Drake 2026-09-08** under
§The decision. Every session plans against it; changing it means editing that section, not
arguing with it in a PR.
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
get credentialed, what does an aggregator cost), not code. **Decided 2026-09-17: the five
dedicated insurance-shop interviews are no longer a gate.** They had sat "still not held" since
2026-08-07 because they answer a question nobody can act on this quarter, while the product has
no customer outside the family. The Path B evidence now comes from real prospects: every
trial-shop conversation asks the two questions that matter (how often does the insurer pay
short; would submitting from inside the software change what you buy) and the answers accrue
in `INSURANCE_SHOP_INTERVIEWS.md` §6. Path B is revisited when a paying customer asks for it.

*Sign-off:* Drake D. · date 09/08/2026. If you want this written differently, change this
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
  requests, SMS transport (dark pending toll-free registration v5, now scoped to staff notifications — see `docs/operations/SMS_REGISTRATION.md`), a report-only CSP, zero
  third-party asset hosts, a 16-minute suite with a committed baseline.
- **Nothing brings a stranger to the signup page.** The landing page is now honest (C1,
  live since 2026-09-07 00:59 UTC — real captures, founder note, no filler stats) but
  honest is not the same as found: there is no channel, no widget, no outreach. **And as of
  the 2026-09-18 audit, "found" is further off than this line implied** — the site is five
  indexable URLs, carries no analytics of any kind, hides 18 written guides behind a login,
  and renders no image when anyone shares it. Its one contact link was `@login_required`
  until #263. That is step 6 and session C3; step 7 is the outreach.
- **Production runs `8da23bbe` (deployed 2026-09-17 14:20 UTC)** — everything through #258;
  the four readiness PRs (#261, #262, #263, #265) and #260 are merged and not yet deployed. A shop can send a quote today. Customers' damage photos have not been
  world-readable since 2026-09-06 22:04 UTC. `ROADMAP.md` keeps that line current.

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
   **Update 2026-09-18 (PR #261, open):** the *form* is still his dad's to fill in, but the
   product's silence about it was ours. An unfinished Connect account is the day-one state of
   every shop, and nothing said so at either end: the customer portal's invoice list offered a
   "Pay Now" gated only on "is money owed", linking to a detail page that gated the actual
   card form on `Tenant.can_accept_payments` — so a fleet contact landed on a page whose only
   control was Download PDF, with no explanation. The owner was told nothing either: the setup
   checklist had eight items and no payments row, so a shop could reach "fully configured",
   invoice for a month, and never learn the money leg was unconnected. Both now read the one
   tenant property, and an unconnected shop can no longer show a full score. **This does not
   make the payment happen — it makes the product say why it hasn't.**
3. ~~**P8 — close the world-readable media bucket**~~ — **done 2026-09-06** (#248 deployed
   22:00 UTC, bucket policy narrowed 22:04 UTC; anonymous damage photo → 403). The
   photo-ML arc has no code left.
4. ~~**Landing-page credibility**~~ (`IMPROVEMENT_SESSIONS.md` C1) — **merged 2026-09-07
   00:16 UTC (`059fa77a`), deployed 00:59 UTC and verified on the live page.** Trust bar out, founder note under the hero, real captures of the app
   regenerated by `scripts/landing_shots.py`, a switching section. No public demo login
   (Drake's call, separate session).
5. **The three spine features, one session each** — **unblocked 2026-09-08** when the
   sign-off line was filled. Order is B3 (quote → job, **PR #253 merged 2026-09-12, deployed 2026-09-14**), then
   B5 (Tier 1 claim tracking, **built 2026-09-16, PR #255**), then B6 (price book, **built 2026-09-16, PR #257**). **All three are on prod as of 2026-09-17 14:20 UTC (`8da23bbe`)**; `seed_price_book` was run and found nothing to read (no replacements on prod yet). **This step is closed.** Nothing else in this list is a session. One owner
   task sits beside it: read the live landing copy once (the switching section promises
   "send your customer list through the contact form" — a manual import by Drake).
6. **Stranger-shop readiness** — **added 2026-09-18, and it contradicts what step 6 used to
   claim.** A readiness audit ("can a shop that isn't family run on this yet?") walked all
   three dashboards on `main` @ `16c01e5b` and found four defects sitting directly on the path
   a stranger takes. Three are built and open: **#261** (the payments silence, step 2 above),
   **#262** (the trial permitted 10 customers and 50 jobs a month as hard blocks, beside a
   landing page inviting a shop to run RS Systems beside their old system for a month — raised
   to Starter's numbers on Drake's call), **#263** (the landing page's only contact link was
   `@login_required`, so it 302'd exactly the interested-but-not-signed-up owner the page was
   written for — fixed by the help center's H2; #264 built the same fix in parallel and was closed). The fourth is a session: **`IMPROVEMENT_SESSIONS.md` C3 · Findability** — the
   site is five indexable URLs, there is **no analytics of any kind**, 18 written guides sit
   behind a login, and no share of rssystems.io renders an image. **None of the four is
   deployed.** #265 (technician dashboard counts, closing A4) rode the same audit but is
   craft, not a blocker.
7. **Go-to-market**: three shops that are not family on the product.
   The five dedicated insurance-shop interviews were **dropped as a gate on 2026-09-17** (see
   §The decision); `INSURANCE_SHOP_INTERVIEWS.md` is kept as the discovery-call outline for
   trial shops (its sections 1, 2, 4 and 6) and as the place the two insurance questions'
   answers accrue.
   **This step used to read "which no code moves." That was wrong** — it was written from the
   sales motion, not from what a stranger's first hour actually touches. Step 6 is that
   correction. What remains genuinely code-free here is the selling: the calls, the trials, the
   two insurance questions. One owner task has no code either and should be done the day this
   is read: **verify rssystems.io in Google Search Console** (a DNS TXT record, no script, no
   CSP argument), so query data accrues while C3 is built.

**Parked, on purpose** — no user is waiting on them, and a fresh session must not pick
them up by default: the Font Awesome → `{% icon %}` sweep (1,217 call sites), enforcing the
CSP (S18b), and the repairable-or-not classifier (P5/P4b — negative class at zero, accruing
at zero; held open by Drake, ask before touching).

## Success criteria

Not features shipped. These are the only numbers that say the direction is working:

- **A shop that is not family pays.** One paying stranger by the end of Q4 2026.
- **Three non-family shops are on the product** (trial or paid) and one of them has sent a
  quote and turned it into a job.
- **Every trial-shop conversation records the two insurance answers** (short-pay frequency;
  would in-app submission change what they buy) in `INSURANCE_SHOP_INTERVIEWS.md` §6. Path B is
  decided from those, when there are enough of them — not from dedicated research calls.
  *(Replaced 2026-09-17; was "five insurance-shop interviews held and written up".)*
- **The Glass Guy has taken a card payment through RS Systems.**

## Document history

| Date | Change |
|---|---|
| 2026-09-18 | **Step 6 was wrong, and is now two steps.** "Go-to-market, which no code moves" was written from the sales motion; a readiness audit of all three dashboards found four defects on the path a stranger actually walks, three of them code. New step 6 (stranger-shop readiness) carries them — #261 payments silence, #262 trial limits, #263 public contact form, and `IMPROVEMENT_SESSIONS.md` **C3 · Findability** for the fourth, which is a session and is next. Selling moves to step 7, where the "no code" claim is true. Step 2 updated: the Connect form is still Drake's dad's to fill in, but the product's silence about it was ours. Nothing is deployed. |
| 2026-06-12 | Initial version — post-stabilization direction for Q3 2026 (90-day plan: growth quick wins → adoption gaps → engagement depth). |
| 2026-09-17 | **Go-to-market prep, and the interviews dropped as a gate.** C2 (pricing page audit) closed: prod plan data is correct, the label/seed defects fixed. `INSURANCE_SHOP_INTERVIEWS.md` written as a script — then, on Drake's call the same day, **the five dedicated interviews were removed from the success criteria**: they decide Path B, which nothing this quarter depends on, while the product has no non-family customer. The script stays as the trial-shop discovery call; the two insurance questions are asked on every prospect and Path B is revisited when a paying customer asks. Step 6 is now one thing: three non-family shops. |
| 2026-09-17 | **B5 and B6 on prod.** #258 (staff SMS) merged into `main` first because it was already live from a feature-branch deploy; `main` at `8da23bbe` deployed 14:20 UTC, health green, `technician_portal/0063` + `core/0035` applied, live routes answer. `seed_price_book` run on the instance: 0 rows — prod has no replacement records yet, the book learns from the first one. The spine is done; the head of the queue is step 6 (three non-family shops, five insurance interviews), not a session. |
| 2026-09-16 | **B6 built** (PR #257): a completed replacement teaches the shop's own price book what that glass on that vehicle costs; the next replacement on it fills its price in with a note saying where it came from; the owner sees, pins and rebuilds the book. Spine feature 3 — the last — is built. Next: merge and deploy #255 and #257 (then `seed_price_book` on prod), and go-to-market (step 6). |
| 2026-09-16 | **B5 built** (PR #255): a job marked "Insurance claim" makes its invoice a tracked claim; the owner records what the insurer actually sent and the claim reads short, paid or closed; the "Owed to you" card counts short-paid claims and claims waiting on an insurer separately. Spine feature 2 is done; B6 (price book) is the head of the queue. |
| 2026-09-14 | **B3 on prod.** PR #253 merged 2026-09-12 (`e47cd18b`), deployed 2026-09-14 15:11 UTC and verified (health green, `/quotes/` and the public quote route answer, both quote migrations applied). Spine feature 1 is done; B5 (Tier 1 claim tracking) is the head of the queue. |
| 2026-09-08 | **B3 built** (PR #253): a shop quotes the work, the customer accepts by emailed link or in the portal, the jobs are created approved at the locked price. First spine feature done the day the direction was signed; B5 is next. |
| 2026-09-08 | **Drake signed §The decision** (Path A with a B-ready spine). Step 5 is unblocked; B3 (quotes) starts the same day as its own session and PR. |
| 2026-09-07 | C1 deployed 00:59 UTC as `60b4563b` and verified live (trust bar gone, four captures serving). Steps 1–4 are on prod; nothing is merged and undeployed. Step 5 remains gated on the sign-off line. |
| 2026-09-07 | Step 4 (C1) merged (`059fa77a`, 00:16 UTC), not yet deployed. Steps 1–4 are closed; step 5 is the head of the queue and is gated on the sign-off line, which is still blank. Two owner tasks recorded beside it (deploy, read the landing copy). |
| 2026-09-06 | Step 4 (C1) built as PR #250: the HTML dashboard mock and the "500+ Jobs Tracked" bar are gone, replaced by captures of the real app (one command to re-take) and the founder's note directly under the hero; a switching section added. Next in order is step 5, which waits on the sign-off line — still blank. |
| 2026-09-06 | Step 3 (P8) closed: #248 merged + deployed 22:00 UTC, bucket policy narrowed 22:04 UTC. Next in order is C1 (landing credibility). Sign-off line still blank. |
| 2026-09-06 | Step 3 (P8) built as PR #248 — the application half; the bucket-policy edit is sequenced after its deploy and recorded as an ops step, not a session. Sign-off line still blank. |
| 2026-09-06 | Steps 1–2 of §What happens next closed: `main` deployed (`61273602`, 19:30 UTC) and The Glass Guy's Connect verified on prod + Stripe live — never onboarded, every requirement still due, 0 invoices. Recorded as an owner task, not a session; P8 promoted to the next code session. Sign-off line still blank. |
| 2026-09-02 | Rewritten to one page from the 2026-09-01 direction review. Records the Path A + B-ready-spine decision as a draft awaiting sign-off, scores the June plan, replaces feature-shipping criteria with strangers-paying criteria, and deletes the stale platform-health items (Sentry set 2026-08-09, Tailwind CDN gone since PR #160, suite baseline committed in #244). |
