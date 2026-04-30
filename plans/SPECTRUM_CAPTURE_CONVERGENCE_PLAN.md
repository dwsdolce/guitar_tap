# Plan: Converge tap_tone_analyzer_spectrum_capture.py with Swift

**Date:** 2026-04-29
**Goal:** Remove ALL divergences between the Python and Swift SpectrumCapture files, except those
that are structurally unavoidable due to Qt signals vs `@Published` reactivity.

The only allowed category of difference is: where Swift uses a `@Published` property assignment
to notify observers, Python must emit an explicit Qt signal (or call a helper that does so).
Every other divergence must be eliminated.

---

## Permitted Differences (do NOT change these)

These are signal/reactivity translations — the only allowed class of divergence:

| Swift | Python equivalent | Reason |
|---|---|---|
| `materialTapPhase = .x` (auto-publishes) | `_set_material_tap_phase(x)` (sets + emits `plateStatusChanged`) | `@Published` → explicit signal |
| `statusMessage = "…"` | `self._set_status_message("…")` | `@Published` → explicit setter |
| `isMeasurementComplete = true` | `self.measurementComplete.emit(True)` | `@Published` → explicit signal |
| `currentPeaks = …` (auto-publishes) | `self.peaksChanged.emit(peaks)` | `@Published` → explicit signal |
| `longitudinalSpectrum = …` (auto-publishes computed `materialSpectra`) | `self.set_material_spectra([…])` | `@Published` computed property → explicit helper |
| `setFrozenSpectrum(…)` | `self.set_frozen_spectrum(…)` + `self.spectrumUpdated.emit(…)` | Swift `@Published` frozenFrequencies/Magnitudes auto-triggers chart redraw; Python requires explicit `spectrumUpdated` |

The `_set_material_tap_phase`, `_set_status_message`, `_emit_peaks_array`, `set_material_spectra`,
and `_on_safety_timeout_no_samples` helpers are acceptable because they exist purely to replace
`@Published` reactivity. Their presence in the Python file is correct.

---

## Changes Required

### 1. `accumulateGatedSamples` / `_accumulate_gated_samples`

**Problem A — Lock scope too wide (Python holds lock through count-check; Swift releases early):**

Swift:
```swift
mpmLock.lock()
// append to gatedAccumBuffer
let count = gatedAccumBuffer.count
mpmLock.unlock()            // ← unlocked before count check

if count >= gatedCaptureSamples {
    gatedCaptureActive = false
    mpmLock.lock()
    captured = Array(gatedAccumBuffer.prefix(gatedCaptureSamples))
    gatedAccumBuffer = []
    mpmLock.unlock()
    // dispatch
}
```

Python does the count check *inside* `with self._gated_lock:`, holding the lock through
the dispatch. The Python approach is more conservative but wrong in structure.

**Fix:** Restructure `_accumulate_gated_samples` so the lock is released after appending and
getting the count, then the count is checked outside the lock. Re-acquire for the slice+clear.
This exactly mirrors the Swift lock/unlock sequence.

**Problem B — `mpmSampleRate` not updated per call:**

Swift sets `mpmSampleRate = sampleRate` at the top of every call. Python derives rate
on-demand from `self.mic.rate`. The two computed properties `_pre_roll_samples` and
`_gated_sample_rate` are acceptable as `@Published`-property translations. However, Python
should store `self._mpm_sample_rate = sample_rate` at the start of `_accumulate_gated_samples`
and use it (instead of `self.mic.rate`) so behaviour is identical.

**Fix:** Add `self._mpm_sample_rate: float = 48000.0` to `__init__`, set it at the top of
`_accumulate_gated_samples`. Update `_gated_sample_rate` property to return `self._mpm_sample_rate`
(with `self.mic.rate` as fallback only during initialisation). Update `_pre_roll_samples` to use
`self._mpm_sample_rate` as well.

---

### 2. `startGatedCapture` / `start_gated_capture`

**Problem A — Nil/mic guard has no Swift equivalent:**

Python lines 190–192 guard on `self.mic is None`. This is a Python-only defensive check.

**Fix:** Remove the guard. If mic is None the code will fail naturally; identical to Swift which
makes no such check.

**Problem B — Log fires before lock acquisition (Python), but after `gatedCaptureActive = true` (Swift):**

Swift order: lock → seed accumulator → unlock → set phase → set active = true → log.
Python order: guard → compute rate → **log** → lock → seed + set active → unlock → timeout.

