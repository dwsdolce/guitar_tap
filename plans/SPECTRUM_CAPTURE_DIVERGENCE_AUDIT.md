# Comparison: TapToneAnalyzer+SpectrumCapture — Swift vs Python

**Swift source:** `GuitarTap/GuitarTap/Models/TapToneAnalyzer+SpectrumCapture.swift`
**Python source:** `src/guitar_tap/models/tap_tone_analyzer_spectrum_capture.py`
**Date:** 2026-04-29

These files are supposed to be structurally, algorithmically, by signature/naming, and functionally
identical — the Python file is a port of the Swift original.

---

## 1. Function/Method Inventory

Both files contain the same 12 core functions in the same order. Python adds 8 extra functions with
no Swift equivalents in this file:

| Python-only method | Reason |
|---|---|
| `_set_material_tap_phase(phase)` | Swift uses `@Published` property directly |
| `_on_safety_timeout_no_samples()` | Qt slot wrapping an inline Swift closure |
| `_do_start_flc()` | Equivalent logic is in a different Swift file |
| `start_plate_analysis()` | Thin wrapper; Swift equivalent is elsewhere |
| `reset_plate_analysis()` | Same |
| `process_averages(mag_y)` | Swift equivalent is in the main class, not this extension |
| `_emit_peaks_array(peaks)` | Qt needs explicit emission; Swift uses `@Published` |
| `finish_capture()` | Exists but is a no-op `pass`; Swift invalidates a timer |

No Swift functions are missing from Python.

### Matched function pairs

| Swift | Python |
|---|---|
| `accumulateGatedSamples(_:sampleRate:)` | `_accumulate_gated_samples(chunk, sample_rate)` |
| `startGatedCapture(phase:)` | `start_gated_capture(phase)` |
| `finishGatedFFTCapture(samples:sampleRate:phase:)` | `finish_gated_fft_capture(samples, sample_rate, phase)` |
| `findDominantPeak(magnitudes:frequencies:minHz:maxHz:preferLowestSignificant:)` | `find_dominant_peak(magnitudes, frequencies, min_hz, max_hz, prefer_lowest_significant)` |
| `handleLongitudinalGatedProgress(magnitudes:frequencies:dominantPeak:)` | `_handle_longitudinal_gated_progress(magnitudes, frequencies, dominant_peak)` |
| `resolvedPlatePeaks(includeCross:crossOverride:includeFlc:flcOverride:)` | `_resolved_plate_peaks(include_cross, cross_override, include_flc, flc_override)` |
| `handleCrossGatedProgress(magnitudes:frequencies:dominantPeak:)` | `_handle_cross_gated_progress(magnitudes, frequencies, dominant_peak)` |
| `handleFlcGatedProgress(magnitudes:frequencies:dominantPeak:)` | `_handle_flc_gated_progress(magnitudes, frequencies, dominant_peak)` |
| `buildAllPeaks(magnitudes:frequencies:dominantPeak:)` | `_build_all_peaks(magnitudes, frequencies, dominant_peak)` |
| `finishCapture()` | `finish_capture()` |
| `averageSpectra(from:)` | `average_spectra(from_taps)` |
| `processMultipleTaps()` | `process_multiple_taps()` |

---

## 2. Algorithmic Differences

### `accumulateGatedSamples` / `_accumulate_gated_samples`

**Difference 1 — Lock discipline and count-check placement:**
Swift unlocks the mutex immediately after appending to `gatedAccumBuffer`, then checks
`count >= gatedCaptureSamples` *outside* the lock (Swift line ~114–116). Python holds the lock
for the entire check-and-clear sequence. This is a threading model difference; Swift deliberately
unlocks early to avoid holding the lock during the dispatch call.

**Difference 2 — Where `gatedCaptureActive = false` is set:**
Swift sets it *outside* the lock after the count check. Python sets `self._gated_capture_active = False`
*inside* the `with self._gated_lock:` block. Python is stricter about atomicity.

**Difference 3 — `mpmSampleRate` update missing in Python:**
Swift sets `mpmSampleRate = sampleRate` at the very top of the function on every call, maintaining
a current snapshot of the hardware rate. Python derives the rate on demand via the `_gated_sample_rate`
property and does not persist a per-call value. Python cannot access the most recent sample rate
without reading from the mic object.

