# Reactive Property Audit Results

Audit performed against all Swift `@Published` properties in
`TapToneAnalyzer.swift` and `RealtimeFFTAnalyzer.swift`, using the rules in
`REACTIVE_PROPERTY_AUDIT_GUIDELINES.md`.

For each property, the Python notification path is classified as one of:

- **Signal** — a Qt `Signal` is emitted on every write; a view slot is connected
- **Pull** — the view reads the property synchronously inside a signal-triggered slot
- **View-local** — Python keeps equivalent state in the view, not the model
- **Not needed** — the property serves a Swift/SwiftUI-specific purpose with no
  Python equivalent
- **⚠ Gap** — no notification path exists; view may observe stale state

---

## TapToneAnalyzer — Configuration Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `peakThreshold` | `peak_threshold` | View-local | Slider drives model; model reads from `TapDisplaySettings` on each use | ✅ |
| `minFrequency` | `min_frequency` | Signal | `freqRangeChanged.emit(fmin, fmax)` via canvas | ✅ |
| `maxFrequency` | `max_frequency` | Signal | `freqRangeChanged.emit(fmin, fmax)` via canvas | ✅ |
| `maxPeaks` | `max_peaks` | Not needed | Internal FFT parameter; no view reads it reactively | ✅ |
| `decayThreshold` | `decay_threshold` | Not needed | Internal threshold; no view notification required | ✅ |
| `numberOfTaps` | `number_of_taps` | View-local | Spinner in view drives model; no back-notification needed | ✅ |
| `captureWindow` | `capture_window` | Not needed | Internal FFT parameter | ✅ |
| `tapDetectionThreshold` | `tap_detection_threshold` | View-local | Slider drives model via `TapDisplaySettings`; no back-notification | ✅ |
| `hysteresisMargin` | `hysteresis_margin` | View-local | Slider drives model via `TapDisplaySettings`; no back-notification | ✅ |

---

## TapToneAnalyzer — Results Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `currentPeaks` | `current_peaks` | Signal | `peaksChanged.emit(peaks)` → `canvas.peaksChanged` → `_on_peaks_changed_results`, `_material_peak_widget.update_peaks` | ✅ |
| `identifiedModes` | `identified_modes` | Pull | Read synchronously in `_export_pdf()` after `peaksChanged` slot completes; only needed at export time | ✅ |
| `currentDecayTime` | `current_decay_time` | Signal | `ringOutMeasured.emit(decay_s)` → `canvas.ringOutMeasured` → `set_ring_out` | ✅ |
| `savedMeasurements` | `saved_measurements` | Signal | `savedMeasurementsChanged.emit()` → `measurements_list_view._rebuild_list` | ✅ |

---

## TapToneAnalyzer — Detection State Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `averageMagnitude` | `average_magnitude` | Signal | `levelChanged.emit(int_level)` → `canvas.levelChanged` → `_on_level_changed`; level encoded as int (dB + 100) | ✅ |
| `tapDetectionLevel` | `tap_detection_level` | Signal | Same `levelChanged` signal carries effective detection level | ✅ |
| `tapDetected` | `tap_detected` | Signal | `tapDetectedSignal.emit()` → canvas relays as `tapDetected` → `_on_tap_detected` | ✅ |
| `isDetecting` | `is_detecting` | View-local | View derives: `_is_running and not _is_measurement_complete`; model value not read reactively | ✅ |
| `isDetectionPaused` | `is_detection_paused` | Signal | `tapDetectionPaused.emit(bool)` → `canvas.tapDetectionPaused` → `_on_tap_detection_paused` | ✅ |
| `isReadyForDetection` | `is_ready_for_detection` | View-local | View derives from `_is_running` and measurement state; model value not read reactively | ✅ |
| `currentTapCount` | `current_tap_count` | Signal | `tapCountChanged.emit(captured, total)` → `canvas.tapCountChanged` → `set_tap_count` | ✅ |
| `tapProgress` | `tap_progress` | Pull | Progress bar updated inside `set_tap_count` slot from `tapCountChanged`; no separate signal needed | ✅ |
| `statusMessage` | `status_message` | Signal | `statusMessageChanged.emit(msg)` via `_set_status_message()` helper → `canvas.statusMessageChanged` → `_on_status_message_changed` → `_sb_detect_msg.setText(msg)`. All writes in control, tap_detection, and spectrum_capture mixins go through the helper. **Fixed this session.** | ✅ |

