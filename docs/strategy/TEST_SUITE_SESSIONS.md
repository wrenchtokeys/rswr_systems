# Test Suite Sessions — making 4,693 tests something anybody runs

**Created:** 2026-08-31
**Author:** Claude (working session with Drake)
**Status:** living document — update statuses and Notes as sessions complete
**Companions:** every other arc in `docs/strategy/` depends on this one and none
of them own it. `UI_MAGIC_SESSIONS.md` carries the "run the guard set, baseline
don't count" recipe that exists *because* of the problem this arc fixes.

**What this arc is for (the durable purpose statement):** this repo has 4,703
tests and **one of them runs in CI**. The full suite takes **80 minutes** on a
16-core laptop, single-process, and **96 of its tests fail on a clean `main`**.
Those three facts are one fact:

> A suite with known-red tests cannot be a merge gate. Because it is not a gate,
> nobody pays to keep it fast. Because it is slow, nobody runs it. Because
> nobody runs it, nobody notices the next red test.

Every arc in this repo has independently invented the same workaround — a
hand-picked "guard set" of five to ten modules, written down in prose, retyped
from notes each session. That workaround is load-bearing and it is also how
sessions lose an hour: see **Traps** below for the `$MODULES` incident that
prompted this file.

**The goal is not "fast tests".** It is that a merge is gated on something, that
the something is honest, and that a fresh session can find out whether it broke
anything in under two minutes without consulting anyone's memory.

Each session is self-contained — a fresh Claude session with no memory should be
able to execute exactly one session using only §0 and that session's table.

**Status legend:** `TODO · IN PROGRESS · DONE · DROPPED`

| Phase | Session | Size | Status |
|---|---|---|---|
| A — Make it honest | T1 · Triage the 96 failures on clean `main` | **L** | TODO |
| A — Make it honest | T2 · Run the suite in CI, advisory, parallel | M | TODO — **start here** |
| B — Make it fast | T3 · `--parallel` is broken locally (macOS `spawn`) | M | TODO |
| B — Make it fast | T4 · A cheap tenant factory | M | TODO |
| B — Make it fast | T5 · `setUp` → `setUpTestData` sweep | L | TODO |
| B — Make it fast | T6 · `SimpleTestCase` where there is no database | M | TODO |
| C — Make it findable | T7 · The guard set belongs in the repo, not in prose | S | TODO |

**Suggested sequence: T2 → T1 → T3, then stop and re-measure.**

This ordering flipped twice while the file was being written, both times because
a measurement contradicted the obvious answer. Recording that, because the next
person will have the same two instincts:

1. *"Fix the red first, nothing can gate on a red suite."* True, but 96 red
   tests triaged against an **80-minute** loop is a session nobody finishes.
2. *"Then make it fast first — `--parallel` is one flag."* Also true, and also
   wrong: **`--parallel` crashes outright on this machine the moment any test
   fails** (see T3). It cannot be the thing that rescues the triage, because
   the triage is exactly when tests are failing.

What breaks the deadlock is that **CI runs Linux and this laptop runs macOS**,
and the crash is very likely macOS-only. So T2 goes first: put the suite on a
Linux runner *with* `--parallel`, advisory, and let CI be the fast honest loop
that makes T1 survivable. If `--parallel` works there — the first CI run
answers this — the whole arc unblocks in one session.

**T1 gates the flip from advisory to required**; advisory CI can ship red, a
required check cannot. Everything in Phase B is a large mechanical edit whose
payoff should be measured against a CI wall-clock that actually exists, not
against a laptop under contention.

**Sizes:** S ≈ half a day · M ≈ 1–2 days · L ≈ 3–5 days.

---

# §0 — What a fresh session needs to know

## The measurements (2026-08-31, `origin/main` at `eb048a1e`)

Taken on this machine, 16 cores, SQLite. **Re-derive before trusting** — a
measurement in a strategy doc is a snapshot with no expiry date, and this repo
has already been burned by that once (`UI_MAGIC_SESSIONS.md`, the summary table
that carried "not yet on prod" for four days after the deploy).