**Difference 4 — Pre-roll trimming:**
Swift: `preRollBuffer.removeFirst(preRollBuffer.count - maxPreRoll)` — mutates in place.
Python: `self._pre_roll_buf = self._pre_roll_buf[-self._pre_roll_samples:]` — creates a new list via
slice. Functionally equivalent.

**Difference 5 — Dispatch mechanism:**
Swift uses `DispatchQueue.main.async { [weak self] in … }` (inline closure). Python emits a Qt signal
(`gatedCaptureComplete`) delivered via a queued connection to the main thread. The logical outcome is
the same, but Python requires an additional hop through the processing thread's signal.

---

### `startGatedCapture` / `start_gated_capture`

**Difference 1 — Log placement:**
Swift logs *after* arming `gatedCaptureActive = true`. Python logs *before* acquiring the lock
and arming. Minor but observable ordering difference.

**Difference 2 — Missing mic guard in Swift:**
Python adds an explicit early-return guard at line 190 (`if self.mic is None`). Swift has no
equivalent guard.

**Difference 3 — Safety timeout dispatch:**
Swift's timeout closure calls `self.statusMessage` and `self.reEnableDetectionForNextPlateTap()`
directly (single synchronous inline call). Python schedules a second
`QTimer.singleShot(0, self._on_safety_timeout_no_samples)` — two async hops instead of one.

**Difference 4 — `gatedCaptureSamples` computation:**
Swift reads a pre-computed `gatedCaptureSamples` property. Python computes
`target_samples = int(rate * self.GATED_CAPTURE_DURATION)` inline and stores it in
`self._gated_capture_samples`. Functionally equivalent.

---

### `finishGatedFFTCapture` / `finish_gated_fft_capture`

**CRITICAL — Plate longitudinal frequency search window (documentation vs code):**
The Swift doc comment states the plate longitudinal range is 50–500 Hz, but the actual Swift code
uses 20–100 Hz. Python matches the Swift *code* (20–100 Hz), not the doc comment. Both are correct;
the Swift doc comment is wrong.

**Difference 1 — `tapCountChanged` signal:**
Python emits `self.tapCountChanged.emit(_cumulative, self.number_of_taps)` after incrementing
`current_tap_count`. Swift increments `currentTapCount` and updates `tapProgress` but emits no
tap-count signal at this point in the function.

**Difference 2 — `captured_taps` tuple — positional vs named fields:**
Swift: `materialCapturedTaps.append((magnitudes: magnitudes, frequencies: frequencies, captureTime: Date()))` — named fields.
Python: `self.captured_taps.append((magnitudes, frequencies, _dt.datetime.now()))` — positional tuple.

**Difference 3 — `current_tap_count` derivation:**
Swift: `currentTapCount += 1` (increment).
Python: `self.current_tap_count = len(self.captured_taps)` (re-derivation). Same value.

**Difference 4 — Division-by-zero guard:**
Python: `min(1.0, float(self.current_tap_count) / max(total, 1))` — guards against zero.
Swift: `min(1.0, Float(currentTapCount) / Float(totalPlateTaps))` — no guard.

---

### `findDominantPeak` / `find_dominant_peak`

**Difference 1 — `Candidate` struct vs tuple:**
Swift defines a local `struct Candidate` with named fields `.index`, `.magnitude`, `.hpsScore`,
`.qFactor`. Python uses a plain 4-tuple `(index, mag, hps_score, q)` accessed by position
(`c[0]`, `c[1]`, etc.). Less readable and type-safe.

**Difference 2 — Pitch calculator guard:**
Swift calls `pitchCalculator.note(frequency:)` unconditionally (non-optional property).
Python guards with `if hasattr(self, "pitch_calculator") and self.pitch_calculator is not None`
and wraps in `try/except Exception: pass`. Defensive check not present in Swift.

**Difference 3 — Local maximum boundary check:**
Python adds an explicit `if 0 <= j < n` bounds check not present in Swift (Swift's loop bounds
make it unnecessary). Defensive addition.

---

### `handleLongitudinalGatedProgress` / `_handle_longitudinal_gated_progress`

