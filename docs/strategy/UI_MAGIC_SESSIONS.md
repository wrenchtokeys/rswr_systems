# UI/UX magic — living session doc

**Companion to** `docs/strategy/UI_MAGIC_PLAN.md` (the diagnosis and the design rules).
This file is the **work queue**: self-contained sessions, each written so a fresh Claude
session with no memory of this work can pick exactly one up and finish it.

**Status legend:** `TODO` · `IN PROGRESS` · `DONE` · `DROPPED`

| Phase | Session | Status |
|---|---|---|
| 1 | S1 · Kill the CDNs, self-host everything | **DONE** 2026-08-09 |
| 1 | S2 · Material, type-scale and motion tokens | **DONE** 2026-08-09 |
| 1 | S3 · `blue-*` → `brand-*` codemod + brand CSS in every shell | **DONE** 2026-08-09 |
| 1 | S4 · Tabular figures on money | **DONE** 2026-08-09 (partial — see S4 notes) |
| 2 | S5 · Owner dashboard: kill the green slab, give revenue meaning | **DONE** 2026-08-09 |
| 2 | S6 · Jobs page: 25 controls → 3 | **DONE** 2026-08-09 |
| 2 | S7 · Job/repair form: drop the green header and ALL-CAPS section tiles | TODO |
| 2 | S8 · Retire the second accent everywhere else (FAB, black pills) | TODO |
| 3 | S9 · Motion primitives: press feedback + enter/exit | TODO |
| 3 | S10 · View Transitions for list → detail continuity | TODO |
| 3 | S11 · Skeletons and optimistic status changes | TODO |
| 3 | S12 · Auth pages: one brand mention, full-height, no marketing nav | TODO |
| 3 | S13 · Icon language: Font Awesome solid → line-weight SVG sprite | TODO |
| 4 | S14 · Landing: real product imagery instead of the fake mock | TODO |
| 4 | S15 · Landing: trust bar rewrite | TODO |
| 4 | S16 · Landing: rhythm, dark section, sharper promise | TODO |
| — | S17 · Stop shipping the Tailwind source to production | TODO |

---

## How to run a session

1. Read `docs/strategy/UI_MAGIC_PLAN.md` Part 2 (the rules). Every session must obey them.
2. Pick **one** session below. Don't batch — each is sized to be verified independently.
3. Branch from `main`: `git checkout -b feat/ui-<session-id>-<slug>`.
4. Verify with the recipe in **Verification** below. Screenshots beat assertions here.
5. Update this file: flip the status, and write what you learned under the session's
   **Notes** heading. That's what makes it a living doc.

### Verification recipe (used for all of Phase 1)

```bash
# Scratch DB so a real dev DB is never touched
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development
export LOCAL_DATABASE_URL="sqlite:////tmp/ui-verify.sqlite3"
python manage.py migrate && python manage.py seed_plans && python manage.py setup_groups
# Seed a tenant (signup has a captcha — call the service directly)
python manage.py shell -c "
from apps.tenants.services.signup_service import create_tenant_with_owner
create_tenant_with_owner(business_name='Test Shop', email='ui@test.com',
                         password='UiTest2026!', first_name='Drake', last_name='D')"
./scripts/build_css.sh          # after ANY template/JS class change
python manage.py runserver 127.0.0.1:8021 --noreload
```

Then, before every commit:

```bash
# 1. No third-party asset hosts may appear in rendered HTML
curl -s http://127.0.0.1:8021/ | grep -E 'jsdelivr|cdnjs|fonts\.(googleapis|gstatic)' && echo FAIL

# 2. collectstatic must pass under the PRODUCTION static pipeline. Dev's plain
#    storage hides broken url() refs that 500 the whole site in prod.
#    production.py refuses SQLite, so use a settings shim:
cat > /tmp/manifest_check_settings.py <<'PY'
from rs_systems.settings.development import *
STATIC_ROOT = "/tmp/staticroot"
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "rs_systems.storage.ForgivingManifestStaticFilesStorage"}}
PY
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=manifest_check_settings python manage.py collectstatic --noinput

# 3. Smoke tests, then the full suite
python manage.py test tests.test_primary_contact tests.test_e2e_today tests.test_step5_nav
python manage.py test tests/ -v 1
```

**The suite has ~103 pre-existing failures. Compare, never count.** On SQLite the full
suite is 3507 tests / ~66 min and ends `FAILED (failures=70, errors=33)` — on a clean
`main` too (verified 2026-08-09; the two failure sets are byte-identical). They're mostly
DB-index introspection and SES-mock tests. So a green run is not the bar; **an unchanged
failure set** is:

