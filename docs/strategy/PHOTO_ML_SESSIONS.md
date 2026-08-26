# Photo ML Sessions — tap-to-crop: a better photo for the customer, and a training set

**Created:** 2026-08-25
**Author:** Claude (planning session with Drake)
**Status:** living document — update statuses and Notes as sessions complete
**Companions:** none required; this arc is self-contained. The wider product queues live in `IMPROVEMENT_SESSIONS.md` and `FIELD_OPS_SESSIONS.md`.

**What this arc is for (the durable purpose statement — REVISED 2026-08-26):**
every damage photo a technician taps gets a **close-up of the break** derived
next to the untouched original. That close-up has **two** jobs, and for four
sessions this document only admitted to one of them:

1. **It is something the customer should see.** A close-up of the actual
   damage on the invoice is proof of work, and on a replacement it is the
   answer to "why couldn't you just repair it?" — plus insurance-claim
   evidence. **This is the job that pays the technician back for tapping, and
   it is not built yet (P6).**
2. **It is training data** for a future **"repairable vs not" classifier** —
   Drake's long-term goal, and the only thing P1–P4a were built for.

**The order matters and was wrong.** Written training-first, the arc gave a
tech nothing in return for a tap: the crop appears on one internal page and
feeds a model that does not exist. The result, measured in production on
2026-08-26, is a marking rate of **1 photo out of 77**. Purpose 1 is what makes
purpose 2 accumulate; a capture pipeline whose only payoff is a future model
does not capture. See **P6** and §The pause.

**The two purposes do not compete**, and that is worth understanding before
touching anything: the stored asset is the **percent coordinates**, not the
JPEG. Any crop — tight for training, generous for a customer — renders from the
same tap. One tap serves both forever.

Nothing in P1–P4a does any ML; they exist to make the dataset accumulate as a
side effect of normal field work, with enough metadata (percent coordinates on
EXIF-upright originals) that the dataset can be regenerated at any time. Do not
delete or "clean up" `RepairPhotoCrop` rows or `repair_photos/crops/` files
thinking they are derived caches — they are the product of human labeling work.

