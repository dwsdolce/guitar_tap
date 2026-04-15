# Structural Divergence Plan

This document supersedes the framing in `DIVERGENCE_VS_SWIFTUI_COMPAT_PLAN.md` and
`SWIFTUI_COMPAT_VIEW_LAYER_PLAN.md`. The destination has changed:

**The Python codebase stays PySide6. No view-layer migration to pyedifice or
swiftui_compat. The `swiftui_compat` dependency is removed.**

The goal of closing divergences is now purely:

1. **Correctness** — Python and Swift produce the same results for the same input.
2. **Traceability** — a developer reading either codebase can find the counterpart
   in the other without a map. Structure, naming, and layering should be parallel
   enough that Swift → Python translation is mechanical, not interpretive.

Traceability matters for long-term maintenance. Every feature added to the Swift
app will need to be ported. Every bug fixed in one will need to be checked in the
other. The structural work already done — mixin extension files, snake_case property
name alignment, `TapDisplaySettings` as a model singleton — directly serves this
goal and should be preserved.

---

## What to keep from the restructuring work

The `PYTHON_ARCHITECTURE_RESTRUCTURING_PLAN.md` (Parts 2–6) delivered real,
lasting value regardless of the swiftui_compat direction:

| What was done | Why it is still valuable |
|---|---|
| Mixin extension files mirroring Swift `+` files | One-to-one file correspondence; easy to navigate between codebases |
| `snake_case` property names matching Swift `camelCase` | `peak_threshold` ↔ `peakThreshold`; property-level traceability |
| `TapDisplaySettings` moved to model layer | Correct layer; matches Swift |
| Hardware-independent `__init__` | Matches Swift's initialiser structure |
| `find_peaks` API returning `list[ResonantPeak]` | Type-level parity with Swift |
| `Published` fields as readable state snapshots | `analyzer.current_peaks` etc. are useful for tests and read-only access |

## What to remove

### `ObservableObject` as a base class

`TapToneAnalyzer` inherits `ObservableObject` but `.subscribe()` is never called
anywhere in the application. The notification machinery (`_change_callbacks`,
`_notify_change`) fires into an empty list on every property write. All reactive UI
updates run through Qt signals. The `ObservableObject` base class is dead weight.

**Action:** Remove `ObservableObject` from `TapToneAnalyzer`'s base class list.
Remove the `ObservableObject.__init__(self)` call. Remove the `swiftui_compat`
import from `tap_tone_analyzer.py`.

### `Published` as a descriptor

`Published` fields store values correctly but the descriptor layer adds overhead on
every property read and write with no runtime benefit. The notification side is
unused. Readable state snapshots — the one genuine use — are equally served by
plain instance attributes.

**Action:** Replace every `field = Published(default)` class-level declaration with
`self.field = default` in `__init__`. The property names stay the same; only the
mechanism changes. This preserves traceability (same names, same initial values)
while eliminating the dependency on `swiftui_compat`.

### `swiftui_compat` dependency

After the two removals above, nothing in `guitar_tap` imports `swiftui_compat`.
Remove it from `requirements.txt` / `pyproject.toml`.

### Dead plan documents

Move to `plans/Completed/` or `plans/Superseded/`:
- `SWIFTUI_COMPAT_VIEW_LAYER_PLAN.md` — the view-layer migration is not happening
- `DIVERGENCE_VS_SWIFTUI_COMPAT_PLAN.md` — the "fix before/during/after view
  rewrite" categorisation is wrong now that the destination has changed
- `PYEDIFICE_EXTENSIONS_PLAN.md` — the 12 CustomWidget wrappers are not needed

---

## Divergence priorities

Each divergence from `STRUCTURAL_DIVERGENCE_AUDIT.md` is re-evaluated below.
Priority is based on two axes: **correctness impact** (does Python give a wrong
answer?) and **traceability impact** (does the divergence make future porting
harder?). The old "fix before/during/after view rewrite" framing is discarded.

---

### Priority 1 — Fix: correctness gaps that produce wrong results

#### Divergence #8 / §10: `peakThreshold` does not trigger `recalculateFrozenPeaksIfNeeded()`

**Impact:** When the user changes the peak threshold, the frozen spectrum's peaks
are not recalculated in Python. In Swift they are, via `didSet`. The peak list shown
after a threshold change is stale in Python.

**Fix:** In the view-layer handler that applies the threshold change
(`_on_apply_settings` or `_on_threshold_changed`), add a call to
`self.fft_canvas.analyzer.recalculate_frozen_peaks_if_needed()` after the threshold
is applied. This matches Swift's `didSet` effect without needing a descriptor-level
mechanism.

