# Job Queue Sessions — making "nobody has picked this job yet" a real state

**Created:** 2026-08-26
**Author:** Claude (working session with Drake)
**Status:** living document — update statuses and Notes as sessions complete
**Companions:** `FIELD_OPS_SESSIONS.md` owns notification delivery (N1–N3) and
the dispatch board (S5); this arc changes what those surfaces are told about.
Read this file's §0 before touching either.

**What this arc is for (the durable purpose statement):** the owner portal's
**Job Assignment** setting (`Tenant.assignment_strategy`, four choices) makes
four promises. Before this arc it kept two. "Manual — a manager must manually
assign every repair" was simply false: every customer request was assigned to
whoever `get_available_technician()` returned first, and that technician was
notified the job was theirs. There was no way for a shop to say *nobody has
chosen yet*, because `GlassService.technician` is a **NOT NULL** foreign key —
"unassigned" was not a state the schema could hold.

This arc makes that state real, without making the FK nullable (~210 references
and 45 `technician__` lookups say no). A `needs_assignment` boolean carries the
meaning the null was supposed to carry: the name on the row is a placeholder,
nobody picked them, and nobody told them. Every promise the settings page makes
should be true when this arc closes.

Each session is self-contained — a fresh Claude session with no memory should be
able to execute exactly one session using only §0 and that session's table.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED`

| Phase | Session | Size | Status |
|---|---|---|---|
| Q — The queue exists | Q1 · Round robin that actually rotates (CODE-278) | S | DONE (2026-08-26, commit `6a199b84`, pushed — **no PR yet**) |
| Q — The queue exists | Q2 · The Unassigned queue (CODE-279) | M | DONE (2026-08-26, commit `33be9b22`) |
| R — The queue drains | Q3 · Approving a queued job takes it (CODE-280) | S | DONE (2026-08-26, commit `fbf27808`) |
| R — The queue drains | Q4 · Telling managers outside the dashboard (CODE-281) | S | DONE (2026-08-26, commit `PLACEHOLDER`) |
| R — The queue drains | Q5 · Where managers actually live: board + aging | M | TODO |
| R — The queue drains | Q6 · One provisional pick, in one place | S | TODO |

**Suggested sequence:** Q5 → Q6. Q3 went first because it was the only
*correctness* gap rather than a reach gap — four code paths tested
`if not job.technician` on a non-null FK, so they were dead branches that read
as working code. Q4 before Q5 because a queue nobody is told about does not
drain no matter how good the board is. Q6 is cleanup and can slip.

**Sizes:** S ≈ half a day · M ≈ 1–2 days · L ≈ 3–5 days.

