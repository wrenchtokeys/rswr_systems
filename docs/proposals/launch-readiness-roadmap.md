# Launch Readiness Roadmap (Funnel → First-Run → Support)

Status: **COMPLETE** — all three phases merged and deployed · Owner: Drake · Started: 2026-08-05 · Closed: 2026-08-11

> Kept for the design charter and decisions log below; there is **no open work** in this document.
> The pre-marketing checklist it tracked is done (`SENTRY_DSN` set + verified 2026-08-09, SES,
> Turnstile, sitemap).

Three phases, **each executed in its own fresh Claude session**. This doc is the handoff between sessions: read it top-to-bottom before starting any phase. Goal: the entire prospect-to-customer journey feels Apple-quality before Google/Facebook ads + SEO spend begins.

## Design Charter (applies to every phase)

- **No jargon a shop owner wouldn't say.** No "MB storage", no "API access" on customer-facing cards — translate to benefits or drop.
- **Never promise what doesn't exist.** Support tiers say "Email support" until the support system (Phase 3) ships. No fabricated-feeling stats.
- **One source of truth per fact.** Plan facts render from `SubscriptionPlan` rows through `templates/components/plan_card.html` — never hand-copied per page.
- **Consistent CTAs.** Public: "Start Free Trial". Signed-in plan grid: "Choose <Plan>".
- **Motion & feel.** Tailwind-only polish: hover lift + soft shadows, smooth transitions, focus rings, scroll-reveal (tiny IntersectionObserver in `ui.js`), celebration moments at milestones (email confirmed, first job, first invoice).
- **Plain, warm microcopy** in Drake's founder voice (the landing testimonial sets the tone).

## Phase Status

