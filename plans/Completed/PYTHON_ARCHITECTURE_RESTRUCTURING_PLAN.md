# Python Architecture Restructuring Plan — Full Swift Parity

## Goal

Make the Python codebase a faithful mirror of the Swift architecture: same class shapes, same property names, same method signatures, same reactive patterns, same state ownership. Tests are a symptom — the root work is restructuring the production code, and tests that become direct ports follow as a consequence.

---

## Part 1 — Reactive Pattern: Replace PyQt Signals with Python `@property` + Observer ✅ DONE

**Status:** `ObservableObject` base class and `Published` descriptor live in
`swiftui_compat/observable.py` and `swiftui_compat/descriptors.py`. `TapToneAnalyzer`
inherits from `ObservableObject` and uses `QtCore.Signal` (not `pyqtSignal`). All model
state changes fire through `Published` / `_notify_change()`.

### Current State (Python)

Python uses `pyqtSignal` for all state change notifications:

```python
peaksChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)
tapDetectedSignal: QtCore.pyqtSignal = QtCore.pyqtSignal()
levelChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
displayModeChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)
```

State is carried as bare attributes (`self.saved_peaks`, `self.threshold`) with manual `emit()` calls scattered across mixin methods.

### Swift Pattern

Swift uses `@Published` on `ObservableObject`. When a `@Published` property is written, Combine automatically sends `objectWillChange` before the mutation and notifies all subscribers after. No explicit emit calls. Properties are the state:

```swift
@Published var currentPeaks: [ResonantPeak] = []
@Published var peakThreshold: Float = ... {
    didSet { recalculateFrozenPeaksIfNeeded() }
}
@Published var annotationVisibilityMode: AnnotationVisibilityMode = ...
@Published var displayMode: AnalysisDisplayMode = .live
```

### Required Change

Introduce a `@published` descriptor in Python that:

