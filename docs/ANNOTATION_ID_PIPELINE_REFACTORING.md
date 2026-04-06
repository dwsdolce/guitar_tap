# Annotation Offset Key: Frequency → Peak ID Refactoring

## Goal

Achieve Swift parity: `peaksChanged` carries `list[ResonantPeak]` (objects all the
way through), so peak IDs flow naturally to every consumer — exactly mirroring
Swift's `@Published var currentPeaks: [ResonantPeak]`.

The original problem (`TypeError` in `annotation_moved` because `update_annotation_offset`
expects a UUID string key but was receiving a float frequency) is a symptom of the
deeper mismatch: the view pipeline strips identity at the signal boundary by
converting peaks to an ndarray before emitting.

---

## Current State (before this refactor)

```
peaksChanged: QtCore.Signal = QtCore.Signal(object)   # carries ndarray (N×3)
```

Every consumer indexes into `peaks[:, 0]` (freq), `peaks[:, 1]` (mag) etc.
Identity (`ResonantPeak.id`) is lost at the emit site.

## Target State (Swift parity)

```
peaksChanged: QtCore.Signal = QtCore.Signal(object)   # carries list[ResonantPeak]
```

Consumers receive the full `ResonantPeak` objects and access `.frequency`,
`.magnitude`, `.quality`, `.id` as attributes — matching how Swift's
`SpectrumView` and `TapAnalysisResultsView` consume `currentPeaks: [ResonantPeak]`.

---

## Loaded-measurement path: Swift parity

In Swift, `loadMeasurement(_:)` simply does:

```swift
currentPeaks = measurement.peaks   // [ResonantPeak] decoded from JSON with original UUIDs
```

`ResonantPeak` is `Codable` and its `id: UUID` is encoded and decoded faithfully —
loaded peaks carry their **persisted** UUIDs, not fresh ones. The same peaks that
were annotated and saved will have the same IDs on reload, so `peakAnnotationOffsets`
lookups work across sessions.

Python's equivalent is: `loaded_measurement_peaks` must be stored as
`list[ResonantPeak]` (decoded from the `.guitartap` JSON file), not as a plain ndarray.
The Python `TapToneMeasurement` model already decodes `peaks` as a list of dicts;
those dicts must be converted to `ResonantPeak` objects (with their saved UUIDs)
at load time, not at emit time.

This means the load path (`load_open_measurement` / `_load_measurement_from_file`)
is responsible for constructing `ResonantPeak` objects from the decoded JSON data
and storing them in `loaded_measurement_peaks: list[ResonantPeak]`.
`_emit_loaded_peaks_at_threshold` then filters that list by threshold and emits it —
no reconstruction needed at emit time.

---

## Files to Change

| File | Change |
|---|---|
| `models/tap_tone_analyzer.py` | Change `peaksChanged` signal comment; update `loaded_measurement_peaks` type annotation to `list[ResonantPeak] \| None` |
| `models/tap_tone_analyzer_peak_analysis.py` | Emit `final_peaks` (list[ResonantPeak]) directly instead of building ndarray first |
| `models/tap_tone_analyzer_spectrum_capture.py` | Emit `peaks` (list[ResonantPeak]) directly instead of ndarray |
| `models/tap_tone_analyzer_analysis_helpers.py` | Filter `loaded_measurement_peaks` (now list[ResonantPeak]) by threshold; emit filtered list directly |
| `models/tap_tone_analyzer_measurement_management.py` (or wherever measurements are loaded) | Construct `ResonantPeak` objects with persisted UUIDs from decoded JSON when setting `loaded_measurement_peaks` |
| `views/fft_canvas.py` | Update `peaksChanged` signal declaration; update `_on_peaks_changed_scatter` to use `.frequency`/`.magnitude` attributes; update `_current_peaks` type and all its usages |
| `views/shared/peaks_model.py` | Update `update_data` to accept `list[ResonantPeak]`; store peak IDs; update `annotationUpdate` signal to `(str, float, float, str, str)` prepending peak_id; update all `annotationUpdate.emit` call sites |
| `views/shared/peak_card_widget.py` | Update `update_data` to accept `list[ResonantPeak]` and forward peak IDs to model |
| `views/peak_annotations.py` | Update `update_annotation` signature to accept `peak_id: str` as first param; store `"peak_id"` in dict; use `peak_id` for offset lookup and `update_annotation_offset` call |
| `views/tap_tone_analysis_view.py` | Update `_on_peaks_changed_results` and `_refresh_results_peaks` to work with list[ResonantPeak]; update `_on_peaks_changed_ratios`; update `update_peaks` (material widget) |

---

## Detailed Changes

### 1. `tap_tone_analyzer_peak_analysis.py` — emit list directly

