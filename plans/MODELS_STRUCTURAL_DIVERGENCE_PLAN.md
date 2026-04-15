# MODELS_STRUCTURAL_DIVERGENCE_PLAN.md

This plan addresses all 29 divergences (D1–D29) listed in
`MODELS_STRUCTURAL_DIVERGENCE_AUDIT.md`. It supersedes and extends the earlier
`STRUCTURAL_DIVERGENCE_PLAN.md` which covered only the TapToneAnalyzer cluster.

---

## Goals

1. **Correctness** — Python and Swift produce the same results for the same input.
2. **Serialisation safety** — JSON produced by one platform can be consumed by the other.
3. **Traceability** — a developer reading either codebase can find the counterpart mechanically.

---

## Divergence catalogue with disposition

### Fix required

All remaining divergences are actionable. Grouped into 19 work items below.

---

## Work Items

### WI-1 — Settings persistence (fixes D2, D3, D4, D5)

**Divergences:** `cycle_annotation_visibility` doesn't persist (D2); `tap_detection_threshold` write doesn't persist (D3); `hysteresis_margin` write doesn't persist (D4); `peak_threshold` write doesn't persist (D5).

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer.py`
- `src/guitar_tap/models/tap_tone_analyzer_control.py`

**Changes:**

1. In `tap_tone_analyzer.py`, `cycle_annotation_visibility()`: add the missing persistence call:
   ```python
   TapDisplaySettings.set_annotation_visibility_mode(self.annotation_visibility_mode)
   # mirrors cycleAnnotationVisibility() → TapDisplaySettings.annotationVisibilityMode in Swift
   ```

2. In `tap_tone_analyzer_control.py`, `set_tap_threshold()`: add persistence after setting:
   ```python
   TapDisplaySettings.set_tap_detection_threshold(self.tap_detection_threshold)
   # mirrors tapDetectionThreshold.didSet in Swift
   ```

3. In `tap_tone_analyzer_control.py`, `set_hysteresis_margin()`: add persistence:
   ```python
   TapDisplaySettings.set_hysteresis_margin(self.hysteresis_margin)
   # mirrors hysteresisMargin.didSet in Swift
   ```

4. In `tap_tone_analyzer_control.py`, `set_threshold()`: add persistence:
   ```python
   TapDisplaySettings.set_peak_threshold(self.peak_threshold)
   # mirrors peakThreshold.didSet in Swift
   ```

Verify `TapDisplaySettings` has setter classmethods for each of these four values (read `tap_display_settings.py` before editing to confirm method names).

**Risk:** Low. Additive only — existing behaviour unchanged; now settings survive restart.

---

### WI-2 — `effectiveXxxPeakID` middle layer (fixes D1)

**Divergence:** Swift has a three-layer resolution (user → `selectedXxxPeak?.id` → auto); Python's `effective_xxx_peak_id` properties skip the middle layer.

**File:** `src/guitar_tap/models/tap_tone_analyzer_annotation_management.py`

**Change:** Update each of the three `effective_xxx_peak_id` properties to consult `self.selected_xxx_peak` as the middle fallback:
```python
@property
def effective_longitudinal_peak_id(self):
    # mirrors Swift: userSelectedLongitudinalPeakID ?? selectedLongitudinalPeak?.id ?? autoSelectedLongitudinalPeakID
    return (
        self.user_selected_longitudinal_peak_id
        or (self.selected_longitudinal_peak.id if self.selected_longitudinal_peak else None)
        or self.auto_selected_longitudinal_peak_id
    )
```
Same pattern for `cross` and `flc`.

**Risk:** Medium. The middle layer is used during plate/brace phase measurement to preserve the user's phase-selected peaks. Read the Swift implementation and confirm `selectedLongitudinalPeak` is set during plate phase before editing.

---

### WI-3 — `ResonantPeak` type alignment (fixes D14, D15, D16)

**Divergences:** `id` is `str` not `UUID` (D14); `timestamp` is `str` not `Date` (D15); `mode_label` is Python-only (D16).

**File:** `src/guitar_tap/models/resonant_peak.py`

**D14/D15 — no code change required.** Python cannot use Swift's `UUID` or `Date` types. These divergences are inherent to the cross-language boundary. The correct action is:
- Add a docstring note to the `id` field: `# str form of UUID — Swift uses UUID type`
- Add a docstring note to the `timestamp` field: `# ISO-8601 string — Swift uses Date`

**D16 — `mode_label` field:** This field is Python-only and not present in Swift `ResonantPeak`. Document it:
```python
mode_label: str = ""
# Python-only display hint — not present in Swift ResonantPeak.
# Set by the view layer before rendering; not persisted.
```

**Risk:** None — documentation only.

---

### WI-4 — `TapToneMeasurement` type alignment (fixes D28, D29)

**Divergences:** `annotation_offsets` is `dict[str, list[float]]` vs Swift `[UUID: CGPoint]` (D28); `peak_mode_overrides` is `dict[str, str]` vs Swift `[UUID: UserAssignedMode]` (D29).

