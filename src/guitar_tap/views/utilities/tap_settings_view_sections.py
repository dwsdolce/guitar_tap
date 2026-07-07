"""
Settings view section builders.

Mirrors Swift's TapSettingsView+Sections.swift — individual settings sections
(Audio Device, Measurement Type, Display, Peak Detection, Plate Dimensions, etc.)

In Python, each section is built inline within _show_settings() in
tap_tone_analysis_view.MainWindow — including the Gore Target Thickness section
(the dialog is a faithful, complete port of TapSettingsView+Sections.swift).

Pending: extract each settings section into a dedicated builder function here,
then call them from the main _show_settings() body (a structural refactor only;
the rendered content already matches Swift).
"""
