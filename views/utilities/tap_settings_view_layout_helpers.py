"""
Settings view layout helper functions.

Mirrors Swift's TapSettingsView+LayoutHelpers.swift — reusable row/section
builder helpers used inside the settings dialog.

In Python, layout helpers for the settings dialog are defined as closures
inside _show_settings() in tap_tone_analysis_view.MainWindow.

Pending: extract the inner helper functions (_add_row, _section_label, etc.)
from MainWindow._show_settings() into standalone module-level functions here.
"""
