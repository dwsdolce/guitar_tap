"""
Tap-tone analysis coordinator — mirrors Swift TapToneAnalyzer.swift.

The Swift TapToneAnalyzer class is split across nine Swift files:
  TapToneAnalyzer.swift                     — class declaration, stored properties, init
  TapToneAnalyzer+Control.swift             — start, stop, reset, FFT parameter changes
  TapToneAnalyzer+PeakAnalysis.swift        — findPeaks, parabolic interp, Q-factor
  TapToneAnalyzer+SpectrumCapture.swift     — gated FFT, 200 ms pre-roll, 400 ms gate, HPS
  TapToneAnalyzer+TapDetection.swift        — hysteresis tap detector state machine
  TapToneAnalyzer+DecayTracking.swift       — ring-out / decay time tracking
  TapToneAnalyzer+AnnotationManagement.swift — annotation offsets, display-mode toggling
  TapToneAnalyzer+ModeOverrideManagement.swift — per-peak UserAssignedMode overrides
  TapToneAnalyzer+MeasurementManagement.swift — build TapToneMeasurement, save/load
  TapToneAnalyzer+AnalysisHelpers.swift     — dominant peak query, tap-tone ratio, in-range

Python mapping:

  TapToneAnalyzer+TapDetection.swift  →  DecayTracker, TapDetector (this file)
  TapToneAnalyzer+DecayTracking.swift →  DecayTracker (this file)
  TapToneAnalyzer+SpectrumCapture.swift → PlateCapture (this file)

  The remaining extensions are implemented in fft_canvas.py (FftCanvas), which
  serves as the Python equivalent of the top-level TapToneAnalyzer coordinator:
    +Control               → FftCanvas._start_audio / _stop_audio / _on_fft_size_changed
    +PeakAnalysis          → FftCanvas._find_peaks (calls realtime_fft_analyzer functions)
    +AnnotationManagement  → fft_annotations.FftAnnotations (used by FftCanvas)
    +ModeOverrideManagement → peaks_model.PeaksModel.set_mode_override
    +MeasurementManagement  → FftCanvas._build_measurement, measurement.py persistence
    +AnalysisHelpers        → FftCanvas query methods, TapToneMeasurement computed props
"""

from __future__ import annotations

# ── Imports ────────────────────────────────────────────────────────────────────

import time as _time
from enum import Enum, auto

import numpy.typing as npt
from PyQt6 import QtCore

from . import realtime_fft_analyzer as _rfa


# ── DecayTracker ───────────────────────────────────────────────────────────────
# Mirrors Swift TapToneAnalyzer+DecayTracking.swift

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


# ── TapDetector ────────────────────────────────────────────────────────────────
# Mirrors Swift TapToneAnalyzer+TapDetection.swift
#
# Matches the Swift GuitarTap TapToneAnalyzer+TapDetection.swift
# implementation in both algorithm and timing:
#
# Guitar mode  — absolute threshold on the RMS input level.
#     risingThreshold  = tapDetectionThreshold
#     fallingThreshold = tapDetectionThreshold − hysteresisMargin
#
# Plate/Brace mode — EMA-relative threshold on the RMS input level.
#     noiseFloor = α × level + (1 − α) × noiseFloor   (α = 0.05, τ ≈ 190 ms at 10 Hz)
#     headroom   = max(tapDetectionThreshold − noiseFloor, 10 dB)
#     risingThreshold  = noiseFloor + headroom
#     fallingThreshold = noiseFloor + max(headroom − hysteresisMargin, 4 dB)
#     Motivation: long-window continuous FFT dilutes plate/brace tap
#     transients by ~15 dB; adaptive thresholds reject small ambient
#     spikes while catching real taps 12-30 dB above the noise floor.
#
# Warmup and cooldown are measured in real time (seconds) so that
# behaviour is independent of the audio block size or call rate.

