"""
    State machine for plate / brace material tap analysis.

    Mirrors Swift's MaterialTapPhase state machine:

    Brace (1 tap):
        IDLE → WAITING_L → COMPLETE
        analysisComplete emits (f_long, 0.0, 0.0)

    Plate without FLC (2 taps):
        IDLE → WAITING_L → WAITING_C → COMPLETE
        analysisComplete emits (f_long, f_cross, 0.0)

    Plate with FLC (3 taps):
        IDLE → WAITING_L → WAITING_C → WAITING_FLC → COMPLETE
        analysisComplete emits (f_long, f_cross, f_flc)

    The caller feeds each detected tap's linear magnitude spectrum via on_tap().
    HPS is used to extract the dominant fundamental frequency from each tap.
    The dB magnitude spectrum for each phase is stored for snapshot persistence.
"""

from __future__ import annotations

from enum import Enum, auto

import numpy as np
import numpy.typing as npt
from PyQt6 import QtCore

import freq_anal as f_a


class PlateCapture(QtCore.QObject):
    """Plate / brace fundamental-frequency capture via HPS."""

    stateChanged:    QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    fLCaptured:      QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    fCCaptured:      QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    fFLCCaptured:    QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    analysisComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)  # fL, fC, fFLC

    class State(Enum):
        IDLE        = auto()
        WAITING_L   = auto()
        WAITING_C   = auto()
        WAITING_FLC = auto()
        COMPLETE    = auto()

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
        self._measure_flc: bool = False
        self._f_long: float = 0.0
        self._f_cross: float = 0.0
        self._f_flc: float = 0.0
        self._long_mag_db:  npt.NDArray | None = None
        self._cross_mag_db: npt.NDArray | None = None
        self._flc_mag_db:   npt.NDArray | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self, is_brace: bool = False, measure_flc: bool = False) -> None:
        """Begin longitudinal tap capture.

        Args:
            is_brace:    True for brace (1 tap: longitudinal only).
                         False for plate (2 or 3 taps).
            measure_flc: True to add the FLC diagonal-tap phase (plate only).
        """
        self._is_brace    = is_brace
        self._measure_flc = measure_flc and not is_brace
        self._f_long  = 0.0
        self._f_cross = 0.0
        self._f_flc   = 0.0
        self._long_mag_db  = None
        self._cross_mag_db = None
        self._flc_mag_db   = None
        self._state = self.State.WAITING_L
        self.stateChanged.emit("Tap long-grain (L) direction…")

    def reset(self) -> None:
        """Return to idle and clear captured values."""
        self._state = self.State.IDLE
        self._f_long  = 0.0
        self._f_cross = 0.0
        self._f_flc   = 0.0
        self._long_mag_db  = None
        self._cross_mag_db = None
        self._flc_mag_db   = None
        self.stateChanged.emit("")

    def on_tap(
        self,
        mag_linear: npt.NDArray,
        mag_db: npt.NDArray | None = None,
    ) -> None:
        """Call this when the tap detector fires.

        Args:
            mag_linear: Linear-scale FFT magnitude spectrum (for HPS).
            mag_db:     dB-scale FFT magnitude spectrum (stored per-phase for
                        snapshot persistence).  May be None if unavailable.
        """
        if self._state not in (
            self.State.WAITING_L,
            self.State.WAITING_C,
            self.State.WAITING_FLC,
        ):
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
            self._f_long       = freq
            self._long_mag_db  = mag_db.copy() if mag_db is not None else None
            self.fLCaptured.emit(freq)
            if self._is_brace:
                self._state = self.State.COMPLETE
                self.stateChanged.emit(f"L: {freq:.1f} Hz — complete")
                self.analysisComplete.emit(self._f_long, 0.0, 0.0)
            else:
                self._state = self.State.WAITING_C
                self.stateChanged.emit(
                    f"L: {freq:.1f} Hz — rotate 90°, then tap cross-grain (C) direction…"
                )

        elif self._state == self.State.WAITING_C:
            self._f_cross      = freq
            self._cross_mag_db = mag_db.copy() if mag_db is not None else None
            self.fCCaptured.emit(freq)
            if self._measure_flc:
                self._state = self.State.WAITING_FLC
                self.stateChanged.emit(
                    f"L: {self._f_long:.1f} Hz  C: {freq:.1f} Hz"
                    " — now tap FLC (diagonal) direction…"
                )
            else:
                self._state = self.State.COMPLETE
                self.stateChanged.emit(
                    f"L: {self._f_long:.1f} Hz  C: {freq:.1f} Hz — complete"
                )
                self.analysisComplete.emit(self._f_long, self._f_cross, 0.0)

        else:  # WAITING_FLC
            self._f_flc      = freq
            self._flc_mag_db = mag_db.copy() if mag_db is not None else None
            self.fFLCCaptured.emit(freq)
            self._state = self.State.COMPLETE
            self.stateChanged.emit(
                f"L: {self._f_long:.1f} Hz  C: {self._f_cross:.1f} Hz"
                f"  FLC: {freq:.1f} Hz — complete"
            )
            self.analysisComplete.emit(self._f_long, self._f_cross, self._f_flc)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_active(self) -> bool:
        """True while waiting for any tap phase."""
        return self._state in (
            self.State.WAITING_L,
            self.State.WAITING_C,
            self.State.WAITING_FLC,
        )

    @property
    def f_long(self) -> float:
        return self._f_long

    @property
    def f_cross(self) -> float:
        return self._f_cross

    @property
    def f_flc(self) -> float:
        return self._f_flc

    @property
    def long_mag_db(self) -> npt.NDArray | None:
        """dB spectrum captured during the longitudinal tap phase."""
        return self._long_mag_db

    @property
    def cross_mag_db(self) -> npt.NDArray | None:
        """dB spectrum captured during the cross-grain tap phase."""
        return self._cross_mag_db

    @property
    def flc_mag_db(self) -> npt.NDArray | None:
        """dB spectrum captured during the FLC diagonal tap phase."""
        return self._flc_mag_db