1. Stores the value on the instance
2. Calls registered observers when the value changes (the Python equivalent of Combine's `objectWillChange`)
3. Supports `didSet`-style callbacks for specific properties

**New file: `models/observable_object.py`**

```python
class Published:
    """Descriptor mirroring Swift @Published.

    When the value changes, calls self._owner._notify(attr_name, old, new).
    Supports a didSet callback registered per-property.
    """

class ObservableObject:
    """Base for TapToneAnalyzer, mirroring Swift ObservableObject.

    Views connect via .observe(attr_name, callback) or .observe_any(callback).
    This replaces pyqtSignal for all state-driven UI updates.
    """
    def observe(self, attr_name: str, callback: Callable) -> None: ...
    def observe_any(self, callback: Callable) -> None: ...
    def _notify(self, attr_name: str, old, new) -> None: ...
```

**Impact:** All view code that currently does `analyzer.peaksChanged.connect(...)` migrates to `analyzer.observe("current_peaks", ...)`. All `self.peaksChanged.emit(peaks)` calls in mixin methods are removed — setting `self.current_peaks = peaks` automatically notifies. This exactly mirrors how SwiftUI observes `@Published` properties via `@ObservedObject`.

---

## Part 2 — Eliminate Separate `TapDetector` and `DecayTracker` Classes ✅ DONE

**Status:** No separate `TapDetector` or `DecayTracker` classes exist. All tap detection
and decay tracking state and logic live as methods directly on `TapToneAnalyzer` via
`TapToneAnalyzerTapDetectionHandlerMixin` and `TapToneAnalyzerDecayTrackingMixin`.

### Current State (Python)

`TapDetector` and `DecayTracker` are separate `QtCore.QObject` subclasses. `TapToneAnalyzer` delegates to them. Tests construct `TapDetector` and `DecayTracker` in isolation.

### Swift Pattern

There are no separate `TapDetector` or `DecayTracker` classes in Swift. All tap detection and decay tracking logic lives as methods directly on `TapToneAnalyzer`, operating on `TapToneAnalyzer`'s own stored properties:

```swift
// On TapToneAnalyzer directly — not a separate class
var isAboveThreshold: Bool = false
var justExitedWarmup: Bool = false
var analyzerStartTime: Date?
var lastTapTime: Date?
var noiseFloorEstimate: Float = -60
var tapDetectionThreshold: Float
var hysteresisMargin: Float
var isTrackingDecay: Bool = false
var peakMagnitudeHistory: [(time: Date, magnitude: Float)] = []
var currentDecayTime: Float?
var decayThreshold: Float = 15

func detectTap(peakMagnitude: Float, magnitudes: [Float], frequencies: [Float]) { ... }
func measureDecayTime(tapTime: Date) -> Float? { ... }
func trackDecayFast(inputLevel: Float) { ... }
```

### Required Change

**Delete `TapDetector` as a class.** Move all its state and logic into `TapToneAnalyzerTapDetectionHandlerMixin` as direct properties and the `detect_tap()` method:

**`tap_tone_analyzer_tap_detection.py`** — transform from:

```python
class TapDetector(QtCore.QObject):        # ← DELETE
    def update(self, amplitude: int): ...  # ← MOVE TO MIXIN

class TapToneAnalyzerTapDetectionHandlerMixin:
    def do_capture_tap(...): ...
```

to:

```python
class TapToneAnalyzerTapDetectionHandlerMixin:
    # Properties now owned here, mirroring Swift TapToneAnalyzer stored properties:
    # self.is_above_threshold: bool
    # self.just_exited_warmup: bool
    # self.analyzer_start_time: datetime | None
    # self.last_tap_time: datetime | None
    # self.noise_floor_estimate: float
    # self.tap_detection_threshold: float
    # self.hysteresis_margin: float
    # self.warmup_period: float = 0.5
    # self.tap_cooldown: float = 0.4
    # self.noise_floor_alpha: float = 0.05
    # self.tap_detected: bool

    def detect_tap(self, peak_magnitude: float, magnitudes: list, frequencies: list) -> None:
        """Mirrors Swift detectTap(peakMagnitude:magnitudes:frequencies:) exactly."""
```

**Delete `DecayTracker` as a class.** Move all its state and logic into `TapToneAnalyzerDecayTrackingMixin`:

**`tap_tone_analyzer_decay_tracking.py`** — transform from:

```python
class DecayTracker(QtCore.QObject):       # ← DELETE
    def start(self, amplitude): ...
    def update(self, amplitude): ...
    def reset(self): ...
    ringOutMeasured: pyqtSignal           # ← replaced by @published current_decay_time
```

to:

```python
class TapToneAnalyzerDecayTrackingMixin:
    # Properties mirroring Swift TapToneAnalyzer stored properties:
    # self.peak_magnitude_history: list[tuple[datetime, float]] = []
    # self.is_tracking_decay: bool = False
    # self.last_tap_time: datetime | None = None   (shared with tap detection)
    # self.current_decay_time: float | None = None
    # self.decay_threshold: float = 15.0
    # self._decay_tracking_timer: Timer | None = None

    def start_decay_tracking(self) -> None:
        """Mirrors Swift startDecayTracking()."""

    def stop_decay_tracking(self) -> None:
        """Mirrors Swift stopDecayTracking()."""

    def track_decay_fast(self, input_level: float) -> None:
        """Mirrors Swift trackDecayFast(inputLevel:)."""

    def measure_decay_time(self, tap_time: datetime) -> float | None:
        """Mirrors Swift measureDecayTime(tapTime:) → Float?."""
```

**`FftProcessingThread`** — remove `TapDetector` and `DecayTracker` instantiation. The processing thread only delivers raw level samples; `detect_tap()` is called by the coordinator.

---

## Part 3 — Property Name and Type Alignment ✅ DONE

**Status:** All `TapToneAnalyzer` property names align with Swift (snake_case equivalents
of Swift camelCase). `current_peaks` is `list[ResonantPeak]`, `frozen_magnitudes` /
`frozen_frequencies` are `list[float]`, etc.

### Current Python names vs Swift names

All properties on `TapToneAnalyzer` should be renamed from Python snake_case-with-abbreviated-prefixes to match Swift's property names exactly (using Python snake_case equivalents of Swift camelCase):

| Current Python | Swift property | New Python name |
|---|---|---|
| `self.threshold` (0–100 int) | `peakThreshold` (Float dBFS) | `self.peak_threshold` (float dBFS) |
| `self.fmin`, `self.fmax` | `minFrequency`, `maxFrequency` | `self.min_frequency`, `self.max_frequency` |
| `self.n_fmin`, `self.n_fmax` | (computed from Hz) | (computed properties, not stored) |
| `self.saved_peaks` (ndarray N×3) | `currentPeaks: [ResonantPeak]` | `self.current_peaks: list[ResonantPeak]` |
| `self.saved_mag_y_db` (ndarray) | `frozenMagnitudes: [Float]` | `self.frozen_magnitudes: list[float]` |
| `self.freq` (ndarray) | `frozenFrequencies: [Float]` | `self.frozen_frequencies: list[float]` |
| `self._tap_num` | `numberOfTaps: Int` | `self.number_of_taps: int` |
| `self._tap_spectra` | `capturedTaps` | `self.captured_taps: list` |
| `self.is_measurement_complete` | `isMeasurementComplete: Bool` | `self.is_measurement_complete: bool` (keep) |
| `self._display_mode` | `displayMode: AnalysisDisplayMode` | `self.display_mode` via `@published` |
| `self.peak_annotation_offsets` (keyed by float Hz) | `peakAnnotationOffsets: [UUID: CGPoint]` | `self.peak_annotation_offsets: dict[str, tuple[float, float]]` (keyed by peak UUID string) |
| `self._loaded_measurement_peaks` (ndarray) | `loadedMeasurementPeaks: [ResonantPeak]?` | `self.loaded_measurement_peaks: list[ResonantPeak] \| None` |
| `self._measurement_type` | `TapDisplaySettings.measurementType` | stays in `TapDisplaySettings` (global settings) |
| `self._guitar_type` | `TapDisplaySettings.guitarType` | stays in `TapDisplaySettings` |

### `ResonantPeak` as the canonical peak type

**Critical:** Replace `ndarray` rows `(freq, mag, Q)` with `ResonantPeak` objects everywhere. Swift never uses raw float arrays for peaks; it always uses `ResonantPeak` structs. This affects:

- `find_peaks()` return type: `ndarray (N,3)` → `list[ResonantPeak]`
- `self.saved_peaks` / `self.current_peaks`: `ndarray` → `list[ResonantPeak]`
- `peaksChanged` signal payload: `ndarray` → `list[ResonantPeak]`
- All call sites in peak analysis, comparison mode, measurement management

**`ResonantPeak`** (Python) already exists. It needs to gain:

- `id: str` (UUID string) as the primary key — currently may be missing or inconsistent
- Parabolic interpolation and Q-factor computation moved to `TapToneAnalyzer.make_peak(at:magnitudes:frequencies:)` — a private helper mirroring Swift's `makePeak(at:magnitudes:frequencies:)`

---

## Part 4 — `TapDisplaySettings` as a Proper Settings Singleton ✅ DONE

**Status:** `models/tap_display_settings.py` exists as a QSettings-backed model-layer
singleton. No model files import from views for settings.

### Current State

`views/utilities/tap_settings_view.py` has `AppSettings` as a class with static methods. Some Python code imports views from models (a layering violation).

### Swift Pattern

`TapDisplaySettings` is a pure model-layer settings singleton accessed by models. No view imports from models.

### Required Change

Move `AppSettings` entirely to `models/tap_display_settings.py` as `TapDisplaySettings`, eliminating the `import views.utilities.tap_settings_view as _as` in model files. The view can import from the model layer; the model layer must not import from views.

---

## Part 5 — Restructure `TapToneAnalyzer.__init__` to Match Swift's Stored Properties ✅ DONE

**Status:** `TapToneAnalyzer.__init__(fft_analyzer=None)` requires no audio hardware.
All stored properties have sensible defaults. Audio-hardware setup is deferred to
`start(parent_widget, fft_params, audio_device, ...)`, called only by the view layer.

### Current State

`__init__` requires `parent_widget`, `fft_params`, `audio_device`, `calibration_corrections`, `guitar_type` — it cannot be instantiated without audio hardware.

### Swift Pattern

`TapToneAnalyzer(fftAnalyzer: RealtimeFFTAnalyzer)` — a single dependency. All other state has sensible defaults. Tests construct `TapToneAnalyzer` directly.

### Required Change

```python
class TapToneAnalyzer(ObservableObject):  # no longer QObject
    def __init__(self, fft_analyzer: RealtimeFFTAnalyzer | None = None) -> None:
        super().__init__()
        self.fft_analyzer = fft_analyzer  # None-safe for tests

        # All @published properties with defaults — no audio hardware required:
        self.peak_threshold: float = TapDisplaySettings.peak_threshold
        self.min_frequency: float = TapDisplaySettings.analysis_min_frequency
        self.max_frequency: float = TapDisplaySettings.analysis_max_frequency
        self.max_peaks: int = TapDisplaySettings.max_peaks
        self.number_of_taps: int = 1
        self.capture_window: float = 0.2
        self.tap_detection_threshold: float = TapDisplaySettings.tap_detection_threshold
        self.hysteresis_margin: float = TapDisplaySettings.hysteresis_margin
        self.decay_threshold: float = 15.0
        self.current_peaks: list[ResonantPeak] = []
        self.identified_modes: list = []
        self.current_decay_time: float | None = None
        self.frozen_frequencies: list[float] = []
        self.frozen_magnitudes: list[float] = []
        self.peak_annotation_offsets: dict[str, tuple] = {}
        self.peak_mode_overrides: dict[str, str | None] = {}
        self.selected_peak_ids: set[str] = set()
        self.annotation_visibility_mode: str = "all"
        self.display_mode: AnalysisDisplayMode = AnalysisDisplayMode.LIVE
        self.is_measurement_complete: bool = False
        self.is_detecting: bool = False
        self.current_tap_count: int = 0
        self.tap_progress: float = 0.0
        self.status_message: str = "Tap the guitar to begin"
        # tap detection state
        self.is_above_threshold: bool = False
        self.just_exited_warmup: bool = False
        self.analyzer_start_time: datetime | None = None
        self.last_tap_time: datetime | None = None
        self.noise_floor_estimate: float = -60.0
        self.tap_detected: bool = False
        # decay tracking state
        self.peak_magnitude_history: list = []
        self.is_tracking_decay: bool = False
        # auxiliary
        self.user_has_modified_peak_selection: bool = False
        self.loaded_measurement_peaks: list[ResonantPeak] | None = None
        self.selected_peak_frequencies: list[float] = []
        self.is_loading_measurement: bool = False
        self.comparison_spectra: list = []
        self.saved_measurements: list[TapToneMeasurement] = []
```

Audio-hardware-specific setup (mic, processing thread) moves to a separate `start(fft_params, audio_device, calibration)` method, called only by the view layer. Tests never call `start()`.

---

## Part 6 — Restructure `find_peaks` to Match Swift's Hz-Based API ✅ DONE

**Status:** `find_peaks(magnitudes, frequencies, min_hz, max_hz)` takes Hz-based float
lists and returns `list[ResonantPeak]`. Mirrors Swift's
`findPeaks(magnitudes:frequencies:minHz:maxHz:) → [ResonantPeak]`.

### Current State

```python
def find_peaks(self, mag_y_db: ndarray) -> tuple[bool, ndarray]:
    # uses bin indices internally, returns (triggered, ndarray N×3)
```

### Swift API

```swift
func findPeaks(magnitudes: [Float], frequencies: [Float],
               minHz: Float? = nil, maxHz: Float? = nil) -> [ResonantPeak]
```

### Required Change

```python
def find_peaks(self, magnitudes: list[float], frequencies: list[float],
               min_hz: float | None = None, max_hz: float | None = None) -> list[ResonantPeak]:
    """Mirrors Swift findPeaks(magnitudes:frequencies:minHz:maxHz:)."""
```

Also add:

```python
def remove_duplicate_peaks(self, peaks: list[ResonantPeak]) -> list[ResonantPeak]:
    """Mirrors Swift removeDuplicatePeaks(_:)."""

def average_spectra(self, from_taps: list[tuple]) -> tuple[list[float], list[float]]:
    """Mirrors Swift averageSpectra(from:). Returns (frequencies, magnitudes)."""
```

---

## Part 7 — Restructure Annotation Management to Match Swift's UUID-Keyed API

### Current State

`peak_annotation_offsets` is keyed by **frequency** (a float). This is a Python-only workaround because Python didn't have stable peak IDs.

### Swift Pattern

`peakAnnotationOffsets: [UUID: CGPoint]` — keyed by the peak's stable `UUID`. The UUID is part of `ResonantPeak`.

### Required Change

Once `ResonantPeak` always carries a `str` UUID:

1. Change `peak_annotation_offsets` key type from `float` to `str` (UUID string)
2. Add Swift-matching methods:

```python
def update_annotation_offset(self, peak_id: str, offset: tuple[float, float]) -> None:
    """Mirrors Swift updateAnnotationOffset(for:offset:)."""

def get_annotation_offset(self, peak_id: str) -> tuple[float, float]:
    """Mirrors Swift getAnnotationOffset(for:)."""

def apply_annotation_offsets(self, offsets: dict[str, tuple]) -> None:
    """Mirrors Swift applyAnnotationOffsets(_:)."""

def reset_all_annotation_offsets(self) -> None:
    """Mirrors Swift resetAllAnnotationOffsets()."""
```

3. Add to `TapToneAnalyzerModeOverrideManagementMixin`:

```python
def set_mode_override(self, override: str | None, peak_id: str) -> None:
    """Mirrors Swift setModeOverride(_:for:). None = .auto."""

def has_manual_override(self, peak_id: str) -> bool:
    """Mirrors Swift hasManualOverride(for:)."""

def effective_mode_label(self, peak: ResonantPeak) -> str:
    """Mirrors Swift effectiveModeLabel(for:)."""
```

4. Add to `TapToneAnalyzerAnnotationManagementMixin`:

```python
def toggle_peak_selection(self, peak_id: str) -> None:
    """Mirrors Swift togglePeakSelection(_:)."""

def select_all_peaks(self) -> None:
    """Mirrors Swift selectAllPeaks()."""

def select_no_peaks(self) -> None:
    """Mirrors Swift selectNoPeaks()."""

def cycle_annotation_visibility(self) -> None:
    """Mirrors Swift cycleAnnotationVisibility()."""

@property
def visible_peaks(self) -> list[ResonantPeak]:
    """Mirrors Swift visiblePeaks computed property."""
```

---

## Part 8 — Rename `recalculate_frozen_peaks_if_needed`

### Current State

`_recalculate_peaks()` in `TapToneAnalyzerAnalysisHelpersMixin` — private, differently named.

### Required Change

Rename to `recalculate_frozen_peaks_if_needed()` (exact Swift name). Restructure internals to operate on `list[ResonantPeak]` rather than `ndarray`.

---

## Part 9 — Test Rewrites as Direct Ports

Once the above production code changes are done, all tests become direct ports with no stubs or adapters needed.

### `test_tap_detection.py`

Replace `TapDetector`-based tests with analyzer-based tests:

```python
def make_sut(threshold=-40.0, hysteresis=5.0, number_of_taps=1):
    sut = TapToneAnalyzer()
    sut.tap_detection_threshold = threshold
    sut.hysteresis_margin = hysteresis
    sut.number_of_taps = number_of_taps
    sut.analyzer_start_time = datetime.now() - timedelta(seconds=2)
    sut.just_exited_warmup = False
    TapDisplaySettings.measurement_type = MeasurementType.ACOUSTIC
    return sut

class TestTapDetection:
    def test_T1_above_threshold_sets_tap_detected(self):
        sut = make_sut(threshold=-40)
        sut.is_detecting = True
        sut.is_above_threshold = False
        sut.detect_tap(peak_magnitude=-35, magnitudes=fake_mags, frequencies=fake_freqs)
        assert sut.tap_detected == True
    # etc. — exact ports of T1–T8
```

### `test_decay_tracking.py`

Replace `DecayTracker`-based tests:

```python
class TestDecayTracking:
    def test_DK1_measure_decay_time_returns_none_with_no_history(self):
        sut = TapToneAnalyzer()
        sut.peak_magnitude_history = []
        result = sut.measure_decay_time(tap_time=datetime.now())
        assert result is None
    # etc. — exact ports of DK1–DK7
```

### `test_annotation_state.py`

Replace JSON round-trip tests with live-state tests:

```python
class TestAnnotationOffsets:
    def test_D1_update_stores_by_peak_id(self):
        sut = TapToneAnalyzer()
        peak = ResonantPeak(frequency=200, magnitude=-20)
        sut.update_annotation_offset(peak.id, (10.0, 20.0))
        assert sut.peak_annotation_offsets[peak.id] == (10.0, 20.0)
    # etc. — exact ports of D1–PS6
```

### `test_frozen_peak_recalculation.py`

Replace `_remap_by_freq` helper tests:

```python
class TestFrozenPeakRecalculation:
    def test_PR1_skipped_while_loading(self):
        sut = TapToneAnalyzer()
        sut.is_loading_measurement = True
        sut.is_measurement_complete = True
        sut.frozen_frequencies = [100.0, 200.0]
        sut.frozen_magnitudes = [-30.0, -25.0]
        original = list(sut.current_peaks)
        sut.recalculate_frozen_peaks_if_needed()
        assert sut.current_peaks == original
    # etc. — exact ports of PR1–PR7
```

---

## Summary of Files Changed

| File | Action | Status |
|------|--------|--------|
| `models/observable_object.py` | **New** — `@published` descriptor + `ObservableObject` base | ✅ Done (in `swiftui_compat`) |
| `models/tap_display_settings.py` | **New** — move `AppSettings` here from views, eliminating model→view import | ✅ Done |
| `models/tap_tone_analyzer.py` | **Rewrite** — new `__init__`, `ObservableObject` base, no `QObject`, all stored properties | ✅ Done |
| `models/tap_tone_analyzer_decay_tracking.py` | **Delete `DecayTracker`** — replace entirely with `TapToneAnalyzerDecayTrackingMixin` | ✅ Done |
| `models/tap_tone_analyzer_tap_detection.py` | **Delete `TapDetector`** — merge all state and logic into `TapToneAnalyzerTapDetectionHandlerMixin` | ✅ Done |
| `models/tap_tone_analyzer_peak_analysis.py` | **Rewrite `find_peaks`** — Hz-based signature, returns `list[ResonantPeak]` | ✅ Done |
| `models/tap_tone_analyzer_annotation_management.py` | **Expand** — add all Swift annotation/selection methods | ✅ Done — all Swift methods present (`updateAnnotationOffset`, `getAnnotationOffset`, `resetAnnotationOffset`, `resetAllAnnotationOffsets`, `applyAnnotationOffsets`, `selectLongitudinalPeak`, `selectCrossPeak`, `selectFlcPeak`); plan entries for `toggle_peak_selection` etc. have no Swift equivalent |
| `models/tap_tone_analyzer_mode_override_management.py` | **Expand** — add `set_mode_override`, `effective_mode_label`, `has_manual_override` | ✅ Done — all Swift methods present (`applyModeOverrides`, `resetAllModeOverrides`, `resetModeOverride`); `set_mode_override`, `effective_mode_label`, `has_manual_override` have no Swift equivalent |
| `models/tap_tone_analyzer_analysis_helpers.py` | **Rename** `_recalculate_peaks` → `recalculate_frozen_peaks_if_needed`; port internals to `list[ResonantPeak]` | ✅ Done — renamed; all call sites updated; frozen and loaded-measurement paths correct |
| `models/tap_tone_analyzer_control.py` | **Rewrite** — `start_tap_sequence`, `reset`, `pause_tap_detection` match Swift method shapes | ✅ Done (`start_tap_sequence`, `pause_tap_detection`, `cancel_tap_sequence` present) |
| `models/resonant_peak.py` | **Ensure** UUID `id` always present; add `make_peak` factory on analyzer | ✅ Done (`id: str` auto-assigned on construction) |
| `models/fft_processing_thread.py` | **Remove** `TapDetector`/`DecayTracker` ownership — becomes pure audio callback deliverer | ✅ Done (pure DSP thread; no `TapDetector`/`DecayTracker`) |
| `tests/test_tap_detection.py` | **Rewrite** — `TapToneAnalyzer`-based, T1–T8 direct ports | ✅ Done |
| `tests/test_decay_tracking.py` | **Rewrite** — `TapToneAnalyzer`-based, DK1–DK7 direct ports | ✅ Done |
| `tests/test_annotation_state.py` | **Rewrite** — live state tests, D1–PS6 direct ports | ✅ Done (UUID-keyed) |
| `tests/test_frozen_peak_recalculation.py` | **Rewrite** — `recalculate_frozen_peaks_if_needed`, PR1–PR7 direct ports | ✅ Done — `TestRecalculateFrozenPeaksIfNeeded` added (PR-A1–A5 call `recalculate_frozen_peaks_if_needed` directly on `TapToneAnalyzer`); PR1–PR7 remap helpers retained |
| `tests/test_peak_finding.py` | **Rewrite** — Hz-based API, `list[ResonantPeak]` results | ✅ Done |
| `views/` (all) | **Update** signal connections: `pyqtSignal.connect` → `analyzer.observe(...)` | Pending — view-layer work (see `SWIFTUI_COMPAT_VIEW_LAYER_PLAN.md`) |

---

## Migration Strategy

This is a ground-up rewrite of the model layer. The recommended sequence minimises the amount of broken intermediate state:

1. ✅ **`ObservableObject` + `TapDisplaySettings`** first — no dependencies on anything else; unblocks all subsequent steps.
2. ✅ **`ResonantPeak` UUID stabilisation** — needed before annotation management can be UUID-keyed and before `find_peaks` can return `list[ResonantPeak]`.
3. ✅ **`TapToneAnalyzer.__init__` restructuring** — new property names, `ObservableObject` base, hardware-free defaults.
4. ✅ **Merge `TapDetector` → `detect_tap()`** and **`DecayTracker` → `TapToneAnalyzerDecayTrackingMixin`** — now that `TapToneAnalyzer` is instantiable without hardware, tests call methods directly on it, exactly like Swift tests do.
5. ✅ **`find_peaks` Hz-based rewrite** — depends on `ResonantPeak` UUID stabilisation.
6. ✅ **Annotation management expansion** — all Swift annotation and mode-override methods present. Plan entries for `toggle_peak_selection`, `select_all_peaks`, `set_mode_override`, etc. have no Swift equivalent and were dropped. `_recalculate_peaks` renamed to `recalculate_frozen_peaks_if_needed`; all call sites updated; `test_frozen_peak_recalculation.py` updated to call it directly on `TapToneAnalyzer`.
7. **View layer updates** — adapt signal connections to `observe()` pattern last, after model layer is solid and tested. See `SWIFTUI_COMPAT_VIEW_LAYER_PLAN.md`.
8. ✅ **Test rewrites** — complete: tap detection, decay tracking, annotation state, peak finding, frozen peak recalculation all done.

---

## Architectural Principles Being Enforced

| Principle | Swift | Python (after restructuring) |
|---|---|---|
| Reactive state | `@Published` + Combine | `@published` descriptor + `ObservableObject` |
| State ownership | All state on `TapToneAnalyzer` | All state on `TapToneAnalyzer` |
| No separate detector objects | `detectTap()` is a method | `detect_tap()` is a method |
| No separate decay objects | `trackDecayFast()` is a method | `track_decay_fast()` is a method |
| Peak representation | `[ResonantPeak]` structs | `list[ResonantPeak]` objects |
| Peak identity | `UUID` stable across recalculation | `str` UUID stable across recalculation |
| Annotation keys | `[UUID: CGPoint]` | `dict[str, tuple[float, float]]` |
| Settings layer | Model-layer `TapDisplaySettings` | Model-layer `TapDisplaySettings` |
| Test construction | `TapToneAnalyzer(fftAnalyzer: fft)` | `TapToneAnalyzer()` |
| Test state setup | Direct property assignment | Direct property assignment |
| Test method calls | Methods on analyzer | Methods on analyzer |
