# Comparison: TapToneAnalyzer+Control — Swift vs Python

**Swift source:** `GuitarTap/GuitarTap/Models/TapToneAnalyzer+Control.swift`
**Python source:** `src/guitar_tap/models/tap_tone_analyzer_control.py`
**Date:** 2026-04-29

These files are supposed to be structurally, algorithmically, by signature/naming, and functionally
identical — the Python file is a port of the Swift original.

---

## 1. Function/Method Inventory

### Swift-only methods (no Python equivalent)

| Swift method | Reason absent from Python |
|---|---|
| `start()` | Microphone management handled differently in Python; `RealtimeFFTAnalyzer.start()` called directly by the view |
| `stop()` | Same; Python calls `mic.stop()` directly |

### Python-only methods (no Swift equivalent in this file)

| Python-only method | Reason |
|---|---|
| `_set_status_message(message)` | Swift uses `@Published statusMessage` directly; Python needs an explicit setter to emit `statusMessageChanged` |
| `_on_devices_refreshed()` | Python-only: PortAudio hot-plug handling with debounce guard; Swift uses CoreAudio/AVAudioSession callbacks handled elsewhere |
| `_on_devices_refreshed_impl()` | Inner implementation of the above; no Swift equivalent in this file |
| `set_device(device)` | Python-only: delegates to `RealtimeFFTAnalyzer.set_device()`; Swift's device switching is handled inside `RealtimeFFTAnalyzer` |
| `_on_mic_calibration_changed(cal)` | Python-only: receives calibration profile emitted by `RealtimeFFTAnalyzer.set_device()`; Swift uses `selectedInputDevice.didSet` |
| `load_calibration(path)` | Python-only: parses and applies a calibration file; Swift equivalent is in `RealtimeFFTAnalyzer` |
| `load_calibration_from_profile(cal)` | Python-only: applies a pre-parsed calibration profile |
| `clear_calibration()` | Python-only: removes active calibration from the FFT pipeline |
| `current_calibration_device()` | Python-only: returns calibration device name |
| `handle_route_change_restart()` | Python-only: equivalent logic is on the main `TapToneAnalyzer` class in Swift, not in this extension file |
| `_restore_detection_after_route_change(was_detecting, was_live)` | Python-only: named equivalent of Swift's inline `asyncAfter` closure in `handleRouteChangeRestart` |
| `set_tap_threshold(value)` | Python-only: UI setter converting 0–100 scale to dBFS; Swift uses a property observer on `tapDetectionThreshold` |
| `set_hysteresis_margin(value)` | Python-only: UI setter; Swift uses a property observer on `hysteresisMargin` |
| `start_from_file(path, on_finished)` | Python-only: feeds audio file through the FFT pipeline; Swift's equivalent is in `RealtimeFFTAnalyzer` |
| `set_measurement_type(measurement_type)` | Python-only: switches analysis mode; Swift uses `TapDisplaySettings` directly |
| `set_threshold(threshold)` | Python-only: peak-detection threshold UI setter |
| `set_fmin(fmin)` / `set_fmax(fmax)` | Python-only: axis bound setters; Swift updates bounds directly |
| `update_axis(fmin, fmax, init)` | Python-only: delegates to `recalculate_frozen_peaks_if_needed()` |
| `set_loaded_axis_range(min_freq, max_freq, min_db, max_db)` | Python-only: atomic axis-range setter emitting `loadedAxisRangeChanged` |
| `set_max_average_count(max_average_count)` | Python-only: UI setter |
| `reset_averaging()` | Python-only: resets averaging counter |
| `set_avg_enable(avg_enable)` | Python-only: enables/disables averaging |
| `set_auto_scale(enabled)` | Python-only: enables/disables auto-scaling |
| `start_plate_analysis()` | Thin wrapper around `start_tap_sequence()`; moved here from `SpectrumCapture` mixin |
| `reset_plate_analysis()` | Thin wrapper around `cancel_tap_sequence()`; same |

### Matched function pairs

