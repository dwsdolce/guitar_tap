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

This file (tap_tone_analyzer.py) contains:
  - The TapToneAnalyzer class declaration, stored properties, and __init__
    (mirrors the top of Swift TapToneAnalyzer.swift)
  - Re-export of AnalysisDisplayMode for import convenience.
"""

from __future__ import annotations

# ── PySide6 ─────────────────────────────────────────────────────────────────────
from PySide6 import QtCore

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode

# ── AnalysisDisplayMode ───────────────────────────────────────────────────────
# Mirrors Swift AnalysisDisplayMode enum defined in TapToneAnalyzer.swift.
# Lives in analysis_display_mode.py so the mixin files can import it without
# creating a circular dependency (they are imported by this file).
from .analysis_display_mode import AnalysisDisplayMode
from .tap_tone_analyzer_analysis_helpers import TapToneAnalyzerAnalysisHelpersMixin
from .tap_tone_analyzer_annotation_management import TapToneAnalyzerAnnotationManagementMixin

# ── TapToneAnalyzer mixin imports ─────────────────────────────────────────────
from .tap_tone_analyzer_control import TapToneAnalyzerControlMixin
from .tap_tone_analyzer_decay_tracking import TapToneAnalyzerDecayTrackingMixin
from .tap_tone_analyzer_measurement_management import TapToneAnalyzerMeasurementManagementMixin
from .tap_tone_analyzer_mode_override_management import TapToneAnalyzerModeOverrideManagementMixin
from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
from .tap_tone_analyzer_spectrum_capture import TapToneAnalyzerSpectrumCaptureMixin
from .tap_tone_analyzer_tap_detection import TapToneAnalyzerTapDetectionHandlerMixin
from guitar_tap.utilities.logging import gt_log

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
    # Emitted when a loaded measurement or comparison supplies all four axis bounds atomically.
    # Payload: (min_freq: int, max_freq: int, min_db: float, max_db: float).
    # Mirrors Swift TapToneAnalyzer.setLoadedAxisRange(minFreq:maxFreq:minDB:maxDB:) which
    # publishes loadedAxisRange so TapToneAnalysisView can apply all four bounds in one pass.
    loadedAxisRangeChanged: QtCore.Signal = QtCore.Signal(int, int, float, float)
    # Peak info for status bar: (peak_hz, peak_db).
    peakInfoChanged: QtCore.Signal = QtCore.Signal(float, float)
    # Human-readable status string for the status bar (mirrors Swift @Published var statusMessage).
    statusMessageChanged: QtCore.Signal = QtCore.Signal(str)
    # Emitted when loadedMeasurementName changes (mirrors Swift @Published var loadedMeasurementName).
    # Payload: str | None — the new name, or None when cleared.
    loadedMeasurementNameChanged: QtCore.Signal = QtCore.Signal(object)
    # Emitted when mic.playing_file_name changes (mirrors Swift @Published var playingFileName
    # on RealtimeFFTAnalyzer).  Payload: str | None — filename without extension, or None.
    # Emitted by the view after calling mic.start_from_file / on playback end, mirroring
    # Swift where @Published drives chartTitle reactively without any explicit emit.
    playingFileNameChanged: QtCore.Signal = QtCore.Signal(object)
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
    # Internal: cross-thread DispatchQueue.main.asyncAfter equivalent.
    # Emitted from any thread; Qt QueuedConnection delivers the slot on the
    # main thread.  Payload: (delay_ms: int, callable: object).
    # Mirrors Swift DispatchQueue.main.asyncAfter(deadline:execute:).
    _mainAsyncAfterRequest: QtCore.Signal = QtCore.Signal(int, object)

    def __init__(self, fft_analyzer=None) -> None:
        """Create a TapToneAnalyzer with all state at sensible defaults.

        Mirrors Swift ``TapToneAnalyzer(fftAnalyzer: RealtimeFFTAnalyzer)``.

        When ``fft_analyzer`` is provided, pipeline signals are wired
        immediately (matching Swift's ``setupSubscriptions()`` called from
        ``init``).  Audio-hardware lifecycle (start/stop) is still managed
        by ``start()``, which the view layer calls after construction.

        Args:
            fft_analyzer: Optional RealtimeFFTAnalyzer.  None-safe — bare
                          instances (no mic) can be constructed for direct
                          analysis method testing.
        """
        import numpy as np
        from models import guitar_mode as _gm
        from models import measurement_type as _mt_mod
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from models.tap_display_settings import TapDisplaySettings as _tds

        # Qt's metaclass does not participate in Python's cooperative super()
        # chain, so the QObject base must be initialised explicitly.
        QtCore.QObject.__init__(self, None)

        # Wire the cross-thread asyncAfter signal.  AutoConnection means:
        #   - Same thread (test path): DirectConnection → slot fires inline
        #   - Different thread (FilePlayback worker): QueuedConnection → slot
        #     fires on the main thread when the event loop pumps.
        # The slot calls QTimer.singleShot to apply the delay, which is safe
        # because it always runs on the main thread (either already there, or
        # delivered there by QueuedConnection).
        self._mainAsyncAfterRequest.connect(
            self._on_main_async_after_request,
        )

        self._np = np
        self._gm = _gm
        self._tds = _tds

        # Pitch calculator — mirrors Swift `let pitchCalculator = Pitch(a4: 440.0)`
        from models.pitch import Pitch as _Pitch
        self.pitch_calculator = _Pitch(a4=440.0)

        # ── fft_analyzer reference (mirrors Swift's fftAnalyzer property) ──
        # Both production and test paths provide a mic at construction time,
        # matching Swift where init(fftAnalyzer:) always receives one.
        self.mic = fft_analyzer  # type: ignore[assignment]

        # ── FFT configuration ──────────────────────────────────────────────
        if self.mic is not None:
            x_axis = np.arange(0, self.mic.h_fft_size + 1)
            self.freq = x_axis * self.mic.rate / self.mic.fft_size
        else:
            self.freq = np.array([])

        # ── Calibration ────────────────────────────────────────────────────
        self._calibration_corrections = None
        self._calibration_profile: object | None = None  # raw MicrophoneCalibration
        self._calibration_device_name: str = ""
        # Name of the currently active calibration profile (device-specific or
        # manually selected).  Mirrors Swift RealtimeFFTAnalyzer.activeCalibration?.name.
        self._active_calibration_name: "str | None" = None

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
        self.peak_min_threshold: float = float(_tds.peak_min_threshold())    # mirrors peakMinThreshold
        self.tap_detection_threshold: float = float(_tds.tap_detection_threshold())  # mirrors tapDetectionThreshold
        self.hysteresis_margin: float = float(_tds.hysteresis_margin())    # mirrors hysteresisMargin
        self.decay_threshold: float = 15.0                                 # mirrors decayThreshold
        self.number_of_taps: int = 1                                       # mirrors numberOfTaps
        self.capture_window: float = 0.2                                   # mirrors captureWindow
        self.capture_timer_active: bool = False                            # mirrors captureTimer != nil

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
        self._is_detecting: bool = False             # mirrors isDetecting
        self.is_detection_paused: bool = False      # mirrors isDetectionPaused
        self.is_ready_for_detection: bool = True    # mirrors isReadyForDetection
        self.current_tap_count: int = 0             # mirrors currentTapCount
        self.tap_progress: float = 0.0              # mirrors tapProgress
        # All writes must go through _set_status_message() to emit statusMessageChanged.
        # Mirrors Swift @Published var statusMessage: String.
        self.status_message: str = "Tap the guitar to begin"

        # MARK: - Input Clipping Detection
        # When the mic input clips (samples reach |1.0| or RMS reaches 0 dBFS),
        # we override the visible status message with a remediation warning.
        # _latest_real_status preserves the analyzer-set message so it can be
        # restored when clipping clears.  Mirrors Swift @Published var
        # isClipping: Bool / latestRealStatus: String.
        self.is_clipping: bool = False
        self._latest_real_status: str = self.status_message

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
        self.comparison_snapshots: list = []   # parallel to _comparison_data — mirrors Swift comparisonSnapshots

        # ── Multi-Tap Comparison State ────────────────────────────────────
        # Per-tap spectra and peaks from the most recent multi-tap guitar sequence.
        # Empty list for single-tap sequences, plate, and brace measurements.
        # Populated by process_multiple_taps(); cleared by reset paths in the control mixin.
        # Mirrors Swift TapToneAnalyzer.tapEntries ([TapEntry]).
        self.tap_entries: list = []

        # When True and is_measurement_complete, the Results panel shows the per-tap
        # comparison view instead of the averaged-only view.
        # Reset to False when a new sequence starts.
        # Mirrors Swift TapToneAnalyzer.showingMultiTapComparison (Bool).
        self.showing_multi_tap_comparison: bool = False

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
        self._pre_roll_seconds: float = 0.2         # 200 ms pre-roll (mirrors Swift preRollDuration)
        self._pre_roll_buf: list = []               # raw PCM samples (float32)
        self._gated_lock = _threading.Lock()
        self._gated_capture_active: bool = False
        self._gated_capture_samples: int = 0        # target window size in samples (snapshot at capture-open)
        self._gated_capture_phase: object = None    # MaterialTapPhase at capture start
        self._gated_accum: list = []                # accumulated raw PCM samples
        self._mpm_sample_rate: float = 48000.0      # mirrors Swift mpmSampleRate (updated per audio buffer)

        # Monotonic capture identity — incremented at every start_*_gated_capture
        # call.  Each pending safety-timeout closure captures the ID at scheduling
        # time and only flushes the accumulator if `_gated_capture_id` still
        # matches.  Without this, a stale timeout from a previous capture can
        # fire while the next capture is mid-fill, dispatch its partial buffer
        # as if it were the new capture's complete result, and silently truncate
        # the capture window from fft_size samples to whatever fragment was
        # collected.  Mirrors Swift `gatedCaptureID`.
        self._gated_capture_id: int = 0
        # The _gated_capture_id set by the most recent audio-queue
        # level-crossing fast-start.  start_gated_capture() and
        # start_guitar_gated_capture() check this: if it matches
        # _gated_capture_id, the fast-start handled this tap (whether
        # still running or already completed) — skip re-seeding.
        self._last_level_crossing_capture_id: int = -1

        # Pre-roll snapshot captured by the level-crossing handler on the
        # audio thread when it fires during file playback but a previous
        # capture's completion is still pending on the main thread.  In this
        # "deferred" case the handler does NOT start _gated_capture_active
        # (which would cascade), but snapshots the pre-roll so the main-
        # thread start_gated_capture can seed from the correct audio position.
        # Cleared by start_gated_capture after consumption.
        # Mirrors Swift pendingLevelCrossingPreRoll.
        self._pending_level_crossing_pre_roll: list | None = None

        # ── Pipeline signal wiring ────────────────────────────────────────
        # Wire all signal/callback connections when the FFT analyzer is
        # provided.  Mirrors Swift init calling setupSubscriptions().
        if self.mic is not None:
            self._wire_pipeline_signals()

    # ------------------------------------------------------------------ #
    # _main_async_after — mirrors Swift DispatchQueue.main.asyncAfter
    # ------------------------------------------------------------------ #

    def _main_async_after(self, delay_ms: int, callback) -> None:
        """Schedule *callback* to run on the main thread after *delay_ms*.

        Thread-safe — can be called from any thread (audio processing,
        FilePlayback worker, main thread).  The implementation emits a Qt
        signal with QueuedConnection, so the slot always executes on the
        main thread.  The slot then calls ``QTimer.singleShot`` (which is
        safe because it now runs on the main thread) to apply the delay.

        This is the Python/Qt equivalent of Swift's
        ``DispatchQueue.main.asyncAfter(deadline: .now() + delay)``.

        Using one unconditional mechanism for all audio sources (live mic,
        UI file playback, test file playback) eliminates the divergent code
        paths that previously existed between live and test modes.

        Args:
            delay_ms: Delay in milliseconds before the callback fires.
            callback: Zero-argument callable to invoke on the main thread.
        """
        self._mainAsyncAfterRequest.emit(delay_ms, callback)

    @QtCore.Slot(int, object)
    def _on_main_async_after_request(self, delay_ms: int, callback) -> None:
        """Main-thread slot: apply the delay via QTimer.singleShot.

        Always runs on the main thread (QueuedConnection).  Mirrors the
        main-thread dispatch that Swift's asyncAfter performs implicitly.
        """
        QtCore.QTimer.singleShot(delay_ms, callback)

    # ------------------------------------------------------------------ #
    # for_testing — mirrors Swift TapToneAnalyzer.forTesting()
    # ------------------------------------------------------------------ #

    @classmethod
    def for_testing(cls, sample_rate: int = 48000) -> "TapToneAnalyzer":
        """Create a TapToneAnalyzer wired for file-playback testing.

        The returned instance has the full pipeline connected (signal wiring,
        raw-sample handler, level-crossing handler) but no audio hardware.
        Use ``play_file_for_testing(path, measurement_type, number_of_taps)``
        to feed a WAV file through the pipeline.

        The FFT size is a constant inside ``RealtimeFFTAnalyzer`` (65 536);
        it is not configurable per-instance.

        Mirrors Swift ``TapToneAnalyzer.forTesting()``.

        Args:
            sample_rate: Sample rate in Hz. Default 48000.
        """
        from models.realtime_fft_analyzer import RealtimeFFTAnalyzer as _Mic

        # 1. Create the hardware-free FFT engine.
        mic = _Mic.for_testing(sample_rate=sample_rate)

        # 2. Construct the analyzer — __init__ sets all state defaults,
        #    computes the frequency axis, and wires pipeline signals.
        return cls(fft_analyzer=mic)

    # ------------------------------------------------------------------ #
    # play_file_for_testing — mirrors Swift playFileForTesting(url:…)
    # ------------------------------------------------------------------ #

    def play_file_for_testing(
        self,
        path: str,
        measurement_type: "MeasurementType",
        number_of_taps: int = 1,
        calibration_path: str | None = None,
    ) -> None:
        """Feed a WAV file through the full analysis pipeline for testing.

        This is the test-only equivalent of the view-layer ``_open_audio_file``.
        It configures the measurement type, starts a tap sequence with warmup
        skipped, and processes all audio through ``process_file_data`` inline.

        A QCoreApplication is created if one does not already exist, and the
        Qt event loop is pumped between audio chunks so that
        ``_main_async_after`` callbacks (cooldown re-enables, finish
        processing, safety timeouts) fire during playback — exactly as
        Swift's ``playFileForTesting`` pumps ``RunLoop.main.run(until:)``
        to drain ``DispatchQueue.main.asyncAfter`` callbacks.  This means
        the test exercises the *exact same* code paths as the live app.

        Mirrors Swift ``TapToneAnalyzer.playFileForTesting(url:measurementType:numberOfTaps:calibrationURL:)``.

        Args:
            path:              Filesystem path to the audio file.
            measurement_type:  The MeasurementType to configure before playback.
            number_of_taps:    Number of taps to detect (guitar mode). Default 1.
            calibration_path:  Optional path to a microphone calibration file
                               (.txt, .cal) to apply during playback.
        """
        import os as _os

        import numpy as np
        import soundfile as _sf

        from models.tap_display_settings import TapDisplaySettings as _tds

        # 1. Configure measurement type and tap count.
        _tds.set_measurement_type(measurement_type)
        self.number_of_taps = number_of_taps

        # 1b. If a calibration file was provided, parse it and temporarily
        #     override the active calibration on the analyzer.
        if calibration_path is not None:
            from models import microphone_calibration as _mc
            cal = _mc.MicrophoneCalibration.from_path(calibration_path)
            self.set_temporary_calibration(cal)

        # 2. Start the tap sequence with warmup skipped (deterministic file audio).
        self.start_tap_sequence(skip_warmup=True)

        # 3. Read the audio file.
        data, file_rate = _sf.read(path, dtype="float32", always_2d=True)
        mono = data.mean(axis=1).astype(np.float32)
        file_name = _os.path.splitext(_os.path.basename(path))[0]

        # 4. Set the sample rate so gated_capture_samples is computed correctly.
        self._mpm_sample_rate = float(file_rate)

        # 5. Process all audio inline, pumping the Qt event loop between
        #    chunks so that _main_async_after callbacks (delivered via
        #    QueuedConnection signal → QTimer.singleShot) fire during
        #    playback — exactly as Swift's playFileForTesting pumps
        #    RunLoop.main.run(until:) to drain asyncAfter callbacks.
        #
        #    A QCoreApplication is required for event-loop pumping.  The
        #    test harness creates one via the qapp fixture (or we create a
        #    transient one here if none exists).
        from PySide6 import QtWidgets
        app = QtWidgets.QApplication.instance()
        owns_app = False
        if app is None:
            app = QtWidgets.QApplication([])
            owns_app = True

        self.mic.process_file_data(mono, int(file_rate), file_name)

        # Continue pumping the Qt event loop until the measurement completes.
        # _finish_capture (and thus process_multiple_taps) is scheduled via
        # QTimer.singleShot with a delay of capture_window (200 ms), so we
        # must keep processing events until it fires and sets
        # is_measurement_complete = True.
        import time as _time
        _deadline = _time.monotonic() + 5.0
        while not self.is_measurement_complete and _time.monotonic() < _deadline:
            app.processEvents()
            _time.sleep(0.01)

        if owns_app:
            app.shutdown()

    # ------------------------------------------------------------------ #
    # _wire_pipeline_signals — shared by start() and for_testing()
    # ------------------------------------------------------------------ #

    def _wire_pipeline_signals(self) -> None:
        """Connect pipeline signals and direct callbacks to this analyzer.

        This wires both the direct callback properties (for file playback
        where there is no Qt event loop) and the Qt signal connections (for
        live mic UI updates).

        Mirrors Swift ``TapToneAnalyzer.setupSubscriptions()``.
        """
        # ── Direct callbacks (work without Qt event loop) ────────────────
        # These are the primary delivery path for pipeline-critical events.
        # Mirrors Swift's direct handler closures on RealtimeFFTAnalyzer.
        self.mic.rms_level_handler = self._on_rms_level_changed_direct
        self.mic.fft_frame_handler = self.on_fft_frame

        # ── Gated-FFT capture signal (Qt — for cross-thread delivery) ────
        self.mic.proc_thread.gatedCaptureComplete.connect(self.finish_gated_fft_capture)

        # ── Input-clipping signal (Qt — UI only) ────────────────────────
        self.mic.proc_thread.clippingChanged.connect(self._set_clipping)

        # ── Raw-sample handler ───────────────────────────────────────────
        self.mic.raw_sample_handler = self._accumulate_gated_samples

        # ── Level-crossing handler (audio-queue fast-start) ──────────────
        def _level_crossing_handler() -> None:
            from models.measurement_type import MeasurementType as _MT
            from models.tap_display_settings import TapDisplaySettings as _tds
            from guitar_tap.utilities.logging import TAP_DEBUG
            import math
            mt = _tds.measurement_type()
            with self._gated_lock:
                if mt == _MT.PLATE or mt == _MT.BRACE:
                    # Guard: only start a capture when we're actually in a
                    # capturing phase.  Before file playback starts the phase
                    # is still NOT_STARTED — mic audio can trigger a spurious
                    # level crossing in that window.  After playback ends the
                    # phase is COMPLETE — mic restart can trigger another.
                    phase = self.material_tap_phase
                    if not phase.is_capturing:
                        TAP_DEBUG("levelCrossing",
                            f"SKIPPED — phase {phase} is not capturing")
                        return

                    # File-playback deferred path: if a previous capture has
                    # completed on the audio thread and its finish_gated_fft_capture
                    # dispatch is still pending on the main thread, starting a
                    # new _gated_capture_active here would cascade — the new capture
                    # fills before the main thread can advance the phase, so it
                    # runs under the stale phase.  Instead, just snapshot the
                    # pre-roll so the main-thread start_gated_capture can seed
                    # from the correct audio position when it eventually runs.
                    # Mirrors Swift levelCrossingHandler deferred path.
                    if (self.mic is not None
                            and self.mic.is_playing_file
                            and self._pending_level_crossing_pre_roll is None
                            and not self._gated_capture_active
                            and self._last_level_crossing_capture_id == self._gated_capture_id):
                        self._pending_level_crossing_pre_roll = list(self._pre_roll_buf)
                        pre_roll_count = len(self._pre_roll_buf)
                        TAP_DEBUG("levelCrossing",
                            f"DEFERRED — snapshot pre-roll ({pre_roll_count} samples) "
                            f"for main-thread start_gated_capture")
                        return

                self._gated_capture_id += 1
                self._last_level_crossing_capture_id = self._gated_capture_id
                self._gated_accum = list(self._pre_roll_buf)
                if mt == _MT.PLATE or mt == _MT.BRACE:
                    # Plate/brace: use the current phase and 400 ms window.
                    self._gated_capture_phase = self.material_tap_phase
                    self._gated_capture_samples = int(
                        float(self._gated_sample_rate) * self.GATED_CAPTURE_DURATION
                    )
                    # Keep the pre-roll even when it contains digital silence
                    # (e.g. inter-tap gaps in a concatenated playback file).
                    # The pre-roll positions the tap transient at ~sample 9600
                    # of the 32768-sample Hann window, matching the live-capture
                    # weighting.  Discarding it shifts the transient to sample 0
                    # where the Hann weight is ~0, distorting magnitudes by
                    # several dB.
                else:
                    # Guitar: None phase sentinel, fft_size window.
                    self._gated_capture_phase = None
                    self._gated_capture_samples = self.mic.fft_size
                self._gated_capture_active = True
                self._pending_level_crossing_pre_roll = None  # consumed by direct start
                pre_roll_count = len(self._gated_accum)
                target = self._gated_capture_samples
            TAP_DEBUG("levelCrossing",
                f"Gated capture started on audio queue | "
                f"mode={mt} pre-roll {pre_roll_count} samples, target {target}")

        self.mic._level_crossing_handler = _level_crossing_handler
        self.mic._level_crossing_threshold = self.tap_detection_threshold

        # ── Pre-mic-restart handler ─────────────────────────────────────
        self.mic._on_pre_mic_restart = self._flush_gated_capture_on_file_end

        # ── Post-engine-stop handler ──────────────────────────────────
        # Wipe both the pre-roll ring buffer AND any in-flight gated
        # capture.  Without resetting _gated_accum/_gated_capture_active,
        # a level-crossing that fired on live-mic noise just before the
        # source switch would persist, causing file chunks to be appended
        # onto a buffer already seeded with mic samples — the captured
        # window then mixes mic noise into the FFT input.
        def _clear_pre_roll():
            with self._gated_lock:
                self._pre_roll_buf = []
                self._gated_accum = []
                self._gated_capture_active = False
                self._gated_capture_phase = None
                # Reset capture IDs so the deferred level-crossing guard
                # (_last_level_crossing_capture_id == _gated_capture_id) won't
                # match on the first file tap due to stale IDs from a prior
                # live capture.  Mirrors Swift postEngineStopHandler.
                self._last_level_crossing_capture_id = -1
                self._gated_capture_id = 0
                self._pending_level_crossing_pre_roll = None
        self.mic._on_post_engine_stop = _clear_pre_roll

        # ── Qt signal connections (for UI — live mic path) ───────────────
        # These are secondary to the direct callbacks above.  They exist
        # for the UI layer (fft_canvas, tap_tone_analysis_view) which
        # connects to these Qt signals for chart updates and level meters.
        self.mic.proc_thread.fftFrameReady.connect(self.on_fft_frame)
        self.mic.proc_thread.rmsLevelChanged.connect(self._on_rms_level_changed)

    # ------------------------------------------------------------------ #
    # _on_rms_level_changed_direct — direct callback version of _on_rms_level_changed
    # ------------------------------------------------------------------ #

    def _on_rms_level_changed_direct(self, level_db: float) -> None:
        """Direct-callback RMS handler — called by process_raw_samples.

        Same logic as ``_on_rms_level_changed(rms_amp)`` but takes
        ``level_db: float`` directly instead of the 0-100 scaled int.
        This works without a Qt event loop (file playback, tests).

        Mirrors Swift's Combine sink on fftAnalyzer.$inputLevelDB.
        """
        rms_amp = int(level_db + 100.0)
        self._on_rms_level_changed(rms_amp)

    # _initialize_pre_roll was removed — pre-filling the pre-roll with
    # zeros diluted the gated capture signal by ~50%, suppressing spectral
    # magnitude by ~6 dB.  The pre-roll buffer now starts empty (cleared by
    # start_tap_sequence) and fills naturally with real audio as chunks arrive.

    # ------------------------------------------------------------------ #
    # is_detecting property — mirrors Swift @Published var isDetecting
    # with didSet that arms/disarms the level-crossing detector.
    # ------------------------------------------------------------------ #

    @property
    def is_detecting(self) -> bool:
        return self._is_detecting

    @is_detecting.setter
    def is_detecting(self, value: bool) -> None:
        old = self._is_detecting
        self._is_detecting = value
        # Mirrors Swift isDetecting.didSet — arm the audio-queue level-crossing
        # detector on false→true transition; disarm on any transition to false.
        if self.mic is not None:
            if value and not old:
                # false → true: arm crossing and sync previous level.
                self.mic._level_crossing_armed = True
                # During file playback the audio queue is already tracking
                # _previous_level_db naturally.  Resetting it to -100 would
                # create a false rising-edge on the next chunk if the
                # previous tap's ring-out tail is still above threshold,
                # causing a spurious capture of silence/decay instead of
                # waiting for the real next tap's attack.
                if not self.mic.is_playing_file:
                    self.mic._previous_level_db = -100.0
            elif not value:
                # → false: disarm crossing.
                # During file playback, the audio queue manages its own
                # re-arming cycle (_accumulate_gated_samples re-arms after
                # each capture completes).  Disarming here would undo that
                # re-arm before the next tap's audio arrives on the queue.
                if not self.mic.is_playing_file:
                    self.mic._level_crossing_armed = False

    def start(
        self,
        parent_widget,
        calibration_corrections=None,
        calibration_name: "str | None" = None,
        calibration_profile: object | None = None,
    ) -> None:
        """Complete view-layer wiring and load persisted state.

        Called by FftCanvas after construction.  The RealtimeFFTAnalyzer
        (self.mic) and pipeline signals are already wired by ``__init__``.
        This method handles the remaining view-layer integration that
        requires the parent widget:
          - QObject re-parenting
          - Hotplug signal wiring
          - Calibration state
          - Device enumeration
          - Saved measurements
          - Auto-start tap sequence

        Tests never call this — ``for_testing()`` provides everything
        ``__init__`` needs.

        Args:
            parent_widget:           The FftCanvas (QObject parent).
            calibration_corrections: ndarray of per-bin dB corrections, or None.
            calibration_name:        Human-readable calibration name, or None.
            calibration_profile:     Full CalibrationProfile object, or None.
        """
        import sounddevice as _sd
        from models import microphone_calibration as _mc_mod

        self._sd = _sd
        self._mc_mod = _mc_mod

        # Re-parent this QObject to the view widget now that we have it.
        self.setParent(parent_widget)
        self.mic.proc_thread.setParent(self)

        # Wire the hotplug signal now that the Qt object hierarchy is valid.
        self._devicesRefreshed.connect(self._on_devices_refreshed)

        # Wire device-change and calibration-change callbacks on the mic.
        # These were deferred from mic construction (passed as None) because
        # self._devicesRefreshed and self._on_mic_calibration_changed require
        # the Qt signal system to be wired, which needs setParent() first.
        self.mic._on_devices_changed = self._devicesRefreshed.emit
        self.mic._on_calibration_changed = self._on_mic_calibration_changed

        # ── Calibration ───────────────────────────────────────────────────
        self._calibration_corrections = calibration_corrections
        self._calibration_profile = calibration_profile
        self._active_calibration_name = calibration_name
        audio_device = self.mic._selected_input_device
        self._calibration_device_name = audio_device.name if audio_device else ""

        # ── Initial device enumeration ────────────────────────────────────
        # Mirrors Swift RealtimeFFTAnalyzer.init() calling loadAvailableInputDevices()
        # synchronously so that availableInputDevices is populated before any
        # measurement can be loaded. Suppresses the _on_devices_changed callback to
        # avoid triggering _on_devices_refreshed (which calls sd._terminate()) during
        # init — the hot-plug monitor will handle subsequent changes.
        saved_cb = self.mic._on_devices_changed
        self.mic._on_devices_changed = None
        try:
            self.mic.load_available_input_devices()
        finally:
            self.mic._on_devices_changed = saved_cb

        # Stamp the cooldown timer so the spurious CM_Register_Notification that
        # Windows fires when Pa_OpenStream is called during init (or when the CM
        # monitor registers) does not immediately trigger _on_devices_refreshed
        # and switch away from the saved/selected device.
        import time as _time_mod
        self._devices_refresh_last_t = _time_mod.monotonic()

        # ── Saved measurements (view-layer import deferred until here) ────
        from views.tap_analysis_results_view import load_all_measurements as _load
        self.saved_measurements = _load()
        self.savedMeasurements = self.saved_measurements
        if self.saved_measurements:
            gt_log(f"📂 Loaded {len(self.saved_measurements)} persisted measurements")
        else:
            gt_log("📂 No persisted measurements file found")

        # ── Auto-start tap sequence on first launch ────────────────────────
        # Mirrors Swift start() auto-start guard:
        #   if !isDetecting && !isMeasurementComplete && !isDetectionPaused
        #      && currentTapCount == 0 { startTapSequence() }
        if (not self.is_detecting and not self.is_measurement_complete
                and not self.is_detection_paused and self.current_tap_count == 0):
            self.start_tap_sequence()

    # ------------------------------------------------------------------ #
    # FFT frequency axis
    # ------------------------------------------------------------------ #

    def _update_frequency_bins(self) -> None:
        """Recompute self.freq from the current mic sample rate.

        Must be called whenever self.mic.rate changes (e.g. after start_from_file
        changes the rate to match a WAV file's native sample rate).

        Mirrors Swift RealtimeFFTAnalyzer.updateFrequencyBins() called in
        startFromFile(_:) after setting actualSampleRate = engineSampleRate.

        Without this, self.freq retains the bins computed at construction from
        the hardware mic rate, causing peak-frequency lookups to be scaled by
        (hardware_rate / file_rate) during file playback.
        """
        import numpy as _np
        x_axis = _np.arange(0, self.mic.h_fft_size + 1)
        self.freq = x_axis * self.mic.rate / self.mic.fft_size

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
    def is_saved_measurement_comparison(self) -> bool:
        """True when the user has loaded saved measurements to overlay for comparison.

        False during multi-tap comparison (per-tap waveform view of the current guitar
        measurement), even though both sub-types set display_mode = COMPARISON.

        Mirrors Swift TapToneAnalyzer.isSavedMeasurementComparison:
            var isSavedMeasurementComparison: Bool {
                displayMode == .comparison && !showingMultiTapComparison
            }
        """
        return self.is_comparing and not self.showing_multi_tap_comparison

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

        Applies the current calibration to the analyzer.
        FftCanvas calls this when it needs to reset all processing state
        (e.g. after the analyzer was already running and the user presses Start
        again).

        Returns the new proc_thread (_FftProcessingThread) so FftCanvas can
        reconnect signals.

        Python-only — Swift achieves equivalent reset via AVAudioEngine stop/start.
        """
        from .realtime_fft_analyzer import _FftProcessingThread as _FPT
        self.mic.proc_thread = _FPT(mic=self.mic, parent=self)
        self.mic.set_calibration(self._calibration_corrections,
                                 profile=self._calibration_profile)
        # Reconnect the Qt signals on the new thread for UI delivery.
        self.mic.proc_thread.fftFrameReady.connect(self.on_fft_frame)
        self.mic.proc_thread.gatedCaptureComplete.connect(self.finish_gated_fft_capture)
        return self.mic.proc_thread

    # ------------------------------------------------------------------ #
    # Mode Override
    # Mirrors Swift TapToneAnalyzer.swift (not in any extension file):
    #   effectiveModeLabel / setModeOverride / hasManualOverride
    # ------------------------------------------------------------------ #

    def effective_mode_label(self, peak) -> str:
        """Return the display label for a peak, respecting any user override.

        Mirrors Swift ``effectiveModeLabel(for peak: ResonantPeak) -> String``:

            switch peakModeOverrides[peak.id] ?? .auto {
            case .auto:              return peakMode(for: peak).displayName
            case .assigned(let l):   return l
            }

        For the auto case, delegates to ``self.peak_mode(peak)`` which reads
        ``identified_modes`` (populated by ``classify_all`` with all peaks together)
        before falling back to ``classify_all([peak])`` — identical to Swift
        ``peakMode(for:)``.  Returns ``mode.display_name`` (human-readable),
        not ``mode.value`` (internal enum string).
        """
        override = self.peak_mode_overrides.get(peak.id)
        if override:
            return override
        # Mirrors Swift .auto case: peakMode(for: peak).displayName
        return self.peak_mode(peak).display_name

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
        from .guitar_mode import GuitarMode
        from .tap_display_settings import TapDisplaySettings
        measurement_type = TapDisplaySettings.measurement_type()
        if measurement_type.is_guitar and not TapDisplaySettings.show_unknown_modes():
            guitar_type = TapDisplaySettings.guitar_type()
            candidates = [p for p in candidates if GuitarMode.is_known(p.frequency, guitar_type)]
        return candidates