```bash
# Extract the failing modules from your run, then replay just those on main.
grep -E "^(FAIL|ERROR): " yours.log | sed -E 's/^(FAIL|ERROR): [^ ]+ \((.*)\)$/\2/' \
  | sed 's/\.[^.]*$//' | sed 's/\.[^.]*$//' | sort -u > modules.txt
git worktree add /tmp/baseline main
# NOTE: run this under bash — zsh does not word-split unquoted $MODULES and you
# will get one bogus "module not found" test instead of the whole list.
bash -c 'cd /tmp/baseline && python manage.py test $(tr "\n" " " < modules.txt)'
# Then diff the two sorted "FAIL:/ERROR:" lists. Anything only in yours is a regression.
```

Replaying only the failing modules takes ~7 min instead of another full hour.

### Traps this work has already hit — don't repeat them

- **`{# … #}` is single-line only.** A multi-line `{# … #}` renders as *visible text at the
  top of every page*. Use `{% comment %}…{% endcomment %}`. Cost: one round of screenshots.
- **`collectstatic` collects the Tailwind source too.** `static/css/src/input.css` is
  collected alongside the built `app.css`, so a relative `url()` resolves differently from
  each location and manifest storage hard-fails. Keep `url()` out of `input.css`
  entirely — put font declarations inline in `head_assets.html` with `{% static %}`.
  (See S17 for the real fix.)
- **Never blanket-convert colour classes.** Blue is both the brand colour *and* the
  semantic "in progress / sent" status colour. See S3 notes.
- **Tailwind purges `@layer components` rules that no template uses yet.** New shared
  classes need a `safelist` entry in `tailwind.config.js` or they silently do nothing.
- **The dev server caches templates even with `--noreload`.** Restart it before concluding
  a template fix didn't work.

---

# Phase 1 — Foundation ✅ DONE

Shipped together on `feat/ui-phase1-foundation` (commit `0e5c1742`), 2026-08-09.

**Verification result:** 65 smoke tests pass; full suite 3507 tests with a failure set
**byte-identical to `main`** (70 failures / 33 errors, all pre-existing); `collectstatic`
passes under the production manifest storage; rendered HTML contains zero third-party
asset hosts; brand theming confirmed end-to-end against a violet test tenant across the
owner app, tech app and customer portal, with the platform login correctly staying blue.

## S1 · Kill the CDNs, self-host everything — DONE

Removed all three third-party asset hosts: Google Fonts, cdnjs (Font Awesome), jsDelivr
(flatpickr). Added `scripts/vendor_assets.sh` (idempotent, pinned, committed output —
same policy as `app.css` and `driver.iife.js`).

**Notes**
- Inter is now a **single variable woff2**, latin subset, 48 KB, covering weights 300–800 —
  smaller than the six static cuts the old Google Fonts URL requested.
- Font Awesome: only `fa-solid-900`, `fa-regular-400`, `fa-brands-400` are vendored
  (usage counts: 1285 / 13 / 43). `fa-v4compatibility` had to be vendored too — the CSS
  references it and manifest storage fails on any missing reference, even unused.
- `.ttf` fallbacks were stripped from the FA CSS (woff2 is universal since 2016). Saves
  ~645 KB of repo weight.
- flatpickr is now **pinned to 4.6.13**; the old URL was unpinned `npm/flatpickr` (i.e.
  whatever jsDelivr served that day — an unreviewed-code-in-production risk on its own).
- The font is `<link rel=preload>`ed. It's same-origin now, so it starts during HTML parse
  instead of after a DNS + TLS handshake — this is what fixes the visible hero font flash.

**Still open:** the Cloudflare Turnstile script on signup is a live third-party request.
That one is functional (captcha) and stays. Factor it into the CSP allowlist.

## S2 · Material, type-scale and motion tokens — DONE

Added to `static/css/src/input.css`: the four-rung material ladder
(`--surface-*`, `--shadow-raised/float/overlay`, `--hairline`), the seven-step type scale
(`.t-display` … `.t-caption`), `.num`, and motion tokens (`--ease-out`, `--dur-*`).

**Notes**
- `.card` and `.modal-panel` were migrated to the ladder immediately — they're the shared
  component layer, so it's one edit for app-wide depth. Radii went `xl` → `2xl`.
