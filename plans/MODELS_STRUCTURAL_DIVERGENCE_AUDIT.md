# Models Structural Divergence Audit: Swift ↔ Python

**Methodology**: Every section below is derived directly from reading all Swift `Models/` files and all
Python `models/` files side-by-side. No section was carried forward from memory — source files were
read directly before findings were written.

**Scope**: All files in the Swift `GuitarTap/Models/` tree and all files in the Python `models/`
directory. View files and controller files are excluded; they are covered in a separate audit.

**Sections §1–§13** cover the `TapToneAnalyzer` cluster and are reproduced from the original
`STRUCTURAL_DIVERGENCE_AUDIT.md`. Sections §14 onward cover the remaining model files.

---

## §1 — AnalysisHelpers

### Swift (`TapToneAnalyzer+AnalysisHelpers.swift`, 95 lines)

Three public methods, all read-only queries on `currentPeaks` / `identifiedModes`:

| Swift method | Return type | Notes |
|---|---|---|
| `peakMode(for peak: ResonantPeak) -> GuitarMode` | `GuitarMode` | Looks up `identifiedModes`; falls back to `GuitarMode.classify` |
| `getPeak(for mode: GuitarMode) -> ResonantPeak?` | optional | Returns highest-magnitude peak for the mode |
| `calculateTapToneRatio() -> Float?` | optional | `fTop / fAir`; nil if either peak absent |

### Python (`tap_tone_analyzer_analysis_helpers.py`, 81 lines)

| Python method | Differences |
|---|---|
| `peak_mode(peak)` | Identical logic. Falls back to `GuitarMode.classify(peak.frequency, guitar_type)` with explicit `guitar_type` arg not present in Swift signature (Swift gets `guitarType` from `self`) |
| `get_peak(mode)` | Uses `entry["mode"].normalized == mode.normalized` for comparison; Swift uses `identifiedModes.map { $0.mode }` directly |
| `calculate_tap_tone_ratio()` | Identical algorithm |

**Verdict**: Full method parity. Minor implementation differences only.

---

## §2 — PeakAnalysis

### Swift (`TapToneAnalyzer+PeakAnalysis.swift`, 749 lines)

| Method | Access | Notes |
|---|---|---|
| `analyzeMagnitudes(_:frequencies:peakMagnitude:)` | internal | Calls `findPeaks`, updates `currentPeaks`/`selectedPeakIDs`/`identifiedModes`, emits via `@Published` |
| `recalculateFrozenPeaksIfNeeded()` | internal | Unified path for live and frozen/loaded spectra |
| `resetToAutoSelection()` | internal | Clears `userHasModifiedPeakSelection`, re-runs `guitarModeSelectedPeakIDs` |
| `findPeaks(magnitudes:frequencies:minHz:maxHz:)` | internal | Two-pass: known-mode ranges + inter-mode; uses `lastClaimedFrequency` cursor |
| `applyFrozenPeakState(peaks:modesByFrequency:...)` | private | Remaps offsets/overrides/selections to new UUIDs by frequency proximity |
| `makePeak(at:magnitudes:frequencies:)` | private | Builds `ResonantPeak` with parabolic interpolation + Q factor |
| `guitarModeSelectedPeakIDs(from:)` | internal | Returns `Set<UUID>` of auto-selected peaks per mode |
| `reclassifyPeaks()` | internal | Re-runs mode classification on existing peaks |
| `removeDuplicatePeaks(_:)` | internal | 2 Hz proximity threshold |
| `parabolicInterpolate(magnitudes:frequencies:peakIndex:)` | internal | δ = 0.5·(α−γ)/(α−2β+γ) |
| `calculateQFactor(magnitudes:frequencies:peakIndex:peakMagnitude:)` | internal | −3 dB bandwidth walk |

Note: `averageSpectra(from:)` lives in `+SpectrumCapture.swift` in Swift, not here.

### Python (`tap_tone_analyzer_peak_analysis.py`, 849 lines)

Full method parity for all 11 methods above. Python additionally contains:

- `average_spectra(from_taps)` — placed here rather than in the spectrum-capture mixin. **Critically: has zero callers in the Python codebase — it is dead code.** In Swift, `averageSpectra` is called by all three gated-capture handlers (`handleLongitudinalGatedProgress`, `handleCrossGatedProgress`, `handleFlcGatedProgress`) and by `processMultipleTaps`, all of which live in `TapToneAnalyzer+SpectrumCapture.swift`. The Python spectrum-capture mixin does not call `average_spectra` at all, indicating the multi-tap averaging path is not hooked up in Python.
- `_emit_loaded_peaks_at_threshold()` — extra helper with no direct Swift counterpart; filters `loaded_measurement_peaks` by threshold and emits `peaksChanged`. Swift covers this via `recalculateFrozenPeaksIfNeeded`.

**Key structural differences**:

1. **`analyze_magnitudes` emit**: Swift auto-fires `objectWillChange` via `@Published`. Python explicitly calls `self.peaksChanged.emit(peaks)`.

2. **`identified_modes` type**: Swift stores `[(peak: ResonantPeak, mode: GuitarMode)]` named-field tuples. Python stores `[{"peak": ..., "mode": ...}]` list of dicts.

3. **`recalculate_frozen_peaks_if_needed` guard**: Python adds `if self.is_loading_measurement: return` at the top. Swift has no equivalent flag — measurement loading is synchronous on the main thread.

**Verdict**: Full method parity. Structural difference in `identified_modes` type.

---

## §3 — TapDetection

### Swift (`TapToneAnalyzer+TapDetection.swift`, 450 lines)

| Method | Notes |
|---|---|
| `detectTap(peakMagnitude:magnitudes:frequencies:)` | Hysteresis state machine; guitar = absolute threshold, plate/brace = EMA-relative |
| `handleTapDetection(magnitudes:frequencies:time:)` | Dispatches to guitar path or `handlePlateTapDetection` |
| `totalPlateTaps` (computed var) | `numberOfTaps × 2` or `× 3` with FLC; brace = `numberOfTaps` |
| `handlePlateTapDetection(magnitudes:frequencies:time:)` | Switches on `materialTapPhase`, calls `startGatedCapture` |
| `reEnableDetectionForNextPlateTap()` | `DispatchQueue.main.asyncAfter(tapCooldown)` re-arms |
| `combinePlatePeaks() -> [ResonantPeak]` | Merges L/C/FLC peaks with 5 Hz dedup tolerance |

Swift `handleTapDetection` schedules `processMultipleTaps()` via `DispatchQueue.main.asyncAfter(captureWindow)`. Re-enable after mid-sequence guitar tap uses same `DispatchQueue.main.asyncAfter`.

### Python (`tap_tone_analyzer_tap_detection.py`, 697 lines)

All 6 methods/properties above are present. Python additionally contains:

| Extra Python method | Description |
|---|---|
| `on_fft_frame(...)` | Main-thread FFT frame receiver. Routes to `analyze_magnitudes`, `detect_tap`, `track_decay_fast`, emits spectrum and level signals. Mirrors Swift's `setupSubscriptions()` Combine sinks. |
| `_on_rms_level_changed(rms_amp)` | `@Slot(int)` for plate/brace tap detection at ~43 Hz. Mirrors Swift's fast-path `$inputLevelDB` Combine sink. |
| `reset_tap_detector()` | Restarts warmup; mirrors Swift `analyzerStartTime = Date()` pattern. |
| `_finish_capture()` | `@Slot()` averaging + freeze. Mirrors Swift `finishCapture()` + `processMultipleTaps()`. |
| `_do_reenable_guitar()` | `@Slot()` re-arms detection after guitar tap cooldown. |
| `_do_reenable_detection()` | `@Slot()` re-arms for plate/brace. |

**Thread-safety difference (key)**:

- Swift: `DispatchQueue.main.asyncAfter` — closure runs on main thread automatically.
- Python: `threading.Timer(delay, callback)` fires on a background thread. All timer callbacks post to the main thread via `QMetaObject.invokeMethod(self, "slot_name", QueuedConnection)` before touching any shared state.

This pattern appears in:
- `_handle_tap_detection` → `_finish_capture` (after `capture_window`)
- `_handle_tap_detection` → `_do_reenable_guitar` (after `tap_cooldown`)
- `re_enable_detection_for_next_plate_tap` → `_do_reenable_detection` (after `tap_cooldown`)

**Noise floor re-enable difference**:

- `_do_reenable_guitar` reads `self._current_peak_magnitude_db` (instantaneous FFT peak, ~2.7 Hz). Mirrors Swift reading `fftAnalyzer.peakMagnitude`.
- `_do_reenable_detection` reads `self._current_input_level_db` (instantaneous RMS, ~43 Hz). Mirrors Swift reading `fftAnalyzer.inputLevelDB`. This distinction prevents the 0.5 s rolling `recent_peak_level_db` from incorrectly latching `is_above_threshold = True`.

**Verdict**: Full method parity. Python adds the `@Slot` targets for timer callbacks and the `on_fft_frame`/`_on_rms_level_changed` signal-wiring equivalents, which replace Swift's Combine subscriptions and `DispatchQueue.main.asyncAfter` calls.

---

## §4 — MeasurementManagement

### Swift (`TapToneAnalyzer+MeasurementManagement.swift`, 733 lines)

| Method | Notes |
|---|---|
| `loadPersistedMeasurements()` | Loads JSON from Documents directory |
| `persistMeasurements()` | Saves JSON to Documents directory |
| `saveMeasurement(peaks:selectedPeakIDs:decayTime:tapToneRatio:...)` | **14 named parameters**; builds `TapToneMeasurement` and appends |
| `updateMeasurement(_:with:)` | Replaces a measurement in-place |
| `deleteMeasurement(_:)` | Removes by ID |
| `importMeasurements(from:)` | Full import with image loading + mic warning |
| `importMeasurements(json:)` | Simple string-based import, no images |
| `loadMeasurement(_:)` | Comprehensive restore — see §11 |
| `exportMeasurement(_:completion:)` | Background-queue JSON encoding |
| `loadComparison(measurements:)` | Loads comparison spectra + axis range |
| `clearComparison()` | Removes comparison spectra |