**Fix:** Move the log statement to after the `with self._gated_lock:` block (after `active = True`),
mirroring Swift's log position.

**Problem C — Safety timeout: Python uses an extra `QTimer.singleShot(0, ...)` hop for the
no-samples branch:**

Swift calls `self.statusMessage = "…"` and `self.reEnableDetectionForNextPlateTap()` directly
inside the timeout closure. Python adds `QTimer.singleShot(0, self._on_safety_timeout_no_samples)`
as an extra dispatch.

The `_on_safety_timeout_no_samples` slot exists purely because Qt signals require main-thread
slots, which is a signal/reactivity translation. However, the `QTimer.singleShot(2000,
_safety_timeout)` already fires on the main thread (because it was posted from the main thread),
so the second `singleShot(0, ...)` hop is genuinely unnecessary.

**Fix:** In the `_safety_timeout` closure, call `self._set_status_message(...)` and
`self.re_enable_detection_for_next_plate_tap()` directly (same as the flush branch calls
`gatedCaptureComplete.emit(...)` directly). Remove `_on_safety_timeout_no_samples` from the
file — it becomes dead code.

---

### 3. `finishGatedFFTCapture` / `finish_gated_fft_capture`

**Problem A — Extra `tapCountChanged` signal (Python only):**

Lines 397–410 of the Python file compute a cumulative tap count and emit `tapCountChanged`.
Swift has no equivalent emission in `finishGatedFFTCapture`. Swift increments `currentTapCount`
and updates `tapProgress` but emits no signal here.

**Fix:** Remove the `tapCountChanged.emit(...)` call and the cumulative phase-offset calculation
(lines 400–410). The `current_tap_count` and `tap_progress` assignments stay.

**Problem B — Positional tuple vs named fields for `captured_taps` append:**

Swift: `materialCapturedTaps.append((magnitudes: magnitudes, frequencies: frequencies, captureTime: Date()))`
Python: `self.captured_taps.append((magnitudes, frequencies, _dt.datetime.now()))`

This is a language-level difference (Python has no named tuple literals in this style). It is
acceptable but should be documented consistently. **No code change required** — positional tuples
are the Python equivalent of named-field tuples.

**Problem C — Division-by-zero guard `max(total, 1)` has no Swift equivalent:**

Python: `self.tap_progress = min(1.0, float(self.current_tap_count) / max(total, 1))`
Swift: `tapProgress = min(1.0, Float(currentTapCount) / Float(totalPlateTaps))`

**Fix:** Remove `max(total, 1)`. Use `self.total_plate_taps` directly, matching Swift exactly.
If `total_plate_taps` is ever 0, it will fail identically to Swift.

---

### 4. `findDominantPeak` / `find_dominant_peak`

**Problem A — `Candidate` is a 4-tuple; Swift uses a named struct:**

Python candidates are `(index, mag, hps_score, q)`, accessed by magic index `c[0]`, `c[1]`, etc.
Swift uses a local `struct Candidate` with named fields.

**Fix:** Replace the 4-tuple with a `typing.NamedTuple`:
```python
from typing import NamedTuple
class _Candidate(NamedTuple):
    index: int
    magnitude: float
    hps_score: float
    q_factor: float
```
Defined locally inside `find_dominant_peak`. Replace all `c[0]`/`c[1]`/`c[2]`/`c[3]` references
with `.index`, `.magnitude`, `.hps_score`, `.q_factor`. Also update the `best_idx, best_mag,
best_hps, best_q = best` unpacking to use named fields.

**Problem B — Bounds check `if 0 <= j < n` in local maximum loop (Python only):**

Swift loop: `for offset in -windowSize...windowSize where offset != 0 { if magnitudes[i + offset] >= mag … }`
— no bounds check; the outer loop range guarantees safety.

Python: adds `if 0 <= j < n` guard.

**Fix:** Remove the `if 0 <= j < n` guard. The Python scan range `scan_start = start_idx +
window_size`, `scan_end = end_idx - window_size` already ensures `i ± window_size` stays within
`[start_idx, end_idx)` which is within `[0, n)`. The check is redundant.

**Problem C — Pitch calculator guard and try/except (Python only):**

Swift calls `pitchCalculator.note(frequency:)` directly with no guard. Python wraps it in
`if hasattr(…)` and `try/except`.