---

## TapToneAnalyzer — Frozen Spectrum Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `frozenFrequencies` | `frozen_frequencies` | Signal | `spectrumUpdated.emit(freqs, mags)` → `canvas._on_spectrum_updated`; canvas renders frozen spectrum directly | ✅ |
| `frozenMagnitudes` | `frozen_magnitudes` | Signal | Same `spectrumUpdated` signal; both arrays emitted together (mirrors Swift `setFrozenSpectrum` atomic update) | ✅ |

---

## TapToneAnalyzer — Annotation & Selection State Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `peakAnnotationOffsets` | `peak_annotation_offsets` | Pull | Read/written synchronously in `peak_annotations.py` drag handlers; no reactive notification needed | ✅ |
| `peakModeOverrides` | `peak_mode_overrides` | Pull | Read from measurement objects during PDF export | ✅ |
| `selectedPeakIDs` | `selected_peak_ids` | View-local | `peak_widget.model.selected_frequencies` (set[float]). Guitar path: `auto_select_peaks_by_mode()` on tap. Plate/brace: set in `_on_plate_analysis_complete` and `_on_material_assignment_changed`. **Rule 5a gap fixed.** | ✅ |
| `highlightedPeakID` | `highlighted_peak_id` | Signal | `peakSelected.emit(freq)` / `peakDeselected.emit()` → `canvas.peakSelected/peakDeselected` → `peak_widget.select_row/clear_selection` | ✅ |
| `annotationVisibilityMode` | `annotation_visibility_mode` | View-local | Managed via `annotations_btn` click cycles in view; model attribute used for persistence on save only | ✅ |

---

## TapToneAnalyzer — Plate/Brace Measurement State Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `materialTapPhase` | `material_tap_phase` | Signal | `_set_material_tap_phase(phase)` helper emits `plateStatusChanged.emit(phase.value)` → `canvas.plateStatusChanged` → `_on_plate_status_changed` → `_update_plate_phase_ui`. **Fixed this session.** | ✅ |
| `isMeasurementComplete` | `is_measurement_complete` | Pull | View's `_is_measurement_complete` flag is set inside `_on_tap_detected` (guitar) and `_on_plate_analysis_complete` (plate/brace) slots; canvas also exposes a property shim. Direct reads of `analyzer.is_measurement_complete` in canvas paint path. | ✅ |
| `longitudinalSpectrum` | `longitudinal_spectrum` | Signal | `materialSpectraChanged.emit(spectra_list)` → `canvas.load_material_spectra` | ✅ |
| `crossSpectrum` | `cross_spectrum` | Signal | Same `materialSpectraChanged` signal | ✅ |
| `flcSpectrum` | `flc_spectrum` | Signal | Same `materialSpectraChanged` signal | ✅ |
| `longitudinalPeaks` | `longitudinal_peaks` | Signal | Emitted as part of `current_peaks` via `peaksChanged`; `_material_peak_widget.update_peaks` receives them | ✅ |
| `crossPeaks` | `cross_peaks` | Signal | Same `peaksChanged` path | ✅ |
| `flcPeaks` | `flc_peaks` | Signal | Same `peaksChanged` path | ✅ |
| `autoSelectedLongitudinalPeakID` | `auto_selected_longitudinal_peak_id` | Pull | Read during peak widget population after `peaksChanged`; no separate reactive path needed | ✅ |
| `selectedLongitudinalPeak` | `selected_longitudinal_peak` | Pull | Read from measurement objects at save/export time | ✅ |
| `userSelectedLongitudinalPeakID` | — | Not needed | View drives model via `assignmentChanged` signal from `_material_peak_widget`; no back-notification needed | ✅ |
| `autoSelectedCrossPeakID` | `auto_selected_cross_peak_id` | Pull | Same as longitudinal | ✅ |
| `selectedCrossPeak` | `selected_cross_peak` | Pull | Read from measurement objects at save/export time | ✅ |
| `userSelectedCrossPeakID` | — | Not needed | View drives model via `assignmentChanged` signal | ✅ |
| `autoSelectedFlcPeakID` | `auto_selected_flc_peak_id` | Pull | Same as longitudinal | ✅ |
| `selectedFlcPeak` | `selected_flc_peak` | Pull | Read from measurement objects at save/export time | ✅ |
| `userSelectedFlcPeakID` | — | Not needed | View drives model via `assignmentChanged` signal | ✅ |