**CRITICAL Difference 1 — Brace path extra emissions:**
Python explicitly emits in the brace path (no Swift equivalents in this function):
- `self._emit_peaks_array(self.current_peaks)` → emits `peaksChanged`
- `self.set_material_spectra([...])` → emits `materialSpectraChanged`
- `self.spectrumUpdated.emit(...)` at the end of the function
- `self.plateAnalysisComplete.emit(dominant_peak.frequency, 0.0, 0.0)`

Swift derives the first two from `@Published` properties automatically. The
`plateAnalysisComplete` emission has no Swift equivalent in this function.

**CRITICAL Difference 2 — Plate path extra emissions:**
Python explicitly calls:
- `self._emit_peaks_array(self.current_peaks)`
- `self._set_material_tap_phase(_MTP.REVIEWING_LONGITUDINAL)`
- `self.set_material_spectra([...])`
- `self.spectrumUpdated.emit(...)`

Swift has none of these explicit calls — `materialSpectra` is a computed `@Published` property
that auto-derives from `longitudinalSpectrum`.

**Difference 3 — `selected_peak_frequencies` pre-set:**
Python line ~629: `self.selected_peak_frequencies = [dominant_peak.frequency]` — explicitly set
before clearing `captured_taps`. No equivalent in Swift's `handleLongitudinalGatedProgress`.

**Difference 4 — `isMeasurementComplete` setter location:**
Swift's `isMeasurementComplete = true` triggers a `didSet` observer (defined elsewhere) that
clears `showLoadedSettingsWarning`. Python replicates this inline because Python has no property
observers. Logic is equivalent, location differs.

---

### `handleCrossGatedProgress` / `_handle_cross_gated_progress`

**Difference 1 — `set_material_spectra` call:**
Python explicitly calls `self.set_material_spectra(spectra)` to show L + C overlays.
Swift derives this from `@Published crossSpectrum`. No explicit call in Swift.

---

### `handleFlcGatedProgress` / `_handle_flc_gated_progress`

**Difference 1 — `set_material_spectra` call:**
Same pattern as cross handler. Python calls `self.set_material_spectra(spectra)` for L + C + FLC.
Swift derives from `@Published`.

**Difference 2 — Missing terminal debug log:**
Swift line ~662: `gtLog("📊 FLC review: L=\(...) C=\(...) FLC=\(...) Hz")`
Python has no equivalent log at the end of `_handle_flc_gated_progress`.

---

### `buildAllPeaks` / `_build_all_peaks`

No algorithmic differences. Both compute the median noise threshold, call `findPeaks`, then
replace or prepend `dominantPeak` if within proximity. The proximity constant name differs:
Swift uses `TapToneAnalyzer.peakProximityHz`; Python uses `self.PEAK_PROXIMITY_HZ`. Same value.

---

### `averageSpectra` / `average_spectra`

**Difference 1 — log10 floor guard:**
Python: `10.0 * math.log10(max(power_sum[b] / n_taps, 1e-30))` — prevents `log10(0)` → `-inf`.
Swift: `10.0 * log10(averageLinear)` — no floor guard. Swift can produce `-inf` in degenerate inputs.
Python is more robust here.

---

### `processMultipleTaps` / `process_multiple_taps` ⚠️ Most Divergent Function

**CRITICAL Difference 1 — Extra `tapDetectedSignal` emission:**
Python emits `self.tapDetectedSignal.emit()` at the very end of `process_multiple_taps`
(Python line ~1077). Swift's `processMultipleTaps` has **no equivalent emission**. This is an
extra signal with potential knock-on effects in the Python UI.

**CRITICAL Difference 2 — `selectedPeakFrequencies` behaviour inverted:**
Swift resets: `selectedPeakFrequencies = []` (line ~820) — clears the cache.
Python populates: `self.selected_peak_frequencies = [p.frequency for p in peaks if p.id in self.selected_peak_ids]`
Python's approach is functionally better (values immediately available) but diverges from Swift.

**CRITICAL Difference 3 — Mode classification order:**
Swift classifies modes *after* setting `selectedPeakIDs` and `userHasModifiedPeakSelection`.
Python classifies modes *before* setting `selected_peak_ids`. The relative ordering is inverted.