| Swift | Python |
|---|---|
| `reset()` | `reset()` |
| `startTapSequence(skipWarmup:)` | `start_tap_sequence(skip_warmup)` |
| `pauseTapDetection()` | `pause_tap_detection()` |
| `resumeTapDetection()` | `resume_tap_detection()` |
| `cancelTapSequence()` | `cancel_tap_sequence()` |
| `acceptCurrentPhase()` | `accept_current_phase()` |
| `redoCurrentPhase()` | `redo_current_phase()` |
| `resetMaterialPhaseState(to:)` (private) | `_reset_material_phase_state(to)` |
| `resetDecayTracking()` (private) | `_reset_decay_tracking()` |

`set_tap_num(n)` in Python mirrors Swift's `numberOfTaps.didSet` property observer. The logic is
present in both; Swift expresses it as a `didSet` on the property declaration, Python as an explicit
setter method.

`_finalise_plate_no_flc()` and `_finalise_plate_with_flc()` in Python are refactored helper methods
extracted from `accept_current_phase()`. Swift inlines this logic directly inside `acceptCurrentPhase()`
in the `reviewingCross` (no-FLC) and `reviewingFlc` branches respectively. Same logic, different
factoring.

---

## 2. Algorithmic Differences

### `reset()`

**Difference 1 — `lastTapTime = nil` in Swift, `last_tap_time` NOT cleared in Python `reset()`:**
Swift `reset()` line 84 sets `self.lastTapTime = nil`. Python has a `last_tap_time` field
(`tap_tone_analyzer.py` line 382), but `reset()` does **not** clear it. Python only clears
`last_tap_time` inside `reset_tap_detector()` (called from `start_decay_tracking()`), not
from the `reset()` / `cancel_tap_sequence()` code paths. A stale `last_tap_time` from a
previous sequence could affect the cooldown guard in `detect_tap()` and the decay time
calculation in `measure_decay_time()` after a hard reset.

**Difference 2 — `tapsForAveraging = []` in Swift, no Python equivalent:**
Swift `reset()` line 91 and `cancelTapSequence()` line 309 clear `tapsForAveraging: [[ResonantPeak]]`.
Investigation confirms this is **dead code in Swift**: the property is declared and cleared but is
never populated or read anywhere in the codebase (`TapToneAnalyzer.swift` line 837). Python correctly
has no equivalent. This is a Swift-only dead declaration, not a Python omission.

**Difference 3 — `captureTimer?.invalidate()` in Swift, no Python equivalent:**
Swift `reset()` (lines 94–95) and `cancelTapSequence()` (lines 329–330) invalidate and nil a
persistent `captureTimer: Timer?`. Python has no stored `capture_timer` property. The equivalent
in Python is `QTimer.singleShot()` called without retaining the timer reference, so there is
no object to invalidate. The `finish_capture()` Python method is a no-op for this reason. This
means that if a Python `QTimer.singleShot` capture callback fires after `reset()` or
`cancel_tap_sequence()` has already run, there is no way to prevent the stale callback from
executing. Whether this is a bug depends on how quickly `reset()` can race with an in-flight
`QTimer.singleShot` callback.

**Difference 4 — `loadedMeasurementName = nil` ordering:**
Swift `reset()` sets `loadedMeasurementName = nil` near the *bottom* of the async block (line 113),
after `resetMaterialPhaseState` and `displayMode = .live`. Python sets `loaded_measurement_name = None`
and emits `loadedMeasurementNameChanged` near the *top* of the function. The final state is
identical; ordering differs.

**Difference 5 — `reset()` runs inside `DispatchQueue.main.async` in Swift, synchronously in Python:**
Swift's `reset()` body is wrapped in `DispatchQueue.main.async { [weak self] in … }`. Python runs
synchronously on the main Qt thread. Functionally equivalent.

---

### `startTapSequence(skipWarmup:)` / `start_tap_sequence(skip_warmup)`

