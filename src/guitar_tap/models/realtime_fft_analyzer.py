# @parity audio/realtime-analyzer
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

  realtime_fft_analyzer_fft_processing.py → RealtimeFFTAnalyzerFFTProcessingMixin
      mirrors RealtimeFFTAnalyzer+FFTProcessing.swift
      Methods: compute_fft (computeFFT(on:)), perform_fft (performFFT(on:))

  realtime_fft_analyzer_device_management.py → RealtimeFFTAnalyzerDeviceManagementMixin
      mirrors RealtimeFFTAnalyzer+DeviceManagement.swift

This file (realtime_fft_analyzer.py) contains:
  - The RealtimeFFTAnalyzer class declaration and stored properties / __init__
    (mirrors the top of Swift RealtimeFFTAnalyzer.swift)
  - _FftProcessingThread (Python-only private inner class — off-main-thread DSP loop)
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
import math

# ── RealtimeFFTAnalyzer / device management ───────────────────────────────────
import queue
import threading
import time
import weakref
from typing import Callable

import numpy as np
import numpy.typing as npt
import sounddevice as sd
from PySide6 import QtCore

from guitar_tap.models.dead_input import BUFFER_DELIVERY_TIMEOUT, DEAD_INPUT_DWELL
from guitar_tap.models.input_level import InputLevel
from guitar_tap.utilities.logging import gt_log

from .realtime_fft_analyzer_device_management import RealtimeFFTAnalyzerDeviceManagementMixin
from .wall_clock import SystemWallClock, WallClock
from .realtime_fft_analyzer_engine_control import (
    RealtimeFFTAnalyzerEngineControlMixin,
    microphone_authorized,
)

