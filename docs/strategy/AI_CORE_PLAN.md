# AI Core Plan — the four tools we build, and what we cut

**Created:** 2026-10-13
**Author:** Claude (planning session with Drake)
**Status:** proposed cut of `AI_SESSIONS.md`. Nothing built. **This page decides what gets
built; `AI_SESSIONS.md` stays the full spec** (§0 ground rules, prompts, schemas, tests) for
anything kept, and the record of everything considered. When a row here changes status,
change the matching row there in the same commit.
**Companions:** `AI_SESSIONS.md` (the ranked queue this trims — read its §0 before building
anything here), `PRODUCT_DIRECTION.md` (step 7 is the current step; this plan is the
smallest AI set that serves it).

---

## Why a cut

The queue has ten sessions and three decisions. All three decisions stand (text may go to the
Claude API, photos never leave; RS Systems pays, bundled; suggest-never-apply). What the
queue does not do is say *stop*. Eight TODO rows is a quarter of work for a product with two
family shops on it, and the ranking rule already answers which of them matter: **does it help
a shop that is not family sign up, switch, and pay in Q4 2026?**

Three of the ten answer that question directly. One more answers the daily pain
`PRODUCT_DIRECTION.md` names. The rest are good ideas for a product with twenty shops. This
page keeps four, defers five behind a named condition, and cuts the rest with the reason
written down so nobody re-proposes them in a fresh session.

The second test is Drake's bar from `simplicity-first`: his dad has to understand what the
button does without being told it is AI. Anything that needs a settings page to explain
itself fails that test, and several trims inside the kept sessions come from it.

## The decision table

| # | Session | Was | Now | One-line reason |
|---|---|---|---|---|
| AI0 | Spine | TODO, M | **BUILD**, S–M (trimmed) | Everything else needs it. Trimmed to one model setting, one platform cap, no admin page |
| AI1 | Just say the job | TODO, M | **BUILD**, M (trimmed) | The parking-lot demo. Job form + quick-add only; portal and notes dictation deferred |
| AI2 | Paste anything | TODO, M | **BUILD**, M (trimmed) | Removes the reason a shop says "later". CSV and pasted text only |
| AI4 | Short-pay detective | TODO, M | **BUILD**, M | The daily pain the direction page names; B5 tracks the gap, this explains it |
| AI3 | Describe it | TODO, M–L | **DEFER** until a non-family shop has a website to put it on | The lead channel for leads we do not have yet. Embed cut outright |
| AI6 | Draft a reminder | TODO, S | **DEFER** until AI4 ships | Fine, small, not acquisition. AI6b (template writer) cut |
| AI7 | Replacement pre-flight | TODO, S | **DEFER** until The Glass Guy logs replacements on the platform | Zero replacement rows on prod; nobody to be right for yet |
| AI5 | Morning brief | TODO, S | **DEFER** until a non-family shop is on a paid plan | Retention for shops we are still acquiring. Prod cron has been missing since 2026-09-27; do not add a job to it yet |
| AI8 | Ask your shop | TODO, M | **CUT** | Generic, highest isolation surface in the product, global search covers the half owners use |
| AI9 | Text it in (was: forward an email) | PARKED, L | **DEFER** until SMS v6 is approved and an inbound path exists | Reframed from email to SMS at Drake's call (2026-10-13). Staff texting a job in is clean under v6; customers texting in waits on B2 |
| AI10 | Fleet health | PARKED, M | **CUT** | Needs months of a stranger fleet's history; when it exists it is a sentence in AI5, not a session |

**Build order:** AI0 → AI1 → AI2 → AI4. Four PRs. AI1's schema carries `scheduled_for` from
the start (see its Keep list) so AI9 is a transport on top of it, not a second parser. AI1 and AI2 are the selling; AI4 is the
first thing that makes a medium shop's eyes widen in a demo of the claim page.

