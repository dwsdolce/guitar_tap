# MODELS_STRUCTURAL_DIVERGENCE_PLAN.md

This plan addresses 46 divergences (D1–D47, with D46 unused) — the original 29 from
`MODELS_STRUCTURAL_DIVERGENCE_AUDIT.md` plus 17 discovered during implementation
(D30–D38 during WI-6 verification; D39–D43 during WI-13 code review; D44 during WI-13
verification; D45 during WI-14 verification; D46 unused; D47 during metrics view bug fix).
It supersedes and extends the earlier `STRUCTURAL_DIVERGENCE_PLAN.md` which covered only
the TapToneAnalyzer cluster.

---

## Goals

1. **Correctness** — Python and Swift produce the same results for the same input.
2. **Serialisation safety** — JSON produced by one platform can be consumed by the other.
3. **Traceability** — a developer reading either codebase can find the counterpart mechanically.

---

## Divergence catalogue with disposition

### Fix required

All remaining divergences are actionable. Grouped into 31 work items below.

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

**~~NO-OP — D20 was a false positive in the audit.~~**

Verification of `MaterialTapPhase.swift` across all commits confirms that Swift has never had `isPlate`, `isBrace`, or `isComplete` properties on `MaterialTapPhase`. The audit incorrectly recorded these as present in Swift; they do not exist. Adding them to Python would create a divergence rather than fix one.

No code change required.

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

### WI-27 — Move all `SpectrumSnapshot` assembly into model layer; fix naming and structure (fixes D39)

**Divergence (corrected and expanded):** Both guitar and per-phase `SpectrumSnapshot` objects are domain data and belong in the model. Python currently builds per-phase snapshots in the view (`_collect_measurement_params()`) because the per-phase magnitude arrays live on `canvas.plate_capture` (a view-layer object). In Swift they live on the analyzer (`tap.longitudinalSpectrum`, `tap.crossSpectrum`, `tap.flcSpectrum`). There are four connected structural problems:

1. **Per-phase spectra live in the wrong layer.** Python: `canvas.plate_capture.long_mag_db` etc. (view layer). Swift: `tap.longitudinalSpectrum` etc. (model/analyzer). The per-phase magnitude arrays must move onto the analyzer so the model can build all snapshots itself.

2. **All snapshot assembly must move to the model.** Once the per-phase spectra are on the analyzer, the model's `save_measurement()` can build guitar *and* per-phase `SpectrumSnapshot` objects from its own state — exactly as Swift's model `saveMeasurement()` does in `TapToneAnalyzer+MeasurementManagement.swift` (lines 191–207). Python's model already builds the guitar snapshot correctly; the per-phase snapshot assembly still lives in the view and must move.

3. **View method name mismatch.** Swift's view has `saveMeasurement()` (`TapToneAnalysisView+Actions.swift` line 115). Python's view has `_collect_measurement_params()` — wrong name. The method must be renamed `save_measurement()` and restructured to call `analyzer.save_measurement(...)` directly (not return a dict). The `makePhaseSnapshot` / `_make_phase_snapshot` local helper disappears because snapshot building moves to the model.

4. **Model signature must match Swift exactly.** Swift's model `saveMeasurement` signature (`TapToneAnalyzer+MeasurementManagement.swift` lines 166–184) includes an optional `spectrumSnapshot: SpectrumSnapshot? = nil` override parameter used by the import path. Python's current model signature omits this and must be updated to match.

**Correct architecture (both Swift and Python):**
- Model `save_measurement()` builds ALL snapshots — guitar snapshot from `frozen_frequencies`/`frozen_magnitudes`, per-phase snapshots from `self.longitudinal_spectrum`/`self.cross_spectrum`/`self.flc_spectrum`.
- View `save_measurement()` does only: read axis range floats from ViewBox (genuine view state), read mic/calibration device identity, call `analyzer.save_measurement(...)`.
- No `SpectrumSnapshot` construction anywhere in the view.

**Swift reference — model `saveMeasurement` builds guitar snapshot** (`TapToneAnalyzer+MeasurementManagement.swift` lines 191–204):
```swift
if includeSpectrum && measurementType.isGuitar {
    snapshot = spectrumSnapshot ?? SpectrumSnapshot(
        frequencies: isMeasurementComplete ? frozenFrequencies : fftAnalyzer.frequencies,
        magnitudes:  isMeasurementComplete ? frozenMagnitudes  : fftAnalyzer.magnitudes,
        minFreq: minFreq ?? TapDisplaySettings.minFrequency, ...
    )
}
```

**Swift reference — view `saveMeasurement` builds per-phase snapshots** (`TapToneAnalysisView+Actions.swift` lines 151–165) using `tap.longitudinalSpectrum` etc. — this is where Python currently is. **This is the Swift technical debt we are fixing in Python** — per-phase spectra should be on the analyzer and per-phase snapshots should be built in the model.

**Four implementation steps:**

**Step 1 — Move per-phase spectra onto the analyzer** (`tap_tone_analyzer.py`):
- `self.longitudinal_spectrum`, `self.cross_spectrum`, `self.flc_spectrum` already exist as `None` on the analyzer (lines 315–317). They are currently populated by `canvas.plate_capture` in the view. Instead, the analyzer's `_finish_capture` / phase-completion paths must set these directly, mirroring Swift's `@Published var longitudinalSpectrum` on the analyzer.
- Concretely: wherever `canvas.plate_capture.long_mag_db` / `.cross_mag_db` / `.flc_mag_db` are currently set in the view's capture flow, also set `analyzer.longitudinal_spectrum`, `analyzer.cross_spectrum`, `analyzer.flc_spectrum` as `(magnitudes, frequencies)` tuples mirroring Swift's `(magnitudes: [Float], frequencies: [Float])` named tuples.

