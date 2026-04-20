# Views Layer Structural Divergence Audit: Swift ↔ Python

**Methodology**: Every section below is derived directly from reading all Swift `Views/` files and all
Python `views/` files side-by-side. No section was carried forward from memory — source files were
read directly before findings were written.

**Scope**: All files in the Swift `GuitarTap/Views/` tree (42 files) and all files in the Python
`views/` directory (61 files). Model files and controller files are excluded; they are covered in
the Models Structural Divergence Audit.

**Reactive-property rules applied**: Rules 1–8 from `REACTIVE_PROPERTY_AUDIT_GUIDELINES.md`.

---

## §1 — File Mapping and Inventory

### §1.1 — Directory listing

**Swift Views root** (17 files):

| Swift file | Python equivalent |
|---|---|
| `TapToneAnalysisView.swift` | `tap_tone_analysis_view.py` |
| `TapToneAnalysisView+Actions.swift` | `tap_tone_analysis_view_actions.py` (stub) |
| `TapToneAnalysisView+Controls.swift` | `tap_tone_analysis_view_controls.py` (stub) |
| `TapToneAnalysisView+Export.swift` | `tap_tone_analysis_view_export.py` (stub) |
| `TapToneAnalysisView+Layouts.swift` | `tap_tone_analysis_view_layouts.py` (stub) |
| `TapToneAnalysisView+SpectrumViews.swift` | `tap_tone_analysis_view_spectrum_views.py` (stub) |
| `SpectrumView.swift` | `spectrum_view.py` + `fft_canvas.py` |
| `SpectrumView+ChartContent.swift` | `fft_canvas.py` (merged) |
| `SpectrumView+GestureHandlers.swift` | `spectrum_view_gesture_handlers.py` |
| `SpectrumView+SnapInterpolation.swift` | `spectrum_view_snap_interpolation.py` |
| `SpectrumScrollWheel.swift` | (no direct equivalent — see D-V13) |
| `TapAnalysisResultsView.swift` | `tap_analysis_results_view.py` (misclassified — see §2.1) |
| `FFTAnalysisMetricsView.swift` | `fft_analysis_metrics_view.py` |
| `PeakAnnotations.swift` | `peak_annotations.py` |
| `SaveMeasurementSheet.swift` | `save_measurement_sheet.py` |
| `ExportableSpectrumChart.swift` | `exportable_spectrum_chart.py` |
| `HelpView.swift` | `help_view.py` |

**Swift Views/Measurements** (5 files):

| Swift file | Python equivalent |
|---|---|
| `Measurements/MeasurementsListView.swift` | `measurements/measurements_list_view.py` |
| `Measurements/MeasurementDetailView.swift` | `measurements/measurement_detail_view.py` |
| `Measurements/MeasurementRowView.swift` | `measurements/measurement_row_view.py` |
| `Measurements/EditMeasurementView.swift` | `measurements/edit_measurement_view.py` |
| `Measurements/ExportView.swift` | **No Python equivalent** (see D-V20) |

**Swift Views/Shared** (3 files):

| Swift file | Python equivalent |
|---|---|
| `Shared/CombinedPeakModeRowView.swift` | `shared/combined_peak_mode_row_view.py` (re-export stub → `peak_card_widget.py`) |
| `Shared/EmptyStateView.swift` | `shared/empty_state_view.py` |
| `Shared/LoadingOverlay.swift` | `shared/loading_overlay.py` |

**Swift Views/Utilities** (5 files):

| Swift file | Python equivalent |
|---|---|
| `Utilities/TapSettingsView.swift` | `utilities/tap_settings_view.py` |
| `Utilities/Extensions.swift` | `utilities/extensions.py` |
| `Utilities/PDFReportGenerator.swift` | `tap_analysis_results_view.py` (merged in) |
| `Utilities/MeasurementFileExporter.swift` | `utilities/measurement_file_exporter.py` (re-export stub) |
| `Utilities/ResultsWindowPresenter.swift` | **No Python equivalent** (see D-V21) |
| `Utilities/AxixTickGenerator.swift` | `utilities/axis_tick_generator.py` (partial — see D-V14) |

### §1.2 — Python-only files (no Swift counterpart)

| Python file | Classification | Assessment |
|---|---|---|
| `fft_canvas.py` | Legitimate split — core pyqtgraph rendering widget split from SpectrumView | Acceptable; functionality covered. See D-V1. |
| `shared/peak_card_widget.py` | Implements `CombinedPeakModeRowView` + `PeaksModel` together | See D-V2. |
| `shared/peaks_model.py` | View-layer Qt table model (no Swift counterpart as a class) | See D-V3. |
| `utilities/platform_adapters.py` | macOS AVFoundation mic permission checking | Equivalent functionality in Swift is in `TapToneAnalysisView+Actions.swift` — pure platform bridge. Acceptable. |
| `utilities/gt_images.py` | Static icon/pixmap loader | No Swift equivalent needed — SF Symbols used in Swift. Acceptable Python-only utility. |
| `utilities/axis_tick_generator.py` | Partial port of `AxixTickGenerator.swift` | Missing functionality — see D-V14. |

### §1.3 — Extension-stub divergence (critical structural issue)

The Swift `TapToneAnalysisView` is split across 6 files using Swift extension syntax. The Python
`TapToneAnalysisView` cluster has 6 corresponding Python files, but **5 of them are stubs** — they
contain only a docstring and a `# Pending:` comment describing what code should be extracted from
`tap_tone_analysis_view.py` but has not been. All actual implementation lives monolithically in
`tap_tone_analysis_view.py`.

**Stub files confirmed empty of implementation**:
- `tap_tone_analysis_view_actions.py` — only docstring
- `tap_tone_analysis_view_controls.py` — only docstring
- `tap_tone_analysis_view_export.py` — only docstring
- `tap_tone_analysis_view_layouts.py` — only docstring
- `tap_tone_analysis_view_spectrum_views.py` — only docstring

This means the "61 Python view files" vs "42 Swift view files" count is partially explained by these stub files existing on the Python side. The stub architecture was intended as scaffolding for a planned extraction but was never completed.

**Also misclassified**: `tap_analysis_results_view.py` is NOT the Python port of
`TapAnalysisResultsView.swift`. It is the Python port of **`PDFReportGenerator.swift` +
`MeasurementFileExporter.swift`** — it contains persistence, JSON encoding, and PDF generation
logic. The actual `TapAnalysisResultsView` content is implemented inline in `MainWindow` within
`tap_tone_analysis_view.py`.

---

## §2 — TapToneAnalysisView / MainWindow

### §2.1 — Naming and classification divergence

**D-V1** | **Medium** | **Open**

`tap_analysis_results_view.py` is named after `TapAnalysisResultsView.swift` but contains the
implementation of `PDFReportGenerator.swift` and `MeasurementFileExporter.swift`. The actual
`TapAnalysisResultsView` panel is embedded directly in `MainWindow` in `tap_tone_analysis_view.py`.
This creates a naming collision that makes it difficult to find the correct file for either task.

**Affected files**:
- Swift: `Utilities/PDFReportGenerator.swift`, `Utilities/MeasurementFileExporter.swift`, `TapAnalysisResultsView.swift`
- Python: `views/tap_analysis_results_view.py`, `views/utilities/measurement_file_exporter.py`

### §2.2 — @State properties vs Python local state

Swift `TapToneAnalysisView` declares the following `@State` variables that drive UI visibility and
transient input state. Python maintains equivalent state as instance attributes on `MainWindow`.