Swift separates a *synchronous* pre-block (setting `isMeasurementComplete`, `setFrozenSpectrum`,
`isDetecting`, `analyzerStartTime` before any audio buffer can arrive) from a
`DispatchQueue.main.async` housekeeping block. Python combines both into a single synchronous block
because the main Qt thread provides the same guarantee.

**Difference 1 — `comparisonSpectra = []` in Swift, state is NOT explicitly cleared in Python:**
Swift `startTapSequence()` async block line 168 sets `self.comparisonSpectra = []`.
Python splits comparison state across three parallel fields: `_comparison_data`,
`comparison_labels`, and `comparison_snapshots` (all in `tap_tone_analyzer.py`).
`start_tap_sequence()` does **not** clear any of them. The Python comment at line 493
says this is "handled by the view's `clear_comparison()`" — meaning the view layer is
expected to call `clear_comparison()` before `start_tap_sequence()`. Swift clears the
state on the model itself. This is a responsibility boundary difference: Python requires
the caller to clear comparison state; Swift handles it internally.

**Difference 2 — `reset_all_annotation_offsets()` called in Python, not in Swift:**
Python `start_tap_sequence()` calls `self.reset_all_annotation_offsets()`. Swift
`startTapSequence()` does NOT call `resetAllAnnotationOffsets()` — annotation offsets
are only cleared in `reset()`. Because `peakAnnotationOffsets` is keyed by UUID and new
measurements produce new UUIDs, orphaned offsets have no visible effect. Python is more
conservative; Swift is not wrong, but the behaviour differs.

**Difference 3 — `source_measurement_timestamp = None` cleared in Python, not in Swift:**
Python `start_tap_sequence()` sets `self.source_measurement_timestamp = None` and emits
`loadedMeasurementNameChanged`. Swift `startTapSequence()` clears `loadedMeasurementName = nil`
but does **not** set `sourceMeasurementTimestamp = nil`. In Swift, `sourceMeasurementTimestamp`
is only cleared in `reset()`. The PDF export uses `tap.sourceMeasurementTimestamp ?? Date()` —
so without this clear, a new live measurement's PDF would show the previously loaded
measurement's original date if the user pressed New Tap without pressing Reset first. Python's
clear is a correctness fix that is absent from Swift.

**Difference 4 — `peakMagnitudeHistory = []` cleared inside async block in Swift, synchronously in Python:**
Swift clears `peakMagnitudeHistory = []` inside the async block (line 192), which runs *after*
`isDetecting = true` has already been set synchronously. Python clears it synchronously before
`is_detecting = True`. There is a narrow window in Swift where `isDetecting = true` but
`peakMagnitudeHistory` still holds old data. In practice the async block is dispatched immediately
and this window is sub-millisecond.

**Difference 5 — `tapCountChanged` signal emitted in Python, no equivalent in Swift:**
Python ends `start_tap_sequence()` with `self.tapCountChanged.emit(0, self.number_of_taps)`.
Swift sets `currentTapCount = 0` (line 183) which auto-notifies via `@Published`. Permitted
reactivity translation.

---

### `pauseTapDetection()` / `pause_tap_detection()`

**Difference 1 — `tapDetectionPaused.emit(True)` in Python, no equivalent in Swift:**
Python emits `self.tapDetectionPaused.emit(True)`. Swift has no equivalent signal — `isDetectionPaused`
is `@Published` and auto-notifies. Permitted reactivity translation.

**Confirmed identical:** guard condition (`isDetecting && !isDetectionPaused`), state assignments
(`isDetecting = false`, `isDetectionPaused = true`), status message string.

---

### `resumeTapDetection()` / `resume_tap_detection()`

**Difference 1 — `tapDetectionPaused.emit(False)` in Python, no equivalent in Swift:**
Same pattern as `pauseTapDetection`. Permitted reactivity translation.

**Confirmed identical:** guard (`isDetectionPaused`), warm-up timer reset, `isAboveThreshold = false`,
`isDetecting = true`, all status message branches.

---

