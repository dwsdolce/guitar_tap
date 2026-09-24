#!/bin/bash
# Build GuitarTapMicProbe — a single-file console executable — on macOS or Linux.
# Windows: use build_win.bat.
#
# Uses the project .venv when present so the executable carries the SAME
# sounddevice/PortAudio library as the shipping Guitar Tap build.
#
# Run it from a terminal (it is a console program, not a .app); on macOS the
# microphone permission is the terminal app's.

# Run from the project root regardless of where this script is invoked from.
cd "$(dirname "$0")/../.." || exit 1

if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    echo "No .venv found; using python3 from PATH"
    PYTHON=python3
fi

"$PYTHON" -m PyInstaller -y --onefile --console --name GuitarTapMicProbe \
    --exclude-module scipy --exclude-module PySide6 --exclude-module pyqtgraph \
    --distpath dist/mic-probe --workpath build/mic-probe --specpath build/mic-probe \
    Tooling/mic-probe/mic_probe.py
if [ $? -ne 0 ]; then
    echo "Running pyinstaller failed"
    exit 1
fi
echo "Built dist/mic-probe/GuitarTapMicProbe"