**Where we are (2026-08-26, after Q4):** Q1–Q3 are four commits on
`fix/job-assignment-round-robin` (worktree `~/projects/rs_assign_wt`), rebased
onto `main` at `f4c1a7ad` (PR #217, photoml P3), and open as **PR #220**. Q4 is
one commit on `feat/jobqueue-q4-manager-alerts`, **stacked on that branch**
because it needs Q2's `needs_assignment` column — merge #220 first. The whole
arc is committed — nothing is left in a working tree.

Verified on sqlite after the rebase: 27 CODE-279 tests, 13 CODE-280 tests, and
the eight adjacent assignment regression modules (84 together); plus
`test_fieldops_s5/s9/s10/n1`, `test_unified_job_list`, `test_job_form_parity`
and `test_services_offered` (167 together). One failure in
`test_code105_repair_detail_unscoped_technician` is **pre-existing** — it
reproduces identically on unmodified `origin/main`, checked in a throwaway
worktree.

**The migration was renumbered during this session.** It was authored as
`0058_add_needs_assignment` against `0057_repairphotocrop`, but `main` gained
its own `0058` and `0059` from photoml P3 while this branch sat unmerged. It is
now `0060_add_needs_assignment` depending on `0059_backfill_confirmed_crops`,
amended into the commit that introduced it so no commit in the branch ever has
two leaf migrations. `manage.py makemigrations --check` is clean. If this
branch sits unmerged again, check for the same collision before opening the PR.

## How to run a session

1. Cut a fresh branch off the latest `main`: `feat/jobqueue-<id>-<slug>`. Never
   stack on another session's branch. Print `git branch --show-current` before
   every test run — other Claude sessions share this checkout's neighbours.
   **Q4–Q6 depend on Q2's migration**, so until `fix/job-assignment-round-robin`
   is merged, branch from it and say so in the PR body.
2. Read §0 plus your session's table. Re-verify the `file:line` anchors before
   coding — the code moves.
3. Tests: the Postgres credentials in `CLAUDE.md` (`amelia_test`) are rejected
   on this machine, so `manage.py test` falls back to sqlite. **Diff against a
   `main` baseline; never read anything into an absolute failure count** —
   ~76 `tests/bug_fixes` tests fail on unmodified `origin/main` under sqlite.
   Prefer targeted modules: the full `tests.bug_fixes` sweep takes over an hour
   when another session is running its own suites. Use
   `~/projects/rs_systems_branch2/venv/bin/python` — this worktree has no venv.
   Don't let a run straddle midnight; several invoice/report tests are
   date-sensitive.
4. Commit files by name; never `git add -A`. Open a PR against `main`.
5. When done: flip the status in the index table and write what you learned
   under the session's **Notes** heading. That's what makes this a living doc.

## §0 · Context primer (read once per session)

**The fact everything else follows from.** `GlassService.technician` is
`models.ForeignKey(Technician, on_delete=models.CASCADE)` —
`apps/technician_portal/models.py:424`. Not nullable. Every caller that creates
a job must name a technician *before* the shop's strategy has been consulted,
so customer-portal requests create the row with a **provisional pick** from
`get_available_technician()` (`apps/customer_portal/views.py:2558`) and only
then call `auto_assign_repair()`. Any code that tests `if not job.technician`
is a dead branch — see Q3.

**The flag.** `GlassService.needs_assignment` — boolean, `db_index=True`,
default `False`, on the abstract base so `Repair` **and** `Replacement` have it
(migration `technician_portal/0058_add_needs_assignment`). True means: the
strategy declined to pick anyone, the name on this row is the caller's
provisional placeholder, and **the technician has not been told**. It is what
the Unassigned queue lists.

**The flag settles itself, and says so.** `GlassService._settle_needs_assignment()`
(`models.py`, called first thing in both `Repair.save()` and
`Replacement.save()`) clears the flag whenever `technician_id` differs from the
value loaded in `__init__`. So the job form, the approve action, the Django
admin, batch reassign and `services.assignments.assign_job` all clear it
without knowing it exists — and none of them can forget. **Saves that pass
`update_fields` get `needs_assignment` appended**, or the clear would happen in
memory and never reach the database. If you add an assignment surface, you get
this for free; if you write to `technician` with raw SQL or `.update()`, you do
not.

It also records `_cleared_needs_assignment` on the instance when *this* save is
the one that drained the job. The assignment signal needs that, because by the
time `post_save` runs the flag is already False — without it the provisional
technician gets a "reassigned away" notification for a job they were never told
they had. **Leaving the queue is a first assignment, not a reassignment**: the
signal drops the old technician when the marker is set, the same shape the
dispatch board's confirm path uses. (CODE-280)

**Two entry points into the strategy** (`apps/tenants/services/assignment_service.py`):

| Function | Writes? | Use when |
|---|---|---|
| `auto_assign_repair(repair)` / `auto_assign_replacement(replacement)` | yes | the row already exists (customer portal) |
| `select_technician(tenant, *, customer, service_type, exclude_pk)` | **no** | you are choosing before the row exists (in-app creation) |

`select_technician` returning `None` means **"flag it for the queue"**, never
"any technician will do". `_auto_assign` turns that `None` into
`_leave_unassigned()`. The strategy-specific `_assign_*` functions still exist
as back-compat wrappers because the CODE-163/172/278 regression tests call them
by name.

**Who gets told what.** A flagged job suppresses the tech-facing "you've been
assigned" notification — the guard is at the top of
`notify_assignment_from_signal` (`apps/technician_portal/services/assignments.py:412`).
In its place `notify_needs_assignment(job)` writes a `TechnicianNotification`
dashboard row to every active manager on the tenant, de-duplicated per
`repair_batch_id` so a six-break request is one decision, not six alerts.
It also sends the `needs_assignment` template through `NotificationService`
— the bell, the email and the delivery log — to the same managers, gated by
the *same* batch check, because an email cannot be unsent. Two writes on
purpose: `TechnicianNotification` is the dashboard's unread list and nothing
else. (CODE-281, Q4)

**Where the flag is visible today.**

| Surface | File | What it shows |
|---|---|---|
| Job list filter | `views/jobs.py:155` + `job_list.html:230` | the "Needs assignment" option — it filtered `technician__isnull=True` and therefore matched **nothing** until Q2 |
| Job list rows | `job_list.html` (card + table) | amber "Needs assignment" chip in the technician column |
| Repair detail | `repair_detail.html:408` | amber chip beside the technician name, tooltip explains the placeholder |
| Dispatch board rows | `includes/schedule_row.html` | amber chip, manager-only (`can_assign`) |
| Owner settings | `saas/owner_settings.html:287` | Manual and Primary-First descriptions now link to the queue |
| Manager email + bell | `needs_assignment` template, core migration `0034` | the alert that reaches a manager who never opens the app (Q4) |
| Manager dashboard | — | **nothing yet** (Q5) |

**The dispatch board's confirm rule.** On a flagged job, submitting the
technician picker *unchanged* is a decision, not a no-op: the name there is a
placeholder, and leaving it is choosing it. `apply_dispatch`
(`services/dispatch.py:209`) treats that as `confirmed`, clears the flag,
notifies the tech (with `old_technician=None` — this is the first they've heard
of it), and says "assigned to" rather than "moved to". An ordinary no-op on an
unflagged job is still refused with "nothing to change".

---

## Q1 · Round robin that actually rotates — DONE (2026-08-26)

**Shipped:** commit `5a572fae` on `fix/job-assignment-round-robin` (`6a199b84` before
the rebase onto `main`).

Round robin sent every customer request to the same technician. The rotation
anchored on the job it was currently assigning — because the row already exists
with a provisional tech (see §0), the "last assigned" lookup found *itself*,
so the rotation advanced one step past the provisional pick every single time
and landed on the same neighbour. `_assign_smart` had the same shape of bug
from the other direction: the job being assigned counted toward its own
technician's workload, pushing the job away from the tech the count was meant
to favour.

**Notes.**
- The anchor query orders by `-id`, deliberately **not** `-service_date`:
  `service_date` is editable from the job form, so backdating a job would drag
  the rotation anchor with it.
- The anchor must come from the same service type being assigned — Repair
  history anchoring a Replacement was CODE-172.
- Guarded by `tests/bug_fixes/test_code278_round_robin_self_anchor.py`.

## Q2 · The Unassigned queue — DONE (2026-08-26)

**Shipped:** commit `33be9b22`, CODE-279, 27 tests. Files: `models.py`,
`services/assignments.py`, `services/dispatch.py`, `services/quick_job.py`,
`views/jobs.py`, `tenants/services/assignment_service.py`, four templates,
migration `0060` (see §Where we are on the renumber),
`tests/bug_fixes/test_code279_unassigned_queue.py`.

Two product decisions, both Drake's, each chosen from three options offered:

1. **Queue → "flag, don't nullify."** A nullable `technician` would have meant
   ~210 references and 45 `technician__` lookups going nullable — too
   expensive, and every one of them a chance to leak an empty technician into
   an invoice. The row keeps its provisional tech; the flag means nobody chose
   them. See §0.
2. **In-app creation → "your own job stays yours."**
   `quick_job.resolve_technician` now returns `(tech, needs_assignment)` and
   goes: the actor's own profile *if `can_perform` says they can do this kind
   of work* → the shop's strategy via the new write-free `select_technician()`
   → an arbitrary fallback, flagged. A tech logging the walk-in they just
   handled keeps it; a dispatcher with no profile gets the shop's configured
   behaviour instead of an arbitrary first row. This is the half of the setting
   that in-app creation used to skip entirely.

**Notes.**
- **What the test run caught.** `tests.test_unified_job_list`'s
  `test_no_template_syntax_leaks_into_pages` failed on the first full run: the
  new `job_list.html` annotation was written as a **multi-line `{# … #}`**,
  which Django does not parse as a comment — its text renders straight into the
  page. Converted to `{% comment %}…{% endcomment %}`; module green (30 tests).
  Single-line `{# … #}` is fine and three others in these templates are
  untouched. The repo already had a guard for this exact mistake — run it when
  you annotate a template.
- `needs_assignment` on `Replacement` is carried by the same abstract base and
  the same migration, so replacements queue too. `notify_needs_assignment`
  passes `repair=job if is_repair else None` — `TechnicianNotification` has no
  replacement FK, so a queued replacement's alert has no deep link. Worth
  fixing in Q5.
- The batch de-dup matches on the literal phrase `is waiting to be assigned`
  (`_WAITING_PHRASE`). If you reword the message, reword the constant — they
  are one thing.
- `can_perform` treats an inactive or ability-less profile as *cannot*, so the
  actor falls through to the strategy rather than taking the job. Assigning
  work to a deactivated tech is CODE-160 from the other direction.

## Q3 · Approving a queued job takes it — DONE (2026-08-26)

**Shipped:** commit `fbf27808`, CODE-280.

**The decision.** Approving a queued job takes it **only if the approver can
actually do that kind of work**. One-person shop: the owner approves and it is
theirs in one motion. Dispatcher shop: approving approves the work and leaves
the pick alone, because a dispatcher who approves everything would otherwise
end up owning the entire queue — the opposite of what Manual is for.
`services.assignments.can_perform(technician, service_type)` is the rule; it
moved out of `quick_job._can_perform` once two callers needed it, and it
answers False for `None`, so an admin-only user with no `Technician` row is an
ordinary case rather than an `AttributeError`.

**What became live.** Bulk approve (`views/repairs.py`) now tests
`needs_assignment` instead of `not repair.technician`, and the update gate —
whose message already read *"this repair has not been assigned yet"* — is live
against the flag too, with **managers exempt**, the same way they are exempt
from the closed-job gate directly above it. They are who the queue waits on.

**What was deleted instead.** Two of the four branches are unreachable by
construction, so reviving them would have invented behaviour nobody asked for.
Each is now a comment saying why it went:
- `views/repairs.py` repair create — `_scoped_tech` is assigned
  unconditionally a few lines above and the view has already returned if it is
  None. A tech creating their own repair has chosen the technician by
  definition.
- `saas/views.py` replacement create — `technician` is a **required field** on
  `ReplacementForm` (non-null FK, no `blank=True`), so `form.is_valid()`
  already guarantees a pick. If that form should ever offer "decide later",
  that is a new field plus a `needs_assignment` write, not a resurrected dead
  branch.

**Notes.**
- **Writing the tests found a hole in Q2.** The provisional tech was being told
  the job was "reassigned away" the moment a manager took it — the first and
  only thing they would ever hear about a job that was never theirs. The flag
  is cleared inside `save()`, so `notify_assignment_from_signal`'s
  `needs_assignment` guard sees nothing by the time `post_save` fires. Fixed
  with `_cleared_needs_assignment` (see §0). **If you add a surface that
  drains the queue, notify with `old_technician=None`.**
- Two `if not <job>.technician` checks survive on purpose and are *not*
  assignment paths: `signals.py:620` is a defensive log guard in a notification
  helper, and `views/repairs.py:1096` is a null-guard before
  `manages_technician()`. Both are harmless; neither decides who gets a job.
- **Test-base trap.** `Tenant.objects.create` gives you a tenant with no
  subscription, and the middleware sends the first view request into a redirect
  loop (`RedirectCycleError`, which reads like a routing bug and is not). Build
  shops with `create_tenant_with_owner` + `TenantMembership`, as
  `tests/test_unified_job_list.py` does.
- The one-person-shop path is the common case and it now costs one click. The
  dispatcher path deliberately costs two, and that is the whole point of the
  decision.

## Q4 · Telling managers outside the dashboard — DONE (2026-08-26)

**Shipped:** CODE-281, 21 tests. Files: `core/migrations/0034_needs_assignment_template.py`,
`core/management/commands/setup_notification_templates.py`,
`templates/emails/notifications/needs_assignment.html` + `.txt`,
`apps/technician_portal/services/assignments.py`, `tests/test_fieldops_n3.py`,
`tests/bug_fixes/test_code281_needs_assignment_reach.py`.

Q2 gave the queue an alert that reached exactly one place: the dashboard's
unread list. The setting promised "a manager must manually assign every
repair"; what it delivered was "a manager must manually go looking". The
alert now also goes through `NotificationService` on a seeded
`needs_assignment` template — bell, email, delivery log.

**Priority HIGH with `channels_override: ['in_app', 'email']`.** HIGH alone
maps to `['in_app', 'sms']` and SMS is dark until fieldops N2, so a HIGH
template without an override renders an email body nothing can deliver —
the trap N3 found in three other rows. SMS is left off rather than staged:
adding it when N2 lands is one line, and `DeliverableChannelTests` will not
let the row go stranded meanwhile.

**Notes.**
- **Two writes, one gate.** `TechnicianNotification` (dashboard) is written
  first and `NotificationService` second, both behind the *same*
  `repair_batch_id` check. That ordering is the point: a dashboard row can
  be deleted and an email cannot be unsent, so the de-dup has to sit above
  both rather than once per delivery path. The email send is split into
  `_email_needs_assignment` and wrapped, so a missing or deactivated
  template cannot cost us the dashboard row CODE-279 already had — asserted
  by `TheDashboardRowSurvivesTest`.
- **The email must not name the provisional technician.**
  `_assignment_context` fills `technician_name` from whoever the non-null FK
  forced onto the row; a manager alert carrying it reads as "assigned to
  Marcus", which is the exact lie this arc exists to stop telling. The key
  is stripped at the call site and the template has no technician row at
  all. If you extend this context, strip it again.
- **It says *why* it is queued.** `_queue_reason(job)` maps
  `tenant.assignment_strategy` to one sentence. Without it "waiting to be
  assigned" cannot distinguish deliberate shop policy (`manual` never
  picks) from a shop that has deactivated every technician (`auto` /
  `round_robin` decline only when the eligible pool is empty). Same event,
  opposite responses.
