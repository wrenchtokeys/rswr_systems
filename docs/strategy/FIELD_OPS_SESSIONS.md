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
| N — The tech finds out | N3 · Notification coverage audit | S | DONE + DEPLOYED (2026-08-24, **PR #204**, live 2026-08-24 22:47) — grew well past S; see Notes |
| N — The tech finds out | N4 · SMS opt-in compliance + registration v2 | S | **SUBMITTED 2026-08-31 — version 4 `REVIEWING`.** Card fixed (#205, deployed). v3 was denied 08-26 on business-email domain + a screenshot staged with the box ticked; v4 fixes both. Activation checklist in Appendix A |
| S — Where and when | S1 · A real "booked time" | M | DONE (2026-08-15, **PR #188**) |
| S — Where and when | S2 · Field dispatch (executes B1) | M | DONE (2026-08-15, PR #189) |
| S — Where and when | S3 · Day / agenda view | M | DONE (2026-08-16, PR #190) |
| S — Where and when | S4 · Customer requests carry when + where | M | DONE (2026-08-18, **PR #195**, deployed same day) |
| S — Where and when | S5 · Dispatch board | L | DONE + DEPLOYED (built 2026-08-18, **PR #197** merged 2026-08-24, live 2026-08-24 22:47) |
| S — Where and when | S6 · Routing / ETA / lot-walking | — | BACKLOG (deliberately deferred) |
| S — Where and when | S7 · Drag to swap two appointments | M | DONE (2026-08-17, **PR #192**) |
| S — Where and when | S8 · Technician working hours | M | DONE + DEPLOYED (2026-08-24, **PR #201**, live 2026-08-24 22:47) — built in two halves, see Notes |
| S — Where and when | S9 · "Leave it blank" means unscheduled | S | **BUILT 2026-08-25** (branch `fix/fieldops-s9-blank-means-unscheduled`) — shipped as an opt-in attribute, not the deletion the spec called for; see Notes |
| S — Where and when | S10 · Quick-add a job from the schedule | M | **BUILT 2026-08-25** (branch `feat/fieldops-s10-quick-add`) — also fixes the REQUESTED-vanishing bug; see Notes |
| S — Where and when | S11 · The move primitive + inline time/date edit | M | TODO |
| S — Where and when | S12 · The ordered day list + drag to move | L | TODO |
| S — Where and when | S13 · Schedule on the dashboard | S | TODO |
| S — Where and when | S14 · Multi-technician moves | M | TODO |
| P — Parts | P1 · Mygrant live quotes + ordering | M | IN PROGRESS (steps 3+4 MERGED+DEPLOYED 2026-08-15, PR #184; step 5 quote-only built 2026-08-15, **PR #186**; steps 1–2 wait on the Mygrant IT callback; step 6 ordering waits for quotes to prove out) |
| P — Parts | P2 · Vehicle→NAGS part lookup | — | BACKLOG (blocked on a NAGS licensing decision — Appendix B) |

**Suggested sequence:** N1 → N4 (start the review clock early — it's days-to-weeks of waiting either way) → S1 → S2 → S3 → N2 (whenever the TFN approves) → S4 → N3 → S5 → (S6 stays backlog until S3/S5 prove demand). **S7 slots in any time after S3** — it needs neither S4 nor S5, and S5 inherits its endpoint. P1 is independent of both arcs and can slot anywhere once Mygrant API onboarding is done (like N4, start that clock early — it's a phone call to the rep).
Rationale: N1 is the reported bug and pays off alone. S1 is the schema foundation every S-session builds on. S2 is IMPROVEMENT_SESSIONS' "biggest daily-felt gain per hour spent." S4 before S5 because the board is only as good as the data flowing into it.

**Where we are (2026-08-25 — Phase S is REOPENED by first real use).** The
2026-08-24 entry below said "there is no unblocked session left in this
document." That held for exactly one day. On 2026-08-25 Drake took a customer
call and used RS Systems to book it instead of a note in his phone — the first
time anyone had driven this arc from the actual motion rather than from a
screen — and the machinery held while the surface did not. **S9–S14 are the
result, and they are all unblocked.** Read §0's *"Scheduling UX — what first
real use found"* before starting any of them.

The one-sentence diagnosis: **S1–S8 built the right machinery behind the wrong
primitive.** Every service is transactional, price-safe and well tested, but
the only gesture that can change a booked time is *swap*, the only way to reach
the schedule at all is a seven-step detour through the job form, and the swap
that does exist confirms itself with a full page reload — so on a half-empty
day, which is every day for a one-tech shop, the feature reads as broken. None
of S9–S14 changes a service's contract; they add the missing *move* primitive
and rebuild the surface on top of what S1–S8 already got right.

*(Kept for the record — the 2026-08-24 state, all of which is still true.)*
Every session N1–S8 is built or deliberately parked. N1, N3, N4, S1, S2,
S3, S4, S5, S7 and S8 are done; S6 and P2 are backlog by decision; N2 waits on
a regulator and P1 on a vendor. A manager runs the morning from one screen: the
rail shows what the customer asked for, one click names a tech and a time, the
tech is notified once, the board knows who is actually working, and — as of N3
— the notification actually leaves the building.

**Deploy state: nothing in this arc is waiting.** Production runs `68dc31e9`
(`app-68dc-260824_224726507237`, deployed 2026-08-24 22:47 CDT, health green),
which carries the whole arc: #197 (S5 dispatch board), #198 (S8 spec), #199,
#200 (the email/notification chassis), #201 (S8 working hours), #204 (N3, incl.
`core/0033`) and #205 (the SMS opt-in card fix). Every session in this document
is live. N3's shop-visible effect — two customer emails that had never sent on
production — started on that deploy.

What's left in the queue:

- **S9–S14 are the live queue** and nothing blocks them. Suggested order is
  the numbering: **S9** (2h, and every later session displays or moves
  `scheduled_for`, so it goes first), **S10** (the one Drake actually asked
  for), **S11** (the missing primitive), **S12** (the layout + the drag),
  **S13** (dashboard), **S14** (multi-tech). S13 is independent of S11/S12 and
  can be pulled forward any time; S14 must come last because it is the only one
  that depends on the primitive being proven.
- **N2** is parked until the toll-free number clears review (Appendix A).
- **P1** waits on Mygrant (steps 1–2), **P2** on a NAGS licensing decision,
  **S6** on demand that S3/S5/S8 have to prove first.
- **S6 item 4 (technician availability) is done** — it graduated into S8 and
  shipped on 2026-08-24. What stays in S6 is the part S8 explicitly refused:
  date-ranged time off, coverage rules and customer-facing slot picking.
- **Two decisions N3 surfaced and deliberately left to Drake:** splitting
  `repair_completed` into a customer body and an internal one, and whether the
  DB-held email subjects should stop saying "- Unit {{ unit_number }}". Both
  are in N3's "Deliberately not done".

*A caution worth keeping:* a `gh pr list` "updated" column is not a merge
date. Reading it as one is how S5 came to be dated 2026-08-18 throughout this
document — that is the day its branch was finished, not the day it reached
`main`, which was 08-24. Check `git log --first-parent` for the real order and
the EB version label for what is actually running.

*A second one, from N3:* a template file existing, being beautiful, and being
referenced by name in a management command does **not** mean anything sends it.
Six lifecycle emails had rendered as bare text since migration 0018 while three
separate sessions rewrote their HTML. Check the seeded row, not the file.

Sizes: **S** ≈ half a day · **M** ≈ 1–2 days · **L** ≈ 3–5 days.

---

## How to run a session

1. **Branch rule (Drake's hard requirement):** every session runs on its **own fresh branch cut from latest `main`** — `feat/fieldops-<id>-<slug>` (e.g. `feat/fieldops-n1-assignment-notifications`). Never stack on, share with, or merge from another session's branch. One session = one branch = one PR.
2. Another Claude session may share this working tree. Print `git branch --show-current` before every test run; never `git add -A` (add files by name).
3. Read §0 plus your session's table. Do not read the whole document to do one session.
4. Re-verify the session's "Verified current state" anchors before coding — line numbers drift.
5. Run the targeted tests named in the session, plus `scripts/test_guards.sh` (guard set, ~25s; pass your module as an argument to run both). Before pushing, `scripts/test_guards.sh --full` — it diffs the whole suite against `docs/strategy/test_baseline_main.txt` and exits non-zero only on regressions. The suite has ~93 pre-existing failures on `main`: **compare against the baseline, never count absolutes**.
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

RS Systems' toll-free number `+18663115189` is **PENDING**. Three registration versions were denied (opt-in language, then a missing-field auto-deny, then business-email domain + a "pre-selected" checkbox); **version 4 is `REVIEWING` as of 2026-08-31** — see **Appendix A** for each reason and its fix. The first denial was product work; the rest were submission hygiene. All current SMS senders are customer-facing (invoice texts, review texts); nothing texts a tech. Prod is inert rather than broken — `SMS_ENABLED=true` but `SMS_ORIGINATION_IDENTITY` is unset, and `SMSService.is_enabled()` requires both.

### Scheduling — planned vs. built

**Planned but unbuilt:** B1 field dispatch (`IMPROVEMENT_SESSIONS.md:376-420`) puts address + `tel:` + a Google Maps link on the job card and adds `service_address` to `GlassService` — explicitly *not* a calendar. `PRODUCT_DIRECTION.md:96-142` sketches a ~3–4-week minimum-viable calendar: a day/week view over existing data plus a scheduled date/time field, with route optimization explicitly deferred and the success bar "a shop can run its day from the calendar view."

**Update 2026-08-18 — what is built now.** The paragraph below is the original
(2026-08-11) survey and is kept as the diagnosis; five sessions have since landed
on top of it, and a fresh session should start from these rather than re-derive:

- **S1** added `GlassService.scheduled_for` + `scheduled_window_end`
  (`apps/technician_portal/models.py:379-386`) — booking time, distinct from
  `service_date`, null = unscheduled. Written by `RepairForm` (`forms.py:443`),
  `QuickJobForm` (`forms.py:975`, nulled at `:1168` for already-completed work),
  `ReplacementForm` (`apps/saas/forms.py:329`), the create view
  (`views/jobs.py:515`) and S7's swap service. The tech dashboard buckets by it
  (`views/dashboard.py:363-391`).
- **S2** added `service_address/_city/_state/_zip` with a render-time fallback to
  the customer record — `get_service_location_parts()` (`models.py:565-590`).
- **S3** added the day view `/tech/schedule/` (`views/schedule.py`), its shared row
  partial `templates/technician_portal/includes/schedule_row.html`, and the
  manager triage rail (rendered inline in `schedule.html:68-96`, *not* through the
  partial).
- **S7** added the only non-form writer of a booked time —
  `apps/technician_portal/services/schedule_swap.py` + `POST /tech/schedule/swap/`
  — and with it the house rules for changing a time (never `save()`; keep each
  job's own duration; notify on commit; answer JSON even when refusing).
- **S4** added the customer-side capture (`preferred_date` +
  `preferred_window` on `GlassService`, a wish that never touches
  `scheduled_for`) and the second non-form writer of a booked time —
  `apps/technician_portal/services/schedule_booking.py` +
  `POST /tech/schedule/book/`, which turns a wish into a real booking, books a
  multi-break batch as one visit, and is what S5 should call. It also folded
  the triage rail into `schedule_row.html` (`triage=True`) and gave it an
  inline date+window+Book control.
- **S5** turned the manager's day view *into* the dispatch board rather than
  building a second surface: `services/dispatch.py` +
  `POST /tech/schedule/dispatch/` sets who and when in one transaction by
  composing N1's `assign_job` with S4's `confirm_appointment` (one
  notification, two optimistic locks), and `services/schedule_conflicts.py`
  flags double-bookings, over-committed days and bookings that miss the
  customer's ask — informational only, nothing blocks a write. The rail grew a
  technician picker and expands in place (`?rail=all`).
- **S8** gave `Technician.working_hours` a shape and four readers
  (`apps/technician_portal/services/working_hours.py`), so the board knows who
  is actually working: an "outside hours" chip beside S5's three signals, an
  "Off today" group line, off-duty marks in the dispatch picker that never
  remove anybody, and declared hours as the capacity denominator. Editing is
  on Settings → My Team behind its own endpoint. `{}` means *undeclared* —
  available whenever, silent everywhere — and that is a rule with tests, not
  a default.
- Still true and still unbuilt: no `Appointment`/`Availability` model, no
  date-ranged time off (PTO), and no customer-facing rescheduling.

**Built (as of 2026-08-11): essentially nothing.**
- `GlassService.service_date` (`apps/technician_portal/models.py:326`) is the only date on a job — a *completion* timestamp defaulting to `now()`. The primary QuickJobForm (`forms.py:872-1060`) has **no date input at all**; only the legacy RepairForm (:407-410) and the multi-break form expose one.
- No `Appointment`/`Schedule`/`TimeSlot`/`Availability` model. No `service_address` anywhere (zero grep hits). `Vehicle` and `Technician` have no location fields. `Customer` has `address/city/state/zip` (`core/models/customer.py:81-84`) shown only on `customer_details.html`.
- "Today's Queue" (`views/dashboard.py:232-251`) is a misnomer: it filters by status with **no date filter** — a three-week-old job still shows.
- The customer request forms capture **no date, time window, or address** (repair: `apps/customer_portal/views.py:1926-2022`; replacement: :1711-1801) — a customer's timing wish can only travel as free text in the notes blob. The success message says *"Repair request received — you're on the schedule!"* (:2018) when no schedule exists.

**Dormant assets to reuse, not rebuild:**
- `CustomerRepairPreference.lot_walking_enabled/_frequency/_time/_days` (`apps/customer_portal/models.py:101-126`) — a fully-formed recurring-visit spec with a settings UI and **zero consumers**. Cheapest possible first calendar feed (S6).
- `RewardRedemption.preferred_date`/`preferred_time` (`apps/rewards_referrals/models.py:210-217`, staff display at `reward_fulfillment.html:87-109`) — a shipped customer-picks-date+window pattern to copy in S4.


### Scheduling UX — what first real use found (2026-08-25)

*(Read this before S9–S14. It is the diagnosis from the first time anyone booked
a real customer call through the product; every finding below is verified in
code, and re-deriving them costs an afternoon.)*

**How the call actually went.** Customer phones, job needs to be on tomorrow.
The path the product offers is: Jobs → New Job → fill the form → save → land on
the job *ticket* → navigate to Schedule → find the job in the triage rail →
set date/window/tech → Book. `job_create` redirects to
`_job_detail_redirect(service)` (`views/jobs.py:280-283`), never to the
schedule, so the detour is structural, not a wrong turn.

**Four findings, in the order they bite:**

1. **There is no reschedule path at all.** Grep confirms it: no endpoint, view,
   URL or service named reschedule / move / edit-time exists. A booked row
   renders only the *technician* picker (`includes/schedule_row.html:224-247`);
   the date/window/exact-time form is gated `{% if triage %}` and so appears
   only on rows that have no time yet. The three ways to change a booked time
   are therefore: trade with another job on the same tech's same day (S7),
   re-book through `/tech/schedule/book/` (which requires sending `expected` or
   it 409s), or open the full edit form — **which runs `GlassService.save()`
   and therefore re-prices the job and pushes prices onto live invoices**, the
   exact thing every schedule service goes out of its way to avoid. Nothing can
   return a job to unscheduled except that same edit form.
2. **Swap confirms itself with a page reload, so a refusal is invisible.**
   `static/js/schedule_swap.js:130-140` does `UI.flash()` + `window.location.reload()`
   on success. Every refusal path leaves the screen *byte-identical*: a
   cross-tech drag (refused by design, `refuse()` at `:76-81`), a 409, a
   read-only tenant's HTML redirect, and — worst — a near-miss drop, where
   `endDrag` returns with **no toast at all** unless the drop landed in the
   triage group. S7's own Notes concede the structural half: *"on a half-empty
   day the manager's intent is 'drop it at 11:00' … so on the easiest day to
   use it, the feature can read as broken."* For a one-tech shop every day is
   that day. **The bug is not the service — it is that swap is the only
   gesture, and that the UI never shows its work.**
3. **A booked REQUESTED job vanishes from both lists.** `day_schedule` filters
   the day sheet on `DAY_STATUSES = ('PENDING','APPROVED','IN_PROGRESS','COMPLETED')`
   (`views/schedule.py:60`) and the triage rail on `scheduled_for__isnull=True`,
   but `confirm_appointment` accepts `REQUESTED` (`BOOKABLE_STATUSES`,
   `schedule_booking.py:57`). So booking a customer-requested job out of the
   rail removes it from the rail (it now has a time) and never adds it to the
   day. Fix in whichever session touches the day query first: add `'REQUESTED'`
   to `DAY_STATUSES`, marked not-yet-accepted. S3's rationale ("the shop hasn't
   accepted it yet") still holds for *unscheduled* REQUESTED work, which stays
   in the rail on the `scheduled_for` filter — the refined rule is **"REQUESTED
   with a booked time belongs on the sheet, marked, because somebody in the
   shop deliberately put it there."** Do **not** auto-promote REQUESTED→APPROVED
   on booking; that bypasses `resolve_initial_shop_status` and the approve/deny
   flow.
4. **"Optional — leave blank to keep this job unscheduled" is a lie.**
   `templates/base_app.html:263-285` runs on *every* page and pre-fills *every*
   empty `input[type="datetime-local"]` with the current time before attaching
   flatpickr. So `job_form.html:248`'s own label cannot be honoured: unchecking
   "Job is already done" reveals a field already populated with now.
   `ReplacementForm.scheduled_for` (`apps/saas/forms.py:355`) has the same
   problem. This is S9, and it goes first because every later session displays
   or moves `scheduled_for`.

**The house rules S9–S14 inherit unchanged** (all four were established by S7
and S4; none of them is up for renegotiation):

- **Never `save()` to move a time.** `.update()` on the queryset, always.
  Creating a job *is* a normal `save()` — pricing and `resolve_initial_shop_status`
  have to run — so the rule applies to the *time* write, not the create.
- **Each job keeps its own duration.** `new_end = new_start + (old_end - old_start)`,
  and NULL stays NULL (`schedule_swap.py:98`).
- **Notifications fire on `transaction.on_commit()`,** never inside the locked
  transaction — `NotificationService` sends email/SMS synchronously.
- **The endpoint answers JSON even when it refuses.** These paths live under
  `/tech/`, not `/api/`, so `SubscriptionEnforcementMiddleware` answers a
  read-only tenant with an HTML redirect that `fetch` follows and delivers as a
  200 — **check `Content-Type` before `res.ok`** (`schedule_swap.js:113-120`).
  And gate authorization **in-body**, not with `@manager_required`, which
  redirects to HTML *and* queues a stray `messages.warning` that then surfaces
  as a banner on the manager's next page.

**Two facts about the data model worth having in hand:** there is no duration
column anywhere — `NOMINAL_JOB_LENGTH = 1h` (`schedule_booking.py:63`) is a
deliberate placeholder, not a measurement — and there is **no per-tenant
timezone**; `TIME_ZONE` is one global setting (`models.py:387`). That second one
is why every client→server schedule payload sends the shop's **wall clock**
(`date` + `time`) rather than an ISO instant: a browser in another zone calling
`toISOString()` would book the wrong hour, silently.

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

## N3 · Notification coverage audit — DONE (2026-08-24, PR #204)

| Field | Value |
|---|---|
| **Goal** | Every event a tech or shop cares about notifies the right person through the real system; the parallel `TechnicianNotification`-only paths stop silently diverging. |
| **Size** | S |
| **Depends on** | N1. Better after S4 exists (schedule-changed events). |
| **Why it matters** | Two notification systems drifted apart once already — that's how this whole bug happened. |
| **Verified current state** *(refreshed 2026-08-24, after #200)* | **This session's ground moved on 2026-08-24: PR #200 landed an email/notification chassis and the replacement lifecycle** — merged, not deployed. Re-read before scoping; the pre-#200 survey below is kept because the structural problem it describes is unchanged. `TechnicianNotification` writes are scattered (assignment views, redemption flows, replacement request `_notify_shop_replacement_requested` at `apps/customer_portal/views.py:1804+`); the bell reads `core.Notification` only; two systems, no shared source of truth. What #200 changed: notification emails are now composed from `templates/emails/components/*` and much of the copy was rewritten (it moved S4-asserted wording — see S8's Notes), and `replacement_*` lifecycle coverage exists where CLAUDE.md still says it doesn't. **Three concrete defects are already on the table** — see "Where to start" below. |
| **Considerations** | Inventory first: grep every `TechnicianNotification.objects.create` and decide each one — fold into `NotificationService`, keep as dashboard-only, or delete. Add the missing events found while writing this doc: customer-requested job auto-assigned (tech should hear), schedule confirmed/changed (after S4 — but note **S7 introduces the first schedule-change template**, so inventory it here rather than inventing a second one). Consider whether `TechnicianNotification` can become a thin projection of `core.Notification` instead of a second source of truth. |
| **Decisions needed** | Whether to add `replacement_*` lifecycle templates now or keep replacements on the shop-email path (Drake previously deferred replacement lifecycle emails by choice — see `simplicity-first-product-direction`; don't expand customer-facing email without asking). |
| **Acceptance criteria** | A written inventory table (in this doc's Notes) of every tech-facing event → recipient → channel; no event a tech must act on lands only in the dashboard list. |
| **Out of scope** | Customer-facing notification redesign. |

**Where to start (2026-08-24)** — three defects found by other sessions, none of them chased down. They are the audit's first rows, not its scope:

1. **A missing `action_url` costs the whole email, not just the button.** *(found by S8)* Nineteen templates in `templates/emails/notifications/` render their CTA through `{% with url=base_url|add:action_url %}`, and `{% with %}` resolves filter arguments strictly — a context without `action_url` raises `VariableDoesNotExist`, killing the render. `NotificationTemplate.render()` (`core/models/notification_template.py:131`) renders `email_html` at `:176` but computes the DB `action_url_template` at `:179`, so the seeded value cannot rescue a caller that omits the key. Not live — every current call site passes it explicitly (`apps/technician_portal/signals.py`, `apps/technician_portal/services/assignments.py`) — but **three tests in `tests/test_primary_contact.py`, part of the smoke set this document tells every session to run, error on `main` because of it.** Decide the convention (guard with `{% if action_url %}`, default the key in `render()`, or require it loudly) and apply it to all nineteen at once.
2. **`ReviewConfig` business hours are compared in UTC.** *(found by S8)* `_adjust_to_business_hours` (`apps/technician_portal/review_service.py:319-332`) clamps an aware UTC datetime by `.hour` against `business_hours_start/end` (defaults 9/19), so in production review-request emails queue for roughly **4 AM local**. Live today, shipping since the review system launched. One-line fix (`timezone.localtime()` before comparing, convert back), but it needs a test that would have caught it, which is why it belongs in an audit rather than in a drive-by.
3. **`repair_request_submitted` still maps to `['in_app','sms']`.** *(found by S5)* Visible rather than hidden now, but nothing texts anybody until N2, so that event effectively has no channel.

**Notes** *(session run 2026-08-24, branch `feat/fieldops-n3-notification-coverage`, PR #204)*

**All three starting defects were real, and the audit found five more.** The
three inherited ones were the cheap part; what the inventory turned up is that
the notification system has been quietly *half-wired since migration 0018*, and
every session since has been decorating templates that could not be delivered.

**The headline: six lifecycle emails have never sent their HTML on a deployed
database.** Migration 0018 seeded the eight repair templates with in-app and
action fields only — it sets no `email_html_template` at all. Migration 0027
noticed and backfilled exactly the two rows N1 needed, leaving the rest.
`EmailService` guards `attach_alternative` on a truthy body, so those six went
out as bare unbranded plain text with the in-app `message_template` as the
body. **None of #200's rewritten HTML has ever reached a recipient on those
events.** `core/0033` backfills the wiring, copying the values verbatim from
`setup_notification_templates` (the documented full source of truth) and only
where the column is blank, so a DB set up through that command is untouched.

**And three of them had no email channel to send on even once wired.** HIGH
maps to `['in_app','sms']`, and SMS stays dark until N2 — the same structural
trap §0 blocker 3 describes, which N1 fixed for `repair_assigned` alone.
`repair_request_submitted` (the shop's "a customer just asked for work"),
`repair_pending_approval` and `repair_completed` all had a body no channel
could deliver. All three now carry `channels_override`.

> **Shop-visible on deploy.** `repair_pending_approval` and `repair_completed`
> are customer-facing and have never emailed anyone on production. Turning
> them on means customers start receiving "please approve this repair" and
> "your repair is done" mail they have not had before — Drake's explicit call,
> 2026-08-24, same class of change as S4's "request received" email. The
> owner's and managers' copies of `repair_completed` start arriving too.

### The inventory (every notification event → recipient → channel)

Generated from a migrated database after `core/0033`. `sms` is inert
everywhere until N2 lights the toll-free number up.

| Event | Recipient | Channels | Email body |
|---|---|---|---|
| `batch_approved` | technician | in_app + email + sms | yes |
| `job_rescheduled` | technician | in_app + email | yes |
| `jobs_bulk_assigned` | technician | in_app + email + sms | yes |
| `jobs_bulk_reassigned_away` | technician | in_app + email | yes |
| `needs_assignment` | managers | in_app + email | yes |
| `repair_approved` | technician | in_app + email + sms | yes |
| `repair_assigned` | technician | in_app + email + sms | yes |
| `repair_completed` | customer + owner + managers | in_app + email + sms | yes |
| `repair_denied` | technician | in_app + email + sms | yes |
| `repair_in_progress` | customer | in_app + email | yes |
| `repair_pending_approval` | customer | in_app + email + sms | yes |
| `repair_reassigned_away` | technician | in_app + email | yes |
| `repair_request_received` | customer | in_app + email | yes |
| `repair_request_submitted` | shop technician | in_app + email + sms | yes |
| `replacement_approved` | technician | in_app + email | yes |
| `replacement_completed` | customer | in_app + email | yes |
| `replacement_denied` | technician | in_app + email | yes |
| `replacement_in_progress` | customer | in_app + email | yes |
| `replacement_pending_approval` | customer | in_app + email | yes |
| `replacement_request_received` | customer | in_app + email | yes |
| `replacement_request_submitted` | shop technician | in_app + email | yes |

No event a technician must act on now lands only in the dashboard list, and no
template has an email body that no channel delivers — both asserted by
`DeliverableChannelTests`, so the next seeding migration cannot reopen it.

**Added 2026-08-26 by JOB_QUEUE_SESSIONS Q4:** `needs_assignment` (core
migration `0034`) — the Unassigned-queue alert, HIGH with
`channels_override: ['in_app', 'email']` for the reason this section
documents. It is the first row whose recipient is *managers* rather than a
technician; the audience is the call site's choice, so the name is the
event. SMS is deliberately left off until N2 lights the number up.

### The other findings

- **`notify_batch_approved` had no callers whatsoever.** The batch email was
  unreachable code. Worse, the two customer-portal batch-approval paths save
  each break in a loop, so a 3-break approval sent the tech **three**
  `repair_approved` emails while the dashboard showed one grouped line — the
  exact two-systems drift this session exists to close. Both paths now set
  `_batch_approval_notifications_handled` before save (same opt-out shape as
  the existing `_assignment_notifications_handled`) and call
  `notify_batch_approved` once afterwards.
- **`batch_approved` rendered as rubble even before that.** It read
  `repairs_count`, `repairs` and `view_repairs_url`; the sender passes
  `repair_count`, no break list, and `action_url`. Subject rendered as
  " repair approved", headline as " breaks approved.", and the button had an
  **empty href**. It also carried no `unsubscribe_url` block, so a technician
  got `base.html`'s customer-portal default — its header comment said
  "Customer" while its only sender passes `first_repair.technician`.
- **`job_display_context` read a field that does not exist.**
  `damage_description` came from `getattr(job, 'break_description', '')`;
  `GlassService` defines `description`. The "Damage" row has therefore never
  rendered on `repair_approved`, `repair_denied` or `repair_completed`.
  `core/views/email_preview.py` invented the same non-field, which is part of
  why nobody noticed — **the preview fed templates keys no sender passes**, so
  it looked right while the real email was empty. The preview now mirrors
  `notify_batch_approved`'s context exactly.
- **The audience test was wrong, not the templates.** `tests/test_primary_contact.py`
  listed `repair_approved`, `repair_denied` and `batch_approved` as
  customer-facing; all three are sent to a technician. Those three assertions
  had been masked by the `action_url` error — fixing defect 1 revealed them.
  Both lists are now complete, and `test_every_notification_body_is_classified`
  fails if a new body is added to neither.
- **A grouped notification hard-coded "Unit #".** The whole-batch approval
  message printed `Unit #{unit_number}` for individuals too. Switched to
  `on_vehicle()`, which was already imported two lines away.

### On the three inherited defects

1. **`action_url`.** Convention chosen: **resolve it in `render()` before the
   bodies, and guard the CTA in every body.** `NotificationTemplate.render()`
   computed `action_url` *after* `email_html`, so the seeded
   `action_url_template` — which every single template has — could never reach
   the button it exists to fill. It now resolves first (an explicit
   caller-supplied value still wins) and is always present in the context, so
   no body can raise on it. All 19 HTML bodies wrap the CTA in
   `{% if action_url %}`, and all 19 text bodies match. Two text bodies
   (`repair_in_progress`, `repair_pending_approval`) were also printing a
   **relative** URL, unclickable in a mail client.
2. **Review-request business hours.** Fixed and tested. `_adjust_to_business_hours`
   now converts to local, clamps, and converts back. The old tests
   (`tests/test_reviews.py::BusinessHoursTests`) *encoded the bug* — they built
   UTC hours and asserted on `result.hour`, so they passed against a helper
   comparing UTC to a local window. Rewritten in local terms.
3. **`repair_request_submitted`'s channel map.** Fixed by `core/0033` above.

### Deliberately not done

- **`repair_completed` still serves three audiences from one template**
  (customer, owner, every manager) with customer copy and the customer
  preferences link. Splitting it into a customer body and an internal one is
  the right fix and is a copy decision, not a plumbing one — it needs Drake.
- **DB-held subjects still say `- Unit {{ unit_number }}`**, which renders as a
  trailing bare "Unit" for an individual and disagrees with the newer
  `replacement_*` house style ("Your glass replacement is done"). `core/0033`
  installs the existing strings verbatim rather than changing copy in a
  delivery fix — see `docs/operations/SES_OPERATIONS.md` before touching it.
- **The remaining ~20 `TechnicianNotification.objects.create` sites** (billing,
  subscriptions, rewards, saas) are dashboard-only by design and involve no
  event a tech must act on in the field. The repair/replacement ones all pair
  with a `NotificationService` call and are projections, not a second source of
  truth. Folding the model into a projection of `core.Notification` remains
  worth doing but is its own session.

**Tests:** `tests/test_fieldops_n3.py` (25) — the action_url convention across
every body, `render()`'s resolution order, `batch_approved` rendered with its
real sender context, local-time business hours, the channel/body inventory, and
audience classification. Plus 4 rewritten in `tests/test_reviews.py`. The three
smoke-set errors this document told every session to run are gone:
`tests.test_primary_contact` is **33/33 green**. 246 fieldops tests, 167
notification/review tests and 89 approval tests pass; the only failures in the
sweep (`test_code234` ×2, `test_code132`) are identical on `main`.

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
  a "Get text updates from {shop}" card with a required consent checkbox, shown to any
  customer who isn't already opted in. POSTs to
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
- **Follow-up 2026-08-24 — the card was invisible on prod.** The widget was gated on the
  invoice's customer already having a usable mobile in `Customer.phone`, which is an
  optional field: Drake opened a live invoice (INV-1017, Rockstar) and there was no
  sign-up at all, because that customer had no number on record. Every emailed invoice to
  a customer the shop only has an email for was in the same state — the surface existed
  and nobody could reach it. Fixed on branch `fix/sms-optin-no-phone-on-file`: with no
  usable number on file the card renders a `tel` field and the customer types their own
  mobile, which is *stronger* first-party consent, not weaker. The supplied number is
  saved to `Customer.phone` (normalized E.164) **only when the shop has nothing usable**
  — a public token must never overwrite a number the shop already has. Invalid entries
  redirect back with `?sms=badphone` and record no consent.
- **Tests:** `tests/test_fieldops_n4.py` (19: disclosure phrases on both shop forms +
  the invoice widget in both variants, consent-source semantics, POST endpoint incl.
  bad-token/GET/no-phone/customer-supplied-number).
  Also fixed a pre-existing N1-introduced failure in `test_invoice_send_polish` —
  creating a Replacement now emails the tech, so `mail.outbox[0]` was the assignment
  email, not the invoice email. Any outbox-indexing test that creates jobs is suspect now.
- **DONE 2026-08-31 — version 4 submitted, `REVIEWING`.** v3 was denied 08-26 (business-email
  domain + a screenshot staged with the box ticked). The steps below are kept as the recipe;
  what actually happened across all four versions, including the two API traps that auto-denied
  version 2, is in Appendix A. Next action is the activation checklist, when it flips COMPLETE.
- **What remains is Drake's (after this PR deploys):**
  1. Pick a test customer **not opted in** in the live shop, open one of their invoice
     public links, screenshot the "Get text updates" card (checkbox + disclosure visible,
     no real PII). Either variant is screenshot-worthy; the number-entry one arguably
     reads better to a reviewer, since the consumer types their own number.
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

## S1 · A real "booked time" — DONE (2026-08-15, PR #188)

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

**Notes** *(session run 2026-08-15, branch `feat/fieldops-s1-booked-time`, PR #188)*

- **Shipped as designed, both recommended decisions taken.** `scheduled_for` +
  `scheduled_window_end` on `GlassService` (migration `technician_portal/0053`,
  additive, indexed on both job types); `service_date` untouched. The quick-job
  form shows "Scheduled for" only while *Job is already done* is unchecked —
  belt AND suspenders: a JS toggle hides it, and `QuickJobForm.clean()` drops
  any submitted schedule when `already_completed` is set, so a walk-in can
  never land in a schedule bucket even with a stale value in the POST.
- **Dashboard buckets are an annotation + stable resort of the existing
  `todays_queue`, not a new query.** Each job gets `job.schedule_bucket`
  (overdue/today/later/unscheduled, computed against `timezone.localtime`);
  `queue_has_schedule` gates both the resort and the template's `{% ifchanged %}`
  group headers, so an all-unscheduled queue renders byte-identically to
  pre-S1 (asserted by test). Unscheduled jobs keep their status-priority order
  via the stable sort (they all share one key). A "Later" bucket was added
  beyond the doc's three — without it a job scheduled next Tuesday would have
  looked unscheduled.
- **Things future S-sessions should know:**
  - `scheduled_window_end` is schema-only — no UI writes it yet. S4's
    customer time-window capture was its intended first writer; **S7 may get
    there first** (see S7's duration rule). Whichever lands first fixes the
    field's semantics for the other.
  - `ReplacementForm` lives in `apps/saas/forms.py` (not technician_portal),
    same as the replacement views — the S3 day view will need both apps.
  - Shop-created jobs passed `queue_status='PENDING'` get flipped to APPROVED
    by `resolve_initial_shop_status` — bucket tests use IN_PROGRESS/APPROVED.
  - The queue is still capped at 20 by status-priority BEFORE bucketing, so
    with >20 active jobs a scheduled-today PENDING job can be cut by
    unscheduled IN_PROGRESS ones. Fine at current shop sizes; S3's dedicated
    day view queries by `scheduled_for` directly and won't inherit this.
  - Multi-break deliberately untouched: its date input is the work date
    (`service_date`), not a booking.
- **Tests:** `tests/test_fieldops_s1.py` (16). Smoke + 190 adjacent green,
  incl. the CSS guards after `./scripts/build_css.sh`.

## S2 · Field dispatch — executes B1 — DONE

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

**Notes** *(session run 2026-08-15, branch `feat/fieldops-s2-field-dispatch`)*

- **Shipped as designed: structured fields, customer fallback, no backfill.**
  `service_address/_city/_state/_zip` on `GlassService` (migration
  `technician_portal/0054` — additive, both tables). The display path is
  `get_service_location()` (+ `get_service_location_parts()`), which uses the
  job's own fields when ANY is set and otherwise **falls back to the
  customer's address at render time** — so every existing job with an
  addressed customer gained a working map link the moment this deployed,
  with zero data migration. `service_address` is a TextField only so a copy
  from `Customer.address` (also a TextField) can never overflow; the forms
  all render it single-line.
- **Only genuine overrides are persisted.** The quick-job picker JS prefills
  the More-details location inputs from `data-address/...` attrs on the
  customer options (`CustomerEmailSelect`), so the tech sees the default and
  can edit it — but `QuickJobForm.clean()` blanks a submission that exactly
  matches the picked customer's current address (whitespace/case-normalized).
  Without that, every job would freeze a copy of the address as it stood on
  creation day, and fixing a typo on the customer would fix nothing anywhere.
  A partial override never splices: `get_service_location()` refuses to mix
  the customer's city onto a job-site street.
- **Links are composed client-side** (`static/js/field_dispatch.js`): the
  templates emit `data-map-query` / `data-call-number` attributes and the JS
  builds the Google Maps universal URL + `tel:` hrefs in the browser, per
  B1's privacy note — the rendered page contains no maps URL (asserted by
  test). Surfaces: dashboard job card (Call sits left with the job info,
  deliberately far from the Continue/Start action on the right), repair
  detail Customer panel, replacement detail Assignment card. All links are
  `.tap-target`. A job with no address and no phone renders no row at all.
- **Things future S-sessions should know:**
  - S3's day view should render the same `data-map-query`/`data-call-number`
    attrs and include `field_dispatch.js` — the card markup in
    `dashboard.html` (grep "Field dispatch (S2)") is the copy source.
  - The job-list mobile card is a whole-card `<a>` — nested links are
    invalid HTML, so it deliberately got no inline actions; the dashboard
    card and detail pages carry them. If S3/S5 want actions on a list row,
    restructure the row first.
  - Legacy per-type forms (RepairForm, saas ReplacementForm) carry the four
    fields for editing; they show the stored override (blank = fallback),
    not the effective address.
  - The dashboard queue and detail views already `select_related('customer')`,
    so the fallback adds no queries.
- **Tests:** `tests/test_fieldops_s2.py` (20). Smoke + 205 adjacent green
  (S1, touch targets, view transitions, individual-vs-fleet, job-form
  parity/create/invoice/list), incl. CSS guards after `./scripts/build_css.sh`.

## S3 · Day / agenda view — DONE (2026-08-16, PR #190)

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
| **Out of scope** | Drag-and-drop (**now S7** — carved out of S5 on 2026-08-17), editing times from the view (S5), customer-facing schedule, iCal export. |

**Notes** *(session run 2026-08-16, branch `feat/fieldops-s3-day-view`, PR #190)*

- **Shipped as designed, both recommended decisions taken:** day view only
  (no week grid), and it lives at `/tech/schedule/` (`day_schedule`) behind a
  "Schedule" nav link (desktop + mobile, `user_can_repairs`-gated); the
  dashboard's *Today* bucket header now links there. View is
  `apps/technician_portal/views/schedule.py`; the row markup is a shared
  partial, `templates/technician_portal/includes/schedule_row.html` — **S5
  should extend that partial, not fork the dashboard card again.** It renders
  the S2 `data-map-query`/`data-call-number` attrs and the page loads
  `field_dispatch.js`.
- **Scope rules that weren't in the table:**
  - REQUESTED jobs never appear on the day sheet even when a wished-for
    `scheduled_for` is set (S4 will write those) — a request isn't a booked
    visit. Managers see them in the "Needs scheduling" triage rail instead,
    alongside unscheduled active work (rail capped at 8, with count +
    overflow link to the job list).
  - COMPLETED jobs stay on the sheet, dimmed — a run day should look run.
  - Replacements are NOT gated on `tenant.offers_replacements` (unlike the
    dashboard queues): a booked replacement is a promise, and flipping the
    shop toggle must not vanish tomorrow's appointment.
  - Manager grouping lists **every active tech** (free techs render
    "Nothing scheduled" — that's the "who's free" answer), plus any
    inactive tech still holding a job that day. Viewer's own group sorts
    first.
- **Day boundaries** are computed in the shop's local timezone
  (`TIME_ZONE=America/Chicago` in prod) by combining midnight per-day —
  same convention as S1's dashboard buckets; storage stays UTC.
- `scheduled_window_end` is rendered ("to 11:00 AM") when present, though
  nothing writes it yet — S4 remains its first writer.
- **Tests:** `tests/test_fieldops_s3.py` (19). Smoke + S1/S2/touch/view-
  transitions/step5-nav/individual-vs-fleet/job-form-parity/N1 green.
  Pre-existing failure to know about: `test_unified_dashboard.…
  test_replacement_only_shop_queue_has_no_repair_wording` fails identically
  on origin/main (it's in the known ~90–105 baseline).
- Verified live against a scratch DB (owner + plain-tech logins, tomorrow
  navigation, walk-in row with no address/phone renders no dispatch links).

## S4 · Customer requests carry when + where — DONE (2026-08-18)

| Field | Value |
|---|---|
| **Goal** | A customer requesting work can say where the vehicle is and when it's available; that preference rides the job all the way to the assigned tech; and one shop click turns it into a real booking. |
| **Size** | M |
| **Depends on** | S1 (`scheduled_for`), S3 (triage rail + day view), S7 (the non-form write path and its four rules), N1 (the assignment/notification helper). S2 supplies the address plumbing — reuse it, don't add a second location concept. |
| **Why it matters** | Drake's scenario: "what if a customer requests a job and the truck is located somewhere else or has to be in a certain time frame." Today that wish can only travel as free text in the notes blob — **and the product already claims the feature in four places** (see below), which is worse than not having it. |
| **Verified current state** *(2026-08-17)* | **Repair requests do not wait for anyone.** `handle_single_repair_request` (`apps/customer_portal/views.py:1940`) and `handle_batch_repair_request` (:2039) create at `REQUESTED`, then call `_auto_accept_customer_repair` (:1903), which saves `APPROVED` (the 2026-08-07 frictionless-requests change, PR #147). Only **replacements** stay `REQUESTED` (`request_replacement` :1722-1812 — the shop must price them first). Neither form captures a date, a window or an address: the repair path reads `unit_number/description/damage_type/damage_photo_before` (:1954-1957), the batch path reads the JSON keys `unitNumber/damageType/notes/hasPhoto/hasMultipleBreaks/breakCount/damageLocation{X,Y}` (:2131-2142), the replacement path reads `unit_number/glass_position/description/damage_photo` (:1760-1763). **The over-promise lives in four places, not one** (the doc's old `:2018` anchor has drifted): `views.py:2032`, `:2250`, `:2257` (the AJAX JSON copy), and the customer detail badge `templates/customer_portal/repair_detail.html:61-62`, which reads **"Scheduled for Repair"** on an auto-approved request whose `scheduled_for` is null. Day sheet admits `DAY_STATUSES = PENDING/APPROVED/IN_PROGRESS/COMPLETED` (`views/schedule.py:22`); the triage rail is `scheduled_for__isnull=True` + `TRIAGE_STATUSES`, capped at 8, sorted `service_date` desc (`:24,:26,:121-139`) and rendered by **inline markup** in `schedule.html:68-96`, not the shared `schedule_row.html`. Capture precedent: `RewardRedemption.preferred_date` (DateField) + `preferred_time` (TimeField) (`apps/rewards_referrals/models.py:210-217`, parsed `views.py:503-515`, staff display `reward_fulfillment.html:87-109`). Customer address is `address/city/state/zip_code` (`core/models/customer.py:81-84`) — note **`zip_code`**, while the job field is `service_zip`. There is **no per-tenant timezone**: `TIME_ZONE` is a global setting (`settings/production.py:197`, America/Chicago). |
| **Considerations** | The engineering detail is long enough to be worth prose — see **"Design notes"** below the table. The four rules that shape everything else: **(1)** a preference is **not** a booking — it gets its own fields and never lands in `scheduled_for` without a shop action, because an auto-approved repair with a `scheduled_for` is a *booked visit on the day sheet* the instant the field is set; **(2)** confirming writes the time through an S7-style `.update()` service, never `save()` (which re-prices the job and rewrites live invoices); **(3)** one submission carries **one** preference, and confirming a multi-break/multi-unit batch times the whole `repair_batch_id` group together — one physical visit; **(4)** reuse S2's `service_address*` for the *where*, with S2's "blank an unchanged prefill" rule, or every request freezes a stale copy of the customer's address. |
| **Decisions needed** | **(a)** Explicit confirm vs. silently defaulting `scheduled_for` to the preference — **recommend explicit**, and this is no longer a taste call: repairs auto-approve, so a silent default publishes an unagreed appointment onto the tech's day sheet. **(b)** Customer-facing confirmation email — **recommend NOT opening a new customer email stream in this session**: echo the preference back in the existing `repair_request_received` email and show the confirmed time in the portal; a new `job_scheduled` customer template needs Drake's yes first (CLAUDE.md: don't expand customer-facing email without asking; replacement lifecycle emails were deferred by choice). **(c)** Field naming + granularity — recommend `preferred_date` (DateField) + `preferred_window` (MORNING/AFTERNOON/ANYTIME) on `GlassService`, **no time picker** (see the timezone note in Design notes). **(d)** Whether the customer sees the confirmed time in the portal — recommend yes, on the service detail page, replacing the badge that lies. |
| **Acceptance criteria** | A customer submits a repair or replacement request with a preferred date + window (and, if the vehicle is elsewhere, a service address) → the shop sees the wish on the job detail **and** on the triage rail, sorted so the soonest wish is visible → one confirm action writes `scheduled_for` (+ `scheduled_window_end` from the window) without changing `cost`, `tax_amount` or any invoice line (asserted by a test that puts the job on a live invoice) → the job appears on the assigned tech's day view at that time, with S2's map/call actions → the assigned tech is notified once, and never for their own action. A batch submission carries one preference onto every row it creates, and confirming times the whole batch. Requests with no preference behave exactly as today. The four over-promise copies are honest. Stale/duplicate confirms are refused, not silently overwritten. |
| **Out of scope** | Live availability or slot-picking against tech capacity (S5/S6). Technician working hours (S6 item 4). Self-service rescheduling by the customer (S6 item 5). Dragging an unscheduled job from the rail onto a time (the S7 follow-on). Customer-facing SMS (N2). A `job_scheduled` customer email unless decision (b) says yes. |

**Design notes** *(from a 2026-08-17 read of the real code — these are the expensive findings; do not re-derive them)*

- **The premise in the old table was wrong, and it changes the design.** "Customer
  requests enter as REQUESTED and the shop confirms" is true only for
  *replacements*. A repair request is auto-accepted to APPROVED milliseconds later
  (`_auto_accept_customer_repair`, `views.py:1903`) — deliberately, so a chip repair
  priced from the shop's price book needs no review. `APPROVED` is in
  `DAY_STATUSES`, so **the only thing keeping a customer's wish off the tech's day
  sheet is that `scheduled_for` is null.** Write the preference there and the shop
  has promised a time nobody agreed to. Hence separate preference fields plus an
  explicit confirm — not "default it and let the shop fix it."
- **The product already claims this feature four times.** Three success messages
  (`views.py:2032`, `:2250`, and the AJAX JSON at `:2257`) say *"you're on the
  schedule!"*, and the customer detail page badges an auto-approved request
  **"Scheduled for Repair"** (`customer_portal/repair_detail.html:61-62`). Fixing
  the copy is part of the session, not a nicety; and note the badge is the one
  that survives on screen long after the toast is gone.
- **Batch requests multiply everything.** One submission can create 50 units × up
  to 20 breaks (`views.py:2080-2081`), all in one `transaction.atomic()`, each with
  its own `repair_batch_id` group for multi-break units. A preference captured once
  must be written to **every** row, or the rail shows some rows with the wish and
  some without. Confirming must set the time for the whole batch in one write —
  S7 refuses to drag a batched repair for exactly this reason (moving one break
  silently splits one physical visit), and a per-row confirm would reintroduce it.
- **The existing request emails already fan out per row.** `signals.py:91-99`
  fires `_notify_customer_request_received` **and** `_notify_technician_new_request`
  on every created REQUESTED Repair — a 5-unit batch is 5 customer emails and 5 tech
  emails today. That is a pre-existing wart (N3's inventory), but it constrains S4:
  if the preference is echoed back to the customer, echo it in that template rather
  than adding a fifth message, and do not add any new per-row send.
- **Never write the time with `save()`.** S7's rule 1: `GlassService.save()` runs
  `TaxService` on every Repair save and pushes prices onto live invoices through
  `invoice_sync`. The confirm action should be a sibling of
  `services/schedule_swap.py` (`set_appointment(...)`, same module or a shared
  `services/schedule.py`), reusing its shape: `select_for_update()` in deterministic
  `(model, pk)` order, expected-current-value folded into the `.update()` WHERE so
  the returned row count *is* the optimistic lock (409 on a stale confirm), JSON
  refusals, and `transaction.on_commit()` for the notification. Two managers
  confirming the same request at once is the realistic race here.
- **Reuse S7's `job_rescheduled` for the tech, don't invent a second template.**
  It exists (core migration `0029`, arriving with PR #192), is category
  `assignment` so the existing `TechnicianNotificationPreference` opt-out covers it,
  and is priority MEDIUM on purpose — **HIGH maps to `['in_app','sms']` and excludes
  email entirely** (N1's structural bug). Any new template S4 does add must be
  MEDIUM or carry `channels_override`. Beware the naming trap while reading:
  `repair_approved` notifies the **technician**, not the customer
  (`signals.py:228-252`), and `core.Notification` has its own unrelated
  `scheduled_for` column (`core/models/notification.py:102`).
- **Window → `scheduled_window_end`, with S7's semantics.** S7 fixed the field's
  meaning: each job keeps its own duration across a move, NULL stays NULL. S4 is its
  second writer and its first *originating* one — confirming "morning" should write
  a real start **and** end (the day view already renders "to 11:00 AM" when present),
  so the shop's window definition (what MORNING means in hours) has to live
  somewhere. Simplest honest answer: constants in the confirm service, not a new
  settings screen.
- **Why a coarse window and not a time picker.** There is no per-tenant timezone —
  `TIME_ZONE` is one global setting. A fleet dispatcher in another timezone picking
  "8:15 AM" is ambiguous in a way that "morning" is not, and the shop is the one who
  decides the real clock time anyway. A DateField plus a three-value choice also
  matches the shipped `RewardRedemption` precedent, which means a customer-facing
  pattern the portal has already proven.
  **— Overturned during the build (Drake, 2026-08-18): "there should be a way to
  dial the time better. we're dealing with trucking companies and fleets in this
  portal, sometimes they're on a tight deadline."** He is right and this note was
  wrong. "Morning" is not an answer when the unit rolls at 06:00 and the yard has
  it from 04:30; worse, it is indistinguishable from a retail customer with no
  constraint at all, so the shop cannot tell an urgent ask from a relaxed one.
  The timezone objection is answered by **labelling** the clock, not by refusing
  precision — see the EXACT bullet in Notes. The presets stayed: most work
  genuinely doesn't care, and making every request pick a clock taxes all of them
  to serve some of them.
- **Address: prefill, but persist only real overrides.** `QuickJobForm.clean()`
  blanks a submitted address that matches the picked customer's current address
  (whitespace/case-normalized) precisely so a typo fixed on the customer record
  fixes every job. The request form must do the same, or each request freezes the
  company address as it stood that day. Two further traps: the customer field is
  `zip_code` and the job field is `service_zip` (a straight name-for-name copy is a
  bug), and `get_service_location_parts()` (`models.py:565-590`) is
  **all-or-nothing** — any job field set wins wholesale, so half an address ("Yard
  4" with no city) silently drops the customer's city and breaks the map link. If
  what customers actually type is a landmark, that belongs in `customer_notes`.
- **The rail is where the wish has to show up, and the rail is a second renderer.**
  `schedule.html:68-96` renders triage rows inline rather than through
  `schedule_row.html` — S7 hit this and had to special-case it. S4 adds the third
  reason to collapse them; do that first if the rail grows a confirm control.
  Also: the rail is **capped at 8 and sorted by `service_date` desc**, so without a
  sort change a request wished for tomorrow can sit invisibly below eight newer
  ones. Sort the rail by preferred date (nulls last).
- **Plain technicians cannot see REQUESTED jobs at all** (`views/dashboard.py:61-74`,
  `views/jobs.py:42-45`) — deliberate, CODE-081. So for replacements the whole
  where-and-when only reaches the tech *after* the shop confirms, which is another
  argument for making confirm a real, visible step rather than a silent default.
- **Testing gotchas inherited from S7 and N4.** Notifications sent from
  `transaction.on_commit()` do not run under `TestCase` — wrap the POST in
  `captureOnCommitCallbacks(execute=True)` or the test passes while testing
  nothing. And any test that indexes `mail.outbox[0]` after creating a job is
  suspect: since N1, creating a job emails the tech.

**Notes** *(session run 2026-08-18, branch `feat/fieldops-s4-request-when-where`)*

- **Shipped as designed; all four recommended decisions taken.** `preferred_date`
  (DateField) + `preferred_window` (MORNING/AFTERNOON/ANYTIME) on `GlassService`
  (migration `technician_portal/0055`, additive, both tables), explicit confirm,
  no new customer email stream, and the customer sees the booked time in the
  portal. The wish and the booking are separate columns end to end — nothing in
  the request path can write `scheduled_for`, which is asserted directly rather
  than left to reviewer discipline.
- **The one write path is `apps/technician_portal/services/schedule_booking.py`**
  (`confirm_appointment`), a deliberate sibling of S7's `schedule_swap.py` reusing
  all four of its rules: `.update()` never `save()`, deterministic pk-ordered
  `select_for_update()`, expected-value-in-WHERE as the optimistic lock (409 on a
  stale confirm), and `transaction.on_commit()` for the notification. Endpoint is
  `POST /tech/schedule/book/` (`schedule_book`), JSON for every outcome including
  refusals, authorization checked in-body. **S5 should call this, not reimplement
  it** — same relationship it has to S7's swap.
- **`window_bounds(day, window, start_time, end_time)` is where a window becomes
  real clock time**, and it is the only place that knows what "morning" means
  (8–12, 12–17, 8–17, in `PREFERRED_WINDOW_HOURS` on the model). Both ends are
  wall-clock combined with the date, so a DST-transition day keeps "8 AM to noon"
  honest. This makes S4 `scheduled_window_end`'s first *originating* writer, as S1
  predicted — S7 only ever preserved an existing duration.
- **EXACT windows — the fleet case, added mid-session at Drake's push (see the
  struck-through Design note above).** `preferred_window='EXACT'` reads
  `preferred_time_start` / `preferred_time_end` (migration
  `technician_portal/0056`) instead of a fixed hour pair, so a customer can ask
  for 04:30–05:45 and the shop can *book* 04:30–05:45 — the rail's control grew
  the same two inputs, because offering precision on the request form and then
  forcing the booking into a four-hour block is the same broken promise as never
  asking. Details worth keeping:
  - **The end field is labelled "Must be done by"**, because for a fleet the
    cutoff *is* the request. A lone end books back from it by
    `NOMINAL_JOB_LENGTH` (1 hour, a constant in the booking service — nothing in
    the app models job duration yet, and a settings screen for it would promise
    more than the number is worth; S5/S6 can replace it).
  - **Every exact-time surface prints `shop_timezone_label()`** ('CDT'). That
    helper and `window_bounds()` are the two places to change when per-tenant
    timezones arrive.
  - **Times are ignored unless the window is EXACT**, on both the customer form
    and the endpoint, so a stale pair left in a POST can never silently override
    a preset. And EXACT submitted with *no* times drops the window entirely
    rather than storing a bucket that lies about its own precision.
  - `preferred_window_short` renders the clock rather than the bucket name for
    an exact ask — "a set window" tells a dispatcher nothing.
  - An end at or before the start is treated as a typo, not a window crossing
    midnight: the endpoint refuses it, and the request form keeps the usable half
    rather than discarding the whole ask.
- **The rail is now a shared partial.** `schedule_row.html` grew a `triage=True`
  mode (no time column, no drag handle, wish chip, inline book form) and
  `schedule.html`'s inline copy is gone. The doc called this "the third reason to
  collapse them"; it was, and it cost about twenty lines. The rail also sorts by
  preferred date now (nulls last, then newest) — with the cap at 8, pure recency
  buried a customer who asked for tomorrow under eight requests naming no day.
- **A live bug found on the way, fixed here: the customer's "request received"
  email has never been sent.** Core migration `0009` seeded
  `repair_request_received` and `repair_request_submitted` with **lowercase**
  `default_priority` ('medium'/'high') — the only two such rows in the table.
  `Notification.get_delivery_channels()` compares against `'MEDIUM'`/`'HIGH'`, so
  a lowercase value matches no branch and falls through to `['in_app']`: the
  email was rendered and thrown away on every migration-seeded database, which is
  every fresh install and production unless someone ran
  `setup_notification_templates` by hand (the command always had it right, which
  is exactly why this survived). Core migration `0031` uppercases both templates
  and any notification rows already written from them. This mattered to S4
  because decision (b) echoes the requested time back *in that email* — the echo
  would have been dead on arrival. **For N3:** `repair_request_submitted` is now
  correctly HIGH, which under N1's mapping is `['in_app','sms']` and still
  excludes email; whether the shop's "new request" notice deserves a
  `channels_override` is N3's call, and it is now visible instead of hidden
  behind a broken string compare. SMS is globally dark, so nothing started
  sending.
- **`job_rescheduled` was generalized rather than forked.** Its body said "Two of
  your jobs traded times", which is false for a booking, so the templates took a
  `lead` variable and a guarded second row and the SMS body now uses `{{ summary }}`
  (core migration `0030`). One template, one category, one opt-out — the doc's
  "don't invent a second template" instruction, honoured in substance.
- **The over-promise was in five places, not four.** The doc found three success
  messages and the detail badge; the fifth is the batch **success modal**, which
  said *"Status: Pending Approval"* — wrong in the opposite direction from the
  toast beside it, since the server auto-approves. And the confirmation email
  said "added to the schedule" / "Status: Scheduled". All now say accepted-not-
  yet-booked. Two tests in `test_customer_auto_accept.py` asserted the old
  wording and were updated with the reason inline.
- **Things future S-sessions should know:**
  - Booking is **manager/owner only** (`sees_whole_shop`, same rule as the swap).
    Plain techs cannot see REQUESTED work at all (CODE-081), so a tech-side
    confirm would be half-blind. If S5 wants the assigned tech to self-schedule,
    that is a real decision, not an oversight.
  - Confirming a **multi-break batch books the whole `repair_batch_id` group in
    one transaction** at one time — one physical visit. The anchor row's expected
    time is applied to every sibling, so a batch someone else half-moved refuses
    rather than splitting.
  - The address override starts **empty behind a toggle** on the customer form
    rather than prefilled. S2 solved the frozen-copy problem by blanking an
    unchanged prefill; starting empty avoids it instead. The server still
    normalizes and drops a match, and **completes a partial override from the
    customer record** — `get_service_location_parts()` is all-or-nothing, so
    "Yard 4" with no city would otherwise drop the customer's city and kill the
    map link.
  - A **past preferred date is dropped on read** (stale autosaved form), so the
    rail never shows a wish for last Tuesday.
  - **Nothing models technician availability or working hours yet**, so a fleet
    can ask for 04:30 and the shop can agree to it with no warning that nobody
    starts before 07:00. That is S6 item 4, and EXACT windows make it matter
    sooner than the backlog assumed — S5's conflict display should surface it.
  - `_read_service_preference()` / `_preference_form_context()` in
    `apps/customer_portal/views.py` are the shared reader/context pair — both
    request flows and all their error-path renders go through them.
- **Tests:** `tests/test_fieldops_s4.py` (46, twelve of them the EXACT-window path). Green alongside S1/S2/S3/S7 (122
  total), N1/N4, customer auto-accept, request-replacement, primary-contact,
  e2e-today, touch targets, view transitions, step5-nav, job-form parity,
  individual-vs-fleet, invoice-send-polish and email branding. The one failure in
  that sweep — `test_unified_dashboard.…test_replacement_only_shop_queue_has_no_repair_wording`
  — was re-confirmed failing identically on a clean `origin/main` worktree; it is
  in the known ~90–105 baseline, same as S3 recorded.
- **Not done, deliberately:** dragging an unscheduled job from the rail onto a
  time (the S7 follow-on), customer-facing notice of a confirmed time beyond the
  portal, and rescheduling from the customer side (S6 item 5).

## S5 · Dispatch board — DONE (2026-08-18)

| Field | Value |
|---|---|
| **Goal** | One owner/manager surface where triage happens: unassigned + unscheduled work beside each tech's day; assign and schedule in one motion; conflicts visible. |
| **Size** | L |
| **Depends on** | S1–S4, N1. |
| **Why it matters** | This is where "notification," "address," and "time" compound into an actual dispatch workflow — the shop runs its morning from one screen. |
| **Verified current state** | Nothing exists. Assignment lives in per-job views (`assign_repair` etc.); triage is the REQUESTED queue; no combined surface. |
| **Considerations** | Build on S3's owner view: the unscheduled/unassigned rail already exists (S3) and already books a time inline (S4). What is left is the *assign* half — POST to the N1 assignment helper for who, and to S4's `schedule_book` endpoint for when; one code path each, always, and neither needs writing.  Conflict display is *informational* first (two jobs overlapping for one tech; job scheduled outside customer's preferred window) — no hard blocking. Drag-and-drop is a polish pass, not the MVP; plain controls first — and the gesture itself is **no longer S5's to design**: S7 owns drag-to-swap and ships the reorder endpoint, so this board reuses it rather than building a second one. Every assignment from the board fires the N1 notification automatically because it goes through the same helper. **Known gap — technician availability:** nothing in the arc models working hours or days off, so conflict detection here can only see job-vs-job overlap, not "Marcus doesn't work Tuesdays." Don't build an availability model preemptively — but when scoping this session, decide whether a minimal per-tech working-hours field (or even a free-text "usual schedule" note shown on the board) is worth including, and record the decision in Notes. Full availability/capacity modeling stays in S6's backlog. |
| **Decisions needed** | Defer all — scope this session properly when S1–S4 are real. Written now only so the arc has a visible destination. |
| **Acceptance criteria** | (Draft) A manager can take a REQUESTED/unassigned job from the rail, pick tech + time, and the tech is notified — without leaving the board. Double-booking is visibly flagged. |
| **Out of scope** | Route optimization, capacity math, customer self-scheduling (S6/backlog). |

**Notes** *(session run 2026-08-18, branch `feat/fieldops-s5-dispatch-board`)*

- **The board is `/tech/schedule/`, not a new screen.** For a manager the S3 day
  view now *is* the dispatch board: rail on top, one card per tech below,
  conflicts inline. Building a second surface would have meant a second set of
  queries, a second row partial and a second answer to "where do I look in the
  morning". Everything S5 added is one more control on rows that already
  existed.
- **One endpoint, one motion: `POST /tech/schedule/dispatch/`**
  (`services/dispatch.py::apply_dispatch`). It writes nothing itself — it
  composes N1's `assign_job` and S4's `confirm_appointment` inside one
  transaction. The doc's plan was two POSTs (one per helper); that turned out
  to be wrong in a way worth recording: **two endpoints means a half-applied
  dispatch** — assigned but not booked when the second call fails — and two
  notifications for one decision. One transaction fixes both, and neither
  helper's rules were copied.
- **One motion, one message.** When a dispatch also reassigns, the booking
  notification is suppressed (`confirm_appointment(notify=False)`) and the
  assignment email carries the time instead — `_booked_when()` fills a new
  `scheduled_when` context key, rendered as a guarded `Scheduled:` row in both
  `repair_assigned` templates. Any assignment of an already-booked job now
  states its time, which is a small win beyond the board. Book-only still uses
  S4's `job_rescheduled`; assign-only still uses N1's pair (new tech +
  reassigned-away). Verified live: one mail to the new tech reading
  `SCHEDULED: Wed Aug 19, 4:30 AM – 5:45 AM`, one reassigned-away to the old.
- **Two gates, not one — and the wider one already existed.** Booking needs
  `sees_whole_shop` (S4's rule); reassigning additionally needs
  `can_assign_work`, because `assign_repair` has gated on it since CODE-079 and
  a second door to the same action must not be a weaker one. A manager with
  only the first gets S4's narrower `/tech/schedule/book/` endpoint rendered
  into their row form and no technician picker at all — **which is why both
  endpoints stay live**: the split is a permission, not dead code. Note
  `is_tenant_admin` returns True for a *membership* role of manager, so the
  `can_assign_work` flag only bites a Technician-record manager — same as
  `assign_repair`.
- **`data-technician-id` is the second optimistic lock**, folded in beside
  S4's `data-scheduled-for`. Two managers working the same rail row at once is
  the realistic race, and the loser now gets a 409 instead of silently winning.
  A refused dispatch books nothing: the assign half rolls back with the
  booking half (asserted).
- **Conflict display, and the finding that shaped it.** Plain interval overlap
  is useless here: S4 books presets into real hours (MORNING = 08:00–12:00),
  so *every* pair of morning jobs overlaps exactly and a board that flagged
  that would flag a normal day end to end. `services/schedule_conflicts.py`
  therefore splits the question in two:
  - **Double-booked** — only between windows ≤ `PRECISE_WINDOW_MAX` (2h), i.e.
    the ones that assert a clock. That's the one that matters, and EXACT
    windows made it real. Rows of one `repair_batch_id` never flag each other
    (S4 books them as one visit on purpose). A pile-up collapses to one chip
    ("Overlaps 2 other jobs at this time") — the first live check printed the
    same sentence twice on every row, and a wall of identical warnings reads
    as decoration.
  - **Over-committed** — per tech, nominal work vs the span it was booked
    into ("3h of work booked into 1h"). This is where the coarse case belongs:
    it's a capacity question, not a collision.
  - **Off the customer's ask** — booked outside the S4 preference. The most
    actionable of the three, because someone can still call them.
  Nothing blocks a write. A shop with two people in a truck is allowed to
  double-book on purpose; the board's job is to stop it happening by accident.
- **Availability decision (the one the table asked for): not built, and not
  faked.** `Technician.working_hours` **already exists** — a `JSONField` with
  `default=dict`, no schema, no consumer, and no UI outside Django admin (only
  hit is `admin.py:112`). Giving it meaning means inventing a shape, a
  settings screen and a validator, which is the availability model S6 owns.
  A free-text "usual schedule" note was considered and rejected: it can't be
  checked, so it would put a claim on the board that the board can't stand
  behind. Consequence to accept: `NOMINAL_JOB_LENGTH` (1h, S4's constant) is a
  placeholder not a measurement, so the capacity signal is directional, and a
  fleet can still be promised 04:30 with nobody starting before 07:00. **S6
  item 4 is now the highest-value unbuilt thing in this arc** — EXACT windows
  made it matter sooner than the backlog assumed.
  *(Update 2026-08-24: **S8 built it**, and the call above held up — it
  invented the shape, the settings screen and the tolerant reader, and it
  took a full session to do properly. `annotate_conflicts()` has a fourth
  signal and `technician_load()` a real denominator; `NOMINAL_JOB_LENGTH` is
  still a placeholder.)*
- **Smaller things worth knowing:**
  - The rail's overflow used to link to the job list, which has no wish, no
    picker and no Book button — the three things a manager came here for. It
    expands in place now (`?rail=all`, "Show fewer" to collapse). The cap of 8
    stays the default so an 80-row rail can't bury the day.
  - The Move control on a booked row stays hidden until the picker names
    somebody else. A `<select>` is one tap from a misfire and this write emails
    two people.
  - `schedule_booking.js` → `schedule_dispatch.js`, and its `data-book-*`
    attributes → `data-dispatch-*`; two S4 tests assert those names and were
    updated with the reason inline. Each form now names its own endpoint in
    `data-post-url` rather than the script choosing.
  - **REQUESTED work still notifies nobody** when dispatched. That is N1's rule
    (a tech can't open REQUESTED work at all — CODE-081) and S4's booking
    notification is already silent the same way; it is consistent, not an
    oversight, but it means a manager who dispatches a REQUESTED replacement
    should expect the tech to hear about it when the shop accepts it.
  - Dispatching a batch moves and books **every** row of the visit, and a batch
    someone else half-moved refuses rather than splitting — S4's rule, extended
    to the technician.
- **Tests:** `tests/test_fieldops_s5.py` (46). Green alongside S1/S2/S3/S4/S7
  and N1 (148 total), plus the smoke set, unified dashboard, touch targets,
  view transitions and step5-nav. The one failure in that sweep —
  `test_unified_dashboard.…test_replacement_only_shop_queue_has_no_repair_wording`
  — is the same pre-existing baseline failure S3 and S4 both recorded. Verified
  live against a scratch DB: rail → Dana at 04:30–05:45 in one click, overlap
  and wish-miss chips on the right rows, Move reveal/hide, and the single
  assignment email carrying the booked time.
- **Not done, deliberately:** dragging a rail row onto a time (still the S7
  follow-on — S5 uses plain controls, as the table asked), technician
  availability (above), route/capacity math (S6), and any customer-facing
  notice that their job was booked or moved (S6 item 5 territory, and CLAUDE.md
  says don't open a new customer email stream without asking).

## S6 · Routing / ETA / lot-walking — BACKLOG (deliberately deferred)

Not a session yet — a parking spot so nobody re-litigates scope. PRODUCT_DIRECTION.md:117/:130 explicitly defers route optimization and time-slot booking until the basic calendar proves demand; this doc honors that. When S3/S5 have real usage, candidates in rough order:

1. **Lot-walking consumer** — `CustomerRepairPreference.lot_walking_*` (`apps/customer_portal/models.py:101-126`) is a complete recurring-visit spec with a UI and zero consumers. Feed it into the S3 day view / S5 board as recurring visit entries. Cheapest item here.
2. **ETA texts** — "Marcus is on his way, ETA 2:15." Needs two-way SMS (B2, size L, provider work) or at minimum outbound-only ETA sends via the N2 plumbing.
3. **Route ordering** — order a tech's day geographically (the ROADMAP's "lot-walking scheduler"). Needs S2's structured addresses; probably needs geocoding. Do not start before a shop asks.
4. ~~**Technician availability / working hours**~~ — **shipped as S8 on 2026-08-24** (promoted out of this backlog 2026-08-19). The weekly pattern, the board chip, the "Off today" line and the capacity denominator are done. What remains in *this* item is only what S8 explicitly refused: date-ranged time off (PTO, "gone next week"), coverage rules for it, and a real capacity model to replace `NOMINAL_JOB_LENGTH`. Those want a `TechnicianAvailability` table with date ranges; a weekly pattern does not, and now has one.
5. **Self-service rescheduling** — customers changing a confirmed time from the portal (S4 deliberately excludes this). Needs a notify-shop + re-confirm loop so a reschedule can't silently invalidate a tech's day; pairs naturally with S8 once slots are real.

---

## S7 · Drag to swap two appointments — DONE (2026-08-17, PR #192)

*(Added 2026-08-17 at Drake's request — the "move a spot in front of another and they trade times" gesture. Deliberately carved out of S5, which had parked drag-and-drop as board polish; this is a self-contained M that runs on the S3 day view alone.)*

| Field | Value |
|---|---|
| **Goal** | On the day view, a manager drags one booked job onto another in the same technician's day and the two **trade time slots** — one gesture, no form, no double-booking arithmetic. |
| **Size** | M |
| **Depends on** | S1 (`scheduled_for`) and S3 (the day view, its row partial, its `_scoped()` helper). Independent of S4 and S5. |
| **Why it matters** | The day changes by phone call, not by form. "Put Acme first" today means opening two job forms, editing two datetime fields, and checking by eye that you didn't collide — while every fact the decision needs is already rendered on one screen. |
| **Verified current state** *(2026-08-17)* | `/tech/schedule/` renders rows from `templates/technician_portal/includes/schedule_row.html`, sorted `(scheduled_for, pk)`, grouped per tech for managers (`apps/technician_portal/views/schedule.py:79-118`; anchors land with PR #190). The module documents itself as read-only and **no reschedule endpoint exists anywhere**. Only three writers of `scheduled_for` exist — `RepairForm` (`forms.py:443`), `QuickJobForm` (`forms.py:975-980`, nulled at `:1168` when *already completed*), `ReplacementForm` (`apps/saas/forms.py:329`); `scheduled_window_end` has **zero writers and zero readers**. **No drag / sortable / Pointer-Events JS exists anywhere** — vendored JS is flatpickr + driver.js only, and policy forbids npm and CDNs; the one touch precedent is the tap-to-place damage diagram (`static/js/multi_break.js:1006`, `touchstart` with `{passive:false}`). `window.UI` (`static/js/ui.js`) already provides `csrfToken()`, `toast()`, `flash()`, `confirm()` and document-level delegation. Locking house rule is pessimistic `select_for_update()` inside `transaction.atomic()`; **no optimistic locking exists anywhere and nothing in the repo locks two rows at once**. |
| **Considerations** | The engineering detail is long enough to be worth prose — see **"Design notes"** below the table. The four rules that shape everything else: **(1)** never call `save()` to move a time (it re-prices the job and rewrites live invoices — see the Traps list); **(2)** each job keeps its **own duration**, so swap the starts, not the window pair; **(3)** notifications fire on `transaction.on_commit()`, never inside the locked transaction; **(4)** the endpoint must answer JSON even when it refuses — two separate mechanisms redirect to HTML today. |
| **Decisions needed** | **Taken 2026-08-17 (Drake):** pure swap (not insert-and-cascade); managers/owners only, technicians keep the page read-only; dropping an *unscheduled* job onto a time is out of scope; notify the assigned tech only, never for one's own drag, and no customer notice. **All three resolved 2026-08-17 (Drake, during the build session):** (a) **reload, no Undo toast** — `UI.flash()` + reload, keeping shared `ui.js` untouched; (b) **multi-break batches refuse the drag**, with a reason; (c) **structured log line**, no history model. Rationale in Notes. |
| **Acceptance criteria** | Manager drags A onto B in one tech's day → the two trade start times, each keeping its own window length; the list reorders and the change is stated in words, not just position. **The swap changes no price, no tax and no invoice line** — asserted by a test that puts both jobs on a live invoice and compares `cost`, `tax_amount` and invoice totals before and after. Cross-tech, cross-day, completed, unscheduled, soft-deleted, other-tenant and same-job-twice are all refused **as JSON** (including for an unauthorised caller and a read-only tenant). A stale swap returns 409 and writes nothing. The assigned tech gets exactly one notification; a manager swapping on their own day gets none; no customer is notified. Works with a finger (44px handle, page still scrolls) and with a mouse; a non-drag path exists; technicians see no handles at all. |
| **Out of scope** | Dropping an unscheduled job from the triage rail onto a time (the obvious follow-on). Cross-technician moves — that is reassignment and belongs in N1's `assign_job()`. Insert-and-cascade reordering. Editing a time inline. Any customer-facing notice (S4). The S5 board, which inherits this endpoint rather than reimplementing it. |

**Design notes** *(from a 2026-08-17 pressure-test of the design against the real code — these are the expensive findings; do not re-derive them)*

- **Writing the swap.** Fold tenant, status and the expected current time into the
  `.update()` `WHERE` clause and use the **returned row count as the optimistic
  lock** — `count != 1` is the 409, which closes the read-then-check gap for free.
  Lock with separate `.get()` calls issued in a deterministic `(table, pk)` order:
  `filter(pk__in=[a, b])` locks in DB-scan order, not yours, and `pk` alone collides
  because Repair 5 and Replacement 5 both exist — that ordering *is* the deadlock
  guard when two managers swap the same pair in opposite directions. Don't chain the
  lock and the update on one queryset, and don't `select_related` a nullable FK under
  `FOR UPDATE` (Postgres refuses the nullable side of an outer join — `Repair.customer`
  is nullable); re-fetch afterwards for the notification context. After `.update()`
  the in-memory objects still hold the **old** times, so re-fetch before building any
  message. Use `Repair.objects` (the soft-delete manager), never `all_objects`.
- **`.update()` skips every model-layer check** — the status machine and the batch
  integrity validation both live in `save()`. Whatever the endpoint does not validate
  is unvalidated: same job twice, either time now null, a status that has left
  `DAY_STATUSES` (a job can go DENIED between render and drop while the stale DOM
  still offers it), an unknown `service_type`, a null tenant.
- **Window end: keep each job's own duration.** `new_end = new_start + (old_end -
  old_start)`, and NULL stays NULL. Swapping the pair wholesale would graft a
  three-hour replacement window onto a thirty-minute repair. This is latent today
  (nothing writes the field), which is exactly why it is cheap to get right now.
- **Notifications fire after commit, never inside it.** `NotificationService` sends
  email and SMS **synchronously** and re-raises on failure — inside the transaction
  that means an SMTP round-trip while holding two row locks, and a mail hiccup rolls
  back a swap the manager already watched happen. Use `transaction.on_commit()` plus
  try/except, the way `services/assignments.py:141-146` already does. Write the
  notifier as a sibling function in that module and reuse its flat JSON-serializable
  context helpers, its "never notify the actor" comparison and its dual write
  (`TechnicianNotification` for the dashboard + `NotificationService` for bell/email).
  Two gotchas there: `TechnicianNotification` has only a `repair` FK, so a swapped
  **replacement** gets a dashboard row with no link (its `action_url` still works);
  and reuse `CATEGORY_ASSIGNMENT` — a new category needs a matching
  `TechnicianNotificationPreference` field or techs cannot opt out. Priority MEDIUM:
  HIGH excludes email (see Traps).
- **The endpoint must answer JSON even when it refuses.** Two independent mechanisms
  return 302-to-HTML today. `@manager_required` redirects *and* queues a
  `messages.warning`, which then surfaces as a stray banner on the manager's next
  page; gate in-body instead with the same tenant-scoped `sees_whole_shop` rule the
  view uses (`manager_required` resolves `request.user.technician` globally first,
  which the day view deliberately avoids per CODE-081). Separately,
  `SubscriptionEnforcementMiddleware` blocks **every** POST for a read-only/grace
  tenant and returns JSON only for paths under `/api/`, otherwise redirecting to the
  referer — i.e. straight back to the schedule page. The JS must therefore check
  `response.ok` **and** the content-type before parsing, or a trial-expired shop gets
  an opaque parse error.
- **The row partial has no identity today.** It emits only `data-map-query` /
  `data-call-number`, and `id` alone is ambiguous — `service_type` is set
  imperatively by the view, not a model field. Key every row `{service_type}-{id}`,
  and emit the expected start as `date:"c"`, comparing **parsed datetimes**
  server-side; string compare will not survive offset spelling or microseconds.
- **Gesture mechanics.** Hand-rolled Pointer Events (one path for mouse and touch);
  drag starts **only** from the handle, because the row already holds three
  interactive children (an external `target="_blank"` map anchor, a `tel:` link and
  the View/Start/Continue button). The handle is always visible — hover-reveal does
  not exist on a tablet — so budget for the row re-layout it forces on a phone; it
  carries `.tap-target` and `touch-action: none` on itself only, so the page still
  scrolls everywhere else. COMPLETED rows are on the sheet and dimmed: give them no
  handle *and* reject them as drop targets. Reject cross-group and triage-rail drops
  **in the browser with a reason** — the rail sits directly above the tech cards and
  is the most tempting wrong target on the page. Put drag state in semantic classes
  in `input.css` toggled by name; Tailwind scans `static/js`, so a literal class
  string survives but a composed one is purged.
- **Undo vs. re-render — the one genuinely unresolved conflict.** Order is computed
  server-side, so a successful swap changes both times *and* both positions. Either
  swap the two DOM nodes **and** their time blocks (including the conditional
  window-end line), or use the house pattern `UI.flash()` + reload. But reload kills
  the Undo toast, and `UI.toast()` auto-dismisses in 4s with no API for buttons and an
  `aria-live` region an interactive control has no business in — so "toast with Undo"
  means changing shared `ui.js` and taking that blast radius across every page.
  `UI.confirm()` is already a branded modal and is good backing for the non-drag path
  ("Move to 11:00 AM — swap with the 11:00 job?").
- **What cannot be verified locally.** Dev runs SQLite, where `select_for_update()`
  is a silent no-op — every lock-ordering test passes green and proves nothing. Only
  the 409 path is locally testable. Stand up Postgres, or say plainly in the PR that
  the deadlock story is argued rather than tested.
- **There is no audit trail at all.** `GlassService` has no `updated_at`, there is no
  history model, and `.update()` fires no signal. This is the first UI that changes a
  customer-facing promise, and afterwards nothing records that a time moved, who moved
  it, or what it was — with Undo re-swapping on top. At minimum log it.
- **Honest limit of pure swap.** Swapping is only the right primitive on a *full* day.
  On a half-empty day the manager's intent is "drop it at 11:00" — which is the
  out-of-scope rail drop — so on the easiest day to use it, the feature can read as
  broken. Expect that in review; the answer is the follow-on session, not a cascade.

**Notes** *(session run 2026-08-17, branch `feat/fieldops-s7-swap-appointments`, PR #192)*

- **Shipped as designed. The Design-notes pressure-test held up** — every trap
  above was real and none of them cost time a second round of discovery would
  have. The write path is `apps/technician_portal/services/schedule_swap.py`
  (`swap_appointments`), the endpoint is `POST /tech/schedule/swap/`, and
  **S5 should call the service, not the endpoint** — it already takes tenant +
  two refs + the acting user and returns a human summary.
- **The three open decisions, taken:** (a) `UI.flash()` + reload, so shared
  `ui.js` is untouched and no interactive control lands in an `aria-live`
  region — reverting is the same one gesture, dragged back; (b) a batched
  repair gets **no handle and is refused as a drop target**, with a reason,
  rather than moving the whole batch — moving one break silently splits one
  physical visit, and N-vs-1 swap arithmetic was the first thing that would
  have broken under review; (c) a **structured log line** (`fieldops S7
  schedule swap: tenant=… actor=… technician=… repair#N old->new | …`) is the
  entire audit trail. It is greppable on the instance and needs no schema.
  **This is a known thin spot** — see the last bullet.
- **Notifications required `captureOnCommitCallbacks` in tests.** The notice
  fires from `transaction.on_commit()` (correctly — `NotificationService`
  sends email synchronously and re-raises, and the caller holds two row
  locks), and `TestCase` never commits. Without wrapping the POST, the entire
  notification path silently does not run and the tests pass anyway. Any
  future session touching this must wrap, or it is testing nothing.
- **Live verification found one bug the tests could not.** The triage rail
  renders its **own** markup, not the shared `schedule_row.html` partial, so a
  drop there resolves to no `[data-job-key]` row at all — the refusal fell
  through to a silent no-op instead of the reasoned rejection the design
  called for. Fixed by falling back to the enclosing `[data-swap-group]`.
  **The general lesson: `schedule_row.html` and the rail's inline rows are two
  different renderers of the same idea.** S5 should collapse them into one
  partial before adding rail interactions, or every rail feature will need
  this same special case.
- **New template `job_rescheduled`** (core migration `0029`, plus
  `emails/notifications/job_rescheduled.html/.txt`). Category `assignment`
  **on purpose**: it reuses the existing `TechnicianNotificationPreference`
  opt-out, and a new category would need a matching preference field or techs
  could not opt out at all. Priority MEDIUM, not HIGH — HIGH maps to
  `['in_app','sms']` and would have reproduced N1's "email is structurally
  impossible" bug on a brand-new template. **N3 should inventory this one**;
  it is the schedule-change template N3's Considerations predicted.
- **Things future S-sessions should know:**
  - `scheduled_window_end` now has its **first writer**. The semantics chosen:
    each job keeps its *own* duration across a move (`new_end = new_start +
    (old_end - old_start)`, NULL stays NULL). S4's customer time-window
    capture inherits this rather than redefining it.
  - The row partial is now keyed `{service_type}-{id}` and carries its
    expected start as `date:"c"`. Anything that re-renders a schedule row must
    keep both, or drags silently 409 against a stale expectation.
  - Authorization is **in-body**, not `@manager_required` — that decorator
    redirects to HTML *and* queues a `messages.warning` that would surface as
    a stray banner on the manager's next page. `_resolve_viewer()` in
    `views/schedule.py` is now shared by the day view and the endpoint so the
    two cannot disagree about who is a manager.
  - The client checks **content-type before `response.ok`**, because a
    read-only tenant's POST is stopped by `SubscriptionEnforcementMiddleware`,
    which redirects (fetch follows it) and so delivers an HTML page as a 200.
- **What is argued rather than tested.** Dev runs SQLite, where
  `select_for_update()` is a silent no-op, so the deterministic `(model, pk)`
  lock ordering is reasoned in the service docstring and **not** proven by any
  test — a lock-ordering test here would pass green and mean nothing. The
  optimistic-lock 409 (expected time folded into the `.update()` WHERE, row
  count as the lock) *is* real on both backends and is tested.
- **Still thin, deliberately:** the log line is the only record that a
  customer-facing promise moved. If S5 puts more time-editing on the board —
  and it will — the right moment to build a real `ScheduleChange` model
  (actor, job, old/new time) is when the second writer appears, not the first.
- **Tests:** `tests/test_fieldops_s7.py` (33). Includes the money guard —
  both jobs on a live invoice, comparing `cost`, `tax_amount` and invoice
  totals before and after — plus every refusal as JSON, the 409 staleness
  paths, and the notification rules. Smoke set + 241 adjacent tests green
  (S1/S2/S3/N1/N4, touch targets, view transitions, job-form parity,
  individual-vs-fleet, invoice send polish), incl. the CSS guards after
  `./scripts/build_css.sh`. One pre-existing failure on `main`,
  **not caused here and not fixed here**:
  `core.tests.test_models.TechnicianNotificationPreferenceTestCase.test_can_send_email_not_verified`
  still asserts the pre-N1 behaviour (techs needing `email_verified`) that N1
  deliberately removed. It belongs to N3's audit.

---

## S8 · Technician working hours — DONE (2026-08-24, PR #201)

*(Added 2026-08-19, promoted out of S6 backlog item 4. S5's Notes call it "the
highest-value unbuilt thing in this arc" — S4's EXACT windows made it matter
sooner than the backlog assumed. Like S7, it is a self-contained M that runs on
surfaces that already exist; unlike S7 it adds no new gesture and no new
endpoint semantics, only a fact the board is currently missing.)*

| Field | Value |
|---|---|
| **Goal** | The shop can say when each technician actually works, and every surface that offers a person or a time knows it: the board stops silently accepting 04:30 for someone who starts at 07:00, and "who's free" becomes a true answer instead of a list of everyone active. |
| **Size** | M |
| **Depends on** | **S5 must merge first** — the whole session plugs into `services/schedule_conflicts.py` and the board's roster, which exist only on PR #197. Also S1 (`scheduled_for`), S3 (day view + per-tech groups), S4 (`PREFERRED_WINDOW_HOURS`, `window_bounds()`, `NOMINAL_JOB_LENGTH`). Independent of Phase N and Phase P. |
| **Why it matters** | S4 lets a fleet ask for 04:30–05:45 to the minute and S5 lets a manager agree to it in one click — and nothing between them knows whether anybody is awake. Everything the board says about capacity is currently a guess: `NOMINAL_JOB_LENGTH` is a constant, "over-committed" compares work against *the span it was booked into* rather than the span the tech is available for, and the technician picker offers every active tech identically at every hour of every day. |
| **Verified current state** *(2026-08-19)* | **The field already exists and is inert.** `Technician.working_hours = JSONField(default=dict, blank=True)` (`apps/technician_portal/models.py:123-127`), added by `technician_portal/0007`, **zero readers and zero writers** — the only reference in the entire codebase outside the model and that migration is a collapsed Django-admin fieldset (`apps/technician_portal/admin.py:111-116`), whose description already declares a shape: `{"monday": ["9:00", "17:00"], ...}`. No test mentions it. Every row in production therefore holds `{}`. **Nothing else models availability**: `Technician.is_active` (`models.py:118-122`, filed under a `# Availability` comment, help text "Is this technician currently active/available?") is an employment flag, and the only clock the app owns is `ReviewConfig.business_hours_start/end` (`apps/technician_portal/review_models.py:66-72`, defaults 9/19) which is a *review-email send window*, per-tenant, and applied in UTC (see Design notes — it is a live bug). **The consumers are all built:** `annotate_conflicts()` and `technician_load()` (`services/schedule_conflicts.py`, S5) are called once per technician group in `views/schedule.py` (~`:165`), not per row in the template; `roster` (`views/schedule.py:152-156`) is every `is_active=True` Technician and is what the board's picker renders; the day view prints "Nothing scheduled" for an empty group (`templates/technician_portal/schedule.html:162`). **Editing surfaces:** `update_team_member` (`apps/saas/views.py:3085-3175`) is POSTed by **three** separate forms in `templates/saas/owner_settings.html` (manager-edits-member `:472`, edit-my-own-abilities `:521`, invite modal `:1378`) and reads its booleans as `request.POST.get('can_repair') == 'on'`; a tech can also edit their own profile at `/tech/profile/` (`views/api.py:97-129`, `TechnicianForm` in `forms.py:18-45` — name/email/phone/password only). **Timezone:** still one global `TIME_ZONE` (`settings/production.py:197`, America/Chicago), no per-tenant setting. Migration head is `technician_portal/0056_exact_time_preference` (S5 adds none). |
| **Considerations** | The engineering detail is worth prose — see **"Design notes"** below. The four rules that shape everything else: **(1)** `{}` means *undeclared*, never *never works* — every existing row holds it, so any reader that treats empty as unavailable flags every job in every shop on the day it deploys; **(2)** hours are **informational**, exactly like S5's conflicts — nothing blocks a write, because a shop that calls someone in on their day off is allowed to; **(3)** hours are wall-clock local and compared after `timezone.localtime()`, never stored or compared as UTC hours; **(4)** the new fact belongs in `schedule_conflicts.py` beside the other three signals, not sprinkled across the view and the template. |
| **Decisions needed** | **(a) Where hours live** — recommend **reusing `working_hours` with a real schema plus helpers on `Technician`**, not a new model: the field exists (no migration), the admin already documents a shape, and a `TechnicianAvailability` table earns its keep only when date-ranged exceptions arrive. **(b) Shape** — recommend adopting the admin's own convention (`{"monday": ["08:00", "17:00"], …}`, a missing day or `null` = off), read tolerantly, written only by the new form. **(c) Who edits** — recommend owner/manager edits anyone and a technician may edit their own, mirroring exactly what `update_team_member` already permits for abilities; but on **its own endpoint** (see Design notes — the existing one erases what its form doesn't carry). **(d) Shop-wide default vs per-tech only** — recommend **per-tech only**, with the form pre-filled Mon–Fri 08:00–17:00: a second config object is a second place to look, and a 1–5 person shop sets this once per person, ever. **(e) One-off days off (vacation, sick)** — recommend **explicitly out of this session**: "doesn't work Tuesdays" is the weekly pattern and answers the S5 gap; "gone next week" is date-ranged, overlaps, and wants coverage rules. Say so out loud in the UI copy rather than half-building it. **(f) Does capacity change?** — recommend yes, and it is the cheapest real win: `technician_load()` should compare booked work against *declared hours* for that weekday when they exist, falling back to today's span-based number when they don't. |
| **Acceptance criteria** | An owner sets Dana to Mon–Fri 07:00–16:00 and the change is visible without a page hunt. Booking Dana at 04:30 still succeeds — and the board says so, as a chip on the row alongside S5's existing three signals, with the same one-chip-per-row discipline. A tech with no hours declared (`{}`) produces **no new chips anywhere** — asserted by a test, because that is every existing row in production. On a day Dana doesn't work, her group on the board reads "Off today" rather than "Nothing scheduled", and the dispatch picker marks her off-duty without removing her. `technician_load()` reports against declared hours when they exist. Auto-assignment behaviour is unchanged (see Design notes). Hand-typed nonsense in the Django admin JSON box degrades to "no hours declared" and never 500s the board. Tests in `tests/test_fieldops_s8.py`; smoke set plus S1–S5/S7 green. |
| **Out of scope** | Date-ranged time off / PTO / coverage (decision (e)). Customer-facing slot picking against real availability — that needs this **plus** a duration model, and stays S6 item 5 territory. Route ordering (S6 item 3). Changing who auto-assign picks. Any blocking validation. Per-tenant timezone. Breaks / split shifts / lunch. |

**Design notes** *(from a 2026-08-19 read of the real code — the expensive findings; do not re-derive them)*

- **The field is not a foundation, it is an empty promise — and it already has a
  shape.** `working_hours` has sat on `Technician` since migration `0007` with
  `default=dict`, no schema, no validator and no consumer. The one place it is
  reachable in production is a collapsed Django-admin fieldset whose help text
  says `{"monday": ["9:00", "17:00"], ...}`. That is worth adopting rather than
  improving on: it is the only convention any existing data could possibly
  follow, and choosing a different one silently orphans anything an admin typed.
  Read it tolerantly (unknown keys ignored, unparseable times = day undeclared),
  write it only through the new form, and keep the admin box as the escape hatch.
- **`{}` must mean undeclared.** Every Technician row in every tenant holds the
  default today. A reader that treats "no hours" as "not available" turns the
  board into a wall of warnings for every shop the moment it deploys — the exact
  failure S5 designed against when it collapsed repeated overlap chips into one.
  The honest default is: no hours declared → the tech is available whenever, and
  the board says nothing about them. This deserves its own test, not a comment.
- **Do not add hours to `update_team_member`.** It is POSTed by three different
  forms in `owner_settings.html` (manager-edits-member, edit-my-own-abilities,
  invite modal) and reads booleans as `POST.get(...) == 'on'` — absent means
  false. Any field added to that endpoint is silently cleared by whichever of the
  three forms doesn't carry it, and the narrow self-edit form carries almost
  nothing. Give hours a dedicated endpoint and a dedicated small form, and mirror
  the endpoint's permission rules rather than extending its body: role changes are
  owner-only, managers may not edit managers or owners (CODE-212), and editing
  your own abilities is already allowed — which is the precedent for letting a
  tech set their own hours.
- **Wall-clock, always. There is still no per-tenant timezone.** Store
  `"HH:MM"` strings, compare after `timezone.localtime()`, and build any datetime
  the way S4's `window_bounds()` does — `datetime.combine(day, clock)` made aware
  per day, never `start + timedelta(hours=n)` — so a DST-transition day stays
  honest. Storage is UTC; the hours never are.
- **The only "business hours" the app has today are wrong, and they are live.**
  `ReviewConfig.business_hours_start/end` (defaults 9 and 19) are applied by
  `_adjust_to_business_hours` (`review_service.py:319-332`) to
  `timezone.now() + send_delay_hours` — an **aware UTC** datetime whose `.hour`
  is the UTC hour. In production (America/Chicago) that clamps review-request
  emails into 09:00–19:00 **UTC** = 04:00–14:00 local, so a job completed in the
  afternoon queues its review email for roughly 4 AM the customer's time. It is
  a one-line fix (`timezone.localtime(...)` before comparing, and convert back)
  but it belongs to the review system, not here — **S8's job is to not inherit
  the bug.** Flag it for N3 / a standalone fix; it has been shipping since the
  review system went live.
- **Where the new signal plugs in — one module, two functions.**
  `annotate_conflicts()` gets a fourth signal ("Outside Dana's hours"), subject to
  the same discipline as the other three: one short chip per row, nothing that
  fires on a normal day. `technician_load()` gets a truer denominator — today it
  compares nominal work against *the span the jobs happen to occupy*, which means
  a tech booked 08:00–08:30 twice looks over-committed while a tech booked
  07:00–19:00 never does. Declared hours replace the span when present. Both are
  computed once per group in `views/schedule.py`, so the template needs no new
  query and no `default` filter.
- **Mark the off-duty tech; never hide them.** The roster is every active tech and
  it is deliberately the *dispatch* list — S5 already distinguishes it from the
  group list (an inactive tech can still appear as a group because they hold work).
  Off-duty is a third state: still offered, visibly marked. A shop with one truck
  down calls somebody in, and a picker that silently omits the person the manager
  is on the phone with reads as broken.
- **"Off today" is the highest-value line in the session.** S3's manager grouping
  renders every active tech precisely so "nobody booked Marcus" is visible, and
  prints "Nothing scheduled" under his name. With hours, that line becomes either
  a real gap in the day or a person who isn't working — two facts that look
  identical today and lead to opposite decisions.
- **Leave auto-assignment alone.** `_get_eligible_techs`
  (`apps/tenants/services/assignment_service.py:82-92`) and
  `get_available_technician` (`apps/customer_portal/views.py:2525-2560`) filter on
  `is_active` plus ability, and the latter's comment records why the
  `can_replace` fallback exists at all: a customer request must never dead-end
  unassignable (CODE-160). Adding hours as a *filter* reintroduces that dead end
  every evening and every weekend — a customer requesting work at 8 PM Saturday
  is the normal case. If hours touch assignment in a later session it must be as
  a preference with a guaranteed fallback, never a filter.
- **Nothing here blocks a write, and nothing here notifies anybody.** Hours change
  what the board *says*, not what it *does*: no new write path, no new
  notification, no `on_commit` work, and therefore none of S7/S4's
  `captureOnCommitCallbacks` testing trap — unless the session invents a
  notification, in which case that trap applies in full.
- **Keep the form smaller than the problem.** These shops run 1–5 people. Seven
  rows of on/off + start + end, pre-filled Mon–Fri 08:00–17:00, is already the
  largest control in the settings area; breaks, split shifts and per-week
  variation are how a scheduling product for 200-tech fleets looks, and Drake's
  bar is that his dad can fill it in once and never think about it again. Any
  template work needs `./scripts/build_css.sh`, and dynamically composed classes
  must be safelisted.

**Notes** *(built in two sittings — foundation 2026-08-19 on
`feat/fieldops-s8-working-hours`, board half 2026-08-24 on
`feat/fieldops-s8-working-hours-board`; shipped together as PR #201)*

- **Every recommended decision was taken, (a) through (f), unchanged.** Hours
  live in the existing `working_hours` column with helpers rather than a new
  model (no migration); the shape is the one the Django admin fieldset has
  documented since `0007`; editing is a dedicated endpoint and form on
  Settings → My Team with `update_team_member`'s permission rules *copied*
  rather than extended; per-tech only, pre-filled Mon–Fri 08:00–17:00 but
  unchecked; no date-ranged time off; and capacity now measures against
  declared hours. `services/working_hours.py` owns the shape and every read.
- **The session split in half, and the split is the lesson.** The foundation
  branch was cut from `main` before S5 merged — the spec's own "S5 must merge
  first" line was written and then not honoured — so it shipped the fact and
  none of the consumers: hours could be set and read, and no screen was any
  wiser. Nothing about it was wrong, and it was also not the session. When a
  spec names a dependency, cutting the branch is the moment it applies; the
  half that plugs into the dependency is the half that delivers the value.
- **What the board actually gained (the four consumers).**
  `annotate_conflicts()` has a fourth signal beside S5's three; `technician_
  load()` has a denominator that means something; the group empty state
  distinguishes "nobody booked Dana" from "Dana isn't working"; and the
  dispatch picker marks off-duty techs while keeping them selectable.
- **`covers()` returns `None`, not `False`, and that is the whole safety
  design.** Three states, not two: covered, not covered, and *nobody said*.
  Every consumer checks `is None` first and stays silent. That one API choice
  is what makes "undeclared means available whenever" impossible to get wrong
  by accident, and it is asserted per consumer rather than once in general —
  five tests exist purely to prove that a technician with `{}` produces no
  chip, no "Off today", no picker mark and no change in load.
- **The span denominator was quietly wrong, and declared hours fixed a real
  false positive.** S5's `technician_load()` compared nominal work against
  *the span the jobs happened to occupy*, so two half-hour jobs booked back to
  back read as over-committed (2h of nominal work in a 1h span) while a day
  booked 07:00–19:00 never did. With hours on file the comparison is against
  the shift, and both cases come out right. The span is kept for undeclared
  techs because it is the only honest number available for them — `basis` in
  the returned dict records which one was used.
- **Chips name the weekday, not the date.** "Marcus is off Saturdays" is the
  standing fact a dispatcher needs and it reads the same next week; the date
  is already on the screen. Booking outside hours still succeeds — this is
  informational exactly like S5's other three signals, and a test asserts the
  write goes through, because a shop with one truck down calls people in.
- **Finding: the board renders per-tech groups only once the day has work in
  it.** An entirely empty day gets S3's single "Nothing scheduled today"
  panel, so "Off today" — a *group* line — never appears on a day nobody is
  booked. That is S3 behaviour, left alone deliberately, but it means the
  answer to "is anyone working Saturday?" is still only visible on a Saturday
  that already has a job on it. If a future session wants the roster on an
  empty day, that is the one-line change (`{% if jobs %}` in `schedule.html`),
  and it is a design decision about what an empty board should say, not a bug.
- **Nothing was added to `update_team_member`, exactly as specced.** Three
  forms POST that view and it reads checkboxes as absent-means-off, so a field
  added there is silently cleared by whichever form omits it. The new endpoint
  copies its permission rules (owner-only role changes; a manager may not edit
  a peer manager or an owner, CODE-212; editing your own is allowed). Two
  doors, one rulebook.
- **Auto-assignment was left alone, also as specced.** Hours are not a filter
  anywhere. A customer requesting work at 8 PM Saturday is the normal case,
  and filtering on hours would re-create the CODE-160 dead end every evening.
- **No CSS rebuild was needed.** Every class the new chips use was already
  compiled into `static/css/app.css` (they are S5's chip classes), and both
  icons are in the vendored Font Awesome. Verified before committing rather
  than assumed — and it kept this session out of a file another session was
  editing at the same time.
- **Collateral repair: PR #200 broke an S4 assertion the morning this ran.**
  The email chassis rewrote the request-received copy from "confirm your time"
  to "we will confirm the time shortly" — the same promise — and
  `test_request_received_email_does_not_say_scheduled` still asserted the old
  phrasing. Fixed here by matching either wording while keeping the two
  assertions that carry the actual intent (the email must never imply a time
  nobody agreed to). Confirmed pre-existing on `origin/main` before touching
  it.
- **Finding for N3 — a missing `action_url` now costs the whole email.**
  Nineteen templates under `templates/emails/notifications/` render their CTA
  through `{% with url=base_url|add:action_url %}`, and `{% with %}` resolves
  filter arguments strictly: a context without `action_url` raises
  `VariableDoesNotExist` instead of dropping a button.
  `NotificationTemplate.render()` (`core/models/notification_template.py:131`)
  renders `email_html` at `:176` and only computes the DB `action_url_template`
  at `:179`, so the seeded `action_url_template` cannot save a caller that
  omits it. **Not live:** every real call site passes `action_url` explicitly
  (`apps/technician_portal/signals.py`, `services/assignments.py`), which is
  why the fieldops suites are green. But three tests in
  `tests/test_primary_contact.py` — part of the **smoke set this doc tells
  every session to run** — now error on `main` for exactly this reason. Left
  for N3 rather than patched here: it is #200's code, the fix is a template
  convention question across nineteen files, and it deserves the inventory N3
  is for.
- **Tests:** `tests/test_fieldops_s8.py`, 51 (30 foundation + 21 board).
  Green alongside S1–S5, S7, `test_owner_setup` and
  `test_settings_consolidation` (282 total). The three smoke-set errors above
  reproduce identically on a clean `origin/main` worktree.
- **Not done, deliberately:** PTO / date-ranged time off, customer-facing slot
  picking, breaks and split shifts, per-tenant timezone, hours as an input to
  auto-assignment, and any blocking validation anywhere.

---

# Phase S reopened — the scheduling UX arc (added 2026-08-25)

*(S1–S8 built the machinery. S9–S14 fix the surface. The premise is unchanged —
where and when — so these live here rather than in a new document; a session
should read §0 plus its own block and nothing else.)*

**The through-line:** today the product has exactly one gesture for changing a
booked time (*swap*), reachable only after a seven-step detour, and it confirms
itself with a page reload. S9–S14 add the missing **move** primitive, put job
creation and scheduling on one screen, and rebuild the day view as an ordered
list where both gestures show their work. **Swap is kept and improved, not
retired** — Drake's call, 2026-08-25.

## S9 · "Leave it blank" means unscheduled — BUILT 2026-08-25

| Field | Value |
|---|---|
| **Goal** | A job the owner meant to leave unscheduled actually comes out unscheduled. |
| **Size** | S (≈2h) |
| **Depends on** | — |
| **Why it matters** | `job_form.html:248` promises *"Optional — leave blank to keep this job unscheduled."* It cannot keep that promise, so jobs land in a schedule bucket at the moment of creation and the Unscheduled list under-reports. Every session after this one displays or moves `scheduled_for`; shipping them on top of a field that silently fills itself means debugging the wrong thing twice. **That is the only reason a two-hour session goes first.** |
| **Verified current state** *(2026-08-25)* | `templates/base_app.html:263-285` runs on every page: it walks `document.querySelectorAll('input[type="datetime-local"]')` and, `if (!input.value)`, writes the current local time before calling `flatpickr(input, …)`. `templates/customer_portal/base_customer.html:329-340` is a **verbatim second copy**. Four `datetime-local` sites exist: `QuickJobForm.scheduled_for` (`forms.py:975`, optional), `ReplacementForm.scheduled_for` (`apps/saas/forms.py:355`, optional, model field is `null=True, blank=True`), `RepairForm.repair_date` via `CustomDateTimeInput` (`forms.py:359`, **required**) and `multi_break_repair_form.html:109` `repair_date` (**required**). |
| **Build** | **Delete the prefill block, keep the flatpickr attachment.** Both files. Six lines each. |
| **Why it is safe** | Both fields that actually want a `now` default already set it themselves — `static/js/multi_break.js:31-34` unconditionally, and `static/js/repair_form.js:56-70`, which `forms.py:542` documents as exactly this. Ordering is what hides it today: `base_app`'s inline `DOMContentLoaded` handler is registered before `{% block extra_js %}`'s deferred scripts, so it fires first and those scripts find a non-empty value and skip. Remove it and they do the job they were already written to do. The customer-portal copy is dead code today (no customer-portal template renders a `datetime-local`) — delete it anyway, because leaving it is how the bug comes back through another door. |
| **Intentional behaviour change** | Jobs created through `QuickJobForm` and replacements through `ReplacementForm` now come out **unscheduled** unless someone types a time. That is what both labels promise, and it is precisely the state S12's Unscheduled drawer exists to surface. Say so in the PR body — it will look like a regression to anyone who reads only the diff. |
| **Tests** | New `tests/test_fieldops_s9.py`: POST `job_create` with `scheduled_for` empty → `service.scheduled_for is None`; same through the replacement form; a posted value still round-trips. Assert the prefill string is **absent** from both base templates (a render-level guard, the way `tests/test_view_transitions.py` guards its inline block) so it cannot be pasted back. Manual: load the multi-break form and the repair edit form and confirm both `repair_date` fields still land on now. |
| **Deliberately not done** | ~~Gating the prefill behind an opt-in `data-default-now` attribute.~~ **This is what shipped** — the spec's reasoning was wrong on two counts it could only have found by reading flatpickr. See Notes. |

**Notes** *(2026-08-25)*

- **The spec said "delete the prefill outright"; that would have broken the
  repair form.** Two findings, both cheap to re-derive and expensive to miss:
  1. **`RepairForm` renders `repair_date` AND `scheduled_for` through the same
     `CustomDateTimeInput` class** (`forms.py:409` and `:458`). One is required
     and wants *now*; the other is an optional booking time that must stay
     blank. They sit on the same page. So the opt-in has to live on the
     **field**, not on the widget class — putting `data-default-now` in
     `CustomDateTimeInput.__init__` would have defaulted the very field this
     session exists to leave alone.
  2. **Order is load-bearing.** `flatpickr` is initialised with
     `altInput: true`, which hides the real input behind a formatted one. The
     prefill therefore has to run *before* init, or the value lands on the
     hidden field and the visible box still reads empty. The spec's plan was to
     let `static/js/repair_form.js` (which fills `repair_date` only when empty)
     do the job instead — but that runs *after* `base_app`'s inline
     `DOMContentLoaded` handler, so the form would have submitted the right data
     while showing the user an empty box. `multi_break.js` would have survived
     only because it happens to sync through `_flatpickr.setDate()`.
- **`defaultDate` was the second half of the bug, and nothing had noticed.**
  The call passed `defaultDate: input.value || new Date()`. flatpickr resolves
  `w.config.defaultDate || w.input.value` — **config wins** — and then writes
  the resolved date into the field. So guarding the prefill alone would have
  left the picker re-filling every "blank" input anyway. It is removed rather
  than guarded, because flatpickr already falls back to the input's own value:
  the option was pure redundancy the whole time. `tests/test_fieldops_s9.py`
  asserts it stays gone.
- **The whole bug was client-side, which is why S1's tests never caught it.**
  `test_no_schedule_behaves_as_before` (S1) posts an empty `scheduled_for` and
  asserts NULL — and passed throughout, because the server was always right.
  Nothing rendered the page and looked at it. The new tests are therefore
  render- and source-level on purpose: they assert the guard exists, that the
  prefill precedes the flatpickr call, and which fields carry the attribute.
- **Verified in a browser, not only in tests** — the point being that this bug
  was invisible to the test suite by construction. Against a seeded tenant on
  `/tech/repairs/create/`: `repair_date` shows "August 25, 2026 - 7:19 PM" in
  the visible box while `scheduled_for` is blank in both the real input and the
  visible box, on one page, from one widget class. Also walked Drake's actual
  motion on `/tech/jobs/new/` (uncheck "Job is already done" → the revealed
  field is empty under the label that promises exactly that).
- **Merge order:** this session's branch was cut from `main`, so it does not
  contain the S9 block it is documented in. **Merge the docs PR first**, or
  these Notes and the code land in the wrong order — the same
  branch-cut-before-its-dependency trap S8 hit and this document already warns
  about.
- Suite: 351 tests green (S9's 11 plus `test_fieldops_s1/s3/s4/s5/s7/s8`,
  `test_job_form_parity`, `test_unified_job_create`, `test_quick_job_invoice`,
  `test_mobile_touch_targets`, `test_view_transitions`, smoke set). No new
  Tailwind classes — `app.css` rebuilds byte-identical. No migration.
- **Watch for in S10–S12:** any dynamically inserted `datetime-local` will now
  get flatpickr but **no** default, which is correct — and is also why S11
  specifies `type="time"` / `type="date"` for the inline editor instead: a node
  inserted after `DOMContentLoaded` never gets a picker at all, because this
  block runs exactly once.


## S10 · Quick-add a job from the schedule — BUILT 2026-08-25

| Field | Value |
|---|---|
| **Goal** | A customer calls; from `/tech/schedule/` one button opens a modal that takes who + what + when and **creates and books the job in one submit**, without leaving the page. |
| **Size** | M (1–2d) |
| **Depends on** | S9 (so "no time" means no time). Nothing else. Runs on today's layout — it does **not** wait for S12. |
| **Why it matters** | This is the session Drake asked for. The current path is seven steps and ends on the wrong screen (`job_create` → `_job_detail_redirect`, `views/jobs.py:280-283`), which is why a note in a phone was winning. |
| **Verified current state** *(2026-08-25)* | `job_create` (`views/jobs.py:383-629`) is a ~250-line view holding its business logic **inline**: plan limits (`UsageService`), customer resolution incl. `find_individual_matches` / `create_individual` and the duplicate-confirm guard, `_resolve_technician_for_create`, the `no_tax` decision, Repair/Replacement construction, extra charges, invoicing. `QuickJobForm` (`forms.py:892`) already supports an existing customer **or** a new individual on the fly (`new_customer_name` / `_phone` / `_email` + `confirmed_new_customer`), and its `__init__` tenant-scopes the `customer` and `technician` querysets. A customer typeahead endpoint already exists: `/tech/api/customers/search/` (`views/customers.py:1003`), used by `job_form.html:46`. `confirm_appointment` (`schedule_booking.py:196`) already books a time correctly, `expected=None` meaning "currently unscheduled". |
| **Build — 1. Extract, don't duplicate** | New `apps/technician_portal/services/quick_job.py`: `allowed_service_types(tenant)` (one definition of the `offers_*` filter), `QuickJobError(message, *, status, suggestions)`, and `create_job(*, tenant, actor_user, data, charges=None, already_completed=False)` covering everything between "resolve the customer" and `service.save()`. `job_create` is refactored to call it and translate `QuickJobError` back into `messages.warning` + redirect / the duplicate-suggestion re-render. **This is the regression-risk half of the session** — a second copy of this logic is how auto-approve or tax silently diverges. |
| **Build — 2. The endpoint** | `POST /tech/schedule/quick-job/` → `views/schedule.py::quick_job`, name `schedule_quick_job`. JSON in / JSON out, `{'ok': bool, 'message'\|'error': str}` like its three siblings, in-body auth via `_resolve_viewer`, gated on `sees_whole_shop` (it books a time, and plain techs cannot even see REQUESTED work — CODE-081). Validation instantiates **`QuickJobForm`** from the JSON body rather than re-deriving the rules; `scheduled_for` never goes through the form — the modal's date/window go around it. |
| **Build — 3. Two writes, one transaction** | `create_job(...)` — a **normal `save()`**, because pricing, `TaxService` and `resolve_initial_shop_status` (auto-approve) all run there and must not be bypassed — then `confirm_appointment(..., expected=None, notify=True)` for the time. The job is created unscheduled and immediately booked, so there stays exactly one answer to "how does a time get onto a job" and `scheduled_window_end` is populated like every other booked job. Set `service._skip_assignment_notifications = True` on create and let the booking send the single message. |
| **Build — 4. The modal** | `templates/technician_portal/includes/quick_job_modal.html`, opened by a `+ Add job` button in the day header through the house `data-modal-open` contract (`static/js/ui.js`) — no new modal machinery. Customer field reuses the existing search endpoint with `job_form.html`'s debounce pattern. Date/window controls are copied from the triage rail's inline form so the page has **one** vocabulary for "when". Defaults to the day on screen. Duplicate suggestions render inline as buttons: pick one to reuse that customer, or "different person" to set `confirmed_new_customer` and resubmit. |
| **Build — 5. Fold in the REQUESTED fix** | Add `'REQUESTED'` to `DAY_STATUSES` (§0 finding 3). Quick-add makes that bug reachable in one click, so it stops being latent here. |
| **Response** | Returns a server-rendered `row_html` from `includes/schedule_row.html` (same context keys the day view supplies: `can_book`, `can_assign`, `roster`, `preferred_windows`, `booking_default_date`, `shop_service_mix`) so the page inserts a real row with no reload and **no second copy of the partial in JS** — S7's Notes are explicit that two renderers of one row is how the rail bug happened. When the booked day is not the day on screen, return `day.on_screen: false` and say which day it landed on instead of inserting. |
| **Acceptance criteria** | From `/tech/schedule/`, an owner adds a brand-new individual and books them for tomorrow morning in one submit, and the row appears without a reload. The job is priced **identically** to one made through `/tech/jobs/new/` — asserted field-by-field on `cost`, `tax_amount` and `queue_status` against a form-created twin. A plan-limited tenant is refused as JSON with the usual upgrade copy. A duplicate name returns suggestions; a confirmed retry creates the second person. A read-only tenant's POST is caught by the content-type check, not a parse error. A non-manager is refused. |
| **Tests** | New `tests/test_fieldops_s10.py`. **Plus, against a `main` baseline, the suites that guard the extracted logic:** `tests.test_unified_job_create`, `tests.test_job_form_parity`, `tests.test_quick_job_invoice`, `tests.test_auto_approve_shop_created`. Wrap POSTs in `captureOnCommitCallbacks` or the notification path silently does not run and the test passes anyway (S7's trap). |
| **Deliberately not done** | Completing or invoicing from the modal (`job_create` keeps `send_and_invoice`). Photos, insurance, extra charges — the modal is who/what/when; everything else is the ticket's job. Editing an existing job from the modal. |

**Notes** *(2026-08-25)*

- **What shipped matches the spec.** `services/quick_job.py` holds
  `allowed_service_types`, `shop_tax_state`, `resolve_technician`,
  `resolve_customer`, `build_job`, `save_extra_charges` and `create_job`;
  `job_create` is a caller that translates `QuickJobError` back into
  `messages` + redirect or the duplicate re-render. `POST
  /tech/schedule/quick-job/` + `includes/quick_job_modal.html` +
  `static/js/schedule_quick_add.js`.
- **`_save_extra_charges` could not just move.** It has four callers outside
  `views/jobs.py` (`views/repairs.py` twice, `apps/saas/views.py` twice) that
  import it by name. It keeps its name and delegates to the service, because
  the entire point of the extraction was to not have two copies.
  `_resolve_technician_for_create` had no other callers and is gone.
- **The extraction is the risk, so it is asserted directly.**
  `test_priced_identically_to_the_form` creates the same job through
  `/tech/jobs/new/` and through the endpoint and compares `cost`,
  `tax_amount`, `tax_rate`, `queue_status`, `no_tax` and `technician_id`
  field-by-field. If a future session changes one path, that test fails rather
  than the shop discovering it on an invoice.
- **The REQUESTED bug reversed an existing S3 test, and that was correct.**
  `test_requested_jobs_never_on_the_sheet` used a fixture with
  `status='REQUESTED'` **and** `scheduled=local_day_at(11)` — the exact
  vanishing case. Its comment justified itself with "a customer request holds
  … even a wished-for time", which was a pre-S4 belief: S4 moved the wish to
  `preferred_date`/`preferred_window` and the customer portal never writes
  `scheduled_for`. So that state can only mean somebody in the shop booked it.
  The test is now split — `test_unscheduled_requested_jobs_are_not_on_the_sheet`
  keeps S3's real rule, and `test_requested_job_with_a_booked_time_IS_on_the_sheet`
  encodes the new one.
- **Browser-verified, and it caught a defect the tests could not.** Added a
  customer who did not exist onto an empty day (landed 8:00 AM–12:00 PM), then
  a second for an existing fleet account (1:00–2:30 PM) — inserted in time
  order with **no page reload**, proven by a marker set on `window` surviving.
  The defect: the service-type buttons only got their selected styling on
  click, so a freshly opened modal showed neither chosen while a repair was
  what would be submitted. The selected classes now live in the markup.
- **One deliberate fallback:** on an *empty* day there is no
  `[data-swap-group]` container to insert into (the page is showing its empty
  state), so the JS falls back to `UI.flash()` + reload. S12 removes the need
  for it by giving the day a list container even when empty.
- **Known thin spot for multi-tech shops:** the assignment notification is
  suppressed (`notify_assignment=False`) so one motion sends one message, and
  the booking notification carries the news. For a shop where the creator is
  not the assignee, that message names the time but does not say "this is
  yours". **S14 fixes it** by threading `when=` into
  `notify_assignment_change`, which `apply_dispatch` already does.
- Suite: 63 targeted tests green (S10's 16, S3, `test_unified_job_create`,
  `test_job_form_parity`), plus S1/S4/S5/S7/S8, `test_quick_job_invoice`,
  `test_auto_approve_shop_created`, the UI guards and the smoke set. No
  migration. `app.css` rebuilt (new modal classes) and committed.


## S11 · The move primitive + inline time/date edit — TODO

| Field | Value |
|---|---|
| **Goal** | A booked job's time can be changed to **any** time, on **any** day, from the schedule — without `save()`, without trading against another job, and without the full edit form. |
| **Size** | M (1–2d) |
| **Depends on** | S9. Independent of S10. |
| **Why it matters** | §0 finding 1: there is no reschedule path in the product at all. This is the missing primitive that S12's drag, S14's cross-tech drop, and any future customer-facing rescheduling all sit on. |
| **Design decision — a new service, not a fourth mode on `confirm_appointment`** | `confirm_appointment`'s contract is *(date, window) → bucket bounds*, its `expected` default means "this job is unscheduled", and its notification lead is "a job on your schedule now has a time". A move is *(exact instant) → keep-own-duration* on a job that already holds a time. Bolting a `start_at` mode on gives one function four modes with two mutually exclusive parameter sets. `dispatch.py` set the precedent by **composing** `assign_job` + `confirm_appointment` rather than absorbing them. |
| **Build — the service** | New `apps/technician_portal/services/schedule_move.py`: `parse_move_request(payload)`, `MoveError(message, *, status)`, and `@transaction.atomic move_appointment(*, tenant, service_type, pk, day, start_time, end_time=None, expected, actor_user=None, notify=True)`. Promote `schedule_swap._shifted_end` (`:98`) to a public `shifted_end(job, new_start)` here and import it back into `schedule_swap` — **one** definition of "keep your own duration", already covered by S7's tests. Reuse `BOOKABLE_STATUSES`, `NOMINAL_JOB_LENGTH`, `window_bounds()` and the `_batch_siblings` pattern from `schedule_booking`. |
| **Wall clock, not an ISO instant** | The client sends `date` + `time` in the shop's wall clock; the server combines them with `timezone.get_current_timezone()`, same convention as `window_bounds` and the day view's day boundaries. There is no per-tenant timezone (`models.py:387`), so a browser in another zone computing `toISOString()` would book the wrong hour silently. `expected` stays a full ISO instant **because it is server-produced** (`{{ job.scheduled_for\|date:'c' }}`). |
| **Duration rules** | had start + end → `shifted_end`; had start, end NULL → **stays NULL** (S7's rule, unchanged); came from the Unscheduled list → `new_start + NOMINAL_JOB_LENGTH`; client sent an explicit `end_time` → `window_bounds(day, 'EXACT', start_time, end_time)[1]`, which reuses S4's `end <= start` typo guard in `_parse_clock_pair`. Note in the docstring, as `schedule_conflicts` does, that `NOMINAL_JOB_LENGTH` is a placeholder, not a measurement. |
| **Batches move whole** | S4's rule, not S7's refusal. S7 refused batches because a *swap* between N rows and one is arithmetic with no answer; a move has an answer — every row of the visit takes the same new start, each keeping its own duration. Every sibling must hold `expected` too, so a batch half-moved by someone else refuses rather than splitting (verbatim `confirm_appointment`'s loop). `schedule_row.html` gains `data-batch-id`. |
| **No cross-day or cross-tech guard** | Pushing a job to Friday **is** the motion. The service never touches `technician` — a cross-tech drop is a *dispatch* (S14). |
| **Refusal table** | unparseable / naive `expected` → **409** "Reload the schedule and try again."  ·  row gone or other tenant → **404** "That job is no longer here."  ·  row count ≠ 1, or any sibling drifted → **409** "This job's time changed while you were looking at it."  ·  status left `BOOKABLE_STATUSES` (pre-checked under the lock, for a specific sentence) → **400** "Only open jobs can be moved — that one is completed."  ·  no tenant → **403**. `expected` is folded into the `.update()` `WHERE` alongside `tenant` and `queue_status__in`; row-count **is** the optimistic lock. |
| **Build — the endpoint** | `POST /tech/schedule/move/` → `views/schedule.py::move_appointment_view`, name `schedule_move`. Same JSON shape as its siblings, in-body auth via `_resolve_viewer`, `sees_whole_shop` required. Return the moved row's new time **and** freshly computed `day.conflicts` / `day.load` (`annotate_conflicts` + `technician_load` over the affected tech's day) — that is what lets S12 repaint every row's conflict chip and the capacity chip without a reload. |
| **Build — first consumer is deliberately NOT drag** | The time block on a booked row becomes a real control that edits in place: `<input type="time">` for the start, an optional end, **and a `<input type="date">`** so moving a job straight onto another day is one control rather than a round trip through an unscheduled limbo (Drake's call, 2026-08-25). Enter or blur commits, Escape cancels. This proves the write path with a UI that is keyboard-reachable and fully testable **before** S12 moves the layout underneath it. **Use `type="time"` / `type="date"`, never `datetime-local`** — a dynamically inserted `datetime-local` never gets flatpickr (the base script runs once on `DOMContentLoaded`) and, until S9, would inherit the prefill bug. |
| **Notifications** | Two siblings in `services/assignments.py` — `notify_appointment_moved(job, previous_start, *, job_count=1, actor_user=None)` and, if/when unscheduling is exposed, `notify_appointment_cleared(...)`. Both reuse the existing `job_rescheduled` template (category `assignment`, priority MEDIUM) with a different lead: **no new template, no migration, no new preference field.** Keep `notify_appointment_set`'s guards — skip when the actor is the assigned tech, skip outside `NOTIFIABLE_STATUSES`, and remember `TechnicianNotification.repair` is NULL for a replacement. Fire on `transaction.on_commit`. |
| **Tests** | New `tests/test_fieldops_s11.py`, mirroring `tests/test_fieldops_s7.py` — including its two habits: the **money guard** (put both jobs on a live invoice; assert `cost`, `tax_amount` and invoice totals identical before and after) and `captureOnCommitCallbacks` around every POST. Cover: arbitrary time same day; a different day; window duration preserved; NULL end stays NULL; explicit `end_time`; a batch moves whole; a batch with one drifted sibling refuses; stale `expected` → 409; COMPLETED → 400; other tenant → 404; non-manager → 403 as JSON. |
| **Deliberately not done** | Drag (S12). Cross-technician moves (S14). Insert-and-cascade reordering. Customer-facing "your time moved" notices — a product decision, not a side effect (S4's rule). An `unschedule` gesture in the UI: Drake's answer was **"straight onto another day"**, no limbo. Build `unschedule_appointment` in the service if it falls out for free, but do not surface it. |
| **Notes** | *(fill in when done)* |

## S12 · The ordered day list + drag to move — TODO

| Field | Value |
|---|---|
| **Goal** | The schedule becomes one ordered day list you can drag; **both** gestures — move and swap — show what they are about to do before they do it, and what they did after. |
| **Size** | L (3–5d) |
| **Depends on** | S11 (the move endpoint). S10 is not a hard dependency but ships the `+ Add job` button this layout wants. |
| **Why it matters** | §0 finding 2. The reported bug — *"the swap feature doesn't even swap them on the UI"* — is not in `schedule_swap.py`, which is correct and well tested. It is that the page reloads to confirm, so success and every flavour of refusal look identical. |
| **Layout** | One day, one ordered list: `⠿  8:00a  Jones — Furnace  ✎`. The `Unscheduled (N)` collapsible drawer moves to the **bottom** (today's amber "Needs scheduling" rail is above the day; the backlog belongs below it). With a one-person roster the list is flat, no technician header. With more than one tech it groups under technician headers exactly as today, keeping `data-swap-group` scoping, the S8 hours chip and the capacity chip — see **Appendix C** before simplifying anything away. |
| **Two gestures, visually distinct — this is how swap survives and gets better** | **Drop *between* two rows = move** (S11's endpoint): an insertion caret appears between the rows and prints the time it will land on — `→ 10:30 AM`. **Drop *onto* a row = swap** (S7's endpoint, unchanged): the whole target row highlights instead, and the caption names whose times trade. Caret-vs-highlight is what makes two gestures on one list guessable, and both now get the same feedback model. **Drake's call, 2026-08-25: keep swap, improve it.** |
| **The drop rule** *(Drake's choice: slot into the gap, keep its length)* | With `prev`/`next` the neighbouring rows, `end_of(r) = r.scheduled_window_end \|\| r.scheduled_for + 1h`, and `own` = the dragged job's own duration: **(1)** between two rows → `end_of(prev)` — butt up against the job above; **(2)** at the top → `next.scheduled_for − own` — finish when the next one starts, with no clamp to opening hours (this app flags, it never blocks, and `describe_outside_hours` will say so); **(3)** at the bottom → `end_of(prev)`, unbounded; **(4)** empty day → the tech's declared start (`working_hours.hours_on`), else 08:00 local. |
| **…then clamp, then snap** | The server re-sorts by `(scheduled_for, pk)`, so the result must land **strictly between the neighbours' starts** or the row renders somewhere other than where it was dropped: `new_start = snap5(clamp(preferred, prev.start + 1min, next.start − 1min))`, skipping the 5-minute snap when the window is narrower than that. **No cascade** — nothing below moves; rewriting times the shop already promised customers is what S7 ruled out and nothing has changed. If `upper < lower` (two neighbours booked within a minute of each other) **refuse in the browser with the reason** — *"Those two are at the same time; there's no room between them. Set a time on this job instead."* — and open S11's inline editor on the dragged row. The one unsolvable geometry becomes a next action. |
| **Where the arithmetic lives** | **The client computes the time; the server writes what it is told.** `move_appointment` stays a pure primitive with no knowledge of neighbours — same shape as `confirm_appointment`, and independently testable. A stale neighbour can at worst produce a slightly-off time, which the reconcile step then states truthfully in the toast; `expected` still guards the moved row. Accept that trade rather than making the primitive impure for a rounding error. |
| **Use the house helpers, don't hand-roll** *(added 2026-08-25)* | `main` gained `static/js/optimistic.js` and `static/js/list-loading.js` with UI\_MAGIC S11 (PR #210) **after** this session was specced, and `CLAUDE.md` now documents both. Optimistic rows opt in with `data-optimistic-row="<type>-<id>"` (prefix the type — a repair and a replacement share ids), repaint their pill through `{% status_badge … optimistic=True %}`, and roll back via `Optimistic.rollback`, which restores saved `innerHTML` — **so a row's handlers must be inline `onclick` attributes, not `addEventListener` bindings**, or they die on rollback. List skeletons are traced, never authored: add `data-skeleton-list` to the row container on **both** breakpoint twins. Read that section of `CLAUDE.md` before writing the snapshot/revert code below; it may already be written. |
| **Build — the feedback model** | New `static/js/schedule_move.js` (plain IIFE, `'use strict'`, event delegation, `window.UI` only — **`ui.js` is not modified**; S7 already established that an Undo toast means an interactive control inside an `aria-live` region). **(a) Show the target before the drop** — the caret prints the landing time, and turns red printing the reason when the drop is refused. This is the single biggest cure for "did anything happen?", because the answer is visible *before* the commit. **(b) `refuse()` runs on every dragover and again on drop**, so a near-miss gets a sentence instead of today's silence; a refused drop animates the row back over ~150ms so the refusal is *seen*, not just read. **(c) Optimistic move, then reconcile** — snapshot `{parent, nextSibling, timeHTML, dataset}`, move the node, mark `.schedule-row-pending`, POST; on success repaint the row's time from the response and **rewrite `data-scheduled-for`** (this is what keeps the next drag's `expected` honest), then repaint every row's conflict chips and the header capacity chip from `day.conflicts` / `day.load`. **No reload.** **(d) On refusal** restore from the snapshot and toast. **(e) On 409** restore, then `UI.confirm({title: "The schedule changed", confirmLabel: "Reload"})` — a 409 gets an *action* without touching shared `ui.js`. |
| **Two carried-over defects to fix while here** | The in-flight guard becomes a **`Set` of job keys**, not the module-level `busy` flag that `schedule_swap.js` and `schedule_dispatch.js` both use — that one blocks a second quick drag on an unrelated row. And keep the **content-type check before `res.ok`**, verbatim (`schedule_swap.js:113-120`). |
| **Progressive enhancement** | Nothing is drag-only. The time block stays S11's real control, so a JS failure degrades to inline editing rather than dead-ending. Handles stay visible (reveal-on-hover does not exist on a tablet) and 44px. |
| **Tailwind** | `.schedule-row-pending`, the caret classes and any class composed in JS must be added to `safelist` in `tailwind.config.js` — the existing `swap-row-*` entries are the precedent — then `./scripts/build_css.sh` and **commit `static/css/app.css`**. |
| **Acceptance criteria** | Dragging a job between two others lands it at the time the caret promised, with the list already in the right order and no reload. Dragging one row **onto** another trades their times **on screen**. A refused drop puts the row back where it started and says why. A near-miss says why. A 409 offers a reload. Conflict chips and the capacity chip are correct afterwards without a refresh. The whole thing works with a finger, and the page still scrolls. |
| **Tests** | New `tests/test_fieldops_s12.py` for the server-visible half (row markup carries `data-batch-id` / `data-window-end`; the day view renders the drawer at the bottom; a one-tech roster renders no technician header). The drop arithmetic is client-side — keep it in one pure function and, if a JS test harness still does not exist, **write the rule's table of cases into this block's Notes and assert them by hand in step 8 of the verification recipe.** `tests.test_mobile_touch_targets` and `tests.test_view_transitions` must stay green. |
| **Decision needed from Drake during this session** | With move, swap, book and dispatch all writing `scheduled_for`, the only audit trail is still S7's log line. **Build a `ScheduleChange` row (actor, job, old, new) now, or carry the debt one more session?** S7's Notes name exactly this moment as the right one to decide. |
| **Deliberately not done** | Insert-and-cascade. A week or month grid — Drake picked the ordered list on purpose. Multi-day jobs. Capacity planning. Replacing `NOMINAL_JOB_LENGTH` with a real duration model. |
| **Notes** | *(fill in when done)* |

## S13 · Schedule on the dashboard — TODO

| Field | Value |
|---|---|
| **Goal** | The owner's dashboard shows what is on deck today and tomorrow, and can take a phone call without navigating first. |
| **Size** | S (½d) |
| **Depends on** | Nothing hard. Reads better after S10 (so it can carry the `+ Add job` button) but can be pulled forward at any time. |
| **Verified current state** *(2026-08-25)* | `grep -n "schedule" templates/saas/owner_dashboard.html` returns **zero hits** — the owner dashboard has no schedule widget and not even a link; the only route in is the navbar (`base_app.html:76`, mobile `:203`). The *technician* dashboard already does this well: "Today's Queue" buckets rows by `job.schedule_bucket` and its "Today" header links to `day_schedule` (`templates/technician_portal/dashboard.html:76-79`, `:126-128`). |
| **Build** | A Today / Tomorrow card on `owner_dashboard.html`, reusing `includes/schedule_row.html` and the **existing** bucket logic at `views/dashboard.py:363-392` (`overdue` / `today` / `later` / `unscheduled`) rather than writing a third query. Include S10's `+ Add job` button. Empty state says what *is* waiting (`N unscheduled jobs could use a time`), the way `schedule.html:200-217` already does — not just what isn't. |
| **Tests** | New `tests/test_fieldops_s13.py`: the card renders for an owner, buckets correctly across an overdue / today / tomorrow fixture, and is tenant-scoped. |
| **Deliberately not done** | A second copy of the day view. Anything writable beyond the quick-add button — the dashboard shows and launches; the schedule page edits. |
| **Notes** | *(fill in when done)* |

## S14 · Multi-technician moves — TODO

| Field | Value |
|---|---|
| **Goal** | On a multi-tech board, dragging a job into **another technician's** list assigns *and* books it in one atomic write with one notification. |
| **Size** | M (1–2d) |
| **Depends on** | S11 (the primitive) and S12 (the layout). **Last on purpose** — it generalises a motion that should be proven single-tech first. |
| **Why it is in the queue at all** | Drake is currently the only tech, so none of this pays off for him today. It is here because **the shops signing up after him are not one-tech shops**, and because S12's layout work is exactly where a single-tech simplification would quietly delete the multi-tech affordances. See **Appendix C**. |
| **Build** | Teach `parse_dispatch_request` / `apply_dispatch` (`services/dispatch.py`) to accept `date` + `time` and delegate the booking half to `move_appointment` instead of `confirm_appointment`, so a cross-list drop is one `transaction.atomic` assign-and-move emitting a single `notify_assignment_change(..., when=...)` — the pattern `apply_dispatch` already uses — rather than an assignment message followed by a booking message. Gate on `can_assign_work`, which is **strictly narrower** than `is_manager` (`views/schedule.py:74`): a manager who may schedule but not reassign gets the move, not the dispatch, and the refusal sentence already exists ("You can schedule work but not reassign it."). |
| **Also closes** | S10's known thin spot: a quick-added job assigned to someone else announces itself only through the booking sentence. Threading `when=` through `notify_assignment_change` fixes both callers at once. |
| **Tests** | New `tests/test_fieldops_s14.py`: cross-tech drop assigns and books atomically; exactly one notification; `can_assign_work=False` is refused as JSON while a same-tech move still succeeds; the optimistic lock on `expected_technician_id` still 409s. |
| **Deliberately not done** | Auto-assignment by capacity. Route optimisation (S6). Per-tech working-hours enforcement — S8 flags, it does not block, and that stays true. |
| **Notes** | *(fill in when done)* |

---

# Phase P — Parts (added 2026-08-12 from the sourcing investigation — full findings in Appendix B)

The one-sentence version: **live Mygrant quotes and ordering are real and buildable now** (Mygrant publishes a SOAP web-service API, keyed on the NAGS numbers techs already type, authenticated with the shop's own Mygrant account); **an in-app vehicle→NAGS part lookup is the gated, expensive half** (NAGS data only comes via a negotiated Mitchell license at roughly $60–75/NAGS-user/month market rate, and Mitchell doesn't even provide the VIN→part mapping). P1 deliberately does not depend on P2.

## P1 · Mygrant live quotes + ordering — IN PROGRESS (steps 3+4 built 2026-08-14, PR #184; steps 1–2 on the Mygrant IT callback)

**P1 order of work** *(updated 2026-08-14 — do these in order; 1–3 need no code and can overlap the callback wait)*:
1. **API onboarding** — voicemail left with Mygrant IT dept 2026-08-14 (never returned); Owen at the Little Rock branch supplied the IT support director's email 2026-08-17 and the written request went out the same day. **Waiting until ~2026-08-24 before escalating.** The escalation is *not* another IT approach — it is back through Owen / the shop's sales rep, who is who the spec routes onboarding through ("API Integration Set Up Form"), and who has a reason to want the account ordering more. Drake is the **account owner** on `C027180-001` (his dad only uses it), so no third-party authorization is in the way — the delay is purely that a cold request to a distributor's IT dept has no SLA behind it. Done when Generate Key appears in Edit User Settings and a key is generated.
2. **On that same call: confirm the billing model** — which lookups bill (~$1/search per Drake): part-number, VIN, make/model — and whether API Inquiries bill the same. This decides how aggressive the quote UX can be.
3. ~~**Decide credential encryption at rest**~~ **DONE 2026-08-14 (PR #184)** — Fernet via `cryptography`, key from `FIELD_ENCRYPTION_KEY` (separate from `SECRET_KEY`; rotating Django's signing key can't brick stored credentials). `common/encryption.py` (+`EncryptedTextField`) is now THE codebase mechanism for tenant secrets. No production fallback — **deploy needs a one-time `eb setenv FIELD_ENCRYPTION_KEY=<Fernet key>`** (recipe in CLAUDE.md); dev/tests derive a key from `SECRET_KEY` automatically. Rationale recorded in the module docstring.
4. ~~**Connect plumbing**~~ **DONE 2026-08-14 (PR #184)** — `MygrantConfig` (`technician_portal/0052`, TenantConfig pattern, per-tenant only), owner Settings → new **Parts tab** with the Connect card (secrets never echoed back; disconnect deletes them; admin registration is status-only so secrets can never render), and an AJAX **Test connection** that fires one staging Inquiry (`EnvironmentID=TEST`, spec sample part DW 01658 — never prod, never an order, so it can't trigger per-search billing). `mygrant_service.py` holds the hand-built `InboundTraffic` envelope. 20 tests in `tests/test_mygrant_connect.py`.
5. ~~**Quote-only PR**~~ **BUILT 2026-08-15 (PR #186)** — Get Mygrant Quote button on the Replacement detail (`replacement_detail`), SKU table with My Price/list/stock/branch/truck-run, one-tap "Use as parts cost" (server-cached prices — one billable search per quote, client can't forge a price), profit-on-this-job line in the Pricing card (amber shop-only). Item-level Mygrant errors render on the row. "Staging first" = `manage.py mygrant_quote --tenant <id> --nags DW01658 --staging` the day the key arrives; prod runs prompt before a billable search. 21 tests in `tests/test_mygrant_quotes.py`. **Dark until steps 1–2 complete** — the whole card is gated on `is_enabled()` (credentials + API key).
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
| **Considerations** | **"Connect your Mygrant account" is the multi-shop answer** — credentials are per-tenant, never the platform's: a `MygrantConfig` inheriting `TenantConfig` (`common/models.py:16` mandates the pattern; `ReviewConfig` is the closest template — off-by-default integration config with `get_for_tenant()`), holding CustomerID `C######-###`, WebUserID, password, API key, entered in an owner Settings card with a **Test connection** button (one staging Inquiry). Mygrant has no OAuth, so "connect" = credential entry + validated ping — the same shop-credential model GlassBiller/Omega/GlasPacLX use; no vendor certification exists or is needed. Gate shape mirrors Stripe Connect (`apps/tenants/services/connect_service.py` `is_enabled()`): a tenant without credentials sees nothing new anywhere, and no platform-wide credential path exists at all. **Encryption at rest is an unmade decision, not a reuse**: nothing in this codebase stores a third-party secret today (no Fernet/KMS precedent anywhere) — decide the mechanism before building. **Per-shop onboarding is table stakes, but it must not be the vendor's phone call.** Every competitor POS (GlassBiller, Omega, GlasPacLX, Elmo, eDirectGlass — B.3) has the shop enter its own Mygrant credentials, so the friction is the category's, not ours, and `is_enabled()` already keeps it off signup/trial/every other feature. What does not scale is RS Systems chasing onboarding per shop: a cold vendor request to Mygrant IT sat unanswered for days (2026-08-14 voicemail, 2026-08-17 email), whereas a shop asking *its own CSR* — someone it talks to weekly about orders and credit — is a routine request from a paying customer. So the Connect card must hand the shop the script and let the shop make the call (built 2026-08-18: "Don't have an API key yet?" panel, open until a key is saved). **Open question for the first Mygrant call that connects: does Mygrant have an integrator/partner listing for POS vendors?** If RS Systems is a name their reps recognize, every future shop's request becomes a form the rep has already filled out — that is worth more than our own key, and only Drake can ask it. **Cost per lookup (Drake, 2026-08-14): searches on the account bill ~$1 each** — so quotes must be a deliberate button-press (never auto-fire on page load or refresh), one Inquiry's multi-SKU response is cached and reused for the pick step, and the UI says a quote may incur a supplier charge; confirm the exact billing model (which search types, and whether API Inquiries bill the same) on the rep call. The order's per-line **PO field should carry the RS Systems job/invoice number** — Mygrant's order history is searchable by PO, which makes reconciliation two-sided for free. The API is one SOAP operation (`InboundTraffic`, string-in/string-out CDATA XML) — hand-built envelope over `requests`, no SOAP library needed. An Inquiry on bare NAGS prefix+number returns *multiple* concrete SKUs (brands, moldings, sensors) with `QtyAvailable`, `ListUnitPrice`, `CustomerUnitPrice`, branch and truck-run — orders require an exact SKU ("Only exact orders will be placed"), so the UI flow is quote → pick SKU → order. Rich item-level error codes (`NoStock`, `ChooseSubstitute`, `OverCreditLimit`, `NoTruckRoute`, surcharge cases) must surface honestly, not be swallowed. Returns are NOT in the API yet ("Coming Soon") — don't promise them. API terms: no redistributing/reselling API data (shop's own prices shown to the shop is fine; don't leak `CustomerUnitPrice` into anything customer-facing), no scraping the website (site ToS separately prohibits it — the API is the only sanctioned route), rate limits at Mygrant's discretion, license revocable. |
| **Decisions needed** | Quote-only first PR vs. quote+order in one session (recommend: ship quote-only first — it's the daily win and de-risks the credential plumbing). Whether a successful quote should offer to fill `parts_cost` (recommend: yes, one tap, never silent). Encryption-at-rest mechanism for tenant credentials (first in the codebase — e.g. Fernet with an env-derived key vs. AWS KMS). Where profit-on-ticket renders (job detail vs. invoice editor) — shop-facing only, never customer-facing. |
| **Acceptance criteria** | Tenant with credentials configured: quote button on the Replacement form/detail returns live SKUs with prices/availability against staging first, then prod. Tenant without credentials sees nothing new. Order path (if in scope) writes the Mygrant order number (`DRLineNo` S-number) onto the job and handles every documented error code with a human message. No Mygrant price ever appears in customer-facing surfaces. |
| **Out of scope** | Vehicle→NAGS lookup (P2). Other suppliers (Pilkington/PGW use the same per-shop-credential pattern — add later behind the same abstraction if a shop asks). Returns. Insurance EDI/Glaxis. |

**Notes** *(fill in after the session)*

- **2026-08-14 (steps 3+4, PR #184 — `feat/mygrant-connect`)**: built while waiting on the Mygrant IT callback. Encryption decision + Connect plumbing shipped exactly as designed above; nothing needed the API key to build, and the card degrades honestly at every gate (no platform key → "not available yet"; no credentials → nothing anywhere; credentials but no API key → save works, Test connection explains the key comes after onboarding). Two things future steps should know: **(a)** Test connection uses the *stored* credentials, not unsaved form edits — save first, then test (the card's flow makes this natural); **(b)** the quote/order gate for step 5 is `MygrantConfig.is_enabled()` (credentials + API key), already defined, so the quote PR only adds UI + the Inquiry-parse beyond what `mygrant_service.py` has. Deploy checklist for whichever PR merges first: generate + `eb setenv FIELD_ENCRYPTION_KEY` (one-time; recipe in CLAUDE.md env-var block).
- **2026-08-15 (steps 3+4 merged + deployed; step 5 built, PR #186 — `feat/mygrant-quotes`)**: PRs #184/#183 merged and `eb deploy` verified (health 200). `FIELD_ENCRYPTION_KEY` was NOT yet set at deploy time — the sandbox couldn't run `eb setenv` with a secret, so Drake runs the one-liner from CLAUDE.md; until then the Parts card shows its "not available yet" state, which was verified deliberate behavior. Step 5 learnings: the Replacement views live in `apps/saas/views.py` (not technician_portal); `Replacement.save()` recomputes cost+tax from `parts_cost` automatically UNLESS `cost_override` is set — the apply endpoint says so out loud instead of silently not moving the total; quote results cache under `mygrant_quote_<tenant>_<replacement>` for 15 min and the apply step reads prices only from that cache. When the API key arrives, the full first-quote sequence is: owner enters key in Settings → Parts → Test connection → `mygrant_quote --staging` → one confirmed `mygrant_quote` prod run → then techs use the button. Step 6 (ordering) should reuse the same cached-SKU pick so the order is exact-SKU by construction.
- **2026-08-15: `FIELD_ENCRYPTION_KEY` IS SET in prod** — Drake ran the `eb setenv` one-liner (config deploy completed 16:18 UTC, instance deployment successful). The encryption-at-rest gate is cleared: the Parts → Connect card is fully functional in production. Remaining blockers for a live quote are steps 1–2 only (Mygrant IT callback → API key + billing-model confirmation).

## P2 · Vehicle→NAGS part lookup — BACKLOG (blocked on a licensing decision)

Not a session yet — the blocker is a contract, not code. To show "2024 F-150 windshield = FW05678 @ $XXX list" inside RS Systems, the NAGS database must be licensed from Mitchell International (no public pricing; negotiated per-end-user-seat terms; competitors pass it through at ~$60–75/NAGS-user/month, with cheap non-NAGS tech seats). Mitchell provides **data only** — every licensee builds or buys its own VIN→part mapping, and data refreshes land every January/May/September. Interim options that need no Mitchell contract: keep typing NAGS numbers (a per-lookup web tool like AutoGlassMatch is ~$1/lookup for the shop), and P1 works today because Mygrant's API accepts the NAGS number as input. **2026-08-14: the Mygrant portal itself already has Search by Make/Model (`/pages/searchm.aspx`) and Search by VIN (`/pages/searchvin.aspx`) built in** — so the tech's vehicle→part step has a supplier-provided home today (per Drake, searches bill ~$1 each — same ballpark as AutoGlassMatch), which further weakens the case for a Mitchell contract until real multi-shop demand shows up. Decision for Drake: whether shop demand ever justifies opening the Mitchell conversation (contact via mitchell.com NAGS pages / 800-551-4012) — see Appendix B for the full landscape, legal constraints, and competitor pricing table.

---

## Where this document ends

> **Superseded 2026-08-25 — this section held for one day.** It was written
> when the last buildable session closed, and its own final test ("what would
> reopen this document rather than start a new one: anything that is still
> *the tech finding out where and when*") is what reopened it. Drake used the
> arc on a real customer call the next morning and it failed him on the
> surface, not in the services — see §0's *"Scheduling UX — what first real
> use found"* and sessions **S9–S14**. Everything below is still an accurate
> description of what S1–S8 delivered; only the sentence "the document no
> longer implies a next action of its own" is now false.
>
> **The lesson worth keeping:** every claim below was true, verified and
> deployed, and the arc still did not survive first contact with the motion it
> was built for. *Shipped and deployed is not the same as used.* Nobody had
> booked a real customer call through this product until 2026-08-25.

*(Written 2026-08-24, when the last buildable session closed. This section is
the wrap-up: what the arc delivers, what is left, and what would reopen it.)*

**The arc is complete.** A technician now finds out about a job the moment it
is assigned (N1), knows where to go and when (S1–S4), and a manager runs the
morning from one screen that knows who is working (S5, S7, S8). Read
end-to-end, the fourteen sessions in this document did one thing: they turned
a shop's day from something held in somebody's head into something the
software can show, without ever blocking the shop from overriding it. Every
scheduling signal in the product is informational by design — S5's conflicts,
S4's missed wishes, S8's hours — because a glass shop's exceptions are the
job, not an error state.

**All of it is deployed.** #197, #198, #200, #201 and #204 went to production
on 2026-08-24 (see "Deploy state" at the top). The document no longer implies a
next action of its own — what is left is gated on other people: a carrier, a
supplier, a licensing decision, and demand.

**What remains, and what unblocks it:**

| Item | Status | Gate |
|---|---|---|
| **N3** · Notification coverage audit | Done and deployed (PR #204, live 2026-08-24) | — |
| **N2** · Tech assignment texts | Parked | The toll-free number clearing registration — **version 4 submitted 2026-08-31, `REVIEWING`** (Appendix A). A carrier's clock, not ours — but check the *version* status, not the registration's: v3 sat DENIED for five days looking like it was still in review. |
| **P1** · Mygrant quotes + ordering | Steps 3–5 built and dark | Mygrant enabling API onboarding on `C027180-001`. Escalation path is in P1's Notes. |
| **P2** · Vehicle→NAGS lookup | Backlog | A licensing decision with Mitchell (Appendix B). |
| **S6** · Routing / ETA / PTO / self-service rescheduling | Backlog by decision | Demand. S3/S5/S8 exist now precisely so a shop can prove it. |
| **S9–S14** · The scheduling UX arc | **TODO, unblocked** *(added 2026-08-25)* | Nothing. This is the live queue. |

**What would reopen this document rather than start a new one:** anything that
is still *the tech finding out where and when*. Date-ranged time off, a
customer rescheduling themselves, ETA texts, route ordering — those are S6
items and they belong here. A calendar product, capacity planning, or
multi-day jobs would not be; they are a different premise, and this doc's
sizing (`S` ≈ half a day, `L` ≈ 3–5 days, one session one PR) would be lying
about them.

**If you are the next session here, read this first:** §0 is still accurate
and still the fastest way in. The five load-bearing modules the arc left
behind are `services/schedule_booking.py` (turn a wish into a booking),
`services/schedule_swap.py` (trade two times), `services/dispatch.py` (who and
when together), `services/schedule_conflicts.py` (everything the board says
out loud) and `services/working_hours.py` (who is working). None of them
blocks a write; all of them are called once per group from
`views/schedule.py`, never per row from a template. Keep both properties.

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
- **A schedule-only `save()` re-prices the job and rewrites the customer's invoice.** *(S7 exploration, 2026-08-17)* `Repair.save()` (`apps/technician_portal/models.py:918-1120`) re-runs `calculate_repair_cost()` for any non-COMPLETED job (`:1047-1061`), re-runs `TaxService` whenever `cost > 0` (`:1065-1080`), and calls `sync_lines_for_service()` (`:1116-1120`) — which rewrites line items on every live invoice and recalculates totals, inside a bare `except: pass` that hides it. `Replacement.save()` recomputes cost from parts+labor on every save (`:1755-1770`) and syncs too (`:1816-1821`). **`save(update_fields=[…])` does not help — the whole `save()` body still runs.** Anything that only moves a time must use a queryset `.update()` (and then owns the validation `save()` would have done). Applies to S4 and S5 as much as S7.
- **`select_for_update()` is a silent no-op in dev.** *(S7, 2026-08-17)* Dev runs SQLite, so lock-ordering and race tests pass green while proving nothing — even a missing `atomic()` won't raise. Any concurrency guard has to be exercised against Postgres or labelled as argued-not-tested.
- **An empty JSONField that nothing reads is not a foundation.** *(S8 exploration, 2026-08-19)* `Technician.working_hours` has existed since migration `0007` with `default=dict`, no schema, no validator, no writer and no reader outside a collapsed Django-admin fieldset — so every row in production holds `{}`. Its presence made "we sort of have availability" believable for a year. When it gets meaning, `{}` has to mean *undeclared* (available whenever, say nothing), never *unavailable*, or the first deploy flags every job in every shop.
- **The app's only "business hours" are compared in UTC.** *(S8 exploration, 2026-08-19)* `_adjust_to_business_hours` (`apps/technician_portal/review_service.py:319-332`) clamps `timezone.now() + delay` using `dt.hour` — the UTC hour of an aware datetime — against `ReviewConfig.business_hours_start/end` (defaults 9/19). In prod that is 04:00–14:00 America/Chicago, so review-request emails queue for roughly 4 AM local. Live today; fix belongs to the review system (N3's neighbourhood). Do not copy the helper: schedule work must localize before comparing.
- **`{% with %}` makes an optional email context key mandatory.** *(S8, 2026-08-24)* Django resolves filter arguments strictly inside `{% with %}`, so `{% with url=base_url|add:action_url %}` raises `VariableDoesNotExist` when `action_url` is absent — the whole email fails to render rather than losing a button. Nineteen notification templates do this. Everything else in these templates is written to the opposite convention (flat context, every optional key guarded by `{% if %}`), which is exactly why it is easy to miss. See N3.
- **A `gh pr list` "updated" column is not a merge date.** *(S8, 2026-08-24)* Reading it as one put a wrong deploy claim into this document (S5 recorded as merged 08-18 and live; it merged 08-24 and was still undeployed). `gh pr list` prints `updatedAt` by default. Use `git log --first-parent` for the real order and the EB version label for what is actually running — `--json mergedAt` if you want the date from `gh`.
- **A session's stated dependency applies when the branch is cut, not when the code is written.** *(S8, 2026-08-24)* S8's spec said "S5 must merge first"; its branch was cut from a `main` without S5, and the result was a half-session that shipped the fact with none of its consumers. Nothing in it was wrong and it still had to be finished twice.
- **A page reload is not feedback.** *(S9–S14 exploration, 2026-08-25)* `schedule_swap.js:130-140` confirms a successful swap with `UI.flash()` + `window.location.reload()`. That reads fine in a code review and is invisible in use: every refusal path — cross-tech, 409, a read-only tenant's HTML redirect, and a near-miss drop that lands between rows and toasts *nothing* — leaves the screen byte-identical to before the gesture. Drake's report was "the swap feature doesn't even swap them on the UI," and the service was correct the whole time. **If a direct-manipulation gesture can be refused, the refusal has to move something on screen.**
- **A write path the UI never exposes does not exist.** *(2026-08-25)* `confirm_appointment` has been able to set a booked job to an arbitrary new time since S4 — pass the current `scheduled_for` as `expected` and it just works. Nobody could reschedule anything for two months because no template rendered the control on a booked row (`schedule_row.html` gates the date/window form on `{% if triage %}`). Before building a new endpoint, check whether an existing service already does the job and is simply unreachable.
- **Full suite has ~90–105 pre-existing failures on main.** Compare against a fresh main baseline; never count absolute failures. Another session may share the working tree — print `git branch --show-current` with every run.

---

## Appendix A — SMS toll-free number status + activation checklist

Checked live 2026-08-31 (`aws pinpoint-sms-voice-v2`, us-east-1, account tier PRODUCTION):

| Number | Status | Registration |
|---|---|---|
| `+18663115189` (RS Systems) | **PENDING** | **`REVIEWING` — version 4 submitted 2026-08-31** (v1/v2/v3 all denied — see below) |
| `+18559394817` (Rockstar shop, older) | ACTIVE | COMPLETE |

Registration status is `REQUIRES_UPDATES` whenever the newest version is denied — that is the
flag meaning *"your move"*, not *"we are still looking"*. Check the **version**, not the
registration: v3 sat denied for five days while the registration looked merely unfinished.

| Version | Submitted | Outcome |
|---|---|---|
| 1 | 2026-08-07 | DENIED 08-11 — Unclear Opt-in Language |
| 2 | 2026-08-25 | DENIED in 3s — Missing required field (empty-draft trap) |
| 3 | 2026-08-25 | DENIED 08-26 — Unofficial Business Email + Pre-selected Opt-in |
| 4 | 2026-08-31 | `REVIEWING` |

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

### Version 3 — DENIED 2026-08-26

Screenshot taken from the live card on prod (INV-1017's public link, a number typed into the
field, **box checked**, the STOP/HELP + Program terms line in frame), and `optInDescription`
rewritten to lead with the first-party path and quote the card's own words (490/500 chars).
Version 1's shop-attested description is gone.

It came back after ~30 hours of human review with **two** reasons, both self-inflicted:

> **Unofficial Business Email** — *"The provided business email address must use an official
> company domain that matches your business name or website."*

`contactInfo.supportEmail` was `drake@rockstarwindshield.repair` — inherited by copy from the
*other*, approved registration (`registration-67ea31aa…`, Rockstar Windshield Repair), where
that domain legitimately matched its own website. Under company name **RS Systems** / website
**rssystems.io** it matches neither. The resubmit script now copies a base version *and asserts
the support email's domain equals `companyInfo.website`* before it will submit.

> **Pre-selected Opt-in** — *"Your opt-in process includes pre-selected checkboxes... Opt-in
> mechanisms must require affirmative action from the consumer (unchecked by default)."*

**The shipping UI was never pre-checked.** `templates/billing/public_invoice_view.html:182` is
`<input type="checkbox" name="sms_agree" value="1" required>` — no `checked` attribute, and
`required`, so the form refuses to submit until the customer ticks it. Two things told the
reviewer otherwise: the screenshot was deliberately captured **with the box ticked** (see the
paragraph above — it was staged that way to show a filled-in form), and the description called
it *"a checked box"*, meaning *"a box they check"*. A compliance reviewer reads both as
pre-selected. **Screenshot the default state, not a filled-in one.**

### Version 4 submitted 2026-08-31 — `REVIEWING`

Fixes exactly those two, nothing else — v3's other 17 fields are copied forward verbatim
(`BASE_VERSION = 3` in the script), since none of them were ever objected to.

- `contactInfo.supportEmail` → **`support@rssystems.io`** (matches `companyInfo.website`).
  **Verified 2026-09-01 via the ImprovMX API**: the alias exists and forwards to
  wdrakeduncan@gmail.com, and the domain is `active`/not banned — so if AWS writes to it,
  Drake reads it. (rssystems.io also has a catch-all, which is why an SMTP probe could not
  have answered this — see `docs/operations/SES_OPERATIONS.md`.)
- `optInDescription` rewritten to state the box is "EMPTY AND UNCHECKED by default", never
  pre-selected, requires the customer's own click, and is HTML `required` (1242/1500 chars).
- `optInImage` re-shot showing the card in its **default state, box unchecked**, with the
  mobile-number field, the full consent label, and the STOP/HELP + Program terms line in frame.

The screenshot is now generated from the real template rather than staged on prod — render
`billing/public_invoice_view.html` standalone (it carries its own inline `<style>` and extends
nothing, so a standalone render is pixel-faithful), then screenshot headless:

```bash
# render with sms_optin_offered=True, sms_opted_in=False, sms_optin_phone_last4=None
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=2 --window-size=780,900 \
  --screenshot=optin.png file://$PWD/optin_page.html
```

Assert `checked` does not appear after `name="sms_agree"` in the rendered HTML before shipping
the image — that assertion is the whole point, and it is cheaper than 30 hours of review.

**Two API traps, both paid for:**

1. **`create-registration-version` opens an EMPTY draft.** It inherits none of the previous
   version's field values. Submitting straight after it produced an *automated* denial —
   version 2, "Missing required field", back within seconds, no human involved. Every
   required field must be re-`put` onto the new version first. Working script:
   `scripts/submit_tollfree_registration.py` (copies a base version wholesale, applies explicit
   overrides, and refuses to submit if any REQUIRED path is still empty). Note the corollary
   v3 paid for: **copying a base version also copies whatever was wrong with it** — every
   override has to be deliberate.
2. **Field values are locked while the last version is denied.** `put-registration-field-value`
   returns `ConflictException EDIT_REGISTRATION_FIELD_VALUES_NOT_ALLOWED` until a new
   version is opened.

A denied version isn't fatal — versions accumulate (1–3 DENIED, 4 REVIEWING) and review runs
on the newest. But each *human* cycle costs days, so verify the whole field set before
submitting, not after — and verify the *content* of inherited fields, not just their presence.
The v2 guard only checked that required paths were non-empty; `supportEmail` was populated the
whole time, just with the wrong company's domain.

Until it clears, the $2/mo lease is running on a number that cannot send.

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

## Appendix C — Multi-technician: what must stay true

*(Added 2026-08-25. Drake's shop currently has exactly one technician — himself —
so every simplification S12 makes for a one-person roster is correct **for him**
and wrong for the shops signing up behind him. This appendix is the list of
things a "just make it simple" pass must not quietly delete. Written down
because the person deleting them will have a one-tech database in front of them
and no way to notice.)*

**The shape of the data.** `GlassService.technician` is a **non-nullable FK** —
there is no unassigned state, so every job always has a name on it, and every
"assign" is really a *reassign*. That is why `apply_dispatch` refuses a no-op
(`dispatch.py:210`) and why the row's technician picker defaults to whoever
already holds the job.

**Three permission levels, not two.** They are genuinely different and the
difference is load-bearing:

| Level | Resolved by | Can |
|---|---|---|
| plain technician | `_resolve_viewer` → `sees_whole_shop = False` | see **only their own** day. Never loads the swap or dispatch scripts at all — there are no handles to find and no endpoint offered. |
| manager / owner | `is_manager` or tenant admin → `sees_whole_shop = True` | see the whole shop, book times, move times, swap. `can_swap` / `can_book` in the day view are exactly this. |
| dispatcher | additionally `technician.can_assign_work` (`models.py:82`) → `_can_assign` (`views/schedule.py:74`) | **reassign** work to someone else. Strictly narrower than manager. |

The refusal sentence for the gap between the last two already exists and should
be reused verbatim: *"You can schedule work but not reassign it."*
(`views/schedule.py:388-395`). `schedule_row.html:156-158` encodes the same
split by choosing the row form's endpoint — `schedule_dispatch` when
`can_assign`, else `schedule_book` — so **neither path is dead code**; a
one-tech shop simply never exercises the narrower one.

**What the day view does with more than one tech.** `day_schedule` builds
`groups`, one per **active technician** — including techs with nothing booked,
so a free person is *visible rather than absent* — and each group carries
`technician_load(annotate_conflicts(jobs))`. Keep all of it:

- **Per-tech grouping and the `data-swap-group="tech-{pk}"` scope.** This is what
  stops a swap from silently becoming a reassignment. A cross-list *swap* is
  refused; a cross-list *move* is a dispatch (S14), not a move.
- **The S8 hours chip** (`hours_today` / `off_today`). "Nothing scheduled" and
  "not working" look identical on a board without hours and lead to opposite
  decisions — one is a gap to fill, the other is a person to leave alone.
- **The capacity chip**, printed only when `load.over_committed` — "5h of work
  booked into 4h" is the honest form of a conflict for coarse windows, where
  plain interval overlap would flag every normal morning.
- **The roster picker**, which deliberately keeps an **off-duty** tech in the
  list, marked. A shop with one truck down calls somebody in on their day off,
  and a picker that omits the person the manager is on the phone with reads as
  broken.
- **Conflict chips are informational and never block.** A shop with two people
  in one truck is allowed to double-book on purpose. `PRECISE_WINDOW_MAX = 2h`
  (`schedule_conflicts.py:60`) exists because every job booked "MORNING"
  overlaps every other by construction.

**How S12 is allowed to simplify.** Collapse to a flat list with no technician
header **when and only when the active roster is one person** — a runtime
check, not a build-time assumption. The moment a second technician is added the
headers, the per-tech scoping and the roster picker must come back with no
migration and no setting. Test both shapes; a one-tech fixture passing is not
evidence.

**Notifications.** Everything above is why the notify rules are what they are:
never notify the actor about their own action, notify the *assigned* tech about
someone else's, and emit **one** message per motion — which is the entire reason
`apply_dispatch` composes assign + book inside one transaction instead of
calling two endpoints. S14 extends that to assign + move.

---

## Document history

| Date | Change |
|---|---|
| 2026-08-11 | Created from live exploration (notification-path + scheduling audits) and Drake's scoping decisions: one combined doc; full arc MVP-first; staff notifications default-ON. |
| 2026-08-11 | Review pass with Drake: confirmed MVP-first sequencing over deeper upfront scheduling design. Named the two known gaps so they don't get lost — technician availability (S5 consideration + S6 backlog item 4) and self-service rescheduling (S6 backlog item 5). |
| 2026-08-12 | Corrected the SMS status: the TFN registration was **denied** on 2026-08-11 (this doc said `REVIEWING` — it was written hours before the denial landed). Rewrote Appendix A with the reason and the resubmission path, and added **N4** to the queue, because the fix is product work on the consent surface, not a console edit. |
| 2026-08-12 | **N1 executed** (branch `feat/fieldops-n1-assignment-notifications`): one assignment write path (`services/assignments.py`), per-template `channels_override`, staff email default-ON, Replacement signals, bulk summaries, rewritten assignment emails. §0 blockers 1–3 closed; blocker 4's SMS half stays with N2. Two traps added (NOT NULL technician; flat-context/absolute-link email rules). Merged as PR #179. |
| 2026-08-25 | **Deploy state trued up.** Every "not yet deployed" claim in this document was stale: #197, #198, #200, #201 and #204 all shipped in the 2026-08-24 22:47 deploy (`app-68dc`), which went out to carry the SMS opt-in card fix (#205) and took the whole merged backlog with it. S5, S8 and N3 rows corrected, the closing section rewritten. |
| 2026-08-25 | **Toll-free registration version 3 SUBMITTED** (`REVIEWING`). Screenshot captured from the live opt-in card on prod with a number typed in; `optInDescription` rewritten first-party. Version 2 was auto-denied in seconds for "Missing required field" — `create-registration-version` opens an empty draft that inherits nothing, and field edits are locked (`EDIT_REGISTRATION_FIELD_VALUES_NOT_ALLOWED`) until a new version exists. Both traps in Appendix A. Also verified the opt-in flow end to end on prod: TEST CUSTOMER opted in first-party, then was reset (phone cleared, checkbox unchecked) for the screenshot. |
| 2026-08-24 | **N4 follow-up**: the first-party opt-in card never rendered on prod — it required a mobile already on `Customer.phone`, and phone is optional, so an emailed-only customer saw nothing. The card now asks for the number when the shop has none (branch `fix/sms-optin-no-phone-on-file`). Registration v2 is still unsubmitted; screenshot this surface. |
| 2026-08-12 | **N4 code executed** (branch `feat/fieldops-n4-sms-opt-in`): compliant disclosure on both shop-side consent checkboxes, first-party opt-in card on the public invoice page (`/invoice/<id>/<token>/sms-opt-in/`), `Customer.sms_opt_in_source` provenance (core migration 0028), `/sms/` opt-in copy rewritten. Registration v2 submission is Drake's post-deploy step — checklist in N4 Notes. |
| 2026-08-12 | Parts sourcing investigation (Drake's ask: own NAGS lookup + live Mygrant quotes/ordering). Findings in **Appendix B**; queued **P1** (Mygrant quotes+ordering — buildable now on Mygrant's documented SOAP API with shop credentials) and parked **P2** (vehicle→NAGS lookup — blocked on a negotiated Mitchell license). Committed the Mygrant spec PDF to `docs/reference/`. |
| 2026-08-14 | Live portal walkthrough on the pilot account (Drake's dad's shop) — **Appendix B.5**. Confirmed: live per-brand shop pricing, 4-warehouse structure, PO-per-line ordering with Freight/Will-Call, PO-searchable history, and that Generate Key is absent until rep API-onboarding (the only real P1 blocker — call the rep). Investigated and **rejected portal automation** (site ToS §8.1). Reworked P1 around the multi-shop "Connect your Mygrant account" design (per-tenant `MygrantConfig` on the `TenantConfig` pattern; encryption-at-rest is a first-in-codebase decision), added Drake's dad's "portal is already easy — win on job context" principle, profit-on-ticket framing, and the ~$1/search cost constraint. Fixed stale `nags_number` line refs. Later same day: added the numbered **P1 order of work** (onboarding → billing → encryption decision → connect → quote-only → ordering); Drake left the onboarding voicemail with Mygrant IT. Later still: **P1 steps 3+4 BUILT (PR #184, `feat/mygrant-connect`)** — `common/encryption.py` (Fernet, `FIELD_ENCRYPTION_KEY`, first secret-storage mechanism in the codebase), `MygrantConfig` migration 0052, owner Settings Parts tab with the Connect card, staging-only Test connection, 20 tests. Deploy needs a one-time `eb setenv FIELD_ENCRYPTION_KEY`. |
| 2026-08-15 | **PRs #184 + #183 merged and deployed** (health 200); `FIELD_ENCRYPTION_KEY` still pending Drake's one-liner (sandbox can't set prod secrets), Parts card in its designed "not available yet" state until then. **P1 step 5 BUILT (PR #186, `feat/mygrant-quotes`)** — quote button + SKU table + one-tap `parts_cost` + profit-on-this-job on `replacement_detail`, server-side quote cache (one billable search per quote, prices unforgeable), item-level errors surfaced, `mygrant_quote` management command for the staging-first proof. Ships dark behind `is_enabled()` until the Mygrant callback delivers the API key. P1 notes updated with the first-quote runbook and step-6 guidance (reuse the cached-SKU pick for exact-SKU orders). |
| 2026-08-18 | **P1 onboarding, non-code session.** Owen (Little Rock branch) supplied the Mygrant IT support director's email 2026-08-17; written onboarding request sent (asks: enable API User onboarding on `C027180-001` so Generate Key appears, and confirm whether API Inquiries bill per-search like portal searches). Corrected a standing factual error: **Drake is the account owner** on `C027180-001` — his dad only uses it — so nothing about onboarding needs a third party. 24h of silence prompted the real question, now answered in P1's Considerations: per-shop onboarding is table stakes (every competitor POS works this way and `is_enabled()` keeps it off every other surface), but **the vendor must not be the one making the call** — a shop's own CSR handles this as routine where a cold vendor request has no SLA. Built the Connect card's **"Don't have an API key yet?"** panel (`owner_settings.html` Parts tab, open until a key is saved): who to call, what to ask for (their account number pre-filled), where Generate Key lives, that its *absence* means the rep hasn't finished, and a nudge to ask about search billing on the same call. No new CSS (every class already compiled). Queued for the first Mygrant call that connects: **does Mygrant have an integrator/partner listing for POS vendors** — worth more than our own key. Escalation if silent by ~2026-08-24 is Owen/the sales rep, not IT again. |
| 2026-08-19 | **S8 specced (doc-only session).** Promoted S6 backlog item 4 — technician working hours — into a full session, pressure-tested against the real code the way S4 and S7 were before their builds. The finding that reframes it: `Technician.working_hours` has existed since migration `0007` and is completely inert (`default=dict`, no schema, no validator, **zero readers and zero writers** outside a collapsed Django-admin fieldset), so every production row holds `{}` — which means the session's first rule is that empty means *undeclared*, not *unavailable*. Recommended shape adopts the convention the admin help text already documents rather than inventing a better one. Named the three places it plugs in (`schedule_conflicts.annotate_conflicts` / `technician_load`, the board's roster, and S3's "Nothing scheduled" line, which should read "Off today"), and the two places it must **not** touch: `update_team_member` (three forms POST it, absent checkbox = false, so a field added there is silently erased) and auto-assignment (hours as a filter re-creates the CODE-160 dead end every evening and weekend). Recorded a live pre-existing bug found on the way: `_adjust_to_business_hours` compares **UTC** hours, so review-request emails clamp to 04:00–14:00 Central and effectively send at ~4 AM local — the fix belongs to the review system, S8's job is not to inherit it. Two traps added. |
| 2026-08-24 | **S8 executed and the document wrapped up.** Merged the 2026-08-19 foundation branch (which had been cut before S5 landed and therefore shipped `services/working_hours.py`, the model delegates and the Settings → My Team editor with *no* consumers) and built the missing board half on top of a `main` that now has S5: a fourth conflict chip ("Outside Marcus's hours" / "Marcus is off Saturdays"), declared hours as `technician_load()`'s denominator in place of the span the jobs happen to occupy, "Off today" where the board used to say "Nothing scheduled", and off-duty marks in the dispatch picker that never remove anybody. 51 tests, no migration, no CSS rebuild. Also trued up an S4 assertion that #200 had broken hours earlier the same morning. **Corrected a deploy claim this doc had wrong:** S5 merged on 08-24, not 08-18, and is still undeployed — a `gh pr list` "updated" column is not a merge date, and that is now a trap. Rewrote the deploy state as a table of four merged-undeployed PRs (#197/#198/#200/#201), refreshed **N3** against post-#200 code with three concrete defects to start from (the `{% with %}`/`action_url` fragility that breaks the smoke set, the UTC review-hours bug, `repair_request_submitted`'s dead channel map), retired S6 backlog item 4 into S8, and added a closing **"Where this document ends"** section: what is left, what gates each item, and what would reopen this doc rather than start a new one. |
| 2026-08-25 | **Phase S reopened by first real use — S9–S14 specced (doc-only session).** Drake took a customer call and booked it through RS Systems instead of a note in his phone; the machinery held and the surface did not. Recorded the diagnosis in a new §0 section (*"Scheduling UX — what first real use found"*) so no future session re-derives it: **there is no reschedule path in the product at all** (no endpoint, view or service; a booked row renders only the technician picker, and the only non-form writer refuses cross-day, cross-tech and batches), **swap confirms itself with a page reload** so every refusal is invisible, **a booked REQUESTED job vanishes from both lists** (`DAY_STATUSES` excludes REQUESTED while `BOOKABLE_STATUSES` includes it), and **`base_app.html:263-285` pre-fills every empty `datetime-local` on every page**, which makes `job_form.html`'s "leave blank to keep this job unscheduled" impossible to honour. Six sessions queued: S9 prefill fix (first, because everything after it moves `scheduled_for`), S10 quick-add from the schedule (the one Drake asked for — extracts `job_create`'s inline logic into `services/quick_job.py` rather than duplicating it), S11 the missing `move` primitive + inline time/date edit, S12 the ordered day list with drag-to-move, S13 dashboard schedule card, S14 multi-tech moves. **Decisions taken with Drake:** quick-add from the schedule page; ordered day list, not a calendar grid; a drop slots into the gap and keeps its own length; **swap is kept and improved, not retired**; moving a job off a day means moving it *straight onto another day*, with no unscheduled limbo. Added **Appendix C — Multi-technician** because Drake is a one-tech shop and S12's simplifications are exactly where the multi-tech affordances would quietly die. Two traps added. |
| 2026-08-31 | **Toll-free registration version 3 was DENIED 2026-08-26** — found five days later, because `RegistrationStatus` read `REQUIRES_UPDATES` while the denial lived on the version. Check the *version*, not the registration. Two reasons, both self-inflicted: `contactInfo.supportEmail` was still `drake@rockstarwindshield.repair`, copied wholesale from the approved *Rockstar Windshield Repair* registration where that domain legitimately matched its own website — under RS Systems / rssystems.io it matches neither; and the opt-in read as pre-selected, because the v3 screenshot was deliberately staged **with the box ticked** and the description called it "a checked box" (meaning *a box they check*), though the shipping input at `public_invoice_view.html:182` has never carried `checked` and is `required`. **Version 4 SUBMITTED, `REVIEWING`**: `support@rssystems.io` (matches the website; the alias was verified 2026-09-01 via the ImprovMX API — it exists and forwards to Drake's own inbox), an `optInDescription` stating the box is unchecked by default and requires the customer's own click, and a screenshot rendered from the real template in its **default** state. `scripts/submit_tollfree_registration.py` rewritten: base version is now explicit, every override deliberate, and it asserts the support email's domain equals `companyInfo.website` before submitting — copying a base version copies its mistakes too. |
