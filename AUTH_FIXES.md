# Auth & Signup — Required Fixes

Second pass of auth hardening, completed 2026-07-08 (follows the 2026-07-07
audit that fixed the login rate-limiter no-op, the API signup bypass, the
duplicate-email 500, the unconfirmed-login error message, and the
confirmation-link double-click). All items below are implemented and tested
(292 tests across tenants, customer portal, auth, security, signup, routing,
and smoke suites — one pre-existing unrelated failure in
`TenantIsolationTest.test_customer_data_isolated`, present on clean tree).

## Completed in this pass

- [x] **1. Retired DRF token authentication.** `TokenAuthentication` removed
  from `REST_FRAMEWORK` (`rs_systems/settings/base.py`). Nothing issues
  tokens anymore, but tokens minted by the old unauthenticated API signup
  never expired — they are now inert. Session auth serves the portals/API.

- [x] **2. Rate-limited password reset.** `RateLimitedPasswordResetView`
  (`rs_systems/views.py`) enforces 5 POSTs/IP/hour on `/password-reset/` and
  `/admin/password_reset/` — stops email-bombing and SendGrid quota burn.
  The reset template now renders real error messages.

- [x] **3. CAPTCHA on customer self-signup.** `/join/<slug>/` runs the same
  Turnstile gate as owner signup (`shop_join_view` + `shop_join.html`).
  Still a no-op when `TURNSTILE_*` env vars are unset (dev/CI).

- [x] **4. Clarified the plan question on signup.** Marked optional with
  "every account starts with a free 30-day trial, no credit card required"
  copy. Field kept — it drives the owner-dashboard trial banner and the
  day-20 nudge email.

- [x] **5. "Remember me" on login.** Sessions now expire at browser close by
  default (shop computers are often shared); the checkbox opts into 30 days.

## Deferred (needs product decisions / bigger lift)

- **Two-factor auth (TOTP)** for owner/manager accounts — needs django-otp,
  enrollment UX, and recovery codes. Worth doing before shops store more
  customer PII.
- **Consolidate signup entry points** — owner `/signup/`, customer
  `/join/<slug>/`, and invite links are three separately-styled flows.
  Visual/copy unification pass.
- **Turnstile fails open** on Cloudflare network errors (deliberate: a
  Cloudflare outage shouldn't block signups). Revisit if bot signups appear.
