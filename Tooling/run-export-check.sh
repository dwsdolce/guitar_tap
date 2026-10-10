#!/bin/bash
# Run the export tests (tests/test_export_e2e.py), which drive the real main window through Import and both
# export paths, and check the exports against Swift's expected values (Tooling/export-check/).
#
# Usage: Tooling/run-export-check.sh [out-dir]   (default: build/export-check)

set -euo pipefail
cd "$(dirname "$0")/.."

out="${1:-build/export-check}"
# Python: this repo's own .venv (.venv/bin on macOS and Linux, .venv/Scripts on Windows); PYTHON names another.
if [ -z "${PYTHON:-}" ]; then
    for candidate in .venv/bin/python .venv/Scripts/python.exe .venv/Scripts/python; do
        if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
    done
fi
if [ -z "${PYTHON:-}" ]; then
    echo "No .venv: set it up as the README's \"Setting up on a new machine\" says." >&2
    exit 1
fi
rm -rf "$out"
GT_EXPORT_DIR="$out" "$PYTHON" -m pytest -q tests/test_export_e2e.py
"$PYTHON" Tooling/export-check/check_exports.py check "$out"
