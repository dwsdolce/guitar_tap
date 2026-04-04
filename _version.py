"""
Application version and build number.

Version comes from the 'version' file (manually maintained, committed to git).
Build comes from the 'version_build' file (generated at package time by the build
script via ``git rev-list --count HEAD > version_build``; not committed to git).

Both files are bundled into PyInstaller distributions via guitar-tap.spec.
When running from source without a 'version_build' file, __build__ is empty and
__version_string__ is just the version (e.g. "0.11").
When a version_build file is present (e.g. "47"), __version_string__ is "0.11 (47)",
matching Swift's "CFBundleShortVersionString (CFBundleVersion)" display.
"""

import os
import sys


def _read_resource(name: str) -> str | None:
    """Read a plain-text resource file from the app bundle or source tree."""
    # PyInstaller extracts bundled data to sys._MEIPASS at runtime.
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, name), "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


__version__: str = _read_resource("version") or "\u2013"
__build__: str = _read_resource("version_build") or ""

# Human-readable string matching Swift's "version (build)" convention.
# e.g. "0.11 (47)"  or just "0.11" when no build file is present.
__version_string__: str = (
    f"{__version__} ({__build__})" if __build__ else __version__
)
