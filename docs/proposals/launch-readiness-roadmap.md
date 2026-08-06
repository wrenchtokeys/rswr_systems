# Launch Readiness Roadmap (Funnel → First-Run → Support)

Status: IN PROGRESS · Owner: Drake · Started: 2026-08-05

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
| 2 | First-run experience (OnboardingState, checklist, tours, /help/ pages, video slots) | **BUILT 2026-08-05** — PR #144 open, pending merge/deploy | 2026-08-05 | PR #144 |
| 3 | Support (/help/contact/ → SES → admin) + pre-marketing checklist | not started | | |

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

## Known Defects Being Fixed in Phase 1

- My Plan page contradicts itself 3×: "permanent Professional plan" banner + "Current Plan: Starter $49/mo, Active, Cancel" + grid marking Pro current. Root: mixed reads of `tenant.plan` (char) vs `tenant.subscription_plan` (FK).
- Pricing matrix shows "Customer portal: —" for every plan (missing `customer_portal` key in `seed_plans.py` features) while landing cards hardcode it as included.
- Pricing support row promises "Email & chat / Priority / Dedicated" — none exists.
- Signup: `novalidate` + only first error shown; no password rules up front; no phone; decorative plan choice (duplicate "undecided" options, no `?plan=` passthrough); render-not-redirect on success (refresh re-POSTs); `fail_silently=True` confirmation email; raw exception leak via SignupError; sitemap advertises `/register/` (404).

## State for Next Session

### What's done (Phase 2, 2026-08-05 — branch `feature/first-run-experience`)
- `OnboardingState` model (tenants migration 0022): OneToOne on Tenant, `get_for_tenant` lazy-create; `wizard_step`, `wizard_completed_at`, `checklist_dismissed_at`, `trial_banner_dismissed_at`, `tours_completed` JSONField.
- Wizard persisted: `onboarding_view` reads/writes the model (session state removed); dashboard shows "Finish setting up (step N of 4) → Resume" only when started-and-abandoned (step 1–3, not completed) — existing shops at step 0 never see it. Progress bar got transition/scale polish.
- Unified checklist: `_setup_checklist_items()` + `templates/components/setup_checklist_items.html` render the SAME item grid on dashboard and Settings; dashboard card has progress bar + persisted Dismiss. Old `setup_steps` context kept but always empty (CODE-110 tests still pass, one updated to the new mechanism).
- Persisted dismiss endpoints: `/owner/checklist/dismiss/`, `/owner/trial-banner/dismiss/`, `/owner/tours/<slug>/complete/` (unknown slug 404s, slugs listed in `TOUR_SLUGS`). Generic `data-dismiss-post`/`data-dismiss-target` handler + `UI.csrfToken()` added to ui.js (reads the form input — csrftoken cookie is HttpOnly in prod).
- Tours: driver.js v1.3.6 vendored (`static/js/vendor/driver.iife.js`, CSS in a marked block in input.css + brand overrides); `static/js/tours.js` auto-starts off server-injected `data-tour` attr, filters hidden/missing anchors, POSTs completion on destroy. Tours: owner-dashboard (7 steps), job-form (6 steps).
- `apps/support`: registered in base.py, `/help/` URLs; 5 guide pages from USER_FLOWS/MULTI_BREAK content + index; `components/video_slot.html` "coming soon" placeholders; Help link in #app-dropdown + mobile nav (owners AND techs).
- Tests: `tests/test_first_run.py` (22 tests) all green; regression run green (test_step3_signup, test_e2e_today, test_primary_contact, test_owner_setup, test_code110, test_signup_ux — 131 tests).
- Verified in browser (fresh tenant): tour auto-starts → skip → never returns; both dismissals survive reload; resume banner correct; help pages render; Settings/dashboard checklists identical. `build_css.sh` run, app.css committed.

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

## Pre-Marketing Checklist (execute in Phase 3, before ads)

- [ ] `eb printenv` shows `SENTRY_DSN` set (without it, 500s reach no one)
- [ ] `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` set in EB (Turnstile is skipped when unset; fails open on network error — ratelimit 5/h is the backstop). Decide: flip to fail-closed?
- [ ] SES out of sandbox, quota adequate: `python manage.py test_ses wdrakeduncan@gmail.com`
- [ ] Live sitemap serves `/signup/` and `/pricing/` (Phase 1 fix deployed)
- [ ] ADMINS email deliverable (signup + support notifications land in Drake's inbox)
- [ ] Prod plans re-seeded (`seed_plans --force`) so pricing matrix shows Customer portal ✓