### `cancelTapSequence()` / `cancel_tap_sequence()`

**Difference 1 — `tapsForAveraging = []` in Swift, no Python equivalent:**
Same as `reset()` Difference 2 above. Dead code in Swift; Python correctly omits it.

**Difference 2 — `captureTimer?.invalidate()` in Swift, no Python equivalent:**
Same as `reset()` Difference 3 above. Stale `QTimer.singleShot` callbacks have no
cancellation path in Python.

**Difference 3 — `isMeasurementComplete = true` via direct assignment in Swift vs helper in Python:**
Swift: `self.isMeasurementComplete = true` (line 318). Python: `self.set_measurement_complete(True)`.
Swift's `@Published` `isMeasurementComplete.didSet` also clears `showLoadedSettingsWarning` when
the value becomes `true`. Verify that Python's `set_measurement_complete` helper replicates this
`didSet` side-effect. If it does not, cancelling a sequence after loading settings could leave the
warning banner visible when it should have been cleared.

**Difference 4 — `tapCountChanged.emit(0, self.number_of_taps)` in Python, no equivalent in Swift:**
`currentTapCount = 0` is `@Published` in Swift. Permitted reactivity translation.

**Difference 5 — `cancelTapSequence` runs inside `DispatchQueue.main.async` in Swift, synchronously in Python:**
Same structural pattern as `reset()`. Functionally equivalent.

---

### `acceptCurrentPhase()` / `accept_current_phase()`

Python factors the `.reviewingCross` (no-FLC) and `.reviewingFlc` completion paths into separate
helper methods (`_finalise_plate_no_flc`, `_finalise_plate_with_flc`). The logic is identical;
the factoring differs.

**Confirmed identical — `REVIEWING_LONGITUDINAL` branch:**
Phase transition, frozen spectrum clear, `isAboveThreshold` computation against falling threshold,
`analyzerStartTime` reset, `isDetecting = true`, `tapDetected = false`, status message string.

**Confirmed identical — `REVIEWING_CROSS` with FLC branch:**
Phase set to `waitingForFlcTap`, status message, `QTimer.singleShot`/`asyncAfter` cooldown
advancing to `capturingFlc`, all inner state assignments.

**REVIEWING_CROSS (no-FLC) — Difference 1 — `selected_peak_frequencies` set in Python, not in Swift:**
Python `_finalise_plate_no_flc()` sets `self.selected_peak_frequencies = [p.frequency for p in sel]`.
Swift's corresponding branch does not set `selectedPeakFrequencies`. `selectedPeakFrequencies` is a
transient cache for frequency-proximity carry-forward when Peak Min is adjusted on a frozen spectrum.
Swift's `selectedPeakIDs` already holds the correct selection after plate completion; the cache is
only needed on the next threshold change. Python's assignment is a proactive population; Swift's
omission is not a bug, but the behaviour diverges on the first post-completion threshold adjustment.

**REVIEWING_CROSS (no-FLC) — Difference 2 — `_emit_peaks_array` and `plateAnalysisComplete` in Python:**
Python `_finalise_plate_no_flc()` calls `self._emit_peaks_array(self.current_peaks)` (emitting
`peaksChanged`) and `self.plateAnalysisComplete.emit(fl, fc, 0.0)`. Swift's branch does not emit
`peaksChanged` explicitly (it fires via `@Published currentPeaks`). `plateAnalysisComplete` has no
Swift equivalent in this function. Permitted reactivity translations.

**REVIEWING_FLC — Difference 3 — `_emit_peaks_array` and `plateAnalysisComplete` in Python:**
Same pattern as no-FLC path. Permitted reactivity translations.

---

### `redoCurrentPhase()` / `redo_current_phase()`

**Structural difference — deferred vs inline `materialTapPhase` assignment:**
Swift sets `materialTapPhase = .capturingLongitudinal` (etc.) *inline* within each case, before
`setFrozenSpectrum`. Python uses a deferred pattern: a local `capture_phase` variable is set in
each branch and applied via `self._set_material_tap_phase(capture_phase)` at the end of the
function, after `set_frozen_spectrum`. The final state is identical; the order of the phase
transition relative to the spectrum clear differs.