| | |
|---|---|
| Test methods | 4,693 collected across 374 files |
| `TestCase` / `SimpleTestCase` / `TransactionTestCase` | 830 / 21 / 4 |
| `setUp` / `setUpTestData` | 706 / 56 |
| Test files that build a tenant | **203 of 374** |
| Migrations replayed per test-DB build | 204 |
| Fixed per-process cost | **~16s** before the first test runs |
| `test_tenant_branding` (representative) | 26 tests, **13.5s** — 0.52s/test |
| Full suite, serial | **4,799s — 80 minutes** |
| Tests running in CI | **1 module** (`test_migration_graph`) |
| Test tooling | none — plain Django runner, no pytest, no factory_boy |

## Where the time actually goes

Two places, and neither is "a few slow tests".

**1. Fixtures are rebuilt per test method.** 706 `setUp` against 56
`setUpTestData`. The archetype is `create_tenant_with_owner` — the *entire*
signup service path: tenant, owner user, plan lookup, subscription, notification
template seeding — called once per **test**, not once per class. 203 of 374 test
files do some version of this. At 0.52s a test in the module measured, this is
the whole curve.

`setUpTestData` runs once per class inside a transaction that is rolled back
between tests. A class with 8 tests goes from 8 tenant builds to 1.

**2. It runs on one core of sixteen.** `manage.py test` is single-process by
default. Django's `--parallel` clones the test database per worker.

**What it is NOT:** it is not the migrations. 204 migrations cost ~16s *once per
process*, and `--keepdb` will not help — see Traps.

## The 96 failures on clean `main`

**60 failures + 36 errors = 96**, measured 2026-08-31 on a detached worktree at
`origin/main` `eb048a1e`. Spread across **42 modules**, so this is not one broken
file — the twelve worst:

| module | red |
|---|---|
| `tests.bug_fixes.test_ux_fixes` | 12 |
| `tests.bug_fixes.test_code101_hardcoded_windshield_repair_stripe_description` | 9 |
| `tests.bug_fixes.test_code117_overdue_reminder_subject_format` | 5 |
| `tests.bug_fixes.test_code127_overdue_reminder_billing_email` | 4 |
| `tests.bug_fixes.test_code109_repair_deleted_at_index` | 4 |
| `tests.bug_fixes.test_code046_connect_setup_template_and_migration` | 4 |
| `tests.test_dashboard_revenue` | 4 |
| `tests.bug_fixes.test_code091_repair_form_unscoped_technician` | 3 |
| `tests.bug_fixes.test_code077_repair_views_unscoped_is_manager` | 3 |
| `tests.test_billing_phase6` | 3 |
| `tests.bug_fixes.test_code054_checkout_unpaid_double_payment` | 3 |
| `tests.bug_fixes.test_code190_dashboard_service_payment_tenant_filter` | 2 |

The full sorted list is reproducible in ~80 minutes:

```bash
git worktree add --detach ../rs_base origin/main
cd ../rs_base && python manage.py test tests 2>&1 \
  | grep -E "^(FAIL|ERROR): " | sort > /tmp/main_baseline.txt
```

**Note the shape.** Most of these live in `tests/bug_fixes/test_code*.py` — files
named for a ticket, written to prove one fix, and never revisited. 36 are
`ERROR`, not `FAIL`: those are not wrong assertions, they are tests that no
longer *run* — a signature changed, an import moved, a fixture drifted. An
`ERROR` is usually cheaper to triage than a `FAIL` and should go first.

They are load-bearing in the wrong way: their existence is the reason no arc has
ever proposed gating on the suite. **T1 is not optional, and at 96 across 42 modules
it is no longer an S.** It is *decide, per test, whether it is a real bug or a
stale assertion*, and record which. A test that is skipped with a reason and a ticket
is honest. A test that fails silently forever is not.

## Traps already paid for

**`--keepdb` is a no-op here.** Django's SQLite backend defaults the *test*
database to `:memory:`, so there is no file to keep and the 204 migrations are
replayed into memory on every run. Measured: 30.2s cold, 29.9s with `--keepdb`,
30.5s on a second `--keepdb` run. There is no `test_db.sqlite3` on disk to
confirm it either way — the absence of that file *is* the confirmation. On
Postgres `--keepdb` is real; that is one of the arguments for T2 using Postgres.

**`export` the module list, not just `MODULES=`.** The known recipe says to run
multi-module test commands under `bash -c` (zsh does not word-split an unquoted
`$MODULES`). That is half the fix. Without `export`, the variable does not cross
into the `bash -c` subshell, `$MODULES` expands to **nothing**, and
`manage.py test` silently runs the **entire suite** instead of the seven modules
you asked for. It does not error. It looks exactly like a hang. This cost
45 minutes on 2026-08-31 and is the direct reason T7 exists.

