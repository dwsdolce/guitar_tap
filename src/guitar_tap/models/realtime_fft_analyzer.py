"""
Real-time FFT audio analyser — mirrors Swift RealtimeFFTAnalyzer.swift.

The Swift RealtimeFFTAnalyzer class is split across four Swift files:
  RealtimeFFTAnalyzer.swift                — class declaration, init/deinit
  RealtimeFFTAnalyzer+EngineControl.swift  — start() / stop()
  RealtimeFFTAnalyzer+FFTProcessing.swift  — performFFT, computeGatedFFT,
                                             peak detection, parabolic interp, Q-factor, HPS
  RealtimeFFTAnalyzer+DeviceManagement.swift — device enumeration, CoreAudio /
                                              AVAudioSession listeners, setInputDevice

This Python package mirrors that structure using four modules:

  realtime_fft_analyzer.py                → RealtimeFFTAnalyzer class declaration,
                                             stored properties, __init__
      mirrors RealtimeFFTAnalyzer.swift (class declaration only)
      Also contains _FftProcessingThread, a Python-only private class that handles
      off-main-thread DSP.  Swift uses AVAudioEngine taps on the main audio graph
      instead; this class has no Swift counterpart and is an implementation detail
      of RealtimeFFTAnalyzer, not a separate model entity.

  realtime_fft_analyzer_engine_control.py → RealtimeFFTAnalyzerEngineControlMixin
      mirrors RealtimeFFTAnalyzer+EngineControl.swift
      Methods: new_frame, get_frames, start, stop, start_from_file, close

  realtime_fft_analyzer_fft_processing.py → module-level FFT functions
      mirrors RealtimeFFTAnalyzer+FFTProcessing.swift
      Key correspondence: dft_anal ↔ computeFFT(on:) (pure DSP core).
      Swift's performFFT(on:) is now a thin wrapper around computeFFT that only
      dispatches results to @Published; Python's equivalent thin wrapper is the
      dft_anal call + fftFrameReady.emit inside _FftProcessingThread.run().

  realtime_fft_analyzer_device_management.py → RealtimeFFTAnalyzerDeviceManagementMixin
      mirrors RealtimeFFTAnalyzer+DeviceManagement.swift

This file (realtime_fft_analyzer.py) contains:
  - The RealtimeFFTAnalyzer class declaration and stored properties / __init__
    (mirrors the top of Swift RealtimeFFTAnalyzer.swift)
  - _FftProcessingThread (Python-only private inner class — off-main-thread DSP loop)
  - Re-export of all FFT functions from realtime_fft_analyzer_fft_processing for
    backward compatibility (callers that do `import models.realtime_fft_analyzer as f_a`
    and call `f_a.dft_anal(...)` continue to work unchanged)
  - Microphone alias for backward compatibility with existing import sites

Python ↔ Swift correspondence:
  RealtimeFFTAnalyzer class  ↔  RealtimeFFTAnalyzer class
    __init__                 ↔  init (stored properties declared here)
    start / stop             ↔  start() / stop()          [in engine_control mixin]
    start_from_file          ↔  startFromFile(_:completion:) [in engine_control mixin]
    close                    ↔  deinit                    [in engine_control mixin]
    set_device               ↔  setInputDevice(_:)        [in device_management mixin]
    reinitialize_portaudio   ↔  (PortAudio-specific; no Swift equivalent)
    _start_hotplug_monitor   ↔  registerMacOSHardwareListener /
                                 iOS routeChangeNotification observer
    _start_coreaudio_monitor ↔  AudioObjectAddPropertyListener block
    _start_windows_monitor   ↔  CM_Register_Notification
    _start_linux_monitor     ↔  (Linux-only; no Swift equivalent)
    get_frames / queue       ↔  rawSampleHandler / inputBuffer [in engine_control mixin]
    proc_thread              ↔  (no direct equivalent — Swift AVAudioEngine taps
                                 deliver audio on a dedicated audio thread; Python
                                 uses an explicit QThread for the same purpose)

NOTE — Python vs Swift architectural differences:
  Swift uses AVAudioEngine with a tap on AVAudioInputNode; Python uses PortAudio
  via sounddevice's InputStream with a per-chunk callback.
  Swift publishes results as @Published properties on the main thread via
  DispatchQueue.main.async; Python pushes raw audio chunks into a queue.Queue
  for consumption by _FftProcessingThread (owned by RealtimeFFTAnalyzer).
  The real-time spectrum accumulation loop (Swift inputBuffer accumulation →
  performFFT continuous path → @Published magnitudes) is implemented in
  _FftProcessingThread, which is created and owned by RealtimeFFTAnalyzer.
"""

from __future__ import annotations

import atexit

# ── RealtimeFFTAnalyzer / device management ───────────────────────────────────
import platform
import queue
import threading
import time
from typing import Callable

