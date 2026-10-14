# AI Sessions — the product does the typing

**Created:** 2026-10-12
**Author:** Claude (planning session with Drake)
**Status:** living document — the queue is written and ranked; nothing in it is built.
Update the Status column and each session's Notes as work lands. The doc is closed, not
deleted, when every row is DONE, DROPPED or PARKED with a named reason.
**Companions:** `AI_CORE_PLAN.md` (2026-10-13 — **the cut: which of these rows get built,
which wait, which are dropped, and the trims inside each kept row.** That page decides scope;
this one stays the spec), `PRODUCT_DIRECTION.md` (the direction every session here serves — step 7,
go-to-market, is the current step and **this queue sits behind it unless Drake promotes
AI1–AI3 as the demo**; see §The ranking rule), `IMPROVEMENT_SESSIONS.md` (B2/B4/D1/D2 are
referenced below), `PHOTO_ML_SESSIONS.md` (P5/P4b stay parked there — **this document never
touches a photo**, see §0.1).

**Three decisions taken 2026-10-12, which every session below assumes:**

1. **Data boundary: text may go to the Claude API; photos stay on our infrastructure.** The
   P3 decision (`PHOTO_ML_SESSIONS.md`) stands untouched — a Claude-vision stage was proposed
   and rejected there, and it is not revisited here. Job notes, customer and vehicle names,
   amounts and pasted remittances are text and may be sent. *(Drake, 2026-10-12.)*
2. **Deliverable: every idea queued and ranked** in this doc, in the house session format,
   Tier 3 marked PARKED. Nothing built this session.
3. **Cost model: RS Systems pays, bundled into the plans.** One platform API key; a
   per-tenant monthly cap exists as a safety net, not a paywall. AI is how the product works,
   not a feature a shop buys. The free trial includes it, the same way it includes loyalty.

---

## What this arc is for (the durable purpose statement)

A 1–5 technician shop competing against paper does not want "AI features." It wants the
software to do the typing. Every session here is **the product doing paperwork the tech or
owner was going to do anyway** — fill the form from what they said, map the spreadsheet they
already have, explain why the insurer paid short, draft the reminder the owner was going to
write at 9pm. The output is always a *suggestion with a note and an Undo*: the price-book
rule (`static/js/price_book_suggestion.js` fills only an empty box, or offers "Use $X" beside
a typed one — never a caller that writes a price without one of those two). Nothing in this
document writes silently, and nothing here animates or auto-writes money.

The word "AI" does not appear in a button label. "Fill from what I said", "Import my list",
"Explain this short payment", "Draft a reminder" — the verb is the feature. (Drake's bar from
`simplicity-first`: dad-simple, plain-language, never promise a feature that does not exist.)

## The ranking rule

One question orders the queue: **does it help a shop that is not family sign up, switch, and
pay in Q4 2026?** That is `PRODUCT_DIRECTION.md` step 7, the step we are on. Three things
follow from it, and they are why the order below looks the way it does:

- **Day-one magic outranks learned magic.** Production has two family shops, 73 tapped photos,
  zero replacement records and no fleet outside Rockstar's. Any session whose pitch is "learns
  from your history" is a promise with nothing behind it for a stranger shop on day one.
  AI10 (fleet health) is parked for exactly this reason.
- **The intake arc is one engine, three surfaces.** AI1 (say it), AI2 (paste it) and AI3
  (describe it) share the structured-extraction core and are respectively *the demo*, *the
  switch* and *the lead channel*. Built in that order, each one is a day's work on the one
  before it.
- **Honesty is a constraint, not a tone.** `tests/test_landing_credibility.py` rejects filler
  claims on the landing page; the same spirit applies to every surface here. Anything
  customer-facing says "estimate — the shop confirms." The product never implies a human
  reviewed something a model wrote.