**Fix:** Remove the `hasattr` guard and `try/except`. Call `self.pitch_calculator.note(...)` etc.
directly, mirroring Swift. If `pitch_calculator` is not set, it will fail at the `__init__` level,
which is the correct place to catch it.

---

### 5. `handleLongitudinalGatedProgress` / `_handle_longitudinal_gated_progress`

**Problem A — Plate path calls `set_frozen_spectrum` before setting `current_peaks` and emitting:**

Swift plate path order:
1. `longitudinalSpectrum = (avgMags, avgFreqs)` — stores spectrum
2. `longitudinalPeaks = buildAllPeaks(…)` — builds peaks
3. `currentPeaks = longitudinalPeaks`
4. `selectedPeakIDs = Set([dominantPeak.id])`
5. `materialCapturedTaps = []`
6. `setFrozenSpectrum(frequencies: avgFreqs, magnitudes: avgMags)` — freezes
7. `materialTapPhase = .reviewingLongitudinal`
8. `isDetecting = false`
9. `statusMessage = "…"`

Python plate path does `set_frozen_spectrum` at line 634 which is *before* the brace/plate split,
causing the frozen spectrum to be set in both branches identically, which is correct. But then
`_emit_peaks_array` (→ `peaksChanged`) is emitted at line 668 after `_set_material_tap_phase`.
In Swift, `currentPeaks` is set at step 3 (before phase change), and `materialTapPhase` at step 7.

Actually looking at Swift more carefully: in the plate path, `setFrozenSpectrum(frequencies: avgFreqs, ...)` is called and then `materialTapPhase = .reviewingLongitudinal`. Python calls
`set_frozen_spectrum` early (line 634, shared path), then `_emit_peaks_array` at 668, then
`_set_material_tap_phase`. This means peaks are emitted before phase is set, matching Swift
where `currentPeaks` is assigned before `materialTapPhase`.

The main divergence is the extra `set_material_spectra` call and `spectrumUpdated.emit` at lines
678–686. These are signal/reactivity translations of Swift's `@Published longitudinalSpectrum`
causing the materialSpectra computed property to update. **These are permitted.**

**Problem B — `selected_peak_frequencies` pre-set (Python only):**

Python line 629: `self.selected_peak_frequencies = [dominant_peak.frequency]`

Swift does NOT set `selectedPeakFrequencies` in `handleLongitudinalGatedProgress`. Swift resets
it to `[]` only in `processMultipleTaps`. For the plate/brace path, it is never set in the handler.

**Fix:** Remove line 629 (`self.selected_peak_frequencies = [dominant_peak.frequency]`).

**Problem C — `showLoadedSettingsWarning` clear is in this function (Python) but in a `didSet` (Swift):**

Python lines 648–650 explicitly check and clear `show_loaded_settings_warning` in the brace path.
In Swift this happens in `isMeasurementComplete.didSet`. Since Python has no property observers,
this inline clear is an acceptable signal/reactivity translation. **No change.**

**Problem D — Brace path calls `set_measurement_complete(True)` but guitar path sets attribute directly:**

In the brace path, Python calls `self.set_measurement_complete(True)` which emits `measurementComplete`.
In the guitar path (`process_multiple_taps`), Python sets `self.is_measurement_complete = True`
first and emits `measurementComplete.emit(True)` later. This inconsistency is within the permitted
signal-emission translation. **No change** — the order difference in `process_multiple_taps` is a
deliberate and documented deviation (to ensure `_is_measurement_complete` is True before `peaksChanged` fires).

**Problem E — `import time as _t` is present but unused:**

Lines 599 and 734 import `time as _t` in two handler functions. Neither uses it.

**Fix:** Remove both unused `import time as _t` lines.

---

### 6. `handleCrossGatedProgress` / `_handle_cross_gated_progress`

**Problem A — `import time as _t` unused:**

Line 734 imports `time as _t`, unused.

**Fix:** Remove it. (Covered by fix in §5 above.)

**Problem B — `set_material_spectra` and `_emit_peaks_array` order vs Swift:**

Swift plate path (cross handler) order:
1. `crossSpectrum = (avgMags, avgFreqs)`
2. `crossPeaks = buildAllPeaks(…)`
3. `autoSelectedCrossPeakID = dominantPeak.id`
4. `selectedCrossPeak = …`
5. `materialCapturedTaps = []`
6. `currentPeaks = combinePlatePeaks()`
7. `selectedPeakIDs = Set([…])`
8. `setFrozenSpectrum(…)`
9. `materialTapPhase = .reviewingCross`
10. `isDetecting = false`
11. `statusMessage = "…"`

