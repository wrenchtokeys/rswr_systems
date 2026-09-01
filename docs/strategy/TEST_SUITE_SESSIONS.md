# Test Suite Sessions — making 4,730 tests something anybody runs

**Created:** 2026-08-31
**Revised:** 2026-09-01 — T3 is done, and it changed the order of everything else
**Author:** Claude (working session with Drake)
**Status:** living document — update statuses and Notes as sessions complete
**Companions:** every other arc in `docs/strategy/` depends on this one and none
of them own it. `UI_MAGIC_SESSIONS.md` carries the "run the guard set, baseline
don't count" recipe that exists *because* of the problem this arc fixes.

> **Read this before the rest of the file.** This document was written on
> 2026-08-31 and its central sequencing argument was **wrong**, for one reason:
> the `--parallel` crash that shaped the whole plan is fixed by
> `pip install tblib`, which Django's own crash output names and this file's
> first draft did not try. That landed 2026-09-01. **The suite now runs in 16
> minutes, on this laptop, today.** Every "80 minutes" argument below has been
> rewritten; if you find one that survived, it is a bug in this file. The
> lesson is the one the file already tried to teach itself at the bottom: do
> not re-plan from the prose, re-run the measurement.

**What this arc is for (the durable purpose statement):** this repo has 4,730
tests in `tests/` and **one of them runs in CI**. **93 of them fail on a clean
`main`.** Those two facts are one fact:

> A suite with known-red tests cannot be a merge gate. Because it is not a gate,
> nobody pays to keep it fast. Because it is slow, nobody runs it. Because
> nobody runs it, nobody notices the next red test.

The speed half of that loop is now broken — 16 minutes is a coffee, not a
morning. **What is left is the honesty half, and it is the whole job.**

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
| B — Make it fast | T3 · `--parallel` crashes on the first failing test | ~~M~~ **XS** | **DONE 2026-09-01** — `tblib` |
| C — Make it findable | T7 · The guard set belongs in the repo, not in prose | S | TODO — **start here** |
| A — Make it honest | T2 · Run the suite in CI, advisory, parallel | S–M | TODO |
| A — Make it honest | T1 · Triage the 93 failures on clean `main` | **L** | TODO |
| B — Make it fast | T3b · The isolation bugs `--parallel` exposed | M | TODO |
| B — Make it fast | T4 · A cheap tenant factory | M | **HOLD — re-measure first** |
| B — Make it fast | T5 · `setUp` → `setUpTestData` sweep | L | **HOLD — re-measure first** |
| B — Make it fast | T6 · `SimpleTestCase` where there is no database | M | **HOLD — re-measure first** |

**Suggested sequence: T7 → T2 → T1, then stop and re-measure before any of
Phase B.**

**The old order was T2 → T1 → T3, and the argument for it is dead.** It ran:
triage-first dies on the 80-minute loop, fast-first dies on `--parallel`
crashing, so CI-on-Linux is the only way out. Both premises were false. T3 was
a `pip install`, the loop is 16 minutes locally, and CI is no longer the thing
that rescues the triage — it is just the thing that stops the next red test
arriving. Note what actually broke the deadlock: **not more planning. Running
the failing command once and reading its last four lines**, which say
`In order to see the traceback, you should install tblib`.

Why the current order:

1. **T7 first because it is half a day and it is the only session that pays out
   on the day it lands.** Every other arc in `docs/strategy/` is retyping module
   lists right now; the `$MODULES` trap below has already cost 45 minutes once
   and will again. It also has no dependencies.
2. **T2 second because it is now S–M, not M.** With `--parallel` working, a
   16-minute advisory check on `pull_request` is a short workflow file. It stops
   the *next* red test landing, which is what makes T1 finite work instead of
   a moving target.
3. **T1 third, and it is still an L.** 93 tests across 41 modules, decided one
   at a time. It is now survivable — a single module answers in seconds and the
   whole suite in 16 minutes — but nothing made it *small*.

