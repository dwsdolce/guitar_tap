"""
Settings view section builders.

Mirrors Swift's TapSettingsView+Sections.swift — individual settings sections
(Audio Device, Measurement Type, Display, Peak Detection, Plate Dimensions, etc.)

In Python, each section is built inline within _show_settings() in
tap_tone_analysis_view.MainWindow.

Pending: extract each settings section into a dedicated builder function here,
then call them from the main _show_settings() body.

Known gap: the Gore Target Thickness section present in
TapSettingsView+Sections.swift is not yet rendered in the Python settings dialog
(documented in VIEWS_STRUCTURE.md implementation gaps, item #10).
"""