- `.surface-float` is new and currently **unused**; it's for dropdowns/popovers in S8.
- The `t-*` scale is **safelisted** so pages can adopt it one at a time. Nothing uses it
  yet — that's Phase 2's job, page by page, not a big-bang restyle.
- Motion tokens are defined but **deliberately not applied**. Applying them is S9/S10.

## S3 · `blue-*` → `brand-*` codemod + brand CSS in every shell — DONE

**This was the point of Phase 1.** `Tenant.brand_color` previously reskinned only the
customer portal, while the Pro plan sells *"Your logo & colors on everything."*

- 1320 `blue-*` → `brand-*` across 96 templates.
- `{% tenant_brand_css %}` added to `base_app.html` (owner + tech) and `base_auth.html`.
- Verified end-to-end by setting a tenant's `brand_color` to violet `#7c3aed`: the owner
  dashboard, jobs list, and customer portal all retheme; the platform login stays RS blue.

**Notes — read before touching colour again**
- **48 classes were deliberately reverted to literal `blue-*`.** Blue does double duty: it
  is the brand colour *and* the semantic "In Progress" / "Sent" / "Approved" status colour
  (see `core/templatetags/ui.py`). A red-branded shop would otherwise render a red
  "In Progress" badge next to a red "Denied" one. The revert rule was: any line whose
  condition is `queue_status ==`, `.status ==`, `role ==`, or `plan ==` keeps literal blue.
- **Five files were excluded on purpose** and keep literal blue: `landing.html`,
  `saas/pricing.html`, `saas/base_public.html`, `saas/terms_of_service.html`,
  `saas/privacy_policy.html`, plus `components/plan_card.html`. These are the *RS Systems*
  brand and the platform's own pricing — a shop's colour must never leak onto them.
- The platform admin console (`templates/admin/**`) was excluded for the same reason.
- Inline status badges should migrate to the existing `{% status_badge %}` tag (the real
  single source of truth) rather than hand-rolled conditionals. Good work for S8.

## S4 · Tabular figures on money — DONE (partial)

`font-variant-numeric: tabular-nums` on all `table` elements (fixes the misaligned money
column in the Jobs and Invoices tables) plus a `.num` utility applied to the owner
dashboard revenue and stat values.

**Notes / remaining**
- Prose keeps proportional figures on purpose — tabular figures read worse inline.
- `.num` still needs applying to non-table money outside the dashboard: invoice detail
  totals, customer statements, loyalty balances, the receive-payment screen. Fold this
  into whichever Phase 2 session touches those pages rather than doing a sweep.

---

# Phase 2 — The daily surfaces

Goal: the three screens a shop owner and tech actually live in. Obey R1 (one accent),
R2 (materials), R5 (stage complexity), R6 (numbers with meaning).

## S5 · Owner dashboard: kill the green slab, give revenue meaning — DONE

Branch `feat/ui-s5-dashboard-revenue`. The green gradient slab is gone; the revenue hero
is a `.card` with a trend, a sparkline and a period toggle. Stat tiles moved onto the
material ladder, and the four pastel icon tints are now neutral.

**Notes**

- **The delta compares the same elapsed days**, not this-month-so-far against all of last
  month. Otherwise every 1st of the month reports "revenue down 95%" — technically true,
  useless, and it trains the owner to ignore the number. `_revenue_window()` clamps the
  previous window so it can never spill into the current month.
- **A zero baseline shows no percentage at all**, rather than a fabricated `+100%` from a
  division by zero. Absent beats invented.
- Revenue trend lives in its own `_get_revenue_summary()`, *not* in
  `_get_billing_context()` — the latter's fallback dict is asserted as an **exact key set**
  by `tests/bug_fixes/test_code001_exception_logging.py`, so adding keys there breaks it.
  The legacy `total_revenue`/`repair_revenue` keys are untouched for back-compat.
- `_get_revenue_summary()` never raises; on error it returns the empty shape and logs. The
  dashboard must render even if revenue can't be computed.
- Sparkline is two bucketed aggregate queries (`TruncDate` + `Sum`), never a row walk. It
  returns nothing when the window has no revenue, so the card omits the chart instead of
  drawing a flat line that implies zero is a trend. The polygon closes to the baseline
  (`0,30 … 100,30`) so the fill reads as an area, not a blob.
- The period toggle is a plain GET `<select>` with `onchange` submit — works without JS,
  and the chosen period survives a refresh or a shared link.
- **`django.contrib.humanize` was added to `base.py`** for `intcomma`. A four-figure
  revenue number rendering as `$3700.00` looks unfinished; money now formats as `$3,700.00`.
