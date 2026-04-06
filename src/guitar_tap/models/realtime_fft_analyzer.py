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

class _FftProcessingThread(QtCore.QThread):
    """Audio processing thread — all DSP runs here, off the main/GUI thread.

    Drains mic.queue chunk-by-chunk, maintains the ring buffer, computes the
    FFT and per-chunk RMS level, and emits results to the main thread via Qt
    signals.  Tap detection and decay tracking are NOT performed here.

    Mirrors the audio delivery pipeline in Swift's RealtimeFFTAnalyzer:
    - Ring buffer         ↔ Swift's inputBuffer accumulation in processAudioBuffer(_:)
    - dft_anal call       ↔ Swift performFFT(on:) via AVAudioEngine FFT node
    - fftFrameReady       ↔ Swift @Published magnitudes / inputLevelDB publishers
    - recent_peak_level_db ↔ Swift recentPeakLevelDB rolling-max property

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

        # MARK: - Gated FFT Capture (mirrors Swift accumulateGatedSamples / preRollBuffer)

        # Pre-roll ring buffer: holds the most recent preRollSamples worth of raw PCM
        # so the tap attack transient (which arrives before the detection event) is
        # included in the gated capture window.
        # Mirrors Swift TapToneAnalyzer.preRollBuffer and preRollSamples.
        self._gated_lock = threading.Lock()
        self._pre_roll_seconds: float = 0.2        # 200 ms pre-roll — mirrors Swift
        self._pre_roll_samples: int = int(mic.rate * self._pre_roll_seconds)
        self._pre_roll_buf: list = []              # raw PCM samples (float32)

        # Gated capture accumulator: filled from tap-onset until gatedCaptureSamples.
        # Mirrors Swift TapToneAnalyzer.gatedAccumBuffer / gatedCaptureActive.
        self._gated_capture_active: bool = False
        self._gated_capture_samples: int = 0      # target window size in samples
        self._gated_capture_phase: object = None  # MaterialTapPhase at capture start
        self._gated_accum: list = []              # accumulated raw PCM samples
        self._gated_sample_rate: float = float(mic.rate)

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

            # Maintain the pre-roll ring buffer (mirrors Swift preRollBuffer maintenance
            # in accumulateGatedSamples — always updated, even when not capturing).
            # Gated capture accumulation also happens here when active.
            with self._gated_lock:
                self._pre_roll_buf.extend(chunk_f32.tolist())
                if len(self._pre_roll_buf) > self._pre_roll_samples:
                    self._pre_roll_buf = self._pre_roll_buf[-self._pre_roll_samples:]

                if self._gated_capture_active:
                    self._gated_accum.extend(chunk_f32.tolist())
                    if len(self._gated_accum) >= self._gated_capture_samples:
                        # Window is full — close capture and dispatch to main thread.
                        # Mirrors Swift: gatedCaptureActive = false; DispatchQueue.main.async
                        self._gated_capture_active = False
                        captured = self._gated_accum[:self._gated_capture_samples]
                        phase = self._gated_capture_phase
                        sample_rate = self._gated_sample_rate
                        self._gated_accum = []
                        # Emit on background thread; Qt queued connection delivers on main thread.
                        self.gatedCaptureComplete.emit(
                            np.array(captured, dtype=np.float32),
                            sample_rate,
                            phase,
                        )

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
        with self._gated_lock:
            self._pre_roll_buf = []
            self._gated_capture_active = False
            self._gated_accum = []

    def set_calibration(self, arr: npt.NDArray | None) -> None:
        """Update the per-bin dB calibration correction array."""
        with self._settings_lock:
            self._calibration = arr

    # MARK: - Gated FFT Capture API (mirrors Swift startGatedCapture / accumulateGatedSamples)

    def start_gated_capture(self, phase: object, duration_seconds: float = 0.4) -> None:
        """Seed the gated buffer from the pre-roll and begin accumulating samples.

        Safe to call from the main thread while run() is executing on the
        background thread; access is protected by _gated_lock.

        Mirrors Swift TapToneAnalyzer.startGatedCapture(phase:):
          - Seeds gatedAccumBuffer with preRollBuffer contents.
          - Sets gatedCaptureActive = true.
          - Stores gatedCapturePhase so finishGatedFFTCapture routes correctly.

        The gated window is:
          pre-roll (200 ms)  +  new samples until total >= gatedCaptureSamples

        When the window fills, run() emits gatedCaptureComplete(samples, rate, phase)
        which is delivered to the main thread via a Qt queued connection.

        Args:
            phase:            MaterialTapPhase being captured.
            duration_seconds: Gate window duration in seconds (default 0.4 s = 400 ms,
                              mirrors Swift gatedCaptureDuration constant).
        """
        rate = self._gated_sample_rate
        target_samples = int(rate * duration_seconds)
        window_ms = int(duration_seconds * 1000)
        print(
            f"🎯 Gated FFT capture started for phase {phase} — "
            f"{target_samples}-sample window ({window_ms} ms at {int(rate)} Hz)"
        )
        with self._gated_lock:
            # Seed accumulator with pre-roll (mirrors Swift: gatedAccumBuffer = preRollBuffer).
            self._gated_accum = list(self._pre_roll_buf)
            self._gated_capture_samples = target_samples
            self._gated_capture_phase = phase
            self._gated_capture_active = True

    def cancel_gated_capture(self) -> None:
        """Cancel any in-progress gated capture without emitting a result.

        Safe to call from the main thread.  Used by the safety-timeout path
        (mirrors Swift's 2-second timeout that calls reEnableDetectionForNextPlateTap
        when the accumulator is empty).
        """
        with self._gated_lock:
            partial = list(self._gated_accum)
            self._gated_capture_active = False
            self._gated_accum = []
        return partial  # caller decides whether to flush or discard

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


class RealtimeFFTAnalyzer:
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
                 fft_size: int = 16384):
        """Create a new real-time FFT analyser and open the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.init(fftSize:targetSampleRate:useHardwareSampleRate:).
        The Swift initialiser creates the AVAudioEngine and registers device listeners;
        this Python initialiser opens a sounddevice InputStream and starts the hot-plug monitor.

        Args:
            parent:             Parent QObject (used to anchor a MacAccess helper on macOS).
            rate:               Fallback sample rate in Hz; overridden by device.sample_rate.
            chunksize:          PortAudio block size in frames (Python-only; Swift uses 1024).
            device:             AudioDevice to open, or None for the system default.
            on_devices_changed: Callback fired on hot-plug connect/disconnect events.
                                Mirrors Swift's @Published availableInputDevices update.
            fft_size:           FFT window size (power of 2).
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

        # Python-only: hot-plug monitoring threads
        self._on_devices_changed = on_devices_changed
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._start_hotplug_monitor()

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

    # MARK: - Device Management (mirrors +DeviceManagement.swift)

    def set_device(self, device: "AudioDevice") -> None:
        """Switch to a different input device without re-checking permissions.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:) (+DeviceManagement.swift).
        Swift restarts AVAudioEngine with the new device set via CoreAudio AUHAL
        on macOS or AVAudioSession.setPreferredInput on iOS; Python closes and
        reopens the sounddevice InputStream.
        """
        from .audio_device import AudioDevice as _AudioDevice
        self._close_stream_only()
        self.device_index = device.index
        self.rate = int(device.sample_rate)
        with self._stop_lock:
            self.is_stopped = False
        self.stream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame,
        )
        self.stream.start()

    def reinitialize_portaudio(self) -> None:
        """Stop, reinitialize PortAudio (refreshes device list), then restart the stream.

        PortAudio caches the device list at Pa_Initialize() time.  Calling
        sd._terminate() + sd._initialize() forces a fresh enumeration so that
        sd.query_devices() reflects the current OS device list.

        If the current device is no longer available after reinit (it was
        unplugged), the stream is left closed; the caller is responsible for
        selecting a replacement via set_device().

        Python-only — Swift reloads the device list via loadAvailableInputDevices()
        which calls CoreAudio/AVAudioSession APIs directly.
        """
        self._close_stream_only()
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        try:
            with self._stop_lock:
                self.is_stopped = False
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=self.rate,
                dtype=np.float32,
                blocksize=self.chunksize,
                callback=self.new_frame,
            )
            self.stream.start()
        except Exception:
            # Device no longer available — stream stays closed until
            # set_device() is called with a working device index.
            pass

    # MARK: - Internal Helpers

    def _close_stream_only(self) -> None:
        """Stop and close the audio stream without touching the hot-plug monitor."""
        with self._stop_lock:
            self.is_stopped = True
        try:
            self.stream.stop()
        except Exception:
            pass
        try:
            self.stream.close()
        except Exception:
            pass

    # MARK: - Hot-plug Monitoring (mirrors +DeviceManagement.swift)
    #
    # Swift registers:
    #   macOS — AudioObjectAddPropertyListenerBlock on kAudioHardwarePropertyDevices
    #   iOS   — AVAudioSession.routeChangeNotification observer
    # Python registers the OS-appropriate listener on a background thread.

    def _notify_devices_changed(self) -> None:
        """Signal the caller that the device list has changed.

        Always invoked from a daemon thread so the OS callback returns fast.
        A brief sleep lets the OS finish its own device enumeration before
        the caller reinitializes PortAudio.

        Mirrors the body of Swift's hardwareListenerBlock / handleRouteChange
        which calls loadAvailableInputDevices() on the main thread.
        """
        if self._on_devices_changed is None:
            return
        time.sleep(0.5)
        self._on_devices_changed()

    def _start_hotplug_monitor(self) -> None:
        """Start the platform-appropriate hot-plug monitor.

        Mirrors Swift registerMacOSHardwareListener() and the iOS
        routeChangeNotification observer setup in init.
        """
        if self._on_devices_changed is None:
            return
        p = platform.system()
        if p == "Darwin":
            self._start_coreaudio_monitor()
        elif p == "Windows":
            self._start_windows_monitor()
        elif p == "Linux":
            self._start_linux_monitor()

    def _stop_hotplug_monitor(self) -> None:
        """Stop the platform-appropriate hot-plug monitor.

        Mirrors Swift unregisterMacOSHardwareListener() and the iOS
        NotificationCenter.removeObserver call in deinit.
        """
        self._monitor_stop.set()
        p = platform.system()
        if p == "Darwin":
            self._stop_coreaudio_monitor()
        elif p == "Windows":
            self._stop_windows_monitor()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

    # -- macOS: CoreAudio AudioObjectAddPropertyListener -------------------
    # Mirrors Swift registerMacOSHardwareListener() in +DeviceManagement.swift.

    def _start_coreaudio_monitor(self) -> None:
        """Register a CoreAudio property listener for device connect/disconnect.

        Watches kAudioHardwarePropertyDevices (0x64657623) on kAudioObjectSystemObject (1).
        Mirrors Swift's AudioObjectAddPropertyListenerBlock on
        kAudioObjectPropertyAddress(selector: .hardwarePropertyDevices).
        """
        import ctypes
        import ctypes.util

        _ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))

        class _PropAddr(ctypes.Structure):
            _fields_ = [
                ("mSelector", ctypes.c_uint32),
                ("mScope",    ctypes.c_uint32),
                ("mElement",  ctypes.c_uint32),
            ]

        # kAudioObjectSystemObject          = 1
        # kAudioHardwarePropertyDevices     = 'dev#' = 0x64657623
        # kAudioObjectPropertyScopeGlobal   = 'glob' = 0x676C6F62
        # kAudioObjectPropertyElementMain   = 0
        prop = _PropAddr(0x64657623, 0x676C6F62, 0)

        CB_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_int32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(_PropAddr),
            ctypes.c_void_p,
        )

        def _listener(obj, n, addrs, data):
            # Return immediately; do the real work on a daemon thread
            threading.Thread(
                target=self._notify_devices_changed, daemon=True
            ).start()
            return 0

        self._ca_cb = CB_TYPE(_listener)   # keep reference — ctypes won't
        self._ca = _ca
        self._ca_prop = prop
        _ca.AudioObjectAddPropertyListener(
            1, ctypes.byref(prop), self._ca_cb, None
        )

    def _stop_coreaudio_monitor(self) -> None:
        """Unregister the CoreAudio property listener.

        Mirrors Swift unregisterMacOSHardwareListener().
        """
        try:
            import ctypes
            self._ca.AudioObjectRemovePropertyListener(
                1, ctypes.byref(self._ca_prop), self._ca_cb, None
            )
        except Exception:
            pass

    # -- Windows: CM_Register_Notification (cfgmgr32, Windows 8+) ---------

    def _start_windows_monitor(self) -> None:
        """Register a Windows device-interface arrival/removal notification.

        Python-only — Swift targets macOS/iOS only.
        Uses CM_Register_Notification (cfgmgr32) to watch all device-interface
        events (CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 1).
        """
        import ctypes

        cfgmgr = ctypes.WinDLL("cfgmgr32")  # type: ignore[attr-defined]

        # CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 1
        # Filter on all device-interface arrivals/removals (no GUID restriction).
        class _CMNotifyFilter(ctypes.Structure):
            class _U(ctypes.Union):
                class _DevIface(ctypes.Structure):
                    _fields_ = [("ClassGuid", ctypes.c_byte * 16)]
                _fields_ = [("DeviceInterface", _DevIface)]
            _fields_ = [
                ("cbSize",     ctypes.c_ulong),
                ("Flags",      ctypes.c_ulong),
                ("FilterType", ctypes.c_ulong),
                ("Reserved",   ctypes.c_ulong),
                ("u",          _U),
            ]

        CB_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_ulong,    # DWORD return
            ctypes.c_void_p,   # HCMNOTIFICATION
            ctypes.c_void_p,   # Context
            ctypes.c_ulong,    # CM_NOTIFY_ACTION (0=arrival, 1=removal)
            ctypes.c_void_p,   # PCM_NOTIFY_EVENT_DATA
            ctypes.c_ulong,    # EventDataSize
        )

        def _cb(hnotify, context, action, event_data, data_size):
            threading.Thread(
                target=self._notify_devices_changed, daemon=True
            ).start()
            return 0

        filt = _CMNotifyFilter()
        filt.cbSize = ctypes.sizeof(_CMNotifyFilter)
        filt.FilterType = 1

        self._win_cb = CB_TYPE(_cb)    # keep reference
        self._win_hnotify = ctypes.c_void_p()
        self._win_cfgmgr = cfgmgr
        cfgmgr.CM_Register_Notification(
            ctypes.byref(filt),
            None,
            self._win_cb,
            ctypes.byref(self._win_hnotify),
        )

    def _stop_windows_monitor(self) -> None:
        """Unregister the Windows CM_Register_Notification handle.

        Python-only.
        """
        try:
            self._win_cfgmgr.CM_Unregister_Notification(self._win_hnotify)
        except Exception:
            pass

    # -- Linux: udev via pyudev --------------------------------------------
    # Python-only — Swift targets macOS/iOS only.

    def _start_linux_monitor(self) -> None:
        """Monitor Linux udev 'sound' subsystem events for device changes.

        Requires the optional ``pyudev`` package; silently disabled if absent.
        Python-only — Swift targets macOS/iOS only.
        """
        try:
            import pyudev  # optional dependency
        except ImportError:
            return  # hot-plug detection unavailable without pyudev

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="sound")

        def _run() -> None:
            monitor.start()
            while not self._monitor_stop.is_set():
                device = monitor.poll(timeout=1.0)
                if device is not None and device.action in ("add", "remove"):
                    self._notify_devices_changed()

        self._monitor_thread = threading.Thread(target=_run, daemon=True)
        self._monitor_thread.start()


# ── Backward-compatibility alias ─────────────────────────────────────────────
# Existing code that does:
#   from models.realtime_fft_analyzer import Microphone
# continues to work unchanged.

Microphone = RealtimeFFTAnalyzer
