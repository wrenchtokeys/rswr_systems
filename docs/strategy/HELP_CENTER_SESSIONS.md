# Help Center Sessions — update and upgrade `/help/` and the support loop

**Created:** 2026-09-17
**Author:** Claude (assessment session with Drake)
**Status:** H1–H6 BUILT 2026-09-17 on `feat/help-center` (one PR, one commit per session; see §"What shipped" under each). D1–D3 decided by Drake the same day (§0.4). H7 stays BACKLOG behind a second shop.
**Companions:** `docs/proposals/launch-readiness-roadmap.md` (Phases 2–3 built what this doc updates; its decisions log is the origin of every "by design" below), `docs/strategy/PRODUCT_DIRECTION.md` (go-to-market step 6 — the help center is what a stranger shop reads instead of calling Drake), `docs/strategy/IMPROVEMENT_SESSIONS.md` (B3/B5/B6 — the spine features H3 documents), `docs/development/ROADMAP.md`.

This file is the **work queue** for the help center and customer-support experience. It exists because the product outran its own help: three guides now promise something the platform deliberately does not do, the landing page's contact link dead-ends on a login wall, and the three newest features (quotes, claims, price book) have no guide at all. Each session is self-contained — a fresh Claude session with no memory should be able to execute exactly one using only §0 and that session's table.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED`

| Session | Size | Status |
|---------|------|--------|
| H1 · Truth pass — guides say only what the product does | S | DONE 2026-09-17 |
| H2 · A contact form a stranger can use | S | DONE 2026-09-17 |
| H3 · Guides for the spine — quotes, claims, price book | M | DONE 2026-09-17 |
| H4 · Retire the "video coming soon" slots | XS | DONE 2026-09-17 |
| H5 · Close the support loop | S | DONE 2026-09-17 |
| H6 · Read the feedback you already collect | S | DONE 2026-09-17 |
| H7 · Polish — guides in global search, freshness, portal-side reporting | M | BACKLOG |

**Suggested sequence:** H1 → H2 → H3 → H4 → H5 → H6 → H7.
Rationale: H1 and H2 fix the two things actively misleading people today and are a day's work together; H1 fits the "tell the truth" theme of the open payments-truth PR (#261). H3 is the biggest gap for a new shop and is the reason a stranger shop would otherwise write in. H4 is a one-line delete that removes six weeks of "coming soon" from 17 pages. H5/H6 make the support channel two-way and the feedback readable. H7 is craft and waits for a second shop.

**Decisions recorded 2026-09-17** (§0.4): D1a remove the card, D2a quote numbers read from settings, D3a one inbox through the form. Everything below was built on those answers.

---

## How to run a session

1. Cut a fresh branch from `main` (`feat/help-h<N>-…`). Print `git branch --show-current` before every test run — another session may share this working tree.
2. Read §0 and the session's block. Nothing else in this doc is required.
3. Build. `scripts/test_guards.sh tests.test_support_contact tests.test_first_run` is the fast loop; both modules cover the help center and auto-cover every slug in `HELP_TOPICS`.
4. Update the session's Status line and the table at the top, in the same PR.
5. `./scripts/build_css.sh` only if a template gained a class the purge has not seen; commit `static/css/app.css` in your own worktree only.

---

## §0 Context Primer

### 0.1 What exists (as of 2026-09-17, all on prod)

| Piece | Where | Notes |
|-------|-------|-------|
| Guide registry | `apps/support/views.py` `HELP_TOPICS` / `HELP_SECTIONS` | 21 guides, 6 sections. Adding a guide = one dict entry + one template. `owner_only` hides a card from techs; direct links still work. `keywords` feed the search box. |
| Hub | `templates/support/index.html` | Client-side filter over title + blurb + keywords. "Interactive tours" cards (owner/manager only). "Still stuck?" card → contact form. |
| Guide chrome | `templates/support/base_topic.html` | Breadcrumb, video slot, thumbs (`GuideFeedback`, one vote per user per slug, overwrite on re-vote), "Next up" within the section. |
| Contact form (signed in) | `apps/support/views.contact` → `templates/support/contact.html` | `@login_required`, ratelimited 10/h per user. Calls `services.submit_support_message` (**record-first**: row saved, then admin notification, then sender acknowledgement; neither email can fail the request). PRG to `?sent=1`; the reply address rides in the session. Lists the user's own past messages under the form (H5). |
| Contact form (public) | `apps/support/views.public_contact` → `/contact/` → `templates/support/public_contact.html` | No account (H2). Name is a field; Turnstile + honeypot + 5/h per IP. Same service, `source='public'`. Exempt in the subscription middleware. Landing "switching" link, landing footer and `/sms/` point here; 404/500 keep `mailto:`. |
| Service + sweep | `apps/support/services.py`, `manage.py sweep_support_messages` | `admin_notification`/`notify_admins`, `acknowledgement_kwargs`/`send_acknowledgement` (also what `preview_emails` renders). The sweep re-sends both for rows >15 min old with `emailed_ok`/`acknowledged=False`; EB cron every 20 min in `12_reviews_cron.config`. |
| Triage | `apps/support/admin.py` | `SupportMessage` list with editable Status, `source` filter, and a readable "where they were" (`views.describe_page`). `GuideFeedback` changelist opens with a per-guide rollup (worst first) and shows the `reason` people typed. Still **no ticket system, by Drake's 2026-08-05 call**. |
| Middleware | `apps/tenants/subscription_middleware.py:40` | `/help/` is exempt — an expired shop is exactly who needs the form. `tests/test_support_contact.py::test_app_is_blocked_but_contact_form_works` guards it. |
| Contextual links | `owner_settings.html` (6 tab panels), `owner_invoices.html:12`, `job_form.html:13`, `owner_loyalty.html:11` | A "Guides: …" line at the top of the panel. This is the pattern H3 extends. |
| Customer-portal help | `apps/customer_portal/views.customer_help` → `templates/customer_portal/help.html` | One page, five cards, loyalty card gated on `LoyaltyConfig.is_active`. Its "questions?" box routes to the **shop's** phone/email, not RS Systems — correct by design (customers are the shop's, not ours). |
| Public touchpoints | `templates/landing.html:377`, `:443`; `saas/sms_program.html:65`; `saas/subscription_blocked.html:37` | Landing links `/help/contact/` in the "switching" section and `mailto:contact@rssystems.io` in the footer. |
| Tests | `tests/test_help_truth.py`, `tests/test_support_contact.py` (both in the guard set), `tests/test_first_run.py` | Slugs are auto-covered from the registry; a new guide needs no new test to be rendered under test. `test_help_truth` fails the build on a banned phrase, a trial number that drifts from settings/plan rows, or any "coming soon". |
| Source docs | `docs/user-guides/*.md` | Repo-only; not linked from the app. The guides were distilled from `USER_FLOWS.md` and `MULTI_BREAK_QUICK_START.md`. `ADMIN_GUIDE.md` last touched 2026-07-19, `USER_FLOWS.md` 2026-08-04. |

### 0.2 What was wrong — with evidence (all seven fixed 2026-09-17; kept as the record)

1. **The landing page's contact link is behind a login wall.** `landing.html:377` sends a prospect to `/help/contact/`; `apps/support/views.py:281` is `@login_required`, so they land on the sign-in page. The footer (`landing.html:443`) is a `mailto:contact@rssystems.io`, while the form emails `ADMINS` = `wdrakeduncan@gmail.com` (`rs_systems/settings/base.py:206`). Two inboxes, and the path a prospect actually takes is dead. This is the "open contact form" item left over from the 2026-09-17 stranger-shop readiness audit.
2. **Three guides promise overdue-reminder emails that never send.** `paid-on-time.html:19–20` ("Let reminders do the chasing… Polite, branded, automatic"), `send-invoice.html:29`, `settings-explained.html:16`. The cron line is commented out as DISABLED BY POLICY (`.ebextensions/11_billing_cron.config:101`; CLAUDE.md: "RS Systems does not email a shop's customers chasing overdue invoices… do not re-enable it"). Yet `owner_settings.html:1112–1170` still renders an "Overdue Reminders" toggle, day pickers and a subject field, and its own copy says "the customer gets one reminder email". An owner turns it on, reads the guide, and nothing ever goes out. This breaks the charter the help center was built on ("never promise what doesn't exist", `launch-readiness-roadmap.md:14`).
3. **The trial guide says 30 days of grace; the code gives 14.** `trial-ending.html` card 2: "You get a 30-day grace period". `rs_systems/settings/base.py:324`: `TRIAL_GRACE_DAYS` defaults to 14. Card 1's "every feature, no card required" stays true after PR #262 (trial = Starter limits), but the guide should say so — a prospect's first question is "what's the catch".
4. **Every guide opens with "Video coming soon".** `components/video_slot.html` has been on 17 of 18 pages since 2026-08-06 (troubleshooting is the exception). No video was ever recorded. Six weeks in, "coming soon" reads as unfinished.
5. **The newest features have no guide.** Quotes (B3, prod 2026-09-14), insurance claims (B5, prod 2026-09-17), price book (B6, prod 2026-09-17), staff SMS alerts (#258), tap-to-crop photos and the photo ZIP (P7) — none has a guide. The only mention is one sentence in `first-job.html:30` ("your price book fills it in"). The troubleshooting FAQ has ten entries and none for "why did my quote expire", "why is this claim short", or "why did the price box fill itself in".
6. **The support loop is one-way.** The sender gets no acknowledgement email and cannot see what they sent. Nothing alerts Drake to an `emailed_ok=False` row except remembering to filter for it in admin. Thumbs-down carries no reason ("No" tells you nothing to fix), and there is no per-slug rollup — the votes are collected, not read.
7. **Nothing stops 2 and 3 from recurring.** No test ties guide text to settings, cron state or plan rows. The launch-readiness charter was enforced by hand.

### 0.3 What is fine and should stay

- No ticket system, no third-party chat, replies from Drake's inbox (2026-08-05 decision). H5 adds an acknowledgement, not a ticket.
- Record-first `SupportMessage` and the middleware exemption. Do not touch.
- Customers contact the shop, not RS Systems, for anything about their vehicles or bills. H7's portal-side reporting is for *portal* problems only and must not blur this.
- Statements of account are deliberately unmentioned (page exists, not linked from nav — `launch-readiness-roadmap.md:88`). Leave it out until it is linked.
- `<i class="fas">` in `index.html` / `contact.html` is not a regression — the chrome is migrated, these surfaces are not. Do not mass-convert while passing through (CLAUDE.md Icons).

### 0.4 Decisions Drake must make before H1

| # | Question | Options | Consequence |
|---|----------|---------|-------------|
| D1 | The Overdue Reminders settings card: what happens to it? | (a) **Remove the card** and the guide text — reminders are policy-off and the UI should not offer them. (b) Keep the card but relabel it "Not available yet — RS Systems doesn't send reminders on your behalf" and disable the controls. (c) Reverse the policy and re-enable the cron. | H1 is written for (a). (b) keeps the model fields live for a future decision. (c) is out of scope here and contradicts CLAUDE.md; it needs its own session and a `--dry-run` on the instance first. |
| D2 | Should the trial guide quote numbers at all? | (a) Say "14 days" and "the same limits as Starter", reading both from settings/plan rows so they cannot drift. (b) Say "a short grace period" and "generous limits" and never quote a number. | (a) is more honest and testable; (b) never goes stale. H1 is written for (a). |
| D3 | Public contact: one inbox or two? | (a) Retire `contact@rssystems.io` on the landing footer and route everything through the form → `ADMINS`. (b) Keep the mailto for the truly public pages (404/500/terms) as the 2026-08-06 decision said, and only fix the landing "switching" link. | H2 is written for (a) on the landing page and (b) on error pages — the error pages must work with no app at all. |

**Answers, 2026-09-17 (Drake):** D1 → (a) remove the card. D2 → (a) quote numbers, read from settings and plan rows. D3 → (a) one inbox: landing link and footer both go to the public form; error pages keep `mailto:`.

---

## H1 · Truth pass — guides say only what the product does — DONE 2026-09-17

**Goal.** No guide, and no settings panel a guide points at, claims a behaviour the platform does not perform. Add a guard so this cannot silently recur.

**Depends on:** D1, D2.

| Item | Detail |
|------|--------|
| Reminders (D1a) | Delete the "Let reminders do the chasing" card from `paid-on-time.html`; rewrite the `send-invoice.html:29` and `settings-explained.html:16` sentences to describe what happens (invoices are *marked* overdue automatically; the "Owed to you" card shows them; reminders are the shop's call to make by phone or by re-sending the invoice). Remove the Overdue Reminders card from `owner_settings.html` (~1112–1170) and the two `form_type` handlers behind it in `apps/saas/views.py` (`toggle_overdue_reminders`, `overdue_reminder_settings`). Leave `BillingConfig.overdue_reminder_*` fields in place — dropping columns is a separate, reversible-with-care migration and not needed to stop the lie. |
| Trial numbers (D2a) | `trial-ending.html` card 2: render `{{ trial_grace_days }}` from `settings.TRIAL_GRACE_DAYS` via the view context (add it in `help_topic`, it is cheap). Card 1: add one sentence — "The trial has the same limits as Starter: N customers, M jobs a month" — read from the `trial` `SubscriptionPlan` row, never typed. If #262 has not merged, the numbers still read from the row and are correct either way. |
| Guard test | New `tests/test_help_truth.py`: (1) no template under `templates/support/` contains "reminder" in the overdue sense (allow the loyalty "little reminder" line by asserting on the exact phrases removed); (2) the trial guide renders the current `TRIAL_GRACE_DAYS` and the trial plan's limits; (3) for every `HELP_TOPICS` slug, the rendered page contains no "coming soon" (this is H4's guard, but it is one assert and belongs with the others). Add to the guard set in `scripts/test_guards.sh`. |
| Cross-check | Grep `templates/support/` for the other settings the guides describe and confirm each still exists under the tab named: `Settings → Pricing & Invoicing`, `→ Card Payments`, `→ Reviews`, `→ Warranty`, `→ Team`. The tab names were consolidated in the 2026-07-24 UX overhaul; spot-check, don't assume. |

**Done when:** the three phrases are gone, the settings card is gone, `test_help_truth` is in the guard set and green, and the guide set + `tests.test_support_contact` + `tests.test_first_run` are green.

**Deliberately not done here:** any change to the `process_overdue_invoices` command or cron config. H1 changes what the app *says*; the policy stays where CLAUDE.md puts it.

**What shipped.** The reminders card in `paid-on-time.html` was *replaced* (not deleted) with "Overdue marks itself" so the numbered steps stay whole; the guide's blurb and keywords stop advertising reminders. The Settings card, its two `form_type` handlers, the day-chip JS and the three context keys are gone; `owner_setup_save_billing` no longer writes the reminder fields either. `support.views.trial_facts()` feeds the trial guide (length and limits from the `trial` plan row, grace from `TRIAL_GRACE_DAYS`, Starter parity only when the rows match). Guard: `tests/test_help_truth.py`, in `scripts/test_guards.sh`.

---

## H2 · A contact form a stranger can use — DONE 2026-09-17

**Goal.** A prospect on the landing page can write to Drake without an account, through the same record-first path as a signed-in shop, and the two inboxes become one.

**Depends on:** D3.

| Item | Detail |
|------|--------|
| Route | New public `/contact/` (name `public_contact`) in `apps/support/urls.py`, registered ahead of `/help/`. Reuse `contact()`'s body by extracting the save-and-notify half into `apps/support/services.py::submit_support_message(tenant, user, name, email, topic, message, page, source)`; both views call it. |
| Anonymous protection | Cloudflare Turnstile on the public form — the only third-party script already allowed by the CSP (`common/csp_middleware.py`), same widget signup uses. Rate limit by IP (`ratelimit(key='ip', rate='5/h')`) instead of by user. Honeypot field as a free second layer. |
| Model | `SupportMessage` gains `source` (`'app'` / `'public'`) — one small migration — so the admin can filter prospects from shops. `tenant`/`user` are already nullable for exactly this. Name becomes a required field on the public form (there is no account to take it from). |
| Wiring | `landing.html:377` → `{% url 'public_contact' %}`. Footer `:443` → the form (D3a). `sms_program.html:65` is a hardcoded `/help/contact/` string — make it `{% url %}`. Error pages (`404.html`, `500.html`) keep `mailto:` — they must render with nothing behind them. |
| Middleware | `/contact/` must be in the subscription middleware's exempt list AND must not resolve a tenant (an anonymous request has none; confirm `TenantMiddleware` tolerates it — it does for `/login/`). |
| Tests | Extend `tests/test_support_contact.py`: anonymous GET renders, anonymous POST with a mocked Turnstile pass saves `source='public'` + emails ADMINS, POST without Turnstile is rejected, IP rate limit, landing page links to the public route (extend `test_help_surfaces_link_to_form_not_mailto`). |

**Done when:** an anonymous browser can send a message from the landing page and it appears in admin with `source='public'`; the signed-in form is unchanged; the guard set is green.

**Outward-facing check before merge:** submit one real message from an incognito window on prod after deploy and confirm it lands in Drake's inbox with Reply-To set.

**What shipped.** As specified, plus `SupportMessage.role` (the sender's shop role at send time) and `acknowledged` — the sender acknowledgement and the "your messages" list (H5) landed in the same commit because they share `services.submit_support_message`. `_verify_turnstile` is imported from `apps.saas.views` at call time (no key set → passes, same as signup). `tests/test_landing_credibility.py` now asserts the landing page links `/contact/` and not `/help/contact/`. **Not yet done: the prod incognito check** — it needs the deploy.

---

## H3 · Guides for the spine — quotes, claims, price book — DONE 2026-09-17

**Goal.** The three features a new shop is least likely to understand on sight each have a plain-language guide, a troubleshooting entry, and a "Guides:" link on the page where the feature lives.

**Depends on:** nothing. Can run in parallel with H1/H2 on its own branch.

| Guide | Section | Audience | What it must say (and what it must not) |
|-------|---------|----------|----------------------------------------|
| `quotes` · "Send a quote before the work" | money | owner/manager (`owner_only`) | Draft → send → customer accepts on the public page → jobs are created already **approved** with the quoted price locked. 30-day expiry. Revising supersedes, never edits a sent quote. Only a draft can be deleted. **Do not** say the customer can accept from the portal inbox if the portal surface differs — check `templates/customer_portal/` for the quote list before writing. Source: `apps/billing/services/quote_service.py`, `tests/test_quotes.py`. |
| `insurance-claims` · "Track an insurance claim" | money | owner/manager | One claim per invoice; created automatically when a job is flagged insurance, or with one tap on the invoice. Expected / received / short are **derived** — the owner never types them. The deductible is an ordinary customer payment. Insurer payments are recorded with "from insurer" ticked. CLOSED is the only hand-set status and records the write-off. Claims never appear in the customer portal. Source: `apps/billing/services/claim_service.py`, `tests/test_claims.py`. |
| `price-book` · "Your price book" | money | owner/manager | The shop's own prices, learned from completed replacements (and Mygrant quotes where enabled). Fills an **empty** price box with a note and Undo; beside a typed price it only offers "Use $X". Pinned rows are never overwritten by a job. Never fabricates a parts/labor split. Source: `apps/technician_portal/services/price_book.py`, `static/js/price_book_suggestion.js`. |
| Troubleshooting additions | fix | all | "Why did my quote expire / can I reopen it?" (revise, don't reopen). "The claim page says short but the aging card doesn't count it" (customer covered it — outstanding is clamped to what the invoice is owed). "The price filled itself in — where did that number come from?" (price book; how to pin or change). "Why can't I delete this quote?" (only drafts). |
| Contextual links | — | — | Same `<p class="… text-xs text-gray-400">Guides: …</p>` line as `owner_invoices.html:12`, on: the quotes list, the quote detail, the claim panel on the invoice page, the price book owner page. |
| Also missing, smaller | for-technicians | tech | One card each on tap-to-crop ("tap the break so the invoice frames it") and the photo ZIP on the job page. One card in `team-roles` on staff SMS alerts (opt-in, RS Systems' number, what gets texted) — **only if registration v5 is COMPLETE at the time of writing**; otherwise leave it out. Check `docs/operations/SMS_REGISTRATION.md` first. |

**Rules for every guide** (inherited from launch-readiness, restated because they are the point):
- Describe what the button does, not what the model stores. No field names.
- Every claim must be something the reader can go click. If you cannot find the screen, do not write the sentence.
- `{% load ui %}` after `{% extends %}`; `{% icon %}` for new markup.
- Register in `HELP_TOPICS` with `keywords` that match what a shop owner types ("estimate", "insurance", "deductible", "adjuster", "book price").

**Done when:** three new slugs render for an owner and 404 nothing; techs do not see the owner-only cards on the hub; the four troubleshooting entries exist; the four contextual links are in place; `tests.test_first_run` (auto-covers slugs) is green.

**What shipped.** `quotes` is *not* `owner_only` — `quote_list` is `technician_required` and Quotes sits in every role's nav, so techs get the guide. `insurance-claims` and `price-book` are owner-only. Contextual links: quotes list, quote page, claims list, the claim panel on the invoice page, price book. Tech guide gained "Tap the break" and "Download all". **Left out on purpose:** the staff-SMS card — registration v5 was `REVIEWING`, not `COMPLETE`, at the time of writing (`docs/operations/SMS_REGISTRATION.md`); add it to `team-roles` when it lands.

---

## H4 · Retire the "video coming soon" slots — DONE 2026-09-17

**Goal.** No page shows a placeholder for something that does not exist.

| Item | Detail |
|------|--------|
| Change | Remove the `{% if topic.video_label %}…{% endif %}` block from `base_topic.html`. Leave `components/video_slot.html` and the `video_label` keys in place — the doc-comment in the component already describes the swap to a real player, and the keys are the labels for whenever a recording exists. |
| Guard | Covered by `test_help_truth` assert (3) from H1. If H4 lands first, create that test file here. |
| If Drake wants video | Three screen recordings cover the top of the funnel: first job, send an invoice, connect card payments. Each is a 2-minute capture of the seeded demo shop (`manage.py seed_demo_shop`, the same fixture `scripts/landing_shots.py` uses). Self-host under `static/video/` — **no YouTube embed**; the CSP allowlist is `'self'` + Turnstile and the no-third-party-hosts rule applies. Re-enable the slot per guide by giving it a `video_src`, not by un-deleting the block. |

**Done when:** no guide renders "coming soon"; nothing else changes.

**What shipped.** Landed with H1 (same commit). `components/video_slot.html` and every `video_label` key are still in place; nothing includes the component.

---

## H5 · Close the support loop — DONE 2026-09-17

**Goal.** A sender knows their message arrived; Drake knows when one did not.

| Item | Detail |
|------|--------|
| Acknowledgement email | After `submit_support_message` saves, send the sender one plain email: "Got your message — Drake will reply from this address." Through `send_branded_email` with the **platform** branding, not a shop's (this is RS Systems talking, the same as signup confirmation). Subject without brackets or emoji (`docs/operations/SES_OPERATIONS.md`). Record it in `templates/emails/` and add it to `manage.py preview_emails`. Failure of this email must not fail the request — same try/except shape as the admin notification. |
| Failed-notification alert | Nothing today surfaces `emailed_ok=False`. Add a `--dry-run`-capable management command `sweep_support_messages` that re-sends the admin notification for rows older than 15 minutes with `emailed_ok=False`, marks them on success, and logs the count. Schedule it in `.ebextensions/12_reviews_cron.config` alongside `send_review_requests` (every 20 min, `leader_only`, through `run-cron.sh` — read the EB cron section of CLAUDE.md before editing; `tests/test_ebextensions_cron.py` will enforce the four rules). |
| "My messages" | Not a ticket system: a single list on `/help/contact/` under the form showing the signed-in user's own past messages (date, topic, first line, status) so "did that go through?" answers itself. Status text: New → "Received", Replied → "Answered by email", Closed → "Closed". No reply-in-app. |
| Reply address sanity | The admin notification's `Reply-To` is the sender; confirm Gmail honours it when Drake hits Reply (it does, but verify once on prod after H2's outward check). |

**Done when:** a test asserts the ack email is sent and its failure is swallowed; `sweep_support_messages --dry-run` reports correctly on a fixture with a failed row; the list renders only the current user's rows; `preview_emails` shows the new template.

**What shipped.** The sweep re-sends the *acknowledgement* too, not only the admin notification — same failure class, same 15-minute floor. The ack is not a template file: it goes through `send_branded_email(platform=True)` from `services.acknowledgement_kwargs`, and `preview_emails` renders that same builder ("platform — support acknowledgement"). **Not yet done: the Gmail Reply-To sanity check** — it needs the deploy, same as H2's outward check.

---

## H6 · Read the feedback you already collect — DONE 2026-09-17

**Goal.** Thumbs-down tells you what to fix; the totals are visible without exporting.

| Item | Detail |
|------|--------|
| Reason on "No" | In `base_topic.html`, a thumbs-down reveals an optional one-line input ("What were you looking for?") and a Send button; POST to the existing `guide_feedback` endpoint with a `reason` field. `GuideFeedback.reason` (CharField 300, blank) — one migration. Never required; the thumb alone still counts. |
| Rollup | A per-slug summary at the top of the `GuideFeedback` admin changelist: slug, up, down, % helpful, last vote — computed with one `values('slug').annotate(...)` query; no new model. Sort by down-votes desc, so the guide that fails most is first. |
| Search misses | The hub's "No guides match" state is the most useful signal the help center has and it is thrown away. POST the query (debounced, only when the empty state shows for 2s) to a tiny `HelpSearchMiss` row (tenant, query, created_at) — or, cheaper and good enough, log it at INFO with a `help.search.miss` prefix and grep the log. Start with the log line; promote to a model only if the log proves useful. |
| Contact `page` field | It stores `document.referrer`. Map it back to a guide slug or a settings tab when rendering the admin preview, so "which page were they on" is readable at a glance. |

**Done when:** a thumbs-down with a reason is stored and visible in admin; the rollup renders; a search miss produces a log line; tests cover the endpoint change.

**What shipped.** Reason rides a second POST after the thumb (the thumb alone always counts); a flip to "yes" clears it. Rollup: `admin.feedback_rollup()` + `templates/admin/support/guidefeedback/change_list.html`. Search miss: the log-line option (`help.search.miss tenant=… user=… q='…'` at INFO from `apps.support.views`), reported after the empty state has sat 2s, once per phrase per page load, 30/h per user. The contact `page` mapping is `views.describe_page` (guide title / settings tab), shown in the `SupportMessage` admin as "Where they were".

---

## H7 · Polish — BACKLOG

Sequenced behind a second shop being live. Each is small; none is urgent.

- **Guides in global search.** `apps/technician_portal/views.global_search` returns customers/jobs/invoices. Add a "Guides" group matched against `HELP_TOPICS` title + keywords, respecting `owner_only`. The hub's filter already does this; the nav search box is where people actually type.
- **"Last updated"** line per guide, read from `git log -1 --format=%cs -- templates/support/<slug>.html` at build time into a JSON the view reads — or, simpler, a `updated` key in `HELP_TOPICS` that the H1 guard test checks is not older than the newest migration touching that feature. Pick the simpler one.
- **Portal-side "report a problem with this page".** Customers today can only reach the shop. A link in `customer_portal/help.html` for *portal* problems (can't log in, page errors) that writes a `SupportMessage` with `source='portal'` — distinct copy so it is never mistaken for "ask about my bill".
- **Keyboard-reachable hub.** `/` focuses the search box; arrow keys move between cards. Pure JS in the existing nonce'd block.
- **Refresh `docs/user-guides/`** so the repo docs and the in-app guides stop diverging; or delete the repo copies and declare `templates/support/` the source of truth. The latter is honest — nobody reads the markdown.

---

## Notes

- **Why a truth test and not a review checklist.** The launch-readiness charter ("never promise what doesn't exist") held for six weeks and then broke in three places without anyone editing the guides — the *policy* changed under them. Only a test notices that.
- **Why H2 reuses `SupportMessage`.** A prospect's question and a shop's question go to the same person and get the same reply. Two models would mean two admin pages and two sweeps for the same inbox.
- **Why not a chat widget.** Decided 2026-08-05, and the CSP argument has only strengthened since: every widget is a third-party script host, and the allowlist is `'self'` + Turnstile on purpose.
- **Found on the way, not fixed here (2026-09-17):** `check_subscription_alerts` still tells an expired trial "Your account is now locked" (its own comment says no grace exists) while `Tenant.effective_grace_period_end` grants `TRIAL_GRACE_DAYS` of read-only, and the two subscription-ended branches say "30 days of read-only access". Same class of drift as §0.2 item 3, in email rather than a guide. It belongs with the subscription-email copy, not the help center; `preview_emails` shows all three.
- **Two pre-existing test fixes rode along:** `tests/test_support_contact.py::test_app_is_blocked_but_contact_form_works` was in the red baseline — its fixture expired the trial 40 days back, inside the 14-day read-only window that did not exist when it was written, and it used a dashboard URL that had moved. Now 60 days and `reverse()`. It comes off the baseline.
