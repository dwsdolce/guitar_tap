# @parity view/export-menus tests=test/export-menus
"""
The two menus besides a saved measurement's own that export: Saved Measurements' library menu and Analysis Results'.
Each is one button, Export, whose items write a file through a save dialog — the same in every edition and in the
shared export-menus.json. Swift's also have Share items (the share sheet, which this edition does not have), and on
iOS and iPadOS its button is Share. Mirrors Swift ``ExportMenus`` (Views/Utilities/ExportMenus.swift).
"""

from __future__ import annotations

from typing import NamedTuple


class ExportMenuEntry(NamedTuple):
    """One item of an export menu."""

    action: str
    title: str
    mdi: str  # the Material Design icon, as qtawesome names it without "mdi."


class ExportMenu(NamedTuple):
    """A menu behind one button: the button's word and icon, and its items' groups."""

    button: str
    mdi: str
    groups: list[list[ExportMenuEntry]]


# Saved Measurements' library menu: all the measurements, or the ones ticked first (as Delete's Selected…), as one
# .guitartap file. Its items have icons as the Delete menu's do.
PANEL = ExportMenu("Export", "upload-outline", [
    [
        ExportMenuEntry("exportAll", "Export All…", "file-export-outline"),
        ExportMenuEntry("exportSelected", "Export Selected…", "check-circle-outline"),
    ],
])

# Analysis Results' menu: a saved measurement's menu's items for the spectrum image and the PDF report.
ANALYSIS_RESULTS = ExportMenu("Export", "upload-outline", [
    [
        ExportMenuEntry("exportSpectrum", "Export Spectrum…", "chart-line"),
        ExportMenuEntry("exportPDF", "Export PDF Report…", "file-pdf-box"),
    ],
])