Each session is self-contained — a fresh Claude session with no memory should be able to
execute exactly one using only §0 and that session's section, without re-running the
exploration that produced this doc.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED · PARKED`

| # | Session | Size | Status |
|---|---|---|---|
| AI0 · Spine | `common/ai.py` wrapper, settings flag, `AiCall` log + per-tenant cap, the no-photo and no-tenant guards, `anthropic` pinned | M | TODO — **prerequisite for every row below** |
| AI1 · Just say the job | Transcript → job form, strict schema from the model's own choice lists; on-device speech; the same engine on the portal request form; dictate notes | M | TODO |
| AI2 · Paste anything | Import page: spreadsheet / CSV / pasted text → mapped `Customer` / `Vehicle` / `UnitRepairCount` with a flagged preview | M | TODO |
| AI3 · Describe it | Text → repair-or-replace under the shop's rules → the real pricing engine → a DRAFT `Quote`; the public embed from the widget proposal | M–L | TODO |
| AI4 · Short-pay detective | Paste the insurer's remittance on the claim → extracted lines, a one-sentence gap explanation, a rebill draft | M | TODO |
| AI5 · Morning brief | Daily cron email to the owner: 120 words and three things to do today, from querysets that already exist | S | TODO |
| AI6 · Draft, never send | "Draft a reminder" on an overdue invoice, in the shop's voice, from what the app already knows; owner sends. AI6b absorbs the email-template proposal | S | TODO |
| AI7 · Replacement pre-flight | Vehicle + glass position → the questions to ask before ordering + an ADAS-calibration flag. Never a NAGS number | S | TODO |
| AI8 · Ask your shop | Read-only questions over tenant-scoped querysets via tool use; the tool list is fixed and tested for isolation | M | TODO — after AI1–AI4 |
| AI9 · Forward an email | SES inbound → drafted REQUESTED jobs for the shop to confirm; the email half of B2 | L | **PARKED** — needs SES receiving infra; revisit when a fleet customer asks |
| AI10 · Fleet health | "Lot walk due at Penske", request-decline signals — the consumer FIELD_OPS S6 lacked | M | **PARKED** — needs months of a non-family fleet's data |

**Suggested sequence:** AI0 → AI1 → AI2 → AI3 → AI4 → AI5 → AI6 → AI7 → AI8. AI9 and AI10
stay parked until the named condition is met; do not pick them up by default.

**Where this sits against step 7.** `PRODUCT_DIRECTION.md` says nothing is queued ahead of
three non-family shops. That is still true: this queue is *behind* step 7. The one argument
for promoting a session is that AI1 is a ten-second parking-lot demo and AI2 removes the
reason a shop says "later" — i.e. they *are* the selling, not a distraction from it. **That
is Drake's call, recorded in `PRODUCT_DIRECTION.md` §Parked, and not a fresh session's to
make.**

---

## §0 Ground rules a fresh session needs

Every session assumes these. Read them before writing a line; most are enforced by a test
that AI0 adds.

### 0.1 The boundary: text only, and one tenant at a time

- **No photo bytes and no photo URL ever enter a request.** Not `damage_photo_before`, not
  `customer_submitted_photo`, not a `cropped_image`, not the S3 address of any of them. The
  wrapper (`common/ai.py`) refuses an `image` content block and refuses any string matching
  a photo-field URL pattern; `tests/test_ai_boundary.py` fails the build if a caller in
  `apps/` or `core/` passes a photo field to it (same shape as `tests/test_photo_serving.py`,
  which already greps templates and modules for a photo-field `.url`). A pasted *document*
  (a remittance, a spreadsheet) is text and is fine. A *photo of* a document is a photo and is
  not — the owner pastes the text, or types it.
- **Every call takes `tenant=` and refuses without it.** A prompt is built from one tenant's
  rows and nothing else. There is no "platform-wide" prompt except AI5's platform digest,
  which contains counts, not rows. AI8's tools are tenant-scoped querysets, never SQL, never a
  queryset the tool author did not write.
- **PII goes in only when the feature needs it.** AI1 needs the customer's name to match it;
  AI5 does not need a customer's phone number to say "three invoices are overdue." The
  wrapper does not strip anything — the *caller* builds the prompt, and the session's "What
  goes in the prompt" line is the contract.
- Anthropic's API does not train on inputs; retention is 30 days. That sentence, and the
  text-only boundary, go in the privacy policy (`templates/saas/privacy_policy.html`) **in
  the session that first ships a customer-facing call (AI3)**, not before.

### 0.2 Off unless configured — the `PLAUSIBLE_DOMAIN` pattern

`rs_systems/settings/base.py` reads `ANTHROPIC_API_KEY` from the environment; `AI_ENABLED`
is derived (`bool(key)`), never set independently. When it is unset: every button, card and
route this doc adds **hides** (a template `{% if ai_enabled %}`, a view that 404s — exactly
how `common/analytics.py` behaves without `PLAUSIBLE_DOMAIN`). Nothing 500s. **The test
suite runs with it unset** and every AI-touching test mocks the wrapper; no test ever reaches
the network (the P3 "opens no sockets" assertion is the precedent, `photo_suggest.py`).
`eb setenv ANTHROPIC_API_KEY=…` is Drake's, in the same breath as the AI0 deploy.

### 0.3 Models and request shape (current as of 2026-10-12 — verify against the API before pinning)

- **Default `claude-opus-5-5`** for the judgment calls: AI3 (repair-or-replace), AI4 (reading a
  remittance), AI7 (what to ask before ordering glass). Thinking is always on; depth is
  `output_config.effort`, whose default on this model is `medium` — set it explicitly per
  route.
- **`claude-haiku-5-5` is the candidate** for the latency-bound, inline-in-a-form calls (AI1,
  AI2's column mapping, AI5's prose, AI6's drafts): $0.10/$0.50 per million tokens, so a job
  fill costs well under a tenth of a cent. **This is a per-session measurement and Drake's
  call, never a silent downgrade** — build on Opus, measure latency and quality on real
  inputs, then propose the swap with numbers in that session's Notes.
- **Structured outputs, `strict: true`, schemas generated from the model's choice lists.**
  `Repair.DAMAGE_TYPE_CHOICES` (`''`, `Chip`, `Crack`, `Star Break`, `Bull's Eye`,
  `Combination Break`, `Half-Moon`, `Other`), `Replacement.GLASS_POSITION_CHOICES`
  (`WINDSHIELD` … `SUNROOF`, `OTHER`), `GLASS_TYPE_CHOICES`. A schema enum that is *built
  from* the choices at import time cannot drift from the form; a hand-typed one will, within
  a release. The answer can only be a value the form accepts, and `''` ("Unknown / Not Sure")
  is a legal answer the model is told to prefer over a guess.
- **Prompt caching** on the stable system prompt and the shop's rules block (`cache_control`
  on the system block); volatile rows last. Verify with `usage.cache_read_input_tokens` in the
  `AiCall` row — zero on repeated calls means a timestamp or an unsorted `json.dumps` crept
  into the prefix.
- Things that 400 on the 5.5 family and must not appear: `budget_tokens`, assistant prefill,
  forced `tool_choice` (`any` / `tool`). Use `auto` plus an instruction, or structured outputs.
- Stream anything a human is watching (AI1 into the form, AI4's explanation, AI8's answer);
  the SDK's `get_final_message()` for anything cron-side. Always check `stop_reason` before
  reading content — a `refusal` is handled as "no suggestion", never as an error the tech sees.
- The `anthropic` SDK is the only new dependency. Pin it in `requirements.txt` with a comment
  naming this doc. No LangChain, no OpenAI-compatible shim, no second provider.

### 0.4 Suggest, never apply

The price-book rule, verbatim: fill only an empty box (with a note saying where the value
came from, and an Undo), or offer "Use X" beside a typed one. **Don't add a caller that
writes a field without one of those two.** This covers a form field, a `Quote` (always
DRAFT), a claim note (appended, attributed), a reminder (drafted, never sent). Money is never
written by a model: AI3 asks the *pricing engine* for the number; the model only classifies.

