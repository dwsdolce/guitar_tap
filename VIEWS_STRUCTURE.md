# Python Views Package — Proposed Structure

Maps the current root-level Python UI files to a `views/` package hierarchy that mirrors
Swift's `Views/` folder structure.  Each entry shows the proposed Python file, its Swift
mirror, the current Python source material, and any implementation gaps.

---

## Proposed Directory Tree

```
views/
├── __init__.py
│
├── fft_canvas.py                          (stays here – central widget)
├── tap_tone_analysis_view.py              (main window shell)
├── tap_tone_analysis_view_actions.py
├── tap_tone_analysis_view_controls.py
├── tap_tone_analysis_view_export.py
├── tap_tone_analysis_view_layouts.py
├── tap_tone_analysis_view_spectrum_views.py
├── tap_analysis_results_view.py
├── spectrum_view.py
├── spectrum_view_gesture_handlers.py
├── spectrum_view_snap_interpolation.py
├── fft_analysis_metrics_view.py
├── peak_annotations.py
├── save_measurement_sheet.py
├── help_view.py
│
├── shared/
│   ├── __init__.py
│   ├── combined_peak_mode_row_view.py
│   ├── compact_fft_metrics_overlay.py     ⚠ GAP
│   ├── empty_state_view.py
│   └── loading_overlay.py                 ⚠ GAP
│
├── measurements/
│   ├── __init__.py
│   ├── measurements_list_view.py
│   ├── measurement_row_view.py
│   ├── measurement_detail_view.py
│   ├── edit_measurement_view.py           ⚠ GAP
│   └── export_view.py                     ⚠ PARTIAL
│
└── utilities/
    ├── __init__.py
    ├── tap_settings_view.py
    ├── tap_settings_view_actions.py
    ├── tap_settings_view_layout_helpers.py
    ├── tap_settings_view_sections.py
    ├── tap_display_settings.py            ⚠ PARTIAL
    ├── exportable_spectrum_chart.py       ⚠ GAP
    ├── pdf_report_generator.py            ⚠ PARTIAL
    ├── measurement_file_exporter.py
    ├── axis_tick_generator.py
    ├── extensions.py
    └── platform_adapters.py
```

---

## Per-File Mapping

### Root Views

| Proposed file | Swift mirror | Python source | Notes |
|---|---|---|---|
| `fft_canvas.py` | `SpectrumView.swift` + `TapToneAnalysisView.swift` | `fft_canvas.py` (root) | Central Qt widget; keep as single file |
| `tap_tone_analysis_view.py` | `TapToneAnalysisView.swift` | `guitar_tap.py` (main window class) | Shell class + mixin assembly |
| `tap_tone_analysis_view_actions.py` | `TapToneAnalysisView+Actions.swift` | `guitar_tap.py` (action handlers) | Button callbacks, menu actions |
| `tap_tone_analysis_view_controls.py` | `TapToneAnalysisView+Controls.swift` | `fft_toolbar.py`, `guitar_tap.py` toolbar section | Toolbar, status bar, control layout |
| `tap_tone_analysis_view_export.py` | `TapToneAnalysisView+Export.swift` | `guitar_tap.py` export/save section | Export to JSON, CSV, PDF triggers |
| `tap_tone_analysis_view_layouts.py` | `TapToneAnalysisView+Layouts.swift` | `guitar_tap.py` `_build_ui()` | `_build_ui()` declarative layout |
| `tap_tone_analysis_view_spectrum_views.py` | `TapToneAnalysisView+SpectrumViews.swift` | `fft_canvas.py` spectrum rendering helpers | Spectrum sub-views, plate/decay area |
| `tap_analysis_results_view.py` | `TapAnalysisResultsView.swift` | `measurement.py` | Results panel / detail display |
| `spectrum_view.py` | `SpectrumView.swift` + `SpectrumView+ChartContent.swift` | `fft_canvas.py` chart drawing | Chart content, axis, grid |
| `spectrum_view_gesture_handlers.py` | `SpectrumView+GestureHandlers.swift` | `fft_canvas.py` mouse/scroll events | Mouse press/move/scroll handlers |
| `spectrum_view_snap_interpolation.py` | `SpectrumView+SnapInterpolation.swift` | `fft_canvas.py` snap logic | Cursor snap-to-peak interpolation |
| `fft_analysis_metrics_view.py` | `FFTAnalysisMetricsView.swift` | `fft_toolbar.py` metrics section | FPS, dt, sample-rate display |
| `peak_annotations.py` | `PeakAnnotations.swift` | `fft_annotations.py` | Peak label/annotation drawing |
| `save_measurement_sheet.py` | `SaveMeasurementSheet.swift` | `save_measurement_dialog.py` | Save dialog / sheet |
| `help_view.py` | `HelpView.swift` | `help_dialog.py` | Help text display |

### views/shared/