import numpy as np
import numpy.typing as npt
import sounddevice as sd
from PySide6 import QtCore

from guitar_tap.utilities.logging import gt_log
from .realtime_fft_analyzer_device_management import RealtimeFFTAnalyzerDeviceManagementMixin
from .realtime_fft_analyzer_engine_control import RealtimeFFTAnalyzerEngineControlMixin

# ── FFT function re-exports (backward compatibility) ─────────────────────────
# Existing code that does:
#   import models.realtime_fft_analyzer as f_a
#   f_a.dft_anal(...)
# continues to work unchanged.
from .realtime_fft_analyzer_fft_processing import (
    dft_anal,
)

if platform.system() == "Darwin":
    from views.utilities import platform_adapters as mac_access


# ── _FftProcessingThread ──────────────────────────────────────────────────────
# Python-only private class — no Swift counterpart.
#
# Swift uses AVAudioEngine taps which deliver audio on the audio processing
# queue (not the main thread) and publish results via @Published on the main
# thread.  Python uses PortAudio callbacks which must return immediately, so
# the actual DSP work is deferred to this QThread.
#
# This class is an implementation detail of RealtimeFFTAnalyzer and is created
# and owned by it (self.proc_thread).  It is not a separate model entity and
# has no corresponding file in the Swift source.
#
# Gated capture state (pre-roll buffer, accumulator, active flag) was previously
# owned here.  It has been moved to TapToneAnalyzer to match Swift's ownership
# model where TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:) owns those
# buffers.  This thread now calls mic.raw_sample_handler(chunk, rate) on every
# chunk so TapToneAnalyzer can accumulate directly.
# The gatedCaptureComplete Qt signal remains here as the delivery mechanism.

class _FftProcessingThread(QtCore.QThread):
    """Queue-draining thread for live mic audio.

    In the live mic path, PortAudio callbacks must return immediately, so
    chunks are queued and this thread drains them and calls
    ``mic.process_raw_samples(chunk)`` — the single processing method shared
    by both live and file paths.

    For file playback, ``process_file_data`` calls ``process_raw_samples``
    inline without using this thread or the queue.

    Python-only: Swift uses AVAudioEngine taps on the main audio graph rather
    than a separate QThread.
    """

    # MARK: - Signals (kept on the QThread for Qt signal delivery)

    # (mag_y_db, mag_y, fft_peak_amp, rms_amp, fps, sample_dt, processing_dt)
    fftFrameReady: QtCore.Signal = QtCore.Signal(
        np.ndarray, np.ndarray, int, int, float, float, float
    )

    # Per-chunk RMS level (0-100 scale) emitted every audio chunk.
    rmsLevelChanged: QtCore.Signal = QtCore.Signal(int)

    # Edge-triggered clipping signal.
    clippingChanged: QtCore.Signal = QtCore.Signal(bool)

    # Emitted when a gated capture window fills.
    gatedCaptureComplete: QtCore.Signal = QtCore.Signal(object, float, object)

    # MARK: - Initialization

    def __init__(
        self,
        mic: "RealtimeFFTAnalyzer",
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._mic = mic
        self._stop_event = threading.Event()

        # Drain barrier — mirrors Swift audioProcessingQueue.sync {}.
        self._drain_event = threading.Event()
        self._drain_ack = threading.Event()

    # MARK: - QThread.run() — thin queue drainer

    def run(self) -> None:
        """Drain mic.queue and call mic.process_raw_samples on each chunk.

        All DSP logic lives in RealtimeFFTAnalyzer.process_raw_samples,
        matching Swift where processRawSamples is on RealtimeFFTAnalyzer.
        """
        while not self._stop_event.is_set():
            try:
                chunk = self._mic.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Drain barrier — None sentinel means "finish current work, then wait".
            if chunk is None:
                self._drain_ack.set()
                while self._drain_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.001)
                continue

            self._mic.process_raw_samples(chunk)

    # MARK: - Public API (safe to call from main thread)

    def stop(self) -> None:
        """Signal the run() loop to exit."""
        self._stop_event.set()

    def reset_state(self) -> None:
        """Reset state; call before start().

        Mirrors Swift inputBuffer.removeAll() + related resets in startFromFile.
        """
        self._mic._input_buffer = []
        self._mic._input_buffer_len = 0
        self._stop_event.clear()
        with self._mic._recent_peak_lock:
            self._mic._recent_peak_db = -100.0
            self._mic._recent_peak_history = []


