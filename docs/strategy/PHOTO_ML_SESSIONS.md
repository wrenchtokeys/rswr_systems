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
   evidence. **This is the job that pays the technician back for tapping**,
   and it was not built until P6 (2026-08-26): the invoice tile and the
   customer portal now frame the photo on the marked break instead of the
   middle of the frame.
2. **It is training data** for a future **"repairable vs not" classifier** —
   Drake's long-term goal, and the only thing P1–P4a were built for.

**The order matters and was wrong.** Written training-first, the arc gave a
tech nothing in return for a tap: for four sessions the crop appeared on one
internal page and fed a model that does not exist. The result, measured in
production on 2026-08-26, was a marking rate of **1 photo out of 77** (fixed
on 2026-08-27: **73**, once P6 gave the tap a payoff and P4a.1 gave it a
queue). Purpose
1 is what makes purpose 2 accumulate; a capture pipeline whose only payoff is
a future model does not capture. P6 fixed the payoff; **P4a.1 is what will
move the rate.** See §The pause.

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
| P4a · Both classes | Crops on replacements + dataset export + class/accuracy report | M | DONE (2026-08-26, PR #218 → **re-landed as PR #219, merged 2026-08-26**) |
| P6 · Show the close-up | Put the marked point on surfaces customers already see — and fix three bugs there | M | DONE (PR #222, merged 2026-08-27) |
| P4a.1 · Backfill | Mark the break on the photos we already have — one queue, not 77 jobs | S | DONE (PR #224) — **and RUN: 1 → 73 confirmed crops, 2026-08-27** |
| P3.1 · Validate | Run the suggester against the 77 real windshield photos we now have | S | DONE (2026-08-27) — **it wins on real photos; but the (41,61) centroid beats it for free** |
| P6.1 · Free win | Default unmarked photos to (41%, 61%) instead of dead centre | XS | **DONE and ON `main`** — merged 2026-08-31 *inside* #236; #234 closed as superseded. Halves the framing error on every photo nobody marked, forever |
| P6.2 · Proof of work | Before/after pair on the public invoice page — one exhibit, not two tiles | S | **DONE and ON `main`** — PR #236, squash `fb4f8b98`, 2026-08-31. **The census says the pairs are already there: 76 of 82 photographed jobs have both** |
| P5 · Negative class | Record the jobs we turn away — the only source of "not repairable" | M | TODO — **this is the actual gate on P4b** |
| P4b · Payoff | Repairability classifier | L | BLOCKED on **P5** — see P4b and §The pause |

**Suggested sequence, as revised 2026-08-26:**
P1 → P2 → P3 → P4a → P6 → P4a.1 → P3.1 → P6.1 → P6.2 → **P5** → P4b. **Every
code session in the arc is now done, P6.2 included.** What is left is not a
session: **P5 is a decision** (see §The pause), and P4b is blocked behind it.
Note that P3.1's
method was revised on 2026-08-27 by a dry run against production: **mark
cold, score afterwards**, rather than sweeping first. See P3.1 for the
numbers.

**The "natural ending" lasted a few hours (revised 2026-08-27).** P6.1
finished the *framing* half: a marked photo frames on the break, an unmarked
one is aimed where techs actually tap. But asked what proves to a shop that
any of this tapping helps — a tech at another tenant sees "Tap the break" pop
up with no explanation and no visible payoff — Drake chose one more
customer-value session: **P6.2, the before/after pair**, the strongest
proof-of-work artifact this product can render from photos it already has.
Read P5's preamble before opening anything classifier-shaped.

**The backfill is done.** Drake marked the whole backlog on production on
2026-08-27: **73 confirmed crops**, up from 1. That unblocked P3.1, whose
measurement is the most useful thing this arc has produced so far — see P3.1's
Notes, and P6.1, which has since cashed it out.

The original sequence (P1 → P2 → P3 → P4a → P4b) assumed the only thing
standing between here and a classifier was volume. Two findings changed it:
the negative class accrues at **zero** per month (§The pause), and the positive
class accrues barely faster because tapping pays nobody back (1 of 77). **P6
before P4a.1** because backfilling 77 photos is worth an afternoon once each
one visibly improves a real invoice, and is charity before that. **P5 before
P4b** because P5 is the only negative-class source this business generates.

**Where we are (2026-08-27, end of day — the backlog is marked and the
suggester has finally been measured):**

**The rate went from 1 of 77 to 73.** Drake sat down with `/tech/photos/mark/`
and marked the whole backlog on production. That is the number this arc exists
to move, and it moved because a person spent twenty minutes — not because of
anything built after P2.

What the 73 marks immediately bought, in one measurement (P3.1's Notes have
the tables):

- **The suggester actually works on real windshields** — median 7.5% error
  against 18.7% for the centre-guess, winning on 78% of the photos it speaks
  about. P3 killed it on a *synthetic* benchmark, and the benchmark was wrong.
- **But a constant beats it for free.** Technicians tap at **(41, 61)**, not
  the middle — left and low, because a chip is shot from the driver's seat.
  Leave-one-out cross-validated, that constant halves the error against dead
  centre (9.3 vs 17.6) and wins on 90% of photos, with **zero computation.**
  That is **P6.1**, and it is **done** — it now applies to every photo nobody
  marked, past and future.
- **The score means something only above 0.8**, where it fires on 15% of
  photos at 3.2% error. Everything below is noise, and `suggest_photo_crops`
  currently gates on nothing.

**Deploy state still lags merge state — check it before you believe it.**
Production is running `app-d88f7-260827_125012793353`, which is commit
`d88f70d5` on `feat/photoml-p31-score-the-suggester` — **a feature branch,
deployed straight off the branch**, not off `main`:

- Prod **has** P4a.1's queue — which is how the backfill got done at all.
- Prod **does not have P6**, so the 73 marks Drake made are recorded and
  their crops derived, but **not one of them reaches a customer's invoice
  until `main` ships.** That deploy is still the highest-value action in the
  arc.
- Prod is also behind `main` on the S13b icon work and P6.1.

**`main` migrates cleanly now** (#231 restored the `0061` merge node and added
CI), and every migration in the graph is **already applied in production** —
`showmigrations technician_portal` shows `0060`, `0060` and `0061` all `[X]`.
So the deploy that ships P6/P6.1 is code-only; `migrate` will be a no-op.

**The 2026-08-27 19:24 UTC deploy failed, and the cause was not the code.**
It died in `01_migrate` with the same conflicting-leaf-nodes error the whole
saga is about:

```
CommandError: Conflicting migrations detected; multiple leaf nodes in the
migration graph: (0060_add_needs_assignment, 0060_photocrop_replacement_fk
in technician_portal).
```

but `main` was **already fixed** by then. The deploy was run from the
**feature branch**, whose HEAD predates #231. `.elasticbeanstalk/config.yml`
sets `sc: git`, so **`eb deploy` ships the current branch's HEAD commit** —
not `main`, and not the working tree. Deploying from a branch that predates a
fix re-runs the bug.

Nothing was damaged: `migrate` refuses at graph-load time, so no migration
partially applied, and the old version kept serving (`/health/` stayed 200).
The cost was a red environment and an hour.

**So: `git checkout main && git pull` BEFORE `eb deploy`, every time.** Round
four of this saga was not a duplicate migration at all — it was deploying the
wrong commit. The CI added in #231 cannot catch this, because CI checks
branches and this was a deploy-time choice.

**START HERE (state as of 2026-09-01):**

| | |
|---|---|
| ~~#231~~ | **Merged.** Restored the `0061` merge migration and added the repo's first CI workflow (`.github/workflows/migration-graph.yml`). |
| ~~#232~~ | **Merged.** P3.1's results. |
| ~~P6.1~~ | **Merged** (inside #236; #234 closed as superseded) — the measured `41% 61%` default for unmarked photos. See its section. |
| **→ DEPLOY `main`** | **The one thing standing between all of this and a customer, and now the ONLY open item in the arc that is not a decision.** Production has run `d88f70d5` since before P6 and is **23+ commits behind**. Verified 2026-08-31: **zero migration files differ** between that commit and `main`, so the deploy is code-only and `migrate` is a no-op. Nothing in this arc is visible to anyone until this happens. |
| ~~P6.2~~ | **Merged** (#236, squash `fb4f8b98`) — the before/after pair. Like P6 and P6.1 it is in the repository and reaches nobody until `main` deploys. |
| **Then** | **P5 is a decision, not a session** — see §The pause before building toward P4b. **Ask Drake whether the classifier is still wanted**; if it is not, close P5 and P4b as DROPPED and the arc ends here, which would be a good ending. |

**How to deploy this, exactly** — the 19:24 failure was caused by getting
this wrong:

```bash
git checkout main && git pull origin main   # NOT a feature branch: sc: git
python manage.py test tests.test_migration_graph   # ~0.3s, no database
eb deploy rs-systems-production
curl -I https://rssystems.io/health/
```


**What is left, in one line:** **deploy `main`** — every code session in the
arc is now written, merged and green — then P5, which is still the only thing
that unblocks the classifier, and is still gated on the business turning a job
away rather than on any code. See §The pause for the census.

**Verifying a merge in this arc.** Every PR here squashes, so the recipe an
earlier session wrote — `git log origin/main..origin/<branch>` should be
empty — **lies**: squashing rewrites the SHAs and the branch commits stay "not
on main" forever. Verify by content instead
(`git ls-tree -r --name-only origin/main | grep photo_backlog`, or
`git diff --stat origin/main origin/<branch>` over the files you care about).

**Where we were (2026-08-26, after P6):** P4a landed on `main` as squash
commit `c8876d8e` (PR #219, after #218 merged into the wrong base). P6 was
built on `feat/photoml-p6-show-the-closeup`: the break a technician marks
became visible to the customer on the public invoice page and the
customer-portal repair detail, and three bugs on that path were fixed (blind
centre-crop, replacements contributing no photos at all, `Unit  — Before` on
every individual's caption). Verified in a real browser against a portrait
photo, which is where the old behaviour was worst — the unmarked tile showed a
wiper and no break at all. See P6's Notes for what the measurement actually
says about the size of the win; it depends on photo orientation, and that is
worth knowing before promising anything.

**Where we were (2026-08-26, after P4a):** P1 merged as PR #211, P2 as PR #215.
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

A crop **file** is therefore still an internal artifact. What a customer sees
is the original — but since P6, framed on the mark.

| Surface | What it renders today |
|---|---|
| Public invoice page (`rs_systems/views.py::_public_invoice_photos` → `templates/billing/public_invoice_view.html`) | The **original**, cropped to a 120px tile — **framed on the marked break** when there is one (P6), blind centre-crop when there isn't. Repair **and** replacement line items (P6; it was repairs only). Captions via `get_vehicle_label()`. |
| Customer portal repair detail | The original in a 4:3 `object-cover` box, **framed on the mark** (P6). |
| Customer portal replacement / batch detail | The original, full frame — the box takes the image's aspect, so nothing is cropped and there is nothing to reframe. |
| Invoice email | No photos by design (multi-MB payloads get invoices quarantined at corporate gateways) — it links to the page above. |
| Invoice PDF | **No photos at all.** `include_photos=False` on the record path and nothing draws them; the URLs on `InvoiceData` are unused. |
| Technician repair detail + `saas/replacement_detail.html` | **The only two places** rendering the crop *file* itself, via `partials/photo_crop_control.html`. |

The mechanism is one helper — `focus_positions_for(job)` in
`services/photo_crops.py`, returning `{source_field: 'x% y%'}` for
`object-position`. It reads the tap coordinates only (so a null-box crop
still frames), skips `damage_photo_after` (never zoom a resin repair's
blemish), and is absent for unmarked photos so every template's `{% if %}`
degrades to the pre-P6 rendering.

**No label is stored anywhere at all** — labels do not exist as a column;
they are derived at export time by `services/photo_dataset.py`. So "I marked
the break and the invoice photo shows no label" is the system working as
designed.

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
- **A squash merge makes the "did it land?" recipe lie** (P6). The check the
  census session wrote — `git log origin/main..origin/<branch>` should be
  empty — assumes a merge commit. Squashing rewrites the SHAs, so the branch
  commits stay "not on main" forever and the check screams about a merge that
  worked perfectly. **Verify a squash by content**, not by SHA:
  `git diff --stat origin/main origin/<branch>` (empty for the files you
  care about) or `git ls-tree -r --name-only origin/main | grep <new file>`.
- **How much a blind centre-crop costs depends on the photo's orientation**
  (P6), and a landscape test photo will hide the whole bug. A 4:3 landscape
  photo in the invoice's ~1.6:1 tile loses ~15% off the top and bottom — the
  break is usually still in frame. A 3:4 **portrait** photo loses ~53% of the
  frame to a band across the middle, and a chip high on the glass is simply
  not on the invoice. Phones shoot portrait; test with one. This also means
  the reverse: do not promise a dramatic improvement on landscape photos.
- **`object-position` with `cover` puts the point in frame, not in the
  middle** (P6). `X% Y%` aligns the image's X% point with the *box's* X%
  point, so a break at 90% down sits near the bottom edge. Always visible,
  never centred. Good enough, and much cheaper than pixel math against a
  CSS-sized box — but don't write "centred" in a spec and then measure it.
- **`Repair` has no `work_done` field** (P6) — a seed script written from
  habit dies on it. The job's own description lives elsewhere; check the
  model before inventing kwargs.
- **`CustomerUser` has no `tenant` FK** (P6): it reaches the tenant through
  `customer`. A test that passes `tenant=` gets `TypeError`.
- **Two branches, one migration number, and both merge green** (2026-08-27).
  #219 (P4a) and #221 (an unrelated arc) each added `technician_portal` `0060`
  on top of `0059` and merged eight minutes apart. Neither PR could have
  noticed: the collision does not exist until both are on `main`, and what it
  breaks is `manage.py migrate` **entirely** — two leaf nodes and Django
  refuses to build a plan, so the postdeploy hook dies before the app serves.
  This is the second occurrence (`0050_merge_20260810_1635` was the first).
  **Before opening a PR that adds a migration, `git fetch && ls` the app's
  migrations directory on `main`** — your number may have been taken while you
  worked. `tests/test_migration_graph.py` (PR #225) now fails on it.
- **…and then it happened to the fix, twenty-four seconds later** (2026-08-27).
  Two sessions independently noticed the duplicate `0060` and each opened a
  PR adding the merge migration; #225 and #226 merged within half a minute of
  each other, and `main` had **two `0061` merge nodes** — two leaves again,
  identical dependencies, identical (empty) operations. A merge migration is
  a migration; it collides like one. The guard test added in #225 is what
  caught it, on `main`, immediately, which is the entire argument for the
  guard. Resolution is a deletion, not a third merge: both files were empty
  merges of the same two parents and neither had been applied anywhere, so
  one is simply removed. **Check whether the fix has already been fixed
  before you write it** — `git fetch && gh pr list` costs nothing.
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

# P6 · Show the close-up — DONE (PR #222, merged 2026-08-27)

| Field | Value |
|---|---|
| **Goal** | The break a technician marked becomes visible to the customer on the surfaces that already show photos, and the three bugs on that path get fixed. A tap starts paying for itself the day it happens. |
| **Size** | M |
| **Depends on** | P1–P4a (all the data exists already). **PR #219 must be on `main` first** — see the merge-race trap. Nothing else. No new model, no migration expected. |
| **Why it matters** | This is the missing half of the arc's purpose (see the revised statement at the top). Four sessions built capture with no payoff for the person capturing, and production says 1 of 77 photos has ever been marked. Every later session in this document — the backfill, P5, and ultimately the classifier — is rate-limited by whether techs mark breaks, and they will not until doing so does something. **Treat the capture rate as the acceptance metric, not the pixels.** |
| **Verified current state (2026-08-26)** | `rs_systems/views.py:657-678` builds the `photos` list for the public invoice page; `templates/billing/public_invoice_view.html:180-189` renders it, with the tile CSS at `:51`. Only these two files matter for the main change. The crop itself is `crop.cropped_image`; the point is `crop.center_x_pct` / `center_y_pct`; read the job with `crop.service` / `crop.service_kind`, never the raw FKs. |
| **The three bugs to fix here** | **(1)** The tile is `height: 120px; object-fit: cover` — a blind centre-crop, i.e. P3's "guess the centre" baseline, ~21% off the real break. **(2)** `:659` does `exclude(repair_id__isnull=True)`, so replacement line items contribute **no photos at all** — the expensive invoices, where a close-up matters most, have none. **(3)** `:672` passes raw `repair.unit_number` into a `Unit {{ photo.unit }}` caption (`:189`); an individual's is blank, so the caption reads "Unit  — Before". That is the documented CLAUDE.md individual-vs-fleet trap — route it through `get_vehicle_identifier()` / `vehicle_column_label`. |
| **DECISION, taken by Drake 2026-08-26** | **(b): reframe the original.** The full original stays the served file and `object-position: <x>% <y>%` moves the crop origin onto the marked point. No new asset, no cache-busting problem, and an unmarked photo renders byte-identically to before. (a) — serving `cropped_image` as the tile — was not chosen and is not queued; if it ever is, it needs `?v={{ crop.updated_at|date:'U' }}` (a re-tap reuses the filename) and a fallback for a null box. |
| **Do not zoom the after photo** | A resin repair leaves a visible blemish; magnifying it shows the customer the scar rather than the fix. Before and customer-submitted → close-up. After → full frame. See the trap. |
| **Consider, don't assume** | The customer portal detail pages (`customer_portal/repair_detail.html`, `replacement_detail.html`, `batch_detail.html`) show the same originals and could get the same treatment — but the invoice is where the money and the dispute are, so do that first and see whether it is worth spreading. The invoice **PDF** is a separate renderer; check before promising it. |
| **Acceptance criteria** | An invoice for a job with a marked break shows the damage centred, not the middle of the frame. A replacement invoice shows its photos. No caption reads "Unit " with nothing after it. A job with **no** crop renders exactly as it does today (this must degrade to current behaviour, not to a broken tile). Nothing writes to an original. |
| **Out of scope** | Backfilling the 77 (P4a.1 — but note P6 is what makes that worth doing). Recording declined work (P5). Any model. |
| **Watch for** | The invoice page is public and tokened — it is served to people who are not logged in, so anything added there must not leak another tenant's media or require auth. Crops live under `media/repair_photos/crops/` with unsigned public URLs in prod, same as the originals already on that page, so this changes no exposure — but verify rather than assume. |

**Notes**

**What shipped.** One helper, four surfaces, three bugs.

- `focus_position(crop)` and `focus_positions_for(job)` in
  `apps/technician_portal/services/photo_crops.py` — the crop service owns
  crop semantics, so both consumers import from there rather than growing a
  second copy. `focus_positions_for` reads the job's prefetched
  `photo_crops`, so a caller that prefetched pays no query per job.
- `rs_systems/views.py::_public_invoice_photos(invoice)` — the photo list for
  the public invoice page, lifted out of `public_view_invoice` so it is
  directly testable without a token or a request.
- `templates/billing/public_invoice_view.html` — inline
  `style="object-position: …"` on the tile, `{% if %}`-guarded.
- `apps/customer_portal/views.py::customer_repair_detail` +
  `templates/customer_portal/repair_detail.html` — same helper, same guard.

**The size of the win depends on the photo's orientation, and this is worth
saying out loud** because it is easy to demo it away. The invoice tile is
`minmax(160px, 1fr)` wide by 120px tall — roughly 1.6:1 in practice.

| Photo | Tile crop | What the blind centre-crop cost |
|---|---|---|
| Landscape 4:3 (1.33) | ~15% off the top and bottom | Little. The break is usually still in frame; reframing barely moves it. |
| **Portrait 3:4 (0.75)** | **~53% of the frame, a band across the middle** | **Everything.** Verified in a browser: a chip 17% down the frame was *not on the invoice at all*. The tile showed a wiper. |

Phones shoot portrait by default and technicians shoot one-handed, so the
portrait case is not the edge case — but do not promise a dramatic change on
a landscape photo, because there isn't one.

**`object-position` guarantees in-frame, not centred.** With `object-fit:
cover`, `object-position: X% Y%` lines the X% point of the *image* up with
the X% point of the *box*. Because 0 ≤ X ≤ 100, the marked point is always
inside the tile — but a break at 90% down lands near the bottom edge rather
than in the middle. That is the standard focal-point technique and it is
enough; true centring needs pixel math against a CSS-sized box and buys
little.

**It works off the tap, not the crop file.** `focus_position` reads only
`center_x_pct`/`center_y_pct`, so a row whose derived close-up failed to
render — unreadable original, null box, the case `retry_photo_crops` exists
for — still frames the invoice correctly. A tap is useful the moment it is
recorded.

**Exposure is unchanged, and that was checked rather than assumed.** No crop
file is linked from the public page; the served URL is the same original that
page has always served. A test asserts `repair_photos/crops/` never appears
in the rendered HTML.

**Surfaces deliberately left alone**, each for a reason:

- `customer_portal/replacement_detail.html` — `w-full object-cover` with no
  height constraint. The box takes the image's own aspect, so `cover` crops
  nothing. There is no blind crop to fix.
- `customer_portal/batch_detail.html` — `max-h-72` with no `object-fit`.
  Letterboxed, full frame. Same reason.
- **The invoice PDF** — checked, and it renders no photos at all today.
  `InvoiceData` carries `before_photo_url`/`after_photo_url` and
  `generate_pdf` takes `include_photos`, but the record path passes
  `include_photos=False` ("Photos disabled by default for now",
  `invoice_service.py:1233`) and nothing draws them. Putting photos in the
  PDF is a product decision, not a P6 follow-up.
- **The invoice email** — no photos by design (multi-MB payloads get invoices
  quarantined at corporate gateways). It links to the page, which is now
  correct.

**Testing.** `tests/test_photo_closeup_visible.py`, 22 tests: the helper
(including clamping out-of-range coordinates and the never-zoom-the-after
rule), the three bugs, the degrade-to-today path, a job billed on two lines,
a free-form charge line, a bad token, and both portal branches. The P1–P4a
suites (139) stay green. `tests.test_customer_request_replacement.
test_shop_is_notified` fails — **pre-existing on `main`**, baselined in a
detached worktree, unrelated.

**What this does not do.** It does not raise the capture rate by itself. It
removes the reason the rate was 1 of 77 — a tap now changes something a
customer sees — but nobody has tapped since. **P4a.1 is what converts this
into banked labels**, and it is now worth doing.

# P3.1 · Validate the suggester against real photos — DONE (2026-08-27)

| Field | Value |
|---|---|
| **Goal** | Answer the question P3 could not: is the saliency suggester any good on photographs of actual windshields? |
| **Size** | S |
| **Depends on** | P3, and — really — **on the backfill having been run**, not merely built. Production holds 77 completed repairs carrying a real damage photo and P4a.1 (#224) put them all in one queue, but as of 2026-08-27 exactly one is marked. Ground truth is what this session scores against, so **check `export_photo_dataset --stats-only` before starting**: if the confirmed-crop count is still ~1, this session has nothing to measure and the afternoon at the queue is the prerequisite. |
| **Why it matters** | P3 ships `PHOTO_SUGGEST_ENABLED=false` on the strength of one synthetic benchmark where the detector lost to "guess the centre of the photo" on cluttered glass. That is either a correct kill or an unfair one, and nobody knows which. A suggester that works raises the capture rate everything downstream feeds on; one that doesn't should be deleted, not left dark. |
| **How — DO NOT SWEEP FIRST (revised 2026-08-27, from measurement)** | The obvious plan is to sweep with the suggester on and then run the queue, so each photo opens on the machine's guess and the correction distance is recorded for free. **A dry run against production says don't.** Mark the 78 cold, then score the suggester offline against those marks. The suggester is deterministic, so it can be re-run over the same photos at any time — nothing is lost by scoring afterwards, and what is gained is a ground truth with no anchoring in it. |
| **What the dry run measured (2026-08-27, prod, writes nothing)** | `suggest_photo_crops --dry-run --field damage_photo_before`: **78 unmarked before-photos, 26 guesses, 52 declines** — it has an opinion about one photo in three, so a sweep does not change the shape of the sitting; you tap the other two-thirds cold regardless. The guesses are *not* degenerate-centre (median 16% away from dead centre, x spanning 20–71%, y 38–75%), so the detector is doing something. Whether it is doing the *right* thing is still unmeasured — that is what the cold marks are for. |
| **Why cold, specifically** | A pre-placed marker anchors the person correcting it, so "correction distance" measured that way **understates the true error** — the sweep would contaminate the exact number P3.1 exists to produce. Cold marks cost the same afternoon and yield a clean baseline. |
| **Two flaws in the sweep, found by the same dry run** | (1) **Score gates nothing.** `MAX_SPREAD` decides whether to decline, but a surviving suggestion is saved regardless of score — 5 of the 26 scored under 0.20, one at **0.04**, and they land with identical standing to a 0.89. If the sweep is ever run for real, it wants a `--min-score`. (2) **The default sweeps after-photos**: 20 of 46 total would-be marks were `damage_photo_after`, which this arc decided is never marked or zoomed. P6 protects the *rendering* (`UNZOOMED_SOURCE_FIELDS`), so no invoice would be reframed — but it would still write 20 junk crops and 20 `not_applicable` rows. **Always pass `--field damage_photo_before`.** |
| **The trap if you sweep anyway** | A photo the suggester marked is `confirmed_by_human=False` until a person confirms it. Do not sweep, see 26 crops appear, and report the backlog burned down — the sweep produces *guesses*, and the dataset weights on the confirmed flag for exactly this reason. The number to watch is confirmed crops, not crops. |
| **Acceptance criteria** | A table of median/worst error for detector vs centre-guess over real photos, plus the decline rate (how often it correctly returns None). A recommendation to tune `MAX_SPREAD`, keep the kill switch off, or remove the suggester. |
| **Out of scope** | Building a better detector. This session measures; a rebuild is its own session and probably wants P4b's data anyway. |
| **Note** | `test_clutter_defeats_the_suggester` is designed to fail once the suggester is fixed. If this session improves it, that test is the one to update — deliberately, with the new numbers in the message. |

**Notes**

**Notes — the measurement, 2026-08-27**

Drake marked the backlog cold on production (73 confirmed crops, 72 of them
before/customer photos). The suggester was then run over the same originals
offline and compared to where he actually tapped. **Nothing was written**; the
originals were opened read-only and the scratch script removed afterwards.

**Finding 1 — P3's conclusion was wrong, and the synthetic benchmark is why.**
P3 shipped `PHOTO_SUGGEST_ENABLED=false` because the detector lost to
"guess the centre" on synthetic cluttered glass. On real windshields it wins
clearly, on the photos it chooses to speak about:

| On its own 27 picks | median | mean | p90 | worst |
|---|---|---|---|---|
| suggester | **7.5** | 11.2 | 20.7 | 41.3 |
| centre (50,50) | 18.7 | 18.4 | 25.5 | 27.6 |

It beats the centre on **21 of 27 (78%)**. The synthetic fixtures were
misleading, not merely unrepresentative — **do not tune this detector against
generated images again.**

**Finding 2 — the big one, and it is not about the detector at all.**
Technicians do not tap the middle. All 72 marks cluster at **(41, 61)** —
left of centre and well below it — with a tight spread (stdev x 8.5, y 7.1;
x spans 17–56, y spans 44–77). Physically obvious in hindsight: a chip is
photographed from the driver's side, low on the glass.

So the cheapest possible change beats the entire suggester. Leave-one-out
cross-validated, therefore honest and out-of-sample:

| Over all 72 | median | mean | p90 |
|---|---|---|---|
| **centroid (41, 61), LOO** | **9.3** | 9.8 | 15.7 |
| centre (50,50) | 17.6 | 17.2 | 24.7 |

**The centroid halves the error against the centre, beats it on 65 of 72
(90%), and costs zero computation** — no Pillow, no flag, no per-photo work.
It is stable across the corpus: first half (40.5, 59.3), second half
(41.0, 63.3).

**Finding 3 — the score is meaningful, but only at the top.**

| score band | n | median error |
|---|---|---|
| 0.0–0.2 | 5 | 11.5 |
| 0.2–0.4 | 3 | 18.1 |
| 0.4–0.6 | 6 | 6.9 |
| 0.6–0.8 | 2 | 24.3 |
| **0.8–1.0** | **11** | **3.2** |

A `>= 0.8` gate fires on 15% of photos at a median error of **3.2%**, which is
very good. But blended against a centroid fallback for the rest it moves the
overall median only from 9.3 to **8.1** — so the detector is a **refinement on
top of the centroid, not a replacement for it**, and most of the available win
is already taken by the constant.

**What to do with this — recommendation**

1. **Change the unmarked-photo default from `50% 50%` to `41% 61%`.** This is
   the shippable result. Every unmarked photo on the invoice tile and the
   portal improves immediately, with no computation and no feature flag. It is
   a one-line change to the fallback in the P6 rendering path.
2. **Turn the suggester on behind a `--min-score 0.8` gate** — worth the 15%
   it fires on, and it wants that gate added to `suggest_photo_crops` first
   (today score gates nothing; see P4a.1's Notes).
3. **Do not tune the detector on synthetic images.** Any future work uses these
   72 real marks as the benchmark. Re-derive the centroid as the corpus grows —
   72 marks from one shop is not a universal constant, and a second shop is the
   first real test of whether (41, 61) generalises.
4. `test_clutter_defeats_the_suggester` was written to fail once the suggester
   improved. It has not improved — the *benchmark* was wrong. Update it with
   these real numbers rather than deleting it.

**Correction to why the backfill was sold, 2026-08-27.** This document argued
for P4a.1 on the grounds that "marking one of these 77 visibly improves a real
customer's invoice", and that turns out to be **weak for the backlog
specifically**. Of the 72 marked photos, only **12** are on jobs from the last
60 days, and they touch **18 invoices, 13 still open**. The rest are on
invoices that were sent, viewed and paid months ago; a better-framed photo
helps there only if somebody revisits the link.

What the backfill actually bought, in order of value:

1. **The measurement** — the 72 marks produced the (41, 61) constant, which
   improves **every unmarked photo forever, including all future ones and ones
   nobody ever taps.** This was not the stated reason for doing it and is by
   far the largest return.
2. **70 positive-class training rows** — real, banked, and currently **inert**:
   P4b still needs a negative class that this business has never once produced
   (§The pause).
3. **The customer-facing improvement on old invoices** — real but small, per
   the numbers above.

The lesson for the next session that wants an afternoon of somebody's time:
**the honest payoff may not be the one in the pitch.** Say which it is.

**Method note:** the marks were made **cold**, with no suggestion pre-placed,
which is what makes this measurement clean — a pre-placed marker anchors the
person correcting it and would have understated the error. That decision is
the reason these numbers mean anything; keep it for any future scoring pass.

# P4a.1 · Backfill the 77 — DONE and RUN (2026-08-27) · **1 → 73 crops**

| Field | Value |
|---|---|
| **Goal** | Every completed repair that already carries a photo gets its break marked. 77 photos, 1 marked. |
| **Size** | S |
| **Depends on** | P2's detail-page endpoint, which already does this one photo at a time. |
| **Why it matters** | 77 labeled positives are sitting in production requiring no new field work, no waiting and no business change. It is the largest single increment available to this arc and the only one not gated on something outside the code. **P6 is merged**, so marking one of these 77 visibly improves a real customer's invoice — the backfill is an afternoon with a product result rather than charity for a model that does not exist. |
| **What shipped** | `/tech/photos/mark/` — one page, the whole worklist, tap and advance. Read the Notes below before touching it; the queue's membership rules are decisions, not implementation. |
| **Built vs run** | The session that built this did **not** run it, and the row here said so in capitals for a day. Drake ran it on 2026-08-27: **73 confirmed crops, up from 1.** Kept as a reminder that "the tool is DONE" and "the backlog is done" are different claims, and only the second one moves a number. |
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

# P6.1 · Aim the blind crop where people actually tap — DONE (2026-08-27)

| Field | Value |
|---|---|
| **Goal** | An **unmarked** photo should centre on (41%, 61%) instead of (50%, 50%). |
| **Size** | XS — a CSS default, not logic. |
| **Depends on** | P6 (the rendering path) and P3.1 (the number). Both done. |
| **Why it matters** | Measured, leave-one-out cross-validated on 72 real marks: the constant **halves** the median error against dead centre (9.3 vs 17.6) and wins on **65 of 72 (90%)** photos. It costs no computation, needs no flag, opens no image, and applies to every photo nobody ever marked — including all future ones. It is the single best return in the arc per line changed. |
| **Where** | The two surfaces P6 wired: the invoice tile's CSS in `templates/billing/public_invoice_view.html` (the rule near `:51` that sets `object-fit: cover`) and the portal's `object-cover` image in `templates/customer_portal/repair_detail.html:295`. Both currently emit `object-position` **only** when `focus_position()` returned something, so an unmarked photo falls through to the CSS default of `50% 50%`. Change that default; do not touch the `{% if %}` — a marked photo must still win. |
| **Do it in CSS, not in the helper** | Resist making `focus_position()` return `'41% 61%'` for a null crop. It is documented as "empty when nothing is marked", the templates branch on that emptiness, and a marked-vs-unmarked distinction is worth keeping in the data even when both render. A default belongs in the stylesheet. |
| **Acceptance criteria** | An unmarked photo renders at `41% 61%`; a marked one still renders at its tap. A test asserting the default survives a Tailwind rebuild — the value is easy to lose in a purge if expressed as a utility class, so prefer plain CSS in the existing block. |
| **Name the constant once** | Put it in one place with a comment pointing at P3.1's table, so the next person knows it is measured rather than taste, and knows to re-derive it as the corpus grows. |
| **Caveat to write down** | 72 marks from **one shop** is not a universal constant. It is very stable within this corpus (first half (40.5, 59.3), second half (41.0, 63.3)), but a second shop is the first real test. Re-derive; do not treat (41, 61) as physics. |

**Notes**

**Executed 2026-08-27** on `feat/photoml-p61-blind-crop-default`. It came in
larger than "one line", for one reason worth keeping.

**The constant is authored once, in Python, and copied into two stylesheets
that cannot import it.** `BLIND_FOCUS_POSITION = '41% 61%'` lives in
`apps/technician_portal/services/photo_crops.py`, next to
`UNZOOMED_SOURCE_FIELDS`, carrying the measurement, the cross-validation
result and the one-shop caveat. The two surfaces P6 wired cannot share a
stylesheet — the customer portal compiles through Tailwind into `app.css`,
while the public invoice page is a standalone document with its own inline
`<style>` block and no access to it. So:

| Surface | Mechanism |
|---|---|
| Customer portal (`customer_portal/repair_detail.html`) | `.photo-blind-focus` in `assets/css/input.css` `@layer components` (was `static/css/src/`; moved by UI_MAGIC S17, PR #233) |
| Public invoice (`billing/public_invoice_view.html`) | `.photo-grid img.blind-focus` in that page's own `<style>` block |

`tests/test_photo_blind_focus.py` is what keeps those three copies honest: it
imports the constant and asserts it appears in the Tailwind source, in the
**compiled** `app.css`, and in the invoice page. The compiled-CSS assertion is
the one that matters — a purge silently dropping `.photo-blind-focus` produces
no error anywhere, and every unmarked photo just quietly goes back to being
centre-cropped.

**The spec's advice was followed exactly on the one thing it insisted on:**
`focus_position()` still returns `''` for an unmarked photo, and both
templates still branch on that emptiness. The default is a stylesheet
default, so a marked photo's inline `object-position` still wins on
specificity, and the marked-vs-unmarked distinction survives in the data.

**One thing the spec did not anticipate, and it is a real bug it would have
shipped.** The invoice page's rule was specified as going on `.photo-grid
img` — but that grid renders the **after** photo too, and P6 established that
an after photo is *never* reframed: a resin repair leaves a visible blemish,
so zooming it shows the customer the scar instead of the fix. Putting the
default on every tile would have aimed the blind crop straight at the
blemish. The fix is a `reframe` flag on each photo dict in
`_public_invoice_photos` (`source_field not in UNZOOMED_SOURCE_FIELDS`), and
the class is emitted only when it is true. The portal needed the same care
for the same reason — its before and after photos sit in identical
`object-cover` boxes ten lines apart, which is exactly how a well-meaning
edit undoes this. There is a test named for that.

**Two existing tests were renamed rather than deleted.**
`test_an_unmarked_photo_renders_exactly_as_before` and
`test_an_unmarked_portal_photo_is_unchanged` both still *passed* after the
change — they assert the absence of an inline `style="object-position`, and
this adds a class, not a style. They passed while describing behaviour that
is no longer true, which is worse than failing. They now assert the default.

**Verification.** 91 tests across `test_photo_blind_focus`,
`test_photo_closeup_visible`, `test_photo_tap_crop`, `test_photo_dataset`,
`test_mobile_touch_targets` and `test_migration_graph`: all pass.
`./scripts/build_css.sh` re-run and `app.css` committed — the compiled rule is
`.photo-blind-focus{-o-object-position:41% 61%;object-position:41% 61%}`.

**When to re-derive.** The moment a second shop has marks. The number is a
median over 72 photos from one shop's technicians shooting from one habitual
position; it is stable *within* that corpus and unproven outside it. The test
`test_the_constant_is_the_measured_pair` asserts the exact pair on purpose —
it is meant to fail loudly when someone changes it, so the change is made
together with P3.1's table and a recorded sample size.


# P6.2 · Before/after pair on the invoice — DONE (2026-08-31)

**Why the arc reopened (2026-08-27).** The question that reopened it: what
does a shop that is not ours get out of any of this? A technician at another
tenant sees "Tap the break" pop up with no explanation and no proof that
tapping helps anyone — the arc already measured what that produces (1 of 77).
Drake's pick from the options: the before/after pair. A glass repair's
product is *invisible when the work is good* — the chip becomes a faint
blemish and the customer drives away with nothing to show anyone. The only
artifact that shows what was actually bought is the damage photo next to the
repaired photo, side by side. Both photos already exist on the model, are
already uploaded by the same technicians, and already render on the public
invoice page — as two unrelated tiles in a flat grid that never says "this is
the same spot on the same glass, an hour apart." This session makes them one
exhibit. It is also the purest expression of the revised purpose statement:
it pays the shop back for photographing (and tapping) with something a fleet
manager forwards to their boss, and every after photo it motivates is a photo
the corpus gets for free.

| Field | Value |
|---|---|
| **Goal** | A job with both a before and an after photo renders them as **one side-by-side pair** on the public invoice page — one shared caption, "Before" / "After" labels — instead of two tiles that happen to share a grid. |
| **Size** | S |
| **Depends on** | P6 (the focus plumbing, merged #222) and P6.1 (the blind default; the pair's unmarked before tile must inherit it). The deploy of `main` is independent of this session and still comes first. |
| **Why it matters** | Proof of work is the entire sales pitch of a repair shop — "chip → nearly invisible" — and no surface in the product currently makes the comparison for the customer. It is the strongest per-tap payoff identified in the 2026-08-27 review, it is the answer to "why should a tech at another shop ever tap", and it doubles as insurance/fleet-approval evidence on the invoices where money is questioned. |
| **Where (verified 2026-08-27)** | The photo fields live on `GlassService` (`apps/technician_portal/models.py:539` `damage_photo_before`, `:546` `damage_photo_after`), so repairs AND replacements carry them. The invoice page's photo list is `_public_invoice_photos` (`rs_systems/views.py:636`) — it flattens every job's photos into one list, one dict per photo, rendered by the flat grid in `templates/billing/public_invoice_view.html:183–193` with the tap's `object-position` inline at `:190`. The customer portal already renders the two photos as a labelled pair in one card (`templates/customer_portal/repair_detail.html:295` and `:308`), so the portal needs at most caption polish — **the invoice page is the whole session.** |
| **The framing decision — read before coding** | The standing decision from P6 is that the after photo is never reframed (`UNZOOMED_SOURCE_FIELDS`, `services/photo_crops.py:72`; P6.1 added a `reframe` flag on the invoice page for the same reason) because zooming a lone after tile magnifies the resin scar. A pair changes the calculus — "the same spot, then and now" is arguably the point — **but tap coordinates never transfer between photos**: the two are different shots from different angles, so the before tap's percents mean nothing on the after image. Matched framing is only honest with the **after photo's own tap**, which capture already collects (`static/js/photo_tap_crop.js:22` prompts "Tap the repaired spot"; `SOURCE_FIELD_CHOICES` includes `damage_photo_after`, `models.py:1856`) and which no renderer has ever used. **v1 keeps the after unzoomed.** Flip it only after looking at real pairs with Drake, and then only using the after crop's own coordinates. |
| **Considerations** | `_public_invoice_photos` returns per-job groups (the pair, plus the customer-submitted photo as its own tile) instead of a flat list; a job with only one photo renders exactly as today — **no placeholder for a missing after** (an empty "After" slot shames the shop on its own invoice). One vehicle caption per group, not per tile (the one-row-one-mention rule). Replacements are included — P6 fought to put them on this page — but their pair reads "the damage → the new glass", so label by service kind, not with repair language. Email policy is unchanged: **no photos in email, ever** (`docs/operations/SES_OPERATIONS.md`); the email's job is to link to this page. The PDF (`InvoiceService.generate_pdf(include_photos=...)`) is a follow-up, not v1. |
| **The real limiter is data, and it is measurable** | The pair only exists when a tech took the after photo. Census the corpus first (`has_photos()` counts either; the pair needs both): if most completed jobs have a before and no after, the binding constraint is that the completion flow never asks for one — that is its own decision (a prompt at COMPLETED is a candidate P6.3), not something to smuggle into this session. Record the number in Notes either way. |
| **Acceptance criteria** | A job with both photos renders one labelled pair with a single caption; a marked before frames on its tap and an unmarked one at the P6.1 default (assert the class survives); the after stays unzoomed; a job with one photo, and an invoice with none, render as today; replacements pair with replacement language; tests cover the grouping helper and the rendered template both. |
| **Out of scope** | Photos in email or the PDF. Prompting for the after photo at completion (P6.3 if wanted). Reusing before coordinates on the after image — never. Anything classifier-shaped. |

**Notes**

**Executed 2026-08-31.** `_public_invoice_photos` returns `(pairs, tiles)`
instead of a flat list: a job with both photos becomes one `.photo-pair`
figure — two labelled shots side by side, captioned once — and everything
else stays the tile it always was, in the same grid, with the same caption.
Verified in a real browser at phone and desktop width against a seeded
invoice carrying two pairs and a single-photo invoice beside it. 19 new
tests; the 22 P6/P6.1 tests in that file still pass, along with the
invoice-page suites that neighbour them (201 photo-arc tests, plus 68 in
`test_invoice_view_tracking` / `test_invoice_send_polish` / `test_fieldops_n4`
/ `test_migration_graph`). No migration, no model change, no new query — the
grouping happens inside the loop that already ran.

**The census contradicted the spec's own fear, and this is the finding worth
keeping.** The spec assumed the after photo would be the binding constraint
and told the session to measure it before building. Measured against
production (read-only, 2026-08-31):

| | count |
|---|---|
| Repairs with any photo | 82 |
| ...with a before **and** an after | **76 (93%)** |
| Completed repairs | 134, of which 74 carry the pair |
| Replacements, ever | 0 |
| Invoices with repair line items | 47 |
| ...carrying at least one pair | **20** |
| ...with a before and no after anywhere on them | **1** |

So there is no missing-after-photo problem: technicians here already shoot
both, and have all along. **P6.3 (prompting for the after photo at
completion) is not worth building** — it would solve a problem the data says
does not exist. The real limiter on this exhibit is that 27 of 47 invoices
have no job photos at all, which is a different question (whether a tech
photographs the job) and not one a completion prompt fixes either.

**What was decided while building, beyond the spec:**

- **The after photo still is not reframed, in a pair either.** The spec left
  this open ("a pair changes the calculus") and v1 keeps it closed. A tap on
  the after photo IS collected at capture and remains unused by every
  renderer; matched framing must come from that tap and never from the before
  photo's coordinates, which describe a different shot from a different
  angle. `test_the_after_photo_is_never_reframed_in_a_pair_either` pins it.
- **The pair stays side by side at every width**, including a phone. Stacking
  it at a narrow breakpoint is the one layout that destroys the comparison,
  and a phone is where an invoice link gets opened.
- **A replacement's pair does not speak repair language.** Nothing was
  repaired, so it reads *Damage* → *New glass*, captioned "…— the damage, and
  the new glass". `PAIR_LANGUAGE` in `rs_systems/views.py` is the one place
  that decides, keyed by service kind.
- **The customer-submitted photo is never half of a pair** — different
  camera, different day. It stays its own tile beside the exhibit.
- **No placeholder for a missing after photo**, as specified: an empty
  "After" slot would shame the shop on its own invoice for a photo nobody
  took.
- The visible caption is shared by both halves; each `<img>` keeps its own
  `alt` ("Unit #4521 — Before"), because a shared caption tells a screen
  reader nothing about which image is which.

**Depended on P6.1, which had not merged — and this is how it was handled.**
`feat/photoml-p61-blind-crop-default` (#234) was still open when P6.2 was
built, and P6.2 rewrites the exact lines it touches, so this branch **merged
#234 into itself rather than racing it**. Given this arc's history with
stacked branches (#218 into a consumed base, three rounds of duplicate
migrations), squash-merging the two separately would have conflicted on every
shared file.

**Outcome, 2026-08-31:** #236 merged as squash `fb4f8b98` carrying both, and
**#234 was closed as superseded** — nothing lost. Both were verified on `main`
*by content*, not by commit log (squashing rewrites SHAs; see "Verifying a
merge in this arc"): `BLIND_FOCUS_POSITION`, `.photo-blind-focus` in the
Tailwind source, the compiled `app.css` and the portal template, plus
`PAIR_LANGUAGE` and `.photo-pair-shot`. 52 tests green against a worktree
checked out at `main` itself. Neither PR carried a migration.


# P5 · Record the jobs we turn away — TODO · **needs Drake's call before it is a session**

**Ask before building (raised 2026-08-27).** P5 is the only negative-class
source this business generates, and P4b cannot happen without it. But P4b's
value is now a fair question rather than an assumption: P3.1 showed that the
customer-facing half of this arc could be finished for free, and **P6.1 has
now finished it** — a measured constant halves the framing error on every
unmarked photo, with no model, no inference and no data. If the better photo
was the point all along, then the arc has already delivered it, and the honest
move is to **close P5 and P4b out** rather than leave them as perpetual TODOs,
and stop describing this as a classifier arc.

So: **do not open this session on the strength of the document.** Ask whether
the classifier is still wanted. If yes, the spec below is ready and its
product case (below, "Considerations, product side") stands on its own without
any ML. If no, mark both DROPPED with the reason and **the arc ends at P6.1,
which is done** — a good ending, not a failed one.

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

- ~~**P6 first.**~~ **Merged (#222).** A tap now visibly reframes the photo
  on the customer's invoice and in their portal. That was the binding
  constraint on everything below and it is lifted — **in the repository.**
  It reaches customers on the next deploy of `main`, which has not happened.
- ~~**P4a.1 — build the queue.**~~ **Merged (#224),** and live in production
  at `/tech/photos/mark/`.
- ~~**Run the queue.**~~ **Done 2026-08-27 — 1 → 73 crops**, in about twenty
  minutes, not the "afternoon" this document kept predicting. It was the
  highest value per minute in the arc and it paid off somewhere unexpected:
  see P3.1, whose measurement is worth more than the 70 training rows.
- ~~**P6.1**~~ **Done** — the measurement is cashed out. Every photo
  nobody marked, past and future, is now aimed at (41%, 61%) instead of dead
  centre, at no computational cost. **In the repository**; like P6, it reaches
  customers only on the next deploy of `main`.
- **Deploy `main`.** P6, P6.1 **and P6.2** are all sitting in the repository
  doing nothing for anybody. This is the highest-value action in the arc, and
  since 2026-08-31 it is the only one left that is not a decision.
- **P5 is the only thing left that is not code**, and it is a decision rather
  than a session: see below.
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
| 2026-08-26 | **P6 executed.** PR #219 merged, so `main` finally carries P4a. The marked break is now visible to customers: the public invoice tile and the portal's repair detail are framed on the tap (`object-position`) instead of the middle of the frame, replacements contribute photos at last, and no caption reads "Unit " with nothing after it. Shared helper `focus_positions_for` in the crop service; the served file is still the untouched original everywhere. Verified in a browser on a portrait photo, where the old tile showed a wiper and no break. **P4a.1 (burn down the 77) is next** — P6 is what makes it worth doing, and it is what will actually move the 1-of-77. |
| 2026-08-26 | **Reframed by Drake.** Asked what a shop gets from cropping: nothing, today. The arc was built training-first and the capture rate proves the cost — **1 of 77**. Purpose statement rewritten around the customer-visible close-up as the *first* purpose and the training set as the second, with the note that percent coordinates serve both from one tap. **P6 added and sequenced next**, carrying three live bugs on the invoice photo path (blind centre-crop, replacements excluded, `Unit ` caption for individuals). Preservation audited and sound; collection is not. |
| 2026-08-26 | **P4a.1 executed.** `/tech/photos/mark/` — the whole unmarked-photo backlog in one queue, tap the break and advance, entered from a link in the job list that hides itself when there is nothing waiting. No new endpoint, model or migration: it drives P2's `save_photo_crop`, and the worklist is recomputed on every load so a marked photo simply leaves it. Label rules and permission checks are shared with the export and the endpoint rather than copied (`label_for_photo`, `can_view_repair` / `_replacement_technician_access`), and the tap-to-percent conversion moved onto `PhotoCropModal.percentFromEvent` so the two tap surfaces cannot drift. **The tool exists; the 77 are still unmarked** — running it against production is the next thing that moves the number. |
| 2026-08-27 | **#222 (P6) and #224 (P4a.1) merged.** Also found and fixed a break neither PR could see: #219 and #221 each added a `technician_portal` migration numbered `0060`, so `main` could not build its migration graph and any deploy would have died in the postdeploy hook. `tests/test_migration_graph.py` added as the guard. |
| 2026-08-27 | **The migration race ran three rounds in one day** — #219+#221 gave duplicate `0060`s; #225+#226 (two independent fixes) gave duplicate `0061`s; #228+#230 (two more, one deletion each) left **no** `0061` at all, back to the start. The guard test caught every round and prevented none, because nothing ran it before a merge. **#231** restores the merge node and adds the repo's first CI workflow — one test, no database, no secrets, ~0.1s. |
| 2026-08-27 | **THE BACKLOG WAS MARKED.** Drake ran `/tech/photos/mark/` against production: **1 → 73 confirmed crops**, in roughly twenty minutes. Marked **cold**, with no suggestions pre-placed, which is what made the next row possible. The metric this arc exists to move moved because a person spent twenty minutes, not because of anything built after P2. |
| 2026-08-27 | **P3.1 executed, and it is the most useful result in the arc.** Scored the suggester against those 73 marks. (1) **P3's kill was wrong** — on real windshields it beats the centre-guess on 78% of the photos it speaks about, median 7.5% vs 18.7%; the synthetic benchmark was misleading, so never tune it on generated images again. (2) **The big one:** technicians tap at **(41, 61)**, not the middle — left and low, because a chip is shot from the driver's seat. Leave-one-out cross-validated, that constant **halves** the error against dead centre (9.3 vs 17.6) and wins on **65 of 72**, at zero computation. (3) The score is meaningful only **≥0.8** (fires on 15%, 3.2% error); blended it moves the median just 9.3→8.1, so the detector is a refinement on the constant, not a replacement. **P6.1 added and sequenced next.** |
| 2026-08-27 | **Correction recorded:** P4a.1 was sold on "each mark visibly improves a real customer's invoice", and measured afterwards that is weak — only 12 of 72 marked photos are on jobs from the last 60 days, touching 18 invoices, 13 still open. The backfill's real return was **the measurement** (a constant that improves every future photo forever), not the old invoices and not yet the 70 training rows, which stay inert until P5. |
| 2026-08-27 | **The deploy failed, and the code was not at fault.** `eb deploy` was run from the feature branch instead of `main`. `.elasticbeanstalk/config.yml` sets `sc: git`, so the EB CLI ships **the current branch's HEAD commit** — that branch predated #231, so the already-fixed duplicate-`0060` graph went to production and `01_migrate` refused to run. Round four of the migration saga was not a duplicate migration at all; it was deploying the wrong commit, which no CI check can catch. Nothing was damaged — `migrate` fails at graph-load time, so nothing partially applied and the running version kept serving 200. **`git checkout main && git pull` before every `eb deploy`.** |
| 2026-08-27 | **P6.1 executed — the arc's code is finished.** Unmarked photos are now aimed at the measured (41%, 61%) instead of dead centre, on both surfaces P6 wired. `BLIND_FOCUS_POSITION` is authored once in `photo_crops.py` and copied into two stylesheets that cannot import Python (the portal's Tailwind build, the standalone invoice page); `tests/test_photo_blind_focus.py` fails if any copy drifts, and asserts the rule survived the Tailwind purge into the committed `app.css`. **Caught a bug the spec would have shipped:** the invoice rule was specified for `.photo-grid img`, which also renders the *after* photo — aiming the blind crop there would frame the resin blemish instead of the fix, so a `reframe` flag now excludes it. Two tests that passed while describing behaviour that was no longer true were renamed and re-pointed. **Everything buildable in this arc is now built; what remains is P5, which is Drake's decision, and a deploy.** |
| 2026-08-27 | **The arc reopens: P6.2 added.** Asked how tap-to-crop justifies itself to a shop that is not ours — the modal explains what to do but never why, and shows no proof — Drake picked the **before/after pair on the invoice** from the proposed options. The "natural ending" note is revised: the customer-facing half has one more session in it. The framing decision (after photo stays unzoomed in v1; matched framing only ever from the after photo's own tap) and the data census (how many jobs have both photos) are written into the spec. P5/P4b remain exactly where they were: a decision, then a gate. |
| 2026-08-31 | **P6.2 executed — the arc's code is finished, again.** A job with both photos is now one exhibit on the public invoice page: two labelled shots side by side, captioned once, framed on the tap (or on P6.1's measured default) with the after photo still deliberately unzoomed. Replacements get their own language. **The census the spec asked for came back the opposite way round:** 76 of 82 photographed repairs already have both photos (20 of 47 invoices carry a pair, exactly 1 has a before and no after), so **P6.3 — prompting for the after photo — should not be built**; the constraint is jobs with no photos at all, not missing after shots. Landed as #236, squash `fb4f8b98`, **carrying #234 (P6.1)**, which was closed as superseded. |
| 2026-09-01 | **Doc brought current after the merges.** P6.1 and P6.2 are on `main` (#236 = `fb4f8b98`; #234 closed as superseded), so the rows that named their branches, the START HERE checklist and the "what is left" line all said the arc had code to write when it does not. **The only open item that is not a decision is the deploy** — production has run `d88f70d5` since before P6, 23+ commits back, and the migration delta is **zero**, so it is code-only. Also recorded: UI_MAGIC **S17 (#233) moved the Tailwind source** to `assets/css/input.css`; that session correctly re-pointed `tests/test_photo_blind_focus.py` and preserved `.photo-blind-focus` in both the source and the committed `app.css`, so the three-copy drift guard still holds. |
