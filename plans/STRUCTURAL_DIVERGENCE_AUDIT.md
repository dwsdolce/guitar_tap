# Structural Divergence Audit: Swift ↔ Python TapToneAnalyzer

**Methodology**: Every section below is derived directly from reading all 10 Swift extension
files and all 10 Python mixin/class files side-by-side. No section was carried forward from a
prior version without re-reading the source.

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

- `average_spectra(from_taps)` — placed here rather than in the spectrum-capture mixin (file-organisation difference only; both are accessible on the shared `TapToneAnalyzer` object).
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

1. **`save_measurement` signature**: Python takes a pre-built object. Swift `saveMeasurement` takes 14 individual named parameters and builds the object internally.

2. **`load_measurement` location**: Swift `loadMeasurement(_:)` lives here. Python's equivalent is in `tap_tone_analyzer_control.py`, not in the MeasurementManagement mixin.

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

**`setFrozenSpectrum` / `setLoadedAxisRange` atomicity**: Not replicated. Frozen arrays are assigned as separate lines wherever needed. No `objectWillChange.send()` equivalent.

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

## Summary of Confirmed Divergences

| # | Location | Swift behaviour | Python behaviour | Severity |
|---|---|---|---|---|
| D1 | `effectiveXxxPeakID` | 3-layer: user → selected → auto | 2-layer: user → auto (middle layer missing) | Medium |
| D2 | `cycleAnnotationVisibility` | Persists to `TapDisplaySettings` | Does not persist | High |
| D3 | `tapDetectionThreshold` write | `didSet` persists to `TapDisplaySettings` | Setter does not persist | High |
| D4 | `hysteresisMargin` write | `didSet` persists to `TapDisplaySettings` | Setter does not persist | High |
| D5 | `peakThreshold` write | `didSet` persists + calls recalculate | `set_threshold()` calls recalculate but does not persist | Medium |
| D6 | `setFrozenSpectrum` atomicity | `objectWillChange.send()` + atomic assign | Separate assignments, no render atomicity | Low |
| D7 | PDF export | Full `PDFReportData` + `PDFReportGenerator` pipeline | Stub file only; not implemented | High |
| D8 | `handleRouteChangeRestart` | 2 s settle + re-anchor `isAboveThreshold` | Not replicated; only reinitialises PortAudio | Medium |
| D9 | `save_measurement` signature | 14 named params | Takes pre-built object | Low (different boundary) |
| D10 | `load_measurement` location | In `+MeasurementManagement.swift` | In `control.py` (not in mixin) | Low (organisation only) |
| D11 | `identified_modes` type | `[(peak: ResonantPeak, mode: GuitarMode)]` named tuples | `[{"peak": ..., "mode": ...}]` dicts | Low |
| D12 | `average_spectra` location | In `+SpectrumCapture.swift` | In `tap_tone_analyzer_peak_analysis.py` | Low (organisation only) |
| D13 | Timer threading | `DispatchQueue.main.asyncAfter` | `threading.Timer` + `QMetaObject.invokeMethod(QueuedConnection)` | Implementation difference only (correct) |