**`REVIEWING_LONGITUDINAL` — Difference 1 — `set_material_spectra([])` in Python, absent in Swift:**
Python calls `self.set_material_spectra([])` to clear the material spectra overlay. Swift does not
call any equivalent function — `longitudinalSpectrum = nil` causes the `materialSpectra` computed
property in the view to return `[]` automatically via `@Published`. Permitted reactivity translation.

**`REVIEWING_CROSS` — Difference 2 — `set_material_spectra([L])` in Python, absent in Swift:**
Python explicitly calls `self.set_material_spectra(spectra)` with `[L]` to restore the longitudinal
overlay after clearing cross data. Swift derives this from `@Published crossSpectrum = nil` leaving
`longitudinalSpectrum` intact. Permitted reactivity translation.

**`REVIEWING_FLC` — Difference 3 — `set_material_spectra([L, C])` in Python, absent in Swift:**
Python explicitly calls `self.set_material_spectra(spectra)` with `[L, C]`. Swift derives from
`@Published flcSpectrum = nil`. Permitted reactivity translation.

**`tapCountChanged` signal — Python emits, Swift does not:**
After redo, Python emits `self.tapCountChanged.emit(self.current_tap_count, self.number_of_taps)`.
Swift's `currentTapCount` is `@Published`. Permitted reactivity translation.

**Confirmed identical — all three branches:** phase-spectrum clear fields, peak clear fields,
tap count restoration logic (`lCount`, `lcCount`), `tapProgress` computation, frozen spectrum
clear, `isAboveThreshold` computation, `analyzerStartTime` reset, `isDetecting = true`,
`tapDetected = false`, status message strings.

---

### `resetMaterialPhaseState(to:)` / `_reset_material_phase_state(to)`

**Confirmed identical:** all twelve field clears (`longitudinalSpectrum`, `crossSpectrum`,
`flcSpectrum`, `longitudinalPeaks`, `crossPeaks`, `flcPeaks`, auto/user/selected peak fields),
gated capture cancellation.

**Lock discipline — same outcome, different syntax:**
Swift: `gatedCaptureActive = false; mpmLock.lock(); gatedAccumBuffer = []; mpmLock.unlock()`
Python: `with self._gated_lock: self._gated_capture_active = False; self._gated_accum = []`
Python sets `_gated_capture_active = False` *inside* the lock (stricter atomicity). Swift sets
`gatedCaptureActive = false` *before* acquiring the lock. Functionally equivalent given Swift's
atomic `@Published` store; Python's approach is more conservative.

**Python adds `set_material_spectra([])` call at the end:**
`_reset_material_phase_state` ends with `self.set_material_spectra([])`. Swift's equivalent is
implicit — `longitudinalSpectrum = nil` etc. cause `materialSpectra` to return `[]` in the view.
Permitted reactivity translation.

---

### `resetDecayTracking()` / `_reset_decay_tracking()`

**Confirmed identical:** `isTrackingDecay = false`, timer invalidation/nil. Swift uses
`decayTrackingTimer?.invalidate()` on a `Timer`. Python calls `self._decay_tracking_timer.stop()`
on a `QTimer`. Structurally equivalent.

---

### `set_tap_num(n)` / `numberOfTaps.didSet`

**Difference — Swift uses a property `didSet`, Python uses an explicit setter method:**
The logic is identical: if the new count is at or below the already-captured count, truncate
and call `process_multiple_taps()` immediately. Otherwise just update the number. The
"clear warning if user deviates from loaded value" check is present in both.

**Difference — `del self.captured_taps[new_num:]` vs `capturedTaps.removeSubrange(new_num...)`:**
Python truncates with `del` on a list. Swift uses `removeSubrange`. Functionally identical.

---

### Tap counting: `currentTapCount`

