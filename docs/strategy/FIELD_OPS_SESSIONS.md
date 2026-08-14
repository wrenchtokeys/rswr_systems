# Field Operations Sessions — tech notifications, dispatch, scheduling

**Created:** 2026-08-11
**Author:** Claude (planning session with Drake)
**Status:** Proposed — pending Drake's review
**Companions:** `docs/strategy/IMPROVEMENT_SESSIONS.md` (sessions B1/B2 — this doc absorbs B1's execution and defers to its text), `docs/strategy/PRODUCT_DIRECTION.md` (Phase B item 5, the minimum-viable calendar), `docs/development/ROADMAP.md` (:148, :161).

This file is the **work queue** for making field operations real: a technician finds out about their job the moment it's assigned (Phase N), then knows where to go and when (Phase S), and can price and order the glass without leaving the app (Phase P). Each session is self-contained — a fresh Claude session with no memory should be able to execute exactly one session using only §0 and that session's table, without re-running the exploration that produced this doc.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED`

| Phase | Session | Size | Status |
|-------|---------|------|--------|
| N — The tech finds out | N1 · Assignment notifications that deliver | M | DONE (2026-08-12, PR #179) |
| N — The tech finds out | N2 · Fix dead verification SMS + tech texts | S | TODO (prod effect blocked on N4 — Appendix A) |
| N — The tech finds out | N3 · Notification coverage audit | S | TODO |
| N — The tech finds out | N4 · SMS opt-in compliance + registration v2 | S | CODE DONE (2026-08-12, PR pending) — v2 submission awaits deploy + Drake (see Notes) |
| S — Where and when | S1 · A real "booked time" | M | TODO |
| S — Where and when | S2 · Field dispatch (executes B1) | M | TODO |
| S — Where and when | S3 · Day / agenda view | M | TODO |
| S — Where and when | S4 · Customer requests carry when + where | M | TODO |
| S — Where and when | S5 · Dispatch board | L | TODO |
| S — Where and when | S6 · Routing / ETA / lot-walking | — | BACKLOG (deliberately deferred) |
| P — Parts | P1 · Mygrant live quotes + ordering | M | TODO (portal verified 2026-08-14 — Appendix B.5; **onboarding clock started: voicemail left with Mygrant IT 2026-08-14** — build order in P1) |
| P — Parts | P2 · Vehicle→NAGS part lookup | — | BACKLOG (blocked on a NAGS licensing decision — Appendix B) |

**Suggested sequence:** N1 → N4 (start the review clock early — it's days-to-weeks of waiting either way) → S1 → S2 → S3 → N2 (whenever the TFN approves) → S4 → N3 → S5 → (S6 stays backlog until S3/S5 prove demand). P1 is independent of both arcs and can slot anywhere once Mygrant API onboarding is done (like N4, start that clock early — it's a phone call to the rep).
Rationale: N1 is the reported bug and pays off alone. S1 is the schema foundation every S-session builds on. S2 is IMPROVEMENT_SESSIONS' "biggest daily-felt gain per hour spent." S4 before S5 because the board is only as good as the data flowing into it.

Sizes: **S** ≈ half a day · **M** ≈ 1–2 days · **L** ≈ 3–5 days.

---

## How to run a session

1. **Branch rule (Drake's hard requirement):** every session runs on its **own fresh branch cut from latest `main`** — `feat/fieldops-<id>-<slug>` (e.g. `feat/fieldops-n1-assignment-notifications`). Never stack on, share with, or merge from another session's branch. One session = one branch = one PR.
2. Another Claude session may share this working tree. Print `git branch --show-current` before every test run; never `git add -A` (add files by name).
3. Read §0 plus your session's table. Do not read the whole document to do one session.
4. Re-verify the session's "Verified current state" anchors before coding — line numbers drift.
5. Run the targeted tests named in the session, plus the fast smoke set (`python manage.py test tests.test_primary_contact tests.test_e2e_today`). The full suite has ~90–105 pre-existing failures on main — **compare against a main baseline, never count absolutes**.
6. When done: flip the status in the index table, and write what you learned under the session's **Notes** heading. That's what makes this a living doc.

---

## §0 Context Primer

*(All anchors verified 2026-08-11. Re-verify before relying on exact line numbers.)*

### Why an assigned tech hears nothing today — four stacked blockers

**Update 2026-08-12 (N1):** blockers 1–3 are fixed, and blocker 4's *email*
half is fixed (techs no longer need `email_verified`); the SMS half
(`send_sms` doesn't exist, `phone_verified` unreachable) is N2's. Details in
N1's Notes. The text below is kept as the original diagnosis:

1. **The assignment views bypass the notification system entirely.** All four assignment paths in `apps/technician_portal/views/repairs.py` — `assign_repair` (:925), `reassign_to_self` (:1043), `admin_reassign_repair` (:1761), `portal_bulk_reassign` (:1840) — hand-roll a `TechnicianNotification` row and never call `NotificationService`. `TechnicianNotification` (`apps/technician_portal/models.py:1787-1808`) is a display-only model: no title, no priority, no delivery machinery, read only by the dashboard's unread list (`views/dashboard.py:103`) — not even the notification bell, which queries `core.Notification`. Round-robin auto-assign (`apps/tenants/services/assignment_service.py:214-247`) does the same.
2. **The fallback signal has a null-hole and misses Replacements.** `apps/technician_portal/signals.py` does call the real service (`_notify_technician_assigned` :377 → `repair_assigned`; `_notify_technician_reassigned` :402 → `repair_reassigned_away`), but the reassignment branch (:142) requires an **old** technician — assigning a previously-unassigned job (the most common owner action) fires nothing. And every receiver is `sender=Repair`; **`Replacement` has no assignment signals at all**.
3. **The priority→channel map makes assignment email structurally impossible.** `repair_assigned` is seeded priority HIGH (core migration 0018:57), and `core/models/notification.py:174-185` maps HIGH → `['in_app','sms']` — no email, ever. The `emails/notifications/repair_assigned.html/.txt` templates exist, are rendered on every send (`core/services/notification_service.py`), and thrown away. Only URGENT yields `['in_app','email','sms']`; MEDIUM yields `['in_app','email']`.
4. **Verification-flag deadlock.** Email delivery requires `preferences.email_verified` — bulk-set for customers by core migration 0009, never for techs. SMS requires `phone_verified`, but the verification flow calls `SMSService.send_sms(...)` — **a method that does not exist** (`apps/technician_portal/views/notifications.py:322`; the AttributeError is swallowed at :329 as "Failed to send verification code"; identical dead call at `apps/customer_portal/views.py:3193`). So a tech can never become SMS-eligible.

What works: recipient resolution (`notification_service.py:340-379` falls through to `technician.user.email` / `technician.phone_number` correctly); the email templates; the seeding. Only the wiring and the gates are broken.

**Policy decision (Drake, 2026-08-11): staff notifications are default-ON.** Technicians are staff the owner added — trust owner-entered email (and phone, once SMS is live). Techs can opt out in preferences. Verification gates remain for customers only.

### SMS status

RS Systems' toll-free number `+18663115189` is **PENDING**, and its registration was **DENIED on 2026-08-11** for *"Unclear Opt-in Language"* — the number cannot send until a corrected version 2 is submitted and approved. This is **product work, not paperwork**: see **Appendix A**. All current SMS senders are customer-facing (invoice texts, review texts); nothing texts a tech. Prod is inert rather than broken — `SMS_ENABLED=true` but `SMS_ORIGINATION_IDENTITY` is unset, and `SMSService.is_enabled()` requires both.

### Scheduling — planned vs. built

**Planned but unbuilt:** B1 field dispatch (`IMPROVEMENT_SESSIONS.md:376-420`) puts address + `tel:` + a Google Maps link on the job card and adds `service_address` to `GlassService` — explicitly *not* a calendar. `PRODUCT_DIRECTION.md:96-142` sketches a ~3–4-week minimum-viable calendar: a day/week view over existing data plus a scheduled date/time field, with route optimization explicitly deferred and the success bar "a shop can run its day from the calendar view."

**Built: essentially nothing.**
- `GlassService.service_date` (`apps/technician_portal/models.py:326`) is the only date on a job — a *completion* timestamp defaulting to `now()`. The primary QuickJobForm (`forms.py:872-1060`) has **no date input at all**; only the legacy RepairForm (:407-410) and the multi-break form expose one.
- No `Appointment`/`Schedule`/`TimeSlot`/`Availability` model. No `service_address` anywhere (zero grep hits). `Vehicle` and `Technician` have no location fields. `Customer` has `address/city/state/zip` (`core/models/customer.py:81-84`) shown only on `customer_details.html`.
- "Today's Queue" (`views/dashboard.py:232-251`) is a misnomer: it filters by status with **no date filter** — a three-week-old job still shows.
- The customer request forms capture **no date, time window, or address** (repair: `apps/customer_portal/views.py:1926-2022`; replacement: :1711-1801) — a customer's timing wish can only travel as free text in the notes blob. The success message says *"Repair request received — you're on the schedule!"* (:2018) when no schedule exists.

**Dormant assets to reuse, not rebuild:**
- `CustomerRepairPreference.lot_walking_enabled/_frequency/_time/_days` (`apps/customer_portal/models.py:101-126`) — a fully-formed recurring-visit spec with a settings UI and **zero consumers**. Cheapest possible first calendar feed (S6).
- `RewardRedemption.preferred_date`/`preferred_time` (`apps/rewards_referrals/models.py:210-217`, staff display at `reward_fulfillment.html:87-109`) — a shipped customer-picks-date+window pattern to copy in S4.

---

# Phase N — The tech finds out

## N1 · Assignment notifications that actually deliver — DONE (2026-08-12)

| Field | Value |
|---|---|
| **Goal** | Assigning any job (Repair or Replacement, previously assigned or not, via any of the five paths) sends the assigned tech the existing `repair_assigned` email and rings the real notification bell. |
| **Size** | M |
| **Depends on** | — |
| **Why it matters** | This is the reported bug. Techs currently learn about work by refreshing the dashboard. |
| **Verified current state** | §0 blockers 1–4. Five write paths: 4 views in `views/repairs.py` (:925, :1043, :1761, :1840) + `assignment_service.py:214-247`. Signal null-hole `signals.py:142`; Repair-only receivers. HIGH → no email (`core/models/notification.py:174-185`). |
| **Considerations** | Prefer routing all five paths through **one** assignment helper (service function) that sets the tech, saves, and calls `NotificationService` — rather than patching five call sites and keeping the fragile signal as the only integration point. Keep writing `TechnicianNotification` for the dashboard list for now (N3 decides its fate). Staff default-ON: bypass/auto-satisfy `email_verified` when the recipient is a `Technician` (owner-entered address is trusted); keep the opt-out (`receive_email_notifications`) honored. Replacement needs coverage too — signals or explicit service calls, match whatever shape the helper takes. |
| **Decisions needed** | How email escapes the HIGH trap: **(a)** per-template channel override (recommended — add an explicit channels field/override so `repair_assigned` says `in_app+email+sms` without touching other templates), or **(b)** remap HIGH to include email — simpler but changes every HIGH template's behavior at once. Confirm with Drake if (b) is tempting. |
| **Acceptance criteria** | Owner assigns a previously-unassigned Repair → tech gets the `repair_assigned` email + bell notification. Same for Replacement. Reassignment notifies new tech (`repair_assigned`) and old tech (`repair_reassigned_away`). Bulk reassign notifies each affected tech once. Tech with `receive_email_notifications=False` gets in-app only. No customer receives any of these. Tests cover all five paths. |
| **Out of scope** | SMS channel (N2). Any scheduling data in the email body (S1/S2 can enrich it later). Digest/batching. |

**Notes** *(session run 2026-08-12, branch `feat/fieldops-n1-assignment-notifications`)*

- **Shipped as designed, decision (a) taken:** `NotificationTemplate.channels_override`
  (core migration `0027_assignment_notification_channels`) — `repair_assigned` now sends
  `in_app+email+sms` without touching any other HIGH template. Staff default-ON is
  implemented as `TechnicianNotificationPreference.can_send_email()` override (no
  `email_verified` gate for techs; `receive_email_notifications` opt-out honored).
- **The single write path is `apps/technician_portal/services/assignments.py`** —
  `assign_job()` (used by assign/reassign/bulk views) + `notify_assignment_change()`
  (shared with the fixed signals, which remain as the fallback for form edits,
  auto-assign, and future code). Suppression contract: `_assignment_notifications_handled`
  (helper already notified), `_assignment_actor_user_id` (never notify someone about
  their own action), `_skip_assignment_notifications` (walk-in logging, extra batch breaks).
- **Corrections to §0's diagnosis found while building:**
  - `technician` is **NOT NULL** on Repair and Replacement — there is no DB-level
    "unassigned" job. The doc's "assigning a previously-unassigned job" is really
    "accepting a REQUESTED job that already holds a provisional tech, often the same
    one" — the signal saw no change and stayed silent. Fixed with two rules: no
    assignment notification while a job is REQUESTED; notify (force) when it crosses
    REQUESTED → APPROVED/IN_PROGRESS. This also gives replacements their "job is a
    go" moment when the customer approves.
  - `repair_assigned.html/.txt` referenced `{{ repair.* }}`/`{{ view_repair_url }}` —
    context keys that are never provided (contexts must stay JSON-serializable for
    `template_context`). The emails would have rendered mostly empty even without the
    channel bug. Rewritten against the real flat context, job-type-aware so
    Replacements say "Replacement".
  - Email CTA links used relative `{{ action_url }}` — broken in a mail client.
    Fixed here and in `repair_reassigned_away`; any new email template must use
    `{{ base_url }}{{ action_url }}`.
- **Bulk reassign sends one summary per affected tech** (new seeded templates
  `jobs_bulk_assigned`, `jobs_bulk_reassigned_away`), not one email per repair.
  Per-repair `TechnicianNotification` dashboard rows are preserved everywhere.
- **Auto-assign (`apps/tenants/services/assignment_service.py`) lost its `_notify_tech`**
  — the fixed signal now covers it with the real system (its hand-rolled rows would
  have doubled up).
- **Prod rollout:** the migration does everything (channels + email-field backfill +
  new templates). No manual `setup_notification_templates` run needed; the command was
  updated to stay canonical for fresh installs.
- **Left for N3:** `repair_request_submitted` still fires at create time to the
  *provisional* tech — if auto-assign moves the request a moment later, the wrong tech
  holds the "New Repair Request" bell. Also: templates seeded by core migration 0018
  (fresh DBs that never ran the command) have blank email fields for the *other* six
  lifecycle templates — only the two assignment ones were backfilled here.
- **Tests:** `tests/test_fieldops_n1.py` (14 tests: all five paths, Replacement,
  REQUESTED acceptance, opt-out, self-action suppression, no-customer-leak, channel
  plumbing). Smoke set + 117 adjacent tests green on the branch.

## N2 · Fix the dead verification SMS + tech assignment texts — TODO

| Field | Value |
|---|---|
| **Goal** | The phone-verification flow actually sends a code, and (once the TFN is approved) an assigned tech with a phone number gets a text. |
| **Size** | S |
| **Depends on** | N1 (channel wiring). Prod effect blocked on TFN approval — Appendix A. |
| **Why it matters** | Field techs live on their phones, not email. Also, two shipped flows (tech + customer phone verification) currently fail 100% of the time in production. |
| **Verified current state** | `SMSService` has no `send_sms` method (`core/services/sms_service.py:56-300` — methods are `is_enabled`, `normalize_phone`, `send_notification_sms`, …). Dead calls: `apps/technician_portal/views/notifications.py:322` (error swallowed :329) and `apps/customer_portal/views.py:3193`. SMS branch gates: `notification_service.py:206-208` (`receive_sms_notifications` + `phone_verified`, both default False). `Technician.phone_number` exists (`models.py:28-38`). |
| **Considerations** | Add a generic `send_sms` (or point both callers at `send_notification_sms`'s transport) — keep the delivery-log pattern the existing senders use. Staff default-ON per N1 policy: techs skip phone verification (owner-entered number is trusted; opt-out honored); the fixed verification flow still matters for **customers**. Respect `SMSService.is_enabled()` so dev/staging without `SMS_ORIGINATION_IDENTITY` stays silent. |
| **Decisions needed** | Whether assignment SMS is on for all techs by default or per-tech opt-in — recommend default-ON with opt-out, consistent with email. |
| **Acceptance criteria** | Verification SMS sends a real code in prod (customer flow). Assigning a job to a tech with a phone number sends a text (behind `is_enabled()`). No AttributeError anywhere in the SMS path; failures are logged, not swallowed. |
| **Out of scope** | Two-way SMS / replies (B2 in IMPROVEMENT_SESSIONS). ETA texts (S6). |

**Notes**

## N3 · Notification coverage audit — TODO

| Field | Value |
|---|---|
| **Goal** | Every event a tech or shop cares about notifies the right person through the real system; the parallel `TechnicianNotification`-only paths stop silently diverging. |
| **Size** | S |
| **Depends on** | N1. Better after S4 exists (schedule-changed events). |
| **Why it matters** | Two notification systems drifted apart once already — that's how this whole bug happened. |
| **Verified current state** | `TechnicianNotification` writes are scattered (assignment views, redemption flows, replacement request `_notify_shop_replacement_requested` at `apps/customer_portal/views.py:1804+`). No `replacement_*` lifecycle templates exist (per CLAUDE.md). Bell reads `core.Notification` only. |
| **Considerations** | Inventory first: grep every `TechnicianNotification.objects.create` and decide each one — fold into `NotificationService`, keep as dashboard-only, or delete. Add the missing events found while writing this doc: customer-requested job auto-assigned (tech should hear), schedule confirmed/changed (after S4). Consider whether `TechnicianNotification` can become a thin projection of `core.Notification` instead of a second source of truth. |
| **Decisions needed** | Whether to add `replacement_*` lifecycle templates now or keep replacements on the shop-email path (Drake previously deferred replacement lifecycle emails by choice — see `simplicity-first-product-direction`; don't expand customer-facing email without asking). |
| **Acceptance criteria** | A written inventory table (in this doc's Notes) of every tech-facing event → recipient → channel; no event a tech must act on lands only in the dashboard list. |
| **Out of scope** | Customer-facing notification redesign. |

**Notes**

## N4 · SMS opt-in compliance + registration v2 — CODE DONE (2026-08-12)

| Field | Value |
|---|---|
| **Goal** | The consent surface carries carrier-compliant language, and toll-free registration version 2 is submitted with a screenshot of it. |
| **Size** | S |
| **Depends on** | — (independent of N1/N3; blocks N2's prod effect) |
| **Why it matters** | Every SMS feature shipped 2026-08-09 (#156/#159/#158) is dark, and stays dark until this number is approved. Version 1 was denied 2026-08-11 — waiting changes nothing on its own. |
| **Verified current state** | Denial reason + full analysis in **Appendix A**. Consent checkbox: `templates/technician_portal/customer_form.html:121` and `customer_edit.html:84` (label states none of message type / frequency / rates / STOP). Compliant copy already written at `templates/saas/sms_program.html:15-50`. Consent model: `Customer.sms_opt_in` / `sms_opt_in_at`, stamped in `core/models/customer.py:190-222`. Prod inert: `SMS_ENABLED=true`, `SMS_ORIGINATION_IDENTITY` unset. |
| **Considerations** | Two levels: (a) minimum — expand the checkbox label in both templates; (b) better — a first-party customer opt-in (portal profile or public invoice page) so consent isn't shop-attested, which is what the reviewer objected to. Recommend doing (b); a second denial costs another review cycle. Keep the copy identical to `/sms/` so the screenshot and the disclosure agree. `sms_opt_in_at` already gives an auditable consent timestamp — surface it if the reviewer asks for proof. |
| **Decisions needed** | Whether to build the first-party opt-in now (recommended) or resubmit with checkbox copy alone and accept the risk. |
| **Acceptance criteria** | Consent surface states message types, frequency, "Msg & data rates may apply", STOP/HELP, and links to `/sms/`. Screenshot taken from live prod. Registration version 2 submitted; `describe-registration-versions` shows version 2 `REVIEWING`. |
| **Out of scope** | Sending anything to techs (N2). Two-way SMS (B2 in IMPROVEMENT_SESSIONS). |

**Notes** *(session run 2026-08-12, branch `feat/fieldops-n4-sms-opt-in`)*

- **Both levels built — (a) and (b).** Shop-side checkbox in `customer_form.html` +
  `customer_edit.html` now carries the full disclosure (message types, "typically 1–2
  messages per completed job", msg & data rates, STOP/HELP, `/sms/` link). AND a
  **first-party opt-in on the public invoice page** (`templates/billing/public_invoice_view.html`):
  a "Get text updates from {shop}" card with a required consent checkbox, shown whenever
  the invoice's customer has a usable mobile and isn't opted in. POSTs to
  `/invoice/<id>/<token>/sms-opt-in/` (`public_invoice_sms_opt_in` in `rs_systems/views.py`).
  This is the screen to screenshot for registration v2 — it's the customer's own device,
  which is exactly what the reviewer objected to not having.
- **Deliberately NOT gated on `SMSService.is_enabled()`** — consent collection (and the
  screenshot) must work while the number is still pending approval. The page shows only
  the LAST 4 digits of the phone (the full number never renders on a token-shared page).
- **Consent provenance is now recorded:** `Customer.sms_opt_in_source` (`SHOP`/`CUSTOMER`,
  core migration `0028_customer_sms_opt_in_source`; existing consent backfilled `SHOP`).
  `record_sms_consent(source=...)` — first-party consent *upgrades* shop-attested (new
  timestamp + source), shop attestation never downgrades first-party. If the reviewer asks
  for proof of consent, `sms_opt_in_at` + `sms_opt_in_source` is the audit answer.
- **`/sms/` "How you opt in" rewritten** to lead with the self-serve invoice-page path so
  the program terms and the screenshot agree.
- **Tests:** `tests/test_fieldops_n4.py` (15: disclosure phrases on both shop forms +
  the invoice widget, consent-source semantics, POST endpoint incl. bad-token/GET/no-phone).
  Also fixed a pre-existing N1-introduced failure in `test_invoice_send_polish` —
  creating a Replacement now emails the tech, so `mail.outbox[0]` was the assignment
  email, not the invoice email. Any outbox-indexing test that creates jobs is suspect now.
- **What remains is Drake's (after this PR deploys):**
  1. Make/pick a test customer **with a mobile number, not opted in** in the live shop,
     open one of their invoice public links, screenshot the "Get text updates" card
     (checkbox + disclosure visible, no real PII).
  2. Update the registration: `optInDescription` should now say consent is collected
     first-party on the customer's own invoice page (checkbox with message types,
     frequency, rates, STOP/HELP), with shop-recorded consent as the secondary path;
     attach the new screenshot as `optInImage`.
  3. Submit version 2 — console (End User Messaging → Registrations) or CLI:
     `aws pinpoint-sms-voice-v2 put-registration-field-value` for the changed fields, then
     `aws pinpoint-sms-voice-v2 submit-registration-version --registration-id registration-3c4aceac54424845b6d540e818f2bddb`
     (us-east-1). Verify with `describe-registration-versions` → version 2 `REVIEWING`.
  4. When it flips COMPLETE: the activation checklist at the bottom of Appendix A.

---

# Phase S — The tech knows where and when

## S1 · A real "booked time" — TODO

| Field | Value |
|---|---|
| **Goal** | "When we said we'd come" becomes a first-class field, distinct from "when the work happened," and the tech dashboard becomes date-aware. |
| **Size** | M |
| **Depends on** | — (foundation for S2–S6) |
| **Why it matters** | Every scheduling feature needs a booking time. Today `service_date` conflates booking and completion, defaults to `now()`, and the primary job form can't even set it. |
| **Verified current state** | `GlassService.service_date` `DateTimeField(default=timezone.now)` (`apps/technician_portal/models.py:326`), inherited by Repair + Replacement; back-compat alias `repair_date` (:761-773, :1577-1583); indexes at :1394/:1401/:1768/:1775. QuickJobForm (`forms.py:872-1060`) has no date field. "Today's Queue" = status filter only (`views/dashboard.py:232-251`, replacements merged :338-350). |
| **Considerations** | Add `scheduled_for` (nullable DateTimeField) + optional `scheduled_window_end` to `GlassService` — one migration covers both job types. **Do not repurpose `service_date`** — it's a completion timestamp with sort/index semantics all over the app. Null `scheduled_for` = "unscheduled" bucket, which keeps walk-in/quick-complete flows (`already_completed` default True, `forms.py:945`) untouched. Dashboard: Today / Unscheduled / Overdue buckets — a query change plus headers, not a new subsystem. Multi-break form already parses a date (`views/batch.py:245,307,455`) — wire it to the new field consistently. Flatpickr is already vendored for date inputs. |
| **Decisions needed** | Whether `scheduled_for` appears on the quick-job form for already-completed work (recommend: only when "already completed" is unchecked — keep the walk-in path zero-friction). |
| **Acceptance criteria** | A job can be created/edited with a scheduled time via QuickJobForm and legacy forms. Tech dashboard shows Today (scheduled today), Unscheduled, and Overdue (scheduled before today, not completed) buckets. Existing flows with no date behave exactly as before. Migration is additive-only. |
| **Out of scope** | Any calendar rendering (S3). Customer-side capture (S4). Capacity/conflicts (S5). |

**Notes**

## S2 · Field dispatch — executes B1 — TODO

| Field | Value |
|---|---|
| **Goal** | B1's goal verbatim: "A technician can go from the job list to the customer's door without leaving the app." |
| **Size** | M |
| **Depends on** | — (independent of S1; sequence-adjacent) |
| **Why it matters** | Ranked #3 in IMPROVEMENT_SESSIONS' sequence — "biggest daily-felt gain per hour spent in the whole document." |
| **Verified current state** | Full spec at `IMPROVEMENT_SESSIONS.md:376-420` — **this doc defers to that text; read it before starting.** Since it was written, the dashboard job card moved to `templates/technician_portal/dashboard.html:57-124`; still no address/phone/map/tel anywhere on card, job list, or `repair_detail.html` (phone only at :351). Customer address exists (`core/models/customer.py:81-84`), surfaced only on `customer_details.html:105-114`. No `service_address` in the codebase. |
| **Considerations** | B1's open decision (:413) is **taken: structured fields** (`service_address/_city/_state/_zip` on `GlassService`) — the foundation S5/S6 need. Prefill from customer address; tech can override per job. `tel:` + Google Maps universal URL built client-side so addresses stay out of logged query strings (B1 :402-409). 44px tap targets; never put *Call* adjacent to *Complete* (:406-407). Graceful degradation for walk-ins with no address (:410-411). Run `./scripts/build_css.sh` after template changes; safelist any dynamic classes. |
| **Decisions needed** | None — inherited decisions are recorded above. |
| **Acceptance criteria** | B1's own acceptance criteria, plus: address prefills from customer on job create, appears on job card + detail with working map/call links, and both Repair and Replacement carry it. Update B1's status in IMPROVEMENT_SESSIONS.md to point here. |
| **Out of scope** | B1's own exclusions stand: calendars, time slots, route optimization, ETA, live tracking. |

**Notes**

## S3 · Day / agenda view — TODO

| Field | Value |
|---|---|
| **Goal** | A tech sees "my day" in order; an owner/manager sees every tech's day. PRODUCT_DIRECTION's success bar: *a shop can run its day from the calendar view.* |
| **Size** | M |
| **Depends on** | S1 (needs `scheduled_for`). S2 makes each entry actionable (address/call/map). |
| **Why it matters** | "Techs can't see where they're supposed to go" — this is the surface that fixes it. |
| **Verified current state** | No calendar/agenda/today URL exists in any app's urls.py. PRODUCT_DIRECTION.md:96-142 sketches exactly this view (~read-mostly, day/week, per-tech). |
| **Considerations** | Read-mostly first: a day list grouped by tech, ordered by `scheduled_for`, with the S2 address/call/map actions inline. Reuse existing job-card partials rather than inventing a new card. Tenant-scoped, obviously. A simple date navigator (prev/today/next + flatpickr jump) beats a month grid nobody asked for. Owner view = same query, grouped by technician, unassigned+unscheduled surfaced at top as a to-triage rail (seed of S5). |
| **Decisions needed** | Week view now or later (recommend: day view only; add week when someone asks). Where it lives in nav (recommend: "Schedule" link in technician portal nav; dashboard "Today" bucket links to it). |
| **Acceptance criteria** | `/tech/schedule/` (or similar) shows the logged-in tech's day; managers/owners see all techs; entries link to job detail and carry S2's map/call actions; empty states are honest ("Nothing scheduled — X unscheduled jobs" linking to the list). |
| **Out of scope** | Drag-and-drop, editing times from the view (S5), customer-facing schedule, iCal export. |

**Notes**

## S4 · Customer requests carry when + where — TODO

| Field | Value |
|---|---|
| **Goal** | A customer requesting work can say where the vehicle is and when it's available; that information rides the job all the way to the assigned tech; and the shop confirms the slot. |
| **Size** | M |
| **Depends on** | S1 (fields), N1 (confirmation notification). S2 recommended (address plumbing exists). |
| **Why it matters** | Drake's scenario: "what if a customer requests a job and the truck is located somewhere else or has to be in a certain time frame." Today that wish can only travel as free text — and the success message *promises a schedule that doesn't exist* (`views.py:2018`). |
| **Verified current state** | Repair request reads `unit_number/description/damage_type/damage_photo_before` (`apps/customer_portal/views.py:1940-1943`); replacement reads `unit_number/glass_position/description/damage_photo` (:1749-1752). No date/window/address on either form. Copy-the-pattern precedent: `RewardRedemption.preferred_date`/`preferred_time` (`apps/rewards_referrals/models.py:210-217`; staff display `reward_fulfillment.html:87-109`). |
| **Considerations** | Capture as *preference*, not booking: `preferred_date` + a coarse window (morning/afternoon/anytime — mirror the RewardRedemption pattern) + optional service location (prefill company address; free-notes field for "truck is at yard 4"). Shop confirms/adjusts → writes `scheduled_for` (S1) → notifies customer AND assigned tech (N1/N3). Fix the over-promise copy at :2018 to honest wording ("Request received — we'll confirm a time"). Surface preferences prominently on job detail + the S3 day view until confirmed. Both request forms, both job types. |
| **Decisions needed** | Whether confirmation is a required shop step or `scheduled_for` silently defaults to the preference (recommend: explicit confirm — it's one click and it's the honest version of "you're on the schedule"). Whether customers see the confirmed time in the portal (recommend: yes, on the service detail page). |
| **Acceptance criteria** | Customer submits a request with date/window/location → shop sees it on the job + triage rail → confirming writes `scheduled_for` and notifies customer + tech → tech's day view shows the job at the right time and place. Requests without preferences behave as today. Success message no longer lies. |
| **Out of scope** | Live availability/slot-picking against tech capacity (S5/S6). Self-service rescheduling. |

**Notes**

## S5 · Dispatch board — TODO

| Field | Value |
|---|---|
| **Goal** | One owner/manager surface where triage happens: unassigned + unscheduled work beside each tech's day; assign and schedule in one motion; conflicts visible. |
| **Size** | L |
| **Depends on** | S1–S4, N1. |
| **Why it matters** | This is where "notification," "address," and "time" compound into an actual dispatch workflow — the shop runs its morning from one screen. |
| **Verified current state** | Nothing exists. Assignment lives in per-job views (`assign_repair` etc.); triage is the REQUESTED queue; no combined surface. |
| **Considerations** | Build on S3's owner view: add an unscheduled/unassigned rail and inline assign+schedule controls (POST to the N1 assignment helper — one code path for assignment, always). Conflict display is *informational* first (two jobs overlapping for one tech; job scheduled outside customer's preferred window) — no hard blocking. Drag-and-drop is a polish pass, not the MVP; plain controls first. Every assignment from the board fires the N1 notification automatically because it goes through the same helper. **Known gap — technician availability:** nothing in the arc models working hours or days off, so conflict detection here can only see job-vs-job overlap, not "Marcus doesn't work Tuesdays." Don't build an availability model preemptively — but when scoping this session, decide whether a minimal per-tech working-hours field (or even a free-text "usual schedule" note shown on the board) is worth including, and record the decision in Notes. Full availability/capacity modeling stays in S6's backlog. |
| **Decisions needed** | Defer all — scope this session properly when S1–S4 are real. Written now only so the arc has a visible destination. |
| **Acceptance criteria** | (Draft) A manager can take a REQUESTED/unassigned job from the rail, pick tech + time, and the tech is notified — without leaving the board. Double-booking is visibly flagged. |
| **Out of scope** | Route optimization, capacity math, customer self-scheduling (S6/backlog). |

**Notes**

## S6 · Routing / ETA / lot-walking — BACKLOG (deliberately deferred)

Not a session yet — a parking spot so nobody re-litigates scope. PRODUCT_DIRECTION.md:117/:130 explicitly defers route optimization and time-slot booking until the basic calendar proves demand; this doc honors that. When S3/S5 have real usage, candidates in rough order:

1. **Lot-walking consumer** — `CustomerRepairPreference.lot_walking_*` (`apps/customer_portal/models.py:101-126`) is a complete recurring-visit spec with a UI and zero consumers. Feed it into the S3 day view / S5 board as recurring visit entries. Cheapest item here.
2. **ETA texts** — "Marcus is on his way, ETA 2:15." Needs two-way SMS (B2, size L, provider work) or at minimum outbound-only ETA sends via the N2 plumbing.
3. **Route ordering** — order a tech's day geographically (the ROADMAP's "lot-walking scheduler"). Needs S2's structured addresses; probably needs geocoding. Do not start before a shop asks.
4. **Technician availability / working hours** — per-tech schedules (days off, hours) so S5's conflict display can flag "scheduled outside Marcus's hours," and the eventual prerequisite for any customer-facing slot picking. S5 may ship a minimal version (see its Considerations); the real model lives here until demand is proven.
5. **Self-service rescheduling** — customers changing a confirmed time from the portal (S4 deliberately excludes this). Needs a notify-shop + re-confirm loop so a reschedule can't silently invalidate a tech's day; pairs naturally with item 4 once slots are real.

---

# Phase P — Parts (added 2026-08-12 from the sourcing investigation — full findings in Appendix B)

The one-sentence version: **live Mygrant quotes and ordering are real and buildable now** (Mygrant publishes a SOAP web-service API, keyed on the NAGS numbers techs already type, authenticated with the shop's own Mygrant account); **an in-app vehicle→NAGS part lookup is the gated, expensive half** (NAGS data only comes via a negotiated Mitchell license at roughly $60–75/NAGS-user/month market rate, and Mitchell doesn't even provide the VIN→part mapping). P1 deliberately does not depend on P2.

## P1 · Mygrant live quotes + ordering — TODO (portal access verified 2026-08-14; onboarding requested — voicemail left with Mygrant IT 2026-08-14)

**P1 order of work** *(updated 2026-08-14 — do these in order; 1–3 need no code and can overlap the callback wait)*:
1. **API onboarding** — voicemail left with Mygrant IT dept 2026-08-14. If no callback within a few business days, follow up through the shop's sales rep/CSR (the spec routes onboarding through them — "API Integration Set Up Form"). Done when Generate Key appears in Edit User Settings and a key is generated.
2. **On that same call: confirm the billing model** — which lookups bill (~$1/search per Drake): part-number, VIN, make/model — and whether API Inquiries bill the same. This decides how aggressive the quote UX can be.
3. **Decide credential encryption at rest** — first secret-storing model in the codebase (no Fernet/KMS precedent). Pick the mechanism (recommend: Fernet via `cryptography`, key from an env var separate from `SECRET_KEY`) before any model code.
4. **Connect plumbing** — `MygrantConfig` (per-tenant, `TenantConfig` pattern), owner Settings "Connect your Mygrant account" card, Test connection (one staging Inquiry). Feature invisible without it.
5. **Quote-only PR** — quote button on the Replacement, SKU list with My Price/stock/branch/truck-run, one-tap fill of `parts_cost`, profit-on-ticket display. Staging first, then prod. This is the daily win; ship it alone.
6. **Ordering PR** — exact-SKU order with delivery/Will-Call, RS job number in the PO field, `DRLineNo` stamped on the job, every documented error code surfaced honestly.
7. **Then stop** — returns aren't in the API yet; other suppliers wait for a shop to ask.

**Design principle (Drake's dad, who runs the pilot account, 2026-08-14): "Mygrant portal is already easy."** RS Systems must not re-implement or complicate the portal — the killer feature is *context the portal can't have*: the quote fires from the job that already holds the NAGS number, the chosen SKU's cost lands in `parts_cost` in one tap, the order number stamps onto the job, and the job shows **cost vs. what the shop is charging = profit on this ticket**. Anything that makes a tech leave the job and come back is a loss; a general Mygrant browse/search screen disconnected from a job is explicitly out.

| Field | Value |
|---|---|
| **Goal** | On a Replacement with a NAGS number, one click shows live Mygrant price (list + this shop's price), quantity available, sourcing branch and next truck run — and, phase two of the session, places the order (delivery or Will Call) and stamps the order number on the job. |
| **Size** | M (quotes alone ≈ S; ordering adds the exact-SKU picker + error handling) |
| **Depends on** | Nothing in Phases N/S. Blocked on a human step: the shop's Mygrant rep/CSR must complete "API User onboarding" (API Integration Set Up Form), then the shop self-serves an API key at MygrantGlass.com → My Account → Edit User Settings → Generate Key. **Verified first-hand 2026-08-14** on the pilot account: Edit User Settings (`/pages/account.aspx`) shows only Full Name + Change Password — no Generate Key — so rep onboarding really is the gate, and that phone call is the long pole. **Clock started: voicemail left with Mygrant IT 2026-08-14.** While on the callback, also confirm the search/quote **billing model** (see Considerations) and whether API Inquiries bill the same way. |
| **Why it matters** | Today pricing a replacement means calling the warehouse or logging into mygrantglass.com, then hand-typing `parts_cost`. A quote button turns that into seconds, prices from the shop's own account, and kills transcription errors. Ordering from the job closes the loop. |
| **Verified current state** | `Replacement.nags_number` is free text (`apps/technician_portal/models.py:1611`), `parts_cost`/`labor_cost` hand-entered nearby, `glass_type` OEM/AFTERMARKET; form field at `apps/technician_portal/forms.py:974`. Vehicle has `year/make/model/vin` (`core/models/vehicle.py:56-68`). Nothing in the codebase talks to any supplier. Spec: `docs/reference/mygrant-soap-webservices-spec-rev-2025-05.pdf` (34 pp., rev 2025-05-05). Production endpoint verified live: `https://webservice.mygrantglass.com/v2/CoRE650WebService.asmx` (+ `-staging` host and `EnvironmentID=TEST`). **2026-08-14: logged-in portal walkthrough on the pilot account (Drake's dad's shop — a live RS Systems tenant) confirmed everything the spec promises is real on the account**: live per-brand `My Price` vs. list, stock, 4 warehouses + regional/national sweep, cart→order with delivery vs. Will-Call and a per-line PO field, order history searchable by PO with CSV export — full page/endpoint map in **Appendix B.5**. Portal *automation* was evaluated and **rejected on ToS grounds** (also B.5) — the SOAP API is the only sanctioned route. |
| **Considerations** | **"Connect your Mygrant account" is the multi-shop answer** — credentials are per-tenant, never the platform's: a `MygrantConfig` inheriting `TenantConfig` (`common/models.py:16` mandates the pattern; `ReviewConfig` is the closest template — off-by-default integration config with `get_for_tenant()`), holding CustomerID `C######-###`, WebUserID, password, API key, entered in an owner Settings card with a **Test connection** button (one staging Inquiry). Mygrant has no OAuth, so "connect" = credential entry + validated ping — the same shop-credential model GlassBiller/Omega/GlasPacLX use; no vendor certification exists or is needed. Gate shape mirrors Stripe Connect (`apps/tenants/services/connect_service.py` `is_enabled()`): a tenant without credentials sees nothing new anywhere, and no platform-wide credential path exists at all. **Encryption at rest is an unmade decision, not a reuse**: nothing in this codebase stores a third-party secret today (no Fernet/KMS precedent anywhere) — decide the mechanism before building. **Cost per lookup (Drake, 2026-08-14): searches on the account bill ~$1 each** — so quotes must be a deliberate button-press (never auto-fire on page load or refresh), one Inquiry's multi-SKU response is cached and reused for the pick step, and the UI says a quote may incur a supplier charge; confirm the exact billing model (which search types, and whether API Inquiries bill the same) on the rep call. The order's per-line **PO field should carry the RS Systems job/invoice number** — Mygrant's order history is searchable by PO, which makes reconciliation two-sided for free. The API is one SOAP operation (`InboundTraffic`, string-in/string-out CDATA XML) — hand-built envelope over `requests`, no SOAP library needed. An Inquiry on bare NAGS prefix+number returns *multiple* concrete SKUs (brands, moldings, sensors) with `QtyAvailable`, `ListUnitPrice`, `CustomerUnitPrice`, branch and truck-run — orders require an exact SKU ("Only exact orders will be placed"), so the UI flow is quote → pick SKU → order. Rich item-level error codes (`NoStock`, `ChooseSubstitute`, `OverCreditLimit`, `NoTruckRoute`, surcharge cases) must surface honestly, not be swallowed. Returns are NOT in the API yet ("Coming Soon") — don't promise them. API terms: no redistributing/reselling API data (shop's own prices shown to the shop is fine; don't leak `CustomerUnitPrice` into anything customer-facing), no scraping the website (site ToS separately prohibits it — the API is the only sanctioned route), rate limits at Mygrant's discretion, license revocable. |
| **Decisions needed** | Quote-only first PR vs. quote+order in one session (recommend: ship quote-only first — it's the daily win and de-risks the credential plumbing). Whether a successful quote should offer to fill `parts_cost` (recommend: yes, one tap, never silent). Encryption-at-rest mechanism for tenant credentials (first in the codebase — e.g. Fernet with an env-derived key vs. AWS KMS). Where profit-on-ticket renders (job detail vs. invoice editor) — shop-facing only, never customer-facing. |
| **Acceptance criteria** | Tenant with credentials configured: quote button on the Replacement form/detail returns live SKUs with prices/availability against staging first, then prod. Tenant without credentials sees nothing new. Order path (if in scope) writes the Mygrant order number (`DRLineNo` S-number) onto the job and handles every documented error code with a human message. No Mygrant price ever appears in customer-facing surfaces. |
| **Out of scope** | Vehicle→NAGS lookup (P2). Other suppliers (Pilkington/PGW use the same per-shop-credential pattern — add later behind the same abstraction if a shop asks). Returns. Insurance EDI/Glaxis. |

**Notes** *(fill in after the session)*

## P2 · Vehicle→NAGS part lookup — BACKLOG (blocked on a licensing decision)

Not a session yet — the blocker is a contract, not code. To show "2024 F-150 windshield = FW05678 @ $XXX list" inside RS Systems, the NAGS database must be licensed from Mitchell International (no public pricing; negotiated per-end-user-seat terms; competitors pass it through at ~$60–75/NAGS-user/month, with cheap non-NAGS tech seats). Mitchell provides **data only** — every licensee builds or buys its own VIN→part mapping, and data refreshes land every January/May/September. Interim options that need no Mitchell contract: keep typing NAGS numbers (a per-lookup web tool like AutoGlassMatch is ~$1/lookup for the shop), and P1 works today because Mygrant's API accepts the NAGS number as input. **2026-08-14: the Mygrant portal itself already has Search by Make/Model (`/pages/searchm.aspx`) and Search by VIN (`/pages/searchvin.aspx`) built in** — so the tech's vehicle→part step has a supplier-provided home today (per Drake, searches bill ~$1 each — same ballpark as AutoGlassMatch), which further weakens the case for a Mitchell contract until real multi-shop demand shows up. Decision for Drake: whether shop demand ever justifies opening the Mitchell conversation (contact via mitchell.com NAGS pages / 800-551-4012) — see Appendix B for the full landscape, legal constraints, and competitor pricing table.

---

## Traps this work has already hit — don't repeat them

- **`TechnicianNotification` is display-only.** It has no delivery machinery and doesn't even feed the bell. Writing one and believing "the tech was notified" is how the original bug shipped. *(exploration, 2026-08-11)*
- **Priority HIGH excludes email.** `core/models/notification.py:174-185`: HIGH → `['in_app','sms']`. An email template on a HIGH notification renders and is discarded silently. Remapping HIGH changes every HIGH template at once — prefer per-template channels (N1 decision).
- **`SMSService.send_sms` does not exist.** Two production call sites invoke it; both fail silently behind broad `except` blocks. Search for swallowed AttributeErrors before trusting any "we already send X" claim in this area.
- **`service_date` is not a booking time.** It defaults to `now()`, means "when work happened," and has sort/index semantics everywhere. Repurposing it instead of adding `scheduled_for` will corrupt history and reports.
- **"Today's Queue" contains no date logic.** It's a status filter. Don't extend it assuming it's date-scoped.
- **The customer-facing copy already over-promises.** "You're on the schedule!" (`apps/customer_portal/views.py:2018`). When touching these flows, fix copy to match reality — Drake's bar: never promise nonexistent features.
- **Signals with `created`/`old_value` guards have null-holes.** `signals.py:142` skipped the unassigned→assigned transition for years. Prefer explicit service calls at the write path over signal archaeology.
- **`technician` is NOT NULL — "unassigned" does not exist at the DB level.** *(N1, 2026-08-12)* Every Repair/Replacement always holds a tech; a "unassigned" job in the product sense is a REQUESTED job carrying a provisional fallback tech. S5's "unassigned rail" and any dashboard bucket must key off `queue_status='REQUESTED'` (or a future explicit flag), not `technician IS NULL`.
- **Email templates must use the flat notification context and absolute links.** *(N1)* Notification contexts are persisted to a JSONField, so they can never contain model objects — a template referencing `{{ repair.* }}` renders empty and nothing errors. CTA links must be `{{ base_url }}{{ action_url }}`; a bare `{{ action_url }}` is a dead relative link in a mail client.
- **Full suite has ~90–105 pre-existing failures on main.** Compare against a fresh main baseline; never count absolute failures. Another session may share the working tree — print `git branch --show-current` with every run.

---

## Appendix A — SMS toll-free number status + activation checklist

Checked live 2026-08-12 (`aws pinpoint-sms-voice-v2`, us-east-1, account tier PRODUCTION):

| Number | Status | Registration |
|---|---|---|
| `+18663115189` (RS Systems) | **PENDING** | `REQUIRES_UPDATES` — version 1 **DENIED 2026-08-11 16:58** |
| `+18559394817` (Rockstar shop, older) | ACTIVE | COMPLETE |

```bash
aws pinpoint-sms-voice-v2 describe-registrations --region us-east-1 \
  --query 'Registrations[].[RegistrationType,RegistrationStatus]'
# the denial reason lives on the VERSION, not the registration:
aws pinpoint-sms-voice-v2 describe-registration-versions --region us-east-1 \
  --registration-id registration-3c4aceac54424845b6d540e818f2bddb \
  --query 'RegistrationVersions[].[VersionNumber,RegistrationVersionStatus,DeniedReasons]'
```

### Why it was denied — and why the fix is product work

> **Unclear Opt-in Language** — *"The language used in your opt-in process is unclear or insufficient to obtain proper consent. Opt-in language must explicitly state message content frequency and that consent is for SMS messages."*

The submitted `messagingUseCase.optInImage` documents **third-party** consent: the shop-side
checkbox at `templates/technician_portal/customer_form.html:121`, whose entire label is
*"OK to text this customer (they've agreed to receive service texts)."* At the point of consent
there is no message-type list, no frequency, no msg&data-rates line, and no STOP/HELP.

All of that language **does** exist — on `/sms/` (`templates/saas/sms_program.html:15-50`), which
is not the screen in the screenshot. The reviewer sees a shop attesting on a customer's behalf.

**Resubmission requires, in order:**
1. Put compliant language beside the checkbox itself: message types (invoice + review texts),
   frequency ("varies; typically 1–2 per completed job"), "Msg & data rates may apply",
   "Reply STOP to opt out, HELP for help", and a link to `/sms/`.
2. Preferably add a **customer-facing self-opt-in** (customer-portal profile / public invoice page)
   so consent is first-party, not attested. Carriers want the consumer's own screen.
3. Re-screenshot that surface, update `messagingUseCase.optInDescription` to describe it, and
   submit registration **version 2** (`put-registration-field-value` → `submit-registration-version`,
   or the console form — Drake runs paid AWS actions in his own terminal).

**Update 2026-08-12 (N4):** steps 1 and 2 are built — compliant checkbox disclosure on both
shop-side forms AND a first-party opt-in on the public invoice page. Step 3 (screenshot from
live prod + submit v2) is Drake's, after the N4 PR deploys — exact checklist in N4's Notes.

Until then the $2/mo lease is running on a number that cannot send.

**When it eventually flips to COMPLETE:**
1. `eb setenv SMS_ORIGINATION_IDENTITY=+18663115189` (against `rs-systems-production`; remember `eb setenv` triggers the collectstatic confighooks — this is fine, just expect a deploy cycle).
2. Send a test SMS to a real number (invoice-text path is the easiest end-to-end check).
3. N2 becomes fully unblocked (tech-facing texts).

---

## Appendix B — Parts sourcing investigation: NAGS lookup + Mygrant quotes/ordering

*(Researched 2026-08-12 from public sources; the Mygrant spec PDF is committed at `docs/reference/mygrant-soap-webservices-spec-rev-2025-05.pdf` because its only public mirror is a third-party site likely to disappear.)*

### B.1 Mygrant Glass — a real, documented API; both live quotes and ordering exist

Mygrant operates an official SOAP/XML web service ("API Integration — SOAP Web Service Specifications", rev 2025-05-05):

- **Endpoints:** prod `https://webservice.mygrantglass.com/v2/CoRE650WebService.asmx`, staging `webservice-staging.…` (verified live; WSDL at `?wsdl`). Two operations: `Ping` and `InboundTraffic(request) -> string` — the request is CDATA-wrapped XML (`MygrantXMLOrderingSystemRequest`), an EDI-style envelope-in-envelope.
- **Request types:** `Inquiry` (price/availability), `Order` (delivery or Will Call), `Return` (**"Coming Soon"** — returns still go through the website or a CSR).
- **Auth — per-shop, self-serve, no vendor program:** HTTP header `AuthToken` = API key the *shop* generates (MygrantGlass.com → My Account → Edit User Settings → Generate Key, after the rep enables "API User onboarding" / the API Integration Set Up Form), plus `CustomerID` (`C######-###`, from the sales rep), `WebUserID` + `Password` (the shop's site login) in the XML header. This is exactly how every competitor POS connects (see B.3) — RS Systems holds each tenant's credentials; there is no certification gate or fee in the public materials.
- **Inquiry** takes NAGS prefix + number (e.g. `DW` `01658` — enough on its own; optional color/hardware/premium codes, brand, quantity, branch, delivery method/date). Response returns *multiple concrete SKUs* per NAGS number (glass, moldings, sensors; e.g. `DW01658 GBY FYG`) each with description, brand, `QtyAvailable`, estimated delivery, next `TruckRun` (route/date/time), ship-from branch, **`ListUnitPrice` and `CustomerUnitPrice`** (the sample shows list $921.13 vs. customer $69.08 — the shop's negotiated pricing comes back), and `PricingCommitment`.
- **Order** requires an exact SKU (`AmbiguousRequest` otherwise); success returns a `DRLineNo` (e.g. `S64581795-1`). Item-level errors: `ChooseSubstitute`, `ChooseInterchange`, `CannotMeetdate`, `InsufficientStock`, `NoStock`, `UnregisteredCustomer`, `OverCreditLimit`, `NoTruckRoute`, `SuccessWithSurcharge`, `MGCPartAtOtherBranch`. Request-level: `E600 NotAuthenticated/NotAuthorized`.
- **Terms:** non-exclusive revocable license to build integrations; **no scraping** (site ToS separately bars any automated access to the website — the API is the only sanctioned route); **no redistributing/reselling API data**; no using the API to compete with Mygrant; rate limits at their discretion; liability cap $1,000; CA law. Terms contact: legal@mygrantglass.com. Mygrant HQ: (510) 785-4360 / (800) 972-0964.
- **Practical caution on data display:** the shop's `CustomerUnitPrice` is the shop's cost — keep it out of every customer-facing surface (that's both good business and the no-redistribution term).

### B.2 NAGS — licensed from Mitchell only; the lookup, not the ordering, is the expensive half

- **NAGS** (National Auto Glass Specifications) — part numbers, specs, labor hours, benchmark list prices — is owned and published by **Mitchell International** (an Enlyte company), updated **three times a year (January / May / September)**. Mitchell once revoked an entire published calculator (Jan 2017), so treat the data as theirs, cadence and all.
- **Licensing:** no public rate card; every path on mitchell.com is a contact form (legacy glass line 800-551-4012). Every auto glass POS licenses it and passes the cost through as a premium seat. Terms visible via licensees (GTS/GlasPacLX license agreement, Omega EDI terms): per-end-user committed terms, **no redistribution in any medium**, NAGS Publishing is a third-party beneficiary that can enforce directly against end users, access dies with nonpayment. One squarely relevant clause: the only sanctioned external use of NAGS data is **"confirming information on your bills or invoices to your customers"** — a public "enter your VIN, see the NAGS price" widget would need explicitly negotiated terms.
- **Mitchell provides data only — no VIN decode, no VIN→part mapping** (Mitchell SVP, on the record): every licensee builds or buys the vehicle→part half themselves, and nobody achieves 100% VIN accuracy. This is the hard, error-prone part of P2, over and above the license.
- **Market pricing for the pass-through seat:** Omega EDI $69.95/NAGS-user/mo (+$1.00/VIN lookup); GlassBiller Pro $199/user/mo incl. NAGS vs. $19 non-NAGS seats; AutoGlassCRM $0.30/search or $75/user/mo unlimited; EAG (PGW's POS) $29.99–34.99/user/mo + $1.00/VIN search; GlasPacLX $70/license/mo + $599 onboarding with NAGS bundled. Pattern: **~$60–75/NAGS-user/month equivalent, cheap non-NAGS tech seats.**
- **No-contract alternatives** (web tools for the shop, not embeddable APIs): AutoGlassMatch.com "$1.00 per successful NAGS VIN lookup" (first 10 free); AutoGlassCRM per-search; AutoBolt and BidClips do VIN→part as product features. Generic VIN APIs (CarAPI etc.) decode year/make/model/trim only — no NAGS numbers or prices. **Scraping distributor catalogs for NAGS data is both a ToS violation and a Mitchell copyright problem — not a path.**

### B.3 The competitive pattern (why the shop-credential model is safe to build on)

GlassBiller, Omega EDI, GlasPacLX (GTS), Elmo Anywhere (IBS) and eDirectGlass (since 2003) all advertise Mygrant pricing + ordering, and all of them configure it the same way: the shop enters its own Mygrant online-ordering username/password + customer number into the POS (Omega's setup docs spell this out; Pilkington and PGW work the same way with Ship-To IDs). Glaxis — the Pilkington-orbit EDI hub Mygrant joined in 2009 — is a second, certification-gated route aimed at insurance-network shops; the direct 2025 API makes it unnecessary for our use case.

### B.4 What this means for RS Systems — recommendation

1. **Build P1 (Mygrant quotes, then ordering) on the shop-credential SOAP API.** It needs no NAGS license because the input is the NAGS number the tech already types into `Replacement.nags_number`. First human step, zero code: Drake asks his Mygrant rep to enable API onboarding on the shop account, then generates a key. Build against staging + `EnvironmentID=TEST` first.
2. **Don't pursue a Mitchell NAGS license now (P2 stays backlog).** It's a negotiated committed contract at real per-seat money, it prohibits exactly the frictionless public display we'd want, and the VIN→part mapping isn't included — it's a second build on top. Revisit when multiple shops ask for in-app part lookup and will pay a NAGS-seat price for it.
3. **Never scrape** mygrantglass.com or any distributor catalog — both distributors' ToS and Mitchell's license prohibit it, and the sanctioned API removes the temptation. *(Re-verified first-hand 2026-08-14 — see B.5: the idea of driving the logged-in portal instead of waiting for API onboarding was investigated and rejected; the site terms prohibit exactly that.)*

### B.5 Portal walkthrough on a real account (2026-08-14) — what's confirmed, and why portal automation is rejected

Logged-in reconnaissance of MygrantGlass.com on the pilot shop's account (Drake's dad's shop; Ship-To `C027180-001`, Little Rock AR branch). One paid search was spent; nothing was ordered (cart emptied and verified empty). No credentials are recorded anywhere — the shop's own browser session was used.

**Confirmed real on the account** (this de-risks P1 — the SOAP Inquiry/Order semantics map 1:1 onto what the portal exposes):

- **Part search** (`/pages/search.aspx?q=DW1256&sc=B062&do=Search`) returns per-brand SKUs with live **My Price** (the shop's negotiated cost — e.g. two brands of the same windshield at $74.28 vs. $114.95) and stock as `Yes`/`Call`. A `Best Deal` variant shows only the cheapest brands. Clicking a SKU lists its **accessories** (moldings, fastener kits, wiper parts) with prices — same quote→pick-exact-SKU shape the API requires.
- **Warehouses are an enumerable dropdown**: `B062` Little Rock (default), `B098` Harahan LA, `B051` Memphis, `B058` Nashville, plus `r` REGIONAL / `n` NATIONAL sweeps; the branch's phone number renders with results.
- **Cart → order**: adds post to `/pages/cartfunctions.aspx`; each line carries qty + a **PO Number field**; checkout (`/pages/cartview.aspx`) offers **Freight ("Order With Run") vs. Will-Call** and free-text special instructions, and submits *immediately* on the delivery-type button — there is no confirmation step past it.
- **Order history** (`/pages/history.aspx`) filters by Ship-To + period + **PO search (wildcard `?`) and has an Export button** — the reconciliation surface for a PO-stamped order.
- **No API key self-serve yet**: My Account → Edit User Settings (`/pages/account.aspx`) contains only Full Name + Change Password. The Generate Key UI the spec describes is absent until the rep completes API User onboarding — confirming the onboarding call is P1's only real blocker.
- **Search billing**: per Drake (from the account holder), searches bill **~$1 each**. Treat every lookup surface (part #, VIN, make/model — and possibly API Inquiries) as billable until the rep says otherwise, and design the quote UX accordingly (deliberate button, cached response, no auto-refresh).

**Why portal automation is rejected.** The tempting shortcut — RS Systems logging into the portal server-side with the shop's credentials and driving these pages directly, skipping API onboarding — would be *technically* trivial (search is a plain querystring GET; only cart/order needs the ASP.NET postback dance). But the site's Terms and Conditions (`/pages/terms.aspx`, §8.1 "Prohibited Conduct") expressly forbid using "any software or other means" to access, collect, or extract content from the site, and separately forbid circumventing authentication measures; §7.1 also makes cost/pricing information confidential. An unofficial integration would put every connected shop's wholesale account — their parts supply and credit line — at revocation risk, on a surface Mygrant can change without notice. The SOAP API exists precisely to sanction this exact capability with the same shop credentials plus an API key. **Decision: the portal is for humans; RS Systems integrates only through the API.**

Key sources: Mygrant SOAP spec (committed PDF; mirror: aswadtsh.com/wp-content/uploads/2025/06/Mygrant-SOAP-WebServices-Technical-Specifications-rev-202505.pdf) · live endpoint webservice.mygrantglass.com/v2/CoRE650WebService.asmx · mygrantglass.com/pages/terms.aspx · mitchell.com NAGS pages · glassbytes.com (Dec 2021 "VINs in NAGS"; Sept 2025 pricing update; May 2009 Mygrant–GLAXIS release) · gtsservices.com license agreement + pricing · omegaedi.com terms/pricing/help (electronic-ordering setup) · glassbiller.com + FAQ · autoglasscrm.com NAGS licensing page · everythingautoglass.com/pricing · autoglassmatch.com · elmoanywhere.com · edirectglass.com history.

---

## Document history

| Date | Change |
|---|---|
| 2026-08-11 | Created from live exploration (notification-path + scheduling audits) and Drake's scoping decisions: one combined doc; full arc MVP-first; staff notifications default-ON. |
| 2026-08-11 | Review pass with Drake: confirmed MVP-first sequencing over deeper upfront scheduling design. Named the two known gaps so they don't get lost — technician availability (S5 consideration + S6 backlog item 4) and self-service rescheduling (S6 backlog item 5). |
| 2026-08-12 | Corrected the SMS status: the TFN registration was **denied** on 2026-08-11 (this doc said `REVIEWING` — it was written hours before the denial landed). Rewrote Appendix A with the reason and the resubmission path, and added **N4** to the queue, because the fix is product work on the consent surface, not a console edit. |
| 2026-08-12 | **N1 executed** (branch `feat/fieldops-n1-assignment-notifications`): one assignment write path (`services/assignments.py`), per-template `channels_override`, staff email default-ON, Replacement signals, bulk summaries, rewritten assignment emails. §0 blockers 1–3 closed; blocker 4's SMS half stays with N2. Two traps added (NOT NULL technician; flat-context/absolute-link email rules). Merged as PR #179. |
| 2026-08-12 | **N4 code executed** (branch `feat/fieldops-n4-sms-opt-in`): compliant disclosure on both shop-side consent checkboxes, first-party opt-in card on the public invoice page (`/invoice/<id>/<token>/sms-opt-in/`), `Customer.sms_opt_in_source` provenance (core migration 0028), `/sms/` opt-in copy rewritten. Registration v2 submission is Drake's post-deploy step — checklist in N4 Notes. |
| 2026-08-12 | Parts sourcing investigation (Drake's ask: own NAGS lookup + live Mygrant quotes/ordering). Findings in **Appendix B**; queued **P1** (Mygrant quotes+ordering — buildable now on Mygrant's documented SOAP API with shop credentials) and parked **P2** (vehicle→NAGS lookup — blocked on a negotiated Mitchell license). Committed the Mygrant spec PDF to `docs/reference/`. |
| 2026-08-14 | Live portal walkthrough on the pilot account (Drake's dad's shop) — **Appendix B.5**. Confirmed: live per-brand shop pricing, 4-warehouse structure, PO-per-line ordering with Freight/Will-Call, PO-searchable history, and that Generate Key is absent until rep API-onboarding (the only real P1 blocker — call the rep). Investigated and **rejected portal automation** (site ToS §8.1). Reworked P1 around the multi-shop "Connect your Mygrant account" design (per-tenant `MygrantConfig` on the `TenantConfig` pattern; encryption-at-rest is a first-in-codebase decision), added Drake's dad's "portal is already easy — win on job context" principle, profit-on-ticket framing, and the ~$1/search cost constraint. Fixed stale `nags_number` line refs. Later same day: added the numbered **P1 order of work** (onboarding → billing → encryption decision → connect → quote-only → ordering); Drake left the onboarding voicemail with Mygrant IT. |