**File:** `src/guitar_tap/models/tap_tone_measurement.py`

**No code change required.** These are cross-language boundary differences. `UUID` and `CGPoint` have no Python equivalents; `str`-keyed dicts are the correct Python representation. The action is:
- Add docstring notes to both fields explaining the Swift counterpart types.
- Verify `to_dict()` / `from_dict()` round-trip produces JSON compatible with Swift's `Codable` output. Specifically:
  - `annotation_offsets` encodes as alternating `[uuid_str, {absFreqHz, absDB}]` array — check this matches Swift's `CGPoint`-keyed `KeyedEncodingContainer` output.
  - `peak_mode_overrides` encodes as `{uuid: {"type": "assigned", "label": "..."}}` — check this matches Swift's `UserAssignedMode` `Codable` output.

**Risk:** None — documentation and verification only.

---

### WI-5 — `MaterialDimensions` storage units (fixes D17)

**Divergence:** Python `MaterialDimensions` stores mm/g; Swift stores SI (m, kg) directly.

**File:** `src/guitar_tap/models/material_properties.py`

**No code change required.** This is a deliberate Python design choice: input fields match the units the user enters (mm/g), and SI properties are computed on demand. This is actually more ergonomic than Swift's approach.

The action is to add a module-level docstring clarification and field-level comments:
```python
# NOTE: stores in mm / g (user-facing units).
# Swift equivalent stores in SI (m, kg) directly.
# Use .length_m, .width_m, .thickness_m, .mass_kg for SI access.
```

**Risk:** None — documentation only.

---

### WI-6 — `TapDisplaySettings` missing helpers (fixes D18, D19)

**Divergences:** `tap_detection_threshold` scale difference (D18); `resetToDefaults` / `validateFrequencyRange` / `validateMagnitudeRange` absent (D19).

**File:** `src/guitar_tap/models/tap_display_settings.py`

**D18 — scale difference:** The QSettings scale (0-100) vs dBFS difference is intentional — QSettings stores the slider integer. The conversion at read time is correct. Add a comment explaining this:
```python
# QSettings stores threshold as 0-100 integer (slider value).
# Converted to dBFS by subtracting 100 at read time.
# Swift stores dBFS directly; Python stores the raw slider value.
```

**D19 — missing helpers:** Add three static classmethods:
1. `reset_to_defaults()` — writes default values for all settings.
2. `validate_frequency_range(min_freq, max_freq)` — clamps to 20–20000 Hz, enforces 10 Hz minimum separation; returns `(min_freq, max_freq)` tuple.
3. `validate_magnitude_range(min_db, max_db)` — clamps to −120–20 dB, enforces 10 dB minimum separation; returns `(min_db, max_db)` tuple.

These mirror the Swift equivalents exactly. Default values for `reset_to_defaults()` should match the Swift defaults in `TapDisplaySettings.swift`.

**Risk:** Low. New classmethods only; no existing code touched.

---

### WI-7 — `MaterialTapPhase` missing convenience properties (fixes D20)

**Divergence:** Python `MaterialTapPhase` missing `is_plate`, `is_brace`, `is_complete` properties.

**File:** `src/guitar_tap/models/material_tap_phase.py`

**Change:** Add three `@property` members mirroring the Swift computed vars:
```python
@property
def is_plate(self) -> bool:
    # mirrors Swift MaterialTapPhase.isPlate
    return self in (
        MaterialTapPhase.CAPTURING_LONGITUDINAL,
        MaterialTapPhase.WAITING_FOR_CROSS_TAP,
        MaterialTapPhase.CAPTURING_CROSS,
        MaterialTapPhase.WAITING_FOR_FLC_TAP,
        MaterialTapPhase.CAPTURING_FLC,
    )

@property
def is_brace(self) -> bool:
    # mirrors Swift MaterialTapPhase.isBrace
    # Read Swift MaterialTapPhase.swift to confirm exact cases before implementing.
    ...

@property
def is_complete(self) -> bool:
    # mirrors Swift MaterialTapPhase.isComplete
    return self == MaterialTapPhase.COMPLETE
```

**Before implementing:** Read `MaterialTapPhase.swift` to confirm the exact Swift case assignments for `isPlate` and `isBrace` (there is a `BRACE_READY` / `BRACE_MEASURED` distinction to check).

**Risk:** Low. New properties only.

---

### WI-8 — `SpectrumSnapshot` extra fields (fixes D21)

**Divergence:** Python `SpectrumSnapshot` has ~18 extra fields (`guitar_type`, `measurement_type`, `is_logarithmic`, plate/brace dimensions, etc.) not present in Swift.

**File:** `src/guitar_tap/models/spectrum_snapshot.py`

**No code removal.** These extra fields serve a legitimate purpose in Python (the snapshot is used to restore full analysis context). Do not remove them.

