"""
DecayTracker — ring-out time measurement after a tap.

Mirrors Swift TapToneAnalyzer+DecayTracking.swift.
"""

from __future__ import annotations

import time as _time

from PyQt6 import QtCore


class DecayTracker(QtCore.QObject):
    """Measures ring-out time after a tap.

    Call start() when a tap is detected.
    Call update() on every subsequent RMS level sample.
    ringOutMeasured is emitted once when the level drops
    decay_threshold_db below the tap peak.

    Amplitude uses the 0–100 scale (dBFS + 100) used throughout the app.

    Mirrors Swift TapToneAnalyzer+DecayTracking.swift decay tracking logic.
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