Each session is self-contained — a fresh Claude session with no memory should be
able to execute exactly one session using only §0 and that session's table,
without re-running the exploration that produced this doc.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED`

| Phase | Session | Size | Status |
|---|---|---|---|
| P1 · Capture | Tap-to-crop on upload (job form + old repair form) | M | DONE (2026-08-25, branch `feat/photoml-p1-tap-to-crop`) |
| P2 · Coverage | Detail-page crop/re-crop + retry queue + multi-break & customer-portal wiring | M | DONE (2026-08-25, branch `feat/photoml-p2-crop-coverage`) |
| P3 · Assist | Auto-suggest crops (local saliency detector; no photo leaves the server) | M | DONE (2026-08-25, branch `feat/photoml-p3-auto-suggest`) |
| P4a · Both classes | Crops on replacements + dataset export + class/accuracy report | M | DONE (2026-08-26, PR #218 → **re-landed as PR #219**, see the merge-race trap) |
| **P6 · Show the close-up** | **Put the marked point on surfaces customers already see — and fix three bugs there** | **M** | **TODO — DO THIS NEXT** |
| P4a.1 · Backfill | Mark the break on the photos we already have — one queue, not 77 jobs | S | DONE (2026-08-26, branch `feat/photoml-p4a1-backfill-queue`) |
| P3.1 · Validate | Run the suggester against the 77 real windshield photos we now have | S | TODO — **unblocked as of 2026-08-26**; P4a.1 is what produces the ground truth to score against |
| P5 · Negative class | Record the jobs we turn away — the only source of "not repairable" | M | TODO — **this is the actual gate on P4b** |
| P4b · Payoff | Repairability classifier | L | BLOCKED on **P5** — see P4b and §The pause |

**Suggested sequence, as revised 2026-08-26:**
P1 → P2 → P3 → P4a → P6 → P4a.1 → **P3.1 → P5** → P4b. Everything through
P4a.1 is built; P6 and P4a.1 are both in open PRs (#222 and this one).
**P3.1 is the cheap next one** — the backfill is what finally produces real
human marks to score the suggester against — but **P5 is the only thing that
unblocks P4b.**

The original sequence (P1 → P2 → P3 → P4a → P4b) assumed the only thing
standing between here and a classifier was volume. Two findings changed it:
the negative class accrues at **zero** per month (§The pause), and the positive
class accrues barely faster because tapping pays nobody back (1 of 77). **P6
before P4a.1** because backfilling 77 photos is worth an afternoon once each
one visibly improves a real invoice, and is charity before that. **P5 before
P4b** because P5 is the only negative-class source this business generates.

**Where we are (2026-08-26, end of day — the backfill is built; two PRs open):**

**P4a.1 shipped** on `feat/photoml-p4a1-backfill-queue`: `/tech/photos/mark/`
puts every unmarked damage photo in one queue — tap the break, Enter, next —
so burning down the backlog is a sitting rather than seventy-seven job pages.
Read P4a.1's Notes for what the queue does and does not include and why.

**Two PRs are open against `main` and they both edit this document's index
table**, so whichever merges second needs a small text conflict resolved (the
P6 and P4a.1 rows, the sequence line, and the history table — nothing
substantive). They are **deliberately not stacked**: P4a.1 branched off `main`
and needs nothing from P6, and the trap list explains at length what stacking
cost this arc last time.

- **#222 — P6**, the customer-visible close-up.
- **#224 — P4a.1**, the queue below.

**The order they land in matters for the copy, not the code.** The queue page
tells a technician their tap "becomes the close-up your customer sees on the
invoice", and that sentence is only true once #222 is on `main`. **Merge #222
first if you have the choice.** Nothing breaks either way — the tap is
recorded and the crop is derived regardless — but the page would be promising
something the product does not yet do.


**Step 0 for the next session: merge PR #219.** P4a's commits are *not* on
`main`, even though #218 reads MERGED — it was stacked on P3's branch and the
two merges landed ten seconds apart in the wrong order (see the merge-race
trap). #219 re-targets the same commits at `main` and carries the doc updates.
Production is nonetheless *running* P4a (`app-7d571-…`, deployed off the branch
directly), so prod behaviour is ahead of `main`. **Verify before building on
it:** `git log origin/main..origin/feat/photoml-p4a-both-classes-export` should
be empty once #219 lands.

**The arc was reframed today, by Drake, and the reframe is the important
part.** Asked what a shop actually gets out of tapping, the honest answer was:
nothing. Drake's response was that he had understood the close-up to be *a
better photo for the customer*, with training as the by-product — the reverse
of how P1–P4a were built. He is right about the direction and the production
numbers prove it: **1 of 77 eligible photos has ever been marked.** The revised
purpose statement at the top of this document is the durable version. **P6
exists to fix it and is the next session.**

Two corrections that came out of the same conversation, both now in §0:

- The mechanics are the other way round from the intuition. The **crop** is
  the derived, training-shaped artifact; the **original** is what is preserved
  *and what every customer already sees*. But the stored asset is the percent
  coordinates, so both uses render from one tap and never compete.
- **The invoice already crops these photos — blindly.**
  `public_invoice_view.html:51` renders them `height: 120px; object-fit:
  cover`, i.e. a centre-crop of the frame. That is precisely the "guess the
  centre" baseline P3 benchmarked at ~21% median error from the actual break.
  A human-marked point exists and the page ignores it.

**Collection and preservation, audited today:** preservation is sound —
`save_crop_for` never assigns to an original photo field (verified by grep),
`audit_repair_photos` enumerates crops so `--delete` cannot eat them
(`:94-97`), and P4a proved crops regenerate byte-identically from the stored
box. **Collection is not** — 1 of 77, for the reason above.

**The classifier is still gated on P5,** not on time; see §The pause for the
census.

**Where we were (2026-08-26, after P4a):****Where we were (2026-08-26, after P4a):** P1 merged as PR #211, P2 as PR #215.
P3 is PR #217, still open. **P4a stacks on P3's branch** — it needs P3's
provenance columns and its migration number, and `main` is still at P2, so
#217 must merge first. P4a fixed the structural blocker P3 discovered (crops
could only hang off a Repair, so the corpus was 100% positive class), added
the export, and made the class balance and the suggester's real accuracy
something the tooling reports out loud instead of something nobody had
measured. **P4b — training the classifier — is blocked on data, not on code,
and that is the correct state.**

**Where we were (2026-08-25, after P3):** P1 merged as PR #211, P2 as PR #215.
P3 built on `feat/photoml-p3-auto-suggest` (39 new tests; P1+P2's 37 still
green) and verified in a real browser end to end. **Every capture surface has
tap-to-crop except the customer portal, which by decision never asks a
customer to tap** (P2's Notes), and an unmarked photo on the detail page now
opens with a suggested marker already placed (P3).

**The big decision of this session: no damage photo leaves our
infrastructure.** The plan below originally recommended sending photos to a
hosted vision model; Drake rejected that outright because these are real
customers' photos. P3 is therefore a local pure-Pillow saliency detector — no
API key, no per-photo cost, nothing to train first. A test asserts the
suggester opens no sockets, so reversing this decision by accident is not
possible. See P3's Notes before reaching for a hosted model again.

That export step is now built (P4a), and it does measure the suggester.

**Sizes:** S ≈ half a day · M ≈ 1–2 days · L ≈ 3–5 days.

## How to run a session

1. Cut a fresh branch off the latest `main`: `feat/photoml-<id>-<slug>`. Never
   stack on another session's branch. Print `git branch --show-current` before
   every test run — another Claude session may share this working tree.
2. Read §0 plus your session's table. Do not read the whole document to do one
   session. Re-verify the `file:line` anchors before coding — the code moves.
3. Tests: use a private test DB name in `LOCAL_DATABASE_URL` (shared-worktree
   trap), run `tests.test_photo_tap_crop` plus your session's new tests, and
   compare failures against a `main` baseline worktree — never count absolutes
   (~90–105 pre-existing failures).
4. Commit files by name; never `git add -A`. Open a PR against `main`.
5. When done: flip the status in the index table and write what you learned
   under the session's **Notes** heading. That's what makes this a living doc.

## §0 · Context primer (read once per session)

**The data model.** `RepairPhotoCrop` (`apps/technician_portal/models.py`,
after the `Repair` model; migration `0057_repairphotocrop`): FK `repair`
**or** FK `replacement` — exactly one, both nullable, a CheckConstraint
(`photocrop_exactly_one_service`, migration `0060`) enforcing it, and one
unique constraint per FK. Both use related_name `photo_crops`; read the job
with `crop.service` and its kind with `crop.service_kind`, never by testing
the FKs. Then `tenant` FK + `TenantManager` (not auto-filtering
— call `.for_tenant()` in views), `source_field` in
{`damage_photo_before`, `damage_photo_after`, `customer_submitted_photo`},
`center_x_pct`/`center_y_pct` (the tap, 0–100), `crop_left/top/right/bottom` +
`natural_width/height` (nullable — null means the tap was recorded but the
image couldn't be opened; retry later), `cropped_image`
(upload_to `repair_photos/crops/`), `created_by` Technician. Unique on
`(repair, source_field)` — re-tap replaces, latest wins, no history.
P3 added provenance (`0058` + backfill `0059`): `confirmed_by_human`
(a human vouched for these coordinates — **the field P4 weights labels by**),
plus `suggested_x_pct`/`suggested_y_pct`/`suggested_by`/`suggestion_score`,
which stay on the row even after a technician moves the mark, so the guess
and the correction can be compared.

**The coordinate convention (do not break this).** Coordinates are percent of
the photo's natural, **EXIF-upright** dimensions. Browsers render photos
EXIF-upright (`image-orientation: from-image` is the CSS default), so a tap on
the rendered image is in upright space; the server MUST
`ImageOps.exif_transpose()` before measuring or cropping
(`apps/technician_portal/services/photo_crops.py::save_crop_for`). Percent (not
pixels) is what makes the crop regenerable from the original no matter how the
photo was displayed.

**The crop service.** `apps/technician_portal/services/photo_crops.py`.
Everything in it takes a **job** — a Repair or a Replacement — not a repair;
`job_kind(job)` and `_crop_fk(job)` are the only two places that decide which,
and the crop filename is namespaced by kind so a repair and a replacement
sharing an id cannot overwrite each other (`repair12_…` is unchanged, so no
existing file moved).
`process_tap_coordinates(job, post_data, technician=None, key_prefix='',
key_suffix='')` reads `crop_x_<field>`/`crop_y_<field>` POST pairs and only
touches Pillow when a pair is present — that is what keeps the wider test suite
(which uploads `b"fake image content"` photos) green. The prefix/suffix wrap
the names for forms that namespace their inputs (multi-break posts
`breaks[0][crop_x_damage_photo_before]`). `save_crop_for()` does the actual
crop: square box, side = `CROP_FRACTION` (0.35) of the shorter dimension with a
`MIN_CROP_PX` (300) floor, clamped by *shifting* into bounds, JPEG q90.
Everything fails open — a crop must never block saving a job in the field, and
a tap on an unreadable original is still recorded (null box) for
`retry_crop(crop)` / `manage.py retry_photo_crops` to finish later.
`delete_crops_for(repair, source_field)` removes crop + file when a source
photo is deleted. `save_crop_for` also takes `confirmed_by_human` and a
`suggestion` — **all three of its callers (tap, sweep, retry) must pass the
right provenance**, because `update_or_create(defaults=…)` writes every key.
`apply_suggestion(repair, source_field)` is the sweep's entry point; it
refuses to overwrite an existing crop.

**The suggester (P3).** `apps/technician_portal/services/photo_suggest.py`:
`suggest_point(fp)` → `Suggestion(x_pct, y_pct, score, engine)` or None, and
`suggest_for(repair, source_field)` for a stored photo. Pure Pillow, ~50ms,
**no network — a test asserts it opens no sockets**, because sending
customers' photos to a hosted model was explicitly rejected. Same
percent-of-EXIF-upright convention as a tap, so a suggestion drops straight
into the modal's marker and into the same columns. Returning None is normal
and frequent; `MAX_SPREAD` is the decline threshold and is a starting guess
meant to be tuned from real corrections, not from more test images. Killable
with `PHOTO_SUGGEST_ENABLED=false`.

**Where a crop is visible — and where it is not (verified 2026-08-26).** The
crop is a **second file derived beside the original; the original is never
modified, replaced or re-pointed** — `save_crop_for` contains no assignment to
`damage_photo_before` / `damage_photo_after` / `customer_submitted_photo`. That
is the core promise of the arc and it is what makes every crop regenerable from
stored percentages.

The consequence, which looks exactly like a bug the first time you meet it:
**no customer-facing surface has ever shown a crop, and none shows a label.**

| Surface | What it renders today |
|---|---|
| Public invoice page (`rs_systems/views.py:657-678` → `templates/billing/public_invoice_view.html:180-189`) | The **original**, CSS centre-cropped to a 120px tile (`:51`). **Repair line items only** — `exclude(repair_id__isnull=True)` at `:659` means a replacement invoice shows no photos at all. |
| Invoice email | No photos by design (multi-MB payloads get invoices quarantined at corporate gateways) — it links to the page above. |
| Customer portal repair / replacement / batch detail | The original, full frame (`damage_photo_before.url`). |
| Technician repair detail + `saas/replacement_detail.html` | **The only two places** referencing `photo_crops` / `cropped_image`, via `partials/photo_crop_control.html`. |

**And no label is stored anywhere at all** — labels do not exist as a column;
they are derived at export time by `services/photo_dataset.py`. So "I marked
the break but the invoice photo is uncropped and unlabeled" is the system
working as designed, not a defect. **P6 is the session that changes it.**

**Three live bugs on that invoice photo path**, all in the same ~20 lines and
all P6's to fix:
1. The tile is a **blind centre-crop** while a human-marked point sits unused.
2. **Replacements contribute no photos** (`:659`), so the invoices where a
   close-up matters most — the expensive ones — have none.
3. The caption is `Unit {{ photo.unit }}` fed from the raw
   `repair.unit_number` (`:672`). That is the documented individual-vs-fleet
   trap in CLAUDE.md: an individual has a blank `unit_number`, so their
   invoice caption reads "Unit  — Before". Must go through
   `get_vehicle_identifier()` / `vehicle_column_label`.

**Insurance lives on the shared base.** `insurance_claim`, `insurance_company`,
`claim_number`, `deductible` are on `GlassService`, so **Replacement has them
too** — a documented close-up of the damage is claim evidence, which is part of
why cropping a replacement is worth a tech's time independent of any model.

**The photo fields.** On the abstract `GlassService` base
(`apps/technician_portal/models.py:517-544`), so `Repair` AND `Replacement`
both have them. P1–P3 cropped repairs only; **P4a crops both**, because that
is the only way the negative class can ever exist.

**The labels.** `apps/technician_portal/services/photo_dataset.py` (P4a) is
the single place that turns a crop into a training label, and it derives it
from **what the shop did**, which is the only ground truth available: a
completed repair is `repairable`; a completed *windshield* replacement is
`not_repairable`. Side and rear glass is tempered — it shatters and is always
replaced no matter what hit it — so a non-windshield replacement is
`not_applicable`, not a negative. Anything undecided is `unknown`, and an
`damage_photo_after` crop is `not_applicable` (it is a photo of the outcome;
training on it would teach the model that resin-filled chips are the
repairable ones). Every row carries the `label_source` rule that fired, so a
training run can drop a rule it doesn't trust without re-deriving anything.

**Upload surfaces map** (who converts HEIC, who compresses, who has tap-to-crop):

| Surface | View | HEIC→JPEG | Client compress | Tap-to-crop |
|---|---|---|---|---|
| Unified job form `/tech/jobs/new/` | `views/jobs.py::job_create` | yes (P1) | `image_compress.js` auto-wire | **P1**, repairs *and* replacements since **P4a** |
| Old repair form create/update | `views/repairs.py` | yes | `repair_form.js` (manual) | **P1** |
| Multi-break | `views/batch.py` | yes | `multi_break.js` | **P2** (one tap per break, posted as `breaks[i][crop_x_<field>]`) |
| Customer portal request | `customer_portal/views.py` (~:1800) | yes | none | never — by decision, customers are not asked to tap; the shop marks their photo from the detail page |
| Repair detail page | `views/repairs.py::save_photo_crop` | n/a | n/a | **P2** (crop or re-crop any photo already on the job) + **P3** (an unmarked photo opens on a suggested marker, via `suggest_photo_crop`) |
| Replacement detail page `/tech/replacement/<pk>/` | same two views, `kind='replacement'` | n/a | n/a | **P4a**. Same partial, same JS, endpoints `/tech/replacements/<id>/photo-crop/[suggest/]`. Permission comes from `_replacement_technician_access`, not `can_view_repair`. The *after* photo is not markable — it is new glass |
| **Backfill queue `/tech/photos/mark/`** | `views/photo_backfill.py::photo_backfill_queue` | n/a | n/a | **P4a.1** — every photo with no *human-confirmed* mark, repairs and replacements, in one list. Read-only itself; each tap POSTs to `save_photo_crop`. Membership rules live in `services/photo_backlog.py` |
| Backlog sweep | `manage.py suggest_photo_crops` | n/a | n/a | **P3** (marks unmarked photos `confirmed_by_human=False`; never overwrites a tap, never touches an original); **P4a** adds `--kind` and sweeps replacements |
| Dataset export | `manage.py export_photo_dataset` | n/a | n/a | **P4a** — read-only; images + JSONL, anonymised, with a class-balance and suggester-accuracy report every run |

**The client JS contract.** The modal itself belongs to
`static/js/photo_crop_modal.js` (ES5 IIFE, house style), which owns
`#photoCropModal` (partial:
`templates/technician_portal/partials/photo_crop_modal.html`, standard `ui.js`
modal contract) and exposes `PhotoCropModal.open({src, title, hint,
confirmLabel, at, onConfirm(xPct, yPct), onSkip})`. **It must load before any
driver.** `open()` returns a **session token** (P3); `suggest(token, x, y)`
pre-places a machine marker and `setHint(token, text)` swaps the sub-line,
both no-ops on a stale token or once the tech has tapped. Three drivers use
it: `photo_tap_crop.js` (upload forms),
`photo_crop_detail.js` (repair detail page — POSTs to `save_photo_crop`) and
`multi_break.js` (keeps the tap in its `breaks[]` state).