Python order is the same through step 11. Then Python adds:
- `set_material_spectra(spectra)` (signal/reactivity translation — permitted)
- `_emit_peaks_array(self.current_peaks)` (signal/reactivity translation — permitted)

These are necessary Qt replacements for Swift's `@Published crossSpectrum` and `@Published currentPeaks`.
**No changes needed here.**

---

### 7. `handleFlcGatedProgress` / `_handle_flc_gated_progress`

**Problem A — Missing terminal debug log:**

Swift line 662: `gtLog("📊 FLC review: L=\(longitudinalPeaks.first?.frequency ?? 0) C=\(crossPeaks.first?.frequency ?? 0) FLC=\(dominantPeak.frequency) Hz")`

Python has no equivalent at the end of `_handle_flc_gated_progress`.

**Fix:** Add the log line at the end of the function (after `_emit_peaks_array`):
```python
gt_log(
    f"📊 FLC review: L={self.longitudinal_peaks[0].frequency if self.longitudinal_peaks else 0} "
    f"C={self.cross_peaks[0].frequency if self.cross_peaks else 0} "
    f"FLC={dominant_peak.frequency} Hz"
)
```

---

### 8. `averageSpectra` / `average_spectra`

**Problem A — log10 floor `max(..., 1e-30)` (Python only):**

Swift: `averagedMagnitudes[binIndex] = 10.0 * log10(averageLinear)` — no floor.
Python: `10.0 * math.log10(max(power_sum[b] / n_taps, 1e-30))` — has floor.

**Fix:** Remove `max(..., 1e-30)`. Use `10.0 * math.log10(power_sum[b] / n_taps)` directly,
matching Swift. This makes behaviour identical, including the potential for `-inf` on degenerate
inputs (which Swift also produces).

---

### 9. `processMultipleTaps` / `process_multiple_taps`

**Problem A — Extra `tapDetectedSignal.emit()` at end (Python only):**

Swift `processMultipleTaps` does **not** set `tapDetected` or emit any tap-detected signal.
Swift's `tapDetected` is set in `TapToneAnalyzer+TapDetection.swift` as part of the tap detection
loop, not in `processMultipleTaps`.

Python emits `self.tapDetectedSignal.emit()` at line 1077.

**Fix:** Remove `self.tapDetectedSignal.emit()` from `process_multiple_taps`.

**Problem B — `selectedPeakFrequencies` is pre-populated; Swift resets to `[]`:**

Swift line 820: `selectedPeakFrequencies = []`
Python lines 1004–1006: `self.selected_peak_frequencies = [p.frequency for p in peaks if p.id in self.selected_peak_ids]`

**Fix:** Change to `self.selected_peak_frequencies = []` to match Swift exactly.

**Problem C — Mode classification order relative to `selectedPeakIDs` assignment:**

Swift order: `selectedPeakIDs = …` (line 817) → `userHasModifiedPeakSelection = false` (line 818) → `loadedMeasurementPeaks = nil` (line 819) → `selectedPeakFrequencies = []` (line 820) → `identifiedModes = …` (line 824).

Python order: `loaded_measurement_peaks = None` → `find_peaks` → `current_peaks = peaks` → classify modes → `selected_peak_ids = …` → `selected_peak_frequencies = []` → `user_has_modified_peak_selection = False`.

Align Python to match Swift's property-assignment sequence precisely:
1. `self.current_peaks = peaks`
2. `self.selected_peak_ids = self.guitar_mode_selected_peak_ids(peaks)`
3. `self.user_has_modified_peak_selection = False`
4. `self.loaded_measurement_peaks = None`
5. `self.selected_peak_frequencies = []`
6. Classify modes → `self.identified_modes = …`

**Problem D — `getattr(self, "max_peaks", None)` defensive guard (Python only):**

Swift: `maxPeaks: maxPeaks` — direct property access.
Python: `max_peaks=getattr(self, "max_peaks", None)` — defensive.

**Fix:** Change to `max_peaks=self.max_peaks`.

**Problem E — TapDisplaySettings access: Python uses method calls, Swift uses static properties:**

