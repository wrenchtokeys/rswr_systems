# Changelog - RS Systems

All notable changes to the RS Systems windshield repair management platform, newest first.

This file merges what used to be two forked changelogs (a root-level one and this one). Going
forward, this is the single canonical changelog — see `docs/README.md`.

## Format
- **Added** for new features
- **Changed** for changes in existing functionality
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes
- **Technical** for internal/infra-only changes

---

## 2026-07-28 — Review requests: production cron + fleet gating

### Added
- **Fleet gating for review requests** — new `ReviewConfig.send_to_fleet`
  (default **off**): automated Google review requests now go only to individual
  (RETAIL / WALK_IN) customers. Fleet accounts are skipped with
  `skip_reason='fleet_disabled'` unless the shop turns on the new
  "Include Fleet Accounts" toggle in Settings → Reviews. The gate is enforced
  when scheduling and re-checked at send time (the toggle may change between
  the two). Migration `technician_portal/0047`.

### Fixed
- **Review request emails were never sent in production** — the
  `send_review_requests` management command existed but had no cron entry, so
  requests queued as `pending` forever. Added
  `.ebextensions/12_reviews_cron.config` (every 20 minutes, logs to
  `/var/log/review-requests.log`). Overlapping runs are safe per CODE-230
  (`select_for_update(skip_locked=True)`).


## 2026-07-12 — Shop-branded emails + replacement-aware customer portal

Deployed to production 2026-07-12 via PR #108 (which also carried the full
2026-07-09 audit remediation A–F to production — see
`docs/development/REMEDIATION_PLAN_2026-07-09.md` for those dispositions).

### Added
- **Customer replacement requests** at `/app/replacements/request/` (URL name
  `customer_request_replacement`). Customers pick the vehicle/unit, which glass
  (windshield, side, rear, sunroof, …), describe what happened, and optionally
  attach a photo. Creates a `Replacement` with `queue_status='REQUESTED'` and
  **no pricing** — the shop confirms the exact glass and sets parts/labor before
  the customer approves. Both request pages now share a "Chip or Crack Repair ↔
  Full Glass Replacement" toggle (`templates/customer_portal/includes/service_type_toggle.html`).
- **Shop notification for replacement requests** — the assigned technician gets
  an in-app `TechnicianNotification` and the owner a tenant-branded email with a
  review link (via `core.email_utils.send_branded_email`). Full replacement
  lifecycle notification templates remain a follow-up.
- Replacement-aware technician assignment: `get_available_technician(tenant,
  service_type='replacement')` prefers `can_replace=True` technicians and falls
  back to any active technician — new shops (whose auto-created owner technician
  has `can_replace=False`) never dead-end.

### Changed
- **Customer dashboard is now service-type aware.** Recent Services merges
  repairs and replacements (type badges, per-type detail links); the
  pending-approval alert includes replacements with approve/deny actions;
  stat cards show combined counts. All previous repair-only context keys are
  preserved for backward compatibility.
- Dashboard greeting is now "Welcome, {name}" (was "Welcome back,
  {first_name}", which greeted brand-new invited users as returning ones and
  rendered blank when `first_name` was empty). Name falls back
  first name → full name → company name; navbar/drawer name displays fall back
  to username.
- Customer portal page titles and invite pages use the tenant's shop name;
  invitation email copy is glass-service-neutral ("vehicle glass service"
  instead of "windshield repairs"); the invalid-invitation page says "contact
  your glass shop" instead of "fleet service provider".
- Mobile bottom-nav Request button opens a repair/replacement chooser sheet.

### Fixed
- **Tenant branding leak in customer-facing email.** The email header, footer,
  and title (`templates/emails/base.html`) rendered `branding.company_name`
  from the platform-wide `EmailBrandingConfig` singleton, so every shop's
  invitations showed the platform-owner tenant's name ("Rockstar Windshield
  Repair"); payment-receipt subjects had the same bug, and the 10 repair
  lifecycle notification emails received **no** branding context at all (blank
  header). New `EmailBrandingConfig.get_tenant_context(tenant)` keeps the
  platform visual identity (colors, fonts) but overrides identity fields
  (name, contact info, logo, footer) with the tenant's. Wired into
  `CustomerInvitationService.send_invitation_email`,
  `NotificationService.create_notification` (auto-derives the tenant from
  repair → customer → recipient), and `PaymentNotificationService.send_customer_receipt`.
  Tests: `tests/test_tenant_email_branding.py`,
  `tests/test_customer_request_replacement.py`,
  `tests/test_customer_unified_dashboard.py`.

---

## 2026-07-11 — Infra: removed unused Redis (ElastiCache)

### Technical
- **Deleted the `rs-systems-redis` ElastiCache cluster** (cache.t3.micro, ~$12/mo). Production caching uses Django `DatabaseCache` (the `django_cache` table), **not** Redis — the `redis` package isn't installed and `CACHES` in `rs_systems/settings/production.py` points at the DB backend. The cluster was unused.
- Removed the now-dead `REDIS_URL` and `REDIS_CACHE_URL` variables from the `rs-systems-production` Elastic Beanstalk environment. They were set but ignored (the app only uses Redis if the package is installed). To reintroduce Redis later, follow the note already in `production.py` (install `redis`, set `REDIS_URL`, recreate the cluster).
- Context: part of a 2026-07 AWS cost cleanup on account `973196283632`. Unrelated to rs-systems, the Rockstar marketing site was migrated off Elastic Beanstalk to AWS Amplify in the same pass; rs-systems infra (EB env, RDS, ALB) was left untouched.

---

## 2026-07-09 — SendGrid → Amazon SES migration

### Changed
- **Email transport is now Amazon SES over SMTP.** `EMAIL_HOST` defaults to `email-smtp.us-east-1.amazonaws.com`; `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` now hold **SES SMTP credentials** (which are *not* an AWS access key pair). The SES account has production access: 50,000 msg/day, 14 msg/sec, domain `rssystems.io` verified and DKIM-signed.
- `EMAIL_RATE_LIMIT` default lowered from `100` to `14` to match the SES per-second ceiling. (Nothing reads this setting today; it is there so a future sender honours the cap.)
- Privacy policy third-party list now discloses Amazon SES instead of SendGrid.

### Fixed
- **Welcome emails would have silently stopped at cutover.** `_send_welcome_email()` returned early unless `os.environ['SENDGRID_API_KEY']` was set — no exception, just a log line. Retiring SendGrid means unsetting that variable, so every new-signup welcome email would have quietly vanished. The credential gate is gone; delivery now goes through the configured backend and failures surface as logged warnings. Regression test: `tests/bug_fixes/test_ses_migration_welcome_email.py`.

### Technical
- Removed dead SendGrid SDK code from `ReminderService._send_email()`. It was gated on `getattr(settings, 'SENDGRID_API_KEY', None)`, but that setting was never defined in any settings module, and the `sendgrid` package was never in `requirements.txt`. The branch could not execute; invoice reminders already went out through Django's SMTP backend. Removal is behaviour-preserving.
- `/clawdbot/` health payload: `integrations.sendgrid` (always `false`) replaced by `integrations.ses`, which reports real credential state. No known consumers.
- `.env.example` previously documented `AWS_SES_HOST` / `AWS_SES_SMTP_USER` / `AWS_SES_SMTP_PASSWORD` as a rollback path. No settings module ever read those names. Replaced with the `EMAIL_*` names that are actually read.
- `docs/DEVELOPER_GUIDE.md` claimed `EMAIL_BACKEND = 'sendgrid_backend.SendgridBackend'`; the SMTP backend has always been the real one. Corrected.