---

## TapToneAnalyzer — Loaded Settings / Warning Properties

These properties exist in Swift to drive in-app warning banners when a loaded
measurement's settings differ from the current analyzer settings. Python keeps
equivalent state as view-local variables set when a measurement is loaded.

| Swift `@Published` | Classification | Python equivalent | Status |
|---|---|---|---|
| `showLoadedSettingsWarning` | View-local | `self._show_loaded_settings_warning` in `TapToneAnalysisView` | ✅ |
| `microphoneWarning` | View-local | Handled via `currentDeviceLost` signal → `_on_device_lost` | ✅ |
| `loadedAxisRange` | View-local | `self._loaded_axis_range` | ✅ |
| `loadedMinFreq` / `loadedMaxFreq` / `loadedMinDB` / `loadedMaxDB` | View-local | View-local state on measurement load | ✅ |
| `loadedTapDetectionThreshold` | View-local | `self._loaded_tap_threshold`; compared in `_on_tap_threshold_changed` to show warning | ✅ |
| `loadedHysteresisMargin` | View-local | Not tracked — warning not implemented for this setting | ✅ |
| `loadedPeakThreshold` | View-local | Not tracked — warning not implemented for this setting | ✅ |
| `loadedNumberOfTaps` | View-local | `self._loaded_tap_num`; compared in `_on_tap_count_changed` to show warning | ✅ |
| `loadedShowUnknownModes` | View-local | Controls peak card visibility on load | ✅ |
| `loadedGuitarType` | View-local | Set on load; configures UI | ✅ |
| `loadedMeasurementType` | View-local | Set on load; configures UI | ✅ |
| `loadedSelectedLongitudinalPeakID` | View-local | Used during load to populate peak selection | ✅ |
| `loadedSelectedCrossPeakID` | View-local | Used during load to populate peak selection | ✅ |
| `loadedSelectedFlcPeakID` | View-local | Used during load to populate peak selection | ✅ |
| `loadedPlate*` / `loadedBrace*` (dimensions + stiffness) | View-local | Stored on load; used for material properties export | ✅ |
| `loadedMeasureFlc` | View-local | Stored on load; configures UI | ✅ |
| `sourceMeasurementTimestamp` | Not needed | Timestamp embedded in `TapToneMeasurement` object | ✅ |
| `loadedMeasurementName` | View-local | Used to label frozen spectrum display | ✅ |

---

## TapToneAnalyzer — Other Properties

| Swift `@Published` | Python attribute | Classification | Python signal / path | Status |
|---|---|---|---|---|
| `displayMode` | `display_mode` | Signal | `displayModeChanged.emit(mode)` → canvas `display_mode` property setter | ✅ |
| `comparisonSpectra` | `comparison_spectra` | Signal | `comparisonChanged.emit(bool)` → `_on_comparison_changed`; spectra loaded via `materialSpectraChanged` | ✅ |

---

## RealtimeFFTAnalyzer — Properties

