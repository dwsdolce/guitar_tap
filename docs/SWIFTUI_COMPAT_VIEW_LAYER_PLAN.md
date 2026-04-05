# SwiftUI-Compat View Layer Plan

## Context

This document is the follow-on to `PYTHON_ARCHITECTURE_RESTRUCTURING_PLAN.md`.

That plan covers the **model layer**: replacing `pyqtSignal` with `ObservableObject`/`Published`,
merging `TapDetector`/`DecayTracker` into `TapToneAnalyzer`, stabilising `ResonantPeak` UUIDs,
and aligning all property names with Swift.

This document covers the **view layer**: replacing the PyQt6 widget hierarchy with
[pyedifice](https://pyedifice.github.io/) views written against the
`swiftui_compat` shim, so that Python view code is a near-1:1 port of the Swift/SwiftUI
views — same class names, same property declarations, same body structure.

The goal remains unchanged:

> Make the Python codebase a faithful mirror of the Swift architecture: same class shapes,
> same property names, same method signatures, same reactive patterns, same state ownership.

---

## Prerequisites

The view-layer rewrite **depends on the model-layer restructuring being complete**:

- `TapToneAnalyzer` must already be an `ObservableObject` with `Published` properties.
- `ResonantPeak` must carry a stable `str` UUID.
- `TapDisplaySettings` must live in the model layer (no model→view imports).
- All `pyqtSignal` / `.emit()` / `.connect()` calls must be gone from models.

Do not start this work until those conditions are met and the model-layer tests pass.

---

## What swiftui_compat Provides

`swiftui_compat` (`/Users/dws/src/swiftui_compat`) is a thin shim on top of pyedifice 5.0
that maps SwiftUI patterns to Python:

| Swift / SwiftUI | Python / swiftui_compat |
|---|---|
| `@State var x = 0` | `x = State(0)` |
| `@Binding var x: T` | `x = Binding(T)` |
| `@Published var x = v` | `x = Published(v)` (on `ObservableObject`) |
| `class Foo: ObservableObject` | `class Foo(ObservableObject)` |
| `@ObservedObject var foo: Foo` | `foo = ObservedObject(Foo)` |
| `@StateObject var foo = Foo()` | `foo = StateObject(Foo)` |
| `@EnvironmentObject var foo: Foo` | `foo = EnvironmentObject(Foo)` |
| `struct MyView: View { var body: … }` | `class MyView(View): @property def body` |
| `VStack { … }` | `with VStack(spacing=8): …` |
| `HStack { … }` | `with HStack(spacing=8): …` |
| `ForEach(items) { … }` | `ForEach(data=items, builder=lambda …)` |

Key porting rules are documented in
`/Users/dws/src/swiftui_compat/README.md` (sections 1–11).

---

## Architecture Overview

### Before (PyQt6)

```
MainWindow (QMainWindow)
  ├── FftCanvas (pg.PlotWidget subclass)       ← 1,500 lines, imperative
  ├── PeaksModel (QAbstractTableModel)
  ├── FftAnnotations (manages pg.TextItem)
  └── [signals wired in _connect_signals()]    ← 4,975-line file
```

State flow: `TapToneAnalyzer` emits `pyqtSignal` → `MainWindow._connect_signals()` routes
them → widgets update imperatively.

### After (pyedifice + swiftui_compat)

```
TapToneAnalysisView (View)
  ├── analyzer = StateObject(TapToneAnalyzer)
  ├── TapToneAnalysisView+Controls body section
  ├── TapToneAnalysisView+SpectrumViews body section
  │     └── SpectrumView (View)
  │           └── FftCanvas widget (pyqtgraph, imperative escape hatch)
  ├── TapToneAnalysisView+Layouts body section
  └── [no explicit signal wiring — ObservedObject triggers re-render]
```

State flow: `TapToneAnalyzer.Published` property changes → `ObservedObject` subscription
fires → pyedifice schedules re-render → view reads current state from model → UI updated.

---

## File-by-File Mapping

### New view files (pyedifice) ↔ Swift originals

| Python file (new) | Swift original | Notes |
|---|---|---|
| `views/tap_tone_analysis_view.py` | `TapToneAnalysisView.swift` + extensions | Root view; owns `StateObject(TapToneAnalyzer)` |
| `views/tap_tone_analysis_view_controls.py` | `TapToneAnalysisView+Controls.swift` | Controls bar: start/pause/cancel, threshold, guitar type |
| `views/tap_tone_analysis_view_layouts.py` | `TapToneAnalysisView+Layouts.swift` | Layout helpers, sidebar/canvas split |
| `views/tap_tone_analysis_view_spectrum_views.py` | `TapToneAnalysisView+SpectrumViews.swift` | Embeds `SpectrumView` |
| `views/tap_tone_analysis_view_actions.py` | `TapToneAnalysisView+Actions.swift` | Button action handlers |
| `views/tap_tone_analysis_view_export.py` | `TapToneAnalysisView+Export.swift` | Export sheet wiring |
| `views/spectrum_view.py` | `SpectrumView.swift` | Embeds pyqtgraph canvas as escape hatch |
| `views/spectrum_view_gesture_handlers.py` | `SpectrumView+GestureHandlers.swift` | Click/drag event forwarding |
| `views/spectrum_view_snap_interpolation.py` | `SpectrumView+SnapInterpolation.swift` | Frequency snap logic |
| `views/peak_annotations.py` | `PeakAnnotations.swift` | Annotation overlay; pyqtgraph `DraggableTextItem` remains |
| `views/fft_analysis_metrics_view.py` | `FFTAnalysisMetricsView.swift` | Metrics panel |
| `views/tap_analysis_results_view.py` | `TapAnalysisResultsView.swift` | Results sheet |
| `views/save_measurement_sheet.py` | `SaveMeasurementSheet.swift` | Save dialog |
| `views/help_view.py` | `HelpView.swift` | Help panel |
| `views/measurements/measurements_list_view.py` | `MeasurementsListView.swift` | Measurements list |
| `views/measurements/measurement_row_view.py` | `MeasurementRowView.swift` | Single row |
| `views/measurements/measurement_detail_view.py` | `MeasurementDetailView.swift` | Detail sheet |
| `views/measurements/edit_measurement_view.py` | `EditMeasurementView.swift` | Edit sheet |
| `views/shared/combined_peak_mode_row_view.py` | `CombinedPeakModeRowView.swift` | Peak + mode row |
| `views/shared/compact_fft_metrics_overlay.py` | `CompactFFTMetricsOverlay.swift` | Compact overlay |
| `views/utilities/tap_settings_view.py` | `TapSettingsView.swift` + extensions | Settings panel |

### Files retained as-is (imperative escape hatches)

| File | Reason |
|---|---|
| `views/fft_canvas.py` (`FftCanvas` / `pg.PlotWidget`) | pyqtgraph canvas; imperative update loop is correct for real-time FFT |
| `views/peak_annotations.py` (`DraggableTextItem`) | `pg.TextItem` with `ItemIsMovable` flag; must remain imperative |
| `views/shared/peaks_model.py` (`PeaksModel` / `QAbstractTableModel`) | No pyedifice equivalent for a Qt table model; keep and embed |

These files are embedded inside pyedifice views using pyedifice's `CustomWidget` or
`child_place` mechanism. The declarative tree owns their lifetime; they remain imperative
internally.

---

## Key Patterns

### 1. Root view owns the analyzer

```python
# Python — mirrors Swift TapToneAnalysisView exactly
class TapToneAnalysisView(View):
    analyzer = StateObject(TapToneAnalyzer)   # owns lifetime, subscribes to changes

    @property
    def body(self):
        with VStack():
            ControlsView(analyzer=self.analyzer)
            SpectrumView(analyzer=self.analyzer)
```

```swift
// Swift equivalent
struct TapToneAnalysisView: View {
    @StateObject var analyzer = TapToneAnalyzer(fftAnalyzer: RealtimeFFTAnalyzer())
    var body: some View {
        VStack {
            ControlsView(analyzer: analyzer)
            SpectrumView(analyzer: analyzer)
        }
    }
}
```

### 2. Child views receive the analyzer via ObservedObject

```python
class ControlsView(View):
    analyzer = ObservedObject(TapToneAnalyzer)

    @property
    def body(self):
        a = self.analyzer
        with HStack():
            Button(title="Start", on_click=lambda _: a.start_tap_sequence())
            Button(title="Reset", on_click=lambda _: a.reset())
            Label(text=f"Taps: {a.current_tap_count}/{a.number_of_taps}")
```

When `a.current_tap_count` changes (via `Published`), `ObservedObject`'s subscription
fires and pyedifice re-renders `ControlsView`. No explicit signal connection needed.

### 3. FftCanvas embedded as an escape hatch

pyedifice's `CustomWidget` wraps an existing `QWidget` so it participates in the
declarative tree. `FftCanvas` is passed the current analyzer on first render; subsequent
re-renders call an `update(analyzer)` method:

```python
from edifice import CustomWidget

class SpectrumView(View):
    analyzer = ObservedObject(TapToneAnalyzer)

    @property
    def body(self):
        a = self.analyzer
        # FftCanvas is a pg.PlotWidget subclass — kept imperative
        CustomWidget(
            make_component=lambda: FftCanvas(analyzer=a),
            update_component=lambda canvas, _: canvas.update_from_analyzer(a),
        )
```

`FftCanvas.update_from_analyzer(analyzer)` replaces the old signal-driven `_on_peaks_changed`,
`_on_spectrum_updated`, etc. handlers. It is called on every re-render triggered by
`analyzer`'s `Published` changes.

### 4. DraggableTextItem annotations unchanged

`DraggableTextItem` and `FftAnnotations` remain as pyqtgraph imperative code.
`SpectrumView` calls `self.canvas.annotations.update(analyzer.current_peaks,
analyzer.peak_annotation_offsets)` inside `update_from_analyzer`. No re-architecture needed.

### 5. PeaksModel embedded via CustomWidget

```python
class PeakTableView(View):
    analyzer = ObservedObject(TapToneAnalyzer)

    @property
    def body(self):
        a = self.analyzer
        # PeaksModel is a QAbstractTableModel — kept as-is, embedded here
        CustomWidget(
            make_component=lambda: _build_peaks_table_widget(a),
            update_component=lambda widget, _: widget.model().refresh(a.current_peaks),
        )
```

### 6. State that belongs on the view, not the analyzer

Some UI state (scroll position, selected tab, whether a sheet is open) is view-local and
should use `State`, not `Published` on the analyzer:

```python
class TapToneAnalysisView(View):
    analyzer = StateObject(TapToneAnalyzer)
    is_settings_shown = State(False)           # view-local: no Swift equivalent needed
    is_measurements_shown = State(False)

    @property
    def body(self):
        with VStack():
            ...
            if self.is_settings_shown:
                TapSettingsView(analyzer=self.analyzer)
```

---

## Handling the Annotation Drag + Persistence Loop

In the current PyQt6 code, dragging an annotation calls
`analyzer.update_annotation_offset(peak_id, offset)` (after the model-layer rewrite).
Since `peak_annotation_offsets` is a `Published` property, this triggers a re-render.
The re-render calls `FftAnnotations.update(...)` which re-positions the labels from
the stored offsets.

This is a tight loop:
1. User drags → `update_annotation_offset` → `Published` fires → re-render →
   `FftAnnotations.update` reads offsets → sets label positions → done.

No special handling needed; the reactive loop terminates because
`FftAnnotations.update` only sets positions, it does not call `update_annotation_offset`.

---

## Migration Sequence

The view-layer migration should follow the model-layer migration sequence from
`PYTHON_ARCHITECTURE_RESTRUCTURING_PLAN.md`. Within the view layer:

1. **Install pyedifice and swiftui_compat** as dependencies. Add to `requirements.txt`:
   ```
   edifice>=5.0.0
   swiftui_compat  # editable install from /Users/dws/src/swiftui_compat
   ```

2. **Port leaf views first** — `FFTAnalysisMetricsView`, `SaveMeasurementSheet`,
   `HelpView`. These have no pyqtgraph dependency and map cleanly to
   pyedifice labels/buttons. Validate each runs standalone with a stub analyzer.

3. **Port the measurements views** — `MeasurementsListView`, `MeasurementRowView`,
   `MeasurementDetailView`, `EditMeasurementView`. These are pure data-display views
   with no audio dependency.

4. **Port `TapSettingsView`** — settings panel driven by `TapDisplaySettings`.

5. **Port `ControlsView` and metrics panel** — depend on `TapToneAnalyzer.Published`
   properties; requires model-layer restructuring to be done.

6. **Wrap `FftCanvas` in `SpectrumView`** — the hardest boundary. Keep `FftCanvas`
   entirely intact; write a thin `SpectrumView` that owns it via `CustomWidget` and
   forwards analyzer state on each re-render.

7. **Port `TapToneAnalysisView` root** — assemble the full layout from the ported
   sub-views. At this point the PyQt6 `MainWindow` can be retired.

8. **Delete `MainWindow._connect_signals()`** — all signal wiring is replaced by
   `ObservedObject` subscriptions. If any `.connect()` calls remain, they indicate
   an unconverted view.

---

## What Does NOT Change

- `FftCanvas` internals (pyqtgraph plot items, cursor crosshair, threshold lines).
- `DraggableTextItem` and `FftAnnotations` internals.
- `PeaksModel` (`QAbstractTableModel`) — table view keeps its Qt model.
- All model-layer files (`models/`) — this plan is view-only.
- `RealtimeFFTAnalyzer` — pure audio/DSP, not a view concern.
- Audio processing thread — not a view concern.
- File export / PDF generation — utility functions, not views.

---

## Known Constraints and Workarounds

### pyedifice change-detection uses `!=`

Edifice compares props with `!=` to decide whether to re-render. This has two consequences:

1. **numpy arrays must not be passed as props.** Read them inside closures.
   Documented in `swiftui_compat` README porting note 11.

2. **Mutable objects passed as props won't trigger re-renders on mutation.**
   Always replace collection elements with new instances (porting note 8).
   `TapToneAnalyzer`'s `Published` setter handles this automatically when the
   property is reassigned; views that receive the whole analyzer object via
   `ObservedObject` re-render whenever any `Published` property changes.

### pyedifice has no `QAbstractTableModel` equivalent

`PeaksModel` stays as a `QAbstractTableModel` and is embedded via `CustomWidget`.
The `update_component` callback refreshes the model on each re-render.

### `provide_context` / `EnvironmentObject` uses a version-counter tuple

pyedifice 5.0's `provide_context` is a hook (not a context manager) and uses string
keys. Mutable objects need to be wrapped in a `(instance, version)` tuple; call the
context setter with `lambda v: (v[0], v[1] + 1)` after mutations to trigger
re-renders in consumers. See `swiftui_compat` README porting note 5 for the full
pattern. For GuitarTap, `TapToneAnalyzer` is passed directly via `ObservedObject`
props (not environment context), so this pattern is only needed if a deeply-nested
view needs the analyzer without prop-drilling.

### `setattr` in lambdas

Python lambdas do not support assignment. Use `setattr(self, "name", value)` for
`State` mutations inside `on_click` lambdas. Documented in porting note 3.

---

## Validation Criteria

The view-layer migration is complete when:

- All pyedifice views render without error with a live `TapToneAnalyzer`.
- Changing `analyzer.peak_threshold` from a test triggers a visible re-render of
  `ControlsView` without any explicit `.connect()` call.
- `FftCanvas` updates its spectrum display on each `spectrumUpdated` equivalent
  (i.e. when `TapToneAnalyzer.frozen_frequencies` / `frozen_magnitudes` change).
- Dragging a peak annotation persists through `analyzer.peak_annotation_offsets`
  and survives a re-render.
- `MainWindow._connect_signals()` no longer exists.
- `from PyQt6 import …` no longer appears in any `views/` file except
  `fft_canvas.py`, `peak_annotations.py`, and `views/shared/peaks_model.py`.
