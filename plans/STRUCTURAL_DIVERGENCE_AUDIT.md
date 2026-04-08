# Structural Divergence Audit: Swift ↔ Python

Objective re-analysis of every place where the Python codebase is structurally different from
the Swift codebase. This document does not evaluate whether a difference "affects correctness"
or is "acceptable". It records every difference so that the reader can decide what to act on.

---

## Methodology

Each Swift file was read in full and compared line-by-line against its Python counterpart.
For methods that exist in both, sub-method call order and parameter lists were checked.
For properties, Swift `@Published` declarations (including `didSet`/`willSet` observers) were
compared against Python `Published()` descriptors.

---

## 1. TapToneAnalyzer+AnalysisHelpers.swift  ↔  tap_tone_analyzer_analysis_helpers.py

### 1a. Method parity

| Swift | Python | Notes |
|---|---|---|
| `peakMode(for:) -> GuitarMode` | `peak_mode(peak) -> GuitarMode` | ✓ Same logic |
| `getPeak(for:) -> ResonantPeak?` | `get_peak(mode) -> ResonantPeak \| None` | ✓ Same logic |
| `calculateTapToneRatio() -> Float?` | `calculate_tap_tone_ratio() -> float \| None` | ✓ Same logic |

No methods missing in either direction.

---

## 2. TapToneAnalyzer+PeakAnalysis.swift  ↔  tap_tone_analyzer_peak_analysis.py

### 2a. Method parity

All methods present in both. No missing methods in either direction.

### 2b. `identified_modes` data structure

- **Swift:** `identifiedModes: [(peak: ResonantPeak, mode: GuitarMode)]` — array of named tuples
- **Python:** `identified_modes: list[dict]` — array of dicts `{"peak": p, "mode": m}`

Python uses a dict where Swift uses a named tuple. Every access site must use `entry["peak"]` /
`entry["mode"]` instead of `item.peak` / `item.mode`.

### 2c. `set_tap_num` early-completion in Python

Swift handles early completion inside `numberOfTaps.didSet` on the analyzer.
Python handles it in `tap_tone_analyzer_control.py: set_tap_num()`. The logic is equivalent
but lives in a different file and is invoked imperatively rather than reactively. See §7b.

---

## 3. TapToneAnalyzer+TapDetection.swift  ↔  tap_tone_analyzer_tap_detection.py

### 3a. Method parity

All methods present in both. No missing methods.

### 3b. Threading

- **Swift:** Combine subscription fires on `DispatchQueue.main` (FFT frames arrive on main).
- **Python:** `on_fft_frame` executes on whichever thread Qt delivers the audio callback;
  no explicit thread dispatch is performed.

---

## 4. TapToneAnalyzer+MeasurementManagement.swift  ↔  tap_tone_analyzer_measurement_management.py

### 4a. Methods in Swift with no Python equivalent

| Swift method | Notes |
|---|---|
| `static var measurementsFileURL: URL` | File I/O path lives in model layer in Swift; Python defers to views module |
| `loadPersistedMeasurements()` | Swift loads from disk in model; Python delegates to views layer |
| `persistMeasurements()` | Swift writes to disk in model (background thread); Python calls views-layer helper |
| `exportMeasurement(_:completion:)` | No Python equivalent on the analyzer |

### 4b. Methods in Python with no Swift equivalent

| Python method | Notes |
|---|---|
| `delete_all_measurements()` | Swift has no `deleteAllMeasurements()` |
| `set_measurement_complete(is_complete:)` | Swift manages frozen state differently (via published properties + view logic) |
| `_persist_measurements()` | Helper; calls into views layer |
| `_comparison_label(m)` | Static label-generation helper |

### 4c. `saveMeasurement` parameter structure

- **Swift `saveMeasurement(...)`:** Takes 16+ individual named parameters
  (`tapLocation`, `notes`, `includeSpectrum`, `spectrumSnapshot`, `longitudinalSnapshot`, etc.)
  and builds the `TapToneMeasurement` inside the method.
- **Python `save_measurement(measurement)`:** Takes a single fully-built `TapToneMeasurement`
  object. Assembly is done at the call site (`_collect_measurement()` in the view).

### 4d. `loadMeasurement` architecture

- **Swift `loadMeasurement(_:)`:** 281-line method on the analyzer. Restores all analyzer state
  (`currentPeaks`, `selectedPeakIDs`, `peakModeOverrides`, `annotationVisibilityMode`, etc.)
  via direct property assignment on the analyzer. Sets 28+ `loaded*` @Published properties so
  SwiftUI views can show/hide settings-restored-from-measurement UI reactively.
