"""
Tap-tone analysis coordinator — mirrors Swift TapToneAnalyzer.swift.

The Swift TapToneAnalyzer class is split across nine Swift extension files.
This Python package mirrors that structure using separate modules:

  tap_tone_analyzer_decay_tracking.py      → DecayTracker
      mirrors Swift TapToneAnalyzer+DecayTracking.swift

  tap_tone_analyzer_tap_detection.py       → TapDetector
      mirrors Swift TapToneAnalyzer+TapDetection.swift

  tap_tone_analyzer_spectrum_capture.py    → PlateCapture
      mirrors Swift TapToneAnalyzer+SpectrumCapture.swift

  tap_tone_analyzer_control.py             → TapToneAnalyzerControlMixin
      mirrors Swift TapToneAnalyzer+Control.swift

  tap_tone_analyzer_peak_analysis.py       → TapToneAnalyzerPeakAnalysisMixin
      mirrors Swift TapToneAnalyzer+PeakAnalysis.swift

  tap_tone_analyzer_analysis_helpers.py    → TapToneAnalyzerAnalysisHelpersMixin
      mirrors Swift TapToneAnalyzer+AnalysisHelpers.swift

  tap_tone_analyzer_tap_detection_handler.py → TapToneAnalyzerTapDetectionHandlerMixin
      mirrors the analyzer-side of Swift TapToneAnalyzer+TapDetection.swift

  tap_tone_analyzer_annotation_management.py → TapToneAnalyzerAnnotationManagementMixin
      mirrors Swift TapToneAnalyzer+AnnotationManagement.swift

  tap_tone_analyzer_measurement_management.py → TapToneAnalyzerMeasurementManagementMixin
      mirrors Swift TapToneAnalyzer+MeasurementManagement.swift

  tap_tone_analyzer_mode_override_management.py → TapToneAnalyzerModeOverrideManagementMixin
      mirrors Swift TapToneAnalyzer+ModeOverrideManagement.swift

  analysis_display_mode.py                → AnalysisDisplayMode
      mirrors Swift AnalysisDisplayMode enum defined at file scope in TapToneAnalyzer.swift.
      Lives in its own file so mixin modules can import it without circular deps.

  fft_parameters.py                       → FftParameters
  fft_processing_thread.py                → FftProcessingThread
      Python-only — no Swift counterparts.  Swift stores equivalent values
      directly on TapToneAnalyzer and uses AVAudioEngine taps instead of a thread.

This file (tap_tone_analyzer.py) contains:
  - The TapToneAnalyzer class declaration, stored properties, and __init__
    (mirrors the top of Swift TapToneAnalyzer.swift)
  - Re-exports of DecayTracker, TapDetector, PlateCapture, AnalysisDisplayMode
    for import convenience.
"""

from __future__ import annotations

# ── Re-exports (backward compatibility) ──────────────────────────────────────
# Existing code that does:
#   from models.tap_tone_analyzer import DecayTracker, TapDetector, PlateCapture
# continues to work unchanged.

from .tap_tone_analyzer_decay_tracking import DecayTracker
from .tap_tone_analyzer_tap_detection import TapDetector
from .tap_tone_analyzer_spectrum_capture import PlateCapture

# ── TapToneAnalyzer mixin imports ─────────────────────────────────────────────

from .tap_tone_analyzer_control import TapToneAnalyzerControlMixin
from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
from .tap_tone_analyzer_analysis_helpers import TapToneAnalyzerAnalysisHelpersMixin
from .tap_tone_analyzer_tap_detection import TapToneAnalyzerTapDetectionHandlerMixin
from .tap_tone_analyzer_annotation_management import TapToneAnalyzerAnnotationManagementMixin
from .tap_tone_analyzer_measurement_management import TapToneAnalyzerMeasurementManagementMixin
from .tap_tone_analyzer_mode_override_management import TapToneAnalyzerModeOverrideManagementMixin

# ── AnalysisDisplayMode ───────────────────────────────────────────────────────
# Mirrors Swift AnalysisDisplayMode enum defined in TapToneAnalyzer.swift.
# Lives in analysis_display_mode.py so the mixin files can import it without
# creating a circular dependency (they are imported by this file).

from .analysis_display_mode import AnalysisDisplayMode

# ── Python-only implementation types ─────────────────────────────────────────
# FftParameters and FftProcessingThread have no Swift counterparts; Swift stores
# equivalent values directly on TapToneAnalyzer / uses AVAudioEngine taps.

from .fft_parameters import FftParameters
from .fft_processing_thread import FftProcessingThread

# ── PySide6 ─────────────────────────────────────────────────────────────────────

