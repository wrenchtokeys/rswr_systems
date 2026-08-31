# UI/UX magic — living session doc

**Companion to** `docs/strategy/UI_MAGIC_PLAN.md` (the diagnosis and the design rules).
This file is the **work queue**: self-contained sessions, each written so a fresh Claude
session with no memory of this work can pick exactly one up and finish it.

**Status legend:** `TODO` · `IN PROGRESS` · `DONE` · `DROPPED`

> **Heads-up (2026-08-25): the schedule page is being rebuilt underneath this
> arc.** `FIELD_OPS_SESSIONS.md` sessions **S9–S14** replace
> `templates/technician_portal/schedule.html` with an ordered day list, add a
> quick-add modal, and change `includes/schedule_row.html` (new data
> attributes, a time control on booked rows). If a session here touches the
> schedule page, the row partial, or `base_app.html`'s `datetime-local`
> bootstrap, check that queue first — **S9 deletes that bootstrap outright.**

| Phase | Session | Status |
|---|---|---|
| 1 | S1 · Kill the CDNs, self-host everything | **DONE** 2026-08-09 |
| 1 | S2 · Material, type-scale and motion tokens | **DONE** 2026-08-09 |
| 1 | S3 · `blue-*` → `brand-*` codemod + brand CSS in every shell | **DONE** 2026-08-09 |
| 1 | S4 · Tabular figures on money | **DONE** 2026-08-09 (partial — see S4 notes) |
| 2 | S5 · Owner dashboard: kill the green slab, give revenue meaning | **DONE** 2026-08-09 |
| 2 | S6 · Jobs page: 25 controls → 3 | **DONE** 2026-08-09 |
| 2 | S7 · Job/repair form: drop the green header and ALL-CAPS section tiles | **DONE** 2026-08-10 |
| 2 | S8 · Retire the second accent everywhere else (FAB, black pills) | **DONE** 2026-08-10 |
| 3 | S9 · Motion primitives: press feedback + enter/exit | **DONE** 2026-08-10 |
| 3 | S10 · View Transitions for list → detail continuity | **DONE** 2026-08-11 |
| 3 | S11 · Skeletons and optimistic status changes | **DONE** 2026-08-25 (PR #210) — merged, **not yet on prod** |
| 3 | S12 · Auth pages: one brand mention, full-height, no marketing nav | **DONE** 2026-08-25 (PR #209) — merged, **not yet on prod** |
| 3 | S13 · Icon language: Font Awesome solid → line-weight SVG sprite | TODO — debt now **1,303** and rising |
| 4 | S14 · Landing: real product imagery instead of the fake mock | TODO |
| 4 | S15 · Landing: trust bar rewrite | TODO |
| 4 | S16 · Landing: rhythm, dark section, sharper promise | TODO — **the `[data-reveal]` half split out and DONE 2026-08-27 (S16a, PR #235, merged 2026-08-31)** |
| — | S17 · Stop shipping the Tailwind source to production | **DONE** 2026-08-27, merged 2026-08-31 (PR #233) |
| Out | Email + notification chassis, replacement lifecycle | **DONE** 2026-08-24 (PR #200) |
| Out | Invoice email onto the chassis | **DONE** 2026-08-24 (PR #202, merged 12:15 CDT, deployed 22:48 CDT) |
| Out | In-app surfaces: notification bell + notification history | **DONE** 2026-08-25 (PR #206) |

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
- ~~**`collectstatic` collects the Tailwind source too.**~~ **Fixed in S17.** The source
  is now `assets/css/input.css`, outside `STATICFILES_DIRS`, so `url()` resolves against
  exactly one directory — the built `static/css/app.css` — and `../fonts/…` is correct.
  The rule that replaces it: **never put the Tailwind source back under `static/`.**
  `tests/test_css_pipeline.py` fails if you do.
- **Never blanket-convert colour classes.** Blue is both the brand colour *and* the
  semantic "in progress / sent" status colour. See S3 notes.
- **Tailwind purges `@layer components` rules that no template uses yet.** New shared
  classes need a `safelist` entry in `tailwind.config.js` or they silently do nothing.
- **The dev server caches templates even with `--noreload`.** Restart it before concluding
  a template fix didn't work. Chrome caches the served `app.css` just as stubbornly —
  hard-reload (`cmd+shift+r`) before concluding a CSS change didn't land. (S9)
- **`.hidden` is not an "is hidden" hook.** `hidden md:flex` is idiomatic Tailwind, so a
  descendant selector like `.hidden .panel` matches at every breakpoint where the parent
  is visibly *shown*. Scope to your own root class instead. (S9) (Hit again in S8 — cost a round of screenshots.)
- **A hidden browser tab runs no view transitions at all.** Chrome only transitions
  documents it actually paints, so in a background/automation tab
  `document.startViewTransition()` rejects with "invalid state", `pagereveal` never fires,
  and a cross-document transition reports `pageswap.viewTransition === null`. Everything
  looks healthy and nothing animates. Verify motion in a rendering browser. (S10)
- **`@view-transition` only counts when it is inline in the document.** From an external
  stylesheet Chrome parses it, exposes it in the CSSOM, and ignores it. It lives in
  `head_assets.html`; moving it to `input.css` silently disables every transition. (S10)
- **zsh does not word-split unquoted `$VAR`.** A `for f in $FILES` codemod loop runs once
  with every filename joined into one string, modifies nothing, and prints a log that
  looks like it worked. Run codemod loops under `bash -c` or `bash <<'EOF'`. (S8)
- **Swapping a page's base template silently deletes whatever that base provided.**
  `saas/base_public.html`'s footer was the only route to Terms and Privacy from the login
  funnel, and its nav height was baked into every `min-h-[calc(100vh-4rem)]` below it.
  Diff the *rendered* HTML before and after a base swap, not the template. (S12)
- **Both breakpoint twins are in the DOM at every width.** These lists render the
  phone card *and* the desktop row for every record; the card comes first, and on a
  desktop viewport it is `display: none`. So `document.querySelector('.my-state')`
  hands you the invisible one, where `getAnimations()` is empty and computed styles
  are frozen at the first keyframe — a perfect description of a broken feature that
  is in fact working one element later. Scope the selector to the twin you can see. (S11)
- **A tracing that keeps its colours is not a skeleton.** Blanking a row's text but
  leaving its status pill blue and its row tint yellow reads as a half-real list —
  and that colour is from the list being *left*, which after a status filter is the
  exact thing about to change. (S11)
- **An in-page anchor defeats every scroll-triggered effect below it.** An
  IntersectionObserver reveal assumes the viewport arrives at a section by travelling
  there. `href="#pricing"` teleports it: the observer fires on the destination in the same
  frame it becomes visible, so the fade runs *after* you are already looking at the
  section, and every block the jump flew over never intersects at all. The landing nav had
  two such anchors pointed straight at the two sections the reveal hid. Before adding
  scroll-driven anything, grep the page for `href="#`. (S16a)
- **A guard that has never been red is a guard nobody has checked.** Stash the change,
  run the new test against the parent commit, confirm it fails, pop. Three of
  `test_landing_visibility.py`'s four tests fail on `main` — that is the evidence the
  assertions match the defect, and it costs one `git stash`. (S16a, and the same lesson
  S17's `@font-face\s*\{` fix taught from the other direction.)
- **A page can be full of `brand-*` classes and still leak RS blue.** Component CSS under
  `static/css/components/` and inline `<style>` blocks use raw hex, load *after* `app.css`,
  and win. Two files were overriding the shared `.btn-primary` this way (S7, S8). Grep for
  `#2563eb|#3b82f6|#eff6ff|#dbeafe` before calling a surface themed.

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
- Motion tokens were defined but **deliberately not applied** here. S9 applied them
  (press feedback + enter/exit); continuity is still S10.

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
- **Addendum (S7 branch, 2026-08-10):** colors alone weren't the whole promise —
  `base_app.html` still hard-coded the RS mark + "RS Systems" wordmark, so owners and
  techs never saw their logo (the customer portal already showed it). The navbar now
  renders `request.tenant.logo` + tenant name with the RS mark as fallback, same
  pattern as `base_customer.html`.
- **Addendum 2 (2026-08-10):** custom branding is now actually plan-gated.
  `Tenant.branding_enabled` (platform owner, pro/enterprise, or a plan whose
  `custom_branding` feature flag is true — the flag existed in `seed_plans` and the
  pricing table since forever but nothing enforced it) gates: `{% tenant_brand_css %}`,
  the navbar logo/name in both shells, email colors+logo
  (`get_tenant_context` / `send_branded_email`), and invoice PDF colors+logo.
  Shop *identity* (name, contact, From/Reply-To) applies on every plan — only the
  visual theming is gated. Settings shows an upgrade note; picks are saved either
  way and apply on upgrade. Logos also render `h-10 w-auto object-contain` now
  instead of a 32px square crop that mangled wide logos.

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

## S7 · Job/repair form: drop the green header and ALL-CAPS section tiles — DONE

Branch `feat/ui-s7-repair-form`. The green gradient header, the green icon squares,
the tinted section boxes and the ALL-CAPS titles are gone from the full repair form;
the multi-break form and the quick job form lost their green (and purple) accents too.

**Notes**

- **The session's file list was stale.** `technician_portal/replacement_form.html`
  doesn't exist — replacements go through the unified quick job form
  (`job_form.html`). The real surfaces were `repair_form.html`,
  `multi_break_repair_form.html`, `job_form.html` and
  `static/css/components/form-fields.css` (loaded *only* by `repair_form.html`).
- **`form-fields.css` was overriding the shared `.btn-primary` with a green
  gradient** — it loads after `app.css`, so the whole repair form's primary button
  ignored the brand. The local button rules are deleted, not restyled; a comment in
  the file now warns against re-adding them. Same lesson as the autosave styles:
  app.css is the single source of truth for shared components.
- Plain CSS files can use the brand palette directly:
  `rgb(var(--brand-500))` / `rgb(var(--brand-500) / 0.1)` — the channels are
  space-separated RGB precisely so alpha composition works outside Tailwind.
- Section grouping is now whitespace + `.form-section + .form-section` hairlines
  (adjacent-sibling, so no `:first-child` edge cases with the form's hidden inputs).
- **Money greens were kept on purpose**: the multi-break "Total Cost" figures stay
  green (green means money), and the success modal keeps a green *check icon* — but
  its green header slab became a quiet white header (green is not a surface).
- The multi-break Add Break button and the success modal's "View Batch Details"
  demoted to outlined secondary — each view keeps exactly one solid brand action.
- The manager-only Custom Price box in the break modal was a *purple* tinted box
  with an ALL-CAPS purple title — a third accent. Now neutral, hairline-separated.
- Element IDs untouched throughout (autosave + `multi_break.js` + `repair_form.js`
  are keyed to them); classes only. Verified in-browser against the violet tenant:
  repair form, multi-break form + Add Break modal, quick job form all retheme.
- Same branch, related fix: `base_app.html` now renders `request.tenant.logo` +
  tenant name in the navbar (see S3 notes addendum).

**Leftovers for S8:** `technician_portal/dashboard.html:40` still has a green
gradient header; `job_form.html` keeps its teal "picked individual" state; the
`icon-field-helper.helper-success` green in form-fields.css is semantic and stays.

## S8 · Retire the second accent everywhere else — DONE

Branch `feat/ui-s8-second-accent`. Green (plus purple, orange, teal, indigo, sky and
black) stop being action and surface colours app-wide. ~40 templates, 2 CSS files.

**Notes**

- **The session's one-line scope was badly under-sized.** Green wasn't a leftover
  accent — it was the *de-facto primary action colour* of the whole technician portal
  and half the owner app: 67 solid `bg-green-*` surfaces, 46 green focus rings, plus
  purple/orange/indigo/teal/sky doing the same job on other pages. The rule applied was
  the one already in `CLAUDE.md`: **green means money (paid/collected/completed) and is
  not a surface, header, or button colour.**
- **What deliberately stayed green** — success toasts (`warranty_policies`,
  `viscosity_rules`, `manager_settings.js`), the "Copied!" button flashes, the
  COMPLETED status dot, money figures, and the plan-usage gauge's red/amber/green
  *thresholds* (a genuine health ramp). Below the threshold that same bar is now brand:
  it isn't reporting anything, so it shouldn't spend a colour.
- **Trial/expiry banners stay orange.** They're a warning state, not decoration.
- **The technician dashboard was the worst surface in the app** and got the most work:
  a green gradient header, five pastel gradient stat tiles (orange/amber/brand/green/
  purple), three stacked solid colour slabs (red "Customer Requests", yellow
  "Notifications", orange "In Progress"), a green "Ready to Start" panel and orange
  Continue buttons. All neutral now, on the S5 stat-tile idiom, with status colour
  coming only from `{% status_badge %}`.
- **Orange was being used for IN_PROGRESS** on that dashboard while `ui.py` says blue,
  so the same job read as a different colour on the dashboard, the jobs list and the
  detail page. All three now come from the shared tag.
- **`{% status_badge %}` migration**: owner dashboard Recent Activity, tech dashboard
  queue, `archived_repairs`, `reassign_to_self`, `unit_details`, `repair_detail`,
  `customer_portal/repair_detail`. The tag takes `label=` — that's how the tech queue
  keeps "Ready" and the customer portal keeps "Submitted — Awaiting Technician" while
  still drawing colour from the single source of truth.
- **Where a row showed status three times** (tinted icon tile + tinted dot + badge),
  the tile and dot became neutral. The badge carries it once.
- **The FAB was seven hand-picked hues** (green/teal/amber/violet/blue/cyan/purple) —
  a colour key with nothing to decode. One neutral circle now; the main button is
  `rgb(var(--brand-600))` so it follows `Tenant.brand_color`. Its open state was red,
  which read as "destructive" for a button that only closes a menu — now brand-700.
- **Black pills → segmented controls** (S6's pattern: `bg-gray-100` track, active
  `bg-white shadow-sm`) on `customer_portal/services`, `technician_portal/customer_list`
  and `owner_invoices`. This also removed the sky/teal Fleet-vs-Individual pills.
- **Two more brand leaks found and fixed, same class as S7's `form-fields.css`:**
  `static/css/components/customer-repair-request.css` **redefined `.btn-primary`** with a
  hardcoded RS-blue gradient and loads after `app.css`, so every button in the
  *customer's request flow* ignored the shop's brand. Deleted, not restyled, with a
  warning comment. `profile_creation.html` hardcoded `#2563eb`/`#eff6ff` for the
  selected radio card, so a violet shop got a blue selection. Both now use
  `rgb(var(--brand-N))`. **Grep for raw hex before assuming a page is themed** —
  `grep -rn '#2563eb\|#3b82f6\|#eff6ff\|#dbeafe' templates/ static/css/components`.
- Left as known raw-hex leaks (out of scope, no `--brand-*` in those documents):
  `templates/billing/public_*.html` (standalone public pay pages) and
  `templates/emails/customer_invitation.html`.
- `.surface-float` adopted by the two remaining absolute dropdowns (`base_app.html`
  account menu, `repair_detail` more-actions).
- **Restart the dev server before believing a template fix failed.** Cost a full round
  of screenshots this session — the same trap already listed at the top of this file.
- **`for f in $FILES` does not word-split in zsh.** The first codemod silently ran on a
  single newline-joined "filename", modified nothing, and printed a plausible-looking
  log. Run codemod loops under `bash -c` (same note as the baseline-replay recipe).

**Leftovers:** `templates/saas/billing.html:14` keeps its purple→indigo "Platform Owner"
gradient — that banner only ever renders for the platform-owner tenant, so it's an
RS Systems surface, not a shop's. The Fleet/Individual and Repair/Replacement chips keep
their two-value hues (`service_type_chip` in `ui.py`) — that's a taxonomy, not an accent.

---

# Phase 3 — Feel

## S9 · Motion primitives: press feedback + enter/exit — DONE

Branch `feat/ui-s9-motion`. The S2 motion tokens are now applied. Every control dips
2% while held; every modal and menu fades and rises in — **and out**. Two CSS files,
one 6-line JS change, and a class on ~130 template elements.

**Notes**

- **Press feedback uses the independent `scale` property, not `transform`.** The plan
  said `active:scale-[0.98]`, which is Tailwind's transform-based scale — it would have
  silently clobbered the FAB's rotate-on-open and the portal drawer's translate. `scale`
  composes with an existing transform; `transform` replaces it.
- **`scale` is declared only in `:active`, never at rest.** A resting `scale: 1` is a
  non-`none` value, which makes the element a containing block for `position: fixed`
  descendants — i.e. every dropdown or modal that happens to live inside a button would
  reposition. Transitioning from `none` interpolates as 1, so nothing is lost.
- **Coverage without a 1,300-site codemod:** the base-layer rule takes `<button>`,
  `[role=button]`, `<summary>` and submit/button inputs, and `.btn` takes every
  `<a class="btn-primary">`. That leaves anchors styled as buttons with raw utilities
  (S6/S8 converted the surfaces they touched; the rest is A1's job) — 112 of those got
  an explicit `.press`, chosen by a heuristic: padding + rounded + an unprefixed
  background. `hover:bg-gray-50` deliberately does not count, or every list row in the
  app would have been treated as a button.
- **The press rules had to out-rank a utility class, and that has two knock-ons.**
  `transition-colors` / `transition-all` are all over these templates, they live in the
  utilities layer (which wins ties against base *and* components), and they set
  `transition-property` without `scale` — so a plain `button { transition: scale }` rule
  leaves the press dipping with **no easing at all**, which reads worse than no press
  feedback. Hence `:not(.no-press)` and the doubled `.press.press`: specificity, not
  logic. And because those rules *replace* the utility's property list wholesale, the
  list has to carry the element's hover properties too — that's `--transition-control`
  (colour, background, border, shadow, transform, scale), not a bare `scale`.
- **`@apply btn` copies declarations; it does not add the `btn` class.** A `.btn.btn`
  rule therefore never matches `<a class="btn-primary">`. Each variant is listed
  explicitly in the doubled-specificity rule. Caught only because a browser check showed
  `.btn-primary` computing `transition: all 0s`.
- **`.press-card` (0.5%) for whole-card links.** 2% on a full-width card doesn't read as
  feedback, it reads as a lurch. The codemod told cards from buttons by all-sides
  padding (`p-4`/`p-5`) — buttons in this codebase always use `px-`/`py-`.
- **Enter/exit is pure CSS**: `@starting-style` + `transition-behavior: allow-discrete`,
  keyed off the `.hidden` class. This is the whole reason it covers the app: modals here
  are toggled from `ui.js`, from page-local `<script>` blocks, and from inline `onclick`
  attributes, and a JS implementation would have had to convert all three. It also gets
  the **exit** animation, which `classList.add('hidden')` can never do on its own.
  Browsers without `@starting-style` (pre-Chrome 117 / Safari 17.5 / Firefox 129) show
  and hide instantly — exactly today's behaviour.
- **`.motion-fade` (root) + `.motion-rise` (panel), applied by codemod to 24 hand-rolled
  modals.** The root only fades: a 4px rise on a full-bleed backdrop slides a sliver of
  page in under it. `.modal-overlay`/`.modal-panel`/`.dropdown-menu`/`[data-dropdown-menu]`
  get it automatically. `.surface-float` deliberately does **not** — it's a *material*
  class, and a static element wearing it would fade in on every page load. Motion is
  opted into by behaviour, not inherited from depth.
- **The multi-break Add Break and success modals toggle `.active`, not `.hidden`** (a
  page-local `.modal` idiom that predates the shared skeleton). They carry
  `.motion-fade`/`.motion-rise` for the transitions and `@starting-style`, plus two
  local rules stating the hidden state in that page's own vocabulary. The same
  `.modal` CSS in `convert_to_batch_form.html` is dead — no modal markup uses it.
- **`pointer-events: none` on the exit state is not optional.** `display: none` is now
  deferred to the end of the transition, so without it a closing overlay eats the next
  220ms of clicks — the fastest way to make "polish" feel broken.
- `UI.confirm()` is the one dialog CSS can't animate out: it's removed from the DOM
  rather than hidden. It now resolves its promise *first* (the caller usually submits a
  form — the exit must never delay that), then fades and removes.
- **`transition-all duration-300` on the toast and the autosave chip is gone.** Both now
  name `opacity, translate` at `--dur-base`; `transition-all` was animating width,
  colour and shadow along with the two properties that actually move.
- `--transition: all 0.3s ease` — the anti-pattern named in UI_MAGIC_PLAN §7 — is dead in
  both `input.css` and `style.css`. It's now a named-property list, which fixes all seven
  legacy `transition: var(--transition)` uses in the portal's stylesheet at once.
- Everything is inside `@media (prefers-reduced-motion: no-preference)`, and the resting
  states of the toast/autosave chip are deliberately *outside* it, so under reduced
  motion they still appear — instantly — instead of being stuck at `opacity: 0`.

**Traps hit this session**

- **`.hidden .thing` does not mean "inside a hidden parent".** `hidden md:flex` is
  idiomatic Tailwind, so a large part of the navbar carries a permanent `hidden` class
  that only stops applying at a breakpoint. The first version pinned the account menu at
  `opacity: 0` forever. Ancestor selectors are now scoped to `.motion-fade.hidden` /
  `.modal-overlay.hidden`, which are our own classes on a modal root.
- **The dev server's `app.css` is aggressively cached by Chrome**, and hot-swapping the
  `<link>` to verify makes the *enter* animation silently not run (`@starting-style`
  needs the rule present when the element first renders). Two false negatives came from
  this. Hard-reload (`cmd+shift+r`) before concluding the motion doesn't work, and
  measure with `element.getAnimations()` rather than by eye.
- **`getComputedStyle` sampling through the browser-automation bridge went stale** after
  one long-running script timed out — it reported a modal as `display: flex, opacity: 0`
  in every state, including states the screenshot plainly contradicted. When the numbers
  stop making sense, take a picture: two screenshots ~200ms apart showed the fade
  perfectly.

**Verified:** account dropdown, the JS-positioned `fixed` kebab menu on the jobs page
(opens at the measured rect, closes click-through), a hand-rolled `.motion-fade` modal,
and `UI.confirm()` — all sampled mid-transition via `getComputedStyle`/`getAnimations`.
`collectstatic` passes under production manifest storage. 111 smoke tests pass. Full
suite: 3618 tests, `failures=71, errors=34`; replaying those 40 modules on clean `main`
gives the same `failures=71, errors=34` and the two sorted failure lists diff to
**zero lines in either direction**.

**Leftover:** `customer_portal/notification_preferences.html` toggles a modal with
`style.display` rather than `.hidden`, so it stays instant — convert it to `.hidden`
when that page is next touched. The customer portal's own component CSS still has a few
`transform: translateY(-2px)` hover lifts of its own (`customer-repair-request.css`);
they're harmless but should collapse into these primitives eventually.

## S10 · View Transitions for list → detail continuity — DONE

Branch `feat/ui-s10-view-transitions`. Navigations cross-fade instead of blinking, the
navbar holds still while they do, and the row you clicked flies into the detail page's
title — then flies back into the row when you return. One inline line, ~35 lines of CSS,
one small script, `data-vt-*` on three lists and `.vt-hero` on four detail titles.

**Notes**

- **The opt-in must be inline in the document.** `@view-transition { navigation: auto; }`
  lives in the `<style>` block in `templates/includes/head_assets.html`, *not* in
  `input.css`. Chrome 151 ignores the opt-in when it comes from an external stylesheet —
  even one that is render-blocking, fully loaded, applying its other rules, and present in
  `document.styleSheets` as a real `CSSViewTransitionRule`. Reduced to two static files to
  be sure: identical pages transition with an inline `<style>` and do nothing with a
  `<link>`. There is no error, no console warning, no visual clue — navigation just goes
  back to a hard swap. `tests/test_view_transitions.py` asserts the rule is in the
  rendered HTML so a future tidy-up can't quietly move it into the stylesheet.
- **The script is in `<head>`, not at the end of `<body>`.** Its `pagereveal` listener
  has to exist before the browser's first render of the incoming page, and these list
  pages are ~70 KB — Chrome paints them mid-parse, long before an end-of-body script runs.
- **The row is named at click time, never up front.** `view-transition-name` must be
  unique in the document, so naming all 20 rows `vt-hero` would abort every transition on
  the page. `static/js/view-transitions.js` marks the one row being left (capture-phase
  click, because the invoice and job tables navigate from an inline
  `onclick="window.location=…"` that runs on bubble — too late).
- **The way back needs two signals.** "Back to Jobs" is a forward navigation, so
  `document.referrer` identifies it; the Back button is a traverse, where the referrer is
  whatever led to the list originally and proves nothing — that case is caught with
  `navigation.activation.navigationType === 'traverse'`. The clicked key is kept in
  `sessionStorage`, and the name is cleared on `viewTransition.finished` so a second stale
  name can't abort the next transition.
- **Naming the navbar is what makes it stop reading as a page load.** `.vt-nav` (and
  `.vt-tabbar` for the portal's mobile bar) lifts the chrome out of the root snapshot, so
  it doesn't dissolve and redraw on every click. It is one line and it does more than the
  hero does.
- **Heroes only where the row title and the page title are the same thing**: job rows
  (customer name → `Repair #6 - Bill Smith`), invoice rows (invoice number → invoice
  number), customer cards (name → name). The customer portal's services list is keyed by
  *unit*, and its detail heading is `Repair #12`; morphing between two unrelated strings
  reads as a glitch, so that list gets the page cross-fade only. Same reason no hero on
  the dashboards.
- Both snapshots are stretched to the group's box by default, which squashes glyphs when
  a 14px row label becomes a 20px page title — `object-fit: contain` +
  `object-position: left top` keeps the aspect and pins the first letter so the word grows
  out of itself.
- Reduced motion kills all three groups' animations (instant swap, i.e. exactly the old
  behaviour). The `*` form is written twice, once with the three names spelled out: if a
  browser doesn't understand `::view-transition-group(*)` it drops the whole rule, and
  silently animating for someone who asked for no motion is the one failure that matters.
- **Verifying this needed a browser that actually renders.** Chrome skips every view
  transition in a document that is never painted, and the MCP automation tab is a hidden
  tab: `document.visibilityState === 'hidden'`, `startViewTransition()` rejects with
  "invalid state", `pagereveal` never fires, and every check reports a perfectly healthy
  no-op. Driving a headless-but-rendering Chrome over CDP (tornado's websocket client is
  already in the venv, so no new dependency) gave both the true/false answer and
  mid-flight screenshots. Worth keeping: `pageswap.viewTransition` on the outgoing page is
  the one-bit test for "did this actually engage".
- **The dev-server template cache bit again**, and cost the wrong conclusion for twenty
  minutes: the inline opt-in was in the file and *not* in the served HTML. It is already
  the fourth bullet in the trap list at the top of this file. Restart the server.
- The flash-message and subscription banners were the stated risk and turned out to be a
  non-issue: they live inside the root snapshot, so a page that has one simply cross-fades
  into a page that doesn't.
- Full suite: 3625 tests, `57F/34E`. Replaying those 34 modules on a clean `main`
  worktree gives the same 57F/34E and the two sorted `FAIL:/ERROR:` lists diff to
  zero lines — no regressions. (Counts drift between runs; the set is the bar.)
- New: `tests/test_view_transitions.py` (7) — the inline opt-in on two shells, the
  `data-vt-key`/`data-vt-hero` contract on each keyed list, and `.vt-hero` on the
  detail titles.

## S11 · Skeletons and optimistic status changes — DONE

Branch `feat/ui-s11-skeletons`. Both lists now say something during the second they
spend waiting on the server, and marking invoices paid shows the answer before the
round trip finishes — then puts back, visibly, whatever the server refuses.

**What changed** (PR #210, branch `feat/ui-s11-skeletons`)

| File | Change |
|---|---|
| `static/js/list-loading.js` | **new** — traces the live list into a skeleton while a same-path navigation is in flight |
| `static/js/optimistic.js` | **new** — `Optimistic.begin/commit/rollback/setBadge`, the three row states |
| `static/css/src/input.css` | `--sk-tone` token; `.sk-bar` / `.sk-lines` / `.sk-list`, `.row-pending` / `.row-rollback` / `.paid-check`; three keyframes |
| `core/templatetags/ui.py`, `components/status_badge.html` | `{% status_badge … optimistic=True %}` emits the repaint + tick hooks |
| `technician_portal/job_list.html` | `data-skeleton-list` on both twins; `data-optimistic-row="repair-<id>"`; bulk approve/deny/reset flip the badges before submitting |
| `saas/owner_invoices.html` | same skeleton hooks; row/badge/due/actions handles; modal spinner → shaped skeleton; `doMarkSelectedPaid` rewritten |
| `apps/saas/views.py` | `owner_invoice_bulk_action` returns `paid_ids` / `skipped_ids` |
| `templates/base_app.html`, `tailwind.config.js` | load the two scripts; safelist the new component classes |
| `tests/test_list_skeletons.py` | **new** — 10 tests, the regression guard |

**Notes**

- **The skeleton is a tracing of the list you are leaving, not a drawing of the one
  you are going to.** Each row is cloned and every text run in the clone is replaced
  by a `.sk-bar` of that run's measured width — one bar per rendered *line*, so
  wrapped text stays two bars tall. Nothing in the JS knows what a job row or an
  invoice row looks like, no page hand-authors a skeleton that will drift from its
  own table, and column widths, row heights and alignment survive because the markup
  does. It works unchanged on the mobile card stack and the desktop table, which are
  two completely different layouts. The whole contract is `data-skeleton-list` on the
  row container.
- **The trees are walked twice in lockstep.** A `TreeWalker` over the live row gives
  the measurements; the identical walk over its clone applies them. That is what
  removes the need to thread ids or markers through the markup — same tree, same
  order, same node.
- **Same pathname = this list, re-queried. Different pathname = a row opening.** That
  one rule is the entire trigger, and it is why a row → detail click is excluded for
  free — which matters, because skeletoning that click would have replaced S10's
  row-into-title morph with a grey bar flying into a heading. It also means no page
  has to annotate its filter links, its pagination, or its search form.
- **The status `<select>` navigates with `location.href =`**, which no click or
  submit listener can see. The Navigation API's `navigate` event can, and it is the
  only reason that listener exists. `traverse` is excluded: skeletoning a Back
  navigation would freeze a skeleton into bfcache.
- **A tracing that keeps its colours is not a skeleton.** The first version blanked
  the text and left the status pills blue/red/green and the `bg-yellow-50/50` row
  tint on the REQUESTED rows. It reads as a half-real list — worse, the colour is
  from the list being *left*, and after a status filter it is the exact thing about
  to change. Chips now keep their shape in `--sk-tone`; anything wider than half the
  row loses its tint entirely. Told apart by width, because a chip is small and a
  row tint is not.
- **180ms of grace.** Nothing paints before that, so a list that comes back fast
  looks like it never left. Verified both ways against a deliberately slowed dev
  server: 240 bars during a 900ms wait, nothing at all inside the grace window.
- **`pagehide`, not `pageswap`, is where the skeleton is undone.** S10's snapshot is
  already taken by then, so the undo is invisible — and it keeps a skeleton out of
  bfcache. There is also a 12s failsafe, because a cancelled navigation tells you
  nothing.
- **Optimism buys the round trip; it does not buy the truth.** Marking invoices paid
  flips the rows instantly and still reloads on full success — after the tick has
  drawn. "Owed to you", the aging bar and the status filter are all server-computed,
  and a page that turned six rows green while the total above them sat still would
  be worse than the wait it replaced. A **partial** failure deliberately does *not*
  reload: the owner needs to stay and watch which ones came back.
- **`paid_ids` is what makes the optimism honest.** `mark_paid` can partly succeed —
  an already-paid, cancelled or fully-credited invoice is skipped — and `updated`
  alone cannot say *which*, so the page could only ever have flipped every selected
  row and hoped. The endpoint now names them, and the refused rows roll back with an
  amber return and a toast that says why.
- **Rollback restores saved `innerHTML`, not an inverse of each edit.** Every handler
  on these rows is an inline `onclick` attribute, which survives that round trip. It
  would not survive it on a row wired with `addEventListener`, and `optimistic.js`
  says so at the top.
- **`.row-rollback` is an animation on purpose.** These rows carry a
  `hover:bg-gray-50` utility, and a components-layer background loses to it at equal
  specificity. Animation-origin declarations outrank every normal rule regardless of
  layer, so the amber wins without a doubled-class hack.
- **Money is not animated.** The amount due just changes to `$0.00`; the only motion
  is the tick drawing itself inside the Paid pill, ~420ms, once, and nothing under
  reduced motion. The two amount-due cells did pick up S4's `.num` — an optimistic
  `$142.50 → $0.00` in proportional figures reflows the column mid-gesture, which is
  the closest this could get to animating a number by accident.
- **The create-invoice modal's skeleton is hand-drawn, and that is the right call.**
  Its target is a fixed, known shape (checkbox, unit line, date line, right-aligned
  amount) and there is no live list to trace — the tracer only has something to copy
  when the thing being replaced is already on screen.

**Traps hit this session**

- **`document.querySelector('.row-rollback')` finds the hidden mobile twin.** Both
  lists render the phone card *and* the desktop row for every record, at every
  width. The card comes first in the DOM, and at 1440px it is `display: none` — so
  the probe reported `getAnimations() === []` and a background frozen at the 0%
  keyframe, for two seconds, on an animation that was in fact running perfectly one
  element later. A screenshot settled it in one look. Scope to `tr.row-rollback`, or
  to the twin you can actually see. (Same shape as S9's stale-`getComputedStyle`
  lesson: when the numbers stop making sense, take a picture.)
- **`Network.emulateNetworkConditions` does not slow down loopback.** Twenty minutes
  went into "the skeleton never paints" before the truth turned out to be "the
  navigation finished in 40ms". A four-line middleware that `time.sleep(0.9)`s on a
  list re-query is the honest way to see a loading state on a dev server.
- **A navigation destroys the JS context that observed it.** Anything measured in the
  outgoing document has to be left in `sessionStorage` for the incoming one to
  report, or the `Runtime.evaluate` that reads it dies with "Inspected target
  navigated or closed".

**Verified:** 10 new tests green, and all 10 fail on the pre-change markup (stash the
six touched files, run, pop — six failures, four errors). Skeleton tracing confirmed
in a rendering headless Chrome at 1440×900 and 390×844: 24 traced job rows / 240 bars,
14 invoice rows / 180 bars desktop and 152 mobile, zero duplicate ids, zero
`data-vt-key` leaked into a tracing. Optimistic mark-paid exercised on all three
branches — partial (one tick, one amber return), refused (both return, error toast)
and real (`paid_ids: [1, 2]`, ticks, reload). Reduced motion checked with the media
feature emulated: bars still show but do not sweep, the rollback becomes a solid amber
outline instead of a flash, and the tick renders already drawn. `collectstatic` passes
under the production manifest storage (196 copied / 556 post-processed); no third-party
asset hosts in either list's rendered HTML. 213 targeted tests green. Full suite: 4341
tests, `53F/36E`; replaying those 38 modules on a clean `main` worktree gives the same
`53F/36E` and the two sorted `FAIL:/ERROR:` lists diff to **zero lines in either
direction**.

**Left for later, deliberately**

- **The jobs list has no rollback branch.** Its bulk actions POST and navigate, so
  the redirect *is* the reconciliation and there is nothing to roll back to. The
  badges flip at confirm-time and the server decides; that is all optimism can buy
  on a form post.
- **The repair detail page's status buttons are untouched.** Six `<form method=post>`
  submissions, each with real side effects (notifications, invoicing). Converting
  them to fetch to make them optimistic is a behaviour change, not a paint change,
  and it belongs to whoever next owns that page.
- **Thirteen `fa-spinner` uses remain** across six files (the repair and multi-break
  forms, the customer request form, autosave, the referrals dashboard, the batch
  detail page, and two inside this page's own Send/Create buttons). Every one of them
  is progress on a *submit* rather than a content load — the one job a spinner is
  still right for. The one this session replaced was the only content load among them.

**What happened next (2026-08-25, added after the fact)**

S11 is the first session in this arc whose output left the arc. Within hours of #210
merging, `static/js/optimistic.js` and `static/js/list-loading.js` were documented in
`CLAUDE.md` and picked up as house infrastructure by a queue that has nothing to do with
UI magic: `FIELD_OPS_SESSIONS.md` now carries a *"Use the house helpers, don't hand-roll"*
rule pointing S12 (the ordered day list) at them, added because that session had been
specced to write its own optimistic-move code before these existed.

Two things follow.

- **The rollback contract is now load-bearing for people who never read this file.**
  `Optimistic.rollback` restores saved `innerHTML`, so a row's handlers must be inline
  `onclick` attributes — an `addEventListener` binding dies on rollback and the row goes
  quietly inert. That was an implementation detail of two lists inside this session; it is
  now an API constraint on every arc in the repo. It is written down in `CLAUDE.md` and in
  FieldOps' §0, and it must stay written down in both.
- **A primitive earns its keep by being reached for, not by being right.** The measure of
  S9/S10/S11 is not the two lists each shipped on. It is whether the next person building
  an unrelated feature finds them before hand-rolling. S11 passed that test in under a day
  because it landed as *named, documented, opt-in* helpers with a one-attribute contract.
  S13's `{% icon %}` tag needs to land the same way, and for the same reason.

## S12 · Auth pages: one brand mention, full-height, no marketing nav — DONE

`/login/` said "RS Systems" **seven** times, not the three this brief guessed at, and the
split panel stopped mid-viewport leaving dead white space.
Dropped the marketing nav from the auth pages, made the split full-height, said the brand once.

**What changed** (PR #209, branch `feat/ui-s12-auth-pages`)

| File | Change |
|---|---|
| `templates/saas/login.html` | `saas/base_public.html` → `base_auth.html`; `min-h-[calc(100vh-4rem)]` → `min-h-screen`; card subcopy "Log in to your RS Systems account." → "Log in to continue."; hand-rolled footer → the shared include |
| `templates/registration/password_reset_{form,done,confirm,complete}.html` | same base swap; `min-h-[calc(100vh-8rem)]` → `min-h-screen`; footer include `with wordmark=True` |
| `templates/includes/auth_footer.html` | **new** — slim `Terms · Privacy` line, optional leading wordmark |
| `tests/test_auth_page_shell.py` | **new** — 4 tests, the regression guard |

**Notes**

- **`base_auth.html` already existed and already did the job.** `signup.html`,
  `customer_portal/register.html`, `registration/register_technician.html` and
  `saas/email_confirmation_invalid.html` were all on it. Only login and the four
  password-reset pages were still on the marketing shell. This session was mostly
  *finding* that, not designing anything — the pattern to copy was `signup.html`.
- **Count the brand from rendered HTML, not from the template.** The brief said three
  mentions; the test found seven, because `base_public.html` contributes a nav wordmark
  *and* a footer wordmark *and* a footer copyright, and login.html carried both a desktop
  and an `lg:hidden` mobile `<h1>`. Only one of that last pair is ever painted, which is
  why `/login/`'s budget in the test is 2 and everything else is 1. Strip
  `<title>`/`<svg>` before counting or the invisible wordmarks inflate it.
- **The nav was carrying Terms and Privacy.** Deleting the marketing shell from a page
  silently deletes the legal links with it. `includes/auth_footer.html` exists to put
  them back; that is the only thing `base_public.html` was legitimately providing here.
- **Auth pages now get tenant branding.** `base_public.html` never emitted
  `{% tenant_brand_css %}`; `base_auth.html` does. `/login/` is unaffected (no tenant
  resolved → the tag renders nothing → RS blue), but a shop-scoped login now themes to
  the shop, which is what that tag was written for.
- **The `-4rem`/`-8rem` in the min-height was load-bearing.** It was subtracting nav and
  footer. Swapping the base without also swapping the height leaves the exact dead strip
  the session was opened to remove. Grep `min-h-\[calc\(100vh-` after any base change.
- **Prove a template test fails first.** `git stash push -q <templates>`, run, `stash pop`
  — seven seconds, and it is the difference between a guard and a green no-op. Ours
  reported `7 not less than or equal to 2` on the old markup, which is also where the
  real mention count came from.
- **Verified:** all four password-reset URLs plus `/login/` render 200; screenshots at
  1440×900 confirm full-height split, no nav, no site footer; `collectstatic` passes
  under the production manifest storage (194 copied / 550 post-processed); no third-party
  asset hosts in the rendered HTML; `tests.test_auth_page_shell` (4) green and
  `test_primary_contact` + `test_e2e_today` + `test_step5_nav` + `test_url_routing` +
  `test_auth_permissions` + `test_view_transitions` (110) green.

**Left for later, deliberately**

- `saas/invite_accept.html`, `saas/shop_join.html` and
  `customer_portal/invitation_accept.html` are standalone `<!DOCTYPE>` documents with
  their own `<head>`, not extenders of any base. They already have no marketing nav, so
  S12's brief does not reach them — but they duplicate `head_assets.html`'s job and
  should be folded into `base_auth.html` in a cleanup of their own.
- `base_public.html` still hardcodes `bg-blue-600` in its nav and footer rather than
  `brand-*`. That is correct for the *platform* marketing surface (S3 note: the platform
  login stays blue), so it was left alone — but it is a raw hex-adjacent literal sitting
  where a token belongs, and worth revisiting with S14–S16.

## S13 · Icon language: Font Awesome solid → line-weight SVG — **tag DONE (PR #223), migration open**

1,281 FA **solid** usages when this session was written. **Re-counted 2026-08-25 20:50 CDT:
1,303** (`grep -rho 'fas fa-' --include='*.html' templates apps | wc -l`), plus 14 `far`.
Solid weights read dated; consistent-stroke line icons are most of what people mean by
"Apple-like".

**The count is not a constant — it is a burn-up.** It grew by 22 in sixteen days without
anyone touching icons on purpose: every new surface in every arc reaches for the icon
vocabulary that already exists, and `fas` is what exists. Photo-ML and FieldOps together
added five more on 2026-08-25 alone (`fa-times`, `fa-plus`, `fa-crosshairs`) and removed
none. That is not carelessness — it is the correct thing to do with no `{% icon %}` tag to
reach for.

The practical consequence: **ship the tag before the migration.** An `{% icon 'name' %}`
that exists and is documented in `CLAUDE.md` stops the debt growing on the day it lands,
months before the last `<i class="fa` is gone, and it is a fraction of the work. Doing it
in the other order means racing three parallel arcs to a moving finish line.

Do this **last in Phase 3**, and incrementally: add an `{% icon 'name' %}` tag backed by an
inlined SVG sprite, migrate surface by surface, and only delete the vendored FA files when
the last `<i class="fa` is gone. S1 already removed the *CDN* risk, so there is no urgency
here — this is purely aesthetic, which is exactly why it must not be rushed into a
1,281-site find-and-replace.

### S13a — the tag, shipped 2026-08-26 (PR #223)

`{% icon 'name' %}` in `core/templatetags/ui.py`, geometry in `core/icons.py`
(70 icons, ~40 aliases), `.icon` in `input.css`, `tests/test_icon_tag.py` (21 tests).
**Nothing was migrated.** Font Awesome is untouched and still correct on all ~1,300 sites.
Documented in `CLAUDE.md` and `UI_DESIGN_GUIDE.md` — which, per this doc's own finding, is
the only reason the other arcs will ever see it.

**The burn-up was still running while this was written.** `origin/main` held steady at
1,303 `fas` overnight, but PRs #220 and #221 (job queue, an arc that has never opened this
file) carried **eight more between them, unmerged**. That is the whole argument for shipping
the tag first, observed live rather than inferred.

**Not a sprite, and the brief was wrong to specify one.** A `<symbol>` sprite has to be
injected into every shell — there are eight-plus here, plus standalone pages like
`billing/public_invoice_view.html` and the `customer_portal/quick_*` confirmations that
extend nothing — and a `<use>` in an HTMX-swapped fragment depends on a sprite that may not
be in that document. Per-call inlining has none of those failure modes, and at this app's
icons-per-page it is *smaller* than shipping a 70-icon sprite to a page that draws three.
The repeated markup gzips to nothing. **The word "sprite" in a brief is an implementation
guess; the requirement was "one place the geometry lives", and `core/icons.py` is that.**

**Drop-in is the whole feature, and it is a CSS fact, not a wish.** `.icon` is `1em` square
with Font Awesome's own `-0.125em` baseline offset. Verified the way this doc verifies
anything — rendered side by side against the real vendored `fontawesome.min.css` at five
font sizes: identical baseline, matching optical weight. Without that offset every migrated
icon shifts a pixel and a two-line diff reads as a redesign.

**Two icons had to be redrawn after looking at them, and no test would have caught either.**

- `car` was a side view. `fa-car` is a *front* view, so every migrated surface would have
  jumped, and the side view goes mushy at `text-sm` where list rows live. Redrawn front-on —
  which is also the right subject for a glass shop. The side view survives as `car-side`,
  which `fa-car-side` (4 uses) now resolves to instead of being aliased away.
- `file-invoice` drew a `$` inside a document. At 24×24 with a 2px stroke the counters of
  the S close up and it renders as a smudge at exactly the inline size invoices are listed
  at. **There is no legible glyph-inside-a-container at this weight** — the container has to
  carry the meaning. `file-invoice`, `file-invoice-dollar` (27 uses between them) and
  `invoice` all resolve to `receipt`, which reads at 16px.

**`.icon` is emitted from Python, so the purge cannot see it.** `tailwind.config.js` does
scan `core/templatetags/*.py`, but the class is spelled `class="icon{extra}"` in a format
string and the extractor is a plain-text regex. Safelisted, and pinned by a test that greps
the *built* `app.css`. Same failure shape as #206's `bg-yellow-200`: markup stays perfectly
valid while every icon renders 0×0.

**An unknown name raises under `DEBUG` and degrades in production.** A typo in a decoration
must not 500 a page; it logs and renders the empty sized box so the layout does not jump.

**What is left of S13:** the migration itself, and only then deleting the vendored FA files.
It is now a mechanical sweep with a stable target instead of a race — which is what shipping
the tag first bought.

### S13b — the chrome, migrated 2026-08-27 (PR #227)

The first migration sweep, scoped to **the chrome**: both app shells and every shared
include and component. **101 call sites across 13 files**; `1,307 → 1,210` `fas`
(`14 → 10` `far`). Seven icons had to be drawn to cover it (`menu`, `gauge`, `file`,
`book-open`, `thumbs-up`, `thumbs-down`, plus the `hand-holding-usd` decision below).

**Start with the chrome, not with the biggest file.** `owner_settings.html` has 116 icons
and `repair_form.html` 80, but they are each one screen. The chrome is on *every* screen,
so one before/after pass over four surfaces exercises the drop-in claim everywhere at
once — and if `.icon` had been wrong about baselines or sizing, it would have been wrong
in the header of every page in the app rather than in one form.

**The drop-in claim held, and the way to know that is two servers.** `origin/main` and the
branch running side by side on 8021/8022 against the *same* seeded SQLite file, driven by
one CDP script that logs in and shoots the same six surfaces on each. Diffing two
screenshots of the same page is the only check that can tell "the icon changed" from "the
layout moved". Nothing moved.

**`{% load %}` cannot go above `{% extends %}`, and only a render says so.** The sweep
inserted `{% load ui %}` at the top of every file that did not already have a `{% load %}`
line. Twelve of the thirteen were includes, where that is correct. The thirteenth,
`support/base_topic.html`, extends `base_app.html`, and Django refuses:
`<ExtendsNode> must be the first tag in the template` — a hard 500 on every help guide.
No test in the suite renders that template. **A mechanical sweep over templates needs a
render of each touched surface, not just a passing suite.**

**Font Awesome has been silently defeating `hidden` this whole time.** Both shells hang a
`chevron-down` off the avatar with `hidden sm:inline`, and both were visible on mobile
anyway. `.fas { display: inline-block }` lives in `fontawesome.min.css`, which is linked
*after* `app.css` in `head_assets.html`; same specificity, later wins, so **no
`<i class="fas">` in this repo could ever be responsively hidden.** Migrating them fixed
it — the chevrons now actually disappear below `sm`. Only two sites repo-wide, both in
this sweep, but the mechanism applies to any display utility on an FA `<i>`.

**`hand-holding-usd` has no line-weight form, and the reason is worth keeping.** Three
attempts at an open palm with a coin above it were all drawn, rendered at 16/24/40px, and
compared against `user`. A palm is a wide shallow curve; a disc above one **is** the
person glyph. Breaking the symmetry with fingers makes it an illegible squiggle instead.
Same answer as `file-invoice`: alias to the mark that reads (`dollar-sign`) and let the
FAB's own "Receive Payment" label name the action. **The failure mode for an icon at this
weight is not always "smudge" — it can be "you have accidentally drawn a different icon in
the set."**

**The contact sheet is a script now** — `scripts/icon_contact_sheet.py`. S13a's two sheets
were built by hand and thrown away, and this session needed them again on day one. It
emits the 70-icon grid *and* the side-by-side against the real vendored
`fontawesome.min.css` at five font sizes. That is what caught `gauge` on its first draft:
a semicircle of r=8 is optically half the weight of its neighbours in a nav row, which no
assertion expresses. Same lesson S14 is waiting on — **regenerate by command, never
re-author.**

**The count the doc has been tracking was never the whole debt.** `grep` over `*.html`
misses **17 icon names that live in Python** — `HELP_TOPICS` in `apps/support/views.py`
stores `'icon': 'fas fa-tools'` and eleven other surfaces read it. `resolve()` tolerates a
bare `fa-` prefix but not the `fas ` weight prefix, so those need either a split at the
call site or a wider `resolve()`. Exactly the shape of #206's `bg-yellow-200`: the
template-only view of a template-and-Python problem.

**The sweep flips string-matching tests, in both directions.** `tests/` has exactly
three assertions on Font Awesome class names, and this PR moved one of them:
`test_ux_fixes.test_wrench_icon_used_not_tools` asserts `/owner/settings/` contains
`fa-wrench` and NOT `fa-tools`, and it **fails on `main`** — the FAB include on that page
emits `fas fa-tools`. Migrating the FAB removed the string, so it now passes, and the
page genuinely draws a wrench (`tools` aliases to `wrench`). But the same test will
**break** the moment `owner_settings.html` itself is migrated: no `fa-` strings will
remain and `assertIn('fa-wrench')` fails. **Rewrite those three against the rendered
`{% icon %}` output as their page comes up in the sweep** — the other two are
`test_ux_fixes:521` and `test_list_skeletons:100` (`assertNotIn('fa-spinner')`, which
survives either way).

**What is left of S13 after this:** the ~1,210 remaining call sites, page by page
(`owner_settings.html` 116, `repair_form.html` 80, `repair_detail.html` 60,
`owner_invoice_detail.html` 56 are the top four), the 17 Python-side names, and only then
deleting the vendored FA files.

---

# Phase 4 — The front door

`templates/landing.html`. Platform-branded — do **not** introduce `brand-*` tokens here
(see S3 notes).

## S14 · Real product imagery instead of the fake mock

`landing.html:120-190` is hand-built HTML imitating the dashboard inside fake browser
chrome — and it has already drifted from reality. Replace with a real screenshot, or
better, a 4-frame scroll-scrubbed sequence: chip photo → job created → invoice sent → paid.

Run this **after S5**, so the shot captures the redesigned dashboard.

**Correction, 2026-08-25.** This brief's example of the drift — *"the mock shows a blue
revenue banner; the real dashboard is green"* — was written before S5 and is now wrong in
both halves. S5 killed the green slab, so the real dashboard is not green; and the drift
is no longer about colour at all. `landing.html:131` still paints
`bg-gradient-to-r from-blue-600 to-blue-800` — a flat slab with a number on it — while the
surface it claims to show is a `.card` with a delta chip, a sparkline and a period toggle.
The mock now under-sells the product it is advertising.

Take that as the argument for the session rather than a detail to fix: **a hand-built mock
does not drift once and stop.** It drifted, then the thing it copied was redesigned, and
the mock's error changed shape without anyone editing either file. A screenshot cannot do
that. Whatever S14 ships, it should be regenerable from the real app by a command, not
re-authored by hand — otherwise this note gets written a third time.

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

~~**Delete the `[data-reveal]` scroll fade**~~ — **done 2026-08-27 as S16a, PR #235.**
See below. The redesign half of S16 is untouched and still open.

### S16a — the scroll fade, deleted 2026-08-27 (PR #235)

Six `data-reveal` wrappers, three CSS rules, the `classList.add('js')` bootstrap and the
IntersectionObserver: 33 lines out, 6 in. `templates/landing.html` is the only file that
had it — nothing in `static/`, no other template, and `app.css` never carried the rule.

**The brief undersold it. The fade was worst on the two paths that matter most.**

- **The nav's own anchors skip the observer entirely.** `#features` and `#pricing`
  (`landing.html:67-68`, and again in the mobile menu at 80-81) jump the viewport
  instantly. Clicking **Pricing** — the page's primary conversion path — put you on three
  plan cards at **opacity 0.28**, prices unreadable, for the better part of a second. Four
  of the six blocks were still at opacity **0** in that same frame, because the jump had
  skipped past them without ever intersecting.
- **It was also on the hero.** `landing.html:120`, the dashboard mock, carried
  `data-reveal` too — so the page's opening product shot assembled itself on first paint,
  at both 1280px and 390px. That is the one image the whole page is built around.
- A measured flick to the pricing section (14 wheel events, so *slower* than a thumb)
  landed with the grid at **opacity 0.52**.

**The proof it is a pure drop-in.** Two Chrome runs against the same server and the same
seeded DB, the branch template stashed and popped between them, same CDP script:

| frame | before | after |
|---|---|---|
| anchor jump to `#pricing`, settled | — | **byte-identical** |
| fast scroll to pricing, settled | — | **byte-identical** |
| first paint, 1280×900, settled | — | **byte-identical** |
| first paint, 390×844, settled | — | **byte-identical** |
| first paint, either width, **t0** | ghosted | **differs — the point** |

Four settled frames identical to the byte at two widths says nothing about the layout
moved; the two t0 frames differing is the entire change. **That table is the shape to
copy for any deletion-of-motion PR** — a removal is only safe if you can show the settled
state is the same picture, and only worth shipping if you can show the first frame is not.

**The guard is `tests/test_landing_visibility.py`**, and it asserts the rule rather than
the word: no inline `<style>` on the landing page may ship content at `opacity: 0` or
`visibility: hidden`, no inline script may tag `<html>` to arm such a rule, and no inline
script may hold an `IntersectionObserver`. Three of its four tests fail on the parent
commit and pass here — a guard that has never been red is a guard nobody has checked.
Tailwind's `hidden md:flex` does not trip it: those live in the linked stylesheet and are
decided by the viewport, not by a script that may not have run.

**Why this was worth doing alone.** S16's redesign half needs Drake's eye on the promise
copy and a decision about the dark section. The fade needed neither, and every day it
stayed was a day the pricing page introduced itself as a blank rectangle.

---

# Housekeeping

## S17 · Stop shipping the Tailwind source to production ✅ DONE 2026-08-27

`static/css/src/input.css` was collected and served publicly, and its presence forced the
`@font-face` workaround in S1/S2. The source moved to `assets/css/input.css`, outside
`STATICFILES_DIRS`; `scripts/build_css.sh`, `CLAUDE.md`, `docs/development/UI_DESIGN_GUIDE.md`
and the rest of the path references followed; and the Inter `@font-face` moved back into the
stylesheet with a plain `url('../fonts/inter-variable-latin.woff2')`.

### Notes

**The brief was right about the shape and it cost about what it said.** One `git mv`, one
line in the build script, one `@font-face` moved, and then the long tail: eleven files
carried the old path in prose or a comment. The path was load-bearing in exactly one place
(`tests/test_mobile_touch_targets.py` reads the source to compare it against the build);
everywhere else it was documentation that would have quietly started lying.

**Why `../fonts/…` is now correct and wasn't before.** `url()` in a collected stylesheet is
resolved by `ManifestStaticFilesStorage` against *that stylesheet's own directory*. With the
source at `static/css/src/input.css` there were two collected copies of the same
declarations, one in `css/` and one in `css/src/`, so no single relative path could be right
from both — `../fonts/…` means `fonts/` from the build and `css/fonts/` from the source.
Reproduced deliberately before deleting it, and the error is worth recognising on sight:

```
ValueError: The file 'css/fonts/inter-variable-latin.woff2' could not be found
with <ManifestStaticFilesStorage>
```

`css/fonts/` — a path that exists nowhere — is the tell that something under `static/` is
resolving a `url()` from the wrong directory.

**The documented recipe would have caught it.** Step 2 of the Verification recipe runs
collectstatic under `ForgivingManifestStaticFilesStorage`, and "forgiving" made it worth
checking whether that variant swallows this. It does not: the override is on `stored_name`
(manifest *lookups*), while this raises in `hashed_name` during post-processing. Both the
forgiving and the strict storage refuse to collect. The recipe is sound as written.

**`app.css` was stale on `main`, unrelated to any of this.** Rebuilding produced two
changes, not one: the `@font-face`, and `.pt-2\.5`, which
`templates/technician_portal/photo_backfill.html` has referenced since 2bbaac1b without
anyone running the build. That hint paragraph has had no top padding in production since.
A committed build artifact only stays honest if every arc that touches a template runs
`./scripts/build_css.sh` — and nothing enforces that, because `bin/tailwindcss` is
gitignored so CI cannot compile. `tests/test_mobile_touch_targets.py` catches staleness
only for the specific declarations it lists by hand.

**What is guarded now** — `tests/test_css_pipeline.py`, 8 tests:

| | |
|---|---|
| No `@tailwind` directive in any `.css` under `static/` | The general form of the bug: *any* uncompiled source there is served, whatever it is named |
| `build_css.sh` reads `-i assets/css/input.css` | Stops a half-move that leaves the build pointing at a file nobody edits |
| Every `url()` in `app.css` resolves from `static/css/` and stays inside `static/` | **The deploy failure as a unit test.** Verified by mutation — point the font `url()` at a missing file and it fails |
| `head_assets.html` declares no `@font-face` rule | Two rules for one family is a second thing to keep in sync; the preload hint stays |

The `url()` test matters more than the others: it is the only one that would have caught the
original bug *without* knowing the original bug. The first draft of it asserted
`'@font-face' not in head_assets.html` and failed on the template's own comment saying where
the rule went — the assertion has to be about the rule (`@font-face\s*\{`), not the word.

**Two things stay inline in `head_assets.html`, and they are not the same reason.** The
`@view-transition` opt-in is inline because Chrome ignores it from an external stylesheet
(S10) — a browser bug, permanent until it isn't. The `<link rel="preload">` for the font is
inline because a preload has to start during HTML parse, before `app.css` has even arrived;
that is correct architecture, not a workaround. Neither is a candidate for the same cleanup.

**Verified:** collectstatic passes under both strict `ManifestStaticFilesStorage` and
production's `ForgivingManifestStaticFilesStorage`; the hashed output carries
`url("../fonts/inter-variable-latin.65850a373e25.woff2")`; `/static/css/src/input.css` is now
404 where it used to be 200; and on a real page `document.fonts.check('16px Inter')` is
`true` with the woff2 fetched 200 and the only inline `<style>` left holding
`@view-transition` alone. 102 tests across the seven CSS/asset suites green.

### The CSP follow-on is now unblocked twice over

The note below has been waiting on Phase 1 soaking. S17 removes the second obstacle nobody
had written down: a `style-src` without `'unsafe-inline'` was impossible while a font
declaration lived in an inline `<style>`, because the `@font-face` had to be re-inlined on
every page. What is left inline is one `@view-transition` rule and it is static — a hash in
the `style-src` allowlist covers it.

## Follow-on once Phase 1 has soaked

Add a strict **Content-Security-Policy**. S1 removed every third-party asset host, so the
allowlist is now small: self + Stripe + Cloudflare Turnstile. This was impossible before
and is the main security dividend of Phase 1 — don't leave it on the table.

---

# Phase 3 — Outbound: email and notifications ✅ DONE (PRs #200 + #202 + #206)

The design canvas that drove this:
https://claude.ai/code/artifact/e43f623b-2e7c-4ea1-959e-93d17dbd7b6d

Every surface in Phases 1 and 2 is a page the shop looks at. Email is the only
surface the shop's *customers* see, and it was the one place none of the work
above had reached: two unrelated email systems, neither using the tokens.

## What landed

**One chassis.** `templates/emails/base.html` is the email shell.
`send_branded_email()` kept its signature — all 24 call sites unchanged — and
renders `emails/generic.html` instead of building HTML in an f-string. The 14
notification templates extend the same base. Components in
`templates/emails/components/` (NOT `parts/` — `.gitignore` carries buildout's
`parts/` rule and silently drops it from the commit).

> This paragraph originally read "is now the **only** email shell". It was
> wrong on the day it was written — there was a third, and it was the invoice.
> See **The invoice email** below.

**Tokens, not settings.** The chassis hardcodes the palette and reads only
identity + `primary_color` from `branding`. `EmailBrandingConfig`'s colour and
font fields are platform-wide; letting them through is how the platform
owner's look leaked onto other shops' mail. Status pills come from
`core/templatetags/email_ui.py`, whose tone table mirrors `ui.py` — an email
badge and a job-page badge cannot drift.

**The replacement lifecycle now exists.** Every seeded template was `repair_*`,
so the shop's most expensive job sent nothing after the request while a $40
chip repair sent five emails. Seven new templates (`replacement_*`), seeded by
`core/0032`, wired through `handle_replacement_status_change`.

## Traps worth remembering

- **A notification's context is flat and JSON-serializable.** It is persisted
  on the `Notification` and re-rendered by the retry path, so the job object is
  never in it. Three templates read `{{ repair.total_cost }}` anyway and
  rendered a bare `$` — and `total_cost` is not a field on `Repair` (it is
  `cost`). Derived values come from `notification_service.job_display_context()`.
- **`PRIORITY_HIGH` sends in-app + SMS, NOT email.** SMS is dark (the toll-free
  registration was denied), so a HIGH template with no `channels_override`
  silently sends nothing. Every `replacement_*` template declares
  `['in_app', 'email']` explicitly rather than trusting the priority mapping.
- **`_handle_assignment_change` pops the tracking dict** and its receiver is
  registered first, so the lifecycle handler needs its own
  (`_replacement_previous_status`) or it always reads `old_status = None` and
  never fires.
- **A generous test fixture hides all of the above.** The first pass supplied
  every variable a template might want and 16 tests passed over four real bugs.
  `RealCallerContextTests` renders each template with exactly the context its
  sender in `signals.py` builds.
- **Buttons must resolve against `base_url`.** Nine templates passed a bare
  relative `action_url`; a relative href is dead in every mail client.

## The invoice email — the third shell (2026-08-24, PR #202)

> **Status: MERGED 2026-08-24 12:15 CDT. Not deployed as of 12:16 CDT** —
> main was redeployed twice that hour and both cuts landed just ahead of this
> merge. **Do not trust that sentence; re-check it**, because production moved
> under it twice while it was being written:
>
> ```bash
> eb status rs-systems-production | grep 'Deployed Version'   # app-<sha>-<stamp>
> git log --first-parent origin/main                          # what should be there
> gh pr view 202 --json mergedAt                              # NOT gh pr list
> ```
>
> `gh pr list`'s fourth column is *updated*, not *merged*. Reading it as a
> merge date has now put a wrong claim in a strategy doc three times.


Found the way these things are always found: Drake deployed #200, sent a real
invoice to himself, and the invoice looked exactly the same as before.

It was a **third** email shell, and #200 never touched it —
`InvoiceEmailService._build_html_email` built its own `<!DOCTYPE>` in an
f-string: a `#1e40af` header bar, `#2563eb` buttons, a `#f3f4f6` ground, its
own three-column line-item table and its own footer. It read the tenant's
*name*, so the email was shop-named but not shop-branded: the one email that
asks a customer for money was the one email a shop's brand colour never
reached.

It now renders `templates/emails/invoice.html`, which extends `base.html` like
everything else.

**What changed beyond the shell**

- **Line items are label/value rows**, not a three-column table. The vehicle
  rides in the label the way the plain-text half already did it — "Unit 4471 ·
  Windshield Repair" for a fleet, "2019 Ford F-150 · …" for an individual — so
  there is no column header that has to explain what the first column means,
  and it stacks on a phone instead of squeezing three columns.
- **Actions are sentence case** and there is one primary: "Pay invoice —
  $84.75" as the button when the shop can take payment, "View invoice online"
  as the link under it. A shop with no Stripe Connect gets the view as its
  button rather than a dead-end pay button.
- **`html.escape()` is gone from the path.** Django auto-escapes at the same
  boundary; escaping first would print `&amp;lt;`. CODE-232's regression tests
  pass unchanged, and a new test asserts nothing is escaped *twice*.
- **The plain-text half is deliberately untouched.** `_build_email_body` is
  correct and CODE-119/CODE-178 pin its behaviour. It is the one place the two
  halves are still built separately — a known, accepted divergence.

**Two live bugs found on the way**

| | |
|---|---|
| **The shop's own copy was written to nobody** | `BillingConfig.invoice_email_template` (CODE-119) fed the plain-text alternative only. A shop that wrote "we're closed the week of the 4th, call Dana" onto its invoices was writing it to the half almost no mail client shows. It is now the HTML's body paragraphs too — on **both** the one-off path and `_send_batch_invoice_email`, which had the identical defect. |
| **A tenant logo raised RuntimeError** | `_absolute_media_url` imported `django.contrib.sites.models` *outside* its own `try`, and `django.contrib.sites` is not in `INSTALLED_APPS` — so it raised `RuntimeError`, not `ImportError`, and took the whole email with it for any tenant with a logo. Production sets `AWS_S3_CUSTOM_DOMAIN` and returns before the import, which is why this only ever fired locally. Import moved inside the try, in both `_absolute_media_url` and `get_logo_url`. |

**Traps**

- **Three of CODE-119's tests were stale and red before this session** — they
  patch `apps.billing.tasks.send_mail`, and that path moved to
  `send_branded_email()` some time ago. Repointed at the real sender. Check
  what a mail test actually patches before trusting it; a patch on a function
  nobody calls asserts nothing.
- **The CODE-232 fixtures build the tenant as a `MagicMock`**, so
  `tenant.logo` and `tenant.branding_enabled` are both truthy and the branding
  lookup takes its most expensive path. That is what surfaced the logo bug —
  worth keeping rather than tidying into a real tenant.
- `_build_html_email`'s **name and signature are load-bearing**: CODE-181 and
  CODE-232 call it directly. Re-shelling inside it kept both suites honest.

Tests: `tests/test_invoice_email_chassis.py` (21).

## The in-app surfaces (built 2026-08-24, shipped 2026-08-25, PR #206)

The bell and the two notification-history pages, onto the same parts as the
emails. The design canvas' `Bell.dc.html` / `History.dc.html` artboards are the
spec; this followed them.

**One row, three surfaces.** `templates/components/notification_row.html` is the
row; `notification_list.html` groups it under day headings; `notification_icon.html`
is the 32 px tinted tile; `notification_filters.html` is the segmented filter.
`core/templatetags/notifications_ui.py` holds the one tone table — category →
icon, tint, short label — plus the time filters. The canvas' line was that the
history row is the dropdown's row with two extra columns, so moving between them
feels like zooming rather than navigating; that only stays true if it is literally
the same include, which it now is.

**What stays split, and why.** The doc asked whether the two history pages should
share a component. The *row*, *filters* and *pagination* now do. The page chrome
does not: the URLs differ, and the two audiences differ (a customer has no
technician preference screen). That is the same platform-vs-shop line the email
work drew — share the parts, not the page.

**Unread is one signal.** It was three at once in the bell (a tinted row, a "New"
pill, a bold title) and four on the history page (plus a `border-left: 4px solid`
stripe that read as an error state). Now it is a 6 px brand dot in a gutter that
is always reserved, so a row does not reflow when the dot clears.

### Five live bugs on the way

| | |
|---|---|
| **The poll ate its own click handlers** | The 30-second poll did `listContainer.innerHTML = html`. The click-to-mark-read handlers were bound once at page load with `querySelectorAll('.notification-item').forEach`, so **after the first tick, clicking an unread notification silently stopped marking it read** — for the entire rest of the session. Handling is delegated to the list container now, so rows survive any re-render. |
| **The poll interpolated notification text into innerHTML** | The same rewrite built rows from a JS template literal: `${notification.title}`, `${notification.message}`, and `${notification.action_url}` into an href — raw. Those strings carry customer names, vehicle descriptions and shop-authored copy. The endpoint now returns HTML rendered from the shared partial, so it arrives Django-escaped and there is no second copy of the row markup to keep in step. |
| **Technician mark-all-read never invalidated its cache** | `mark_all_read` uses a queryset `.update()`, which fires no `post_save` — so CODE-234's invalidation signal never ran for it. The badge went to zero on click and **bounced back to the stale count on the next poll**, for up to the 120-second TTL. The customer portal's equivalent had always cleared its own key; the technician one never did. The key now has one owner, `_unread_cache_key()`. |
| **The customer's notification history was Bootstrap** | `list-group` / `card-body` / `form-select` / `page-link` / `bg-light` / `alert-info` / `col-md-4` — on an app that has never shipped Bootstrap. Almost none of it resolves to a rule in `style.css` or `app.css`, so the page rendered as browser defaults: a bare select, a bulleted pagination list, and **no unread treatment at all**. Its technician twin was a proper Tailwind page the whole time. Rebuilt on the shared parts. |
| **Tailwind was purging the tone tables** | `tailwind.config.js` scanned `templates/`, `apps/**/templates/` and `static/js/` — not `.py`. The colour tables in `core/templatetags/` are Python strings, so the purge could not see them. `bg-yellow-200` — the background of the **"Customer Requested" status pill**, the first status every job passes through — was genuinely absent from the built `app.css`. Added `./core/templatetags/*.py` to `content`. This one predates the notification work and affects `ui.py` app-wide. |

### Smaller corrections

- **"0 minutes ago"** is what `timesince` renders for anything under a minute —
  i.e. on the notification you are most likely to be looking at. The bell now
  uses `short_age` ("Just now", "9m", "1h", "3d"); the history page uses absolute
  clock times under a day heading, because a record you search is not a feed.
- **The history pages defaulted to unread-only.** The bell's footer says "View
  all notifications" and then landed on a page filtered to unread, so a tech
  looking for the assignment they read this morning found an empty page. Default
  is now everything; unread is a segment. `?show_read=false` still works.
- **The bell only has server context on two pages.** `get_notification_context()`
  has exactly one caller, and the technician dashboard has its own — so on every
  other page the bell shipped empty and stayed empty for a full 30 seconds. It now
  renders a neutral placeholder (never "You're all caught up", which would be a
  false statement) and polls once immediately. `bell_prefetched` marks the two
  contexts that are real.
- `aria-expanded` was never updated, and Escape did not close the panel. Both do now.
- The poll skipped its update when the payload was empty, so a list that had just
  been emptied stayed on screen. The endpoint always returns rendered HTML.

### Traps

- **An empty `href` is not "the current page".** `{% querystring %}` renders the
  empty string when it drops every param, and an empty href resolves to the
  current URL *including its query string* — so the "All" segment was a no-op from
  every other segment. Caught in review of the first render, not by a test.
  Falls back to `request.path`.
- **Tailwind's content globs are the whole safelist question.** The existing
  `safelist` entries in `tailwind.config.js` exist because a class appears only in
  JS or only in an `@layer`. A class that appears only in a **`.py` tone table**
  has the same problem and no entry — and unlike a missing `@layer` class, it fails
  silently as a pill with no background rather than an obviously unstyled element.
  `tests/test_notification_surfaces.py` now asserts every class in `ui.py`'s and
  `notifications_ui.py`'s tables is present in the built `app.css`.
- **Do not write a PR number you have not been given.** This section was first
  drafted claiming PR #205. The PR did not exist yet — 205 was the *next* number,
  and by the time the work was picked up again a parallel session had opened and
  merged an unrelated SMS fix as #205. A doc that names the wrong PR sends the
  next reader to somebody else's diff. Open the PR, then stamp the number `gh`
  hands back.
- **`created_at` is `auto_now_add`**, so a test fixture cannot backdate it on
  `create()`. Only a `queryset.update()` can — which is also why the day-grouping
  and short-age tests need one.
- **A held payload is a stale payload.** "Don't rewrite the list while the panel
  is open" and "mark rows read optimistically" are each right and together they
  bite: the held HTML was fetched *before* the click, so applying it on close put
  the dots back on rows the reader had just cleared. Any local read-state change
  has to drop the held payload (`invalidateHeldPayload()`) and let the next poll
  re-sync. Found by driving the real bell in a browser, not by reading it — the
  window is 30 seconds wide and only opens if you mark something read with the
  panel open.

Tests: `tests/test_notification_surfaces.py` (43), green 2026-08-25, along with
the 59 in the four email-chassis suites and the 22 in CODE-234/CODE-087, which
cover the cache key this PR gave one owner.

**The documented test credentials do not work on a fresh machine.** "Running
Tests" above prints a `LOCAL_DATABASE_URL` for an `amelia_test` Postgres role;
that role does not authenticate here, and `.env` sets `LOCAL_DATABASE_URL` to
`sqlite:///db.sqlite3`. These runs are SQLite. Nothing in this PR is
backend-specific, but a suite that touches raw SQL or Postgres-only fields needs
the real thing — and note the local Postgres 16 launchd daemon
(`/Library/LaunchDaemons/postgresql-16.plist`) is not loaded at boot, so `pg` is
simply down until someone loads it.

## Still open

- **The message copy sweep.** The canvas has a third in-app artboard,
  `InAppCopy.dc.html`, that rewrites the notification *titles and messages*
  themselves — the strings built in `signals.py` and the seeded templates, not the
  chrome around them. Untouched here: it is a content pass over the notification
  templates, not a UI one, and it wants Drake's eye on the wording.
- **The invoice's plain-text half** is still built in Python
  (`_build_email_body`) rather than rendered from the same context as the HTML.
  Accepted, not forgotten: it is correct today and two bug-fix suites pin it.
  If the two ever disagree, this is why.
- **Safe drive-away time** is deliberately not implemented. Estimating cure
  time on a shop's behalf is a liability question, not a design one — Drake's
  call, 2026-08-24. Do not add it without him.
- **Emoji in staff-only surfaces**: `technician_portal/admin.py`,
  `billing/admin.py` and `process_billing.py` still carry them in admin action
  labels and command output. Same sweep, no customer impact.
- **#202 shipped late on 2026-08-24, riding another branch's deploy.** For most
  of that day this section read "merged and still not deployed" — true when
  written (16:20 CDT: `eb status` reported `app-4668a-…`, a *pre-merge* commit
  carrying none of #202/#203/#204). It stopped being true at 22:48 CDT, when the
  #205 session deployed `68dc31e9` and swept all four in behind it. Re-verified
  2026-08-25 08:30 CDT: `eb status rs-systems-production` reports
  `app-68dc-260824_224726507237`, and `git merge-base --is-ancestor` confirms
  `68dc31e9` contains #202, #203 and #204. The branded invoice is live.

  The lesson is not about #202. **In a repo running parallel sessions, "merged
  but not deployed" has a shelf life measured in hours** — someone else's
  deploy ships your commits without telling you, and a deploy claim written into
  a doc rots faster than anything else in it. Date-stamp it, and re-run
  `eb status` before repeating it rather than reading it forward.

---

# Where this stands — 2026-08-25, 20:50 CDT

Written after S11 and S12 closed Phase 3's design work. Nothing was built in this pass;
it is a state check, and it exists because the last one found that a doc's claims about
*merged* and *deployed* rot at very different speeds.

## Merged is not deployed — again

**S11 (#210) and S12 (#209) are on `main` and are not on production.**

```
$ eb status rs-systems-production
  Deployed Version: app-0f9d-260825_141159999225        # 0f9d062d — PR #208, 09:54 CDT
$ git merge-base --is-ancestor 496b83a9 0f9d062d ; echo $?
  1                                                      # #210 not contained
```

`0f9d062d` is the email-chassis quality pass. Everything merged after 14:11 CDT that day
— #209, #210, then #211, #212, #213, #214, #215 — is sitting on `main` waiting for
somebody's deploy. Drake's call on 2026-08-25 was to leave it: record the gap and let the
next arc's deploy sweep it in, exactly as #205's deploy swept in #202/#203/#204.

So this section is a **dated snapshot, not a status**. Do not read it forward. If you are
here to find out whether the skeletons are live, run `eb status` — the answer has probably
changed, and the way it changes is that someone else ships it without telling you. That is
the second time this arc has recorded this. It is the normal behaviour of a repo running
parallel sessions, not an incident.

## This file no longer owns its own surfaces

When Phase 1 started, UI magic was the only arc touching templates. It is now one of three
live queues in this repo, and the other two edit pages this doc redesigned:

| Arc | Queue | Landed 2026-08-25 | UI_MAGIC surfaces it touched |
|---|---|---|---|
| Photo-ML | `PHOTO_ML_SESSIONS.md` | P1 (#211), P2 (#215) | `job_form.html`, `repair_form.html` (S7), `repair_detail.html`, `base_app.html` |
| FieldOps | `FIELD_OPS_SESSIONS.md` | S9 (#213), S10 (#214) | `schedule.html`, `base_app.html`, `quick_job_modal.html` |

Consequences worth acting on rather than just noting:

- **A "DONE" here means done on the day it merged.** S7 flattened the job/repair form;
  two sessions have since added crop controls and a multi-break flow to it. The design
  rules held — nothing reintroduced the green header or the ALL-CAPS tiles — but the
  session notes describe a page that no longer exists exactly as described. Re-read the
  template before trusting a Phase 2 note about its markup.
- **The rules only hold because they are in `CLAUDE.md`.** No one on the Photo-ML or
  FieldOps sessions read this file. They stayed inside the design system because the
  brand tokens, the motion primitives and the S11 helpers are documented where a fresh
  session actually looks. **Anything in this doc that other arcs must obey belongs in
  `CLAUDE.md`, and this doc is the reasoning behind it, not the source of it.** S13 will
  live or die on this.
- **Debt accrues from arcs that never opened this file.** Five new `fas` icons on
  2026-08-25 (see S13). Nobody did anything wrong; the alternative did not exist yet.

## What is actually left

| # | Session | Size | Why it is still here |
|---|---|---|---|
| S13 | Icon migration | M | **The tag shipped 2026-08-26 (S13a, PR #223).** What is left is the sweep of ~1,300 `<i class="fas">` and then deleting the vendored FA files — mechanical, no longer a race |
| S14 | Landing: real product imagery | M | Blocked on nothing, and its brief needed a correction this pass — the mock's drift changed shape on its own. See S14 |
| S15 | Landing: trust bar rewrite | S | Copy, not code. Wants Drake's eye, like the `InAppCopy` sweep below |
| S16 | Landing: rhythm + dark section | M | **The `[data-reveal]` half is done — S16a, PR #235.** What is left is the redesign, and it wants Drake on the promise copy |
| CSP | Strict Content-Security-Policy | S–M | **Newly unblocked.** S17 took the last inline `<style>` that had to carry a font declaration; S1 removed every third-party asset host. The allowlist is self + Stripe + Turnstile |

~~**If you want the cheapest real win:** S17, or the `[data-reveal]` deletion split out of
S16.~~ — **both done, both merged 2026-08-31** (S17 is PR #233, the deletion is S16a /
PR #235). ~~If you want the one that stops getting more expensive: the `{% icon %}` tag.~~
— taken 2026-08-26, see S13a / PR #223. **What is cheapest now is the strict CSP**, which
S17 unblocked. Phase 4 is the only chunk that is genuinely a project rather than a session.

## Re-dating the Still-open list

Re-checked 2026-08-25 20:50 CDT, all four still open and unchanged: the `InAppCopy`
message-copy sweep (still wants Drake's wording), the invoice's Python-built plain-text
half (still correct, still pinned by two suites), safe drive-away time (still Drake's
call, still do not add it without him), and emoji in the three staff-only surfaces. The
fifth entry — #202's deploy — is closed and correct as written; leave it, it is the
worked example this section's first half depends on.

---

# Where this stands — 2026-08-26, S13a (PR #223)

Everything Phase 3 had open on 2026-08-25 is now merged: **#206** (14:09), **#209** (19:11),
**#210** (22:19) and the state pass **#216** (2026-08-26 18:30). This arc had nothing open
when this session started.

## The thing the last pass predicted, happening

#216 argued the icon count was a burn-up rather than a constant, and that the tag therefore
had to ship before the migration. Checked at the top of this session: `origin/main` had not
moved (1,303 `fas`, 14 `far`) — but **PRs #220 and #221 held eight more `fas` between them,
unmerged**, from the job-queue arc. The prediction was right and it was right *within a day*.
Worth keeping as a template: a debt claim is only actionable once you can point at the rate,
and the rate lives in the open PRs, not in `main`.

## What shipping-before-migrating actually bought

Nothing in the app changed. That is the point, and it is the part that will look like an
under-delivery to whoever reads the diff without the argument: 70 icons, a tag, a CSS rule,
21 tests, two doc entries, and **zero** call sites converted. What it bought is that S13 is
now a mechanical sweep against a target that has stopped moving, instead of a race against
three arcs that have never opened this file.

## Verify by looking, not by asserting

Two of the seventy icons were wrong in ways no test could express, and both were found by
putting them on a screen: `car` drawn from the wrong angle (and mushy at list-row size), and
a `$` inside a document that dissolves into a smudge at 16px. **A test suite can hold an
icon set to its rules; only a contact sheet can tell you an icon is unreadable.** Both
sheets — the 70-icon grid and the side-by-side against the real vendored Font Awesome at
five font sizes — are worth regenerating before the migration sweep, not just before this PR.

## Still open, re-dated 2026-08-26

Unchanged and still all open: the `InAppCopy` message-copy sweep, the invoice's Python-built
plain-text half, safe drive-away time (still Drake's call), and emoji in the three staff-only
surfaces. S14/S15/S16 and S17 are exactly where #216 left them; **S17 and the `[data-reveal]`
deletion are still the two cheapest real wins on the board.**

---

# Where this stands — 2026-08-27, S17

`origin/main` was clean and had **no open PRs** when this session started: #229 landed the
S13b reland, #230/#231 fixed and then CI-guarded the duplicate `0061` merge node, #232
landed the photo-ML work. S17 was the smallest thing on the board and it is done.

## The backlog after this pass

| # | Session | Size | Where it stands |
|---|---|---|---|
| S13 | Icon migration sweep | M | The tag shipped (S13a, #223) and the chrome went with S13b (#229). What is left is the ~1,300-call-site sweep and deleting the vendored FA files |
| S14 | Landing: real product imagery | M | Unblocked, unstarted |
| S15 | Landing: trust bar rewrite | S | Copy. Wants Drake's eye |
| S16 | Landing: rhythm + kill `[data-reveal]` | M | **The `[data-reveal]` deletion is now the cheapest real win on the board** — small, strictly an improvement, does not need the redesign half |
| — | Strict CSP | S–M | Newly unblocked in full; see the S17 section |

## Two things this session found that nobody was looking for

**A committed build artifact drifts silently.** `static/css/app.css` was stale on `main`
— `.pt-2\.5`, referenced by a template since 2bbaac1b. Nothing catches this: CI cannot
compile because `bin/tailwindcss` is gitignored by design, and the one test that compares
source to build does it against a hand-written list of four declarations. Any session that
runs `./scripts/build_css.sh` should read the resulting diff, because anything in it beyond
that session's own changes is a rule that has not been shipping. This is the same shape as
the icon-debt argument in #216: the cost accrues from arcs that never open this file.

**"Forgiving" storage is forgiving about one specific thing.** Worth knowing before the CSP
work leans on the same recipe: `ForgivingManifestStaticFilesStorage` relaxes manifest
*lookups* at request time, not collection. A broken `url()` still refuses to collect, in
production settings exactly as in strict ones. The Verification recipe's step 2 is a real
gate, not a formality.

## Still open, re-dated 2026-08-27

All four unchanged and still open: the `InAppCopy` message-copy sweep (still wants Drake's
wording), the invoice's Python-built plain-text half (still correct, still pinned by two
suites), safe drive-away time (still Drake's call, still do not add it without him), and
emoji in the three staff-only surfaces.
