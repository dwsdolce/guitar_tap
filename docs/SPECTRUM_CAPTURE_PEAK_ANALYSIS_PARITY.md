# Spectrum Capture & Peak Analysis Parity Fixes

Two pre-existing parity gaps were identified during the Annotation ID Pipeline
Refactoring review. Neither was introduced by that refactoring; both exist in the
code that preceded it.

---

## Gap 3 — `find_peaks()` emits inside itself; Swift defers to caller

### Current Python behaviour

`find_peaks()` in `tap_tone_analyzer_peak_analysis.py` ends with:

```python
# lines 239–241
self.current_peaks = final_peaks
self.peaksChanged.emit(final_peaks)
return final_peaks
```

`find_peaks()` therefore has two responsibilities:

1. Compute and return the peak list.
2. Store + emit `peaksChanged`.

### Swift behaviour

`findPeaks()` in `TapToneAnalyzer+PeakAnalysis.swift` only computes and returns:

```swift
// line 461
return finalPeaks.sorted(by: { $0.magnitude > $1.magnitude })
```

The caller (`analyzeMagnitudes()`) owns storage and notification:

```swift
// lines 94–101
let peaks = findPeaks(magnitudes: magnitudes, frequencies: frequencies)
currentPeaks = peaks                          // fires @Published → view updates
selectedPeakIDs = Set(peaks.map { $0.id })    // auto-select all new peaks
let modeMap = GuitarMode.classifyAll(peaks)
identifiedModes = peaks.map { (peak: $0, mode: modeMap[$0.id] ?? .unknown) }
```

`recalculateFrozenPeaksIfNeeded()` also calls `findPeaks()` directly and handles
its own storage, selection, and mode-remapping via `applyFrozenPeakState()`.

### Problem

Because Python stores and emits inside `find_peaks()`, any call site that calls
`find_peaks()` always emits — even `recalculateFrozenPeaksIfNeeded()`, which should
own its own post-processing before notifying the view. This conflation of concerns
makes it harder to add `applyFrozenPeakState()` parity (the Pair 2 gap in
`TEST_PARITY_ANALYSIS.md`) without double-emitting.

### Fix

Remove the store + emit block from `find_peaks()`. Move it into the call sites
exactly as Swift does.

#### Files to change

**`tap_tone_analyzer_peak_analysis.py`** — remove the two lines before `return`:

```python
# REMOVE these two lines:
self.current_peaks = final_peaks
self.peaksChanged.emit(final_peaks)
```

**`tap_tone_analyzer_analysis_helpers.py`** — `recalculate_frozen_peaks_if_needed()`,
frozen-spectrum branch: add store + emit after the `find_peaks()` call, mirroring the
current `_emit_loaded_peaks_at_threshold()` pattern:

```python
peaks = self.find_peaks(...)
self.current_peaks = peaks
self.peaksChanged.emit(peaks)
```

(The `_emit_loaded_peaks_at_threshold()` branch already owns its own store + emit and
does not call `find_peaks()`, so it is unaffected.)

**`tap_tone_analyzer_spectrum_capture.py`** — `_build_all_peaks()` calls `find_peaks()`
internally. After this fix, `_build_all_peaks()` will return the list without
side-effects. The gated-progress handlers already call `_emit_peaks_array()` after
`_build_all_peaks()`, so no change is needed there — the existing explicit emit
calls remain correct.

#### Tests to update / add

- `test_frozen_peak_recalculation.py` — PRA1 / PRA2 tests call
  `recalculate_frozen_peaks_if_needed()` and check `current_peaks`; they should
  continue to pass unchanged since `recalculate_frozen_peaks_if_needed()` will still
  store and emit (now explicitly in the frozen-spectrum branch).
- Consider adding a test that calls `find_peaks()` directly and asserts it does
  **not** mutate `current_peaks`, confirming the separation of concerns.

---

## Gap 4 — Double-emit in `_handle_longitudinal_gated_progress()`

### Current Python behaviour

`_handle_longitudinal_gated_progress()` calls `_emit_peaks_array()` **twice** in
the brace-measurement path:

```python
# line 525 — inside the `is_brace` branch
self._emit_peaks_array(self.current_peaks)
self.plateAnalysisComplete.emit(...)

# line 553 — unconditionally, after the if/else
self._emit_peaks_array(self.current_peaks)
self.spectrumUpdated.emit(...)
```

