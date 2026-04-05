"""
Application version and build number.

Version comes from the 'version' file (manually maintained, committed to git).
Build number sources, in priority order:
  1. PyInstaller bundle: 'version_build' file extracted to sys._MEIPASS.
  2. Source tree: ask git directly via 'git rev-list --count HEAD'.
  3. Neither available: __build__ is empty.

__version_string__ follows Swift's "CFBundleShortVersionString (CFBundleVersion)"
convention, e.g. "0.11 (47)" or just "0.11" when no build number is available.
"""

import os
import subprocess
import sys


def _read_file(path: str) -> str | None:
    """Read a plain-text file, returning stripped content or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _git_commit_count() -> str | None:
    """Return the git commit count for HEAD, or None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None
    except Exception:
        return None


def _resolve_build() -> str:
    # PyInstaller bundle: version_build is extracted alongside the package.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return _read_file(os.path.join(meipass, "version_build")) or ""
    # Development: ask git directly — no file needed.
    return _git_commit_count() or ""


__version__: str = _read_file(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "version")
) or "\u2013"

__build__: str = _resolve_build()

# Human-readable string matching Swift's "version (build)" convention.
# e.g. "0.11 (47)"  or just "0.11" when no build number is available.
__version_string__: str = (
    f"{__version__} ({__build__})" if __build__ else __version__
)