Swift (`TapToneAnalyzer+TapDetection.swift` line 267): `currentTapCount += 1` — incremented on each
detected tap event (rising-edge crossing). Python: `self.current_tap_count = len(self.captured_taps)`
— re-derived from the list length after each append. Both values are semantically identical at any
observable point (both track the number of successfully captured taps). This is not a divergence.

---

## 3. Signal/Emit Ordering Differences

### `reset()`

| Swift | Python |
|---|---|
| `loadedMeasurementName = nil` (near bottom, auto-notifies) | `loadedMeasurementNameChanged.emit(None)` (near top, explicit) |
| `isMeasurementComplete = false` (auto-notifies) | `measurementComplete.emit(False)` (explicit) |
| `showLoadedSettingsWarning = false` (auto-notifies) | `showLoadedSettingsWarningChanged.emit(False)` (explicit) |
| `statusMessage = "..."` (auto-notifies) | `_set_status_message("...")` → emits `statusMessageChanged` |

### `startTapSequence()`

| Swift | Python |
|---|---|
| `comparisonSpectra = []` (on model, in async block) | view must call `clear_comparison()` before starting |
| `isMeasurementComplete = false` (sync, before async block) | `measurementComplete.emit(False)` (sync) |
| `showLoadedSettingsWarning = false` (in async block) | `showLoadedSettingsWarningChanged.emit(False)` (sync, early) |
| `loadedMeasurementName = nil` (in async block) | `loadedMeasurementNameChanged.emit(None)` (sync) |
| `currentTapCount = 0` (auto-notifies) | `tapCountChanged.emit(0, self.number_of_taps)` (at end) |

### `cancelTapSequence()`

| Swift | Python |
|---|---|
| `isMeasurementComplete = true` (direct `@Published`, triggers `didSet`) | `set_measurement_complete(True)` helper |
| `currentTapCount = 0` (auto-notifies) | `tapCountChanged.emit(0, self.number_of_taps)` |

### `pauseTapDetection()` / `resumeTapDetection()`

Python emits `tapDetectionPaused.emit(True/False)` — no Swift equivalent signal.

### `redoCurrentPhase()`

Python emits `tapCountChanged.emit(...)` and calls `set_material_spectra(spectra)` at the end.
Swift has neither explicit call — both auto-derive from `@Published` properties.

---

## 4. Naming Divergences

Beyond the expected camelCase → snake_case convention, these names specifically differ:

| Swift | Python | Issue |
|---|---|---|
| `statusMessage = "..."` | `_set_status_message("...")` | `@Published` property → setter method |
| `materialTapPhase = .x` | `_set_material_tap_phase(x)` | `@Published` property → setter method |
| `isMeasurementComplete = true` | `set_measurement_complete(True)` in cancel; `self.is_measurement_complete = True` in guitar completion | **Inconsistent within Python itself** — should standardise |
| `numberOfTaps.didSet` | `set_tap_num(n)` | Property observer → explicit setter |
| `tapDetectionThreshold.didSet` | `set_tap_threshold(value)` | Property observer → explicit setter |
| `hysteresisMargin.didSet` | `set_hysteresis_margin(value)` | Property observer → explicit setter |
| `peakThreshold.didSet` | `set_threshold(threshold)` | Property observer → explicit setter |
| `mpmLock` | `_gated_lock` | Different name (aligns with `_gated_*` naming in Python) |
| `analyzerStartTime = Date()` | `self.analyzer_start_time = _time.monotonic()` | Foundation `Date` → POSIX monotonic clock |
| `lastTapTime: Date?` | `last_tap_time: float \| None` | Exists in Python but name matches; NOT cleared in `reset()` / `cancel_tap_sequence()` |
| `captureTimer: Timer?` | no equivalent stored property | Swift persists a reference; Python uses `QTimer.singleShot` with no stored reference |
| `tapsForAveraging: [[ResonantPeak]]` | no equivalent | Swift dead code — declared and cleared but never populated or read; Python correctly omits it |
| `comparisonSpectra: [ComparisonSpectrum]` | `_comparison_data` / `comparison_labels` / `comparison_snapshots` | Swift: single list on model; Python: three parallel fields, view-managed clearing |

