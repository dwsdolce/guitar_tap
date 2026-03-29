"""
    State machine for plate / brace material tap analysis.

    Mirrors Swift's MaterialTapPhase state machine:

    Brace (1 tap):
        IDLE → WAITING_L → COMPLETE
        analysisComplete emits (f_long, 0.0)

    Plate (2 taps):
        IDLE → WAITING_L → WAITING_C → COMPLETE
        analysisComplete emits (f_long, f_cross)

    The caller feeds each detected tap's linear magnitude spectrum via
    on_tap().  HPS is used to extract the dominant fundamental frequency
    from each tap.
"""

from __future__ import annotations

from enum import Enum, auto

import numpy as np
import numpy.typing as npt
from PyQt6 import QtCore

import freq_anal as f_a


class PlateCapture(QtCore.QObject):
    """Plate / brace fundamental-frequency capture via HPS."""

    stateChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    fLCaptured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    fCCaptured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    analysisComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float)  # fL, fC

    class State(Enum):
        IDLE = auto()
        WAITING_L = auto()
        WAITING_C = auto()
        COMPLETE = auto()

    def __init__(
        self,
        sample_freq: int = 48000,
        n_f: int = 65536,
        f_min: float = 50.0,
        f_max: float = 2000.0,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sample_freq = sample_freq
        self._n_f = n_f
        self._f_min = f_min
        self._f_max = f_max
        self._state = self.State.IDLE
        self._is_brace: bool = False
        self._f_long: float = 0.0
        self._f_cross: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self, is_brace: bool = False) -> None:
        """Begin longitudinal tap capture.

        Args:
            is_brace: True for brace (1 tap: longitudinal only).
                      False for plate (2 taps: longitudinal + cross-grain).
        """
        self._is_brace = is_brace
        self._f_long = 0.0
        self._f_cross = 0.0
        self._state = self.State.WAITING_L
        self.stateChanged.emit("Tap long-grain (L) direction…")

    def reset(self) -> None:
        """Return to idle and clear captured values."""
        self._state = self.State.IDLE
        self._f_long = 0.0
        self._f_cross = 0.0
        self.stateChanged.emit("")

    def on_tap(self, mag_linear: npt.NDArray) -> None:
        """Call this when the tap detector fires with the linear FFT spectrum.

        Extracts the dominant frequency via HPS and advances the state machine.
        """
        if self._state not in (self.State.WAITING_L, self.State.WAITING_C):
            return

        freq = f_a.hps_peak_freq(
            mag_linear,
            self._sample_freq,
            self._n_f,
            f_min=self._f_min,
            f_max=self._f_max,
        )
        if freq <= 0:
            return

        if self._state == self.State.WAITING_L:
            self._f_long = freq
            self.fLCaptured.emit(freq)
            if self._is_brace:
                # Brace: longitudinal only — done
                self._state = self.State.COMPLETE
                self.stateChanged.emit(f"L: {freq:.1f} Hz \u2014 complete")
                self.analysisComplete.emit(self._f_long, 0.0)
            else:
                self._state = self.State.WAITING_C
                self.stateChanged.emit(
                    f"L: {freq:.1f} Hz \u2014 now tap cross-grain (C) direction\u2026"
                )
        else:  # WAITING_C (plate only)
            self._f_cross = freq
            self.fCCaptured.emit(freq)
            self._state = self.State.COMPLETE
            self.stateChanged.emit(
                f"L: {self._f_long:.1f} Hz  C: {freq:.1f} Hz \u2014 complete"
            )
            self.analysisComplete.emit(self._f_long, self._f_cross)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_active(self) -> bool:
        """True while waiting for L or C tap."""
        return self._state in (self.State.WAITING_L, self.State.WAITING_C)

    @property
    def f_long(self) -> float:
        return self._f_long

    @property
    def f_cross(self) -> float:
        return self._f_cross
