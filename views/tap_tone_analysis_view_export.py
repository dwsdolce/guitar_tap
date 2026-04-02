"""
MainWindow export and save triggers.

Mirrors Swift's TapToneAnalysisView+Export.swift — handlers for saving
measurements, exporting JSON/CSV/PDF, and file open/import dialogs.

Pending: extract the export-related callbacks from
  tap_tone_analysis_view.MainWindow, specifically:
  _collect_measurement()
  _on_save_measurement()
  _on_open_measurements()
  _on_export_json() / _on_export_csv() / _on_export_pdf()
  _on_import_json()
"""