**Action:**
1. Add a class-level comment explaining the extra fields:
   ```python
   # NOTE: Python SpectrumSnapshot carries additional analysis-context fields
   # (guitar_type, measurement_type, dimension fields) that are not present in
   # Swift SpectrumSnapshot. In Swift these values are stored on TapToneMeasurement,
   # not on the snapshot. Python merges them here for self-contained serialisation.
   ```
2. Verify that the six core fields (`frequencies`, `magnitudes`, `min_freq`, `max_freq`, `min_db`, `max_db`) and the Base64 binary encoding format for `frequenciesData`/`magnitudesData` remain compatible with Swift's `Codable` output. This is the cross-platform boundary that matters.

**Risk:** None — documentation only.

---

### WI-9 — `CalibrationStorage` device key (fixes D24, D25)

**Divergences:** `CalibrationStorage` keys by device name (Python) vs CoreAudio UID (Swift) (D24); `AudioDevice` uses `fingerprint` vs `uid` (D25).

**Files:**
- `src/guitar_tap/models/microphone_calibration.py`
- `src/guitar_tap/models/audio_device.py`

**No code change required.** This divergence is a platform constraint — PortAudio provides no stable UID. Keying by device name is the correct Python approach.

**Action:**
1. In `CalibrationStorage`, add a comment on `_DEVICE_MAP_KEY`:
   ```python
   # Maps device name to calibration UUID.
   # Swift equivalent maps by CoreAudio UID (stable across sessions).
   # Python uses device name as a best-effort key (PortAudio provides no UID).
   ```
2. In `AudioDevice`, confirm the `fingerprint` property docstring already explains this (it does — verified).

**Risk:** None — documentation only.

---

### WI-10 — Replace `threading.Timer` with `QTimer.singleShot` (fixes D13)

**Divergence:** Swift uses `DispatchQueue.main.asyncAfter` to schedule deferred work on the main thread. Python uses `threading.Timer`, which fires on a background thread and then must hand back to the main thread via `QMetaObject.invokeMethod(QueuedConnection)`. The two-step pattern is more complex and relies on a non-obvious trampoline.

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer_spectrum_capture.py`
- `src/guitar_tap/models/tap_tone_analyzer_tap_detection.py`
- `src/guitar_tap/models/tap_tone_analyzer_decay_tracking.py`

**Change:** Replace every `threading.Timer` + `QMetaObject.invokeMethod(QueuedConnection)` pair with a single `QTimer.singleShot(ms, slot)` call. `QTimer.singleShot` fires on the thread that owns the receiver object (the main thread), exactly matching `DispatchQueue.main.asyncAfter`.

Pattern to replace:
```python
# Before
def _callback():
    QMetaObject.invokeMethod(self, "_my_slot", Qt.QueuedConnection)
t = threading.Timer(delay_seconds, _callback)
t.daemon = True
t.start()

# After
QTimer.singleShot(int(delay_seconds * 1000), self._my_slot)
```

**Before implementing:** Read each of the three files to confirm all usages follow this pattern. There are at least 6 timer sites across the three files (safety timeout, phase transitions × 2, capture window, re-enable cooldown × 2, decay tracking).

**Risk:** Medium. Timer behaviour change — validate that `QTimer.singleShot` fires on the correct thread in the Qt event loop context used by the application.

---

### WI-11 — Eliminate `FftParameters` class (fixes D27)

**Divergence:** Python has a standalone `FftParameters` class (`fft_parameters.py`) with no Swift counterpart. In Swift, `RealtimeFFTAnalyzer` owns `fftSize`, `targetSampleRate`, and `window` from construction time. Python's `RealtimeFFTAnalyzer` already owns the same fields at runtime (`fft_size`, `m_t`, `h_fft_size`, `window_fcn`). `FftParameters` exists only because `FftCanvas` (view) currently constructs `RealtimeFFTAnalyzer` and needs FFT config before the mic object exists.

**Files:**
- `src/guitar_tap/models/fft_parameters.py` — to be deleted
- `src/guitar_tap/views/fft_canvas.py` — construction-order dependency to resolve
- `src/guitar_tap/models/tap_tone_analyzer.py` — should own `RealtimeFFTAnalyzer` from `__init__`

**Change:** Restructure ownership so that `TapToneAnalyzer.__init__` creates `RealtimeFFTAnalyzer` directly (passing `fft_size` and `rate`), eliminating the need for `FftCanvas` to construct it. Any axis computation currently done with `FftParameters` fields in `FftCanvas` should read from `TapToneAnalyzer.fft_analyzer` instead.

Delete `fft_parameters.py` once no callers remain.

**Before implementing:** Read `fft_canvas.py` and `tap_tone_analyzer.py` to map all current usages of `FftParameters` and confirm the construction sequence. The change touches the view layer (`fft_canvas.py`) as well as the model layer.

**Risk:** High. Touches construction order across view and model layers. Read both files fully before editing.

---

### WI-12 — Add `set_frozen_spectrum()` helper (fixes D6)

**Divergence:** Swift's `setFrozenSpectrum(frequencies:magnitudes:)` calls `objectWillChange.send()` before assigning both arrays atomically, preventing SwiftUI from rendering a state where `frozenFrequencies` and `frozenMagnitudes` have mismatched lengths. Python assigns both fields at separate lines across multiple call sites. The `spectrumUpdated` signal carries both arrays as a payload (safe), but direct property reads of `frozen_frequencies` and `frozen_magnitudes` in `tap_tone_analysis_view.py` (snapshot creation, measurement load, export) can observe a half-updated state if called between the two assignments.

**File:** `src/guitar_tap/models/tap_tone_analyzer.py`

**Change:** Add a `set_frozen_spectrum(frequencies, magnitudes)` method:
```python
def set_frozen_spectrum(self, frequencies, magnitudes) -> None:
    """Set frozen spectrum arrays atomically.

    mirrors Swift setFrozenSpectrum(frequencies:magnitudes:) — assigns both
    arrays before any connected slot can observe them, preventing callers from
    reading a half-updated state where the two arrays have mismatched lengths.
    """
    self.frozen_frequencies = frequencies
    self.frozen_magnitudes = magnitudes
