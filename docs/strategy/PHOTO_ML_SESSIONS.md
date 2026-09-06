# Photo ML Sessions — tap-to-crop: a better photo for the customer, and a training set

**Created:** 2026-08-25
**Author:** Claude (planning session with Drake)
**Status:** living document, **and finished being written (2026-09-01)** — every
session that is going to be specced is specced. What remains is execution and one
decision, both enumerated with owners in **§Closing the arc** at the end. Update
statuses and Notes as those complete; when the checklist there is empty this
document is closed, not deleted.
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
| P6.2 · Proof of work | Before/after pair on the public invoice page — one exhibit, not two tiles | S | **DONE, DEPLOYED 2026-08-31** — PR #236, squash `fb4f8b98`. **The census says the pairs are already there: 76 of 82 photographed jobs have both** |
| P7 · Records | Let a customer **keep** the photos, not just look at them | M | **DONE 2026-09-01 — PR #243 MERGED 2026-09-01 15:12 UTC** (squash `f2506773`). Tokened ZIP on the public invoice, per-job download in the portal AND on the shop side. **DEPLOYED 2026-09-06 19:30 UTC** (prod `61273602`) |
| P8 · Close the bucket | Stop serving customers' damage photos to anyone who guesses a filename | S–M | **DONE 2026-09-06.** #248 merged (`969a4035`) and deployed 22:00 UTC; **bucket policy narrowed 22:04 UTC** — anonymous `repair_photos/**` → 403, `tenants/logos/**` → 200, every app route still 200. **The arc's code is finished.** |
| P5 · Negative class | Record the jobs we turn away — the only source of "not repairable" | M | **PARKED** — held open by Drake, 2026-09-01; the structural reason: **zero negatives, accruing at zero**, because the one shop entering data does no replacements. Revisit when a shop that does replacements is on the platform. Still the actual gate on P4b. **Ask before touching; do not close it out on the strength of this row** |
| P4b · Payoff | Repairability classifier | L | **PARKED** behind P5 (or behind The Glass Guy entering replacement jobs — see §The pause). Same structural reason, same rule: ask Drake first |

**Suggested sequence, as revised 2026-09-01:**
P1 → P2 → P3 → P4a → P6 → P4a.1 → P3.1 → P6.1 → P6.2 → **P7 → P8** → **P5** → P4b.
Everything up to and including P6.2 is done, deployed and confirmed serving in
production (2026-08-31). **P7 is deployed** (#243, merged 2026-09-01, on prod
2026-09-06). **P8's application half is built** (PR #248, 2026-09-06): every
damage photo is served by the app behind the same gates as the ZIP, so the
bucket's `repair_photos/*` prefix can go private without breaking a surface.
What remains of P8 is one bucket-policy edit, sequenced *after* PR #248
reaches production for the rollback reason its section gives. **P5 is a
decision**, held open by Drake on 2026-09-01 (see §The pause), and P4b is
parked behind it.
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

**And it reopened once more, on 2026-09-01, for the same reason both other
times.** Hours after the deploy finally put the framed close-up in front of
customers, Drake asked what a customer can do with one — *"what if a trucking
company wants them for record?"* The answer is: look at it, and right-click it
one at a time for a file called `IMG_4686.jpg`. **P7** is that gap, and it is
specced. The pattern is now three for three: every time this arc is asked
"and then what does the person on the other end get?", it has an answer for
the shop and not for the customer.

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

**Where we are (2026-09-01, end of day — one session to merge, one to write,
one decision held):**

**Everything this arc built through P6.2 is deployed and reaching customers**
(see the verification below). The customer-facing half — a close-up framed on
the break, on the invoice and in the portal, plus the before/after exhibit —
is finished, shipped and confirmed serving. **P7 finished it properly**: those
photos can now be *kept*, as a named ZIP, from the public invoice and from
every job page on both sides. It is merged as **PR #243** (2026-09-01) and
reaches customers with the next deploy of `main`.

**The arc's last code is written: P8's application half (PR #248,
2026-09-06).** A customer's damage photo is a route now — shop, portal and
public invoice each serve it behind their own gate, reading bytes through
storage — so nothing the app renders depends on the bucket being public. What
is left of P8 is not code: **one bucket-policy edit**, narrowing
`PublicReadMediaOnly` to the two branding prefixes, done *after* PR #248 is on
prod and the photo surfaces are confirmed rendering there (§P8 Notes has the
exact commands and the rollback). The exposure is still live until that edit
is made.

**The census has not moved where it matters.** Production, 2026-09-01:
78 crops, `repairable=73`, **`not_repairable=0`**. One class, still. Five more
crops than August 27 and not one of them a negative. §The pause explains why
waiting does not fix this and P5 does.

**Drake's call, 2026-09-01: P5 and P4b stay `TODO` — held, not dropped.**
Asked whether to close the classifier out (the honest option once the
customer-facing half shipped) or to build P5 for its own sake, Drake chose
neither: leave both open and decide later. **So do not open P5 on the strength
of this document, and do not close it either.** The Glass Guy is **likely** to
start entering jobs, which would open the second negative-class source with no
new code at all — that is now a live possibility rather than the dead end the
census made it look like.

