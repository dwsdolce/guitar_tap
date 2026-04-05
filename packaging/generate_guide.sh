#!/bin/bash
# Generate the Guitar Tap Quick-Start Guide (HTML + PDF).
#
# Prerequisites (one-time):
#   macOS:  brew install pango
#           pip install weasyprint
#   Linux:  sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
#           pip install weasyprint
#
# Usage:
#   packaging/generate_guide.sh          # from project root
#   ./generate_guide.sh                  # from packaging/

# Run from the project root regardless of where this script is invoked from.
cd "$(dirname "$0")/.."

python packaging/generate_guide.py