```python
# Before:
self.current_peaks = final_peaks
if final_peaks:
    arr = _np.array([[p.frequency, p.magnitude, p.quality] for p in final_peaks], ...)
else:
    arr = _np.zeros((0, 3), ...)
self.peaksChanged.emit(arr)

# After:
self.current_peaks = final_peaks
self.peaksChanged.emit(final_peaks)   # list[ResonantPeak] — mirrors Swift currentPeaks
```

### 2. `tap_tone_analyzer_spectrum_capture.py` — emit list directly

Same pattern: remove the ndarray build, emit `peaks` (already a `list[ResonantPeak]`).

### 3. Load path — construct `ResonantPeak` objects with persisted UUIDs

The Python `TapToneMeasurement` decodes `peaks` from JSON as a list of dicts.
At load time (in the measurement-loading code), convert those dicts to `ResonantPeak`
objects **using the saved UUID from each dict** — mirroring Swift's `Codable` decode:

```python
from models.resonant_peak import ResonantPeak
import uuid
loaded_peaks = [
    ResonantPeak(
        id=str(d["id"]),          # preserve the saved UUID — same as Swift Codable decode
        frequency=float(d["frequency"]),
        magnitude=float(d["magnitude"]),
        quality=float(d.get("quality", 0.0)),
        ...
    )
    for d in measurement_dict["peaks"]
]
self.loaded_measurement_peaks = loaded_peaks
```

`_emit_loaded_peaks_at_threshold` then simply filters by threshold and emits:

```python
filtered = [p for p in self.loaded_measurement_peaks if p.magnitude >= threshold]
self.current_peaks = filtered
self.peaksChanged.emit(filtered)
```

This gives full parity: annotation offsets survive save/load cycles because the
IDs are stable across sessions, exactly as in Swift.

### 4. `fft_canvas.py` — update scatter plot consumer

```python
# Signal declaration:
peaksChanged: QtCore.Signal = QtCore.Signal(object)   # now list[ResonantPeak]

# _on_peaks_changed_scatter:
def _on_peaks_changed_scatter(self, peaks) -> None:
    if peaks:
        self._current_peaks = peaks   # list[ResonantPeak]
        freqs = [p.frequency for p in peaks]
        mags  = [p.magnitude for p in peaks]
        self.points.setData(x=freqs, y=mags, brush=self._peak_brushes(freqs))
    else:
        self._current_peaks = []
        self.points.setData(x=[], y=[])
```

`_current_peaks` type changes from `np.ndarray` to `list[ResonantPeak]`.
All existing usages of `self._current_peaks[:, 0]` / `[:, 1]` must be updated
to list comprehensions.

### 5. `peaks_model.py` — accept list[ResonantPeak], thread IDs through annotationUpdate

```python
# Signal:
annotationUpdate: QtCore.Signal = QtCore.Signal(str, float, float, str, str)
#                                                id   freq  mag   html  mode

# update_data:
def update_data(self, peaks: list) -> None:   # list[ResonantPeak]
    self._peaks = peaks   # store objects
    data = np.array([[p.frequency, p.magnitude, p.quality] for p in peaks], ...) if peaks else np.zeros((0,3))
    self._data = data
    ...
    for row in range(self._data.shape[0]):
        peak_id = peaks[row].id if row < len(peaks) else ""
        ...
        self.annotationUpdate.emit(peak_id, freq, mag, html, mode)
```

`set_annotation_mode` self-call must re-pass `self._peaks`.

### 6. `peak_card_widget.PeakListWidget.update_data` — forward list

```python
def update_data(self, peaks: list) -> bool:   # list[ResonantPeak]
    self._last_peaks = peaks
    self.model.update_data(peaks)
    data = np.array([[p.frequency, p.magnitude, p.quality] for p in peaks], ...) if peaks else np.zeros((0,3))
    self._rebuild_cards(data)
    ...
```

### 7. `peak_annotations.py` — accept peak_id in update_annotation; use it for offset

```python
# Before:
def update_annotation(self, freq, mag, html, mode_str): ...
    saved = self._analyzer.peak_annotation_offsets.get(freq)
    ...  # dict stores no "peak_id"
# In annotation_moved:
    self._analyzer.update_annotation_offset(ann_dict["freq"], (x, y))

# After:
def update_annotation(self, peak_id: str, freq, mag, html, mode_str): ...
    saved = self._analyzer.peak_annotation_offsets.get(peak_id) if peak_id else None
    ...  # dict stores "peak_id": peak_id
# In annotation_moved:
    self._analyzer.update_annotation_offset(ann_dict["peak_id"], (x, y))
```

### 8. `tap_tone_analysis_view.py` — update all three peaksChanged consumers