### Python (`tap_tone_analyzer_measurement_management.py`)

| Python method | Swift equivalent |
|---|---|
| `_persist_measurements()` | `persistMeasurements()` |
| `import_measurements(path)` | `importMeasurements(from:)` |
| `import_measurements_from_data(data)` | `importMeasurements(json:)` |
| `save_measurement(measurement)` | `saveMeasurement(...)` — **takes a pre-built object, not 14 params** |
| `update_measurement(measurement)` | `updateMeasurement(_:with:)` |
| `delete_measurement(measurement_id)` | `deleteMeasurement(_:)` |
| `delete_all_measurements()` | No direct Swift counterpart in this file |
| `set_measurement_complete(measurement_id)` | No Swift counterpart |
| `load_comparison(measurements)` | `loadComparison(measurements:)` |
| `clear_comparison()` | `clearComparison()` |

**Key divergences**:

1. **`save_measurement` signature**: Python takes a pre-built `TapToneMeasurement` object. Swift `saveMeasurement` takes 14 individual named parameters and builds the object internally — the model is the factory. This is an architectural difference: Swift keeps measurement assembly in the model layer, while Python's assembly happens in `_collect_measurement()` in the view layer (`tap_tone_analysis_view.py`), which calls `TapToneMeasurement.create()` (a 25-parameter factory on the model) and then passes the result to `save_measurement()`. The Swift approach is architecturally preferred — the view should not be responsible for constructing model objects. The import path (`_on_import()` in `measurements_list_view.py`) passes already-deserialized objects, so it legitimately needs a separate lower-level entry point.

2. **`load_measurement` location**: Swift `loadMeasurement(_:)` lives here (~280 lines; restores full analyzer state from a measurement). Python's equivalent is `_restore_measurement()` in `tap_tone_analysis_view.py` (~350 lines) — **not** in the model layer at all. There is no `load_measurement` in any Python model file. The function name differs and the location is in the view layer, not the model layer.

3. **`load_persisted_measurements` location**: Not in Python's MeasurementManagement mixin. Equivalent initialisation happens in `tap_tone_analyzer.py` `__init__`.

4. **`exportMeasurement`**: No Python equivalent in this mixin. Python export is handled by the view layer (`tap_tone_analysis_view_export.py`, currently a stub).

5. **Persistence mechanism**: Swift writes a single JSON file to the Documents directory. Python delegates to `save_all_measurements` via the view layer.

**Verdict**: Partial structural divergence. Python mixin covers save/delete/compare but omits `load_measurement` and `load_persisted_measurements`. `save_measurement` signature is fundamentally different.

---

## §5 — AnnotationManagement

### Swift (`TapToneAnalyzer+AnnotationManagement.swift`, 188 lines)

| Method | Notes |
|---|---|
| `updateAnnotationOffset(_:for:)` | Sets per-peak offset in `peakAnnotationOffsets` |
| `getAnnotationOffset(for:)` | Returns offset or `(0,0)` |
| `resetAnnotationOffset(for:)` | Removes single entry |
| `resetAllAnnotationOffsets()` | Clears all |
| `applyAnnotationOffsets(_:)` | Replaces entire dict |
| `selectLongitudinalPeak(_:)` | Sets `selectedLongitudinalPeak`; calls `resolvedPlatePeaks`; updates `currentPeaks` |
| `selectCrossPeak(_:)` | Same for cross |
| `selectFlcPeak(_:)` | Same for FLC |

`effectiveLongitudinalPeakID`, `effectiveCrossPeakID`, `effectiveFlcPeakID` are **computed vars in `TapToneAnalyzer.swift`** (main file), not in `+AnnotationManagement.swift`. Swift logic is three-layer:

```swift
effectiveLongitudinalPeakID =
    userSelectedLongitudinalPeakID
    ?? selectedLongitudinalPeak?.id      // ← phase-stored peak (middle layer)
    ?? autoSelectedLongitudinalPeakID
```

### Python (`tap_tone_analyzer_annotation_management.py`)

Same 8 methods with snake_case names — full parity.

`effective_longitudinal_peak_id`, `effective_cross_peak_id`, `effective_flc_peak_id` are **properties in this mixin** (not in main `tap_tone_analyzer.py`). Their Python logic is **two-layer**:

```python
@property
def effective_longitudinal_peak_id(self):
    return self.user_selected_longitudinal_peak_id or self.auto_selected_longitudinal_peak_id
```

**The middle layer (`selected_longitudinal_peak?.id`) is absent from Python's effective-ID resolution.** Python has `self.selected_longitudinal_peak` as an instance attribute (set in `_reset_material_phase_state`) but `effective_longitudinal_peak_id` does not consult it.

**Verdict**: Method parity. Structural difference: Swift three-layer `effectiveXxxPeakID` resolution vs Python two-layer (missing `selectedXxxPeak?.id` middle layer).

---

## §6 — ModeOverrideManagement

### Swift (`TapToneAnalyzer+ModeOverrideManagement.swift`, 99 lines)

| Method | Notes |
|---|---|
| `applyModeOverrides(_ overrides: [UUID: UserAssignedMode])` | Replaces entire dict |
| `resetAllModeOverrides()` | Clears all overrides |
| `resetModeOverride(for peakID: UUID)` | Removes single entry |

### Python (`tap_tone_analyzer_mode_override_management.py`, 74 lines)

| Python method | Notes |
|---|---|
| `apply_mode_overrides(overrides: dict[str, str])` | `overrides` is `{UUID-string → mode-label-string}` vs Swift `[UUID: UserAssignedMode]` |
| `reset_all_mode_overrides()` | Identical |
| `reset_mode_override(peak_id: str)` | Identical |

**Verdict**: Full method parity. Type difference: Swift uses typed `UUID` keys and `UserAssignedMode` values; Python uses plain strings for both.

---

## §7 — TapToneAnalyzer Main Class

### Swift (`TapToneAnalyzer.swift`, 975 lines) — key `@Published` properties

**Analysis-state properties** (with `didSet` side effects noted):

| Property | Type | `didSet` side effect |
|---|---|---|
| `peakThreshold` | `Float` | Calls `recalculateFrozenPeaksIfNeeded()` + persists to `TapDisplaySettings` |
| `minFrequency` | `Float` | None |
| `maxFrequency` | `Float` | None |
| `numberOfTaps` | `Int` | Updates status if detecting; triggers `processMultipleTaps` if already have enough taps |
| `tapDetectionThreshold` | `Float` | Persists to `TapDisplaySettings`; clears `showLoadedSettingsWarning` |
| `hysteresisMargin` | `Float` | Persists to `TapDisplaySettings` |
| `isMeasurementComplete` | `Bool` | Clears `showLoadedSettingsWarning` when set to `true` |
| `displayMode` | `AnalysisDisplayMode` | None |
| `comparisonSpectra` | array | None |

**Loaded-measurement `@Published` properties** (lines 600–657):

`loadedPeakThreshold`, `loadedNumberOfTaps`, `loadedShowUnknownModes`, `loadedGuitarType`, `loadedMeasurementType`, `showLoadedSettingsWarning`, `microphoneWarning`, `loadedSelectedLongitudinalPeakID`, `loadedSelectedCrossPeakID`, `loadedSelectedFlcPeakID`, `loadedPlateLength`, `loadedPlateWidth`, `loadedPlateThickness`, `loadedPlateMass`, `loadedGuitarBodyLength`, `loadedGuitarBodyWidth`, `loadedPlateStiffnessPreset`, `loadedCustomPlateStiffness`, `loadedMeasureFlc`, `loadedBraceLength`, `loadedBraceWidth`, `loadedBraceThickness`, `loadedBraceMass`, `sourceMeasurementTimestamp`, `loadedMeasurementName`

**Gated FFT state** (non-`@Published`, lines 679–743):

`mpmLock`, `gatedCaptureActive`, `gatedAccumBuffer`, `gatedCaptureCompletion`, `gatedCapturePhase`, `mpmSampleRate`, `preRollBuffer`, `noiseFloorEstimate`, `noiseFloorAlpha`

**Atomic helpers**:
- `setFrozenSpectrum(frequencies:magnitudes:)` — calls `objectWillChange.send()` before assigning both arrays to prevent SwiftUI from seeing a length mismatch mid-render.
- `setLoadedAxisRange(minFreq:maxFreq:minDB:maxDB:)` — same pattern for four axis bounds.

**`init` / `setupSubscriptions`**:

`init(fftAnalyzer:)` restores persisted settings from `TapDisplaySettings`, calls `loadPersistedMeasurements()`, then `setupSubscriptions()`. `setupSubscriptions()` wires 4 Combine sinks:
1. `$magnitudes + $frequencies + $peakMagnitude` → `analyzeMagnitudes` (~1 Hz, main thread)
2. `$inputLevelDB` → `trackDecayFast` (~10 Hz, main thread)
3. `$inputLevelDB` (plate/brace only, guarded) → `detectTap` (~10 Hz, main thread)
4. `$routeChangeRestartCount` → `handleRouteChangeRestart` (main thread)

**`handleRouteChangeRestart`**: 2-second settle delay; re-anchors `isAboveThreshold` to current `peakMagnitude`; restores `isDetecting` state.

### Python (`tap_tone_analyzer.py`, 680 lines) — equivalents

Python replaces every `@Published` property with a plain instance attribute (`self.x = default` in `__init__`) plus explicit Qt signals defined at class level. Reactivity is opt-in.

**`didSet` side effects — replication status**:

| Swift `didSet` | Python replication |
|---|---|
| `peakThreshold.didSet` → `recalculateFrozenPeaksIfNeeded()` + persist | `set_threshold()` in `control.py` calls recalculate ✅ but does **not** persist to `TapDisplaySettings` ❌ |
| `tapDetectionThreshold.didSet` → persist + clear warning | `set_tap_threshold()` sets value only — neither persist nor warning-clear ❌ |
| `hysteresisMargin.didSet` → persist | `set_hysteresis_margin()` sets value only — no persist ❌ |
| `isMeasurementComplete.didSet` → clear warning | Not replicated as a helper; handled contextually ❌ |
| `numberOfTaps.didSet` → process if enough taps | `set_tap_num()` handles the early-process case ✅ |

**`setFrozenSpectrum` / `setLoadedAxisRange` atomicity**: Not replicated. `frozen_frequencies` and `frozen_magnitudes` are assigned as separate lines at multiple call sites. There are no dedicated `frozen_frequencies_changed` or `frozen_magnitudes_changed` signals; the view is normally notified via `spectrumUpdated`, which carries both arrays as a single payload — so that path is safe. However, direct property access in `tap_tone_analysis_view.py` (lines 2776, 3136, 3424) reads `frozen_frequencies` and `frozen_magnitudes` independently and could observe a half-updated state if called between the two assignments. A `set_frozen_spectrum()` helper matching the Swift function would eliminate this race.

**`handleRouteChangeRestart`**: Not replicated. Python's `_on_devices_refreshed` calls `mic.reinitialize_portaudio()` and emits `devicesChanged`, but the 2-second settle delay and `isAboveThreshold` re-anchor are absent.

**Python-only properties / methods on main class**:

| Python | Notes |
|---|---|
| `is_comparing` (property) | Returns `self._display_mode == COMPARISON`; no Swift equivalent |
| `n_fmin`, `n_fmax` (computed properties) | FFT bin index for `min_frequency`/`max_frequency`; no Swift equivalent |
| `saved_measurements` / `savedMeasurements` | Legacy alias pair |
| `set_material_spectra(longitudinal, cross, flc)` | Aggregates spectra for the spectrum view; no direct Swift equivalent |
| `recreate_proc_thread()` | Python-only audio pipeline management |
| `display_mode` (property with setter) | Setter emits `displayModeChanged`; Swift uses `@Published var displayMode` |

**Verdict**: All properties present in Python as plain instance attributes. Key gaps: `tapDetectionThreshold` and `hysteresisMargin` setter side effects (persist to settings) not replicated; `setFrozenSpectrum` atomicity not replicated; `handleRouteChangeRestart` 2-second settle not replicated. Python has `is_comparing`, `n_fmin`, `n_fmax` with no Swift equivalent.

---

## §8 — PDF Export

### Swift (`PDFReportGenerator.swift`, 1040 lines)

`PDFReportData` is a value struct with ~25 fields including: `timestamp`, `tapLocation`, `notes`, `measurementType`, `guitarType`, `peaks`, `selectedPeakIDs`, `decayTime`, `tapToneRatio`, `spectrumImageData`, `minFreq`, `maxFreq`, `plateProperties`, `braceProperties`, `selectedLongitudinalPeakID`, `selectedCrossPeakID`, `selectedFlcPeakID`, `peakModeOverrides`, `peakModes`, `microphoneName`, `calibrationName`, `guitarBodyLength`, `guitarBodyWidth`, `plateStiffness`, `plateStiffnessPreset`.

`PDFReportData.from(measurement:spectrumImageData:)` — static factory that re-derives `PlateProperties`/`BraceProperties` from stored dimensions and peak IDs.

`PDFReportGenerator.generate(data:)` — must be called on `@MainActor`; uses `ImageRenderer` to render `PDFReportContentView` into a `CGContext` PDF page.

### Python

`tap_tone_analysis_view_export.py` is a **stub** (15 lines, docstring only). No `PDFReportData` struct or `PDFReportGenerator` equivalent exists. The comment states: "Pending: extract the export-related callbacks from `tap_tone_analysis_view.MainWindow`".

**Verdict**: Swift has a full PDF report pipeline. Python has a stub with no PDF export implementation.

---

## §9 — `cycleAnnotationVisibility` Persistence

### Swift (`TapToneAnalyzer.swift`)

```swift
func cycleAnnotationVisibility() {
    // cycles .all → .selected → .none → .all
    TapDisplaySettings.annotationVisibilityMode = annotationVisibilityMode  // ← persists
}
```

### Python (`tap_tone_analyzer.py`)

```python
def cycle_annotation_visibility(self):
    # cycles self.annotation_visibility_mode
    # does NOT write to TapDisplaySettings
```

**Verdict**: Python `cycle_annotation_visibility` does not persist the new mode to `TapDisplaySettings`. This is a confirmed missing side effect.

---

## §10 — Settings Persistence on Property Write

### Swift

Four properties auto-persist via `didSet`:

| Property | Persists to |
|---|---|
| `peakThreshold` | `TapDisplaySettings.peakThreshold` |
| `tapDetectionThreshold` | `TapDisplaySettings.tapDetectionThreshold` |
| `hysteresisMargin` | `TapDisplaySettings.hysteresisMargin` |
| `annotationVisibilityMode` (via `cycleAnnotationVisibility`) | `TapDisplaySettings.annotationVisibilityMode` |

### Python

| Property | Persists? |
|---|---|
| `peak_threshold` via `set_threshold()` | ❌ `recalculate_frozen_peaks_if_needed()` is called but `TapDisplaySettings.peak_threshold` is NOT written |
| `tap_detection_threshold` via `set_tap_threshold()` | ❌ Not persisted |
| `hysteresis_margin` via `set_hysteresis_margin()` | ❌ Not persisted |
| `annotation_visibility_mode` via `cycle_annotation_visibility()` | ❌ Not persisted |

**Verdict**: None of the four settings-persistence `didSet` side effects are replicated in Python. Settings written during a session are lost on restart.

---

## §11 — `loadMeasurement` Comprehensiveness

### Swift (`TapToneAnalyzer+MeasurementManagement.swift`, ~lines 450–628)

`loadMeasurement(_:)` performs:
1. Freezes spectrum via `setFrozenSpectrum`; sets `isMeasurementComplete = true`
2. Loads peaks into `loadedMeasurementPeaks`; calls `recalculateFrozenPeaksIfNeeded()`
3. Restores `selectedPeakIDs` from `measurement.selectedPeakIDs`
4. Restores mode overrides via `applyModeOverrides`
5. Restores annotation offsets via `applyAnnotationOffsets`
6. Restores axis range atomically via `setLoadedAxisRange`
7. Sets `showLoadedSettingsWarning = true`
8. Sets all loaded-settings `@Published` vars: `loadedPeakThreshold`, `loadedNumberOfTaps`, `loadedGuitarType`, `loadedMeasurementType`, all plate/brace dimension properties
9. Restores plate/brace phase peaks: `longitudinalPeaks`, `crossPeaks`, `flcPeaks`, `selectedLongitudinalPeak`, etc.
10. Auto-selects/warns microphone: tries UID match, then name match; emits `microphoneWarning` if not found

### Python

Python's `load_measurement` equivalent is in `tap_tone_analyzer_control.py`. It performs the same logical steps. Differences:

- Uses `self._set_material_tap_phase(phase)` to emit `plateStatusChanged` instead of direct assignment.
- Axis range restore assigns `self.loaded_min_freq` etc. individually (no atomic helper).
- Microphone device-switch logic is delegated to the view layer; only `self.microphone_warning` is set here.
- `show_loaded_settings_warning = True` with explicit signal emit.

**Verdict**: Structural parity. Axis range restore is non-atomic in Python.

---

## §12 — Comparison Overlay

### Swift (`TapToneAnalyzer+MeasurementManagement.swift`, lines 682–731)

`loadComparison(measurements:)`:
- Filters to measurements with `spectrumSnapshot != nil`
- Assigns colors from a 5-color palette cycling by index
- Calls `setLoadedAxisRange` atomically with union of all snapshot axis ranges
- Sets `displayMode = .comparison` (or `.live` if empty)

`clearComparison()`: sets `comparisonSpectra = []`, `displayMode = .live`

### Python (`tap_tone_analyzer_measurement_management.py`)

`load_comparison(measurements)` and `clear_comparison()` are present. Differences:

- Uses matching 5-color `comparisonPalette`
- Axis range: assigns `self.loaded_min_freq` etc. individually — **no atomic helper**
- Emits `comparisonLoaded` signal after loading (no Swift equivalent signal; Swift uses `@Published`)
- `clear_comparison()` sets `self.comparison_spectra = []` and emits `displayModeChanged`

**Verdict**: Functional parity. Axis range assignment is non-atomic in Python. Python emits an additional `comparisonLoaded` signal.

---

## §13 — Control (start/stop/reset/tap-sequence)

### Swift (`TapToneAnalyzer+Control.swift`, 348 lines)

| Method | Notes |
|---|---|
| `start()` | Starts `fftAnalyzer`; sets `isReadyForDetection = true` |
| `stop()` | Stops `fftAnalyzer` |
| `reset()` | Stops detection; calls `resetMaterialPhaseState(.notStarted)` + `resetDecayTracking`; clears frozen spectrum, peaks, annotation offsets; clears loaded-measurement state |
| `startTapSequence()` | Seeds noise floor; resets per-sequence state; arms detection; sets status message |
| `pauseTapDetection()` | No-op if not detecting/already paused; sets `isDetectionPaused = true` |
| `resumeTapDetection()` | Resets warm-up timer; re-arms detection; restores prompt |
| `cancelTapSequence()` | Like reset but keeps detection active |
| `resetMaterialPhaseState(to:)` | private; clears all phase state |
| `resetDecayTracking()` | private; stops timer, clears flag |

