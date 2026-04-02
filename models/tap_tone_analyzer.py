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

This file (tap_tone_analyzer.py) contains:
  - The TapToneAnalyzer class declaration, stored properties, and __init__
    (mirrors the top of Swift TapToneAnalyzer.swift)
  - Re-exports of DecayTracker, TapDetector, PlateCapture for backward
    compatibility with existing import sites.
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

# ── PyQt6 ─────────────────────────────────────────────────────────────────────

from PyQt6 import QtCore


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
    QtCore.QObject,
):
    """Central analysis coordinator — owns all analysis state and business logic.

    Mirrors Swift's TapToneAnalyzer ObservableObject.  FftCanvas (the view)
    creates one of these, connects its signals to rendering slots, and delegates
    all analysis method calls to it.

    Emits Qt signals rather than Swift @Published properties so the view layer
    can respond to state changes without polling.
    """

    # ── Signals (Python equivalents of Swift @Published properties) ────────
    # New peak list emitted after every analysis frame and after threshold/range changes.
    peaksChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)          # ndarray (N, 3)
    # Full spectrum ready for the view to draw.
    spectrumUpdated: QtCore.pyqtSignal = QtCore.pyqtSignal(object, object)  # (freqs, mags_db)
    # A single tap has been fully captured (all required taps averaged).
    tapDetectedSignal: QtCore.pyqtSignal = QtCore.pyqtSignal()
    # Live tap count update: (captured, total).
    tapCountChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)
    # Ring-out time measured by DecayTracker (seconds).
    ringOutMeasured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    # Input level 0-100 scale (dBFS + 100).
    levelChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    # FFT frame diagnostics: (fps, sample_dt, processing_dt).
    framerateUpdate: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)
    # Averaging: number of completed averages.
    averagesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    # Emitted on every live FFT frame (for average-enable logic).
    newSample: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Display mode changed: emits the new DisplayMode enum value.
    displayModeChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)
    # Measurement complete state changed.
    measurementComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Hot-plug: list[str] of current input device names.
    devicesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(list)
    # Hot-plug: name of the device that disappeared.
    currentDeviceLost: QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    # Plate/brace phase status text for display.
    plateStatusChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    # Plate analysis complete: (fL, fC, fFLC) Hz.
    plateAnalysisComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)
    # Tap detection pause state changed.
    tapDetectionPaused: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Emitted when comparison overlay data changes (True=entering, False=leaving).
    comparisonChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Emitted when frequency range changes (fmin, fmax).
    freqRangeChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)
    # Peak info for status bar: (peak_hz, peak_db).
    peakInfoChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float)
    # Internal: fired from hotplug monitor thread → main thread (no-arg).
    _devicesRefreshed: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(
        self,
        parent_widget,
        fft_data,
        audio_device,
        calibration_corrections,
        guitar_type,
    ) -> None:
        """
        Args:
            parent_widget:         The FftCanvas (QObject parent).
            fft_data:              FftData instance (sample_freq, n_f, window_fcn, …).
            audio_device:          AudioDevice to open, or None for the system default.
            calibration_corrections: ndarray of per-bin dB corrections, or None.
            guitar_type:           GuitarType enum value for mode classification.
        """
        # Lazily import here to avoid a circular import: fft_canvas → models.tap_tone_analyzer
        # → fft_canvas.  These imports are only needed at runtime, not at module load.
        import sounddevice as _sd
        import numpy as _np
        from models.realtime_fft_analyzer import RealtimeFFTAnalyzer as _Mic
        from models import guitar_mode as _gm
        from models import measurement_type as _mt_mod
        from models import microphone_calibration as _mc_mod
        import app_settings as _as

        super().__init__(parent_widget)

        self._sd = _sd
        self._np = _np
        self._gm = _gm
        self._as = _as
        self._mc_mod = _mc_mod

        # ── Audio engine (mirrors Swift's analyzer: RealtimeFFTAnalyzer) ──
        self._devicesRefreshed.connect(self._on_devices_refreshed)
        self.mic: _Mic = _Mic(
            parent_widget,
            rate=fft_data.sample_freq,
            chunksize=4096,
            device=audio_device,
            on_devices_changed=self._devicesRefreshed.emit,
        )

        # ── FFT configuration ──────────────────────────────────────────────
        self.fft_data = fft_data
        import numpy as np
        x_axis = np.arange(0, fft_data.h_n_f + 1)
        self.freq = x_axis * fft_data.sample_freq // fft_data.n_f

        # ── Calibration ────────────────────────────────────────────────────
        self._calibration_corrections = calibration_corrections
        self._calibration_device_name: str = audio_device.name if audio_device else ""

        # ── Guitar/mode classification ─────────────────────────────────────
        self._guitar_type = guitar_type

        # ── Display mode (mirrors Swift AnalysisDisplayMode) ───────────────
        # Imported lazily from fft_canvas to avoid circular import at module load.
        # The DisplayMode enum lives in fft_canvas.py; we import it on first use.
        self._display_mode = None   # set to DisplayMode.LIVE by FftCanvas after import

        # ── Measurement state ──────────────────────────────────────────────
        self.is_measurement_complete: bool = False

        # ── Peak analysis state ────────────────────────────────────────────
        self.threshold: int = 60                          # 0-100 scale
        self.fmin: int = 0
        self.fmax: int = 1000
        self.n_fmin: int = 0
        self.n_fmax: int = 0
        self.saved_mag_y_db = np.array([])
        self.saved_peaks = np.zeros((0, 3))               # (freq, mag, Q)
        self.b_peaks_freq = np.array([])
        self.peaks_f_min_index: int = 0
        self.peaks_f_max_index: int = 0
        self._loaded_measurement_peaks = None             # ndarray or None
        self.selected_peak: float = 0.0
        self._mode_color_map: dict = {}                   # freq → RGB tuple

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
            sample_freq=fft_data.sample_freq,
            n_f=fft_data.n_f,
            parent=self,
        )
        self.plate_capture.stateChanged.connect(self.plateStatusChanged)
        self.plate_capture.analysisComplete.connect(self.plateAnalysisComplete)
        self._current_mag_y = np.array([])

        # ── Comparison overlay data ───────────────────────────────────────
        self.comparison_labels: list = []        # list of (label, color) tuples
        # _comparison_data is for the analyzer's knowledge of what's being compared;
        # actual PlotDataItem curves live in FftCanvas.
        self._comparison_data: list = []

        # ── Processing thread (created/managed by FftCanvas) ─────────────
        # FftCanvas sets self._proc_thread after constructing TapToneAnalyzer.
        self._proc_thread = None

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
        """True when in COMPARISON display mode."""
        from fft_canvas import DisplayMode
        return self._display_mode == DisplayMode.COMPARISON
