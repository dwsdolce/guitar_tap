"""
Tap-tone analysis coordinator — mirrors Swift TapToneAnalyzer.swift.

The Swift TapToneAnalyzer class is split across nine Swift extension files.
This Python package mirrors that structure using separate modules:

  tap_tone_analyzer_decay_tracking.py      → TapToneAnalyzerDecayTrackingMixin
      mirrors Swift TapToneAnalyzer+DecayTracking.swift

  tap_tone_analyzer_tap_detection.py       → TapToneAnalyzerTapDetectionHandlerMixin
      mirrors Swift TapToneAnalyzer+TapDetection.swift

  tap_tone_analyzer_spectrum_capture.py    → TapToneAnalyzerSpectrumCaptureMixin
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
  - Re-export of AnalysisDisplayMode for import convenience.
"""

from __future__ import annotations

# ── TapToneAnalyzer mixin imports ─────────────────────────────────────────────

from .tap_tone_analyzer_control import TapToneAnalyzerControlMixin
from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
from .tap_tone_analyzer_analysis_helpers import TapToneAnalyzerAnalysisHelpersMixin
from .tap_tone_analyzer_tap_detection import TapToneAnalyzerTapDetectionHandlerMixin
from .tap_tone_analyzer_decay_tracking import TapToneAnalyzerDecayTrackingMixin
from .tap_tone_analyzer_annotation_management import TapToneAnalyzerAnnotationManagementMixin
from .tap_tone_analyzer_measurement_management import TapToneAnalyzerMeasurementManagementMixin
from .tap_tone_analyzer_mode_override_management import TapToneAnalyzerModeOverrideManagementMixin
from .tap_tone_analyzer_spectrum_capture import TapToneAnalyzerSpectrumCaptureMixin

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

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode


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
    TapToneAnalyzerSpectrumCaptureMixin,
    QtCore.QObject,
):
    """Central analysis coordinator — owns all analysis state and business logic.

    Mirrors Swift's `final class TapToneAnalyzer: ObservableObject`.
    All reactive UI updates use Qt signals; properties are plain instance
    attributes initialised in __init__.
    """

    # MARK: - Signals (Qt — view layer bridge, no Swift equivalent) ──────────
    # ── Signals (Python equivalents of Swift @Published properties) ────────
    # New peak list emitted after every analysis frame and after threshold/range changes.
    peaksChanged: QtCore.Signal = QtCore.Signal(object)          # list[ResonantPeak]
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
    # Human-readable status string for the status bar (mirrors Swift @Published var statusMessage).
    statusMessageChanged: QtCore.Signal = QtCore.Signal(str)
    # Emitted when loadedMeasurementName changes (mirrors Swift @Published var loadedMeasurementName).
    # Payload: str | None — the new name, or None when cleared.
    loadedMeasurementNameChanged: QtCore.Signal = QtCore.Signal(object)
    # Emitted when showLoadedSettingsWarning changes (mirrors Swift @Published var showLoadedSettingsWarning).
    # Payload: bool — True to show warning, False to hide.
    showLoadedSettingsWarningChanged: QtCore.Signal = QtCore.Signal(bool)
    # Emitted when microphoneWarning changes (mirrors Swift @Published var microphoneWarning).
    # Payload: str | None — warning text, or None when cleared.
    microphoneWarningChanged: QtCore.Signal = QtCore.Signal(object)
    # Emitted when load_measurement() finds the recorded device is currently connected
    # and wants the view to switch to it.  Payload: AudioDevice.
    # Mirrors Swift fftAnalyzer.setInputDevice(match) called inside loadMeasurement().
    requestDeviceSwitch: QtCore.Signal = QtCore.Signal(object)
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

        # Qt's metaclass does not participate in Python's cooperative super()
        # chain, so the QObject base must be initialised explicitly.
        QtCore.QObject.__init__(self, None)

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
        # Name of the currently active calibration profile (device-specific or
        # manually selected).  Mirrors Swift RealtimeFFTAnalyzer.activeCalibration?.name.
        self._active_calibration_name: "str | None" = None

        # ── Guitar/mode classification ─────────────────────────────────────
        self._guitar_type = None

        # ── Display mode (mirrors Swift AnalysisDisplayMode) ───────────────
        self._display_mode: AnalysisDisplayMode = AnalysisDisplayMode.LIVE

        # ── Stored properties — mirrors Swift TapToneAnalyzer @Published vars ──
        # Previously declared as Published(...) class-level descriptors.
        # Plain instance attributes are equivalent: all reactive UI updates
        # go through Qt signals, not through the swiftui_compat notify chain.

        # MARK: - Configuration (mirrors Swift @Published vars)
        self.min_frequency: float = float(_tds.analysis_min_frequency())   # mirrors minFrequency
        self.max_frequency: float = float(_tds.analysis_max_frequency())   # mirrors maxFrequency
        self.max_peaks: int = _tds.max_peaks()                             # mirrors maxPeaks
        self.peak_threshold: float = float(_tds.peak_threshold())          # mirrors peakThreshold
        self.tap_detection_threshold: float = float(_tds.tap_detection_threshold())  # mirrors tapDetectionThreshold
        self.hysteresis_margin: float = float(_tds.hysteresis_margin())    # mirrors hysteresisMargin
        self.decay_threshold: float = 15.0                                 # mirrors decayThreshold
        self.number_of_taps: int = 1                                       # mirrors numberOfTaps
        self.capture_window: float = 0.2                                   # mirrors captureWindow

        # MARK: - Results
        self.current_peaks: list = []                                      # mirrors currentPeaks
        self.identified_modes: list = []                                   # mirrors identifiedModes
        self.current_decay_time: "float | None" = None                    # mirrors currentDecayTime
        self.saved_measurements: list = []                                 # mirrors savedMeasurements
        self.savedMeasurements = self.saved_measurements                   # legacy alias

        # MARK: - Detection State
        self.average_magnitude: float = -100.0      # mirrors averageMagnitude
        self.tap_detection_level: float = -100.0    # mirrors tapDetectionLevel
        self.tap_detected: bool = False             # mirrors tapDetected
        self.is_detecting: bool = False             # mirrors isDetecting
        self.is_detection_paused: bool = False      # mirrors isDetectionPaused
        self.is_ready_for_detection: bool = True    # mirrors isReadyForDetection
        self.current_tap_count: int = 0             # mirrors currentTapCount
        self.tap_progress: float = 0.0              # mirrors tapProgress
        # All writes must go through _set_status_message() to emit statusMessageChanged.
        # Mirrors Swift @Published var statusMessage: String.
        self.status_message: str = "Tap the guitar to begin"

        # MARK: - Frozen Spectrum
        self.frozen_frequencies = np.array([])      # mirrors frozenFrequencies
        self.frozen_magnitudes = np.array([])       # mirrors frozenMagnitudes

        # MARK: - Annotation & Selection State
        self.peak_annotation_offsets: dict = {}     # mirrors peakAnnotationOffsets
        self.peak_mode_overrides: dict = {}         # mirrors peakModeOverrides
        self.selected_peak_ids: set = set()         # mirrors selectedPeakIDs
        self.highlighted_peak_id = None             # mirrors highlightedPeakID
        self.annotation_visibility_mode = AnnotationVisibilityMode.from_string(
            _tds.annotation_visibility_mode()
        )                                           # mirrors annotationVisibilityMode

        # MARK: - Measurement Complete State
        self.is_measurement_complete: bool = False  # mirrors isMeasurementComplete

        # Mirrors Swift @Published var showLoadedSettingsWarning: Bool
        # Set True by load_measurement(); cleared when the user changes threshold
        # or tap count away from the loaded values, or on a successful new tap, or reset.
        self.show_loaded_settings_warning: bool = False
        # Sentinel values stored at load time — used to detect user-initiated changes.
        # Mirror Swift loadedTapDetectionThreshold and loadedNumberOfTaps.
        self.loaded_tap_detection_threshold: "float | None" = None
        self.loaded_number_of_taps: "int | None" = None

        # Mirrors Swift @Published var microphoneWarning: String?
        # Set by import_measurements_from_data when an imported measurement's device
        # is not among the currently available input devices.  View clears it after
        # showing the alert (mirrors MeasurementsListView.swift behaviour).
        self.microphone_warning: "str | None" = None

        # ── Loaded-measurement metadata ────────────────────────────────────
        # Mirrors Swift @Published var loadedMeasurementName: String? and
        # @Published var sourceMeasurementTimestamp: Date?
        # Set by load_measurement(); cleared by start_tap_sequence() / reset.
        self.loaded_measurement_name: "str | None" = None
        self.source_measurement_timestamp: "str | None" = None  # ISO-8601 string

        # ── Additional peak analysis state ────────────────────────────────
        self.loaded_measurement_peaks: "list[ResonantPeak] | None" = None
        self.selected_peak: float = 0.0
        # Whether the user has manually changed peak selection since last auto-run.
        # Mirrors Swift TapToneAnalyzer.userHasModifiedPeakSelection.
        self.user_has_modified_peak_selection: bool = False
        # Suppresses recalculate_frozen_peaks_if_needed() during loadMeasurement.
        # Mirrors Swift TapToneAnalyzer.isLoadingMeasurement.
        self.is_loading_measurement: bool = False
        # Frequencies of currently selected peaks — stable carry-forward for
        # recalculate_frozen_peaks_if_needed(). Mirrors Swift selectedPeakFrequencies.
        self.selected_peak_frequencies: list = []

        # ── Averaging ──────────────────────────────────────────────────────
        self.avg_enable: bool = False
        self.max_average_count: int = 1
        self.mag_y_sum = []
        self.num_averages: int = 0

        # ── Multi-tap accumulator ─────────────────────────────────────────
        # Consolidates Swift's two separate lists into one, cleared between phases:
        #   capturedTaps         — guitar mode (raw mag_y_db arrays)
        #   materialCapturedTaps — plate/brace phases (magnitudes, frequencies, captureTime) tuples
        # Python clears this list at the start of each phase / tap sequence,
        # so the same list safely serves both roles.
        self.captured_taps: list = []

        # ── Auto-scale ────────────────────────────────────────────────────
        self._auto_scale_db: bool = False

        # ── Measurement type ──────────────────────────────────────────────
        self._measurement_type = _mt_mod.MeasurementType.CLASSICAL

        self._current_mag_y = np.array([])
        self._current_mag_y_db = np.array([])
        # Instantaneous RMS level in dBFS — mirrors Swift fftAnalyzer.inputLevelDB.
        # Updated every ~23 ms by _on_rms_level_changed; used by _do_reenable_detection
        # so it reads the current level (not the 0.5 s peak-hold) exactly as Swift does.
        self._current_input_level_db: float = -100.0
        # Instantaneous FFT peak magnitude in dBFS — mirrors Swift fftAnalyzer.peakMagnitude.
        # Updated every ~370 ms (at FFT rate) by on_fft_frame; used by guitar-mode _reenable()
        # which mirrors Swift handleTapDetection's re-enable closure using fftAnalyzer.peakMagnitude.
        # Distinct from _current_input_level_db (inputLevelDB/RMS) and from tap_peak_level
        # (recentPeakLevelDB, captured at tap-fire time).
        self._current_peak_magnitude_db: float = -100.0

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

        # ── Gated FFT capture state ────────────────────────────────────────
        # Mirrors Swift TapToneAnalyzer stored properties for gated capture:
        #   preRollBuffer: [Float]     — ring buffer of recent raw PCM
        #   preRollSamples: Int        — capacity of the pre-roll buffer
        #   gatedAccumBuffer: [Float]  — accumulator for the capture window
        #   gatedCaptureActive: Bool   — whether a capture is in progress
        #   gatedCaptureSamples: Int   — target window size in samples
        #   gatedCapturePhase: ...     — phase at capture start
        #
        # Previously lived on _FftProcessingThread; moved here so that
        # _accumulate_gated_samples (called via mic.raw_sample_handler) owns
        # this state directly — matching Swift where
        # TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:) owns the buffers.
        import threading as _threading
        self._pre_roll_seconds: float = 0.2         # 200 ms pre-roll (mirrors Swift)
        self._pre_roll_samples: int = 0             # set in start() once sample rate is known
        self._pre_roll_buf: list = []               # raw PCM samples (float32)
        self._gated_lock = _threading.Lock()
        self._gated_capture_active: bool = False
        self._gated_capture_samples: int = 0        # target window size in samples
        self._gated_capture_phase: object = None    # MaterialTapPhase at capture start
        self._gated_accum: list = []                # accumulated raw PCM samples
        # Placeholder; overridden in start() to float(self.mic.rate).
        # Swift uses 48000 as its placeholder (mpmSampleRate); Python uses 44100.0.
        # Both values are replaced by the actual hardware rate before first use.
        self._gated_sample_rate: float = 44100.0

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
            chunksize=1024,
            device=audio_device,
            on_devices_changed=self._devicesRefreshed.emit,
            on_calibration_changed=self._on_mic_calibration_changed,
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

        # ── Gated-FFT capture state — initialise rate-dependent fields ───────
        # _pre_roll_samples and _gated_sample_rate depend on the actual hardware
        # sample rate, which is only known after the mic is constructed.
        self._gated_sample_rate = float(self.mic.rate)
        self._pre_roll_samples = int(self.mic.rate * self._pre_roll_seconds)

        # ── Gated-FFT capture signal ───────────────────────────────────────
        # Wire the processing thread's gatedCaptureComplete signal to the
        # finishGatedFFTCapture handler (from TapToneAnalyzerSpectrumCaptureMixin).
        # Mirrors Swift's Combine sink on fftAnalyzer.gatedCaptureComplete.
        self.mic.proc_thread.gatedCaptureComplete.connect(self.finish_gated_fft_capture)

        # ── Raw-sample handler ────────────────────────────────────────────
        # Set mic.raw_sample_handler so _FftProcessingThread.run() calls
        # _accumulate_gated_samples on every audio chunk.
        # Mirrors Swift TapToneAnalyzer.start() registering rawSampleHandler.
        self.mic.raw_sample_handler = self._accumulate_gated_samples

        # ── Saved measurements (view-layer import deferred until here) ────
        from views.tap_analysis_results_view import load_all_measurements as _load
        self.saved_measurements = _load()
        self.savedMeasurements = self.saved_measurements

        # ── Wire FFT frames directly to the analyzer ──────────────────────
        # Connect proc_thread.fftFrameReady → self.on_fft_frame here so the
        # analyzer owns its own audio-frame wiring (mirrors Swift's direct
        # RealtimeFFTAnalyzer.$magnitudes → TapToneAnalyzer subscription).
        # FftCanvas._connect_proc_thread_signals() handles only rmsLevelChanged
        # and finished — not fftFrameReady.
        self.mic.proc_thread.fftFrameReady.connect(self.on_fft_frame)

        # ── Wire per-chunk RMS level for plate/brace tap detection ────────
        # Connect proc_thread.rmsLevelChanged → self._on_rms_level_changed so
        # plate/brace tap detection fires at ~43 Hz (every 1024 samples) rather
        # than at the FFT-frame rate (~2.7 Hz).  Mirrors Swift's Combine sink on
        # fftAnalyzer.$inputLevelDB used for plate/brace detectTap calls.
        self.mic.proc_thread.rmsLevelChanged.connect(self._on_rms_level_changed)

        # ── Auto-start tap sequence on first launch ────────────────────────
        # Mirrors Swift start() auto-start guard:
        #   if !isDetecting && !isMeasurementComplete && !isDetectionPaused
        #      && currentTapCount == 0 { startTapSequence() }
        # Safe to call synchronously here because fftFrameReady is now
        # connected above before this line executes.
        if (not self.is_detecting and not self.is_measurement_complete
                and not self.is_detection_paused and self.current_tap_count == 0):
            self.start_tap_sequence()

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
        # Reconnect the analyzer-owned signals on the new thread.
        self.mic.proc_thread.fftFrameReady.connect(self.on_fft_frame)
        self.mic.proc_thread.gatedCaptureComplete.connect(self.finish_gated_fft_capture)
        return self.mic.proc_thread

    # ------------------------------------------------------------------ #
    # Guitar Type & Mode Override
    # Mirrors Swift TapToneAnalyzer.swift (not in any extension file):
    #   setGuitarType / effectiveModeLabel / setModeOverride / hasManualOverride
    # ------------------------------------------------------------------ #

    def set_guitar_type(self, guitar_type) -> None:
        """Update the guitar type used for mode classification.

        Mirrors Swift setting ``guitarType`` on ``TapToneAnalyzer``.
        Accepts either a GuitarType enum value or its raw string (e.g. "Classical").
        Always stores a GuitarType enum so reclassify_peaks() can call
        guitar_type.mode_ranges without a type check.
        """
        from .guitar_type import GuitarType
        if isinstance(guitar_type, str):
            try:
                guitar_type = GuitarType(guitar_type)
            except (ValueError, KeyError):
                guitar_type = GuitarType.CLASSICAL
        self._guitar_type = guitar_type

    def effective_mode_label(self, peak) -> str:
        """Return the display label for a peak, respecting any user override.

        If ``peak_mode_overrides`` contains an entry for ``peak.id``, that
        string is returned. Otherwise the auto-classification from
        ``GuitarMode.classify_peak`` is used.

        Mirrors Swift ``effectiveModeLabel(for peak: ResonantPeak) -> String``.
        """
        override = self.peak_mode_overrides.get(peak.id)
        if override:
            return override
        from .guitar_mode import classify_peak
        from models.tap_display_settings import TapDisplaySettings as _tds_eml
        return classify_peak(peak.frequency, _tds_eml.guitar_type())

    def set_mode_override(self, mode: "str | None", peak_id: str) -> None:
        """Set or clear a mode-label override for a specific peak.

        Passing ``None`` or the string ``"auto"`` clears any existing override.
        Any other string is stored as a manual label.

        Mirrors Swift ``setModeOverride(_ override: UserAssignedMode, for peakID: UUID)``.
        """
        if mode is None or mode == "auto":
            self.peak_mode_overrides.pop(peak_id, None)
        else:
            self.peak_mode_overrides[peak_id] = mode

    def has_manual_override(self, peak_id: str) -> bool:
        """Return ``True`` when the peak has a manually-assigned (non-auto) mode label.

        Mirrors Swift ``hasManualOverride(for peakID: UUID) -> Bool``.
        """
        return peak_id in self.peak_mode_overrides

    # ------------------------------------------------------------------ #
    # Guitar Peak Selection
    # Mirrors Swift TapToneAnalyzer.swift (not in any extension file):
    #   togglePeakSelection / selectAllPeaks / selectNoPeaks /
    #   cycleAnnotationVisibility / visiblePeaks
    # ------------------------------------------------------------------ #

    def toggle_peak_selection(self, peak_id: str) -> None:
        """Toggle the selection state of a single guitar peak.

        Mirrors Swift ``togglePeakSelection(_ peakID: UUID)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        current = set(self.selected_peak_ids)
        if peak_id in current:
            current.discard(peak_id)
        else:
            current.add(peak_id)
        self.selected_peak_ids = current
        self.user_has_modified_peak_selection = True

    def select_all_peaks(self) -> None:
        """Mark all current peaks as selected.

        Mirrors Swift ``selectAllPeaks()``.
        """
        self.selected_peak_ids = {p.id for p in self.current_peaks}
        self.user_has_modified_peak_selection = True

    def select_no_peaks(self) -> None:
        """Clear all peak selections.

        Mirrors Swift ``selectNoPeaks()``.
        """
        self.selected_peak_ids = set()
        self.user_has_modified_peak_selection = True

    def set_frozen_spectrum(self, frequencies, magnitudes) -> None:
        """Set frozen spectrum arrays atomically.

        Mirrors Swift ``setFrozenSpectrum(frequencies:magnitudes:)`` — assigns both
        arrays before any connected slot can observe them, preventing callers from
        reading a half-updated state where the two arrays have mismatched lengths.

        Python's GIL guarantees no other thread runs between the two assignments,
        which is sufficient since all view reads occur on the main thread.
        """
        self.frozen_frequencies = frequencies
        self.frozen_magnitudes = magnitudes

    def cycle_annotation_visibility(self) -> None:
        """Advance annotation_visibility_mode: all → selected → none → all.

        Persists the new value via TapDisplaySettings.
        Mirrors Swift ``cycleAnnotationVisibility()``.
        """
        self.annotation_visibility_mode = self.annotation_visibility_mode.next
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_annotation_visibility_mode(self.annotation_visibility_mode)
        # mirrors cycleAnnotationVisibility() → TapDisplaySettings.annotationVisibilityMode in Swift

    @property
    def visible_peaks(self) -> list:
        """Subset of current_peaks to render given annotation_visibility_mode.

        In guitar mode, peaks classified as Unknown are excluded when
        ``TapDisplaySettings.show_unknown_modes`` is False, keeping the chart
        consistent with the Analysis Results panel.

        Mirrors Swift ``visiblePeaks: [ResonantPeak]``.
        """
        from .annotation_visibility_mode import AnnotationVisibilityMode
        mode = self.annotation_visibility_mode
        if mode == AnnotationVisibilityMode.ALL:
            candidates = list(self.current_peaks)
        elif mode == AnnotationVisibilityMode.SELECTED:
            candidates = [p for p in self.current_peaks if p.id in self.selected_peak_ids]
        else:
            # NONE
            return []

        # Filter unknown-mode peaks in guitar mode when the setting is off
        from .tap_display_settings import TapDisplaySettings
        from .guitar_mode import GuitarMode
        measurement_type = TapDisplaySettings.measurement_type()
        if measurement_type.is_guitar and not TapDisplaySettings.show_unknown_modes():
            guitar_type = TapDisplaySettings.guitar_type()
            candidates = [p for p in candidates if GuitarMode.is_known(p.frequency, guitar_type)]
        return candidates