### Python (`tap_tone_analyzer_control.py`, 466 lines)

All methods above are present with snake_case names plus additional Python-only methods:

| Extra Python method | Description |
|---|---|
| `_set_status_message(message)` | Assigns `status_message` + emits `statusMessageChanged`. Mirrors Swift `@Published statusMessage` auto-emit. |
| `_on_devices_refreshed()` | Hot-plug handler; no Swift equivalent in Control |
| `load_calibration(path)` | Loads calibration file |
| `load_calibration_from_profile(cal)` | Applies pre-parsed calibration |
| `clear_calibration()` | Removes calibration |
| `current_calibration_device()` | Returns calibration device name |
| `set_device(device)` | Switches input device; syncs `fft_data.sample_freq` |
| `_on_mic_calibration_changed(cal)` | Applies/clears calibration from device switch |
| `set_tap_threshold(value)` | Sets `tap_detection_threshold` (no persist) |
| `set_hysteresis_margin(value)` | Sets `hysteresis_margin` (no persist) |
| `set_measurement_type(measurement_type)` | Sets `_measurement_type` |
| `set_threshold(threshold)` | Sets `peak_threshold` + calls `recalculate_frozen_peaks_if_needed` |
| `set_fmin / set_fmax / update_axis` | Update frequency analysis range |
| `set_max_average_count / reset_averaging / set_avg_enable / set_auto_scale` | Additional parameter setters |
| `_reset_material_phase_state(to)` | private; mirrors Swift; includes gated-capture cancel |
| `_reset_decay_tracking()` | private; mirrors Swift |

**Verdict**: Full parity for the core 9 methods. Python adds `_set_status_message` (explicitly required since `status_message` is not `@Published`), calibration management, and additional parameter setters that are handled elsewhere in Swift.

---

## §14 — ResonantPeak

### Swift (`ResonantPeak.swift`)

`ResonantPeak` is a `struct` conforming to `Identifiable`, `Codable`, `Equatable`, `Hashable`.

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` | Auto-generated; used as `Identifiable` key |
| `frequency` | `Float` | Hz |
| `magnitude` | `Float` | dBFS |
| `quality` | `Float` | Q factor (−3 dB bandwidth method) |
| `bandwidth` | `Float` | Hz |
| `timestamp` | `Date` | When peak was detected |
| `pitchNote` | `String` | Nearest ET note name, e.g. "A4" |
| `pitchCents` | `Float` | Signed cents offset from nearest note |
| `pitchFrequency` | `Float` | Exact frequency of nearest note |

Serialisation: `Codable` auto-synthesis. `UUID` encodes as a string; `Date` encodes as ISO-8601.
No `mode_label` field.

### Python (`resonant_peak.py`)

`ResonantPeak` is a `@dataclass`.

| Field | Type vs Swift |
|---|---|
| `id` | `str` (UUID string, not `UUID`) |
| `frequency`, `magnitude`, `quality`, `bandwidth` | `float` — equivalent |
| `timestamp` | `str` (ISO-8601 string, not `Date`) |
| `pitch_note`, `pitch_cents`, `pitch_frequency` | `str`/`float` — equivalent |
| `mode_label` | `str = ""` — **Python-only field** |

Serialisation: explicit `to_dict()` / `from_dict()`.
Additional property `formatted_pitch` (Python-only) — combines note name and cents offset.

**Divergences**:

1. `id` is `str` in Python vs `UUID` in Swift. Comparison across the boundary must use `str(peak.id)`.
2. `timestamp` is `str` in Python vs `Date` in Swift.
3. `mode_label: str = ""` is Python-only — used as a display-time hint; Swift has no equivalent field.
4. `formatted_pitch` property is Python-only.

**Verdict**: Field parity (excluding `mode_label`). Type divergence on `id` and `timestamp`. Python adds one extra field and one extra property.

---

## §15 — GuitarMode

### Swift (`GuitarMode.swift`)

`GuitarMode` is an `enum` with `String` raw values. Cases (current):

`air`, `top`, `back`, `dipole`, `ringMode`, `upperModes`, `unknown`

Legacy/additional labels are handled separately. Key methods:

| Method/Property | Notes |
|---|---|
| `classify(frequency:guitarType:)` | Static; returns the mode whose range contains the frequency |
| `classifyAll(peaks:guitarType:)` | Static; claiming algorithm using `Set<UUID>` |
| `isKnown` (var) | `self != .unknown` |
| `modeRange(for:)` | Returns `ClosedRange<Float>?` for the guitar type |
| `displayName`, `color`, `abbreviation`, `description`, `icon` | UI properties |
| `normalized` | Returns canonical mode (maps legacy to current) |

### Python (`guitar_mode.py`)

`GuitarMode(Enum)` with 7 current cases + 4 legacy cases. Raw values are strings: `"air"`, `"top"`, `"back"`, `"dipole"`, `"Ring Mode"`, `"Upper Modes"`, `"unknown"`. Raw values match Swift exactly — no cross-platform serialisation risk.

**Python-only additions**:

| Addition | Notes |
|---|---|
| `from_mode_string(s)` | Maps legacy string representations to `GuitarMode`; no Swift counterpart |
| `_classify_all_tuples(peak_tuples, guitar_type)` | Variant of `classify_all` that takes `(freq, uuid)` tuples; used for numpy array pipelines |
| `_PYTHON_STR_TO_MODE` | Class-level dict mapping legacy strings |
| `current_cases` (class attr) | Set of non-legacy cases; assigned post-class-body |
| `additional_mode_labels` (class attr) | Set of strings for user-entered modes not in the enum |
| `get_bands(guitar_type)` | Module-level function; returns `[(name, low, high)]` list |
| `in_mode_range(frequency, mode, guitar_type)` | Module-level helper |
| `classify_peak(peak, guitar_type)` | Module-level helper wrapping `GuitarMode.classify()` |
| `mode_display_name(mode_or_label)` | Module-level function for display string; handles strings and GuitarMode values |

**Verdict**: Full algorithmic parity. Python adds module-level helper functions and a legacy-string mapping. Raw values for all cases (including `ringMode`/`upperModes`) match between platforms — no serialisation risk.

---

## §16 — GuitarType

### Swift (`GuitarType.swift`)

`GuitarType` enum with `String` raw values: `classical`, `flamenco`, `acoustic`.

`ModeRanges` is a struct with `ClosedRange<Float>` fields.
`DecayThresholds` is a struct with `Float` fields.

`decay_quality_label(for:)` — static func on `Float` extension: takes a Float (quality value) and a GuitarType, returns a `String` label.

### Python (`guitar_type.py`)

`GuitarType(Enum)` with same 3 cases and same raw values.

`ModeRanges` — `@dataclass(frozen=True)` with `tuple[float, float]` fields (not `ClosedRange`).
`DecayThresholds` — `@dataclass(frozen=True)` with `float` fields — equivalent.

`decay_quality_label(quality)` — method on `GuitarType` itself (not a Float extension). Takes the quality float as a parameter.

**Divergences**:

1. `ModeRanges` uses `tuple[float, float]` in Python vs `ClosedRange<Float>` in Swift. Range containment check differs: Python `low <= freq <= high` vs Swift `range.contains(freq)`.
2. `decay_quality_label` is a method on `GuitarType` in Python vs a static func on `Float` extension in Swift. Callable as `guitar_type.decay_quality_label(q)` (Python) vs `q.decayQualityLabel(for: guitarType)` (Swift).

**Verdict**: Algorithmic parity. Structural difference in `ModeRanges` field types and `decay_quality_label` ownership.

---

## §17 — MeasurementType

### Swift (`MeasurementType.swift`)

`MeasurementType` enum with `String` raw values: `guitar`, `top`, `back`, `flc`, `brace`.

`isPlate` computed var: `self == .top || self == .back || self == .flc`

### Python (`measurement_type.py`)

`MeasurementType(Enum)` with same 5 cases and same raw values.

**Python-only additions**:

| Addition | Notes |
|---|---|
| `is_plate` property | Equivalent to Swift `isPlate`; present in Python (Swift has this too — parity) |
| `storage_key` property | Returns a short key string for QSettings persistence; no Swift equivalent |
| `from_string(s)` | Maps raw string to enum; no Swift equivalent (Swift uses `MeasurementType(rawValue:)`) |
| `from_combo_values(guitar_type, is_plate)` | Factory combining guitar type and plate flag; no Swift equivalent |

**Verdict**: Enum parity. Python adds `storage_key`, `from_string`, and `from_combo_values` as Python-specific convenience additions.

---

## §18 — TapToneMeasurement

### Swift (`TapToneMeasurement.swift`)

`TapToneMeasurement` is a `struct` conforming to `Codable`, `Identifiable`, `Equatable`.

Key fields: `id: UUID`, `timestamp: Date`, `measurementName: String?`, `guitarType: GuitarType`, `measurementType: MeasurementType`, `peaks: [ResonantPeak]`, `selectedPeakIDs: Set<UUID>`, `peakModeOverrides: [UUID: UserAssignedMode]`, `peakAnnotationOffsets: [UUID: CGPoint]`, `spectrumSnapshot: SpectrumSnapshot?`, `decayTime: Float?`, `tapToneRatio: Float?`, plate/brace dimension fields, `notes: String`, `tapLocation: String`, `microphoneName: String`, `calibrationName: String`, `guitarBodyLength: Float`, `guitarBodyWidth: Float`, `plateStiffnessPreset: PlateStiffnessPreset`, `customPlateStiffness: Float`, `measureFlc: Bool`, `measurementComplete: Bool`.

`tapToneRatio` is stored as a persisted value (computed at save time).

Serialisation: `Codable` auto-synthesis. `measurementType` and `guitarType` are serialised as enum raw values automatically.

### Python (`tap_tone_measurement.py`)

`TapToneMeasurement` is a `@dataclass` (~25 fields).

**Divergences**:

1. `id` stored as `str` (UUID string) vs Swift `UUID`. Comparison must use string form.
2. `timestamp` stored as `str` (ISO-8601) vs Swift `Date`.
3. `measurement_type` and `guitar_type` stored as plain enum values (convenience fields); Swift stores them as typed fields but must handle decoding.
4. `annotation_offsets` stored as `{str: [float, float]}` (UUID-string → `[x, y]` list); Swift stores as `[UUID: CGPoint]`.
5. `peak_mode_overrides` stored as `{str: str}` (UUID-string → mode-label-string); Swift stores as `[UUID: UserAssignedMode]`.
6. `tap_tone_ratio` property needs explicit `guitar_type` resolution in Python; Swift returns stored value.
7. `display_name()` method is Python-only — returns a human-readable measurement name.
8. `with_()` uses `dataclasses.replace()` (Python); Swift uses struct mutation.
9. `create()` factory classmethod (Python-only) — sets `id` and `timestamp` defaults.

**Verdict**: Full field parity. Type divergence on `id`, `timestamp`, `annotation_offsets`, and `peak_mode_overrides` (strings vs typed values). Python adds `display_name()` and `create()`.

---

## §19 — MaterialProperties

### Swift (`MaterialProperties.swift`)

**`MaterialDimensions` struct**: Stores SI values directly (`length: Float` in metres, `width: Float` in metres, `thickness: Float` in metres, `mass: Float` in kg). No unit-conversion methods — values are stored in SI.

**`PlateProperties` struct**: Computed vars for `youngsModulus: Float`, `speedOfSound: Float`, `specificModulus: Float`, `radiationRatio: Float`, `soundToWeightRatio: Float`, `woodQuality: WoodQuality`.

**`BraceProperties` struct**: Fields `dimensions: MaterialDimensions`, `fundamentalFrequencyLong: Float`. Computed vars: `youngsModulusLong`, `speedOfSoundLong`, `youngsModulusLongGPa`, `specificModulusLong`, `radiationRatioLong`, `spruceQuality`. Coefficient `22.37332` (slightly more precise than plate's `22.37`).

**`TonewoodReference` struct**: 4 static tuple constants: `sitkaSpruceTypical`, `engelmannSpruceTypical`, `europeanSpruceTypical`, `westernRedCedarTypical`. Each is a `(length: Float, width: Float, thickness: Float, mass: Float, fundamentalFrequencyLong: Float)` tuple.

**`WoodQuality` enum**: Cases `exceptional`, `excellent`, `veryGood`, `good`, `average`, `belowAverage`, `poor`. `evaluate(specificModulus:radiationRatio:)` static factory.

**`goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:)` free function**: Gore Equation 4.5-7. Parameters in mm; returns Float in mm.

### Python (`material_properties.py`)

**`MaterialDimensions @dataclass`**: Stores in mm/g (`length_mm`, `width_mm`, `thickness_mm`, `mass_g`). Provides SI conversion properties (`length_m`, `width_m`, `thickness_m`, `mass_kg`) and convenience `length`/`width`/`thickness`/`mass` aliases pointing to SI values.

**`PlateProperties` class**: Uses `@property` decorators for all derived values (`youngs_modulus_long`, `speed_of_sound`, etc.) — equivalent to Swift's computed vars.

**`BraceProperties` class**: Same pattern — `@property` decorators throughout.

**`TonewoodReference` class**: Uses class-attribute dicts with named keys; no static tuple constants.

**`WoodQuality(Enum)`**: Same cases. `evaluate(specific_modulus, radiation_ratio)` classmethod.

**Module-level factory functions** (Python-only):

| Function | Notes |
|---|---|
| `calculate_brace_properties(dimensions, fundamental_freq_long)` | Constructs `BraceProperties`; no direct Swift counterpart (Swift initialises struct directly) |
| `calculate_plate_properties(dimensions, fundamental_freq_long, fundamental_freq_cross)` | Constructs `PlateProperties` |
| `calculate_gore_target_thickness(body_length_mm, body_width_mm, vibrational_stiffness)` | Mirrors Swift `goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:)` |
| `_euler_bernoulli_e(freq, length, thickness, density_factor)` | Private helper |

**Python-only alias**: `PlateDimensions = MaterialDimensions` (backward compat).

**Divergences**:

1. `MaterialDimensions` stores mm/g in Python vs SI in Swift. All downstream formulas must apply SI conversions in Python; Swift uses values directly.
2. `TonewoodReference` uses class attribute dicts in Python vs static tuple constants in Swift.
3. Python adds `calculate_brace_properties()`, `calculate_plate_properties()`, `PlateDimensions` alias.

**Verdict**: Full algorithmic parity. Significant structural difference in `MaterialDimensions` storage units (mm/g vs SI). `PlateProperties`/`BraceProperties` use `@property` in Python — equivalent to Swift computed vars, not a divergence. Python adds module-level factory functions.

---

## §20 — TapDisplaySettings

### Swift (`TapDisplaySettings.swift`)

`TapDisplaySettings` is an `enum` (no cases — used purely as a namespace). All members are `static` computed vars backed by `UserDefaults`.

Key static vars: `peakThreshold: Float`, `tapDetectionThreshold: Float`, `hysteresisMargin: Float`, `annotationVisibilityMode: AnnotationVisibilityMode`, `showUnknownModes: Bool`, `minFrequency: Float`, `maxFrequency: Float`, `minMagnitude: Float`, `maxMagnitude: Float`, `numberOfTaps: Int`, `tapDetectionEnabled: Bool`.

Static methods: `resetToDefaults()`, `validateFrequencyRange(minFreq:maxFreq:)`, `validateMagnitudeRange(minDB:maxDB:)`.

XCTest isolation: some properties check `ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"]` and return defaults rather than reading `UserDefaults`.