Python: `_tds2.min_frequency()`, `_tds2.max_frequency()`, `_tds2.min_magnitude()`, etc.
Swift: `TapDisplaySettings.minFrequency`, `TapDisplaySettings.maxFrequency`, etc.

This is a Python API difference (methods vs properties), not an algorithmic divergence. Leave
as-is if `TapDisplaySettings` is already using method calls everywhere else.
**No change** — this is a Python API convention.

**Problem F — `TapEntry.id` is `str(uuid4())` in Python, `UUID()` in Swift:**

Python: `id=str(_uuid2.uuid4())` → string.
Swift: `id: UUID()` → typed value.

**Fix:** This requires checking whether `TapEntry` in Python accepts `UUID` objects or strings.
If it accepts both, change to pass a `uuid.UUID` object. If it requires a string (e.g. for JSON
serialisation), leave as-is and document the divergence. **Investigate before changing.**

---

### 10. Functions to MOVE OUT of `tap_tone_analyzer_spectrum_capture.py`

**`process_averages`** (lines 1118–1152) does not exist anywhere in Swift's
`TapToneAnalyzer+SpectrumCapture.swift`. It implements live FFT accumulation/averaging with
`num_averages` / `max_average_count`. In Swift this logic lives in the main `TapToneAnalyzer`
class body or in a different extension. It must be moved to the correct Python file — most likely
`tap_tone_analyzer.py` (the main class) or wherever `num_averages`, `max_average_count`, and
`mag_y_sum` are initialised.

**`start_plate_analysis`** and **`reset_plate_analysis`** (lines 1100–1111) are thin wrappers.
Neither exists in `TapToneAnalyzer+SpectrumCapture.swift`. They are call-site convenience methods.
Move them to the file that corresponds to whichever Swift file calls `startTapSequence()` and
`cancelTapSequence()` — likely `tap_tone_analyzer_control.py` or the main analyzer class.

---

### 11. Properties to add/move to match Swift

`mpmSampleRate` lives in `TapToneAnalyzer.swift` (line 751) as a stored property on the main
class, not in the extension. The `_mpm_sample_rate` stored backing field must be added to
`TapToneAnalyzer.__init__` in `tap_tone_analyzer.py`, not declared inside the mixin.

`capturedTaps` (Swift line 831) is declared in the main `TapToneAnalyzer.swift`, not in the
extension. Verify that Python's `captured_taps` is initialised in `TapToneAnalyzer.__init__`
(not in the mixin). If it is currently initialised in the mixin, move it to `__init__`.

`captureTimer` (Swift line 840) is declared in `TapToneAnalyzer.swift`. Python has no equivalent
stored timer reference. The `finish_capture()` no-op is correct. No change needed.

---

## Summary of Changes (Code-level)