---

## 5. Structural Differences

**`DispatchQueue.main.async` wrapping:**
`reset()` and `cancelTapSequence()` in Swift run their entire body inside `DispatchQueue.main.async`.
`startTapSequence()` has a *synchronous* pre-block before an async housekeeping block.
Python runs everything synchronously on the main Qt thread. All logic that Swift dispatches
asynchronously is executed synchronously in Python with identical functional outcome.

**`acceptCurrentPhase()` factoring:**
Swift inlines all phase completion logic inside `acceptCurrentPhase()`. Python extracts
`_finalise_plate_no_flc()` and `_finalise_plate_with_flc()` as named helpers. Identical logic,
different factoring.

**Comparison state ownership:**
Swift owns `comparisonSpectra` on the model and clears it inside `startTapSequence()`.
Python splits comparison state across three fields managed by `TapToneAnalyzerMeasurementManagementMixin`
and delegates clearing to the view layer via `clear_comparison()`. This is a responsibility boundary
difference.

**Python-only calibration and device subsystem:**
`_on_devices_refreshed`, `_on_devices_refreshed_impl`, `set_device`, `_on_mic_calibration_changed`,
`load_calibration`, `load_calibration_from_profile`, `clear_calibration`, `current_calibration_device`
form a device/calibration management block with no equivalent in this Swift extension. In Swift
these responsibilities are distributed across `RealtimeFFTAnalyzer` and the main `TapToneAnalyzer`
class via `selectedInputDevice.didSet`.

**Python-only `handle_route_change_restart()` and `_restore_detection_after_route_change()`:**
In Swift, `handleRouteChangeRestart()` lives on the main `TapToneAnalyzer` class (not in this
extension file). Python places it here because it is logically a control-flow method.

**Python-only UI parameter setters:**
`set_threshold`, `set_fmin`, `set_fmax`, `update_axis`, `set_loaded_axis_range`,
`set_max_average_count`, `reset_averaging`, `set_avg_enable`, `set_auto_scale` expose model
mutations to the view layer. Swift connects the view directly to `@Published` properties and
settings.

---

## 6. Missing or Divergent Logic

### Missing in Python (divergences requiring investigation or remediation)

- **`reset()` / `cancel_tap_sequence()`: `last_tap_time` not cleared.**
  Python has `last_tap_time` but neither `reset()` nor `cancel_tap_sequence()` clears it. Swift clears
  `lastTapTime = nil` in both. A stale `last_tap_time` from a previous sequence affects the cooldown
  guard in `detect_tap()` and the decay calculation in `measure_decay_time()`.

- **`reset()` / `cancel_tap_sequence()`: `captureTimer` has no stored reference to invalidate.**
  Swift invalidates `captureTimer` in both. Python uses `QTimer.singleShot` with no stored reference,
  so stale callbacks cannot be cancelled. `finish_capture()` is a no-op as a result. Whether a
  stale callback can race with `reset()` / `cancel_tap_sequence()` should be assessed.

- **`startTapSequence()`: comparison state not cleared on the model.**
  Swift clears `comparisonSpectra = []` inside `startTapSequence()`. Python delegates this to the
  view via `clear_comparison()`. If the view does not call `clear_comparison()` before
  `start_tap_sequence()`, stale comparison spectra remain on the model for the new sequence.

### Missing in Swift (Python has logic absent from Swift)

- **`startTapSequence()`: `source_measurement_timestamp = None` cleared in Python, not in Swift.**
  Without this clear, a new live measurement's PDF shows the previously loaded measurement's
  original date (`sourceMeasurementTimestamp ?? Date()` in `TapToneAnalysisView+Export.swift`).

- **`startTapSequence()`: `reset_all_annotation_offsets()` called in Python, not in Swift.**
  Functionally benign (orphaned UUID-keyed offsets have no visible effect), but Python is more
  conservative.

