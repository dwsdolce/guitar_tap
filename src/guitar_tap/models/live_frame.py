# @parity model/live-frame tests=test/live-frame
"""
LiveFrame — the latest live FFT frame: its spectrum, peak, readout level and processing times.

Owned by ``RealtimeFFTAnalyzer`` as ``frame`` and announced once per frame, several times a second. It is an
object of its own so that only what draws a frame hears of it — the spectrum, the status bar's readouts, the
metrics panel — and the analyzer, which takes each frame from it. Announced by the analyzer, every frame
would reach every view that listens to the analyzer.

Mirrors Swift ``LiveFrame`` (Models/LiveFrame.swift) and web ``LiveFrame``.
"""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore


class LiveFrame(QtCore.QObject):
    """The latest live FFT frame. Mirrors Swift ``LiveFrame``."""

    # A new frame: its values are this object's attributes. Swift's objectWillChange.
    frameChanged: QtCore.Signal = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        # The frame's spectrum in dB, one per bin of the engine's frequencies. Swift ``magnitudes``.
        self.magnitudes: np.ndarray = np.array([], dtype=np.float64)
        # The loudest bin's frequency in Hz, and its magnitude in dB. Swift ``peakFrequency`` /
        # ``peakMagnitude``; -100 dB @ 0 Hz before the first frame and after a stop.
        self.peak_frequency: float = 0.0
        self.peak_magnitude: float = -100.0
        # The input level as a readout, at the frame rate. Swift ``displayLevelDB``.
        self.display_level_db: float = -100.0
        # Time taken to process the frame, and the average over the last several frames, in ms.
        # Swift ``processingTimeMs`` / ``avgProcessingTimeMs``.
        self.processing_time_ms: float = 0.0
        self.avg_processing_time_ms: float = 0.0