**Full `@State` audit table**:

| Swift `@State` | Python equivalent | Classification | Status |
|---|---|---|---|
| `tapLocation: String` | `self._tap_location` (pre-filled in dialog) | View-local | ✅ |
| `notes: String` | `self._notes` (pre-filled in dialog) | View-local | ✅ |
| `isLandscape: Bool` | Not needed — single window layout | View-local (N/A) | ✅ |
| `showingSaveSheet: Bool` | Dialog shown imperatively | View-local | ✅ |
| `showingMeasurements: Bool` | Dialog shown imperatively | View-local | ✅ |
| `showingMetrics: Bool` | `self._metrics_dialog` reference | View-local | ✅ |
| `showingResults: Bool` | `self._results_panel` visibility | View-local | ✅ |
| `showingSettings: Bool` | Dialog shown imperatively | View-local | ✅ |
| `showingHelp: Bool` | Dialog shown imperatively | View-local | ✅ |
| `isExportingSpectrum: Bool` | No explicit flag — see D-V4 | View-local | ⚠ Gap |
| `isSavingMeasurement: Bool` | No explicit flag — see D-V4 | View-local | ⚠ Gap |
| `isGeneratingReport: Bool` | No explicit flag — see D-V4 | View-local | ⚠ Gap |
| `showingMicrophonePermissionAlert: Bool` | Handled in `platform_adapters.py` via `_show_denied()` | View-local | ✅ |
| `openURLImportSuccess: String?` | Partially handled — see D-V5 | View-local | ⚠ Gap |
| `openURLImportError: String?` | Partially handled — see D-V5 | View-local | ⚠ Gap |
| `minFreq: Float` | `self._fmin` | View-local | ✅ |
| `maxFreq: Float` | `self._fmax` | View-local | ✅ |
| `minDB: Float` | `self._db_min` | View-local | ✅ |
| `maxDB: Float` | `self._db_max` | View-local | ✅ |
| `minFreqInput: String` | Text field directly updated | View-local | ✅ |
| `maxFreqInput: String` | Text field directly updated | View-local | ✅ |
| `isAutoScaleEnabled: Bool` | `self._auto_scale_enabled` | View-local | ✅ |
| `crosshairMode: Bool` (iOS only) | Not applicable on macOS/Python | Platform N/A | ✅ |
| `selectedLongitudinalPeakID: UUID?` | `self._long_peak_id` | View-local | ✅ |
| `selectedCrossPeakID: UUID?` | `self._cross_peak_id` | View-local | ✅ |
| `selectedFlcPeakID: UUID?` | `self._flc_peak_id` | View-local | ✅ |
| `warningIconOpacity: Double` | Animation not replicated — see D-V6 | View-local | ⚠ Gap |

**D-V4** | **Medium** | **Open**

Swift shows a `LoadingOverlay` while `isExportingSpectrum`, `isSavingMeasurement`, or
`isGeneratingReport` is `true`. These flags are set at the start of each async operation and cleared
on completion. Python has no equivalent blocking overlay during these operations. The user cannot
tell when a slow export is in progress.

**D-V5** | **Low** | **Open**

Swift `TapToneAnalysisView` handles `Notification.Name.openMeasurementFile` (AirDrop / "Open in…")
via `.onReceive` and displays the result in `openURLImportSuccess` / `openURLImportError` status
banners. Python `MeasurementsDialog` handles file import via a menu action (`_on_import_json`) but
does not handle OS-level "open file" events (no `QApplication.instance().openFileRequest`
equivalent is wired).

**D-V6** | **Low** | **Open**

Swift `warningIconOpacity` drives a repeating `withAnimation` throb on the loaded-settings warning
icon (pulsing between 0.3 and 1.0 opacity). Python has a static warning indicator with no animation.

### §2.3 — Computed view properties (Rule 6)

The following Swift computed view properties aggregate model state that Python must reassemble
explicitly:

**D-V7** | **High** | **Open**

`cancelButtonEnabled` (Swift) is a computed view property that checks
`isInReviewPhase`, `tapToneAnalyzer.isDetecting`, `TapDisplaySettings.measurementType.isGuitar`,
`tapToneAnalyzer.numberOfTaps`, and `tapToneAnalyzer.currentTapCount` to enable/disable the
Cancel / Redo button. Python must recompute this at every signal boundary where any of these inputs
change. **No explicit Python reassembly call site is present for the plate/brace review phase
transition** — the Cancel/Redo button state is not re-evaluated when `materialTapPhase` changes to
a review phase.

| Swift computed property | `@Published` inputs consumed | Python assembly | Call site | Status |
|---|---|---|---|---|
| `cancelButtonEnabled` | `materialTapPhase`, `isDetecting`, `measurementType`, `numberOfTaps`, `currentTapCount` | Button enabled/disabled in slots | Partially — missing phase-change path | ⚠ Gap |
| `pauseResumeButtonEnabled` | `materialTapPhase`, `isDetecting`, `isDetectionPaused` | Button enabled/disabled in slots | Partially checked | ⚠ Gap |
| `newTapButtonDisabled` | `displayMode`, `fft.isRunning`, `isReadyForDetection`, `measurementType`, `isDetecting`, `isMeasurementComplete` | Partially wired | Missing `isReadyForDetection` gate | ⚠ Gap |
| `isInReviewPhase` | `materialTapPhase`, `measurementType` | Not found as explicit computed value | Used inline — needs explicit tracking | ⚠ Gap |

**D-V8** | **High** | **Open**

Swift `TapToneAnalysisView` uses `.onReceive(tap.$loadedMinFreq)` and three similar `.onReceive`
modifiers to sync `@State` axis range variables whenever a measurement is loaded. These are
**separate from the `loadMeasurement` action call** — they fire asynchronously when the model
updates its `@Published` loaded-range properties.

Python must wire `loadedAxisRangeChanged` (or equivalent) signals to update `_fmin`, `_fmax`,
`_db_min`, `_db_max` and push the new range to `fft_canvas`. The current Python
`_restore_measurement()` method does this synchronously inline, which is correct; however, if any
code path updates `loaded*` properties without calling `_restore_measurement()` the axis state will
diverge.

**Rule 6 table**:

| Swift `.onReceive` | Source `@Published` | Python equivalent slot | Status |
|---|---|---|---|
| `.onReceive(tap.$loadedMinFreq)` | `loadedMinFreq` | `_restore_measurement()` inline sync | Pull-on-signal ✅ |
| `.onReceive(tap.$loadedMaxFreq)` | `loadedMaxFreq` | Same | Pull-on-signal ✅ |
| `.onReceive(tap.$loadedMinDB)` | `loadedMinDB` | Same | Pull-on-signal ✅ |
| `.onReceive(tap.$loadedMaxDB)` | `loadedMaxDB` | Same | Pull-on-signal ✅ |
| `.onReceive(tap.$showLoadedSettingsWarning)` | `showLoadedSettingsWarning` | Warning widget visibility updated | Needs verification ⚠ |
| `.onReceive(tap.$microphoneWarning)` | `microphoneWarning` | Status bar message | Needs verification ⚠ |

### §2.4 — menuActions / AppCommands (macOS)

**D-V9** | **Medium** | **Open**

Swift `TapToneAnalysisView` declares `@State private var menuActions = MenuActions()` and injects
it into `FocusedValues` so that `AppCommands` (the global macOS menu bar) can invoke actions on the
currently focused window. Python uses `QMenuBar` actions wired directly to `MainWindow` slots. The
functional difference is that Swift's approach allows the menu to be driven by the window's focus
state, whereas Python's approach hardcodes menu items to the single main window. This is acceptable
for a single-window app but becomes a bug if multiple windows are ever added.