### Python (`tap_display_settings.py`)

`TapDisplaySettings` is a regular class that is never instantiated. All members are `@classmethod` delegating to `AppSettings` (which wraps QSettings).

`tap_detection_threshold()` classmethod converts QSettings 0-100 scale to dBFS: `return float(_app_settings().tap_threshold()) - 100.0`. In Swift the value is stored as dBFS directly.

**Divergences**:

1. Python `tap_detection_threshold` converts 0-100 → dBFS at read time; Swift stores dBFS directly.
2. Python has no `resetToDefaults()`, `validateFrequencyRange()`, or `validateMagnitudeRange()` methods.
3. Python has no XCTest isolation pattern (irrelevant — tests use pytest).
4. Python delegates to `AppSettings`/QSettings; Swift accesses `UserDefaults` directly.

**Verdict**: Interface parity for read operations. Python missing `resetToDefaults` and range-validation helpers. Scale conversion difference on `tap_detection_threshold`.

---

## §21 — SpectrumSnapshot

### Swift (`SpectrumSnapshot.swift`)

`SpectrumSnapshot` is a `struct` conforming to `Codable`.

Fields: `frequencies: [Float]`, `magnitudes: [Float]`, `minFrequency: Float`, `maxFrequency: Float`, `minMagnitude: Float`, `maxMagnitude: Float`.

Custom `Codable`: frequencies and magnitudes are serialised as Base64-encoded little-endian `float32` binary blobs in keys `frequenciesData` and `magnitudesData`. Decoding handles both the binary format and a legacy plain-array format.

### Python (`spectrum_snapshot.py`)

`SpectrumSnapshot` is a `@dataclass`.

Core fields: `frequencies`, `magnitudes`, `min_freq`, `max_freq`, `min_db`, `max_db`.

`to_dict()` encodes `frequencies`/`magnitudes` as Base64 binary (matching Swift format exactly). `from_dict()` handles both binary and legacy plain-array formats (matching Swift).

Python `SpectrumSnapshot` carries ~18 additional optional fields not present in Swift: `is_logarithmic`, `show_unknown_modes`, `guitar_type`, `measurement_type`, `max_peaks`, `plate_length`, `plate_width`, `plate_thickness`, `plate_mass`, `guitar_body_length`, `guitar_body_width`, `plate_stiffness_preset`, `custom_plate_stiffness`, `measure_flc`, `brace_length`, `brace_width`, `brace_thickness`, `brace_mass`. In Swift these values live on `TapToneMeasurement`; Python merges them into the snapshot for self-contained serialisation.

**Divergences**:

1. Python `SpectrumSnapshot` carries ~18 additional analysis-context fields not present in Swift. All are optional (`| None`).
2. Extra fields do not affect the core spectrum encoding and are ignored by Swift decoders.

**Verdict**: Core serialisation format is cross-platform compatible (same Base64 binary encoding for `frequenciesData`/`magnitudesData`). Python snapshot is a superset of Swift snapshot.

---

## §22 — MaterialTapPhase

### Swift (`MaterialTapPhase.swift`)

`MaterialTapPhase` is an `enum` with `String` raw values. All raw values are human-readable strings: `"Not Started"`, `"Capturing Longitudinal"`, `"Waiting for Cross-grain Tap"`, `"Capturing Cross-grain"`, `"Waiting for FLC Tap"`, `"Capturing FLC"`, `"Complete"`.

Properties: `instruction: String`, `shortStatus: String`, `isPlate: Bool`, `isBrace: Bool`, `isComplete: Bool`.

Note: `PlateCapture.State` is a separate inner enum in another file with 5 cases.

### Python (`material_tap_phase.py`)

`MaterialTapPhase(Enum)` with 7 matching cases. Raw values are the same human-readable strings as Swift — all 7 match exactly.

Properties: `instruction`, `short_status`.

**Divergences**:

1. Python does not implement `is_plate`, `is_brace`, `is_complete` convenience properties (present in Swift).

