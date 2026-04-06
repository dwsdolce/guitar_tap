"""
FftProcessingThread — off-main-thread audio DSP loop.

Previously lived in views/fft_canvas.py.  Moved here so the model layer
owns its own processing pipeline, matching Swift's architecture where all
audio analysis logic is contained within TapToneAnalyzer and its extensions,
not in any view class.

Swift equivalent: the per-frame audio processing that this thread performs
corresponds to the AVAudioEngine tap callback installed by RealtimeFFTAnalyzer
on the input node, together with the frame-processing logic inside
TapToneAnalyzer+Control.swift and TapToneAnalyzer+TapDetection.swift.
Python splits this into an explicit QThread because PortAudio callbacks are
short and cannot block; the actual DSP work is deferred to this thread so the
mic callback stays fast.

Mirrors Swift TapToneAnalyzer's audio processing pipeline:
  - Swift TapToneAnalyzer+Control.swift startTapSequence() / AVAudioEngine tap
  - Swift TapToneAnalyzer+TapDetection.swift tap detection state machine
  - Swift TapToneAnalyzer+DecayTracking.swift decay tracker
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np
import numpy.typing as npt
from PySide6 import QtCore

import models.realtime_fft_analyzer as _rfa
from models.tap_tone_analyzer_tap_detection import TapDetector
from models.tap_tone_analyzer_decay_tracking import DecayTracker


class FftProcessingThread(QtCore.QThread):
    """Audio processing thread — all DSP runs here, off the main/GUI thread.

    Drains mic.queue chunk-by-chunk, maintains the ring buffer, runs the
    tap detector and decay tracker, computes the FFT, and emits results to
    the main thread via Qt signals.

    Mirrors the audio processing pipeline in Swift's TapToneAnalyzer:
    - Ring buffer ↔ Swift's circular pre-roll buffer
    - TapDetector ↔ Swift TapToneAnalyzer+TapDetection hysteresis state machine
    - DecayTracker ↔ Swift TapToneAnalyzer+DecayTracking ring-out tracker
    - dft_anal call ↔ Swift RealtimeFFTAnalyzer AVAudioEngine FFT node

    Python-only: Swift uses AVAudioEngine taps on the main audio graph rather
    than a separate QThread.
    """

    # MARK: - Signals

    # (mag_y_db, mag_y, tap_fired, tap_amp, fps, sample_dt, processing_dt)
    # Mirrors Swift TapToneAnalyzer fftFrameReady notification.
    fftFrameReady: QtCore.Signal = QtCore.Signal(
        np.ndarray, np.ndarray, bool, int, float, float, float
    )

    # Per-chunk RMS level (plate/brace) or per-FFT peak level (guitar), 0-100 scale.
    # Mirrors Swift TapToneAnalyzer @Published inputLevelDB.
    rmsLevelChanged: QtCore.Signal = QtCore.Signal(int)

    # Ring-out time in seconds, relayed from DecayTracker.
    # Mirrors Swift TapToneAnalyzer+DecayTracking ringOutTime.
    ringOutMeasured: QtCore.Signal = QtCore.Signal(float)

    # (captured, total) tap count — emitted by TapToneAnalyzer, not here.
    # Declared for symmetry; not emitted from this thread.
    tapCountChanged: QtCore.Signal = QtCore.Signal(int, int)

    # MARK: - Initialization

    def __init__(
        self,
        mic: "_rfa.RealtimeFFTAnalyzer",
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
        # Mirrors Swift's circular pre-roll buffer used for gated FFT capture.
        self._audio_ring: npt.NDArray[np.float32] = np.zeros(
            mic.m_t, dtype=np.float32
        )
        self._ring_fill: int = 0
        self._samples_since_last_fft: int = 0

        # MARK: - Tap / Decay State

        from models.tap_display_settings import TapDisplaySettings as _tds
        self._tap_detector = TapDetector(
            tap_threshold=_tds.tap_detection_threshold(),
            hysteresis_margin=_tds.hysteresis_margin(),
            mode=TapDetector.MODE_GUITAR,
            parent=self,
        )
        self._decay_tracker = DecayTracker(parent=self)

        # tapDetected fires from within run() (background thread) — use
        # DirectConnection so _tap_pending is set synchronously in the same thread.
        self._tap_detector.tapDetected.connect(
            self._on_tap_detected, QtCore.Qt.ConnectionType.DirectConnection
        )
        # ringOutMeasured fires from the background thread; relay via QueuedConnection.
        self._decay_tracker.ringOutMeasured.connect(
            self.ringOutMeasured, QtCore.Qt.ConnectionType.QueuedConnection
        )

        self._tap_pending: bool = False
        self._last_detector_amp: int = 0

        # MARK: - Thread-Safe Settings

        # Settings protected by a lock (written from main thread, read from run()).
        self._settings_lock = threading.Lock()
        self._is_measurement_complete: bool = False
        self._is_guitar: bool = True
        self._calibration: npt.NDArray | None = None

    # MARK: - Internal Slot

    def _on_tap_detected(self) -> None:
        """Called from run() via DirectConnection when tap detector fires."""
        self._tap_pending = True
        self._decay_tracker.start(self._last_detector_amp)

    # MARK: - QThread.run() — the processing loop

    def run(self) -> None:
        """Main processing loop — runs on the background thread.

        Drains mic.queue, maintains the ring buffer, computes per-chunk level,
        fires the tap detector, and emits fftFrameReady for each FFT frame.

        Mirrors Swift's AVAudioEngine input tap callback + TapToneAnalyzer
        frame processing logic.
        """
        lastupdate = time.time()
        while not self._stop_event.is_set():
            try:
                chunk = self._mic.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Snapshot mutable settings under lock — avoid holding the lock
            # during the expensive DSP computation below.
            with self._settings_lock:
                is_frozen = self._is_measurement_complete
                is_guitar = self._is_guitar
                calibration = self._calibration

            enter_now = time.time()
            n = len(chunk)

            # Update ring buffer — shift old samples out, append new samples.
            self._audio_ring = np.concatenate(
                [self._audio_ring[n:], chunk[:n].astype(np.float32)]
            )
            self._ring_fill = min(self._ring_fill + n, self._mic.m_t)
            self._samples_since_last_fft += n

            # Per-chunk RMS level — used for plate/brace tap detection.
            # Mirrors Swift TapToneAnalyzer inputLevelDB computation.
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            level_db = 20.0 * np.log10(max(rms, 1e-10))
            rms_amp = int(level_db + 100.0)

            if not is_guitar:
                # Plate/brace mode: tap detection and level reporting use RMS.
                self._last_detector_amp = rms_amp
                self.rmsLevelChanged.emit(rms_amp)
                if not is_frozen:
                    self._tap_detector.update(rms_amp)
                self._decay_tracker.update(rms_amp)

            # Only compute a new FFT once m_t new samples have accumulated.
            if self._samples_since_last_fft < self._mic.m_t:
                continue
            self._samples_since_last_fft -= self._mic.m_t

            sample_dt = enter_now - lastupdate
            lastupdate = enter_now

            # FFT — mirrors Swift RealtimeFFTAnalyzer FFT node output.
            mag_y_db, mag_y = _rfa.dft_anal(
                self._audio_ring, self._mic.window_fcn, self._mic.fft_size
            )
            if calibration is not None:
                mag_y_db = mag_y_db + calibration

            if is_guitar:
                # Guitar mode: tap detection and level reporting use FFT peak.
                fft_peak_amp = int(np.max(mag_y_db) + 100.0)
                self._last_detector_amp = fft_peak_amp
                self.rmsLevelChanged.emit(fft_peak_amp)
                if not is_frozen:
                    self._tap_detector.update(fft_peak_amp)
                self._decay_tracker.update(fft_peak_amp)

            tap_fired = self._tap_pending and not is_frozen
            if self._tap_pending and is_frozen:
                print(
                    "TAP_DEBUG [run] tap_pending=True but is_measurement_complete=True"
                    " → tap suppressed"
                )
            if tap_fired:
                print("TAP_DEBUG [run] tap_fired=True → forwarding to _do_capture_tap")
                self._tap_pending = False

            exit_now = time.time()
            processing_dt = exit_now - enter_now
            fps = 1.0 / max(sample_dt, 1e-12)

            self.fftFrameReady.emit(
                mag_y_db, mag_y, tap_fired, self._last_detector_amp,
                fps, sample_dt, processing_dt,
            )

    # MARK: - Public API (safe to call from main thread)

    def stop(self) -> None:
        """Signal the run() loop to exit."""
        self._stop_event.set()

    def reset_state(self) -> None:
        """Reset ring buffer and tap detector state; call before start()."""
        self._audio_ring = np.zeros(self._mic.m_t, dtype=np.float32)
        self._ring_fill = 0
        self._samples_since_last_fft = 0
        self._tap_pending = False
        self._last_detector_amp = 0
        self._stop_event.clear()
        self._tap_detector.reset()

    def set_measurement_complete(self, value: bool) -> None:
        """Freeze or unfreeze tap detection from the main thread."""
        with self._settings_lock:
            self._is_measurement_complete = value

    def set_measurement_type(self, is_guitar: bool) -> None:
        """Switch between guitar (FFT-peak) and plate/brace (RMS) tap detection."""
        with self._settings_lock:
            self._is_guitar = is_guitar
        mode = TapDetector.MODE_GUITAR if is_guitar else TapDetector.MODE_PLATE_BRACE
        self._tap_detector.set_mode(mode)

    def set_calibration(self, arr: npt.NDArray | None) -> None:
        """Update the per-bin dB calibration correction array."""
        with self._settings_lock:
            self._calibration = arr

    def set_tap_threshold(self, value: int) -> None:
        """Update the tap-trigger threshold (0-100 scale)."""
        self._tap_detector.set_tap_threshold(value)

    def set_hysteresis_margin(self, value: float) -> None:
        """Update the hysteresis margin (dB below trigger for reset)."""
        self._tap_detector.set_hysteresis_margin(value)

    def pause_tap_detection(self) -> None:
        """Pause tap detection (e.g. while a dialog is open)."""
        self._tap_detector.pause()

    def resume_tap_detection(self) -> None:
        """Resume tap detection."""
        self._tap_detector.resume()

    def reset_tap_detector(self) -> None:
        """Clear pending tap state and reset the detector."""
        self._tap_pending = False
        self._tap_detector.reset()

    def cancel_tap_sequence_in_thread(self) -> None:
        """Cancel any pending tap sequence from within the processing thread context."""
        self._tap_pending = False
        self._tap_detector.cancel()
