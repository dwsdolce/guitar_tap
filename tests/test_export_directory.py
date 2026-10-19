# @parity test/export-directory
"""
The export Save dialog's first-run default: the user's Documents/GuitarTap, Documents as the system names it
(so a Documents folder moved elsewhere — OneDrive on Windows — is the one used).

Mirrors: GuitarTapTests/ExportDirectoryTests.swift (the real home's Documents, out of the macOS sandbox).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtCore  # noqa: E402

from guitar_tap.views import tap_analysis_results_view as results_view  # noqa: E402


def test_default_export_directory_is_documents_guitartap(monkeypatch, tmp_path):
    documents = tmp_path / "Moved Documents"
    monkeypatch.setattr(QtCore.QStandardPaths, "writableLocation", staticmethod(lambda _location: str(documents)))
    path = results_view.default_export_dir()
    assert path == str(documents / "GuitarTap")
    assert os.path.isdir(path), "it is made when missing"
