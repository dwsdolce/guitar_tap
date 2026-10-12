# @parity model/input-level
"""
InputLevel — the input level of the latest audio buffer: its RMS level, the recent peak and clipping.

Owned by ``RealtimeFFTAnalyzer`` as ``level`` and updated on every audio buffer, many times a second.
It is an object of its own so that only the threshold slider's meter observes it: the level is the
one value the engine changes on every buffer, and nothing else need hear of it.

Mirrors Swift ``InputLevel`` (Models/InputLevel.swift) and web ``InputLevel``.
"""

from __future__ import annotations

from PySide6 import QtCore


class InputLevel(QtCore.QObject):
    """The latest audio buffer's input level. Mirrors Swift ``InputLevel``."""

    # The per-buffer RMS level in dB — Swift's published ``inputLevelDB``. For the UI (the threshold
    # meter) ONLY: tap detection takes the level from the engine's direct ``rms_level_handler``, as
    # Swift's does from ``rmsLevelHandler``, so each chunk reaches detection exactly once.
    inputLevelChanged: QtCore.Signal = QtCore.Signal(float)

    # Edge-triggered clipping — Swift's published ``isClipping``.
    clippingChanged: QtCore.Signal = QtCore.Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        # The last chunk's level in dBFS (silence -100), for detection, the meter and decay.
        # Swift ``inputLevelDB``.
        self.input_level_db: float = -100.0
        # True while any chunk in the last clip-hold period reached full scale. Swift ``isClipping``.
        self.is_clipping: bool = False
        # The highest level of the last peak-hold period, in dBFS — the tap's peak for decay
        # tracking. Swift ``recentPeakLevelDB``.
        self.recent_peak_level_db: float = -100.0