### 0.5 No queue

Celery and Redis are gone (`core/tasks.py`: "now called directly"). Two shapes only:

- **Inline**, when a human is waiting: budget ~2s to first token, stream into the UI, and
  degrade to "couldn't fill this — carry on by hand" on any error. The form must work with the
  wrapper raising; `form_autosave.js` keeps what they typed.
- **Cron**, when nobody is: a management command installed through
  `/opt/rs-systems/run-cron.sh` under the four EB cron rules in `CLAUDE.md` (one top-level key
  per `.config`, `/var/log/rs-systems/` paths, purge `.bak`, `leader_only`). Every such
  command supports `--dry-run` and is run with it on the instance before it is enabled.

### 0.6 Cost: one row per call, one cap per tenant

`AiCall` (`common/ai_models.py` or `apps/tenants/ai_models.py` — AI0 decides; it must be
tenant-FK'd either way): `tenant`, `feature` (a short slug: `job_fill`, `import_map`,
`estimate`, `short_pay`, `brief`, `nudge`, `preflight`, `ask`), `model`, `input_tokens`,
`output_tokens`, `cache_read_tokens`, `latency_ms`, `cost_cents` (computed from a price
table in code, dated), `ok`, `created_at`. **Tenant.ai_monthly_cap_cents** (default from
`PlatformConfig`, overridable per tenant like the platform fee). At the cap, features
**degrade to hidden** for the rest of the month and the owner sees one quiet line in Settings
— the shop's work never blocks. A platform report page beside `/admin/platform-fees/` sums
by tenant and feature. Expected spend at 2026 prices for a busy 5-tech shop: cents a day;
the cap exists for a runaway loop, not for a shop.

### 0.7 Copy and claims

Button labels are verbs; the word "AI" appears in Settings and the privacy policy, not on a
job form. Customer-facing output (AI3's estimate, AI6's reminder once sent) carries the
shop's name and voice, never RS Systems'. No surface implies a human reviewed what a model
wrote. The landing page gets a line about any of this **only after it is on prod**, and then
it is a capture of the real thing (`scripts/landing_shots.py`), never a mock.

### 0.8 Tests, in the house pattern

Every session adds to `tests/test_ai_<session>.py`, with the wrapper mocked at
`common.ai.complete` (or whatever AI0 names it). AI0 adds `tests/test_ai_boundary.py` to the
guard set (`scripts/test_guards.sh --list`). A session is not DONE without: the feature
hidden when the key is unset; the feature degrading cleanly when the wrapper raises; tenant
isolation asserted with two tenants' rows in the DB; and the structured-output schema
asserted equal to the live choice list.

---

## AI0 · Spine — `common/ai.py`, the flag, the log, the guards

**Goal:** one wrapper every later session calls, and nothing else in the codebase ever
imports `anthropic` directly. Size M. **Prerequisite for every other row.**

**Why first:** every session below needs the same six things — a configured client, a
tenant guard, a photo guard, a cost row, a cap, and a mock point for tests. Built once here,
each later session is its own feature and nothing else. Built per-session, there would be
three wrappers by AI3 (the `calculate_platform_fee` lesson, CODE-069).

**What to build:**

- `common/ai.py`:
  - `is_enabled()` → `bool(settings.ANTHROPIC_API_KEY)`; a context processor exposes
    `ai_enabled` to templates (register in `base.py` TEMPLATES like the others).
  - `complete(*, tenant, feature, system, messages, schema=None, model=DEFAULT_MODEL,
    effort='medium', stream=False, max_tokens=…)` → a small result object (`text`,
    `parsed`, `usage`, `ok`, `refused`). Raises `AiDisabled` when off, `AiOverCap` when the
    tenant is capped, `AiBoundaryError` on a photo; wraps SDK errors so callers catch one
    class. `schema` → structured outputs (`output_config.format`) with `strict`; `parsed` is
    the validated dict.
  - The photo guard: rejects any `image` block, and any string content containing a
    `repair_photos/` path, a `/photos/` app route, or a signed S3 URL (regex, tested).
  - The cost row: writes `AiCall` after every call, including failures (`ok=False`).
  - Prompt-cache placement: `system` is sent as a list with `cache_control` on the last
    stable block; the wrapper does not add timestamps.
