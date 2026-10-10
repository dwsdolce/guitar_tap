#!/bin/bash
# Generate the Guitar Tap Quick Start Guide (HTML + PDF).
#
# Prerequisites (one-time):
#   macOS:  brew install pango
#   Linux:  sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
#   weasyprint comes with requirements-dev.txt, in this repo's .venv
#
# Usage:
#   packaging/generate_guide.sh          # from project root
#   ./generate_guide.sh                  # from packaging/

# Run from the project root regardless of where this script is invoked from.
cd "$(dirname "$0")/.."

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

"$PYTHON" packaging/generate_guide.py