**Where we were (2026-08-27, end of day — the backlog is marked and the
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

**IT IS DEPLOYED (2026-08-31 23:46 UTC).** Production runs
`app-966a-260831_234633995822` = commit `966a31da`, taken off `main`, which
contains `fb4f8b98` (P6.1 + P6.2) and `c8876d8e` (P4a). This document has been
wrong about deploy state before, so it was verified 2026-09-01 three ways:

- `git merge-base --is-ancestor fb4f8b98 966a31da` — the P6 work is inside the
  **deployed commit**, not merely on `main`. (Ancestry, not the commit log:
  every PR here squashes.)
- The stylesheet production actually serves —
  `https://rssystems.io/static/css/app.3a79468a77b2.css` — contains
  `photo-blind-focus{object-position:41% 61%}`. The measured default is in a
  customer's browser, not just in the repository.
- `/health/` 200, environment Green.

`migrate` was the no-op it was predicted to be: the migration delta between
`d88f70d5` and `main` was zero.

**What that means in rows, counted on production 2026-09-01:** the marks now
reach **20 invoices** (62 line items across **75** marked repairs). Every one
of those invoices frames its damage photo on the break a technician tapped,
and every unmarked photo everywhere else is aimed at (41%, 61%) instead of
dead centre. **This is the arc delivering its first purpose to actual
customers** — the thing four sessions of training-first work never did.

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
| ~~P6.2~~ | **Merged** (#236, squash `fb4f8b98`) — the before/after pair. |
| ~~DEPLOY `main`~~ | **DONE 2026-08-31 23:46 UTC.** Prod runs `966a31da` off `main`; `fb4f8b98` verified inside it by ancestry, and `object-position:41% 61%` verified in the stylesheet production serves. 20 invoices now carry a marked job. The item this document called "the highest-value action in the arc" for five days is closed. |
| ~~#243 (P7)~~ | **Merged 2026-09-01.** One control saves every photo on an invoice as a named ZIP, and every job page (customer *and* shop) has the same button. 29 tests. **Deployed 2026-09-06** (prod `61273602`) — the gate on P8 is cleared. |
| **→ PR #248 (P8, app half)** | **OPEN 2026-09-06.** Every damage photo is served through the app behind the ZIP's gates; ten templates, the mark queue and the crop-save JSON render routes instead of storage URLs; the invoice PDF reads its logo through storage. **Deploy this, confirm photos render on prod, THEN narrow the bucket policy** — the AWS edit is the only step left in the arc and it must not go first (§P8 Notes). |
| **P5 / P4b** | **`TODO`, held by Drake's call of 2026-09-01** — not dropped, not scheduled. He was asked directly whether the classifier is still wanted now that the customer-facing half has shipped, and chose to keep both open and decide later. **Do not open P5 on the strength of this document; ask again.** |
| **The live second source** | The Glass Guy (tenant 15) is **likely** to start entering jobs. A windshield replacement with a photo is a negative-class row and P4a already made that expressible — **no code needed**, so watch `export_photo_dataset --stats-only` rather than building for it. |

**How to deploy, exactly** — kept because the 19:24 failure was caused by
getting this wrong, and the next deploy can repeat it:

```bash
git checkout main && git pull origin main   # NOT a feature branch: sc: git
python manage.py test tests.test_migration_graph   # ~0.3s, no database
eb deploy rs-systems-production
curl -I https://rssystems.io/health/
```


**What is left, in one line:** **merge and deploy PR #248, then make the one
bucket-policy edit in §P8 Notes** — and the code was finished on 2026-09-06.
Everything through P7 is merged, deployed and confirmed serving; P5 is held
open by choice and P4b sits behind it, both gated on the business producing a
job it turned away rather than on anything in this repository. See §The pause
for the census, and §P8 for the bucket.

**Every one of those items now has an owner and a condition that says when it
is finished, in §Closing the arc at the end of this document.** That section
is what makes this doc closeable: it holds the scorecard (purpose 1 delivered,
purpose 2 not), the four-item checklist, the rules that must be moved out of
here before it closes, and the re-entry path if the classifier ever comes
back. **The spec-writing is finished** — nothing above needs another planning
pass, only execution and one decision.

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

**The download path (P7).**
`apps/technician_portal/services/photo_archive.py` is the substrate for every
"save the photos" control: jobs in, `(filename, FieldFile)` pairs out, and a
ZIP built from those in memory. Bytes are read with `field.open()` — **never
by fetching the photo's own URL** — which is what makes it survive P8. Five
routes call it — `/invoice/<id>/<token>/photos.zip` (HMAC),
`/app/repairs/<id>/photos.zip` and `/app/replacements/<id>/photos.zip`
(session, customer-scoped), `/tech/repairs/<id>/photos.zip` and
`/tech/replacements/<id>/photos.zip` (`_job_access`) — plus the customer
batch page, which links per repair to the repair route. Each has its own gate
and none has its own naming:
`<invoice#>_<vehicle>_<date>_<Before|After|Customer-submitted>.jpg`, built
from `get_vehicle_label()` so an individual's file never says "Unit".
`_public_invoice_jobs` (`rs_systems/views.py`) feeds both the page's photos and
the ZIP's, and `_job_access` (`views/repairs.py`) is shared with the crop
endpoints so a download can never be laxer than a tap.

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
**unsigned public URLs** — `AWS_S3_CUSTOM_DOMAIN` is set, and one bucket-policy
statement grants `s3:GetObject` to everyone on `media/*`, which is **P8's whole
subject**; treat any code that depends on a photo URL being fetchable without
credentials as already broken. Everything is under prefix `media/`. Crops:
`media/repair_photos/crops/`. Static files are **not** in this bucket. Dev pre-creates the local dirs in
`development.py`. `core/management/commands/audit_repair_photos.py` diffs S3
against DB references — **any new photo-bearing field or model MUST be added to
its enumeration or `--delete` destroys the files as orphans** (P1 added crops +
fixed two blind spots: soft-deleted repairs and all Replacement photos).

**Tests.** `tests/test_photo_tap_crop.py` (13, P1),
`tests/test_photo_crop_coverage.py` (24, P2),
`tests/test_photo_suggest.py` (40, P3),
`tests/test_photo_dataset.py` (40, P4a),
`tests/test_photo_closeup_visible.py` (41, P6 + P6.2),
`tests/test_photo_backfill_queue.py` (37, P4a.1),
`tests/test_photo_blind_focus.py` (6, P6.1 — the three-copy drift guard),
`tests/test_photo_downloads.py` (29, P7). **230 tests across eight files**;
run all eight before touching anything shared, they are ~40s. `real_jpeg()` there
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
- **The app must never fetch its own media over HTTP** (P7). Every photo URL
  is unsigned today, so a server-side "just download the URL" works — and
  breaks the day the bucket closes (P8), costs an anonymous round trip to S3
  for a file the app already has, and hides a permission bug behind a public
  read. Read bytes with `field.open()`; `photo_archive.py` and
  `export_photo_dataset` both do. The one surviving offender is the invoice
  PDF's logo (`invoice_service.py:239`, `urlretrieve`), listed in P8.
- **`<a download>` is ignored cross-origin** (P7). Photo URLs point at S3, so
  a "Download" attribute on the existing markup silently *opens* the photo
  instead of saving it. That is why every download in this arc is an app
  route, not an attribute — and why it survives P8.
- **Signed URLs expire, so they cannot go in an email** (pre-dates this arc,
  and P8 can re-create it). `templates/emails/notifications/repair_completed.html:12`
  records photos being pulled from that email for exactly this reason. Any
  move to presigned media URLs must leave `tenants/logos/` and
  `email_branding/` alone.

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


# P7 · Let the customer keep the photos — DONE · **built 2026-09-01, PR #243 merged 2026-09-01 (squash `f2506773`), not yet deployed as of 2026-09-02**

**Where this came from.** Drake, 2026-09-01, immediately after the deploy
landed: *"how customers can save their repair photos instead of only getting
to see them in the online public invoice page. Like what if a trucking company
wants them for record?"*

**The miss, stated plainly.** P6, P6.1 and P6.2 made the photo *legible* — it
is framed on the break, and a job with both shots is one exhibit. None of them
made it **keepable**. A fleet manager's record is not a web page they have to
find again; it is a file in a folder, per unit, per date. This is the same
shape of miss the arc already made once and wrote a purpose statement about:
the artifact exists and the payoff for the person on the other end does not.

**What a customer could do before this session — audited 2026-09-01, all four
surfaces. This table is the "before" picture; what replaced it is at the end
of this section.**

| Surface | What exists | What the customer gets |
|---|---|---|
| Public invoice page | Every photo is wrapped in `<a href="{{ photo.url }}" target="_blank">` — `templates/billing/public_invoice_view.html:219` (pair) and `:233` (tile) | Opens the original in a tab; right-click / long-press saves it. **One at a time, and the file is named by the technician's phone** (`IMG_4686.jpg`) — no invoice, no unit, no date |
| Customer portal, repair detail | A JS lightbox: `onclick="openImageModal(...)"` at `templates/customer_portal/repair_detail.html:288`, defined `:438` | **View only.** No link out, no download control |
| Customer portal, replacement + batch detail | Bare `<img>` — `replacement_detail.html:248`, `batch_detail.html:95` | View only |
| Invoice PDF | `include_photos` threaded through three signatures: `apps/billing/services/invoice_service.py:695`, `:860`, `:1233` | **Nothing.** `generate_pdf()` accepts the flag and never reads it, and `InvoiceData.before_photo_url` / `after_photo_url` are populated (`:433`, `:635`) and **read nowhere in the repository**. Do not start this session believing there is a flag to flip |
| Email | Photos deliberately never attached (SES policy, CLAUDE.md) | — |

| Field | Value |
|---|---|
| **Goal** | A customer — above all a fleet manager filing proof of work per unit — can save every photo for a job, or for a whole invoice, in **one action**, as files whose names say what they are. |
| **Size** | M |
| **Depends on** | Nothing unmerged. P6.2's `_public_invoice_photos` (`rs_systems/views.py:656`) is the assembly point; `focus_positions_for` and `get_vehicle_label()` already exist and are already correct about individuals vs fleets. |
| **Why it matters** | It is the second half of the promise P6 made. A close-up framed on the break proves the work *while the page is open*; a trucking company needs it after the tab is closed, in a claim file, next to a unit number. It also costs the shop nothing to give away and is the kind of thing a fleet account notices. |
| **The three shapes** | **(1) A named, app-served single-photo download** — `Content-Disposition: attachment; filename="INV-1042_Unit-4521_2026-08-14_Before.jpg"`. Cheapest, and the substrate the other two want. **(2) "Download all photos" for an invoice** — a ZIP at `/invoice/<id>/<token>/photos.zip`, mirroring `public_invoice_pdf` (`rs_systems/views.py:875`, route at `rs_systems/urls.py:54`) exactly: same `_resolve_public_invoice` gate, same response shape. **This is the fleet answer and what the session should deliver.** **(3) Photos inside the invoice PDF** — the single artifact a fleet manager already files, and therefore the strongest one; but it changes the size and look of every invoice PDF, and it is unwritten work rather than a flag. **Out of scope here unless Drake says otherwise.** |
| **Acceptance criteria** | One control on the public invoice page saves every photo on that invoice as a ZIP, entries named `<invoice#>_<vehicle>_<date>_<Before\|After\|Customer-submitted>.jpg`, with **no unit noun on an individual's file**. The same, per job, from the customer portal. Photo bytes are read **from storage**, never re-fetched over HTTP. A photo missing from storage is skipped and the rest of the ZIP still downloads. The public route refuses without a valid token, exactly like `/pdf/`. Nothing new is written to media or S3. |
| **Out of scope** | Photos in the invoice PDF (its own decision). Emailing photos (SES policy). Changing *which* photos are shown — P6.2 settled that. Watermarking. Closing the media bucket (see below — it is a bigger blast radius than this session). |
| **Decisions needed from Drake** | Whether the invoice PDF should carry photos — the strongest record artifact and the biggest change. Whether the customer's own submitted photo belongs in the ZIP (it is theirs, so probably yes). Whether the shop side wants the same button on the job page. |

**Considerations — the traps this will actually hit**

- **`_public_invoice_photos` returns URLs, not files.** Its dicts carry
  `url` / `label` / `caption` / `focus` / `reframe` and **no handle on the job
  or the storage field** (`rs_systems/views.py:713`–`732`). A ZIP builder must
  read bytes from storage (`field.open()` / `field.read()`), never re-fetch
  its own public URL over HTTP — that is the server making an anonymous round
  trip to S3 for a file it already has, and it breaks the day the bucket is
  closed. Extend the helper to carry the field (or `(job, source_field)`)
  rather than parsing a URL back into an object.
- **Name files with `get_vehicle_label()`, never the raw `unit_number`.** The
  individual-vs-fleet rule in CLAUDE.md applies to a filename exactly as it
  applies to an invoice line: an individual has no unit, and `Unit_.jpg` is
  the filename version of the `Unit  — Before` bug P6 already fixed. Sanitize
  for filesystems too — a vehicle label is free text and can contain `/`.
- **The ZIP is generated, never stored.** `io.BytesIO` + `zipfile`; do not
  write to media or S3. Size is the real risk on a big invoice — decide
  whether to cap or stream, and keep the page's existing habit of tolerating a
  photo that will not open (`try/except`, skip quietly).
- **`<a download>` does not work cross-origin.** The attribute is ignored when
  the href points at another origin — which every photo URL does today (S3).
  A "Download" link bolted onto the current markup would silently *open* the
  photo instead of saving it. This is the concrete reason the download has to
  be served by the app rather than linked.
- **The portal needs its own route, not this one.** The public route is
  HMAC-gated per invoice; the portal is session-gated per customer
  (`customer_repair_detail`, `apps/customer_portal/views.py:709`, scoped
  `customer=customer, tenant=customer.tenant`). Reuse the naming and the ZIP
  builder; do **not** reuse the auth.
- **Per job, not only per invoice.** A fleet manager files by unit and date,
  and an uninvoiced job still has photos worth keeping. The portal detail
  pages are where that belongs.
- **CSP:** the control is a link or a form, not an inline `on*` handler —
  inline handlers are the one thing holding the header at report-only
  (CLAUDE.md).

**Found while specifying this: the photos are world-readable (2026-09-01).**

`AWS_S3_CUSTOM_DOMAIN` is set (`rs_systems/settings/production.py:72`), so
django-storages returns **unsigned** URLs, and an anonymous `curl` of
`media/repair_photos/before/IMG_4686.jpg` returns **200**. Filenames are the
technician's phone's originals: probing `IMG_4680`–`IMG_4695` against our own
bucket returned one live customer photo, so an `IMG_0001`–`9999` sweep would
harvest a real share of the corpus.

- **The HMAC token protects the invoice page, not the photos on it.** Access
  control for a customer's damage photo is currently "know the filename".
- It is also **why saving works at all today**. Closing the bucket *requires*
  the app-served download this session builds, so the order is: ship P7, then
  close the bucket. Reversing it takes away the only save path customers have.
- **Do not close the bucket inside this session.** Every `<img>` in the
  technician portal and the customer portal resolves through the same `.url`,
  so it is a wider change than a download button and deserves its own PR and
  its own verification. Record it, ship P7, raise the bucket separately.

**What shipped, 2026-09-01**

`apps/technician_portal/services/photo_archive.py` is the whole substrate:
jobs in, `(filename, FieldFile)` out, and a ZIP built from those. Every
surface calls the same two functions, so the file a customer saves from the
public invoice page and the one the shop saves from the job page are named
identically — which is the point. It is ~200 lines and no migration.

| Surface | Route | Gate |
|---|---|---|
| Public invoice page | `/invoice/<id>/<token>/photos.zip` (`rs_systems/views.py`) | The same `_resolve_public_invoice` HMAC as `/pdf/` |
| Customer portal, repair | `/app/repairs/<id>/photos.zip` | Session, scoped `customer=` + `tenant=` |
| Customer portal, replacement | `/app/replacements/<id>/photos.zip` | Same |
| Customer portal, batch | per repair, links to the repair route | Same |
| Shop, repair | `/tech/repairs/<id>/photos.zip` | `_job_access` — the gate the crop endpoints already used |
| Shop, replacement | `/tech/replacements/<id>/photos.zip` | Same, via `_replacement_technician_access` |

**Drake's three calls, taken at the top of the session:**

1. **Photos in the invoice PDF: no.** It stays its own decision, unbuilt.
   Nothing in this branch touches the PDF, and `include_photos` is still a
   flag nobody reads — do not mistake it for a switch next session either.
2. **The customer's own submitted photo: yes, it is in the archive.** They
   took it and sent it in; it is theirs. It is named `Customer-submitted` so
   it is never confused with the shop's proof of work.
3. **The shop gets the same button: yes.** The shop is who a customer phones
   asking for the photos — a claim, a fleet's records, a dispute — and once
   the builder exists the shop side is a route and a link.

**Two things worth knowing before touching this again:**

- **`_public_invoice_jobs` was extracted from `_public_invoice_photos`.** One
  traversal now feeds both the photos the page renders and the photos the ZIP
  carries. They must not drift: a ZIP that misses a photo the page showed is
  worse than no ZIP, and a test asserts the two counts match.
- **`_job_access` was extracted from `_resolve_crop_target`.** The shop-side
  download and the crop endpoints answer for the same object under the same
  permission; a download that was laxer than the crop endpoint would leak one
  shop's photos to another just as effectively.

**Where the traps landed.** Every one the spec listed was real and is now a
test in `tests/test_photo_downloads.py` (29 tests, all green, plus the 190 in
the adjacent photo/CSP/icon/CSS suites re-run unchanged):

- Bytes are read with `field.open()`. A test patches `FieldFile.url` to
  raise, and the ZIP still builds — the server never fetches its own public
  URL, which is also what makes closing the bucket possible.
- Filenames go through `get_vehicle_label()`. An individual's file reads
  `INV-1042_2019-Ford-F-150_2026-08-14_Before.jpg`; the word "Unit" cannot
  appear on it. Free text is sanitised, so `Ford F-150 / spare` cannot put a
  slash in a path.
- Two breaks on one unit on one day — a normal multi-break ticket — get `-2`
  appended rather than silently overwriting each other in the customer's
  unzipper.
- A photo missing from storage is skipped, the rest still download, **and the
  ZIP carries a `README.txt` naming what was left out.** A partial archive
  that looks complete is the one outcome worse than an error.
- Nothing is written to media or S3, and no `<a download>` was used anywhere
  (it is ignored cross-origin, which is the whole reason this is an app route
  rather than an attribute).

**What is still not possible, deliberately:** photos in the PDF (call 1
above), photos in email (SES policy), and any change to *which* photos are
shown — P6.2 settled that and this session read its output rather than
re-deciding it.

**Found while specifying this, still open: the photos are world-readable.**
See the subsection above. **P7 was the prerequisite and P7 is built**, so
closing the bucket is unblocked — it is now **§P8**, the next section and the
last code this arc has to write. It was not folded in here on purpose: every
`<img>` in the technician portal and the customer portal resolves through the
same `.url`, so it is a wider change than a download button and deserves its
own PR and its own verification. **Sequence it after #243 is deployed**, not
after it is merged: until the app-served download is actually serving,
closing the bucket takes away the only way a customer can save a photo.

# P8 · Close the media bucket — **DONE 2026-09-06** (PR #248 deployed 22:00 UTC; policy narrowed 22:04 UTC)

**Where this came from.** Found while specifying P7 on 2026-09-01, not while
looking for it: every photo URL this app renders is unsigned, so an anonymous
`curl` of `media/repair_photos/before/IMG_4686.jpg` returns **200**, and the
filenames are the technician's phone's originals. A 16-name probe
(`IMG_4680`–`IMG_4695`) against our own bucket hit one live customer photo.
**The invoice's HMAC token protects the page, not the photos on it** — access
control for a customer's damage photo is currently "know the filename", and
the filenames are sequential.

**Why it was not folded into P7.** Closing the bucket removes the only way a
customer could save a photo (right-click on an unsigned URL). P7 had to ship
first so that the save path exists before the public path closes — and it now
does, reading bytes through storage rather than over HTTP. **That ordering is
also the gate on this session: P8 does not start until P7 is merged and
deployed** — merged 2026-09-01 (#243), deployed 2026-09-06, and the
application half was built the same day (PR #248; see Notes).

**What is actually public — verified against production, 2026-09-01, read-only**

| | |
|---|---|
| Bucket | `rs-systems-media-20251029` (`USE_S3=true`) |
| Why it is public | **One bucket-policy statement**, `PublicReadMediaOnly`: `s3:GetObject` for `Principal: "*"` on `arn:aws:s3:::rs-systems-media-20251029/media/*` |
| ACLs | Already off — `BlockPublicAcls` and `IgnorePublicAcls` are **true**, ownership is `BucketOwnerEnforced`. **Nothing is public by object ACL**, so there are no 235 objects to re-permission: the entire exposure is that one `Resource` line |
| What is behind it | `media/repair_photos/**` — **235 objects** (before/after/customer-submitted/crops). `media/tenants/logos/` — **2**. `media/email_branding/` — **0** |
| What is *not* in this bucket | **Static files.** `STORAGES["staticfiles"]` is `ForgivingManifestStaticFilesStorage` on the instance (`rs_systems/settings/production.py:75`–`92`), so no CSS, JS or font can break here. This is worth knowing before anyone gets nervous about the blast radius |
| What makes URLs unsigned | `AWS_S3_CUSTOM_DOMAIN` (`production.py:72`). django-storages skips signing entirely when a custom domain is set |

| Field | Value |
|---|---|
| **Goal** | A damage photo is readable by the customer it belongs to, the shop that took it, and anybody holding that invoice's token — and by nobody who merely guesses a filename. |
| **Size** | S–M. The AWS half is one policy edit; the application half is however many surfaces render an `<img>`. |
| **Depends on** | **P7 merged and deployed.** Nothing else. |
| **Why it matters** | These are real customers' vehicles, photographed at their homes and yards, in a database that also knows the plate, the unit and the company. It is the same principle that killed the hosted vision model in P3 (§P3's Notes) — that decision refused to let photos leave our infrastructure, and this one is the discovery that they already had. |
| **Out of scope** | Renaming the 235 existing objects. Signed *download* expiry policy for the ZIP (P7 serves bytes, not links). Anything about which photos are shown or how they are framed — P6/P6.1/P6.2 settled that and this session must not change a single class on an `<img>`. |
| **Decisions needed from Drake** | **App-served vs presigned** (below — the recommendation is app-served). Whether the two shop logos stay public (they should; email needs them durable). |

**The prefix split is the shape of this session.** Do not delete the policy
statement: `media/tenants/logos/*` and `media/email_branding/*` must stay
publicly readable, because they are `<img src>` in **email**, opened days
later on a machine with no session. Narrow the statement's `Resource` to those
two prefixes and drop `media/repair_photos/*`. That single change is the
security fix; everything else in this session exists to keep the photos
working afterwards.

**Two ways to serve a private photo. The recommendation is the first.**

1. **App-served, same-origin.** A route per photo, gated exactly like P7's ZIP
   — `_job_access` on the shop side, `customer=`/`tenant=` scoping in the
   portal, `_resolve_public_invoice` for the token path — streaming
   `field.open()` the way `photo_archive.py` already does. No expiry, no
   signature churn, `img-src` collapses to `'self'`, and the gate is *the same
   code* that decides who may download the ZIP, so the two cannot disagree.
   Cost: photo bytes flow through the web instance (P7's ZIP already does
   this), and someone has to choose a `Cache-Control` for an authenticated
   image.
2. **Presigned URLs.** Drop `AWS_S3_CUSTOM_DOMAIN` so `.url` signs. Smaller
   diff, and wrong in a way this repository has already paid for: signed URLs
   **expire** (default 3600s). `templates/emails/notifications/repair_completed.html:12`
   records photos being removed from that email for exactly this reason. It
   also needs a *second* storage backend for branding, because dropping the
   custom domain globally would sign the logo URLs too — see the trap below.

**Traps — every one of these is a live line of code, checked 2026-09-01**

- **The invoice PDF fetches the shop's logo over anonymous HTTP.**
  `urllib.request.urlretrieve(url, tmp.name)` at
  `apps/billing/services/invoice_service.py:239`, with a fallback at `:224`
  that hand-builds `https://{AWS_S3_CUSTOM_DOMAIN}/…`. It is the **only**
  place left where this app fetches its own media over the network. Under the
  prefix split it keeps working by luck — logos stay public — but it is the
  same bug P7 was careful not to write, and it should read
  `tenant.logo.open()` while somebody is in here.
- **Email logos must never become signed.** `_absolute_media_url`
  (`core/models/email_branding.py:32`) returns `filefield.url` whenever
  `AWS_S3_CUSTOM_DOMAIN` is set, and that URL goes into an inbox. An expiring
  logo is broken art in every email opened an hour after it was sent.
- **`img-src` is derived at runtime from `MEDIA_URL`**
  (`common/csp_middleware.py:55`–`68`), and its own docstring says getting it
  wrong *"does not fail a test — it fails repair photos on production only."*
  If photos move to an app route, make sure the header still covers whatever
  origin the remaining `<img>` tags resolve to.
- **Ten templates render a media `.url`** — `customer_portal/repair_detail`,
  `replacement_detail`, `batch_detail`; `technician_portal/repair_detail`,
  `repair_form`, `batch_detail`, `partials/photo_crop_control`;
  `saas/replacement_detail`, `replacement_edit`; and
  `billing/public_invoice_view`. Grep for `.url` at the time you do the work
  rather than trusting this list — a surface missed is broken art, not an
  error page.
- **The crop modal and the mark queue read the same URLs.** `/tech/photos/mark/`
  and `PhotoCropModal` display the original to be tapped; if photos move to an
  app route, the JS that loads them moves with it, or the backlog tool goes
  blind.
- **Already immune, and worth copying rather than re-deriving:** the P7 ZIP
  (`photo_archive.py`, `field.open()`), `export_photo_dataset`
  (`crop.cropped_image.open('rb')`) and `retry_photo_crops`. Nothing in the
  ML pipeline reads a URL.
- **Do not rename the 235 objects.** Enumeration stops mattering the moment
  the prefix is private, and renaming means rewriting every `ImageField` value
  that points at them — a data migration with a much worse failure mode than
  the thing it fixes.

**Acceptance criteria**

- Anonymous `curl -I` of a `media/repair_photos/**` key returns **403**;
  anonymous `curl -I` of `media/tenants/logos/**` still returns **200**.
- A customer sees their photos in the portal; a technician sees them in the
  shop; the public invoice page renders both the pair and the tiles **with no
  cookies and a valid token**, and refuses without one.
- The P7 ZIP still builds on all six routes (it should be untouched — if a
  change to it was needed, something read a URL that should have read
  storage).
- A branded invoice PDF still carries its logo, and a notification email still
  renders its header logo.
- `python manage.py test tests.test_photo_downloads tests.test_csp` green,
  plus whatever asserts the new gate.

**Verification and rollback.** Verify from a machine with no AWS credentials
and no session cookie — an authenticated `curl` proves nothing here. Rollback
is re-adding the dropped prefix to the policy statement: seconds, no deploy,
no object rewrite. That asymmetry is why the AWS half should land *after* the
application half is deployed and confirmed, not before.

**Notes**

**2026-09-06 — application half built (PR #248), app-served as recommended.**
Drake was not asked between app-served and presigned; the recommendation
above was taken as the working assumption, because the presigned path was
wrong for a reason this repository had already paid for. What shipped:

- `apps/technician_portal/services/photo_serving.py` — URL builders per
  surface and one `photo_response()` that streams `field.open()` with
  `Cache-Control: private, max-age=86400`. **The route names the field, not
  the file** (`/photos/damage_photo_before/`), so a `?v=` derived from the
  stored filename is what stops a replaced photo being served stale. Crops
  are versioned by `updated_at` instead, because a re-tap rewrites the same
  filename.
- Three gates, none new: shop routes (`/tech/…/photos/<field>/` and
  `/thumb/` for the close-up) sit behind `_job_access`; portal routes behind
  the `customer=`/`tenant=` scoping the detail page uses; the public route
  (`/invoice/<id>/<token>/photos/<kind>/<job>/<field>/`) behind
  `_resolve_public_invoice` **plus** membership in `_public_invoice_jobs`,
  so a token for one invoice cannot open another job's photo. The public
  route passes `record_view=False` — an `<img>` is not a click.
- `{% load photo_tags %}` (`shop_photo_url`, `customer_photo_url`,
  `crop_thumb_url`) replaced every `.url` in the ten templates the trap list
  named — the list was right. The include-with-parameter in the crop control
  needed `{% shop_photo_url … as before_photo_src %}` bindings on the two
  detail pages. **No `<img>` class changed**; `test_photo_blind_focus` now
  finds the tags by field name instead of `.url`.
- The mark queue's `src` and the crop-save JSON's `crop_url` are routes now
  (`photo_backlog.BacklogItem.photo_url`, `save_photo_crop`), so the backlog
  tool and `PhotoCropModal` did not go blind — the JS never held a URL of its
  own, which is why no JS changed.
- The invoice PDF's logo is read via `tenant.logo.open()`; `urllib` is gone
  from `invoice_service.py`. `InvoiceLineItem.before_photo_url`/`after_…`
  are set to `None` — nothing ever rendered them.
- **CSP untouched.** `img-src` still carries the S3 origin because shop logos
  are still served from it (settings page, join page, email).
- 39 tests in `tests/test_photo_serving.py`, in the guard set. The one worth
  knowing about is `NothingPrintsAStorageUrlTests`: it scans `templates/`
  and the app packages for `<photo field>.url` and fails on any hit, because
  a surface missed is broken art, not an error page.
- Two tests that simulated "broken storage" with `MEDIA_URL=None` were
  rewritten: building the page no longer reads storage at all, so the honest
  assertion is that a deleted file is a 404 on its route and a 200 on the
  page.

**2026-09-06 22:04 UTC — the AWS half is done.** Applied exactly as below after
#248 was verified serving from outside (public invoice 79: page, photo route,
ZIP). Kept for the rollback and for the next bucket. **One finding from the
verification, not P8's but found by it:** the web process (gunicorn) runs with
a **50-character `SECRET_KEY`** while `get-config environment` — and therefore
`/opt/rs-systems/run-cron.sh` — holds the configured **53-character** value.
The raw EB env file mangles the `!%&()` characters on the way into the web
process. Consequences: any HMAC token minted through the cron runner (or an
`eb ssh … run-cron.sh shell`) does **not** validate on the site, and vice
versa; sessions and every emailed invoice link are signed with the web value,
so *changing* either side to match would log everyone out and break every
outstanding link. Nothing in cron mints `generate_payment_token` links today
(review requests use UUIDs), so it is latent — but it is why the first probe
here 404'd, and it belongs in a session of its own before any cron job ever
emails a pay link.

Anonymous, from a machine with no AWS credentials, before and after:

```bash
BUCKET=rs-systems-media-20251029
KEY=media/repair_photos/before/<any key from an eb ssh 'aws s3 ls'>
curl -sI https://$BUCKET.s3.amazonaws.com/$KEY | head -1          # 200 today

aws s3api get-bucket-policy --bucket $BUCKET --query Policy --output text > policy.before.json
cp policy.before.json policy.json
# In policy.json, the PublicReadMediaOnly statement's Resource goes from
#   "arn:aws:s3:::rs-systems-media-20251029/media/*"
# to
#   ["arn:aws:s3:::rs-systems-media-20251029/media/tenants/logos/*",
#    "arn:aws:s3:::rs-systems-media-20251029/media/email_branding/*"]
# Nothing else in the policy changes. Object ACLs are already blocked.
aws s3api put-bucket-policy --bucket $BUCKET --policy file://policy.json

curl -sI https://$BUCKET.s3.amazonaws.com/$KEY | head -1          # 403
curl -sI https://$BUCKET.s3.amazonaws.com/media/tenants/logos/<a logo key> | head -1   # 200
```

Then open the same three pages again. **Rollback** is
`aws s3api put-bucket-policy --bucket $BUCKET --policy file://policy.before.json`
— seconds, no deploy. Uploads are unaffected either way: the app writes with
its own IAM key, not through the public statement. Keep
`AWS_S3_CUSTOM_DOMAIN`; `.url` staying unsigned is what the logos need, and
nothing renders it for a photo any more (the guard test says so).

# P5 · Record the jobs we turn away — TODO · **held open by Drake, 2026-09-01 — ask again before opening it, and do not close it either**

**ASKED AND ANSWERED — 2026-09-01: held.** Drake was given the three options
below (drop it, build it for its own sake, or leave it open) and chose to
**leave P5 and P4b as `TODO` and decide later**. So this section is neither
dead nor scheduled: the spec is ready, the product case stands on its own, and
nobody has committed to it. **Ask again before opening it.** The one thing
that changed underneath it: The Glass Guy entering replacement jobs is now
**likely** rather than hypothetical, and that would supply the negative class
without P5 being built at all — see §The pause, way out 2.

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

| | count (2026-08-26) | count (2026-09-01) | rate |
|---|---|---|---|
| Positive class — completed repairs with a photo | **77** banked | — | ~9/month |
| ...of those actually marked with a crop | **1** | **73** | — |
| Negative class — windshield replacements with a photo | **0** | **0** | **0/month** |

The 2026-09-01 column is `export_photo_dataset --stats-only` run on
production: 78 crops considered, `repairable=73`, `not_applicable=3`,
`unknown=2`, and the command's own verdict — *"Only one class present (73
rows, no not_repairable). A classifier cannot be trained on this."* Believe
that line over any narrative, this one included.

**One sentence in that output will always be there, and it is not a
regression:** *"No confirmed rows carry a machine suggestion, so there is
still nothing to say about the suggester's accuracy."* That is **by design** —
the backlog was deliberately marked **cold**, with no suggestion pre-placed,
which is exactly what made P3.1's measurement honest. P3.1 scored the
suggester offline against those cold marks. Do not read that sentence as "the
suggester has never been measured"; read P3.1's Notes.

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
   replacement crops possible at all. **Asked 2026-09-01: Drake says this is
   likely** — he expects the shop to start entering jobs. That makes it a live
   source rather than the dead end the census implied, and it needs **no
   code**: P4a already lets a crop hang off a `Replacement`, and
   `photo_dataset.py` already labels a completed *windshield* replacement
   `not_repairable`. The action is to watch `--stats-only` for the first row,
   not to build anything.
3. **Import an outside corpus.** Note the asymmetry with P3's standing
   decision: Drake rejected sending *our customers' photos out*. Bringing
   someone else's photos *in* is a different question and has not been asked.
   Do not assume the answer either way.

### What to do during the pause

- ~~**P6 first.**~~ **Merged (#222).** A tap now visibly reframes the photo
  on the customer's invoice and in their portal. That was the binding
  constraint on everything below and it is lifted — **and deployed.**
  It reached customers on the 2026-08-31 deploy of `main`.
- ~~**P4a.1 — build the queue.**~~ **Merged (#224),** and live in production
  at `/tech/photos/mark/`.
- ~~**Run the queue.**~~ **Done 2026-08-27 — 1 → 73 crops**, in about twenty
  minutes, not the "afternoon" this document kept predicting. It was the
  highest value per minute in the arc and it paid off somewhere unexpected:
  see P3.1, whose measurement is worth more than the 70 training rows.
- ~~**P6.1**~~ **Done** — the measurement is cashed out. Every photo
  nobody marked, past and future, is now aimed at (41%, 61%) instead of dead
  centre, at no computational cost. **Live in production since 2026-08-31**,
  verified in the stylesheet the site serves.
- ~~**Deploy `main`.**~~ **DONE 2026-08-31 23:46 UTC** — prod runs `966a31da`,
  P6/P6.1/P6.2 verified inside the deployed commit and the `41% 61%` rule
  verified in the stylesheet production serves. 20 invoices carry a marked
  job. The arc's first purpose is now being delivered to customers, which it
  had never once been while this section was being written.
- **P7 and P8 are not waiting on data.** P7 (keep the photos) is merged
  (#243, 2026-09-01); P8 (close the bucket) is specced and gated on P7 reaching
  production. Neither has anything to do with the classifier or the census —
  they are the customer-facing half finishing itself, and they should not be
  held up by a decision about P5.
- **P5 stays open by decision, not by neglect (2026-09-01).** Drake was asked
  whether to close the classifier out now that the customer-facing half has
  shipped, and chose to hold both P5 and P4b as `TODO`. Nothing about the
  census changed; the appetite is simply undecided. **Ask again before
  building; do not close it unilaterally either.**
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
| **Depends on** | P4a's export, and **a negative class from somewhere** — not merely "data", and not merely time. Two possible sources: **P5** (held open, 2026-09-01) or **The Glass Guy entering replacement jobs** (likely as of 2026-09-01, and needs no code). The minority class stands at **0** and accrues at **0/month**; see §The pause. `export_photo_dataset --stats-only` is the check; it prints the balance and refuses to flatter it. |
| **Why it matters** | The whole point of the arc. |
| **Verified current state** | The export exists, is anonymised, tenant-scoped and reproducible from metadata. Labels come from `services/photo_dataset.py`. Label strength is recorded (`confirmed_by_human`) and unconfirmed suggestions are excluded by default. |
| **Considerations** | Class imbalance is the live risk, not model choice: techs photograph what they already know is repairable, and windshield replacements are rarer than repairs. Read the balance before writing a line of training code. Rows carrying both a `suggested_*` point and a human-confirmed mark are the training pairs for a *learned* detector, and their correction distances are also the honest answer to whether P3's saliency suggester is worth keeping at all. Train outside this codebase; the app's job is the export and, later, serving a verdict. |
| **Decisions needed** | Where training runs (local vs cloud). Whether the classifier ships in-app (an advisory badge on customer requests?) or stays an experiment. Both are Drake's calls and neither is urgent while the data is thin. |
| **Acceptance criteria** | A held-out evaluation with honest per-class numbers before anything ships. |
| **Out of scope** | Auto-quoting or auto-declining work. It advises; humans decide. |

**Notes**

# §Closing the arc · what "done" means, who owns the rest, and what survives this document

*Written 2026-09-01, when the last session that needed specifying was specced.
Everything above this line is the record of the work. This section exists so
that closing the arc is a checklist rather than a judgement call, and so that
the things worth keeping do not die with the document that happens to hold
them.*

## The scorecard, stated once and without flattering it

The purpose statement at the top names two jobs. **One is delivered. One is
not, and not by an amount of time that will fix itself.**

| Purpose | State | The number that says so |
|---|---|---|
| **1 · A close-up of the break the customer can see** | **Delivered, and reaching real customers since the 2026-08-31 deploy** | **20 invoices** frame their damage photo on a break a technician tapped (62 line items, 75 marked repairs). Every *unmarked* photo in the product, past and future, is aimed at the measured **(41%, 61%)** instead of dead centre. **76 of 82** photographed repairs carry a before *and* an after, rendered as one exhibit |
| **1b · …and can keep** | **Merged 2026-09-01** (#243), **deployed 2026-09-06** | Five routes and six surfaces serve a named ZIP: `INV-1042_Unit-4521_2026-08-14_Before.jpg`, or the vehicle for an individual. Bytes read through storage, so it survives P8 |
| **2 · A repairable-vs-not training set** | **Not delivered** | `repairable=73`, **`not_repairable=0`**, accruing at **0/month**. The classifier was never trained and must not be until a second class exists |

**What the arc actually produced, as opposed to what it set out to produce:**
a shop's tap, stored as percent coordinates on an EXIF-upright original, that
reframes a photo on every customer-facing surface — and **one constant**.
(41%, 61%) came out of 73 human marks, halves the framing error against dead
centre on 90% of photos, cost nothing to compute, and improves every photo
nobody will ever mark. That is the most valuable single result in eight
sessions, it is not a model, and it would not exist if the backlog had not
been marked.

**The cost, for the next person estimating something like this:** 9 merged
PRs plus #243 open, 5 service modules (`photo_crops`, `photo_suggest`,
`photo_dataset`, `photo_backlog`, `photo_archive`), 4 migrations — all of them
before P6 — 230 tests, one CI workflow the repo did not have, and four rounds
of a duplicate-migration saga that the CI workflow now prevents.

## What is left, with an owner on each

Nothing below is discovery. Each item has a spec above and a condition that
says when it is finished.

| # | Item | Kind | Owner | Done when |
|---|---|---|---|---|
| ~~1~~ | ~~**Merge #243 (P7)**~~ | code | — | **DONE 2026-09-01 15:12 UTC** — squash `f2506773` on `main` |
| ~~2~~ | ~~**Deploy `main`**~~ | ops | — | **DONE 2026-09-06 19:30 UTC** — prod `61273602` carries #243 by ancestry. (Shipped from a docs branch cut after #244, so it is `main` minus #245's script — nothing runtime.) Item 3 is unblocked |
| ~~3a~~ | ~~**P8 · app half**~~ | code | — | **DONE 2026-09-06** — PR #248 merged `969a4035`, deployed 22:00 UTC; verified from outside on invoice 79: page 200 with route-only markup, photo route 200 `image/jpeg` 2.8 MB, ZIP 200 |
| ~~3b~~ | ~~**P8 · bucket policy**~~ | ops | — | **DONE 2026-09-06 22:04 UTC** — `PublicReadMediaOnly` Resource is now the two branding prefixes. Anonymous `repair_photos/before/IMG_2097.jpg` → **403**; `tenants/logos/IMG_4213.jpeg` → **200**; page / photo route / ZIP still 200 afterwards. Rollback = the `media/*` Resource, recorded in §P8 Notes |
| 4 | **P5 / P4b — ask, then decide** | decision | Drake | Either scheduled, or marked **DROPPED with the reason written down**. Held since 2026-09-01; **do not decide either way on the strength of this document** |
| 5 | **The Glass Guy** | business, no code | Drake | Watch `export_photo_dataset --stats-only` for the first `not_repairable` row. P4a already made it expressible; there is nothing to build |
| 6 | **Move the durable rules out of here** | docs | whoever closes it | The list below is in CLAUDE.md or a test, not only in this file |

When 1–4 are resolved — **resolved, not necessarily built**; a written-down
`DROPPED` closes item 4 — flip the header **Status** to `closed` with the
date, and leave the document where it is. It is the only record of why the
photos are framed the way they are.

## What must outlive this document

A living doc that closes takes its knowledge with it unless the knowledge is
somewhere a person will trip over. **Already safe** — in CLAUDE.md, in a
constraint, or in a test that fails:

- **Percent coordinates on an EXIF-upright original**, never pixels — the one
  convention that makes every crop regenerable and both purposes serveable
  from a single tap.
- **`RepairPhotoCrop` rows and `repair_photos/crops/` are human labour, not
  derived caches.** CLAUDE.md says so; `audit_repair_photos` would otherwise
  delete them as orphans.
- **A crop hangs off a `Repair` *or* a `Replacement`** (CheckConstraint), and
  side/rear glass is tempered — so only a *windshield* replacement means "not
  repairable".
- **No damage photo leaves our infrastructure.** P3's decision, enforced by a
  test that asserts the suggester opens no sockets.

**Not yet safe — these live only in this file, and item 6 above is to fix
that:**

- **(41%, 61%) is measured, not chosen**, and is authored once in
  `photo_crops.py` and copied into two stylesheets that cannot import Python.
  `tests/test_photo_blind_focus.py` catches the drift but not the *why*; a
  future reader who thinks it is an arbitrary constant will "clean it up".
- ~~**Photo bytes are read through storage (`field.open()`), never by fetching
  the photo's own URL.**~~ **Safe as of PR #248:** true of the PDF logo too now,
  written into CLAUDE.md ("Damage photos are routes, not files"), and
  `tests/test_photo_serving.py` fails on any photo-field `.url` in a template
  or app module.
- **The media bucket's prefix split**: `tenants/logos/` and `email_branding/`
  are public *on purpose* — email `<img>` opened days later — and
  `repair_photos/` must not be. Re-widening that one policy statement would
  undo P8 silently and no test can see it. **In CLAUDE.md as of PR #248**; the
  policy edit itself is item 3b above.

## If the classifier comes back

Nothing was lost by waiting, and that is a property of the design rather than
luck: the stored asset is the tap, so the corpus can be re-exported at any
crop size a future model wants. Re-entry, in order:

1. Run `export_photo_dataset --stats-only` **first** and believe its balance
   line over anything written here, including this section. It refuses to
   flatter the count on purpose.
2. Read **§The pause** for why volume is not the constraint, and **P5** for
   the only source this business generates on its own. P5's spec is ready and
   its product case — a shop seeing the work it walks away from — stands
   without any ML.
3. The reason list ("crack too long", "in the sight line", …) is **Drake's to
   supply, not ours to invent**; it is the actual class vocabulary.
4. `--stats-only`'s line about no confirmed row carrying a machine suggestion
   is **permanent and by design** — the backlog was marked cold so P3.1 could
   score honestly. It is not evidence the suggester was never measured.

## The one lesson worth carrying to the next arc

**This arc was reopened three separate times by the same question, and never
once by a bug:** *what does the person on the other end actually get?* Asked
after P4a it produced P6; asked after P6.1 it produced P6.2; asked hours after
the deploy it produced P7. Written training-first, four sessions of capture
plumbing moved the marking rate to **1 photo out of 77**. The number moved to
**73 in about twenty minutes** — because a person sat down with a queue, on a
day when tapping had finally started paying that person's shop back.

The plumbing was not wrong and the sequence was. **Ask that question at spec
time**, not after a deploy, and expect the answer to reorder the plan.

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
| 2026-09-01 | **P7 added — the customer can see the photos and cannot keep them.** Asked, hours after the deploy, what a trucking company does when it wants the photos for its records. Audited all four surfaces: the public invoice page links each photo (right-click, one at a time, saved as `IMG_4686.jpg`), the portal lightbox has no download at all, and **the invoice PDF's `include_photos` flag is threaded through three signatures and read by none of them** — photos-in-PDF looks built and is not. Specced as a tokened ZIP mirroring `public_invoice_pdf`, plus per-job download in the portal, with the naming, storage-read and individual-vs-fleet traps written down. **Also found while specifying it: the media bucket is world-readable and filenames are the phone's originals** (`IMG_4686.jpg` returns 200 anonymously; a 16-name probe of our own bucket hit one live photo), so the invoice token protects the page and not the photos — recorded as its own piece of work, deliberately not folded into P7, and sequenced *after* it because closing the bucket removes today's only save path. |
| 2026-09-01 | **IT SHIPPED, and the arc's purpose is finally being served.** The deploy this document called its highest-value action for five days happened on 2026-08-31 23:46 UTC: prod runs `966a31da` off `main`, with `fb4f8b98` (P6.1+P6.2) verified *inside the deployed commit* by ancestry and `object-position:41% 61%` verified in the stylesheet production actually serves. `migrate` was the predicted no-op. **20 invoices now carry a job whose damage photo is framed on the break a technician tapped** (62 line items, 75 marked repairs, counted live). Census re-run: 78 crops, `repairable=73`, **`not_repairable=0`** — unchanged where it matters. **Drake's calls, asked directly:** P5 and P4b are **held as `TODO`**, neither built nor dropped — ask again, don't decide for him; and **The Glass Guy starting to enter jobs is *likely***, which would supply the negative class with no code at all, so §The pause's second way out is now live rather than a dead end. Also recorded: the `--stats-only` line about no machine suggestions on confirmed rows is permanent and by design (the backlog was marked cold on purpose), not evidence that P3.1 never ran. |
| 2026-09-01 | **Doc brought current after the merges.** P6.1 and P6.2 are on `main` (#236 = `fb4f8b98`; #234 closed as superseded), so the rows that named their branches, the START HERE checklist and the "what is left" line all said the arc had code to write when it does not. **The only open item that is not a decision is the deploy** — production has run `d88f70d5` since before P6, 23+ commits back, and the migration delta is **zero**, so it is code-only. Also recorded: UI_MAGIC **S17 (#233) moved the Tailwind source** to `assets/css/input.css`; that session correctly re-pointed `tests/test_photo_blind_focus.py` and preserved `.photo-blind-focus` in both the source and the committed `app.css`, so the three-copy drift guard still holds. |
| 2026-09-01 | **P7 executed — the photos are now keepable.** One control on the public invoice page saves every photo on that invoice as a ZIP through the same HMAC gate as `/pdf/`, and every job page — customer portal *and* shop — has the same button. Files arrive named `INV-1042_Unit-4521_2026-08-14_Before.jpg`, or `…_2019-Ford-F-150_…` for an individual, because the name is built from `get_vehicle_label()` and the word "Unit" cannot reach a retail customer's filename. **Drake's three calls, taken up front:** photos in the invoice PDF stay unbuilt and stay their own decision; the customer's own submitted photo *is* in the archive (it is theirs); the shop gets the same button, because the shop is who a customer phones asking for the photos. New shared module `services/photo_archive.py`, no migration; `_public_invoice_jobs` extracted so the page and the ZIP can never disagree about which jobs an invoice has, and `_job_access` extracted so the shop download cannot be laxer than the crop endpoint next to it. Bytes are read through storage — a test patches `FieldFile.url` to raise and the ZIP still builds — which is both correct today and the precondition for closing the bucket. A photo missing from storage is skipped and named in a `README.txt` inside the ZIP rather than silently dropped. 29 new tests; the 190 in the adjacent photo/CSP/icon/CSS suites re-run green. **The bucket is now the arc's only open piece of work that is not a decision.** |
| 2026-09-01 | **P8 added — the bucket is the arc's last piece of code, and it is smaller than it looked.** With P7 built, the exposure it uncovered was specced as its own session against production facts rather than left as a paragraph in P7's Notes. What the audit found: the photos are public because of **one bucket-policy statement** (`PublicReadMediaOnly`, `s3:GetObject` for `*` on `media/*`), object ACLs are **already blocked** (`BucketOwnerEnforced`, `BlockPublicAcls`), **static files are not in this bucket** so no CSS can break, and the sensitive prefix is **235 objects** against 2 shop logos. So the fix is to narrow one `Resource` line — keeping `tenants/logos/` and `email_branding/` public because email `<img>` tags are opened days later — and serve `repair_photos` through the app the way P7's ZIP already reads bytes. Recommendation recorded as **app-served over presigned**, because signed URLs expire and this repo has already paid for that once (`repair_completed.html:12` says why photos left that email). Three traps written down with line numbers: the invoice PDF still fetches the shop's logo by anonymous `urlretrieve` (`invoice_service.py:239`) — the last place the app fetches its own media over the network; `_absolute_media_url` would sign email logos if `AWS_S3_CUSTOM_DOMAIN` were dropped globally; and `img-src` is derived at runtime from `MEDIA_URL`, whose own docstring notes that getting it wrong fails photos on production only. **Sequenced after #243 deploys, not after it merges.** |
| 2026-09-01 | **The document is finished being written.** Added **§Closing the arc**: the honest scorecard (purpose 1 — the customer-visible close-up — is delivered and reaching customers, **20 invoices** framed on a tapped break and every unmarked photo aimed at the measured (41%, 61%); purpose 2 — the training set — is **not**, at `not_repairable=0` accruing 0/month), the arc's real cost (9 merged PRs, 5 service modules, 4 migrations, **230 tests**, one CI workflow), and a four-item checklist with an owner on each: merge #243, deploy `main`, do P8, and **ask Drake about P5/P4b** — where a written-down `DROPPED` closes the item just as well as building it. Also recorded what must **outlive** this file: (41,61) is measured rather than chosen, photo bytes are read through storage and never over HTTP (the invoice PDF's `urlretrieve` logo fetch is the last exception), and the bucket's prefix split is deliberate — none of which any test explains, so they belong in CLAUDE.md the day P8 lands. Two corrections to §0 while in here: the test inventory omitted `test_photo_closeup_visible.py` (41) and `test_photo_blind_focus.py` (6) entirely, so a session reading the primer would not have known to run the two suites guarding P6 and P6.1. **The lesson recorded for the next arc:** this one was reopened three times by the same question — *what does the person on the other end get?* — and never once by a bug; ask it at spec time. |
| 2026-09-06 | **P8 closed — the arc's code is finished.** #248 merged as `969a4035` and deployed 22:00 UTC (health 200). Verified from outside on invoice 79 with a token minted from the web process's key: page 200 with no S3 URL in it, photo route 200 `image/jpeg`, ZIP 200. Then the one bucket-policy edit at 22:04 UTC: `PublicReadMediaOnly` narrowed to `media/tenants/logos/*` + `media/email_branding/*`; anonymous damage photo → 403, logo → 200, app routes unchanged. Checklist items 3a/3b struck. **Found on the way:** the web process's `SECRET_KEY` is 50 chars and the EB-configured value is 53 — tokens minted through `run-cron.sh` do not validate on the site (recorded in §P8 Notes; latent today, a session of its own before cron ever emails a pay link). |
| 2026-09-06 | **P8's application half built — PR #248.** A damage photo is a route on every surface (shop, portal, public invoice), each behind the gate that surface already used for the P7 ZIP, streaming `field.open()` with a private, versioned cache header. Ten templates, the mark queue and the crop-save JSON stopped printing storage URLs; a new `{% load photo_tags %}` library carries the three URL builders; the invoice PDF reads its logo through storage and `urllib` left `invoice_service.py`. App-served was taken over presigned without asking — the spec's reasoning stood. 39 tests plus a source-scan guard, added to `scripts/test_guards.sh`. **The bucket-policy edit is deliberately not in the PR**: it goes after the deploy is confirmed, with the exact commands and rollback now in §P8 Notes. Rules the closing section said must outlive this document (bytes via storage; the prefix split) are in CLAUDE.md. |
| 2026-09-06 | **Deployed.** `main` reached prod at 19:30 UTC as `61273602`, carrying #243 (P7). Every "merged, not deployed" line above now says deployed; P8's gate is cleared and it is the next session. §Closing the arc item 2 is struck. No spec content changed. |
| 2026-09-02 | **Status refresh from the direction review.** #243 (P7) merged 2026-09-01 15:12 UTC as `f2506773`; every line that said "open, not merged" now says merged, not deployed (prod is still `966a31da`, which predates it). P5 and P4b are marked **PARKED** with the structural reason spelled out on their rows — zero negatives, accruing at zero — and Drake's hold stands: ask before touching, do not close them from this document. P8 stays the one open code item, waiting only on the deploy. §Closing the arc item 1 is struck. No spec content changed. |