### Follow-ups (not done here)
- Cancel the SendGrid subscription, then drop `include:sendgrid.net` from the `rssystems.io` SPF record (SPF permits only 10 DNS lookups).
- Rotate (better: delete) the **root** AWS access key found in the local `~/.aws/credentials` default profile; it belongs to no IAM user. Root accounts should have no access keys at all. The application's own `.env` correctly uses the scoped `rs-systems-ses-user`. *(Key ID scrubbed from this doc per B6, 2026-07-10.)*
- Consider wiring SES bounce/complaint notifications to an SNS topic. Today the account-level suppression list absorbs them, which satisfies AWS's requirement but gives no in-app visibility.

---

## 2026-07-08 — Auth & Signup Hardening (two-pass audit)

### Fixed
- **CODE-268** — Login brute-force protection was a no-op: `login_router` called `is_ratelimited()` without `increment=True`, so the attempt counter never advanced and the 30/h limit could never trigger. Fixed, and added a per-account limit (10 attempts / 15 min keyed on the submitted identifier) to blunt password spraying from distributed IPs.
- **CODE-269** — `POST /api/tenants/signup/` bypassed both the Turnstile CAPTCHA and email confirmation: it created a fully **active** account and returned a DRF auth token immediately. Now matches the UI flow — account is inactive until the emailed confirmation link is clicked, and no token is issued. (No external consumers; tests updated.)
- **CODE-270** — Login could 500: user lookup used `User.objects.get(email=...)` (raises `MultipleObjectsReturned` on duplicate emails, which the exact-case uniqueness checks at signup allowed to exist). All email-uniqueness checks (`SignupForm`, `signup_service`, API signup, `shop_join_view`) are now `iexact`, and login uses `filter().first()` with a duplicate warning log.
- **CODE-271** — Users who tried to log in before confirming their email were told "Invalid email or password" (ModelBackend silently rejects inactive users) — with the *correct* password. Now shows "your email hasn't been confirmed" plus a resend link, revealed only after the password verifies so it can't be used to enumerate accounts.
- **CODE-272** — Clicking the confirmation email link a second time showed the scary "invalid link" page (first click rotates `last_login`, invalidating the token). Already-active users are now redirected to login with "already confirmed — just log in." The welcome email also moved from signup-time (dead code since CODE-269) to actual activation.
- **CODE-273** — Retired `TokenAuthentication` from the DRF config. Nothing issues tokens (CODE-269 removed the last path; `api-token-auth/` has been commented out for ages) and no client sends `Authorization: Token` — but tokens minted through the old unauthenticated signup never expire. Disabling the auth class renders them inert.
- **CODE-274** — `/password-reset/` and `/admin/password_reset/` accepted unlimited POSTs (email-bombing arbitrary users + SendGrid quota burn). New `RateLimitedPasswordResetView` enforces 5/IP/hour; the reset template now renders real error messages instead of a hardcoded one.
- **CODE-275** — Customer self-signup at `/join/<slug>/` had no CAPTCHA (only a 10/h IP rate limit) while owner signup had Turnstile. Now runs the same `_verify_turnstile` gate (still skips when keys unconfigured, so dev/CI unaffected).

### Changed
- Signup plan question marked optional ("Which plan interests you? *(optional)*", default "I'll decide during my trial") with copy clarifying every account starts with a free 30-day trial, no card required. Field kept — it drives the owner-dashboard trial banner and day-20 nudge email.
- Login sessions now expire at browser close by default (shop computers are often shared); new "Keep me logged in for 30 days" checkbox opts into a persistent session.
- Login, signup, shop-join, and password-reset forms got proper `autocomplete` attributes (`username`, `current-password`, `new-password`, `email`, …) so password managers behave.

