"""
MainWindow layout builders.

Mirrors Swift's TapToneAnalysisView+Layouts.swift — `_build_ui()` and all
`_build_*` helper methods that assemble the Qt widget hierarchy.

Pending: extract the following methods from tap_tone_analysis_view.MainWindow:
  _build_toolbar()          — top button bar (auto-dB, annotations, save, etc.)
  _build_controls_bar()     — tap controls, freq range spinboxes, threshold sliders
  _build_right_panel()      — analysis results + peaks + material properties panel
  _build_decay_strip()      — ring-out / decay-time display strip
  _build_status_bar()       — status dot + progress bar + tap count
  _build_material_instr_panel() — plate/brace instruction panel
"""