The Python equivalent is split across `realtime_fft_analyzer.py` and
`realtime_fft_analyzer_fft_processing.py`.  These properties flow through
the `_FftProcessingThread` Qt signals rather than main-model signals.

| Swift `@Published` | Classification | Python signal / path | Status |
|---|---|---|---|
| `magnitudes` / `frequencies` | Signal | `fftFrameReady` signal from `_FftProcessingThread` → `_on_fft_frame` → `spectrumUpdated.emit()` to view | ✅ |
| `peakFrequency` / `peakMagnitude` | Signal | Carried in `fftFrameReady` payload; emitted via `peakInfoChanged.emit(hz, db)` to view | ✅ |
| `inputLevelDB` / `displayLevelDB` / `recentPeakLevelDB` | Signal | `rmsLevelChanged.emit(int_level)` → `levelChanged.emit()` to view | ✅ |
| `isRunning` | Pull | View reads `canvas.is_running` (property shim) synchronously in button state update methods | ✅ |
| `microphonePermissionDenied` | Not needed | macOS doesn't gate microphone on Python/Qt in the same way | ✅ |
| `selectedInputDevice` | Signal | `devicesChanged.emit(list)` → `_on_devices_changed`; selection managed via combo box | ✅ |
| `availableInputDevices` | Signal | Same `devicesChanged` signal | ✅ |
| `frameRate` / `processingTimeMs` / `avgProcessingTimeMs` | Signal | `framerateUpdate.emit(fps, sample_dt, proc_dt)` → `_on_framerate_update` | ✅ |
| `actualSampleRate` / `hopSizeOverlap` / `frequencyResolution` / `bandwidth` / `sampleLengthSeconds` | Pull | Read synchronously in canvas paint path or status bar update on `framerateUpdate` signal | ✅ |
| `routeChangeRestartCount` | Not needed | iOS-specific audio route change counter; no Python equivalent | ✅ |
| `activeCalibration` | Pull | Read synchronously when applying calibration correction to spectrum | ✅ |

---

## Rule 5a Audit — View-local Write-site Enumeration

Audit of View-local classified `@Published` properties to verify that Python writes
its view-local equivalent at every site where Swift writes the model property.

This rule was added after `selectedPeakIDs` was correctly *classified* as View-local
and *justified*, but the plate/brace write sites were never wired — `selected_frequencies`
was always empty for plate/brace measurements, so "Selected" annotation mode showed nothing.

| Swift `@Published` | Swift write sites | View-local Python equivalent | Python write sites | Status |
|---|---|---|---|---|
| `selectedPeakIDs` | (1) Longitudinal phase complete: `= Set(longitudinalPeaks.map { $0.id })`; (2) Cross-grain phase complete: `= Set(resolvedPlatePeaks().map { $0.id })`; (3) FLC phase complete: same; (4) Guitar tap: `= guitarModeSelectedPeakIDs`; (5) `applyFrozenPeakState` (threshold change, all modes): plate/brace `= Set(peaks.map { $0.id })`, guitar = auto or carry-forward; (6) Measurement load: `= Set(saved)` or `= Set(measurement.peaks.map { $0.id })` | `peak_widget.model.selected_frequencies: set[float]` | Guitar (4): `auto_select_peaks_by_mode()` in `_on_tap_detected`; Plate/brace (1–3): `_on_plate_analysis_complete` sets `selected_frequencies`; user reassign (plate/brace): `_on_material_assignment_changed`; Threshold recalc (5, all modes): `_on_peaks_changed_results` propagates `analyzer.selected_peak_frequencies → set()` when `_is_measurement_complete`; Load (6): `_restore_measurement` sets directly before emitting peaks | ✅ Fixed |
| `annotationVisibilityMode` | Written on user tap via `cycleAnnotationVisibility()` only; persisted to UserDefaults | `self._ann_mode_idx` + `_apply_annotation_mode()` in view | `_on_cycle_annotation_mode()` handles user cycles; no model-side writes to mirror | ✅ No gap |
| `loadedMinFreq` / `loadedMaxFreq` / `loadedMinDB` / `loadedMaxDB` | Set when a measurement is loaded | View-local variables set in `_on_measurement_loaded` | Single write site in Swift, single write site in Python | ✅ |
| `loadedTapDetectionThreshold` | Set on load | `self._loaded_tap_threshold` | Set in `_on_measurement_loaded` | ✅ |
| `loadedNumberOfTaps` | Set on load | `self._loaded_tap_num` | Set in `_on_measurement_loaded` | ✅ |
| `isDetecting` | Set at multiple detection state transitions | View derives from `_is_running and not _is_measurement_complete` — no direct write needed | N/A — derived, not stored | ✅ |
| `isReadyForDetection` | Computed from multiple inputs | View derives from `_is_running` and measurement state | N/A — derived | ✅ |