**Traceability note:** Add a comment: `# mirrors peakThreshold.didSet in Swift`.

---

#### Divergence #10 / §9: `cycle_annotation_visibility` does not persist

**Impact:** The docstring on `TapToneAnalyzer.cycle_annotation_visibility()` claims
it persists the new mode, but the code does not call
`TapDisplaySettings.set_annotation_visibility_mode()`. The view handler does the
persistence. The model method is bypassed; the view calls `_on_cycle_annotation_mode`
directly.

**Fix (two parts):**
1. Add `TapDisplaySettings.set_annotation_visibility_mode(self.annotation_visibility_mode)`
   inside `cycle_annotation_visibility()` on the analyzer, matching Swift exactly.
2. Make the view call `self.fft_canvas.analyzer.cycle_annotation_visibility()`
   instead of reimplementing the logic inline. Delete the redundant view-layer
   `_on_cycle_annotation_mode` implementation of the cycling logic.

**Traceability note:** The model method should be the single call site, matching
Swift's architecture.

---

### Priority 2 — Fix: layer inversions that hurt traceability and future porting

#### Divergence #5 / §12: `loadMeasurement` lives in the view layer

**Impact:** Swift's `loadMeasurement(_:)` is a 281-line method on the analyzer.
Python's `_restore_measurement()` is a ~360-line method in the view that directly
manipulates UI widgets. This is the most damaging traceability gap: every future
change to measurement loading in Swift requires finding the equivalent view-layer
code in Python.

**Fix:** Create `TapToneAnalyzerMeasurementManagementMixin.load_measurement(measurement)`
that restores all analyzer-owned state directly:
- `self.current_peaks = measurement.peaks`
- `self.peak_mode_overrides = measurement.peak_mode_overrides`
- `self.selected_peak_ids = measurement.selected_peak_ids`
- `self.annotation_visibility_mode = measurement.annotation_visibility_mode`
- `self.peak_annotation_offsets = measurement.annotation_offsets`
- `self.min_frequency`, `self.max_frequency`, `self.peak_threshold` etc.

The view's `_restore_measurement()` then becomes a thin coordinator:
calls `analyzer.load_measurement(m)`, then syncs the UI controls to the
restored state (`.setValue()`, `.setCurrentText()` calls that belong in the view).
This mirrors Swift's architecture: model method restores model state; view
observes the result and updates controls.

**Traceability note:** Each block in `load_measurement()` should have a comment
citing the Swift line number it mirrors.

---

#### Divergence #9 / §11: Settings persistence in view-layer handlers

**Impact:** In Swift, `peakThreshold.didSet`, `tapDetectionThreshold.didSet`, and
`hysteresisMargin.didSet` each persist to `TapDisplaySettings` in the model. In
Python this happens in view-layer event handlers. When Swift adds a new setting
with auto-persistence, there is no obvious Python counterpart location.

**Fix:** For each of these three properties, add explicit persistence calls in the
Python model at the point where the value is set — currently in the model's own
setter paths — so that persistence is a model-layer concern. Specifically:
- In whatever code path sets `self.peak_threshold`, also call
  `TapDisplaySettings.set_peak_threshold(self.peak_threshold)`.
- Same for `tap_detection_threshold` and `hysteresis_margin`.

Remove the persistence calls from the view-layer handlers so each responsibility
lives in exactly one place.

**Traceability note:** Comment each persistence call with `# mirrors didSet in Swift`.

---

#### Divergence #14 / §4a: Measurement file I/O in views module

**Impact:** `measurementsFileURL`, `loadPersistedMeasurements()`, and
`persistMeasurements()` all live on the Swift analyzer. In Python they live in the
views module. This is the same layer-inversion pattern as `loadMeasurement`.

**Fix:** Move `measurements_file_url`, `load_persisted_measurements()`, and
`persist_measurements()` to `TapToneAnalyzerMeasurementManagementMixin`. The views
module calls these methods on the analyzer instead of implementing them itself.

---

### Priority 3 — Fix: named gaps that are low-cost to close

#### Divergence #1 / §2b: `identified_modes` structure

**Impact:** Swift uses named tuples `[(peak: ResonantPeak, mode: GuitarMode)]`.
Python uses `list[dict]`. Every access site uses `entry["peak"]` instead of
`item.peak`. Not a correctness gap, but it requires mental translation at every
access point.

