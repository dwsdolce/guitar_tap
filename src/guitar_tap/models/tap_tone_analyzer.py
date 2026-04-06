"""
Tap-tone analysis coordinator — mirrors Swift TapToneAnalyzer.swift.

The Swift TapToneAnalyzer class is split across nine Swift extension files.
This Python package mirrors that structure using separate modules:

  tap_tone_analyzer_decay_tracking.py      → TapToneAnalyzerDecayTrackingMixin
      mirrors Swift TapToneAnalyzer+DecayTracking.swift

  tap_tone_analyzer_tap_detection.py       → TapToneAnalyzerTapDetectionHandlerMixin
      mirrors Swift TapToneAnalyzer+TapDetection.swift

  tap_tone_analyzer_spectrum_capture.py    → PlateCapture
      mirrors Swift TapToneAnalyzer+SpectrumCapture.swift

  tap_tone_analyzer_control.py             → TapToneAnalyzerControlMixin
      mirrors Swift TapToneAnalyzer+Control.swift

  tap_tone_analyzer_peak_analysis.py       → TapToneAnalyzerPeakAnalysisMixin
      mirrors Swift TapToneAnalyzer+PeakAnalysis.swift

  tap_tone_analyzer_analysis_helpers.py    → TapToneAnalyzerAnalysisHelpersMixin
      mirrors Swift TapToneAnalyzer+AnalysisHelpers.swift

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
      Python-only — no Swift counterpart.  Swift stores equivalent values
      directly on TapToneAnalyzer / RealtimeFFTAnalyzer.

This file (tap_tone_analyzer.py) contains:
  - The TapToneAnalyzer class declaration, stored properties, and __init__
    (mirrors the top of Swift TapToneAnalyzer.swift)
  - Re-export of PlateCapture and AnalysisDisplayMode for import convenience.
"""

from __future__ import annotations

# ── Re-exports ────────────────────────────────────────────────────────────────
from .tap_tone_analyzer_spectrum_capture import PlateCapture

# ── TapToneAnalyzer mixin imports ─────────────────────────────────────────────

from .tap_tone_analyzer_control import TapToneAnalyzerControlMixin
from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
from .tap_tone_analyzer_analysis_helpers import TapToneAnalyzerAnalysisHelpersMixin
from .tap_tone_analyzer_tap_detection import TapToneAnalyzerTapDetectionHandlerMixin
from .tap_tone_analyzer_decay_tracking import TapToneAnalyzerDecayTrackingMixin
from .tap_tone_analyzer_annotation_management import TapToneAnalyzerAnnotationManagementMixin
from .tap_tone_analyzer_measurement_management import TapToneAnalyzerMeasurementManagementMixin
from .tap_tone_analyzer_mode_override_management import TapToneAnalyzerModeOverrideManagementMixin

# ── AnalysisDisplayMode ───────────────────────────────────────────────────────
# Mirrors Swift AnalysisDisplayMode enum defined in TapToneAnalyzer.swift.
# Lives in analysis_display_mode.py so the mixin files can import it without
# creating a circular dependency (they are imported by this file).

from .analysis_display_mode import AnalysisDisplayMode

# ── Python-only implementation types ─────────────────────────────────────────
# FftParameters has no Swift counterpart; Swift stores equivalent values
# directly on TapToneAnalyzer / RealtimeFFTAnalyzer.
# _FftProcessingThread is a private implementation detail of RealtimeFFTAnalyzer
# (owned via mic.proc_thread); it is not imported here.

