# Photo ML Sessions — tap-to-crop toward a repairability classifier

**Created:** 2026-08-25
**Author:** Claude (planning session with Drake)
**Status:** living document — update statuses and Notes as sessions complete
**Companions:** none required; this arc is self-contained. The wider product queues live in `IMPROVEMENT_SESSIONS.md` and `FIELD_OPS_SESSIONS.md`.

**What this arc is for (the durable purpose statement):** every damage photo a
technician taps gets a close-up crop of the break saved next to the untouched
original, labeled before/after by which field it came from. Those crops, joined
to the repair's eventual outcome, are the training set for a future
**"repairable vs not" classifier** — Drake's explicit long-term goal. Nothing in
P1–P2 does any ML; they exist to make the dataset accumulate as a side effect of
normal field work, with enough metadata (percent coordinates on EXIF-upright
originals) that the dataset can be regenerated at any time. Do not delete or
"clean up" `RepairPhotoCrop` rows or `repair_photos/crops/` files thinking they
are derived caches — they are the product of human labeling work.

Each session is self-contained — a fresh Claude session with no memory should be
able to execute exactly one session using only §0 and that session's table,
without re-running the exploration that produced this doc.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED`

| Phase | Session | Size | Status |
|---|---|---|---|
| P1 · Capture | Tap-to-crop on upload (job form + old repair form) | M | DONE (2026-08-25, branch `feat/photoml-p1-tap-to-crop`) |
| P2 · Coverage | Detail-page crop/re-crop + retry queue + multi-break & customer-portal wiring | M | DONE (2026-08-25, branch `feat/photoml-p2-crop-coverage`) |
| P3 · Assist | Auto-suggest crops (local saliency detector; no photo leaves the server) | M | DONE (2026-08-25, branch `feat/photoml-p3-auto-suggest`) |
| P4 · Payoff | Dataset export + repairability classifier | L | TODO |

**Suggested sequence:** P1 → P2 → P3 → P4. P2 first because coverage compounds
(every uncovered surface is training data lost forever — you can't retro-tap a
photo whose break location nobody remembers). P4's *export step only* can be
built any time after a few hundred crops exist and is a good way to smoke-test
the metadata before committing to a model. P3 before the P4 classifier because
auto-suggest raises the capture rate that P4 feeds on.

**Where we are (2026-08-25, after P3):** P1 merged as PR #211, P2 as PR #215.
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

Next up is P4 — and its export step alone is worth building now, because the
suggester's real accuracy is sitting in the `suggested_*` columns waiting to
be measured.

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
(related_name `photo_crops`), `tenant` FK + `TenantManager` (not auto-filtering
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

**The crop service.** `apps/technician_portal/services/photo_crops.py`:
`process_tap_coordinates(repair, post_data, technician=None, key_prefix='',
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

**The photo fields.** On the abstract `GlassService` base
(`apps/technician_portal/models.py:517-544`), so `Repair` AND `Replacement`
both have them; P1 crops repairs only.

**Upload surfaces map** (who converts HEIC, who compresses, who has tap-to-crop):

| Surface | View | HEIC→JPEG | Client compress | Tap-to-crop |
|---|---|---|---|---|
| Unified job form `/tech/jobs/new/` | `views/jobs.py::job_create` | yes (P1) | `image_compress.js` auto-wire | **P1** |
| Old repair form create/update | `views/repairs.py` | yes | `repair_form.js` (manual) | **P1** |
| Multi-break | `views/batch.py` | yes | `multi_break.js` | **P2** (one tap per break, posted as `breaks[i][crop_x_<field>]`) |
| Customer portal request | `customer_portal/views.py` (~:1800) | yes | none | never — by decision, customers are not asked to tap; the shop marks their photo from the detail page |
| Repair detail page | `views/repairs.py::save_photo_crop` | n/a | n/a | **P2** (crop or re-crop any photo already on the job) + **P3** (an unmarked photo opens on a suggested marker, via `suggest_photo_crop`) |
| Backlog sweep | `manage.py suggest_photo_crops` | n/a | n/a | **P3** (marks unmarked photos `confirmed_by_human=False`; never overwrites a tap, never touches an original) |

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
`tests/test_photo_suggest.py` (39, P3). `real_jpeg()` there
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
| **Acceptance criteria** | ✅ Suggestion appears in under ~3s or not at all (client abandons at 3s; the local pass measures ~25–50ms). ✅ Tech can always override — a tap wins over a suggestion, always. ✅ Suggested-but-unconfirmed is distinguishable in the data (`confirmed_by_human`) and in the UI ("Check the mark" / "We guessed this one"). |
| **Out of scope** | The repairability classifier itself (P4). A hosted vision model (rejected). Suggesting inside the upload modal (the photo isn't on the server yet). |

**Notes**
*(session run 2026-08-25, branch `feat/photoml-p3-auto-suggest`)*

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

# P4 · Payoff: dataset export + repairability classifier — TODO

| Field | Value |
|---|---|
| **Goal** | A `manage.py export_photo_dataset` command producing an images+JSONL (or COCO) bundle: crop file, coords, dims, source_field (before/after label), and the outcome label joined through the repair. Then train and evaluate a repairable-vs-not classifier on it. |
| **Size** | L (export is S on its own — build it early to smoke-test the metadata) |
| **Depends on** | Enough data: realistically high hundreds+ of before-crops with outcomes, and a meaningful "not repairable" class. |
| **Why it matters** | The whole point of the arc. |
| **Verified current state** | Label sources in the schema today: `Repair.queue_status` COMPLETED = repaired successfully; a `Replacement` created after a repair request / a customer request that got quoted as a replacement = not repairable; warranty/redo signals (`WarrantyPolicy` usage) = weak negative. `customer_submitted_photo` on portal requests is the best source of the "not repairable" class — people photograph big cracks when asking, and the shop's answer (repair vs replacement) is the label. |
| **Considerations** | **Label strength is now recorded, so use it** (P3): export `confirmed_by_human=True` rows as strong labels and either exclude or down-weight the machine suggestions — training on the suggester's own unreviewed output just teaches the next model to imitate this one. Rows carrying *both* a `suggested_*` point and a human-confirmed mark are the training pairs for a learned detector, and the distance between the two is the first honest measurement of whether P3's suggester is worth keeping (see P3's Notes on `MAX_SPREAD`). Class imbalance is the other real risk: techs mostly photograph what they already know is repairable. Track the class counts from the first export. Export must be tenant-aware (Drake's dad's shop is real customer data — anonymize: no names/plates in the JSONL, crops only). Train outside this codebase; the app's only job is the export and, later, serving the verdict. |
| **Decisions needed** | Where training runs (local vs cloud); whether the classifier ships in-app (advisory badge on customer requests?) or stays an experiment. |
| **Acceptance criteria** | Export regenerates byte-identical crops from originals using only DB metadata; a held-out evaluation with honest per-class numbers before anything ships. |
| **Out of scope** | Auto-quoting or auto-declining work based on the model. It advises; humans decide. |

**Notes**

## Document history

| Date | Change |
|---|---|
| 2026-08-25 | Created with P1 executed in the same session; P2–P4 sketched from verified code state. |
| 2026-08-25 | P2 executed: detail-page crop/re-crop endpoint + UI, multi-break per-break taps, `retry_photo_crops`, shared `PhotoCropModal`. Customer-portal tapping decided against. |
| 2026-08-25 | P3 executed: local saliency suggester, suggest endpoint, pre-placed marker, `suggest_photo_crops` sweep, provenance columns. **Hosted vision model rejected — photos stay on our infrastructure.** |