**Where this sits against step 7:** unchanged from the queue. The plan is behind step 7
unless Drake promotes AI1 and AI2 as the demo, and that is recorded in
`PRODUCT_DIRECTION.md` §Parked, not here.

---

## What we keep, and what is trimmed inside each

Every kept session is built exactly as written in `AI_SESSIONS.md` **except** the trims below.
A trim is a line removed from scope, not a change to the ground rules.

### AI0 · Spine

Keep: `common/ai.py` with `is_enabled()`, `complete()`, the photo guard, the tenant guard,
the `AiCall` row per call, structured outputs with enums built from the model choice lists,
prompt caching on the system block, `anthropic` pinned as the only new dependency,
`tests/test_ai_boundary.py` in the guard set.

Trim:

- **One model setting, not two.** `AI_DEFAULT_MODEL` only. `AI_FAST_MODEL` is added in the
  session that first proposes Haiku with numbers in its Notes, not before.
- **One cap, platform-wide.** `PlatformConfig.ai_monthly_cap_cents` with a default; no
  `Tenant` override column and no `effective_*` resolution. The per-tenant override is a
  thirty-minute addition the day a shop needs one, and today no shop will reach a dollar.
- **No `/admin/ai-usage/` page.** A superuser reads spend from `AiCall` in a shell until
  there is a third shop. The page is a session of its own when it is wanted.
- **The owner Settings card stays**, because it is the privacy courtesy and it is one
  sentence: "Assistance: on / off for this shop" plus the month's spend in words. The audit
  event on toggle stays with it.

### AI1 · Just say the job

Keep: the "Say it" button on the job form and the quick-add modal, on-device Web Speech with
a typed fallback, the fill-from-text endpoint that fills gaps only, the strict schema with
`''` as the preferred answer under doubt, the nine-region location table, each filled field
with a note and an Undo, streaming so the first field lands within a second.

Add one field the queue did not have: **`scheduled_for | null`** in the schema, so "Thursday
morning" or "tomorrow at 2" fills the booking the same way every other field is filled, as a
suggestion with a note and an Undo. The model resolves relative dates against the request's
date in the shop's timezone; the form validates it like a typed one. This is what makes AI9
(text it in) a transport change later rather than a second extraction schema.

Trim:

- **No customer-portal surface in v1.** A fleet manager pasting a driver's text is real, but
  the portal form has four fields and the demo is the tech's phone. Portal is the first
  follow-up after a stranger shop has a fleet customer.
- **No "dictate notes" second button.** The main button already fills `technician_notes`
  from what was said; a second cleaned-up version of the same words is polish. The
  customer-safe one-line description it would have produced comes from the existing
  `get_invoice_description()` rules at invoice time, as today.

### AI2 · Paste anything

Keep: `/owner/import/` with a pasted block or an uploaded file, the model mapping the header
row plus ~20 sample rows to the fixed field list and nothing more, Python parsing every row
against that mapping, the preview with editable column headers and flagged rows, the explicit
fleet-vs-individual decision per row, one atomic "Import N rows", an `import_batch` tag so
Recently Deleted can undo the whole batch, `repair_count` seeding `UnitRepairCount`.

Trim:

- **CSV and pasted text only. No `openpyxl`.** Every spreadsheet program exports CSV in two
  clicks and the import page says so in one line. This is the one decision the queue left
  to Drake; the plan takes the smaller option and a later session can add `.xlsx` if a
  prospect stumbles on it.
- **No setup-checklist card until the page exists on prod and someone has used it.** The
  checklist is already the longest list a new owner sees.

### AI4 · Short-pay detective

Keep: the paste box on the claim page (owner/manager only), the strict schema of extracted
lines and totals, the one-sentence gap explanation appended to `InsuranceClaim.notes` with
attribution, the appeal draft as a textarea with Copy, the "Record $X from insurer?" offer
that routes through the existing `owner_record_payment` with `from_insurer=1`, `reconcile()`
untouched, the new `claim_remittance_read` audit event.

Trim:

- **Drop `likely_recoverable`.** It is a prediction, and the queue already suggested it must
  not feed the aging card. A field the UI shows but nothing uses invites the question "why is
  it wrong"; the explanation sentence and the draft are the deliverable.

---

## What we defer, and the condition that reopens each

A deferred session keeps its full section in `AI_SESSIONS.md` and is not touched until the
condition is met. A fresh session that meets the condition picks it up as written.

- **AI3 · Describe it — until a non-family shop has a website to put it on.** The public
  estimate page is the right lead channel for a shop with a site and traffic; the two shops
  on prod have neither. It is also the largest session, the only customer-facing model
  output, the one that adds a settings block (repair rules) and a privacy-policy sentence,
  and the one where the honesty bar is highest. **The embed (part c) is cut, not deferred**:
  a pasted `<script>` on a shop's site is the widget proposal's scope and a support surface
  of its own. When AI3 is built, it ships the portal surface and the branded public page,
  and a shop links to the page.
- **AI6 · Draft a reminder — until AI4 ships.** Same shape as AI4 (owner pastes nothing,
  taps once, gets a draft, sends by hand through the existing modal), half the size, and it
  honours the overdue-email policy exactly. It is deferred only because it does not sell;
  it is the natural fifth PR. **AI6b is cut**: a style line in Settings that rewrites the
  three email templates is a feature for an owner who opens the templates page, and the
  simplicity bar says most never will. The default templates are already fine.
- **AI7 · Replacement pre-flight — until The Glass Guy logs replacements on the platform.**
  Production has zero replacement records. The card is right when a tech who actually orders
  glass says it asked what he would have asked, and there is nobody to ask yet. The 90-day
  cache table is also a new model for a feature with no users. When it reopens, the
  never-a-NAGS-number rule and its post-filter are non-negotiable.
- **AI5 · Morning brief — until a non-family shop is on a paid plan.** It is cheap and it is
  the product's first proactive voice, but it is retention for a shop we have not acquired,
  and it is a cron job on an instance whose cron table has been missing since 2026-09-27.
  Reopen it after the next deploy restores cron and a paying stranger shop exists; AI10's
  fleet signals, if they are ever wanted, become sentences in this brief rather than a
  session.
- **AI9 · Text it in — until SMS version 6 is approved and an inbound path exists.** Drake's
  reframe (2026-10-13): the email version is cut, the SMS version is the one worth having.
  An owner driving between jobs texts *"Penske unit 42, star break, Thursday morning"* to
  the RS Systems number and finds the job on Thursday's sheet, already scheduled. It is AI1's
  engine on a new channel, and with `scheduled_for` in AI1's schema the parse is already
  done; the session is the transport. **The audience split in `SMS_REGISTRATION.md` §3.5
  decides what it can be:**
  - **Staff texting in is clean under version 6.** An owner or tech texting RS Systems'
    number is an account holder talking to RS Systems, and the reply ("Got it, job #1042 on
    Thursday 9am for Penske unit 42. Reply NO to undo.") is an account notification to a
    registered user. That is exactly the audience v6 is filed for. The sender is matched to
    a `Technician`'s verified phone on one tenant; an unknown number gets nothing back and
    creates nothing. The job is created APPROVED with `scheduled_for` set, because the shop
    itself said when; the reply is the Undo.
  - **A fleet customer texting in is not.** The inbound text is fine, but any reply to them
    is a customer-facing text as the shop, which is the thing four registrations were denied
    for. Until B2 (`IMPROVEMENT_SESSIONS.md`) gives a shop a number of its own (Path A) or a
    conversation surface, a customer's text can only arrive silently as a REQUESTED job with
    `preferred_date` (a wish, never `scheduled_for`) and a notification to the shop. Silent
    intake with no confirmation is a worse experience than the portal form, so **the
    customer half waits for B2** and is not built as a half-measure.
  - **What inbound needs**: the number moves from SNS to AWS End User Messaging two-way (an
    SNS topic or webhook on `+18663115189`), one `inbound_sms` view, STOP/HELP handling the
    carrier already expects, and `tests/test_ai_text_in.py` asserting an unknown sender
    creates nothing, a sender on tenant A cannot create on tenant B, and the reply carries
    the `RS Systems:` prefix the registration samples promise. Size M once AI1 exists, not L.

---

## What we cut, and why it stays cut

- **AI8 · Ask your shop.** Every SaaS will ship this; the ones that get it wrong leak a
  tenant's data, and the queue itself says to build it last on a spine four features have
  exercised. Global search already answers "find Penske" and the invoices list already
  answers "what does Penske owe me" with a filter. A read-only question box over money is
  the highest isolation surface in the product for a feature a stranger shop will not ask
  for in its first quarter. Cut; if it is ever re-proposed, the fixed tool list and the
  two-tenant isolation test in the queue are the starting point.
- **AI9's email transport.** SES receiving (receipt rules, a bucket or topic, an inbound
  route, sender verification) is infrastructure the platform has never had, for a request no
  fleet customer has made. The SMS transport replaces it (see the deferred AI9 above); an
  email channel is only reopened if a fleet customer who is not family asks for it by name.