class TapDetector(QtCore.QObject):
    """Hysteresis rising-edge tap detector with Guitar and Plate/Brace modes.

    The detector is fed RMS input levels (0-100 scale, 0 = -100 dBFS,
    100 = 0 dBFS) from small audio buffers (~85 ms at 48 kHz), matching
    the Swift implementation's fast `inputLevelDB` path.

    Guitar mode  uses a fixed absolute threshold.
    Plate/Brace  uses an EMA noise-floor tracker to produce adaptive
                 rising and falling thresholds, making it robust to slowly
                 varying ambient noise while still catching sharp tap transients.

    States:
        WARMUP    — ignoring input for `warmup_s` seconds after start/reset.
        IDLE      — waiting for a rising edge above the effective threshold.
                    Checks time-based cooldown (`cooldown_s`) from the last
                    fired tap before emitting (matches Swift tapCooldown).
        TRIGGERED — tap confirmed (or cooldown-blocked rise); waiting for
                    level to drop below the falling threshold before rearming.

    Mirrors Swift TapToneAnalyzer+TapDetection.swift.
    """

    MODE_GUITAR: str = "guitar"
    MODE_PLATE_BRACE: str = "plate_brace"

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
        warmup_s: float = 0.5,          # matches Swift warm-up period
        cooldown_s: float = 0.4,        # matches Swift tap cooldown
        mode: str = MODE_GUITAR,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.tap_threshold: int = tap_threshold
        self.hysteresis_margin: float = hysteresis_margin
        self.warmup_s: float = warmup_s
        self.cooldown_s: float = cooldown_s

        self._mode: str = mode

        # EMA noise-floor state for Plate/Brace mode
        # α = 0.05 → τ ≈ 190 ms at 10 Hz update rate (matches Swift)
        self._ema_alpha: float = 0.05
        self._noise_floor_db: float = -80.0   # dBFS; reset on mode switch
        self._min_headroom_db: float = 10.0   # minimum headroom safety floor
        self._min_falling_db: float = 4.0     # minimum falling headroom

        self._state: str = self._WARMUP
        self._state_entry_time: float = _time.monotonic()
        self._pre_pause_state: str = self._WARMUP
        self._last_tap_time: float | None = None  # time of last fired tap (for cooldown)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def is_paused(self) -> bool:
        return self._state == self._PAUSED

    def set_mode(self, mode: str) -> None:
        """Switch between Guitar and Plate/Brace detection algorithms.

        Resets the EMA noise-floor estimate when entering Plate/Brace mode
        so it adapts quickly to current conditions (matches Swift behaviour
        of re-anchoring state on mode transitions).
        """
        if mode == self._mode:
            return
        self._mode = mode
        if mode == self.MODE_PLATE_BRACE:
            self._noise_floor_db = -80.0  # will catch up within ~2 s at α=0.05

    def reset(self) -> None:
        """Restart warmup (call after device change, new tap sequence, etc.)."""
        import traceback as _tb
        print("TAP_DEBUG [TapDetector.reset] called from:")
        for line in _tb.format_stack()[:-1]:
            print("  ", line.strip())
        self._state = self._WARMUP
        self._state_entry_time = _time.monotonic()
        self._last_tap_time = None

    def set_tap_threshold(self, value: int) -> None:
        self.tap_threshold = value

    def set_hysteresis_margin(self, value: float) -> None:
        self.hysteresis_margin = max(1.0, value)

    def pause(self) -> None:
        if self._state != self._PAUSED:
            self._pre_pause_state = self._state
            self._state = self._PAUSED

    def resume(self) -> None:
        if self._state == self._PAUSED:
            self._state = self._pre_pause_state

    def cancel(self) -> None:
        """Cancel the current sequence and return to IDLE (no warmup)."""
        self._state = self._IDLE
        self._state_entry_time = _time.monotonic()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _compute_thresholds(self, level_db: float) -> tuple[float, float]:
        """Return (rising_threshold_dBFS, falling_threshold_dBFS).

        Guitar mode: fixed thresholds from the user-set tap_threshold.
        Plate/Brace: EMA-adaptive thresholds tracking the noise floor.
        Both match the corresponding Swift algorithm exactly.
        """
        tap_db = float(self.tap_threshold) - 100.0   # 0-100 → dBFS

        if self._mode == self.MODE_GUITAR:
            self._last_headroom: float = 0.0
            return tap_db, tap_db - self.hysteresis_margin

        # --- Plate/Brace EMA adaptive threshold ---
        self._noise_floor_db = (
            self._ema_alpha * level_db
            + (1.0 - self._ema_alpha) * self._noise_floor_db
        )
        headroom = max(tap_db - self._noise_floor_db, self._min_headroom_db)
        self._last_headroom = headroom
        rising  = self._noise_floor_db + headroom
        falling = self._noise_floor_db + max(
            headroom - self.hysteresis_margin, self._min_falling_db
        )
        return rising, falling

    # ------------------------------------------------------------------ #
    # Core update — call for every RMS level sample (~10-12 Hz)
    # ------------------------------------------------------------------ #

    def update(self, amplitude: int) -> None:
        """Feed the latest RMS input level (0–100 scale).

        Emits tapDetected exactly once per confirmed tap.
        Safe to call at any rate; warmup/cooldown use the monotonic clock.
        """
        if self._state == self._PAUSED:
            return

        level_db = float(amplitude) - 100.0          # 0-100 → dBFS
        rising_db, falling_db = self._compute_thresholds(level_db)

        # Work in 0-100 scale to stay consistent with the rest of the app
        rising_amp  = rising_db  + 100.0
        falling_amp = falling_db + 100.0

        now = _time.monotonic()

        # TAP_DEBUG: mode/threshold print (every frame, mirrors Swift detectTap top-of-function)
        if self._mode == self.MODE_PLATE_BRACE:
            print(
                f"TAP_DEBUG [detectTap] RELATIVE mode | "
                f"peakMag={level_db:.2f} noiseFloor={self._noise_floor_db:.2f} "
                f"headroom={getattr(self, '_last_headroom', 0.0):.2f} "
                f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                f"state={self._state}"
            )
        else:
            print(
                f"TAP_DEBUG [detectTap] ABSOLUTE mode | "
                f"peakMag={level_db:.2f} "
                f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                f"state={self._state}"
            )

        match self._state:
            case self._WARMUP:
                remaining = self.warmup_s - (now - self._state_entry_time)
                if remaining > 0:
                    print(
                        f"TAP_DEBUG [detectTap] WARMUP in progress | "
                        f"remaining={remaining:.2f}s peakMag={level_db:.2f}"
                    )
                else:
                    # Re-anchor to current level on warmup exit (Swift behaviour):
                    # don't fire immediately if signal is already above threshold.
                    if amplitude >= rising_amp:
                        self._state = self._TRIGGERED
                        print(
                            f"TAP_DEBUG [detectTap] WARMUP EXIT (already above) | "
                            f"peakMag={level_db:.2f} risingThresh={rising_db:.2f} "
                            f"→ state=TRIGGERED"
                        )
                    else:
                        self._state = self._IDLE
                        if self._mode == self.MODE_PLATE_BRACE:
                            print(
                                f"TAP_DEBUG [detectTap] WARMUP EXIT (relative) | "
                                f"peakMag={level_db:.2f} "
                                f"noiseFloorAnchored={self._noise_floor_db:.2f} "
                                f"risingAnchored={rising_db:.2f} isAboveThreshold=False"
                            )
                        else:
                            print(
                                f"TAP_DEBUG [detectTap] WARMUP EXIT (absolute) | "
                                f"peakMag={level_db:.2f} "
                                f"risingThresh={rising_db:.2f} isAboveThreshold=False"
                            )
                    self._state_entry_time = now

            case self._IDLE:
                now_above = amplitude >= rising_amp
                print(
                    f"TAP_DEBUG [detectTap] HYSTERESIS eval | "
                    f"peakMag={level_db:.2f} wasAbove=False nowAbove={now_above} "
                    f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                    f"isDetecting=True currentTapCount=?"
                )
                if now_above:
                    # Check time-based cooldown from last tap (matches Swift tapCooldown)
                    cooldown_remaining = (
                        self.cooldown_s - (now - self._last_tap_time)
                        if self._last_tap_time is not None else 0.0
                    )
                    if cooldown_remaining > 0:
                        print(
                            f"TAP_DEBUG [detectTap] COOLDOWN active | "
                            f"remaining={cooldown_remaining:.3f}s peakMag={level_db:.2f}"
                        )
                        # Signal is rising but still in cooldown — track as TRIGGERED
                        # without firing, so we wait for it to drop and re-arm.
                        self._state = self._TRIGGERED
                        self._state_entry_time = now
                    else:
                        print(
                            f"TAP_DEBUG [detectTap] RISING EDGE FIRED | "
                            f"peakMag={level_db:.2f} risingThresh={rising_db:.2f}"
                        )
                        self._last_tap_time = now
                        self._state = self._TRIGGERED
                        self._state_entry_time = now
                        self.tapDetected.emit()

            case self._TRIGGERED:
                now_above = amplitude >= falling_amp
                print(
                    f"TAP_DEBUG [detectTap] HYSTERESIS eval | "
                    f"peakMag={level_db:.2f} wasAbove=True nowAbove={now_above} "
                    f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                    f"isDetecting=False currentTapCount=?"
                )
                if not now_above:
                    print(
                        f"TAP_DEBUG [detectTap] FALLING EDGE | "
                        f"peakMag={level_db:.2f} fallingThresh={falling_db:.2f} "
                        f"— signal settled, returning to IDLE"
                    )
                    self._state = self._IDLE
                    self._state_entry_time = now

            case _:
                pass


# ── PlateCapture ───────────────────────────────────────────────────────────────
# Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift
#
# State machine for plate / brace material tap analysis.
#
# Brace (1 tap):
#     IDLE → WAITING_L → COMPLETE
#     analysisComplete emits (f_long, 0.0, 0.0)
#
# Plate without FLC (2 taps):
#     IDLE → WAITING_L → WAITING_C → COMPLETE
#     analysisComplete emits (f_long, f_cross, 0.0)
#
# Plate with FLC (3 taps):
#     IDLE → WAITING_L → WAITING_C → WAITING_FLC → COMPLETE
#     analysisComplete emits (f_long, f_cross, f_flc)
#
# The caller feeds each detected tap's linear magnitude spectrum via on_tap().
# HPS is used to extract the dominant fundamental frequency from each tap.
# The dB magnitude spectrum for each phase is stored for snapshot persistence.

class PlateCapture(QtCore.QObject):
    """Plate / brace fundamental-frequency capture via HPS.

    Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift.
    """

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

        freq = _rfa.hps_peak_freq(
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