**Difference 4 — Signal emission sequence:**

Swift (via `@Published`, assignment order):
1. `setFrozenSpectrum` publishes
2. `isMeasurementComplete = true` publishes
3. `currentPeaks` publishes
4. `selectedPeakIDs` publishes
5. `userHasModifiedPeakSelection = false` publishes
6. `selectedPeakFrequencies = []` publishes
7. `identifiedModes` publishes

Python (explicit `.emit()` calls):
1. `set_frozen_spectrum(...)` — no signal yet
2. `self.is_measurement_complete = True` — no signal yet
3. Mode classification runs
4. `selected_peak_ids` set
5. `selected_peak_frequencies` set (populated, not cleared)
6. Per-tap `TapEntry` building
7. `self.measurementComplete.emit(True)` ← measurement complete fires here
8. `self.peaksChanged.emit(peaks)` ← peaks fire after measurement complete
9. `self.tapDetectedSignal.emit()` ← **Python-only, no Swift equivalent**

The deliberate ordering of `measurementComplete` before `peaksChanged` (steps 7→8) is correct
for Python: it ensures `_is_measurement_complete` is `True` in the view when
`_on_peaks_changed_results` runs, enabling peak annotations to appear.

**Difference 5 — `TapEntry.id` type:**
Swift: `UUID()` — a typed value type.
Python: `str(_uuid2.uuid4())` — a string. Type mismatch if cross-language serialisation occurs.

**Difference 6 — `TapDisplaySettings` access pattern:**
Swift reads static properties: `TapDisplaySettings.minFrequency`, etc.
Python calls methods: `_tds2.min_frequency()`, `_tds2.max_frequency()`, etc.
Structurally equivalent, different call syntax.

**Difference 7 — `max_peaks` access:**
Swift: `maxPeaks: maxPeaks` (direct property access).
Python: `max_peaks=getattr(self, "max_peaks", None)` (defensive `getattr` with fallback).

---

## 3. Signal/Emit Ordering Differences

### In all three phase handlers (`_handle_longitudinal/cross/flc_gated_progress`)

Python explicitly calls `self._emit_peaks_array(self.current_peaks)` and
`self.set_material_spectra([...])` at the end of each handler. Swift derives both from
`@Published` properties automatically. The explicit Qt emissions are architecturally necessary
but represent structural additions not literally present in the Swift code.

### In `_handle_longitudinal_gated_progress` (brace path)

Python emits `plateAnalysisComplete.emit(dominant_peak.frequency, 0.0, 0.0)`.
No equivalent emission exists in Swift's function — it fires from a different location in Swift.

### In `_handle_cross_gated_progress` and `_handle_flc_gated_progress`

Python calls `self._emit_peaks_array(self.current_peaks)` at the end of both handlers
(emitting `peaksChanged`). Swift does not emit `peaksChanged` explicitly — `@Published currentPeaks`
propagates automatically.

---

## 4. Naming Divergences

Beyond the expected camelCase → snake_case convention, these names specifically differ:

| Swift | Python | Issue |
|---|---|---|
| `materialCapturedTaps` | `captured_taps` | "material" prefix dropped |
| `gatedAccumBuffer` | `_gated_accum` | "Buffer" dropped |
| `mpmSampleRate` | `_gated_sample_rate` | Completely different name |
| `mpmLock` | `_gated_lock` | Different name |
| `samples` (param in accumulate) | `chunk` | Different parameter name |
| `from taps:` (label in averageSpectra) | `from_taps` | Swift uses external label `from`; Python merges into `from_taps` |
| `statusMessage` | `_set_status_message(...)` | `@Published` property → setter method |
| `materialTapPhase` | `_set_material_tap_phase(...)` | `@Published` property → setter method |
| `isMeasurementComplete = true` (guitar) | `set_measurement_complete(True)` (brace) / `self.is_measurement_complete = True` (guitar) | **Inconsistent within Python itself** |
| `Candidate` (local struct) | 4-tuple `(index, mag, hps_score, q)` | Named struct → positional tuple |

---

## 5. Structural Differences

The 12 shared functions appear in the same order in both files. Python inserts additional functions
between them (documented in §1).

