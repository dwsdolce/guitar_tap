# Parity Method Call Sites

Analysis of where the 8 methods added for Swift parity are used in Swift,
and whether they have callers in Python yet.

---

## 1. `get_peaks()` / `getPeaks(in:)`

**Swift call sites:** None found — defined but never called.

**Python callers:** None.

---

## 2. `peak_mode()` / `peakMode(for:)`

**Swift call sites:**

- `TapAnalysisResultsView.swift:290` — Maps over identified peaks to pair each
  peak with its classified guitar mode for display in the analysis results view.
- `TapToneAnalyzer.swift:352` — Used inside `effectiveModeLabel` to get the
  display name for a peak when the mode override is set to `.auto`.

**Python callers:** None. The Python `effective_mode_label()` in
`tap_tone_analyzer.py` covers the second use case via a different code path.

---

## 3. `get_peak()` / `getPeak(for:)`

**Swift call sites:**

- `TapToneAnalyzer+AnalysisHelpers.swift:99–100` — Called internally by
  `calculateTapToneRatio()` to retrieve the Air and Top mode peaks.

**Python callers:** Called internally by `calculate_tap_tone_ratio()` — same
as Swift.

---

## 4. `calculate_tap_tone_ratio()` / `calculateTapToneRatio()`

**Swift call sites:**

- `TapAnalysisResultsView.swift:550` — Displays ratio in a "Tap Tone Ratio"
  GroupBox; only shown when a value is available.
- `TapAnalysisResultsView.swift:620` — Formats and displays ratio as "X.XX:1"
  in a secondary location.
- `TapToneAnalysisView+Export.swift:124` — Includes ratio in PDF export data
  as `tapToneRatio: tap.calculateTapToneRatio()`.

**Python callers:** None call `calculate_tap_tone_ratio()`. Python has the
equivalent display and PDF code but computes the ratio inline at each site
instead of delegating to the method:

- `tap_tone_analysis_view.py:2239–2262` — `_on_peaks_changed_ratios()` in
  `MainWindow` (the live results panel, equivalent to `TapAnalysisResultsView`)
  mirrors Swift:550,620 but classifies peaks and computes the ratio inline
  via `GuitarMode._classify_all_tuples()` rather than calling
  `self.fft_canvas.analyzer.calculate_tap_tone_ratio()`. **Needs fix.**
- `tap_tone_analysis_view.py:2881–2904` — `_collect_measurement()` builds a
  `TapToneMeasurement` but never sets `tap_tone_ratio` on it, so the field is
  always `None` when `pdf_report_data_from_measurement()` reads it at line 428.
  The fix is to pass `tap_tone_ratio=self.fft_canvas.analyzer.calculate_tap_tone_ratio()`
  in `TapToneMeasurement.create()`. Mirrors `TapToneAnalysisView+Export.swift:124`.
  **Needs fix.**
- `measurement_detail_view.py:389–412` — `_compute_tap_tone_ratio()` ignores
  `m.tap_tone_ratio` and recomputes inline via `GuitarMode.classify_all()`.
  Should read `m.tap_tone_ratio` first (populated once the §4 fix above lands),
  falling back to inline for measurements saved before the fix. **Needs fix.**

---

## 5. `compare_to()` / `compareTo(_:)`

**Swift call sites:** None found — defined but never called.

**Python callers:** None.

---

## 6. `analyze_magnitudes()` / `analyzeMagnitudes(_:frequencies:peakMagnitude:)`

**Swift call sites:**

- `TapToneAnalyzer.swift:876` — Called via a Combine subscription that fires
  whenever the FFT analyzer produces a new magnitude frame (~1 Hz). This is the
  main live-analysis entry point: tap detection → peak finding → mode
  classification all flow through here.

**Python callers:** None. The Python FFT pipeline calls `find_peaks()` directly
rather than going through `analyze_magnitudes()`.

---

## 7. `reclassify_peaks()` / `reclassifyPeaks()`

**Swift call sites:**

- `TapToneAnalysisView+Layouts.swift:102` — "Apply" button callback in the
  settings sheet (compact layout); re-classifies peaks after parameter changes.
- `TapToneAnalysisView+Layouts.swift:225` — Same "Apply" callback, regular
  layout. Swift implements compact and regular layouts as separate views, so the
  same logical action appears twice. Python has no separate compact/regular
  layout variant — the two Swift sites collapse to **one** Python fix site.
- `TapToneAnalyzer+MeasurementManagement.swift:568` — Called after loading a
  saved measurement to rebuild `identifiedModes` so that
  `calculateTapToneRatio()` and other helpers work immediately without a new tap.

**Python callers:** None. The §7 task therefore identifies **two** Python fix
sites (not three), because the two Layouts callers above are the same logical
action in different layout variants:

1. The settings-apply path — mirrors `Layouts.swift:102` and `:225` combined.
2. The measurement load path — mirrors `MeasurementManagement.swift:568`.

