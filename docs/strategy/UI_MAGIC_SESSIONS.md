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
| 2 | S7 · Job/repair form: drop the green header and ALL-CAPS section tiles | **DONE** 2026-08-10 |
| 2 | S8 · Retire the second accent everywhere else (FAB, black pills) | **DONE** 2026-08-10 |
| 3 | S9 · Motion primitives: press feedback + enter/exit | **DONE** 2026-08-10 |
| 3 | S10 · View Transitions for list → detail continuity | **DONE** 2026-08-11 |
| 3 | S11 · Skeletons and optimistic status changes | TODO |
| 3 | S12 · Auth pages: one brand mention, full-height, no marketing nav | TODO |
| 3 | S13 · Icon language: Font Awesome solid → line-weight SVG sprite | TODO |
| 4 | S14 · Landing: real product imagery instead of the fake mock | TODO |
| 4 | S15 · Landing: trust bar rewrite | TODO |
| 4 | S16 · Landing: rhythm, dark section, sharper promise | TODO |
| — | S17 · Stop shipping the Tailwind source to production | TODO |
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

Tests: `tests/test_notification_surfaces.py` (40).

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