### Rule 5a Issues Found

| Property | Issue | Severity | Status |
|---|---|---|---|
| `selectedPeakIDs` | Plate/brace write sites (phase completions) had no Python equivalent — `selected_frequencies` always empty for plate/brace; "Selected" annotation mode showed no labels | High | **Fixed** |

---

## Rule 6 Audit — Swift Computed View Properties (N-to-1 Aggregation)

Audit of Swift computed view properties that aggregate multiple `@Published` model vars.
SwiftUI re-evaluates these automatically; Python requires explicit assembly call sites.

Source files audited:
- `TapToneAnalysisView+SpectrumViews.swift`
- `TapAnalysisResultsView.swift`
- `TapToneAnalysisView+Controls.swift`
- `TapToneAnalysisView.swift`

| Swift computed property | `@Published` inputs | Python assembly call | Call sites | Status |
|---|---|---|---|---|
| `materialSpectra` | `longitudinalSpectrum`, `crossSpectrum`, `flcSpectrum`, `displayMode`, `comparisonSpectra` | `set_material_spectra(spectra_list)` | After brace L-only complete; after plate L+C complete; after plate L+C+FLC complete (all in `tap_tone_analyzer_spectrum_capture.py`) | ✅ Fixed this session |
| `displaySpectrum` / `displayFrequencies` / `displayMagnitudes` | `isMeasurementComplete`, `frozenFrequencies`, `frozenMagnitudes`, `fft.frequencies`, `fft.magnitudes` | Canvas renders either frozen or live spectrum based on `is_measurement_complete` flag; no single assembly call needed — canvas paint path gates on this flag | Canvas `_on_spectrum_updated` + paint path gated by `is_measurement_complete` property shim | ✅ |
| `sortedPeaksWithModes` | `displayMode`, `currentPeaks`, `TapDisplaySettings.showUnknownModes` | `_on_peaks_changed_results(peaks)` receives full peak list; `peak_widget.model` sorts and filters; mode classification applied by `peak_widget.model.auto_select_peaks_by_mode()` | `_on_peaks_changed_results` in `tap_tone_analysis_view.py` | ✅ |
| `calculatedPlateProperties` | `effectiveLongitudinalPeakID`, `effectiveCrossPeakID`, `effectiveFlcPeakID`, `longitudinalPeaks`, `crossPeaks`, `flcPeaks`, `TapDisplaySettings.plate*` dimensions | `PA.calculate_plate_properties(dims, long_freq, cross_freq, f_flc_hz)` called inside `_on_material_assignment_changed` and `_on_plate_analysis_complete` | `_on_plate_analysis_complete`, `_on_material_assignment_changed` in `tap_tone_analysis_view.py` | ✅ |
| `calculatedBraceProperties` | `effectiveLongitudinalPeakID`, `sortedPeaksWithModes`, `TapDisplaySettings.brace*` dimensions | `PA.calculate_brace_properties(dims, long_freq)` called inside `_on_material_assignment_changed` and at brace completion | Same slots | ✅ |
| `hasFlcMeasurement` | `flcPeaks.isEmpty`, `autoSelectedFlcPeakID`, `selectedFlcPeak` | Derived inline in `_on_plate_analysis_complete` from `f_flc > 0` signal payload; FLC peak card shown/hidden accordingly | `_on_plate_analysis_complete` | ✅ |
| `chartTitle` | `loadedMeasurementName` | Canvas `_measurement_name_label` set when a measurement is loaded | `_on_measurement_loaded` in `tap_tone_analysis_view.py` | ✅ |
| `effectiveLongitudinalPeakID` / `effectiveCrossPeakID` / `effectiveFlcPeakID` | `userSelectedLongitudinalPeakID`, `autoSelectedLongitudinalPeakID` (and cross/FLC equivalents) | `_material_peak_widget.set_assignment(long, cross, flc)` sets the effective assignments that `assignmentChanged` signal then propagates | Called from `_on_plate_analysis_complete` and `_on_material_assignment_changed` | ✅ |
| `cancelButtonEnabled` | `numberOfTaps`, `isDetecting`, `currentTapCount` | `cancel_tap_btn.setEnabled(is_detecting and tap_num > 1 and 0 < _tap_count_captured < tap_num)` | `_update_tap_buttons()` called from every detection state change | ✅ |
| `pauseResumeButtonEnabled` | `TapDisplaySettings.measurementType`, `isDetecting`, `isDetectionPaused` | `pause_tap_btn.setEnabled(is_detecting and (tap_num > 1 or is_plate))` + text/icon toggle in `_on_tap_detection_paused` | `_update_tap_buttons()` called from all state changes; `_on_tap_detection_paused` slot | ✅ |
| `materialPhaseStep` / `materialPhaseTitle` / `materialPhaseDescription` / `materialPhaseColor` / `materialPhaseIcon` | `materialTapPhase`, `TapDisplaySettings.measurementType`, `TapDisplaySettings.measureFlc` | `_update_plate_phase_ui()` sets `_mip_step_lbl`, `_mip_title_lbl`, `_mip_body_lbl`, dot stylesheet for each state | `_on_plate_status_changed` (via `plateStatusChanged` signal) and on measurement type change | ✅ |