| # | File | Change |
|---|---|---|
| 1a | `tap_tone_analyzer_spectrum_capture.py` | Restructure `_accumulate_gated_samples` lock/unlock to match Swift's two-step lock pattern |
| 1b | `tap_tone_analyzer.py` | Add `self._mpm_sample_rate: float = 48000.0` to `__init__` |
| 1b | `tap_tone_analyzer_spectrum_capture.py` | Set `self._mpm_sample_rate = sample_rate` at top of `_accumulate_gated_samples`; update `_gated_sample_rate` and `_pre_roll_samples` to use it |
| 2a | `tap_tone_analyzer_spectrum_capture.py` | Remove mic=None guard from `start_gated_capture` |
| 2b | `tap_tone_analyzer_spectrum_capture.py` | Move log statement in `start_gated_capture` to after the lock block |
| 2c | `tap_tone_analyzer_spectrum_capture.py` | In safety timeout, call `_set_status_message` and `re_enable_detection_for_next_plate_tap` directly; remove `_on_safety_timeout_no_samples` slot |
| 3a | `tap_tone_analyzer_spectrum_capture.py` | Remove `tapCountChanged.emit(...)` and cumulative-phase-offset calculation from `finish_gated_fft_capture` |
| 3c | `tap_tone_analyzer_spectrum_capture.py` | Remove `max(total, 1)` guard from `tap_progress` calculation |
| 4a | `tap_tone_analyzer_spectrum_capture.py` | Replace 4-tuple `candidates` with local `_Candidate(NamedTuple)` struct; use named fields throughout `find_dominant_peak` |
| 4b | `tap_tone_analyzer_spectrum_capture.py` | Remove `if 0 <= j < n` bounds check from local-maximum loop |
| 4c | `tap_tone_analyzer_spectrum_capture.py` | Remove `hasattr`/`try-except` guard around pitch_calculator calls |
| 5b | `tap_tone_analyzer_spectrum_capture.py` | Remove `self.selected_peak_frequencies = [dominant_peak.frequency]` from `_handle_longitudinal_gated_progress` |
| 5e | `tap_tone_analyzer_spectrum_capture.py` | Remove unused `import time as _t` from `_handle_longitudinal_gated_progress` and `_handle_cross_gated_progress` |
| 7a | `tap_tone_analyzer_spectrum_capture.py` | Add terminal FLC debug log to `_handle_flc_gated_progress` |
| 8a | `tap_tone_analyzer_spectrum_capture.py` | Remove `max(..., 1e-30)` floor from `average_spectra` |
| 9a | `tap_tone_analyzer_spectrum_capture.py` | Remove `self.tapDetectedSignal.emit()` from `process_multiple_taps` |
| 9b | `tap_tone_analyzer_spectrum_capture.py` | Change `selected_peak_frequencies` population to `self.selected_peak_frequencies = []` |
| 9c | `tap_tone_analyzer_spectrum_capture.py` | Reorder property assignments in `process_multiple_taps` to match Swift sequence |
| 9d | `tap_tone_analyzer_spectrum_capture.py` | Change `getattr(self, "max_peaks", None)` to `self.max_peaks` |
| 9f | `tap_tone_analyzer_spectrum_capture.py` / `tap_tone_measurement.py` | Investigate `TapEntry.id` type; change to `uuid.UUID` if possible |
| 10a | `tap_tone_analyzer_spectrum_capture.py` → `tap_tone_analyzer.py` or other | Move `process_averages` to the file corresponding to its Swift home |
| 10b | `tap_tone_analyzer_spectrum_capture.py` → `tap_tone_analyzer_control.py` or other | Move `start_plate_analysis` and `reset_plate_analysis` to the file corresponding to their Swift callers |

---

## Order of Operations

Perform changes in this order to avoid cascading breakage:

1. **Items 5e, 7a** — pure additions/removals, no logic change, lowest risk.
2. **Items 8a, 3c** — remove defensive guards; verify no inputs produce zero/negative power sums.
3. **Items 9b, 9a** — change `process_multiple_taps` signal order; test multi-tap live flow.
4. **Item 9c** — reorder property assignments in `process_multiple_taps`; test peak annotations.
5. **Items 3a** — remove `tapCountChanged` from `finish_gated_fft_capture`; verify plate/brace UI still shows progress.
6. **Item 4a** — introduce `_Candidate` NamedTuple; pure refactor, same logic.
7. **Items 4b, 4c** — remove defensive bounds/pitch guards.
8. **Items 2a, 2b, 2c** — restructure `start_gated_capture`; test plate tap sequence.
9. **Items 1a, 1b** — restructure lock in `_accumulate_gated_samples` and add `_mpm_sample_rate`.
10. **Items 5b** — remove `selected_peak_frequencies` pre-set from longitudinal handler.
11. **Items 9d, 9f** — `max_peaks` and UUID type changes.
12. **Items 10a, 10b** — move `process_averages`, `start_plate_analysis`, `reset_plate_analysis`.

---

## Items Requiring Investigation Before Changing

- **9f**: Check `TapEntry.__init__` signature in `tap_tone_measurement.py` to determine whether
  `id` is stored as a `str` or `uuid.UUID`, and whether any serialisation/deserialisation code
  depends on it being a string.

- **10a**: Confirm which Python file corresponds to the Swift file or class body where live-FFT
  accumulation (`num_averages`, `max_average_count`, `mag_y_sum`) is implemented. Then move
  `process_averages` there.

- **10b**: Confirm which Python file's `__init__` or control layer calls `start_plate_analysis`
  and `reset_plate_analysis`, to choose the correct destination file.

- **3a (`tapCountChanged`)**: Before removing `tapCountChanged.emit`, confirm that no UI widget
  or view connects to this signal for plate/brace progress display. If the signal is used by the
  view's progress indicator, the fix is instead to move it to the correct Swift-equivalent location
  (e.g. `TapToneAnalyzer+TapDetection.swift` equivalent) rather than simply delete it.