```bash
# wrong — runs all 4,703 tests, looks like a hang
MODULES="tests.test_a tests.test_b" && bash -c '... manage.py test $MODULES ...'

# right
export MODULES="tests.test_a tests.test_b" && bash -c '... manage.py test $MODULES ...'
```

**`--parallel` dies on the first failing test — locally.** Not "some tests fail":
the whole run produces nothing and exits. Green subsets are fine. Reproducer,
hypothesis and the plan are in T3; the practical rule until then is
**`--parallel` for a run you expect to be green, `--parallel 1` for anything
else.**

**Pipe every run through a filter.** Assertion messages in this repo dump whole
templates; a raw full-suite run overflows the tool-result buffer and silently
keeps only the tail. `| grep -E "^(FAIL|ERROR): |^Ran |^FAILED|^OK"`.

**Baseline, don't count.** With 96 red on a clean `main`, a raw failure count
from a branch tells you nothing at all. Diff the *sorted FAIL/ERROR lists*
against a detached worktree on `origin/main` (`git worktree add --detach`):

```bash
grep -E "^(FAIL|ERROR): " branch.txt | sort > b.txt
grep -E "^(FAIL|ERROR): " main.txt   | sort > m.txt
comm -23 b.txt m.txt   # regressions — the only output that matters
comm -13 b.txt m.txt   # things the branch fixed
```

**Budget 80 minutes per side, and run them one at a time.** Two full suites
side by side on this 16-core machine took 80 minutes each; the same two beside
two *accidental* ones (see the `$MODULES` trap) took closer to two hours. This
is the single most expensive routine operation in the repo, and T3 exists mostly
to make it stop being one.

**`amelia_test` does not authenticate on this machine.** CLAUDE.md's Postgres
creds do not work here. Plain SQLite is the default when neither `USE_AWS_DB`
nor `LOCAL_DATABASE_URL` is set (`rs_systems/settings/development.py:48-66`), so
the usual `export LOCAL_DATABASE_URL="sqlite:///db.sqlite3"` is belt-and-braces
rather than required — it matters only if a Postgres URL is already exported in
the shell profile.

---

# Phase A — Make it honest

## T1 · Triage the 96 failures on clean `main` — L

**Why it is second.** Nothing can gate on a red suite, which is what makes this
Phase A. But triage means running the suite over and over, and at 80 minutes a
run that is a session nobody finishes — so T2 goes first to buy a fast loop.

**You do not need the 80-minute run to triage.** You need it once, to produce the
list, and that has been done — the module breakdown is above and the command to
regenerate it is with it. Triage is then **per module, serially**, and a single
module answers in seconds: `tests.test_dashboard_revenue` is 15 tests in 6.5s.
Work down the list by module, largest first.

**Do:** run the full suite on a detached `origin/main` worktree, take the sorted
FAIL/ERROR list, and for each one decide:

- **real bug** → fix it, or open an issue and `@skip` with the issue in the reason
- **stale assertion** → rewrite it against what the code now does
- **environment-dependent** → make it skip on that condition explicitly, not by
  accident

**Do not** delete a failing test to make the count zero. The output of this
session is a suite where **red means red**, plus a written list of what was
skipped and why. That list goes in this file.

**Known starting point:** `tests/bug_fixes/test_ux_fixes.py` carries most of
them, and `UI_MAGIC_SESSIONS.md` already flags three `fa-*` assertions there that
are expected to be rewritten during the S13 icon sweep
(`test_wrench_icon_used_not_tools`, `test_ux_fixes:521`) — those two are *stale
assertion*, not bug, and the S13 sweep will land on them anyway. Coordinate or
they get fixed twice.

## T2 · Run the suite in CI — M

**Why this is the highest-value session in the arc.** It moves the cost off a
laptop onto a machine that is idle anyway, and it is the only change that makes
every *later* speedup worth doing. Today `.github/workflows/migration-graph.yml`
is the entire CI surface — one module, chosen because it had already burned four
PRs in a day. That workflow is the template: it is short, it explains itself in a
header comment, and it needs no services.