`_on_peaks_changed_results` / `_refresh_results_peaks`: filter by frequency range
using list comprehension on `p.frequency`; pass filtered `list[ResonantPeak]` to
`peak_widget.update_data`.

`_on_peaks_changed_ratios`: build `peaks_data` from `[(p.frequency, p.magnitude) for p in peaks]`.

`update_peaks` (material widget): already builds `(freq, mag)` tuples — update to
read from `p.frequency` / `p.magnitude`.

---

## Connection wiring (no change needed)

`model.annotationUpdate.connect(canvas.annotations.update_annotation)` uses a
signal→slot connection matched by position. As long as both sides agree on the new
`(str, float, float, str, str)` shape, no wiring change is needed.

---

## What Does Not Need to Change

- `peaksChanged` signal type tag (`object`) — Qt `object` carries any Python type.
- `hideAnnotation(float)` / `showAnnotation(float)` — display-only, frequency-keyed. No change.
- `find_annotation_index(freq)` — internal display lookup. No change.
- `FftAnnotations.annotation_reset()` — clears whole dict. No change.
- `PEAK_PROXIMITY_HZ`, `find_peaks` algorithm internals — analysis logic unchanged.

---

## Implementation Steps

> **Status: COMPLETE** — All 9 steps implemented and verified. 215/215 tests passing.
> Test `test_PRA3` / `test_PRA4` in `test_frozen_peak_recalculation.py` updated to use
> `ResonantPeak` objects (were setting `loaded_measurement_peaks` to a raw ndarray).

Changes are ordered so that signal producers are updated before consumers, keeping
the app in a runnable state after each step. Steps 1–4 are model/emit-site changes;
steps 5–9 are view-consumer changes.

1. ✅ **Load path** (`tap_tone_analyzer_measurement_management.py`): Convert decoded
   JSON peak dicts to `ResonantPeak` objects with persisted UUIDs when setting
   `loaded_measurement_peaks`. Update type annotation in `tap_tone_analyzer.py`
   from `np.ndarray | None` to `list[ResonantPeak] | None`.

2. ✅ **`tap_tone_analyzer_analysis_helpers.py`** — `_emit_loaded_peaks_at_threshold`:
   Replace ndarray threshold-filter with list comprehension on `p.magnitude`;
   emit the filtered `list[ResonantPeak]`.

3. ✅ **`tap_tone_analyzer_peak_analysis.py`** — `find_peaks` emit block:
   Remove ndarray construction; emit `final_peaks` (`list[ResonantPeak]`) directly.
   Update `peaksChanged` signal comment in `tap_tone_analyzer.py`.

4. ✅ **`tap_tone_analyzer_spectrum_capture.py`** — `_emit_peaks_array` (or inline emit):
   Remove ndarray construction; emit `peaks` (`list[ResonantPeak]`) directly.

5. ✅ **`views/fft_canvas.py`** — scatter plot consumer:
   Change `_current_peaks` from `np.ndarray` to `list[ResonantPeak]` (init to `[]`).
   Update `_on_peaks_changed_scatter` to use list comprehensions for `freqs`/`mags`.
   Update all other `_current_peaks[:, 0]` / `[:, 1]` usages to list comprehensions.

6. ✅ **`views/shared/peaks_model.py`** — model and annotationUpdate signal:
   Change `annotationUpdate` signal from `(float, float, str, str)` to
   `(str, float, float, str, str)` adding `peak_id` as first arg.
   Update `update_data` to accept `list[ResonantPeak]`; store as `self._peaks`;
   build internal ndarray from the list for existing display logic.
   Prepend `peak_id` to every `annotationUpdate.emit` call.
   Ensure `set_annotation_mode` re-passes `self._peaks` to `update_data`.

7. ✅ **`views/shared/peak_card_widget.py`** — `PeakListWidget.update_data`:
   Change signature to accept `list[ResonantPeak]`; store as `self._last_peaks`;
   forward to `self.model.update_data(peaks)`; build display ndarray from the list.

8. ✅ **`views/peak_annotations.py`** — `update_annotation` and `annotation_moved`:
   Add `peak_id: str` as first parameter to `update_annotation`.
   Store `"peak_id"` in each annotation dict.
   Use `peak_id` for `peak_annotation_offsets` lookup and `update_annotation_offset` call.

9. ✅ **`views/tap_tone_analysis_view.py`** — three `peaksChanged` consumers:
   `_on_peaks_changed_results` / `_refresh_results_peaks`: filter by `p.frequency`;
   pass filtered `list[ResonantPeak]` to `peak_widget.update_data`.
   `_on_peaks_changed_ratios`: replace ndarray indexing with list comprehension.
   `update_peaks` (material widget): read `p.frequency` / `p.magnitude` from objects.
