# @parity audio/tap-analyzer tests=test/tap-decisions,test/effective-peak-id,test/tap-count-change
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

import os
import sys
from datetime import datetime
from typing import NamedTuple, Callable

# ── PySide6 ─────────────────────────────────────────────────────────────────────
from PySide6 import QtCore

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode
from guitar_tap.utilities.logging import gt_log
from guitar_tap.utilities import slack_probe as _slack_probe

# ── AnalysisDisplayMode ───────────────────────────────────────────────────────
# Mirrors Swift AnalysisDisplayMode enum defined in TapToneAnalyzer.swift.
# Lives in analysis_display_mode.py so the mixin files can import it without
# creating a circular dependency (they are imported by this file).
from .analysis_display_mode import AnalysisDisplayMode
from .detected_peaks import DetectedPeaks
from .detection_state import DetectionState
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
from .wall_clock import SystemWallClock, WallClock

# ── TapToneAnalyzer ───────────────────────────────────────────────────────────
# Mirrors the top-level Swift TapToneAnalyzer class declaration and its stored
# properties / init.  All methods live in the mixin base classes above,
# matching the Swift extension-file organisation.


class ResultProvenance(NamedTuple):
    """Where a result came from when it is not the live input: a played file (no microphone — the one
    that recorded a file is not known — the calibration it was played with, or None, and its sample
    rate) or a loaded measurement (what the file recorded). Mirrors Swift
    ``TapToneAnalyzer.ResultProvenance``."""
    microphone_name: "str | None"
    microphone_uid: "str | None"
    calibration_name: "str | None"
    sample_rate: "float | None"

