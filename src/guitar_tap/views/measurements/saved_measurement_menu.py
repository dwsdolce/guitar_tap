# @parity view/saved-measurement-menu tests=test/saved-measurement-menu
"""
A saved measurement's menu — from its ⋯ or a right-click in Saved Measurements: what each item does, says and
shows. The list builds the menu from these groups; the same groups are in every edition and in the shared
saved-measurement-menu.json. Mirrors Swift ``SavedMeasurementMenu`` (Views/Measurements/SavedMeasurementMenu.swift).
"""

from __future__ import annotations

from typing import NamedTuple


class SavedMeasurementMenuEntry(NamedTuple):
    """One item of a saved measurement's menu. Mirrors Swift ``SavedMeasurementMenuEntry``."""

    action: str
    title: str
    mdi: str  # the Material Design icon, as qtawesome names it without "mdi." — Swift's SF Symbol's nearest


# A saved measurement's menu, in the groups a separator divides. Export writes the file through a save dialog. Swift
# also has Share, in a group of its own after Export's: the share sheet, which this edition does not have. "…" as
# style guide S9.
GROUPS: list[list[SavedMeasurementMenuEntry]] = [
    [
        SavedMeasurementMenuEntry("load", "Load into View", "file-download-outline"),
    ],
    [
        SavedMeasurementMenuEntry("details", "View Details", "eye-outline"),
        SavedMeasurementMenuEntry("edit", "Edit Name & Notes", "pencil-outline"),
    ],
    [
        SavedMeasurementMenuEntry("exportMeasurement", "Export Measurement…", "file-export-outline"),
        SavedMeasurementMenuEntry("exportSpectrum", "Export Spectrum…", "chart-line"),
        SavedMeasurementMenuEntry("exportPDF", "Export PDF Report…", "file-pdf-box"),
    ],
    [
        SavedMeasurementMenuEntry("delete", "Delete", "trash-can-outline"),
    ],
]
