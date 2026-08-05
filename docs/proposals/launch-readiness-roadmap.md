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
| 1 | Conversion funnel & plans surfaces (landing, /pricing/, signup, login, My Plan) | built — PR open, awaiting Drake review + deploy | 2026-08-05 | branch `feature/funnel-plans-overhaul` |
| 2 | First-run experience (OnboardingState, checklist, tours, /help/ pages, video slots) | not started | | |
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

## Known Defects Being Fixed in Phase 1

- My Plan page contradicts itself 3×: "permanent Professional plan" banner + "Current Plan: Starter $49/mo, Active, Cancel" + grid marking Pro current. Root: mixed reads of `tenant.plan` (char) vs `tenant.subscription_plan` (FK).
- Pricing matrix shows "Customer portal: —" for every plan (missing `customer_portal` key in `seed_plans.py` features) while landing cards hardcode it as included.
- Pricing support row promises "Email & chat / Priority / Dedicated" — none exists.
- Signup: `novalidate` + only first error shown; no password rules up front; no phone; decorative plan choice (duplicate "undecided" options, no `?plan=` passthrough); render-not-redirect on success (refresh re-POSTs); `fail_silently=True` confirmation email; raw exception leak via SignupError; sitemap advertises `/register/` (404).

## State for Next Session

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
- PR NOT merged/deployed — Drake reviews visuals first. After deploy: `seed_plans --force` in prod, then re-check live /pricing/ matrix + My Plan on rsadmin.

### Gotchas discovered
- `rsadmin` (Rockstar Windshield Repair) is the platform-owner tenant in prod — its My Plan page is the worst-case rendering; test platform-owner display with it.
- After deploying Phase 1, run `python manage.py seed_plans --force` in prod to pick up the new `features` keys, then re-check the live pricing matrix.

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