from PySide6 import QtCore

# ── swiftui_compat — ObservableObject + Published ────────────────────────────
# TapToneAnalyzer mirrors Swift's `final class TapToneAnalyzer: ObservableObject`.
# swiftui_compat provides ObservableObject (subscribe/notify base) and
# Published (class-level descriptor that fires _notify_change on every write).
# Views connect via analyzer.subscribe(callback) in addition to Qt signals.

from swiftui_compat import ObservableObject, Published


# ── TapToneAnalyzer ───────────────────────────────────────────────────────────
# Mirrors the top-level Swift TapToneAnalyzer class declaration and its stored
# properties / init.  All methods live in the mixin base classes above,
# matching the Swift extension-file organisation.

class TapToneAnalyzer(
    TapToneAnalyzerControlMixin,
    TapToneAnalyzerPeakAnalysisMixin,
    TapToneAnalyzerAnalysisHelpersMixin,
    TapToneAnalyzerTapDetectionHandlerMixin,
    TapToneAnalyzerAnnotationManagementMixin,
    TapToneAnalyzerMeasurementManagementMixin,
    TapToneAnalyzerModeOverrideManagementMixin,
    ObservableObject,
    QtCore.QObject,
):
    """Central analysis coordinator — owns all analysis state and business logic.

    Mirrors Swift's `final class TapToneAnalyzer: ObservableObject`.

    Inherits from both swiftui_compat.ObservableObject and QtCore.QObject:
    - ObservableObject provides subscribe()/notify() for model-layer observers
      (the Python equivalent of Combine's objectWillChange publisher).
    - QtCore.QObject provides Qt signals for the existing view layer.

    @Published properties declared at class level mirror Swift's @Published vars.
    Setting them fires _notify_change so any subscriber (including future SwiftUI-
    style views) can react without polling.  Qt signals remain for the current
    FftCanvas/TapToneAnalysisView layer.
    """

    # ── @Published properties (mirrors Swift @Published vars) ────────────────
    # Declared at class level so the Published descriptor is active on every
    # instance.  Setting self.x = value in __init__ or any method fires
    # _notify_change(attr_name, new_value) through the ObservableObject base.
    #
    # Mirrors Swift TapToneAnalyzer stored @Published properties.

    # MARK: - Configuration
    peak_threshold: float = Published(-60.0)        # mirrors peakThreshold: Float
    min_frequency: float = Published(30.0)          # mirrors minFrequency: Float
    max_frequency: float = Published(2000.0)        # mirrors maxFrequency: Float
    max_peaks: int = Published(0)                   # mirrors maxPeaks: Int
    decay_threshold: float = Published(15.0)        # mirrors decayThreshold: Float
    number_of_taps: int = Published(1)              # mirrors numberOfTaps: Int
    capture_window: float = Published(0.2)          # mirrors captureWindow: TimeInterval
    tap_detection_threshold: float = Published(-40.0)   # mirrors tapDetectionThreshold: Float
    hysteresis_margin: float = Published(3.0)       # mirrors hysteresisMargin: Float

    # MARK: - Published Results
    current_peaks: list = Published([])             # mirrors currentPeaks: [ResonantPeak]
    identified_modes: list = Published([])          # mirrors identifiedModes: [(peak, mode)]
    current_decay_time: object = Published(None)    # mirrors currentDecayTime: Float?
    saved_measurements: list = Published([])        # mirrors savedMeasurements: [TapToneMeasurement]

    # MARK: - Published Detection State
    average_magnitude: float = Published(-100.0)    # mirrors averageMagnitude: Float
    tap_detection_level: float = Published(-100.0)  # mirrors tapDetectionLevel: Float
    tap_detected: bool = Published(False)           # mirrors tapDetected: Bool
    is_detecting: bool = Published(False)           # mirrors isDetecting: Bool
    is_detection_paused: bool = Published(False)    # mirrors isDetectionPaused: Bool
    is_ready_for_detection: bool = Published(True)  # mirrors isReadyForDetection: Bool
    current_tap_count: int = Published(0)           # mirrors currentTapCount: Int
    tap_progress: float = Published(0.0)            # mirrors tapProgress: Float
    status_message: str = Published("Tap the guitar to begin")  # mirrors statusMessage: String

    # MARK: - Published Frozen Spectrum
    frozen_frequencies: list = Published([])        # mirrors frozenFrequencies: [Float]
    frozen_magnitudes: list = Published([])         # mirrors frozenMagnitudes: [Float]

    # MARK: - Published Annotation & Selection State
    peak_annotation_offsets: dict = Published({})   # mirrors peakAnnotationOffsets: [UUID: CGPoint]
    peak_mode_overrides: dict = Published({})       # mirrors peakModeOverrides: [UUID: UserAssignedMode]
    selected_peak_ids: set = Published(set())       # mirrors selectedPeakIDs: Set<UUID>
    highlighted_peak_id: object = Published(None)   # mirrors highlightedPeakID: UUID?
    annotation_visibility_mode: str = Published("selected")  # mirrors annotationVisibilityMode

    # MARK: - Published Measurement Complete State
    is_measurement_complete: bool = Published(False)  # mirrors isMeasurementComplete: Bool

    # MARK: - Signals (Qt — view layer bridge, no Swift equivalent) ──────────
    # ── Signals (Python equivalents of Swift @Published properties) ────────
    # New peak list emitted after every analysis frame and after threshold/range changes.
    peaksChanged: QtCore.Signal = QtCore.Signal(object)          # ndarray (N, 3)
    # Full spectrum ready for the view to draw.
    spectrumUpdated: QtCore.Signal = QtCore.Signal(object, object)  # (freqs, mags_db)
    # A single tap has been fully captured (all required taps averaged).
    tapDetectedSignal: QtCore.Signal = QtCore.Signal()
    # Live tap count update: (captured, total).
    tapCountChanged: QtCore.Signal = QtCore.Signal(int, int)
    # Ring-out time measured by DecayTracker (seconds).
    ringOutMeasured: QtCore.Signal = QtCore.Signal(float)
    # Input level 0-100 scale (dBFS + 100).
    levelChanged: QtCore.Signal = QtCore.Signal(int)
    # FFT frame diagnostics: (fps, sample_dt, processing_dt).
    framerateUpdate: QtCore.Signal = QtCore.Signal(float, float, float)
    # Averaging: number of completed averages.
    averagesChanged: QtCore.Signal = QtCore.Signal(int)
    # Emitted on every live FFT frame (for average-enable logic).
    newSample: QtCore.Signal = QtCore.Signal(bool)
    # Display mode changed: emits the new DisplayMode enum value.
    displayModeChanged: QtCore.Signal = QtCore.Signal(object)
    # Measurement complete state changed.
    measurementComplete: QtCore.Signal = QtCore.Signal(bool)
    # Hot-plug: list[str] of current input device names.
    devicesChanged: QtCore.Signal = QtCore.Signal(list)
    # Hot-plug: name of the device that disappeared.
    currentDeviceLost: QtCore.Signal = QtCore.Signal(str)
    # Plate/brace phase status text for display.
    plateStatusChanged: QtCore.Signal = QtCore.Signal(str)
    # Plate analysis complete: (fL, fC, fFLC) Hz.
    plateAnalysisComplete: QtCore.Signal = QtCore.Signal(float, float, float)
    # Tap detection pause state changed.
    tapDetectionPaused: QtCore.Signal = QtCore.Signal(bool)
    # Emitted when comparison overlay data changes (True=entering, False=leaving).
    comparisonChanged: QtCore.Signal = QtCore.Signal(bool)
    # Emitted when per-phase material spectra change for plate/brace measurements.
    # Payload: list of (label, (r,g,b), freqs, mags) tuples — empty list clears the overlay.
    # Mirrors Swift @Published var longitudinalSpectrum / crossSpectrum / flcSpectrum
    # which TapToneAnalysisView+SpectrumViews observes to build materialSpectra.
    materialSpectraChanged: QtCore.Signal = QtCore.Signal(list)
    # Emitted when savedMeasurements list changes (mirrors Swift @Published var savedMeasurements).
    savedMeasurementsChanged: QtCore.Signal = QtCore.Signal()
    # Emitted when frequency range changes (fmin, fmax).
    freqRangeChanged: QtCore.Signal = QtCore.Signal(int, int)
    # Peak info for status bar: (peak_hz, peak_db).
    peakInfoChanged: QtCore.Signal = QtCore.Signal(float, float)
    # Internal: fired from hotplug monitor thread → main thread (no-arg).
    _devicesRefreshed: QtCore.Signal = QtCore.Signal()

    def __init__(
        self,
        parent_widget,
        fft_params: "FftParameters",
        audio_device,
        calibration_corrections,
        guitar_type,
    ) -> None:
        """
        Args:
            parent_widget:           The FftCanvas (QObject parent).
            fft_params:              FftParameters instance (sample_freq, n_f, window_fcn, …).
            audio_device:            AudioDevice to open, or None for the system default.
            calibration_corrections: ndarray of per-bin dB corrections, or None.
            guitar_type:             GuitarType enum value for mode classification.
        """
        import sounddevice as _sd
        import numpy as _np
        from models.realtime_fft_analyzer import RealtimeFFTAnalyzer as _Mic
        from models import guitar_mode as _gm
        from models import measurement_type as _mt_mod
        from models import microphone_calibration as _mc_mod
        from models.tap_display_settings import TapDisplaySettings as _tds

        # Initialise both bases explicitly.
        # Qt's metaclass does not participate in Python's cooperative super()
        # chain, so both must be called directly.
        QtCore.QObject.__init__(self, parent_widget)
        ObservableObject.__init__(self)

        self._sd = _sd
        self._np = _np
        self._gm = _gm
        self._tds = _tds
        self._mc_mod = _mc_mod

        # ── Audio engine (mirrors Swift's analyzer: RealtimeFFTAnalyzer) ──
        # FFT configuration (fft_size, window_fcn) lives on the mic object,
        # matching Swift where RealtimeFFTAnalyzer owns fftSize, window, etc.
        self._devicesRefreshed.connect(self._on_devices_refreshed)
        self.mic: _Mic = _Mic(
            parent_widget,
            rate=fft_params.sample_freq,
            chunksize=4096,
            device=audio_device,
            on_devices_changed=self._devicesRefreshed.emit,
            fft_size=fft_params.n_f,
        )

        # ── FFT configuration ──────────────────────────────────────────────
        # Stored as fft_data for backward compatibility with existing call sites.
        self.fft_data = fft_params
        import numpy as np
        x_axis = np.arange(0, fft_params.h_n_f + 1)
        self.freq = x_axis * fft_params.sample_freq / fft_params.n_f

        # ── Calibration ────────────────────────────────────────────────────
        self._calibration_corrections = calibration_corrections
        self._calibration_device_name: str = audio_device.name if audio_device else ""

        # ── Guitar/mode classification ─────────────────────────────────────
        self._guitar_type = guitar_type

        # ── Display mode (mirrors Swift AnalysisDisplayMode) ───────────────
        # AnalysisDisplayMode lives in models/analysis_display_mode.py — no circular import.
        # Mirrors Swift TapToneAnalyzer @Published var displayMode: AnalysisDisplayMode = .live
        self._display_mode: AnalysisDisplayMode = AnalysisDisplayMode.LIVE

        # ── @Published property initialisation from persisted settings ───────
        # These assignments go through the Published descriptor, setting the
        # per-instance storage key and firing _notify_change on the
        # ObservableObject base.  Mirrors Swift's property initialiser syntax:
        #   @Published var minFrequency: Float = TapDisplaySettings.analysisMinFrequency
        self.min_frequency = float(_tds.analysis_f_min())
        self.max_frequency = float(_tds.analysis_f_max())
        self.max_peaks = _tds.max_peaks()
        self.peak_threshold = float(_tds.peak_threshold())
        self.tap_detection_threshold = float(_tds.tap_detection_threshold())
        self.hysteresis_margin = float(_tds.hysteresis_margin())
        self.annotation_visibility_mode = _tds.annotation_visibility_mode()

        # ── Measurement state ──────────────────────────────────────────────
        # is_measurement_complete is a @Published property (class-level default False).
        # No re-assignment needed here — the class default is correct.

        # Saved measurement list — mirrors Swift @Published var savedMeasurements: [TapToneMeasurement].
        # Loaded once at startup and kept in sync; all mutations go through the
        # mixin methods (save_measurement, update_measurement, delete_measurement,
        # delete_all_measurements) which persist and emit savedMeasurementsChanged.
        from views.tap_analysis_results_view import load_all_measurements as _load
        self.saved_measurements = _load()
        # Legacy alias kept for any remaining view code that reads savedMeasurements.
        # Will be removed once the view layer is migrated.
        self.savedMeasurements = self.saved_measurements

        # ── Peak analysis state ────────────────────────────────────────────
        self.threshold: int = 60                          # 0-100 scale (legacy)
        self.fmin: int = 0
        self.fmax: int = 1000
        self.n_fmin: int = 0
        self.n_fmax: int = 0
        self.saved_mag_y_db = np.array([])
        self.saved_peaks = np.zeros((0, 3))               # (freq, mag, Q)
        self._loaded_measurement_peaks = None             # ndarray or None
        self.selected_peak: float = 0.0
        # Frequency axis that matches saved_mag_y_db.
        # Mirrors Swift frozenFrequencies: [Float] = [] on TapToneAnalyzer.
        # A loaded measurement captured by Swift's gated FFT (32 768-sample window
        # → 16 384 bins) has a different length than the live self.freq (32 769 bins
        # for fft_size=65 536).  Storing the loaded axis here keeps self.freq intact
        # (always the live FFT axis) and prevents shape-mismatch crashes when a
        # queued FFT frame fires while a loaded measurement is displayed.
        self._saved_freq = np.array([])

        # ── Averaging ──────────────────────────────────────────────────────
        self.avg_enable: bool = False
        self.max_average_count: int = 1
        self.mag_y_sum = []
        self.num_averages: int = 0

        # ── Multi-tap accumulator ─────────────────────────────────────────
        self._tap_num: int = 1
        self._tap_spectra: list = []

        # ── Auto-scale ────────────────────────────────────────────────────
        self._auto_scale_db: bool = False

        # ── Measurement type ──────────────────────────────────────────────
        self._measurement_type = _mt_mod.MeasurementType.CLASSICAL

        # ── Plate/brace capture ───────────────────────────────────────────
        self.plate_capture = PlateCapture(
            sample_freq=fft_params.sample_freq,
            n_f=fft_params.n_f,
            parent=self,
        )
        self.plate_capture.stateChanged.connect(self.plateStatusChanged)
        self.plate_capture.analysisComplete.connect(self.plateAnalysisComplete)
        self._current_mag_y = np.array([])

        # ── Per-phase material spectra (mirrors Swift longitudinalSpectrum / crossSpectrum / flcSpectrum)
        # Owned by the analyzer so that FftCanvas can react reactively via materialSpectraChanged.
        # Each entry is (label, (r,g,b), freqs_list, mags_list).  Empty list = no overlay.
        self._material_spectra: list = []

        # ── Annotation offsets (mirrors Swift peakAnnotationOffsets: [UUID: CGPoint]) ──
        # Keyed by peak frequency (float) → (x_offset, y_offset) in data-space coordinates.
        # Stored on the analyzer so dragged positions survive pan/zoom annotation rebuilds.
        self.peak_annotation_offsets: dict[float, tuple[float, float]] = {}

        # ── Comparison overlay data ───────────────────────────────────────
        self.comparison_labels: list = []        # list of (label, color) tuples
        # _comparison_data is for the analyzer's knowledge of what's being compared;
        # actual PlotDataItem curves live in FftCanvas.
        self._comparison_data: list = []

        # ── Processing thread ─────────────────────────────────────────────
        # TapToneAnalyzer owns and creates its processing thread — mirrors Swift's
        # architecture where TapToneAnalyzer owns its entire audio processing pipeline.
        # FftCanvas starts the thread via start_analyzer() and stops it via stop_analyzer().
        self._proc_thread: FftProcessingThread = FftProcessingThread(
            mic=self.mic,
            parent=self,
        )

    # ------------------------------------------------------------------ #
    # display_mode property — kept in sync with FftCanvas.display_mode
    # ------------------------------------------------------------------ #

    @property
    def display_mode(self):
        return self._display_mode

    @display_mode.setter
    def display_mode(self, value) -> None:
        self._display_mode = value
        self.displayModeChanged.emit(value)

    @property
    def is_comparing(self) -> bool:
        """True when in COMPARISON display mode.

        Mirrors Swift TapToneAnalyzer computed property that checks displayMode == .comparison.
        """
        return self._display_mode == AnalysisDisplayMode.COMPARISON

    def set_material_spectra(self, spectra: list) -> None:
        """Set per-phase plate/brace spectra and notify observers.

        Mirrors Swift: setting longitudinalSpectrum / crossSpectrum / flcSpectrum
        @Published properties on TapToneAnalyzer, which causes TapToneAnalysisView
        to rebuild its materialSpectra computed property and pass it to SpectrumView.

        Parameters
        ----------
        spectra:
            List of (label, (r,g,b), freqs, mags) tuples.  Pass [] to clear.
        """
        self._material_spectra = spectra
        self.materialSpectraChanged.emit(spectra)

    # ------------------------------------------------------------------ #
    # Processing thread management
    # ------------------------------------------------------------------ #

    def recreate_proc_thread(self) -> "FftProcessingThread":
        """Destroy the current processing thread and create a fresh one.

        Applies the current calibration and measurement type to the new thread.
        FftCanvas calls this when it needs to reset all processing state
        (e.g. after the analyzer was already running and the user presses Start
        again).

        Returns the new FftProcessingThread so FftCanvas can reconnect signals.

        Python-only — Swift achieves equivalent reset via AVAudioEngine stop/start.
        """
        self._proc_thread = FftProcessingThread(
            mic=self.mic,
            parent=self,
        )
        self._proc_thread.set_calibration(self._calibration_corrections)
        self._proc_thread.set_measurement_type(self._measurement_type.is_guitar)
        return self._proc_thread
