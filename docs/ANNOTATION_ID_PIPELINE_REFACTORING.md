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

## Complication: the loaded-measurement path

`tap_tone_analyzer_analysis_helpers._emit_loaded_peaks_at_threshold` currently
works with `loaded_measurement_peaks`, which is a plain ndarray (loaded from a
saved file — no `ResonantPeak` objects exist). This path must either:

**Option A (preferred):** Reconstruct `ResonantPeak` objects from the ndarray rows
when loading a measurement, so `loaded_measurement_peaks` becomes `list[ResonantPeak]`
rather than an ndarray. This gives full parity and means IDs exist for loaded peaks too.

**Option B (fallback):** Emit an empty list for the loaded-measurement path and
keep those annotations frequency-keyed. Simpler but incomplete parity.

Option A is preferred — it closes the gap entirely.

---

## Files to Change

| File | Change |
|---|---|
| `models/tap_tone_analyzer.py` | Change `peaksChanged` signal comment; update `loaded_measurement_peaks` type annotation |
| `models/tap_tone_analyzer_peak_analysis.py` | Emit `final_peaks` (list[ResonantPeak]) directly instead of building ndarray first |
| `models/tap_tone_analyzer_spectrum_capture.py` | Emit `peaks` (list[ResonantPeak]) directly instead of ndarray |
| `models/tap_tone_analyzer_analysis_helpers.py` | Reconstruct ResonantPeak objects from ndarray rows; emit list[ResonantPeak] |
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

### 3. `tap_tone_analyzer_analysis_helpers.py` — reconstruct ResonantPeak objects

`loaded_measurement_peaks` is currently an ndarray loaded from file. At the point
where peaks are loaded into the analyzer, reconstruct `ResonantPeak` objects so
that `_emit_loaded_peaks_at_threshold` can emit a proper list:

```python
# In _emit_loaded_peaks_at_threshold (or at load time):
from models.resonant_peak import ResonantPeak
peaks_list = [
    ResonantPeak(frequency=float(row[0]), magnitude=float(row[1]),
                 quality=float(row[2]) if len(row) > 2 else 0.0)
    for row in filtered_rows
]
self.current_peaks = peaks_list
self.peaksChanged.emit(peaks_list)
```

Note: `ResonantPeak.__init__` assigns a fresh UUID to each object. For loaded
measurements the IDs are ephemeral (they don't persist across loads), but that
is acceptable — annotation offsets for loaded measurements are keyed by the
IDs assigned at load time, which is consistent within a session.

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