- **Permitted reactivity additions throughout:** `tapCountChanged.emit(...)`,
  `tapDetectionPaused.emit(...)`, `set_material_spectra(...)` calls,
  `_emit_peaks_array(...)` — all replace Swift's `@Published` auto-notification.

---

## 7. Data Type / Structure Differences

| Swift | Python | Difference |
|---|---|---|
| `analyzerStartTime: Date` | `analyzer_start_time: float` (`time.monotonic()`) | Foundation `Date` → POSIX monotonic clock |
| `lastTapTime: Date?` | `last_tap_time: float \| None` | Exists in Python; not cleared in reset/cancel |
| `captureTimer: Timer?` | no stored property | Swift persists and invalidates; Python discards after `singleShot` |
| `tapsForAveraging: [[ResonantPeak]]` | no equivalent | Swift dead code — never populated or read; correctly absent from Python |
| `comparisonSpectra: [ComparisonSpectrum]` | `_comparison_data` + `comparison_labels` + `comparison_snapshots` | Single model field vs three parallel view-managed fields |
| `mpmLock: NSLock` | `_gated_lock: threading.Lock` | Both are mutex types; different APIs |

---

## 8. Priority Issues for Remediation

1. **`last_tap_time` not cleared in Python `reset()` and `cancel_tap_sequence()`.**
   Swift clears `lastTapTime = nil` in both. Add `self.last_tap_time = None` to both methods in
   Python, mirroring Swift's `reset()` line 84 and `cancelTapSequence()` (implicitly, via the
   full state wipe).

2. **`sourceMeasurementTimestamp` not cleared in Swift `startTapSequence()`.**
   Python `start_tap_sequence()` sets `self.source_measurement_timestamp = None` explicitly. Swift
   `startTapSequence()` does not clear `sourceMeasurementTimestamp` — it is only cleared in `reset()`.
   The Swift PDF export path uses `tap.sourceMeasurementTimestamp ?? Date()`, so the `?? Date()`
   fallback applies whenever the field is nil, which is the normal live (non-loaded) state. A stale
   value can only appear if the user calls `startTapSequence()` directly without a prior `reset()` —
   i.e. without pressing the Reset / New Tap button — which the view does not currently do. The user
   has not observed this bug in practice. **This divergence is lower risk than originally assessed.**
   If the view always calls `reset()` before `startTapSequence()`, there is no observable effect.
   Nonetheless, matching Python's explicit clear in Swift (`sourceMeasurementTimestamp = nil` in the
   `startTapSequence()` async block) would be a defensive improvement for correctness parity.

3. **`isMeasurementComplete` signalling inconsistent within Python.**
   `cancel_tap_sequence()` uses `self.set_measurement_complete(True)` (emits signal); the guitar
   completion path in `process_multiple_taps()` sets `self.is_measurement_complete = True` directly
   (no signal, deferred to `measurementComplete.emit(True)` later). Standardise to one pattern.
   Also verify that `set_measurement_complete(True)` replicates Swift's `isMeasurementComplete.didSet`
   side-effect of clearing `showLoadedSettingsWarning`.

4. **Comparison state not cleared inside `start_tap_sequence()`.**
   Swift clears `comparisonSpectra = []` on the model. Python delegates to the view. Either add
   an explicit `_comparison_data = []; comparison_labels = []; comparison_snapshots = []` clear
   inside `start_tap_sequence()`, or document that the caller is contractually required to call
   `clear_comparison()` first.

5. **`QTimer.singleShot` capture callbacks cannot be cancelled.**
   Swift's `captureTimer` allows `reset()` / `cancelTapSequence()` to prevent stale callbacks from
   firing. Python has no equivalent cancellation. Assess whether any `QTimer.singleShot` callbacks
   in the tap detection path (e.g. `_finish_capture`, `_do_reenable_guitar`) can fire after a
   `reset()` and cause incorrect state transitions.