**Fix:** Define a lightweight dataclass or named tuple:
```python
from typing import NamedTuple
class IdentifiedMode(NamedTuple):
    peak: ResonantPeak
    mode: GuitarMode
```
Change `identified_modes` to `list[IdentifiedMode]`. Update all access sites.
This matches Swift's named-tuple access syntax directly (`entry.peak`, `entry.mode`).

---

#### Divergence #10 / §9: `cycleAnnotationVisibility` docstring

Already fixed as part of Priority 1 #10 above.

---

#### Divergence #4 / §4c: `saveMeasurement` parameter structure

**Impact:** Swift takes 16+ individual named parameters. Python takes a single
pre-built `TapToneMeasurement`. This is not a correctness gap — the data is the
same — but it means you cannot read the Swift method signature and know what Python
is doing at that call site without finding `_collect_measurement()`.

**Fix:** Low priority. The Python approach (pre-build the measurement object, then
pass it) is actually a reasonable Python idiom. Add a docstring to
`save_measurement()` explicitly citing the Swift counterpart and noting the
structural difference. This is the lowest-cost traceability fix.

---

### Priority 4 — Accept with documentation

These divergences are real but either have acceptable Python-idiomatic equivalents
or are not worth the refactoring cost given the current state of the codebase.

#### Divergence #6 / §7a: 28 `loaded*` @Published properties absent from Python

**Why accepted:** In Swift, these properties exist so SwiftUI views can reactively
show/hide "settings restored from measurement" UI without any additional wiring.
In Python, the Qt signal/slot system makes this unnecessary — the view can read
back from the analyzer after `load_measurement()` returns and update controls
directly. The 28 properties are a SwiftUI-reactive-rendering artifact, not a
fundamental design requirement.

**What to do:** After `load_measurement()` is moved to the model (Priority 2
above), the view reads the restored state from the analyzer's plain properties
(`analyzer.peak_threshold`, `analyzer.min_frequency`, etc.) to sync controls. No
`loaded*` shadow properties are needed.

**Document in code:** Add a comment to `load_measurement()`:
```python
# Swift equivalent has 28 loaded* @Published properties that drive reactive UI
# updates. Python reads back from plain properties after load_measurement()
# returns, which is equivalent for a Qt signal-driven architecture.
```

---

#### Divergence #2 and #3 / §3b, §5a, §6a: Thread safety

**Correction to the audit framing:** After reading the actual Python audio
pipeline, the threading architecture is equivalent to Swift in every way that
matters. Both run tap detection on the main thread; both return from the hardware
callback immediately; both use a background thread for FFT computation.

| Stage | Swift | Python |
|-------|-------|--------|
| Hardware callback | CoreAudio thread → `audioProcessingQueue.async` | PortAudio thread → `queue.put()` |
| FFT computation | `audioProcessingQueue` (background) | `_FftProcessingThread` (QThread) |
| Delivery to tap detection | `DispatchQueue.main.async { magnitudes = db }` → Combine fires | `fftFrameReady.emit()` → Qt `QueuedConnection` → main thread |
| Tap detection runs on | Main thread | Main thread (`on_fft_frame`) |

The `Thread.isMainThread` guards in `AnnotationManagement` and
`ModeOverrideManagement` are defensive measures for callers outside the audio
path (e.g. gesture handlers from a non-main context). They are not evidence of
a threading gap in the audio pipeline itself. Python does not need equivalent
guards because `on_fft_frame` is already guaranteed to run on the main thread
via Qt's `QueuedConnection`.

**The FFT frame rate is identical in both implementations.** Swift requests
1024-sample hardware tap buffers but accumulates them in `inputBuffer` until
`fftSize` samples (16384) are collected before firing the FFT. Python uses a
16384-sample PortAudio `chunksize` that fills the ring buffer in one callback.
Both fire one FFT per 16384 samples (~371 ms at 44.1 kHz). The apps report
the same frame rate because it is the same.

**The two real audio pipeline differences are:**

1. **Raw sample handler granularity:** Swift calls `rawSampleHandler` every
   1024 samples (~23 ms); Python calls `raw_sample_handler` every 16384
   samples (~371 ms). This makes Swift's pre-roll buffer 16× finer-grained
   at the moment of tap detection. Reducing Python's `chunksize` to 1024
   would match Swift without changing the FFT frame rate.

2. **RMS level meter update rate:** `inputLevelDB` updates at ~43 Hz in
   Swift (every 1024-sample callback); `rmsLevelChanged` updates at ~2.7 Hz
   in Python (every 16384-sample chunk). This affects the plate/brace tap
   detection path, which uses RMS level for its threshold comparison.
   Guitar mode uses FFT peak magnitude — no difference there.