On the upload forms, `input[data-tap-crop="<field>"]` marks a crop-eligible
file input. After compression finishes, `image_compress.js` and
`repair_form.js` dispatch a bubbling `photocrop:offer` CustomEvent
(`detail: {file}`) on the input; `photo_tap_crop.js` listens on `document`,
opens the modal, and on Confirm writes the hidden inputs
`crop_x_<field>`/`crop_y_<field>` that live inside each form. Skip/Escape/
overlay close = coords stay empty = server does nothing. The photo "Remove"
buttons clear coords via `window.PhotoTapCrop.clear(input)` (programmatic
`input.value=''` fires no change event). On the job form the offer is gated on
`service_type == 'repair'`. The four `crop_*` names are in FormAutosave's
`excludeFields` in both forms — autosave persists hidden inputs, and restored
coords would orphan from a photo autosave can't restore.

**Storage.** Prod: S3 via `STORAGES` in `rs_systems/settings/production.py`,
unsigned public URLs, everything under prefix `media/`. Crops:
`media/repair_photos/crops/`. Dev pre-creates the local dirs in
`development.py`. `core/management/commands/audit_repair_photos.py` diffs S3
against DB references — **any new photo-bearing field or model MUST be added to
its enumeration or `--delete` destroys the files as orphans** (P1 added crops +
fixed two blind spots: soft-deleted repairs and all Replacement photos).

**Tests.** `tests/test_photo_tap_crop.py` (13, P1),
`tests/test_photo_crop_coverage.py` (24, P2),
`tests/test_photo_suggest.py` (39, P3),
`tests/test_photo_dataset.py` (40, P4a),
`tests/test_photo_backfill_queue.py` (37, P4a.1). `real_jpeg()` there
builds actual decodable JPEGs (with optional EXIF orientation);
`QuickJobForm` uses `forms.ImageField`, which rejects fake bytes at form
validation — but model-level writes (multi-break, customer portal) don't, so
fake-bytes photos exist in the wild and the crop service must swallow them.
Postgres recipe when local auth fails: scratch cluster via
`/Library/PostgreSQL/16/bin/initdb` + `pg_ctl -o "-p 5433 -k /tmp"`, role
`amelia_test`, private DB name.

## Traps this work has already hit — don't repeat them

- **EXIF orientation vs tap coords** (P1): crop without `exif_transpose` and
  every portrait iPhone photo's crop lands in the wrong place. The client
  canvas re-encode strips EXIF from compressed JPEGs, but HEIC and <500KB
  files keep theirs.
- **Fake-bytes tests** (P1): any code path that unconditionally `Image.open`s
  uploads breaks dozens of existing tests. Gate image-opening on the tap
  coords being present; fail open on unreadable bytes.
- **`audit_repair_photos --delete`** (P1): it deletes anything in S3 not
  enumerated from the DB. New photo fields/models must be added to it in the
  same PR that creates them.
- **HEIC won't render in `<img>`/canvas off-Safari** (P1): the tap modal
  silently skips those (photo still uploads). iPhone Safari — the main HEIC
  source — renders fine. `pillow-heif` opens them server-side (opener
  registered in `apps/technician_portal/apps.py`).
- **Programmatic input clears fire no `change` event** (P1): the Remove
  buttons must clear crop coords explicitly (`PhotoTapCrop.clear`).
- **`multi_break.js` keeps Files in a JS array** and posts bespoke FormData —
  there is no simple input hook; P2 needs per-break coordinate fields.
- **FormAutosave persists hidden inputs** — exclude any new coord fields.
- **CustomEvents don't bubble by default** — pass `bubbles: true` or a
  document-level listener never hears them.
- **CSS purge**: new `@layer components` classes unused by templates get
  purged; safelist in `tailwind.config.js` or (better) inline-style small
  one-off UI like the tap marker. P1 used only existing classes — no CSS
  rebuild was needed.
- **10MB request cap** (nginx + Django): photos are client-compressed before
  posting; don't add anything that re-inflates the payload.
- **`image_compress.js` has no `?v=` cache-buster** (P2): the dev server sets
  no `max-age`, so Chrome heuristically caches it for hours and can run a copy
  from before your change while the file on disk is right. A tap-to-crop bug
  that makes no sense is this until proven otherwise — hard-reload
  (`fetch(src, {cache:'reload'})` then `location.reload()`) before debugging.
- **A re-tap reuses the crop's filename** (P2): `save_crop_for` deletes the old
  file first, so the same name is free again and the browser serves the stale
  close-up. Any surface showing a crop must version the URL — the detail page
  uses `?v={{ crop.updated_at|date:'U' }}`, the JS uses a timestamp.
- **A confident wrong answer is worse than no answer** (P3): the first scoring
  function rated a foliage boundary 0.89 while pointing 32% away from the
  chip. Any suggestion engine here needs a signal that catches *ambiguity*,
  not just strength — see P3's Notes on compactness.
- **`save_crop_for` is called by three paths with different provenance** (P3):
  a tap, a sweep suggestion, and `retry_crop` re-deriving an existing row. Any
  new field on `RepairPhotoCrop` must be threaded through all three, or a
  retry silently resets it. `update_or_create(defaults=…)` writes every key.
- **A suggestion is asynchronous but the modal is not** (P3): open first, mark
  later, and gate the late arrival on a session token — otherwise a slow
  answer for photo A drops a marker on photo B.
- **Patching a name in its source module rebinds a lazily-imported consumer
  for the rest of the process** (P4a). `suggest_photo_crops` does
  `from ...photo_suggest import is_enabled` at module scope, and Django only
  imports the command module when `call_command` first runs it. Patch
  `photo_suggest.is_enabled` and then trigger that first import *inside the
  same `with` block*, and the command binds the **mock** as its module-level
  `is_enabled` — the patch exiting restores `photo_suggest`, not the copy the
  command took. Every later test in the process then sees a mock that returns
  True, so `test_kill_switch_stops_the_sweep` failed only when a new test
  module ran ahead of it, and passed in isolation. Flip the switch with
  `override_settings(PHOTO_SUGGEST_ENABLED=…)` — the house idiom — and patch
  only leaf functions like `suggest_for`.
- **A crop of a repair is not a neutral data point** (P4a). It is a positive
  label by construction. Any pipeline that collects only repairs is
  collecting only one class, and it will look healthy the whole time — rows
  accumulate, files land, tests pass. The tell is a count nobody prints;
  `export_photo_dataset` now prints it every run and says "Only one class
  present" in red.
- **Side and rear glass is tempered** (P4a): it always gets replaced, so a
  non-windshield replacement is not evidence that anything was unrepairable.
  Labeling it as a negative would have taught the model that a shattered door
  window is what unrepairable windshield damage looks like.
- **A capture pipeline with no user-visible payoff does not capture**
  (2026-08-26). P1–P4a built four sessions of tap-to-crop whose entire visible
  output was a thumbnail on an internal page, in exchange for a model that
  does not exist yet. Production marking rate: **1 photo out of 77**. The code
  was never the problem and no further capture surface would have helped.
  **If you are asking a human for fifteen seconds, find what those fifteen
  seconds give *them* before you optimise the mechanism.** P5's table already
  says this about declined work; it applies with equal force to the four
  sessions that came before it, and nobody noticed until Drake asked what a
  shop gets out of cropping.
- **Do not zoom the *after* photo of a repair** (2026-08-26, product
  judgement). A resin repair leaves a visible blemish — that is normal and
  expected. A tight close-up magnifies the scar and shows the customer the
  flaw instead of the fix. Before → close-up. After → full frame. This is
  also consistent with the dataset, which labels after-photos
  `not_applicable`.