- **Python:** No `load_measurement` on the analyzer. All restoration is done in
  `_restore_measurement()` in the view layer (~360 lines). Restores state by calling
  `.setValue()` / `.setCurrentText()` directly on UI widgets.

### 4e. `load_comparison` return shape

- **Swift `loadComparison(measurements:)`:** Stores data in `comparisonSpectra:
  [(magnitudes: [Float], frequencies: [Float], color: Color, label: String)]` — a single
  @Published array of 4-tuples.
- **Python `load_comparison(measurements:)`:** Stores data in two separate lists:
  `_comparison_data: list[dict]` and uses `comparisonChanged` signal. Different internal
  shape from Swift.

---

## 5. TapToneAnalyzer+AnnotationManagement.swift  ↔  tap_tone_analyzer_annotation_management.py

### 5a. Thread-safety guards

Swift marks every mutating method "Safe to call from any thread" and implements this via
`Thread.isMainThread` + `DispatchQueue.main.async` dispatch:

| Swift method | Thread-safe? |
|---|---|
| `updateAnnotationOffset(for:offset:)` | ✓ has `Thread.isMainThread` + async dispatch |
| `resetAnnotationOffset(for:)` | ✓ has `Thread.isMainThread` + async dispatch |
| `resetAllAnnotationOffsets()` | ✓ has `Thread.isMainThread` + async dispatch |
| `applyAnnotationOffsets(_:)` | ✓ has `Thread.isMainThread` + async dispatch |
| `getAnnotationOffset(for:)` | read-only, no dispatch needed |
| `selectLongitudinalPeak(_:)` | no dispatch (assumed main-thread only) |
| `selectCrossPeak(_:)` | no dispatch |
| `selectFlcPeak(_:)` | no dispatch |

**Python has NO thread-safety checks or dispatches in any of these methods.**

### 5b. Type differences

| Swift | Python |
|---|---|
| `peakID: UUID` | `peak_id: str` |
| returns / accepts `CGPoint` | returns / accepts `tuple[float, float]` |

### 5c. Methods present in Python but not Swift

Python adds three `@property` computed properties (`effective_longitudinal_peak_id`,
`effective_cross_peak_id`, `effective_flc_peak_id`). Swift computes these as properties
on `TapToneAnalyzer` itself (not in this extension file), so they exist in Swift but in
a different location.

---

## 6. TapToneAnalyzer+ModeOverrideManagement.swift  ↔  tap_tone_analyzer_mode_override_management.py

### 6a. Thread-safety guards

All three Swift methods are marked "Safe to call from any thread" and use
`Thread.isMainThread` + `DispatchQueue.main.async`.

**Python has NO thread-safety checks or dispatches in any of these methods.**

### 6b. Type differences

| Swift | Python |
|---|---|
| `[UUID: UserAssignedMode]` | `dict[str, str]` |

---

## 7. TapToneAnalyzer.swift (property declarations)  ↔  tap_tone_analyzer.py

### 7a. `@Published` properties missing from Python

Swift defines **80 `@Published` properties** in total. Python has **~33**.

The following Swift `@Published` properties have **no Python `Published()` equivalent**:

#### `loaded*` group (28 properties)

These expose measurement-restoration state reactively to SwiftUI views. Python stores the
equivalent data imperatively in the view layer instead.

| Swift property | Type |
|---|---|
| `loadedAxisRange` | `LoadedAxisRange?` |
| `loadedMinFreq` | `Float?` |
| `loadedMaxFreq` | `Float?` |
| `loadedMinDB` | `Float?` |
| `loadedMaxDB` | `Float?` |
| `loadedTapDetectionThreshold` | `Float?` |
| `loadedHysteresisMargin` | `Float?` |
| `loadedPeakThreshold` | `Float?` |
| `loadedNumberOfTaps` | `Int?` |
| `loadedShowUnknownModes` | `Bool?` |
| `loadedGuitarType` | `GuitarType?` |
| `loadedMeasurementType` | `MeasurementType?` |
| `loadedSelectedLongitudinalPeakID` | `UUID?` |
| `loadedSelectedCrossPeakID` | `UUID?` |
| `loadedSelectedFlcPeakID` | `UUID?` |
| `loadedPlateLength` | `Float?` |
| `loadedPlateWidth` | `Float?` |
| `loadedPlateThickness` | `Float?` |
| `loadedPlateMass` | `Float?` |
| `loadedGuitarBodyLength` | `Float?` |
| `loadedGuitarBodyWidth` | `Float?` |
| `loadedPlateStiffnessPreset` | `PlateStiffnessPreset?` |
| `loadedCustomPlateStiffness` | `Float?` |
| `loadedMeasureFlc` | `Bool?` |
| `loadedBraceLength` | `Float?` |
| `loadedBraceWidth` | `Float?` |
| `loadedBraceThickness` | `Float?` |
| `loadedBraceMass` | `Float?` |
| `loadedMeasurementName` | `String?` |