### Deferred
- **Two-factor auth (TOTP)** for owner/manager accounts — needs django-otp, enrollment UX, and recovery codes. Worth doing before shops store more customer PII.
- **Consolidate signup entry points** — owner `/signup/`, customer `/join/<slug>/`, and invite links are three separately-styled flows. Visual/copy unification pass.
- **Turnstile fails open** on Cloudflare network errors (deliberate: a Cloudflare outage shouldn't block signups). Revisit if bot signups appear.

---

## 2026-07-06 — Production 500 on Repair Form (staticfiles manifest race)

### Fixed
- **CODE-266 (root cause)** — `/tech/repairs/create/` returned 500 in production: gunicorn started **before** the postdeploy hook ran `collectstatic`, so workers on freshly-booted instances (autoscaling scale-up, immutable updates) loaded an empty staticfiles manifest and cached it for the life of the process. Every `{% static %}` render then raised `ValueError: Missing staticfiles manifest entry`. Collectstatic moved to `.platform/hooks/predeploy/01_collectstatic.sh` (runs against `/var/app/staging` before the app flips and the web service starts, on deploys *and* scale-up self-startup). Removed the now-redundant `leader_only` container command (`.ebextensions/06_static_files.config`) and the postdeploy collectstatic. Same failure signature hit `admin/css/base.css` on the previous instance July 2–4.
- **CODE-266 (resilience)** — Static storage switched to `rs_systems.storage.ForgivingManifestStaticFilesStorage` (`manifest_strict = False`): a missing manifest entry now falls back to hashing the file on disk instead of turning the whole page into a 500.
- **CODE-266 (error handler)** — `create_repair()`'s render-failure fallback crashed with `NameError: name 'settings' is not defined` (`settings.DEBUG` check without the import), replacing the intended diagnostic page with a raw 500. Import added.
- **CODE-267** — `InvoiceEmailService` called `logger.warning()` but the module never defined `logger`. The `NameError` was swallowed by an outer `except Exception: pass`, silently dropping the Stripe payment link from invoice emails whenever payment-token generation failed. Module logger added. (Found via pyflakes undefined-name audit; the audit found no other real instances.)

See `docs/operations/INCIDENT_2026-07-06_REPAIR_FORM_500.md` for the full incident report.

---

## 2026-05-23 — Mobile Repair Form & Invoicing Fixes

Mobile production bugs reported from the field (iPhone via rssystems.io); desktop dev was unaffected for styling.

### Fixed
- **Batch pricing recalculated incorrectly on edit (financial)** — `Repair.save()` re-priced COMPLETED batch repairs against the already-incremented `UnitRepairCount`, shifting every break down a tier on edit (a batch that created at $50/$40 showed $40/$35 after editing). Now preserves the batch price computed at creation time for existing multi-break repairs.
- **Broken styling / unusable form on mobile (UX)** — `repair_form.html`, `multi_break_repair_form.html`, and 13 other technician templates each loaded the Tailwind CDN a **second** time (already loaded in `base_app.html`) plus a redundant `tailwind.config`, causing a race on slow mobile connections that left the form unstyled. Removed the duplicate CDN `<script>` and redundant configs (the green palette they defined is already Tailwind's default).
- **Batch photos mixed up between breaks (data integrity)** — `multi_break.js` reused stale file-input state, so submitting a second break overwrote the first break's photo. Added per-session `photoBeforeChanged`/`photoAfterChanged` flags and a modal reset on edit; an unchanged break now keeps its own photos.

### Added
- **Invoice editing** — new API endpoints: `update_invoice` (notes, internal notes, description, due date, payment terms) and `update_invoice_line_item` (description, unit price, discount, amount — recalculates invoice subtotal/discount/tax/total). Both reject PAID/CANCELLED invoices and are tenant-scoped. Owner invoice detail page now has an **Edit Details** button and a per-line-item edit (pencil) wired to these endpoints via AJAX. Hidden for PAID/CANCELLED invoices.
- **Invoice description field** — new `Invoice.description` text field, exposed in the admin, the invoice API, the edit UI, and PDF rendering.

### Tests
- New `tests/test_invoice_edit_api.py` (23 tests) covering the edit endpoints, description field, PDF render, and the detail-page edit UI.

---

## 2026-03-26 — Sprint 7: Cleanup & Registry

### Added
- **Management Command Registry** — `docs/deployment/PRODUCTION_CHECKLIST.md` now contains a full registry of all management commands (scheduled EB cron, on-demand, and maintenance-only). Includes per-command flags, log file paths, and a 6-step checklist for adding new commands. (§19 of implementation-plan.md)
- **`TenantConfig` abstract base class** (`common/models.py`) — DRY pattern for all per-tenant config models. Provides `get_for_tenant()` classmethod and `created_at`/`updated_at` timestamps. `LoyaltyConfig` now inherits from it. All future per-tenant configs (`ReviewConfig`, `WarrantyPolicy`, etc.) must inherit from `TenantConfig`. (CODE-184, implementation-plan.md §16)
- **`docs/PRICING_TIERS.md`** — canonical feature-to-plan tier matrix, single source of truth for pricing decisions across all proposals. All proposals must reference this before features ship. (CODE-184, implementation-plan.md §17)

### Fixed
- **CODE-199** — `reconcile_loyalty_balances` command crashed with `TransactionManagementError` due to `select_for_update()` called outside an atomic block in the read path. Silent failure masked as "0 drifts found" on every run. Fixed by using plain `.get()` in read path; `--fix` mode still uses proper locked atomic block.
- **CODE-198** — Missing `db_index` on `Tenant.stripe_customer_id`, `stripe_subscription_id`, and `stripe_connect_account_id`. Every Stripe webhook triggered a full table scan. Three indexes added via migration `0017`.
- **CODE-197 / Loyalty Phase 2** — Four Phase 2 items shipped: `reconcile_loyalty_balances` command, `expire_loyalty_points` command, point liability report (`GET /owner/loyalty/liability/`), manual point adjustment (`POST /owner/loyalty/customers/<id>/adjust/`). 59 new tests.
- **CODE-196** — Missing `select_related('warranty_policy')` in `repair_detail()` view; extra DB query per page load for every warranted repair.
- **CODE-195 / Sprint 5 — Warranty UI** — Owner warranty policy settings, repair warranty badges, warranty claim modal, invoice PDF warranty terms. 12 new tests.
- **CODE-190** — `account_settings()` used bare `len(password) < 8` instead of `validate_password()`. Third and final instance of this pattern (CODE-188 fixed the other two).
- **CODE-190 / DashboardService** — `_filter()` applied `filter(tenant=...)` to Payment querysets which have no direct `tenant` FK (path is Payment → Invoice → Tenant). `FieldError` → 500 on billing dashboard.
- **CODE-189** — `WarrantyService.get_all_warranty_repairs()` used `models.Q(...)` without importing `models`. Runtime `NameError` on any call.
- **CODE-188** — `customer_register()` and `accept_customer_invitation()` used bare length check instead of Django's `validate_password()`. Weak/common passwords accepted.
- **CODE-187** — `unit_details()` fell into `else` branch doing `Repair.objects.filter(technician=None)` instead of `.none()` when no Technician record existed.
- **CODE-186 — Repair Completion Hook Orchestrator** — `Repair.save()` now calls a hook orchestrator (`technician_portal/hooks.py`) instead of `award_completion_points` directly. Loyalty, warranty, and review hooks all isolated; one failure can't block others.
- **CODE-185** — `ReferralCode.customer_user` field changed from `ForeignKey(unique=True)` to `OneToOneField` (fixes Django W342 warning; no schema change, constraint was already enforced).
- **CODE-184 (Decimal falsy)** — Three templates used `{% if value %}` on optional Decimal fields. `Decimal('0.00')` is falsy; managers with zero approval limits and $0.00-override repairs were invisible. Fixed to `{% if value is not None %}`.
- **CODE-183** — CANCELLED invoice email guard missing in 3 send paths: single-send API, batch API, and owner portal resend.
- **CODE-182** — `send_invoice_email_batch()` batch success path never updated `invoice.status` or `invoice.sent_at`. All batch-sent invoices stayed as DRAFT indefinitely.
- **CODE-181 (email fallbacks)** — Three exception-fallback paths in `InvoiceEmailService` hardcoded `https://rssystems.io` instead of using `settings.BASE_URL`.
- **CODE-181 (convert_to_batch)** — `cost_override` not persisted on new Repair rows in `convert_to_batch()`, silently wiping manager price overrides on repair completion.
- **CODE-180** — `reward_fulfillment_detail()` used wrong email field for Customer lookup. `customer_repairs` always empty; "Apply to Repair" dropdown never appeared.

### Technical
- `WarrantyPolicy` model, migrations, admin, service, and hook — full warranty system Phase 1
- `PointTransaction` ledger, `LoyaltyConfig`, `LoyaltyService` — full loyalty Phase 2
- `db_index=True` on three Stripe ID fields — migration `0017_add_stripe_id_indexes`
- `docs/proposals/suggestions.md` and `implementation-plan.md` — full proposals audit and action plan
- All proposal bugs §1–4 corrected in source proposal docs

---

## 2026-03-24 — Loyalty System Phase 1

### Added
- **PointTransaction model** — immutable ledger for all point changes (earn/spend/expire)
- **LoyaltyConfig model** — per-tenant configurable point values, program name, expiry
- **LoyaltyService** — single entry point for all balance changes with row-level locking
- Points balance badge in customer portal navigation
- Points history page at `/rewards/points-history/`
- Backfill migration for existing reward balances
- PointTransaction + LoyaltyConfig admin pages

### Changed
- `award_completion_points()` reads from LoyaltyConfig instead of hardcoded values
- `ReferralService.process_referral()` delegates to LoyaltyService
- `RewardService.redeem_reward()` creates PointTransaction via LoyaltyService
- `referral_rewards` view now routes to `dashboard.html` (was using broken `rewards_compact.html`)
- Replaced browser `confirm()` dialog with Tailwind modal for reward redemption

### Fixed
- `referral_rewards` view missing `is_active=True` filter (deactivated options shown)
- `reward_options` view missing `points` in context (all Redeem buttons disabled)
- Duplicate Tailwind CDN in `rewards_compact.html`
- `ReferralCode.customer_user` missing unique constraint (race condition for duplicate codes)
- CODE-164 through CODE-175: tenant isolation in rewards, race conditions, N+1 queries, admin `delete_queryset` gaps, round-robin assignment bugs

---

## 2026-03-23 — Stripe Connect Live & Platform Polish

### Added
- **Stripe Connect live** — `charges_enabled`, `payouts_enabled`, real payments flowing
- **FAB quick action button** — on all 19 portal pages with staggered animation
- **Public payment links** — HMAC-token URLs for customer payment without login
- **Branded HTML emails** — all 11+ email types converted from plain text
- **Platform owner flag** — permanent pro plan, no subscription needed

### Changed
- Windshield damage diagram restored on repair, multi-break, and customer request forms
- Mobile batch buttons: 44px min tap targets, grid layout
- Wider repair + multi-break forms on mobile

### Fixed
- Stale Stripe customer IDs from test→live mode switch
- Payment notification stale data (`refresh_from_db`)
- Connect webhook endpoint (`connect: false` → `true`)

---

## 2026-03-21 to 03-22 — Signup Flexibility, Invoice Voiding & Bug Sweep

### Added
- **"Not sure yet" plan option at signup** — users who don't know which plan they want can skip the decision and explore during trial
- **Intended plan pre-selection on billing page** — if a user chose a plan at signup, it's highlighted with a "Recommended for you" badge and pulsing border on the billing/upgrade page
- **Stripe Checkout plan default** — the Upgrade button falls back to the user's intended plan from signup, reducing friction at checkout
- **Day 20 nudge email for undecided signups** — tenants who chose "Not sure yet" get a friendly email when 10 days remain on trial, linking to the pricing page
- **Void invoice action** — owners can void invoices from both the bulk action bar (invoice list) and individual invoice detail page. Voiding sets status to CANCELLED. Paid and already-voided invoices are skipped.
- **Delete voided invoices** — the delete action now accepts both DRAFT and CANCELLED (voided) invoices. Active invoices must be voided first before deletion.
- New URL: `POST /owner/invoices/<id>/void/` for single-invoice void
- Proposal: AI-powered plan recommendation based on shop usage data (`docs/proposals/ai-plan-recommendation.md`)

### Changed
- Bulk action bar: "Delete Drafts" renamed to "Delete" with updated confirmation text explaining void-first workflow
- Street address field added to billing location settings (owner Settings → Billing tab)

### Fixed
- **CODE-113 through CODE-124** — 12 bugs: `shop_join` IntegrityError, Decimal falsy checks, bulk invoice `mark_paid`, overdue reminder date format, custom email template rendering, PDF number formatting, admin tax bypass, batch rewards, void `ProtectedError`, `PaymentAdmin` delete
- Signup CAPTCHA fix

---

## 2026-03-18 to 03-20 — Tenant Isolation Sweep (CODE-077–104)

### Fixed
- Systematic fix for unscoped `request.user.technician` OneToOneField across the entire technician portal
- DRF API ViewSets tenant-scoped
- Clawdbot invoice views tenant-scoped
- Reminder/auto-invoice services tenant-scoped
- Billing API tenant-scoped
- `shop_join_view` blocking existing users (CODE-093)
- `InvoiceService` missing tenant in 3 billing call sites (CODE-092)
- ~70+ regression tests added

---

## 2026-03-17 — Stripe Connect: Online Invoice Payments (Phases 1-3)

**Feature: Shop owners can now connect their Stripe account to accept online invoice payments.**

### Phase 1: Connected Account Onboarding
- **`Tenant` model** — new Stripe Connect fields: `stripe_connect_account_id`, `stripe_onboarding_status` (not_started/pending/in_review/active/restricted/disabled), `stripe_connect_charges_enabled`, `stripe_connect_payouts_enabled`, `stripe_connect_onboarding_complete`, `stripe_connected_at`, `platform_fee_percent`
- **`ConnectService`** (`apps/tenants/services/connect_service.py`) — full service class for Express account creation, onboarding links, status sync, and direct charge sessions
- **Module-level functions**: `create_connect_account`, `create_account_link`, `handle_account_updated_webhook`, `calculate_platform_fee`, `create_direct_charge_session` — spec-aligned API for views and tests
- **Owner portal Connect views**: `connect_setup`, `connect_return`, `connect_refresh`, `connect_dashboard` in `apps/saas/views.py`
- **URLs**: `/owner/payments/setup/`, `/owner/payments/setup/return/`, `/owner/payments/setup/refresh/`, `/owner/payments/dashboard/`
- **Owner Settings template** — new "Payment Processing" tab with Connect status badge, action buttons, and "Customers cannot pay invoices online" warning when not active

### Phase 2: Payment Routing (Direct Charges)
- **Hard block in `create_direct_charge_session`**: raises `ConnectError` if `stripe_onboarding_status != 'active'` OR `stripe_connect_charges_enabled` is False
- **Direct charges**: checkout sessions created on the connected account via `stripe_account=` param with `application_fee_amount` for platform fee
- **Invoice email gate** (`InvoiceEmailService`): payment links omitted when `tenant.can_accept_payments` is False
- **Customer portal gate**: `can_pay_online` context variable is False when tenant has no active Connect

### Phase 3: Admin Fee Dashboard
- **`PlatformConfig` model** — singleton global settings (`default_fee_percent`, `competition_pool_enabled`, `competition_pool_fee_percent`); added `get_solo()` alias for `get()`
- **`PlatformFeeRecord` model** — tracks every platform fee collected (tenant, invoice, payment_intent_id, gross_amount, fee_amount, fee_percent, stripe_account_id)
- **Fee recording** in `_handle_payment_succeeded` webhook handler — creates `PlatformFeeRecord` when `application_fee_amount > 0`; deduplication prevents double-recording
- **Admin views**: `/admin/connect-accounts/` (list all tenants with Connect status) and `/admin/platform-config/` (edit global fee settings singleton)
- **Admin templates**: `templates/admin/connect_accounts.html` and `templates/admin/platform_config.html`

### Tests
- **`tests/test_stripe_connect.py`** — 31 new tests covering:
  - Fee calculation: tenant override > global default > 0 fallback
  - `create_direct_charge_session` hard block for non-active Connect
  - `handle_account_updated_webhook`: status transitions (active, restricted, in_review, pending)
  - First activation sets `stripe_connected_at`; re-activation doesn't overwrite it
  - Invoice email: `can_accept_payments` gate
  - Customer portal: `can_pay_online` context var logic
  - `PlatformConfig` singleton behavior and `get_solo()` alias
  - `PlatformFeeRecord` creation, deduplication, and zero-fee bypass

See `docs/proposals/stripe-connect-implementation-plan.md` for the canonical architecture reference.

---

## 2026-03-17 — Soft-Delete for Repairs & Invoices

**Feature: Repairs and invoices can now be soft-deleted instead of permanently removed.**

### Added
- **`Repair.deleted_at`** — new nullable `DateTimeField`; when set, the repair is excluded from all default querysets
- **`Invoice.deleted_at`** — same pattern on Invoice model
- **`RepairSoftDeleteManager` / `InvoiceSoftDeleteManager`** — default managers auto-filter `deleted_at__isnull=True`; use `Repair.all_objects` / `Invoice.all_objects` for unfiltered access
- **`delete_repair` view** (`POST /tech/repairs/<id>/delete/`) — owner/manager only; blocks if any payment exists on a linked invoice; soft-deletes repair + cascades to linked invoices
- **`restore_repair` view** (`POST /tech/repairs/<id>/restore/`) — owner/manager only; restores repair + its linked invoices; blocked after 30 days
- **`archived_repairs` view** (`GET /tech/repairs/archived/`) — shows all soft-deleted repairs and invoices within the 30-day window with one-click restore
- **Delete button** on `repair_detail.html` — visible to owners/managers only; triggers a confirmation modal before POSTing
- **`purge_deleted_records` management command** — hard-deletes records older than `--days` (default 30); dry-run by default, use `--apply` to execute; handles PROTECT constraint by deleting `InvoiceLineItem` rows first
- **Migrations**: `billing.0017_invoice_deleted_at`, `technician_portal.0034_repair_deleted_at`
- **Docs**: `docs/SOFT_DELETE.md` — full reference for the feature

### Technical
- Cascade on delete: invoices with line items pointing to the deleted repair are soft-deleted in the same atomic transaction
- Restore cascade: restoring a repair also restores `deleted_at__isnull=False` invoices linked to it
- All existing querysets automatically exclude deleted records via the new default manager (no call-site changes needed)

---

## 2026-03-16 to 03-18 — Security Hardening Continued (CODE-049–061)

### Fixed
- Race conditions: payment concurrency, TOCTOU
- Financial bugs: Stripe Connect routing, double-billing via unpaid sessions
- IDOR fixes, price override permission escalation
- Replacement-only invoice email skip
- Customer approve/deny status guards
- ~103 new regression tests

---

## 2026-03-15 — Security Hardening Sprint (CODE-005–035)

### Fixed
- 35 bugs fixed: tenant isolation gaps, cross-tenant IDORs, broken permission decorators, N+1 queries

---

## 2026-03-14 — Admin TenantFilterMixin Coverage (CODE-006)

### Fixed
- **TechnicianAdmin** — added `tenant` to `list_display` and `list_filter`
- **UnitRepairCountAdmin** — added `TenantFilterMixin`; tenant now visible in list_display/list_filter
- **ViscosityRecommendationAdmin** — added `TenantFilterMixin`; tenant visible in list_display/list_filter
- **TaxRateAdmin** (billing app) — added `TenantFilterMixin`; tenant visible in list_display/list_filter
- **DeliveryLogAdmin** (core) — added `TenantFilterMixin` (model already had tenant FK; was missing from admin)
- **customer_portal admins** — new `CustomerTenantFilterMixin` (filters via `customer__tenant`) applied to CustomerUserAdmin, CustomerPreferenceAdmin, RepairApprovalAdmin (`repair__customer`), CustomerPricingAdmin, CustomerRepairPreferenceAdmin, CustomerInvitationAdmin; `get_tenant_display` shown in all list views
- **rewards_referrals admins** — `RewardOptionAdmin` uses `TenantFilterMixin`; `RewardAdmin`, `ReferralCodeAdmin` use new `CustomerUserTenantFilterMixin`; `ReferralAdmin` and `RewardRedemptionAdmin` have custom `get_queryset` scoping; all show tenant in list view
- **BillingConfig data fix** — new management command `fix_billing_config_names` corrects `company_name = tenant.name` for all rows where migration incorrectly defaulted to "Rockstar Windshield Repair" (`python manage.py fix_billing_config_names --apply`)
- All 98 existing admin/billing/owner-setup tests pass

---

## 2026-03-14 — Multi-Tenant BillingConfig (CODE-002)

### Fixed
- **BillingConfig is now per-tenant** (`OneToOneField(Tenant)`) — removed the `singleton_id` global singleton
- Added `BillingConfig.get_for_tenant(tenant)` — creates with defaults if missing for that tenant
- `BillingConfig.get_instance()` now raises `RuntimeError` to surface any remaining legacy callers
- Updated all 14 call sites across 7 files: `apps/saas/views.py` (10), `invoice_service.py`, `invoice_tracking_service.py`, `payment_notification_service.py`, `reminder_service.py`, `tax_service.py`
- `tax_debug` management command now iterates all tenants (or accepts `--tenant <id|slug>`)
- Admin: `BillingConfigAdmin` uses `TenantFilterMixin` — non-superusers only see their tenant's config
- Migrations: `0013_billingconfig_tenant_fk` (data migration assigns existing config to first tenant) + `0014_alter_billingconfig_options`
- Tests: updated 11 existing tests + added 3 new tests (two-tenant isolation, deprecated `get_instance`, idempotent `get_for_tenant`)

---

## 2026-03-13 — Configure Your Shop + Documentation Refresh

### Added
- **"Configure Your Shop" unified setup page** (`/owner/setup/`)
  - 6-section accordion UI covering Business Info, Pricing, Tax, Billing, Viscosity, Assignment
  - Per-section AJAX save (no page reload), individual Save buttons
  - Completion status badges (Complete / Not configured / Optional)
  - Info tooltips on each section explaining why the setting matters
  - Viscosity auto-populate: enabling creates 5 standard temperature rules scoped to the tenant
  - Mobile responsive layout with Tailwind CSS
  - Toast notifications on save success/error
  - Auto-opens first incomplete section on page load
- **Owner dashboard setup progress card** — shows "X of 6 configured" with progress bar; links to `/owner/setup/`; disappears when critical sections (Business Info + Billing) are done
- **"Configure Your Shop" link** on the existing `/owner/settings/` page
- **26 tests** in `tests/test_owner_setup.py` covering access control, each save endpoint, viscosity auto-populate, and tenant isolation

### Technical
- Added `_setup_completion(tenant)` helper to `apps/saas/views.py` (computes completion across all 6 sections)
- Added 7 new URL patterns in `apps/saas/urls.py` under `/owner/setup/`
- Dashboard view now passes `setup_completion` context to template
- `DEFAULT_VISCOSITY_RULES` constant defined in `views.py` for auto-populate

### Documentation
- **ADMIN_GUIDE.md** — updated for v2.4 admin overhaul: Admin Dashboard, Tenant Filtering, Subscription Management, CSV Exports, Bulk Invoice Generation, Audit Log, Global Search sections
- **CUSTOMER_GUIDE.md** — added "When the Shop's Subscription Expires" section
- **TECHNICIAN_GUIDE.md** — added viscosity recommendation note with default temperature rules table; clarified settings access for owners AND managers
- **VISCOSITY_CONFIGURATION_GUIDE.md** — major rewrite; primary access path is now `/owner/setup/` with auto-populate defaults
- **USER_FLOWS.md** — added 4 new flows: Configure Your Shop, Subscription Expiry, Statement of Account, AR Aging Report
- **MULTI_BREAK_QUICK_START.md** — corrected optimal temperature range to 60–95°F (ideal: 75–95°F)

---

## 2026-03-11 — Subscription Expiry UX

### Role-Aware Blocked Page
- **`/subscription-blocked/`** — dedicated page for expired/canceled tenants (replaces hard redirect to `/pricing/`)
  - **Owner** → upgrade CTA with plan comparison
  - **Technician** → contact-your-account-owner messaging
  - **Customer** → shop contact info and status message

### Grace Period
- **30-day read-only grace period** after trial/subscription expiry
  - GET requests allowed — users can still view their data
  - Write operations blocked — no new repairs, customers, or invoices
  - `grace_period_end` field added to Tenant model
  - Grace period warnings shown in banners

### Subscription Banners
- **Trial countdown** — amber banner for all authenticated users when ≤ 7 days remain
- **Grace period warnings** — banner shown when in read-only grace window
- **Expired notice** — clear messaging when grace period ends
- Smart messaging distinguishes trial-ended vs subscription-ended scenarios

### Email Alerts — 6 Lifecycle Stages
- Management command: `check_subscription_alerts` (run daily via cron)
- Alert stages tracked via `subscription_alerts_sent` JSONField on Tenant

| Stage | Trigger |
|-------|---------|
| 7 days before expiry | Friendly heads-up with upgrade CTA |
| 1 day before expiry | Last-chance alert |
| Day of expiry | Trial/subscription ended notice |
| 15 days into grace | Mid-grace warning |
| 5 days before grace ends | Urgent final warning |
| Grace period ended | Access fully suspended notice |

### Tests
- 31 tests covering blocked page, grace period, banners, email alerts, and management command

---

## 2026-03-11 to 03-12 — Admin Console Overhaul

#### Custom Metrics Dashboard
- **Subscription breakdown** — trial/active/expired counts, plan distribution
- **Monthly repairs + revenue** — rolling 30-day summary on admin home
- **Activity feed** — recent signups, repairs, and key events at a glance

#### Tenant Filtering
- **TenantFilterMixin** — non-superusers (tenant admins) now see only their own tenant's data across all admin list views

#### Subscription Management Actions
- **Extend trial 7 days** — one-click action on Tenant admin list
- **Extend trial 30 days** — bulk or individual
- **Activate subscription** — mark tenant as active from admin
- **Deactivate subscription** — cancel/expire a tenant from admin

#### Data Exports
- **CSV export: repairs** — all repairs for selected tenants
- **CSV export: invoices** — invoice history with line-item totals
- **CSV export: customers** — customer roster with contact info

#### Bulk Invoice Generation
- Select customers in admin → generate invoices for all uninvoiced repairs in one action

#### Audit Log Viewer
- **Django LogEntry integration** — read-only view of all admin actions
- Color-coded by action type (add/change/delete)
- Filterable by user, content type, and date

#### Global Admin Search
- `/admin/search/` — search across tenants, users, repairs, and customers from one place

#### Performance Improvements
- `select_related` on all heavy admin list views
- `autocomplete_fields` on FK dropdowns (eliminates N+1 on inline selects)
- `list_per_page` tuned across all model admins
- `@admin.register` cleanup — removed legacy `admin.site.register()` calls

#### Tests
- 41 admin tests covering metrics, filtering, actions, exports, search, and audit log

#### Infrastructure
- **Domain migration** — all `rockstarwindshield.repair` references replaced with `rssystems.io`
- **Contact email** — standardized to `contact@rssystems.io` across all templates and settings
- **SendGrid domain auth** — `rssystems.io` authenticated for email deliverability
- **ImprovMX inbound forwarding** — `contact@rssystems.io` forwards to Gmail

---

## 2026-03-09 to 03-12 — Bug Fixes & UX Polish

#### Bug Fixes
- **BUG-001** — `create_repair` 500 error when no technician is assigned; added guard for empty technician queryset
- **BUG-004** — Custom branded 404/500 error pages with RS Systems styling (replaces Django defaults)
- **Viscosity settings 500** — Changed `@technician_required` → `@manager_required` on viscosity settings view; owners without technician profiles can now access it

#### UX Fixes (UX-001 through UX-011)
- **UX-001** — Navbar name truncation on long business names
- **UX-002** — Customer repair table clipping on small screens
- **UX-003** — Customer Portal preview button added to owner settings
- **UX-004** — Trial badge blue outline styling fixed
- **UX-005** — Onboarding technician confirmation messages corrected
- **UX-006** — Contextual assignment warning when no primary techs are set
- **UX-007** — Add phone/email CTAs shown in customer detail when fields are empty
- **UX-009** — Redundant ability badges removed from team member list; using fa-wrench icon instead
- **UX-010** — Billing settings improvements
- **UX-011** — Batch invoicing improvements

---

## 2026-03-03 — Security: Cross-Tenant Leaks & Subscription Enforcement

### Security
- **CRITICAL: Cross-tenant customer data leak** — RepairForm showed ALL customers from ALL shops. Now tenant-filtered. (BUG-001)
- **CRITICAL: Cross-tenant tax leak** — TaxService read from global BillingConfig singleton. Now reads from tenant-scoped TaxRate entries. New tenants default to zero tax. (BUG-003)
- **CRITICAL: No subscription enforcement** — Users could use app indefinitely after trial expired. New `SubscriptionEnforcementMiddleware` blocks expired/canceled tenants. (BUG-002)
- **Missing CSRF token** on primary technician change form — caused 403 on save. (BUG-007)
- **Technician queryset unfiltered** — RepairForm technician dropdown now tenant-scoped. (BUG-001)
- **Technician lookup on primary tech update** — now filtered by tenant to prevent cross-tenant assignment.

### Fixed
- **Signup crash on Django 5.x** — `User.objects.make_random_password()` removed in Django 5. Replaced with `secrets.token_urlsafe()`. (BUG-004)
- **"Add myself as technician" required name fields** — now uses owner's existing user when `add_self` is checked. (BUG-005)
- **Skip buttons on onboarding broken** — browser HTML5 validation blocked submit. Added `formnovalidate`. (BUG-006)
- **Real customer names in placeholder text** — changed "EOS Trucking, Penske" to generic examples. (BUG-014)

### Added
- **Subscription lifecycle documentation** — `docs/development/SUBSCRIPTION_LIFECYCLE.md` with data retention policy, trial email alert plan, and soft landing page spec.
- **Automated test suite** — 109 tests covering billing models, auth/permissions, tenant isolation, core models, URL routing, and bug fix regressions.
- **Data retention policy** — all tenant data preserved indefinitely after trial/subscription expiration.

---

## 2026-02-19 — Progressive Pricing & Replacements

### Added
- **Configurable progressive pricing tiers** — shop owners can set custom prices for repairs 1-5+ per unit
- **Progressive pricing toggle** — enable/disable per tenant in owner settings
- **Per-customer progressive pricing flag** — override tenant default for specific customers
- **Viscosity rules configuration** — moved to General tab in owner settings with dedicated link
- **Customer portal replacement views** — customers can view, approve, and deny replacements
- **Replacement list view** — with filtering and pagination for technicians
- **Replacement edit view** — technicians can update replacement details and status
- **Tax fields on Replacement model** — full tax support for glass replacements
- **Terms of Service page** — `/terms/` with legal content
- **Privacy Policy page** — `/privacy/` with legal content
- **Email verification on signup** — sends verification email after owner and customer registration

### Fixed
- **Multi-break batch tenant isolation** — `convert_to_batch` now correctly copies tenant to new repairs
- **UnitRepairCount tenant lookup** — includes tenant in `get_or_create` to prevent cross-tenant issues
- **Pricing preview** — respects progressive pricing settings from tenant
- **Repair count reset** — resets unit repair count when replacement is completed
- **Owner dashboard recent activity** — fixed template bugs in activity display
- **Registration form data preservation** — form data preserved on validation errors
- **Stale branding** — updated all references to RS Systems

### Changed
- **Documentation cleanup** — removed all emojis from documentation files

---

## 2026-02-10 to 02-11 — SaaS Subscription Billing Polish

### Usage Enforcement
- **Repair creation limit** — blocks creating repairs when monthly limit reached
- **Customer creation limit** — blocks adding customers when at plan limit
- **Technician invite limit** — blocks inviting technicians when at seat limit
- All limits show a friendly message with upgrade CTA

### Subscription Status Banners
- **Trial expiring soon** (7 days) — amber banner with upgrade CTA
- **Trial expired** — red banner prompting upgrade
- **Past due** — red banner prompting payment method update
- **Canceled** — gray banner with reactivate option
- Banners display for owners/managers across all pages

### Also shipped this pass
- Usage meters on owner dashboard (repairs/technicians/customers with progress bars)
- Full subscription API (subscribe, update, cancel, reactivate, billing portal)
- Stripe webhook handlers for subscription lifecycle
- `SubscriptionPlan` model with limits and Stripe price IDs
- `UsageService` for tracking usage vs limits

### Security
- **CRITICAL: Plan upgrade now requires payment** — fixed security hole where clicking "Upgrade" granted paid plan features before payment completed. Plan now only upgrades via `checkout.session.completed` webhook after Stripe confirms payment.

### Fixed
- **Stripe API breaking change** — switched from direct subscription creation to Stripe Checkout Sessions (Stripe removed `payment_intent` from Invoice objects in March 2025)
- **Added `checkout.session.completed` webhook handler** — captures subscription ID and upgrades plan after successful payment

### Changed
- `create_subscription` now returns `checkout_url` for redirect instead of `client_secret`
- Plan/subscription_plan fields only updated in webhook handlers, never before payment

---

## 2026-02-04 — Send Reminder Button

### Added
- **Send Reminder** button on invoice detail page now functional
- **Polished modal** with invoice summary, email preview, and confirmation — shows customer, amount due, due date, status; email subject and body preview; lists what's included (PDF, payment link, invoice details); warning if no email on file; Escape key or click outside to close
- **PDF invoice attached** to reminder emails
- **Company info from BillingConfig** (no more hardcoded placeholders)
- Subject format: `[RS Systems] Overdue Notice: Invoice X - Customer`
- "Do not reply" footer added
- Reminder logged in invoice `internal_notes`
- URL: `POST /owner/invoices/<id>/reminder/`

---

## 2026-02-04 — Invoice UX Improvements

#### Clickable Overdue Badge
- **Overdue summary card** on `/owner/invoices/` is now clickable — filters to show only overdue invoices
- **Count badge** shows number of overdue invoices when > 0
- **Visual highlight** (ring) when overdue filter is active

#### Send Confirmation Modal
- **"Create & Send"** now opens a confirmation modal instead of sending immediately, showing: email subject preview, invoice summary (number, repair count, total amount), editable recipient email field, support for multiple recipients (comma-separated)
- Backend `send_invoice_email` endpoint now accepts custom `recipient_email` and `cc_emails` parameters
- Invoice status auto-updates DRAFT → SENT when email is sent

#### Dismiss Uninvoiced Repairs
- **"Dismiss" button** on uninvoiced work section — for legacy repairs already paid outside the system
- Marks repairs with `skip_invoicing=True` flag — hides from invoicing without deleting
- API endpoint: `POST /api/billing/customers/<id>/uninvoiced/dismiss/`
- Accepts `{"all": true}` to dismiss all, or `{"repair_ids": [1,2,3]}` for specific repairs

#### Dev Email Fix
- Development settings now use **console email backend** by default — emails print to terminal instead of sending (avoids SSL certificate errors). Set `USE_REAL_EMAIL=True` in `.env` to send actual emails locally.

#### Technical Details
- Templates: `saas/owner_invoices.html` (modal + clickable badge + dismiss button)
- Views: `apps/saas/views.py` (added `overdue_count` to context)
- API: `apps/billing/views.py` (`send_invoice_email` updated, `dismiss_uninvoiced_repairs` added)
- Model: `apps/technician_portal/models.py` (added `skip_invoicing` field to Repair)
- Settings: `rs_systems/settings/development.py` (console email backend)

---

## 2026-02-01 — Tax Calculation on Repair Tickets & Invoices

### Fixed
- **Tax on repair tickets** — added `tax_rate`, `tax_amount` fields to Repair model. Tax is now calculated automatically from `BillingConfig` rates every time a repair is saved. `total_with_tax` property shows cost + tax.
- **Tax display** — repair detail pages in both technician and customer portals now show tax breakdown and total with tax.
- **Invoice creation fix** — moved `InvoiceService` (reportlab) import into the PDF generation block so invoice record creation and tax calculation no longer fail if reportlab is unavailable.
- **Auto-enable tax on rate save** — saving non-zero tax rates in Owner Settings now automatically sets `tax_enabled = True`.

---

## 2026-02-01 — Invoice Portals & Payment Management

Full invoice visibility and payment handling across all three portals.

#### Customer Portal
- **Invoice List** (`/app/invoices/`) — customers see all their invoices with status badges (Paid, Overdue, Sent, Partial, Cancelled)
- **Invoice Detail** (`/app/invoices/<id>/`) — line items, totals, payment history, PDF download
- **Pay Now** — one-click Stripe checkout from invoice detail page
- **"Invoices" nav link** added to customer portal navigation

#### Owner Portal
- **Invoice Dashboard** (`/owner/invoices/`) — summary cards (outstanding, overdue, payments this month) + full invoice table with filters
- **Manual Payment Recording** — form on invoice detail to record cash, check, wire, ACH, credit card payments with reference number, date, notes
- **Auto-status updates** — recording payment automatically updates invoice status + sends confirmation emails
- **PDF view + payment actions** on every invoice row

#### Technician Portal
- **Collect Payment On-Site** (`/tech/repairs/<id>/collect-payment/`) — techs can record cash/check payments from repair detail page for completed+invoiced repairs
- Payment auto-linked to invoice, confirmation emails sent

#### Stripe Landing Pages
- `/payment-complete` — branded thank-you page after successful Stripe payment
- `/payment-cancelled` — return page for cancelled Stripe checkouts

#### Technical Details
- Customer views: `apps/customer_portal/views.py` (`customer_invoices`, `customer_invoice_detail`, `customer_invoice_pay`)
- Owner views: `apps/saas/views.py` (`owner_invoice_list`, `owner_invoice_detail`)
- Tech view: `apps/technician_portal/views/repairs.py` (`tech_collect_payment`)
- Templates: `customer_portal/invoices/`, `saas/owner_invoices.html`, `saas/owner_invoice_detail.html`

---

## 2026-01-31 — Billing & Invoicing System

Complete billing infrastructure: auto-invoicing, Stripe payments, payment confirmation emails.

### Added
- **BillingConfig singleton** — company address (street/city/state/zip), default payment terms, invoice prefix/footer, configurable via Admin > Billing
- **Payment Terms** — COD (default), Due on Receipt, NET15/30/45/60. Due date auto-calculated. Displayed on PDF invoices.
- **Stripe Integration** — Payment Links auto-generated on invoice creation. Checkout Sessions. Webhook handler at `/api/billing/stripe/webhook/`
- **Auto-Invoice on Completion** — Django signal fires on repair COMPLETED → generates PDF → saves to S3 → emails customer (for `per_ticket` preference customers)
- **Payment Confirmation Emails** — branded HTML receipt to customer (amount, method, date, remaining balance with "Pay Remaining" link for partials). Plain text notification to owner.
- **Payment Status in Portals** — owner dashboard and repair detail pages show invoice/payment status
- **15+ Billing API Endpoints** at `/api/billing/` — dashboard, CRUD, Stripe, reminders, customer preferences

### Technical Details
- Invoice + InvoiceLineItem + Payment models with double-billing prevention
- Services: `invoice_service.py` (PDF), `auto_invoice_service.py`, `stripe_service.py`, `invoice_email_service.py`, `reminder_service.py`, `dashboard_service.py`, `report_service.py`
- Stripe webhook handles `checkout.session.completed` + `payment_intent.succeeded` → auto-records Payment → updates Invoice status
- Full history of this build: `docs/archive/BILLING_ROADMAP.md`

---

## 2026-01-30 — Unified Permissions, Templates & Onboarding

Major architectural overhaul: one permission system, one base template, fixed signup flow. Built in a single session — 28 tests passing.

### Added
- **Unified Permission System** (`common/auth.py`):
  - `can_access(user, area, tenant)` — single function replacing 182 scattered permission checks across 7 mechanisms
  - `@requires('area')` decorator for all views
  - Context processor providing `user_can_repair`, `user_can_invoice`, etc. to all templates
  - Areas: repairs, customers, invoices, reports, team, settings
- **`base_app.html`** — one base template for all shop staff (owner, manager, tech). Modern Tailwind, sticky nav, adapts to user capabilities. Replaces the old `base.html` / `base_owner.html` split.
- **Settings Package** — refactored `settings.py` into `rs_systems/settings/base.py`, `development.py`, `production.py`

### Changed
- **Signup & Onboarding** — `create_tenant_with_owner()` now auto-creates Technician profile + adds to Technicians group. Onboarding cut to 2 steps (business info → dashboard). No more silent failures.
- **All redirects** — `redirect('home')` for authenticated users replaced with `redirect_to_portal(user)` — customers go to `/app/`, staff go to `/tech/dashboard/`
- **Owner Navigation** — changed from `Dashboard | Billing | Settings | [Tech Portal]` to `Dashboard | Repairs | Customers | Invoices | Settings` — linking to existing pages
- **~25 tech portal templates** updated from `{% extends "base.html" %}` to `{% extends "base_app.html" %}`

### Fixed
- Onboarding wizard silently advancing on form failures, leaving users without Technician profiles
- Owners landing on `base.html` pages with wrong nav after clicking dashboard actions
- Authenticated users being redirected to landing page instead of their portal

---

## 2025-11-18 — Manager Settings Portal

### Added
- **Manager Settings Dashboard** (`/tech/settings/`) — card-based navigation hub for managers
- **Viscosity Rules Management** (`/tech/settings/viscosity/`) — CRUD interface with auto-priority system (badges), modal editing, toggle switches, AJAX operations
- **Team Overview** (`/tech/settings/team/`) — performance dashboard, per-technician stats, completion rates, recent repairs
- **`@manager_required` decorator** for view-level access control

### Changed
- Viscosity rules UX: removed confusing manual priority input, replaced with automatic ordering + visual badges
- `ViscosityRecommendation` model: added public `get_temp_range_display()` for template access

### Fixed
- Template syntax error from calling private `_get_temp_range_display` method

---

## 2025-11-03 — Storage & Data Management

### Added
- **Automatic Photo Deletion** — `django-cleanup` package deletes S3 files when repairs are removed
- **Storage Audit Command** — `python manage.py audit_repair_photos` finds orphaned files, calculates storage costs, optional `--delete`

### Changed
- `TechnicianNotification` cascade behavior: SET_NULL → CASCADE (notifications deleted with repair)

### Fixed
- Orphaned photos remaining in S3 after repair deletion (14+ files, ~16 MB in production)

### Security
- Deleted repair photos now actually removed from S3 (GDPR compliance improvement)

---

## 2025-10-30 — Backup & Data Protection

### Changed
- **RDS backup retention**: 7 → 30 days with point-in-time recovery
- **S3 versioning enabled**: deleted/replaced photos recoverable for 30 days
- **Lifecycle policies**: auto-cleanup of old versions, expired markers, incomplete uploads

### Removed
- Custom SQLite backup system (was silently failing since August — production uses PostgreSQL)
- Empty `rs-systems-backups-20250823` S3 bucket

---

## 2025-10-29 — Admin Enhancements: Lot Walking

### Added
- **Lot Walking Admin Configuration** — checkbox widgets for day selection, time picker, frequency dropdown in CustomerRepairPreference admin
- **Enhanced admin list** — `lot_walking_enabled` and `lot_walking_frequency` columns + filters

---

## 2025-10-29 — Image Upload Enhancements

### Added
- **HEIC/HEIF Support** — native iPhone photo format with auto-conversion to JPEG (95% quality)
- **10MB Upload Limit** — increased from 2.5MB (Django + Nginx configured)
- **Image Conversion Utility** (`common/utils.py`) — shared HEIC→JPEG converter

### Fixed
- Upload failures for 2.5-5MB files (Django default limit)
- AWS 413 errors (Nginx 1MB default)
- HEIC images not displaying in browser

---

## 2025-10-25 — Major UI/UX Redesign

### Changed
- **Customer Account Settings** — complete redesign: card-based layout, tooltip system, tab navigation, Tailwind CSS

### Added
- **Lot Walking Configuration UI** — customer-facing settings for frequency, preferred days/time
- **UI Design Guide** (`docs/development/UI_DESIGN_GUIDE.md`)

---

## 2025-10-21 — Critical Security Fixes & Workflow

### Security
- **CRITICAL** — fixed approval bypass; technicians could set status to COMPLETED to skip customer approval
- **HIGH** — fixed IntegrityError when technicians updated their own repairs

### Added
- Manager assignment system for REQUESTED repairs
- Customer approval dashboard with yellow alert banner
- Customer repair preferences (AUTO_APPROVE, REQUIRE_APPROVAL, UNIT_THRESHOLD)
- Notification enhancement: repair ForeignKey + "View Repair" button
- Repair visibility controls (REQUESTED=managers only, PENDING=hidden from techs)

---

## 2025-09-28 — Sprint 1: Core Pricing & Roles

### Added
- Custom pricing system (CustomerPricing model + PricingService)
- Manager role system (`is_manager`, `approval_limit`, `managed_technicians` M2M)
- Performance tracking fields (`repairs_completed`, `average_repair_time`, `customer_rating`)
- Manager override UI with audit trail

---

## 2025-08-23 — Backup & Security

### Added
- Automated backup system (daily S3 backups, 30-day retention)
- Security audit command

---

## 2025-08 — Photos & Security

### Added
- Photo upload system (S3 integration, before/after photos)
- Security: rate limiting, bot protection, honeypot fields, security headers

---

## 2025-07 — Initial Release

### Added
- Customer Portal (repair requests, status tracking, approval workflow, D3.js analytics)
- Technician Portal (queue workflow, smart pricing, photo documentation, rewards)
- Rewards & Referrals System (referral codes, points, flexible redemption)
- Admin interface, authentication, RESTful API with Swagger docs
- Infrastructure: PostgreSQL, WhiteNoise, AWS Elastic Beanstalk, Gunicorn