- **A replacement's email links; its dashboard row still does not.**
  `Notification.repair` is a Repair-only FK, so replacements pass
  `repair=None` and merge `job_display_context(job)` themselves — the split
  that function documents. `action_url` is a plain string the sender
  controls, so the email deep-links either way. The route is
  `/tech/replacement/<pk>/`, **singular** — `_job_action_url` has it right.
  The `TechnicianNotification` gap is still Q5's.
- **Found while writing the tests:** core migration `0032` seeds
  `replacement_request_submitted` (and every other replacement template)
  with `action_url_template: '/tech/replacements/{{ replacement_id }}/'` —
  **plural, and a 404**. `apps/saas/urls.py:120` is
  `tech/replacement/<int:pk>/`. Every replacement notification's button has
  been pointing at a dead URL since 0032. Left alone here because it is a
  fieldops row and not this arc's, but it is a one-line seed fix and
  somebody should take it.
- The new template deliberately carries a blank `action_url_template` for
  the same reason: one default would be right for repairs and a 404 for
  replacements, so the sender passes the URL.
- **A queued job's provisional tech does still get mail** — just not
  assignment mail. `repair_request_submitted` goes to every technician in
  the shop when a customer asks for work, and that is a different event
  with a different meaning. The first draft of
  `test_the_technician_nobody_picked_hears_nothing_about_assignment`
  asserted an empty inbox and failed on exactly this; the assertion is now
  scoped to assignment events. Worth knowing before you read a stray email
  in a test as a regression.