from .fft_parameters import FftParameters

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
    TapToneAnalyzerDecayTrackingMixin,
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

    def __init__(self, fft_analyzer=None) -> None:
        """Create a TapToneAnalyzer with all state at sensible defaults.

        Mirrors Swift ``TapToneAnalyzer(fftAnalyzer: RealtimeFFTAnalyzer)``.

        No audio hardware is required.  Tests can construct a bare instance and
        exercise all analysis methods directly.  Audio-hardware setup is deferred
        to ``start()``, which the view layer calls after construction.

        Args:
            fft_analyzer: Optional RealtimeFFTAnalyzer.  None-safe — tests never
                          pass one.  When provided (production path) the mic is
                          wired up inside ``start()`` rather than here.
        """
        import numpy as np
        from models import guitar_mode as _gm
        from models import measurement_type as _mt_mod
        from models.tap_display_settings import TapDisplaySettings as _tds
        from models.material_tap_phase import MaterialTapPhase as _MTP

        # Initialise both bases explicitly.
        # Qt's metaclass does not participate in Python's cooperative super()
        # chain, so both must be called directly.
        QtCore.QObject.__init__(self, None)
        ObservableObject.__init__(self)

        self._np = np
        self._gm = _gm
        self._tds = _tds

        # ── fft_analyzer reference (mirrors Swift's fftAnalyzer property) ──
        # None when constructed without audio hardware (tests, import-time).
        # Populated by start() in the production path.
        self.mic = fft_analyzer  # type: ignore[assignment]

        # ── FFT configuration ──────────────────────────────────────────────
        # fft_data and freq are populated by start(); None-safe guarded by
        # the n_fmin / n_fmax computed properties below.
        self.fft_data = None
        self.freq = np.array([])

        # ── Calibration ────────────────────────────────────────────────────
        self._calibration_corrections = None
        self._calibration_device_name: str = ""

        # ── Guitar/mode classification ─────────────────────────────────────
        self._guitar_type = None

        # ── Display mode (mirrors Swift AnalysisDisplayMode) ───────────────
        self._display_mode: AnalysisDisplayMode = AnalysisDisplayMode.LIVE

        # ── @Published property initialisation from persisted settings ───────
        # Mirrors Swift's property initialisers:
        #   @Published var minFrequency: Float = TapDisplaySettings.analysisMinFrequency
        self.min_frequency = float(_tds.analysis_f_min())
        self.max_frequency = float(_tds.analysis_f_max())
        self.max_peaks = _tds.max_peaks()
        self.peak_threshold = float(_tds.peak_threshold())
        self.tap_detection_threshold = float(_tds.tap_detection_threshold())
        self.hysteresis_margin = float(_tds.hysteresis_margin())
        self.annotation_visibility_mode = _tds.annotation_visibility_mode()

        # ── Measurement state ──────────────────────────────────────────────
        # saved_measurements loaded lazily by start() to avoid importing views here.
        self.saved_measurements = []
        self.savedMeasurements = self.saved_measurements  # legacy alias

        # ── Peak analysis state ────────────────────────────────────────────
        self.frozen_magnitudes = np.array([])
        self.current_peaks: list = []
        self.loaded_measurement_peaks: "list | None" = None
        self.selected_peak: float = 0.0
        self.frozen_frequencies = np.array([])

        # ── Averaging ──────────────────────────────────────────────────────
        self.avg_enable: bool = False
        self.max_average_count: int = 1
        self.mag_y_sum = []
        self.num_averages: int = 0

        # ── Multi-tap accumulator ─────────────────────────────────────────
        self.number_of_taps: int = 1
        self.captured_taps: list = []

        # ── Auto-scale ────────────────────────────────────────────────────
        self._auto_scale_db: bool = False

        # ── Measurement type ──────────────────────────────────────────────
        self._measurement_type = _mt_mod.MeasurementType.CLASSICAL

        # ── Plate/brace capture ───────────────────────────────────────────
        # Populated by start(); None-safe until then.
        self.plate_capture = None
        self._current_mag_y = np.array([])

        # ── Per-phase material spectra ────────────────────────────────────
        self._material_spectra: list = []

        # ── Comparison overlay data ───────────────────────────────────────
        self.comparison_labels: list = []
        self._comparison_data: list = []

        # ── Plate/brace phase state ───────────────────────────────────────
        self.material_tap_phase: "_MTP" = _MTP.NOT_STARTED
        self.longitudinal_spectrum = None
        self.cross_spectrum = None
        self.flc_spectrum = None
        self.longitudinal_peaks: list = []
        self.cross_peaks: list = []
        self.flc_peaks: list = []
        self.auto_selected_longitudinal_peak_id = None
        self.auto_selected_cross_peak_id = None
        self.auto_selected_flc_peak_id = None
        self.selected_longitudinal_peak = None
        self.selected_cross_peak = None
        self.selected_flc_peak = None
        self.user_selected_longitudinal_peak_id = None
        self.user_selected_cross_peak_id = None
        self.user_selected_flc_peak_id = None

        # ── Tap detection state (mirrors Swift TapToneAnalyzer stored properties)
        self.is_above_threshold: bool = False
        self.just_exited_warmup: bool = False
        self.analyzer_start_time: "float | None" = None
        self.last_tap_time: "float | None" = None
        self.noise_floor_estimate: float = -60.0
        self.noise_floor_alpha: float = 0.05
        self.warmup_period: float = 0.5
        self.tap_cooldown: float = 0.5
        self.tap_peak_level: float = -100.0

        # ── Decay tracking state (mirrors Swift TapToneAnalyzer stored properties)
        self.peak_magnitude_history: list = []
        self.is_tracking_decay: bool = False
        self._decay_tracking_timer = None

    def start(
        self,
        parent_widget,
        fft_params: "FftParameters",
        audio_device,
        calibration_corrections,
        guitar_type,
    ) -> None:
        """Wire up audio hardware and load persisted state.

        Called by the view layer (FftCanvas) after construction.  Tests never
        call this — they work with the bare defaults set by ``__init__``.

        This is the Python equivalent of Swift's audio-engine setup that lives
        in ``RealtimeFFTAnalyzer`` and is called from the view layer.

        Args:
            parent_widget:           The FftCanvas (QObject parent).
            fft_params:              FftParameters instance.
            audio_device:            AudioDevice to open, or None for the default.
            calibration_corrections: ndarray of per-bin dB corrections, or None.
            guitar_type:             GuitarType enum value for mode classification.
        """
        import sounddevice as _sd
        import numpy as np
        from models.realtime_fft_analyzer import RealtimeFFTAnalyzer as _Mic
        from models import microphone_calibration as _mc_mod

        self._sd = _sd
        self._mc_mod = _mc_mod

        # Re-parent this QObject to the view widget now that we have it.
        self.setParent(parent_widget)

        # Wire the hotplug signal now that the Qt object hierarchy is valid.
        self._devicesRefreshed.connect(self._on_devices_refreshed)

        # ── Audio engine ──────────────────────────────────────────────────
        self.mic = _Mic(
            parent_widget,
            rate=fft_params.sample_freq,
            chunksize=4096,
            device=audio_device,
            on_devices_changed=self._devicesRefreshed.emit,
            fft_size=fft_params.n_f,
        )
        self.mic.proc_thread.setParent(self)

        # ── FFT configuration ─────────────────────────────────────────────
        self.fft_data = fft_params
        x_axis = np.arange(0, fft_params.h_n_f + 1)
        self.freq = x_axis * fft_params.sample_freq / fft_params.n_f

        # ── Calibration ───────────────────────────────────────────────────
        self._calibration_corrections = calibration_corrections
        self._calibration_device_name = audio_device.name if audio_device else ""

        # ── Guitar/mode classification ────────────────────────────────────
        self._guitar_type = guitar_type

        # ── Plate/brace capture ───────────────────────────────────────────
        self.plate_capture = PlateCapture(
            sample_freq=fft_params.sample_freq,
            n_f=fft_params.n_f,
            parent=self,
        )
        self.plate_capture.stateChanged.connect(self.plateStatusChanged)
        self.plate_capture.analysisComplete.connect(self.plateAnalysisComplete)

        # ── Saved measurements (view-layer import deferred until here) ────
        from views.tap_analysis_results_view import load_all_measurements as _load
        self.saved_measurements = _load()
        self.savedMeasurements = self.saved_measurements

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

    @property
    def n_fmin(self) -> int:
        """Bin index corresponding to min_frequency.

        Computed from min_frequency, mirrors Swift's bin-index helpers
        derived from minFrequency inside findPeaks.
        Returns 0 when fft_data is not yet set (before start()).
        """
        if self.fft_data is None:
            return 0
        return int(self.fft_data.n_f * self.min_frequency) // self.fft_data.sample_freq

    @property
    def n_fmax(self) -> int:
        """Bin index corresponding to max_frequency.

        Computed from max_frequency, mirrors Swift's bin-index helpers
        derived from maxFrequency inside findPeaks.
        Returns 0 when fft_data is not yet set (before start()).
        """
        if self.fft_data is None:
            return 0
        return int(self.fft_data.n_f * self.max_frequency) // self.fft_data.sample_freq

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

    def recreate_proc_thread(self):
        """Destroy the current processing thread and create a fresh one.

        Applies the current calibration to the new thread.
        FftCanvas calls this when it needs to reset all processing state
        (e.g. after the analyzer was already running and the user presses Start
        again).

        Returns the new proc_thread (_FftProcessingThread) so FftCanvas can
        reconnect signals.

        Python-only — Swift achieves equivalent reset via AVAudioEngine stop/start.
        """
        from .realtime_fft_analyzer import _FftProcessingThread as _FPT
        self.mic.proc_thread = _FPT(mic=self.mic, parent=self)
        self.mic.proc_thread.set_calibration(self._calibration_corrections)
        return self.mic.proc_thread
