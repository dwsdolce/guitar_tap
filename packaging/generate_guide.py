#!/usr/bin/env python3
"""
Generate the Guitar Tap Quick-Start Guide as HTML and PDF.

Requires WeasyPrint and Pango (the PDF step only):
    macOS:  brew install pango
    Linux:  sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
    Windows: install GTK runtime from https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
    Then:   pip install weasyprint

Run from the project root:
    python packaging/generate_guide.py

Outputs:
    docs/GuitarTap-Quick-Start-Guide.html
    docs/GuitarTap-Quick-Start-Guide.pdf
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup — make src/guitar_tap importable regardless of where we are run
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))          # packaging/
_root = os.path.dirname(_here)                               # project root
_src  = os.path.join(_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

# ---------------------------------------------------------------------------
# Qt must be initialised before importing help_view (qtawesome needs it)
# Use the offscreen platform so no display is required.
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

# Offscreen/minimal Qt platforms warn if PySide6/lib/fonts is missing.
# We don't render with Qt fonts (only produce HTML), so create an empty
# directory to silence the warning.
_pyside_dir = os.path.dirname(QtWidgets.__file__)
_fonts_dir = os.path.join(_pyside_dir, "lib", "fonts")
os.makedirs(_fonts_dir, exist_ok=True)

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# ---------------------------------------------------------------------------
# Import the HTML builder (now safe — QApplication is alive)
# Import the module directly to avoid triggering the heavy views/__init__.py
# which pulls in the entire application.
# ---------------------------------------------------------------------------
import importlib.util as _ilu  # noqa: E402

_help_view_path = os.path.join(_src, "guitar_tap", "views", "help_view.py")
_spec = _ilu.spec_from_file_location("help_view", _help_view_path)
_mod  = _ilu.module_from_spec(_spec)   # type: ignore[arg-type]
_spec.loader.exec_module(_mod)         # type: ignore[union-attr]

get_help_html = _mod.get_help_html


def _enhanced_css() -> str:
    """Extra CSS appended for the PDF / standalone HTML version."""
    return """\
<style>
  /* ---- page layout (WeasyPrint / print media) ---- */
  @page {
    size: A4;
    margin: 20mm 20mm 22mm 20mm;
    @bottom-center {
      content: "Guitar Tap Quick-Start Guide — page " counter(page) " of " counter(pages);
      font-size: 9px;
      color: #888;
    }
  }
  body  { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
          font-size: 11px; margin: 0; }
  h1    { font-size: 18px; }
  h2    { font-size: 13px; page-break-after: avoid; }
  .row  { page-break-inside: avoid; }
</style>"""


def _inject_css(html: str, extra_css: str) -> str:
    """Insert extra_css just before </head>."""
    return html.replace("</head>", extra_css + "\n</head>", 1)


def main() -> None:
    out_dir = os.path.join(_root, "docs")
    os.makedirs(out_dir, exist_ok=True)

    html_path = os.path.join(out_dir, "GuitarTap-Quick-Start-Guide.html")
    pdf_path  = os.path.join(out_dir, "GuitarTap-Quick-Start-Guide.pdf")

    # Build HTML from the app's own help content
    html = _inject_css(get_help_html(), _enhanced_css())

    # Write the HTML file
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML written: {html_path}")

    # Generate PDF via WeasyPrint
    # On macOS, help WeasyPrint find Homebrew-installed Pango/GObject libs.
    _homebrew_lib = "/opt/homebrew/lib"
    if os.path.isdir(_homebrew_lib):
        existing = os.environ.get("DYLD_LIBRARY_PATH", "")
        if _homebrew_lib not in existing.split(os.pathsep):
            os.environ["DYLD_LIBRARY_PATH"] = (
                f"{_homebrew_lib}{os.pathsep}{existing}" if existing else _homebrew_lib
            )
    try:
        import weasyprint  # noqa: PLC0415
    except (ImportError, OSError) as exc:
        print(
            f"Cannot load WeasyPrint ({exc}).\n\n"
            "WeasyPrint requires Pango (a native library). Install it first:\n"
            "    macOS:   brew install pango\n"
            "    Linux:   sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0\n"
            "    Windows: install GTK runtime, see packaging/generate_guide.py docstring\n"
            "Then: pip install weasyprint\n\n"
            "The HTML file was written successfully and can be printed to PDF from a browser."
        )
        sys.exit(1)

    weasyprint.HTML(string=html, base_url=_root).write_pdf(pdf_path)
    print(f"PDF  written: {pdf_path}")


if __name__ == "__main__":
    main()