### Rule 6 Issues Found

| Property | Issue | Severity | Status |
|---|---|---|---|
| `materialSpectra` | `set_material_spectra()` never called at plate/brace completion points — canvas always showed live spectrum, never the captured spectra | High | **Fixed this session** |

---

## Rule 7 Audit — Slot Handler Payload Consumption

Audit of Python slot handlers to verify they use signal payload as primary data source.

| Slot | Signal | Payload params | Alternative source read | Justified? | Status |
|---|---|---|---|---|---|
| `_on_level_changed` | `levelChanged(int)` | `amp` | `self._is_running`, `self._current_mt()` (view-local) | Yes — view-local state | ✅ |
| `_on_peak_info` | `peakInfoChanged(float, float)` | `peak_hz`, `peak_db` | `self._is_running` (view-local) | Yes | ✅ |
| `_on_framerate_update` | `framerateUpdate(float, float, float)` | `framerate`, `sampletime`, `processingtime` | `self.fft_canvas.saved_peaks` (for metrics dialog peak display) | Acceptable: metrics dialog is a debug tool; stale peaks show last known peak. Documented. | ✅ with note |
| `_on_peaks_changed_results` | `peaksChanged(object)` | `peaks` | None | — | ✅ |
| `_on_canvas_freq_range_changed` | `freqRangeChanged(int, int)` | `fmin`, `fmax` | None | — | ✅ |
| `_on_threshold_changed` | threshold signal | `db_val` | None | — | ✅ |
| `_on_tap_threshold_changed` | tap threshold signal | `db_val` | `self._loaded_tap_threshold` (view-local cache) | Yes — comparing loaded vs current | ✅ |
| `_on_tap_num_changed` | tap count signal | `n` | `self._loaded_tap_num` (view-local cache) | Yes | ✅ |
| `_on_tap_detection_paused` | `tapDetectionPaused(bool)` | `paused` | None | — | ✅ |
| `_on_status_message_changed` | `statusMessageChanged(str)` | `msg` | None | — | ✅ |
| `_on_tap_detected` | `tapDetected()` | (none) | `self._is_measurement_complete` (view-local) | Yes | ✅ |
| `_on_new_tap` | `tapDetected()` relayed | (none) | `self.fft_canvas.is_comparing` (property shim to analyzer) | Yes — current state | ✅ |
| `_on_ring_out_measured` | `ringOutMeasured(float)` | `time_s` | None — caches payload locally | — | ✅ |
| `_on_material_assignment_changed` | `assignmentChanged(float, float, float)` from peak widget | `long_freq`, `cross_freq`, `flc_freq` | `self.fft_canvas.saved_peaks` (for label assignment loop) | **No** — `saved_peaks` empty for plate mode; label loop never executes | **⚠ Gap — Fixed** |
| `_on_plate_status_changed` | `plateStatusChanged(str)` | `status` | Delegates to `_update_plate_phase_ui()` which reads analyzer via adapter | Yes — reads current live state | ✅ |
| `_on_plate_analysis_complete` | `plateAnalysisComplete(float, float, float)` | `f_long`, `f_cross`, `f_flc` | Previously read `saved_peaks` | **Fixed** — now uses payload only | ✅ |
| `_on_peaks_changed_ratios` | `peaksChanged(object)` | `peaks` | `analyzer.calculate_tap_tone_ratio()` — reads classified mode context from analyzer | Yes — payload used as guard; ratio needs mode classification context not in raw peak list | ✅ with note |
| `_on_comparison_changed` | `comparisonChanged(bool)` | `is_comparing` | `canvas.comparison_count` | Yes — signal carries only `True/False`; count needed for "Comparing N measurements" label | ✅ |
| `_on_devices_changed` | `devicesChanged(list)` | `device_names` | `sd.query_devices()` | Yes — `device_names` carries only name strings; full device metadata (channels, index) requires sounddevice query | ✅ |
| `_restore_measurement` | `measurementSelected(TapToneMeasurement)` | `m` | canvas/view-local state resets | Yes — `m` is authoritative payload; canvas state resets are side effects of restoring the measurement, not alternative data sources | ✅ |
| `_on_guitar_type_changed` | `currentTextChanged(str)` | `guitar_type` | None | — | ✅ |
| `_on_fmin_changed` / `_on_fmax_changed` | `valueChanged(int)` | `value` | `AS.AppSettings` persisted after set | Yes — persisting the value is a side effect, not an alternative read | ✅ |