**Do:** a second workflow running the full suite on `pull_request`. Use a
**Postgres service container**, not SQLite — production is Postgres, `--keepdb`
is real there, and a suite that only ever runs on SQLite will eventually pass on
something Postgres rejects.

**The judgement calls a fresh session should not make alone:**

- **Required vs advisory.** Branch protection here already needs
  `gh pr merge N --squash --admin`. An **80-minute** required check would stop
  this repo dead — ~20 parallel worktrees cannot each wait out an hour and a
  half. Start advisory, and do not promote until T3 and Phase B have it under
  ~10 minutes. **The honest reading is that T2 and T3 are one session:** CI has
  no usable form here until the suite is parallel.
- **What to do about the ~20 worktrees.** This repo runs many parallel Claude
  sessions; a full-suite check on every push to every branch is a lot of CI
  minutes. `pull_request` only, not `push`, is the cheap answer.

**Run it with `--parallel` from the first build, and treat that build as an
experiment.** `--parallel` is broken on macOS here (T3) and the suspected cause
is the `spawn` start method, which Linux does not use. The first CI run either
comes back with results — in which case the arc is unblocked and T3 shrinks to
a local-only annoyance — or it comes back with `TypeError: cannot pickle
'traceback' object`, in which case T3 is a real blocker and gets promoted ahead
of T1. **Write which one happened into this file.**

**Verify** the way the migration-graph workflow was verified: open a PR that
deliberately breaks one test and confirm the check goes red before merging the
real thing. With 96 already red, also confirm the *opposite* — that an unchanged
branch reproduces exactly the 96 and not 97.

---

# Phase B — Make it fast

## T3 · `--parallel` is broken locally (macOS `spawn`) — M

**This is not "add a flag". It is a bug, and it is measured.**

`--parallel` works perfectly here as long as **everything passes**, and takes the
whole run down with it the moment **anything fails**:

```bash
# green modules — fine
python manage.py test --parallel 4 tests.test_view_transitions tests.test_icon_tag
#   Ran 28 tests in 3.400s / OK

# any module with a failing test — the entire run dies, no results at all
python manage.py test --parallel 4 tests.test_dashboard_revenue
#   TypeError: cannot pickle 'traceback' object
```

`tests.test_dashboard_revenue` is the 6-second reproducer. Its three reds are
ordinary `assertEqual` failures — nothing exotic — so this is not one weird test.
The full suite under `--parallel 8` produced **zero** output and exited in 20s.

**The hypothesis, with the evidence for it.** macOS defaults `multiprocessing` to
the **`spawn`** start method (confirmed: `mp.get_start_method()` → `spawn`), and
Django's `ParallelTestSuite` branches explicitly on that. Under `spawn` a
worker's result — including the exception's traceback — has to cross a process
boundary by pickle, and a traceback object cannot be pickled. Django has a
`check_picklable` guard for exactly this (`django/test/runner.py:207`) and it is
not catching this case. **Linux defaults to `fork`, so CI may well be unaffected**
— which is why T2 runs first and its first green build is the experiment that
settles it.

**Do:**

1. Find out whether CI (Linux, `fork`) has the bug at all. If not, this session
   is only about the local loop and drops to an S.
2. Locally: establish whether it is Django 5.1.2 + Python 3.13.4 specifically
   (both are recent), and whether a newer Django fixes it. Report upstream if it
   is genuinely Django's.
3. Whatever the outcome, **write the answer into `CLAUDE.md`**: today the honest
   local rule is *`--parallel` for a green run, `--parallel 1` when triaging*,
   and nobody knows that.

**And what `--parallel` will surface once it runs:** every test that depends on
shared mutable state — module-level caches, `django.core.cache` (LocMem is
per-process), files at a fixed path, any test assuming it is the only writer.
`TransactionTestCase` (4 here) does not roll back, so those are the first
suspects. Expect real isolation bugs that serial execution has been masking.

## T4 · A cheap tenant factory — M

`create_tenant_with_owner` is the **signup service**. It exists to be tested by
the handful of tests that are about signup. The other ~200 files calling it need
"a tenant exists", and are paying for plan lookup, subscription creation and
notification-template seeding to get it.

**Do:** a test helper that inserts the rows directly — `Tenant`, one owner
`User`, a plan — with no service-layer work, and switch the tests that only need
a tenant to exist. Leave the signup tests on the real path; that path is the
thing they assert.