- **A stacked PR can merge green and land nowhere** (2026-08-26). #218 was
  based on P3's branch, correctly — it needed P3's columns and migration
  number. #217 merged that branch into `main` at `18:30:31Z`; #218 merged P4a
  *into the same branch* at `18:30:41Z`, ten seconds later. Both PRs report
  MERGED. `main` has P3 and none of P4a, and the tip carrying P4a is a commit
  no branch consumes. **Merging a stack bottom-up is a race, and GitHub's
  "Merged" badge is not evidence your code is on `main`.** After any stacked
  merge, verify with `git log origin/main..origin/<branch>` — empty or it did
  not land. Better: don't stack. The house rule (one session, one branch off
  `main`) exists for this, and P4a broke it for a real reason and still paid
  for it.
- **A pipeline can be code-complete and still collect nothing** (2026-08-26).
  P4a made the negative class *possible*; the census afterwards found the
  production database has never contained a single `Replacement` row. Every
  test passed, every surface worked, and the collection rate for half the
  dataset was zero and always had been. **Count the rows in production before
  declaring a data pipeline done** — `--stats-only` on a seeded dev database
  proves the code runs, not that anything is arriving.
- **`Repair` has no `created_at`** (2026-08-26) — the date field is
  `service_date`. A rate query written from habit raises `FieldError` listing
  every field on the model, which is at least a fast way to find that out.
- **A backlog nobody can see is a backlog nobody burns down** (P4a.1). Every
  photo in the 1-of-77 could already be marked from its job's detail page, and
  had been able to since P2. The missing thing was never the ability; it was
  that the app never once said "there are 77 of these". The fix was one link
  in a summary line and one page that puts them in a row. **Before building a
  better way to do a thing, check whether anyone knows the thing is waiting.**
- **`{# … #}` is single-line only** (P4a.1) — CLAUDE.md says so, and I wrote a
  three-line one anyway. It renders as visible prose on the page: in this case
  a paragraph of implementation notes across the top of a technician's tap
  surface. Use `{% comment %}…{% endcomment %}`.
- **`Repair.vehicle_description` is a read-only property**, not a column
  (P4a.1) — it is derived from `vehicle_year`/`vehicle_make`/`vehicle_model`,
  and `vehicle_year` is an **IntegerField**, so `vehicle_year=''` dies too. A
  fixture written from habit hits both in one line.
- **A confirm that needs scrolling is not a confirm** (P4a.1). The queue's
  first layout gave the photo `62vh` and pushed both buttons below the fold —
  on a page whose entire design is tap, Enter, tap, Enter without moving. If a
  surface is meant to be repeated dozens of times, measure it against one
  screen before anything else.
- **`MEDIA_ROOT` is a real directory that survives between runs** (P3): dev
  and test share `media/`, and it accumulates crop files. Any test that
  counts or names files there must diff against what was already present.
  P1's `test_retap_replaces_the_previous_crop` asserted a re-tap gets a
  *different* filename and passed only because a stale file from an earlier
  run was squatting on the base name — on a clean `media/` it failed, on
  `main` as well as on the P3 branch. It now asserts the real invariant
  (one file survives, the box moved) and says nothing about the name.

---

# P1 · Tap-to-crop on upload — DONE (2026-08-25)

| Field | Value |
|---|---|
| **Goal** | Tech attaches a damage photo → modal shows it full-size → tap the break → server saves a square crop + coordinates next to the untouched original. Skippable, never blocks. Repairs only. |
| **Size** | M |
| **Depends on** | — |
| **Why it matters** | Starts the training-set clock. Every photo that goes uncropped is a labeled example lost — the tech's knowledge of where the break is exists only at capture time. |
| **Acceptance criteria** | Crop row + file created from both the unified job form and the old repair form; skip/no-coords paths leave zero rows and open no image server-side; EXIF-rotated photos crop in the right place; deleting a photo deletes its crop; replacements unaffected; `audit_repair_photos` enumerates crops. |
| **Out of scope** | Multi-break and customer portal (P2). Detail-page crop/re-crop (P2). Any auto-detection (P3). |

**Notes**
*(session run 2026-08-25, branch `feat/photoml-p1-tap-to-crop`)*
- Shipped exactly the §0 architecture; §0 was written from this session's
  verified state, so trust its anchors as of this date.
- Decisions taken: after-photo prompt reads "Tap the repaired spot" (before/
  customer photos read "Tap the break"); re-tap replaces (unique constraint);
  crop constants are module constants in `photo_crops.py`, not settings.
- Rode along: HEIC→JPEG conversion added to `views/jobs.py::job_create` (was
  the only tech upload path storing raw HEIC), and `audit_repair_photos` fixed
  to enumerate soft-deleted repairs (`all_objects`) and Replacement photos —
  both were `--delete` data-loss holes.
- Tests: `tests/test_photo_tap_crop.py`, 13 tests. Baseline note: 5 failures in
  `test_multi_break_repair` + `test_code091_*` reproduce identically on `main`
  (damage_type choices drift) — not this work.
- P2 should reuse `save_crop_for` untouched: it already handles
  `customer_submitted_photo` and records taps on unreadable images for retry.

# P2 · Coverage: detail-page crop/re-crop, retry queue, remaining surfaces — DONE (2026-08-25)

| Field | Value |
|---|---|
| **Goal** | A break can be tapped (or re-tapped) after upload from the repair detail page; the multi-break form and the customer-portal request flow capture taps too; crops that failed (null box) get retried. |
| **Size** | M |
| **Depends on** | P1. |
| **Why it matters** | P1 only captures at upload time on two of four surfaces. Multi-break is the power-user path (several breaks per windshield = several labeled examples per job), and old photos + skipped taps are recoverable labeling work. |
| **Verified current state** | See §0 upload-surfaces map. Detail page: `templates/technician_portal/repair_detail.html` photo section ~:564-666 with `openImageModal()` lightbox ~:794 — natural home for a "Mark the break" action. Multi-break: per-break File objects in `multi_break.js` `breaks[]`, posted as `breaks[i][photo_before]` FormData (`views/batch.py` ~:397-463); per-break coords need matching `breaks[i][crop_x_before]` keys. Customer portal: `customer_portal/views.py` ~:1800 writes `customer_submitted_photo` directly. |
| **Considerations** | Detail-page tap needs a small POST endpoint (tenant-scoped, technician-gated) calling `save_crop_for` — the P1 hidden-input transport doesn't apply there. Retry = iterate rows with `cropped_image=''`/null dims and call `save_crop_for` with the stored coords. Customer-portal UX must stay optional and dead simple — customers are not techs. |
| **Decision taken** | Techs only. Customers are never asked to tap; their photos are marked by the shop from the detail page (which handles `customer_submitted_photo` like any other). The customer-portal request flow is unchanged. |
| **Acceptance criteria** | Every crop-eligible photo on the detail page can be tapped/re-tapped; multi-break taps produce one crop per break's photo; a failed crop retries successfully once the image is readable. |
| **Out of scope** | Auto-suggest (P3). Bulk backfill UI for hundreds of old photos — do it only if the shop actually wants to label history. |

**Notes**
*(session run 2026-08-25, branch `feat/photoml-p2-crop-coverage`)*
- **The modal is now a shared module.** `static/js/photo_crop_modal.js` owns
  `#photoCropModal` and exposes `PhotoCropModal.open({src, title, hint, at,
  onConfirm(xPct,yPct), onSkip})`; three thin drivers sit on top —
  `photo_tap_crop.js` (upload forms, writes hidden inputs),
  `photo_crop_detail.js` (detail page, POSTs on its own) and `multi_break.js`
  (keeps the tap in its `breaks[]` JS state). **Load `photo_crop_modal.js`
  before any of them.** P1's `photo_tap_crop.js` was rewritten onto this and
  its behaviour re-verified in a browser — its public contract
  (`data-tap-crop`, `photocrop:offer`, `PhotoTapCrop.clear`) is unchanged.
- **Detail page**: `POST /tech/repairs/<id>/photo-crop/` (`save_photo_crop`,
  name `save_photo_crop`), tenant-scoped and gated by the existing
  `can_view_repair` helper. Every photo on the page gets a "Mark the break"
  button via `partials/photo_crop_control.html`; one that already has a crop
  shows the thumbnail and reads "Move the mark", and re-opening pre-places the
  previous mark (`at:`) so a correction is a nudge, not a fresh hunt.
- **Multi-break**: coords ride in the bespoke FormData as
  `breaks[i][crop_x_<field>]`, read back by the new `key_prefix`/`key_suffix`
  arguments on `process_tap_coordinates` — no second parser. The break dialog
  predates the shared modal skeleton and sits at `z-index: 1000`, so that page
  raises `#photoCropModal` to 1100 in its own `extra_css`. The localStorage
  draft deliberately does NOT persist taps: it can't persist Files either, and
  a tap restored without its photo is an orphan.
- **Retry**: `manage.py retry_photo_crops [--dry-run] [--tenant N] [--limit N]`
  re-runs `save_crop_for` from the stored percentages for any row with no
  derived image. Not wired into EB cron — it is a manual sweep, and cron in
  this app has four documented ways to fail silently (see CLAUDE.md).
- Traps hit this session, both now in the list above: a stale browser cache of
  `image_compress.js` (no `?v=`) made a working upload path look broken for
  half an hour, and the crop filename is reused on a re-tap, so the detail
  page versions the thumbnail URL by `updated_at`.
- Tests: `tests/test_photo_crop_coverage.py`, 24 tests. Baseline note:
  `test_code105_repair_detail_unscoped_technician` fails identically on `main`
  (a Manager badge assertion) — not this work. The multi-break form's
  `damage_type` options post display strings (`Chip`, not `CHIP`) — the same
  choices drift P1 saw.
