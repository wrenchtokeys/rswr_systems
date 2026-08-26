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
| Q — The queue exists | Q2 · The Unassigned queue (CODE-279) | M | DONE (2026-08-26, **working tree only, uncommitted**) |
| R — The queue drains | Q3 · Approving a queued job takes it | S | TODO — needs a product decision first |
| R — The queue drains | Q4 · Telling managers outside the dashboard | S | TODO |
| R — The queue drains | Q5 · Where managers actually live: board + aging | M | TODO |
| R — The queue drains | Q6 · One provisional pick, in one place | S | TODO |

**Suggested sequence:** Q3 → Q4 → Q5 → Q6. Q3 first because it is the only one
that is currently a *correctness* gap rather than a reach gap — three code paths
still test `if not job.technician` on a non-null FK, so they are dead branches
that read as working code. Q4 before Q5 because a queue nobody is told about
does not drain no matter how good the board is. Q6 is cleanup and can slip.

**Sizes:** S ≈ half a day · M ≈ 1–2 days · L ≈ 3–5 days.

**Where we are (2026-08-26, after Q2):** Q1 is committed and pushed on
`fix/job-assignment-round-robin` (worktree `~/projects/rs_assign_wt`); **no PR
has been opened for either session.** Q2 is built and green but sits
uncommitted in that worktree: 10 modified files, migration
`0058_add_needs_assignment`, and `tests/bug_fixes/test_code279_unassigned_queue.py`
(27 tests). Verified this session on sqlite: the 27 new tests pass, 44 tests
across the eight adjacent assignment regression modules pass, and
`test_fieldops_s5 / s9 / s10 / n1 / unified_job_list` are 117 green after fixing
one real defect found in the run — see Q2 Notes, "What the test run caught."

## How to run a session

1. Cut a fresh branch off the latest `main`: `feat/jobqueue-<id>-<slug>`. Never
   stack on another session's branch. Print `git branch --show-current` before
   every test run — other Claude sessions share this checkout's neighbours.
   **Q3–Q6 depend on Q2's migration**, so until Q2 is merged, branch from Q2's
   branch and say so in the PR body.
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

**The flag settles itself.** `GlassService._settle_needs_assignment()`
(`models.py`, called first thing in both `Repair.save()` and
`Replacement.save()`) clears the flag whenever `technician_id` differs from the
value loaded in `__init__`. So the job form, the approve action, the Django
admin, batch reassign and `services.assignments.assign_job` all clear it
without knowing it exists — and none of them can forget. **Saves that pass
`update_fields` get `needs_assignment` appended**, or the clear would happen in
memory and never reach the database. If you add an assignment surface, you get
this for free; if you write to `technician` with raw SQL or `.update()`, you do
not.

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
**Dashboard rows only — no bell, no email**: that path needs a
`NotificationTemplate`, and none is seeded for this event. That is Q4.

**Where the flag is visible today.**

| Surface | File | What it shows |
|---|---|---|
| Job list filter | `views/jobs.py:155` + `job_list.html:230` | the "Needs assignment" option — it filtered `technician__isnull=True` and therefore matched **nothing** until Q2 |
| Job list rows | `job_list.html` (card + table) | amber "Needs assignment" chip in the technician column |
| Repair detail | `repair_detail.html:408` | amber chip beside the technician name, tooltip explains the placeholder |
| Dispatch board rows | `includes/schedule_row.html` | amber chip, manager-only (`can_assign`) |
| Owner settings | `saas/owner_settings.html:287` | Manual and Primary-First descriptions now link to the queue |
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

**Shipped:** commit `6a199b84` on `fix/job-assignment-round-robin`, pushed. No PR.

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

## Q2 · The Unassigned queue — DONE (2026-08-26), uncommitted

**State:** built, 27 new tests green, **not committed**. Files: `models.py`,
`services/assignments.py`, `services/dispatch.py`, `services/quick_job.py`,
`views/jobs.py`, `tenants/services/assignment_service.py`, four templates,
migration `0058`, `tests/bug_fixes/test_code279_unassigned_queue.py`.

Two product decisions, both Drake's, each chosen from three options offered:

1. **Queue → "flag, don't nullify."** A nullable `technician` would have meant
   ~210 references and 45 `technician__` lookups going nullable — too
   expensive, and every one of them a chance to leak an empty technician into
   an invoice. The row keeps its provisional tech; the flag means nobody chose
   them. See §0.
2. **In-app creation → "your own job stays yours."**
   `quick_job.resolve_technician` now returns `(tech, needs_assignment)` and
   goes: the actor's own profile *if `_can_perform` says they can do this kind
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
- `_can_perform` treats an inactive or ability-less profile as *cannot*, so the
  actor falls through to the strategy rather than taking the job. Assigning
  work to a deactivated tech is CODE-160 from the other direction.

## Q3 · Approving a queued job takes it — TODO (needs a product decision)

**The gap.** Three paths still branch on a non-null FK and are therefore dead
code that reads as working code:

- `apps/technician_portal/views/repairs.py:1218` — bulk approve:
  `if repair.queue_status == 'REQUESTED' and not repair.technician and technician`
- `apps/saas/views.py:1259` — replacement create: `if not replacement.technician_id`
- `apps/technician_portal/views/repairs.py:395` — repair create "safety net":
  `if not repair.technician_id`

Rewriting the first as `if repair.needs_assignment` would make it live, and
that means **"approving a queued job assigns it to whoever approved it."**
That is a third product decision, not covered by Q2's two, and it is a real
fork: for a dispatcher who approves everything, it silently makes every queued
job theirs — the opposite of what Manual is for.

**Decide first, then build.** Options worth putting to Drake:
(a) approving takes the job (fastest for one-person shops, wrong for
dispatchers); (b) approving leaves it queued and approval never assigns
(purest, but "approve" then feels incomplete); (c) approving takes it **only
when the approver can actually perform the work** (`_can_perform` already
exists) — a dispatcher who can't repair leaves it queued.

The other two branches are less loaded: `saas/views.py:1259` should call
`auto_assign_replacement` on the flag rather than the FK, and `repairs.py:395`
is a genuine safety net that has never fired and can either become
flag-aware or be deleted.

**Done when:** each of the three branches is either live and tested or removed
with a comment saying why, and no `if not <job>.technician` remains in an
assignment path. Grep for it — that shape is this arc's recurring bug.

## Q4 · Telling managers outside the dashboard — TODO

Queued jobs currently produce a `TechnicianNotification` dashboard row and
nothing else — no bell, no email — because `notify_needs_assignment` has no
`NotificationTemplate` to render. A shop that doesn't open the dashboard on a
given afternoon never learns a customer request is waiting.

**Build:** seed a `needs_assignment` (name it for the event, not the audience)
`NotificationTemplate` and route the alert through `NotificationService` like
every other real event. **Read `FIELD_OPS_SESSIONS.md` §N1/N3 first** — the
priority→channel map decides whether email is even possible: HIGH yields
`['in_app','sms']` and no email ever; MEDIUM yields `['in_app','email']`;
URGENT yields all three. Audience is decided by the call site, not the template
name. `tests/test_fieldops_n3.py` guards the inventory table.

**Watch for:** one email per break. The batch de-dup in Q2 is per-`repair_batch_id`
and unread-scoped; the template path needs the same rule or a six-break request
becomes six emails.

**Done when:** a queued job reaches a manager who never opened the app, exactly
once per customer request, and `tests/test_fieldops_n3.py`'s inventory lists
the new event.

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