**The trap:** a factory that drifts from what signup actually produces gives you
green tests against a tenant shape production never creates. Pin it with one test
that builds a tenant both ways and asserts the rows match on the fields anything
else reads.

## T5 · `setUp` → `setUpTestData` sweep — L

706 → 56 is the ratio to move. Mechanical, but **not blind**: `setUpTestData`
objects are class-level, and a test that mutates one would leak into its
siblings. Django wraps them so each test gets a deepcopy on attribute access,
which covers most cases and not all — anything holding a reference across the
class boundary, or mutating through a related manager, needs reading.

**Do it per-module, largest first**, and re-run that module before and after —
the win should be visible as wall-clock per module, and if it is not, the module
was not fixture-bound and should be left alone. Biggest by test count:
`test_warranty.py` (85), `bug_fixes/test_ux_fixes.py` (84),
`bug_fixes/test_tenant_scoping.py` (64), `test_admin.py` (57),
`bug_fixes/test_billing_fixes.py` (52).

**Do T4 first** — a cheap factory makes some of this sweep unnecessary, and
doing them in the other order means editing the same 706 methods twice.

## T6 · `SimpleTestCase` where there is no database — M

21 of 855 test classes today. A `TestCase` that never queries still pays for the
DB machinery; a `SimpleTestCase` raises on any query, which makes it an
**assertion** as well as a speedup.

The pattern is already in the repo — `tests/test_csp.py` (UI_MAGIC S18a) moved
five of its six classes and runs 37 tests in ~0.5s. Its `ReportEndpointTests` is
the case worth copying: `/csp-report/` is unauthenticated, CSRF-exempt and
postable in a loop by anyone, so a database round-trip on that path would be a
denial-of-service lever. `SimpleTestCase` is what keeps it that way.

**Candidates are cheap to find** — pure-function tests (`BrandShadesTests` in
`test_tenant_branding.py` is one), template-markup assertions that read files off
disk, and settings/policy assertions. Convert, run, and let the runner tell you:
a class that needed the DB fails immediately and loudly.

---

# Phase C — Make it findable

## T7 · The guard set belongs in the repo, not in prose — S

Today the fast set is a list of module paths living in prose and in session
memory, retyped by hand each time. That is how the `$MODULES` incident happened,
and it will happen again.

**Do:** make it a thing the tooling knows. Options, cheapest first:

1. **A `scripts/test_guards.sh`** holding the list, with the `export` already
   correct and the output already piped through the filter. One line to run, no
   retyping. Fits how this repo does everything else (`scripts/build_css.sh`,
   `scripts/vendor_assets.sh`).
2. A `tests/guards/` package that imports or re-exports the guard modules, so
   `manage.py test tests.guards` is the whole command.

**Whichever it is, CLAUDE.md gets the one-line command** and the session docs
stop carrying module lists. The guard set as of 2026-08-31 — 162 tests, ~39s serial,
green on `eb048a1e`, and safe to run `--parallel` precisely because it is green:

```
tests.test_css_pipeline tests.test_photo_blind_focus tests.test_landing_visibility
tests.test_migration_graph tests.test_view_transitions tests.test_mobile_touch_targets
tests.test_icon_tag tests.test_csp tests.test_notification_surfaces
tests.test_tenant_branding
```

---

# Where this stands — 2026-08-31

Nothing in this arc has been started. The file exists because a UI_MAGIC S18a
session lost 45 minutes to the `$MODULES` trap and, in working out why,
measured the suite properly for the first time.

**The one number that matters:** 4,693 tests, 1 in CI, 96 of them red.
Everything else in this file is downstream of that.

**Two claims in this file were wrong in its first draft and are worth keeping
as a warning.** It was drafted saying the suite took "north of twenty minutes"
and had "12 failures" — both from estimate and from a half-remembered note
scoped to a single file. The real numbers, measured the same evening, are
**80 minutes** and **96**. Everything downstream — T1's size, the whole session
order — changed when they landed. **Do not re-plan this arc from the prose here;
re-run the measurement.**

**Start with T2.** Both obvious alternatives were tried on paper and killed by a
measurement — the red-first instinct dies on the 80-minute loop, and the
fast-first instinct dies on `--parallel` crashing whenever a test fails. CI is
the way out because it is Linux, and the bug looks like it is macOS's.