```

Then replace all paired direct assignments of `frozen_frequencies` / `frozen_magnitudes` in:
- `tap_tone_analyzer_spectrum_capture.py` (lines 596-597, 928-929)
- `tap_tone_analyzer_control.py` (lines 304-305, 350-351)

with calls to `self.set_frozen_spectrum(...)`.

Reset-to-empty calls (clearing both to `np.array([])`) should also use `set_frozen_spectrum(np.array([]), np.array([]))`.

**Note:** Python has no `objectWillChange.send()` equivalent. The guarantee here is that no Python code runs between the two assignments (Python's GIL ensures the method body runs without interruption from other threads), which is sufficient since all view reads occur on the main thread.

**Risk:** Low. Additive helper; all existing signal flows through `spectrumUpdated` are unaffected.

---

### WI-13 — Move measurement assembly into model layer (fixes D9)

**Divergence:** `_collect_measurement()` in `tap_tone_analysis_view.py` (view layer) assembles a `TapToneMeasurement` and passes the pre-built object to `save_measurement()`. Swift's `saveMeasurement` keeps this assembly in the model layer, accepting 14 individual parameters and constructing `TapToneMeasurement` internally.

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer_measurement_management.py`
- `src/guitar_tap/views/tap_tone_analysis_view.py`

**Changes:**

1. In `tap_tone_analyzer_measurement_management.py`, rename the current `save_measurement(measurement)` to `_append_measurement(measurement)` (private — only used internally and by the import path).

2. Add a new `save_measurement(...)` method that accepts the individual parameters currently passed to `TapToneMeasurement.create()` in `_collect_measurement()`:
   ```python
   def save_measurement(
       self,
       tap_location: str,
       notes: str,
       include_spectrum: bool,
       spectrum_snapshot: ...,
       # ... remaining parameters mirroring TapToneMeasurement.create() signature
   ) -> None:
       """Save a new measurement assembled from individual parameters.

       mirrors Swift saveMeasurement(tapLocation:notes:includeSpectrum:...) in
       TapToneAnalyzer+MeasurementManagement.swift — the model is responsible for
       constructing TapToneMeasurement, not the view layer.
       """
       measurement = TapToneMeasurement.create(
           tap_location=tap_location,
           notes=notes,
           include_spectrum=include_spectrum,
           spectrum_snapshot=spectrum_snapshot,
           # ... forward all parameters
       )
       self._append_measurement(measurement)
   ```

3. In `tap_tone_analysis_view.py`, update `_on_save_measurement()` to call `self.analyzer.save_measurement(...)` with the individual parameters directly, removing the `_collect_measurement()` / `TapToneMeasurement.create()` call from the view.

4. The import path (`_on_import()` in `measurements_list_view.py`) that passes already-deserialized objects continues to call `_append_measurement()` directly — this is the correct entry point for pre-built objects.

**Before implementing:** Read `tap_tone_analysis_view.py` `_collect_measurement()` and `_on_save_measurement()` in full to enumerate the exact parameter list, then read `TapToneMeasurement.create()` to confirm the factory signature. The new `save_measurement` signature should be a 1:1 forward of all parameters to `TapToneMeasurement.create()`.

**Risk:** Medium. The view call site changes significantly. The import path must be explicitly updated to use `_append_measurement` — do not leave it calling the old `save_measurement` or it will break.

---

### WI-14 — Move `_restore_measurement` into model layer (fixes D10)

**Divergence:** Swift `loadMeasurement(_:)` lives in `TapToneAnalyzer+MeasurementManagement.swift` (~280 lines) — it is a model method that restores the full analyzer state from a saved measurement. Python's equivalent is `_restore_measurement()` in `tap_tone_analysis_view.py` (~350 lines) — entirely in the view layer, with a different name. There is no `load_measurement` in any Python model file.