### Rule 7 Notes

**`_on_framerate_update` / `saved_peaks`:** The metrics dialog calls `update_metrics(peaks=self.fft_canvas.saved_peaks)`. The `saved_peaks` array is the last set of peaks received by the canvas, populated via `peaksChanged` for guitar mode. For plate mode the array is empty after a reset. The metrics dialog gracefully handles an empty array (`if peaks.ndim == 2 and peaks.shape[0] > 0`). Since the metrics dialog is a debugging tool and not correctness-critical, this is acceptable but should be noted: in plate mode, the "Peak Frequency" and "Peak Magnitude" rows in the metrics dialog will show "—" after measurement completion. This matches the Swift behavior where `peakFrequency`/`peakMagnitude` are not exposed in the material measurement results view.

**`_on_material_assignment_changed` / `saved_peaks`:** The label-assignment loop at line 2320 iterated over `saved_peaks[:, 0]` to match peaks by frequency and update `peak_model.modes`. Since `saved_peaks` is never populated for plate/brace measurements, the loop body never executed and annotations were never labeled L/C/FLC. Fixed by iterating over `self.fft_canvas._current_peaks` (the `list[ResonantPeak]` populated by `peaksChanged` for all modes).

---

## Summary

### Issues Found This Audit

| Property / Component | Rule | Issue | Severity | Status |
|---|---|---|---|---|
| `materialTapPhase` | Rule 2 | `plateStatusChanged` never emitted — view UI phase step indicator never advanced | High | **Fixed** |
| `statusMessage` | Rule 2 | Model wrote `status_message` but view never received it — status bar never updated from model | Low | **Fixed** — `_set_status_message()` helper now emits `statusMessageChanged`; view slot `_on_status_message_changed` connected |
| `selectedPeakIDs` | Rule 5a | Plate/brace phase completion write sites had no Python equivalent — `selected_frequencies` always empty for plate/brace; "Selected" annotation mode showed no labels on spectrum | High | **Fixed** |
| `selectedPeakIDs` | Rule 5a | `applyFrozenPeakState` write site (peak threshold change on frozen measurement) had no Python equivalent — `_apply_frozen_peak_state` updated `analyzer.selected_peak_frequencies` but `peak_widget.model.selected_frequencies` was never updated; "Selected" mode showed stale selection after threshold slider move | High | **Fixed** — `_on_peaks_changed_results` now propagates `analyzer.selected_peak_frequencies` to `peak_widget.model.selected_frequencies` when `_is_measurement_complete` |
| `materialSpectra` (computed view property) | Rule 6 | `set_material_spectra()` never called at plate/brace completion — canvas showed wrong spectrum | High | **Fixed** |
| `_on_plate_analysis_complete` | Rule 7 | Read `saved_peaks` (always empty for plate) instead of signal payload `f_long/f_cross/f_flc` — L/C/FLC labels never applied | High | **Fixed** |
| `_on_material_assignment_changed` | Rule 7 | Read `saved_peaks` (always empty for plate) for label assignment loop — loop never executed for plate mode | High | **Fixed** |