**T1 still gates the flip from advisory to required**; advisory CI can ship red,
a required check cannot.

**Phase B is on hold, deliberately.** T4/T5/T6 are ~8 days of mechanical edits
justified against an 80-minute suite that no longer exists. At 16 minutes the
payoff is unproven, and this file's own rule applies to itself: re-measure
before spending the week. What was Phase B's *unexamined* benefit — that
`--parallel` would surface tests depending on shared mutable state — turned out
to be real and is now T3b, on evidence (see §0).

**Sizes:** XS ≈ under an hour · S ≈ half a day · M ≈ 1–2 days · L ≈ 3–5 days.

---

# §0 — What a fresh session needs to know

## The measurements (2026-09-01, `origin/main` at `6ad8b59d`)

Taken on this machine, 16 cores, SQLite, Django 5.1.2 / Python 3.13.4.
**Re-derive before trusting** — a measurement in a strategy doc is a snapshot
with no expiry date, and this repo has already been burned by that twice: once
in `UI_MAGIC_SESSIONS.md` (the summary table that carried "not yet on prod" for
four days after the deploy), and once by *this file*, whose first draft was
planned around an 80-minute number that a `pip install` deleted the next day.

| | |
|---|---|
| Test methods in `tests/` | 4,730 across 367 files |
| **Test methods outside `tests/`** | **496** — `core/tests/`, `apps/billing/tests/`, `apps/*/tests.py` |
| Everything `manage.py test` discovers | **5,226** |
| `TestCase` / `SimpleTestCase` / `TransactionTestCase` | 880 / 21 / 4 |
| `setUp` / `setUpTestData` | 705 / 56 |
| Test files that create a tenant | **315 of 367** (54 of them via `create_tenant_with_owner`) |
| Migrations replayed per test-DB build | 204 |
| Fixed per-process cost | **~16s** before the first test runs |
| `test_tenant_branding` (representative) | 26 tests, **13.5s** — 0.52s/test |
| Full suite, serial | 4,799s — **80 minutes** |
| **Full suite, `--parallel 8`** | **967s — 16 minutes** (5× faster) |
| Red on clean `main` | **93** (57 failures + 36 errors) across 41 modules |
| Tests running in CI | **1 module** (`test_migration_graph`) |
| Test tooling | plain Django runner + `tblib`. No pytest, no factory_boy |
| Merged PRs, Aug 2026 | **104** — ~3.5/day, gated on nothing |

**The suite grew ~1,200 tests in three weeks.** `UI_MAGIC_SESSIONS.md` measured
3,507 tests / 66 min / ~103 red on 2026-08-09; this is 4,730 / 16 min / 93 red
on 2026-09-01. Red count is flat, which is the good news, and the denominator is
climbing fast, which is why T1 gets more expensive every week it waits.