In the brace path both calls carry the same single-peak list. The first is a
dedicated "measurement complete" notification; the second is the general
spectrum-update notification that also applies to the plate path.

### Swift behaviour

Swift assigns `currentPeaks` exactly once per state transition. The `@Published`
property observer fires a single notification per assignment. There is no
equivalent of the unconditional second emit.

In the brace branch:
```swift
// lines 502–524 (simplified)
currentPeaks = [selPeak]
// ... set frozen spectrum, materialTapPhase, etc.
plateAnalysisComplete(...)
// function returns — no second currentPeaks assignment
```

In the plate branch:
```swift
currentPeaks = longitudinalPeaks
// ... set state, start cooldown timer
// function returns — no second currentPeaks assignment
```

The `spectrumUpdated` equivalent fires separately via `setFrozenSpectrum()`, which
does not reassign `currentPeaks`.

### Problem

The unconditional `_emit_peaks_array()` at line 553 causes the view to re-process
the same peak list a second time immediately after the brace-completion emit at
line 525. This is wasteful and can cause annotation flicker or duplicate annotation
creation if the view is not idempotent. The plate path is unaffected (only one emit
reaches line 553 there), but the inconsistency is a latent bug.

### Fix

Remove the unconditional `_emit_peaks_array()` call at line 553. Keep the
`spectrumUpdated` emit that follows it. The brace branch at line 525 and the
plate-path-only implicit emit (via no change to `current_peaks` after line 500)
are both correct without the unconditional second call.

Concretely, change lines 552–557 from:

```python
# Notify spectrum update.
self._emit_peaks_array(self.current_peaks)
self.spectrumUpdated.emit(
    self.frozen_frequencies if len(self.frozen_frequencies) else self.freq,
    self.frozen_magnitudes  if len(self.frozen_magnitudes)  else self.freq * 0,
)
```

to:

```python
# Notify spectrum update.
self.spectrumUpdated.emit(
    self.frozen_frequencies if len(self.frozen_frequencies) else self.freq,
    self.frozen_magnitudes  if len(self.frozen_magnitudes)  else self.freq * 0,
)
```

However, the plate branch then has no `peaksChanged` emit for the
longitudinal peaks that were just stored at line 500. Add an explicit emit
in the `else` branch (plate path) before the cooldown timer, mirroring the
brace branch:

```python
else:
    # Plate: transition to cross-grain phase.
    self._emit_peaks_array(self.current_peaks)   # ← add here
    self.material_tap_phase = _MTP.WAITING_FOR_CROSS_TAP
    ...
```

This gives:
- **Brace path:** one `_emit_peaks_array()` at line 525, then `spectrumUpdated`.
- **Plate path:** one `_emit_peaks_array()` in the `else` block, then `spectrumUpdated`.

Both paths emit exactly once for `peaksChanged`, matching Swift's single-assignment
behaviour.

#### Tests to update / add

- Add a test to `test_spectrum_capture.py` (or equivalent) that:
  1. Drives a simulated brace tap through `_handle_longitudinal_gated_progress()`.
  2. Counts `peaksChanged` signal emissions.
  3. Asserts exactly **one** emission.
- Add an equivalent test for the plate (non-brace) path.

---

## Implementation Order

1. **Gap 4 first** — simpler and self-contained; touches only
   `tap_tone_analyzer_spectrum_capture.py`. Run tests after.

2. **Gap 3 second** — touches `tap_tone_analyzer_peak_analysis.py` and
   `tap_tone_analyzer_analysis_helpers.py`; requires checking every caller of
   `find_peaks()` to confirm each one now owns its own store + emit. Run tests
   after.

3. **Note:** Gap 3 is a prerequisite for the `applyFrozenPeakState()` parity work
   described in `TEST_PARITY_ANALYSIS.md` — once `find_peaks()` no longer emits
   internally, `recalculate_frozen_peaks_if_needed()` can add mode-remapping and
   selection carry-forward without risk of double-emission.

---

## Status

> **Status: COMPLETE** — Both gaps implemented and verified. 215/215 tests passing.

- [x] Gap 4: Remove double-emit in `_handle_longitudinal_gated_progress()`
- [x] Gap 3: Remove store + emit from `find_peaks()`; add explicit store + emit at call sites