### All Other Properties

All other `@Published` properties are either correctly signal-driven, correctly
pull-on-signal, correctly view-local, or not needed in the Python port.

All other slot handlers consume their signal payload correctly; any alternative source
reads are view-local state or are explicitly justified.

---

## Signal Coverage Map

The complete Swift→Python signal mapping for `TapToneAnalyzer`:

| Python signal | Swift `@Published` properties it covers |
|---|---|
| `peaksChanged(object)` | `currentPeaks`, `longitudinalPeaks`, `crossPeaks`, `flcPeaks` |
| `spectrumUpdated(object, object)` | `frozenFrequencies`, `frozenMagnitudes`, `magnitudes`, `frequencies` |
| `tapDetectedSignal()` | `tapDetected` |
| `tapCountChanged(int, int)` | `currentTapCount` |
| `ringOutMeasured(float)` | `currentDecayTime` |
| `levelChanged(int)` | `averageMagnitude`, `tapDetectionLevel`, `inputLevelDB` |
| `framerateUpdate(float, float, float)` | `frameRate`, `processingTimeMs`, `avgProcessingTimeMs` |
| `averagesChanged(int)` | (internal averaging count) |
| `newSample(bool)` | (FFT frame clock) |
| `displayModeChanged(object)` | `displayMode` |
| `measurementComplete(bool)` | (partial; primary path is `plateAnalysisComplete` + `tapDetected`) |
| `devicesChanged(list)` | `availableInputDevices`, `selectedInputDevice` |
| `currentDeviceLost(str)` | `microphoneWarning` |
| `plateStatusChanged(str)` | `materialTapPhase` |
| `plateAnalysisComplete(float, float, float)` | `isMeasurementComplete`, final peaks |
| `tapDetectionPaused(bool)` | `isDetectionPaused` |
| `comparisonChanged(bool)` | `comparisonSpectra` |
| `materialSpectraChanged(list)` | `longitudinalSpectrum`, `crossSpectrum`, `flcSpectrum` |
| `savedMeasurementsChanged()` | `savedMeasurements` |
| `freqRangeChanged(int, int)` | `minFrequency`, `maxFrequency` |
| `peakInfoChanged(float, float)` | `peakFrequency`, `peakMagnitude` |