The audit previously described this as "in `control.py`" — that was incorrect. The function does not exist in the model layer at all.

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer_measurement_management.py` — add `load_measurement(measurement)` here
- `src/guitar_tap/views/tap_tone_analysis_view.py` — thin the `_restore_measurement()` to a view-only wrapper

**Changes:**

1. In `tap_tone_analyzer_measurement_management.py`, add a `load_measurement(measurement: TapToneMeasurement)` method that takes over the analyzer-state restoration currently done in `_restore_measurement()`. This includes:
   - Setting frozen frequencies/magnitudes (via `set_frozen_spectrum()`)
   - Restoring loaded peaks, peak selections, decay time
   - Restoring annotation offsets, visibility mode
   - Restoring thresholds, number of taps
   - Restoring phase-specific spectra (`loaded_longitudinal_snapshot`, etc.)
   - Emitting the appropriate signals (`peaksChanged`, `spectrumUpdated`, etc.)

2. In `tap_tone_analysis_view.py`, reduce `_restore_measurement()` to a view-only wrapper that:
   - Calls `self.analyzer.load_measurement(m)` for all model-state changes
   - Handles only view-layer concerns: UI widget updates, guitar type / measurement type selectors, plate/brace dimension widgets, display settings controls

**Before implementing:** Read `_restore_measurement()` in full (lines 3040–3390) to classify each statement as model-layer (goes to model) or view-layer (stays in view). Read `loadMeasurement(_:)` in Swift to understand the intended split — Swift's version handles only model state; the SwiftUI view observes `@Published` properties and reacts automatically, which is why there is no view-layer restoration code in Swift.

**Note on view-only state:** Some restoration in `_restore_measurement()` directly updates Qt widget state (combo boxes, spin boxes, sliders). These lines must stay in the view wrapper. Only the analyzer state mutations belong in the model.

**Risk:** High. This is the largest single refactor in the plan (~350 lines moved/split across two files). The boundary between model-state and view-state restoration must be drawn carefully. Read both files fully before editing.

---

### WI-15 — Move `average_spectra` to spectrum-capture mixin and wire up callers (fixes D12)

**Divergence:** `average_spectra` lives in `TapToneAnalyzerPeakAnalysisMixin` (`tap_tone_analyzer_peak_analysis.py`) but has **zero callers in the entire Python codebase** — it is dead code. In Swift, `averageSpectra` lives in `TapToneAnalyzer+SpectrumCapture.swift` and is called by all three gated-capture handlers (`handleLongitudinalGatedProgress`, `handleCrossGatedProgress`, `handleFlcGatedProgress`) and by `processMultipleTaps`. The multi-tap averaging path is not wired up in Python at all.

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer_peak_analysis.py` — remove `average_spectra`
- `src/guitar_tap/models/tap_tone_analyzer_spectrum_capture.py` — add `average_spectra`; wire up callers

**Changes:**

1. Move `average_spectra(from_taps)` from `TapToneAnalyzerPeakAnalysisMixin` to `TapToneAnalyzerSpectrumCaptureMixin` in `tap_tone_analyzer_spectrum_capture.py`. The implementation is correct — only the location changes.