- `rs_systems/settings/base.py`: `ANTHROPIC_API_KEY`, `AI_DEFAULT_MODEL`
  (`claude-opus-5-5`), `AI_FAST_MODEL` (`claude-haiku-5-5`, used only where a session's
  Notes record Drake's go-ahead). Document all three in `CLAUDE.md` §Environment Variables
  with the same "off unless set" sentence `PLAUSIBLE_DOMAIN` has.
- `AiCall` model + migration; `Tenant.ai_monthly_cap_cents` (+ `PlatformConfig` default)
  + migration. `Tenant.ai_spend_this_month()` sums `AiCall.cost_cents`.
- Owner Settings: one card under General — "Assistance: on / off for this shop", the
  month's spend as a sentence, and nothing else. Off per tenant means `complete()` raises
  `AiDisabled` for that tenant; the UI hides identically.
- Platform report: `/admin/ai-usage/` beside `/admin/platform-fees/`, superuser-only, by
  tenant × feature × month.
- `requirements.txt`: `anthropic==<current>` with a comment pointing here.

**Reuse:** `common/analytics.py` for the off-unless-set shape; `Tenant.effective_platform_fee`
for the platform-default-then-tenant-override resolution; `apps/security/audit.log_event` for
the owner toggling assistance off/on (add `ai_toggled` to `SecurityAuditLog.EVENT_TYPES` —
an unknown event type raises).

**Tests:** `tests/test_ai_boundary.py` (guard set): photo rejection on bytes and on URL
patterns; `complete()` without `tenant` raises; nothing in `apps/` or `core/` imports
`anthropic` except `common/ai.py` (grep, like `test_photo_serving.py`); no test opens a socket
when the key is unset. `tests/test_ai_spine.py`: cap behaviour, `AiCall` written on failure,
settings card hidden when off, audit event on toggle.

**Done when:** the wrapper is callable from a shell with a key and returns a parsed
structured output; with no key every route this session added 404s and every template
fragment is absent; guard set green; `eb setenv ANTHROPIC_API_KEY` is a one-line note in the
PR for Drake.

**Notes / decisions for Drake:** where `AiCall` lives (common vs tenants); the platform
default cap (suggest $5/tenant/month to start — a 5-tech shop will not reach $1).

---

## AI1 · Just say the job

**Goal:** a tech in a parking lot says or types *"Penske unit 42, 2019 F-150, star break
driver side low, drilled it, 74 degrees"* and the job form is filled — customer matched,
vehicle, damage type, approximate damage location, drilled flag, windshield temperature —
with each filled field carrying a note and an Undo. Size M.

**Why it ranks here:** it is the ten-second demo. Every pitch to a stranger shop is a
parking-lot conversation, and this is the one thing the product can do in that lot that
paper cannot. It is also the most-used path in the app (the job form; see
`job-form-parity-gaps`), so it pays the two shops back on day one.

**What to build:**

- **Speech stays on the phone.** A "Say it" button on `templates/technician_portal/job_form.html`
  (and the quick-add modal, `includes/quick_job_modal.html`) uses the browser's Web Speech
  API for the transcript; audio never leaves the device, and the API is unsupported on some
  browsers, so the same box accepts typing and the button simply hides where `SpeechRecognition`
  is absent. A static JS module, `static/js/job_dictate.js`, loaded like
  `viscosity_suggestion.js`; CSP nonce rules apply.
- **Extraction endpoint:** `POST /tech/jobs/fill-from-text/` (tenant-scoped, technician
  login). Input: the transcript + the form's current values (so the model fills *gaps*, never
  overwrites). The prompt carries the tenant's customer list as `(id, name, type,
  unit-number examples)` — hundreds of rows at most — and the model returns a strict schema:
  `customer_id | null`, `new_customer_name | null`, `customer_type`, `unit_number`,
  `vehicle_year/make/model`, `service_type` (repair/replacement), `damage_type` (enum from
  `DAMAGE_TYPE_CHOICES`), `damage_location` (`{x_pct, y_pct} | null`, from phrases like
  "driver side low" via a fixed table of nine regions, not free numbers), `drilled`,
  `windshield_temperature`, `glass_position` (enum), `notes_for_tech`, `confidence` per field.
- **Fill behaviour:** the price-book rule per field. `windshield_temperature` being filled
  triggers the existing viscosity auto-populate (`viscosity_suggestion.js`) — do not
  reimplement it. A matched customer fires the existing duplicate-job warning
  (`repair_form.js`). A `new_customer_name` goes through the same on-the-fly individual/fleet
  picker the form already has (`individual-general-public-work`); the model's `customer_type`
  guess preselects, never creates.
- **Dictate notes:** a second button beside `technician_notes` returns two strings:
  `technician_notes` (cleaned, first person removed) and a one-line customer-safe description
  the invoice can use (`get_invoice_description()` rules: names its service, never the
  vehicle). Both are suggestions with Undo.
- **Customer portal:** the same endpoint, portal-authenticated, on the repair request form
  (`static/js/customer_repair_request.js`) — a fleet manager pastes the driver's text. Fields
  limited to what the portal form has (unit, damage type, notes, location).
- Streaming: the endpoint streams the structured output and the JS fills fields as they
  arrive; first field within ~1s.

**What goes in the prompt:** the transcript; the tenant's customer names and types; the
form's current values; the shop's `services_offered`. Nothing else. No photos.

**Reuse:** `QuickJobForm` (`apps/technician_portal/forms.py:914`) and
`services/quick_job.py` for the field names and validation — the endpoint does *not* save;
`UnitRepairCount.key_for` is untouched because nothing is saved; the customer picker and
`Customer.is_individual`.

**Tests:** schema enum equals `DAMAGE_TYPE_CHOICES` / `GLASS_POSITION_CHOICES` at import;
a transcript naming another tenant's customer returns `customer_id=null`; the endpoint
404s with no key; a wrapper failure returns 200 with `{filled: {}}` and the form stays
usable; the nine-region location table round-trips.

**Done when:** on a phone over CDP (the house browser recipe — the Chrome extension cannot
emulate a phone), the sentence above fills six fields with notes, Undo restores each, and
saving produces a job identical to one typed by hand.

**Notes / decisions for Drake:** Haiku for this route (measure first); whether the portal
surface ships in the same PR or the next.

---

## AI2 · Paste anything — import a shop's customers in an afternoon, not Drake's

**Goal:** an owner drops a `.xlsx`/`.csv` or pastes a block of a spreadsheet and gets a
preview table of customers, vehicles and repair counts with the model's guesses flagged;
they confirm, rows are created under the existing rules. Size M.

**Why it ranks here:** the landing page's switching section promises "send your customer
list through the contact form" — which is a manual import by Drake, which is the single
largest switching cost for a shop on Excel or sticky notes, and the reason a prospect says
"later." Day-one history also means progressive pricing (`UnitRepairCount`) and the price
book are right from the first job instead of the thirtieth.

**What to build:**

- Owner page `/owner/import/` (Settings → General, and a card on the setup checklist until
  it is used once). Accepts a file (`openpyxl` for `.xlsx` — new dep, or ask for CSV only in
  v1; Drake's call) or pasted text. Size cap ~2,000 rows; above that, "send it to us" — the
  contact form still exists.
- **Column mapping is the model's job; row parsing is not.** The sheet's header row and the
  first ~20 rows go to the model with a strict schema: for each source column → one of
  `customer_name, customer_type, contact_name, email, phone, address, city, state, zip,
  unit_number, vin, year, make, model, repair_count, last_service_date, notes, ignore`, with a
  confidence and a one-line reason ("'Co.' and 'Contact' columns → fleet accounts"). The
  *rows* are then parsed in Python against that mapping — deterministic, testable, and the
  model never sees 2,000 rows of PII when 20 will do.
- **Preview:** a table with the mapping as editable column headers (a `<select>` each), rows
  flagged where a value failed validation (phone, email, year), duplicates against existing
  `Customer` rows flagged (reuse the FLEET-only name constraint logic in
  `core/models/customer.py`), and the fleet-vs-individual decision shown per row — this is
  the exact axis invoices got wrong once (`individual-vs-fleet`), so it is explicit, not
  inferred silently. "Import N rows" is one POST, atomic, with a summary and an Undo window
  (soft-delete exists: imported rows are tagged with an `import_batch` UUID so one click
  trashes the batch within 30 days).
- Creates `Customer`, `Vehicle` (when year/make/model or VIN is present), and
  `UnitRepairCount` rows keyed with `UnitRepairCount.key_for` semantics (fleet: unit number;
  individual: vehicle). A `repair_count` column seeds the counter so pricing is right
  immediately; this is a **count**, not jobs — no `Repair` rows are invented.

**What goes in the prompt:** the header row and ~20 sample rows. Not the whole sheet.

**Reuse:** the customer duplicate-suggest and type picker; `Customer.customer_type`
defaults (note it defaults to `'FLEET'` — the mapping must set it explicitly for individuals);
soft delete + Recently Deleted for the Undo; the setup checklist (`apps/saas/views.py`).

**Tests:** mapping schema enum equals the field list; a sheet with "Unit" and "Tag" columns
maps both to `unit_number` with one flagged; rows for another tenant's names do not
dedupe against them; the Undo trashes exactly the batch; `repair_count` seeds the counter
and the next job prices as repair N+1.

**Done when:** Rockstar's real spreadsheet (Drake has it) imports on a dev DB with zero
hand edits to the mapping, and the preview catches every row the hand import would have.

**Notes / decisions for Drake:** `.xlsx` support (openpyxl) in v1 or CSV only; whether the
landing page's switching line changes to "import it yourself in five minutes" — only after
it is on prod and captured.

---

## AI3 · Describe it — an instant estimate from a sentence, and the public embed

**Goal:** a customer types *"golf-ball chip in the middle of the windshield, 2021 Camry,
happened yesterday"* and gets an estimate — repair or replacement, and the shop's real
number — as a DRAFT `Quote` the shop sends with one tap. On the shop's own website, via an
embed. Size M–L.

**Why it ranks here:** it is the lead channel. C3 made the site findable; this gives a
stranger who found it something to *do* that paper shops cannot offer, and every submission
is a `Quote` in the shop's queue — the B3 spine feature doing what it was built for. It is
also the text-only sibling of the parked classifier (P5/P4b): no photo, no dataset, and it
works on day one from the shop's rules rather than from history.

**What to build:**

- **Classification is the model's; the price is the engine's.** Prompt: the description, the
  vehicle, and the shop's repair rules as text (today these are implicit — AI3 adds a small
  "What we repair" block to Settings → Services: max chip size, max crack length, "not in the
  driver's direct view", "not on the edge"; defaults from industry norms, editable). Strict
  schema: `service_type` (repair / replacement / needs_inspection), `damage_type` (enum),
  `glass_position` (enum, replacement only), `confidence`, `customer_facing_reason` (one
  sentence: "Cracks over six inches can't be repaired safely"). **`needs_inspection` is the
  default under uncertainty**, and it produces a quote with no number — "we'll take a look."
- **Pricing:** repair → `calculate_repair_cost(customer, repair_count, tenant)`
  (`services/pricing_service.py:99`) — for an unknown customer, repair #1 at the shop's
  rate; replacement → the price book (`services/price_book.py`) when it has a row, else
  `needs_inspection`. The model never emits a dollar amount.
- **The quote:** `quote_service` creates a DRAFT `Quote` + `QuoteLineItem` with the vehicle
  fields and `notes` = the customer-facing reason; the owner sees it in `/quotes/` and sends
  it through the existing B3 flow (public tokened page, accept → APPROVED jobs). Nothing is
  sent automatically.
- **Surfaces:** (a) the customer portal (a fleet contact describing a new chip), (b) a public
  page `/estimate/<tenant-slug>/` wearing the shop's brand (`{% tenant_brand_css %}`,
  `base_public`-style shell — never the app shell; the C3 lesson), protected like `/contact/`
  (Turnstile via `_verify_turnstile`, honeypot, per-IP rate limit), and (c) the embed from
  `docs/proposals/website-integration-widget.md`: one `<script>` the shop pastes, rendering
  an iframe of (b). The proposal's lead queue / conversion metrics are *not* in scope —
  `/quotes/` with `view_count` and `accepted_via` already is one.
- Copy, everywhere: "Estimate — <Shop> confirms before any work." The shop's name, not ours.

**What goes in the prompt:** the description, vehicle text, the shop's rules block (cached),
`services_offered`. No customer identity is needed for the classification; the contact
details go on the `Quote`, not to the model.

**Reuse:** B3 end to end (`apps/billing/quote_models.py`, `services/quote_service.py`);
`_verify_turnstile` (`apps/saas/views.py:196`) and the public contact view's guards
(`apps/support/views.py:512`); `tenant_brand_css`; `BillingConfig.allocate_quote_number()`.

**Tests:** a six-inch crack classifies as replacement under default rules and as
`needs_inspection` when the shop blanks the rule; the model's output never reaches a price
field (assert the quote total equals the engine's number); a public submission for tenant A
cannot create a quote under tenant B; the embed page carries no app-shell link a stranger
cannot follow (the C3 test pattern); Turnstile failure → no quote.

**Done when:** a description typed on the public page produces a DRAFT quote in the shop's
queue that the owner can send unedited; `test_findability.py` passes with the new public
URL in the sitemap (only once it is real).

**Notes / decisions for Drake:** whether (c) the embed ships with (b) or follows; the
default repair rules; privacy-policy sentence (§0.1) lands here.

---

## AI4 · Short-pay detective

**Goal:** on a claim's page, the owner pastes the insurer's remittance / EOB text and gets
the extracted line items, a one-sentence explanation of the gap ("$150 short: labor-rate cap
applied; calibration line denied as not pre-authorized"), and a rebill/appeal draft in the
shop's voice. Size M.

**Why it ranks here:** `PRODUCT_DIRECTION.md` names short insurance payments as "where the
daily pain is," and B5 tracks the gap without explaining it. This is the feature that makes a
medium shop's eyes widen, and every parsed remittance is a data point for the two insurance
questions the trial-shop script asks — Path B evidence accruing from use, not interviews.

**What to build:**

- On the claim page (owner/manager only — the B5 gate): a "Paste what the insurer sent"
  box. Strict schema out: `lines[]` (`description, billed, allowed, paid, reason_code,
  reason_text`), `totals` (`billed, allowed, paid, patient_responsibility`), `deductible_applied`,
  `gap_explanation` (one sentence), `likely_recoverable` (bool + why), `appeal_draft` (text,
  shop's voice, references the authorization number if present).
- Shown as a card; the explanation is **appended to `InsuranceClaim.notes`** with an
  attribution line and timestamp (the field is "Shop only — who you spoke to, what they
  said", which is exactly what this is). The draft is a textarea with Copy — it is **not**
  emailed by the app; insurers have portals and fax numbers, and sending is the owner's.
- **`reconcile()` is untouched.** The model's `totals.paid` is shown beside the recorded
  `received_amount`; if they differ, a one-line "Record $X from insurer?" offers the existing
  `owner_record_payment` with `from_insurer=1` (`apps/saas/views.py:3834`) — same guard,
  lock and overpayment check. The model never writes a `Payment`.
- `log_event(request, 'claim_remittance_read', …)` — add the event type.

**What goes in the prompt:** the pasted text; the claim's `billed_amount`,
`authorized_amount`, `deductible`, `received_amount`, insurer name, the invoice's lines
(description + amount). The customer's name is on the remittance already; nothing else.

**Reuse:** B5 in full (`apps/billing/claim_models.py`, `services/claim_service.py`);
`owner_record_payment`; `log_event`.

**Tests:** a fixture remittance with a labor cap and a denied calibration line yields the
expected gap sentence (mocked model, asserted plumbing); notes append, never replace;
`received_amount` unchanged by the feature alone; technician role gets 403; no key → the box
is absent.

**Done when:** Drake pastes one of Rockstar's real remittances (redacted or not — it is
their data) on prod and the explanation is right.

**Notes / decisions for Drake:** Opus 5.5 stays for this route; whether `likely_recoverable`
feeds the aging card's short-paid count (suggest no — the card is money, keep it mechanical).

---

## AI5 · Morning brief

**Goal:** a daily email to the owner — about 120 words and three things to do today —
written from querysets that already exist. Size S.

**Why it ranks here:** cheap, retention-shaped, and the product's first proactive voice.
`generate_aging_report` runs at 9:00 and produces a table nobody reads; this turns the same
numbers into sentences: "INV-1042 was viewed four times and not paid — probably waiting on a
PO. Quote Q-1007 is unanswered after four days. Penske's requests are down 60% on last
month." Owner-only, per the subscription-visibility policy (techs never see money state).

**What to build:**

- `manage.py send_morning_briefs [--dry-run] [--tenant-id]`: for each active tenant whose
  owner has not opted out, build a JSON facts block from existing querysets — yesterday's
  completed jobs and collected amount, open invoices by age bucket (`apps/billing/tasks.py`
  aging logic), quotes unanswered > 3 days (`Quote.view_count`, `first_viewed_at`), claims
  short-paid > 14 days, today's `scheduled_for` jobs by tech, unassigned queue count,
  requests awaiting pricing. Hand the block to the model with a fixed schema: `summary`
  (≤120 words), `actions[]` (max 3: `text`, `url`). **Numbers are copied from the block into
  the schema, never computed by the model**; the template renders `actions` as links.
- Sent through `send_branded_email(platform=True)` — this is RS Systems talking to its owner,
  not the shop talking to a customer. Subject: "Your morning at <Shop>" (no emoji, no
  brackets — `SES_OPERATIONS.md`). Skips a tenant with nothing to say (a quiet Tuesday sends
  nothing, which is the point).
- Cron: `14_ai_cron.config`, one `files:` key, `leader_only`, via `run-cron.sh`, 7:00 local
  (the aging report's 9:00 is UTC; pick the tenant's timezone if one exists, else 12:00 UTC).
- Owner Settings → Notifications: one checkbox, default on for owners.

**What goes in the prompt:** counts, amounts, invoice/quote numbers and customer *company*
names. No contact details.

**Reuse:** `apps/billing/tasks.py` aging; `send_branded_email`; `check_subscription_alerts`
as the command shape (per-tenant loop, `--dry-run`, idempotency by date).

**Tests:** a tenant with nothing pending sends nothing; a tech user never receives one;
numbers in the summary equal the block (assert the schema copies, not generates); the cron
config passes `tests/test_ebextensions_cron.py`'s four rules; `--dry-run` writes no email.

**Done when:** `run-cron.sh send_morning_briefs --dry-run` on the instance prints Rockstar's
brief and Drake agrees it is what he would have wanted to read.

**Notes / decisions for Drake:** Haiku for this route; send time.

---

## AI6 · Draft, never send

**Goal:** on an overdue invoice, "Draft a reminder" writes one in the shop's voice using what
the app already knows about that invoice; the owner edits and sends through the existing
send path. Size S. **AI6b** absorbs `docs/proposals/ai-email-template-assistant.md`.

**Why it ranks here:** `process_overdue_invoices` is **DISABLED BY POLICY** — RS Systems
does not chase a shop's customers. The draft honours the policy exactly: the shop sends, in
one tap, with a better letter than it would have written at 9pm. The invoice knows things the
owner forgets: `view_count`, `first_viewed_at`, `last_viewed_at`, days overdue, the customer's
history of paying late or on time, whether a claim is attached (the insurer, not the
customer, may be the one to chase).

**What to build:**

- Invoice page, owner/manager, status past due: "Draft a reminder" → schema `subject`,
  `body`, `tone_used` (one of `friendly, direct, firm`, chosen from days overdue and the
  shop's default), `why` (one line: "viewed four times, never paid — likely waiting on
  approval, so this asks who to send the PO to"). Fills the existing send-invoice modal's
  message field (the "confirm-before-send" modal from `invoice-send-polish`) — the owner
  reads, edits, sends; `Reply-To` is the shop (`shop_sender`).
- **AI6b — "Write my templates in my voice."** On Settings → Billing beside
  `BillingConfig.invoice_email_template` / `reminder_email_template` /
  `overdue_reminder_subject`: a one-line style box ("friendly, family business, Arkansas") and
  "Write it" → fills the textarea with the placeholders correctly placed (the proposal's
  prompt, with the placeholder list generated from the code that renders them, not typed).
  Owner saves as usual. This is the proposal's Phase 1+2; its Phase 3 (learn from edits, A/B)
  is dropped.
- Never a send, never a schedule, never an automatic draft. The button is the only trigger.

**What goes in the prompt:** invoice number, amounts, due date, days overdue, view
timestamps, the customer's company name and a one-word payment history (`usually_on_time` /
`often_late`), claim presence; the shop's name and style. Not the customer's email or phone.

**Reuse:** the send modal and `InvoiceEmailService`; `shop_sender`; `BillingConfig`
templates; `invoice-delivery-tracking` fields.

**Tests:** a PAID invoice shows no button; a tech sees no button; the draft never leaves
the modal without the owner's POST; AI6b's placeholder list equals the renderer's; the
template feature is hidden without a key.

**Done when:** Drake drafts a reminder for a real overdue Rockstar invoice, edits one word,
and sends it through the existing path.

**Notes / decisions for Drake:** the default tone; whether AI6b ships in the same PR.

---

## AI7 · Replacement pre-flight

**Goal:** given year/make/model and `glass_position`, produce the three or four questions to
ask the customer before ordering ("Rain sensor behind the mirror? Camera for lane-keeping?
Heated wiper park? Acoustic glass — a 'SoundScreen' label?") and a `requires_adas_calibration`
likelihood with the reason. Size S.

**Why it ranks here:** the costliest error in replacement is the wrong glass on the truck.
The Mygrant inquiry, when it is live (P1), prices a NAGS number — it does not tell a tech
which of four part numbers the vehicle takes. This narrows four lookups to one, from
information the customer can read off their own windshield.

**What to build:**

- On the job form when `service_type=replacement` and the vehicle fields are set: a
  "Before you order" card. Schema: `questions[]` (`text`, `why_it_matters`, `affects` ∈
  {`part`, `calibration`, `price`}), `adas_calibration` (`likely | unlikely | unknown`, `reason`),
  `notes_for_tech`. Suggest-only: a checked question appends its answer to
  `technician_notes`; `requires_adas_calibration` is *offered* ("Likely — mark it?"), never set.
- **Never a NAGS number, never a part number.** D2 (`IMPROVEMENT_SESSIONS.md`) is the
  licensing argument; hallucination is the other. The card says what to *ask*, the supplier
  says what to *order*. If a NAGS number is already typed, the card does not touch it.
- Cached by (year, make, model, position) in a small table for 90 days — the questions for a
  2021 Camry windshield do not change daily, and this keeps the cost at one call per vehicle
  per shop per quarter.

**What goes in the prompt:** year, make, model, glass position, `glass_type` if set. No
customer.

**Reuse:** the job form's replacement block; `price_book` (if a pinned row exists, note it
beside the card); `mygrant_service` is untouched.

**Tests:** output contains no string matching a NAGS pattern (`^(FW|DW|DB|FB|DQ)\d{3,5}`,
asserted on the mocked output *and* enforced by a post-filter in the view); the card is absent
on repairs; the cache hit skips the wrapper; a checked question appends and never overwrites.

**Done when:** for The Glass Guy's first real replacement, the card asks the questions his
dad would have asked, and the ADAS flag is right.

**Notes / decisions for Drake:** cache TTL; whether the card also appears on a `Quote` line
of type replacement.

---

## AI8 · Ask your shop

**Goal:** an owner types "how much does Penske owe me?" or "which unit have we repaired the
most?" and gets an answer with the rows it came from, read-only. Size M. **After AI1–AI4** —
global search already covers the easy half, and the isolation surface is the whole product.

**Why it ranks here:** high wow, generic. Every SaaS will have it within a year; the ones
that get it wrong leak a tenant's data. Build it last of the Tier 1/2 set, on a spine that has
been exercised by four features.

**What to build:**

- A tool-use loop (`client.messages` with `tools`, `auto` tool choice; the SDK tool runner
  is fine) over a **fixed list of tools, each a Python function returning a tenant-scoped
  queryset serialised to ≤ 50 rows**: `customers_matching(name)`, `invoices(customer_id,
  status, since)`, `jobs(customer_id, unit, status, since)`, `quotes(...)`, `claims(...)`,
  `unit_repair_counts(customer_id)`, `payments(...)`. The tool functions take `tenant`
  from the request, never from the model. There is no `run_sql`, no `raw`, no free-form
  filter — adding a question the tools cannot answer means adding a tool, with a test.
- UI: the global search box gains a "?"-prefixed mode or a second tab; the answer streams
  with the rows under it as links (`data-vt-key` on rows so the morph works). Owner/manager
  only — the answers are money.
- Each conversation is request-scoped (no stored history in v1); `AiCall` per turn.

**Tests:** two tenants with a "Penske" each — the answer and every row cited belong to the
asking tenant; a tool call with a forged `tenant` kwarg is rejected at the function
boundary; a question the tools cannot answer returns "I can't look that up" rather than a
guess; a tech gets 403.

**Done when:** ten real questions from Drake's list answer correctly on Rockstar's prod data
and the isolation test is in the guard set.

**Notes / decisions for Drake:** whether to keep per-session history (suggest no in v1).

---

## AI9 · Forward an email — PARKED

**Goal:** a fleet manager forwards or sends "three trucks with chips, units 12, 18 and 40,
Thursday if you can" to `<slug>@jobs.rssystems.io`; the shop finds three REQUESTED jobs in
the queue to confirm, each with the unit and the preferred day. Size L.

**Why parked:** it needs SES *receiving* — a receipt rule set, an S3 bucket or SNS topic, and
an inbound route — which the platform has never had, plus sender verification so a stranger
cannot create jobs by guessing the address (match the From against the tenant's
`CustomerUser` emails; anything else goes to the owner as "unknown sender wrote…"). It is
the email half of B2 (two-way SMS), which is itself TODO. **Revisit when a fleet customer who
is not family asks for it**, or when B2 is built and inbound exists for one channel.

**When it is unparked:** reuse AI1's extraction schema (a batch of it — `jobs[]`), create via
`handle_batch_repair_request`'s path with `queue_status='REQUESTED'`, and notify the owner
through the existing request notification. The parse is the easy part.

**2026-10-13 — reframed to SMS.** `AI_CORE_PLAN.md` carries the current shape: the owner or
tech texts the job to the RS Systems number and it lands on the day sheet scheduled. Staff
texting in is registrable under SMS v6 (`SMS_REGISTRATION.md` §3.5); a customer texting in
waits on B2 because the reply to them is the unregisterable half. The email transport above
is cut unless a non-family fleet asks for it by name.

---

## AI10 · Fleet health — PARKED

**Goal:** "Units 12 and 40 at Penske have been repaired three times each this year; a lot
walk is due" — and the inverse, "Penske's requests are down 60%; worth a call." The consumer
that FIELD_OPS S6 (lot-walking preferences) was deferred for lack of. Size M.

**Why parked:** it needs months of a non-family fleet's history; today every signal it would
read is Rockstar's, and Drake already knows Rockstar's fleets. **Revisit when a non-family
fleet has 90 days of jobs on the platform.** When it is unparked, the signals are
rule-based querysets (repair counts by unit, request cadence by customer) and the model only
writes the sentence — AI5's brief is the natural surface, not a new page.

---

## Appendix A — Amelia's two AI proposals, scored

| Proposal | Date | Disposition |
|---|---|---|
| `docs/proposals/ai-email-template-assistant.md` | 2026-03-21 | **Absorbed as AI6b.** Phase 1+2 as written (one button, a style line, placeholders generated from the renderer). Phase 3 (learn from edits, A/B on open rates) dropped — no volume to learn from, and the tracking proposal it leans on is itself Proposed. Its "paid tiers get AI" upsell line is overruled by decision 3 above: bundled. |
| `docs/proposals/ai-plan-recommendation.md` | 2026-03-21 | **Not an AI session.** Its Phase 1 is rule-based and has no model in it; it belongs beside the trial-expiry email work in `IMPROVEMENT_SESSIONS.md`, if anywhere. Its Phase 2 ("an LLM explains the recommendation") is a sentence AI5's brief could carry in a trial's last week, and is noted there, not built. Status line updated to say so. |

## Appendix B — considered and not queued, with the reason

- **Photo → instant quote / damage assessment.** The single most "magic" idea and the one
  P3 explicitly rejected: no customer photo leaves our infrastructure. Not revisited here;
  if it ever is, it is a change to `PHOTO_ML_SESSIONS.md`'s standing decision with Drake's
  name on it, and a local model would be the first option considered, not a hosted one.
- **Replying to Google reviews.** Needs the Google Business Profile API and an OAuth grant
  per shop; the review system today is a link-out by design. Backlog, not AI.
- **Technician coaching from comeback / warranty patterns.** "Resin didn't fill the legs"
  notes plus warranty claims would be a real signal at a hundred techs. At five, it is a
  sentence about one person. Not before a stranger shop has a year of history.
- **NAGS / part-number lookup from the vehicle.** D2's licensing problem in a new coat; a
  model confidently emitting `FW02345` is worse than a tech looking it up. AI7 deliberately
  stops at the questions.
- **Automatic anything to a customer.** Reminders (policy), review requests (already
  scheduled and rule-based), lifecycle emails (templated and correct). A model's words do not
  go to a shop's customer without the shop's hand on the button — AI3's estimate is the one
  exception and it is labelled as an estimate the shop confirms.
- **Support deflection from the 18 help guides.** Real, cheap, and mostly serves Drake rather
  than a shop. Worth a small session once the help center has traffic worth deflecting;
  Plausible (C3) will say when.
- **A second provider / provider abstraction.** No. One SDK, one wrapper, one place the
  argument lives (`common/ai.py`), exactly as the CSP allowlist lives in one middleware.

## Document history

| Date | Change |
|---|---|
| 2026-10-13 | `AI_CORE_PLAN.md` written: four rows build (AI0, AI1, AI2, AI4), five defer with a reopen condition (AI3, AI6, AI7, AI5, AI9 reframed to SMS), two cut (AI8, AI10). This doc stays the spec; that one owns scope. |
| 2026-10-12 | Created. Three decisions taken with Drake (text-only boundary, queue everything ranked, bundled cost). Ten sessions written, AI0 as the spine, AI9/AI10 parked with the condition that unparks each. Amelia's two proposals dispositioned (Appendix A). Nothing built. |
