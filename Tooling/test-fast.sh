#!/usr/bin/env bash
# The fast test run: the whole pytest suite except the two tests that replay every recording through
# the full pipeline — the playback regression (tests/test_file_playback_regression.py) and the
# self-regression (tests/test_self_regression.py) — which are most of the suite's time. Swift's fast
# run skips the same work: its playback regression is also its self-regression. Use it while working;
# run the full suite (`pytest`) before a commit or after a change to capture, detection or peak
# finding, which the replays cover.
#
# The same split in the other editions: web `npm run test:fast`, Swift `Tooling/test-fast.sh`.
#
# Portable bash: macOS, Linux, and Windows under Cygwin/Git-Bash. The interpreter is auto-detected
# (Unix .venv/bin vs Windows .venv/Scripts, else PATH); override with PYTEST="…".
#
# Usage:  Tooling/test-fast.sh [pytest args…]      e.g. Tooling/test-fast.sh -q -x
set -u
cd "$(dirname "$0")/.." || exit 1

if [ -z "${PYTEST:-}" ]; then
  if   [ -x .venv/bin/python ];         then PYTEST=".venv/bin/python -m pytest"
  elif [ -x .venv/Scripts/python.exe ]; then PYTEST=".venv/Scripts/python.exe -m pytest"
  elif [ -x .venv/Scripts/python ];     then PYTEST=".venv/Scripts/python -m pytest"
  else                                       PYTEST="python -m pytest"
  fi
fi

# $PYTEST is intentionally unquoted so bash word-splits "…/python -m pytest" into its parts.
exec $PYTEST --ignore=tests/test_file_playback_regression.py \
  --ignore=tests/test_self_regression.py "$@"