from .realtime_fft_analyzer_fft_processing import RealtimeFFTAnalyzerFFTProcessingMixin



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

    It also carries the pipeline's Qt signals (``fftFrameReady``, ``gatedCaptureComplete`` and the
    rest — the input level's are on ``mic.level``): ``RealtimeFFTAnalyzer`` is not a QObject, so it cannot own
    signals, and this thread object does. So the object is created once, with the mic, and never
    replaced: a replacement would start with no connections. And each ``connect()`` ADDS a receiver, so
    connecting a signal twice delivers every emission twice. Both are guarded by the pipeline
    cases in ``tests/test_tap_detection.py``.

    The object holds no processing state: only its stop and drain events, and its signals. The input
    buffer and the peak hold live on the mic and are cleared by ``reset_state()``.

    Python-only: Swift uses AVAudioEngine taps on the main audio graph rather
    than a separate QThread.
    """

    # MARK: - Signals (kept on the QThread for Qt signal delivery)

    # Run a callable on the main thread: this object lives there. runOnMainBlocking makes the emitting
    # thread wait for it (Swift DispatchQueue.main.sync); runOnMain does not (DispatchQueue.main.async).
    # The file-playback worker uses them for the end-of-file step. Emitted only from other threads —
    # a blocking emit from the main thread would wait on itself.
    runOnMainBlocking: QtCore.Signal = QtCore.Signal(object)
    runOnMain: QtCore.Signal = QtCore.Signal(object)

    # (mag_y_db, peak_db, fps, sample_dt, processing_dt). The ONE delivery of a frame to the
    # analyzer: connected to on_fft_frame, which therefore runs on the main thread — Swift's analyzer
    # takes frames through a Combine sink `.receive(on: DispatchQueue.main)`. The peak travels as float
    # dB (Swift's `peakMagnitude`), unrounded.
    fftFrameReady: QtCore.Signal = QtCore.Signal(np.ndarray, float, float, float, float)

    # Edge-triggered dead-input signal: True while buffers arrive carrying no
    # signal. Lives here because RealtimeFFTAnalyzer is not a QObject, so the QThread owns
    # Qt signal delivery. (The input level and clipping have their own object, ``mic.level``.)
    inputAppearsDeadChanged: QtCore.Signal = QtCore.Signal(bool)

    # Edge-triggered: True once the watchdog has given up after restarts that failed.
    inputCouldNotRestartChanged: QtCore.Signal = QtCore.Signal(bool)

    # Edge-triggered: True while the microphone permission is refused.
    microphonePermissionDeniedChanged: QtCore.Signal = QtCore.Signal(bool)

    # Edge-triggered: True once a deliberate start has failed for anything but the permission.
    inputCouldNotStartChanged: QtCore.Signal = QtCore.Signal(bool)

    # Edge-triggered: the engine started (True) or stopped (False). Mirrors Swift `@Published isRunning`.
    runningChanged: QtCore.Signal = QtCore.Signal(bool)

    # Emitted when a gated capture window fills.
    gatedCaptureComplete: QtCore.Signal = QtCore.Signal(object, float, object)

    # MARK: - Initialization

    @QtCore.Slot(object)
    def _run_callable(self, fn) -> None:
        """Slot for runOnMainBlocking / runOnMain: runs *fn* on the main thread."""
        fn()

    def __init__(
        self,
        mic: "RealtimeFFTAnalyzer",
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runOnMainBlocking.connect(self._run_callable, QtCore.Qt.ConnectionType.BlockingQueuedConnection)
        self.runOnMain.connect(self._run_callable, QtCore.Qt.ConnectionType.QueuedConnection)

        # Weak back-reference to the owning analyzer.  A strong ref here would
        # form a QObject reference cycle (analyzer.proc_thread → thread._mic →
        # analyzer) collectable only by Python's *cyclic* GC, whose
        # non-deterministic timing intermittently freed the analyzer's C++
        # object mid-use and raised "Internal C++ object already deleted".
        # The analyzer owns this thread and always outlives it (stop()+wait()
        # precede its release), so the weakref is always live while run() runs.
        # Python-only: no Swift counterpart (Swift uses AVAudioEngine taps).
        self._mic_ref = weakref.ref(mic)
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
            mic = self._mic_ref()
            if mic is None:
                break  # analyzer gone — nothing to drain into.
            try:
                chunk = mic.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Drain barrier — None sentinel means "finish current work, then wait".
            if chunk is None:
                self._drain_ack.set()
                while self._drain_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.001)
                continue

            mic.process_raw_samples(chunk)

    # MARK: - Public API (safe to call from main thread)

    def stop(self) -> None:
        """Signal the run() loop to exit."""
        self._stop_event.set()

    def reset_state(self) -> None:
        """Reset state; call before start().

        Mirrors Swift inputBuffer.removeAll() + related resets in startFromFile.
        """
        self._stop_event.clear()
        mic = self._mic_ref()
        if mic is None:
            return  # analyzer gone — nothing to reset.
        mic._input_buffer = []
        mic._input_buffer_len = 0
        with mic._recent_peak_lock:
            mic.level.recent_peak_level_db = -100.0
            mic._recent_peak_time = 0.0


class RealtimeFFTAnalyzer(
    RealtimeFFTAnalyzerEngineControlMixin,
    RealtimeFFTAnalyzerDeviceManagementMixin,
    RealtimeFFTAnalyzerFFTProcessingMixin,
):
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

    def __init__(self, parent, rate: int = 44100, chunksize: int = 1024,
                 on_devices_changed: Callable[[], None] | None = None,
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
            parent:                  Parent QObject.
            rate:                    Fallback sample rate in Hz; overridden by the selected
                                     device's sample rate.
            chunksize:               PortAudio block size in frames (Python-only; Swift uses 1024).
            on_devices_changed:      Callback fired on hot-plug connect/disconnect events.
                                     Mirrors Swift's @Published availableInputDevices update.
            for_testing:             When True, skip all audio hardware setup.
                                     Mirrors Swift ``init(forTesting:)``.
        """
        self.is_for_testing = for_testing

        # Python-only: PortAudio session state
        self.rate: int = rate
        self.chunksize: int = chunksize
        self.device_index: int | None = None

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

        # MARK: - Buffer-delivery watchdog (mirrors Swift RealtimeFFTAnalyzer+Watchdog).
        # Recovers from a silently-wedged stream (the PortAudio callback stops firing
        # with no error — e.g. mic contention / device reconfiguration). A QTimer
        # detects the silence and re-opens the stream with bounded backoff.
        # The wall clock the watchdog reads its times from and schedules its restart on — the system's
        # in the app, one moved by hand in a test. Mirrors Swift `wallClock`.
        self.wall_clock: WallClock = SystemWallClock()
        # The recovery's restart. None reopens the selected device (reinitialize_portaudio); a test
        # stands in for it. Mirrors Swift `watchdogRestart`.
        self.watchdog_restart: "Callable[[], None] | None" = None
        # Whether macOS reports the microphone authorized — the watchdog acts only when it is. A
        # test, whose host may not be authorized, stands in for it. Mirrors Swift
        # `microphoneAuthorized`.
        self.microphone_authorized: "Callable[[], bool]" = microphone_authorized
        self._last_buffer_time: float = 0.0
        self._watchdog_timer = None  # QtCore.QTimer | None
        self._is_recovering: bool = False
        # A stream close that timed out and is still running on its thread; PortAudio is not
        # terminated while it is (terminating would wait on it).
        self._pending_stream_close: "threading.Thread | None" = None
        # A PortAudio re-initialise was skipped for that pending close and is still owed.
        self._portaudio_reinit_owed: bool = False
        # Called after the watchdog's restart reopens the stream (set by TapToneAnalyzer).
        self._on_stream_reopened: "Callable[[], None] | None" = None
        self._watchdog_recovery_attempts: int = 0
        self._watchdog_engine_start_time: float | None = None
        # Thresholds are owned by dead_input.py so the rule and its constants are
        # unit-testable; these keep the historical attribute names.
        self._watchdog_silence_threshold: float = BUFFER_DELIVERY_TIMEOUT
        self._watchdog_max_attempts: int = 6

        # MARK: - Dead-input watchdog (mirrors Swift RealtimeFFTAnalyzer+Watchdog).
        # A second, distinct failure mode: buffers keep arriving on schedule but carry
        # NO SIGNAL. Delivery looks healthy (`_last_buffer_time` is stamped by every
        # callback regardless of content), so the buffer-delivery watchdog above is
        # blind to it — the spectrum keeps updating and every reading is silence.
        # Seen on macOS with a USB mic after wake-from-sleep and while idling between
        # taps, where the stream survives the device re-enumerating underneath it.
        #
        # The discriminator is "impossibly quiet", never merely "quiet": any real
        # microphone clears this floor on its own self-noise, so a silent room can
        # never trigger a restart.
        self._last_signal_time: float = 0.0
        self._watchdog_dead_input_threshold: float = DEAD_INPUT_DWELL
        # True once recovery has exhausted its attempts. Restart attempts stop, but the
        # watchdog keeps WATCHING, so the app heals itself the moment audio returns
        # instead of staying deaf until it is relaunched. Mirrors Swift
        # `watchdogRecoveryExhausted`.
        self._watchdog_recovery_exhausted: bool = False
        # True while the input delivers buffers carrying no signal. Surfaced in the
        # status line rather than only auto-healed: a device-level failure cannot be
        # fixed by restarting the stream (the recorded incident needed a USB
        # re-enumeration), so recovery exhausts its attempts and stops — and the
        # status line is then all that stands between the user and an app that looks
        # alive while deaf. Mirrors Swift `inputAppearsDead`.
        self.input_appears_dead: bool = False
        # True once the recovery has given up after restarts that failed: the input could not be
        # opened again. Surfaced in the status line, above the dead-input warning; cleared by a
        # deliberate start or by signal returning. Mirrors Swift `inputCouldNotRestart`.
        self.input_could_not_restart: bool = False
        # Whether the last start or restart failed. Mirrors Swift `engineStartFailed`.
        self.engine_start_failed: bool = False
        # True while the microphone permission is refused: set by a start the system refuses, by a
        # refusal of the request, and by the 3-second check after a start (macOS); cleared by a start
        # that succeeds and by a healthy watchdog tick. Mirrors Swift `microphonePermissionDenied`.
        self.microphone_permission_denied: bool = False
        # True once a deliberate start has failed for anything but the permission: the input is
        # unavailable until a start succeeds. Mirrors Swift `inputCouldNotStart`.
        self.input_could_not_start: bool = False
        # Whether the engine is running — on the microphone, or on a file. Set by a start that
        # succeeds and a file's playback, cleared by a stop and by a recovery's close. Mirrors Swift
        # `isRunning`; the view's indicators and the button rule read it.
        self.is_running: bool = False
        # Called on the main thread when the user grants the permission in the system's request, so
        # the owner's full start runs (set by TapToneAnalyzer). Mirrors Swift `onPermissionGranted`.
        self.on_permission_granted: "Callable[[], None] | None" = None
        # Set when the permission has just been granted, so the 3-second check skips once. Mirrors
        # Swift `permissionJustGranted`.
        self._permission_just_granted: bool = False

        # MARK: - WAV File Playback (mirrors Swift RealtimeFFTAnalyzer.isPlayingFile)
        # True while a background thread is feeding a WAV file into self.queue.
        # Set to False by stop() or when the file thread finishes.
        self.is_playing_file: bool = False
        self._file_playback_thread: threading.Thread | None = None
        # Identity token for the active playback: bumped when a playback starts or is stopped. The
        # worker checks it on every chunk and before any end-of-file work. Mirrors Swift
        # filePlaybackGeneration.
        self._file_playback_generation: int = 0

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
        # Set by the device enumeration below (not in testing).
        self._selected_input_device: "AudioDevice | None" = None

        # Python-only: hot-plug monitoring threads
        self._on_devices_changed = on_devices_changed
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        # Which monitor is running: 'mmdevice' | 'cm' (Windows), 'coreaudio', 'udev', None.
        # The caller consults it because the cascade guard is only needed for cfgmgr32.
        self._hotplug_kind: str | None = None
        # Windows/MMDevice: COM holds a raw pointer, so the client must outlive registration.
        self._mm_client: object | None = None
        self._mm_enumerator: object | None = None

        # Raw-sample handler callback.
        # Mirrors Swift RealtimeFFTAnalyzer.rawSampleHandler.
        # Set by TapToneAnalyzer._wire_pipeline_signals() to _accumulate_gated_samples.
        self.raw_sample_handler: "Callable[[np.ndarray, float], None] | None" = None

        # MARK: - Direct callback properties (mirrors Swift handlers)
        # These are called directly by process_raw_samples — no Qt signal dispatch.
        # For file playback this is the only delivery path (no event loop).
        # For live mic the Qt signals are emitted in parallel for UI updates.
        # (level_db, audio_time) — audio_time is audio_elapsed AT THE MOMENT THIS CHUNK WAS
        # PROCESSED. It travels WITH the sample rather than being read later by the consumer:
        # the handler may be delivered across a thread hop, and the audio side races ahead, so
        # reading audio_elapsed at the consumer would give the CURRENT audio time, not this
        # chunk's — which silently skips the detection warm-up. Mirrors Swift rmsLevelHandler.
        self.rms_level_handler: "Callable[[float, float], None] | None" = None

        # MARK: - Processing State (formerly on _FftProcessingThread)
        # Moved here so process_raw_samples can access them directly.
        # Mirrors Swift processRawSamples state on RealtimeFFTAnalyzer.

        # Input buffer — growing accumulator for FFT.
        self._input_buffer: list[npt.NDArray[np.float32]] = []
        self._input_buffer_len: int = 0

        # Thread-safe settings (calibration).
        self._settings_lock = threading.Lock()
        # The active calibration and the corrections the engine computed from it, for the bins of
        # `_calibration_rate` (see `calibration_corrections`).
        self._calibration: npt.NDArray | None = None
        self._calibration_profile: object | None = None
        self._calibration_rate: "int | None" = None

        # The latest buffer's input level — level, clipping, recent peak — on an object of its own so
        # that only the threshold meter observes it. Swift `level`.
        self.level = InputLevel()

        # Recent peak level (`level.recent_peak_level_db`) — Swift recentPeakLevelDB: latch the running
        # max, release to the current level only after `_recent_peak_window` seconds without a higher
        # peak (peak-hold, NOT a sliding window). Window = Swift peakHoldDuration (2.0 s).
        self._recent_peak_lock = threading.Lock()
        self._recent_peak_window: float = 2.0
        self._recent_peak_time: float = 0.0

        # The live spectrum's loudest bin — Swift peakFrequency / peakMagnitude. Set on every frame
        # by perform_fft; read by the Metrics panel. Starts at, and stop() returns it to, Swift's
        # silent state (-100 dB @ 0 Hz).
        self.peak_frequency: float = 0.0
        self.peak_magnitude: float = -100.0

        # The material level readout — Swift readoutLevelDB (per chunk) and displayLevelDB (the
        # same, published at the frame rate by perform_fft). True silence is -inf on the readout;
        # detection reads the per-chunk level, which stays -100 on silence.
        self.readout_level_db: float = -100.0
        self.display_level_db: float = -100.0

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

        # Diagnostic counters.
        self._fft_frame_counter: int = 0
        self._samples_consumed: int = 0

        # Seconds of AUDIO processed — the audio clock. The detection warm-up is measured against
        # this, not the wall clock: the warm-up must cover the first 0.5 s of AUDIO, however long
        # the setup before the first chunk took. Mirrors Swift RealtimeFFTAnalyzer.audio_elapsed.
        self.audio_elapsed: float = 0.0
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

        # Enumerate the input devices and select the one to use — the saved choice when it is
        # present, else the system default, else the first. Mirrors Swift init calling
        # loadAvailableInputDevices(). The callbacks are not wired yet, so nothing is notified.
        self.load_available_input_devices()
        selected = self._selected_input_device
        if selected is not None:
            self.device_index = selected.index
            self.rate = int(selected.sample_rate)

        # The stream is opened by start(), as Swift opens AVAudioEngine in start(), so an analyzer
        # exists — and the app runs — when no input device can be opened.
        self.stream: sd.InputStream | None = None

        # Start the hot-plug device monitor.
        self._start_hotplug_monitor()

        atexit.register(self.close)

    @property
    def input_unavailable(self) -> bool:
        """The engine is not running because its input is unavailable — refused the permission, a
        start failed, or the recovery's restarts failed — rather than because it is starting: what
        the not-running placeholders say. Mirrors Swift `inputUnavailable`."""
        return (self.microphone_permission_denied or self.input_could_not_start
                or self.input_could_not_restart)

    # MARK: - Selected Input Device Property
    # Mirrors Swift @Published var selectedInputDevice: AVAudioDevice? { didSet { ... } }
    # The setter mirrors Swift's didSet: saves the device and auto-loads its calibration on
    # every assignment.

    @property
    def selected_input_device(self) -> "AudioDevice | None":
        """The active audio input device, or None.

        Assigning it saves it and auto-loads that device's calibration. Every selection is
        saved — a Settings choice, a device plugged in, a fallback, the launch selection and a
        loaded measurement's microphone — so what Settings shows is what the next launch uses.
        Mirrors Swift `selectedInputDevice`.
        """
        return self._selected_input_device

    @selected_input_device.setter
    def selected_input_device(self, device: "AudioDevice | None") -> None:
        self._selected_input_device = device
        if device is None:
            return

        # Save it so it is restored on the next launch. Mirrors Swift selectedInputDevice.didSet
        # writing selectedInputDeviceUID.
        try:
            from guitar_tap.views.utilities.tap_settings_view import AppSettings as _AS
            _AS.set_audio_device(device)
        except Exception:
            pass

        # The device's own calibration, applied by the engine itself — at launch too. Mirrors Swift
        # selectedInputDevice.didSet → setCalibrationWithoutSavingDeviceMapping(_:).
        try:
            from guitar_tap.models.microphone_calibration import CalibrationStorage as _CS
            cal = _CS.calibration_for_device(device.fingerprint)
            if cal is None:
                cal = _CS.calibration_for_device(device.name)
        except Exception:  # noqa: BLE001 — unreadable storage means no calibration, never a failed selection
            cal = None
        if cal is not None:
            gt_log(f"📊 Auto-loaded calibration for device '{device.name}'")
        else:
            gt_log(f"📊 No calibration for device '{device.name}' - using uncalibrated mode")
        self.set_calibration_without_saving_device_mapping(cal)

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
        5. rms_level_handler callback + level.inputLevelChanged Qt signal
        6. Clipping detection → level.clippingChanged Qt signal
        7. Recent peak history update
        8. Input buffer accumulation → FFT → fftFrameReady Qt signal (the analyzer's one frame delivery)
        """
        enter_now = time.time()
        chunk_f32 = chunk.astype(np.float32)

        # DIAG: running total of samples consumed from the audio source
        self._diag_total_samples += len(chunk_f32)

        # Deliver every raw audio chunk to the raw_sample_handler if set.
        # Mirrors Swift rawSampleHandler?(samples, actualSampleRate)
        handler = self.raw_sample_handler
        if handler is not None:
            handler(chunk_f32, float(self.rate))

        # Advance the AUDIO clock — seconds of audio processed, not wall-clock seconds. The detection
        # warm-up is measured against this so it always covers the first 0.5 s of AUDIO, however long
        # the setup before the first chunk took. Mirrors Swift processRawSamples.
        if self.rate > 0:
            self.audio_elapsed += len(chunk_f32) / float(self.rate)

        # Per-chunk RMS level — mirrors Swift vDSP_rmsqv → levelDB calculation.
        # Silence is -100, exactly as Swift (`rms > 0 ? 20*log10(rms) : -100`). This was
        # `max(rms, 1e-10)`, i.e. -200 — written independently of Swift, so detection saw a
        # different level on true digital silence than Swift's did.
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        level_db = 20.0 * math.log10(rms) if rms > 0 else -100.0
        self.level.input_level_db = level_db
        # The READOUT's level — Swift readoutLevelDB: the same value, except true silence is -inf,
        # because -100 dB is a real level a quiet UMIK-1 reaches. Detection keeps level_db.
        self.readout_level_db = level_db if rms > 0 else float("-inf")

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
            rms_handler(level_db, self.audio_elapsed)

        # Qt signal — the UI's copy (threshold meter). Detection used the direct handler above.
        self.level.inputLevelChanged.emit(level_db)

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
        if new_clip_state != self.level.is_clipping:
            self.level.is_clipping = new_clip_state
            self.level.clippingChanged.emit(new_clip_state)

        # Update recent peak (Swift recentPeakLevelDB): latch the max; release to the current level
        # only after `_recent_peak_window` (2.0 s) without a higher peak.
        with self._recent_peak_lock:
            if (
                level_db > self.level.recent_peak_level_db
                or (enter_now - self._recent_peak_time) > self._recent_peak_window
            ):
                self.level.recent_peak_level_db = level_db
                self._recent_peak_time = enter_now

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

            # FFT + post-processing (calibration, the live peak).
            mag_y_db, peak_db = self.perform_fft(samples)

            exit_now = time.time()
            processing_dt = exit_now - enter_now
            fps = 1.0 / max(sample_dt, 1e-12)

            # The ONE delivery of this frame to the analyzer (see fftFrameReady). Live, it is queued to
            # the main thread; in tests and inline file playback the emitter and receiver share a thread,
            # so Qt delivers it synchronously.
            self.proc_thread.fftFrameReady.emit(mag_y_db, peak_db, fps, sample_dt, processing_dt)

    # MARK: - Calibration
    #
    # The engine owns the calibration, as Swift's RealtimeFFTAnalyzer does: it holds the active
    # profile, computes the per-bin corrections from its own bins, and applies them. The analyzer
    # only reads them.

    @property
    def active_calibration(self):
        """The active microphone calibration, or None. Mirrors Swift ``activeCalibration``."""
        with self._settings_lock:
            return self._calibration_profile

    def set_active_calibration(self, cal) -> None:
        """Make *cal* (None: no calibration) the user's choice and save it — as the last chosen (the
        global active id) and for the selected input, so it loads whenever that input is selected.

        Mirrors Swift assigning ``activeCalibration``, whose didSet saves both. A device's own
        calibration loading when the input switches (``set_calibration_without_saving_device_mapping``)
        and a file playback's (``set_temporary_calibration``) save nothing.
        """
        from guitar_tap.models.microphone_calibration import CalibrationStorage

        self._apply_calibration(cal)
        cal_id = cal.id if cal is not None else None
        CalibrationStorage.set_active_calibration_id(cal_id)
        device = self._selected_input_device
        if device is not None:
            # The map is keyed by device name; the lookup tries the fingerprint first, so any
            # fingerprint entry for this device is removed.
            CalibrationStorage.set_calibration_for_device(device.fingerprint, None)
            CalibrationStorage.set_calibration_for_device(device.name, cal_id)

    def set_calibration_without_saving_device_mapping(self, cal) -> None:
        """Apply *cal* without saving it — a device's own calibration, loaded when it is selected.
        Mirrors Swift ``setCalibrationWithoutSavingDeviceMapping(_:)``."""
        self._apply_calibration(cal)

    def set_temporary_calibration(self, cal) -> None:
        """Apply *cal* for a file playback, saving nothing; the caller restores the previous one.
        Mirrors Swift ``setTemporaryCalibration(_:)``."""
        self._apply_calibration(cal)

    def _apply_calibration(self, cal) -> None:
        with self._settings_lock:
            self._calibration_profile = cal
            self._calibration = None
            self._calibration_rate = None

    @property
    def calibration_corrections(self) -> "npt.NDArray | None":
        """The active calibration's per-bin dB corrections, or None without one.

        Computed by the engine from its own bin frequencies — ``i · rate / fft_size``, the exact
        frequency of each bin — and computed again when the sample rate changes. Mirrors Swift
        ``calibrationCorrections`` (``updateCalibrationCorrections``).
        """
        with self._settings_lock:
            if self._calibration_profile is None:
                return None
            if self._calibration is None or self._calibration_rate != self.rate:
                bins = np.arange(self.h_fft_size) * float(self.rate) / self.fft_size
                self._calibration = self._calibration_profile.interpolate_to_bins(bins)
                self._calibration_rate = self.rate
            return self._calibration

    # MARK: - Gated FFT Compute

    def compute_gated_fft(
        self,
        samples: "npt.NDArray[np.float32]",
        sample_rate: float,
    ) -> "tuple[list[float], list[float]]":
        """Run a one-shot Hann-windowed FFT on a pre-captured buffer; return dB
        magnitudes and a matching frequency axis.

        Unlike the live per-frame path (rectangular window) this method:
          - Accepts an arbitrary-length buffer (zero-padded to the next power of
            two, capped at 32768 samples for ~1.35 Hz/bin resolution at 44.1 kHz).
          - Applies a periodic Hann window spanning the PADDED length (below).
          - Returns raw dB values (not published), one-sided with interior bins
            doubled and normalised by 1/fft_size.
          - Applies microphone calibration at the bin frequencies.
          - Returns an empty spectrum for fewer than two samples.

        The window is the PERIODIC unit-peak Hann w[n] = 0.5·(1 − cos(2πn/N)), which
        is what Swift's vDSP_HANN_DENORM produces — NOT np.hanning, which is the
        symmetric 0.5·(1 − cos(2πn/(N−1))). The two differ by less than most tolerances
        can see, so a window test in all three editions pins it. (Nor HANN_NORM, which would inflate magnitudes
        by +4.26 dB via its √(8/3) energy normalisation.)

        The window spans the padded length, not the captured one. At 48 kHz the 0.4 s
        capture is 19200 of 32768 samples, so its last sample is weighted ≈0.93, not
        tapered to zero. For a steady tone that is a hard edge with poor sidelobes (a
        tone 7 Hz from a stronger one picks up its leakage at about −21 dB). For a TAP it
        works: the ring-out decays, so the signal supplies its own end taper, and the
        abrupt onset — 0.1 s in, after the pre-onset silence — is weighted ≈0.2. Tested
        against decaying modes at known frequencies, this measures a tap's frequency as
        well as or better than a Hann spanning only the captured samples.
        Because the capture fills a different share of the padded window at each sample
        rate, the window's gain differs with it: about −10.8 dB at 44.1 kHz, −9.5 dB at
        48 kHz, and −6.0 dB at 96 kHz, where the capture exceeds 32768 samples and is
        truncated to it.

        Args:
            samples:     PCM samples captured after tap detection.
            sample_rate: Hardware sample rate at capture time, in Hz.

        Returns:
            (magnitudes, frequencies) in dB and Hz.

        Mirrors Swift RealtimeFFTAnalyzer.computeGatedFFT(samples:sampleRate:).
        """
        from numpy.fft import fft

        # Fewer than two samples is not a spectrum; callers treat an empty one as a failed
        # capture. Mirrors Swift's guard.
        n = len(samples)
        if n < 2:
            return [], []

        MAX_FFT = 32768
        fft_size = 1
        while fft_size < n:
            fft_size <<= 1
        fft_size = min(fft_size, MAX_FFT)

        padded = np.zeros(fft_size, dtype=np.float64)
        copy_count = min(n, fft_size)
        padded[:copy_count] = samples[:copy_count]

        # The periodic Hann — Swift's vDSP_HANN_DENORM — not np.hanning's symmetric form.
        window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(fft_size) / fft_size)
        padded *= window

        complex_fft = fft(padded)
        half_n = fft_size // 2
        abs_fft = np.abs(complex_fft[:half_n])
        abs_fft /= fft_size
        abs_fft[1:] *= 2.0

        # NO epsilon clamp. A bin with no energy is -inf, which is what Swift's vDSP_vdbcon
        # produces and what the Peak readout should say: -inf means "nothing at all", and it has to
        # stay distinguishable from -100 dB, which is a REAL level a live UMIK-1 reaches in a quiet
        # room. A clamp to float64 epsilon would put -313.0 dB on screen instead — a precise-looking
        # number for the absence of a signal.
        #
        # Safe because no axis is derived from the data: every setYRange call uses explicit bounds
        # (settings, a fixed -100..0, or a loaded measurement's saved range), so -inf bins clip off
        # the bottom rather than collapsing the scale. errstate only silences numpy's per-frame
        # divide-by-zero warning; the -inf is the intended result.
        with np.errstate(divide="ignore"):
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
