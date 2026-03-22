"""
    Hysteresis-based tap detector.

    Monitors FFT peak amplitude and emits tapDetected when a tap event is
    confirmed (rising edge above threshold, with warmup, cooldown, and
    hysteresis margin to avoid false triggers).
"""

import time as _time

from PyQt6 import QtCore


class DecayTracker(QtCore.QObject):
    """Measures ring-out time after a tap.

    Call start() when a tap is detected with the peak amplitude.
    Call update() on every subsequent frame.  ringOutMeasured is emitted
    once when the amplitude drops decay_threshold_db below the tap peak.

    Amplitude uses the 0–100 scale (dB + 100) used throughout the app.
    """

    ringOutMeasured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)  # seconds

    def __init__(
        self,
        decay_threshold_db: float = 15.0,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.decay_threshold_db = decay_threshold_db
        self._tracking: bool = False
        self._peak_amplitude: float = 0.0
        self._start_time: float = 0.0

    def start(self, amplitude: int) -> None:
        """Begin tracking from this tap's peak amplitude."""
        self._peak_amplitude = float(amplitude)
        self._start_time = _time.monotonic()
        self._tracking = True

    def update(self, amplitude: int) -> None:
        """Feed the current amplitude; emits ringOutMeasured if threshold crossed."""
        if not self._tracking:
            return
        if float(amplitude) <= self._peak_amplitude - self.decay_threshold_db:
            elapsed = _time.monotonic() - self._start_time
            self._tracking = False
            self.ringOutMeasured.emit(elapsed)

    def reset(self) -> None:
        self._tracking = False


class TapDetector(QtCore.QObject):
    """State machine that detects tap events from a stream of amplitude values.

    Amplitude is on the 0–100 scale used by the rest of the app
    (0 = −100 dBFS, 100 = 0 dBFS).

    States:
        WARMUP   — ignoring input for the first `warmup_frames` frames after
                   start or reset (suppresses false triggers at startup).
        IDLE     — waiting for amplitude to rise above `tap_threshold`.
        TRIGGERED — tap confirmed; waiting for amplitude to fall below
                   `tap_threshold - hysteresis_margin` before arming again.
        COOLDOWN — brief lockout after the triggered state expires, preventing
                   double-triggers on the same tap.
    """

    tapDetected: QtCore.pyqtSignal = QtCore.pyqtSignal()

    _WARMUP = "WARMUP"
    _IDLE = "IDLE"
    _TRIGGERED = "TRIGGERED"
    _COOLDOWN = "COOLDOWN"
    _PAUSED = "PAUSED"

    def __init__(
        self,
        tap_threshold: int = 60,
        hysteresis_margin: float = 3.0,
        warmup_frames: int = 5,   # ~0.5 s at 10 fps
        cooldown_frames: int = 5, # ~0.5 s at 10 fps
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.tap_threshold: int = tap_threshold
        self.hysteresis_margin: float = hysteresis_margin
        self.warmup_frames: int = warmup_frames
        self.cooldown_frames: int = cooldown_frames

        self._state: str = self._WARMUP
        self._frame_count: int = 0
        self._pre_pause_state: str = self._WARMUP

    # ------------------------------------------------------------------ #

    @property
    def is_paused(self) -> bool:
        return self._state == self._PAUSED

    def reset(self) -> None:
        """Restart warmup (call after device change, stream restart, etc.)."""
        self._state = self._WARMUP
        self._frame_count = 0

    def set_tap_threshold(self, value: int) -> None:
        self.tap_threshold = value

    def set_hysteresis_margin(self, value: float) -> None:
        self.hysteresis_margin = max(1.0, value)

    def pause(self) -> None:
        """Pause detection — remember current state for resume."""
        if self._state != self._PAUSED:
            self._pre_pause_state = self._state
            self._state = self._PAUSED

    def resume(self) -> None:
        """Resume from a paused state."""
        if self._state == self._PAUSED:
            self._state = self._pre_pause_state

    def cancel(self) -> None:
        """Cancel the current sequence and return to IDLE (no warmup)."""
        self._state = self._IDLE
        self._frame_count = 0

    # ------------------------------------------------------------------ #

    def update(self, amplitude: int) -> None:
        """Feed the latest peak amplitude (0–100 scale).

        Emits tapDetected exactly once per confirmed tap.
        """
        if self._state == self._PAUSED:
            return

        match self._state:
            case self._WARMUP:
                self._frame_count += 1
                if self._frame_count >= self.warmup_frames:
                    self._state = self._IDLE
                    self._frame_count = 0

            case self._IDLE:
                if amplitude >= self.tap_threshold:
                    self._state = self._TRIGGERED
                    self.tapDetected.emit()

            case self._TRIGGERED:
                # Wait for signal to fall back below the lower hysteresis bound
                if amplitude < self.tap_threshold - self.hysteresis_margin:
                    self._state = self._COOLDOWN
                    self._frame_count = 0

            case self._COOLDOWN:
                self._frame_count += 1
                if self._frame_count >= self.cooldown_frames:
                    self._state = self._IDLE
                    self._frame_count = 0