**Verdict**: Algorithmic parity. Raw values match exactly — no cross-platform serialisation risk. Python missing three convenience Bool properties.

---

## §23 — AnalysisDisplayMode

### Swift (`TapToneAnalyzer.swift` — defined at top of file)

```swift
enum AnalysisDisplayMode {
    case live
    case frozen
    case comparison
}
```

No raw values. Equatable by default (synthesised).

### Python (`analysis_display_mode.py`)

```python
class AnalysisDisplayMode(Enum):
    LIVE = auto()       # → 1
    FROZEN = auto()     # → 2
    COMPARISON = auto() # → 3
```

Uses `auto()` (integer values). Defined in its own file to avoid circular imports.

**Divergences**:

1. Python uses `auto()` integer values; Swift has no raw values. Integer-based comparison in Python; identity comparison in Swift.
2. Python defined in its own file; Swift defined at top of `TapToneAnalyzer.swift`.
3. No cross-platform serialisation risk because `AnalysisDisplayMode` is not persisted to disk.

**Verdict**: Functional parity. Organisation difference only; no serialisation risk.

---

## §24 — AnnotationVisibilityMode

### Swift (`AnnotationVisibilityMode.swift`)

`AnnotationVisibilityMode` enum with `String` raw values: `"all"`, `"selected"`, `"none"`.

`icon` computed var returns SF Symbols names: `"tag"`, `"tag.slash"` / `"bubble.left"`, etc.

### Python (`annotation_visibility_mode.py`)

`AnnotationVisibilityMode(str, Enum)` with same raw values: `'all'`, `'selected'`, `'none'`.

Inherits from both `str` and `Enum` to allow direct string comparison (`mode == 'all'`).

`icon_name` property returns qtawesome (fa5) icon names instead of SF Symbols.

`from_string(s)` classmethod — maps raw string to enum; no Swift equivalent (Swift uses `AnnotationVisibilityMode(rawValue:)`).

**Divergences**:

1. Python inherits `(str, Enum)` for string comparison compatibility; Swift is a plain `String`-raw-value enum.
2. `icon_name` uses fa5 icons (Python) vs SF Symbols (Swift) — platform-specific, expected divergence.
3. Python adds `from_string()` classmethod.

**Verdict**: Functional parity. Icon names are platform-specific (expected). `from_string` is a minor Python convenience.

---

## §25 — UserAssignedMode

### Swift (`UserAssignedMode.swift`)

`UserAssignedMode` is an `enum` with associated values:

```swift
enum UserAssignedMode {
    case auto                      // no user override
    case assigned(label: String)   // user-entered string
}
```

Static properties: `guitarTapModes: [UserAssignedMode]`, `additionalModes: [UserAssignedMode]`, `allSuggestions: [UserAssignedMode]`, `longestPredefinedLabel: String`.

Equatable, Hashable (synthesised for associated-value enum).

Serialisation: Custom `Codable` — encodes as `{"type": "auto"}` or `{"type": "assigned", "label": "..."}`.

### Python (`user_assigned_mode.py`)

Python enums cannot have associated values. `UserAssignedMode` is implemented as a regular class with factory class methods.

```python
class UserAssignedMode:
    @classmethod
    def auto(cls) -> "UserAssignedMode": ...
    @classmethod
    def assigned(cls, label: str) -> "UserAssignedMode": ...
```

Implements `__eq__`, `__hash__`, `__repr__` explicitly.

Static methods: `guitar_tap_modes()`, `additional_modes()`, `all_suggestions()`, `longest_predefined_label()`.

`to_dict()` / `from_dict()` for serialisation.

**Divergences**:

1. Python implements as a class (not enum) due to Python's lack of enums with associated values. Behaviour is equivalent.
2. `to_dict()`/`from_dict()` vs Swift `Codable` — compatible JSON format (same keys: `"type"`, `"label"`).
3. `__eq__` and `__hash__` are manually implemented in Python; synthesised by Swift.

**Verdict**: Behavioural parity. Implementation pattern differs due to language constraint (no associated-value enums in Python). JSON format compatible.

---

## §26 — PlateStiffnessPreset

### Swift (`PlateStiffnessPreset.swift`)

`PlateStiffnessPreset` is an `enum` with `String` raw values matching display strings:

```swift
case steelStringTop  = "Steel String Top"
case steelStringBack = "Steel String Back"
case classicalTop    = "Classical Top"
case classicalBack   = "Classical Back"
case custom          = "Custom"
```

`value: Float` computed var returns `f_vs` for the preset.
`shortName: String` computed var returns compact picker label.

### Python (`plate_stiffness_preset.py`)

`PlateStiffnessPreset(Enum)` with same cases and same raw values (display strings).

**Key Python issue**: Python's `Enum` uses `.value` to access the raw value. `PlateStiffnessPreset.STEEL_STRING_TOP.value` would normally return the string `"Steel String Top"`. But the class defines a `value` **property** that returns the float `f_vs`. This overrides `Enum.value` — the raw string is inaccessible via `.value` on an instance.

Lookup via `PlateStiffnessPreset("Steel String Top")` still works (Python searches by raw value in `__new__`).

`short_name` property — equivalent to Swift `shortName`.

**Divergences**:

1. Python `value` property returns `float` (overriding Enum's raw-value access). Swift `value` computed var returns `Float` without collision.
2. Raw string values are identical, so `PlateStiffnessPreset(rawValue:)` (Swift) and `PlateStiffnessPreset(string)` (Python) both work.

**Active display bug**: `tap_tone_analysis_view.py` line 2653 contains:
```python
f"f_vs = {int(_fvs)} ({_preset.value})"
```
where `_fvs` is already the stiffness float. The intent is to produce a label like `"f_vs = 75 (Steel String Top)"`, using the preset's display name in parentheses. However, because `.value` returns the stiffness float (e.g. `75.0`) rather than the raw display string (`"Steel String Top"`), the label currently reads `"f_vs = 75 (75.0)"` — the float is duplicated and the display name is lost.

**Fix**: Rename `@property value` to `@property stiffness` in `plate_stiffness_preset.py`. This restores standard `Enum.value` semantics (returning the raw string `"Steel String Top"` etc.) and:
- Fixes the display bug at line 2653 automatically (`.value` now returns the string as intended).
- Requires updating `tap_display_settings.py:240` and `tap_analysis_results_view.py:437` from `.value` to `.stiffness` (they want the float).
- Leaves `tap_tone_analysis_view.py:2653` unchanged — the standard `.value` string is exactly what is needed there.

**Verdict**: Real bug — active display regression at `tap_tone_analysis_view.py:2653`. Naming collision causes stiffness float to appear where the preset display name is expected.

---

## §27 — MicrophoneCalibration

### Swift (`MicrophoneCalibration.swift`)

**`CalibrationPoint` struct**: `frequency: Float`, `offsetDB: Float`.

**`MicrophoneCalibration` struct**: `Codable`, `Equatable`. Fields: `deviceUID: String`, `deviceName: String`, `points: [CalibrationPoint]`, `name: String?`.
Methods: `offsetDB(for:)` (linear interpolation), `toFrequencyBins(frequencies:)` (maps calibration to FFT bins).

**`CalibrationFileParser` struct**: `ParseError` inner enum. `parse(url:)` throws; returns `MicrophoneCalibration`.

**`CalibrationStorage`**: `class`. `loadCalibration(for: AVAudioDevice) -> MicrophoneCalibration?` — queries UserDefaults by `device.uid`. `saveCalibration(_:for: AVAudioDevice)` — keys by UID. `deleteCalibration(for: AVAudioDevice)`. `allCalibrations() -> [MicrophoneCalibration]`.

### Python (`microphone_calibration.py`)

**`MicrophoneCalibration @dataclass`**: fields: `device_fingerprint: str`, `device_name: str`, `points: list`, `name: str | None`. Methods: `offset_db(frequency)`, `to_frequency_bins(frequencies)`.

**`CalibrationFileParser` class** (not struct): raises `ValueError` / `ParseError` instead of Swift `throw`.

**`CalibrationStorage` class**: uses QSettings. Keys by `device.fingerprint` (synthesised `name:sample_rate` string) vs Swift keys by `device.uid` (platform-assigned CoreAudio UID).

**Python-only additions**:

| Addition | Notes |
|---|---|
| `delete_all()` | Clears all stored calibrations; no Swift counterpart |
| `parse_cal_metadata(path)` | Module-level function extracting metadata from file |
| `parse_cal_file(path)` | Module-level function returning `MicrophoneCalibration` |
| `interpolate_to_bins(points, frequencies)` | Module-level interpolation helper |

**Divergences**:

1. `CalibrationStorage` keys by device fingerprint (Python) vs CoreAudio UID (Swift). Calibrations are not cross-platform portable in storage.
2. `deviceUID` field is named `device_fingerprint` in Python (conceptually different: synthesised vs platform-assigned).
3. Python adds `delete_all()` and three module-level helper functions.

**Verdict**: Functional parity for calibration load/save/apply. Storage key mismatch means calibration files exported from one platform cannot be directly imported by the other without remapping device identifiers.

---

## §28 — Pitch

### Swift (`Pitch.swift`)

`Pitch` class. `a4: Float` property. Key methods: `pitch(frequency:) -> (note: Int, octave: Int)`, `pitchRange(frequency:) -> (upper: Float, lower: Float)`, `note(frequency:) -> String`, `freq0(frequency:) -> Float`, `freq(note:octave:) -> Float`, `cents(frequency:) -> Float`, `formattedNote(frequency:) -> String`, `isInTune(frequency:threshold:) -> Bool`.

`c0` derived property: `a4 × 2^(−4.75)`.

Debug helper: `static func runExample()` behind `#if DEBUG`.

### Python (`pitch.py`)

`Pitch` class with `a4: float`. Identical algorithm for all methods. `c0` as `@property`.

`run_example()` is a **module-level function** (not a static method inside the class, not gated by `#if DEBUG`).

`if __name__ == "__main__": run_example()` guard at module level.

**Divergences**:

1. `run_example` is module-level in Python; `runExample` is a static method on the class in Swift (behind `#if DEBUG`).

**Verdict**: Full algorithmic parity. Trivial organisational difference on `run_example`.

---

## §29 — AVAudioDevice / AudioDevice

### Swift (`AVAudioDevice.swift`)

`AVAudioDevice` struct conforming to `Identifiable`, `Equatable`, `Hashable`.

Fields: `uid: String` (platform-assigned CoreAudio UID — stable across sessions), `name: String`, `id: UUID` (transient SwiftUI identity), `sampleRate: Double`.

On macOS: `deviceID: AudioDeviceID` (CoreAudio integer ID). On iOS: `port: AVAudioSessionPortDescription?`.

### Python (`audio_device.py`)

`AudioDevice` `@dataclass` (no "AV" prefix).

Fields: `name: str`, `sample_rate: int`, `index: int` (PortAudio session-scoped index — not stable across sessions), `fingerprint: str` (property, synthesised as `f"{name}:{sample_rate}"`).

No `uid` — PortAudio provides no stable device identifier. `fingerprint` is a best-effort substitute.
No `id: UUID` — Python uses `name:sample_rate` for identity; no SwiftUI `Identifiable` requirement.
No `deviceID` (CoreAudio) or `port` (AVAudioSession) — platform-specific Swift properties.

**Python-only factory/helper methods**:

| Method | Notes |
|---|---|
| `from_sounddevice_dict(info)` | Constructs from PortAudio `sounddevice` device-info dict |
| `from_fingerprint(fp)` | Parses `"name:sample_rate"` fingerprint string |
| `resolve(devices)` | Finds matching device from list by fingerprint |

**Divergences**:

1. `uid` (stable, platform-assigned) vs `fingerprint` (synthesised, best-effort). Fingerprint can collide if two devices share name and sample rate.
2. `index: int` (PortAudio session-scoped) vs `deviceID: AudioDeviceID` (stable CoreAudio integer).
3. No `id: UUID` (transient Identifiable) in Python.
4. Class name: `AudioDevice` (Python) vs `AVAudioDevice` (Swift).

**Verdict**: Equivalent purpose, significant structural difference in device identification due to platform constraints. Fingerprint-based matching is best-effort; CoreAudio UID is deterministic.

---

## §30 — RealtimeFFTAnalyzer

### Swift (`RealtimeFFTAnalyzer.swift` + extensions)

`RealtimeFFTAnalyzer: ObservableObject`. Key `@Published` properties:

`magnitudes: [Float]`, `frequencies: [Float]`, `peakFrequency: Float`, `peakMagnitude: Float`, `inputLevelDB: Float`, `isRunning: Bool`, `selectedDevice: AVAudioDevice?`, `availableInputDevices: [AVAudioDevice]`, `routeChangeRestartCount: Int`.

Configuration: `fftSize: Int`, `targetSampleRate: Double`, `window: [Float]`.

Audio pipeline: `AVAudioEngine` + `AVAudioInputNode.installTap`. Tap fires at ~1024-sample callback; processed on the audio engine's queue.

### Python (`realtime_fft_analyzer.py`)

`RealtimeFFTAnalyzer(RealtimeFFTAnalyzerDeviceManagementMixin)`.

**Python-only `_FftProcessingThread(QtCore.QThread)`**: Off-main-thread DSP worker. No Swift counterpart — Swift processes on the AVAudioEngine audio queue.

**Structural pipeline difference**:
- Swift: `AVAudioInputNode.installTap` → callback → `processAudioBuffer` on audio queue → update `@Published` vars → Combine pipeline → `TapToneAnalyzer`.
- Python: `sounddevice.InputStream` → `queue.Queue` → `_FftProcessingThread` pulls from queue → computes FFT → emits Qt signals → `TapToneAnalyzer.on_fft_frame`.

**Properties present in Python but absent from Swift's `@Published` set**:
`queue`, `chunksize`, `stream`, `is_stopped`, `proc_thread`, `raw_sample_handler`.

**`@Published` properties from Swift absent in Python** (not needed — Python uses signals):
`magnitudes`, `frequencies`, `peakFrequency`, `peakMagnitude`, `inputLevelDB`, `routeChangeRestartCount`.

**Backward compat alias**: `Microphone = RealtimeFFTAnalyzer` (Python-only).

**`realtime_fft_analyzer_engine_control.py`**: Documentation-only file (no executable code). Contains a detailed structural comparison table of Swift `start()`/`stop()` vs Python equivalents.

**Verdict**: Same purpose, fundamentally different audio pipeline architecture (AVAudioEngine + Combine vs PortAudio/sounddevice + QThread + Qt signals). All observable results (FFT frames, peak detection, device management) are functionally equivalent.

---

## §31 — RealtimeFFTAnalyzer+FFTProcessing

### Swift (`RealtimeFFTAnalyzer+FFTProcessing.swift`)

Key methods:

| Method | Notes |
|---|---|
| `processAudioBuffer(_:)` | Accumulates samples into `inputBuffer`; triggers FFT at every `fftSize` samples |
| `performFFT()` | Uses `vDSP_DFT_zrop`; applies rectangular window; stores in `magnitudes`/`frequencies` |
| `computeGatedFFT(buffer:sampleRate:)` | Gated MPM capture; includes HPS post-processing |
| `updateFrequencyBins()` | Recomputes `frequencies` array from current `fftSize` + sample rate |
| `updateCalibrationCorrections()` | Applies mic calibration offsets to FFT bins |
| `updateMetrics()` | Updates `peakFrequency`/`peakMagnitude`/`inputLevelDB` from new magnitudes |
| `resample(_:from:to:)` | Linear resampling for gated capture |

### Python (`realtime_fft_analyzer_fft_processing.py`)

Module-level functions (not methods on a class):

| Function | Notes |
|---|---|
| `dft_anal(x, window_fcn, n_fft)` | scipy.fft + zero-phase rotation (ifftshift trick); functionally equivalent to `performFFT` |
| `peak_detection(mX, t)` | Returns indices of peaks above threshold |
| `peak_interp(mX, ploc)` | Parabolic interpolation — same algorithm as `parabolicInterpolate` in `TapToneAnalyzer+PeakAnalysis.swift` |
| `peak_q_factor(mX, freqs, ploc)` | −3 dB Q factor — same algorithm as `calculateQFactor` |
| `hps_peak_freq(mX, freqs, n_harmonics)` | Harmonic Product Spectrum; called module-level, not inside class |
| `is_power2(n)` | Utility |

**Swift-only methods (no Python equivalents in this file)**:

`updateFrequencyBins()`, `updateCalibrationCorrections()`, `updateMetrics()`, `processAudioBuffer(_:)`, `resample(_:from:to:)` — these are handled by the `_FftProcessingThread` pipeline in Python, not as methods on the analyzer class.

**FFT library difference**:

Swift uses `vDSP_DFT_zrop` (Accelerate framework, SIMD-optimised). Python uses `scipy.fft.fft` with an `ifftshift` zero-phase rotation trick.

**Verdict**: Algorithmic parity for FFT computation, peak detection, interpolation, Q-factor, and HPS. Implementation pattern differs (module-level functions vs class methods) and DSP library differs (scipy vs vDSP).

---

## §32 — RealtimeFFTAnalyzer+DeviceManagement

### Swift (`RealtimeFFTAnalyzer+DeviceManagement.swift`)

Key methods:

| Method | Notes |
|---|---|
| `loadAvailableInputDevices()` | Enumerates `AVAudioEngine` input devices; updates `availableInputDevices` |
| `setInputDevice(_:)` | macOS: stops engine, assigns device, restarts. iOS: `session.setPreferredInput` |
| `registerSampleRateListener(for:)` | Registers CoreAudio property listener for sample-rate changes (macOS) |
| `handleRouteChange(notification:)` | iOS route-change handler |
| `restartEngineAfterRouteChange()` | Restarts engine after route change with settle delay |

### Python (`realtime_fft_analyzer_device_management.py`)

`RealtimeFFTAnalyzerDeviceManagementMixin`.

| Method | Notes |
|---|---|
| `load_available_input_devices()` | Enumerates via `sounddevice`; applies 4-priority auto-selection |
| `set_device(device)` | Stops stream, sets device index, restarts |
| `reinitialize_portaudio()` | Python-only — reinitialises PortAudio subsystem; no Swift equivalent |

**Platform-specific monitors**:

| Monitor | Platform | Notes |
|---|---|---|
| `_start_coreaudio_monitor()` | macOS | Uses ctypes to call CoreAudio property listeners (not AVFoundation) |
| `_start_windows_monitor()` | Windows | Uses `cfgmgr32` CM_Register_Notification — **Python-only** |
| `_start_linux_monitor()` | Linux | Uses pyudev — **Python-only** |

**Swift-only methods (no Python equivalents)**:

`registerSampleRateListener(for:)` — PortAudio does not surface per-device sample-rate change notifications through its public API. However, OS-level APIs exist on all platforms: macOS (CoreAudio `kAudioDevicePropertyNominalSampleRate`), Windows (WASAPI `IMMNotificationClient::OnPropertyValueChanged` / `IAudioSessionEvents::OnSessionDisconnected` with `DisconnectReasonFormatChanged`), and Linux (PulseAudio `pa_context_subscribe(PA_SUBSCRIPTION_MASK_SOURCE)` via `pulsectl`, or PipeWire `pw_stream_events.param_changed`; bare ALSA has no notification mechanism). The fix in Python is to extend the existing platform-native monitors to also watch for sample rate changes. D26 is fixable in code on macOS, Windows, and PulseAudio/PipeWire Linux; bare ALSA Linux has no fix.
`handleRouteChange(notification:)`, `restartEngineAfterRouteChange()` — iOS-specific; no Python equivalent.

**Divergences**:

1. Python adds Windows and Linux hot-plug monitors; Swift is macOS/iOS only.
2. Python `reinitialize_portaudio()` has no Swift counterpart.
3. Swift `registerSampleRateListener` has no Python counterpart.
4. Swift iOS route-change handling has no Python counterpart.
5. **Auto-device-switch on plug-in**: Swift `loadAvailableInputDevicesMacOS()` compares the new device list against the previous list and automatically calls `setInputDevice(_:)` for the first newly-connected real device (filtered for transient `CADefaultDeviceAggregate` artifacts), stopping and restarting the engine immediately. Python's `_notify_devices_changed()` only calls `self._on_devices_changed()`, which emits `devicesChanged` and rebuilds the UI combo box — the user must manually select the new device. This is a behavioural divergence, not a PortAudio limitation: the auto-selection logic can be added to Python's `_notify_devices_changed()` path.
6. **Stale `_gated_sample_rate` after device switch**: In `TapToneAnalyzer.set_device()`, `fft_data.sample_freq` is synced to `mic.rate` after the device switch, but `_gated_sample_rate` (used to compute the gated MPM capture window size) is not updated. It is set only once in `start()`. If the new device has a different sample rate, the gated capture window is sized incorrectly. Fix: add `self._gated_sample_rate = float(self.mic.rate)` and `self._pre_roll_samples = int(self.mic.rate * self._pre_roll_seconds)` to `set_device()` after `self.mic.set_device(device)`.

**Verdict**: Hot-plug detection is functionally present on all platforms. Two additional gaps identified: auto-device-switch (fixable in Python) and stale `_gated_sample_rate` (one-liner fix in `set_device()`). `registerSampleRateListener` (mid-session sample rate change on active device) is fixable in code by extending the existing platform-native monitors: macOS via CoreAudio `kAudioDevicePropertyNominalSampleRate`, Windows via WASAPI `IMMNotificationClient`/`IAudioSessionEvents`. Linux mechanism is under investigation. D26 is no longer considered a PortAudio limitation.

---

## §33 — FftParameters (Python-only)

### Swift

No equivalent. In Swift, FFT configuration values (`fftSize`, `targetSampleRate`, `window`) are owned by `RealtimeFFTAnalyzer` from construction time.

### Python (`fft_parameters.py`)

`FftParameters` class with fields: `sample_freq: int`, `n_f: int` (FFT size), `m_t: int` (= `n_f`, ring-buffer length), `window_fcn` (boxcar window array), `h_n_f: int` (= `n_f // 2`).

**Why it exists**: `FftCanvas` (view) constructs `RealtimeFFTAnalyzer` and must pass FFT configuration to the analyzer before the mic object exists. `FftParameters` bridges this construction-order dependency.

`RealtimeFFTAnalyzer` already owns the same fields at runtime (`fft_size`, `m_t`, `h_fft_size`, `window_fcn`). The divergence is the extra file and the view-layer construction dependency — both of which should be eliminated so that `TapToneAnalyzer` owns `RealtimeFFTAnalyzer` from construction time, exactly as in Swift.

**Verdict**: Python-only. Exists due to a view-layer construction-order dependency. The fields belong on `RealtimeFFTAnalyzer`; this class and its file should be removed once that dependency is resolved.

---

## §34 — SpectrumCapture (Swift-only section)

### Swift (`TapToneAnalyzer+SpectrumCapture.swift`)

`startGatedCapture(phase:completion:)` — starts MPM gated accumulation. `averageSpectra(from:)` — averages multiple `SpectrumSnapshot` instances. `resolvedPlatePeaks` computed var.

### Python

`start_gated_capture`, `average_spectra` present in `tap_tone_analyzer_peak_analysis.py` (see §2). `resolved_plate_peaks` property present in main `tap_tone_analyzer.py`.

No structural divergence beyond file organisation (already noted in §2).

---

## Summary of Confirmed Divergences

### TapToneAnalyzer Cluster (§1–§13)

| # | Location | Swift behaviour | Python behaviour | Severity |
|---|---|---|---|---|
| D1 | `effectiveXxxPeakID` | 3-layer: user → selected → auto | 2-layer: user → auto (middle layer missing) | Medium |
| D2 | `cycleAnnotationVisibility` | Persists to `TapDisplaySettings` | Does not persist | High |
| D3 | `tapDetectionThreshold` write | `didSet` persists to `TapDisplaySettings` | Setter does not persist | High |
| D4 | `hysteresisMargin` write | `didSet` persists to `TapDisplaySettings` | Setter does not persist | High |
| D5 | `peakThreshold` write | `didSet` persists + calls recalculate | `set_threshold()` calls recalculate but does not persist | Medium |
| D6 | `setFrozenSpectrum` atomicity | `objectWillChange.send()` + atomic assign | Separate assignments; direct property reads in view could observe half-updated state | Medium |
| D7 | PDF export | Full `PDFReportData` + `PDFReportGenerator` pipeline | Stub file only; not implemented | High |
| D8 | `handleRouteChangeRestart` | 2 s settle + re-anchor `isAboveThreshold` | Not replicated; only reinitialises PortAudio | Medium |
| D9 | `save_measurement` signature | 14 named params; model is the factory | View layer assembles object, passes pre-built to model | Medium — model-layer logic scattered into view |
| D10 | `load_measurement` location | `loadMeasurement(_:)` in `+MeasurementManagement.swift` (model) | `_restore_measurement()` in `tap_tone_analysis_view.py` (view layer) — no model equivalent exists | High — ~350 lines of model-layer state restoration living in the view |
| D11 | `identified_modes` type | `[(peak: ResonantPeak, mode: GuitarMode)]` named tuples | `[{"peak": ..., "mode": ...}]` dicts | Low |
| D12 | `average_spectra` location | In `+SpectrumCapture.swift`; called by all gated-capture handlers | In `tap_tone_analyzer_peak_analysis.py`; **zero callers — dead code** | High — multi-tap averaging is not wired up in Python |
| D13 | Timer threading | `DispatchQueue.main.asyncAfter` | `threading.Timer` + `QMetaObject.invokeMethod(QueuedConnection)` | Medium — fires on background thread; `QTimer.singleShot` would run on main thread directly |

### Remaining Model Files (§14–§29)

| # | Location | Swift behaviour | Python behaviour | Severity |
|---|---|---|---|---|
| D14 | `ResonantPeak.id` | `UUID` | `str` (UUID string) | Low (boundary conversion needed) |
| D15 | `ResonantPeak.timestamp` | `Date` | `str` (ISO-8601) | Low |
| D16 | `ResonantPeak.mode_label` | Not present | `str = ""` Python-only field | Low |
| D17 | `MaterialDimensions` storage | SI units (m, kg) | mm and g; conversion properties provided | Medium |
| D18 | `TapDisplaySettings.tap_detection_threshold` | Stored as dBFS | QSettings stores 0-100; converted at read | Medium (value-range difference) |
| D19 | `TapDisplaySettings.resetToDefaults` | Present | Not present | Low |
| D20 | `MaterialTapPhase` convenience props | `isPlate`, `isBrace`, `isComplete` | Not present | Low |
| D21 | `SpectrumSnapshot` extra fields | Core 6 fields only | ~18 additional analysis-context fields | Low (superset; extra fields ignored by Swift) |
| D22 | `UserAssignedMode` implementation | `enum` with associated values | Regular class with factory methods | Low (equivalent behaviour) |
| D23 | `PlateStiffnessPreset.value` | Computed var (Float) — no name collision | `value` property overrides `Enum.value`; display bug at `tap_tone_analysis_view.py:2653` (float shown where string expected) | Medium — active display regression |
| D24 | `CalibrationStorage` device key | CoreAudio UID (stable) | Device name string (best-effort) | Medium (devices not cross-platform portable) |
| D25 | `AVAudioDevice` identifier | `uid: String` (platform-assigned) | `fingerprint: str` (synthesised, best-effort) | Medium |
| D26 | `registerSampleRateListener` | Present (macOS CoreAudio) — detects mid-session rate change on active device | Not present — PortAudio does not surface this but macOS (CoreAudio) and Windows (WASAPI) both have OS APIs for it; fixable by extending platform-native monitors. Linux under investigation. | Medium |
| D27 | `FftParameters` | Not present | Python-only; `FftCanvas` constructs before `RealtimeFFTAnalyzer` exists; fields belong on `RealtimeFFTAnalyzer` | Medium — construction-order dependency that should be eliminated |
| D28 | `TapToneMeasurement.annotation_offsets` | `[UUID: CGPoint]` | `{str: [float, float]}` | Low (boundary conversion needed) |
| D29 | `TapToneMeasurement.peak_mode_overrides` | `[UUID: UserAssignedMode]` | `{str: str}` | Low (boundary conversion needed) |
| D30 | Auto-device-switch on plug-in | `loadAvailableInputDevicesMacOS()` auto-selects and switches to first newly-connected real device | `_notify_devices_changed()` only rebuilds UI combo — user must select manually | Medium — UX divergence; fixable in Python |
| D31 | `_gated_sample_rate` after device switch | Sample rate always current (AVAudioEngine reads hardware format on `start()`) | `_gated_sample_rate` set once in `start()`; not updated in `set_device()` — stale after switching to device with different rate | Medium — gated capture window sized incorrectly after device switch |

### Cross-Platform JSON Serialisation Notes

No high-severity serialisation risks exist. All enum raw values that cross the platform boundary match between Swift and Python. The core `SpectrumSnapshot` binary encoding (Base64 little-endian float32) is fully compatible between platforms. Python's extra snapshot fields are ignored by Swift decoders.