| Phase | Scope | Status | Session date | Commits/PR |
|-------|-------|--------|--------------|------------|
| 1 | Conversion funnel & plans surfaces (landing, /pricing/, signup, login, My Plan) | **DEPLOYED to prod 2026-08-05** (PR #143 merged; prod plans re-seeded; live pricing + My Plan verified) | 2026-08-05 | PR #143 |
| 2 | First-run experience (OnboardingState, checklist, tours, /help/ pages, video slots) + help-center backlog (FAQ, search, role-aware guides, /app/help/, GuideFeedback) | **MERGED + DEPLOYED 2026-08-06** (PR #144) | 2026-08-05/06 | PR #144 |
| 3 | Support (/help/contact/ → SES → admin) + pre-marketing checklist | **MERGED + DEPLOYED 2026-08-06** (PR #146) | 2026-08-06 | PR #146 |

## Decisions Log

- 2026-08-05: Three phases in fresh sessions, coordinated via this doc (Drake).
- 2026-08-05: Support = in-app help + email to Drake; no third-party chat, no full ticket system (Drake).
- 2026-08-05: Tutorials = getting-started checklist + interactive tours + in-app help pages + video slots for later (Drake — all four).
- 2026-08-05: Quality bar raised to "Apple-level magic" across landing, signup, sign-in, plan cards, My Plan (Drake — he explicitly dislikes current plan cards + My Plan page).
- 2026-08-05: Optional phone field added at signup rather than softening the dashboard nag (`create_tenant_with_owner` already accepted `phone`).
- 2026-08-05: `/pricing/` kept as a standalone page (better ads landing target) and linked from landing nav.
- 2026-08-05: Phase 2 will vendor driver.js v1.x (MIT, ~5 kB) for tours rather than hand-rolling.
- 2026-08-05: Phase 2 creates `apps/support` (help pages Phase 2, contact model Phase 3) — keeps saas/views.py from growing.
- 2026-08-05 (P2): "Your First Customer" added as a checklist item (`_setup_completion` gained `customers`; counts are now 7, or 8 with resin rules) — replaces the old dashboard-only `setup_steps` card so dashboard and Settings can never disagree.
- 2026-08-05 (P2): Trial-banner dismissal is persisted BUT urgent states (expired / ≤7 days) re-surface the banner regardless — losing "trial ends Friday" to a week-old dismissal is worse than the nag.
- 2026-08-05 (P2): Tours are owner/manager-gated and per-TENANT (tours_completed lives on OnboardingState); skip = complete, never re-nag. Two tours shipped: owner-dashboard, job-form.
- 2026-08-05 (P2): Help pages live at /help/ (login required, owner + tech). "Still stuck?" box emails contact@rssystems.io — becomes the /help/contact/ form in Phase 3.
- 2026-08-06 (P3): `/help/` added to the subscription middleware's EXEMPT_PREFIXES — a shop whose trial just expired is exactly who needs guides + the contact form, and grace-period tenants must be able to POST it.
- 2026-08-06 (P3): SupportMessage is record-first (row saved before the notification email is attempted; `emailed_ok=False` marks mail failures to sweep in admin) — same never-lose-it pattern as auto-invoice.
- 2026-08-06 (P3): No ticket system, per Drake's earlier call — replies happen from Drake's inbox (notification carries Reply-To: sender), admin just has a New/Replied/Closed status for triage.
- 2026-08-06 (P3): Success redirect is `?sent=1` + session-stashed reply address — the email never rides in a query string (access logs).
- 2026-08-06 (P3): Contact POST rate-limited 10/h per user (block=False → friendly 429 copy, not an error page). Login-required, so no Turnstile on this form.

## Known Defects Being Fixed in Phase 1

- My Plan page contradicts itself 3×: "permanent Professional plan" banner + "Current Plan: Starter $49/mo, Active, Cancel" + grid marking Pro current. Root: mixed reads of `tenant.plan` (char) vs `tenant.subscription_plan` (FK).
- Pricing matrix shows "Customer portal: —" for every plan (missing `customer_portal` key in `seed_plans.py` features) while landing cards hardcode it as included.
- Pricing support row promises "Email & chat / Priority / Dedicated" — none exists.
- Signup: `novalidate` + only first error shown; no password rules up front; no phone; decorative plan choice (duplicate "undecided" options, no `?plan=` passthrough); render-not-redirect on success (refresh re-POSTs); `fail_silently=True` confirmation email; raw exception leak via SignupError; sitemap advertises `/register/` (404).

## State for Next Session

### What's done (Phase 3, 2026-08-06 — branch `feature/support-contact`)
- `SupportMessage` model (support migration 0002): tenant/user SET_NULL + name/email snapshots so deletions never orphan a message; topic (question/problem/billing/idea/other), message, page (referrer via hidden input), status (new/replied/closed), `emailed_ok`, created_at.
- `/help/contact/` (`help_contact`): login-required GET/POST, PRG to `?sent=1` success card; reply email prefilled from the account and overridable; record-first then EmailMessage → `settings.ADMINS` with Reply-To sender and a deep link to the admin change page; failures logged, row kept with `emailed_ok=False`.
- `templates/support/contact.html`: topic radio pills (peer-checked styling), textarea, reply-email field, success card echoing the address; matches help-center design.
- Admin: `SupportMessageAdmin` (status editable in the list, everything else read-only, no add) alongside GuideFeedback — that's the whole "support console".
- Touchpoints now link the form instead of mailto: help index (no-results + "Still stuck?" card, now a full-card link), guide thumbs-down box, troubleshooting footer, subscription-blocked owner card. Public/unauthenticated pages (404/500, landing, terms, payment returns) keep mailto by design.
- Middleware: `/help/` in EXEMPT_PREFIXES (see decision).
- Tests: `tests/test_support_contact.py` (13) + regression (test_first_run, test_subscription_expiry, test_code130, test_e2e_today, test_primary_contact — 160 total) all green.

### Phase 3 pre-marketing checklist findings (2026-08-06, read-only prod checks)
- ❌ `SENTRY_DSN` NOT in `eb printenv` — 500s currently reach no one. **Blocked on Drake**: create the Sentry project (or say the word and Amelia sets it up), then `eb setenv SENTRY_DSN=...` — remember the confighook/static-files gotcha means setenv triggers a redeploy.
- ✅ Turnstile keys set in EB. Open decision for Drake: flip to fail-closed? (Currently fails open on network error; 5/h ratelimit is the backstop.)
- ✅ SES: `ProductionAccessEnabled: true`, healthy, 50k/day quota, 14/s send rate — plenty.
- ✅ Live sitemap serves `/signup/` + `/pricing/` (Phase 1 fix confirmed deployed).
- ✅ Prod plans re-seeded (done in Phase 1).
- ◻ ADMINS deliverability: `ADMIN_EMAIL` unset in EB so base.py default (wdrakeduncan@gmail.com) applies — signup notifications have been arriving, and the first real contact-form submission after deploy is the end-to-end proof. (`DJANGO_ADMIN_EMAIL=admin@example.com` in EB is a different, unused-for-ADMINS var — ignore or clean up.)

### What's done (Phase 2, 2026-08-05 — branch `feature/first-run-experience`)
- `OnboardingState` model (tenants migration 0022): OneToOne on Tenant, `get_for_tenant` lazy-create; `wizard_step`, `wizard_completed_at`, `checklist_dismissed_at`, `trial_banner_dismissed_at`, `tours_completed` JSONField.
- Wizard persisted: `onboarding_view` reads/writes the model (session state removed); dashboard shows "Finish setting up (step N of 4) → Resume" only when started-and-abandoned (step 1–3, not completed) — existing shops at step 0 never see it. Progress bar got transition/scale polish.
- Unified checklist: `_setup_checklist_items()` + `templates/components/setup_checklist_items.html` render the SAME item grid on dashboard and Settings; dashboard card has progress bar + persisted Dismiss. Old `setup_steps` context kept but always empty (CODE-110 tests still pass, one updated to the new mechanism).
- Persisted dismiss endpoints: `/owner/checklist/dismiss/`, `/owner/trial-banner/dismiss/`, `/owner/tours/<slug>/complete/` (unknown slug 404s, slugs listed in `TOUR_SLUGS`). Generic `data-dismiss-post`/`data-dismiss-target` handler + `UI.csrfToken()` added to ui.js (reads the form input — csrftoken cookie is HttpOnly in prod).
- Tours: driver.js v1.3.6 vendored (`static/js/vendor/driver.iife.js`, CSS in a marked block in assets/css/input.css + brand overrides); `static/js/tours.js` auto-starts off server-injected `data-tour` attr, filters hidden/missing anchors, POSTs completion on destroy. Tours: owner-dashboard (7 steps), job-form (6 steps).
- `apps/support`: registered in base.py, `/help/` URLs; 5 guide pages from USER_FLOWS/MULTI_BREAK content + index; `components/video_slot.html` "coming soon" placeholders; Help link in #app-dropdown + mobile nav (owners AND techs).
- Tests: `tests/test_first_run.py` (22 tests) all green; regression run green (test_step3_signup, test_e2e_today, test_primary_contact, test_owner_setup, test_code110, test_signup_ux — 131 tests).
- Verified in browser (fresh tenant): tour auto-starts → skip → never returns; both dismissals survive reload; resume banner correct; help pages render; Settings/dashboard checklists identical. `build_css.sh` run, app.css committed.

### Phase 2 round 2 (same day, Drake feedback)
- **Bug fixed:** tours re-appeared on every refresh — completion was only recorded on close, so a mid-tour refresh recorded nothing. Now "shown = seen": tours.js POSTs completion the moment the tour starts. Deliberate replays via `?tour=1` (dashboard + job form), linked as "Interactive tours" cards on /help/.
- **Help center expanded 5 → 14 guides**, grouped into sections (Getting started / Billing & getting paid / Your team / Your customers / Grow your business). New: card-payments, sales-tax, paid-on-time, team-roles, for-technicians, customer-portal, loyalty-referrals, review-requests, warranty. Registry (`HELP_TOPICS` + `HELP_SECTIONS`) drives index, routing, AND the tests (all slugs auto-covered).
- **Contextual help from Settings:** each tab panel (general/team/billing/payments/reviews/warranty) opens with a small "Guides: …" link line to the relevant help pages.
- Statements of account deliberately NOT mentioned in guides — the page exists but isn't linked from any UI (charter: never promise what doesn't exist). Candidate for a future nav link.

### Phase 2 round 3 (Drake: "dismissed card came back on refresh — not the magic feel")
- Root cause of the reappearing cards on Drake's machine: **stale browser-cached JS** — dev static files have no cache-busting, so his Chrome kept running the old ui.js/tours.js whose dismissals were cosmetic. (Reproduced exactly: a `--noreload` dev server ALSO serves stale templates — Django ≥4.1's cached template loader only invalidates via the autoreloader.)
- Fix, three layers so a dismissal can NEVER visibly fail: (1) server record (cross-device), (2) **localStorage** in the browser (`rs-dismissed:<tenant>:<id>`, `rs-tour-seen:<slug>`) written at click/show time — a failed POST, stale script, or dropped network can't resurrect the element, (3) **resync on page load**: if the server renders something this browser already dismissed, it's removed instantly and the POST is re-sent until the server record heals.
- `?v=N` cache-buster on ui.js/tours.js script tags (bump on behavior change; prod is already content-hashed via manifest storage).
- Verified by sabotage test: dismiss all three, wipe the server records, refresh — nothing reappears, and the server records self-heal from the resync POSTs.

### Phase 2 deferred (stretch items not built)
- Invoice-send + settings tours (only the two priority tours shipped).
- Customer-portal help variant; contextual "?" links from settings sections.
- Empty-state component rollout + first-job/first-invoice celebration moments.

### Phase 2 gotchas
- `_setup_completion` gained a `customers` key and the counts changed (6 → 7/8). Anything hardcoding "/6" is wrong (dashboard template updated).
- Owner-dashboard trial banner id stays `trialBanner`; dismissal is server-persisted now — don't reintroduce `display:none`.
- Local Postgres was down again — scratch cluster recipe (memory `test-suite-debt-and-local-postgres`) works; cluster left running on 5432 from this session's scratchpad dir.

### Phase 2 test command
```bash
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development
python manage.py test tests.test_first_run tests.test_step3_signup tests.test_e2e_today -v 1 --noinput
```

### What's done (Phase 1, 2026-08-05)
- `templates/components/plan_card.html` — the ONLY plan-card renderer; consumed by landing #pricing, /pricing/, and My Plan. Benefit-first copy, no MB/API jargon, consistent CTAs ("Start Free Trial" public / "Choose <Plan>" signed in), hover-lift polish.
- seed_plans: `customer_portal: True` + honest `features.support` strings on all 4 plans (**prod needs `seed_plans --force` after deploy**).
- billing_view resolves ONE current plan (`tenant.plan` slug wins over stale `subscription_plan` FK — prod drift from migration 0016); platform owner: no Cancel button/modal, no switch CTAs, "Permanent plan — you'll never be billed".
- /pricing/: Trial card dropped (banner "Every plan starts with a 30-day free trial" instead), comparison table de-jargoned (Job photos ~N, support from plan.features.support).
- Signup: PRG via new `/signup/check-email/` (session `signup_pending`, refresh-safe); confirmation email no longer fail-silent — failure shows amber warning + resend button (reuses existing resend route); optional phone → `Tenant.business_phone`; password rules shown up front; all field errors render + error summary + scroll-to-first-error; `novalidate` removed; plan choice deduped (CharField degrades stale 'not_sure' to undecided); `?plan=` preselect wired from all plan-card CTAs.
- signup_service exception leak fixed (logger.exception + generic user-safe message).
- Landing: scroll-reveal (reduced-motion safe, no-JS safe), hero mockup glow, footer/pricing-section links to /pricing/, structured-data highPrice 249.
- Sitemap: /register/ (404) → /signup/ + /pricing/ added.
- Dashboard checklist: dead "add a technician" item removed; business-info copy updated.
- Tests: `tests/test_signup_ux.py` (22 tests) + 3 updated in test_step3_signup for PRG. 47 targeted + 60 smoke (test_primary_contact, test_e2e_today) all green. `build_css.sh` run, app.css committed.

### What's NOT done / deferred
- Monthly↔annual billing toggle on plan cards (stretch — annual price shown as text line only).
- Login page redesign — already matches the two-panel design language; skipped deliberately.
- Confirm-email celebration is message-copy only (no confetti/interstitial).
- Landing trust-bar stats ("500+ Jobs Tracked", "$50K+ Invoiced") left as-is — Drake should confirm they're accurate before ads.
- ~~PR NOT merged/deployed~~ → **PR #143 MERGED + DEPLOYED 2026-08-05**; prod `seed_plans --force` run (twice — first attempt hit the SQLite-fallback gotcha above); live /pricing/ + My Plan (rsadmin) verified in browser.
- Landing trust-bar stats ("500+ Jobs Tracked", "$50K+ Invoiced") still need Drake's accuracy confirmation before ads.

### Gotchas discovered
- `rsadmin` (Rockstar Windshield Repair) is the platform-owner tenant in prod — its My Plan page is the worst-case rendering; test platform-owner display with it.
- **eb ssh prod-command recipe MUST export the EB env first** — `sudo bash -c 'source /var/app/venv/*/bin/activate && …'` silently runs with `DJANGO_SETTINGS_MODULE=rs_systems.settings.development` → SQLite fallback at `/var/app/current/db.sqlite3`, and management commands report success while touching a throwaway DB. Working recipe:
  `eb ssh rs-systems-production --command "sudo bash -c 'export \$(cat /opt/elasticbeanstalk/deployment/env | xargs) && source /var/app/venv/*/bin/activate && cd /var/app/current && python manage.py <cmd>'"`
- Drake removed the Stripe Connect "Payment Processing" card from My Plan mid-review — My Plan is subscription-only; Connect lives in Settings → Card Payments.
- Phase 1 changes are invisible to a signed-in localhost user on `/` (redirects to dashboard) — view landing/signup logged-out; also re-seed the local DB (`seed_plans --force`) or cards render without the new feature keys.

### Exact test commands that must pass
```bash
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development
python manage.py test tests.test_step3_signup tests.test_signup_ux tests.test_referral_signup_flow -v 2
```

## Help Center Improvement Backlog (proposed 2026-08-05; built 2026-08-06)

Assessment after Phase 2 round 2 shipped 14 guides. Everything code-doable shipped
2026-08-06 (round 3 of PR #144); only the items gated on Drake or Phase 3 remain.

**Bundle 1 — high value, one round of work:**
- [x] **Troubleshooting/FAQ section** — `/help/troubleshooting/`: 10 symptom-first entries (invoice email, missing tax, tech can't see replacements, price ladder surprise, locked price, unpaid-after-payment, review requests, points, undelete, portal login). Own index section "When something looks wrong".
- [x] **Search on /help/** — filter-as-you-type over title/blurb/`keywords` (new registry field), hides empty sections, no-results state with the support mailto. Stretch item (guide matches in top-nav global search) still open.
- [x] **Role-aware index** — `owner_only` flag on HELP_TOPICS (simpler than a roles list: the only split that exists today is owner/manager vs tech); index filters, direct links still work for everyone, "Next up" respects the filter.
- [x] **Two missing guides**: `/help/trial-ending/` and `/help/progressive-pricing/`.

**After that:**
- [x] Customer-portal help page — `/app/help/` (approve, request, invoices, rewards when active, team/notifications), linked from both portal menus.
- [x] "Was this helpful? 👍👎" per guide — `GuideFeedback` model (support migration 0001, one vote per user per guide, re-vote overwrites) + POST `/help/<slug>/feedback/`; thumbs-down reply points at support email. Phase 3 admin surface can read it alongside SupportMessage.
- [x] Guide-to-guide "Next up →" flow within each section.
- [x] More contextual entry points: job form, Invoices page, Loyalty page now carry "Guides:" one-liners.
- [ ] **Videos** — the placeholder slots are built; each page auto-upgrades to a player when its recording exists. ~90 sec each, Drake records (or Amelia scripts + Drake narrates). Biggest single "magic" upgrade available. **Blocked on Drake.**

**Further out / flashier (all still open by design):**
- [ ] Floating "?" help beacon opening guides in a slide-over panel (never lose your place).
- [ ] "Ask a question" box powered by Claude over guide content — only after real support email (Phase 3) shows what people actually ask.
- [ ] Link Statement of Account into the UI, then document it (currently URL-only, kept out of guides per charter).

~~Contact form deliberately stays in Phase 3 where it's planned~~ → **built 2026-08-06** (`/help/contact/`, Phase 3); every in-app mailto touchpoint now links the form instead.

## Pre-Marketing Checklist (executed 2026-08-06 — see Phase 3 findings above for detail)

- [ ] `eb printenv` shows `SENTRY_DSN` set (without it, 500s reach no one) — **NOT SET, blocked on Drake**
- [x] `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` set in EB. Still open: decide fail-open vs fail-closed (Drake)
- [x] SES out of sandbox: production access granted, 50k/day quota, healthy
- [x] Live sitemap serves `/signup/` and `/pricing/` (Phase 1 fix deployed)
- [ ] ADMINS email deliverable — verify end-to-end with the first contact-form submission after Phase 3 deploys
- [x] Prod plans re-seeded (`seed_plans --force`) so pricing matrix shows Customer portal ✓ (done in Phase 1)