**`tests/` is not the whole suite.** `manage.py test tests` — the command in
every recipe in this repo, including the ones below — silently skips 496 test
methods that live next to the apps. `manage.py test` with no label discovers all
5,226. This is a documented choice in CLAUDE.md ("the canonical suite is under
`tests/`"), and it is fine for a smoke run, but **a merge gate that runs
`tests` gates 90% of the suite and calls it the suite.** Decide this explicitly
in T2.

## Where the time actually goes

Two places, and neither is "a few slow tests". **The second one is now fixed**,
which is why Phase B is on hold rather than in progress.

**1. Fixtures are rebuilt per test method.** 705 `setUp` against 56
`setUpTestData`. The archetype is `create_tenant_with_owner` — the *entire*
signup service path: tenant, owner user, plan lookup, subscription, notification
template seeding — called once per **test**, not once per class. 315 of 367 test
files create a tenant some way. At 0.52s a test in the module measured, this is
the whole curve.

`setUpTestData` runs once per class inside a transaction that is rolled back
between tests. A class with 8 tests goes from 8 tenant builds to 1.

**This is still true and it is still worth money — but it is no longer urgent,
and the arithmetic has to be redone.** T4/T5 were sized against 80 minutes. They
are now competing with 16, on a suite where the 16 is mostly *good enough*, and
the parallel runner has already collected the easy factor of five. Measure one
module before committing to the sweep.

**2. ~~It runs on one core of sixteen.~~ FIXED 2026-09-01.** `manage.py test` is
single-process by default and `--parallel` was unusable (T3). With `tblib`
installed, `--parallel 8` takes the full suite from **4,799s to 967s**. This was
one line in `requirements.txt`.

**What it is NOT:** it is not the migrations. 204 migrations cost ~16s *once per
process*, and `--keepdb` will not help — see Traps. Note this cost is now paid
*per worker*: at `--parallel 8` the fixed cost is ~16s × 8 in CPU, still ~16s in
wall-clock, and it is why `--parallel 8` gives 5× rather than 8×.

## The 93 failures on clean `main`

**57 failures + 36 errors = 93**, measured 2026-09-01 at `origin/main`
`6ad8b59d`, `--parallel 8`. Spread across **41 modules**, so this is not one
broken file — the worst twelve:

| module | red |
|---|---|
| `tests.bug_fixes.test_ux_fixes` | 12 |
| `tests.bug_fixes.test_code101_hardcoded_windshield_repair_stripe_description` | 9 |
| `tests.bug_fixes.test_code117_overdue_reminder_subject_format` | 5 |
| `tests.bug_fixes.test_code127_overdue_reminder_billing_email` | 4 |
| `tests.bug_fixes.test_code109_repair_deleted_at_index` | 4 |
| `tests.bug_fixes.test_code046_connect_setup_template_and_migration` | 4 |
| `tests.test_dashboard_revenue` | 3 |
| `tests.test_billing_phase6` | 3 |
| `tests.bug_fixes.test_code091_repair_form_unscoped_technician` | 3 |
| `tests.bug_fixes.test_code077_repair_views_unscoped_is_manager` | 3 |
| `tests.bug_fixes.test_code054_checkout_unpaid_double_payment` | 3 |
| `tests.test_ux004_005_fixes` | 2 |

**The full sorted list is committed at `docs/strategy/test_baseline_main.txt`.**
Do not regenerate it to find out what is red — read it. Regenerate it (16
minutes) only when you have *changed* what is red:

```bash
python manage.py test --parallel 8 tests 2>&1 \
  | grep -E "^(FAIL|ERROR): " | sort > mine.txt
comm -23 mine.txt <(grep -v '^#' docs/strategy/test_baseline_main.txt)  # regressions
```

**Note the shape.** Most of these live in `tests/bug_fixes/test_code*.py` — files
named for a ticket, written to prove one fix, and never revisited. That directory
is now **239 files and 2,093 test methods**, 44% of the suite, and 20 more files
landed in the last 60 days. 36 of the 93 are `ERROR`, not `FAIL`: those are not
wrong assertions, they are tests that no longer *run* — a signature changed, an
import moved, a fixture drifted. An `ERROR` is usually cheaper to triage than a
`FAIL` and should go first.

**The red set is flag-dependent, and that is itself a finding.** The same tree
run serially produced **91** red (60F + 31E at `eb048a1e`); under `--parallel 8`
it is **93** (57F + 36E). Tests moved between the two runs in both directions.
That delta is not noise — it is tests that depend on execution order or on being
the only writer, which serial execution has been hiding. See **T3b**. The
practical consequence for T1: **take your baseline under the same flags you will
gate under**, or you will triage a moving target.

They are load-bearing in the wrong way: their existence is the reason no arc has
ever proposed gating on the suite. **T1 is not optional, and at 93 across 41
modules it is an L.** It is *decide, per test, whether it is a real bug or a
stale assertion*, and record which. A test that is skipped with a reason and a
ticket is honest. A test that fails silently forever is not.

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
# wrong — runs all 4,730 tests, looks like a hang
MODULES="tests.test_a tests.test_b" && bash -c '... manage.py test $MODULES ...'

# right
export MODULES="tests.test_a tests.test_b" && bash -c '... manage.py test $MODULES ...'
```

**If `--parallel` dies with `cannot pickle 'traceback' object`, your venv is
stale.** `tblib` is in `requirements.txt` as of 2026-09-01; `pip install -r
requirements.txt` and it goes away. Read T3 before concluding anything else
about this — it looks exactly like a Django bug and is not one.

**Read the last four lines of a crash before theorising about it.** This is the
trap that cost the most in this arc, and it was not a shell quoting bug or a
platform bug: it was that the first draft of this file diagnosed the
`--parallel` crash from the *traceback* and built a whole session ordering on
the diagnosis, while the four lines Django printed *underneath* the traceback
said `In order to see the traceback, you should install tblib`. A day of
planning, one `pip install`. When a tool crashes, read all of what it said.

**Pipe every run through a filter.** Assertion messages in this repo dump whole
templates; a raw full-suite run overflows the tool-result buffer and silently
keeps only the tail. `| grep -E "^(FAIL|ERROR): |^Ran |^FAILED|^OK"`.

**Baseline, don't count.** With 93 red on a clean `main`, a raw failure count
from a branch tells you nothing at all. The baseline is committed — diff against
`docs/strategy/test_baseline_main.txt` rather than building a second worktree:

```bash
python manage.py test --parallel 8 tests 2>&1 \
  | grep -E "^(FAIL|ERROR): " | sort > mine.txt
BASE=$(mktemp); grep -v '^#' docs/strategy/test_baseline_main.txt > $BASE
comm -23 mine.txt $BASE   # regressions — the only output that matters
comm -13 mine.txt $BASE   # things the branch fixed
```

Compare like with like: that file was taken at `--parallel 8` on SQLite. A
serial run or a Postgres run will differ by a handful of tests for reasons that
have nothing to do with your branch.

**Budget 16 minutes a side, not 80.** Two full suites side by side on this
16-core machine used to take 80 minutes each. `--parallel 8` makes a full run
routine — but two *parallel* suites at once will contend for all 16 cores, so
still run them one at a time.

**`amelia_test` does not authenticate on this machine.** CLAUDE.md used to
export those Postgres creds at the top of its Running Tests section; that block
is gone as of 2026-09-01. Plain SQLite is the default when neither `USE_AWS_DB`
nor `LOCAL_DATABASE_URL` is set (`rs_systems/settings/development.py:48-66`), so
export a database URL only if you specifically want Postgres — and note that a
stale Postgres URL in your shell profile will silently redirect the run.

---

# Phase A — Make it honest

## T1 · Triage the 93 failures on clean `main` — L

**Why it is third.** Nothing can gate on a red suite, which is what makes this
Phase A. It is last of the three only because T7 and T2 are half-day sessions
that make this one cheaper and stop it being re-run work — not because it is
optional. It is the session this arc exists for.

**You do not need to run the full suite to triage.** The list is committed at
`docs/strategy/test_baseline_main.txt`. Triage is **per module**, and a single
module answers in seconds: `tests.test_dashboard_revenue` is 15 tests in 6.5s.
Work down the module breakdown above, largest first. A full re-run to confirm
you have not moved anything else costs 16 minutes, so take one at the end of
each working session rather than after each fix.

**Do:** for each failing test, decide:

- **real bug** → fix it, or open an issue and `@skip` with the issue in the reason
- **stale assertion** → rewrite it against what the code now does
- **environment-dependent** → make it skip on that condition explicitly, not by
  accident

**Do not** delete a failing test to make the count zero. The output of this
session is a suite where **red means red**, plus a written list of what was
skipped and why. That list goes in this file, and
`docs/strategy/test_baseline_main.txt` shrinks as you go — a baseline that never
moves is a licence to ignore red.

**Take your working baseline under the flags you will gate under.** The red set
differs by a handful of tests between serial and `--parallel 8` (see §0). Pick
one — `--parallel 8`, matching the committed baseline — and stay on it, or you
will spend the session chasing tests that were never yours.

**Known starting point:** `tests/bug_fixes/test_ux_fixes.py` carries most of
them, and `UI_MAGIC_SESSIONS.md` already flags three `fa-*` assertions there that
are expected to be rewritten during the S13 icon sweep
(`test_wrench_icon_used_not_tools`, `test_ux_fixes:521`) — those two are *stale
assertion*, not bug, and the S13 sweep will land on them anyway. Coordinate or
they get fixed twice.

**A note on where these come from, because it decides whether T1 is worth
repeating.** 44% of this suite is `tests/bug_fixes/test_code*.py`: one file per
ticket, written to prove one fix, never revisited, and 20 more arrived in the
last 60 days. That is a good instinct — every one of them is a regression that
cannot silently come back — but the files accrete assertions about *incidental*
detail (a subject line's exact wording, an icon class, a template fragment)
which is what rots. If T1 triage keeps finding the same shape, the follow-up
worth proposing is a convention for those files, not another sweep.

## T2 · Run the suite in CI — S–M

**Why it is worth doing even though the local loop is now fast.** A 16-minute
laptop run only helps the person who remembers to run it, and this repo merged
104 PRs in August across ~20 parallel worktrees. CI is what makes "did this
branch break something" a fact attached to the PR rather than a thing somebody
did or didn't do. It is also what stops T1's triage being re-run work: without a
gate, tests go red faster than one session can fix them.

Today `.github/workflows/migration-graph.yml` is the entire CI surface — one
module, chosen because it had already burned four PRs in a day. That workflow is
the template: it is short, it explains itself in a header comment, and it needs
no services.

**Do:** a second workflow running the full suite with `--parallel` on
`pull_request`. It is now a short file: no experiment, no unknowns, ~16 minutes
of runner time.

**Start on SQLite, not Postgres — this reverses what this file said on
2026-08-31.** The original argument for a Postgres service container is sound in
the long run (production is Postgres, `--keepdb` is real there, and a
SQLite-only suite will eventually pass something Postgres rejects) but it
contradicted this session's own verification step, which asks you to confirm an
unchanged branch reproduces *exactly* the known baseline. Changing the backend
is precisely what changes that set. So:

1. **First workflow: SQLite**, matching `test_baseline_main.txt`. Its job is to
   reproduce 93 and nothing else. That is a check you can reason about on day
   one.
2. **Then a second, separate Postgres job**, also advisory, whose failures mean
   *"SQLite was hiding this"* rather than *"you broke something"*. Kept apart,
   that job is a source of real bugs. Merged into the first, it is noise that
   makes the whole check unreadable and un-promotable.

**The judgement calls a fresh session should not make alone:**

- **What the gate actually runs.** `manage.py test tests` skips 496 test methods
  outside `tests/` (§0). Either run bare `manage.py test` and accept a new set
  of red to triage, or run `tests` and say so in the workflow's header comment.
  Do not leave it implicit. **Recommendation: gate on `tests` now, add the rest
  as a second advisory job**, same shape as the Postgres split.
- **Required vs advisory.** Branch protection here already needs
  `gh pr merge N --squash --admin`. Start advisory — a required check cannot go
  in front of 93 known-red tests, and that is T1's job to clear, not this
  session's. But note the wall-clock objection is gone: **16 minutes is a
  promotable check**, and the old "not until Phase B has it under ~10 minutes"
  condition should not be treated as binding. T1 is the only real gate on
  promotion.
- **Cost is not a constraint here.** `wrenchtokeys/rswr_systems` is a **public**
  repo, so GitHub Actions standard runners are free and unmetered. The
  2026-08-31 worry about "~20 worktrees costing a lot of CI minutes" was
  unfounded. The live limit is 20 concurrent jobs, and this repo merged 104 PRs
  in August (~3.5/day) — nowhere near it. `pull_request` only (not `push`) is
  still right, but for noise, not for money.

**Verify** the way the migration-graph workflow was verified: open a PR that
deliberately breaks one test and confirm the check goes red before merging the
real thing. With 93 already red, also confirm the *opposite* — that an unchanged
branch reproduces exactly 93 and not 94. Note that CI is Linux (`fork`) and the
baseline was taken on macOS (`spawn`); if the counts differ by a test or two,
that is T3b, not your workflow.

---

# Phase B — Make it fast

## T3 · `--parallel` crashes on the first failing test — DONE 2026-09-01

**The whole fix was one line in `requirements.txt`:** `tblib>=3.0`.

**The symptom.** `--parallel` worked as long as everything passed, and took the
whole run down with it the moment anything failed — no results, exit in seconds:

```bash
python manage.py test --parallel 4 tests.test_dashboard_revenue
#   TypeError: cannot pickle 'traceback' object
```

**The mechanism**, which the 2026-08-31 draft had essentially right: macOS
defaults `multiprocessing` to **`spawn`** (`mp.get_start_method()` → `spawn`), so
a worker's result — including the exception's traceback — crosses the process
boundary by pickle, and a traceback object cannot be pickled.

**What the draft got wrong is that it stopped reading.** Django knows about this
and prints the fix in the four lines *after* the traceback:

```
Unfortunately, tracebacks cannot be pickled, making it impossible for the
parallel test runner to handle this exception cleanly.

In order to see the traceback, you should install tblib:
    python -m pip install tblib
```

`tblib` makes tracebacks picklable; Django's runner uses it automatically when
it is importable. This is not a Django bug, not macOS-specific, and not
version-specific. **A day of session planning was built on the assumption that
it was, and the entire ordering of this arc followed from that assumption.**

**Verified, in this order:**

| | |
|---|---|
| Reproducer before | `--parallel 4 tests.test_dashboard_revenue` → `TypeError`, no results |
| Reproducer after | same command → `Ran 15 tests in 7.9s / FAILED (failures=3)` |
| Full suite before | 4,799s serial (`--parallel` unusable) |
| Full suite after | **967s at `--parallel 8`** — 4,730 tests, 93 red |

**Landed:** `tblib>=3.0` in `requirements.txt` with the reasoning in a comment,
and the Running Tests section of `CLAUDE.md` rewritten around `--parallel 8`
(it had said "~331 tests, ~7 min" and exported Postgres creds that do not
authenticate — both years-stale). Anyone hitting the old crash has a stale venv:
`pip install -r requirements.txt`.

## T3b · The isolation bugs `--parallel` exposed — M

The 2026-08-31 draft predicted this and it is now evidence rather than
prediction: **the same tree gives 91 red serially and 93 red at `--parallel 8`**,
with tests moving in both directions. Some of this suite depends on execution
order or on being the only writer.

**The suspects, cheapest first:** `django.core.cache` (LocMem is per-process, so
a test that warms a cache another test reads is order-dependent), module-level
caches and singletons, files written to a fixed path, and the 4
`TransactionTestCase` classes — those do not roll back, so anything they leave
behind is visible to whatever runs next in that worker.

**Do:** diff a serial and a parallel run of the same commit, take the symmetric
difference, and fix those tests — not by pinning execution order, but by making
each one create and tear down what it needs. **Do this before T1, or during it**:
a test that is red only under one runner will otherwise be triaged as a real bug,
which is a wasted afternoon.

**Do not** treat this as a reason to go back to serial. A 5× speedup that also
surfaces real isolation bugs is two wins; the bugs were always there.

> **T4, T5 and T6 are on HOLD as of 2026-09-01.** They are ~8 days of mechanical
> edits, and every argument for them was sized against an 80-minute suite that
> `tblib` turned into 16. The reasoning below is still correct — fixtures really
> are rebuilt per test method, and that really is where the remaining time goes
> — but "correct" and "worth a week" are different claims, and only the first
> one has been established. **Before starting any of these: pick one module,
> measure it, do the change, measure again.** If a module-level win does not
> extrapolate to something you would trade a week for, the honest answer is that
> the suite is now fast enough and this arc ends at T1.
>
> T6 is the exception worth reading twice: it is a *correctness* change that
> happens to be faster, so it does not need the speed argument at all.

## T4 · A cheap tenant factory — M · HOLD

`create_tenant_with_owner` is the **signup service**. It exists to be tested by
the handful of tests that are about signup. 54 test files call it directly and
315 of 367 create a tenant somehow — the ones that just need "a tenant exists"
are paying for plan lookup, subscription creation and notification-template
seeding to get it.

**Do:** a test helper that inserts the rows directly — `Tenant`, one owner
`User`, a plan — with no service-layer work, and switch the tests that only need
a tenant to exist. Leave the signup tests on the real path; that path is the
thing they assert.

**The trap:** a factory that drifts from what signup actually produces gives you
green tests against a tenant shape production never creates. Pin it with one test
that builds a tenant both ways and asserts the rows match on the fields anything
else reads.

## T5 · `setUp` → `setUpTestData` sweep — L · HOLD

705 → 56 is the ratio to move. Mechanical, but **not blind**: `setUpTestData`
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
doing them in the other order means editing the same 705 methods twice.

## T6 · `SimpleTestCase` where there is no database — M · HOLD (but see the note above)

21 of 905 test classes today. A `TestCase` that never queries still pays for the
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
green on `eb048a1e`:

```
tests.test_css_pipeline tests.test_photo_blind_focus tests.test_landing_visibility
tests.test_migration_graph tests.test_view_transitions tests.test_mobile_touch_targets
tests.test_icon_tag tests.test_csp tests.test_notification_surfaces
tests.test_tenant_branding
```

**Two things changed for this session on 2026-09-01.** First, the script should
just use `--parallel` — the old "safe to run `--parallel` precisely because it
is green" caveat is gone, so the guard set has no special status any more and
the script needs no branching. Second, and more interesting: **with the full
suite at 16 minutes, ask whether a hand-picked guard set should exist at all.**
Its entire reason for being was that the real suite was unrunnable. A script
that runs *everything* and diffs against `test_baseline_main.txt` is one command,
needs no curation, cannot drift, and cannot quietly stop covering the thing you
changed. The guard set's remaining advantage is 39 seconds versus 16 minutes,
which matters in a tight edit loop and nowhere else.

**Recommendation: build `scripts/test_guards.sh` with both modes** — a default
fast path over the list above, and a `--full` that runs the suite and diffs the
baseline for you. Then the fast set is what you use while editing and the full
diff is what you run before pushing, and neither is retyped from prose.

---

# Where this stands — 2026-09-01

**T3 is done.** `tblib` is in `requirements.txt`, `CLAUDE.md`'s Running Tests
section is rewritten, and `docs/strategy/test_baseline_main.txt` now holds the
93-line failure set so nobody regenerates it by hand. Everything else is TODO.

**The numbers that matter:** 4,730 tests, **1 in CI**, **93 red**, 16 minutes
to find out. The middle two are the arc; the last one is no longer an excuse.

**This file has now been wrong twice, in the same way, and that is the most
useful thing in it.** Draft one said "north of twenty minutes" and "12 failures"
from a half-remembered note; measurement made those 80 minutes and 96. Draft two
then built its entire session ordering on the 80 minutes and on a `--parallel`
crash it had diagnosed but not tried to fix; one `pip install` made those 16
minutes and a non-issue. Each time the prose was internally consistent,
confidently argued, and wrong at the root. **Do not re-plan this arc from the
prose here. Re-run the measurement, and when a tool crashes, read everything it
printed before you theorise.**

**Start with T7**, then T2, then T1 — and treat Phase B as unproven until a
single module's before-and-after says otherwise.