class CaptureRecording(NamedTuple):
    """A capture's audio waiting to be saved by Dump Capture Audio. Mirrors Swift
    ``TapToneAnalyzer.CaptureRecording``."""

    samples: object       # float32 ndarray
    sample_rate: float
    label: str
    captured_at: datetime  # when it was captured — names the file, whenever it is written


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
    # Full spectrum ready for the view to draw.
    spectrumUpdated: QtCore.Signal = QtCore.Signal(object, object)  # (freqs, mags_db)
    # A single tap has been fully captured (all required taps averaged).
    # Live tap count update: (captured, total).
    tapCountChanged: QtCore.Signal = QtCore.Signal(int, int)

    # Emitted whenever detection_state changes, carrying the new DetectionState. Stands in for
    # Swift's @Published detectionState, which the status bar binds to directly; without it the
    # view cannot re-evaluate on a detection-state change.
    detectionStateChanged: QtCore.Signal = QtCore.Signal(object)
    # Emitted whenever is_ready_for_detection changes. Stands in for Swift's @Published
    # isReadyForDetection: there it flips during a route-change restart and every bound view
    # re-renders, which is what greys New Tap out for the settle. Python has no such binding, so
    # this signal is what tells the view to re-evaluate the button state.
    readyForDetectionChanged: QtCore.Signal = QtCore.Signal(bool)
    # The ring-out on screen changed: seconds, or None while there is none yet. Swift's
    # `@Published var currentDecayTime` re-renders the Ring-Out box on every change; Python has no such
    # binding, so the property below emits this.
    currentDecayTimeChanged: QtCore.Signal = QtCore.Signal(object)
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
    # Each material peak, announced on every write (capture, load, redo's clear); payload the
    # ResonantPeak or None. Mirrors Swift @Published selectedLongitudinalPeak / selectedCrossPeak /
    # selectedFlcPeak — the view widens the chart onto an identified peak.
    selectedLongitudinalPeakChanged: QtCore.Signal = QtCore.Signal(object)
    selectedCrossPeakChanged: QtCore.Signal = QtCore.Signal(object)
    selectedFlcPeakChanged: QtCore.Signal = QtCore.Signal(object)
    # Plate analysis complete: (fL, fC, fFLC) Hz.
    plateAnalysisComplete: QtCore.Signal = QtCore.Signal(float, float, float)
    # Tap detection pause state changed.
    tapDetectionPaused: QtCore.Signal = QtCore.Signal(bool)
    # Emitted when comparison overlay data changes (True=entering, False=leaving).
    comparisonChanged: QtCore.Signal = QtCore.Signal(bool)
    # Emitted when longitudinal_spectrum, cross_spectrum or flc_spectrum is assigned. Mirrors Swift's
    # @Published longitudinalSpectrum / crossSpectrum / flcSpectrum, which TapToneAnalysisView observes to
    # rebuild overlaySpectra.
    phaseSpectraChanged: QtCore.Signal = QtCore.Signal()
    # Emitted when savedMeasurements list changes (mirrors Swift @Published var savedMeasurements).
    savedMeasurementsChanged: QtCore.Signal = QtCore.Signal()
    # Emitted when frequency range changes (fmin, fmax).
    freqRangeChanged: QtCore.Signal = QtCore.Signal(int, int)
    # Emitted when a loaded measurement or comparison supplies all four axis bounds atomically.
    # Payload: (min_freq: int, max_freq: int, min_db: float, max_db: float).
    # Mirrors Swift TapToneAnalyzer.setLoadedAxisRange(minFreq:maxFreq:minDB:maxDB:) which
    # publishes loadedAxisRange so TapToneAnalysisView can apply all four bounds in one pass.
    loadedAxisRangeChanged: QtCore.Signal = QtCore.Signal(float, float, float, float)
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
    # Emitted after load_measurement() switched the input to the recorded microphone, so the
    # view shows it. Payload: AudioDevice. Swift's view re-reads @Published selectedInputDevice.
    inputDeviceSwitched: QtCore.Signal = QtCore.Signal(object)
    # Emitted when a device switched to while running (plugged in, or a fallback) could not be
    # opened; the previous device is kept. Payload: the message for the alert. Mirrors Swift
    # @Published var inputDeviceOpenFailure.
    inputDeviceOpenFailed: QtCore.Signal = QtCore.Signal(str)
    # Emitted when arming is refused because Dump Capture Audio is on and its folder can't be
    # reached; the view prompts (Change Location / Turn Off Saving / Cancel). Mirrors Swift
    # @Published var dumpFolderUnreachable.
    dumpFolderUnreachable: QtCore.Signal = QtCore.Signal()
    # Emitted when a finished measurement's captured audio could not be written and is held; the view
    # asks the user to choose a folder, turn off saving, or cancel. Mirrors Swift
    # @Published var captureRecordingHeld.
    captureRecordingHeld: QtCore.Signal = QtCore.Signal()
    # The file name of the last capture audio Dump Capture Audio wrote (for the "saved" notice), or
    # None when none is shown. Mirrors Swift @Published var captureAudioSaved.
    captureAudioSavedChanged: QtCore.Signal = QtCore.Signal(object)
    # The two edges of load_measurement() — is_loading_measurement going True, then False (Swift's
    # isLoadingMeasurement). SwiftUI re-renders from the loaded state on its own; Qt does not, so the
    # view does its restoration work in response to these rather than by wrapping the load itself.
    # That is what lets ANY caller load — the list, and an import — and still have the screen follow.
    # STARTING exists because two view steps must precede the load's own signals (see the view).
    measurementLoadStarting: QtCore.Signal = QtCore.Signal()
    measurementLoaded: QtCore.Signal = QtCore.Signal(object)   # the TapToneMeasurement just loaded
    # The highlighted peak's id changed (None: none). The chart's star and the peak list's highlighted card
    # draw from it — Swift's views read @Published highlightedPeakID.
    highlightedPeakChanged: QtCore.Signal = QtCore.Signal(object)
    # Internal: fired from hotplug monitor thread → main thread (no-arg).
    _devicesRefreshed: QtCore.Signal = QtCore.Signal()
    # Internal: cross-thread DispatchQueue.main.asyncAfter equivalent.
    # Emitted from any thread; Qt QueuedConnection delivers the slot on the
    # main thread.  Payload: (delay_ms: int, callable: object).
    # Mirrors Swift DispatchQueue.main.asyncAfter(deadline:execute:).
    _mainAsyncAfterRequest: QtCore.Signal = QtCore.Signal(int, object)

    def __init__(self, fft_analyzer=None, wall_clock: "WallClock | None" = None) -> None:
        """Create a TapToneAnalyzer with all state at sensible defaults.

        Mirrors Swift ``TapToneAnalyzer(fftAnalyzer: RealtimeFFTAnalyzer, wallClock:)``.

        When ``fft_analyzer`` is provided, pipeline signals are wired
        immediately (matching Swift's ``setupSubscriptions()`` called from
        ``init``).  Audio-hardware lifecycle (start/stop) is still managed
        by ``start()``, which the view layer calls after construction.

        Args:
            fft_analyzer: Optional RealtimeFFTAnalyzer.  None-safe — bare
                          instances (no mic) can be constructed for direct
                          analysis method testing.
            wall_clock: The wall clock the capture's safety timeout reads and
                        schedules on — the system's when None, as in the app.
        """
        import numpy as np

        from guitar_tap.models import guitar_mode as _gm
        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        # Qt's metaclass does not participate in Python's cooperative super()
        # chain, so the QObject base must be initialised explicitly.
        QtCore.QObject.__init__(self, None)

        self.wall_clock: WallClock = wall_clock if wall_clock is not None else SystemWallClock()

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
        from guitar_tap.models.pitch import Pitch as _Pitch
        self.pitch_calculator = _Pitch(a4=440.0)

        # ── fft_analyzer reference (mirrors Swift's fftAnalyzer property) ──
        # Both production and test paths provide a mic at construction time,
        # matching Swift where init(fftAnalyzer:) always receives one.
        self.mic = fft_analyzer  # type: ignore[assignment]

        # ── FFT configuration ──────────────────────────────────────────────
        if self.mic is not None:
            x_axis = np.arange(0, self.mic.h_fft_size)
            self.freq = x_axis * self.mic.rate / self.mic.fft_size
        else:
            self.freq = np.array([])

        # ── Calibration ────────────────────────────────────────────────────
        # The calibration lives on the engine (self.mic.active_calibration / calibration_corrections),
        # as Swift's on fftAnalyzer.
        self._calibration_device_name: str = ""

        # ── Display mode (mirrors Swift AnalysisDisplayMode) ───────────────
        self._display_mode: AnalysisDisplayMode = AnalysisDisplayMode.LIVE

        # ── Stored properties — mirrors Swift TapToneAnalyzer @Published vars ──
        # Previously declared as Published(...) class-level descriptors.
        # Plain instance attributes are equivalent: all reactive UI updates
        # go through Qt signals, not through the swiftui_compat notify chain.

        # MARK: - Configuration (mirrors Swift @Published vars)
        self.min_frequency: float = float(_tds.analysis_min_frequency())   # mirrors minFrequency
        self.max_frequency: float = float(_tds.analysis_max_frequency())   # mirrors maxFrequency
        self._peak_min_threshold: float = float(_tds.peak_min_threshold())   # backing store for the peak_min_threshold property (mirrors peakMinThreshold)
        # Backing store for the ``tap_detection_threshold`` property (Swift's ``didSet`` on
        # ``tapDetectionThreshold``: it saves the value and ends the loaded-settings warning).
        self._tap_detection_threshold: float = float(_tds.tap_detection_threshold())
        # Minimum decay level below the tap peak for ring-out measurement, in dB.
        # Ring-out is measured from the peak to the first moment the signal drops
        # more than this below it; 15 dB works well against room noise floors.
        self.decay_threshold: float = 15.0                                 # mirrors decayThreshold
        self._number_of_taps: int = 1                                      # mirrors numberOfTaps
        self.capture_timer_active: bool = False                            # mirrors captureTimer != nil

        # MARK: - Results
        # The detected peaks — all_peaks, peaks_above_peak_min, identified_modes and selected_peak_ids —
        # held and announced (peaksChanged) on their own: they change on every live frame while a sequence
        # waits for a tap, and announced by the analyzer they would reach every view that listens to it.
        # Mirrors Swift `peaks` (DetectedPeaks). The analyzer reads and writes them through the properties
        # below. The DURABLE full peak set (found at the -100 dB floor at capture) is the source of truth
        # for peak identity; peaks_above_peak_min is its Peak-Min display projection. Assign via the
        # all_peaks property so the projection refreshes (Swift allPeaks' setter).
        self.peaks = DetectedPeaks()
        # `peaks_above_peak_min` (mirrors Swift `peaksAbovePeakMin`) is the Peak-Min projection of
        # `all_peaks` — NOT "the peaks". Three distinct scopes exist; this is the MIDDLE one:
        #   all_peaks                        = the MEASUREMENT (capture / explicit Re-analyze)
        #   peaks_above_peak_min             = a SETTING       (the Peak Min slider)
        #   fft_canvas._all_peaks_in_range   = the VIEWPORT    (pan / zoom / a different chart)
        # Anything asking a question ABOUT THE MEASUREMENT — save, selection, classification,
        # per-peak state carry-forward, whether a measurement exists — reads `all_peaks`, never this.
        self._current_decay_time: "float | None" = None                   # mirrors currentDecayTime
        self.saved_measurements: list = []                                 # mirrors savedMeasurements
        # The library could not be read at launch and was kept aside: the message, shown once by the view
        # and cleared (Swift libraryLoadFailure); and whether it could not be kept aside either, so the
        # library is not written this session (Swift isLibraryWriteBlocked).
        self.library_load_failure: str | None = None
        self.is_library_write_blocked: bool = False

        # MARK: - Detection State
        # mirrors detectionState; is_detecting / is_detection_paused derive from it
        self._detection_state: DetectionState = DetectionState.IDLE
        # True while a device/route change settles and the chart should show nothing. A flag of its
        # own, separate from display_mode, so the transient blank never touches a completed
        # measurement's display.
        self.is_settling: bool = False
        # mirrors isReadyForDetection; the property below emits readyForDetectionChanged
        self._is_ready_for_detection: bool = True
        self.current_tap_count: int = 0             # mirrors currentTapCount
        self.tap_progress: float = 0.0              # mirrors tapProgress
        # All writes must go through _set_status_message() to emit statusMessageChanged.
        # Mirrors Swift @Published var statusMessage: String.
        # @parity state/status-message
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
        self.highlighted_peak_id = None             # mirrors highlightedPeakID
        self.annotation_visibility_mode = AnnotationVisibilityMode.from_string(
            _tds.annotation_visibility_mode()
        )                                           # mirrors annotationVisibilityMode

        # MARK: - Measurement Complete State
        # Assign the backing field, not the property: the setter reads collaborators that
        # __init__ has not created yet (show_loaded_settings_warning, is_loading_measurement,
        # material_inputs, all below).  Mirrors Swift, whose property initialiser likewise
        # does not run didSet.
        self._is_measurement_complete: bool = False  # mirrors isMeasurementComplete

        # Mirrors Swift @Published var showLoadedSettingsWarning: Bool
        # Set True by load_measurement(); cleared when the user changes threshold
        # or tap count away from the loaded values, or on a successful new tap, or reset.
        self.show_loaded_settings_warning: bool = False
        # Sentinel values stored at load time — used to detect user-initiated changes.
        # Mirror Swift loadedTapDetectionThreshold and loadedNumberOfTaps.
        self.loaded_tap_detection_threshold: "float | None" = None
        self.loaded_number_of_taps: "int | None" = None

        # Mirrors Swift @Published var microphoneWarning: String?
        # Set by load_measurement() when the loaded measurement's microphone is not connected, or
        # its calibration / sample rate differs. An import never sets it — only a load shows the user
        # data. The view clears it once the alert is acknowledged; import_and_load_measurements()
        # folds it into its message and clears it (mirrors Swift).
        self.microphone_warning: "str | None" = None
        # The title of the dialog that shows microphone_warning; set with it. Mirrors Swift
        # microphoneWarningTitle.
        self.microphone_warning_title: str = "Microphone Not Found"

        # ── Loaded-measurement metadata ────────────────────────────────────
        # Mirrors Swift @Published var loadedMeasurementName: String?,
        # @Published var loadedNotes: String?, and
        # @Published var sourceMeasurementTimestamp: Date?
        # Set by load_measurement(); cleared by start_tap_sequence() / reset.
        self.loaded_measurement_name: "str | None" = None
        # loaded_notes: restored on load so re-saving a loaded measurement keeps its notes
        # (R10) — previously only the name was restored, so the notes were silently dropped.
        self.loaded_notes: "str | None" = None
        self.source_measurement_timestamp: "str | None" = None  # ISO-8601 string

        # ── Additional peak analysis state ────────────────────────────────
        # Whether the user has manually changed peak selection since last auto-run.
        # Mirrors Swift TapToneAnalyzer.userHasModifiedPeakSelection.
        self.user_has_modified_peak_selection: bool = False
        # True while load_measurement restores a measurement, so completing it there is told apart
        # from a capture completing. Mirrors Swift TapToneAnalyzer.isLoadingMeasurement.
        self.is_loading_measurement: bool = False
        # Store B — the current material measurement's own dimensions (plate/brace L·W·T·M + Gore
        # body dims + f_vs). None for guitar and before a material measurement completes. Seeded from
        # the Settings defaults at the complete-freeze, restored from the snapshot on load, edited in
        # the Results panel; it is the sole source for the measurement's calc/display/PDF and Save.
        # Mirrors Swift TapToneAnalyzer.materialInputs.
        self.material_inputs = None  # type: "MaterialMeasurementInputs | None"
        # Where the current result came from when it is not the live input — a played file or a loaded
        # measurement — or None while listening to the input. Mirrors Swift resultProvenance.
        self.result_provenance: "ResultProvenance | None" = None
        # Frequencies of the currently selected peaks, kept with the selection and saved with the
        # measurement; nothing reads it back. Mirrors Swift selectedPeakFrequencies.
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

        self._current_mag_y_db = np.array([])
        # Instantaneous RMS level in dBFS — mirrors Swift fftAnalyzer.inputLevelDB.
        # Updated every ~23 ms by _on_rms_level_changed; used by _do_reenable_detection
        # so it reads the current level (not the 0.5 s peak-hold) exactly as Swift does.
        self._current_input_level_db: float = -100.0
        # Instantaneous FFT peak magnitude in dBFS — mirrors Swift fftAnalyzer.peakMagnitude.
        # Updated every ~370 ms (at FFT rate) by on_fft_frame; used by guitar-mode _reenable()
        # which mirrors Swift handleTapDetection's re-enable closure using fftAnalyzer.peakMagnitude.
        # Distinct from _current_input_level_db (inputLevelDB/RMS).
        self._current_peak_magnitude_db: float = -100.0

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
        # Current phase of the multi-tap material sequence: NOT_STARTED ->
        # CAPTURING_LONGITUDINAL -> REVIEWING_LONGITUDINAL -> CAPTURING_CROSS ->
        # REVIEWING_CROSS -> (optional FLC phases) -> COMPLETE. Mirrors materialTapPhase.
        self.material_tap_phase: "_MTP" = _MTP.NOT_STARTED
        # Averaged FFT spectrum from each material tap, once its phase completes (None
        # before), as (magnitudes, frequencies). Mirrors longitudinalSpectrum / crossSpectrum /
        # flcSpectrum; assigning one emits phaseSpectraChanged.
        self._longitudinal_spectrum = None
        self._cross_spectrum = None
        self._flc_spectrum = None
        # The identified peak of each material phase — the dominant peak of its averaged spectrum,
        # stored when the phase completes. These are a material measurement's peaks: there is no
        # per-peak selection and no other material peak state (all_peaks / selected_peak_ids are
        # guitar-only). Mirrors Swift selectedLongitudinalPeak / selectedCrossPeak / selectedFlcPeak.
        self.selected_longitudinal_peak = None
        self.selected_cross_peak = None
        self.selected_flc_peak = None

        # ── Tap detection state (mirrors Swift TapToneAnalyzer stored properties)
        # State bit of the hysteresis state machine: True while the signal is above the
        # detection threshold. A tap registers only on a rising edge (False->True)
        # confirmed by LEVEL_CROSSING_CONFIRMATION_CHUNKS chunks. Mirrors isAboveThreshold.
        self.is_above_threshold: bool = False
        # Running count of consecutive above-rising-threshold chunks within
        # the current candidate rising-edge run for the main-thread tap
        # detector.  Reset to 0 whenever the signal falls back below the
        # rising threshold before reaching
        # ``RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS``.  Once
        # the counter reaches the target, ``is_above_threshold`` latches to
        # True and the rising-edge actions run.  Mirrors Swift
        # ``TapToneAnalyzer.detectTapConsecutiveAbove``.
        self.detect_tap_consecutive_above: int = 0
        # True for the single FFT frame right after warm-up ends, so is_above_threshold
        # can be re-anchored to the real signal level without firing a spurious tap.
        # Mirrors justExitedWarmup.
        self.just_exited_warmup: bool = False
        # Value of the engine's AUDIO clock (mic.audio_elapsed) when a sequence was last armed.
        # Used to enforce the warm-up. Deliberately the AUDIO clock, not the wall clock: the warm-up
        # must cover the first `warmup_period` of AUDIO. Live the two coincide; in FILE PLAYBACK they
        # do not (setup happens between arming and the first chunk), and a wall-clock warm-up can
        # expire before any audio arrives — the warm-up never runs, the noise-floor re-anchor never
        # fires, and the EMA latches at its seed, silently disabling relative detection.
        self.warmup_start_audio_time: "float | None" = None
        # The audio clock as the analyzer has seen it: the audio time of the latest chunk delivered to
        # _on_rms_level_changed, recorded on every chunk before any guard. The tap-lifecycle timers run
        # on THIS clock, not the wall clock: file playback advances audio at "real time + processing
        # time", so a wall-clock delay would cover a different stretch of audio on a slower run and move
        # late captures in a sequence. Mirrors Swift lastAudioTime.
        self.last_audio_time: float = 0.0
        # The level (dBFS) of that chunk — a re-arm that falls due re-anchors the latch from it.
        # Mirrors Swift lastChunkLevelDB.
        self.last_chunk_level_db: float = -100.0
        # The WALL time (wall_clock) at which the latest chunk reached _on_rms_level_changed — what the
        # capture safety timeout measures its silence from (after_audio_stall). Mirrors Swift
        # lastChunkWallTime.
        self.last_chunk_wall_time: float = 0.0
        # Tap-lifecycle actions waiting on the audio clock: (due, released_at_file_end, action).
        # See after_audio(). Mirrors Swift pendingAudioActions.
        self._pending_audio_actions: "list[tuple[float, bool, Callable[[], None]]]" = []
        # Actions waiting for the next FFT frame, each given its peak magnitude. See after_next_frame().
        # Mirrors Swift pendingFrameActions.
        self._pending_frame_actions: "list[Callable[[float], None]]" = []
        # The device-change settle: what the status said before it (Swift statusBeforeSettle), whether
        # its end re-arms listening (Swift detectingBeforeSettle) — both None when no settle is in
        # progress — and the count of changes, so a later change supersedes an earlier one's restore
        # (Swift routeChangeGeneration).
        self._status_before_settle: "str | None" = None
        self._detecting_before_settle: "bool | None" = None
        self._route_change_generation: int = 0
        # Counts abandoned captures (abandon_capture). What a capture schedules — its processing,
        # the next tap's re-arm — runs only if no abandon has come since. Mirrors Swift
        # captureGeneration.
        self._capture_generation: int = 0
        # Exponential moving average of the input level, used as the ambient noise-floor
        # estimate for relative tap detection in plate/brace modes. Updated only when
        # the signal is below threshold (between taps) so tap energy does not
        # contaminate it. Mirrors noiseFloorEstimate.
        self.noise_floor_estimate: float = -60.0
        # ── Gated FFT capture state ────────────────────────────────────────
        # Mirrors Swift TapToneAnalyzer stored properties for gated capture:
        #   preRollBuffer: [Float]     — ring buffer of recent raw PCM
        #   preRollSamples: Int        — capacity of the pre-roll buffer
        #   gatedAccumBuffer: [Float]  — accumulator for the capture window
        #   gatedCaptureActive: Bool   — whether a capture is in progress
        #   gatedCaptureSamples: Int   — target window size in samples
        #   gatedCapturePhase: ...     — phase at capture start
        #
        # Owned here, as Swift's TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:) owns its buffers;
        # main thread only — every chunk reaches the analyzer there, in order (process_audio_frame).
        self._pre_roll_seconds: float = 0.2         # 200 ms pre-roll (mirrors Swift preRollDuration)
        self._pre_roll_buf: list = []               # raw PCM samples (float32)
        self._gated_capture_active: bool = False
        self._gated_capture_samples: int = 0        # target window size in samples (snapshot at capture-open)
        self._gated_capture_phase: object = None    # MaterialTapPhase at capture start
        self._gated_accum: list = []                # accumulated raw PCM samples
        self._mpm_sample_rate: float = 48000.0      # mirrors Swift mpmSampleRate (updated per audio buffer)

        # ── Session recording ─────────────────────────────────────────────
        # A continuous audio buffer that accumulates raw mic samples while tap
        # detection is active, producing one WAV per measurement that replays
        # identically through the pipeline.  Mirrors Swift TapToneAnalyzer
        # sessionRecordingBuffer / isSessionRecording / sessionCheckpoints /
        # sessionRecordingSampleRate.
        self._session_recording_buffer: list = []
        # True from the start of a sequence, whatever Dump Capture Audio says — the bounded pre-roll
        # is kept either way. False during pause, at the first tap when the sequence is not being
        # saved, when Dump Capture Audio is turned off after the first tap, when a loaded measurement
        # or comparison ends the sequence, or when the measurement completes.
        self._is_session_recording: bool = False
        # Whether this sequence's recording is saved — read from Dump Capture Audio when the sequence
        # starts, and again when the setting changes before the first tap (until then only the
        # pre-roll exists, so it is still the start). Turning the setting on after the first tap
        # takes effect from the next sequence; turning it off stops the recording at any point.
        # Mirrors Swift isSessionRecordingEnabled.
        self._is_session_recording_enabled: bool = False
        # Recordings that could not be written when their measurement finished (the chosen folder
        # was no longer at its path, or the write failed). Held until the user chooses a folder or
        # lets them go. Mirrors Swift heldCaptureRecordings.
        self.held_capture_recordings: list[CaptureRecording] = []
        # The file name of the last capture audio written, for the "saved" notice; None when none is
        # shown. A new sequence clears it. Mirrors Swift captureAudioSaved.
        self.capture_audio_saved: str | None = None
        # Whether the plate / brace peaks were restored by a load rather than identified by a capture. A
        # load shows the range it was saved with, so its peaks do not widen the chart. Set by a load
        # before it writes the peaks; cleared when a sequence starts. Mirrors Swift
        # materialPeaksFromLoad.
        self.material_peaks_from_load: bool = False
        self._session_checkpoints: list = []
        self._session_recording_sample_rate: float = 48000.0

        # Bounded pre-roll for the session WAV. True from
        # start_tap_sequence until the first gated capture begins, then False for the rest of the
        # session. While True, the session buffer keeps only the last SESSION_PRE_ROLL_DURATION of
        # audio — with Dump Capture Audio off too, so turning the setting on before the first tap
        # saves the same recording as having it on from the start; after the first tap it grows
        # straight through. Mirrors Swift sessionPreRollActive.
        self._session_pre_roll_active: bool = False

        # Monotonic capture identity — incremented at every start_*_gated_capture
        # call.  Each pending safety-timeout closure captures the ID at scheduling
        # time and only flushes the accumulator if `_gated_capture_id` still
        # matches.  Without this, a stale timeout from a previous capture can
        # fire while the next capture is mid-fill, dispatch its partial buffer
        # as if it were the new capture's complete result, and silently truncate
        # the capture window from fft_size samples to whatever fragment was
        # collected.  Mirrors Swift `gatedCaptureID`.
        self._gated_capture_id: int = 0
        # Load any previously saved measurements. Mirrors Swift init calling loadPersistedMeasurements().
        self.load_persisted_measurements()

        # ── Pipeline signal wiring ────────────────────────────────────────
        # Wire all signal/callback connections when the FFT analyzer is
        # provided.  Mirrors Swift init calling setupSubscriptions().
        if self.mic is not None:
            self._wire_pipeline_signals()

    # ------------------------------------------------------------------ #
    # Constants — Swift declares these `let`, so they are read-only here: a property with no setter,
    # so writing one raises AttributeError.
    # ------------------------------------------------------------------ #

    @property
    def _measurement_type(self):
        """The measurement type — the saved setting itself, as Swift's analyzer reads
        ``TapDisplaySettings.measurementType``. One store: a load, Settings and the analyzer all
        read and write the same value."""
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        return _tds.measurement_type()

    @property
    def hysteresis_margin(self) -> float:
        """Hysteresis margin, in dB. After a tap, the signal must fall at least this far below the
        detection threshold before the next tap can register — prevents re-triggering during a single
        tap's ring-out. A constant; it was once a user setting. Mirrors Swift ``hysteresisMargin``."""
        return 3.0

    @property
    def noise_floor_alpha(self) -> float:
        """EMA smoothing factor for noise-floor tracking. At ~23 ms audio-buffer updates (1024 samples at
        44.1 kHz), alpha = 0.05 gives a time constant tau ~= 450 ms (alpha ~= 1 - exp(-dt/tau)) — slow
        enough that brief transients (handling / room-noise spikes) do not drive the estimate up.
        Mirrors Swift ``noiseFloorAlpha``."""
        return 0.05

    @property
    def warmup_period(self) -> float:
        """Duration of the warm-up during which all taps are suppressed, in seconds of AUDIO; lets the
        audio engine and FFT pipeline settle after a cold start. Mirrors Swift ``warmupPeriod``."""
        return 0.5

    @property
    def tap_cooldown(self) -> float:
        """The rest after a capture before detection re-arms, and the hold before the FLC phase arms, in
        seconds of AUDIO (see ``after_audio``). Mirrors Swift ``tapCooldown``."""
        return 0.5

    @property
    def capture_window(self) -> float:
        """After the LAST guitar tap, "All taps captured. Processing..." shows for this much AUDIO before
        the taps are averaged (``after_audio``, released at file end). Mirrors Swift
        ``captureWindow``."""
        return 0.2

    # ------------------------------------------------------------------ #
    # number_of_taps — mirrors Swift @Published var numberOfTaps { didSet { … } }
    #
    # A property, not a plain attribute, so the hook runs on EVERY write: there is one way to change
    # the value and it cannot be bypassed, as in Swift (and as with is_measurement_complete).
    #
    # No clamp: Swift's didSet has none, and the spinner already bounds the value 1..10 in the view,
    # exactly as the Swift stepper and the web stepper do.  ``set_tap_num``'s ``max(1, n)`` was a
    # model-layer guard no sibling had.
    _number_of_taps: int = 1

    @property
    def current_decay_time(self) -> "float | None":
        """The ring-out of what is on screen, in seconds, or None: the live measurement during a capture,
        the file's when a measurement is loaded. Mirrors Swift ``@Published var currentDecayTime``."""
        return self._current_decay_time

    @current_decay_time.setter
    def current_decay_time(self, value: "float | None") -> None:
        # Swift's @Published re-renders the Ring-Out box on every change; this emit is Python's.
        if value == self._current_decay_time:
            return
        self._current_decay_time = value
        self.currentDecayTimeChanged.emit(value)

    @property
    def number_of_taps(self) -> int:
        """How many taps to accumulate before freezing.  Mirrors Swift ``numberOfTaps``."""
        return self._number_of_taps

    @number_of_taps.setter
    def number_of_taps(self, value: int) -> None:
        self._number_of_taps = value
        # Mirrors Swift numberOfTaps.didSet: clear the loaded-settings warning once the user
        # deviates from the value the measurement was saved with.
        if (self.show_loaded_settings_warning
                and self._number_of_taps != self.loaded_number_of_taps):
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)
        # Mirrors Swift numberOfTaps.didSet: refresh the prompt while armed and waiting for the
        # FIRST tap of the measurement.
        #
        # `current_tap_count`, not `len(captured_taps)`: the latter is the WITHIN-PHASE buffer,
        # cleared at every material phase completion, so it read zero at the start of every plate
        # phase rather than only at the start of the measurement.  current_tap_count is the
        # cumulative count -- the same field the spinner lock reads, so the guard and the lock
        # agree.  And `_armed_prompt()`, not `_tap_prompt()`: the latter is the GUITAR prompt, and
        # changing Taps at the start of a plate or brace sequence must keep the material prompt
        # ("Ready for fL tap (×3 each for L, C)").
        if self.is_detecting and self.current_tap_count == 0:
            self._set_status_message(self._armed_prompt())

    # ------------------------------------------------------------------ #
    # Status derivation — mirrors Swift TapToneAnalyzer.swift's section of the same name
    # ------------------------------------------------------------------ #

    def _tap_prompt(self) -> str:
        """The guitar resting prompt (post-warmup steady state) — the single source for the
        'Tap the guitar…' / 'Tap the guitar N times…' strings.  Mirrors Swift tapPrompt()."""
        return ("Tap the guitar..." if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times...")

    PAUSED_STATUS = "Detection paused – tap freely, then resume"

    def _armed_prompt(self) -> str:
        """The prompt for an ARMED analyzer — guitar count-aware, material phase-aware.

        Extracted from resume_tap_detection(), which is where this logic lived as the only
        "restore a context-appropriate prompt" in the app. Mirrors Swift armedPrompt().
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        if _tds.measurement_type().is_guitar:
            return self._guitar_loop_status(False)
        return self._material_arm_prompt()

    def _material_arm_prompt(self) -> str:
        """The prompt a material (plate/brace) sequence shows while armed in its CURRENT phase —
        the single source for these strings.

        Three callers, which is the point: start_tap_sequence() (which sets the phase before the
        status), the phase advances in accept_current_phase(), and _armed_prompt().  One set of
        literals for all three, so resuming or changing the tap count never rewords the instruction
        the user is following.

        The fL branch is count-aware, because that is the phase whose prompt names the tap count and
        the only phase where the Taps spinner is still unlocked.  Mirrors Swift materialArmPrompt().
        """
        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        phase = getattr(self, "material_tap_phase", _MTP.NOT_STARTED)
        if phase == _MTP.CAPTURING_CROSS:
            return "Rotate 90° and tap for fC"
        if phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP):
            return "Set up for fLC tap, then tap"
        # CAPTURING_LONGITUDINAL / NOT_STARTED.
        if self.number_of_taps <= 1:
            return "Ready for fL tap"
        if _tds.measurement_type() != _MT.PLATE:
            return f"Ready for fL tap (×{self.number_of_taps})"
        phases = "L, C, FLC" if _tds.measure_flc() else "L, C"
        return f"Ready for fL tap (×{self.number_of_taps} each for {phases})"

    def _status_after_settle(self) -> "str | None":
        """The status to restore when a device/route-change settle ends, or None to leave it alone.

        The status is a function of state, so it is derived rather than chosen from a fixed pair —
        mid-sequence it reflects the taps already captured, and a finished measurement keeps its
        "Analysis complete! N peaks…". It says nothing where the status is a RESULT announcement
        rather than a live prompt, because a completed or loaded measurement's status is not
        re-derivable and must not be thrown away. Mirrors Swift statusAfterSettle().
        """
        from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode as _ADM

        if self.is_measurement_complete:
            return None                      # "Analysis complete…" / "Loaded measurement…"
        if self.display_mode == _ADM.COMPARISON:
            return None                      # an overlay is not a tap prompt
        if self.is_detection_paused:
            return self.PAUSED_STATUS
        if self.is_detecting:
            # A material phase prompt is an INSTRUCTION tied to a transition that already happened
            # -- "Rotate 90deg and tap for fC" -- not a description of the state the analyzer is in.
            # It is therefore not re-derivable here: after a device swap the user has already
            # rotated the plate, and a redo's "Ready for fC tap - tap again" is a different, equally
            # correct string for the same phase.  Preserve it, exactly as a completed measurement's
            # announcement is preserved.  Guitar's prompt IS a function of count and total, both of
            # which the analyzer holds, so it is still derived.
            from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds2
            if not _tds2.measurement_type().is_guitar:
                return None
            return self._armed_prompt()
        return "Ready"

    def _restored_status(self, before: str) -> str:
        """The status to show when a settle ends, given what it said before the settle began.

        The whole decision in one pure function, so every edition can pin it. Mirrors Swift
        restoredStatus(before:).
        """
        derived = self._status_after_settle()
        return derived if derived is not None else before

    def _guitar_loop_status(self, capturing: bool) -> str:
        """Guitar detection-loop status derived from state — the analyzer's equivalent of the
        web setGuitarStatus(engineState).  capturing=False -> resting prompt (count 0) or the
        between-taps '…captured. Tap again…'; capturing=True -> 'Tap n/N capturing…' or, on the
        final tap, 'All taps captured. Processing…'.  (guitar mode keeps current_tap_count ==
        len(captured_taps), so the provisional +1 matches the old len(captured_taps) + 1.)
        Mirrors Swift guitarLoopStatus(capturing:)."""
        if capturing:
            prov = min(self.current_tap_count + 1, self.number_of_taps)
            return (f"Tap {prov}/{self.number_of_taps} capturing..." if prov < self.number_of_taps
                    else "All taps captured. Processing...")
        return (self._tap_prompt() if self.current_tap_count == 0
                else f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again...")

    # ------------------------------------------------------------------ #
    # _set_status_message
    # ------------------------------------------------------------------ #

    def _set_status_message(self, message: str) -> None:
        """Assign status_message and notify the view via statusMessageChanged.

        All writes to status_message must go through this helper so that the
        status bar label is kept in sync.  Mirrors Swift @Published var
        statusMessage: String whose every write auto-fires objectWillChange on
        TapToneAnalyzer, causing SwiftUI to re-render the Text(tap.statusMessage)
        label in TapToneAnalysisView+Controls.swift.

        If an input condition is active -- a dead input, or clipping -- the displayed message is
        overridden with a remediation warning while the analyzer's intended message is preserved in
        _latest_real_status for restoration when the condition clears.  The precedence lives in
        _resolved_status(), shared with _apply_status_overrides().  Mirrors Swift's identical
        override pattern.
        """
        self._latest_real_status = message
        # Resolve through the ONE precedence rule rather than re-deciding here, so a status write
        # while the input is dead keeps the "no audio" warning -- as Swift's $statusMessage sink
        # calls applyStatusOverrides() on every write and keeps it.
        #
        # The emit is UNCONDITIONAL, unlike _apply_status_overrides()'s: Swift's @Published fires on
        # every write regardless of equality, and the view's slot re-applies the status COLOUR,
        # which is a function of detection state rather than of the text.  Suppressing a same-text
        # write would leave the colour stale.
        self.status_message = self._resolved_status()
        self.statusMessageChanged.emit(self.status_message)

    # The device-change transient. Named because two places must agree on it: the write below, and
    # the guard that keeps a second route change from capturing it as the pre-settle status.
    ROUTE_CHANGE_STATUS = "Audio device changed - reinitializing..."

    CLIPPING_WARNING_STATUS = "⚠\ufe0e Input clipping — reduce mic gain"
    DEAD_INPUT_STATUS = "⚠\ufe0e No audio input — check the microphone connection"
    # Shown once the recovery has given up after restarts that failed. Outranks every other input
    # warning. Mirrors Swift `couldNotRestartStatus`.
    COULD_NOT_RESTART_STATUS = ("⚠\ufe0e The microphone could not be restarted — check its connection, "
                                "or choose it again in Settings")
    # Shown while the microphone permission is refused. Outranks every other input warning. Mirrors
    # Swift `microphoneAccessStatus`.
    MICROPHONE_ACCESS_STATUS = "⚠\ufe0e Microphone access required — enable it in Settings, then restart GuitarTap"
    # Shown while the input could not be started. Ranks just below the permission warning. Mirrors
    # Swift `couldNotStartStatus`.
    COULD_NOT_START_STATUS = ("⚠\ufe0e The audio input could not be started — check it, or choose another "
                              "input in Settings")

    def _set_clipping(self, clipping: bool) -> None:
        """Update the input-clipping state and re-render the status message.

        Called from a slot connected to the FFT thread's clippingChanged signal.
        Mirrors Swift TapToneAnalyzer.setClipping(_:).
        """
        if clipping == getattr(self, "is_clipping", False):
            return
        self.is_clipping = clipping
        self._apply_status_overrides()

    def _set_input_appears_dead(self, dead: bool) -> None:
        """Update the dead-input state and re-render the status message.

        Called from a slot connected to the FFT thread's inputAppearsDeadChanged
        signal.  Mirrors Swift's `$inputAppearsDead` sink.
        """
        if dead == getattr(self, "input_appears_dead", False):
            return
        self.input_appears_dead = dead
        self._apply_status_overrides()

    def _set_input_could_not_start(self, failed: bool) -> None:
        """Update whether the input could not be started and re-render the status message.

        Called from a slot connected to the FFT thread's inputCouldNotStartChanged signal. Mirrors
        Swift's `$inputCouldNotStart` sink.
        """
        if failed == getattr(self, "input_could_not_start", False):
            return
        self.input_could_not_start = failed
        self._apply_status_overrides()

    def _set_microphone_permission_denied(self, denied: bool) -> None:
        """Update whether the microphone permission is refused and re-render the status message.

        Called from a slot connected to the FFT thread's microphonePermissionDeniedChanged signal.
        Mirrors Swift's `$microphonePermissionDenied` sink.
        """
        if denied == getattr(self, "microphone_permission_denied", False):
            return
        self.microphone_permission_denied = denied
        self._apply_status_overrides()

    def _set_input_could_not_restart(self, failed: bool) -> None:
        """Update whether the input could not be restarted and re-render the status message.

        Called from a slot connected to the FFT thread's inputCouldNotRestartChanged signal. Mirrors
        Swift's `$inputCouldNotRestart` sink.
        """
        if failed == getattr(self, "input_could_not_restart", False):
            return
        self.input_could_not_restart = failed
        self._apply_status_overrides()

    def _apply_status_overrides(self) -> None:
        """Resolve the displayed status against the active input-condition overrides.

        One place decides precedence — dead input, then clipping, then whatever the
        analyzer last set — so the two overrides cannot fight each other or leave a
        stale warning on screen after its condition clears.  Dead input outranks
        clipping: a dead input cannot also be clipping, and "no audio" is the more
        actionable message.  Mirrors Swift `applyStatusOverrides()`.
        """
        resolved = self._resolved_status()
        if self.status_message != resolved:
            self.status_message = resolved
            self.statusMessageChanged.emit(self.status_message)

    def _resolved_status(self) -> str:
        """The status that SHOULD be displayed: the microphone permission refused, then an input that
        could not be started, then one that could not be restarted, then dead input, then clipping, then
        the analyzer's own.

        The precedence itself, with no assignment and no signal, so the write path and the override
        toggles share one rule instead of each deciding.
        """
        if getattr(self, "microphone_permission_denied", False):
            return self.MICROPHONE_ACCESS_STATUS
        if getattr(self, "input_could_not_start", False):
            return self.COULD_NOT_START_STATUS
        if getattr(self, "input_could_not_restart", False):
            return self.COULD_NOT_RESTART_STATUS
        if getattr(self, "input_appears_dead", False):
            return self.DEAD_INPUT_STATUS
        if getattr(self, "is_clipping", False):
            return self.CLIPPING_WARNING_STATUS
        return self._latest_real_status

    # ------------------------------------------------------------------ #
    # Route change handling — mirrors Swift TapToneAnalyzer.swift's section of the same name
    # ------------------------------------------------------------------ #

    # @parity state/route-change-settle tests=test/notification
    def handle_route_change_restart(self) -> None:
        """Respond to an audio-engine restart triggered by a device or route change.

        Mirrors Swift TapToneAnalyzer.handleRouteChangeRestart():
        - If detection was active: temporarily disable, reset warmup timer,
          wait 3 s for the FFT buffer to refill (covering HALC startup transients),
          then restore is_detecting.
        - If is_measurement_complete (frozen result): leave it untouched.
        - If idle (not detecting): stay idle.
        - If the display was live: blank the spectrum and clear peak annotations
          during the settle period so the view shows nothing rather than stale data.

        The 3-second settle mirrors Swift's fftSettleTime constant (extended from 2 s to absorb
        HALC/CoreAudio startup transients at ~2.5 s): 3 s of audio after the last change, then the
        next FFT frame. A later change inside the settle supersedes this one's restore.
        """
        from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode as _ADM

        gt_log("🔄 TapToneAnalyzer: Handling route change restart - resetting detection state")

        was_detecting = self.detection_state is DetectionState.LISTENING
        # The change that begins a settle decides whether its end re-arms; a later change inside it
        # finds the detector already stood down.
        if self._detecting_before_settle is None:
            self._detecting_before_settle = was_detecting

        # Disable the is_ready_for_detection flag while reinitialising.
        # Mirrors Swift: isReadyForDetection = false, then IDLE only if it was listening —
        # a sequence paused before the route change must still be paused after it.
        self.is_ready_for_detection = False
        if was_detecting:
            self.detection_state = DetectionState.IDLE

        # Reset the warmup timer so the new engine session starts cleanly.
        # Mirrors Swift: warmupStartAudioTime = fftAnalyzer.audioElapsed.
        self.warmup_start_audio_time = self._audio_now()

        # Pre-set is_above_threshold = True so the first FFT frame does not fire a
        # false rising edge.  The actual value is corrected after the settle delay.
        # Mirrors Swift: isAboveThreshold = true.
        self.is_above_threshold = True

        # Blank only if a LIVE spectrum is on screen. `display_mode == LIVE` is not that test: a
        # finished measurement is still LIVE. is_measurement_complete is the field that says whether
        # what you are looking at is a result. Mirrors Swift wasShowingLive / is_settling.
        was_showing_live = (not self.is_measurement_complete
                            and self.display_mode != _ADM.COMPARISON)
        if was_showing_live:
            # The flag is the whole mechanism — no display_mode write, so a completed or loaded
            # measurement is untouched.
            self.is_settling = True
            self.all_peaks = []
            self.identified_modes = []
            self.peaks.peaksChanged.emit([])

        # Remember what the status said BEFORE the transient replaces it. When the settle ends,
        # _status_after_settle() returns None for the states whose status is a result announcement
        # rather than a prompt — and "leave it alone" means restoring THIS, not leaving the
        # transient up.
        #
        # _latest_real_status, NOT status_message: the latter is the OVERRIDE-RESOLVED string, and
        # during a route change while the input is clipping or dead it holds the warning sentinel;
        # fed back through _set_status_message() it would be stored AS the real status, so clearing
        # the condition would restore the warning.  The override layer re-resolves on its own, so
        # the real status is what has to survive the settle.
        #
        # Guarded so a route change during a settle does not capture the transient itself: a
        # captured ROUTE_CHANGE_STATUS would be put back by _restored_status() for every state whose
        # status is not re-derivable — a completed measurement, a material phase prompt — and stay
        # up until something else writes a status. The settle's end clears it, so a value already
        # here means a settle is in progress and the change that began it captured the real status.
        if self._status_before_settle is None:
            self._status_before_settle = self._latest_real_status
        # Mirrors Swift: statusMessage = "Audio device changed - reinitializing...".
        self._set_status_message(self.ROUTE_CHANGE_STATUS)

        # Wait for the FFT pipeline to fill with valid post-restart data
        # (~1.36 s for 65 536 samples at 48 kHz).  Use 3 s to absorb HALC/CoreAudio
        # startup transients that can arrive at ~2.5 s on the engine-recovery path. On the AUDIO
        # clock: what has to pass is that much audio from the new device. A later change supersedes
        # this one's restore, so the settle ends 3 s after the last change.
        # Mirrors Swift: fftSettleTime = 3.0 / afterAudio.
        self._route_change_generation += 1
        generation = self._route_change_generation

        def _settled() -> None:
            # Mirrors Swift scheduleRouteChangeSettleEnd: a later change supersedes this one; and if the
            # engine is restarting again when the settle is due — a retry after a start that failed — the
            # settle waits that much audio from the restarted engine instead of ending without it, so it
            # cannot be left waiting for good.
            if generation != self._route_change_generation or self.mic is None:
                return
            if self.mic.is_stopped:
                self.after_audio(3.0, _settled)
                return
            # Wait for the next FFT frame before re-anchoring detection and unfreezing the display,
            # so both happen on the first frame the user sees. Mirrors Swift afterNextFrame.
            self.after_next_frame(
                lambda peak_db: self._restore_detection_after_route_change(generation, was_showing_live, peak_db))

        self.after_audio(3.0, _settled)

    def _restore_detection_after_route_change(self, generation: int, was_live: bool, peak_db: float) -> None:
        """End the device-change settle on the first FFT frame after it: re-anchor the level latch from
        that frame's peak, unblank a live chart, set readiness, put detection back to listening if the
        change that began the settle found it listening, and restore the status.

        The body of Swift's ``afterNextFrame`` closure in ``handleRouteChangeRestart()``; a named
        method only so it can be read on its own — it should not be called from anywhere else.
        """
        if generation != self._route_change_generation:
            return

        # Re-anchor is_above_threshold to the frame's peak. Mirrors Swift:
        # isAboveThreshold = (peakMagnitude > tapDetectionThreshold).
        self.is_above_threshold = peak_db > self.tap_detection_threshold

        if was_live:
            self.is_settling = False

        self.is_ready_for_detection = True

        # Derive the status from the state we are now in, and leave it alone where it is a result
        # announcement.
        if self._detecting_before_settle:
            self.detection_state = DetectionState.LISTENING
        self._detecting_before_settle = None
        self._set_status_message(self._restored_status(self._status_before_settle or "Ready"))
        self._status_before_settle = None

        gt_log(f"🔄 TapToneAnalyzer: Detection re-enabled after route change "
               f"(current level: {peak_db} dB, threshold: {self.tap_detection_threshold} dB, "
               f"above threshold: {self.is_above_threshold})")

    # ------------------------------------------------------------------ #
    # is_measurement_complete — mirrors Swift @Published var isMeasurementComplete
    # ------------------------------------------------------------------ #

    # Class-level default so the getter is safe for any read that reaches the instance
    # before __init__ assigns the backing field.
    _is_measurement_complete: bool = False

    @property
    def is_measurement_complete(self) -> bool:
        """Whether a measurement is frozen and complete.

        Mirrors Swift ``TapToneAnalyzer.isMeasurementComplete``.  The setter carries the two
        actions Swift performs in its ``didSet`` and nothing else.  The reset work that
        accompanies *leaving* the complete state is not here: Swift does it in
        ``startTapSequence()``, and so does this edition.

        The ``measurementComplete`` signal is deliberately NOT emitted from the setter.
        Swift's notification comes from ``@Published``/``objectWillChange``, which SwiftUI
        coalesces to the end of the run loop, so the view is never told until the enclosing
        method has finished populating state.  A Qt signal fires synchronously, so emitting
        here would hand the view a half-built model at the two sites that set the flag early
        on purpose — ``process_multiple_taps()`` and ``_load_measurement_body()``, both of
        which emit once all state is restored.  Callers emit at the point Swift renders.
        """
        return self._is_measurement_complete

    @is_measurement_complete.setter
    def is_measurement_complete(self, value: bool) -> None:
        old_value = self._is_measurement_complete
        self._is_measurement_complete = value
        if not value:
            return

        # Mirrors Swift didSet: a completed measurement clears the loaded-settings warning,
        # so the user knows their loaded settings produced this result.  load_measurement()
        # raises that warning *after* setting complete, so a load's own warning survives —
        # the same ordering dependency Swift has (isMeasurementComplete = true at line 709,
        # showLoadedSettingsWarning = true at line 833).
        if self.show_loaded_settings_warning:
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)

        # Mirrors Swift didSet: seed Store B from the Settings defaults at the material
        # measurement-complete freeze — the one and only seed hook (nothing on New Tap,
        # type-change or Cancel).  Guarded to the transition (!oldValue), to material types,
        # and to not-loading (a load seeds Store B from the snapshot instead).
        if old_value or self.is_loading_measurement:
            return
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        if _tds.measurement_type().is_guitar:
            return
        from guitar_tap.models.material_measurement_inputs import MaterialMeasurementInputs
        self.material_inputs = MaterialMeasurementInputs.from_settings(_tds.measurement_type())

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
    def for_testing(cls, sample_rate: int = 48000, wall_clock: "WallClock | None" = None) -> "TapToneAnalyzer":
        """Create a TapToneAnalyzer wired for file-playback testing.

        The returned instance has the full pipeline connected (signal wiring, the engine's
        ``audio_frame_handler``) but no audio hardware.
        Tests play a file through it with ``tests/playback_support.play_file_and_wait``,
        which runs the app's own ``play_file``.

        The FFT size is a constant inside ``RealtimeFFTAnalyzer`` (65 536);
        it is not configurable per-instance.

        Mirrors Swift ``TapToneAnalyzer.forTesting()``.

        Args:
            sample_rate: Sample rate in Hz. Default 48000.
            wall_clock: The analyzer's wall clock — the system's when None.
        """
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer as _Mic

        # 1. Create the hardware-free FFT engine.
        mic = _Mic.for_testing(sample_rate=sample_rate)

        # 2. Construct the analyzer — __init__ sets all state defaults,
        #    computes the frequency axis, and wires pipeline signals.
        return cls(fft_analyzer=mic, wall_clock=wall_clock)

    # ------------------------------------------------------------------ #
    # _wire_pipeline_signals — shared by start() and for_testing()
    # ------------------------------------------------------------------ #

    def _wire_pipeline_signals(self) -> None:
        """Connect this analyzer to the mic's pipeline. Called once, from ``__init__``.

        A handler on the mic: ``audio_frame_handler``, which takes every chunk on the main thread, in order.
        Signals on the processing thread object: ``inputAppearsDeadChanged`` and the rest; on the mic's input
        level (``mic.level``): ``clippingChanged``; on the mic's frame (``mic.frame``): ``frameChanged``.

        The signals are connected once. The processing thread object and the input level are created
        with the mic and never replaced, so these connections hold for the whole run. A second ``connect()`` on it would
        deliver every emission twice.

        Mirrors Swift ``TapToneAnalyzer.setupSubscriptions()``.
        """
        # ── Every chunk, on the main thread, in order: the pre-roll, the capture, the clock, detection ──
        self.mic.audio_frame_handler = self._on_audio_frame
        _slack_probe.start()

        # ── Input-clipping signal (Qt — UI only) ────────────────────────
        # Swift: fftAnalyzer.level.$isClipping sink.
        self.mic.level.clippingChanged.connect(self._set_clipping)
        self.mic.proc_thread.inputAppearsDeadChanged.connect(self._set_input_appears_dead)
        self.mic.proc_thread.inputCouldNotRestartChanged.connect(self._set_input_could_not_restart)
        self.mic.proc_thread.microphonePermissionDeniedChanged.connect(self._set_microphone_permission_denied)
        self.mic.proc_thread.inputCouldNotStartChanged.connect(self._set_input_could_not_start)
        # The user granted the permission in the system's request: the full start, as Swift's
        # onPermissionGranted. A failure is the engine's to report (its flag) or the log's.
        self.mic.on_permission_granted = self._start_after_permission_granted

        # ── Pre-mic-restart handler ─────────────────────────────────────
        self.mic._on_pre_mic_restart = self._flush_gated_capture_on_file_end

        # ── Post-engine-stop handler ──────────────────────────────────
        # Clear the pre-roll after the engine stops, so mic noise that leaked in between
        # start_tap_sequence (which clears it) and the engine stop is flushed; a mic chunk still queued
        # for the main thread is dropped when it arrives. Mirrors Swift postEngineStopHandler.
        def _clear_pre_roll():
            self._pre_roll_buf = []
        self.mic._on_post_engine_stop = _clear_pre_roll

        # ── FFT frame → peak analysis: the frame's signal ────────────────
        # Connected to a method of this object, so it runs on the main thread, as Swift's analyzer takes
        # frames from fft.frame through a Combine sink `.receive(on: DispatchQueue.main)`.
        # level.inputLevelChanged is not connected here: it is the UI's copy of the level (the threshold
        # meter).
        self.mic.frame.frameChanged.connect(self._on_live_frame)

    # The pre-roll buffer starts empty (cleared by start_tap_sequence) and fills
    # with real audio as chunks arrive. It is not pre-filled with zeros, which
    # would dilute the gated capture signal by ~50% (~6 dB of spectral magnitude).

    def _on_audio_frame(self, samples, level_db: float, audio_time: float) -> None:
        """The mic's ``audio_frame_handler``: one chunk, on the main thread, timed by the slack probe when it is
        on."""
        with _slack_probe.timed("main/chunk"):
            self.process_audio_frame(samples, level_db, audio_time, float(self.mic.rate))

    def process_audio_frame(self, samples, level_db: float, audio_time: float, sample_rate: float) -> None:
        """One chunk, on the main thread, in order — the per-chunk entry, as the web's ``processAudioFrame``:
        its samples into the pre-roll, the session recording and any capture under way (a capture that fills
        is finished there and then), then its level to the detector (``_on_chunk_level``). Mirrors Swift
        ``processAudioFrame(_:levelDB:audioTime:sampleRate:)``."""
        _slack_probe.set_chunk_period(len(samples), sample_rate)
        with _slack_probe.timed("accumulate"):
            self._accumulate_gated_samples(samples, sample_rate)
        self._on_chunk_level(level_db, audio_time)

    def _on_chunk_level(self, level_db: float, audio_time: float) -> None:
        """One chunk's level, on the main thread — the detector's part of ``process_audio_frame``, after the
        chunk's samples have fed the capture. Tests feed levels through it: Swift ``onChunkLevel``."""
        self._on_rms_level_changed(level_db, audio_time)

    # ------------------------------------------------------------------ #
    # tap_detection_threshold — mirrors Swift @Published var tapDetectionThreshold
    # ------------------------------------------------------------------ #

    @property
    def tap_detection_threshold(self) -> float:
        """Rising-edge threshold (dBFS) for the main-thread tap detector.

        Mirrors Swift ``TapToneAnalyzer.tapDetectionThreshold`` and its ``didSet``: setting it
        saves it and clears the loaded-settings warning when it moves off the loaded value.
        """
        return self._tap_detection_threshold

    @tap_detection_threshold.setter
    def tap_detection_threshold(self, value: float) -> None:
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        self._tap_detection_threshold = float(value)
        _tds.set_tap_detection_threshold(self._tap_detection_threshold)
        # A threshold moved off the loaded measurement's value ends the loaded-settings warning.
        if (getattr(self, "show_loaded_settings_warning", False)
                and self._tap_detection_threshold != self.loaded_tap_detection_threshold):
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)

    # ── Durable peak set + display projection ──────────────────────────────
    @property
    def all_peaks(self) -> list:
        """The DURABLE full peak set — the source of truth for peak identity.

        Peak identity lives here and changes ONLY when the spectrum changes (a new
        tap, freeze, or an explicit Re-analyze) — never because the display changed.
        Per-peak state (selection, mode overrides, annotation offsets) is keyed to
        these identities, which is what makes it durable across a Peak Min move.
        Mirrors Swift `allPeaks` (@Published; didSet -> refreshDisplayedPeaks()).
        """
        return self.peaks.all_peaks

    @all_peaks.setter
    def all_peaks(self, value: list) -> None:
        self.peaks.all_peaks = value
        # Mirrors Swift allPeaks.didSet — re-project the display set. Assigning
        # all_peaks is the ONLY way peaks_above_peak_min should change.
        self.refresh_displayed_peaks()

    @property
    def peaks_above_peak_min(self) -> list:
        """``all_peaks`` with Peak Min applied — held in ``peaks``. Mirrors Swift ``peaksAbovePeakMin``."""
        return self.peaks.peaks_above_peak_min

    @peaks_above_peak_min.setter
    def peaks_above_peak_min(self, value: list) -> None:
        self.peaks.peaks_above_peak_min = value

    @property
    def identified_modes(self) -> list:
        """Each peak with its mode — held in ``peaks``. Mirrors Swift ``identifiedModes``."""
        return self.peaks.identified_modes

    @identified_modes.setter
    def identified_modes(self, value: list) -> None:
        self.peaks.identified_modes = value

    @property
    def selected_peak_ids(self) -> set:
        """The peaks marked as significant — held in ``peaks``. Mirrors Swift ``selectedPeakIDs``."""
        return self.peaks.selected_peak_ids

    @selected_peak_ids.setter
    def selected_peak_ids(self, value: set) -> None:
        self.peaks.selected_peak_ids = value

    def refresh_displayed_peaks(self) -> None:
        """Recompute `peaks_above_peak_min` (the Peak-Min display projection) from
        `all_peaks`. Called when the peak set or Peak Min changes — a cheap filter,
        no detection. Hands back the SAME peak objects, so filtering can never
        disturb identity. Peak Min is guitar-only, so material shows all_peaks
        unfiltered. Mirrors Swift `refreshDisplayedPeaks()`.
        """
        if self._tds.measurement_type().is_guitar:
            self.peaks_above_peak_min = [
                p for p in self.peaks.all_peaks if p.magnitude >= self.peak_min_threshold
            ]
        else:
            self.peaks_above_peak_min = list(self.peaks.all_peaks)

    @property
    def selected_peaks(self) -> list:
        """The user's selected peaks, resolved over the DURABLE set — mirrors Swift
        `selectedPeaks { allPeaks.filter { selectedPeakIDs.contains($0.id) } }`. Selection is a
        fact about the measurement, not about what is on screen: a selected peak may legitimately
        sit below Peak Min, so resolving over `peaks_above_peak_min` (the display projection) would
        silently drop it from every derived value (e.g. the multi-tap averaged Air/Top/Back row).
        """
        return [p for p in self.peaks.all_peaks if p.id in self.selected_peak_ids]

    @property
    def peak_min_threshold(self) -> float:
        """Minimum magnitude (dBFS) for a peak to be displayed.

        A DISPLAY control: assigning it saves it and re-projects `peaks_above_peak_min` from the
        durable `all_peaks` — no re-detection, no re-classification. Mirrors Swift
        `@Published var peakMinThreshold { didSet { save; refreshDisplayedPeaks() } }`. The view's
        `peaksChanged` emit stays at the call sites: Python's `peaks_above_peak_min` is not
        signal-backed like Swift's `@Published peaksAbovePeakMin`, so emitting here would fire
        prematurely during capture/load.
        """
        return self._peak_min_threshold

    @peak_min_threshold.setter
    def peak_min_threshold(self, value: float) -> None:
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        self._peak_min_threshold = value
        # Mirrors Swift peakMinThreshold.didSet: save, then refreshDisplayedPeaks().
        _tds.set_peak_min_threshold(value)
        self.refresh_displayed_peaks()

    # The identified peak of each material phase, announced on every write. Mirrors Swift's
    # @Published selectedLongitudinalPeak / selectedCrossPeak / selectedFlcPeak.

    @property
    def selected_longitudinal_peak(self):
        return self._selected_longitudinal_peak

    @selected_longitudinal_peak.setter
    def selected_longitudinal_peak(self, peak) -> None:
        self._selected_longitudinal_peak = peak
        self.selectedLongitudinalPeakChanged.emit(peak)

    @property
    def selected_cross_peak(self):
        return self._selected_cross_peak

    @selected_cross_peak.setter
    def selected_cross_peak(self, peak) -> None:
        self._selected_cross_peak = peak
        self.selectedCrossPeakChanged.emit(peak)

    @property
    def selected_flc_peak(self):
        return self._selected_flc_peak

    @selected_flc_peak.setter
    def selected_flc_peak(self, peak) -> None:
        self._selected_flc_peak = peak
        self.selectedFlcPeakChanged.emit(peak)

    @property
    def detection_state(self) -> DetectionState:
        """Whether the detector is listening, paused mid-sequence, or neither.

        Mirrors Swift `detectionState`.

        One value rather than the ``is_detecting`` / ``is_detection_paused`` pair it
        replaced: that pair could express "detecting AND paused", and every site touching
        either flag had to keep them consistent by hand. Both remain available as
        read-only properties below.
        """
        return self._detection_state

    @detection_state.setter
    def detection_state(self, value: DetectionState) -> None:
        old = self._detection_state
        # Nothing to do for a same-value assignment: re-asserting the state the detector is
        # already in must not run the transition's work again. Mirrors Swift's
        # `guard oldValue != detectionState`.
        if value is old:
            return
        self._detection_state = value

        # Swift's `detectionState` is @Published, so every view bound to it re-evaluates on ANY
        # change — that is how the status bar's tap-count label tracks it. Python has no such
        # binding: without this signal the view could only sample the state inside some other
        # slot (set_tap_count, driven by tapCountChanged), which meant a state change alone
        # never refreshed anything — the label's visibility and text both went stale.
        self.detectionStateChanged.emit(value)

    @property
    def is_detecting(self) -> bool:
        """Whether the analyzer is actively listening for taps.

        False after stop(), cancel_tap_sequence(), or while paused.
        Mirrors Swift `isDetecting`.
        """
        return self._detection_state is DetectionState.LISTENING

    @property
    def is_ready_for_detection(self) -> bool:
        """False during the brief period after a route change while the engine reinitialises.

        The New Tap button is disabled while this is False. Mirrors Swift `isReadyForDetection`;
        setting it emits readyForDetectionChanged so the view can re-evaluate, which is what
        Swift gets for free from @Published.
        """
        return self._is_ready_for_detection

    @is_ready_for_detection.setter
    def is_ready_for_detection(self, value: bool) -> None:
        if value == self._is_ready_for_detection:
            return
        self._is_ready_for_detection = value
        self.readyForDetectionChanged.emit(value)

    @property
    def is_detection_paused(self) -> bool:
        """Whether the tap sequence is paused (spectrum stays live, detection is off).

        Distinct from DetectionState.IDLE because pause preserves the in-progress tap
        count, while a full stop resets it. Mirrors Swift `isDetectionPaused`.
        """
        return self._detection_state is DetectionState.PAUSED

    def attach_to_view(
        self,
        parent_widget,
    ) -> None:
        """The Qt wiring that needs the view's widget, which Swift has no counterpart of.

        Called by FftCanvas after construction, before ``start``. The RealtimeFFTAnalyzer
        (self.mic) and pipeline signals are already wired by ``__init__``. This makes the
        rest, which needs the parent widget:
          - QObject re-parenting
          - Hotplug signal wiring
          - Calibration state

        Tests never call this — ``for_testing()`` provides everything
        ``__init__`` needs.

        Args:
            parent_widget: The FftCanvas (QObject parent).
        """
        from guitar_tap.models import microphone_calibration as _mc_mod
        from guitar_tap.models.audio_backend import sd as _sd

        self._sd = _sd
        self._mc_mod = _mc_mod

        # Re-parent this QObject to the view widget now that we have it.
        self.setParent(parent_widget)
        self.mic.proc_thread.setParent(self)

        # Wire the hotplug signal now that the Qt object hierarchy is valid.
        self._devicesRefreshed.connect(self._on_devices_refreshed)

        # Wire the device-change callbacks on the mic. These were deferred from mic construction
        # (passed as None) because self._devicesRefreshed requires the Qt signal system to be wired,
        # which needs setParent() first.
        self.mic._on_devices_changed = self._devicesRefreshed.emit
        self.mic._on_stream_reopened = self._on_stream_reopened

        # ── Calibration ───────────────────────────────────────────────────
        # The engine applied the selected device's calibration when it selected the device.
        audio_device = self.mic._selected_input_device
        self._calibration_device_name = audio_device.name if audio_device else ""

        # Stamp the cooldown timer so the spurious CM_Register_Notification that
        # Windows fires when Pa_OpenStream is called during init (or when the CM
        # monitor registers) does not immediately trigger _on_devices_refreshed
        # and switch away from the saved/selected device.
        import time as _time_mod
        self._devices_refresh_last_t = _time_mod.monotonic()

        # Register the hot-plug monitor now that _on_devices_changed is wired.  The
        # mic's __init__ already called _start_hotplug_monitor(), but at that point
        # the callback was still None (deferred from mic construction), so it bailed
        # at the `if self._on_devices_changed is None: return` guard and the OS
        # listener was never installed.  Registering here — once, after wiring — is
        # what actually enables device connect/disconnect detection on macOS,
        # Windows, and Linux.
        self.mic._start_hotplug_monitor()

    def load_persisted_measurements(self) -> None:
        """Load the saved measurements. Mirrors Swift ``loadPersistedMeasurements()``, called from init.

        Entries that cannot be read are left out: the file is first copied aside as it was —
        ``_keep_copy_of_library`` — and the library is then saved without them. A file that cannot be
        read at all is set aside — ``_set_aside_unreadable_library``."""
        from guitar_tap.views.tap_analysis_results_view import decode_library, measurements_file

        path = measurements_file()
        if not os.path.exists(path):
            gt_log("📂 No persisted measurements file found")
            self.saved_measurements = []
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                library = decode_library(f.read())
        except Exception as exc:
            gt_log(f"❌ Failed to load persisted measurements: {exc}")
            self.saved_measurements = []
            self._set_aside_unreadable_library(path)
            return
        self.saved_measurements = library.measurements
        gt_log(f"📂 Loaded {len(self.saved_measurements)} persisted measurements")

        if library.unreadable:
            gt_log(f"❌ {len(library.unreadable)} persisted measurement(s) could not be read: {library.unreadable}")
            self._keep_copy_of_library(path, len(library.unreadable))
            self._persist_measurements()
            return

        # Files written before the find_peaks duplicate fix carry one bit-identical twin per
        # capture; decoding repairs them in memory. The library is ours, so write the corrected
        # form back immediately — one save, once, and the corruption is gone. A .guitartap
        # opened from disk is NOT rewritten this way; it is healed on every read until the user
        # chooses to save it. Mirrors Swift loadPersistedMeasurements().
        healed_count = sum(1 for m in self.saved_measurements if getattr(m, "was_healed", False))
        if healed_count:
            gt_log(
                f"🩹 Healed duplicate peaks in {healed_count} saved measurement(s) — forcing a save"
            )
            self._persist_measurements()

    def _keep_copy_of_library(self, path: str, unreadable_count: int) -> None:
        """The library holds entries that cannot be read. Before it is saved without them, it is copied —
        ``<name>-unreadable-<date and time>.json`` beside itself, as it was — and the user is told once
        how many were left out and where the copy is. If it cannot be copied, the library is not
        written this session, so the only copy of those entries is not replaced. Mirrors Swift
        ``keepCopyOfLibrary(at:unreadableCount:)``."""
        import shutil

        kept = self._unreadable_library_path(path)
        count = "1 saved measurement" if unreadable_count == 1 else f"{unreadable_count} saved measurements"
        was = "was" if unreadable_count == 1 else "were"
        try:
            shutil.copyfile(path, kept)
            gt_log(f"📂 Library with unreadable entries copied to {kept}")
            self.library_load_failure = (
                f"{count} could not be read and {was} removed from the list. The original file was kept as "
                f"{os.path.basename(kept)} {self._where_to_find(kept)}.")
        except OSError as exc:
            gt_log(f"❌ Could not copy the library aside: {exc} — the library is not written this session")
            self.is_library_write_blocked = True
            self.library_load_failure = (
                f"{count} could not be read and {was} left out of the list. The file, {os.path.basename(path)}, "
                f"was left as it is {self._where_to_find(path)}, and new measurements will not be saved to it "
                "this session.")

    @staticmethod
    def _unreadable_library_path(path: str) -> str:
        """Where an unreadable library, or a copy of one, is kept: ``<name>-unreadable-<date and
        time>.json`` beside it. Mirrors Swift ``unreadableLibraryURL(for:)``."""
        stem = os.path.splitext(os.path.basename(path))[0]
        return os.path.join(os.path.dirname(path),
                            f"{stem}-unreadable-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")

    @staticmethod
    def _where_to_find(path: str) -> str:
        """Where a file of the library's is, in the words a user finds it by: its folder's path — from
        the home folder on macOS and Linux, whole on Windows, where Explorer does not read ``~``.
        Mirrors Swift ``whereToFind(_:)``."""
        folder = os.path.dirname(path)
        home = os.path.expanduser("~")
        if sys.platform != "win32" and folder.startswith(home + os.sep):
            folder = "~" + folder[len(home):]
        return f"in GuitarTap's data folder, {folder}"

    def _set_aside_unreadable_library(self, path: str) -> None:
        """The library could not be read. It is kept — renamed ``<name>-unreadable-<date and time>.json``
        beside itself — so no save writes over it, the library starts empty, and the user is told once
        where it is: fixing the file and renaming it back restores it. If it cannot be renamed it stays
        where it is and the library is not written this session. Mirrors Swift
        ``setAsideUnreadableLibrary(at:)``."""
        kept = self._unreadable_library_path(path)
        try:
            os.rename(path, kept)
            gt_log(f"📂 Unreadable library kept as {kept}")
            self.library_load_failure = self._unreadable_library_message(kept, path)
        except OSError as exc:
            gt_log(f"❌ Could not keep the unreadable library aside: {exc} — the library is not written this session")
            self.is_library_write_blocked = True
            self.library_load_failure = self._unreadable_library_message(path, path)

    @staticmethod
    def _unreadable_library_message(kept: str, original: str) -> str:
        """The message for a library that could not be read and was kept as *kept*. Mirrors Swift
        ``unreadableLibraryMessage(keptAs:original:)``."""
        if kept == original:
            return (f"Your saved measurements could not be read. The file, {os.path.basename(kept)}, was left "
                    f"as it is {TapToneAnalyzer._where_to_find(kept)}, and new measurements will not be saved "
                    "to it until it can be read.")
        return (f"Your saved measurements could not be read, so the library starts empty. The file was kept "
                f"as {os.path.basename(kept)} {TapToneAnalyzer._where_to_find(kept)} — fix it and rename it "
                f"back to {os.path.basename(original)} to restore it.")

    def _start_after_permission_granted(self) -> None:
        """The start the engine resumes once the user grants the permission. Mirrors Swift's
        ``onPermissionGranted`` closure."""
        try:
            self.start()
        except Exception as exc:  # noqa: BLE001 — a start failure here has no caller to report it
            gt_log(f"❌ Start after the permission was granted failed: {exc}")

    def start(self) -> None:
        """Start the engine, anchor the warm-up and, one main-loop pass later, make the guarded
        auto-start. Mirrors Swift ``start()``.

        The engine is the processing thread and the input stream; each is started only if it is not
        running already, the thread first, so a file can still be played when no input opens. Raises
        what the stream's start raises (no input device, or one that cannot be opened), for the view
        to report, as Swift's ``start()`` throws.
        """
        if not self.mic.proc_thread.isRunning():
            self.mic.proc_thread.reset_state()
            self.mic.proc_thread.start()
        if self.mic.stream is None or not self.mic.stream.active:
            self.mic.start()
        self.warmup_start_audio_time = self._audio_now()  # begin the warm-up period for the new session
        # Evaluate the auto-start guard on the main loop after pending state changes have settled.
        self._main_async_after(0, self.auto_start_tap_sequence)

    def auto_start_tap_sequence(self) -> None:
        """What the engine coming up does: start a tap sequence — only when nothing is under way or on
        screen (not detecting, not complete, not paused, no taps taken, no comparison shown), so an engine
        start never replaces a measurement or a comparison. Through ``request_start_tap_sequence``, for its
        dump-folder check. Mirrors Swift ``autoStartTapSequence()``."""
        if (not self.is_detecting and not self.is_measurement_complete
                and not self.is_detection_paused and self.current_tap_count == 0
                and self.display_mode != AnalysisDisplayMode.COMPARISON):
            self.request_start_tap_sequence()

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
        x_axis = _np.arange(0, self.mic.h_fft_size)
        self.freq = x_axis * self.mic.rate / self.mic.fft_size

    # ------------------------------------------------------------------ #
    # display_mode property — kept in sync with FftCanvas.display_mode
    # ------------------------------------------------------------------ #

    @property
    def display_mode(self):
        """Current spectrum display mode (live vs. captured/frozen).

        Kept in sync with `FftCanvas.display_mode`; the setter emits
        `displayModeChanged`. Mirrors Swift `displayMode`.
        """
        return self._display_mode

    @display_mode.setter
    def display_mode(self, value) -> None:
        self._display_mode = value
        self.displayModeChanged.emit(value)

    @property
    def longitudinal_spectrum(self):
        """The longitudinal phase's averaged spectrum, (magnitudes, frequencies), or None. Mirrors Swift
        ``longitudinalSpectrum``."""
        return self._longitudinal_spectrum

    @longitudinal_spectrum.setter
    def longitudinal_spectrum(self, value) -> None:
        self._longitudinal_spectrum = value
        self.phaseSpectraChanged.emit()

    @property
    def cross_spectrum(self):
        """The cross-grain phase's averaged spectrum, (magnitudes, frequencies), or None. Mirrors Swift
        ``crossSpectrum``."""
        return self._cross_spectrum

    @cross_spectrum.setter
    def cross_spectrum(self, value) -> None:
        self._cross_spectrum = value
        self.phaseSpectraChanged.emit()

    @property
    def flc_spectrum(self):
        """The FLC phase's averaged spectrum, (magnitudes, frequencies), or None. Mirrors Swift
        ``flcSpectrum``."""
        return self._flc_spectrum

    @flc_spectrum.setter
    def flc_spectrum(self, value) -> None:
        self._flc_spectrum = value
        self.phaseSpectraChanged.emit()

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

    @property
    def compared_span(self) -> "tuple[float, float, float, float] | None":
        """The compared span while a comparison measurement is shown — the span of the compared
        measurements' saved views (min Hz, max Hz, min dB, max dB), the range a new comparison opens at — else
        None. The chart's menu resets to it ("Comparison Range"). Not a saved comparison's own range
        (``TapToneMeasurement.comparison_range``), the view it was saved with. Mirrors Swift ``comparedSpan``."""
        if not self.is_saved_measurement_comparison:
            return None
        from .display_range import spanning_range
        return spanning_range(self.comparison_snapshots)

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

        For the auto case, delegates to ``self.peak_mode(peak)``, which reads ``identified_modes``
        (populated by ``classify_all`` with all peaks together) and returns UNKNOWN for a peak that
        has no entry — identical to Swift ``peakMode(for:)``.  Returns ``mode.display_name``
        (human-readable), not ``mode.value`` (internal enum string).
        """
        override = self.peak_mode_overrides.get(peak.id)
        if override:
            return override
        # Mirrors Swift .auto case: peakMode(for: peak).displayName
        return self.peak_mode(peak).display_name

    def auto_detected_mode(self, peak) -> "GuitarMode":
        """The mode this peak would carry with **no** override — the mode a "Reset to Auto-Detected"
        would restore it to.

        Deliberately override-BLIND: it reads the auto-classification (``identified_modes``) and
        never consults ``peak_mode_overrides``. This is exactly the value the reset menu item should
        name — the target of the reset, not the current label. ``UNKNOWN`` is a legitimate result (a
        peak in no band, or a material peak, which has no guitar mode) and is shown as such — so a
        peak with no entry resolves to it rather than being classified alone. See ``peak_mode``.

        Mirrors Swift ``autoDetectedMode(for:)``.
        """
        from .guitar_mode import GuitarMode
        for entry in self.identified_modes:
            if entry.get("peak") and entry["peak"].id == peak.id:
                return entry["mode"]
        return GuitarMode.UNKNOWN

    def set_mode_override(self, mode: str, peak_id: str) -> None:
        """Give a peak a manual mode label. ``reset_mode_override`` removes one.

        Mirrors Swift ``setModeOverride(_:for:)``.
        """
        self.peak_mode_overrides[peak_id] = mode
        # A mode change on an ALREADY-SELECTED peak can leave two definitive peaks in one mode; that
        # is the only way an override touches selection. Relabelling an unselected peak just adds a
        # candidate (enforce early-returns for it). Mirrors Swift setModeOverride.
        self.enforce_definitive_mode_uniqueness(preferring=peak_id)

    def has_manual_override(self, peak_id: str) -> bool:
        """Return ``True`` when the peak has a manually-assigned (non-auto) mode label.

        Mirrors Swift ``hasManualOverride(for peakID: UUID) -> Bool``.
        """
        return peak_id in self.peak_mode_overrides

    @property
    def overridden_peak_ids(self) -> set:
        """The ids of every peak the user has given a manual mode label.

        Passed to ``GuitarMode.peaks_in_display_range`` so a static, pure function can apply the
        same unknown-mode rule the analyzer uses, without an analyzer reference at the call site.
        Python's ``peak_mode_overrides`` stores only user-assigned label strings (every entry IS an
        assignment), so this is the equivalent of Swift's ``.assigned``-case ``compactMap`` — and the
        same set ``has_manual_override`` tests membership in.

        Mirrors Swift ``TapToneAnalyzer.overriddenPeakIDs``.
        """
        return set(self.peak_mode_overrides.keys())

    def is_unknown(self, peak) -> bool:
        """Whether *peak* counts as **unknown** for the Show Unknown Modes filter.

        The single rule behind all three display surfaces — the results panel, the chart dot layer
        and the annotation badges. A peak is unknown only when auto-classification failed to place it
        in any mode band **and** the user has not named it. **Naming a peak makes it known**: a user
        who labels a peak "Wolf note" has identified it, and hiding it would discard their own work.

        Equivalent to the old positional test ``GuitarMode.is_known(frequency)`` for every peak
        *without* an override, because ``GuitarMode.classify_all`` falls back to a per-frequency
        lookup for peaks its one-per-mode claiming pass did not take. The two differ only under a user
        override — which is exactly the case this predicate exists to fix.

        Mirrors Swift ``TapToneAnalyzer.isUnknown(_:)``.
        """
        from .guitar_mode import GuitarMode
        return (
            self.peak_mode(peak) == GuitarMode.UNKNOWN
            and not self.has_manual_override(peak.id)
        )

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
        was_selected = peak_id in current
        if was_selected:
            current.discard(peak_id)
        else:
            current.add(peak_id)
        self.selected_peak_ids = current
        if not was_selected:
            # Selecting a peak whose mode already has a definitive holder deselects the previous one.
            self.enforce_definitive_mode_uniqueness(preferring=peak_id)
        self.user_has_modified_peak_selection = True

    @property
    def single_holder_modes(self) -> set:
        """The modes that can have at most one **definitive** (selected) peak.

        Air, Top and Back are single physical resonances, so exactly one peak can be *the* Air, Top or
        Back. Dipole, Ring and Upper Modes are clusters — several selected peaks are meaningful there,
        so they are deliberately unconstrained. Mirrors Swift ``TapToneAnalyzer.singleHolderModes``.
        """
        from .guitar_mode import GuitarMode
        return {GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK}

    def enforce_definitive_mode_uniqueness(self, preferring: str) -> None:
        """Keep the selection invariant: **at most one selected peak per Air / Top / Back**.

        The selected peak *is* the definitive Air/Top/Back; every other peak of that mode remains a
        candidate. Deselecting a peak does **not** relabel it — classification is band membership and
        is untouched by selection. This only ever removes other peaks from the selection; it never
        reclassifies and never promotes a replacement. Called from the two things that can break the
        invariant: ``toggle_peak_selection`` (select branch) and ``set_mode_override``. Overriding an
        *unselected* peak changes no selection; overriding the definitive Top away leaves Top with no
        definitive peak, deliberately (nothing auto-promotes). Guitar only.

        Mirrors Swift ``enforceDefinitiveModeUniqueness(preferring:)``.
        """
        from .tap_display_settings import TapDisplaySettings
        if not TapDisplaySettings.measurement_type().is_guitar:
            return
        if preferring not in self.selected_peak_ids:
            return
        winner = next((p for p in self.all_peaks if p.id == preferring), None)
        if winner is None:
            return
        # Resolve through peak_mode() — the OVERRIDE-AWARE path. identified_modes is built from
        # classify_all alone and never consults overrides, so using it here would silently ignore a
        # mode the user assigned by hand.
        mode = self.peak_mode(winner)
        if mode not in self.single_holder_modes:
            return
        for other in self.all_peaks:
            if (other.id != preferring
                    and other.id in self.selected_peak_ids
                    and self.peak_mode(other) == mode):
                self.selected_peak_ids.discard(other.id)

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

    def set_highlighted_peak(self, peak_id) -> None:
        """Highlight a peak by id, or none — the chart-dot ↔ peak-list cross-highlight. Transient view
        state: not selection, not saved. Mirrors Swift ``highlightedPeakID``."""
        if self.highlighted_peak_id == peak_id:
            return
        self.highlighted_peak_id = peak_id
        self.highlightedPeakChanged.emit(peak_id)

    def toggle_highlighted_peak(self, peak_id) -> None:
        """Clicking a peak's chart dot or its card: the same peak again clears the highlight, another
        moves it. Mirrors Swift's dot and row taps (both toggle) and the web's toggleHighlightedPeak."""
        self.set_highlighted_peak(None if self.highlighted_peak_id == peak_id else peak_id)

    # @parity state/visible-peaks tests=test/annotation-state,test/comparison
    def cycle_annotation_visibility(self) -> None:
        """Advance annotation_visibility_mode: all → selected → none → all.

        Persists the new value via TapDisplaySettings.
        Mirrors Swift ``cycleAnnotationVisibility()``.
        """
        self.annotation_visibility_mode = self.annotation_visibility_mode.next
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_annotation_visibility_mode(self.annotation_visibility_mode)
        # mirrors cycleAnnotationVisibility() → TapDisplaySettings.annotationVisibilityMode in Swift

    @property
    def chart_peaks(self) -> "list | None":
        """The peaks the chart marks: a guitar's above Peak Min, a plate's or brace's identified
        ones — None while a comparison is shown, which draws its entries' own. Mirrors Swift
        ``chartPeaks``."""
        from .analysis_display_mode import AnalysisDisplayMode
        from .tap_display_settings import TapDisplaySettings as _tds_cp
        if self.display_mode == AnalysisDisplayMode.COMPARISON:
            return None
        return (self.peaks_above_peak_min if _tds_cp.measurement_type().is_guitar
                else self.material_identified_peaks)

    @property
    def chart_annotation_peaks(self) -> "list | None":
        """The peaks the chart labels: ``visible_peaks`` — None while a comparison is shown. Mirrors
        Swift ``chartAnnotationPeaks``."""
        from .analysis_display_mode import AnalysisDisplayMode
        return None if self.display_mode == AnalysisDisplayMode.COMPARISON else self.visible_peaks

    @property
    def shows_mode_boundaries(self) -> bool:
        """Whether the chart draws the guitar mode lines: not for a comparison of saved
        measurements, whose entries need not be of one guitar type. A multi-tap guitar's per-tap
        overlay keeps them. Mirrors Swift ``showsModeBoundaries``."""
        return not self.is_saved_measurement_comparison

    @property
    def visible_peaks(self) -> list:
        """Subset of peaks_above_peak_min to render given annotation_visibility_mode.

        In guitar mode, peaks classified as Unknown are excluded when
        ``TapDisplaySettings.show_unknown_modes`` is False, keeping the chart
        consistent with the Analysis Results panel.

        Mirrors Swift ``visiblePeaks: [ResonantPeak]``.
        """
        from .annotation_visibility_mode import AnnotationVisibilityMode
        from .tap_display_settings import TapDisplaySettings as _tds_vp
        # Material (plate/brace): annotate the accumulated identified L/C/FLC (stable, persistent),
        # matching the web — NOT peaks_above_peak_min, which churns through 87→126→3 raw peaks during
        # capture. No per-peak selection, so ALL/SELECTED are equivalent.
        if not _tds_vp.measurement_type().is_guitar:
            if self.annotation_visibility_mode == AnnotationVisibilityMode.NONE:
                return []
            return self.material_identified_peaks
        mode = self.annotation_visibility_mode
        if mode == AnnotationVisibilityMode.ALL:
            candidates = list(self.peaks_above_peak_min)
        elif mode == AnnotationVisibilityMode.SELECTED:
            candidates = [p for p in self.peaks_above_peak_min if p.id in self.selected_peak_ids]
        else:
            # NONE
            return []

        # Filter unknown-mode peaks in guitar mode when the setting is off. One rule for all three
        # display surfaces — see `is_unknown()`. Note the annotation layer carries an extra gate the
        # results panel and the dot layer do not: the visibility mode above. `ALL` means all
        # *identified* peaks, selected or not.
        from .tap_display_settings import TapDisplaySettings
        measurement_type = TapDisplaySettings.measurement_type()
        if measurement_type.is_guitar and not TapDisplaySettings.show_unknown_modes():
            candidates = [p for p in candidates if not self.is_unknown(p)]
        return candidates

    @property
    def material_identified_peaks(self) -> list:
        """The identified per-phase peaks (L, then C, then FLC) found so far in a material
        measurement, in phase order — a material measurement's peaks. The three selected_* peaks are
        the only material peak state (all_peaks / selected_peak_ids are guitar-only); the chart,
        annotations, results panel, save and PDF all read them through here. Empty for guitar.
        Mirrors Swift materialIdentifiedPeaks.
        """
        from .tap_display_settings import TapDisplaySettings
        if TapDisplaySettings.measurement_type().is_guitar:
            return []
        return [p for p in (self.selected_longitudinal_peak, self.selected_cross_peak,
                            self.selected_flc_peak) if p is not None]