**Step 2 — Move per-phase snapshot assembly into model** (`tap_tone_analyzer_measurement_management.py`):
- Add a `_make_phase_snapshot(magnitudes, frequencies, min_freq, max_freq, min_db, max_db)` method to the model (private helper, mirrors Swift's local `makePhaseSnapshot` but lifted to model scope since the model owns the data).
- In `save_measurement()`, build `longitudinal_snapshot`, `cross_snapshot`, `flc_snapshot` from `self.longitudinal_spectrum`, `self.cross_spectrum`, `self.flc_spectrum` using `_make_phase_snapshot`.
- Remove `longitudinal_snapshot`, `cross_snapshot`, `flc_snapshot` from `save_measurement()`'s public parameter list (they are no longer passed from the view).
- Add `spectrum_snapshot: SpectrumSnapshot | None = None` optional override parameter to match Swift's signature.

**Step 3 — Rename and restructure view method** (`tap_tone_analysis_view.py`):
- Rename `_collect_measurement_params()` → `save_measurement(tap_location, notes)`.
- Remove all `SpectrumSnapshot` construction (the `_make_phase_snapshot` local helper and everything using it).
- The method now: reads axis range floats, reads mic/calibration identity, calls `analyzer.save_measurement(tap_location=..., notes=..., min_freq=..., max_freq=..., min_db=..., max_db=..., microphone_name=..., microphone_uid=..., calibration_name=..., selected_longitudinal_peak_id=..., selected_cross_peak_id=..., selected_flc_peak_id=...)` directly, then clears UI state (mirrors Swift's `tapLocation = ""; notes = ""; showingSaveSheet = false; isSavingMeasurement = false`).
- Update all callers of the old `_collect_measurement_params()` to call `save_measurement()` directly.

**Step 4 — Update model signature** (`tap_tone_analyzer_measurement_management.py`):
- Add `spectrum_snapshot: SpectrumSnapshot | None = None` parameter (optional override for import/testing path).
- Verify all other parameters match Swift's signature exactly.

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer.py` — Step 1: populate `longitudinal_spectrum`, `cross_spectrum`, `flc_spectrum` in capture completion paths
- `src/guitar_tap/models/tap_tone_analyzer_measurement_management.py` — Steps 2 & 4: add `_make_phase_snapshot`; build all snapshots in model; update signature
- `src/guitar_tap/views/tap_tone_analysis_view.py` — Step 3: rename `_collect_measurement_params` → `save_measurement`; remove snapshot construction; call model directly

**Note on axis range:** Swift's view passes `minFreq`/`maxFreq`/`minDB`/`maxDB` as explicit `@State` floats. Python view passes ViewBox Y-range floats. Both are genuine view state — this is correct and intentional.

**Risk:** Medium-High. Four coordinated changes across three files. Do steps in order: 1 → 2 → 3 → 4. Run tests after each step.

---

### WI-28 — Remove `_append_measurement`; wire import path through model's `import_measurements` (fixes D40)

**Divergence:** `_append_measurement` exists in Python but has no equivalent in Swift. Swift's `importMeasurements(from: Data)` decodes JSON and calls `savedMeasurements.append(contentsOf:)` + `persistMeasurements()` directly — there is no named helper. Python introduced `_append_measurement` as a shared private method used by both `save_measurement` and the view's import path. This is structural noise with no Swift counterpart.

Additionally, the view's import path (`measurements_list_view.py`) currently:
1. Calls `M.import_measurements_from_json(raw)` — a view-layer helper that decodes JSON outside the model
2. Loops over the decoded list calling `self._analyzer._append_measurement(item)` for each item

Swift's equivalent: the view calls `tap.importMeasurements(from: data)` on the model — one call, model owns decoding and appending.

The model already has `import_measurements(json_str: str) -> bool` and `import_measurements_from_data(data: bytes)` which decode and append correctly. The import path in the view should be calling one of these instead.

**Files:**
- `src/guitar_tap/models/tap_tone_analyzer_measurement_management.py` — remove `_append_measurement`; `save_measurement` calls `self.savedMeasurements.append()` + `self._persist_measurements()` directly
- `src/guitar_tap/views/measurements/measurements_list_view.py` — replace `M.import_measurements_from_json(raw)` + loop of `_append_measurement` with a single call to `self._analyzer.import_measurements(raw)`; update the returned list handling accordingly
- `src/guitar_tap/views/measurements/measurements_list_view.py` — verify `M.import_measurements_from_json` can be removed from the view if no longer needed

**Before implementing:** Read the full import block in `measurements_list_view.py` around line 428 to understand what the returned list is used for (auto-loading single measurement, microphone warning folding). The model's `import_measurements` returns `bool`; `import_measurements_from_data` returns the list — use the latter if the list is needed, or add a return value to `import_measurements`. Check Swift `importMeasurements(from:)` return value and how the caller uses it.

**Risk:** Low-Medium. Mechanical change with clear before/after. The import path logic (single-measurement auto-load, mic warning) stays in the view — only the decode+append moves to the model call.

---

### WI-29 — PDF export: use source measurement timestamp when viewing a loaded measurement (fixes D41)

**Divergence:** Swift's `exportPDFReport()` uses `tap.sourceMeasurementTimestamp ?? Date()` — when a saved measurement is loaded, the PDF is stamped with the original capture time; for a live capture it falls back to now. Python's `_on_export_pdf()` always uses `datetime.now()`, so a PDF exported from a loaded measurement shows the export time rather than the original capture time.

The data is available in Python: `self._loaded_measurement` holds the loaded `TapToneMeasurement` and its `.timestamp` attribute (an ISO-format string) is the original capture time.

**File:** `src/guitar_tap/views/tap_tone_analysis_view.py`

**Change:** In `_on_export_pdf()`, replace the `datetime.now(...)` call with:
```python
# mirrors Swift: tap.sourceMeasurementTimestamp ?? Date()
if self._loaded_measurement is not None:
    timestamp = datetime.fromisoformat(self._loaded_measurement.timestamp)
else:
    timestamp = datetime.now(timezone.utc)
```

**Before implementing:** Confirm the attribute name and type of the timestamp on `TapToneMeasurement` (it is an ISO string). Confirm `self._loaded_measurement` is `None` during a live capture and set during a loaded measurement view.

**Risk:** Low. Single-field change; no structural impact.

---

### WI-30 — PDF export: pass active calibration name (fixes D42)

**Divergence:** Swift's `exportPDFReport()` passes `calibrationName: fft.activeCalibration?.name` to `PDFReportData`. Python's `_on_export_pdf()` hardcodes `calibration_name=None`.

Python's `FFTCanvas` / `RealtimeFFTAnalyzer` may or may not expose the active calibration name through a property. This needs investigation.

**File:** `src/guitar_tap/views/tap_tone_analysis_view.py`

**Before implementing:** Read `realtime_fft_analyzer.py` (or equivalent) to find whether `active_calibration` or `active_calibration_name` is exposed. If it is, wire it to the `calibration_name` parameter in `_on_export_pdf()`. If it is not, add the property to the model first (mirrors Swift's `fft.activeCalibration`).

**Change:** Replace `calibration_name=None` with `calibration_name=getattr(self.fft_canvas.analyzer, "active_calibration_name", None)` (or the correct attribute path once confirmed).

**Risk:** Low-Medium. May require adding a property to the model if not already exposed.

---

### WI-31 — PDF export: use selected input device name, not calibration device name (fixes D43)

**Divergence:** Swift's `exportPDFReport()` passes `microphoneName: fft.selectedInputDevice?.name` — the currently selected audio input device. Python's `_on_export_pdf()` passes `microphone_name=getattr(analyzer, "_calibration_device_name", None)` — the device name stored during calibration, which may be stale or different from the currently selected device.

**File:** `src/guitar_tap/views/tap_tone_analysis_view.py`

**Before implementing:** Read `realtime_fft_analyzer.py` (or equivalent) to find the property that exposes the currently selected input device name — this is the Python equivalent of Swift's `fft.selectedInputDevice?.name`. It may be something like `analyzer.selected_device.name` or `analyzer.mic.name`.

**Change:** In `_on_export_pdf()`, replace `getattr(analyzer, "_calibration_device_name", None)` with the correct selected-device name property.

**Risk:** Low. Single-field change; no structural impact.

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

### WI-32 — Fix `_finish_capture` `selected_peak_ids` and `identified_modes` (fixes D44)

**Divergence:** Swift `processMultipleTaps()` sets both `selectedPeakIDs = guitarModeSelectedPeakIDs(from: peaksFromAveragedSpectrum)` (guitar-mode subset) and `identifiedModes = peaksFromAveragedSpectrum.map { (peak: $0, mode: captureModeMap[$0.id] ?? .unknown) }` after averaging. Python's `_finish_capture` set `selected_peak_ids = {p.id for p in peaks}` (all peaks — fixed the UUID-staleness bug but diverges from Swift's subset) and never set `identified_modes`, leaving it referencing old pre-capture peak objects with stale UUIDs.

**File:** `src/guitar_tap/models/tap_tone_analyzer_tap_detection.py`

**Changes:**

1. Replace `self.selected_peak_ids = {p.id for p in peaks}` with a call to `self.guitar_mode_selected_peak_ids(peaks)`, which mirrors Swift's `guitarModeSelectedPeakIDs(from: peaksFromAveragedSpectrum)`.

2. Add `identified_modes` assignment immediately after, using the same `GuitarMode.classify_all` + list-comprehension pattern used in `analyze_magnitudes` and `reclassify_peaks`:
   ```python
   from .guitar_mode import GuitarMode
   from .guitar_type import GuitarType
   guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
   mode_map = GuitarMode.classify_all(peaks, guitar_type)
   self.identified_modes = [
       {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)}
       for p in peaks
   ]
   # mirrors Swift: identifiedModes = peaksFromAveragedSpectrum.map { (peak: $0, mode: captureModeMap[$0.id] ?? .unknown) }
   ```

**Before implementing:** Confirm `guitar_mode_selected_peak_ids` in `tap_tone_analyzer_peak_analysis.py` accepts a `peaks` argument (it does — `peaks: list | None = None`). Confirm `GuitarMode.classify_all` is importable from `.guitar_mode` (it is — used identically in `reclassify_peaks`).

**Risk:** Low. The `guitar_mode_selected_peak_ids` call is a drop-in replacement for the set comprehension. The `identified_modes` assignment exactly mirrors the pattern already used in two other methods in the same class hierarchy.

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
| WI-20 | D32 | Documentation (intentional platform difference) | `plans/MODELS_STRUCTURAL_DIVERGENCE_AUDIT.md` (done); add a comment block in `tap_tone_analysis_view.py` near the menu bar setup describing how the Python menu structure intentionally differs from Swift's `AppCommands` layout |
| WI-21 | D33 | Content update — Python help | `help_view.py` `_build_help_html()`: add a Controls Reference sub-section describing the Python menu bar (File menu shortcuts, Help menu); note that toolbar layout descriptions are desktop-only (no mobile equivalent in Python); regenerate `docs/GuitarTap-Quick-Start-Guide.html/.pdf` after editing |
| WI-22 | D34 | Logic divergence — `guitarType` getter | `tap_display_settings.py` `guitar_type()`: Swift getter checks `measurementType` first (returns it if it is a guitar type) before reading the stored `guitarTypeKey`; Python getter delegates directly to `AppSettings.guitar_type()` without the `measurementType` fallback. |
| WI-23 | D35 | Logic divergence — `guitarType` setter | `tap_display_settings.py` `set_guitar_type()`: Swift setter also writes `measurementType = MeasurementType.from(newValue)`; Python setter only writes the guitar type key, leaving `measurementType` out of sync. |
| WI-24 | D36 | Missing inline defaults — dimension getters | `tap_display_settings.py`: Swift dimension getters (`plateLength`, `plateWidth`, `plateThickness`, `plateMass`, `braceLength`, `braceWidth`, `braceThickness`, `braceMass`, `guitarBodyLength`, `guitarBodyWidth`, `customPlateStiffness`) return hardcoded defaults when the stored value is 0; Python delegates entirely to `AppSettings` so the default values live outside `TapDisplaySettings`. |
| WI-25 | D37 | Missing convenience properties — `minFrequency`/`maxFrequency` static var | `tap_display_settings.py`: Swift exposes `static var minFrequency: Float` and `static var maxFrequency: Float` as computed properties that read/write using the current `measurementType` (Swift lines 429–438); Python has no direct equivalent (callers must pass `meas_type` explicitly). |
| WI-26 | D38 | `reset_to_defaults` resets legacy shared key, not per-type keys | `tap_display_settings.py` `reset_to_defaults()`: Swift resets `minFrequency`/`maxFrequency` via the `static var` setters which write to per-type keys (`displayMinFreq_<type>`); Python calls `s.set_f_min()`/`s.set_f_max()` which may write only to the legacy shared key, leaving per-type persisted values un-reset. |
| WI-27 | D39 | Refactor (model owns snapshot assembly) | `tap_tone_analyzer_measurement_management.py`, `tap_tone_analysis_view.py` |
| WI-28 | D40 | Refactor (remove `_append_measurement`; wire import path through model) | `tap_tone_analyzer_measurement_management.py`, `measurements_list_view.py` |
| WI-29 | D41 | Bug fix — PDF timestamp uses source measurement time, not export time | `tap_tone_analysis_view.py` |
| WI-30 | D42 | Gap — PDF export passes active calibration name | `tap_tone_analysis_view.py`, possibly `realtime_fft_analyzer.py` |
| WI-31 | D43 | Bug fix — PDF export uses selected device name, not calibration device name | `tap_tone_analysis_view.py` |
| WI-32 | D44 | Bug fix — `_finish_capture` sets `selected_peak_ids` to all peaks instead of guitar-mode subset; `identified_modes` not set | `tap_tone_analyzer_tap_detection.py` |
| WI-33 | D45 | Architectural fix — `canvas.start_analyzer()` bypassed `start_tap_sequence()` and poked model state directly from the view layer | `tap_tone_analyzer_control.py`, `fft_canvas.py` |
| WI-34 | — | Bug — `RecursionError: maximum recursion depth exceeded` in `_on_cal_selected` → `CalibrationStorage.set_calibration_for_device` → `_load_device_map` → `cls._s()` → `from PySide6 import QtCore` | `microphone_calibration.py`, `tap_tone_analysis_view.py` |

**D47** — `FFTAnalysisMetricsView` / `fft_analysis_metrics_view.py`: Swift's view reads `analyzer.actualSampleRate`, `analyzer.frequencyResolution`, `analyzer.bandwidth`, and `analyzer.sampleLengthSeconds` — all `@Published` properties on `RealtimeFFTAnalyzer` that are updated on every FFT frame (`RealtimeFFTAnalyzer+FFTProcessing.swift` lines 77–79, 175). Python's `_build_ui()` computes `sr`, `spectral_res`, `bandwidth`, and `sample_len` once at dialog construction time from `self._canvas.analyzer.mic.rate` and `self._canvas.analyzer.mic.fft_size`. The static values are correct at dialog-open time, but will not update if the device changes while the panel is open. The corresponding `@Published` properties (`actualSampleRate`, `frequencyResolution`, `bandwidth`, `sampleLengthSeconds`) are listed as "Swift-only" in `realtime_fft_analyzer.py`'s docstring (line 442). Disposition: **Document** — static snapshot at dialog-open is acceptable for a diagnostics panel; the cost of adding reactive `@Published`-equivalent signals for these four derived values to `RealtimeFFTAnalyzer` is not justified. Record here that this is a known, accepted structural difference. No code change required; the `realtime_fft_analyzer.py` "Swift-only properties" comment already documents it.

**All 46 divergences are addressed (D47 accepted as documented).** 8 bugs/races fixed (D1, D2, D3/D4/D5, D6, D12, D23, D31, D44). 3 new behaviours (D26, D30). 3 add missing methods/properties (D19, D20). 4 refactors (D9, D10, D13, D27). 2 documentation/content updates (D32, D33). The remainder are documentation. D34–D38 added post-audit during WI-6 verification. D39–D43 added during WI-13 code review. D44 added during WI-13 verification. D45 added and resolved during WI-14 verification.

---

## Implementation order

- [x] 1. **WI-1** (settings persistence bugs) — highest correctness impact, lowest risk
- [x] 2. **WI-12** (`set_frozen_spectrum` helper) — low risk, closes a real race condition
- [x] 3. **WI-2** (`effectiveXxxPeakID` middle layer) — read Swift before editing
- [x] 4. **WI-7** (`MaterialTapPhase` convenience properties) — NO-OP: D20 was audit false positive; Swift never had these properties
- [x] 5. **WI-6** (`TapDisplaySettings` helpers) — fixed D18 setter bug (`set_tap_detection_threshold` and `reset_to_defaults` now convert dBFS → 0-100 scale correctly); D19 helpers already present
- [x] 6. **WI-10** (`QTimer.singleShot` refactor) — replaced 7 `threading.Timer`+`invokeMethod` pairs across 3 files; removed `import threading` from all 3; 290 tests green
- [x] 7. **WI-13** (model owns measurement assembly) — read `_collect_measurement()` and `TapToneMeasurement.create()` in full before editing; update import path explicitly
- [x] 7a. **WI-32** (`_finish_capture` `selected_peak_ids` + `identified_modes`) — discovered during WI-13 manual verification; `selected_peak_ids` now set via `guitar_mode_selected_peak_ids(peaks)` matching Swift; `identified_modes` now set from `GuitarMode.classify_all` result
- [x] 8. **WI-27** (all snapshot assembly in model; fix naming) — four steps in order: (1) populate `analyzer.longitudinal_spectrum/cross_spectrum/flc_spectrum` in capture completion paths; (2) add `_make_phase_snapshot` to model, build all snapshots in `save_measurement()`; (3) rename view `_collect_measurement_params` → `save_measurement`, remove all snapshot construction, call model directly; (4) add `spectrum_snapshot` optional override to model signature. Run tests after each step.
- [x] 9. **WI-28** (remove `_append_measurement`; wire import path through model) — `_append_measurement` removed; `save_measurement` now inlines `self.savedMeasurements.append(measurement)` + `self._persist_measurements()`. View `_on_import` now calls `self._analyzer.import_measurements_from_data(data)` directly (bytes, not string). Two post-implementation divergences found and fixed: (1) single-object JSON guard `if isinstance(raw, dict): raw = [raw]` removed — Swift always expects a JSON array; (2) microphone warning check added to `import_measurements_from_data` mirroring Swift's `importMeasurements(from:)` (checks UID then name against `self.mic.available_input_devices`; sets `self.microphone_warning`). `self.microphone_warning: str | None = None` added to `TapToneAnalyzer.__init__`. 301 tests green.
- [x] 10. **WI-29** (PDF timestamp — use source measurement timestamp) — `date_label` in `_on_export_pdf()` now uses `datetime.fromisoformat(self._loaded_measurement.timestamp)` when a measurement is loaded, falling back to `datetime.now(utc)` for live captures. 301 tests green.
- [x] 11. **WI-31** (PDF microphone name — use selected device, not calibration device) — `_on_export_pdf()` now reads `analyzer.mic.selected_input_device.name` (via `getattr` chain) instead of `analyzer._calibration_device_name`. Also fixed the same bug in view `save_measurement()` (the `mic_name` used when saving). 301 tests green.
- [x] 12. **WI-30** (PDF calibration name — pass active calibration name) — Initial fix used `MicrophoneCalibration.active_calibration()` (global active profile), but this missed device-specific auto-loaded calibrations. Bug found during verification: UMIK-1 calibration auto-loaded on device switch showed as "uncalibrated" in PDF. Root cause: `load_calibration_from_profile` consumed the `MicrophoneCalibration` object and discarded it — only the numpy array was kept. Fix: added `self._active_calibration_name: str | None = None` to `TapToneAnalyzer.__init__`; set it in `load_calibration_from_profile` and cleared in `clear_calibration`. `_on_export_pdf()` now reads `analyzer._active_calibration_name` directly. Second sub-bug: `calibration_name` was not passed to `analyzer.save_measurement()` in the view's `save_measurement()`, so saved measurements always had `calibration_name=None`. Fixed by adding `cal_name = getattr(analyzer, "_active_calibration_name", None)` and passing `calibration_name=cal_name` to the model call — mirrors Swift `saveMeasurement(calibrationName: fft.activeCalibration?.name)`. 301 tests green.
- [x] 13. **WI-14** (model owns measurement load) — Added `load_measurement(measurement)` to `TapToneAnalyzerMeasurementManagementMixin` in `tap_tone_analyzer_measurement_management.py`. The method sets all model state: clears comparison, sets FROZEN display mode, restores `current_peaks`, `current_decay_time`, per-phase spectra (`longitudinal_spectrum`/`cross_spectrum`/`flc_spectrum`), `frozen_frequencies`/`frozen_magnitudes` (via `set_frozen_spectrum`), `material_tap_phase = COMPLETE` for plate/brace, `selected_longitudinal_peak`/`selected_cross_peak`/`selected_flc_peak`, `user_selected_*_peak_id = None`, `reclassify_peaks()`, `peak_annotation_offsets`, `loaded_measurement_peaks`, `selected_peak_ids` + `selected_peak_frequencies`, `user_has_modified_peak_selection = True`, `annotation_visibility_mode`, `peak_mode_overrides` (via `apply_mode_overrides`), analysis settings (`tap_detection_threshold`, `hysteresis_margin`, `number_of_taps`, `peak_threshold`), detection flags (`is_detecting = False`, `is_detection_paused = False`, `current_tap_count = 0`), and AppSettings (the Python equivalent of Swift's `loaded*` @Published + `.onReceive` → TapDisplaySettings writes). Emits `measurementComplete(True)` and sets status message. Uses `is_loading_measurement` guard (mirrors Swift `isLoadingMeasurement = true / defer { = false }`). View `_restore_measurement()` thinned to: clear stale tap count, call `analyzer.load_measurement(m)`, then handle all Qt widget updates, canvas drawing, peak_model updates, mic auto-select, ring-out widget, and loaded-settings warning UI. AppSettings dimension writes removed from view (now done by model). Analysis settings slider/spinner `.setValue()` calls now read back from `analyzer.*` attrs set by `load_measurement()` — mirrors Swift `.onReceive` on `loaded*` properties. 301 tests green.
- [x] 13a. **WI-33** (D45 — `canvas.start_analyzer()` bypassed model) — discovered during WI-14 verification. `start_tap_sequence()` now sets `is_measurement_complete = False` and emits `measurementComplete(False)` internally (mirrors Swift's `isMeasurementComplete = false` inside `startTapSequence()`). `canvas.start_analyzer()` now calls `analyzer.start_tap_sequence()` instead of `analyzer.set_measurement_complete(False)` + manual `captured_taps.clear()`. Canvas is now responsible only for thread lifecycle and UI overlay.
- [x] 14. **WI-15** (`average_spectra` move + wire callers) — `_average_captured_taps()` was already present in `tap_tone_analyzer_spectrum_capture.py` and wired to all three gated handlers and `process_multiple_taps`; the only remaining action was deleting the dead `average_spectra` method from `tap_tone_analyzer_peak_analysis.py`
- [x] 15. **WI-11** (`FftParameters` elimination) — `fft_parameters.py` deleted; `FftParameters` import removed from `fft_canvas.py`, `tap_tone_analyzer.py`, and `models/__init__.py`. `TapToneAnalyzer.start()` now takes `sample_rate` and `fft_size` directly; `RealtimeFFTAnalyzer` owns these values. Freq axis computed as `x_axis * mic.rate / mic.fft_size` (matches Swift `updateFrequencyBins`: `i * rate / fftSize`). `n_fmin`/`n_fmax` read `self.mic.fft_size` and `self.mic.rate` directly — but `find_peaks` uses `firstIndex`-style freq-array search (matching Swift), so these properties are effectively unused. Device-switch `fft_data.sample_freq` sync removed from `set_device()` (redundant: `n_fmin`/`n_fmax` now read `mic.rate` live). 314 tests green.
- [x] 16. **WI-18** (`_gated_sample_rate` / `_pre_roll_samples` → computed properties) — both fields replaced with `@property` computed from `self.mic.rate`, matching Swift's `preRollSamples` and `gatedCaptureSamples` computed vars. Stored fields and all initialisation/assignment sites removed (`__init__`, `start()`, `set_device()`). No cache-invalidation needed on device switch — the live `mic.rate` value is always correct. 314 tests green.
- [x] 17. **WI-16** (`PlateStiffnessPreset.value` → `stiffness` rename) — `stiffness` property added returning the float; Python `Enum.value` now naturally returns the human-readable label string (e.g. `"Classical Top"`). Two numeric call sites updated to `.stiffness`; display call site at `tap_tone_analysis_view.py:2978` now produces `"f_vs = 60 (Classical Top)"` matching Swift. Empty FFT Processing group box also removed from Python Advanced settings (was left as a shell after hop-size removal).
- [ ] 18. **WI-17** (auto-device-switch on plug-in) — read `_notify_devices_changed()` and `_on_devices_refreshed()` first; medium risk
- [x] 19. **WI-22** (`guitarType` getter — add `measurementType` fallback) — `TapDisplaySettings.guitar_type()` now checks `mt.guitar_type` (from `measurement_type()`) first; falls back to stored `guitarTypeKey` only if `measurementType` has no associated guitar type. Returns `GuitarType` enum directly (not a raw string). All 7+ `self._guitar_type` read sites in the model now call `TapDisplaySettings.guitar_type()`.
- [x] 20. **WI-23** (`guitarType` setter — also set `measurementType`) — `TapDisplaySettings.set_guitar_type()` now writes both `guitarTypeKey` and `measurementType = MeasurementType.from_guitar_type(gt)` atomically. Accepts `str | GuitarType`; normalises strings to `GuitarType` enum before writing.
- [ ] 21. **WI-24** (dimension getter inline defaults) — low risk; add fallback defaults matching Swift's hardcoded values to each dimension getter in `TapDisplaySettings`
- [ ] 22. **WI-25** (`minFrequency`/`maxFrequency` convenience properties) — add `static`-equivalent no-arg accessors that use the current `measurement_type()`
- [ ] 23. **WI-26** (`reset_to_defaults` per-type frequency keys) — verify what `AppSettings.set_f_min()` actually writes; fix to write per-type keys to match Swift
- [ ] 24. **WI-3, WI-4, WI-5, WI-8, WI-9** — documentation passes; can be done in any order
- [ ] 25. **WI-19** (platform-native rate-change listeners) — do after WI-17/WI-18 since all three touch the device management monitor; confirm Linux mechanism before implementing that platform; macOS and Windows can proceed independently
- [ ] 26. **WI-20** (menu bar comment) — one-time documentation; no code logic changes; can be done any time
- [ ] 27. **WI-21** (Python help content update) — read `help_view.py` `_build_help_html()` in full before editing; add menu bar section mirroring the macOS-only rows added to `HelpView.swift`; regenerate docs after
- [x] 28. **WI-34** (`CalibrationStorage._s()` RecursionError) — hoist `from PySide6 import QtCore` to module level in `microphone_calibration.py` and remove the deferred in-method import from `_s()`; this prevents shiboken's import machinery from recursing when `_s()` is called during a PySide6 signal dispatch
- [ ] 29. **WI-35** (D46 — `measurementType` multiple sources of truth) — **Deferred**. Replace `self.measurement_type_combo` / `self.guitar_type_combo` as the interaction surface in `tap_tone_analysis_view.py` with direct reads/writes to `TapDisplaySettings`, mirroring Swift's single-source pattern. All code that currently calls `self._current_mt()` or reads from `self.measurement_type_combo.currentText()` should instead call `TapDisplaySettings.measurement_type()`. The combo widgets can be retained as display-only UI elements but must no longer be the authoritative state store. This is a significant refactor of `tap_tone_analysis_view.py`; read the entire file before starting. **Prerequisite**: no other open regressions.

---

## Verification

After implementation:

- [x] 1. **WI-1:** Start Python app, change threshold/hysteresis/annotation settings, quit, relaunch — verify settings are restored from QSettings.
- [x] 2. **WI-2:** In plate measurement mode, capture a longitudinal tap (sets `selected_longitudinal_peak`), then check `effective_longitudinal_peak_id` returns that peak's id when no user override is set.
- [x] 3. **WI-6:** 20 unit tests in `test_wi6_tap_display_settings.py` verify round-trip correctness of `tap_detection_threshold`, `validate_frequency_range`, `validate_magnitude_range`, and `reset_to_defaults`.
- [x] 4. **WI-7:** NO-OP — D20 was audit false positive; no verification needed.
- [x] 5. **WI-10:** Verify each deferred callback fires on the main thread; run tap detection sequence end-to-end. 11 tests in `test_wi10_qtimer_slots.py` cover: QTimer.singleShot main-thread delivery (via processEvents), all 6 timer-fired slots (_do_reenable_detection, _do_reenable_guitar, _finish_capture, _do_start_cross, _do_start_flc), and the QTimer-based decay tracking timer (create, cancel, stop, signal-fired stop). 301 tests green.
- [x] 6. **WI-11:** Verified `FftParameters` is no longer imported anywhere (only stale `.pyc` and `SOURCES.txt`); `fft_parameters.py` confirmed deleted; FFT capture sequence verified end-to-end by user.
- [x] 7. **WI-13:** Save a measurement from the UI — verify it is persisted correctly. Import a measurement from file — verify `_append_measurement` path works. Export a PDF report — verify it generates correctly with peaks, spectrum image, and metadata (tap location, notes, decay time). Confirm `_collect_measurement()` is no longer present in the view. Model `save_measurement(...)` accepts individual parameters and constructs `TapToneMeasurement` internally. `_append_measurement` used by import path. `_on_export_pdf` now builds `PDFReportData` directly from live analyzer state (no `TapToneMeasurement` intermediary), mirroring Swift `exportPDFReport()`. All bugs found during WI-13 manual verification fixed (annotation signal arity, UUID staleness in `_finish_capture`, annotation mode mismatch after tap). D44 identified during verification → WI-32.
- [x] 7a. **WI-32:** `_finish_capture` sets `selected_peak_ids` via `guitar_mode_selected_peak_ids(peaks)` (matches Swift's `guitarModeSelectedPeakIDs`); sets `identified_modes` from `GuitarMode.classify_all` result (matches Swift's `identifiedModes` assignment). Tests green.
- [x] 8. **WI-27:** Code checks (a–f done): (a) `analyzer.longitudinal_spectrum`, `cross_spectrum`, `flc_spectrum` set in spectrum capture (`tap_tone_analyzer_spectrum_capture.py` lines 606, 703, 761). (b) Guitar snapshot built in model from `frozen_frequencies`/`frozen_magnitudes`. (c) Per-phase snapshots built in model from `self.longitudinal_spectrum` etc. via `_make_phase_snapshot` (`tap_tone_analyzer_measurement_management.py` line 101). (d) No `SpectrumSnapshot` construction in the view. (e) View method named `save_measurement` (line 2967 of `tap_tone_analysis_view.py`), calls `analyzer.save_measurement(...)` directly, no dict return. (f) Model signature has `spectrum_snapshot=None` override (line 155). Runtime verification: (g) ✓ User verified plate measurement save→reload shows all three phase spectra (fixed two bugs this session: `measurement_type` not passed to `TapToneMeasurement.create()`, and phase spectra not restored on load). (h) ✓ User verified guitar measurement round-trip works correctly. (i) ✓ User verified PDF export from saved plate measurement.
- [x] 9. **WI-28:** Import a measurement from file — verify the model's `import_measurements_from_data` is called directly; confirm `_append_measurement` no longer exists in the model; confirm `M.import_measurements_from_json` is no longer called from `measurements_list_view.py`. Also verify: if the imported measurement was recorded with a microphone not currently connected, a `microphone_warning` string is set on the analyzer (view can read and display it). ✓ User verified: guitar measurement imported, mic warning displayed correctly.
- [x] 10. **WI-29:** Export a PDF from a loaded measurement — verify the PDF timestamp matches the original capture time, not the export time. Export a PDF from a live (unsaved) capture — verify the PDF timestamp is approximately now. ✓ User verified: loaded measurement PDF shows original capture time in local timezone; live capture PDF shows current time.
- [x] 11. **WI-31:** Export a PDF — verify `microphone_name` in the report matches the currently selected input device (not the calibration device name). ✓ User verified.
- [x] 12. **WI-30:** Export a PDF with an active calibration loaded — verify `calibration_name` appears in the report. Export without calibration — verify it is absent (None). ✓ User verified.
- [x] 13. **WI-14:** Load a saved measurement from the measurements list — verify all peaks, spectrum, decay time, and settings restore correctly. Confirm `_restore_measurement()` in the view contains only widget updates; all analyzer-state mutations are in `load_measurement()` on the model. ✓ User verified. Also fixed: status message now displays in orange when frozen (signal ordering fix in `set_measurement_complete`); phase/tap count labels now hidden when frozen (mirrors Swift's `isDetecting`-gated visibility).
- [x] 13a. **WI-33:** After loading a measurement, press New Tap — verify the spectrum unfreezes and the app enters live detection mode (i.e. `start_tap_sequence()` correctly sets `is_measurement_complete = False` and emits `measurementComplete(False)`). Confirm no direct model-state manipulation remains in `canvas.start_analyzer()` — it should call `analyzer.start_tap_sequence()` and then manage only the thread and UI overlay. ✓ User verified.
- [x] 14. **WI-15:** Capture a multi-tap measurement — verify the averaged spectrum is used (not just the last tap). Confirm `average_spectra` no longer exists in `tap_tone_analyzer_peak_analysis.py`. ✓ Automated: MC2 (`processMultipleTaps_populatesFrozenSpectrum`) and MC3 (`processMultipleTaps_multiTap_setsIsMeasurementComplete`) confirm the averaged spectrum is populated after multi-tap capture. `grep` confirms `average_spectra` is absent from `tap_tone_analyzer_peak_analysis.py`.
- [x] 15. **WI-16:** Verify `PlateStiffnessPreset.STEEL_STRING_TOP.value == "Steel String Top"` (standard Enum.value). Verify `PlateStiffnessPreset.STEEL_STRING_TOP.stiffness == 75.0`. Verify the f_vs label in the UI reads `"f_vs = 75 (Steel String Top)"` not `"f_vs = 75 (75.0)"`. ✓ User verified. (Also fixed missed call site in `TapDisplaySettings.plate_stiffness()` which still used `.value` and caused Gore target thickness to disappear after load.)
- [ ] 16. **WI-17:** Plug in a new microphone while the Python app is running — verify it auto-switches without user interaction. Unplug a device — verify the app does not crash and does not attempt to auto-switch.
- [x] 17. **WI-18:** Switch to a 48 kHz device after starting on a 44.1 kHz device; immediately perform a plate tap measurement — verify the gated capture window is sized correctly for 48 kHz (not 44.1 kHz). ✓ User verified: UMIK-1 (48 kHz) produces `19200-sample window (400 ms at 48000 Hz)` for both CAPTURING_LONGITUDINAL and CAPTURING_CROSS phases. Computed properties `_gated_sample_rate` and `_pre_roll_samples` read live `mic.rate` correctly after device switch.
- [x] 17a. **WI-22:** Code-verified: `guitar_type()` reads `mt.guitar_type` first (returns enum directly for guitar measurement types); falls back to stored `guitarTypeKey` when `mt.guitar_type is None` (e.g. SPRUCE_TOP). The fallback path is exercised whenever a plate measurement is loaded, which was covered during WI-14 verification. Runtime: no `self._guitar_type` attribute reads remain in model mixin files.
- [x] 17b. **WI-23:** Unit-verify `TapDisplaySettings.set_guitar_type("Classical")` writes both `guitarTypeKey = "Classical"` and `measurementType = MeasurementType.CLASSICAL`. Verify passing a `GuitarType` enum value directly also writes both keys. Runtime: load the Contreras classical guitar measurement from the saved `.guitartap` file — verify Analysis Results shows "Top" and "Back" peaks correctly (not two "Back" peaks as before this fix). Switching guitar type in the UI selector — verify `reclassify_peaks()` uses the newly-selected type immediately.
- [ ] 18. **Run existing tests:** `pytest` from the Python project root — no regressions.
- [ ] 19. **Build Swift project:** `BuildProject` MCP command — ensure no Swift changes needed.
- [ ] 20. **WI-20:** Open `tap_tone_analysis_view.py`, locate the menu bar setup, confirm the comment block is present and accurately describes the differences from Swift's `AppCommands`.
- [ ] 21. **WI-21:** Launch the Python app, open Help > Guitar Tap Help — verify the Controls Reference section contains a menu bar sub-section with correct shortcut descriptions. Open `docs/GuitarTap-Quick-Start-Guide.html` and verify the same section appears.
- [x] 22. **WI-34:** Open the Settings panel and select a calibration profile for the current device — verify no `RecursionError` is raised. Root causes (two, both fixed): (1) `CalibrationStorage._s()` had a deferred `from PySide6 import QtCore` inside the method body — hoisted to module level. (2) `_update_cal_display()` in the Settings panel called `cal_combo.setCurrentIndex()` without blocking signals during initial panel construction; when a calibration was already active this fired `_on_cal_selected` inside PySide6's widget init stack, causing numpy's lazy submodule load (`np.iscomplexobj` via `np.interp`) to re-enter shiboken's `feature_import` and exceed the recursion limit. Fixed by wrapping the `setCurrentIndex` calls in `_update_cal_display()` with `blockSignals(True/False)`. ✓ User verified: Settings panel opens without crash with an active calibration.
- [ ] 23. **WI-35:** Start the app — confirm `TapDisplaySettings.measurement_type()` returns the correct type without any combo-box interaction. Open Settings, change the measurement type, Apply — confirm `TapDisplaySettings.measurement_type()` reflects the new value immediately. Restart the app — confirm the type persists correctly. Perform a tap in guitar mode and in plate mode — confirm routing goes to the correct pipeline in both cases. Grep for `self.measurement_type_combo.currentText()` and `self._current_mt()` in `tap_tone_analysis_view.py` — confirm no remaining call sites outside the display-update path.