**`GATED_CAPTURE_DURATION` constant:**
Python: class attribute `GATED_CAPTURE_DURATION: float = 0.4` (line 71 of the Python file).
Swift: static property on the main `TapToneAnalyzer` class, not in this extension file.
Same value (0.4 s), different location.

**`mpmSampleRate` persistent update:**
Swift `accumulateGatedSamples` updates `mpmSampleRate` on every call. Python derives the
rate on demand and does not maintain a persistent per-call snapshot.

**`_do_start_flc` method:**
Python has `_do_start_flc()` called via `QTimer.singleShot` to arm FLC detection. The Swift
equivalent logic lives in `acceptCurrentPhase` or similar in a different file.

**`process_averages` method:**
Python lines ~1118–1152: accumulates/averages live FFT frames with `num_averages` / `max_average_count`.
Absent from the Swift extension — it corresponds to Swift functionality in the main class or a
different extension.

---

## 6. Missing Logic

### Missing in Python

- `_accumulate_gated_samples`: Swift sets `mpmSampleRate = sampleRate` on every call; Python does not persist the rate.
- `_handle_flc_gated_progress`: Swift emits a terminal debug log of L/C/FLC frequencies; Python does not.
- `finish_capture`: Swift explicitly invalidates a `captureTimer`; Python is a no-op `pass`.

### Missing in Swift (Python adds defensive guards not present in Swift)

- `start_gated_capture`: nil mic guard — Python line ~190 (`if self.mic is None`).
- `find_dominant_peak`: pitch calculator guard — Python lines ~567–573 (try/except + hasattr).
- `finish_gated_fft_capture`: division-by-zero guard — Python `max(total, 1)`.
- `average_spectra`: log10 floor — Python `max(..., 1e-30)`.

---

## 7. Data Type / Structure Differences

| Swift | Python | Difference |
|---|---|---|
| `materialCapturedTaps: [(magnitudes:, frequencies:, captureTime:)]` | `captured_taps: list[tuple]` | Named fields → positional tuple |
| `struct Candidate` with named fields | 4-tuple `(index, mag, hps_score, q)` | Named struct → positional tuple |
| `longitudinalSpectrum: (magnitudes:, frequencies:)?` | `self.longitudinal_spectrum: tuple \| None` | Named fields → positional |
| `TapEntry.id: UUID()` | `TapEntry(id=str(uuid4()))` | Typed UUID → string |
| `averageSpectra` returns `(magnitudes:, frequencies:)` | `average_spectra` returns `(list, list)` | Named → positional tuple |

---

## Priority Issues for Remediation

1. **Extra `tapDetectedSignal.emit()` in `process_multiple_taps`** — no Swift equivalent.
   May cause spurious UI updates on tap completion. Investigate whether any connected slot
   produces undesired side effects when called from this context.

2. **`selectedPeakFrequencies`: Swift resets to `[]`; Python pre-populates** — undocumented
   intentional divergence. The Python behaviour is arguably better (avoids a stale-empty cache)
   but should be explicitly documented as a deliberate deviation.

3. **Mode classification order inverted in `process_multiple_taps`** — Swift classifies after
   setting selection; Python classifies before. Verify this does not affect `peak_mode()` results
   when `_on_peaks_changed_results` calls `update_data_with_modes`.

4. **`isMeasurementComplete` signalling inconsistent within Python** — brace path calls
   `set_measurement_complete(True)` (emits signal); guitar path sets
   `self.is_measurement_complete = True` (no signal, deferred to `measurementComplete.emit(True)`
   later). Standardise to one pattern.

5. **`Candidate` struct is a positional tuple in Python** — reduces readability.
   Consider replacing with a `dataclass` or `NamedTuple`.

6. **Missing `mpmSampleRate` per-call update** in `_accumulate_gated_samples` — low risk since
   `_gated_sample_rate` derives on demand, but the persistent snapshot property that Swift reads
   does not exist in Python.

7. **Missing terminal debug log** in `_handle_flc_gated_progress` — minor; add to parity with Swift.

8. **`materialCapturedTaps` naming** — Python dropped the "material" prefix, making it harder
   to distinguish from the guitar-mode `captured_taps`. These are the same list (shared) but the
   name no longer signals its plate/brace-specific origin.
