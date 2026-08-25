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
| P2 · Coverage | Detail-page crop/re-crop + retry queue + multi-break & customer-portal wiring | M | TODO |
| P3 · Assist | Auto-suggest crops (Claude vision first; trained detector when data suffices) | M | TODO |
| P4 · Payoff | Dataset export + repairability classifier | L | TODO |

**Suggested sequence:** P1 → P2 → P3 → P4. P2 first because coverage compounds
(every uncovered surface is training data lost forever — you can't retro-tap a
photo whose break location nobody remembers). P4's *export step only* can be
built any time after a few hundred crops exist and is a good way to smoke-test
the metadata before committing to a model. P3 before the P4 classifier because
auto-suggest raises the capture rate that P4 feeds on.

**Where we are (2026-08-25, after P1):** P1 built and tested on branch
`feat/photoml-p1-tap-to-crop` (13 new tests green; the 5 failures in adjacent
modules reproduce exactly on `main`). Not yet merged/deployed at the time of
writing — check the PR list.

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

**The coordinate convention (do not break this).** Coordinates are percent of
the photo's natural, **EXIF-upright** dimensions. Browsers render photos
EXIF-upright (`image-orientation: from-image` is the CSS default), so a tap on
the rendered image is in upright space; the server MUST
`ImageOps.exif_transpose()` before measuring or cropping
(`apps/technician_portal/services/photo_crops.py::save_crop_for`). Percent (not
pixels) is what makes the crop regenerable from the original no matter how the
photo was displayed.

**The crop service.** `apps/technician_portal/services/photo_crops.py`:
`process_tap_coordinates(repair, post_data, technician=None)` reads
`crop_x_<field>`/`crop_y_<field>` POST pairs and only touches Pillow when a
pair is present — that is what keeps the wider test suite (which uploads
`b"fake image content"` photos) green. `save_crop_for()` does the actual crop:
square box, side = `CROP_FRACTION` (0.35) of the shorter dimension with a
`MIN_CROP_PX` (300) floor, clamped by *shifting* into bounds, JPEG q90.
Everything fails open — a crop must never block saving a job in the field.
`delete_crops_for(repair, source_field)` removes crop + file when a source
photo is deleted.

**The photo fields.** On the abstract `GlassService` base
(`apps/technician_portal/models.py:517-544`), so `Repair` AND `Replacement`
both have them; P1 crops repairs only.

**Upload surfaces map** (who converts HEIC, who compresses, who has tap-to-crop):

| Surface | View | HEIC→JPEG | Client compress | Tap-to-crop |
|---|---|---|---|---|
| Unified job form `/tech/jobs/new/` | `views/jobs.py::job_create` | yes (P1) | `image_compress.js` auto-wire | **P1** |
| Old repair form create/update | `views/repairs.py` | yes | `repair_form.js` (manual) | **P1** |
| Multi-break | `views/batch.py` | yes | `multi_break.js` | P2 (Files live in a JS array, posted as bespoke FormData — needs per-break coord plumbing) |
| Customer portal request | `customer_portal/views.py` (~:1800) | yes | none | P2 |

**The client JS contract.** `input[data-tap-crop="<field>"]` marks a
crop-eligible file input. After compression finishes, `image_compress.js` and
`repair_form.js` dispatch a bubbling `photocrop:offer` CustomEvent
(`detail: {file}`) on the input; `static/js/photo_tap_crop.js` (ES5 IIFE, house
style, loaded after the compressor) listens on `document`, opens
`#photoCropModal` (partial:
`templates/technician_portal/partials/photo_crop_modal.html`, standard `ui.js`
modal contract), and on Confirm writes the hidden inputs
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

**Tests.** `tests/test_photo_tap_crop.py` (13 tests). `real_jpeg()` there
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

# P2 · Coverage: detail-page crop/re-crop, retry queue, remaining surfaces — TODO