- The drain rule from Q3 needed nothing new: this notification fires when a
  job *enters* the queue, and the one that fires when it leaves is
  `notify_assignment_from_signal`, which `_cleared_needs_assignment`
  already turns into a first assignment (§0).

**Verified on sqlite:** 21 CODE-281 tests; `test_fieldops_n3` (28),
`test_code279` (27), `test_code280` (13), `test_code278` (4) — 72 together;
`test_email_chassis`, `test_notification_surfaces`, `test_fieldops_n1`,
`test_tenant_email_branding`, `test_fieldops_s5` — 133 together;
`test_unified_job_list`, `test_job_form_parity`, `test_fieldops_s9`,
`test_fieldops_s10` — 75 together. All green.
`manage.py makemigrations --check` is clean; `core/0034` depends on `0033`,
which is `main`'s leaf, so there is no renumber to redo unless this branch
sits while another core migration lands.

## Q5 · Where managers actually live: board + aging — TODO

The queue is discoverable only if you already know to pick "Needs assignment"
from a filter dropdown. Managers live on the dashboard and the S5 dispatch
board.

**Build:** a count/badge on the manager dashboard linking to
`?assignment=unassigned`; the same on the dispatch board, which already renders
the chip per row but offers no way to see only what needs deciding. Add
**aging** — a job queued three days ago is a different problem from one queued
ten minutes ago, and nothing currently distinguishes them. `created_at` is
enough; no new field.

Fix the deep-link gap here too: a queued **replacement**'s manager alert has no
link, because `TechnicianNotification` has only a `repair` FK (§0).

**Done when:** a manager who never opens a filter dropdown still finds the
queue, and the oldest thing in it is the most visible.

## Q6 · One provisional pick, in one place — TODO

`get_available_technician()` (`apps/customer_portal/views.py:2558`) is called
from at least three places to satisfy the non-null FK before the strategy runs,
and `quick_job.resolve_technician` hand-rolls its own version of the same idea.
Four spellings of "somebody has to go on this row" is how the Manual promise
got broken in the first place.

**Build:** one helper — a provisional pick that is always paired with the flag,
so it is impossible to write a placeholder onto a row without saying it is a
placeholder. Then `select_technician()` is the only thing that ever means "this
is a real choice."

**Done when:** every job-creation path takes its placeholder from one function,
and that function's docstring is the only place the non-null-FK workaround is
explained.
