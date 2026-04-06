"""
Real-time FFT audio analyser — mirrors Swift RealtimeFFTAnalyzer.swift.

The Swift RealtimeFFTAnalyzer class is split across four Swift files:
  RealtimeFFTAnalyzer.swift                — class declaration, init/deinit
  RealtimeFFTAnalyzer+EngineControl.swift  — start() / stop()
  RealtimeFFTAnalyzer+FFTProcessing.swift  — performFFT, computeGatedFFT,
                                             peak detection, parabolic interp, Q-factor, HPS
  RealtimeFFTAnalyzer+DeviceManagement.swift — device enumeration, CoreAudio /
                                              AVAudioSession listeners, setInputDevice

This Python package mirrors that structure using two modules:

  realtime_fft_analyzer.py               → RealtimeFFTAnalyzer class
      mirrors RealtimeFFTAnalyzer.swift + +EngineControl.swift + +DeviceManagement.swift
      Also contains _FftProcessingThread, a Python-only private class that handles
      off-main-thread DSP.  Swift uses AVAudioEngine taps on the main audio graph
      instead; this class has no Swift counterpart and is an implementation detail
      of RealtimeFFTAnalyzer, not a separate model entity.

  realtime_fft_analyzer_fft_processing.py → module-level FFT functions
      mirrors RealtimeFFTAnalyzer+FFTProcessing.swift

This file (realtime_fft_analyzer.py) contains:
  - The RealtimeFFTAnalyzer class (audio capture, device management, start/stop)
  - _FftProcessingThread (Python-only private inner class — off-main-thread DSP loop)
  - Re-export of all FFT functions from realtime_fft_analyzer_fft_processing for
    backward compatibility (callers that do `import models.realtime_fft_analyzer as f_a`
    and call `f_a.dft_anal(...)` continue to work unchanged)
  - Microphone alias for backward compatibility with existing import sites

Python ↔ Swift correspondence:
  RealtimeFFTAnalyzer class  ↔  RealtimeFFTAnalyzer class
    __init__ / close         ↔  init / deinit
    start / stop             ↔  start() / stop()
    set_device               ↔  setInputDevice(_:)
    reinitialize_portaudio   ↔  (PortAudio-specific; no Swift equivalent)
    _start_hotplug_monitor   ↔  registerMacOSHardwareListener /
                                 iOS routeChangeNotification observer
    _start_coreaudio_monitor ↔  AudioObjectAddPropertyListener block
    _start_windows_monitor   ↔  CM_Register_Notification
    _start_linux_monitor     ↔  (Linux-only; no Swift equivalent)
    get_frames / queue       ↔  rawSampleHandler / inputBuffer
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

# ── FFT function re-exports (backward compatibility) ─────────────────────────
# Existing code that does:
#   import models.realtime_fft_analyzer as f_a
#   f_a.dft_anal(...)
# continues to work unchanged.

from .realtime_fft_analyzer_fft_processing import (
    is_power2,
    dft_anal,
    peak_detection,
    peak_interp,
    peak_q_factor,
    hps_peak_freq,
    Float64_1D,
)

# ── RealtimeFFTAnalyzer / device management ───────────────────────────────────

import platform
import queue
import threading
import atexit
import time
from typing import Callable

import sounddevice as sd
import numpy as np
import numpy.typing as npt
from PySide6 import QtCore

from .realtime_fft_analyzer_device_management import RealtimeFFTAnalyzerDeviceManagementMixin

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
    """Audio processing thread — continuous FFT and raw-sample delivery.

    Drains mic.queue chunk-by-chunk, maintains the ring buffer, computes the
    FFT and per-chunk RMS level, calls mic.raw_sample_handler on every chunk,
    and emits results to the main thread via Qt signals.
    Tap detection, decay tracking, and gated capture are NOT performed here.

    Mirrors the audio delivery pipeline in Swift's RealtimeFFTAnalyzer:
    - Ring buffer           ↔ Swift's inputBuffer accumulation in processAudioBuffer(_:)
    - dft_anal call         ↔ Swift performFFT(on:) via AVAudioEngine FFT node
    - fftFrameReady         ↔ Swift @Published magnitudes / inputLevelDB publishers
    - recent_peak_level_db  ↔ Swift recentPeakLevelDB rolling-max property
    - raw_sample_handler    ↔ Swift rawSampleHandler callback (delivered per-chunk)
    - gatedCaptureComplete  ↔ delivery signal for finishGatedFFTCapture (emitted by
                               TapToneAnalyzer._accumulate_gated_samples when window fills)

    Python-only: Swift uses AVAudioEngine taps on the main audio graph rather
    than a separate QThread.
    """

    # MARK: - Signals

    # (mag_y_db, mag_y, fft_peak_amp, rms_amp, fps, sample_dt, processing_dt)
    # fft_peak_amp: FFT peak level on 0-100 scale (dBFS + 100), used by guitar mode.
    # rms_amp:      Per-chunk RMS level on 0-100 scale (dBFS + 100), used by plate/brace.
    # Mirrors Swift RealtimeFFTAnalyzer @Published magnitudes and inputLevelDB.
    fftFrameReady: QtCore.Signal = QtCore.Signal(
        np.ndarray, np.ndarray, int, int, float, float, float
    )

    # Per-chunk RMS level (0-100 scale) emitted every audio chunk (not just per-FFT).
    # Mirrors Swift RealtimeFFTAnalyzer @Published inputLevelDB.
    rmsLevelChanged: QtCore.Signal = QtCore.Signal(int)

    # Emitted when a gated capture window fills: (samples: ndarray, sample_rate: float, phase: object).
    # Delivered to the main thread via Qt queued connection.
    # Mirrors Swift's DispatchQueue.main.async { finishGatedFFTCapture(samples:sampleRate:phase:) }.
    gatedCaptureComplete: QtCore.Signal = QtCore.Signal(object, float, object)

    # MARK: - Initialization

    def __init__(
        self,
        mic: "RealtimeFFTAnalyzer",
        parent: QtCore.QObject | None = None,
    ) -> None:
        """
        Args:
            mic:    RealtimeFFTAnalyzer — supplies audio via mic.queue and owns
                    FFT configuration (mic.fft_size, mic.window_fcn, mic.m_t).
            parent: Qt parent object (TapToneAnalyzer).
        """
        super().__init__(parent)

        self._mic = mic
        self._stop_event = threading.Event()

        # MARK: - Ring Buffer State

        # Circular ring buffer holding the most recent m_t audio samples.
        # Mirrors Swift's inputBuffer accumulation in processAudioBuffer(_:).
        self._audio_ring: npt.NDArray[np.float32] = np.zeros(
            mic.m_t, dtype=np.float32
        )
        self._ring_fill: int = 0
        self._samples_since_last_fft: int = 0

        # MARK: - Thread-Safe Settings

        # Settings protected by a lock (written from main thread, read from run()).
        self._settings_lock = threading.Lock()
        self._calibration: npt.NDArray | None = None

        # MARK: - Recent Peak Level (mirrors Swift RealtimeFFTAnalyzer.recentPeakLevelDB)

        # Rolling maximum RMS level over the last 0.5 s, protected by a dedicated lock.
        # Mirrors Swift recentPeakLevelDB which holds the max level over the last 0.5 s
        # so that tapPeakLevel captures the actual tap peak even when FFT detection is delayed.
        self._recent_peak_lock = threading.Lock()
        self._recent_peak_db: float = -100.0       # current rolling max (dBFS)
        self._recent_peak_window: float = 0.5      # rolling window in seconds
        self._recent_peak_history: list = []       # [(timestamp, level_db), ...]

        # NOTE: The pre-roll buffer and gated accumulator previously lived here.
        # They have been moved to TapToneAnalyzer (as _pre_roll_buf, _gated_accum,
        # etc.) and are maintained by TapToneAnalyzer._accumulate_gated_samples(),
        # which is called via mic.raw_sample_handler on every audio chunk.
        # This matches Swift where TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:)
        # owns the buffers rather than RealtimeFFTAnalyzer.
        #
        # gatedCaptureComplete signal remains here as the delivery mechanism —
        # _accumulate_gated_samples emits it when the window fills so that the
        # queued Qt connection delivers finishGatedFFTCapture on the main thread.

        # (gatedCaptureComplete is declared as a class-level Qt Signal above)

    # MARK: - QThread.run() — the processing loop

    def run(self) -> None:
        """Main processing loop — runs on the background thread.

        Drains mic.queue, maintains the ring buffer, computes per-chunk RMS
        level, and emits fftFrameReady for each FFT frame.

        Mirrors Swift's AVAudioEngine input tap callback + processAudioBuffer(_:)
        accumulation logic.  Tap detection is performed on the main thread
        inside TapToneAnalyzer.on_fft_frame().
        """
        lastupdate = time.time()
        while not self._stop_event.is_set():
            try:
                chunk = self._mic.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Snapshot calibration under lock — avoid holding during DSP.
            with self._settings_lock:
                calibration = self._calibration

            enter_now = time.time()
            n = len(chunk)
            chunk_f32 = chunk[:n].astype(np.float32)

            # Update ring buffer — shift old samples out, append new samples.
            # Mirrors Swift inputBuffer accumulation in processAudioBuffer(_:).
            self._audio_ring = np.concatenate(
                [self._audio_ring[n:], chunk_f32]
            )
            self._ring_fill = min(self._ring_fill + n, self._mic.m_t)
            self._samples_since_last_fft += n

            # Deliver every raw audio chunk to the raw_sample_handler if set.
            # Mirrors Swift RealtimeFFTAnalyzer calling rawSampleHandler on every
            # audio buffer on audioProcessingQueue.
            # TapToneAnalyzer sets this to _accumulate_gated_samples so it can
            # own the pre-roll buffer and gated accumulator directly.
            handler = self._mic.raw_sample_handler
            if handler is not None:
                handler(chunk_f32, float(self._mic.rate))

            # Per-chunk RMS level — used for plate/brace tap detection and decay.
            # Mirrors Swift RealtimeFFTAnalyzer inputLevelDB computation.
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            level_db = 20.0 * np.log10(max(rms, 1e-10))
            rms_amp = int(level_db + 100.0)
            self.rmsLevelChanged.emit(rms_amp)

            # Update rolling recent-peak history (mirrors Swift recentPeakLevelDB).
            # Trim entries older than the window, then update the rolling max.
            with self._recent_peak_lock:
                cutoff = enter_now - self._recent_peak_window
                self._recent_peak_history = [
                    (t, v) for t, v in self._recent_peak_history if t > cutoff
                ]
                self._recent_peak_history.append((enter_now, level_db))
                self._recent_peak_db = max(
                    (v for _, v in self._recent_peak_history), default=-100.0
                )

            # Only compute a new FFT once m_t new samples have accumulated.
            if self._samples_since_last_fft < self._mic.m_t:
                continue
            self._samples_since_last_fft -= self._mic.m_t

            sample_dt = enter_now - lastupdate
            lastupdate = enter_now

            # FFT — mirrors Swift RealtimeFFTAnalyzer performFFT(on:).
            mag_y_db, mag_y = dft_anal(
                self._audio_ring, self._mic.window_fcn, self._mic.fft_size
            )
            if calibration is not None:
                mag_y_db = mag_y_db + calibration

            # FFT peak level (guitar mode) — 0-100 scale.
            fft_peak_amp = int(np.max(mag_y_db) + 100.0)

            exit_now = time.time()
            processing_dt = exit_now - enter_now
            fps = 1.0 / max(sample_dt, 1e-12)

            self.fftFrameReady.emit(
                mag_y_db, mag_y, fft_peak_amp, rms_amp,
                fps, sample_dt, processing_dt,
            )

    # MARK: - Public API (safe to call from main thread)

    def stop(self) -> None:
        """Signal the run() loop to exit."""
        self._stop_event.set()

    def reset_state(self) -> None:
        """Reset ring buffer state; call before start()."""
        self._audio_ring = np.zeros(self._mic.m_t, dtype=np.float32)
        self._ring_fill = 0
        self._samples_since_last_fft = 0
        self._stop_event.clear()
        with self._recent_peak_lock:
            self._recent_peak_db = -100.0
            self._recent_peak_history = []

    def set_calibration(self, arr: npt.NDArray | None) -> None:
        """Update the per-bin dB calibration correction array."""
        with self._settings_lock:
            self._calibration = arr

    # MARK: - Gated FFT Compute (pure function; no gated state owned here)

    def compute_gated_fft(
        self,
        samples: "npt.NDArray[np.float32]",
        sample_rate: float,
    ) -> "tuple[list[float], list[float]]":
        """Compute a Hann-windowed FFT from a gated PCM capture.

        Mirrors Swift RealtimeFFTAnalyzer.computeGatedFFT(samples:sampleRate:):
        - Zero-pads to the next power-of-two, capped at 32768 samples.
        - Applies a Hann window (suppresses sidelobes by ~31 dB vs rectangular).
        - Returns the one-sided magnitude spectrum (dBFS) and frequency axis (Hz).

        Args:
            samples:     Raw PCM samples (mono, normalised to ±1.0, float32).
            sample_rate: Hardware sample rate in Hz.

        Returns:
            (magnitudes_db, frequencies) — both as list[float].
            Returns ([], []) if samples is empty.
        """
        from scipy.signal import get_window as _get_window

        n = len(samples)
        if n == 0:
            return [], []

        # Zero-pad to the next power-of-two, capped at 32768.
        # Mirrors Swift nextPowerOfTwo(_:) with max cap.
        MAX_FFT = 32768
        fft_size = 1
        while fft_size < n:
            fft_size <<= 1
        fft_size = min(fft_size, MAX_FFT)

        # Truncate if capture is longer than fft_size.
        chunk = samples[:fft_size].astype(np.float32)
        if len(chunk) < fft_size:
            chunk = np.concatenate([chunk, np.zeros(fft_size - len(chunk), dtype=np.float32)])

        # Hann window — sidelobe suppression for accurate Q readings.
        window = _get_window("hann", fft_size).astype(np.float64)

        mag_db, _ = dft_anal(chunk, window, fft_size)

        # Build the one-sided frequency axis.
        half_n = fft_size // 2 + 1
        freqs = [float(i) * sample_rate / fft_size for i in range(half_n)]

        return list(mag_db), freqs

    @property
    def recent_peak_level_db(self) -> float:
        """Rolling maximum RMS level over the last 0.5 s, in dBFS.

        Thread-safe: safe to read from the main thread while run() updates it
        on the background thread.

        Mirrors Swift RealtimeFFTAnalyzer.recentPeakLevelDB used by
        detectTap() to set tapPeakLevel at the moment of a confirmed tap.
        """
        with self._recent_peak_lock:
            return self._recent_peak_db


class RealtimeFFTAnalyzer(RealtimeFFTAnalyzerDeviceManagementMixin):
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
      actualSampleRate, hopSizeOverlap, frequencyResolution, bandwidth
      sampleLengthSeconds, frameRate, processingTimeMs, avgProcessingTimeMs
      activeCalibration, calibrationCorrections, rawSampleHandler
      fftSetup, targetSampleRate, useHardwareSampleRate
      isRunning, microphonePermissionDenied, routeChangeRestartCount
      firstBufferReceived, fftCount, engineStartTime
    """

    # MARK: - Initialization

    def __init__(self, parent, rate: int = 44100, chunksize: int = 16384,
                 device: "AudioDevice | None" = None,
                 on_devices_changed: Callable[[], None] | None = None,
                 on_calibration_changed: "Callable[[object | None], None] | None" = None,
                 fft_size: int = 16384):
        """Create a new real-time FFT analyser and open the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.init(fftSize:targetSampleRate:useHardwareSampleRate:).
        The Swift initialiser creates the AVAudioEngine and registers device listeners;
        this Python initialiser opens a sounddevice InputStream and starts the hot-plug monitor.

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
            fft_size:                FFT window size (power of 2).
                                     Mirrors Swift RealtimeFFTAnalyzer.fftSize.
        """
        from .audio_device import AudioDevice as _AudioDevice
        from scipy.signal import get_window as _get_window

        if platform.system() == "Darwin":
            mac_access.MacAccess(parent)

        # Python-only: PortAudio session state
        self.rate: int = int(device.sample_rate) if device else rate
        self.chunksize: int = chunksize
        self.device_index: int | None = device.index if device else None

        # MARK: - FFT Configuration (mirrors Swift RealtimeFFTAnalyzer)

        # FFT window size — must be a power of 2.
        # Mirrors Swift RealtimeFFTAnalyzer.fftSize.
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
        self.window_fcn = _get_window("boxcar", fft_size)

        # Open the sounddevice stream; Swift opens AVAudioEngine in start()
        self.stream: sd.InputStream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame)

        # Python-only: audio chunk delivery via Queue
        # Swift delivers audio via rawSampleHandler callback + inputBuffer accumulation
        self._stop_lock: threading.Lock = threading.Lock()
        self.is_stopped: bool = False
        self.queue: queue.Queue[npt.NDArray[np.float32]] = queue.Queue()

        # MARK: - Device Lists (mirrors Swift RealtimeFFTAnalyzer @Published properties)

        # Live list of available input devices.
        # Mirrors Swift RealtimeFFTAnalyzer.availableInputDevices (@Published).
        # Populated by load_available_input_devices() (see
        # realtime_fft_analyzer_device_management.py — Recommendation 2 to implement).
        # Currently empty at construction; the view layer populates it via
        # sd.query_devices() until Recommendation 2 is implemented.
        self.available_input_devices: list = []

        # The currently selected input device.
        # Mirrors Swift RealtimeFFTAnalyzer.selectedInputDevice (@Published).
        # Set by set_device() / auto-selection logic in load_available_input_devices()
        # once Recommendation 2 is implemented.
        # Currently None; set externally by TapToneAnalyzerControlMixin.set_device().
        self.selected_input_device: "AudioDevice | None" = device

        # Python-only: hot-plug monitoring threads
        self._on_devices_changed = on_devices_changed
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._start_hotplug_monitor()

        # Calibration-change callback.
        # Called by set_device() after looking up and loading the device-specific
        # calibration from CalibrationStorage.
        # Mirrors Swift selectedInputDevice.didSet → setCalibrationWithoutSavingDeviceMapping(_:).
        self._on_calibration_changed: "Callable[[object | None], None] | None" = on_calibration_changed

        # Raw-sample handler callback.
        # Mirrors Swift RealtimeFFTAnalyzer.rawSampleHandler: (([Float], Double) -> Void)?
        # Set by TapToneAnalyzer.start() to self._accumulate_gated_samples so that
        # TapToneAnalyzer owns the pre-roll buffer and gated accumulator directly,
        # matching Swift where TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:)
        # is the handler.
        self.raw_sample_handler: "Callable[[np.ndarray, float], None] | None" = None

        # Python-only: off-main-thread DSP worker.
        # Mirrors Swift's AVAudioEngine audio processing queue that delivers
        # performFFT results on a background thread before publishing @Published
        # properties on the main thread.  Created here so that TapToneAnalyzer
        # (which owns the analyzer) can access proc_thread immediately after init.
        # The parent QObject is set by TapToneAnalyzer after construction.
        self.proc_thread: _FftProcessingThread = _FftProcessingThread(mic=self)

        atexit.register(self.close)

    # MARK: - Engine Control (mirrors +EngineControl.swift)

    # pylint: disable=unused-argument
    def new_frame(self, data: np.ndarray, _frame_count, _time_info, _status) -> tuple[None, int]:
        """PortAudio stream callback — enqueues the incoming audio chunk.

        Called by PortAudio on every block of ``chunksize`` frames.
        Enqueues the first channel's samples for _FftProcessingThread (self.proc_thread).

        Python-only — Swift delivers audio via an AVAudioInputNode installTap block
        that feeds ``processAudioBuffer(_:)`` on ``audioProcessingQueue``.
        """
        with self._stop_lock:
            if self.is_stopped:
                raise sd.CallbackStop
        self.queue.put(data[:, 0])  # take first channel

        return None

    def get_frames(self) -> list[npt.NDArray[np.float32]]:
        """Non-blocking drain: returns all audio chunks currently in the queue.

        Python-only — Swift exposes audio via ``rawSampleHandler`` and the
        ``inputBuffer`` accumulation inside ``processAudioBuffer(_:)``.
        """
        frames: list[npt.NDArray[np.float32]] = []
        try:
            while True:
                frames.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return frames

    def start(self) -> None:
        """Start the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.start() (+EngineControl.swift).
        Swift starts AVAudioEngine and installs the input tap after checking
        microphone permission; Python starts the PortAudio InputStream directly.
        """
        self.stream.start()

    def stop(self) -> None:
        """Stop the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.stop() (+EngineControl.swift).
        """
        with self._stop_lock:
            self.is_stopped = True
        self.stream.stop()

    def close(self) -> None:
        """Stop the audio stream and shut down the hot-plug monitor.

        Mirrors Swift RealtimeFFTAnalyzer.deinit.
        """
        self._stop_hotplug_monitor()
        self._close_stream_only()

    # MARK: - Device Management
    # All device management methods live in realtime_fft_analyzer_device_management.py
    # via RealtimeFFTAnalyzerDeviceManagementMixin, mirroring Swift's
    # RealtimeFFTAnalyzer+DeviceManagement.swift extension.


# ── Backward-compatibility alias ─────────────────────────────────────────────
# Existing code that does:
#   from models.realtime_fft_analyzer import Microphone
# continues to work unchanged.

Microphone = RealtimeFFTAnalyzer