2. Identify the Python equivalents of the four Swift call sites:
   - `handleLongitudinalGatedProgress` → Python's gated longitudinal completion handler
   - `handleCrossGatedProgress` → Python's gated cross-grain completion handler
   - `handleFlcGatedProgress` → Python's gated FLC completion handler
   - `processMultipleTaps` → Python's multi-tap processing path

   In each, replace whatever spectrum selection is currently used (likely just using the last tap's spectrum) with a call to `self.average_spectra(taps)`, matching Swift's behaviour.

**Before implementing:** Read `tap_tone_analyzer_spectrum_capture.py` to find the Python equivalents of the four Swift call sites and understand what data structure the captured taps are stored in. The `from_taps` parameter expects items with `.magnitudes` and `.frequencies` attributes — confirm the Python tap storage format matches.

**Risk:** Medium. Moving the function is trivial. Wiring up callers touches the spectrum capture path and changes which spectrum is used for multi-tap measurements — this is a correctness change (from single-tap to properly averaged) that must be verified to produce the expected result.

---

### WI-16 — Rename `PlateStiffnessPreset.value` to `stiffness` (fixes D23)

**Divergence:** Python's `PlateStiffnessPreset` defines `@property value` to return the stiffness float, which silently overrides Python's `Enum.value` (which would normally return the raw display string e.g. `"Steel String Top"`). This causes an active display bug: `tap_tone_analysis_view.py:2653` uses `_preset.value` expecting the display string in a label like `"f_vs = 75 (Steel String Top)"`, but currently receives the float `75.0`, producing `"f_vs = 75 (75.0)"` instead.

In Swift, the computed var is named `value: Float` and does not collide with anything — Swift enums have no built-in `.value` accessor.

**File:** `src/guitar_tap/models/plate_stiffness_preset.py`
**Call sites:** `tap_display_settings.py:240`, `tap_analysis_results_view.py:437`, `tap_tone_analysis_view.py:2653`

**Changes:**

1. In `plate_stiffness_preset.py`, rename `@property value` to `@property stiffness`:
   ```python
   @property
   def stiffness(self) -> float:
       # mirrors Swift PlateStiffnessPreset.value — named 'stiffness' in Python to
       # avoid overriding Enum.value (which returns the raw display string).
       ...
   ```

2. In `tap_display_settings.py:240`, change `preset.value` → `preset.stiffness` (this call expects the stiffness float).

3. In `tap_analysis_results_view.py:437`, change `_preset.value` → `_preset.stiffness` (this call expects the stiffness float).

4. In `tap_tone_analysis_view.py:2653`, **no change required**. After the rename, `_preset.value` returns the standard `Enum.value` string (e.g. `"Steel String Top"`), which is exactly what the label format string requires. The display bug is resolved automatically.

**Risk:** Low. Only 3 call sites; the rename is mechanical. The fix at line 2653 is a side effect of restoring correct `Enum.value` semantics, not an explicit change.

---

### WI-17 — Auto-device-switch on plug-in (fixes D30)

**Divergence:** Swift `loadAvailableInputDevicesMacOS()` compares the newly-enumerated device list against the previous list and automatically calls `setInputDevice(_:)` for the first newly-connected real device (filtering out transient `CADefaultDeviceAggregate` entries). Python's `_notify_devices_changed()` only rebuilds the UI combo box — the user must manually select the new device.

**File:** `src/guitar_tap/models/realtime_fft_analyzer_device_management.py`
Also: `src/guitar_tap/models/tap_tone_analyzer_control.py` (the `_on_devices_refreshed` slot that handles the hot-plug callback)

**Change:** In the Python hot-plug callback path, after rebuilding the device list, compare it against the previously-known list and auto-switch if a new real device was added:

```python
def _notify_devices_changed(self) -> None:
    """Signal the caller that the device list has changed, and auto-switch
    to a newly-connected device — mirrors Swift loadAvailableInputDevicesMacOS()
    which auto-selects the first newly-connected real device."""
    if self._on_devices_changed is None:
        return
    time.sleep(0.5)  # Let OS finish its own device enumeration
    # Store previous device list before refreshing
    previous = list(self._available_devices or [])
    self._on_devices_changed()
    # Auto-switch to newly-connected device (mirrors Swift auto-selection)
    current = list(self._available_devices or [])
    newly_connected = [d for d in current if d.fingerprint not in {p.fingerprint for p in previous}]
    if newly_connected and self._on_auto_switch_device is not None:
        self._on_auto_switch_device(newly_connected[0])
```

The `_on_auto_switch_device` callback should be wired to `TapToneAnalyzerControlMixin.set_device()`.

**Before implementing:** Read `_notify_devices_changed()`, `load_available_input_devices()`, and the `_on_devices_refreshed()` handler in `tap_tone_analyzer_control.py` to understand how `_available_devices` is maintained and how to plumb the auto-switch callback. The implementation detail may differ from the sketch above — follow the existing callback pattern.

**Risk:** Medium. Auto-switching is a behaviour change that must be tested: verify it fires only for genuinely new devices, not on every hot-plug event, and not when a device is removed.

---

### WI-18 — Fix stale `_gated_sample_rate` after device switch (fixes D31)

**Divergence:** `TapToneAnalyzer._gated_sample_rate` is initialised once in `start()` from `self.mic.rate`. When `set_device()` is called later with a device at a different sample rate, `fft_data.sample_freq` is updated but `_gated_sample_rate` and `_pre_roll_samples` are not. The gated MPM capture window is then sized for the wrong sample rate.

**File:** `src/guitar_tap/models/tap_tone_analyzer_control.py`

**Change:** Add two lines to `set_device()` immediately after `self.mic.set_device(device)`:
```python
self._gated_sample_rate = float(self.mic.rate)
self._pre_roll_samples = int(self.mic.rate * self._pre_roll_seconds)
# mirrors Swift: AVAudioEngine re-reads hardware format on every start(),
# so _gated_sample_rate is always current after a device switch.
```

**Risk:** Low. Two-line additive fix; no structural change.

---

### WI-19 — Mid-session sample rate change detection (fixes D26)

**Divergence:** Swift `registerSampleRateListener(for:)` detects when the user changes the active device's sample rate in Audio MIDI Setup mid-session (e.g. 44.1 kHz → 48 kHz) and automatically stops, reconfigures, and restarts the audio engine. Python has no equivalent. PortAudio does not surface per-device sample-rate change notifications through its public API, but the underlying OS APIs do exist and can be called directly — the same pattern already used for hot-plug detection.

**Approach:** Extend the existing platform-native monitors in `realtime_fft_analyzer_device_management.py`:

- **macOS**: Register an additional `AudioObjectAddPropertyListener` on the active device for `kAudioDevicePropertyNominalSampleRate` (selector `0x73726174`, device scope). When fired, compare the new rate to the current stream rate; if different, stop the stream, update `mic.rate`, and restart — mirroring Swift's `registerSampleRateListener(for:)` behaviour. The CoreAudio `ctypes` infrastructure is already in place.

- **Windows**: Implement `IAudioSessionEvents::OnSessionDisconnected` (via `comtypes` or `pywin32`) and handle `DisconnectReasonFormatChanged`, or implement `IMMNotificationClient::OnPropertyValueChanged` filtering on `PKEY_AudioEngine_DeviceFormat`. Either approach triggers a stream teardown and reinitialisation at the new format.

- **Linux**: More fragmented than the other platforms, depending on the audio layer in use:
  - **ALSA (bare)**: No notification mechanism exists. ALSA has no push-event model for device parameter changes; errors from `snd_pcm_readi` are the only signal. PortAudio's ALSA backend inherits this — no fix possible at this layer.
  - **PulseAudio**: `pa_context_subscribe(PA_SUBSCRIPTION_MASK_SOURCE)` + `pa_context_set_subscribe_callback()` fires on any source property change. In the callback, query the source info to check whether the sample rate changed. Not a pinpoint "rate changed" event, but works as a push notification. Python binding: `pulsectl` (pip-installable).
  - **PipeWire (native)**: `pw_stream_events.param_changed` fires when the stream's negotiated format changes including sample rate; PipeWire can renegotiate mid-session rather than just disconnecting. Accessible via raw `ctypes` to `libpipewire`. On systems running PipeWire with the PulseAudio compatibility layer (`pipewire-pulse`), the `pulsectl` approach also works.
  - **Practical recommendation**: Run a `pulsectl` subscription thread alongside the sounddevice stream. This covers both PulseAudio and PipeWire-as-PulseAudio (the default on Fedora, Ubuntu, Debian since ~2022). On pure ALSA systems no fix is possible; add a code comment noting the limitation.

**Files:** `realtime_fft_analyzer_device_management.py` (extend `_start_linux_monitor()`; add rate-change subscription alongside existing `pyudev` hot-plug monitor); Windows COM interop helper (TBD); `pulsectl` added to Linux dependencies.

**Note:** The existing `_start_linux_monitor()` uses `pyudev` for hot-plug detection. The rate-change monitor is a separate concern and should run as an additional subscription thread alongside it, not replace it.

**Risk:** Medium. Extends platform-native monitors with new property selectors; requires careful thread handling (CoreAudio callbacks run on a background thread). Follow the existing hot-plug callback pattern.

---

## Summary table

| Work Item | Divergences fixed | Type | Files touched |
|---|---|---|---|
| WI-1 | D2, D3, D4, D5 | Bug fix | `tap_tone_analyzer.py`, `tap_tone_analyzer_control.py` |
| WI-2 | D1 | Bug fix | `tap_tone_analyzer_annotation_management.py` |
| WI-3 | D14, D15, D16 | Documentation | `resonant_peak.py` |
| WI-4 | D28, D29 | Documentation + verification | `tap_tone_measurement.py` |
| WI-5 | D17 | Documentation | `material_properties.py` |
| WI-6 | D18, D19 | New methods | `tap_display_settings.py` |
| WI-7 | D20 | New properties | `material_tap_phase.py` |
| WI-8 | D21 | Documentation | `spectrum_snapshot.py` |
| WI-9 | D24, D25 | Documentation | `microphone_calibration.py`, `audio_device.py` |
| WI-10 | D13 | Refactor | `tap_tone_analyzer_spectrum_capture.py`, `tap_tone_analyzer_tap_detection.py`, `tap_tone_analyzer_decay_tracking.py` |
| WI-11 | D27 | Refactor + deletion | `fft_parameters.py` (delete), `fft_canvas.py`, `tap_tone_analyzer.py` |
| WI-12 | D6 | New helper + call-site update | `tap_tone_analyzer.py`, `tap_tone_analyzer_spectrum_capture.py`, `tap_tone_analyzer_control.py` |
| WI-13 | D9 | Refactor (model owns assembly) | `tap_tone_analyzer_measurement_management.py`, `tap_tone_analysis_view.py` |
| WI-14 | D10 | Refactor (model owns load) | `tap_tone_analyzer_measurement_management.py`, `tap_tone_analysis_view.py` |
| WI-15 | D12 | Move + wire callers (dead code fix) | `tap_tone_analyzer_peak_analysis.py`, `tap_tone_analyzer_spectrum_capture.py` |
| WI-16 | D23 | Bug fix (rename + display fix) | `plate_stiffness_preset.py`, `tap_display_settings.py`, `tap_analysis_results_view.py` |
| WI-17 | D30 | New behaviour (auto-switch on plug-in) | `realtime_fft_analyzer_device_management.py`, `tap_tone_analyzer_control.py` |
| WI-18 | D31 | Bug fix (one-liner) | `tap_tone_analyzer_control.py` |
| WI-19 | D26 | New behaviour (platform-native rate-change listeners) | `realtime_fft_analyzer_device_management.py`; Windows COM helper (TBD); Linux TBD |

**All 31 divergences are addressed.** 7 bugs/races fixed (D1, D2, D3/D4/D5, D6, D12, D23, D31). 3 new behaviours (D26, D30). 3 add missing methods/properties (D19, D20). 4 refactors (D9, D10, D13, D27). The remainder are documentation.

---

## Implementation order

1. **WI-1** (settings persistence bugs) — highest correctness impact, lowest risk
2. **WI-12** (`set_frozen_spectrum` helper) — low risk, closes a real race condition
3. **WI-2** (`effectiveXxxPeakID` middle layer) — read Swift before editing
4. **WI-7** (`MaterialTapPhase` convenience properties) — read Swift before editing
5. **WI-6** (`TapDisplaySettings` helpers) — new code, read Swift defaults first
6. **WI-10** (`QTimer.singleShot` refactor) — read all three files before editing
7. **WI-13** (model owns measurement assembly) — read `_collect_measurement()` and `TapToneMeasurement.create()` in full before editing; update import path explicitly
8. **WI-14** (model owns measurement load) — largest refactor; read `_restore_measurement()` in full and classify each line as model or view before touching anything; do WI-13 first since both touch `tap_tone_analyzer_measurement_management.py`
9. **WI-15** (`average_spectra` move + wire callers) — read spectrum capture file first to find Python call sites; do after WI-10 since both touch the spectrum capture file
10. **WI-11** (`FftParameters` elimination) — highest structural risk; read view and model layers first
11. **WI-18** (`_gated_sample_rate` fix in `set_device()`) — two-line fix; do before WI-17 since WI-17 relies on `set_device()` working correctly
12. **WI-16** (`PlateStiffnessPreset.value` → `stiffness` rename) — low risk; mechanical rename across 3 call sites
13. **WI-17** (auto-device-switch on plug-in) — read `_notify_devices_changed()` and `_on_devices_refreshed()` first; medium risk
14. **WI-3, WI-4, WI-5, WI-8, WI-9** — documentation passes; can be done in any order
15. **WI-19** (platform-native rate-change listeners) — do after WI-17/WI-18 since all three touch the device management monitor; confirm Linux mechanism before implementing that platform; macOS and Windows can proceed independently

---

## Verification

After implementation:

1. **WI-1:** Start Python app, change threshold/hysteresis/annotation settings, quit, relaunch — verify settings are restored from QSettings.
2. **WI-2:** In plate measurement mode, capture a longitudinal tap (sets `selected_longitudinal_peak`), then check `effective_longitudinal_peak_id` returns that peak's id when no user override is set.
3. **WI-6:** Call `TapDisplaySettings.reset_to_defaults()` and verify all settings revert to the values in Swift's `TapDisplaySettings.swift` defaults.
4. **WI-7:** Verify `MaterialTapPhase.CAPTURING_LONGITUDINAL.is_plate == True`, `MaterialTapPhase.NOT_STARTED.is_complete == False`, `MaterialTapPhase.COMPLETE.is_complete == True`.
5. **WI-10:** Verify each deferred callback fires on the main thread; run tap detection sequence end-to-end.
6. **WI-11:** Verify `FftParameters` is no longer imported anywhere; verify `fft_parameters.py` is deleted; run FFT capture sequence end-to-end.
7. **WI-13:** Save a measurement from the UI — verify it is persisted correctly. Import a measurement from file — verify `_append_measurement` path works. Confirm `_collect_measurement()` is no longer present in the view.
8. **WI-14:** Load a saved measurement from the measurements list — verify all peaks, spectrum, decay time, and settings restore correctly. Confirm `_restore_measurement()` in the view contains only widget updates; all analyzer-state mutations are in `load_measurement()` on the model.
9. **WI-15:** Capture a multi-tap measurement — verify the averaged spectrum is used (not just the last tap). Confirm `average_spectra` no longer exists in `tap_tone_analyzer_peak_analysis.py`.
10. **WI-16:** Verify `PlateStiffnessPreset.STEEL_STRING_TOP.value == "Steel String Top"` (standard Enum.value). Verify `PlateStiffnessPreset.STEEL_STRING_TOP.stiffness == 75.0`. Verify the f_vs label in the UI reads `"f_vs = 75 (Steel String Top)"` not `"f_vs = 75 (75.0)"`.
11. **WI-17:** Plug in a new microphone while the Python app is running — verify it auto-switches without user interaction. Unplug a device — verify the app does not crash and does not attempt to auto-switch.
12. **WI-18:** Switch to a 48 kHz device after starting on a 44.1 kHz device; immediately perform a plate tap measurement — verify the gated capture window is sized correctly for 48 kHz (not 44.1 kHz).
13. **Run existing tests:** `pytest` from the Python project root — no regressions.
14. **Build Swift project:** `BuildProject` MCP command — ensure no Swift changes needed.
