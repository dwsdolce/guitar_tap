#!/usr/bin/env bash
# Python soak / stress harness — a DEV TOOL, not a CI test.
# Portable bash: macOS, Linux, and Windows under Cygwin/Git-Bash. The interpreter is auto-detected
# (Unix .venv/bin vs Windows .venv/Scripts, else PATH); override with PYTEST="…".
#
# Loops the FAST pytest suite (playback excluded) N times with a per-run wall-clock cap, hunting
# nondeterministic FAILURES and HANGS that a single run hides. This is the Python analog of the Swift
# Combine-`deinit` race (../GuitarTap Tooling/deinit-soak.sh) and the web React-effect-cleanup race —
# here the class is the QObject GC / teardown race (e.g. the playback weakref fix). See the web repo's
# Development/SOAK-STRESS-HARNESS.md for the shared rationale.
#
# Three caveats (baked into the design):
#   1. Optional/on-demand, NOT CI — it is N× slower and probabilistic.
#   2. A green soak is CONFIDENCE, NOT PROOF — you cannot prove a race is absent, only make it unlikely.
#   3. Faithfulness: each run does a REAL full-suite setup/teardown (Qt objects torn down under GC) —
#      that is the signal. A synthetic same-thread create/destroy loop would not reproduce it.
#
# Detection:
#   - FAIL — pytest exits non-zero (a failed test, or a C++/Qt crash aborting the run). The tail of the
#            failing run is printed.
#   - HANG — a fully-wedged run is killed by the per-run wall-clock cap (macOS has no `timeout`, so the
#            cap is a background killer). NOTE: for finer PER-TEST hang detection, `pip install
#            pytest-timeout` and add `--timeout=<secs>` below — it is not a dependency of this script.
#
# Usage:  Tooling/soak.sh [N]        (default N=100)
#         SOAK_RUN_TIMEOUT=<seconds>  caps one fully-wedged run (default 180).
#
# Exits 0 only if every run passed with no failures and no hangs.
set -u
cd "$(dirname "$0")/.." || exit 1

N="${1:-100}"
RUN_TIMEOUT="${SOAK_RUN_TIMEOUT:-180}"
# Pick the interpreter: an explicit PYTEST override, else the venv (Unix bin/ or Windows Scripts/),
# else whatever `python` is on PATH.
if [ -z "${PYTEST:-}" ]; then
  if   [ -x .venv/bin/python ];         then PYTEST=".venv/bin/python -m pytest"
  elif [ -x .venv/Scripts/python.exe ]; then PYTEST=".venv/Scripts/python.exe -m pytest"
  elif [ -x .venv/Scripts/python ];     then PYTEST=".venv/Scripts/python -m pytest"
  else                                       PYTEST="python -m pytest"
  fi
fi
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

# Portable per-run wall-clock cap: run in the background, kill it if it overruns (kill -9 → exit 137).
run_capped() {
  "$@" >"$LOG" 2>&1 &
  local pid=$!
  ( sleep "$RUN_TIMEOUT"; kill -9 "$pid" 2>/dev/null ) &
  local watcher=$!
  wait "$pid" 2>/dev/null; local rc=$?
  kill "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null
  return $rc
}

echo "python soak: $N runs · per-run cap ${RUN_TIMEOUT}s · $PYTEST (playback excluded)"
PASS=0; FAIL=0; HANG=0
for i in $(seq 1 "$N"); do
  # $PYTEST is intentionally unquoted so bash word-splits "…/python -m pytest" into its parts.
  run_capped $PYTEST -q --ignore=tests/test_file_playback_regression.py
  rc=$?
  if [ "$rc" -eq 0 ]; then
    PASS=$((PASS + 1))
  elif [ "$rc" -eq 137 ]; then
    HANG=$((HANG + 1)); echo; echo "!!! RUN $i: HANG (killed after ${RUN_TIMEOUT}s)"
  else
    FAIL=$((FAIL + 1)); echo; echo "!!! RUN $i: FAIL (exit $rc)"; tail -25 "$LOG"
  fi
  printf "\r%d/%d  pass=%d fail=%d hang=%d " "$i" "$N" "$PASS" "$FAIL" "$HANG"
done
echo
echo "done: $PASS passed · $FAIL failed · $HANG hung  (of $N)"
[ "$FAIL" -eq 0 ] && [ "$HANG" -eq 0 ]