See `AUDIO_PIPELINE_ANALYSIS.md` for the full side-by-side analysis.

**No threading fixes needed.** The `QMutex` recommendation in the original
audit was based on an incorrect reading of the pipeline.

---

#### Divergence #7 / §7a material spectrum properties not Published

**Why accepted:** `longitudinalSpectrum`, `crossSpectrum`, `longitudinalPeaks`,
`crossPeaks` etc. are not `Published` in Python because the reactive mechanism that
made them Published in Swift (SwiftUI observing them) does not exist in the Python
architecture. They are already present as plain instance attributes, which is correct.

---

#### Divergence #11 / §13: `comparisonSpectra` structure

**Impact:** Swift uses a single 4-tuple array; Python uses two separate lists.
Not a correctness gap if the data is equivalent. However, round-trip file
compatibility could be affected if comparison data is serialised differently.

**What to do:** Audit whether comparison data is written to the `.guitartap` file
format. If yes, unify the structure. If no, add a comment noting the structural
difference and that it is view-internal.

---

#### Divergences #12 and #13 / §8: PDF export source differences

**Impact:** Swift reads `guitarBodyLength`, `guitarBodyWidth`, `plateStiffness`,
`plateStiffnessPreset` from live `TapDisplaySettings`. Python reads them from the
measurement snapshot. These could differ if the user changes settings after taking
a measurement but before exporting.

**What to do:** Audit whether this is user-visible. If the "export PDF" action
always occurs in the same session as the measurement (no loading of old
measurements then re-exporting), the difference is not observable. Document the
divergence in a comment in `_on_export_pdf`. Fix only if a real user scenario
produces different output.

---

#### Divergences #15, #16, #17: Extra/missing methods

- `exportMeasurement` — absent from Python; the equivalent is in the view. Low
  priority; add to `MeasurementManagementMixin` only if it simplifies the view
  materially.
- `delete_all_measurements` — extra in Python, not in Swift. Harmless; keep it.
- `set_measurement_complete` — extra in Python. Document that this replaces Swift's
  `@Published isMeasurementComplete` + `didSet` approach.

---

## Implementation order

| Step | Action | Divergences closed |
|------|---------|-------------------|
| 1 | Remove `ObservableObject` base class and `Published` descriptors; replace with plain attributes; remove `swiftui_compat` dependency | — (cleanup, not a divergence) |
| 2 | Fix `recalculate_frozen_peaks_if_needed()` call on threshold change | #8 |
| 3 | Fix `cycle_annotation_visibility()` persistence and make it the sole call site | #10 |
| 4 | Move `load_measurement()` to the model layer | #5, #6 (partially) |
| 5 | Move measurement file I/O to the model layer | #14 |
| 6 | Move settings persistence (`peak_threshold`, `tap_detection_threshold`, `hysteresis_margin`) to model layer | #9 |
| 7 | Replace `identified_modes` dict with `IdentifiedMode` named tuple | #1 |
| 8 | Audit and document comparison data serialisation | #11 |
| 9 | Audit and document PDF export source difference | #12, #13 |
| 10 | Add thread-safety comments to annotation and mode override methods | #2, #3 |

Steps 1–3 are small, safe, and independently releasable.
Steps 4–6 are larger refactors; do them together since they all touch
`TapToneAnalyzerMeasurementManagementMixin` and the view's `_restore_measurement`.
Steps 7–10 are documentation or audit tasks.

---

## Traceability conventions going forward

To maintain long-term Swift ↔ Python traceability without imposing a framework:

1. **File correspondence:** Each Python mixin file corresponds to one Swift
   extension file. New Swift extensions get a new Python mixin. Name mapping:
   `TapToneAnalyzer+Foo.swift` ↔ `tap_tone_analyzer_foo.py`.

2. **Property name mapping:** Python property names are `snake_case` of the Swift
   `camelCase` name. Do not rename unless the Swift name changes.

3. **Method-level comments:** For any method that deviates structurally from its
   Swift counterpart (different layer, different parameter shape), add a comment:
   ```python
   # Swift equivalent: TapToneAnalyzer.loadMeasurement(_:) (TapToneAnalyzer.swift:340)
   # Structural difference: [one sentence explaining why]
   ```

4. **`didSet` equivalents:** Wherever Swift uses a `didSet` observer for a side
   effect, the Python equivalent (wherever it lives) gets a comment:
   ```python
   # mirrors peakThreshold.didSet in Swift
   ```

5. **Layer differences:** If a method belongs in the model in Swift but the view
   in Python (or vice versa), document it at the method definition, not just in
   this plan. Future porters will read the code, not the plans folder.