Python stores only `self._loaded_measurement: TapToneMeasurement | None` and two simple
view-state vars (`_loaded_tap_threshold`, `_loaded_tap_num`) in the view layer.

#### Material tap phase / plate-specific group

| Swift property | Type | Python equivalent |
|---|---|---|
| `materialTapPhase` | `MaterialTapPhase` (Published) | Has Python equivalent |
| `longitudinalSpectrum` | `(magnitudes, frequencies)?` (Published) | Not a Published property in Python |
| `crossSpectrum` | `(magnitudes, frequencies)?` (Published) | Not a Published property in Python |
| `longitudinalPeaks` | `[ResonantPeak]` (Published) | Not Published in Python |
| `crossPeaks` | `[ResonantPeak]` (Published) | Not Published in Python |
| `autoSelectedLongitudinalPeakID` | `UUID?` (Published) | Not Published in Python |
| `selectedLongitudinalPeak` | `ResonantPeak?` (Published) | Not Published in Python |
| `userSelectedLongitudinalPeakID` | `UUID?` (Published) | Not Published in Python |
| `autoSelectedCrossPeakID` | `UUID?` (Published) | Not Published in Python |
| `selectedCrossPeak` | `ResonantPeak?` (Published) | Not Published in Python |
| `userSelectedCrossPeakID` | `UUID?` (Published) | Not Published in Python |
| `flcPeaks` | `[ResonantPeak]` (Published) | Not Published in Python |
| `flcSpectrum` | `(magnitudes, frequencies)?` (Published) | Not Published in Python |
| `autoSelectedFlcPeakID` | `UUID?` (Published) | Not Published in Python |
| `selectedFlcPeak` | `ResonantPeak?` (Published) | Not Published in Python |
| `userSelectedFlcPeakID` | `UUID?` (Published) | Not Published in Python |
| `showLoadedSettingsWarning` | `Bool` (Published) | View-layer `_show_loaded_settings_warning` bool |
| `microphoneWarning` | `String?` (Published) | Not Published in Python |
| `sourceMeasurementTimestamp` | `Date?` (Published) | Not Published in Python |
| `displayMode` | `AnalysisDisplayMode` (Published) | Has Python equivalent |
| `comparisonSpectra` | tuple array (Published) | Different structure; see §4e |

### 7b. `@Published` properties whose `didSet` observers have no Python equivalent

Python's `Published` descriptor only emits `_notify_change`. It has no mechanism for
`didSet`-style side effects. These Swift properties have `didSet` blocks that Python
does not replicate in the model layer:

| Swift property | didSet behavior | Python equivalent location |
|---|---|---|
| `peakThreshold` | (1) Persists to `TapDisplaySettings`; (2) calls `recalculateFrozenPeaksIfNeeded()` | Persistence happens in view-layer `_on_apply_settings()`; `recalculateFrozenPeaksIfNeeded()` is not called on threshold change in Python |
| `tapDetectionThreshold` | (1) Persists to `TapDisplaySettings`; (2) clears `showLoadedSettingsWarning` if value ≠ loaded value | Persistence in view-layer `_on_tap_threshold_changed()`; warning cleared via `_clear_loaded_settings_warning()` |
| `hysteresisMargin` | Persists to `TapDisplaySettings` | Persistence in view-layer settings-apply handler |
| `numberOfTaps` | (1) Updates `statusMessage`; (2) triggers early completion if `currentTapCount >= numberOfTaps`; (3) clears warning | Handled in `set_tap_num()` in `tap_tone_analyzer_control.py` (equivalent logic exists); warning cleared in view layer |
| `isMeasurementComplete` | Clears `showLoadedSettingsWarning` when `true` | Handled in view-layer `_clear_loaded_settings_warning()` |

**For `peakThreshold` specifically:** Swift's `didSet` calls `recalculateFrozenPeaksIfNeeded()`
every time the threshold changes. Python does **not** call this when the threshold changes —
only when a measurement is loaded.

---

## 8. TapToneAnalysisView+Export.swift  ↔  `_on_export_pdf` in tap_tone_analysis_view.py

