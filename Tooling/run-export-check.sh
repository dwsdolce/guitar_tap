#!/bin/bash
# Run the export tests (tests/test_export_e2e.py), which drive the real main window through Import and both
# export paths, and check the exports against Swift's expected values (Tooling/export-check/).
#
# Usage: Tooling/run-export-check.sh [out-dir]   (default: build/export-check)

set -euo pipefail
cd "$(dirname "$0")/.."

out="${1:-build/export-check}"
python="${PYTHON:-.venv/bin/python}"
rm -rf "$out"
GT_EXPORT_DIR="$out" "$python" -m pytest -q tests/test_export_e2e.py
"$python" Tooling/export-check/check_exports.py check "$out"
