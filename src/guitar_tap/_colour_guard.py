"""
Colour guard — refuses to run when a colour is written outside the palette.

Mirrors the Swift edition's Tooling/check-colours.sh and the web edition's
tooling/check-colours.mjs — same rule.

The rule: every colour the app draws is a role in views/utilities/palette.py, with its
own light and dark value. A colour written anywhere else — a hex or numeric rgb()
literal, a QColor built from numbers or a name, a named colour in a stylesheet or a
qtawesome call, a Qt palette(...) role, a pyqtgraph colour shorthand — does not follow
the Appearance setting and differs from the Swift and web editions.

DEVELOPMENT CHECKOUTS ONLY, as _release_guard.py: a shipped (frozen) build carries no
source to scan, so the guard allows it.

Used two ways, one implementation:
  - imported by __main__.py, so `python -m guitar_tap` fails before the UI opens;
  - run as a script — `.venv/bin/python src/guitar_tap/_colour_guard.py` (stdlib only).
"""

import os
import re
import sys

_NAMED = (r"red|green|blue|gray|grey|orange|yellow|purple|white|black|cyan|magenta|pink|brown|"
          r"darkgray|lightgray")
PATTERNS = {
    "hex": r"""["'][^"'\n]*(?<!&)#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{2})?)?\b""",
    "rgb": r"rgba?\(\s*\d",
    "QColor": r"QColor\(\s*(?:\d|[\"'])|GlobalColor\.",
    "named": (r"(?:\bcolor|background(?:-color)?|border(?:-color)?)\s*:\s*(?:" + _NAMED + r")\b"
              r"|color\s*=\s*[\"'](?:" + _NAMED + r")[\"']"),
    "palette()": r"palette\([a-z-]+\)",
    "pyqtgraph": (r"""mkPen\(\s*["'][rgbcmykw]["']|mkBrush\(\s*["'][rgbcmykw]["']"""
                  r"""|\b(?:pen|brush)\s*=\s*["'][rgbcmykw]["']"""),
}
PALETTE = "views/utilities/palette.py"


def _package_root() -> str:
    """Return src/guitar_tap — the directory this file is in."""
    return os.path.dirname(os.path.abspath(__file__))


def failures(root: str | None = None) -> list[str]:
    """Return every line under `root` (default: this package) that writes a colour outside the
    palette, as "path:line [kind] text"; empty means good to go."""
    if root is None:
        if getattr(sys, "_MEIPASS", None):
            return []
        root = _package_root()
    patterns = {k: re.compile(p, re.IGNORECASE if k == "named" else 0) for k, p in PATTERNS.items()}
    found = []
    for directory, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(directory, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel == PALETTE:
                continue
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    if line.lstrip().startswith("#"):
                        continue
                    for kind, pattern in patterns.items():
                        if pattern.search(line):
                            found.append(f"{rel}:{number} [{kind}] {line.strip()}")
    return found


def enforce() -> None:
    """Print every colour written outside the palette and exit non-zero, or return if none."""
    found = failures()
    if not found:
        return
    print("BLOCKED — a colour is written outside the palette (views/utilities/palette.py):",
          file=sys.stderr)
    for line in found:
        print(f"  {line}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    enforce()