| Field | Value |
|---|---|
| **Goal** | A break can be tapped (or re-tapped) after upload from the repair detail page; the multi-break form and the customer-portal request flow capture taps too; crops that failed (null box) get retried. |
| **Size** | M |
| **Depends on** | P1. |
| **Why it matters** | P1 only captures at upload time on two of four surfaces. Multi-break is the power-user path (several breaks per windshield = several labeled examples per job), and old photos + skipped taps are recoverable labeling work. |
| **Verified current state** | See §0 upload-surfaces map. Detail page: `templates/technician_portal/repair_detail.html` photo section ~:564-666 with `openImageModal()` lightbox ~:794 — natural home for a "Mark the break" action. Multi-break: per-break File objects in `multi_break.js` `breaks[]`, posted as `breaks[i][photo_before]` FormData (`views/batch.py` ~:397-463); per-break coords need matching `breaks[i][crop_x_before]` keys. Customer portal: `customer_portal/views.py` ~:1800 writes `customer_submitted_photo` directly. |
| **Considerations** | Detail-page tap needs a small POST endpoint (tenant-scoped, technician-gated) calling `save_crop_for` — the P1 hidden-input transport doesn't apply there. Retry = iterate rows with `cropped_image=''`/null dims and call `save_crop_for` with the stored coords. Customer-portal UX must stay optional and dead simple — customers are not techs. |
| **Decisions needed** | Whether customers are asked to tap at all, or only techs (recommend: techs only at first; customer photos get cropped by the shop from the detail page). |
| **Acceptance criteria** | Every crop-eligible photo on the detail page can be tapped/re-tapped; multi-break taps produce one crop per break's photo; a failed crop retries successfully once the image is readable. |
| **Out of scope** | Auto-suggest (P3). Bulk backfill UI for hundreds of old photos — do it only if the shop actually wants to label history. |

**Notes**

# P3 · Assist: auto-suggest crops — TODO

| Field | Value |
|---|---|
| **Goal** | The modal opens with a suggested marker already placed; the tech confirms or drags. Capture rate goes up because confirming is cheaper than aiming. |
| **Size** | M |
| **Depends on** | P1 (modal + coords plumbing). Better after P2. |
| **Why it matters** | The dataset grows only as fast as techs tap. A one-tap confirm beats an aim-and-tap, and the suggestion engine is a dry run for P4's model. |
| **Verified current state** | No detection anywhere in the codebase. Claude API access exists (Amelia/clawdbot namespace) but no vision calls in this app yet. |
| **Considerations** | Two stages. (a) **Claude vision**: send the compressed photo, ask for the break's bounding point; works day one, costs pennies per photo, needs an API key in EB env and a strict timeout + fail-open (no suggestion = P1 behavior). Client-side call is not an option (no CDN/keys in the browser) — suggest server-side on a small endpoint, or suggest lazily on the P2 detail page rather than blocking the upload modal. (b) **Trained detector**: once ≥ a few hundred confirmed taps exist, a nano detection model on the crops; only worth it if Claude-vision accuracy or cost disappoints. Confirmed-vs-suggested must be recorded (add `suggested` / `confirmed_by_human` fields) — ML-suggested crops that nobody confirmed are weaker labels. |
| **Decisions needed** | Where the suggestion happens (upload modal vs detail page); Claude vs detector first (recommend Claude). |
| **Acceptance criteria** | Suggestion appears in under ~3s or not at all; tech can always override; suggested-but-unconfirmed is distinguishable in the data. |
| **Out of scope** | The repairability classifier itself (P4). |

**Notes**

# P4 · Payoff: dataset export + repairability classifier — TODO

| Field | Value |
|---|---|
| **Goal** | A `manage.py export_photo_dataset` command producing an images+JSONL (or COCO) bundle: crop file, coords, dims, source_field (before/after label), and the outcome label joined through the repair. Then train and evaluate a repairable-vs-not classifier on it. |
| **Size** | L (export is S on its own — build it early to smoke-test the metadata) |
| **Depends on** | Enough data: realistically high hundreds+ of before-crops with outcomes, and a meaningful "not repairable" class. |
| **Why it matters** | The whole point of the arc. |
| **Verified current state** | Label sources in the schema today: `Repair.queue_status` COMPLETED = repaired successfully; a `Replacement` created after a repair request / a customer request that got quoted as a replacement = not repairable; warranty/redo signals (`WarrantyPolicy` usage) = weak negative. `customer_submitted_photo` on portal requests is the best source of the "not repairable" class — people photograph big cracks when asking, and the shop's answer (repair vs replacement) is the label. |
| **Considerations** | Class imbalance is the real risk: techs mostly photograph what they already know is repairable. Track the class counts from the first export. Export must be tenant-aware (Drake's dad's shop is real customer data — anonymize: no names/plates in the JSONL, crops only). Train outside this codebase; the app's only job is the export and, later, serving the verdict. |
| **Decisions needed** | Where training runs (local vs cloud); whether the classifier ships in-app (advisory badge on customer requests?) or stays an experiment. |
| **Acceptance criteria** | Export regenerates byte-identical crops from originals using only DB metadata; a held-out evaluation with honest per-class numbers before anything ships. |
| **Out of scope** | Auto-quoting or auto-declining work based on the model. It advises; humans decide. |

**Notes**

## Document history

| Date | Change |
|---|---|
| 2026-08-25 | Created with P1 executed in the same session; P2–P4 sketched from verified code state. |
