"""
MainWindow signal wiring and control-state update methods.

Mirrors Swift's TapToneAnalysisView+Controls.swift — `_connect_signals()`,
`set_running()`, `set_tap_count()`, and related status-bar update methods.

Pending: extract the following sections from tap_tone_analysis_view.MainWindow:
  Signal connections section (# ================================================================
                               # Signal connections)
  State update methods section (# State update methods (formerly in PeakControls))
  Frequency range section (_on_fmin_changed, _on_fmax_changed, etc.)
  Annotation visibility cycling section (_on_cycle_annotation_mode, etc.)
"""