- P3 should suggest from the detail page rather than the upload modal: the
  endpoint, the pre-placed marker (`at:`) and the re-crop UI are already there,
  so a suggestion is just a marker the tech confirms — and it costs the tech
  nothing while they are still in the field.

# P3 · Assist: auto-suggest crops — DONE (2026-08-25)

| Field | Value |
|---|---|
| **Goal** | The modal opens with a suggested marker already placed; the tech confirms or nudges. Capture rate goes up because confirming is cheaper than aiming. |
| **Size** | M |
| **Depends on** | P1 (modal + coords plumbing), P2 (detail-page endpoint + `at:` marker). |
| **Why it matters** | The dataset grows only as fast as techs tap. A one-tap confirm beats an aim-and-tap, and the suggestion engine is a dry run for P4's model. |
| **Decisions taken** | **(1) Local only — no hosted vision model.** Drake's call: these are real customers' photos and they do not leave our infrastructure. The Claude-vision stage this plan originally recommended is *not* built and should not be built without asking him again. **(2) Suggest from the detail page**, as P2 recommended: the photo is already on S3 so the server fetches it itself (the upload modal would mean a second upload of the photo over field data), and P2's endpoint, `at:` marker and re-crop UI were already there. **(3) Sweep the backlog too**, on Drake's condition that originals are preserved — they are, and three tests assert it byte-for-byte. |
| **Acceptance criteria** | ✅ Suggestion appears in under ~3s or not at all. ✅ Tech can always override. ✅ Suggested-but-unconfirmed is distinguishable in data and UI. ⚠️ **But accuracy was never an acceptance criterion, and that was the mistake — see "The detector does not work well enough" below. It ships DISABLED.** |
| **Out of scope** | The repairability classifier itself (P4). A hosted vision model (rejected). Suggesting inside the upload modal (the photo isn't on the server yet). |

**Notes**
*(session run 2026-08-25, branch `feat/photoml-p3-auto-suggest`)*

### The detector does not work well enough — it ships disabled

Benchmarked after the fact against the dumbest possible baseline, "guess the
centre of the photo", over 12 randomised chip placements per condition:

| condition | detector median error | centre-guess median error |
|---|---|---|
| chip on clean glass | **0.2%** | 21.2% |
| chip + road grime + wiper + dash in frame | **30.7%** | 22.4% |

On a clean pane it is excellent. On a windshield that looks like a windshield
it is **worse than guessing the middle of the frame** — and it does not
decline, it answers confidently all 12 times. The spread gate catches diffuse
texture (foliage), but a bug splat is a compact high-contrast blob, which is
exactly what the algorithm is built to find. Most real windshields are dirty.

`PHOTO_SUGGEST_ENABLED` therefore defaults to **False**, and
`test_clutter_defeats_the_suggester` pins the failure so it cannot be quietly
forgotten — **that test is designed to fail once the suggester is actually
fixed.**

Two process lessons worth more than the code:

1. **Fixtures I invented were graded by the same intuition that wrote the
   algorithm.** The clean-glass fixtures were near-perfect from the first
   run, which read as success and stopped the investigation. Nothing was
   validated until a baseline was introduced.
2. **A baseline should come before the algorithm, not after.** "Guess the
   centre" takes one line and would have set the bar on day one. Without it,
   "0.2% error" sounds like proof and is not.

**Nothing here has ever been run against a real windshield photo.** That is
still true, and it is the first thing P3.1 should fix.


- **The suggester is `apps/technician_portal/services/photo_suggest.py`, pure
  Pillow, ~50ms.** No numpy, no OpenCV — neither is installed and neither was
  added. The method, in four lines: high-pass the greyscale thumbnail to get
  local structure; blur it small to gather structure into blobs; blur it large
  to measure how busy the neighbourhood is anyway; subtract. What survives is
  structure that stands out *from its surroundings*, which is what a chip in
  glass is and what a uniformly textured background is not. A gentle centre
  prior encodes the fact that the tech aimed the camera at the break.
- **Compactness is the confidence signal, not peak height.** This was the one
  real discovery of the session. The obvious score — how tall is the peak
  relative to the mean — rates a sky/foliage boundary behind the glass at 0.89
  while it points 32% away from the actual chip. Confidently wrong. Measuring
  instead how *spread out* the bright patch is separates the cases cleanly:
  chip ≈ 0.01, crack ≈ 0.07, background texture ≈ 0.14, all as a fraction of
  the image diagonal. Above `MAX_SPREAD` (0.12) the suggester returns nothing,
  and nothing is a perfectly good answer — the tech gets the plain P1 modal.
- **The mark is the hot region's centroid, not the peak pixel.** On a crack the
  peak lands wherever contrast happens to be highest, usually near one end
  (36% error on a test crack); the centroid lands mid-crack (12%). On a chip
  the two agree to within a pixel.
- **`MAX_SPREAD = 0.12` is a starting guess and is documented as one.** It was
  set against synthetic fixtures, which is not evidence. Do not hand-tune it
  against more synthetic images — every row now stores `suggested_x/y_pct`
  beside whatever the technician finally marked, so the first few hundred real
  corrections will say where the threshold belongs. That is also the honest
  answer to "is this thing any good": measure the correction distance.
- **New columns on `RepairPhotoCrop`** (`0058` + backfill `0059`):
  `confirmed_by_human`, `suggested_x_pct`, `suggested_y_pct`, `suggested_by`,
  `suggestion_score`. `0059` marks every pre-P3 row confirmed — the field
  defaults to False so a machine guess is untrusted by default, which makes
  the default exactly wrong for the hand-labeled P1/P2 rows. A separate
  `origin`/`suggested` boolean was considered and dropped: it would have been
  a strict function of `confirmed_by_human` + `suggested_by`, i.e. a third
  copy of the same fact waiting to drift.
- **`retry_crop` had to learn to carry provenance.** It re-derives the image
  from stored percentages by calling `save_crop_for` again, which would have
  reset the new fields to their defaults and quietly demoted every
  technician's tap that ever needed a retry. Tested both directions.
- **`POST /tech/repairs/<id>/photo-crop/suggest/`** (`suggest_photo_crop`).
  It shares `_resolve_crop_target` with `save_photo_crop` deliberately: two
  endpoints answering for the same object under two copies of a permission
  check is how one of them ends up laxer, and a lax suggest endpoint is a way
  to read another shop's photos. `found: false` is a **success**, not an error.
- **The modal now hands out a session token.** `PhotoCropModal.open()` returns
  an integer instead of `true`; `suggest(token, x, y)` and `setHint(token, …)`
  no-op on a stale one. Without it, a slow suggestion for one photo lands on
  whichever photo the tech opened next. `suggest()` also refuses once the tech
  has tapped (a new `tapped` flag, distinct from "a marker is showing"), and
  parks the suggestion if it beats the image's `onload` — marker positions are
  read off the rendered `<img>`, so it has to wait for layout.
- **`manage.py suggest_photo_crops [--dry-run] [--tenant N] [--limit N]
  [--field F]`** sweeps unmarked photos. It refuses to overwrite an existing
  crop, so it can never trample a tap and re-running it is a no-op. Manual,
  not cron — same reasoning as `retry_photo_crops`. Note `iterator()` needs an
  explicit `chunk_size` after `prefetch_related`, or it raises.
- Traps hit: `Repair.technician` is NOT NULL, so a second-tenant fixture needs
  its own `Technician`. And the shared working tree switched branches under
  this session mid-run (the documented collision) — the recovery is to back
  the work up outside the repo first, then move.
- **Rode along**: fixed P1's `test_retap_replaces_the_previous_crop`, which
  was passing for the wrong reason (see the new `MEDIA_ROOT` trap above). It
  fails on `main` too on a clean media directory — found by running the full
  suite, not the crop suite, because a full run uses repair ids no previous
  run had written files for.
- **Full-suite baseline for this branch**: 4445 tests, 92 failures, against
  `main`'s 4406 / 95 on the same machine and cluster. **Zero new failures**;
  the three that differ fail on `main` and pass here (order-dependent
  customer-register flakes). Both runs were done in parallel worktrees with
  separate DB names — expect ~75 min wall-clock each under that contention,
  not the usual ~7.
- **For P4**: `confirmed_by_human=True` rows are the strong labels;
  `False` rows are machine guesses nobody has looked at and should be weighted
  down or excluded — training on them would teach the next model to imitate
  this one. Rows where `suggested_by` is set *and* `confirmed_by_human` is
  True are the most interesting of all: those carry both the guess and the
  human's correction, which is the training pair for a learned detector.

# P4a · Both classes, and an export that counts them — DONE (2026-08-26)

| Field | Value |
|---|---|
| **Goal** | Make the negative class collectable at all, then export the corpus and report honestly what is in it. |
| **Size** | M |
| **Depends on** | P1–P3. Built on P3's branch, because it needs P3's provenance columns and its migration number. |
| **Why it matters** | P3 discovered that `RepairPhotoCrop` could only hang off a `Repair`. A crop of a repair is by definition a photo of damage that WAS repaired, so every crop the arc had ever collected was the positive class — and no amount of further waiting would have changed that. The dataset was not "small yet". It was structurally untrainable, and nothing in the app said so. |
| **Acceptance criteria** | ✅ A crop can hang off a Replacement, enforced so it can never hang off both or neither. ✅ Every surface that captures a repair tap captures a replacement tap. ✅ `export_photo_dataset` produces images + JSONL, anonymised and tenant-scoped. ✅ The bundle regenerates byte-identically from the originals using only stored metadata. ✅ Every run reports the class balance and the suggester's real correction distance. |
| **Out of scope** | Training anything (P4b). Tuning `MAX_SPREAD` — the export now measures it, but there is no real data to tune against yet. |

**Notes**
*(session run 2026-08-26, branch `feat/photoml-p4a-both-classes-export`, 40 new tests)*

### The blocker, and how invisible it was

The bug was not that replacements lacked a feature. It was that the pipeline
had a *sampling* fault: it collected labels only from jobs whose label was
always the same value. Everything downstream looked healthy — rows
accumulated, crops rendered, 77 tests passed, the detail page showed
thumbnails. The only symptom was a count nobody was printing.

Three things now make that impossible to repeat:

1. `RepairPhotoCrop` carries both FKs with a `CheckConstraint` that exactly
   one is set (`InvoiceLineItem` precedent, migration `0060`).
2. The unified job form's tap was gated on `service_type == 'repair'`, in the
   view **and** in `photo_tap_crop.js`. That gate is gone — it was the single
   highest-volume place the app declined to label a negative. Its P1 test,
   `test_replacement_posts_are_ignored`, asserted the old behaviour and has
   been rewritten to assert the new one.
3. `export_photo_dataset` prints the class balance every run, and says
   **"Only one class present — a classifier cannot be trained on this"** in
   red when that is true. A test pins that message.

### What the label actually is

`services/photo_dataset.py` derives labels from **what the shop did**, which
is the only ground truth here and a good one: a technician who replaced a
windshield decided, with the glass in front of them, that the damage was not
repairable.

The one piece of real domain knowledge in it: **tempered glass**. Side and
rear windows shatter and are always replaced, so a non-windshield replacement
says nothing about repairability — it is `not_applicable`, not a negative.
Blank `glass_position` is common and usually means a windshield, but
"usually" is not a label, so it keeps a distinct `label_source`
(`replacement_completed_glass_unspecified`) that a training run can drop in
one line. `damage_photo_after` crops are `not_applicable` too: training on a
resin-filled chip would teach the model that repaired damage is the
repairable kind.

### The export

`manage.py export_photo_dataset [--out DIR] [--tenant N] [--limit N]
[--include-unconfirmed] [--trainable-only] [--from-originals] [--stats-only]`

- Read-only. Nothing is written back to the database or to media storage, and
  no original is touched.
- Anonymised: ids only. No customer name, unit number, plate or note text
  reaches the bundle. A test greps the JSONL for the customer's name.
- Unconfirmed machine suggestions are **excluded by default** — training on
  the suggester's own unreviewed output teaches the next model to imitate it.
- `--from-originals` re-derives every crop from the untouched original using
  only the stored box, at `save_crop_for`'s Pillow settings, and comes out
  byte-identical. That is the standing proof that the derived files are
  disposable and the coordinates are the real asset. Verified through the CLI
  as well as in a test.

### Measuring the suggester, at last

Every run ends with the median/worst/best distance between the P3 suggestion
and the mark a human settled on, over confirmed rows only — an unconfirmed
row sits exactly on its own suggestion, and averaging those in would report
the suggester as pixel-perfect. When there is nothing to measure it says so
rather than printing a flattering zero. **There is still no real data in it**;
the machinery is now in place for the first few hundred real corrections to
answer the question P3 left open.

### Verified

- 40 new tests in `tests/test_photo_dataset.py`; the P1–P3 suites (117 total
  with P4a) pass, twice, with no new failures. `test_customer_request_
  replacement::test_shop_is_notified` fails identically on P3's tip — not
  this work.
- Driven end to end in the running app over HTTP: logged in, loaded
  `/tech/replacement/1/`, confirmed the control and modal render with the
  replacement endpoints, POSTed a re-tap (crop written as
  `replacement1_customer_submitted_photo…jpg`), and called the suggest
  endpoint (`found: false` — `PHOTO_SUGGEST_ENABLED` is off, as P3 shipped it).
- `export_photo_dataset` run through argparse against a seeded database, and
  `--from-originals` diffed byte-for-byte against the stored crops.

### For P4b

The corpus is now *capable* of holding both classes. It does not yet hold
them, and no amount of code changes that. The next honest step is Drake's
own plan from P3: keep marking breaks during normal work, and re-run
`export_photo_dataset --stats-only` every so often. When the minority class
clears a few hundred rows, P4b has something to train on.

# P6 · Show the close-up — TODO · **DO THIS NEXT**

| Field | Value |
|---|---|
| **Goal** | The break a technician marked becomes visible to the customer on the surfaces that already show photos, and the three bugs on that path get fixed. A tap starts paying for itself the day it happens. |
| **Size** | M |
| **Depends on** | P1–P4a (all the data exists already). **PR #219 must be on `main` first** — see the merge-race trap. Nothing else. No new model, no migration expected. |
| **Why it matters** | This is the missing half of the arc's purpose (see the revised statement at the top). Four sessions built capture with no payoff for the person capturing, and production says 1 of 77 photos has ever been marked. Every later session in this document — the backfill, P5, and ultimately the classifier — is rate-limited by whether techs mark breaks, and they will not until doing so does something. **Treat the capture rate as the acceptance metric, not the pixels.** |
| **Verified current state (2026-08-26)** | `rs_systems/views.py:657-678` builds the `photos` list for the public invoice page; `templates/billing/public_invoice_view.html:180-189` renders it, with the tile CSS at `:51`. Only these two files matter for the main change. The crop itself is `crop.cropped_image`; the point is `crop.center_x_pct` / `center_y_pct`; read the job with `crop.service` / `crop.service_kind`, never the raw FKs. |
| **The three bugs to fix here** | **(1)** The tile is `height: 120px; object-fit: cover` — a blind centre-crop, i.e. P3's "guess the centre" baseline, ~21% off the real break. **(2)** `:659` does `exclude(repair_id__isnull=True)`, so replacement line items contribute **no photos at all** — the expensive invoices, where a close-up matters most, have none. **(3)** `:672` passes raw `repair.unit_number` into a `Unit {{ photo.unit }}` caption (`:189`); an individual's is blank, so the caption reads "Unit  — Before". That is the documented CLAUDE.md individual-vs-fleet trap — route it through `get_vehicle_identifier()` / `vehicle_column_label`. |
| **DECISION NEEDED FROM DRAKE (ask before building)** | Two ways to show the mark, and it was left open deliberately: **(a)** render the stored `cropped_image` as the tile — a true close-up, tightest on the damage; **(b)** keep the full original and *position* it on the marked point (`object-position: <x>% <y>%`), so the customer still sees their whole windshield with the damage centred, and the click-through is unchanged. **(b) is the safer default** — it changes no asset, degrades gracefully to today's behaviour when no crop exists, and cannot surprise anyone with a 300px square. Recommend (b) unless he wants the harder close-up. |
| **Do not zoom the after photo** | A resin repair leaves a visible blemish; magnifying it shows the customer the scar rather than the fix. Before and customer-submitted → close-up. After → full frame. See the trap. |
| **Consider, don't assume** | The customer portal detail pages (`customer_portal/repair_detail.html`, `replacement_detail.html`, `batch_detail.html`) show the same originals and could get the same treatment — but the invoice is where the money and the dispute are, so do that first and see whether it is worth spreading. The invoice **PDF** is a separate renderer; check before promising it. |
| **Acceptance criteria** | An invoice for a job with a marked break shows the damage centred, not the middle of the frame. A replacement invoice shows its photos. No caption reads "Unit " with nothing after it. A job with **no** crop renders exactly as it does today (this must degrade to current behaviour, not to a broken tile). Nothing writes to an original. |
| **Out of scope** | Backfilling the 77 (P4a.1 — but note P6 is what makes that worth doing). Recording declined work (P5). Any model. |
| **Watch for** | The invoice page is public and tokened — it is served to people who are not logged in, so anything added there must not leak another tenant's media or require auth. Crops live under `media/repair_photos/crops/` with unsigned public URLs in prod, same as the originals already on that page, so this changes no exposure — but verify rather than assume. |

**Notes**

# P3.1 · Validate the suggester against real photos — TODO (newly unblocked)

| Field | Value |
|---|---|
| **Goal** | Answer the question P3 could not: is the saliency suggester any good on photographs of actual windshields? |
| **Size** | S |
| **Depends on** | P3. **Unblocked 2026-08-26** — production holds 77 completed repairs carrying a real damage photo. Until now the only evidence was synthetic fixtures the author also designed. |
| **Why it matters** | P3 ships `PHOTO_SUGGEST_ENABLED=false` on the strength of one synthetic benchmark where the detector lost to "guess the centre of the photo" on cluttered glass. That is either a correct kill or an unfair one, and nobody knows which. A suggester that works raises the capture rate everything downstream feeds on; one that doesn't should be deleted, not left dark. |
| **How** | Pull the 77 originals (they are on S3 under `media/repair_photos/`; do NOT mutate them). Run `suggest_point` over each. There are no ground-truth marks yet — so either run this *after* P4a.1 and measure against the human taps it produces, or have a human tap first and treat P3.1 as the scoring pass. **Keep "guess the centre" in the table as the baseline; that is the lesson P3 paid for.** |
| **Acceptance criteria** | A table of median/worst error for detector vs centre-guess over real photos, plus the decline rate (how often it correctly returns None). A recommendation to tune `MAX_SPREAD`, keep the kill switch off, or remove the suggester. |
| **Out of scope** | Building a better detector. This session measures; a rebuild is its own session and probably wants P4b's data anyway. |
| **Note** | `test_clutter_defeats_the_suggester` is designed to fail once the suggester is fixed. If this session improves it, that test is the one to update — deliberately, with the new numbers in the message. |

**Notes**

# P4a.1 · Backfill the 77 — DONE (2026-08-26)

| Field | Value |
|---|---|
| **Goal** | Every completed repair that already carries a photo gets its break marked. 77 photos, 1 marked. |
| **Size** | S |
| **Depends on** | P2's detail-page endpoint, which already does this one photo at a time. |
| **Why it matters** | 77 labeled positives are sitting in production requiring no new field work, no waiting and no business change. It is the largest single increment available to this arc and the only one not gated on something outside the code. **Do P6 first** — after it, marking one of these 77 visibly improves a real customer's invoice, and the backfill is an afternoon with a product result. Before it, the backfill is charity for a model that does not exist. |
| **What shipped** | `/tech/photos/mark/` — one page, the whole worklist, tap and advance. Read the Notes below before touching it; the queue's membership rules are decisions, not implementation. |
| **Considerations** | P2 deliberately left "a bulk backfill UI for hundreds of old photos" out of scope, *"do it only if the shop actually wants to label history."* The census makes the case that it does. Think about what the cheapest possible burn-down looks like: probably one page, one photo at a time, tap and auto-advance — not a new modal, not a queue model. The existing `save_photo_crop` endpoint is the whole backend. |
| **Order it by value** | An unmarked photo on a completed repair is worth more than one on a cancelled job; a `damage_photo_before` is worth more than a `damage_photo_after` (which labels `not_applicable` anyway — do not spend human taps on after-photos). |
| **Acceptance criteria** | A human can mark the whole backlog in one sitting without navigating job by job. `export_photo_dataset --stats-only` reports the new count. Originals untouched — assert it. |
| **Out of scope** | Turning the suggester on (that is P3.1's call). Running the backfill against production — the tool is the deliverable; the sitting is Drake's. |
| **Revised in flight** | The original row here read *"out of scope: marking anything the machine suggested"*, meaning **do not let the machine mark things for you**. It does not mean a machine-guessed row should be hidden from a human — the opposite: an unconfirmed row is precisely what still needs a person, so the queue includes it, sorts it last, and opens on the guess. Confirming one is how the suggester finally gets scored. |

**Notes**
*(session run 2026-08-26, branch `feat/photoml-p4a1-backfill-queue`, 37 new tests)*

### What shipped

`/tech/photos/mark/` (`views/photo_backfill.py`, template
`technician_portal/photo_backfill.html`, driver `static/js/photo_backfill.js`).
The whole worklist is handed to the page as JSON at load, one photo fills the
screen, a tap places a marker and **Save close-up / Enter** posts it and
advances. Skip is `S`, `→`, or the button. Progress reads "*n* of *N*" with a
bar, and the end card says how many were marked and how many skipped.

Everything it writes goes through P2's `save_photo_crop` — **no new endpoint,
no new model, no new migration, and no stored queue state.** The view itself
is read-only.

### The three decisions worth keeping

1. **The worklist is a question, not a record.** It is recomputed on every
   load from "which photos have no human-confirmed crop", so a marked photo
   simply stops appearing. That is what makes the page safe to reload, to
   run from two devices, to abandon halfway, and to hand to a second person.
   A `BacklogItem` is a throwaway object; nothing is cached anywhere.
2. **Two taps per photo, not one.** The obvious burn-down is tap-to-save-and-
   advance, and it is wrong here: a mis-tap would silently write a wrong mark
   onto a real customer's invoice with no undo on this page. Tap places the
   marker, the confirm commits — and the confirm is where `Enter` lives,
   which is what actually makes a desk session fast (tap, Enter, tap, Enter,
   no mouse travel to a button).
3. **The page is not the shared modal.** `PhotoCropModal` is right for a
   surface that captures one tap; a modal opening and closing seventy-seven
   times would be the worst part of the job. What *is* shared is the one
   thing that must never drift — the tap-to-percent conversion, now
   `PhotoCropModal.percentFromEvent(img, event)`, used by the modal's own
   `placeMarker` and by this driver.

### What is in the queue, and why

`services/photo_backlog.py` owns membership. Three rules, all of them
product decisions rather than filters:

- **After-photos are never offered.** They label `not_applicable`, and P6
  will not zoom them for a customer either (magnifying a resin repair's
  blemish shows the scar, not the fix). A tap there is worth nothing at
  *both* ends, which is a stronger reason than either one alone.
- **"Marked" means marked by a human** — `confirmed_by_human=True`, not
  merely "a crop row exists". A row the P3 sweep guessed at is excluded from
  the dataset export by design, so it still needs a person. It stays in the
  queue, sorted last, and **opens with the guess pre-placed**; confirming or
  nudging it posts the guess back alongside the final mark. That is the pair
  P3.1 needs and it now accrues as a side effect of the backfill.
- **Completed jobs first.** Their label exists today (`repairable` /
  `not_repairable`); an open job's photo is `unknown` until somebody finishes
  the work. Tempered-glass replacements sort last — still worth a mark for
  the customer's invoice, worth nothing to the dataset.

Both repairs *and* replacements are in it. Leaving replacements out would
have quietly rebuilt the exact sampling fault P4a existed to fix.

### Two things deliberately not copied

- **The label rules.** `photo_dataset.label_for(crop)` now delegates to a new
  `label_for_photo(job, source_field)`, which is the same rule set reached
  one step earlier — these photos have no crop row yet. A second copy would
  have drifted, and `label_source` is only worth anything if a training run
  can trust which rule fired.
- **The permission check.** The queue filters with `can_view_repair` and
  `_replacement_technician_access` — the crop endpoint's own gates — so it
  can never offer a technician a job the save will refuse.
  `test_everything_the_queue_offers_the_endpoint_accepts` states the
  invariant directly: walk the whole queue, mark every entry, none may be
  refused. **A queue that hands someone a 403 for doing what it asked is
  worse than no queue.**

### The entry point is one link, and it hides itself

The job list's summary line gains "*n* photos to mark" when there is a
backlog and nothing when there isn't. The nav has no room (it is documented
as not fitting seven owner links already), and the arc's real problem was
never that marking was hard — it was that **nobody knew the backlog existed**.
The count runs the same permission-filtered query the queue does, capped at
`QUEUE_LIMIT` (200), with the joins the page needs dropped (`detail=False`):
a number that promises more than the page delivers is worse than no number.

The query is bounded at the database, not in Python — completed-first, newest
-first, sliced to the limit — so a shop with thousands of unmarked photos
loads a page, not a history. On a backlog longer than the limit the tiering
therefore sorts the newest 200 rather than everything, and the page says so.

### Verified

- **In a browser, end to end**, against seeded portrait (900×1200) and
  landscape (1200×900) photos with a chip drawn at a known point. Three taps
  landed at (50.1, 39.9), (35.0, 55.1) and (61.7, 17.0) against seeded chips
  at (50, 40), (35, 55) and (62, 17) — **within 0.3 percentage points on both
  orientations.** The crops wrote, `Skip` skipped, the marked ones dropped out
  of the queue on reload, the end card read "2 breaks marked, 1 skipped", and
  the empty state and the vanishing job-list link both behaved.
- `export_photo_dataset --stats-only` afterwards saw all three with the right
  labels and rules (`repair_completed` ×2, `replacement_completed_windshield`
  ×1) — the loop from queue to dataset closes.
- 37 new tests in `tests/test_photo_backfill_queue.py`; the P1–P4a suites
  (117) and `test_unified_job_list` stay green. 184 tests in the combined run,
  zero failures.

### Traps hit this session

- **The multi-line `{# … #}` comment**, which CLAUDE.md documents and which I
  wrote anyway. It rendered as a paragraph of prose across the top of the tap
  surface. Use `{% comment %}`.
- **`Repair.vehicle_description` is a read-only property** derived from
  `vehicle_year`/`make`/`model`, and `vehicle_year` is an **IntegerField** —
  `vehicle_description='Silver Camry'` raises `AttributeError`, and
  `vehicle_year=''` raises `ValueError`.
- **The first layout put the buttons below the fold.** For a burn-down that is
  fatal — confirming must never mean scrolling. The photo box is now a fixed
  `52vh` with the image `max-height: 100%` inside it, so a landscape photo
  letterboxes rather than losing its top and bottom (which on this page would
  hide the very break being marked).

### For P3.1

The backfill is what makes P3.1 possible, and the two compose: turn the
suggester on, sweep the backlog with `suggest_photo_crops`, then run the queue
— every photo opens on the machine's guess and every confirm records the
correction distance. `export_photo_dataset` already prints the median. That is
the honest measurement P3 could not make and it now costs one sitting.

# P5 · Record the jobs we turn away — TODO · **the gate on P4b**

| Field | Value |
|---|---|
| **Goal** | When a technician looks at damage and decides it cannot be repaired, the app can record that — with the photo — in about fifteen seconds, on site. |
| **Size** | M |
| **Depends on** | P1–P4a (the crop plumbing already exists and already accepts a job that is not a repair). |
| **Why it matters** | **This is the only negative-class source that this business actually generates.** The census found zero replacements, ever. But a repair shop turns away unrepairable damage constantly — that is a normal week — and the moment it happens is the moment an expert has looked at real damage and rendered exactly the verdict the classifier is meant to learn. Today that verdict is spoken aloud and never written down. Every one is a training example destroyed at the point of creation. |
| **The insight, stated plainly** | The arc assumed the negative class would arrive as completed windshield *replacements*. That assumed the shop does replacements. It does not. The negative class it really produces is **declined work**, and nothing in the product can express it. |
| **Considerations** | Do not model this as a `Replacement` — the shop did not replace anything and inventing a phantom replacement row would poison invoicing, counts and revenue. It is closer to a *declined assessment*: photo, reason, timestamp, vehicle, and nothing financial. Check first whether an existing shape fits (a `Repair` with a terminal declined status? a lightweight new model?) before adding one. `services/photo_dataset.py` is the single place a new label rule goes, and its `label_source` convention means a training run can drop the rule if it turns out to be noisy. |
| **The reason field is the real prize** | "Crack too long", "in the driver's sight line", "already spidered", "edge crack", "prior bad repair" — those are the classes a genuinely useful model would predict, and a tech will pick from a five-item list where they would never type a sentence. Get the list from Drake; do not invent it. |
| **Considerations, product side** | This has value beyond ML and should be pitched on that: a shop that records what it turned away can see how much work it is walking away from, and can hand the customer something (a referral, a quote for replacement) instead of nothing. That is what makes it worth a tech's fifteen seconds — an ML dataset never is. |
| **Acceptance criteria** | A declined assessment can be recorded from the field in one screen; it carries a photo; that photo can be tapped like any other; `photo_dataset.py` labels it `not_repairable` with its own `label_source`; `export_photo_dataset` shows two classes for the first time. |
| **Out of scope** | Quoting the replacement. Referral routing. Anything that makes the flow longer than the walk back to the van. |
| **Decisions needed from Drake** | The reason list. Whether this is worth building for its own sake (it should be pitched that way). Whether The Glass Guy is going to be recording replacement jobs, which would open the second source. |

**Notes**

# §The pause · what we are waiting for, and why waiting alone won't end it

*(census taken 2026-08-26 against production, read-only, both tenants,
soft-deleted rows included)*

**The short answer to "how much longer until we pause and collect data": we are
already there.** P4a was the last thing worth building without data, and
everything after it needs rows that do not exist. But the shape of the wait is
not what the arc assumed.

### What is actually banked

| | count | rate |
|---|---|---|
| Positive class — completed repairs with a photo | **77** banked | ~9/month |
| ...of those actually marked with a crop | **1** | — |
| Negative class — windshield replacements with a photo | **0** | **0/month** |

The positive side is healthy: 77 examples are sitting in production right now,
already photographed, needing only a human to tap where the break is. That is
an afternoon of work, not a wait — see **P4a.1**.

The negative side is not thin. It is **empty, and structurally so**. There has
never been a `Replacement` row in this database. Tenant 1 (Rockstar Windshield
Repair) is a repair shop and does not do replacements; tenant 15 (The Glass
Guy) does, and has no jobs in the app at all.

### Why "collect data for a few months" is the wrong plan

P4a's Notes end by recommending exactly that: keep marking breaks during
normal work and re-run `--stats-only` every so often. That advice is right for
the positive class and **useless for the negative one**, because normal work
at this shop produces zero replacements and always has. Three months of
patience multiplies zero by three.

The mistake is the same species as the one P4a itself caught, one level up.
P4a found that the *schema* could only express one class. The census finds
that the *business* only generates one class. Fixing the schema was necessary
and did not move the count.

### The three ways out, in order of cost

1. **Record the jobs we turn away (P5).** Every repair shop looks at damage it
   cannot repair — a crack past the length limit, damage in the driver's sight
   line, a chip that has already spidered — and says so out loud, on site,
   with the customer's windshield in front of them. That judgement is the
   single most valuable label in this entire arc, and today the app has no
   way to write it down. The tech says "that's a replacement, I can't help
   you," and walks away, and nothing is recorded. **This is the cheapest
   negative-class source that exists and it is already happening every week.**
2. **Get The Glass Guy onto the app for replacement work.** A business
   question, not an engineering one, and the reason P4a bothered to make
   replacement crops possible at all. Worth asking Drake where that stands.
3. **Import an outside corpus.** Note the asymmetry with P3's standing
   decision: Drake rejected sending *our customers' photos out*. Bringing
   someone else's photos *in* is a different question and has not been asked.
   Do not assume the answer either way.

### What to do during the pause

- **P6 first.** Nothing else in this list is worth much while a tap pays the
  technician back with nothing — the capture rate is 1 of 77 and that is the
  binding constraint on every remaining session, this one included.
- ~~**P4a.1**~~ — **built (2026-08-26)**: `/tech/photos/mark/` turns the 77
  into one sitting. **The tool exists; the 77 are still unmarked.** This
  session built the burn-down, it did not run it against production — that is
  an afternoon of Drake's, and it is the highest value per minute left in the
  arc. It is pure positive class, which is only half useful until P5 exists —
  do it anyway; it is perishable in the sense that nobody remembers where the
  break was on a 2025 windshield.
- **P3.1** — the suggester has never once been run on a real windshield photo,
  which P3 flagged as the first thing to fix. **There are now 77 of them.**
  This is the cheapest honest test in the arc, and P4a.1 composes with it:
  sweep the backlog with the suggester on, then run the queue — every photo
  opens on the machine's guess, every confirm records a correction distance,
  and `export_photo_dataset` already prints the median.
- **P5** — the real gate.
- Re-run `export_photo_dataset --stats-only` after each, and believe the
  balance line over any narrative, this one included.

# P4b · Payoff: the repairability classifier — BLOCKED on P5

| Field | Value |
|---|---|
| **Goal** | Train and evaluate a repairable-vs-not classifier on the exported bundle. |
| **Size** | L |
| **Depends on** | P4a's export, and **P5** — not merely "data", and not merely time. The minority class stands at **0** and accrues at **0/month**; see §The pause. `export_photo_dataset --stats-only` is the check; it prints the balance and refuses to flatter it. |
| **Why it matters** | The whole point of the arc. |
| **Verified current state** | The export exists, is anonymised, tenant-scoped and reproducible from metadata. Labels come from `services/photo_dataset.py`. Label strength is recorded (`confirmed_by_human`) and unconfirmed suggestions are excluded by default. |
| **Considerations** | Class imbalance is the live risk, not model choice: techs photograph what they already know is repairable, and windshield replacements are rarer than repairs. Read the balance before writing a line of training code. Rows carrying both a `suggested_*` point and a human-confirmed mark are the training pairs for a *learned* detector, and their correction distances are also the honest answer to whether P3's saliency suggester is worth keeping at all. Train outside this codebase; the app's job is the export and, later, serving a verdict. |
| **Decisions needed** | Where training runs (local vs cloud). Whether the classifier ships in-app (an advisory badge on customer requests?) or stays an experiment. Both are Drake's calls and neither is urgent while the data is thin. |
| **Acceptance criteria** | A held-out evaluation with honest per-class numbers before anything ships. |
| **Out of scope** | Auto-quoting or auto-declining work. It advises; humans decide. |

**Notes**

## Document history

| Date | Change |
|---|---|
| 2026-08-25 | Created with P1 executed in the same session; P2–P4 sketched from verified code state. |
| 2026-08-25 | P2 executed: detail-page crop/re-crop endpoint + UI, multi-break per-break taps, `retry_photo_crops`, shared `PhotoCropModal`. Customer-portal tapping decided against. |
| 2026-08-25 | P3 executed: local saliency suggester, suggest endpoint, pre-placed marker, `suggest_photo_crops` sweep, provenance columns. **Hosted vision model rejected — photos stay on our infrastructure.** |
| 2026-08-26 | P4a executed: crops hang off replacements too (the negative class was structurally uncollectable), `export_photo_dataset`, label rules in `services/photo_dataset.py`. P4 split into P4a (done) and P4b (blocked on data, correctly). |
| 2026-08-26 | **Census + pause.** Discovered P4a never reached `main` (stacked-merge race, #218 merged into an already-consumed branch; re-landed as #219). Production census: 77 banked positives, **0 replacements ever**. P4b re-gated from "blocked on data" to **blocked on P5**. Added P3.1 (suggester now testable on real photos), P4a.1 (backfill the 77), P5 (record declined work — the only negative-class source this business generates). |
| 2026-08-26 | **Reframed by Drake.** Asked what a shop gets from cropping: nothing, today. The arc was built training-first and the capture rate proves the cost — **1 of 77**. Purpose statement rewritten around the customer-visible close-up as the *first* purpose and the training set as the second, with the note that percent coordinates serve both from one tap. **P6 added and sequenced next**, carrying three live bugs on the invoice photo path (blind centre-crop, replacements excluded, `Unit ` caption for individuals). Preservation audited and sound; collection is not. |
| 2026-08-26 | **P4a.1 executed.** `/tech/photos/mark/` — the whole unmarked-photo backlog in one queue, tap the break and advance, entered from a link in the job list that hides itself when there is nothing waiting. No new endpoint, model or migration: it drives P2's `save_photo_crop`, and the worklist is recomputed on every load so a marked photo simply leaves it. Label rules and permission checks are shared with the export and the endpoint rather than copied (`label_for_photo`, `can_view_repair` / `_replacement_technician_access`), and the tap-to-percent conversion moved onto `PhotoCropModal.percentFromEvent` so the two tap surfaces cannot drift. **The tool exists; the 77 are still unmarked** — running it against production is the next thing that moves the number. |