- **AI10 · Fleet health.** Needs ninety days of a stranger fleet's history to say anything
  Drake does not already know about Rockstar's. Cut as a session; the signals are rule-based
  querysets and belong in AI5's brief when both exist.
- **AI3's embed.** See AI3 above.
- **AI6b · Write my templates.** See AI6 above.
- **AI0's admin usage page, per-tenant cap override, and second model setting.** See AI0.
- **AI1's portal surface and notes dictation.** See AI1.
- **AI2's `.xlsx` support and checklist card.** See AI2.
- **AI4's `likely_recoverable`.** See AI4.

Appendix B of `AI_SESSIONS.md` (photo quotes, review replies, tech coaching, NAGS lookup,
automatic customer messages, support deflection, a second provider) is unchanged and is not
repeated here. Nothing in it moves.

---

## What this leaves for a fresh session

A fresh session picking up this plan reads `AI_SESSIONS.md` §0 (ground rules: the text-only
boundary, off unless `ANTHROPIC_API_KEY`, models and request shape, suggest-never-apply, no
queue, one row per call, copy and claims, tests in the house pattern), then the AI0 section
there, then the trims above. The order is AI0, AI1, AI2, AI4, one PR each, and a session is
not DONE without the four things §0.8 names: hidden when the key is unset, degrades when the
wrapper raises, two-tenant isolation asserted, schema enum asserted equal to the live choice
list.

`eb setenv ANTHROPIC_API_KEY=…` is Drake's, in the same breath as the AI0 deploy.

## Decisions for Drake

1. **Confirm the four.** AI0, AI1, AI2, AI4. If AI3 feels like the demo rather than AI1,
   say so; the engine is shared and the order flips cleanly, but the public page roughly
   doubles the first customer-facing session.
2. **Platform cap default.** The queue suggested $5 per tenant per month; with one platform
   cap and no override, the same number works.
3. **CSV only for import.** Taken here as the smaller option; say if `.xlsx` is a must-have
   for the first prospect.
4. **Promotion ahead of step 7.** Unchanged from the queue and still yours.

## Document history

| Date | Change |
|---|---|
| 2026-10-13 | Created. Ten sessions cut to four builds (AI0, AI1, AI2, AI4), four deferrals with named reopen conditions (AI3, AI6, AI7, AI5), three cuts (AI8, AI9, AI10), and nine trims inside the kept sessions. Nothing built. |
| 2026-10-13 | **AI9 reframed from email to SMS and moved from cut to deferred** (Drake: "would be cool with SMS if that ever got approved, easily text and schedule jobs"). Staff texting a job in fits SMS v6's audience; customers texting in waits on B2. `scheduled_for` added to AI1's schema so the text channel is a transport, not a second parser. |