class RealtimeFFTAnalyzer(RealtimeFFTAnalyzerEngineControlMixin, RealtimeFFTAnalyzerDeviceManagementMixin):
    """Real-time FFT audio analyser using PortAudio/sounddevice.

    Captures audio from a selected input device, delivers raw PCM chunks via
    ``queue`` for downstream FFT processing, and monitors device hot-plug events.

    Mirrors Swift RealtimeFFTAnalyzer (class declaration, init/deinit from
    RealtimeFFTAnalyzer.swift; start/stop from +EngineControl.swift; device
    management from +DeviceManagement.swift).

    NOTE — Python vs Swift architectural differences:
      Swift uses AVAudioEngine with a tap on AVAudioInputNode and publishes
      results as @Published properties on the main thread.
      Python uses PortAudio (sounddevice) with a blocking Queue callback model;
      downstream FFT processing is done by _FftProcessingThread (owned by this class).

    Python-only properties:
      queue              — audio chunk queue; Swift has rawSampleHandler + inputBuffer
      device_index       — PortAudio device index; Swift has selectedInputDevice (AVAudioDevice)
      chunksize          — PortAudio block size; Swift uses 1024-sample AVAudioEngine tap
      stream             — sounddevice.InputStream; Swift has audioEngine + inputNode
      is_stopped         — stream stop flag; Swift has isRunning (@Published)
      _stop_lock         — threading.Lock for is_stopped; Swift uses DispatchQueue sync
      _monitor_stop      — threading.Event to signal monitor thread exit
      _on_devices_changed — plain callback; Swift uses @Published availableInputDevices
      proc_thread        — _FftProcessingThread instance owned by this analyzer;
                           Swift equivalent is the AVAudioEngine audio processing queue

    Python FFT configuration properties (mirrors Swift RealtimeFFTAnalyzer):
      fft_size    ↔  Swift fftSize      — FFT window size (power of 2)
      window_fcn  ↔  Swift window       — pre-computed window function array (length fft_size)
      m_t         ↔  (same as fft_size) — ring-buffer length; equals fft_size, matching Swift
      h_fft_size  —  Python-only fft_size // 2 convenience field

    Swift-only properties (no Python equivalent):
      audioEngine, inputNode, audioProcessingQueue, bufferAccessQueue
      magnitudes, frequencies, peakFrequency, peakMagnitude (@Published)
      inputLevelDB, displayLevelDB, recentPeakLevelDB, recentPeakTime
      actualSampleRate, frequencyResolution, bandwidth
      sampleLengthSeconds, frameRate, processingTimeMs, avgProcessingTimeMs
      activeCalibration, calibrationCorrections, rawSampleHandler
      fftSetup
      isRunning, microphonePermissionDenied, routeChangeRestartCount
      firstBufferReceived, fftCount, engineStartTime
    """

    # MARK: - Testing Support

    ## When ``True``, the analyzer was created via ``for_testing()`` and has no
    ## audio hardware wired.  Checked by ``close()`` to skip hardware teardown.
    ## Mirrors Swift ``RealtimeFFTAnalyzer.isForTesting``.
    is_for_testing: bool = False

    @classmethod
    def for_testing(
        cls,
        sample_rate: int = 48000,
    ) -> "RealtimeFFTAnalyzer":
        """Create a ``RealtimeFFTAnalyzer`` suitable for unit testing.

        The returned instance has a fully functional FFT pipeline (window,
        buffers, processing thread) but **no audio hardware**: no PortAudio
        stream, no device enumeration, no hot-plug monitor.
        Use ``process_file_data()`` to feed audio.

        The FFT size is a class-level constant (65 536); it is not
        configurable per-instance.

        Mirrors Swift ``RealtimeFFTAnalyzer.forTesting()``.

        Args:
            sample_rate: Sample rate in Hz. Default 48000.
        """
        return cls(
            parent=None,
            rate=sample_rate,
            chunksize=1024,
            device=None,
            for_testing=True,
        )

    # MARK: - Level-Crossing Confirmation
    #
    # Number of consecutive above-threshold audio chunks required to
    # confirm a level crossing before ``_level_crossing_handler`` fires.
    #
    # At a 1024-sample chunk and 48 kHz sample rate each chunk is ~21 ms,
    # so the default of ``2`` requires ~43 ms of sustained signal above
    # the threshold.  This rejects brief 1-chunk broadband bumps — for
    # example handling noise between plate-mode phases — while still
    # firing reliably on real taps, including high-Q brace ring-outs that
    # may only spend ~2 chunks above the rising threshold before the
    # per-chunk RMS decays below it.
    #
    # **Why 2 and not 3:** the brace test fixture
    # (brace-umik-1-swift-mac-1778816093.wav) has a real tap whose
    # per-chunk RMS drops below threshold after only the second chunk:
    #   chunk 1: RMS -47.76 dB (above)
    #   chunk 2: RMS -52.48 dB (above)
    #   chunk 3: RMS -54.80 dB (below)
    # A confirmation requirement of 3 would reject this real tap.  The
    # observed plate-mode bump in plate-umik-1-swift-mac-1778816330.wav
    # is a single-chunk excursion (RMS -46.78 dB then -53.55 dB), so 2
    # already rejects it.
    #
    # The trade-off vs ``1`` (legacy fire-on-first-crossing):
    # - Pros: filters single-chunk noise events that previously triggered
    #   bogus gated captures — especially during file playback, which
    #   has no human review-time gap between phases.
    # - Cons: trigger fires ``LEVEL_CROSSING_CONFIRMATION_CHUNKS - 1``
    #   chunks later than before.  ``align_capture_to_onset`` compensates
    #   by anchoring the FFT window to the sample-precise tap onset, so
    #   the FFT input is unchanged.  A bump spanning 2+ chunks could
    #   still slip through; a higher value would start cutting into
    #   weak marginal taps like the brace example above.
    #
    # This constant is also consulted by the main-thread tap detector
    # (``TapToneAnalyzer.detect_tap``) so both rising-edge paths apply
    # the same confirmation logic — otherwise a bump rejected here can
    # still fire the main-thread detector and start a bogus capture.
    #
    # Mirrors Swift ``RealtimeFFTAnalyzer.levelCrossingConfirmationChunks``.
    LEVEL_CROSSING_CONFIRMATION_CHUNKS: int = 2

    # MARK: - Initialization

    def __init__(self, parent, rate: int = 44100, chunksize: int = 16384,
                 device: "AudioDevice | None" = None,
                 on_devices_changed: Callable[[], None] | None = None,
                 on_calibration_changed: "Callable[[object | None], None] | None" = None,
                 for_testing: bool = False):
        """Create a new real-time FFT analyser.

        The FFT size is a class-level constant (65 536) and cannot be
        overridden.  At 48 kHz this gives ≈0.73 Hz/bin resolution.

        Mirrors Swift ``RealtimeFFTAnalyzer.init(forTesting:)``.

        When ``for_testing`` is True, the initialiser sets up the FFT pipeline
        (window, buffers, processing thread) but skips all audio hardware:
        no PortAudio stream, no device enumeration, no hot-plug monitor.
        This mirrors Swift's ``guard !forTesting else { return }`` pattern.

        Args:
            parent:                  Parent QObject (used to anchor a MacAccess helper on macOS).
            rate:                    Fallback sample rate in Hz; overridden by device.sample_rate.
            chunksize:               PortAudio block size in frames (Python-only; Swift uses 1024).
            device:                  AudioDevice to open, or None for the system default.
            on_devices_changed:      Callback fired on hot-plug connect/disconnect events.
                                     Mirrors Swift's @Published availableInputDevices update.
            on_calibration_changed:  Callback fired by set_device() after auto-loading the
                                     device-specific calibration.  Receives the loaded
                                     MicrophoneCalibration profile, or None if no calibration
                                     exists for the new device.
                                     Mirrors Swift selectedInputDevice.didSet calling
                                     setCalibrationWithoutSavingDeviceMapping(_:).
            for_testing:             When True, skip all audio hardware setup.
                                     Mirrors Swift ``init(forTesting:)``.
        """
        self.is_for_testing = for_testing

        # Python-only: PortAudio session state
        self.rate: int = int(device.sample_rate) if device else rate
        self.chunksize: int = chunksize
        self.device_index: int | None = device.index if device else None

        # MARK: - FFT Configuration (mirrors Swift RealtimeFFTAnalyzer)

        # FFT window size — compile-time constant (65 536 points).
        # At 48 kHz the window spans ≈1.36 s with ≈0.73 Hz/bin resolution.
        # Both the continuous display path and the guitar gated-capture path
        # use this value.  The plate/brace gated path (compute_gated_fft)
        # computes its own size independently.
        # Mirrors Swift ``RealtimeFFTAnalyzer.fftSize``.
        fft_size = 65536
        self.fft_size: int = fft_size

        # Ring-buffer length in samples — identical to fft_size, matching Swift's
        # inputBuffer which accumulates exactly fftSize samples before each FFT.
        self.m_t: int = fft_size

        # Half FFT size — number of positive-frequency bins (DC to Nyquist inclusive).
        self.h_fft_size: int = fft_size // 2

        # Window function applied to the ring buffer before the FFT.
        # Using a rectangular (boxcar) window of fft_size samples — matching Swift's
        # performFFT which applies a rectangular window of exactly fftSize samples
        # with no zero-padding.
        # See realtime_fft_analyzer_fft_processing.py for why rectangular is preferred.
        # numpy.ones is identical to scipy.signal.get_window("boxcar", N).
        self.window_fcn = np.ones(fft_size)

        # Python-only: audio chunk delivery via Queue
        # Swift delivers audio via rawSampleHandler callback + inputBuffer accumulation
        self._stop_lock: threading.Lock = threading.Lock()
        self.is_stopped: bool = False
        self.queue: queue.Queue[npt.NDArray[np.float32]] = queue.Queue()

        # MARK: - WAV File Playback (mirrors Swift RealtimeFFTAnalyzer.isPlayingFile)
        # True while a background thread is feeding a WAV file into self.queue.
        # Set to False by stop() or when the file thread finishes.
        self.is_playing_file: bool = False
        self._file_playback_thread: threading.Thread | None = None

        # Filename (without extension) of the file currently being played, or None.
        # Mirrors Swift RealtimeFFTAnalyzer.playingFileName (@Published var).
        self.playing_file_name: str | None = None

        # Optional callback invoked (from the playback thread) when file playback ends
        # and the mic stream has been restarted.  Used by TapToneAnalyzer to clear the
        # chart title — mirrors Swift's completion closure in startFromFile(_:completion:).
        self._on_playback_finished: Callable[[], None] | None = None

        # Optional callback invoked (from the playback thread) after the input buffer
        # flush but BEFORE the mic stream is restarted.  Used by TapToneAnalyzer to
        # zero-pad and complete any active gated capture so mic noise cannot fill the
        # remaining window.  Mirrors Swift preMicRestartHandler in startFromFile's
        # asyncAfter block.
        self._on_pre_mic_restart: Callable[[], None] | None = None

        # Optional callback invoked after the audio engine stops and the queue is
        # drained, but BEFORE file chunks are pumped.  Used by TapToneAnalyzer to
        # re-initialize the pre-roll buffer with silence so stale mic audio from
        # between startTapSequence and engine-stop does not leak into the gated
        # capture's pre-roll seed.  Mirrors Swift postEngineStopHandler.
        self._on_post_engine_stop: Callable[[], None] | None = None

        # MARK: - Device Lists (mirrors Swift RealtimeFFTAnalyzer @Published properties)

        # Live list of available input devices.
        # Mirrors Swift RealtimeFFTAnalyzer.availableInputDevices (@Published).
        self.available_input_devices: list = []

        # The currently selected input device (backing store for the property).
        # Mirrors Swift RealtimeFFTAnalyzer.selectedInputDevice (@Published).
        # Use _selected_input_device directly only during init to avoid
        # firing didSet logic before callbacks are wired.
        self._selected_input_device: "AudioDevice | None" = device

        # Python-only: hot-plug monitoring threads
        self._on_devices_changed = on_devices_changed
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None

        # Calibration-change callback.
        self._on_calibration_changed: "Callable[[object | None], None] | None" = on_calibration_changed

        # Raw-sample handler callback.
        # Mirrors Swift RealtimeFFTAnalyzer.rawSampleHandler.
        # Set by TapToneAnalyzer._wire_pipeline_signals() to _accumulate_gated_samples.
        self.raw_sample_handler: "Callable[[np.ndarray, float], None] | None" = None

        # MARK: - Direct callback properties (mirrors Swift handlers)
        # These are called directly by process_raw_samples — no Qt signal dispatch.
        # For file playback this is the only delivery path (no event loop).
        # For live mic the Qt signals are emitted in parallel for UI updates.
        self.rms_level_handler: "Callable[[float], None] | None" = None
        self.fft_frame_handler: "Callable[..., None] | None" = None

        # MARK: - Processing State (formerly on _FftProcessingThread)
        # Moved here so process_raw_samples can access them directly.
        # Mirrors Swift processRawSamples state on RealtimeFFTAnalyzer.

        # Input buffer — growing accumulator for FFT.
        self._input_buffer: list[npt.NDArray[np.float32]] = []
        self._input_buffer_len: int = 0

        # Thread-safe settings (calibration).
        self._settings_lock = threading.Lock()
        self._calibration: npt.NDArray | None = None
        self._calibration_profile: object | None = None

        # Recent peak level (rolling max over 0.5 s).
        self._recent_peak_lock = threading.Lock()
        self._recent_peak_db: float = -100.0
        self._recent_peak_window: float = 0.5
        self._recent_peak_history: list = []

        # Level-crossing detection.
        self._level_crossing_handler: "Callable[[], None] | None" = None
        self._level_crossing_threshold: float = -100.0
        self._level_crossing_armed: bool = False
        self._previous_level_db: float = -100.0
        # Running count of consecutive above-threshold chunks in the
        # current candidate rising-edge run.  Reset to 0 when arming
        # changes (handled at the assignment sites) or when the level
        # falls back below threshold.  Once it reaches
        # LEVEL_CROSSING_CONFIRMATION_CHUNKS the handler fires and the
        # level crossing is disarmed.
        self._level_crossing_consecutive_above: int = 0

        # Input clipping detection.
        self._clip_hold_seconds: float = 1.5
        self._last_clip_time: float | None = None
        self._is_clipping_state: bool = False

        # Diagnostic counters.
        self._fft_frame_counter: int = 0
        self._samples_consumed: int = 0
        self._diag_total_samples: int = 0

        # Timing for FFT frame rate.
        self._last_fft_time: float = time.time()

        # Python-only: off-main-thread DSP worker (for live mic queue draining).
        # Mirrors Swift's AVAudioEngine audio processing queue.
        self.proc_thread: _FftProcessingThread = _FftProcessingThread(mic=self)

        # ── Guard: skip hardware setup for testing ───────────────────────
        # Mirrors Swift: guard !forTesting else { return }
        if for_testing:
            self.stream = None  # type: ignore[assignment]
            return

        if platform.system() == "Darwin":
            mac_access.MacAccess(parent)

        # Open the sounddevice stream; Swift opens AVAudioEngine in start()
        self.stream: sd.InputStream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame)

        # Verify the negotiated stream rate; warns if WASAPI resampled to a different rate.
        from .realtime_fft_analyzer_device_management import _log_stream_diagnostics
        self.rate = _log_stream_diagnostics(self.stream, self.rate)

        # Start the hot-plug device monitor.
        self._start_hotplug_monitor()

        atexit.register(self.close)

    # MARK: - Selected Input Device Property
    # Mirrors Swift @Published var selectedInputDevice: AVAudioDevice? { didSet { ... } }
    # The setter mirrors Swift's didSet: persists the device fingerprint and
    # auto-loads the device-specific calibration on every assignment.

    @property
    def selected_input_device(self) -> "AudioDevice | None":
        return self._selected_input_device

    @selected_input_device.setter
    def selected_input_device(self, device: "AudioDevice | None") -> None:
        self._selected_input_device = device
        if device is None:
            return

        # Persist the selected device fingerprint so it can be restored on next launch.
        # Mirrors Swift: UserDefaults.standard.set(deviceUID, forKey: "selectedInputDeviceUID")
        try:
            from views.utilities.tap_settings_view import AppSettings as _AS
            _AS.set_selected_input_device_fingerprint(device.fingerprint)
        except Exception:
            pass

        # Automatically load device-specific calibration when device changes.
        # Mirrors Swift selectedInputDevice.didSet → setCalibrationWithoutSavingDeviceMapping(_:).
        on_cal = getattr(self, "_on_calibration_changed", None)
        if on_cal is not None:
            try:
                from models.microphone_calibration import CalibrationStorage as _CS
                cal = _CS.calibration_for_device(device.fingerprint)
                if cal is None:
                    cal = _CS.calibration_for_device(device.name)
                if cal is not None:
                    gt_log(f"📊 Auto-loaded calibration for device '{device.name}'")
                else:
                    gt_log(f"📊 No calibration for device '{device.name}' - using uncalibrated mode")
                on_cal(cal)
            except Exception:
                pass

    # MARK: - process_raw_samples (mirrors Swift processRawSamples)

    def process_raw_samples(self, chunk: npt.NDArray) -> None:
        """Process a single audio chunk through the full DSP pipeline.

        This is the single processing method for ALL audio — live mic and
        file playback both call this identically.  Mirrors Swift
        ``processRawSamples(_ samples: [Float])`` in
        ``RealtimeFFTAnalyzer+FFTProcessing.swift``.

        Steps (matches Swift processRawSamples ordering):
        1. float32 cast, diagnostic counter
        2. raw_sample_handler (gated sample delivery)
        3. RMS calculation
        4. Level-crossing detection → _level_crossing_handler callback
        5. rms_level_handler callback + rmsLevelChanged Qt signal
        6. Clipping detection → clippingChanged Qt signal
        7. Recent peak history update
        8. Input buffer accumulation → FFT → fft_frame_handler callback + fftFrameReady Qt signal
        """
        from .realtime_fft_analyzer_fft_processing import perform_fft as _perform_fft

        enter_now = time.time()
        chunk_f32 = chunk.astype(np.float32)

        # DIAG: running total of samples consumed from the audio source
        self._diag_total_samples += len(chunk_f32)

        # Deliver every raw audio chunk to the raw_sample_handler if set.
        # Mirrors Swift rawSampleHandler?(samples, actualSampleRate)
        handler = self.raw_sample_handler
        if handler is not None:
            handler(chunk_f32, float(self.rate))

        # Per-chunk RMS level — mirrors Swift vDSP_rmsqv → levelDB calculation.
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        level_db = 20.0 * np.log10(max(rms, 1e-10))
        rms_amp = int(level_db + 100.0)

        # ── Level-crossing detection (audio-queue fast-start) ────
        # MUST run BEFORE rms_level_handler.  Mirrors Swift processRawSamples
        # where the level-crossing check fires before rmsLevelHandler.  The
        # rms_level_handler callback triggers tap detection →
        # start_guitar_gated_capture which disarms the level-crossing.  If
        # rms_level_handler fires first, the crossing never gets a chance
        # to fire and the gated capture starts via the slower main-thread
        # fallback path with fewer pre-roll samples.
        #
        # Requires ``LEVEL_CROSSING_CONFIRMATION_CHUNKS`` consecutive
        # above-threshold chunks (default 2 = ~43 ms) before firing.  This
        # rejects brief noise bumps that would otherwise consume a phase's
        # gated capture window — especially during file playback where
        # there is no human review-time gap between phases.
        # ``align_capture_to_onset`` re-anchors the FFT window to the
        # sample-precise onset, so the few chunks of trigger delay
        # introduced here are invisible downstream.
        if self.is_playing_file:
            from guitar_tap.utilities.logging import TAP_DEBUG as _td_lc
            _td_lc("processRawSamples",
                   f"LEVEL_CHECK | armed={self._level_crossing_armed} "
                   f"levelDB={level_db:.1f} threshold={self._level_crossing_threshold:.1f} "
                   f"prevDB={self._previous_level_db:.1f} chunkLen={len(chunk_f32)} "
                   f"fileSamplePos={self._diag_total_samples}")
        if self._level_crossing_armed:
            above_threshold = level_db > self._level_crossing_threshold
            prev_above_threshold = self._previous_level_db > self._level_crossing_threshold
            confirm_target = self.LEVEL_CROSSING_CONFIRMATION_CHUNKS
            if above_threshold:
                if self._level_crossing_consecutive_above > 0:
                    # Already counting — extend the run.
                    self._level_crossing_consecutive_above += 1
                elif not prev_above_threshold:
                    # Fresh rising edge — start a new candidate run.
                    self._level_crossing_consecutive_above = 1
                    if self.is_playing_file and confirm_target > 1:
                        from guitar_tap.utilities.logging import TAP_DEBUG as _td_lc_pend
                        _td_lc_pend("processRawSamples",
                                    f"LEVEL_CROSSING_PENDING | rmsDB={level_db:.1f} "
                                    f"prevDB={self._previous_level_db:.1f} "
                                    f"need={confirm_target - 1} more")
                # If above && counter == 0 && prev_above, signal was
                # already above when arming happened — wait for a fall
                # + rise (handled when the level drops then climbs).
                if self._level_crossing_consecutive_above >= confirm_target:
                    self._level_crossing_armed = False
                    self._level_crossing_consecutive_above = 0
                    if self.is_playing_file:
                        from guitar_tap.utilities.logging import TAP_DEBUG as _td_lc2
                        _td_lc2("processRawSamples",
                                f"LEVEL_CROSSING_FIRED | rmsDB={level_db:.1f} "
                                f"prevDB={self._previous_level_db:.1f} "
                                f"confirmedBy={confirm_target}")
                    lc_handler = self._level_crossing_handler
                    if lc_handler is not None:
                        lc_handler()
            else:
                # Below threshold — abort any in-progress candidate run.
                if self._level_crossing_consecutive_above > 0 and self.is_playing_file:
                    from guitar_tap.utilities.logging import TAP_DEBUG as _td_lc_cancel
                    _td_lc_cancel("processRawSamples",
                                  f"LEVEL_CROSSING_CANCELED | rmsDB={level_db:.1f} "
                                  f"(signal fell below after "
                                  f"{self._level_crossing_consecutive_above}/{confirm_target} chunks)")
                self._level_crossing_consecutive_above = 0
        self._previous_level_db = level_db

        # ── RMS level callbacks (tap detection runs from here) ────
        # Direct callback (works without Qt event loop — for file playback and tests).
        # Mirrors Swift rmsLevelHandler?(levelDB)
        rms_handler = self.rms_level_handler
        if rms_handler is not None:
            rms_handler(level_db)

        # Qt signal (for UI updates via event loop — live mic path).
        self.proc_thread.rmsLevelChanged.emit(rms_amp)

        # Accumulate samples — mirrors Swift bufferAccessQueue.sync { inputBuffer.append }.
        # In Swift this comes after the level-crossing and rmsLevelHandler blocks.
        self._input_buffer.append(chunk_f32)
        self._input_buffer_len += len(chunk_f32)

        # ── Input-clipping detection ─────────────────────────────
        peak_abs = float(np.max(np.abs(chunk.astype(np.float64))))
        chunk_clipped = (peak_abs >= 0.99) or (level_db >= 0.0)
        if chunk_clipped:
            self._last_clip_time = enter_now
        new_clip_state = (
            self._last_clip_time is not None
            and (enter_now - self._last_clip_time) < self._clip_hold_seconds
        )
        if new_clip_state != self._is_clipping_state:
            self._is_clipping_state = new_clip_state
            self.proc_thread.clippingChanged.emit(new_clip_state)

        # Update rolling recent-peak history.
        with self._recent_peak_lock:
            cutoff = enter_now - self._recent_peak_window
            self._recent_peak_history = [
                (t, v) for t, v in self._recent_peak_history if t > cutoff
            ]
            self._recent_peak_history.append((enter_now, level_db))
            self._recent_peak_db = max(
                (v for _, v in self._recent_peak_history), default=-100.0
            )

        # Fire an FFT for each complete fft_size-sample chunk available.
        fft_size = self.fft_size
        while self._input_buffer_len >= fft_size:
            flat = np.concatenate(self._input_buffer)
            samples = flat[:fft_size]
            remainder = flat[fft_size:]
            self._input_buffer = [remainder] if len(remainder) else []
            self._input_buffer_len = len(remainder)

            sample_dt = enter_now - self._last_fft_time
            self._last_fft_time = enter_now

            # FFT + post-processing — perform_fft now reads calibration
            # from self (the analyzer) instead of the thread.
            mag_y_db, mag_y, fft_peak_amp = _perform_fft(self, samples, fft_size)

            exit_now = time.time()
            processing_dt = exit_now - enter_now
            fps = 1.0 / max(sample_dt, 1e-12)

            # Direct callback (works without Qt event loop).
            fft_handler = self.fft_frame_handler
            if fft_handler is not None:
                fft_handler(mag_y_db, mag_y, fft_peak_amp, rms_amp,
                            fps, sample_dt, processing_dt)

            # Qt signal (for UI updates).
            self.proc_thread.fftFrameReady.emit(
                mag_y_db, mag_y, fft_peak_amp, rms_amp,
                fps, sample_dt, processing_dt,
            )

    # MARK: - Calibration (formerly on _FftProcessingThread)

    def set_calibration(self, arr: npt.NDArray | None,
                        profile: object | None = None) -> None:
        """Update the per-bin dB calibration correction array.

        Args:
            arr:     Pre-interpolated dB corrections for the live FFT bins.
            profile: Raw MicrophoneCalibration object (optional).
        """
        with self._settings_lock:
            self._calibration = arr
            self._calibration_profile = profile

    # MARK: - Gated FFT Compute

    def compute_gated_fft(
        self,
        samples: "npt.NDArray[np.float32]",
        sample_rate: float,
    ) -> "tuple[list[float], list[float]]":
        """Compute a Hann-windowed FFT from a gated PCM capture.

        Mirrors Swift RealtimeFFTAnalyzer.computeGatedFFT(samples:sampleRate:).
        """
        from numpy.fft import fft

        n = len(samples)
        if n == 0:
            return [], []

        MAX_FFT = 32768
        fft_size = 1
        while fft_size < n:
            fft_size <<= 1
        fft_size = min(fft_size, MAX_FFT)

        padded = np.zeros(fft_size, dtype=np.float64)
        copy_count = min(n, fft_size)
        padded[:copy_count] = samples[:copy_count]

        window = np.hanning(fft_size)
        padded *= window

        complex_fft = fft(padded)
        half_n = fft_size // 2
        abs_fft = np.abs(complex_fft[:half_n])
        abs_fft /= fft_size
        abs_fft[1:] *= 2.0

        abs_fft[abs_fft < np.finfo(float).eps] = np.finfo(float).eps
        mag_db = 20.0 * np.log10(abs_fft)

        freqs_arr = np.array([float(i) * sample_rate / fft_size
                              for i in range(half_n)])

        with self._settings_lock:
            cal_profile = self._calibration_profile
        if cal_profile is not None:
            corrections = cal_profile.interpolate_to_bins(freqs_arr)
            if len(corrections) == len(mag_db):
                mag_db = mag_db + corrections

        return list(mag_db), list(freqs_arr)

    @property
    def recent_peak_level_db(self) -> float:
        """Rolling maximum RMS level over the last 0.5 s, in dBFS."""
        with self._recent_peak_lock:
            return self._recent_peak_db

    # MARK: - Engine Control
    # All engine control methods live in realtime_fft_analyzer_engine_control.py
    # via RealtimeFFTAnalyzerEngineControlMixin, mirroring Swift's
    # RealtimeFFTAnalyzer+EngineControl.swift extension.
    # Methods: new_frame, get_frames, start, stop, start_from_file, close

    # MARK: - Device Management
    # All device management methods live in realtime_fft_analyzer_device_management.py
    # via RealtimeFFTAnalyzerDeviceManagementMixin, mirroring Swift's
    # RealtimeFFTAnalyzer+DeviceManagement.swift extension.


# ── Backward-compatibility alias ─────────────────────────────────────────────
# Existing code that does:
#   from models.realtime_fft_analyzer import Microphone
# continues to work unchanged.

Microphone = RealtimeFFTAnalyzer