- Deviation from the plan, deliberate: the plan said "green stays only on the money
  figure". In practice a large green number still read as decoration, so the **figure is
  neutral and the delta chip carries green/red**. Money semantics land on the thing that
  actually has a direction.
- New tests: `tests/test_dashboard_revenue.py` (15) covering the elapsed-days comparison,
  month-length clamping, zero-baseline guard, tenant scoping, COMPLETED-only totals,
  period validation, and the render path.
- Also added `tests/test_template_comment_syntax.py` after hitting the multi-line `{# #}`
  bug a **second** time. It renders explanatory notes as visible text at the top of every
  page and fails silently — no exception, no 500, nothing red. Now it fails a test.

## S6 · Jobs page: 25 controls → 3 — DONE

Branch `feat/ui-s6-jobs-controls` (stacked on S5). Before the first job row there are
now exactly four things: a segmented type control, a status dropdown, a search box, and
a "Filters" button with an active-count badge. The 4 stat tiles became one quiet summary
line under the H1 (each count is a link that applies the filter). Row actions collapsed
to a kebab; the FAB is gone from this page.

**Notes**

- **The FAB wasn't just a duplicate "New Job"** — it carried Multi-Break, Receive
  Payment and New Customer, and `tests/test_unified_job_list.py::FabReceivePaymentTests`
  pins Receive Payment to this page for managers. Those actions moved into a `⋯` menu
  next to the primary button (same `is_admin or technician.is_manager` gate), so the
  tests pass unchanged. Export CSV folded into the same menu.
- **Deliberate deviation:** the session said "active pills → `brand-600`". The pills
  became a segmented control with the neutral white-thumb treatment instead (track
  `bg-gray-100`, active `bg-white shadow-sm`), which removes the black accent without
  spending colour on a control that doesn't need it. The brand colour appears once, on
  the Filters count badge.
- **Dropdown menus are positioned `fixed` via JS**, not `absolute` — the table wrapper
  is `overflow-hidden` for its rounded corners and would clip an absolute menu. Menus
  flip upward near the viewport bottom and close on scroll/click-out/Escape.
- **Measure the button *before* unhiding the menu.** Removing `hidden` first makes the
  menu a static block for one frame, which widens its flex container and shifts the
  button ~150px — the rect you then read is stale and the menu opens misaligned. Caught
  only in the browser; no test would ever see this.
- Menus inside table cells inherit the cell's `text-align: right` — the shared
  `.dropdown-menu` carries `text-left`.
