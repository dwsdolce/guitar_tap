"""
Spectrum sub-views and plate/decay area rendering.

Mirrors Swift's TapToneAnalysisView+SpectrumViews.swift — the area below
the spectrum chart that shows plate properties, decay time, and guitar
analysis summary depending on the current measurement type and display mode.

Pending: extract from tap_tone_analysis_view.MainWindow the methods that
build and update the right-panel sub-views:
  decayTimeView / _update_decay_time_display()
  materialInstructionsView / _build_material_instr_panel()
  guitarAnalysisSummary / _update_guitar_summary()
"""