---

## 8. `plate_stiffness()` / `plateStiffness`

**Swift call sites:**

- `TapAnalysisResultsView.swift:993` — called directly to compute Gore thickness
  for the live results view.
- `TapToneAnalysisView+Export.swift:139` — called directly when building
  `PDFReportData` for a live export.

**Python callers:** Both sites resolve the value inline instead of calling
`TDS.plate_stiffness()`:

- `tap_tone_analysis_view.py:2610–2614` — mirrors `TapAnalysisResultsView.swift:993`,
  but resolves `plate_stiffness_preset()` + `custom_plate_stiffness()` inline.
  **Needs fix.**
- `tap_analysis_results_view.py:395–408` — mirrors `TapToneAnalysisView+Export.swift:139`
  for the non-snapshot fallback, but resolves inline. **Needs fix.**

---

## Summary

| Method | Swift callers | Python callers | Status |
|---|---|---|---|
| `get_peaks()` | 0 | 0 | No action needed |
| `peak_mode()` | 2 | 0 | Python uses `effective_mode_label()` instead |
| `get_peak()` | 1 (internal) | 1 (internal) | ✅ Equivalent |
| `calculate_tap_tone_ratio()` | 3 | 0 inline (needs fix) | Python computes ratio inline at 3 sites instead of calling the method |
| `compare_to()` | 0 | 0 | Delete — no callers in either codebase |
| `analyze_magnitudes()` | 1 | 0 | Python FFT pipeline calls `find_peaks()` directly |
| `reclassify_peaks()` | 3 | 0 | Python `set_guitar_type()` / measurement load not wired up |
| `plate_stiffness()` | 2 | 2 inline (needs fix) | 2 sites need updating |

---

## Tasks

- [ ] **§1 — `get_peaks()` removal**: Delete `getPeaks(in:)` from
  `TapToneAnalyzer+AnalysisHelpers.swift` and `get_peaks()` from
  `tap_tone_analyzer_analysis_helpers.py` — both are defined but have zero callers
  in either codebase or tests.
- [ ] **§5 — `compare_to()` removal**: Delete `compareTo(_:)` from
  `TapToneAnalyzer+AnalysisHelpers.swift` and `compare_to()` from
  `tap_tone_analyzer_analysis_helpers.py` — both are defined but have zero callers
  in either codebase or tests.
- [ ] **§8 — `plate_stiffness()` live site**: Update `tap_tone_analysis_view.py:2610–2614`
  to replace the inline `plate_stiffness_preset()` + `custom_plate_stiffness()` resolution
  with `TDS.plate_stiffness()`. Mirrors `TapAnalysisResultsView.swift:993`.
- [ ] **§8 — `plate_stiffness()` PDF factory fallback**: Update
  `tap_analysis_results_view.py:395–408` so the non-snapshot fallback uses
  `TDS.plate_stiffness()` instead of resolving inline. The snapshot-first path
  mirrors `PDFReportGenerator.swift:231` and stays as-is.
- [ ] **§7 — `reclassify_peaks()` wiring**: Wire `reclassify_peaks()` into the Python
  `set_guitar_type()` path and into the measurement load path, mirroring
  `TapToneAnalysisView+Layouts.swift:102,225` and
  `TapToneAnalyzer+MeasurementManagement.swift:568`.
- [ ] **§6 — `analyze_magnitudes()` wiring**: Wire `analyze_magnitudes()` into the
  Python FFT pipeline so it is the entry point for live analysis frames, replacing
  the direct `find_peaks()` call. Mirrors `TapToneAnalyzer.swift:876`.
- [ ] **§4 — `calculate_tap_tone_ratio()` live panel**: Replace inline classification
  in `tap_tone_analysis_view.py:2239–2262` (`_on_peaks_changed_ratios`) with a call to
  `self.fft_canvas.analyzer.calculate_tap_tone_ratio()`. Mirrors `TapAnalysisResultsView.swift:550,620`.
- [ ] **§4 — `calculate_tap_tone_ratio()` measurement collect**: Pass
  `tap_tone_ratio=self.fft_canvas.analyzer.calculate_tap_tone_ratio()` in
  `_collect_measurement()` so the field is populated before `pdf_report_data_from_measurement()`
  reads it. Mirrors `TapToneAnalysisView+Export.swift:124`.
- [ ] **§4 — `calculate_tap_tone_ratio()` measurement detail**: Update
  `measurement_detail_view.py:389–412` (`_compute_tap_tone_ratio`) to read `m.tap_tone_ratio`
  first, falling back to inline compute for older measurements where the field is absent.
- [ ] **§2 — `peak_mode()` display**: Add `peak_mode()` call in the Python results
  view to pair peaks with classified modes for display, mirroring
  `TapAnalysisResultsView.swift:290`.