| Proposed file | Swift mirror | Python source | Notes |
|---|---|---|---|
| `combined_peak_mode_row_view.py` | `CombinedPeakModeRowView.swift` | `peak_card_widget.py`, `mode_combo_delegate.py`, `show_button_delegate.py` | Peak row with mode dropdown |
| `compact_fft_metrics_overlay.py` | `CompactFFTMetricsOverlay.swift` | — | ⚠ **GAP** — no equivalent; small overlay showing FPS/dt on top of spectrum |
| `empty_state_view.py` | `EmptyStateView.swift` | Inline in `measurements_dialog.py` | Empty-list placeholder widget |
| `loading_overlay.py` | `LoadingOverlay.swift` | — | ⚠ **GAP** — no equivalent; spinner overlay while loading files |

### views/measurements/

| Proposed file | Swift mirror | Python source | Notes |
|---|---|---|---|
| `measurements_list_view.py` | `MeasurementsListView.swift` | `measurements_dialog.py` | Measurement list dialog/panel |
| `measurement_row_view.py` | `MeasurementRowView.swift` | `measurements_dialog.py` (row rendering) | Single row in measurements list |
| `measurement_detail_view.py` | `MeasurementDetailView.swift` | `measurement_detail_dialog.py` | Detail panel for one measurement |
| `edit_measurement_view.py` | `EditMeasurementView.swift` | — | ⚠ **GAP** — no inline editor; Python only has read-only detail view |
| `export_view.py` | `ExportView.swift` | `guitar_tap.py` export section | ⚠ **PARTIAL** — no in-app JSON/CSV preview panel; only file-save dialogs |

### views/utilities/

| Proposed file | Swift mirror | Python source | Notes |
|---|---|---|---|
| `tap_settings_view.py` | `TapSettingsView.swift` | `app_settings.py` settings dialog | Settings dialog shell |
| `tap_settings_view_actions.py` | `TapSettingsView+Actions.swift` | `app_settings.py` action handlers | Apply/reset callbacks |
| `tap_settings_view_layout_helpers.py` | `TapSettingsView+LayoutHelpers.swift` | `app_settings.py` layout helpers | Row/section builder helpers |
| `tap_settings_view_sections.py` | `TapSettingsView+Sections.swift` | `app_settings.py` section builders | Individual settings sections |
| `tap_display_settings.py` | `TapDisplaySettings.swift` | `app_settings.py` display constants | `showUnknownModes` implemented; `captureAllPeaks` (max-peaks = 0 toggle) implemented |
| `exportable_spectrum_chart.py` | `ExportableSpectrumChart.swift` | — | ⚠ **GAP** — no off-screen renderer for PDF/image export |
| `pdf_report_generator.py` | `PDFReportGenerator.swift` | `guitar_tap.py` PDF section | ⚠ **PARTIAL** — basic export only; no spectrum image embed |
| `measurement_file_exporter.py` | `MeasurementFileExporter.swift` | `guitar_tap.py` file I/O | JSON/CSV read-write |
| `axis_tick_generator.py` | `AxixTickGenerator.swift` | `fft_canvas.py` tick logic | Frequency/dB axis tick calculation |
| `extensions.py` | `Extensions.swift` | Scattered helpers across files | Utility extensions / free functions |
| `platform_adapters.py` | `PlatformAdapters.swift` | `mac_access.py`, platform guards | macOS permission + platform shims |

---

## Implementation Gaps

| # | Missing item | Priority | Swift equivalent | Notes |
|---|---|---|---|---|
| 1 | `views/measurements/edit_measurement_view.py` | High | `EditMeasurementView.swift` | Entire feature absent — no inline editor for name/notes/type on a saved measurement |
| 2 | `views/shared/loading_overlay.py` | Medium | `LoadingOverlay.swift` | No spinner/progress overlay when loading large files or doing slow I/O |
| 3 | `views/shared/compact_fft_metrics_overlay.py` | Low | `CompactFFTMetricsOverlay.swift` | Small FPS/dt overlay composited on top of spectrum canvas |
| 4 | `views/utilities/exportable_spectrum_chart.py` | Medium | `ExportableSpectrumChart.swift` | Off-screen renderer needed for embedding spectrum image in PDF reports |
| 5 | `views/measurements/export_view.py` (partial) | Low | `ExportView.swift` | Python has file-save dialogs; Swift has an in-app preview + share sheet |
| 6 | `views/utilities/pdf_report_generator.py` (partial) | Medium | `PDFReportGenerator.swift` | Python generates basic text PDF; Swift embeds spectrum chart image |
| 7 | Cursor snap-to-waveform | Low | `SpectrumView+SnapInterpolation.swift` | Logic exists in `fft_canvas.py` but is incomplete vs Swift |

---

## Migration Notes

- Files that currently live at the Python root (`guitar_tap.py`, `fft_canvas.py`, etc.) will move
  into `views/` and be split into mixin modules following the same pattern as `models/`.
- The entry-point (`guitar_tap.py`) will remain at the root, importing from `views/`.
- `mac_access.py` moves to `views/utilities/platform_adapters.py`.
- `gt_images.py` (image resources) moves to `views/utilities/extensions.py` or a dedicated
  `views/utilities/gt_images.py` depending on size.
- The `peaks_model.py`, `peaks_filter_model.py`, `peaks_table.py` files (Qt item model layer)
  sit between views and models; they can live in a `views/peaks/` sub-package or directly
  under `views/` — to be decided during implementation.