---

## §3 — SpectrumView / FftCanvas

### §3.1 — Structural split

Swift has `SpectrumView.swift` as the containing view struct. Python splits this into two classes:

- `SpectrumView` (in `spectrum_view.py`) — thin wrapper that holds `FftCanvas` and routes
  signals/slots.
- `FftCanvas` (in `fft_canvas.py`) — the actual pyqtgraph `PlotWidget` subclass that handles all
  rendering, gesture handling, annotation drawing, and spectrum updates.

This split is the correct approach for Qt (a `QWidget` cannot be a SwiftUI view) and is a
legitimate platform-inherent difference. However, it creates several functional divergences:

### §3.2 — Gesture handling divergence (algorithmic)

**D-V10** | **High** | **Open**

Swift `SpectrumView+GestureHandlers.swift` implements a unified zoom gesture that supports three
distinct **target regions**:
1. Zoom over the **plot area** → zooms both axes simultaneously
2. Zoom over the **frequency axis** → zooms frequency axis only
3. Zoom over the **magnitude axis** → zooms magnitude axis only

The gesture target is determined by comparing the gesture start point against the `plotFrame` and
axis label areas using `GeometryProxy`.

Python `spectrum_view_gesture_handlers.py` implements zoom and pan on `FftCanvas` via
`wheelEvent` and `mousePressEvent` / `mouseMoveEvent`. The pyqtgraph `PlotItem` uses
`ViewBox.setMouseEnabled(x=True, y=True)`. **Axis-only zoom (zooming only frequency or only
magnitude by targeting the axis label area) is not implemented in Python.**

Impact: Users cannot zoom/pan the dB axis independently by clicking on it, nor zoom the frequency
axis independently. Any chart interaction zooms both axes together (or the axis pyqtgraph
happens to associate the mouse position with).

**D-V11** | **Medium** | **Open**

Swift scroll wheel handling (macOS):

| Modifier | Action |
|---|---|
| None | Zoom both axes around cursor |
| Shift | Pan frequency axis |
| Option | Pan magnitude axis |
| Command or Control | Zoom both axes around cursor |

`SpectrumScrollWheel.swift` installs a local `NSEvent` monitor that intercepts scroll wheel events
with modifier-key detection. Python uses pyqtgraph's default `ViewBox.wheelEvent` which zooms
around the cursor but does **not** distinguish modifier keys. Shift-scroll for panning and
Option-scroll for magnitude-only pan are absent.

**D-V12** | **Medium** | **Open**

Swift `SpectrumScrollWheel.swift` is compiled only `#if os(macOS)` and implements
`ScrollWheelModifier`, `ScrollWheelMonitorView`, `ScrollWheelHostView`, and the
`View.onScrollWheel(_:)` extension. Python has no equivalent `SpectrumScrollWheel`-class file.
Scroll-wheel zoom works in Python via pyqtgraph's built-in `wheelEvent`, but the modifier-key
semantics in D-V11 are missing. This is the Python-only gap.

### §3.3 — SnapInterpolation divergence

**D-V13** | **Medium** | **Open**

