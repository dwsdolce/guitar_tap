#!/bin/bash
# Build GuitarTapMicProbe — a single-file console executable — on macOS, Linux, or Windows (Cygwin bash).
#
# Uses the project .venv when present so the executable carries the SAME
# sounddevice/PortAudio library as the shipping Guitar Tap build.
#
# Run it from a terminal (it is a console program, not a .app); on macOS the
# microphone permission is the terminal app's.

# Run from the project root regardless of where this script is invoked from.
cd "$(dirname "$0")/../.." || exit 1

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

# Windows: the exe carries the app's icon.
icon=()
case "$(uname -s)" in CYGWIN*|MINGW*|MSYS*) icon=(--icon src/guitar_tap/icons/guitar-tap.ico) ;; esac

"$PYTHON" -m PyInstaller -y --onefile --console --name GuitarTapMicProbe "${icon[@]}" \
    --exclude-module scipy --exclude-module PySide6 --exclude-module pyqtgraph \
    --distpath dist/mic-probe --workpath build/mic-probe --specpath build/mic-probe \
    Tooling/mic-probe/mic_probe.py
if [ $? -ne 0 ]; then
    echo "Running pyinstaller failed"
    exit 1
fi
echo "Built dist/mic-probe/GuitarTapMicProbe"