- Kebab reveal is `opacity-0 group-hover:opacity-100` **plus** `tr:focus-within` and a
  `.menu-open` state, so it stays keyboard-reachable. Mobile is unaffected: cards are
  whole-card links there (and the mobile table doesn't render). "New Job" is now visible
  on mobile in the header since the FAB no longer provides it.
- Search is a plain GET form; every other live filter rides along as hidden inputs so it
  works without JS. Sort + per-page moved into the Filters panel as ordinary form
  fields; the count line (`1–20 of 43`) stays above the table.
- `active_filter_count` (panel filters only, not the visible controls) is computed in
  the view. First adopter of `.surface-float` from S2.
- Leftover for S8: the type badges (emerald/purple), the REQUESTED row's amber status
  text, and warranty/goodwill chips are still hand-coloured; the bulk toolbar is still
  `bg-gray-900` (kept — it's a fixed mode bar, not a pill).

## S7 · Job/repair form: drop the green header and ALL-CAPS section tiles

**Files:** `templates/technician_portal/repair_form.html`, `replacement_form.html`,
`static/css/components/form-fields.css`

- The green gradient page header and green rounded-square section icons are the app's
  second accent. Remove both — quiet section headings on the `t-*` scale.
- "Document windshield repair with professional-grade tracking" is filler; cut it.
- Group fields with whitespace and hairlines, not tinted boxes.

**Care:** this form has autosave (`static/js/form_autosave.js`) and multi-break logic
(`static/js/multi_break.js`) keyed to element IDs. Change classes, not IDs.

## S8 · Retire the second accent everywhere else

**Known leftovers after S5:** the dashboard's floating `+` FAB is still green, and the
`Recent Activity` rows still use hand-rolled status badge conditionals rather than
`{% status_badge %}`.

Sweep for the remaining green/black accents outside S5–S7: the global FAB, any remaining
`bg-gray-900` pills, the four-tint icon system. Migrate hand-rolled status badges to
`{% status_badge %}`. Adopt `.surface-float` for dropdown menus.

---

# Phase 3 — Feel

## S9 · Motion primitives: press feedback + enter/exit

Apply the S2 tokens. Only two things in this session:
- `active:scale-[0.98]` + `transition` on `.btn` and every actionable row/chip. This one
  line changes how the whole app feels more than any redesign.
- Enter/exit on dropdowns, modals and toasts: 220 ms, `--ease-out`, opacity + 4px translate.

**Never animate `all`** — name the properties. Wrap everything in
`@media (prefers-reduced-motion: reduce)`.

## S10 · View Transitions for list → detail continuity

`@view-transition { navigation: auto; }` plus `view-transition-name` on the row and the
detail header. Works with plain Django full-page loads and degrades silently in
unsupporting browsers. Highest magic-per-line in the whole plan.

**Care:** verify it doesn't fight the flash-message banner or the subscription banner.

## S11 · Skeletons and optimistic status changes

Skeletons shaped like the final layout (not spinners) for the jobs and invoices lists.
Optimistic status transitions that roll back visibly on failure. One restrained success
moment when an invoice is paid — confirmation, not confetti (R4 + the Part 4 guardrail:
never animate money).

## S12 · Auth pages: one brand mention, full-height, no marketing nav

`/login/` currently says "RS Systems" three times (marketing nav, brand panel, card
heading) and the split panel stops mid-viewport leaving dead white space.
Drop the marketing nav from auth pages, make the split full-height, say the brand once.

## S13 · Icon language: Font Awesome solid → line-weight SVG sprite

1,281 FA **solid** usages. Solid weights read dated; consistent-stroke line icons are most
of what people mean by "Apple-like".

Do this **last in Phase 3**, and incrementally: add an `{% icon 'name' %}` tag backed by an
inlined SVG sprite, migrate surface by surface, and only delete the vendored FA files when
the last `<i class="fa` is gone. S1 already removed the *CDN* risk, so there is no urgency
here — this is purely aesthetic, which is exactly why it must not be rushed into a
1,281-site find-and-replace.

---

# Phase 4 — The front door

`templates/landing.html`. Platform-branded — do **not** introduce `brand-*` tokens here
(see S3 notes).

## S14 · Real product imagery instead of the fake mock

`landing.html:120-190` is hand-built HTML imitating the dashboard inside fake browser
chrome — and it has already drifted from reality (the mock shows a *blue* revenue banner;
the real dashboard is green). Replace with a real screenshot, or better, a 4-frame
scroll-scrubbed sequence: chip photo → job created → invoice sent → paid.

Run this **after S5**, so the shot captures the redesigned dashboard.

## S15 · Trust bar rewrite

`500+ Jobs Tracked · $50K+ Invoiced · 100% Mobile Friendly · 24/7 Access Anywhere` — two
are unverifiable self-reported numbers, two aren't stats at all. A skeptical shop owner
reads the whole bar as filler.

Replace with checkable claims: payments processed by Stripe · export your data anytime ·
built and run by a working glass shop in Arkansas · no contract, cancel in one click.
Keep real usage numbers only if accurate and attributed.

Also: the only testimonial is from the founder. Until there's a second shop, label it
honestly as a founder's note — honest beats hollow.

## S16 · Rhythm, dark section, sharper promise

Six identical centred-text stacked sections today. Alternate light/dark ground, add one
asymmetric split and one full-bleed moment. Sharpen "Manage your glass shop without the
headache" into the specific thing nobody else does.

**Delete the `[data-reveal]` scroll fade** (`landing.html:43`, and the observer at the
bottom of the file). At real scroll speed it fires *after* you've passed the section — the
pricing cards render as a blank void, then pop in. It is the page's only motion and it is
making the page worse.

---

# Housekeeping

## S17 · Stop shipping the Tailwind source to production

`static/css/src/input.css` is collected and served publicly, and its presence forced the
`@font-face` workaround in S1/S2. Move the build source out of the served tree
(e.g. `assets/css/input.css`), update `scripts/build_css.sh`, `CLAUDE.md`, and
`docs/development/UI_DESIGN_GUIDE.md`, then move the `@font-face` back into the stylesheet
where it belongs.

Small, self-contained, and it removes a footgun that will otherwise bite the next person.

## Follow-on once Phase 1 has soaked

Add a strict **Content-Security-Policy**. S1 removed every third-party asset host, so the
allowlist is now small: self + Stripe + Cloudflare Turnstile. This was impossible before
and is the main security dividend of Phase 1 — don't leave it on the table.
