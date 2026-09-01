#!/usr/bin/env bash
# Run the guard set — the ten modules that catch the things this repo actually
# breaks — or the full suite diffed against the committed baseline.
#
# Why this file exists: the guard set used to live in prose, in four different
# strategy docs, retyped by hand each session. Retyping it is how a session
# loses 45 minutes: `MODULES="..."` without `export` expands to nothing inside
# `bash -c`, `manage.py test` silently runs all 4,730 tests instead of your ten
# modules, and it does not error — it looks exactly like a hang. A bash array
# inside a script cannot word-split, cannot fail to cross into a subshell, and
# cannot be mistyped. See docs/strategy/TEST_SUITE_SESSIONS.md (T7).
#
#   scripts/test_guards.sh                      # guard set, ~30s
#   scripts/test_guards.sh tests.test_foo       # guard set + the module you touched
#   scripts/test_guards.sh --full               # whole suite (~16 min), diffed vs baseline
#
# Fast mode is what you run while editing. `--full` is what you run before you
# push: it is the only mode that can tell you whether you broke something the
# guard set does not cover.
set -euo pipefail
cd "$(dirname "$0")/.."

# The guard set. Add a module here when an arc starts depending on it; do NOT
# copy this list into a strategy doc — point at this script instead.
GUARDS=(
  tests.test_css_pipeline           # Tailwind build is committed and current
  tests.test_photo_blind_focus      # photo ML crop defaults
  tests.test_landing_visibility     # public pages render logged-out
  tests.test_migration_graph        # no duplicate/divergent migration heads
  tests.test_view_transitions       # nav shell markup
  tests.test_mobile_touch_targets   # tap-target floors
  tests.test_icon_tag               # {% icon %} renders vendored SVG, no CDN
  tests.test_csp                    # no inline script/style regressions
  tests.test_notification_surfaces  # in-app notification rendering
  tests.test_tenant_branding        # per-tenant theming + tenant scoping
)

BASELINE="docs/strategy/test_baseline_main.txt"
PYTHON="${PYTHON:-python}"
PARALLEL="${PARALLEL:-8}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-rs_systems.settings.development}"

# Only FAIL/ERROR/summary lines. Assertion messages in this repo dump whole
# templates; a raw full run overflows a tool-result buffer and silently keeps
# only the tail.
FILTER='^(FAIL|ERROR): |^Ran |^FAILED|^OK'

usage() {
  cat <<'EOF'
scripts/test_guards.sh [--full] [--list] [extra.test.labels ...]

  (no args)   Run the guard set under --parallel. Green means green: the guard
              set carries no known failures, so any red is yours.
  --full      Run the whole suite and diff FAIL/ERROR against the committed
              baseline. Prints regressions and fixes; exits non-zero only on
              regressions. Absolute counts mean nothing here.
  --list      Print the guard modules, one per line, and exit.

Env: PARALLEL (default 8) · PYTHON (default python)
EOF
}

MODE=fast
EXTRA=()
for arg in "$@"; do
  case "$arg" in
    --full) MODE=full ;;
    --list) printf '%s\n' "${GUARDS[@]}"; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "Unknown flag: $arg" >&2; usage >&2; exit 2 ;;
    *) EXTRA+=("$arg") ;;
  esac
done

# --- Pre-flight ------------------------------------------------------------
# Both of these are silent failure modes that have cost real time, and both are
# one line to check.
if ! "$PYTHON" -c 'import tblib' 2>/dev/null; then
  echo "tblib is not installed — --parallel would die with" >&2
  echo "  TypeError: cannot pickle 'traceback' object" >&2
  echo "printing nothing useful. Fix: pip install -r requirements.txt" >&2
  exit 1
fi
if [ -n "${LOCAL_DATABASE_URL:-}" ] || [ -n "${USE_AWS_DB:-}" ]; then
  echo "warning: LOCAL_DATABASE_URL/USE_AWS_DB is set, so this run is NOT on" >&2
  echo "         SQLite. $BASELINE was taken on SQLite; the diff will be noisy." >&2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- Fast mode -------------------------------------------------------------
if [ "$MODE" = fast ]; then
  MODULES=("${GUARDS[@]}" ${EXTRA+"${EXTRA[@]}"})
  echo "==> ${#MODULES[@]} modules, --parallel $PARALLEL"
  set +e
  "$PYTHON" manage.py test --parallel "$PARALLEL" "${MODULES[@]}" 2>&1 \
    | grep -E "$FILTER"
  status=${PIPESTATUS[0]}
  set -e
  if [ "$status" -ne 0 ]; then
    echo
    if [ "${#EXTRA[@]}" -gt 0 ]; then
      echo "RED. The ten guard modules carry no known failures — but the extra"
      echo "modules you passed may be red on main too. Check which one it is"
      echo "against $BASELINE before assuming it is yours."
    else
      echo "Guard set is RED. It carries no known failures, so this is yours."
    fi
    echo "Re-run that one module without the filter to see the assertion:"
    echo "  $PYTHON manage.py test <module>"
  fi
  exit "$status"
fi

# --- Full mode -------------------------------------------------------------
# The baseline is flag-dependent: some tests in this suite depend on execution
# order or on being the only writer, so serial and parallel runs disagree by a
# handful. Compare like with like or you will triage tests that were never
# yours.
if [ "$PARALLEL" != 8 ]; then
  echo "warning: $BASELINE was taken at --parallel 8; you are running" >&2
  echo "         --parallel $PARALLEL. Expect a few spurious diffs." >&2
fi
if [ ! -f "$BASELINE" ]; then
  echo "Missing $BASELINE — nothing to diff against." >&2
  exit 1
fi

echo "==> full suite, --parallel $PARALLEL — this takes ~16 minutes"
set +e
"$PYTHON" manage.py test --parallel "$PARALLEL" tests 2>&1 | tee "$TMP/raw.log" \
  | grep -E '^Ran |^FAILED|^OK'
set -e

# A run that dies before collecting tests produces an empty FAIL/ERROR set,
# which diffs against the baseline as "you fixed all 93" and exits 0. That is
# the one way this script can report a false green, so check the run actually
# finished before believing its output.
if ! grep -qE '^Ran [0-9]+ test' "$TMP/raw.log"; then
  echo >&2
  echo "The suite did not run to completion — no 'Ran N tests' line. Last 20:" >&2
  tail -20 "$TMP/raw.log" >&2
  exit 1
fi

grep -E '^(FAIL|ERROR): ' "$TMP/raw.log" | sort > "$TMP/mine.txt" || true
grep -v '^#' "$BASELINE" | sed '/^$/d' | sort > "$TMP/base.txt"

comm -23 "$TMP/mine.txt" "$TMP/base.txt" > "$TMP/regressions.txt" || true
comm -13 "$TMP/mine.txt" "$TMP/base.txt" > "$TMP/fixed.txt" || true
n_reg=$(wc -l < "$TMP/regressions.txt" | tr -d ' ')
n_fix=$(wc -l < "$TMP/fixed.txt" | tr -d ' ')

echo
echo "==> vs $BASELINE: $(wc -l < "$TMP/mine.txt" | tr -d ' ') red now, $(wc -l < "$TMP/base.txt" | tr -d ' ') red on main"

if [ "$n_fix" -gt 0 ]; then
  echo
  echo "--- FIXED ($n_fix) — update the baseline if these are yours ---"
  cat "$TMP/fixed.txt"
fi

if [ "$n_reg" -gt 0 ]; then
  echo
  echo "--- REGRESSIONS ($n_reg) — the only output that matters ---"
  cat "$TMP/regressions.txt"
  exit 1
fi

echo
echo "No regressions."