Swift `SpectrumView+SnapInterpolation.swift` implements:
- `snapToWaveform(at:in:chartData:isLogarithmic:)` — nearest-bin binary search plus parabolic
  frequency interpolation (mirrors the peak finder's parabolic interpolation)
- `snapToMaterialCurve(at:in:materialSpectra:isLogarithmic:)` — gravity-based curve locking
  within 20 dB of cursor, returns the index of the locked curve
- `CursorSnapState` struct — holds `(frequency, magnitude, lockedCurveIndex?)`

Python `spectrum_view_snap_interpolation.py` implements:
- `snap_to_waveform(x_pos, plot_item, data)` — nearest-bin search, **no parabolic interpolation**
- `snap_to_material_curve(x_pos, plot_item, material_spectra)` — curve locking present

**Missing parabolic interpolation** in snap-to-waveform means the cursor readout shows the
frequency of the nearest FFT bin rather than the interpolated peak frequency. For a 65536-point
FFT at 48 kHz the bin width is ~0.73 Hz, so this is a minor precision issue at normal zoom levels
but becomes visible at high zoom.

`CursorSnapState` struct is not replicated as an explicit type in Python — the snap functions
return tuples. This is a low-severity naming/typing difference.

### §3.4 — Chart content layers

Swift `SpectrumView+ChartContent.swift` defines 5 distinct `@ChartContentBuilder` layers:

| Layer | Swift | Python (`FftCanvas`) |
|---|---|---|
| `spectrumLineContent` | Red `LineMark` | `self._spectrum_curve` (`PlotDataItem`) |
| `modeBoundaryContent` | Vertical `RuleMark` per boundary | `InfiniteLine` items, `_mode_boundary_lines` |
| `peakAnnotationContent` | `PointMark` + invisible annotations | `_peak_markers` scatter plot |
| `materialSpectraContent` | Coloured `LineMark` per phase | `_material_curves` dict |
| `thresholdLinesContent` | Horizontal `RuleMark` threshold | Not found in Python — **see D-V15** |

**D-V14** | **Medium** | **Open**

Swift spectrum view shows a horizontal `RuleMark` line at the `tapDetectionThreshold` (dBFS) to
provide the user with visual feedback about where the tap detector will trigger. Python `FftCanvas`
does not render a threshold line. The user has no visual indicator of the trigger threshold.

### §3.5 — Axis tick generation divergence

**D-V15** | **Medium** | **Open**

Swift `AxixTickGenerator.swift` (note: filename has a typo, the type is correctly named
`AxisTickGenerator`) implements a full "nice number" algorithm for both linear and logarithmic axes
that:
- Snaps tick intervals to {1, 2, 5} × 10ⁿ values
- Auto-increases decimal precision until all tick labels are unique
- Generates log-scale minor ticks (2–9× sub-decade positions)

Python `utilities/axis_tick_generator.py` implements only two utility functions:
- `freq_bin_range(n_f, sample_freq, fmin, fmax)` — converts Hz to bin indices
- `clamp_freq_range(fmin, fmax)` — ensures fmin < fmax

**The "nice number" tick generation, log-minor tick generation, and label deduplication algorithms
are completely absent from the Python port.** Pyqtgraph handles tick generation automatically, but
its automatic algorithm does not implement the "nice number" snapping or the label deduplication
that Swift's custom implementation provides. The Python module docstring acknowledges this:
"pyqtgraph handles tick generation automatically; this module provides the helper functions that
map between FFT bin indices and Hz/dB values".

---

## §4 — PeakAnnotations

### §4.1 — Draggable annotation architecture

Swift `PeakAnnotations.swift` defines:
- `PeakAnnotationsOverlay` — container that iterates all visible peaks
- `DraggablePeakAnnotation` — per-peak drag/hover/context-menu handler
- `ConnectionLine` — dashed line from peak to label
- `PeakAnnotationLabel` — badge with mode name, pitch, frequency, dBFS

Python `peak_annotations.py` defines:
- `DraggableTextItem` — a `pg.TextItem` subclass with custom `paint()` for rounded-rectangle
  background (mirrors Swift `PeakAnnotationLabel`)
- `FftAnnotations` — container class managing all annotations (mirrors `PeakAnnotationsOverlay`)

The architecture is functionally equivalent. Key differences:

**D-V16** | **Medium** | **Open**

Swift `DraggablePeakAnnotation` supports **double-tap (iOS) to reset label to default position**.
Python `DraggableTextItem` supports right-click "Reset Position" (matching Swift macOS behavior) but
**does not implement double-click reset**. On macOS this is acceptable (macOS doesn't have double-tap
on touchscreen), but the iOS port would need this.

**D-V17** | **Low** | **Open**

Swift `DraggablePeakAnnotation` shows a **hover cursor** change to open-hand cursor on macOS when
hovering over an annotation label. Python `DraggableTextItem` does not set a custom cursor on hover.
The cursor remains the default arrow when hovering over annotations.

### §4.2 — Annotation offset storage type

**D-V18** | **Medium** | **Open**

Swift stores annotation offsets as `[UUID: CGPoint]` — keyed by `UUID`, positions in `CGPoint`
(screen-space pixels). Python stores offsets differently: the `DraggableTextItem._default_pos`
and current position are stored in **data space** (Hz, dB) as `QPointF`. The conversion between
screen-space and data-space offsets must be done at render time in both directions.

Swift: offset is `CGPoint` applied to the final screen-space badge position.
Python: position is stored as data-space `QPointF`, and pyqtgraph handles the data-to-screen
coordinate mapping when positioning the `TextItem`.

This is a legitimate platform-inherent difference (Qt stores data-space positions while SwiftUI
stores screen-space offsets) but means that saved annotation offsets from a Swift `.guitartap`
file cannot be faithfully restored in Python at the same screen position. The `peakAnnotationOffsets`
field in the JSON file contains data-space values from Python that Swift interprets as screen-space
pixels (wrong scale).

**Impact**: Loading a measurement saved by Python in Swift (or vice versa) will display annotations
at the wrong positions.

---

## §5 — TapAnalysisResultsView (inline in MainWindow)

### §5.1 — Results panel location

As noted in §2.1, Swift's `TapAnalysisResultsView.swift` is a standalone `View` presented in a
floating `NSWindow` (macOS) or as a sheet (iOS). The Python equivalent is the right-hand panel
of `MainWindow` — a `QScrollArea` containing multiple collapsible `QGroupBox` sections built
inline in `tap_tone_analysis_view.py`.

The functional surface area covered is equivalent. Key divergences:

**D-V19** | **Medium** | **Open**

Swift `TapAnalysisResultsView` has explicit **Select All / Select None** batch controls in the
section header of the peaks table (guitar mode). Python `PeakListWidget` / `PeakCardWidget` has
no batch peak selection UI. The user must toggle peaks individually.

**D-V20** | **Low** | **Open**

Swift `TapAnalysisResultsView` renders a **mini spectrum `Chart`** inside the results panel for
comparison measurements (one line per loaded spectrum, colored by phase). Python does not render a
mini spectrum in the results panel; comparison spectra are shown only in the main `FftCanvas`.

### §5.2 — Mode override picker

Swift `CombinedPeakModeRowView` presents the mode override picker as a **`Popover`** (macOS) or
**`Sheet`** (iOS compact). Python `PeakCardWidget` presents a `QMenu` (context menu-style dropdown)
when the mode label button is clicked. Functionally equivalent.

**D-V21** | **Low** | **Open**

Swift `CombinedPeakModeRowView` allows a "Custom…" text entry for arbitrary mode label text.
Python `PeakCardWidget` presents the same `QMenu` with a list of standard mode names but a
"Custom…" entry that opens a `QInputDialog` for free text. The custom entry path appears to be
present in Python but was not confirmed as fully exercised.

---

## §6 — ResultsWindowPresenter

**D-V22** | **Medium** | **Open**

Swift `ResultsWindowPresenter.swift` is a `#if os(macOS)` class that manages a free-floating
`NSWindow` hosting `TapAnalysisResultsView`. Features:
- `show(analyzer:fftAnalyzer:minFreq:maxFreq:...)` — opens or refreshes the window
- `close()` — programmatic close
- `onClose` callback — notifies parent when window is closed by user
- `win.isRestorable = false` — prevents macOS from re-opening this window on next launch
- Positions the window to the right of the main window, aligned at the top

Python has no `ResultsWindowPresenter`. The results panel is a `QWidget` docked to the right side
of `MainWindow`. It is not a separate floating window and cannot be independently positioned,
minimized, or closed while the main window stays open.

**Functional impact**: In Swift, the user can view analysis results and interact with the main
spectrum simultaneously. In Python, the results panel shares horizontal space with the spectrum,
reducing the available area for the spectrum chart.

---

## §7 — ExportView (Swift-only)

**D-V23** | **Medium** | **Open**

Swift `Measurements/ExportView.swift` provides a dedicated modal sheet that:
- Displays the full JSON text of a measurement in a monospaced, selectable `ScrollView`
- Copy button — writes to pasteboard with transient "Copied" banner (auto-dismiss after 2 s)
- Save/Share button — calls `MeasurementFileExporter.exportJSON`

Python has no equivalent `ExportView`. JSON export from `MeasurementsDialog` calls
`QFileDialog.getSaveFileName` directly and writes the file, without offering a "view the JSON
content" panel. The Copy-to-clipboard path is absent.

---

## §8 — FFTAnalysisMetricsView

### §8.1 — Section differences

Swift `FFTAnalysisMetricsView.swift` has 4 sections:
1. Analysis Configuration: frequency resolution, bin count, sample rate, bandwidth, sample length, frame rate
2. Performance: update interval, estimated FPS, processing mode
3. Peak Detection: dominant frequency, magnitude
4. Calibration: active calibration file name

Python `fft_analysis_metrics_view.py` has 4 sections:
1. Analysis Configuration: frequency resolution, bin count, sample rate, bandwidth, sample length, **frame rate** ✅
2. Performance: processing time (last frame), average processing (30-frame), **CPU usage** (Python-only)
3. Peak Detection: dominant frequency, magnitude ✅
4. **Status**: Running/Stopped indicator (Python-only; replaces Swift's Calibration section)

**D-V24** | **Low** | **Open**

Swift metrics view shows the **active calibration file name** in a dedicated Calibration section.
Python metrics view shows a **Running/Stopped status indicator** instead and does not show the
active calibration name. Python does show calibration state in the settings dialog but not in the
live metrics panel.

**D-V25** | **Low** | **Open**

Python metrics view adds **CPU usage** to the Performance section. This is a Python-only addition
with no Swift counterpart. Acceptable Python-only feature; not a bug.

### §8.2 — Update mechanism

Swift `FFTAnalysisMetricsView` uses `@ObservedObject var analyzer: RealtimeFFTAnalyzer` — the view
automatically re-renders whenever any `@Published` property changes on the analyzer, which includes
every FFT frame.

Python `FFTAnalysisMetricsView.update(canvas)` is called explicitly from `FftCanvas`'s
`framerateUpdate` signal. This is the correct Qt equivalent (Rule 1 / Signal-driven). The
signal chain is:
- Declared: `framerateUpdate: Signal` in `FftCanvas`
- Connected: `canvas.framerateUpdate.connect(metrics_view.update)`
- Emitted: after each frame render in `FftCanvas.paintEvent` or equivalent

Verification of the full chain is needed but architecture is correct.

---

## §9 — HelpView

**D-V26** | **Low** | **Open**

Swift `HelpView` is a `List` with `Section` groups of static `Text` content presented in a
dedicated `Window` (macOS, id `"help"`, 520×620 pt) accessible from `⌘?` or as a sheet (iOS).

Python `HelpView` is a `QDialog` with a `QTextBrowser` showing rich HTML content (same information,
different rendering). Content parity is approximately equivalent in sections covered.

**Missing from Python**:
- Swift HelpView has a "**Plate Mode**" section covering Two-tap / Three-tap process.
- Python HelpView content was not fully verified for section parity.

**D-V27** | **Low** | **Open**

Swift `HelpView` uses SF Symbol icons rendered inline as `Image(systemName:)` in each row header.
Python `HelpView` uses `qtawesome` icons embedded as base64 PNG data-URIs in the HTML. The icon
set is different (qtawesome vs SF Symbols), meaning some icons may not have a visual counterpart.

---

## §10 — SaveMeasurementSheet

Swift `SaveMeasurementSheet` uses `@Binding var tapLocation: String` and `@Binding var notes:
String` to two-way sync the text field content with the parent view's state — changes in the dialog
immediately update the parent's `@State` without any explicit "on dismiss" callback needed for
reading values.

Python `SaveMeasurementDialog` exposes `tap_location` and `notes` as read-only properties that
are read by the caller after `exec()` returns. The dialog also provides `set_tap_location()` and
`set_notes()` for pre-filling. This is the correct Qt equivalent and is functionally identical.

Verdict: Full functional parity.

---

## §11 — TapSettingsView / AppSettings

### §11.1 — Architecture difference

Swift `TapSettingsView` is a `Form`-based SwiftUI sheet with all settings organized in one view.
Python `utilities/tap_settings_view.py` contains `AppSettings` — a pure settings-access class
backed by `QSettings`. The actual settings **UI** is implemented inline in `MainWindow` as part of
a `_show_settings()` method that creates a `QDialog`. This is a significant structural difference:

- Swift: settings UI is a reusable `View` struct that owns its state via `@Binding`
- Python: settings UI is embedded in `MainWindow`, and settings persistence is in `AppSettings`

**D-V28** | **Medium** | **Open**

Swift `TapSettingsView` has an **Apply button** that calls `onApply(_ measurementChanged: Bool)`.
The `measurementChanged` parameter is `true` when the measurement type or FLC toggle changed,
which causes `TapToneAnalysisView` to cancel the current measurement and restart. Python's settings
dialog applies settings and closes, but the "cancel and restart if measurement type changed" logic
has not been confirmed as present.

### §11.2 — Settings parity

**D-V29** | **Medium** | **Open**

Swift `TapSettingsView` has a **"Show Unknown Modes" toggle** (`showUnknownModes: Bool`) that
controls whether peaks with `GuitarMode.unknown` classification appear in the results panel and
on the spectrum chart. Python `AppSettings` has a `show_unknown_modes` setting, but the filter
in `PeakListWidget` / `FftCanvas` has not been confirmed as reading this setting and applying it
consistently in all display paths (results panel, chart annotations, comparison mode).

**D-V30** | **Low** | **Open**

Swift `TapSettingsView` has an **"Advanced" section** (collapsible via `@State private var
showingAdvanced: Bool`) containing the hysteresis margin and maximum peaks settings. Python's
settings dialog layout was not confirmed to have an equivalent collapsible advanced section.

---

## §12 — MeasurementsListView / MeasurementsDialog

### §12.1 — Import/export flow

**D-V31** | **High** | **Open**

Swift `MeasurementsListView` handles `.guitartap` file imports using a **security-scoped resource
access pair** (`startAccessingSecurityScopedResource` / `stopAccessingSecurityScopedResource`).
This is required on iOS and macOS sandboxed apps to read files outside the app's container.
Python `MeasurementsDialog._on_import()` uses `QFileDialog.getOpenFileName` which returns a path
that is already accessible in the non-sandboxed Python context.

**More critically**: Python's import path reads the raw file bytes and calls
`import_measurements_from_json(data)`. Swift's import path calls
`TapToneAnalyzer.importMeasurements(from:)` which triggers the microphone warning check (comparing
the measurement's stored microphone name against available devices). The Python path does not
invoke the microphone warning check on import.

**D-V32** | **Medium** | **Open**

Swift `MeasurementsListView` observes `Notification.Name.openMeasurementFile` to handle
AirDrop / "Open in…" import events routed through the app delegate. Python has no equivalent
mechanism — files dropped into the Python app from Finder, AirDrop, or "Open with…" are not
handled.

**D-V33** | **Medium** | **Open**

Swift `MeasurementsListView` shows a **compare mode** in which the user selects multiple
measurements (max 3 by convention, though not enforced) and requests an overlay spectrum comparison.
Python `MeasurementsDialog` implements compare mode (`_compare_mode`, `_compare_ids`, "Compare…"
button). Functional parity appears present, but the comparison uses **integer indices** in Python
(`_compare_ids: set[str]` — actually UUIDs) vs `Set<Int>` indices in Swift. This is consistent.

**D-V34** | **Low** | **Open**

Swift `MeasurementsListView` uses macOS `NSWindowController` for the detail view on macOS (a
separate floating window). Python `MeasurementsDialog` opens `MeasurementDetailDialog` as a child
modal dialog. Functionally equivalent but the macOS user experience differs (modal vs free-floating).

---

## §13 — ExportableSpectrumChart

### §13.1 — Rendering approach

Swift `ExportableSpectrumChart` is a stateless SwiftUI view rendered via `ImageRenderer` (which
requires `@MainActor`). Python `ExportableSpectrumChart` creates a temporary `PlotWidget`, renders
it to a `QImage`, and returns `bytes`.

Both approaches produce a PNG-encoded image. The key difference:

**D-V35** | **Medium** | **Open**

Swift `ExportableSpectrumChart` renders annotation connection lines using `ConnectionLineShape`
(a `Shape` conforming type), which works with `ImageRenderer`. Python's `exportable_spectrum_chart.py`
states in its docstring that connection lines are drawn with `QPainter.drawLine()` directly onto
the captured `QImage`. The `render()` method must call `QPainter.begin(qimage)`, draw the
connection lines, then `QPainter.end()`. If this two-phase rendering is not correctly sequenced the
connection lines may be absent from exported images.

**Verification needed**: Confirm that exported spectrum images actually include annotation
connection lines in Python.

---

## §14 — MeasurementFileExporter / PDFReportGenerator

### §14.1 — Structural merge

As noted in §2.1, Swift's `PDFReportGenerator.swift` and `MeasurementFileExporter.swift` are
separate files. Python merges both into `tap_analysis_results_view.py`. The `measurement_file_exporter.py`
module is a thin re-export shim.

### §14.2 — PDF generation approach

**D-V36** | **Medium** | **Open**

Swift `PDFReportGenerator.generate(data:)` uses `ImageRenderer<PDFReportContentView>` to render
a SwiftUI view into a PDF `CGContext`. The PDF is produced as `Data` (in-memory bytes) and then
saved to disk or shared.

Python `export_pdf(data, output_path)` uses `reportlab` to imperatively build a PDF from a story
list of `Flowable` objects. The output is written directly to `output_path`.

**Functional differences**:
1. Swift renders to an in-memory `Data` buffer first, then saves. Python writes directly to
   the output path (no in-memory buffer stage). If the write fails mid-document, a partial file
   is left on disk.
2. Swift can return the PDF `Data` to a share sheet (iOS) without writing to disk. Python always
   writes to disk first.
3. Swift PDF uses SwiftUI layout engine (flexible, font-metric-based). Python PDF uses reportlab
   fixed-point geometry. Visual fidelity between platforms is expected to differ.

### §14.3 — MeasurementFileExporter platform branches

**D-V37** | **Medium** | **Open**

Swift `MeasurementFileExporter` has separate platform implementations:
- macOS: `NSSavePanel` for PDF/PNG, `NSSharingServicePicker` for JSON
- iOS: `UIActivityViewController` share sheet for all exports

Python export uses `QFileDialog.getSaveFileName` for all export types, which corresponds to the
macOS `NSSavePanel` path only. **The `NSSharingServicePicker` (AirDrop, Mail, Messages) path for
JSON export is absent.** Python JSON export saves to a chosen local file path only.

---

## §15 — Shared Components

### §15.1 — PeakCardWidget / PeaksModel vs Swift

**D-V38** | **High** | **Open**

Python `shared/peaks_model.py` contains `PeaksModel(QAbstractTableModel)` which is the backing
model for a `QTableWidget`-style peaks display. It emits:
- `annotationUpdate: Signal(str, float, float, str, str)` — (peak_id, freq, mag, html, mode_str)
- `clearAnnotations: Signal()`
- `hideAnnotations: Signal()`
- `hideAnnotation: Signal(float)` — by frequency
- `showAnnotation: Signal(float)` — by frequency
- `userModifiedSelectionChanged: Signal(bool)`
- `modeColorsChanged: Signal(object)` — dict[float, tuple[int,int,int]]

Swift has no direct counterpart to `PeaksModel` as a class — Swift peaks are `@Published` arrays
on `TapToneAnalyzer` rendered by `CombinedPeakModeRowView` in a `ForEach` loop.

**D-V38 details**: The `hideAnnotation` and `showAnnotation` signals emit a `float` frequency as
the peak identifier. Swift identifies peaks by `UUID`. This means Python's annotation show/hide
signals are **keyed by frequency**, not by UUID. If two peaks have the same frequency (within
floating-point precision) both will be affected by a single hide/show signal. This is an
architectural divergence from Swift's UUID-keyed approach.

The `annotationUpdate` signal also uses `float` frequency as the peak identifier rather than UUID,
consistent with the above.

### §15.2 — EmptyStateView differences

**D-V39** | **Low** | **Open**

Swift `EmptyStateView` accepts `icon: String` (SF Symbol name), `title: String`, and
`message: String`. It displays a large SF Symbol (60pt) above the title and message.

Python `EmptyStateView` accepts `title: str` and `subtitle: str`. It has **no icon parameter** and
displays no icon — just text. Any caller that passes an `icon` argument would need to be updated.

### §15.3 — LoadingOverlay

Python `shared/loading_overlay.py` was present in the listing but not read in detail. Based on the
Swift equivalent (`LoadingOverlay.swift` is a simple `ZStack` with `ProgressView` + `Text`), the
Python equivalent should be a `QProgressDialog` or custom overlay widget. No Python equivalent has
been confirmed as connected to the export/save operations in `MainWindow`.

**D-V40** | **Medium** | **Open**

The `LoadingOverlay` in Swift is applied via `.overlay(isExportingSpectrum || isSavingMeasurement
|| isGeneratingReport ? LoadingOverlay(...) : nil)` in `TapToneAnalysisView+Layouts.swift`. Python
has no corresponding overlay shown to the user during these async operations — see also D-V4.

---

## §16 — Utilities/Extensions

**D-V41** | **Low** | **Open**

Swift `Extensions.swift` defines `View.hint(_:)` and `HintText` — a platform-adaptive
`.help()` / `.accessibilityHint()` modifier with a centralized enum of all toolbar button hint
strings. Python `utilities/extensions.py` contains only `AppSettings` (the settings persistence
class). **No Python equivalent for `HintText` or accessibility hints exists.** This is acceptable
for Python desktop accessibility compliance (Qt accessibility is handled differently) but means
toolbar button tooltips may not be consistently defined.

---

## §17 — iOS-only Features (no Python equivalent, acceptable)

The following Swift features exist only on iOS (`#if os(iOS)`) and have no Python equivalent.
These are noted for completeness but do not represent bugs:

| Swift feature | Location | Python status |
|---|---|---|
| `crosshairMode` long-press gesture on `SpectrumView` | `SpectrumView+GestureHandlers.swift` | Not applicable (desktop only) |
| `AVAudioSession.requestRecordPermission` | `TapToneAnalysisView+Actions.swift` | `MacAccess` in `platform_adapters.py` (macOS path) |
| `UIActivityViewController` share sheet export | `MeasurementFileExporter.swift` | `QFileDialog` instead |
| `DocumentPicker` file import | `MeasurementsListView.swift` | `QFileDialog` instead |
| `UIDevice.current.userInterfaceIdiom` | `TapToneAnalysisView.swift` | Not needed |
| iPhone landscape layout | `TapToneAnalysisView+Layouts.swift` | Not needed |
| `@Environment(\.scenePhase)` | `TapToneAnalysisView.swift` | Not needed |

---

## §18 — Signal Chain Audit for View-Layer Reactive Properties

Applying REACTIVE_PROPERTY_AUDIT_GUIDELINES Rules 1–7 to the view-layer signal connections:

### §18.1 — Swift `.onChange(of:)` → Python signal connections

| Swift `.onChange(of:)` target | Python signal | Connected? | Emitted? | Status |
|---|---|---|---|---|
| `analyzer.peaksChanged` (spectrum update) | `FftCanvas.peaksChanged` | ✅ | ✅ | ✅ |
| `analyzer.spectrumUpdated` | `FftCanvas.spectrumUpdated` or `update_spectrum` | ✅ | ✅ | ✅ |
| `analyzer.statusMessageChanged` | `analyzer.statusMessageChanged` | ✅ | Needs verify | ⚠ |
| `analyzer.plateStatusChanged` | `analyzer.plateStatusChanged` | ✅ | ✅ | ✅ |
| `analyzer.savedMeasurementsChanged` | `analyzer.savedMeasurementsChanged` | ✅ in `MeasurementsDialog` | ✅ | ✅ |
| `analyzer.identifiedModesChanged` | Not found as named signal | Unknown | Unknown | ⚠ Gap |
| `tap.$showLoadedSettingsWarning` `.onReceive` | Signal for loaded-settings warning | Needs verification | Needs verify | ⚠ |
| `tap.$microphoneWarning` `.onReceive` | `analyzer.microphoneWarning` | Needs verification | Needs verify | ⚠ |

**D-V42** | **High** | **Open**

`identifiedModesChanged` — Swift's `TapToneAnalysisView` re-renders whenever `tap.identifiedModes`
changes because `TapToneAnalyzer` is an `@ObservedObject`. Python must have an explicit signal for
`identified_modes` changes. The `peaksChanged` signal carries the raw `ResonantPeak` list but may
not carry the mode classification dict. If `identified_modes` is updated after `peaksChanged` is
emitted (which happens in `analyze_magnitudes` → `reclassify_peaks` → `identifiedModes` update),
then any Python slot that builds the peak mode display (mode colors, labels) inside a `peaksChanged`
handler may read stale `identified_modes` data.

**Rule 7 concern**: The `_on_peaks_changed` slot in `MainWindow` may read `self.analyzer.identified_modes`
(a model attribute) rather than receiving modes as part of the signal payload. If `identified_modes`
has not been updated at the time `peaksChanged` fires, mode labels will be wrong.

### §18.2 — Swift `.onAppear` / `.task` → Python equivalents

| Swift modifier | Purpose | Python equivalent |
|---|---|---|
| `.onAppear` in `TapToneAnalysisView` | Starts analyzer (if auto-start enabled) | `MainWindow.__init__` startup sequence |
| `.onAppear` in `MeasurementsListView` | Rebuilds measurement list | `MeasurementsDialog.__init__` + `_rebuild_list()` |
| `.task` in `TapToneAnalysisView` | Background auto-scale polling | `QTimer` polling in `MainWindow` |

No critical gaps identified in this area.

---

## §19 — Summary Table

| ID | Severity | Area | Description | Status |
|---|---|---|---|---|
| D-V1 | Low | File structure | `fft_canvas.py` is a legitimate platform split of `SpectrumView` | Open |
| D-V2 | Low | File structure | `peak_card_widget.py` implements `CombinedPeakModeRowView` under different name | Open |
| D-V3 | Low | File structure | `peaks_model.py` is a Python-only Qt table model (no Swift counterpart) | Open |
| D-V4 | Medium | Loading UX | No `LoadingOverlay` during export/save/report operations | Open |
| D-V5 | Low | File handling | AirDrop / OS-level "open file" events not handled in Python | Open |
| D-V6 | Low | Animation | Warning icon throb animation not replicated | Open |
| D-V7 | High | Button state | `cancelButtonEnabled` not re-evaluated on material phase transitions | Open |
| D-V8 | High | Reactive | `.onReceive(tap.$showLoadedSettingsWarning)` / `$microphoneWarning` signal chains unverified | Open |
| D-V9 | Medium | macOS menus | `FocusedValues` / `MenuActions` pattern not replicated; single-window workaround | Open |
| D-V10 | High | Gestures | Axis-only zoom (freq-axis-only / mag-axis-only) not implemented in Python | Open |
| D-V11 | Medium | Gestures | Modifier-key scroll-wheel semantics (Shift=pan, Option=mag-pan) absent | Open |
| D-V12 | Medium | Gestures | `SpectrumScrollWheel` modifier-key scroll bridge has no Python equivalent | Open |
| D-V13 | Medium | Cursor | Parabolic interpolation absent from Python `snap_to_waveform()` | Open |
| D-V14 | Medium | Chart | Tap detection threshold `RuleMark` line not rendered in Python spectrum | Open |
| D-V15 | Medium | Axis ticks | "Nice number" tick algorithm and log minor ticks absent from Python | Open |
| D-V16 | Medium | Annotations | Double-click reset for annotation labels not implemented | Open |
| D-V17 | Low | Annotations | Hover cursor change on annotation labels not implemented | Open |
| D-V18 | Medium | Annotations | Annotation offset coordinate space mismatch (screen-space vs data-space) — cross-platform load positions wrong | Open |
| D-V19 | Medium | Results panel | Select All / Select None batch peak controls absent in Python | Open |
| D-V20 | Low | Results panel | Mini comparison spectrum in results panel absent in Python | Open |
| D-V21 | Low | Mode override | "Custom…" mode label entry path not confirmed fully functional | Open |
| D-V22 | Medium | Window mgmt | No `ResultsWindowPresenter` equivalent; results panel is docked not floating | Open |
| D-V23 | Medium | Export | `ExportView` (JSON text viewer with copy-to-clipboard) has no Python equivalent | Open |
| D-V24 | Low | Metrics | Calibration file name not shown in Python metrics panel | Open |
| D-V25 | Low | Metrics | Python adds CPU usage to metrics (Python-only feature, acceptable) | Open |
| D-V26 | Low | Help | Help view content section parity not fully verified | Open |
| D-V27 | Low | Help | SF Symbol icons vs qtawesome icons — different icon sets | Open |
| D-V28 | Medium | Settings | "Cancel and restart if measurement type changed" behavior on Apply not confirmed | Open |
| D-V29 | Medium | Settings | `showUnknownModes` filter not confirmed applied in all display paths | Open |
| D-V30 | Low | Settings | Advanced section collapse state not confirmed in Python settings dialog | Open |
| D-V31 | High | Import | Microphone warning check not invoked on measurement import in Python | Open |
| D-V32 | Medium | Import | AirDrop / "Open with…" file-open events not handled | Open |
| D-V33 | Medium | Measurements | Compare mode uses UUID strings vs Swift's integer indices (consistent internally but cross-platform) | Open |
| D-V34 | Low | Measurements | Detail view is modal dialog in Python vs free-floating window in Swift/macOS | Open |
| D-V35 | Medium | Export image | Annotation connection lines in exported spectrum image need verification | Open |
| D-V36 | Medium | PDF | reportlab imperative vs SwiftUI `ImageRenderer` — partial write on error leaves corrupt file | Open |
| D-V37 | Medium | Export | `NSSharingServicePicker` (AirDrop, Mail) path for JSON export absent in Python | Open |
| D-V38 | High | Peaks model | `hideAnnotation` / `showAnnotation` / `annotationUpdate` use `float` frequency as key vs Swift UUID — multi-peak collision risk | Open |
| D-V39 | Low | Empty state | `EmptyStateView` lacks `icon` parameter — no SF Symbol displayed | Open |
| D-V40 | Medium | Loading UX | `LoadingOverlay` widget not confirmed connected to async operations | Open |
| D-V41 | Low | Accessibility | `HintText` / toolbar accessibility hints not replicated | Open |
| D-V42 | High | Reactive | `identifiedModesChanged` signal / Rule 7 payload concern for `identified_modes` in `peaksChanged` handler | Open |

---

## §20 — Severity Summary

| Severity | Count | IDs |
|---|---|---|
| **High** | 7 | D-V7, D-V8, D-V10, D-V31, D-V38, D-V42, and D-V7 button-state gap |
| **Medium** | 21 | D-V4, D-V9, D-V11, D-V12, D-V13, D-V14, D-V15, D-V16, D-V18, D-V19, D-V22, D-V23, D-V28, D-V29, D-V32, D-V33, D-V35, D-V36, D-V37, D-V40, D-V44 |
| **Low** | 14 | D-V1, D-V2, D-V3, D-V5, D-V6, D-V17, D-V20, D-V21, D-V24, D-V25, D-V26, D-V27, D-V30, D-V34, D-V39, D-V41 |

---

## §21 — Investigation Notes: Why Python Has 61 Files vs Swift's 42

The 19 extra Python files are accounted for as follows:

| Category | Count | Files |
|---|---|---|
| Stub extension files (code not yet extracted from monolith) | 5 | `_actions.py`, `_controls.py`, `_export.py`, `_layouts.py`, `_spectrum_views.py` |
| Legitimate platform split | 1 | `fft_canvas.py` — split from `SpectrumView` as required by Qt architecture |
| Combined Swift files | 2 | `peak_card_widget.py` + `peaks_model.py` together implement `CombinedPeakModeRowView` + its model |
| Python-only utility | 2 | `platform_adapters.py`, `gt_images.py` |
| Partial port with renamed role | 1 | `utilities/axis_tick_generator.py` (partial; Swift has `AxixTickGenerator.swift`) |
| `__init__.py` files (Python package markers) | ~3 | One per subdirectory |
| `__pycache__` directories | counted as 1 | Not a file but listed in some counts |

Accounting for these, the actual code-bearing Python view files number approximately **41** — essentially matching Swift's 42. The discrepancy is an artifact of:
1. The 5 intentional-but-empty stub extension files
2. Python's package `__init__.py` files which have no Swift counterpart

---

## Appendix A — Stub File Inventory

The following Python files were confirmed to contain only a module docstring and a `# Pending:`
comment with no implementation:

- `/Users/dws/src/guitar_tap/src/guitar_tap/views/tap_tone_analysis_view_actions.py`
- `/Users/dws/src/guitar_tap/src/guitar_tap/views/tap_tone_analysis_view_controls.py`
- `/Users/dws/src/guitar_tap/src/guitar_tap/views/tap_tone_analysis_view_export.py`
- `/Users/dws/src/guitar_tap/src/guitar_tap/views/tap_tone_analysis_view_layouts.py`
- `/Users/dws/src/guitar_tap/src/guitar_tap/views/tap_tone_analysis_view_spectrum_views.py`

Each stub includes a `# Pending:` list of the sections that should be extracted from
`tap_tone_analysis_view.py::MainWindow` into that file. This extraction work is pending and
represents a technical debt item separate from the functional divergences catalogued above.

---

## Appendix B — Strategic Recommendations: Divergence Work vs QML Migration

*Added after review of the full audit findings in the context of a potential QML migration.*

### Recommended order of work

**Phase 1 — Fix high-severity divergences first (prerequisites for everything else)**

The 7 high-severity items must be addressed before either the QML migration or broader divergence
remediation, because they represent correctness bugs, not just structural debt:

1. **D-V38** — `hideAnnotation` / `showAnnotation` / `annotationUpdate` use `float` frequency as
   peak identifier instead of UUID. This is an architectural prerequisite for QML: any
   `QAbstractListModel` built for the peaks list must key by UUID, not frequency. Fixing this
   after the model is in place is significantly harder than fixing it now.
2. **D-V42** — `identifiedModesChanged` signal / Rule 7 payload concern. If `identified_modes` is
   stale when `peaksChanged` fires, mode labels are wrong. Must be confirmed and fixed before the
   peaks model is restructured.
3. **D-V7** — `cancelButtonEnabled` not re-evaluated on material phase transitions. Button state
   correctness bug, independent of framework.
4. **D-V8** — `.onReceive(tap.$showLoadedSettingsWarning)` / `$microphoneWarning` signal chains
   unverified. Must be confirmed before any restructuring touches the signal wiring.
5. **D-V10** — Axis-only zoom not implemented. pyqtgraph-level fix, unaffected by framework choice.
6. **D-V31** — Microphone warning check not invoked on measurement import. Model-layer logic gap,
   independent of framework.
7. **D-V8 (second item)** — `identifiedModesChanged` signal chain verification (see D-V42).

**Phase 2 — Extract the `tap_tone_analysis_view.py` monolith**

The 5 stub extension files (`_actions.py`, `_controls.py`, `_export.py`, `_layouts.py`,
`_spectrum_views.py`) were created as scaffolding for an extraction that was never completed.
This extraction must happen before QML work begins because:

- QML binds to clean, signal-emitting model objects and slim view coordinators. A monolith
  provides no clean seam for QML to bind against.
- The extraction is also divergence remediation — the Swift codebase has this separation as its
  design; the Python monolith is itself a divergence from that design.
- Doing the extraction now (as divergence work) means the QML migration starts with a correct
  structural foundation rather than porting structural debt into a new framework.

The extraction order should match the Swift extension file responsibilities:
- `_layouts.py` first — purely structural, no logic, lowest risk
- `_controls.py` second — widget construction only, no signal logic
- `_actions.py` third — action handlers, needs signal wiring to be stable first (D-V7, D-V8)
- `_export.py` fourth — export logic; the comparison export work done in this session is a preview
- `_spectrum_views.py` last — most coupled to `FftCanvas`

**Phase 3 — Remaining medium/low divergences**

Once Phase 1 and Phase 2 are complete, the remaining items can be addressed in severity order.
Items that resolve naturally under QML (D-V4, D-V40 loading overlay; D-V19 batch peak controls;
D-V29 showUnknownModes consistency) can be deferred to the QML migration if that is planned.
Items that QML cannot help with (D-V10/D-V11/D-V12 gesture gaps; D-V13 parabolic interpolation;
D-V14 threshold RuleMark; D-V15 axis tick algorithm; D-V18 annotation coordinate space) should
be addressed as part of Phase 2 since they are pyqtgraph-level issues independent of framework.

**Phase 4 — QML migration (if pursued)**

The QML migration is worthwhile given the clean model layer inherited from the SwiftUI
architecture. However, it should only start after Phases 1–2 are complete. The recommended
migration order within QML work:

1. `AppState` / global state first — sliders, status, proves the Python↔QML bridge works
2. Settings dialog — self-contained, no list models, good QML practice
3. Metrics window — pure property bindings, straightforward
4. Peaks list — first `QAbstractListModel`, the hardest conceptual step but most reusable pattern;
   requires D-V38 to be fixed (UUID keys, not frequency floats)
5. Saved measurements window — second list model, much easier once the peaks pattern is established
6. Main layout + `FftCanvas` embed via `QQuickWidget`
7. Menu bar, help window — lowest risk, last

### Why divergence work makes the QML migration better

Several divergences *resolve themselves* naturally in QML:
- **D-V7/D-V8** (button state, `.onReceive` reactive chains) — QML `@Property` + signals gives
  this for free; the "re-evaluate at every signal boundary" problem disappears.
- **D-V42** (`identifiedModesChanged` stale-read risk) — QML's binding system re-evaluates all
  dependents when a notify signal fires, reducing timing sensitivity.
- **D-V4/D-V40** (LoadingOverlay not connected) — a `BusyIndicator` bound to `isExporting`
  property is natural in QML.
- **D-V19** (Select All / Select None) — trivial once peaks are in a proper `QAbstractListModel`.
- **D-V29** (showUnknownModes inconsistency) — a single `@Property` on `AppState` ensures
  consistency everywhere in QML.

The items QML cannot help with are all pyqtgraph-level or model-layer issues that must be fixed
regardless of framework choice.

### The pyqtgraph seam

`FftCanvas` performs real-time multi-spectrum rendering with annotation overlay, crosshair, and
gesture handling. This is not replaceable with QML Canvas and should not be attempted. The correct
architecture is `QQuickWidget` embedding `FftCanvas` inside QML. This seam is contained and
manageable, but it means:
- The pyqtgraph gesture divergences (D-V10, D-V11, D-V12) remain Qt widget-level problems that
  QML cannot address.
- Layout interactions between `QQuickWidget` and surrounding QML require careful sizing hints.

---

## Appendix C — File Location Quick Reference

All paths are absolute:

**Swift Views root**: `/Users/dws/src/GuitarTap/GuitarTap/Views/`
**Python Views root**: `/Users/dws/src/guitar_tap/src/guitar_tap/views/`

Key cross-reference:
- Swift `PDFReportGenerator.swift` → Python `views/tap_analysis_results_view.py` (lines 471–1319)
- Swift `TapAnalysisResultsView.swift` → Python `MainWindow` results panel in `tap_tone_analysis_view.py`
- Swift `CombinedPeakModeRowView.swift` → Python `shared/peak_card_widget.py::PeakCardWidget`
- Swift `SpectrumView.swift` + `SpectrumView+ChartContent.swift` → Python `fft_canvas.py::FftCanvas`
- Swift `SpectrumScrollWheel.swift` → Python: not ported (pyqtgraph `wheelEvent` instead)
- Swift `ResultsWindowPresenter.swift` → Python: not ported (docked panel instead)
- Swift `Measurements/ExportView.swift` → Python: not ported
- Swift `Utilities/AxixTickGenerator.swift` (typo in filename) → Python `utilities/axis_tick_generator.py` (partial port only)