### 8a. Fields passed to PDFReportData by Swift but NOT as explicit parameters in Python

Swift `exportPDFReport()` (line 115) constructs `PDFReportData` with 26 named parameters.
Python calls `M.pdf_report_data_from_measurement(m, png_data, tap_tone_ratio=..., peak_modes=...)`.

The following fields that Swift passes explicitly from the **live analyzer** are instead
derived by Python from the **collected measurement object `m`** (populated by `_collect_measurement()`):

| Swift source | Swift parameter | Python path |
|---|---|---|
| `tap.sourceMeasurementTimestamp ?? Date()` | `timestamp:` | `m.timestamp` (from `_collect_measurement`) |
| `tap.selectedPeakIDs` | `selectedPeakIDs:` | `m.selected_peak_ids` (from `_collect_measurement`) |
| `tap.currentDecayTime` | `decayTime:` | `m.decay_time` (from `_collect_measurement`) |
| `tap.peakModeOverrides` | `peakModeOverrides:` | `m.peak_mode_overrides` (from `_collect_measurement`) |
| `tap.effectiveLongitudinalPeakID` | `selectedLongitudinalPeakID:` | `m.selected_longitudinal_peak_id` |
| `tap.effectiveCrossPeakID` | `selectedCrossPeakID:` | `m.selected_cross_peak_id` |
| `tap.effectiveFlcPeakID` | `selectedFlcPeakID:` | `m.selected_flc_peak_id` |
| `fft.selectedInputDevice?.name` | `microphoneName:` | `m.microphone_name` |
| `fft.activeCalibration?.name` | `calibrationName:` | `m.calibration_name` |
| `TapDisplaySettings.guitarBodyLength` | `guitarBodyLength:` | Derived by `pdf_report_data_from_measurement` from snapshot |
| `TapDisplaySettings.guitarBodyWidth` | `guitarBodyWidth:` | Derived by `pdf_report_data_from_measurement` from snapshot |
| `TapDisplaySettings.plateStiffness` | `plateStiffness:` | Derived by `pdf_report_data_from_measurement` from snapshot |
| `TapDisplaySettings.plateStiffnessPreset` | `plateStiffnessPreset:` | Derived by `pdf_report_data_from_measurement` from snapshot |

Swift reads `guitarBodyLength`, `guitarBodyWidth`, `plateStiffness`, and `plateStiffnessPreset`
from **live `TapDisplaySettings`**. Python reads these from the **snapshot stored inside
the measurement** (via `pdf_report_data_from_measurement`). These are different sources.

### 8b. `peakModeOverrides` parameter not accepted by `pdf_report_data_from_measurement`

Swift passes `peakModeOverrides: tap.peakModeOverrides` directly from the live analyzer to
`PDFReportData`. Python's `pdf_report_data_from_measurement` does not accept a
`peak_mode_overrides` parameter — it always reads `m.peak_mode_overrides`. The live
analyzer's `peak_mode_overrides` is not forwarded explicitly.

---

## 9. `cycle_annotation_visibility` / `cycleAnnotationVisibility`

**Swift** (`TapToneAnalyzer.swift` line 415–418):
```swift
func cycleAnnotationVisibility() {
    annotationVisibilityMode = annotationVisibilityMode.next
    TapDisplaySettings.annotationVisibilityMode = annotationVisibilityMode
}
```
Persistence is in the **model**.

**Python** (`tap_tone_analyzer.py` line 666–672):
```python
def cycle_annotation_visibility(self) -> None:
    """Advance annotation_visibility_mode: all → selected → none → all.

    Persists the new value via TapDisplaySettings.
    Mirrors Swift ``cycleAnnotationVisibility()``.
    """
    self.annotation_visibility_mode = self.annotation_visibility_mode.next
```
The docstring claims persistence but the code **does not call
`TapDisplaySettings.set_annotation_visibility_mode()`**. Persistence is done in the view
layer (`_on_cycle_annotation_mode()` calls `TDS.set_annotation_visibility_mode(next_mode)`).
`cycle_annotation_visibility()` on the analyzer is not the actual UI call site — the view
calls `_on_cycle_annotation_mode` directly, bypassing this method.

---

## 10. `peakThreshold` — `recalculateFrozenPeaksIfNeeded()` not called on change

**Swift** (`TapToneAnalyzer.swift` line 98–103):
```swift
@Published var peakThreshold: Float = TapDisplaySettings.peakThreshold {
    didSet {
        TapDisplaySettings.peakThreshold = peakThreshold
        recalculateFrozenPeaksIfNeeded()
    }
}
```
Every time `peakThreshold` changes, frozen peaks are immediately recalculated.

**Python:** `peak_threshold` is a plain `Published(-60.0)` descriptor. No call to
`recalculate_frozen_peaks_if_needed()` is made when the threshold changes. Recalculation
only happens on explicit user action or measurement load.

---

## 11. Settings persistence architecture

**Swift:** Persistence of analysis settings (`peakThreshold`, `tapDetectionThreshold`,
`hysteresisMargin`) happens in `@Published didSet` observers **in the model layer**.

**Python:** Persistence happens in **view-layer event handlers**:
- `_on_tap_threshold_changed` → `AS.AppSettings.set_tap_threshold()`
- Settings-apply dialog → `AS.AppSettings.set_peak_threshold()`, `set_hysteresis_margin()`

The Python `Published` descriptor has no mechanism for `didSet` observers.

---

## 12. `loadMeasurement` architecture

**Swift:** `loadMeasurement(_:)` is a 281-line method on `TapToneAnalyzer`. It restores all
analyzer state (peaks, selections, overrides, spectra, display settings) via direct
property assignment, then sets 28+ `loaded*` @Published properties so SwiftUI views
reactively show/hide "settings restored from measurement" UI.

**Python:** No equivalent method on the analyzer. All restoration is done in
`_restore_measurement()` (~360 lines) in the **view layer**. The view directly manipulates
UI widgets (`.setValue()`, `.setCurrentText()`) and stores only two values from the loaded
measurement (`_loaded_tap_threshold`, `_loaded_tap_num`) for warning-banner logic.

---

## 13. Comparison data structure

**Swift:** `comparisonSpectra: [(magnitudes: [Float], frequencies: [Float], color: Color, label: String)]`
— single `@Published` array of 4-tuples.

**Python:** `_comparison_data` (list of dicts) + separate `comparison_labels` (list of tuples).
Different shape; accessed via different code paths.

---

## Summary Table

| # | Area | Swift | Python | Difference |
|---|---|---|---|---|
| 1 | `identified_modes` structure | Named tuple array `[(peak:, mode:)]` | Dict array `[{"peak":, "mode":}]` | Different accessor syntax |
| 2 | Thread safety in AnnotationManagement | Every mutating method has `Thread.isMainThread` + `DispatchQueue.main.async` | No thread-safety checks | Absent in Python |
| 3 | Thread safety in ModeOverrideManagement | All 3 methods thread-safe | No thread-safety checks | Absent in Python |
| 4 | `saveMeasurement` parameters | 16+ individual named parameters | Single `TapToneMeasurement` object | Structure differs |
| 5 | `loadMeasurement` location | Model layer (281-line method on analyzer) | View layer (360-line `_restore_measurement`) | Layer inversion |
| 6 | `loaded*` @Published properties | 28+ reactive published properties on analyzer | Not present; view stores 2 plain vars | Absent in Python |
| 7 | Material spectrum @Published properties | `longitudinalSpectrum`, `crossSpectrum`, `longitudinalPeaks`, `crossPeaks`, etc. all @Published | Not Published in Python | Absent in Python |
| 8 | `peakThreshold.didSet` → `recalculateFrozenPeaksIfNeeded()` | Automatic on every threshold change | Not called on threshold change | Missing side effect |
| 9 | Settings persistence location | `@Published didSet` in model | View-layer event handlers | Layer difference |
| 10 | `cycleAnnotationVisibility` persistence | Persists in model method | Model method does not persist; view handler does | Docstring wrong; code path differs |
| 11 | `comparisonSpectra` structure | Single @Published 4-tuple array | Two separate lists | Different shape |
| 12 | PDF export: `guitarBodyLength/Width`, `plateStiffness`, `plateStiffnessPreset` | Read from live `TapDisplaySettings` | Read from measurement snapshot | Different source |
| 13 | PDF export: `peakModeOverrides` | Passed explicitly from live `tap.peakModeOverrides` | Not a parameter; read from `m.peak_mode_overrides` | Not forwarded explicitly |
| 14 | Measurement file I/O | On the model (`measurementsFileURL`, `loadPersistedMeasurements`, `persistMeasurements`) | On views module | Layer difference |
| 15 | `exportMeasurement` | On the analyzer | Not on the analyzer | Absent in Python |
| 16 | `delete_all_measurements` | Not on the analyzer | On the analyzer mixin | Extra in Python |
| 17 | `set_measurement_complete` | Not a single method; managed via @Published properties | Single method on analyzer mixin | Extra in Python |
